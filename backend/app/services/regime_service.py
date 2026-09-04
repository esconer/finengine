"""
Market-regime detection via a 3-state Gaussian HMM over NIFTY 50 returns.

States are ordered by risk (return/vol profile) and labeled crisis / calm /
bull so downstream UI never sees raw integer state ids. Persistence
(day-over-day stability) is reported so consumers can distrust a flapping fit.
"""

import asyncio
from datetime import datetime, timezone
from functools import partial
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from app.services.benchmark_service import BenchmarkService
from app.utils.holdings import portfolio_regime_summary
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

REGIME_LABELS_WORST_TO_BEST = ["crisis", "calm", "bull"]
MIN_OBSERVATIONS = 200

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


def classify(
    bench_data: Any,
    n_components: int = 3,
    is_returns: bool = False,
) -> Optional[Dict[str, Any]]:
    """Fit a 3-state Gaussian HMM over 21-day return and realized volatility.

    Architecture (Hamilton, 1989):
    1. Features:
       - 21-day log holding return: log(P_t / P_{t-21}).
       - 21-day realized volatility: rolling 21d std of daily returns, annualized.
    2. Persistence-friendly initialization (96% diagonal transition matrix,
       balanced start probabilities). These are EM starting values, not
       fixed priors: Baum-Welch re-estimates them, and on NIFTY data the
       fitted diagonal stays ≈0.96, i.e. the persistence is in the data.
       (A sticky HDP-HMM in the Fox et al., 2011 sense is out of scope.)
    3. Compound CAGR & Realized Volatility:
       - Computes geometric CAGR for each state to eliminate arithmetic Jensen's inequality skew.
    """
    from hmmlearn.hmm import GaussianHMM
    from sklearn.preprocessing import StandardScaler

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
        ewma_vol = float((ret_1d.ewm(span=10).std() * np.sqrt(252)).iloc[-1]) if len(ret_1d) > 10 else None
        if high_col and low_col:
            high = df[high_col].astype(float).replace(0, np.nan)
            low = df[low_col].astype(float).replace(0, np.nan)
            valid_hl = (high > 0) & (low > 0) & (high >= low)
            if valid_hl.sum() >= 10:
                log_hl = np.log((high[valid_hl] / low[valid_hl]).clip(lower=1.00001))
                parkinson_daily = np.sqrt((log_hl ** 2) / (4 * np.log(2))) * np.sqrt(252)
                parkinson_vol = float(parkinson_daily.rolling(10, min_periods=3).mean().iloc[-1])
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
        ewma_vol = float((ret_1d.ewm(span=10).std() * np.sqrt(252)).iloc[-1]) if len(ret_1d) > 10 else None
        parkinson_vol = None

    # Macroeconomic continuous features: 21-day holding return and 21-day realized volatility
    ret21 = np.log(close / close.shift(21)).dropna()
    vol21 = (ret_1d.rolling(21).std() * np.sqrt(252)).dropna()

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
        covariance_type="full",
        init_params="mc",
        params="mc",
        random_state=100,
        n_iter=200,
        tol=1e-4,
    )
    hmm.startprob_ = np.array([0.33, 0.34, 0.33])
    hmm.transmat_ = sticky_trans.copy()

    hmm.fit(x_scaled)
    states = hmm.predict(x_scaled)
    posteriors = hmm.predict_proba(x_scaled)

    # Compute compound annualized growth rate (CAGR) and realized vol for each state
    rows = []
    for s in range(n_components):
        mask = states == s
        r_sub = ret_1d.loc[common].values[mask]
        n_sub = len(r_sub)
        if n_sub > 0:
            cum_prod = np.prod(1.0 + r_sub)
            cagr = float((cum_prod ** (252.0 / n_sub)) - 1.0) if cum_prod > 0 else float(r_sub.mean() * 252)
        else:
            cagr = 0.0
        ann_v = float(vol21.loc[common].values[mask].mean()) if n_sub > 0 else 0.0
        rows.append({
            "state": s,
            "ann_ret": cagr,
            "cagr": cagr,
            "ann_vol": ann_v,
            "days_pct": float(mask.mean() * 100),
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
        label_map[int(s)]: round(float(posteriors[-1, s]) * 100, 1)
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
        "realtime_ewma_vol": round(ewma_vol, 4) if ewma_vol is not None else None,
        "realtime_parkinson_vol": round(parkinson_vol, 4) if parkinson_vol is not None else None,
        "states": [
            {
                "regime": label_map[int(row.state)],
                "ann_ret": round(row.ann_ret, 4),
                "ann_vol": round(row.ann_vol, 4),
                "historical_days_pct": round(row.days_pct, 1),
            }
            for row in stats_df.reset_index().itertuples(index=False)
        ],
        "recent_history": history,
        "all_regimes": all_regimes,
        "observations": int(len(common)),
    }


async def detect_regime(
    db_session,
    lookback_days: int = 1100,
    portfolio_returns: Optional[pd.Series] = None,
) -> Dict[str, Any]:
    """Fetch benchmark history through the shared cache and classify regimes."""
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

    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result

