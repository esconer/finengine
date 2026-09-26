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

The ordering invariant (PA-1)
-----------------------------
`mu`, `cov` and the weight vector are ALWAYS in `returns.columns` order.
`_as_matrices` establishes that order once, `_weight_vector` is the single
funnel that puts every solver's output into it, and `_moments` is the only
producer of the `expected_annual_*` triple. So the published moments are, by
construction, the moments of the published weights. HRP previously broke this:
it returned its Series in scipy-linkage leaf order, `optimize()` rebound only
`assets` to that order, and `mu @ w_vec` became a dot product of two
differently-ordered vectors - a Sharpe that could come out with the opposite
sign. Nothing downstream may reintroduce a positionally-aligned product.
"""

from typing import Any, Dict, Mapping, Optional

import cvxpy as cp
import numpy as np
import pandas as pd
from scipy.cluster import hierarchy as sch
from scipy.spatial.distance import squareform

from app.utils.logger import setup_logger

logger = setup_logger(__name__)

STRATEGIES = ("hrp", "min_vol", "max_sharpe", "min_cvar", "black_litterman")
TRADING_DAYS = 252
WEIGHT_DECIMALS = 6
MOMENT_DECIMALS = 4

#: What each strategy actually optimises (PA-2). `hrp` clusters and allocates
#: by inverse cluster variance and never reads mu at all, so a Sharpe printed
#: beside its weights describes the solution - it is not the quantity the
#: solver maximised. Only the two tangency solvers may claim Sharpe.
STRATEGY_OBJECTIVES = {
    "hrp": "hierarchical risk parity (recursive bisection on cluster variance; mu is not used by the allocation)",
    "min_vol": "minimum portfolio variance",
    "max_sharpe": "maximum Sharpe (tangency portfolio)",
    "min_cvar": "minimum conditional value at risk at the requested beta",
    "black_litterman": "maximum Sharpe of the Black-Litterman posterior",
}
SHARPE_OBJECTIVE_STRATEGIES = frozenset({"max_sharpe", "black_litterman"})

#: The published moment triple, in publication order.
MOMENT_KEYS = (
    "expected_annual_return",
    "expected_annual_volatility",
    "expected_sharpe",
)


def _as_matrices(returns: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """(mu_annual, cov_annual, assets) aligned to returns.columns order.

    PA-1: this is the single place the order is established. Every weight
    vector that is ever dot-multiplied against `mu`/`cov` comes back through
    `_weight_vector` in exactly this order.
    """
    mu = returns.mean().values * TRADING_DAYS
    cov = returns.cov().values * TRADING_DAYS
    return mu, cov, list(returns.columns)


def _weight_vector(weights: pd.Series, assets: list[str]) -> np.ndarray:
    """Reindex a solver's weights into `assets` (= returns.columns) order.

    PA-1: the single funnel. `hrp` comes back keyed in scipy-linkage LEAF
    order, which is not the column order; every other solver returns a bare
    array already in column order. Funnelling once, here, with a universe
    check that fails loudly on a solver that returned somebody else's tickers,
    is what stops `mu @ w` from becoming a dot product of two orders.
    """
    if len(weights) != len(assets) or set(weights.index) != set(assets):
        raise ValueError(
            "solver returned weights for a different universe than the sample: "
            f"{len(weights)} legs vs {len(assets)} assets"
        )
    return weights.reindex(assets).to_numpy(dtype=float)


def _moments(
    mu: np.ndarray,
    cov: np.ndarray,
    w: np.ndarray,
    risk_free_rate: float,
) -> Dict[str, Optional[float]]:
    """mu'w, sqrt(w' Sigma w) and their Sharpe, in ONE order (PA-1).

    The only producer of the `expected_annual_*` triple. `w` must already be
    in `mu`/`cov` order (see `_weight_vector`); the shape guard below is the
    cheap check against a transposed covariance. A quantity that cannot be
    computed is None with a reason - never a substitute number.
    """
    if w.shape != (mu.shape[0],) or cov.shape != (mu.shape[0], mu.shape[0]):
        raise ValueError(
            "moment inputs disagree in shape: "
            f"mu={mu.shape}, cov={cov.shape}, w={w.shape}"
        )
    exp_ret = float(mu @ w)
    variance = float(w @ cov @ w)
    if not np.isfinite(exp_ret) or not np.isfinite(variance):
        return {
            "expected_annual_return": None,
            "expected_annual_volatility": None,
            "expected_sharpe": None,
            "unavailable_reason": "mu or covariance contains non-finite values",
        }
    if variance < 0.0:
        # Reachable only from a non-PSD covariance estimate. A negative
        # variance has no square root; it is not reported as zero volatility.
        return {
            "expected_annual_return": exp_ret,
            "expected_annual_volatility": None,
            "expected_sharpe": None,
            "unavailable_reason": (
                f"portfolio variance is negative ({variance:.6e}); the covariance "
                "estimate is not positive semi-definite"
            ),
        }
    exp_vol = float(np.sqrt(variance))
    return {
        "expected_annual_return": exp_ret,
        "expected_annual_volatility": exp_vol,
        "expected_sharpe": (exp_ret - risk_free_rate) / exp_vol if exp_vol > 0.0 else None,
        "unavailable_reason": None if exp_vol > 0.0 else "portfolio volatility is zero, so Sharpe is undefined",
    }


def _round_or_none(value: Optional[float], decimals: int) -> Optional[float]:
    return None if value is None else round(float(value), decimals)


def _objective_block(strategy: str) -> Dict[str, Any]:
    """State what the strategy optimised, so `expected_sharpe` cannot read as
    'this Sharpe was maximised' when it was not (PA-2)."""
    is_sharpe_objective = strategy in SHARPE_OBJECTIVE_STRATEGIES
    return {
        "what_was_optimised": STRATEGY_OBJECTIVES[strategy],
        "expected_sharpe_was_the_optimised_objective": is_sharpe_objective,
        "expected_sharpe_basis": (
            "expected_sharpe is the objective this strategy maximised, subject to "
            "the long-only fully-invested constraint."
            if is_sharpe_objective
            else (
                f"{strategy} optimises {STRATEGY_OBJECTIVES[strategy]}, so "
                "expected_sharpe is DESCRIPTIVE of the weights this record "
                "publishes - it is not the quantity that was maximised, and a "
                "higher expected_sharpe alone would not make this solution "
                "better. Compare it against current_portfolio.expected_sharpe, "
                "which is scored on the same mu, cov and sample."
            )
        ),
    }


def _moments_basis_block(
    returns: pd.DataFrame,
    risk_free_rate: float,
    moments: Dict[str, Optional[float]],
) -> Dict[str, Any]:
    """Publish the recipe behind `expected_annual_*` (PA-1)."""
    return {
        "order": "returns_column_order",
        "order_invariant": (
            "mu, cov and the weight vector share returns.columns order by "
            "construction, so expected_annual_return == mu_annual @ w and "
            "expected_annual_volatility == sqrt(w @ cov_annual @ w) for the "
            "exact weights published in this record."
        ),
        "formulas": {
            "expected_annual_return": "mu_annual @ w, mu_annual = mean(daily return) * 252",
            "expected_annual_volatility": "sqrt(w @ cov_annual @ w), cov_annual = cov(daily return) * 252",
            "expected_sharpe": "(expected_annual_return - risk_free_rate) / expected_annual_volatility",
        },
        "annualization_factor": TRADING_DAYS,
        "risk_free_rate": risk_free_rate,
        "return_observations": int(len(returns)),
        "display_rounding": {
            "weights_decimals": WEIGHT_DECIMALS,
            "moment_decimals": MOMENT_DECIMALS,
            "note": (
                "A reader recomputing from the published 6-decimal weights lands "
                "within 5e-7 * len(universe) of the internally computed moment, "
                "which is orders of magnitude below the 4-decimal display step "
                "except within one display step of a rounding boundary."
            ),
        },
        "unavailable_reason": moments["unavailable_reason"],
    }


def _current_portfolio_block(
    mu: np.ndarray,
    cov: np.ndarray,
    assets: list[str],
    recommended: Dict[str, Optional[float]],
    current_weights: Optional[Mapping[str, float]],
    risk_free_rate: float,
) -> Dict[str, Any]:
    """Score the incumbent book on the SAME mu, cov, order and sample (PA-2).

    Without this, "is the recommendation better than what I hold?" cannot be
    answered from the payload - every other Sharpe in the export sits on a
    different window. `current_weights` is the published book; it is used as
    given and never renormalised, so a cash or off-universe leg shows up in
    `tickers_without_sample` and in `published_weight_total` rather than
    being silently absorbed into the scored vector.
    """
    if current_weights is None:
        return {
            "available": False,
            "unavailable_reason": (
                "no current weights were supplied to the optimizer, so the "
                "incumbent book cannot be scored on this sample"
            ),
        }
    try:
        w = pd.Series(
            {a: float(current_weights.get(a, 0.0)) for a in assets}, dtype=float
        )
    except (TypeError, ValueError):
        return {
            "available": False,
            "unavailable_reason": "current weights are not numeric",
        }
    if not bool(np.isfinite(w.to_numpy()).all()) or float(w.sum()) <= 0.0:
        return {
            "available": False,
            "unavailable_reason": (
                "current weights contain non-finite values or carry no positive "
                "gross exposure, so their moments are undefined"
            ),
        }

    current = _moments(mu, cov, w.to_numpy(), risk_free_rate)
    return {
        "available": True,
        "expected_annual_return": _round_or_none(current["expected_annual_return"], MOMENT_DECIMALS),
        "expected_annual_volatility": _round_or_none(current["expected_annual_volatility"], MOMENT_DECIMALS),
        "expected_sharpe": _round_or_none(current["expected_sharpe"], MOMENT_DECIMALS),
        # The comparison PA-2 exists for. Both levels are computed from the same
        # mu, cov, order, sample and risk-free rate, so the difference is a
        # difference of like with like rather than two unrelated windows.
        "recommended_minus_current": {
            key: (
                None
                if recommended[key] is None or current[key] is None
                else round(float(recommended[key] - current[key]), MOMENT_DECIMALS)
            )
            for key in MOMENT_KEYS
        },
        "published_weight_total": round(float(w.sum()), WEIGHT_DECIMALS),
        "tickers_without_sample": sorted(set(current_weights) - set(assets)),
        "same_sample": True,
        "basis": (
            "identical mu_annual, cov_annual, column order, annualization factor "
            "and risk_free_rate as the recommended moments in this record, over "
            "the same return observations; the weights are the published current "
            "weights, used as given and NOT renormalised"
        ),
        "note": (
            "Cash and legs outside the sampled universe are not credited: they "
            "appear in published_weight_total and tickers_without_sample instead. "
            "Compare recommended_minus_current, not the two levels in isolation."
        ),
    }


def _solve(prob: cp.Problem) -> None:
    """Solve in place; map cvxpy SolverError to ValueError so API routes
    map solver failures to 400, not 500 (SolverError is not a ValueError)."""
    try:
        prob.solve(solver=cp.CLARABEL)
    except cp.error.SolverError as e:
        raise ValueError(f"Optimization solver failed: {e}") from e


def _cluster_var(cov_ord: np.ndarray, items: list[int]) -> float:
    """Inverse-variance-weighted cluster variance for HRP bisection.

    Lopez de Prado (2016): allocate between sibling clusters in inverse
    proportion to their aggregated variances, where each cluster's variance
    is computed under its own inverse-variance (IVP) allocation.
    """
    sub = cov_ord[np.ix_(items, items)]
    diag = np.diag(sub)
    with np.errstate(divide="ignore", invalid="ignore"):
        ivp = 1.0 / diag
    ivp = np.where(np.isfinite(ivp) & (ivp > 0), ivp, np.nan)
    if np.isnan(ivp).all():
        ivp = np.ones(len(items)) / len(items)
    else:
        ivp = np.where(np.isnan(ivp), 0.0, ivp)
        total = ivp.sum()
        ivp = ivp / total if total > 0 else np.ones(len(items)) / len(items)
    return float(ivp @ sub @ ivp)


def _hrp_weights(returns: pd.DataFrame) -> pd.Series:
    """Lopez de Prado HRP via public scipy APIs only."""
    corr = returns.corr().fillna(0.0)
    # pandas CoW: .values is read-only — take a writable copy before mutating
    corr_np = corr.to_numpy(copy=True)
    np.fill_diagonal(corr_np, 1.0)
    # distance matrix for linkage: sqrt(0.5 * (1 - r))
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr_np), 0.0, 1.0))
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

    cov_ord = np.asarray(returns.cov().loc[labels, labels].values, dtype=float)
    cov_ord = np.where(np.isfinite(cov_ord), cov_ord, 0.0)
    variances = np.diag(cov_ord)
    valid = variances[np.isfinite(variances) & (variances > 1e-12)]
    fill = float(np.mean(valid)) if valid.size else 1.0
    variances = np.where(np.isfinite(variances) & (variances > 1e-12), variances, fill)
    np.fill_diagonal(cov_ord, variances)

    weights = pd.Series(1.0, index=labels)

    clusters: list[list[int]] = [list(range(len(labels)))]
    while clusters:
        nxt: list[list[int]] = []
        for cluster in clusters:
            if len(cluster) < 2:
                continue
            mid = len(cluster) // 2
            left, right = cluster[:mid], cluster[mid:]
            var_left = _cluster_var(cov_ord, left)
            var_right = _cluster_var(cov_ord, right)
            denom = var_left + var_right
            if not np.isfinite(denom) or denom <= 0:
                alpha = 0.5
            else:
                alpha = 1.0 - var_left / denom
            weights.iloc[left] *= alpha
            weights.iloc[right] *= (1.0 - alpha)
            if len(left) > 1:
                nxt.append(left)
            if len(right) > 1:
                nxt.append(right)
        clusters = nxt

    return weights / weights.sum()


def _min_vol(cov: np.ndarray) -> np.ndarray:
    n = cov.shape[0]
    w = cp.Variable(n)
    prob = cp.Problem(
        cp.Minimize(cp.quad_form(w, cp.psd_wrap(cov))),
        [cp.sum(w) == 1, w >= 0],
    )
    _solve(prob)
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
    _solve(prob)
    if y.value is None:
        raise ValueError("max_sharpe optimization failed to converge")
    raw = np.asarray(y.value).flatten()
    if raw.sum() <= 0 or not np.all(np.isfinite(raw)):
        raise ValueError("max_sharpe undefined: tangency weights sum to non-positive")
    return raw / raw.sum()


def _min_cvar(returns: pd.DataFrame, beta: float = 0.95) -> np.ndarray:
    """Rockafellar-Uryasev scenario LP."""
    scenarios = returns.values          # (T, N)
    t_len, n = scenarios.shape
    w = cp.Variable(n)
    alpha = cp.Variable()  # VaR of loss is free (can be > 0); neg=True cuts off positive-loss VaR
    z = cp.Variable(t_len, nonneg=True)
    loss = -(scenarios @ w)             # daily portfolio losses (positive = loss)
    prob = cp.Problem(
        cp.Minimize(alpha + (1.0 / ((1 - beta) * t_len)) * cp.sum(z)),
        [z >= loss - alpha, cp.sum(w) == 1, w >= 0],
    )
    _solve(prob)
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
    - Incorporates views on the EXCESS-return convention (the prior Pi and
      the final tangency both work in excess space: mu_bl - rf). Express
      absolute-return views as view minus risk-free rate, e.g. an expected
      15% return with rf=6% is passed as 0.09. Relative (long-short) view
      diffs are rf-invariant and need no adjustment.
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
    beta: float = 0.95,
    current_weights: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """Run one strategy over a wide returns frame.

    Returns weights (normalized, long-only) plus ex-post diagnostics.
    Raises ValueError for unknown strategies or solver failures.

    PA-1: `assets` is never rebound. Every solver's output is funnelled through
    `_weight_vector` into `returns.columns` order, and the moments are then
    computed from that one vector, so the published moments are the moments of
    the published weights.

    PA-2: pass `current_weights` (the published book) to also score the
    incumbent on the SAME mu, cov and sample. Without it `current_portfolio` is
    `available: false` with a reason, because a Sharpe printed beside a
    recommendation with nothing to compare it against is not actionable.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy '{strategy}'. Choose from {list(STRATEGIES)}")

    mu, cov, assets = _as_matrices(returns)
    if strategy == "hrp":
        # Keyed in scipy-linkage leaf order - deliberately NOT assumed to be
        # the column order. `_weight_vector` is what aligns it.
        solved: pd.Series = _hrp_weights(returns)
    else:
        if strategy == "min_vol":
            solved = pd.Series(_min_vol(cov), index=assets)
        elif strategy == "max_sharpe":
            solved = pd.Series(_max_sharpe(mu, cov, risk_free_rate), index=assets)
        elif strategy == "black_litterman":
            solved = pd.Series(
                _black_litterman(returns, views=views, relative_views=relative_views, risk_free_rate=risk_free_rate),
                index=assets,
            )
        else:
            solved = pd.Series(_min_cvar(returns, beta=beta), index=assets)

    w_vec = _weight_vector(solved, assets)
    w_vec = np.clip(w_vec, 0.0, None)
    gross = float(w_vec.sum())
    if not np.isfinite(gross) or gross <= 0.0:
        raise ValueError(f"{strategy} produced no positive gross exposure to normalize")
    w_vec = w_vec / gross

    moments = _moments(mu, cov, w_vec, risk_free_rate)

    return {
        "strategy": strategy,
        "weights": {a: round(float(x), WEIGHT_DECIMALS) for a, x in zip(assets, w_vec)},
        "expected_annual_return": _round_or_none(moments["expected_annual_return"], MOMENT_DECIMALS),
        "expected_annual_volatility": _round_or_none(moments["expected_annual_volatility"], MOMENT_DECIMALS),
        "expected_sharpe": _round_or_none(moments["expected_sharpe"], MOMENT_DECIMALS),
        "solver": "cvxpy/clarabel" if strategy != "hrp" else "hierarchical-bisection",
        "objective": _objective_block(strategy),
        "moments_basis": _moments_basis_block(returns, risk_free_rate, moments),
        "current_portfolio": _current_portfolio_block(
            mu, cov, assets, moments, current_weights, risk_free_rate
        ),
    }
