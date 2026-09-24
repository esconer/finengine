"""Agent A pre-fix evidence: aggregate Monte Carlo live-array budget."""
from __future__ import annotations
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.dont_write_bytecode = True
import app.services.monte_carlo_service as mc


def main() -> None:
    returns = pd.Series(np.random.default_rng(10).normal(0.0004, 0.01, 300))
    calls: list[int] = []
    original = mc._simulate_gbm

    def fake_gbm(mu_annual, sigma_annual, initial_value, horizon_years, num_paths, rng):
        calls.append(int(num_paths))
        steps = int(round(float(horizon_years) * mc.TRADING_DAYS))
        # Broadcast view avoids a multi-GB test allocation while preserving shape.
        return np.broadcast_to(np.array([[float(initial_value)]]), (num_paths, steps + 1))

    mc._simulate_gbm = fake_gbm
    try:
        result = mc.simulate_goal(returns, 100_000, 150_000, 40, method="gbm", num_paths=20_000, seed=1)
    finally:
        mc._simulate_gbm = original

    steps = int(round(40 * mc.TRADING_DAYS))
    # Current GBM names four path-sized arrays and hstack allocates a fifth.
    named_arrays = 5
    backend_elements = max(calls) * steps * named_arrays
    aggregate_budget = 50_000_000
    reference_max_chunk = aggregate_budget // (steps * named_arrays)
    diff = abs(backend_elements - aggregate_budget)
    rel = diff / aggregate_budget
    ok = backend_elements <= aggregate_budget and max(calls) <= reference_max_chunk
    print(f"CHECK|aggregate_live_elements|backend={backend_elements}|reference={aggregate_budget}|abs_diff={diff}|rel_diff={rel}|tolerance=atol:0,rtol:0|{'PASS' if ok else 'FAIL'}")
    print(f"CHECK|chunk_path_count|backend={max(calls)}|reference={reference_max_chunk}|abs_diff={abs(max(calls)-reference_max_chunk)}|rel_diff={abs(max(calls)-reference_max_chunk)/max(reference_max_chunk,1)}|tolerance=atol:0,rtol:0|{'PASS' if max(calls) <= reference_max_chunk else 'FAIL'}")
    print(f"OUTPUT|backend_calls|{calls}|output_num_paths={result['num_paths']}|steps={steps}")


if __name__ == "__main__":
    main()
