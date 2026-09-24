"""Agent B B-11 baseline: missing history synthesizes ADV/Amihud values."""
import asyncio
import pandas as pd
from app.services.india_data_service import IndiaDataService
from app.models.database import PortfolioPosition
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
async def main():
    engine=create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread":False})
    async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
    S=async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        p=PortfolioPosition(ticker="B11.NS", quantity=10, buy_price=10, last_price=10, market_value=100, weight=1)
        out=await IndiaDataService(db).calculate_portfolio_liquidity_limits([p], {})
        row=out["positions"][0]
        print({"missing": {"adv_30d_shares":row["adv_30d_shares"],"amihud":row["amihud_illiquidity"],"days":row["days_to_liquidate_10pct_adv"]}})
        dates = pd.date_range("2025-01-02", periods=2, freq="B")
        measured = await IndiaDataService(db).calculate_portfolio_liquidity_limits([p], {"B11.NS": pd.DataFrame({"close": [10.0, 10.1], "volume": [1000.0, 1000.0]}, index=dates)})
        m = measured["positions"][0]
        print({"measured": {"adv_30d_shares":m["adv_30d_shares"],"days":m["days_to_liquidate_10pct_adv"],"amihud":m["amihud_illiquidity"]}})
    await engine.dispose()
asyncio.run(main())
