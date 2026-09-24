"""Agent A pre-fix evidence: initial wealth baseline for analytics/backtest drawdown."""
from __future__ import annotations
import asyncio
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.dont_write_bytecode = True
from app.services.analytics_engine import AnalyticsEngine
from app.services.backtest_service import run_walk_forward_backtest


def report(name: str, backend: float, reference: float, atol: float = 1e-12) -> None:
    diff = abs(float(backend) - float(reference))
    rel = diff / max(abs(float(reference)), 1e-15)
    ok = diff <= atol + 1e-12 * abs(float(reference))
    print(f"CHECK|{name}|backend={float(backend):.12g}|reference={float(reference):.12g}|abs_diff={diff:.12g}|rel_diff={rel:.12g}|tolerance=atol:{atol:g},rtol:1e-12|{'PASS' if ok else 'FAIL'}")


def main() -> None:
    engine = AnalyticsEngine()
    one_loss = pd.Series([-0.10])
    analytics_backend = engine._calculate_drawdown_metrics(one_loss)["max_drawdown"]
    wealth = np.concatenate(([1.0], np.cumprod(1.0 + one_loss.to_numpy())))
    peaks = np.maximum.accumulate(wealth)
    analytics_reference = float(np.min((wealth - peaks) / peaks))
    report("analytics_initial_loss", analytics_backend, analytics_reference)

    idx = pd.bdate_range("2024-01-01", periods=40)
    returns = pd.DataFrame(0.0, index=idx, columns=["A"])
    returns.iloc[20, 0] = -0.10
    result = run_walk_forward_backtest(
        returns, strategy="equal_weight", lookback_days=20,
        rebalance_freq_days=20, transaction_cost_bps=0.0,
    )
    oos = returns.iloc[20:].copy()
    daily = oos["A"].to_numpy(dtype=float)
    wealth = np.concatenate(([1.0], np.cumprod(1.0 + daily)))
    peaks = np.maximum.accumulate(wealth)
    reference = float(np.min((wealth - peaks) / peaks))
    report("backtest_initial_loss", result["max_drawdown"], reference, atol=5e-5)
    print(f"OUTPUT|analytics|backend={analytics_backend}|reference={analytics_reference}")
    print(f"OUTPUT|backtest|backend={result['max_drawdown']}|reference={reference}")


if __name__ == "__main__":
    main()
