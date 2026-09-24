"""C-02 pre-change fixture: first position on empty SQLite book."""
from __future__ import annotations
from unittest.mock import AsyncMock, Mock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
from app.models.database import PortfolioPosition
from app.models.schemas import PortfolioPositionCreate
from app.api.portfolio import add_portfolio_position
from agent_c_fixture_support import run


async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
                                 connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    try:
        svc = Mock()
        svc.validate_ticker = AsyncMock(return_value=True)
        svc.fetch_quote = AsyncMock(return_value={"current_price": 100, "sector": "Tech", "industry": "Software"})
        with patch("app.api.portfolio.GlobalDataService", return_value=svc):
            response = await add_portfolio_position(
                PortfolioPositionCreate(ticker="AAPL", weight=.2, quantity=1, buy_price=100),
                db=session, data_service=svc,
            )
        row = (await session.execute(PortfolioPosition.__table__.select())).mappings().first()
        print("before.response_weight", response.weight, "stored_weight", row["weight"], "expected=1.0", "tolerance=0")
        print("verdict=REQUIRES_ZERO_STATE_100_PERCENT")
    finally:
        await session.close()
        await engine.dispose()


if __name__ == "__main__":
    run(main())
