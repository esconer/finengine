"""Agent A pre-fix evidence: one-observation EWMA contract."""
from __future__ import annotations
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.dont_write_bytecode = True
from app.services.volatility_service import VolatilityService


def main() -> None:
    try:
        backend = VolatilityService.calculate_ewma_volatility(pd.Series([0.05]))
    except ValueError:
        backend = "ValueError"
    reference = 0.0
    if isinstance(backend, str):
        diff = float("inf")
        rel = float("inf")
        ok = backend == "ValueError"
    else:
        diff = abs(float(backend) - reference)
        rel = diff / max(abs(reference), 1e-15)
        ok = diff <= 1e-12
    print(f"CHECK|one_observation_ewma|backend={backend}|reference={reference}|abs_diff={diff}|rel_diff={rel}|tolerance=atol:1e-12,rtol:0|{'PASS' if ok else 'FAIL'}")
    print("OUTPUT|contract|reference=explicit zero variance for one observation")


if __name__ == "__main__":
    main()
