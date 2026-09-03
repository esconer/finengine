"""
Market-regime detection via a 3-state Gaussian HMM over NIFTY 50 returns.

States are ordered by risk (return/vol profile) and labeled calm / volatile /
crisis so downstream UI never sees raw integer state ids. Persistence
(day-over-day stability) is reported so consumers can distrust a flapping fit.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from app.services.benchmark_service import BenchmarkService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

REGIME_LABELS_WORST_TO_BEST = ["crisis", "calm", "bull"]
MIN_OBSERVATIONS = 200


def _label_states_by_risk(state_stats: pd.DataFrame) -> Dict[int, str]:
    """Map raw HMM states to economic regime labels: crisis, calm (normal), and bull (expansion).

    States are mapped monotonically by their annualized return drift:
    1. Lowest return (negative drift) -> Crisis (bear markets, drawdowns, corrections).
    2. Middle return (positive steady drift) -> Calm (normal equilibrium).
    3. Highest return (expansion momentum) -> Bull Rally.
    """
    sorted_indices = state_stats.sort_values("ann_ret").index.tolist()
    return {
        int(sorted_indices[0]): "crisis",
        int(sorted_indices[1]): "calm",
        int(sorted_indices[2]): "bull",
    }


def classify(
    bench_data: Any,
    n_components: int = 3,
) -> Optional[Dict[str, Any]]:
    """Fit a Sticky-Prior Gaussian HMM over macroeconomic trend and volatility.

    Econometric Architecture (Fox et al., 2011; Hamilton, 1989):
    1. Features:
       - 21-day log return: Captures multi-week macroeconomic directional trend.
       - 21-day realized volatility: Captures structural market dispersion.
    2. Sticky Transition Prior (96% diagonal persistence):
       - Enforces true regime persistence (mean duration 20-35 trading days).
       - Eliminates high-frequency 1-day chattering between crisis and bull states.
    3. Decoding:
       - Global optimal state sequence decoded via the Viterbi algorithm.
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
        close = bench_data.astype(float)
        ret_1d = close.pct_change().dropna()
        ewma_vol = float((ret_1d.ewm(span=10).std() * np.sqrt(252)).iloc[-1]) if len(ret_1d) > 10 else None
        parkinson_vol = None

    # Macroeconomic features: 21-day holding return and 21-day realized volatility
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
        random_state=42,
        n_iter=200,
        tol=1e-4,
    )
    hmm.startprob_ = np.array([0.33, 0.34, 0.33])
    hmm.transmat_ = sticky_trans.copy()

    hmm.fit(x_scaled)
    states = hmm.predict(x_scaled)
    posteriors = hmm.predict_proba(x_scaled)

    # Compute descriptive parameters for each discovered state
    rows = []
    for s in range(n_components):
        mask = states == s
        rows.append({
            "state": s,
            "ann_ret": float(ret_1d.loc[common].values[mask].mean() * 252),
            "ann_vol": float(vol21.loc[common].values[mask].mean()),
            "days_pct": float(mask.mean() * 100),
        })
    stats_df = pd.DataFrame(rows).set_index("state")

    # Economically rigorous monotonic label mapping
    label_map = _label_states_by_risk(stats_df)

    flips = (np.diff(states) != 0).mean()
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
        for ts, s in zip(common[-120:], states[-120:])
    ]

    all_regimes = {
        (ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]): label_map[int(s)]
        for ts, s in zip(common, states)
    }

    return {
        "as_of": common[-1].strftime("%Y-%m-%d") if hasattr(common[-1], "strftime") else str(common[-1]),
        "current_regime": label_map[int(states[-1])],
        "stability_pct": stability,
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
    if bench_df is None or len(bench_df) < MIN_OBSERVATIONS:
        rets = await bench.get_returns(days=lookback_days)
        if rets is None or len(rets) < MIN_OBSERVATIONS:
            raise ValueError(
                f"Insufficient benchmark history for regime detection "
                f"(need >= {MIN_OBSERVATIONS})"
            )
        bench_data = rets
    else:
        bench_data = bench_df

    result = await __import__("asyncio").to_thread(classify, bench_data)
    if result is None:
        raise ValueError("Regime classification produced no result")

    # Conditional portfolio behavior inside the CURRENT regime across FULL history.
    if portfolio_returns is not None and "all_regimes" in result:
        all_regimes = result.pop("all_regimes")
        pr = portfolio_returns.dropna()
        # Ensure timezone-naive normalized dates for bulletproof intersection
        pr.index = pd.to_datetime(pr.index).tz_localize(None).normalize()
        reg_series = pd.Series(all_regimes)
        reg_series.index = pd.to_datetime(reg_series.index).tz_localize(None).normalize()
        current = result["current_regime"]
        mask = reg_series == current
        common = pr.index.intersection(reg_series.index[mask])
        if len(common) >= 5:
            sub = pr.loc[common]
            ann_v = float(sub.std() * np.sqrt(252)) if len(sub) > 1 and not np.isnan(sub.std()) else 0.0
            result["portfolio_in_current_regime"] = {
                "days": int(len(common)),
                "ann_ret": round(float(sub.mean() * 252), 4),
                "ann_vol": round(ann_v, 4),
            }
    elif "all_regimes" in result:
        result.pop("all_regimes")

    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result

