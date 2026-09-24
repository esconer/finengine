"""C-13 pre-change fixture: malformed dates and oversized collections."""
from __future__ import annotations
from unittest.mock import AsyncMock, Mock
from fastapi import HTTPException
from app.api.data import get_batch_stock_data
from app.models.schemas import BatchStockDataRequest
from agent_c_fixture_support import run


async def main():
    calls = []
    svc = Mock()
    async def fetch(*args, **kwargs): calls.append(args); return {"data": {}, "failed_tickers": []}
    svc.fetch_ohlcv_batch = fetch
    for req in (BatchStockDataRequest(tickers=["AAPL"], start="2025-02-30", end="2025-03-01"),
                BatchStockDataRequest(tickers=["AAPL"], start="2025-03-02", end="2025-03-01"),
                BatchStockDataRequest(tickers=[f"T{i}" for i in range(101)])):
        try:
            await get_batch_stock_data(req, data_service=svc)
            print("before.status", 200)
        except HTTPException as exc:
            print("before.status", exc.status_code, "detail", exc.detail)
    print("before.vendor_calls", len(calls), "expected=0", "tolerance=0")
    print("verdict=REQUIRES_TYPED_DATE_AND_COLLECTION_BOUNDARY")


if __name__ == "__main__":
    run(main())
