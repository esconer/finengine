"""
Portfolio optimization service.

Why direct numpy/cvxpy instead of riskfolio-lib / PyPortfolioOpt:
- riskfolio-lib 7.0.1 crashes on the current scipy (1.16+) inside
  `scipy.linalg.sqrtm` (scalar branch on what should be a 3x3 matrix) and its
  upgrade path drags in vectorbt + a multi-minute dependency churn.
- PyPortfolioOpt 1.5.6 uses scipy's private `hierarchy._LINKAGE_METHODS`,
  removed in scipy 1.18.
Both are documented with repros in `.scratch/advanced-analytics/issues/08`.
The four strategies below use only stable public APIs (numpy / cvxpy /
scipy.cluster.hierarchy.linkage) and run in milliseconds at personal-portfolio
scale.

Strategies
----------
- hrp        : Hierarchical Risk Parity (Lopez de Prado recursive bisection)
- min_vol    : global minimum variance (long-only, fully invested)
- max_sharpe : tangency portfolio via the standard homogenization trick
- min_cvar   : Rockafellar-Uryasev scenario LP at 95%
"""

from typing import Any, Dict, Optional

import cvxpy as cp
import numpy as np
import pandas as pd
from scipy.cluster import hierarchy as sch
from scipy.spatial.distance import squareform

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

STRATEGIES = ("hrp", "min_vol", "max_sharpe", "min_cvar", "black_litterman")
TRADING_DAYS = 252


def _as_matrices(returns: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(mu_annual, cov_annual, assets) aligned to returns.columns order."""
    mu = returns.mean().values * TRADING_DAYS
    cov = returns.cov().values * TRADING_DAYS
    return mu, cov, list(returns.columns)


def _hrp_weights(returns: pd.DataFrame) -> pd.Series:
    """Lopez de Prado HRP via public scipy APIs only."""
    corr = returns.corr()
    # distance matrix for linkage: sqrt(0.5 * (1 - r))
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr.values), 0.0, 1.0))
    condensed = squareform(dist, checks=False)
    link = sch.linkage(condensed, method="single")

    def _quasi_diag(link_matrix: np.ndarray) -> list[int]:
        """Expand linkage tree into leaf order (canonical iterative form).

        Leaf indices are 0..N-1; each cluster node k references children
        link[k-N] -> repeatedly replace nodes >= N until only leaves remain.
        """
        link_int = link_matrix[:, :2].astype(int)
        num_leaves = len(link_matrix) + 1
        order = [int(link_int[-1][0]), int(link_int[-1][1])]
        while max(order) >= num_leaves:
            expanded = []
            for item in order:
                if item < num_leaves:
                    expanded.append(item)
                else:
                    row = link_int[item - num_leaves]
                    expanded.extend([int(row[0]), int(row[1])])
            order = expanded
        return order

    ordered = _quasi_diag(link)
    labels = corr.index[ordered].tolist()

    cov = returns.cov().loc[labels, labels].values
    ivp = 1.0 / np.diag(cov)
    ivp /= ivp.sum()
    weights = pd.Series(ivp, index=labels)

    clusters = [labels]
    while len(clusters) > 0:
        clusters = [
            j
            for i in clusters
            for j in ([i[k : k + len(i) // 2] for k in range(0, len(i), len(i) // 2)])
            if len(j) > 1
        ]
        for sub in range(0, len(clusters), 2):
            left = clusters[sub]
            right = clusters[sub + 1]
            w_left = weights[left].sum()
            w_right = weights[right].sum()
            denom = w_left + w_right
            if denom > 0:
                weights.loc[left] *= 1 - w_left / denom
                weights.loc[right] *= 1 - w_right / denom

    return weights / weights.sum()


def _min_vol(cov: np.ndarray) -> np.ndarray:
    n = cov.shape[0]
    w = cp.Variable(n)
    prob = cp.Problem(
        cp.Minimize(cp.quad_form(w, cp.psd_wrap(cov))),
        [cp.sum(w) == 1, w >= 0],
    )
    prob.solve(solver=cp.CLARABEL)
    if w.value is None:
        raise ValueError("min_vol optimization failed to converge")
    return np.asarray(w.value).flatten()


def _max_sharpe(mu: np.ndarray, cov: np.ndarray, rf: float) -> np.ndarray:
    """Tangency portfolio: min y'Σy s.t. (mu-rf)'y = 1, y>=0; then normalize."""
    n = len(mu)
    excess = mu - rf
    if (excess <= 0).all():
        raise ValueError("max_sharpe undefined when all expected returns <= risk-free rate")
    y = cp.Variable(n)
    prob = cp.Problem(
        cp.Minimize(cp.quad_form(y, cp.psd_wrap(cov))),
        [excess @ y == 1, y >= 0],
    )
    prob.solve(solver=cp.CLARABEL)
    if y.value is None:
        raise ValueError("max_sharpe optimization failed to converge")
    raw = np.asarray(y.value).flatten()
    return raw / raw.sum()


def _min_cvar(returns: pd.DataFrame, beta: float = 0.95) -> np.ndarray:
    """Rockafellar-Uryasev scenario LP."""
    scenarios = returns.values          # (T, N)
    t_len, n = scenarios.shape
    w = cp.Variable(n)
    alpha = cp.Variable(neg=True)       # alpha <= 0 conventionally; free var works too
    z = cp.Variable(t_len, nonneg=True)
    loss = -(scenarios @ w)             # daily portfolio losses (positive = loss)
    prob = cp.Problem(
        cp.Minimize(alpha + (1.0 / ((1 - beta) * t_len)) * cp.sum(z)),
        [z >= loss - alpha, cp.sum(w) == 1, w >= 0],
    )
    prob.solve(solver=cp.CLARABEL)
    if w.value is None:
        raise ValueError("min_cvar optimization failed to converge")
    return np.asarray(w.value).flatten()


def _black_litterman(
    returns: pd.DataFrame,
    views: Optional[Dict[str, float]] = None,
    relative_views: Optional[list[dict[str, Any]]] = None,
    risk_free_rate: float = 0.02,
    tau: float = 0.05,
    delta: float = 2.5,
) -> np.ndarray:
    """Black-Litterman Bayesian Portfolio Optimization.

    - Implied equilibrium excess returns: Pi = delta * Sigma * w_mkt
    - Incorporates absolute views (e.g. {'INFY.NS': 0.15}) and relative views
    - View uncertainty Omega = diag(P * (tau * Sigma) * P^T) (He-Litterman method)
    - Blended posterior parameters mu_bl and cov_bl
    - Long-only tangency solution
    """
    mu_ann, cov_ann, assets = _as_matrices(returns)
    n = len(assets)
    asset_to_idx = {a: i for i, a in enumerate(assets)}

    # Prior market portfolio (equal weight if market caps not specified)
    w_mkt = np.ones(n) / n
    # Implied equilibrium excess returns
    pi = delta * (cov_ann @ w_mkt)

    p_rows = []
    q_vals = []

    if views:
        for ticker, ret in views.items():
            if ticker in asset_to_idx:
                row = np.zeros(n)
                row[asset_to_idx[ticker]] = 1.0
                p_rows.append(row)
                q_vals.append(float(ret))

    if relative_views:
        for rview in relative_views:
            long_t = rview.get("long")
            short_t = rview.get("short")
            diff = float(rview.get("diff", 0.0))
            if long_t in asset_to_idx and short_t in asset_to_idx:
                row = np.zeros(n)
                row[asset_to_idx[long_t]] = 1.0
                row[asset_to_idx[short_t]] = -1.0
                p_rows.append(row)
                q_vals.append(diff)

    if p_rows:
        P = np.array(p_rows)
        Q = np.array(q_vals)
        tau_sigma = tau * cov_ann
        omega_diag = np.diag(P @ tau_sigma @ P.T)
        omega_diag = np.clip(omega_diag, 1e-6, None)
        Omega = np.diag(omega_diag)

        inner = P @ tau_sigma @ P.T + Omega
        inv_inner = np.linalg.pinv(inner)
        mu_bl = pi + (tau_sigma @ P.T @ inv_inner @ (Q - P @ pi))
        cov_bl = (1.0 + tau) * cov_ann - (tau * tau) * (cov_ann @ P.T @ inv_inner @ P @ cov_ann)
    else:
        mu_bl = pi
        cov_bl = cov_ann

    excess = mu_bl - risk_free_rate
    if (excess <= 0).all():
        return _min_vol(cov_bl)

    y = cp.Variable(n)
    prob = cp.Problem(
        cp.Minimize(cp.quad_form(y, cp.psd_wrap(cov_bl))),
        [excess @ y == 1, y >= 0],
    )
    prob.solve(solver=cp.CLARABEL)
    if y.value is None or np.isnan(y.value).any():
        return _min_vol(cov_bl)

    raw = np.asarray(y.value).flatten()
    raw = np.clip(raw, 0.0, None)
    total_raw = raw.sum()
    if total_raw <= 0:
        return _min_vol(cov_bl)
    return raw / total_raw


def optimize(
    returns: pd.DataFrame,
    strategy: str,
    risk_free_rate: float = 0.02,
    views: Optional[Dict[str, float]] = None,
    relative_views: Optional[list[dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run one strategy over a wide returns frame.

    Returns weights (normalized, long-only) plus ex-post diagnostics.
    Raises ValueError for unknown strategies or solver failures.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy '{strategy}'. Choose from {list(STRATEGIES)}")

    if strategy == "hrp":
        weights_series = _hrp_weights(returns)
        assets = list(weights_series.index)
        w_vec = weights_series.values
    else:
        mu, cov, assets = _as_matrices(returns)
        if strategy == "min_vol":
            w_vec = _min_vol(cov)
        elif strategy == "max_sharpe":
            w_vec = _max_sharpe(mu, cov, risk_free_rate)
        elif strategy == "black_litterman":
            w_vec = _black_litterman(returns, views=views, relative_views=relative_views, risk_free_rate=risk_free_rate)
        else:
            w_vec = _min_cvar(returns)

    w_vec = np.clip(w_vec, 0.0, None)
    w_vec = w_vec / w_vec.sum()

    mu, cov, _ = _as_matrices(returns)
    exp_ret = float(mu @ w_vec)
    exp_vol = float(np.sqrt(max(0.0, w_vec @ cov @ w_vec)))

    return {
        "strategy": strategy,
        "weights": {a: round(float(x), 6) for a, x in zip(assets, w_vec)},
        "expected_annual_return": round(exp_ret, 4),
        "expected_annual_volatility": round(exp_vol, 4),
        "expected_sharpe": round((exp_ret - risk_free_rate) / exp_vol, 4) if exp_vol > 0 else None,
        "solver": "cvxpy/clarabel" if strategy != "hrp" else "hierarchical-bisection",
    }
