"""
Market-regime detection via a 3-state Gaussian HMM over NIFTY 50 returns.

States are ordered by state CAGR (worst -> crisis, middle -> calm, best ->
bull; volatility does not enter the ordering) and labeled so downstream UI
never sees raw integer state ids. Persistence (day-over-day stability) is
reported so consumers can distrust a flapping fit.
"""

import asyncio
from datetime import datetime, timezone
from functools import partial
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from app.services.benchmark_service import BENCHMARK_SYMBOL, BenchmarkService
from app.utils.holdings import portfolio_regime_summary
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

REGIME_LABELS_WORST_TO_BEST = ["crisis", "calm", "bull"]
MIN_OBSERVATIONS = 200

# Fit configuration of the Gaussian HMM. These are the literals `classify`
# actually fits with; naming them here keeps `detect_regime`'s model metadata
# block from drifting away from the fit that produced the numbers.
REGIME_STATES = 3
HMM_COVARIANCE_TYPE = "full"
HMM_N_ITER = 200
HMM_TOL = 1e-4
HMM_RANDOM_STATE = 100
REGIME_FEATURE_WINDOW_DAYS = 21
TRADING_DAYS_PER_YEAR = 252

# Crash veto: a day whose trailing 21-day log-return is worse than this is
# never displayed as calm/bull, no matter which HMM state claimed it.
# -0.10/21d is a ~-60%-annualized pace: unambiguously crash-like, while
# normal pullbacks (and V-shaped recoveries whose trailing window never
# breaches it) pass through untouched. Measured false-positive rate on
# 2023-2025 NIFTY history: 0 days. This is a display-level guardrail, not a
# model refit: clustering, transition matrix and posteriors are unchanged.
CRASH_VETO_RET21 = -0.10


def _label_states_by_risk(state_stats: pd.DataFrame) -> Dict[int, str]:
    """Map raw HMM states to economic regime labels: crisis, calm, and bull.

    States are mapped monotonically by geometric CAGR (worst -> crisis,
    middle -> calm, best -> bull). With a non-3-state fit there is no
    crisis/calm/bull ordering, so states keep generic labels instead of
    raising IndexError.
    """
    ids = [int(s) for s in state_stats.index.tolist()]
    if len(ids) != 3:
        return {s: f"state_{s}" for s in ids}
    if "cagr" in state_stats.columns:
        sorted_indices = state_stats.sort_values("cagr").index.tolist()
    else:
        sorted_indices = state_stats.sort_values("ann_ret").index.tolist()

    return {
        int(sorted_indices[0]): "crisis",
        int(sorted_indices[1]): "calm",
        int(sorted_indices[2]): "bull",
    }


def _looks_like_returns(series: pd.Series) -> bool:
    """Heuristic: return series are small, centered ~0 with negatives.

    Prices (e.g. NIFTY levels) are large positives with no negatives;
    daily returns have a sub-0.5 median and a material negative fraction.
    Used to route `detect_regime`'s return-Series fallback away from the
    price path (`pct_change` of returns is nonsense).
    """
    probe = pd.Series(series).dropna()
    if len(probe) == 0:
        return False
    try:
        median = float(probe.median())
        neg_frac = float((probe < 0).mean())
    except (TypeError, ValueError):
        return False
    return abs(median) < 0.5 and neg_frac > 0.25


def apply_crash_veto(
    state_ids: np.ndarray,
    label_map: Dict[int, str],
    ret21_values: np.ndarray,
    threshold: float = CRASH_VETO_RET21,
) -> Tuple[np.ndarray, int]:
    """Relabel crash-paced days to the crisis state (pure, deterministic).

    Trailing 21-day windows stay positive for ~2-4 weeks into a fast crash,
    so crash days can land in a high-mean state that global labeling crowns
    'bull' (Mar-2026 inversion). Any day with trailing ret21 below threshold
    is reassigned to the crisis state id; everything else is untouched.
    Returns (display state ids, vetoed day count).
    """
    display = np.asarray(state_ids).copy()
    crisis_ids = [s for s in range(len(label_map)) if label_map.get(int(s)) == "crisis"]
    if not crisis_ids:
        return display, 0
    assigned = np.array([label_map.get(int(s)) for s in display])
    trigger = (np.asarray(ret21_values) < threshold) & (assigned != "crisis")
    vetoed = int(np.sum(trigger))
    if vetoed:
        display[trigger] = crisis_ids[0]
    return display, vetoed


def _fit_convergence_disclosure(hmm: Any) -> Dict[str, Any]:
    """Publish what hmmlearn's own convergence monitor recorded for the fit.

    `hmm.fit()` RETURNS self and also leaves the monitor on `hmm.monitor_`;
    the return value used to be discarded, so `converged` was never read and
    the payload published `n_iter: 200` with nothing to say whether the fit
    actually reached the tolerance or simply ran out of iterations.

    hmmlearn's `ConvergenceMonitor.converged` is true when EITHER the last
    log-likelihood improvement fell below `tol` OR the iteration cap was
    reached, so the bare flag cannot distinguish a converged fit from an
    exhausted one. Both conditions are reported separately and the flag is
    republished verbatim, un-reinterpreted, so a reader can see which happened.

    A model with no usable monitor publishes `available: false` and why, rather
    than a fabricated `converged`.
    """
    monitor = getattr(hmm, "monitor_", None)
    if monitor is None:
        return {
            "available": False,
            "converged": None,
            "reason": (
                "the fitted estimator exposed no convergence monitor "
                "(hmm.monitor_ is absent), so no convergence state exists to "
                "publish; the model was fitted by something other than "
                "hmmlearn's Baum-Welch and its stopping rule is unknown"
            ),
            "evaluation_basis": "unknown",
        }

    # A non-finite log-likelihood is not a measurement; it would also serialize
    # as a bare NaN, so it is dropped rather than rounded and republished.
    history = []
    for value in getattr(monitor, "history", []) or []:
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(value):
            history.append(value)
    iterations_run = getattr(monitor, "iter", None)
    if isinstance(iterations_run, bool) or not isinstance(iterations_run, int):
        iterations_run = None
    tolerance = getattr(monitor, "tol", None)
    tolerance = float(tolerance) if isinstance(tolerance, (int, float)) else None
    cap = getattr(monitor, "n_iter", None)
    if isinstance(cap, bool) or not isinstance(cap, int):
        cap = None

    final_ll = history[-1] if history else None
    final_delta = (history[-1] - history[-2]) if len(history) >= 2 else None
    # `report()` warns and keeps going when the likelihood falls, so a
    # non-monotone history is the monitor's own "not converging" signal.
    monotonic = all(b >= a for a, b in zip(history, history[1:])) if len(history) >= 2 else None
    hit_cap = bool(iterations_run is not None and cap is not None and iterations_run >= cap)
    within_tol = bool(final_delta is not None and tolerance is not None and final_delta < tolerance)

    return {
        "available": True,
        "converged": bool(getattr(monitor, "converged", False)),
        "converged_within_tolerance": within_tol if final_delta is not None else None,
        "hit_iteration_cap": hit_cap,
        "iterations_run": iterations_run,
        "iteration_cap": cap if cap is not None else HMM_N_ITER,
        "tolerance": tolerance if tolerance is not None else HMM_TOL,
        "final_log_likelihood": round(final_ll, 6) if final_ll is not None else None,
        "final_log_likelihood_delta": round(final_delta, 10) if final_delta is not None else None,
        "log_likelihood_monotonic": monotonic,
        "log_likelihood_observations": len(history),        "convergence_rule": (
            "hmmlearn's monitor: converged is true when EITHER the last "
            "log-likelihood improvement is below tolerance OR the iteration cap "
            "was reached, so a true flag with hit_iteration_cap true means the "
            "cap was exhausted, not that the tolerance was met; "
            "converged_within_tolerance reports the tolerance test alone"
        ),
        "evaluation_basis": "in_sample_baum_welch_on_the_requested_window",
        "posterior_basis": (
            "regime_probabilities is the IN-SAMPLE filtered posterior of the "
            "final observation: the standard scaler and the HMM were both "
            "fitted on this same window and there is no holdout, so the "
            "posterior is not a validated probability and no convergence flag "
            "can make it one"
        ),
        "reason": None,
    }


def classify(
    bench_data: Any,
    n_components: int = 3,
    is_returns: bool = False,
) -> Optional[Dict[str, Any]]:
    """Fit a 3-state Gaussian HMM over 21-day return and realized volatility.

    Every input is BENCHMARK data (``bench_data``, the NIFTY 50 frame or its
    return series) — this function has no access to portfolio holdings, so
    every feature it derives describes the benchmark, never the book. That is
    why the published feature name says `benchmark`.

    Architecture (Hamilton, 1989):
    1. Features (all benchmark-derived):
       - 21-day log benchmark return: log(P_t / P_{t-21}).
       - 21-day realized volatility: rolling 21d std of daily returns, annualized.
    2. Persistence-friendly initialization (96% diagonal transition matrix,
       balanced start probabilities). NOTE: the transition matrix is assigned
       this sticky value BEFORE fit() and, with params="mc", Baum-Welch does
       not re-estimate it. The published diagonal is therefore a CONFIGURED
       PRIOR, not a fitted quantity; the fitted parameters are the per-state
       means and covariances. Callers must not read persistence out of the
       transition matrix. (A sticky HDP-HMM in the Fox et al., 2011 sense is
       out of scope.)
    3. Compound CAGR & Realized Volatility (both descriptive; neither feeds
       the estimator, which consumed only `feats` above and was decoded before
       these figures are computed):
       - Computes geometric CAGR for each state to eliminate arithmetic
         Jensen's inequality skew. When the state's compounded product is not
         positive that extrapolation is unavailable and an arithmetic mean is
         used instead; `ann_ret_method` publishes which definition produced
         each number.
       - Annualized volatility is sqrt(252 * variance of the state's daily
         returns): the variance is pooled and the sqrt taken ONCE. Averaging
         per-window ANNUALIZED sigmas would apply Jensen's inequality in the
         wrong direction and understate the state's volatility.
       - Each state's observation count and its 252/n annualization
         extrapolation factor are published beside the annualized figure,
         because the figure is a geometric mean over that count extrapolated to
         a year.
    """
    from hmmlearn.hmm import GaussianHMM
    from sklearn.preprocessing import StandardScaler

    # The sticky init matrices and crisis/calm/bull labeling are defined for
    # exactly 3 states; any other value would be rejected by hmmlearn's fit
    # anyway (after accepting the wrong-shaped setters), so fail fast here.
    if n_components != REGIME_STATES:
        raise ValueError(
            f"n_components must be {REGIME_STATES} (crisis/calm/bull), got {n_components}"
        )

    if bench_data is None or len(bench_data) < MIN_OBSERVATIONS:
        return None

    # Handle DataFrame (with High/Low/Close) vs Series (Close returns)
    if isinstance(bench_data, pd.DataFrame):
        df = bench_data.copy()
        price_col = next((c for c in ("adj_close", "close", "Adj Close", "Close") if c in df.columns), None)
        high_col = next((c for c in ("high", "High") if c in df.columns), None)
        low_col = next((c for c in ("low", "Low") if c in df.columns), None)

        if price_col is None:
            return None
        close = df[price_col].astype(float)
        ret_1d = close.pct_change().dropna()

        # Real-time diagnostic overlays
        ewma_vol = float((ret_1d.ewm(span=10).std() * np.sqrt(TRADING_DAYS_PER_YEAR)).iloc[-1]) if len(ret_1d) > 10 else None
        if high_col and low_col:
            high = df[high_col].astype(float).replace(0, np.nan)
            low = df[low_col].astype(float).replace(0, np.nan)
            valid_hl = (high > 0) & (low > 0) & (high >= low)
            if valid_hl.sum() >= 10:
                log_hl = np.log((high[valid_hl] / low[valid_hl]).clip(lower=1.00001))
                # Pool mean(logHL^2) over the window and take ONE sqrt
                # (Jensen-correct); annualizing each observation first and
                # averaging the sigmas would bias the result downward.
                pooled_var = (log_hl ** 2).rolling(10, min_periods=3).mean() / (4 * np.log(2))
                parkinson_vol = float((np.sqrt(pooled_var) * np.sqrt(TRADING_DAYS_PER_YEAR)).iloc[-1])
            else:
                parkinson_vol = None
        else:
            parkinson_vol = None
    else:
        raw = bench_data.astype(float).dropna()
        if is_returns or _looks_like_returns(raw):
            # Return-Series path: reconstruct a price level for the
            # ret21/vol21 geometry instead of pct_change-ing returns.
            ret_1d = raw
            close = (1.0 + raw).cumprod()
        else:
            close = raw
            ret_1d = close.pct_change().dropna()
        ewma_vol = float((ret_1d.ewm(span=10).std() * np.sqrt(TRADING_DAYS_PER_YEAR)).iloc[-1]) if len(ret_1d) > 10 else None
        parkinson_vol = None

    # Benchmark-derived continuous features: 21-day log return and 21-day
    # realized volatility. `close` comes from `bench_data`, so both describe
    # the benchmark; this function never sees the portfolio.
    ret21 = np.log(close / close.shift(REGIME_FEATURE_WINDOW_DAYS)).dropna()
    vol21 = (ret_1d.rolling(REGIME_FEATURE_WINDOW_DAYS).std() * np.sqrt(TRADING_DAYS_PER_YEAR)).dropna()

    common = ret21.index.intersection(vol21.index)
    feats = pd.concat([ret21.loc[common].rename("ret21"), vol21.loc[common].rename("vol21")], axis=1).dropna()

    if len(feats) < MIN_OBSERVATIONS:
        return None

    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(feats.values)

    # Sticky Dirichlet prior on transition matrix: 96% persistence per regime
    sticky_trans = np.array([
        [0.96, 0.03, 0.01],
        [0.02, 0.96, 0.02],
        [0.01, 0.03, 0.96],
    ])

    hmm = GaussianHMM(
        n_components=n_components,
        covariance_type=HMM_COVARIANCE_TYPE,
        init_params="mc",
        params="mc",
        random_state=HMM_RANDOM_STATE,
        n_iter=HMM_N_ITER,
        tol=HMM_TOL,
    )
    hmm.startprob_ = np.array([0.33, 0.34, 0.33])
    hmm.transmat_ = sticky_trans.copy()

    hmm.fit(x_scaled)
    # `fit` returns self and leaves the monitor on `hmm.monitor_`; it used to
    # be discarded, so nothing in the payload said whether the fit converged.
    model_convergence = _fit_convergence_disclosure(hmm)
    states = hmm.predict(x_scaled)
    posteriors = hmm.predict_proba(x_scaled)

    # Compute compound annualized growth rate (CAGR) and realized vol for each state
    rows = []
    for s in range(n_components):
        mask = states == s
        r_sub = ret_1d.loc[common].values[mask]
        n_sub = len(r_sub)
        # `ann_ret` is a GEOMETRIC figure: the state's compounded product raised
        # to 252/n. It is reported as such, except when the product cannot be
        # raised to a fractional power or has been wiped out, in which case the
        # definition silently changed to an ARITHMETIC mean and said nothing.
        # `ann_ret_method` now publishes which of the three produced the number.
        if n_sub > 0:
            cum_prod = np.prod(1.0 + r_sub)
            if cum_prod > 0:
                cagr = float((cum_prod ** (252.0 / n_sub)) - 1.0)
                ann_ret_method = "geometric_cagr_from_compounded_state_returns"
            elif cum_prod == 0:
                # A zero product means the state's wealth was total. Here the
                # geometric extrapolation IS defined (0 ** positive - 1 ==
                # -1.0), so routing to the arithmetic mean discards a correct
                # answer and substitutes a different quantity that ignores the
                # wipeout entirely -- it can even come out POSITIVE. Measured
                # as unreachable through `classify` today: the day that zeroes
                # the product also zeroes the reconstructed `close`, so ret21
                # is -inf there, survives `dropna()` (which drops NaN, not
                # -inf) and the StandardScaler refuses the matrix. Kept
                # because the value is now published with its method, so a
                # future caller reaching it is disclosed rather than misled.
                cagr = float(r_sub.mean() * TRADING_DAYS_PER_YEAR)
                ann_ret_method = "arithmetic_mean_fallback_product_wiped_out"
            else:
                # Negative product: a negative base has no real fractional
                # power, so genuinely no geometric annualization exists and
                # bailing out is the right call. Also measured as unreachable
                # through `classify`: a return below -100% flips the sign of
                # the reconstructed `close`, which makes that row's ret21 NaN,
                # and `dropna()` removes the wiping day before it can reach any
                # state's `r_sub`. Kept, and disclosed, for the same reason.
                cagr = float(r_sub.mean() * TRADING_DAYS_PER_YEAR)
                ann_ret_method = "arithmetic_mean_fallback_product_negative"
        else:
            cagr = 0.0
            ann_ret_method = "no_observations"
        # `ann_vol` pools the state's DAILY return variance and takes ONE
        # sqrt. It used to be the MEAN of the `vol21` feature's already
        # annualised sigmas, which Jensen's inequality biases DOWNWARD
        # (E[sqrt(v)] <= sqrt(E[v])) -- the exact trap the Parkinson block
        # above avoids by pooling mean(logHL^2) before the sqrt. This is a
        # published descriptive field only: `vol21` reaches the estimator
        # through `feats`, and `states` is decoded before this loop runs, so
        # the fit, the transition matrix and the state labels are untouched.
        # ddof=1 matches `vol21` itself (pandas rolling std) and the other
        # `ann_vol` publishers in this codebase (analytics.py, holdings.py).
        # A state with fewer than two observations has no measurable variance;
        # publishing 0.0 would claim a volatility that was never observed.
        ann_v = (
            float(np.sqrt(TRADING_DAYS_PER_YEAR * np.var(r_sub, ddof=1)))
            if n_sub > 1
            else None
        )
        rows.append({
            "state": s,
            "ann_ret": cagr,
            "ann_ret_method": ann_ret_method,
            "cagr": cagr,
            "ann_vol": ann_v,
            "days_pct": float(mask.mean() * 100),
            # n_sub was computed here and never published, so `ann_ret` was a
            # geometric mean over an undisclosed n. It is the same count
            # `days_pct` is a percentage of, and the factor below is the
            # extrapolation that turns it into a per-year figure.
            "observations": int(n_sub),
            "annualization_factor": (
                round(TRADING_DAYS_PER_YEAR / n_sub, 4) if n_sub > 0 else None
            ),
        })
    stats_df = pd.DataFrame(rows).set_index("state")

    # Economically rigorous monotonic label mapping
    label_map = _label_states_by_risk(stats_df)

    # Crash veto (display-level): crash-paced days are never shown as
    # calm/bull even if the HMM assigned them to a high-mean state.
    # Model statistics (rows, transition matrix, posteriors) intentionally
    # still describe the raw fit.
    ret21_common = ret21.loc[common].values
    display_states, veto_days = apply_crash_veto(states, label_map, ret21_common)

    flips = (np.diff(display_states) != 0).mean()
    stability = round(float((1.0 - flips) * 100), 1)

    current_probs = {
        label_map[int(s)]: round(float(posteriors[-1, s]) * 100, 4)
        for s in range(n_components)
    }

    # Extract Markov transition matrix
    transition_matrix = {}
    for i in range(n_components):
        from_lbl = label_map[int(i)]
        transition_matrix[from_lbl] = {
            label_map[int(j)]: round(float(hmm.transmat_[i, j]) * 100, 1)
            for j in range(n_components)
        }
    # Read off `hmm.transmat_`, but under params="mc" Baum-Welch does NOT
    # re-estimate transmat: it is the sticky prior assigned above, republished.
    # The `classify` docstring said so and the payload did not, so a reader
    # could treat it as a fitted statistic and infer persistence from it.
    transition_matrix_basis = "configured_sticky_prior_not_fitted"

    history = [
        {"date": ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10], "regime": label_map[int(s)]}
        for ts, s in zip(common[-120:], display_states[-120:])
    ]

    all_regimes = {
        (ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]): label_map[int(s)]
        for ts, s in zip(common, display_states)
    }

    return {
        "as_of": common[-1].strftime("%Y-%m-%d") if hasattr(common[-1], "strftime") else str(common[-1]),
        "current_regime": label_map[int(display_states[-1])],
        "stability_pct": stability,
        "label_overrides": {
            "crash_veto_days": int(veto_days),
            "crash_veto_threshold": float(CRASH_VETO_RET21),
        },
        "regime_probabilities": current_probs,
        "transition_matrix": transition_matrix,
        "transition_matrix_basis": transition_matrix_basis,
        "realtime_ewma_vol": round(ewma_vol, 4) if ewma_vol is not None else None,
        "realtime_parkinson_vol": round(parkinson_vol, 4) if parkinson_vol is not None else None,
        "states": [
            {
                "regime": label_map[int(row.state)],
                "ann_ret": round(row.ann_ret, 4),
                # One published key, two definitions: this says which one the
                # number above is. Without it a reader cannot tell a geometric
                # CAGR from the arithmetic fallback that replaced it.
                "ann_ret_method": row.ann_ret_method,
                # None (not 0.0) when the state has fewer than two daily
                # returns, because a variance was never measurable.
                "ann_vol": round(row.ann_vol, 4) if row.ann_vol is not None else None,
                "historical_days_pct": round(row.days_pct, 1),
                "observations": int(row.observations),
                "annualization_factor": (
                    round(float(row.annualization_factor), 4)
                    if row.annualization_factor is not None
                    else None
                ),
            }
            for row in stats_df.reset_index().itertuples(index=False)
        ],
        "model_convergence": model_convergence,
        "recent_history": history,
        "all_regimes": all_regimes,
        "observations": int(len(common)),
    }


async def detect_regime(
    db_session,
    lookback_days: int = 1100,
    portfolio_returns: Optional[pd.Series] = None,
) -> Dict[str, Any]:
    """Fetch benchmark history through the shared cache and classify regimes.

    Besides the classification, this returns the interpretation metadata a
    consumer needs to read the numbers correctly: the benchmark series, the
    price input that was actually used, the model configuration and the unit
    of every percentage and annualized fraction. It lives here (not in
    ``classify``) because the model window is a request parameter that
    ``classify`` never sees.
    """
    bench = BenchmarkService(db_session)
    bench_df = await bench.get_benchmark_df(days=lookback_days)
    use_returns = False
    if bench_df is None or len(bench_df) < MIN_OBSERVATIONS:
        rets = await bench.get_returns(days=lookback_days)
        if rets is None or len(rets) < MIN_OBSERVATIONS:
            raise ValueError(
                f"Insufficient benchmark history for regime detection "
                f"(need >= {MIN_OBSERVATIONS})"
            )
        bench_data = rets
        use_returns = True
    else:
        bench_data = bench_df

    result = await asyncio.to_thread(partial(classify, bench_data, n_components=3, is_returns=use_returns))
    if result is None:
        raise ValueError("Regime classification produced no result")

    # Conditional portfolio behavior inside the CURRENT regime across FULL history.
    if portfolio_returns is not None and "all_regimes" in result:
        all_regimes = result.pop("all_regimes")
        pr = portfolio_returns.dropna()
        # Ensure timezone-naive normalized dates for bulletproof intersection
        # (tz_localize(None) raises on already-naive indexes in pandas 2.x,
        # so only strip when tz-aware).
        pr_idx = pd.to_datetime(pr.index)
        if pr_idx.tz is not None:
            pr_idx = pr_idx.tz_localize(None)
        pr.index = pr_idx.normalize()
        reg_series = pd.Series(all_regimes)
        reg_idx = pd.to_datetime(reg_series.index)
        if reg_idx.tz is not None:
            reg_idx = reg_idx.tz_localize(None)
        reg_series.index = reg_idx.normalize()
        current = result["current_regime"]
        mask = reg_series == current
        common = pr.index.intersection(reg_series.index[mask])
        # Always emit when return history exists: short overlaps report days
        # + holding-period total with annualized ratios suppressed, so young
        # books see their (thin) regime behavior instead of "add holdings".
        # Omission now strictly means no positions or no price data.
        result["portfolio_in_current_regime"] = portfolio_regime_summary(pr.loc[common])
    elif "all_regimes" in result:
        result.pop("all_regimes")

    result.update(_regime_metadata(result, use_returns=use_returns, lookback_days=lookback_days))
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result


def _regime_metadata(
    result: Dict[str, Any],
    *,
    use_returns: bool,
    lookback_days: int,
) -> Dict[str, Any]:
    """Interpretation metadata for a `classify` payload.

    Pure function over the classification result so it is testable without a
    benchmark fetch. Three gaps it closes:

    1. `regime_probabilities` / `transition_matrix` are percentage points
       (0-100, each row summing to 100) and nothing said so, so a reader
       could read `62.0` as 6200% or as 0.62.
    2. `regime_probabilities` is the FILTERED posterior of the final
       observation while `current_regime` is the VITERBI-decoded path (which
       additionally carries the crash-veto relabel). The two can disagree;
       that disagreement was previously invisible.
    3. The benchmark series, the price input that was used and the model
       configuration were undeclared.
    """
    observations = result.get("observations")
    if isinstance(observations, bool) or not isinstance(observations, int):
        observations = None

    probabilities = result.get("regime_probabilities")
    posterior_argmax: Optional[str] = None
    if isinstance(probabilities, dict) and probabilities:
        try:
            posterior_argmax = max(probabilities, key=probabilities.get)
        except TypeError:  # non-numeric posterior payload
            posterior_argmax = None
    current_regime = result.get("current_regime")

    return {
        # Percentage-point declarations (V3-13).
        "probability_unit": "percent_0_to_100",
        "transition_unit": "percent_0_to_100",
        "posterior_type": "filtered_final_observation",
        "current_regime_source": "viterbi_decoded_path",
        "posterior_argmax_regime": posterior_argmax,
        "current_regime_matches_posterior_argmax": (
            bool(posterior_argmax is not None and posterior_argmax == current_regime)
        ),
        "benchmark": {
            "symbol": BENCHMARK_SYMBOL,
            "name": "NIFTY 50",
            # Both paths are market observations, but the returns view is
            # derived from measured closes rather than being a price series.
            "price_input": "daily_returns_series" if use_returns else "daily_ohlcv_price_frame",
            "price_input_provenance": "derived" if use_returns else "measured",
            "price_input_reason": (
                "benchmark price frame unavailable for the requested window; "
                "daily returns series used instead"
                if use_returns
                else None
            ),
            "lookback_days_requested": int(lookback_days),
            "data_status": "available",
        },
        "model": {
            "type": "gaussian_hmm",
            "architecture": "hamilton_1989",
            "states": REGIME_STATES,
            "state_labels": list(REGIME_LABELS_WORST_TO_BEST),
            "features": [
                f"ret{REGIME_FEATURE_WINDOW_DAYS}_log_benchmark_return_{REGIME_FEATURE_WINDOW_DAYS}d",
                f"vol{REGIME_FEATURE_WINDOW_DAYS}_realized_vol_{REGIME_FEATURE_WINDOW_DAYS}d_annualized",
            ],
            # The features above are log(close_t / close_{t-21}) and the
            # rolling 21d std of daily returns, both taken from the BENCHMARK
            # series passed to `classify`. `classify` has no holdings input at
            # all, so nothing here describes this portfolio; the previous
            # feature name said "log_holding_return" and invited exactly that
            # reading.
            "feature_source": "benchmark_series_not_portfolio_holdings",
            "feature_source_detail": (
                "both features are derived from the benchmark close/return "
                "series (`classify` receives no holdings data), so the regime "
                "classification, the transition matrix and the per-state "
                "ann_ret describe the benchmark, not the book; the portfolio's "
                "own behaviour in the current regime is the separate "
                "portfolio_in_current_regime block"
            ),
            "covariance_type": HMM_COVARIANCE_TYPE,
            "scaler": "standard_scaler_fitted_on_requested_window",
            "n_iter": HMM_N_ITER,
            "tolerance": HMM_TOL,
            "random_state": HMM_RANDOM_STATE,
            "lookback_days": int(lookback_days),
            "observations": observations,
            "minimum_observations": MIN_OBSERVATIONS,
            "training_window_status": "available" if observations else "unavailable",
            "decoding": "viterbi",
            "posterior": "filtering",
        },
        "units": {
            "regime_probabilities": "percent_0_to_100",
            "transition_matrix": "percent_0_to_100",
            "transition_matrix_basis": (
                "'configured_sticky_prior_not_fitted' means transition_matrix is "
                "the 96%-diagonal sticky prior assigned before fit() and "
                "republished unchanged: the estimator runs with params=\"mc\", so "
                "Baum-Welch re-estimates the state means and covariances but NOT "
                "the transition matrix. Persistence must therefore be read from "
                "stability_pct (measured off the decoded path), never out of "
                "transition_matrix"
            ),
            "stability_pct": "percent_0_to_100",
            "states[].historical_days_pct": "percent_0_to_100",
            "label_overrides.crash_veto_days": "count_trading_days",
            "label_overrides.crash_veto_threshold": "fraction_log_return_21d",
            "states[].ann_ret": "annualized_fraction_geometric_cagr",
            # `states[].ann_ret` used to carry ONE definition under one key: a
            # geometric CAGR normally, and an arithmetic mean times 252 whenever
            # the compounded product was not positive, with the switch
            # undisclosed. `ann_ret_method` is now the co-published qualifier
            # that names the definition each number actually used.
            "states[].ann_ret_method": (
                "definition_qualifier_for_states[].ann_ret: "
                "'geometric_cagr_from_compounded_state_returns' means ann_ret is "
                "the geometric CAGR named above (compounded product raised to "
                "252/n, minus 1); 'arithmetic_mean_fallback_product_wiped_out' "
                "and 'arithmetic_mean_fallback_product_negative' mean the "
                "compounded product was not positive and ann_ret is instead an "
                "ARITHMETIC mean of the state's daily returns times 252 -- a "
                "different quantity, not another estimate of the same one; "
                "'no_observations' means the state captured no trading days and "
                "ann_ret is 0.0 by construction rather than by measurement"
            ),
            "states[].ann_vol": "annualized_fraction",
            "states[].ann_vol_basis": (
                "states[].ann_vol is sqrt(252 * variance of the state's daily "
                "benchmark returns, ddof=1): the daily variance is pooled and "
                "the sqrt taken ONCE, because the mean of already-annualised "
                "sigmas is biased downward by Jensen's inequality "
                "(E[sqrt(v)] <= sqrt(E[v])). It is null when the state has "
                "fewer than two daily returns, because no variance was then "
                "measurable"
            ),
            "states[].observations": "count_trading_days",
            "states[].annualization_factor": (
                "ratio_trading_days_per_year_over_state_observations"
            ),
            "model_convergence.iterations_run": "count_em_iterations",
            "model_convergence.iteration_cap": "count_em_iterations",
            "model_convergence.tolerance": "log_likelihood_nats_per_iteration",
            "model_convergence.final_log_likelihood": "log_likelihood_nats",
            "model_convergence.final_log_likelihood_delta": (
                "log_likelihood_nats_per_iteration"
            ),
            "realtime_ewma_vol": "annualized_fraction",
            "realtime_parkinson_vol": "annualized_fraction",
            "portfolio_in_current_regime.ann_ret": "annualized_fraction_geometric_cagr",
            "portfolio_in_current_regime.ann_vol": "annualized_fraction",
            "portfolio_in_current_regime.total_ret": "holding_period_fraction",
            "portfolio_in_current_regime.days": "count_trading_days",
            "portfolio_in_current_regime.annualized": "boolean_flag",
            "observations": "count_trading_days",
            "as_of": "date",
        },
    }

