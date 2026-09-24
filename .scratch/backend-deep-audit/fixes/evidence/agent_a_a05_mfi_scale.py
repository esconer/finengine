"""Agent A pre-fix evidence: canonical 0-100 MFI scale."""
from __future__ import annotations
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.dont_write_bytecode = True
from app.services.indicators_service import _compute_sync


def main() -> None:
    rng = np.random.default_rng(314)
    n = 260
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.012, n)))
    open_price = close * (1.0 + rng.normal(0.0, 0.003, n))
    high = np.maximum.reduce([close, open_price, close * (1.0 + rng.uniform(0.002, 0.02, n))])
    low = np.minimum.reduce([close, open_price, close * (1.0 - rng.uniform(0.002, 0.02, n))])
    volume = rng.integers(10_000, 100_000, n)
    frame = pd.DataFrame({"Date": pd.bdate_range("2020-01-01", periods=n), "Open": open_price, "High": high, "Low": low, "Close": close, "Volume": volume})
    backend = float(_compute_sync(frame, ["mfi"])["mfi"].iloc[-1])

    typical = (high + low + close) / 3.0
    raw_flow = typical * volume
    delta = np.diff(typical, prepend=typical[0])
    positive = np.where(delta > 0.0, raw_flow, 0.0)[-14:].sum()
    negative = np.where(delta < 0.0, raw_flow, 0.0)[-14:].sum()
    reference = 100.0 * positive / (positive + negative) if positive + negative else 50.0
    diff = abs(backend - reference)
    rel = diff / max(abs(reference), 1e-15)
    ok = diff <= 1e-10 + 1e-10 * abs(reference)
    print(f"CHECK|mfi_scale|backend={backend:.12g}|reference={reference:.12g}|abs_diff={diff:.12g}|rel_diff={rel:.12g}|tolerance=atol:1e-10,rtol:1e-10|{'PASS' if ok else 'FAIL'}")
    print(f"OUTPUT|mfi|backend={backend:.12g}|reference={reference:.12g}|stockstats_contract=fraction_times_100")


if __name__ == "__main__":
    main()
