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
    """Fit a canonical 3-state Gaussian HMM with real-time tactical volatility overlays.

    Features fed to Gaussian HMM:
    1. 5-day smoothed log return (trend signal filtering high-frequency Brownian noise)
    2. 10-day realized annualized volatility (dispersion / regime shock detector)
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
            high = df[high_col].astype(float)
            low = df[low_col].astype(float)
            log_hl = np.log((high / low).clip(lower=1.00001))
            parkinson_daily = np.sqrt((log_hl ** 2) / (4 * np.log(2))) * np.sqrt(252)
            parkinson_vol = float(parkinson_daily.rolling(10, min_periods=3).mean().iloc[-1])
        else:
            parkinson_vol = None
    else:
        close = bench_data.astype(float)
        ret_1d = close.pct_change().dropna()
        ewma_vol = float((ret_1d.ewm(span=10).std() * np.sqrt(252)).iloc[-1]) if len(ret_1d) > 10 else None
        parkinson_vol = None

    # Gaussian HMM features: 5-day log return (filtered momentum) and 10-day realized volatility
    ret5 = np.log(close / close.shift(5)).dropna()
    vol10 = (ret_1d.rolling(10).std() * np.sqrt(252)).dropna()

    common = ret5.index.intersection(vol10.index)
    feats = pd.concat([ret5.loc[common].rename("ret5"), vol10.loc[common].rename("vol10")], axis=1).dropna()

    if len(feats) < MIN_OBSERVATIONS:
        return None

    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(feats.values)

    hmm = GaussianHMM(
        n_components=n_components,
        covariance_type="full",
        random_state=42,
        n_iter=300,
        tol=1e-4,
    )
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
            "ann_vol": float(vol10.loc[common].values[mask].mean()),
            "days_pct": float(mask.mean() * 100),
        })
    stats_df = pd.DataFrame(rows).set_index("state")

    # Economically rigorous label mapping:
    # 1. State with lowest return -> Crisis (severe crash, drawdowns)
    # 2. State with lowest volatility -> Calm (normal equilibrium, positive steady return)
    # 3. State with highest return -> Bull Rally (momentum expansion)
    crisis_id = int(stats_df["ann_ret"].idxmin())
    rem = set(stats_df.index) - {crisis_id}
    rem_df = stats_df.loc[list(rem)]
    calm_id = int(rem_df["ann_vol"].idxmin())
    bull_id = int((rem - {calm_id}).pop())

    label_map = {crisis_id: "crisis", calm_id: "calm", bull_id: "bull"}

    flips = (np.diff(states) != 0).mean()
    stability = round(float((1.0 - flips) * 100), 1)

    current_probs = {
        label_map[int(s)]: round(float(posteriors[-1, s]) * 100, 1)
        for s in range(n_components)
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
