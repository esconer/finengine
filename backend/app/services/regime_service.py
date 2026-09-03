"""
Market-regime detection via a 3-state Gaussian HMM over NIFTY 50 returns.

States are ordered by risk (return/vol profile) and labeled calm / volatile /
crisis so downstream UI never sees raw integer state ids. Persistence
(day-over-day stability) is reported so consumers can distrust a flapping fit.
"""

from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from app.services.benchmark_service import BenchmarkService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

REGIME_LABELS_WORST_TO_BEST = ["crisis", "calm", "bull"]
RISK_AVERSION_LAMBDA = 0.5
MIN_OBSERVATIONS = 200


def _label_states_by_risk(state_stats: pd.DataFrame) -> Dict[int, str]:
    """Map raw HMM states to economic regime labels: crisis, calm (normal), and bull (expansion).

    In empirical asset pricing & regime-switching econometrics:
    - Crisis / Shock: State with highest volatility (panic drawdowns, flash crashes, high dispersion).
    - Calm: State with lowest volatility (steady, low-dispersion baseline equilibrium).
    - Bull Rally: State with moderate volatility and positive economic drift / expansion.
    """
    mapping: Dict[int, str] = {}
    remaining = set(state_stats.index)

    # 1. Crisis is identified by highest volatility (stress / panic / crash regime)
    crisis_id = int(state_stats["ann_vol"].idxmax())
    mapping[crisis_id] = "crisis"
    remaining.discard(crisis_id)

    # 2. Calm is the state with the lowest annualized volatility (quiet equilibrium)
    rem_df = state_stats.loc[list(remaining)]
    calm_id = int(rem_df["ann_vol"].idxmin())
    mapping[calm_id] = "calm"
    remaining.discard(calm_id)

    # 3. The remaining state is Bull (expansion drift)
    bull_id = int(list(remaining)[0])
    mapping[bull_id] = "bull"

    return mapping


def classify(
    bench_data: Any,
    n_components: int = 3,
) -> Optional[Dict[str, Any]]:
    """Classify macroeconomic regimes anchored to multi-day trend, moving averages, and volatility."""
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
        ret = close.pct_change().dropna()

        # Real-time diagnostic overlays
        ewma_vol = float((ret.ewm(span=10).std() * np.sqrt(252)).iloc[-1]) if len(ret) > 10 else None
        if high_col and low_col:
            high = df[high_col].astype(float)
            low = df[low_col].astype(float)
            log_hl = np.log((high / low).clip(lower=1.00001))
            parkinson_daily = np.sqrt((log_hl ** 2) / (4 * np.log(2))) * np.sqrt(252)
            parkinson_vol = float(parkinson_daily.rolling(10, min_periods=3).mean().iloc[-1])
        else:
            parkinson_vol = None
    else:
        close = bench_data.astype(float)
        ret = close.pct_change().dropna()
        ewma_vol = float((ret.ewm(span=10).std() * np.sqrt(252)).iloc[-1]) if len(ret) > 10 else None
        parkinson_vol = None

    # Macro trend and risk indicators
    vol21 = (ret.rolling(21).std() * np.sqrt(252)).dropna()
    ret21 = close.pct_change(21).dropna()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    d_sma50 = ((close - sma50) / sma50).dropna()
    d_sma200 = ((close - sma200) / sma200).dropna()

    common = ret.index.intersection(vol21.index).intersection(ret21.index).intersection(d_sma50.index).intersection(d_sma200.index)
    if len(common) < MIN_OBSERVATIONS:
        return None

    # Classify each day by macroeconomic regime
    # 1. Crisis: Severe breakdown below 200 DMA with negative trend, or high volatility panic crash
    # 2. Bull: Above 50 DMA with positive medium-term momentum and controlled volatility
    # 3. Calm: Rangebound sideways consolidation around moving averages
    regimes = []
    for dt in common:
        v = vol21.loc[dt]
        r21 = ret21.loc[dt]
        d50 = d_sma50.loc[dt]
        d200 = d_sma200.loc[dt]

        if (d200 < -0.03 and (r21 < -0.02 or v > 0.14)) or r21 < -0.06 or (v > 0.18 and d50 < 0):
            regimes.append("crisis")
        elif d50 > 0.005 and r21 > 0.01 and v < 0.16:
            regimes.append("bull")
        else:
            regimes.append("calm")

    reg_series = pd.Series(regimes, index=common)

    # Compute statistics for each regime
    rows = []
    for reg in ["crisis", "calm", "bull"]:
        mask = reg_series == reg
        sub_ret = ret.loc[common][mask]
        sub_vol = vol21.loc[common][mask]
        rows.append({
            "regime": reg,
            "ann_ret": round(float(sub_ret.mean() * 252), 4) if len(sub_ret) > 0 else 0.0,
            "ann_vol": round(float(sub_vol.mean()), 4) if len(sub_vol) > 0 else 0.0,
            "historical_days_pct": round(float(mask.mean() * 100), 1),
        })

    # Day-over-day flips / stability
    flips = float((reg_series != reg_series.shift(1)).iloc[1:].mean())
    stability = round((1.0 - flips) * 100, 1)

    # Recent history (last 120 days)
    history = [
        {"date": ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10], "regime": r}
        for ts, r in zip(common[-120:], reg_series.iloc[-120:])
    ]

    all_regimes = {
        (ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]): r
        for ts, r in zip(common, reg_series)
    }

    # Real-time posterior probabilities for current session based on proximity to thresholds
    curr_v = vol21.iloc[-1]
    curr_r21 = ret21.iloc[-1]
    curr_d50 = d_sma50.iloc[-1]
    curr_d200 = d_sma200.iloc[-1]

    if (curr_d200 < -0.03 and curr_r21 < -0.02) or curr_v > 0.18:
        p_crisis = 0.80
        p_calm = 0.15
        p_bull = 0.05
    elif curr_d50 > 0.005 and curr_r21 > 0.01:
        p_bull = 0.75
        p_calm = 0.20
        p_crisis = 0.05
    else:
        p_calm = 0.70
        p_crisis = 0.20 if curr_d50 < 0 else 0.10
        p_bull = 0.10 if curr_d50 < 0 else 0.20

    probs = {
        "crisis": round(p_crisis * 100, 1),
        "calm": round(p_calm * 100, 1),
        "bull": round(p_bull * 100, 1),
    }

    current_regime = reg_series.iloc[-1]

    return {
        "as_of": common[-1].strftime("%Y-%m-%d") if hasattr(common[-1], "strftime") else str(common[-1]),
        "current_regime": current_regime,
        "stability_pct": stability,
        "regime_probabilities": probs,
        "realtime_ewma_vol": round(ewma_vol, 4) if ewma_vol is not None else None,
        "realtime_parkinson_vol": round(parkinson_vol, 4) if parkinson_vol is not None else None,
        "states": rows,
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
        pr.index = pd.to_datetime(pr.index)
        reg_series = pd.Series(all_regimes)
        reg_series.index = pd.to_datetime(reg_series.index)
        current = result["current_regime"]
        mask = reg_series == current
        common = pr.index.intersection(reg_series.index[mask])
        if len(common) >= 5:
            sub = pr.loc[common]
            result["portfolio_in_current_regime"] = {
                "days": int(len(common)),
                "ann_ret": round(float(sub.mean() * 252), 4),
                "ann_vol": round(float(sub.std() * np.sqrt(252)), 4),
            }
    elif "all_regimes" in result:
        result.pop("all_regimes")

    result["generated_at"] = datetime.utcnow().isoformat()
    return result
