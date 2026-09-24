"""Agent A pre-fix evidence: self-financing backtest weight drift."""
from __future__ import annotations
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.dont_write_bytecode = True
import app.services.backtest_service as bt


def reference_replay(returns: pd.DataFrame, lookback: int, frequency: int) -> tuple[float, list[float], list[float]]:
    values = returns.to_numpy(dtype=float)
    boundaries = list(range(lookback, len(values), frequency)) + [len(values)]
    weights = np.full(values.shape[1], 1.0 / values.shape[1])
    total_turnover = 0.0
    events: list[float] = []
    daily: list[float] = []
    target = np.array([0.8, 0.2])
    for start, end in zip(boundaries[:-1], boundaries[1:]):
        turnover = float(0.5 * np.sum(np.abs(target - weights)))
        events.append(round(turnover, 4))
        total_turnover += turnover
        weights = target.copy()
        for offset in range(start, end):
            row = values[offset]
            gross = float(weights @ row)
            daily.append(gross)
            denominator = 1.0 + gross
            if denominator <= 1e-12 or not math.isfinite(denominator):
                raise ValueError("non-positive simulated wealth")
            weights = weights * (1.0 + row) / denominator
    return round(total_turnover, 2), events, daily


def main() -> None:
    idx = pd.bdate_range("2024-01-01", periods=60)
    values = np.zeros((60, 2), dtype=float)
    values[20] = [0.10, 0.00]
    values[21] = [0.00, 0.05]
    values[40] = [0.00, 0.10]
    values[41] = [0.05, 0.00]
    returns = pd.DataFrame(values, index=idx, columns=["A", "B"])

    original = bt.optimize
    bt.optimize = lambda train_window, strategy="hrp", risk_free_rate=0.02: {"weights": {"A": 0.8, "B": 0.2}}
    try:
        backend = bt.run_walk_forward_backtest(
            returns, strategy="hrp", lookback_days=20,
            rebalance_freq_days=20, transaction_cost_bps=0.0,
        )
    finally:
        bt.optimize = original
    ref_total, ref_events, _ = reference_replay(returns, 20, 20)
    checks = [
        ("total_turnover", backend["total_turnover"], ref_total),
        ("second_rebalance_turnover", backend["rebalance_events"][1]["turnover"], ref_events[1]),
    ]
    for name, b, r in checks:
        diff = abs(float(b) - float(r))
        rel = diff / max(abs(float(r)), 1e-15)
        ok = diff <= 1e-12 + 1e-12 * abs(float(r))
        print(f"CHECK|{name}|backend={float(b):.12g}|reference={float(r):.12g}|abs_diff={diff:.12g}|rel_diff={rel:.12g}|tolerance=atol:1e-12,rtol:1e-12|{'PASS' if ok else 'FAIL'}")
    print(f"OUTPUT|backend_events|{backend['rebalance_events']}")
    print(f"OUTPUT|reference_events|{ref_events}")


if __name__ == "__main__":
    main()
