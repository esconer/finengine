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

    - Crisis: state with lowest / negative return and elevated volatility (bear crash).
    - Calm: state with lowest annualized volatility (steady rangebound normal market).
    - Bull: state with high positive return & momentum (expansion rally).
    """
    mapping: Dict[int, str] = {}
    remaining = set(state_stats.index)

    # 1. Identify Crisis (lowest annualized return, typically severe negative)
    crisis_id = int(state_stats["ann_ret"].idxmin())
    mapping[crisis_id] = "crisis"
    remaining.discard(crisis_id)

    # 2. Between remaining states, the one with lowest volatility is Calm (Normal)
    rem_df = state_stats.loc[list(remaining)]
    calm_id = int(rem_df["ann_vol"].idxmin())
    mapping[calm_id] = "calm"
    remaining.discard(calm_id)

    # 3. The remaining state with high momentum is Bull / Expansion
    bull_id = int(list(remaining)[0])
    mapping[bull_id] = "bull" if state_stats.loc[bull_id, "ann_ret"] > 0.15 else "volatile"

    return mapping


def classify(
    bench_returns: pd.Series,
    n_components: int = 3,
) -> Optional[Dict[str, Any]]:
    """Fit the HMM synchronously (call from a worker thread)."""
    from hmmlearn.hmm import GaussianHMM
    from sklearn.preprocessing import StandardScaler

    if len(bench_returns) < MIN_OBSERVATIONS:
        return None

    vol21 = bench_returns.rolling(21).std()
    feats = pd.concat([bench_returns.rename("ret"), vol21.rename("vol")], axis=1).dropna()
    if len(feats) < MIN_OBSERVATIONS:
        return None

    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(feats.values)

    model = GaussianHMM(
        n_components=n_components,
        covariance_type="full",
        random_state=42,
        n_iter=300,
        tol=1e-4,
    )
    model.fit(x_scaled)
    states = model.predict(x_scaled)

    rows = []
    for s in range(n_components):
        mask = states == s
        rows.append({
            "state": s,
            "ann_ret": float(feats["ret"].values[mask].mean() * 252),
            "ann_vol": float(feats["vol"].values[mask].mean() * np.sqrt(252)),
            "days_pct": float(mask.mean() * 100),
        })
    stats_df = pd.DataFrame(rows).set_index("state")
    label_map = _label_states_by_risk(stats_df)

    flips = (np.diff(states) != 0).mean()
    history = [
        {"date": ts.strftime("%Y-%m-%d"), "regime": label_map[int(s)]}
        for ts, s in zip(feats.index[-120:], states[-120:])
    ]

    return {
        "as_of": feats.index[-1].strftime("%Y-%m-%d") if hasattr(feats.index[-1], "strftime") else str(feats.index[-1]),
        "current_regime": label_map[int(states[-1])],
        "stability_pct": round(float((1 - flips) * 100), 1),
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
        "observations": int(len(feats)),
    }


async def detect_regime(
    db_session,
    lookback_days: int = 1100,
    portfolio_returns: Optional[pd.Series] = None,
) -> Dict[str, Any]:
    """Fetch benchmark history through the shared cache and classify regimes."""
    bench = BenchmarkService(db_session)
    rets = await bench.get_returns(days=lookback_days)
    if rets is None or len(rets) < MIN_OBSERVATIONS:
        raise ValueError(
            f"Insufficient benchmark history for regime detection "
            f"(need >= {MIN_OBSERVATIONS}, got {0 if rets is None else len(rets)})"
        )

    result = await __import__("asyncio").to_thread(classify, rets)
    if result is None:
        raise ValueError("Regime classification produced no result")

    # Conditional portfolio behavior inside the CURRENT regime, when provided.
    if portfolio_returns is not None:
        pr = portfolio_returns.dropna()
        pr.index = pd.to_datetime(pr.index)
        hist = pd.DataFrame(result["recent_history"])
        hist.index = pd.to_datetime(hist["date"])
        current = result["current_regime"]
        mask = hist["regime"] == current
        common = pr.index.intersection(hist.index[mask])
        if len(common) > 20:
            sub = pr.loc[common]
            result["portfolio_in_current_regime"] = {
                "days": int(len(common)),
                "ann_ret": round(float(sub.mean() * 252), 4),
                "ann_vol": round(float(sub.std() * np.sqrt(252)), 4),
            }

    result["generated_at"] = datetime.utcnow().isoformat()
    return result
