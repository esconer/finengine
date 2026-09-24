"""Agent A pre-fix evidence: historical benchmark fetch anchoring."""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "backend"))
sys.dont_write_bytecode = True
from app.services.benchmark_service import BenchmarkService


class FakeData:
    def __init__(self):
        self.calls = []

    async def fetch_historical_data(self, ticker, start, end):
        self.calls.append((ticker, start, end))
        dates = pd.date_range("2020-01-01", "2020-02-15", freq="D")
        return pd.DataFrame({"date": dates, "adj_close": range(100, 100 + len(dates))})


async def main() -> None:
    service = BenchmarkService(db_session=Mock())
    fake = FakeData()
    service.data_service = fake
    await service.get_returns(start="2020-01-01", end="2020-02-01", days=10)
    backend_end = fake.calls[0][2]
    reference_end = "2020-02-01"
    diff = abs((pd.Timestamp(backend_end) - pd.Timestamp(reference_end)).days)
    ok = backend_end == reference_end
    print(f"CHECK|fetch_end_anchor|backend={backend_end}|reference={reference_end}|abs_diff={diff}|rel_diff=0|tolerance=atol:0,rtol:0|{'PASS' if ok else 'FAIL'}")
    print(f"OUTPUT|fetch_call|{fake.calls[0]}")


if __name__ == "__main__":
    asyncio.run(main())
