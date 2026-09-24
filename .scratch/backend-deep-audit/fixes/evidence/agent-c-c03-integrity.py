"""C-03 pre-change fixture: commit-time uniqueness race mapping."""
from __future__ import annotations
from unittest.mock import AsyncMock, Mock, patch
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from app.api.portfolio import add_portfolio_position
from app.models.schemas import PortfolioPositionCreate
from agent_c_fixture_support import FakeDB, run


async def main():
    db = FakeDB()
    async def fail_commit(): raise IntegrityError("INSERT", {}, Exception("UNIQUE ticker"))
    db.commit = fail_commit
    svc = Mock()
    svc.validate_ticker = AsyncMock(return_value=True)
    svc.fetch_quote = AsyncMock(return_value={"current_price": 10, "sector": "Tech", "industry": "Software"})
    with patch("app.api.portfolio.GlobalDataService", return_value=svc):
        try:
            await add_portfolio_position(PortfolioPositionCreate(ticker="AAPL", weight=.2, quantity=1, buy_price=10), db=db, data_service=svc)
            print("before.status", 200)
        except HTTPException as exc:
            print("before.status", exc.status_code, "detail", exc.detail, "rollbacks", db.rollbacks)
    print("verdict=REQUIRES_INTEGRITY_TO_409")


if __name__ == "__main__":
    run(main())
