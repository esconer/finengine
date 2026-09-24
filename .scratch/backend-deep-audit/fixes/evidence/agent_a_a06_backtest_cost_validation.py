"""Agent A pre-fix evidence: invalid backtest cost/risk-free inputs."""
from __future__ import annotations
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.dont_write_bytecode = True
from app.services.backtest_service import run_walk_forward_backtest


def probe(**kwargs: object) -> tuple[bool, float | None]:
    try:
        result = run_walk_forward_backtest(
            _returns(), strategy="equal_weight", lookback_days=20,
            rebalance_freq_days=10, **kwargs
        )
        return True, float(result["cagr"])
    except ValueError:
        return False, None


def _returns() -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=40)
    return pd.DataFrame({"A": np.linspace(-0.01, 0.01, 40), "B": np.linspace(0.01, -0.01, 40)}, index=idx)


def main() -> None:
    for label, kwargs in (
        ("negative_cost", {"transaction_cost_bps": -100.0}),
        ("nan_cost", {"transaction_cost_bps": float("nan")}),
        ("inf_cost", {"transaction_cost_bps": float("inf")}),
        ("nan_risk_free", {"risk_free_rate": float("nan"), "transaction_cost_bps": 10.0}),
    ):
        accepted, value = probe(**kwargs)
        reference = 0.0
        diff = float(accepted) - reference
        print(f"CHECK|{label}|backend_accepted={accepted}|reference_accepted=False|abs_diff={abs(diff):.12g}|rel_diff=inf|tolerance=atol:0,rtol:0|{'PASS' if not accepted else 'FAIL'}")
        print(f"OUTPUT|{label}|backend_value={value}|reference_value='ValueError'")


if __name__ == "__main__":
    main()
