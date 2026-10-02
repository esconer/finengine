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

from app.services.analytics_engine import (
    MIN_SHARED_ROWS_FOR_CORRELATION,
    UNCERTAINTY_CONFIDENCE_LEVEL,
    UNCERTAINTY_DECIMALS,
    UNCERTAINTY_MIN_OBSERVATIONS,
    UNMEASURABLE_CORRELATION_REASON,
    measure_estimate_uncertainty,
)
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


# ---------------------------------------------------------------------------
# SI-5 -- estimation error on the moment triple
# ---------------------------------------------------------------------------
# `expected_annual_return`, `expected_annual_volatility` and `expected_sharpe`
# are FORWARD-LOOKING ESTIMATES FROM A FITTED MODEL, not measurements: mu and
# cov are estimated from the sample, and the weights are solved rather than
# observed. The uncertainty that matters is therefore the estimation error on
# mu and cov, and the sample they came from has to be published beside them.
#
# The method is the same circular moving-block bootstrap the rest of the export
# uses, applied to what is actually uncertain here: the sample ROWS. Whole
# trading days are resampled across every leg at once, mu and cov are refitted
# from scratch on each resample exactly as `_as_matrices` fits them on the full
# sample, and the moment triple is re-scored on the SAME published weights. A
# resample that moved the weights would measure solver noise, not estimation
# error.
#
# `expected_annual_return` additionally carries the closed-form normal-theory
# standard error, so the two methods can be compared instead of one standing in
# for the other.
OPTIMIZER_POINT_TOLERANCE = 1e-4


def _moment_statistic_closure(
    w: np.ndarray, risk_free_rate: float
) -> Any:
    """`evaluate(block) -> {moment: array}` for one weight vector.

    `block` is ``(n, draws, k)``: the resampled daily return rows, time axis
    first. mu and cov are refitted on it, then the triple is scored on `w`.
    """
    weights = np.asarray(w, dtype=float)

    def evaluate(block: Any) -> Dict[str, np.ndarray]:
        rows = int(block.shape[0])
        centred = block - block.mean(axis=0, keepdims=True)
        mu_draws = block.sum(axis=0) / rows * TRADING_DAYS
        cov_draws = (
            np.einsum("ndi,ndj->dij", centred, centred) / max(1, rows - 1)
        ) * TRADING_DAYS
        expected = mu_draws @ weights
        variance = np.einsum("dij,i,j->d", cov_draws, weights, weights)
        with np.errstate(divide="ignore", invalid="ignore"):
            volatility = np.sqrt(np.where(variance > 0.0, variance, np.nan))
            return {
                "expected_annual_return": expected,
                "expected_annual_volatility": volatility,
                "expected_sharpe": (expected - float(risk_free_rate)) / volatility,
            }

    return evaluate


def optimizer_estimate_uncertainty(
    returns: pd.DataFrame,
    w: np.ndarray,
    moments: Mapping[str, Optional[float]],
    risk_free_rate: float,
    *,
    scope: str,
) -> Dict[str, Any]:
    """Precision disclosure for one optimizer moment triple (SI-5).

    `moments` is the UNROUNDED triple from `_moments`, because the identity
    check below compares it against the published 4-decimal level; passing the
    rounded values would make every block fail its own reproduction test.
    """
    published = {
        key: _round_or_none(moments.get(key), MOMENT_DECIMALS) for key in MOMENT_KEYS
    }
    observations = len(returns)
    block = measure_estimate_uncertainty(
        returns.to_numpy(dtype=float),
        _moment_statistic_closure(w, risk_free_rate),
        published,
        scope=scope,
        point_tolerance=OPTIMIZER_POINT_TOLERANCE,
        notes={
            "estimator": (
                "the moment triple re-scored on the SAME published weights "
                "after mu_annual and cov_annual are refitted on each resampled "
                "set of trading days; the weights are solved, not measured, so "
                "the uncertainty being measured is the estimation error on mu "
                "and cov, not solver noise"
            ),
            "resampling_basis": (
                "whole trading days are resampled across every leg together, so "
                "the cross-sectional dependence between legs on one day - which "
                "is what the covariance estimate is made of - survives the "
                "resampling"
            ),
            "annualization_factor": TRADING_DAYS,
            "risk_free_rate": risk_free_rate,
            "forward_looking": (
                "these are ex-ante estimates of the moments of the PUBLISHED "
                "weights, not realised outcomes; the interval is the sampling "
                "error of that estimate, not a forecast error"
            ),
        },
    )
    entry = block["estimates"].get("expected_annual_return")
    volatility = moments.get("expected_annual_volatility")
    if entry is not None and volatility and observations > 1:
        # Normal theory for the ANNUALIZED sample mean:
        #   SE(252 * r_bar) = 252 * sigma_daily / sqrt(n)
        #                  = 252 * (sigma_p / sqrt(252)) / sqrt(n)
        #                  = sigma_p * sqrt(252 / n)
        # The annualization factor does not cancel: `sigma_p` is already scaled
        # by sqrt(252), so the SE carries sqrt(252) back out. Dropping it (the
        # `sigma_p / sqrt(n)` form) understates the interval by a factor of
        # sqrt(252 / n) - about 1.2x at n = 170 and 15.9x at n = 1.
        analytic = float(volatility) * float(
            np.sqrt(float(TRADING_DAYS) / float(observations))
        )
        entry["normal_theory_standard_error"] = round(analytic, UNCERTAINTY_DECIMALS)
        entry["normal_theory_basis"] = (
            "closed-form normal-theory standard error of the same estimate, "
            "sqrt(252 / n) * expected_annual_volatility, which is "
            "252 * (sigma_p / sqrt(252)) / sqrt(n) for the annualized sample "
            "mean; valid under an independence assumption the measured AR(1) "
            "may not support. Compare with the bootstrap standard error rather "
            "than substituting one for the other."
        )
    return block


def no_estimate_uncertainty(
    reason: str, fields: tuple[str, ...] = MOMENT_KEYS
) -> Dict[str, Any]:
    """The declared-absence block for a record that never produced a moment.

    The `conf_int` key is present and null for every field, so a consumer can
    tell "no interval was computed, and here is why" from "this field has no
    uncertainty", which is the ambiguity the whole block exists to remove.
    """
    entries = {
        field: {
            "point": None,
            "standard_error": None,
            "conf_int": None,
            "conf_int_level": None,
            "conf_int_method": None,
            "conf_int_basis": None,
            "point_within_conf_int": None,
            "point_within_conf_int_note": None,
            "observations": None,
            "effective_n": None,
            "status": "not_computed",
            "reason": reason,
        }
        for field in fields
    }
    return {
        "scope": "optimizer moment triple",
        "status": "not_computed",
        "reason": reason,
        "method": None,
        "method_basis": None,
        "confidence_level": UNCERTAINTY_CONFIDENCE_LEVEL,
        "observations": None,
        "observation_columns": None,
        "autocorrelation": {
            "ar1": None,
            "ar1_basis": "OLS slope of r_t on r_(t-1) over the measured window",
            "effective_n": None,
            "effective_n_formula": "n * (1 - ar1) / (1 + ar1)",
            "effective_n_basis": None,
            "observations": None,
            "status": "not_computed",
            "reason": reason,
        },
        "estimates": entries,
    }


def optimizer_no_sample_reason(what: str) -> str:
    """The reason a record with no usable sample publishes no interval."""
    return (
        f"not computed: {what}, so no mu_annual or cov_annual was ever "
        f"estimated and there is no sample to resample. A moment triple needs "
        f"at least {UNCERTAINTY_MIN_OBSERVATIONS} return rows before a "
        "percentile interval over a refitted mu/cov has any meaning; the point "
        "estimate is null for the same reason and is not replaced by a "
        "plausible-looking band."
    )


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


def _current_uncertainty(
    returns_frame: Optional[pd.DataFrame],
    w: pd.Series,
    current: Mapping[str, Optional[float]],
    risk_free_rate: float,
) -> Dict[str, Any]:
    """Precision block for the incumbent, or the declared absence of one."""
    if returns_frame is None or returns_frame.empty:
        return no_estimate_uncertainty(
            optimizer_no_sample_reason(
                "the optimizer run carries no sampled return frame, so the "
                "incumbent book was scored without one"
            )
        )
    return optimizer_estimate_uncertainty(
        returns_frame,
        w.to_numpy(dtype=float),
        current,
        risk_free_rate,
        scope=(
            "optimizer current_portfolio: the incumbent book's moments on the "
            "SAME mu_annual, cov_annual, column order, risk-free rate and return "
            "observations as the recommended triple in this record"
        ),
    )


def _current_portfolio_block(
    mu: np.ndarray,
    cov: np.ndarray,
    assets: list[str],
    recommended: Dict[str, Optional[float]],
    current_weights: Optional[Mapping[str, float]],
    risk_free_rate: float,
    returns_frame: Optional[pd.DataFrame] = None,
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
        # SI-5: the incumbent is an estimate on the same footing as the
        # recommendation, so it carries its own interval rather than being
        # read off the recommendation's. Same seed, same n, same block length,
        # so the two bands come from identical resample draws and their
        # difference is a difference of like with like.
        "estimate_uncertainty": _current_uncertainty(
            returns_frame, w, current, risk_free_rate
        ),
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


def unmeasurable_correlation_pairs(returns: pd.DataFrame) -> list[str]:
    """Upper-triangle pairs whose correlation pandas could not measure.

    Returns `"A/B"` labels in column order, i.e. the pairs for which
    `returns.corr()` is NaN - either fewer than
    `MIN_SHARED_ROWS_FOR_CORRELATION` shared finite rows, or no variation in
    one of the two legs. A NaN here is UNKNOWN. It is the absence of a
    measurement, and it is emphatically not the number 0.0.
    """
    if not isinstance(returns, pd.DataFrame) or returns.shape[1] < 2:
        return []
    corr = returns.corr()
    columns = list(corr.columns)
    return [
        f"{columns[i]}/{columns[j]}"
        for i in range(len(columns))
        for j in range(i + 1, len(columns))
        if not np.isfinite(corr.iat[i, j])
    ]


def measurable_clustering_universe(returns: pd.DataFrame) -> tuple[list[str], list[str]]:
    """The largest subset of legs in which EVERY pair has a correlation.

    HRP needs a distance matrix to build a linkage tree, and
    `sqrt(0.5 * (1 - r))` over a NaN pair is not a distance. The old code
    filled those NaNs with `0.0`, which asserted the strongest claim a
    correlation matrix can make - no relationship whatsoever - and handed the
    linker `sqrt(0.5)`, the LARGEST distance in the matrix. Single-linkage then
    pushed the unmeasurable name as far from every other name as it could go,
    so a leg that was merely unobserved was allocated as though it were a
    diversifier.

    A distance cannot be invented, so the legs involved are left out of the
    clustering instead. Which leg goes is decided by how little is measurable
    about it: repeatedly drop the leg stuck in the most unmeasurable pairs,
    breaking ties on the thinner history and then on the name so the choice is
    deterministic. The dropped names are returned so the caller can publish
    them - a holding may not leave the user's book silently.
    """
    columns = [str(c) for c in returns.columns]
    kept = list(columns)
    dropped: list[str] = []
    if len(kept) < 3:
        # One leg has no pair at all, two have exactly one; nothing to drop.
        return kept, dropped
    finite_counts = {
        c: int(np.isfinite(returns[c].to_numpy(dtype=float)).sum()) for c in kept
    }
    while True:
        frame = returns[kept]
        corr = frame.corr()
        offending = [
            (kept[i], kept[j])
            for i in range(len(kept))
            for j in range(i + 1, len(kept))
            if not np.isfinite(corr.iat[i, j])
        ]
        if not offending:
            return kept, dropped
        # Drop the leg that is LEAST measurable, which is not the same as the
        # leg with the fewest rows: a leg that never moves has a full column of
        # finite returns and no correlation to any of them, and dropping a
        # healthy neighbour instead of it would fix nothing. So the count of
        # unmeasurable pairs a leg is stuck in decides first, then the thinner
        # history, then the name, so the choice is deterministic.
        blame: Dict[str, int] = {}
        for left, right in offending:
            blame[left] = blame.get(left, 0) + 1
            blame[right] = blame.get(right, 0) + 1
        victim = min(blame, key=lambda c: (-blame[c], finite_counts[c], c))
        kept.remove(victim)
        dropped.append(victim)


def _hrp_weights(returns: pd.DataFrame) -> pd.Series:
    """Lopez de Prado HRP via public scipy APIs only.

    Only legs whose pairwise correlations are all measurable are clustered; see
    `measurable_clustering_universe` for why the old `corr().fillna(0.0)` was
    the worst available fill rather than a safe one. A dropped leg is absent
    from the returned Series, and `optimize` re-publishes it at weight zero
    with its reason.
    """
    kept, _dropped = measurable_clustering_universe(returns)
    corr = returns[kept].corr()
    if not np.isfinite(corr.to_numpy(dtype=float)).all():  # pragma: no cover
        # `measurable_clustering_universe` guarantees a fully finite matrix, so
        # this is unreachable. It stays because a NaN reaching `squareform`
        # would surface as an opaque scipy error rather than a stated refusal.
        raise ValueError(
            "hrp: the correlation matrix is still not fully measurable after "
            "restricting to the legs that share at least "
            f"{MIN_SHARED_ROWS_FOR_CORRELATION} return rows"
        )
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

    # Restricted to the clustered legs: the dropped names carry no measurable
    # correlation, so their covariance belongs to no cluster here.
    cov_ord = np.asarray(returns[kept].cov().loc[labels, labels].values, dtype=float)
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


def _black_litterman_posterior(
    cov_ann: np.ndarray,
    pi: np.ndarray,
    P: np.ndarray,
    Q: np.ndarray,
    tau: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Blended posterior (mu_bl, cov_bl) from a prior and a set of views.

    QM-1. The posterior covariance is `tau*Sigma - tau*Sigma P' (Omega +
    P tau Sigma P')^-1 P tau Sigma`, the Woodbury reduction of the standard
    `[(tau Sigma)^-1 + P' Omega^-1 P]^-1`. The leading coefficient is `tau`,
    NOT `1 + tau`: the shipped form was exactly `Sigma + Sigma_BL`, i.e. the
    prior covariance added back on top of the posterior, which INFLATES the
    risk matrix where confident views must shrink it. `inv_inner` is the
    `Omega + P tau Sigma P'` factor; `pinv` stays because `Omega`'s 1e-6 clip
    floor can leave `inner` ill-conditioned for near-collinear views.
    """
    tau_sigma = tau * cov_ann
    omega_diag = np.diag(P @ tau_sigma @ P.T)
    omega_diag = np.clip(omega_diag, 1e-6, None)
    Omega = np.diag(omega_diag)

    inner = P @ tau_sigma @ P.T + Omega
    inv_inner = np.linalg.pinv(inner)
    mu_bl = pi + (tau_sigma @ P.T @ inv_inner @ (Q - P @ pi))
    cov_bl = tau_sigma - (tau_sigma @ P.T @ inv_inner @ P @ tau_sigma)
    return mu_bl, cov_bl


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
    - EVERYTHING here is in EXCESS-return space. `Pi = delta * Sigma * w_mkt`
      is the Black-Litterman risk premium `E[R] - rf*1`, so no `rf` term
      appears in its construction and none is added afterwards; `mu_bl` is
      `Pi` plus a linear combination of `Q - P Pi`, hence also excess. QM-5:
      this function used to compute `mu_bl - risk_free_rate`, de-risking a
      second time and shifting the tangency direction by
      `Sigma^-1 (mu_bl - rf 1)`. `risk_free_rate` is consequently accepted for
      signature stability with `optimize()` but does NOT enter the tangency.
    - Views are read on the SAME convention. Express absolute-return views as
      view minus risk-free rate, e.g. an expected 15% return with rf=6% is
      passed as 0.09. Relative (long-short) view diffs are rf-invariant and
      need no adjustment. That conversion happens once, at the edge, when the
      view is written down - not again inside the posterior.
    - View uncertainty Omega = diag(P * (tau * Sigma) * P^T) (He-Litterman method)
    - Blended posterior parameters mu_bl and cov_bl (see
      `_black_litterman_posterior` for the covariance form)
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
        mu_bl, cov_bl = _black_litterman_posterior(cov_ann, pi, P, Q, tau)
    else:
        mu_bl = pi
        cov_bl = cov_ann

    # QM-5: `mu_bl` is ALREADY excess, so `rf` is not subtracted here. The
    # normalisation `excess @ y == 1` only fixes the scale of y, and the
    # published weights are y/sum(y), so the scale never reaches the output.
    excess = mu_bl
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

    `excluded` / `excluded_reasons`: `hrp` cannot measure the distance between
    two legs that share fewer than two return rows, so rather than invent one
    it declines to cluster them. The declined legs are published here, at a
    weight of zero, because a holding may not leave the user's book silently.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown strategy '{strategy}'. Choose from {list(STRATEGIES)}")

    mu, cov, assets = _as_matrices(returns)
    excluded: list[str] = []
    excluded_reasons: Dict[str, str] = {}
    if strategy == "hrp":
        # Keyed in scipy-linkage leaf order - deliberately NOT assumed to be
        # the column order. `_weight_vector` is what aligns it.
        solved: pd.Series = _hrp_weights(returns)
        _kept, excluded = measurable_clustering_universe(returns)
        if excluded:
            unmeasurable = unmeasurable_correlation_pairs(returns[assets])
            for ticker in excluded:
                bad = [p for p in unmeasurable if ticker in p.split("/")]
                excluded_reasons[ticker] = (
                    f"{UNMEASURABLE_CORRELATION_REASON}; left out of the HRP "
                    f"clustering with {', '.join(bad) if bad else 'the book'}"
                )
            # `_weight_vector` refuses a universe mismatch by design, so the
            # declined legs are put back HERE, at an explicit zero, rather than
            # by loosening that guard.
            solved = solved.reindex(assets).fillna(0.0)
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
        # Which legs this strategy declined to reason about, and why. Empty for
        # every strategy but `hrp` today; published unconditionally so a
        # consumer never has to infer "nothing was dropped" from an absent key.
        "excluded": excluded,
        "excluded_reasons": excluded_reasons,
        "moments_basis": _moments_basis_block(returns, risk_free_rate, moments),
        # SI-5: the triple above is an ex-ante estimate from a fitted mu/cov,
        # not a measurement, so it carries the estimation error on that fit and
        # the sample it was fitted on. 170 rows is the number a reader needs in
        # order to judge an `expected_annual_return` of 0.16.
        "estimate_uncertainty": optimizer_estimate_uncertainty(
            returns, w_vec, moments, risk_free_rate,
            scope=(
                "optimizer moment triple: mu_annual and cov_annual estimated "
                "from this record's return observations, re-scored on the "
                "published weights on every resample"
            ),
        ),
        "current_portfolio": _current_portfolio_block(
            mu, cov, assets, moments, current_weights, risk_free_rate,
            returns_frame=returns,
        ),
    }
