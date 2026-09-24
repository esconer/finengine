"""C-10 pre-change fixture: duplicate rows reconcile to submitted rows."""
from __future__ import annotations
from unittest.mock import AsyncMock, Mock
from app.api.portfolio import bulk_add_positions
from app.models.schemas import BulkAddRequest, PortfolioPositionBase
from agent_c_fixture_support import FakeDB, run


async def main():
    db = FakeDB(["AAPL"])
    svc = Mock()
    svc.validate_ticker = AsyncMock(return_value=True)
    svc.fetch_quote = AsyncMock()
    result = await bulk_add_positions(BulkAddRequest(positions=[PortfolioPositionBase(ticker="AAPL", weight=.2, quantity=1, buy_price=10)], auto_normalize=False), db=db, data_service=svc)
    print("after.added", result.added, "failed", result.failed, "skipped", result.skipped, "submitted", result.submitted, "duplicates", result.duplicates)
    print("verdict=PASS" if result.added + result.failed + result.skipped == result.submitted and result.duplicates else "verdict=FAIL")
    print("tolerance=exact row-count reconciliation")


if __name__ == "__main__":
    run(main())
