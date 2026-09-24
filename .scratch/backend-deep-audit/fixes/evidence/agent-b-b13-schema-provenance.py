"""Agent B B-13 baseline: quote field naming drops the 52-week contract and source."""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
from app.services.data_service import DataService
async def main():
    engine=create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread":False})
    async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
    S=async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        class T:
            def __init__(self, symbol): self.fast_info=SimpleNamespace(last_price=10,last_volume=2,market_cap=100,year_high=12,year_low=8); self.info={"sector":"X","industry":"Y"}
        with patch("app.services.data_service.yf.Ticker", T), patch("app.services.data_service.bfinance.Ticker", T), patch.object(DataService, "_YF_TICKER_REAL", staticmethod(T)), patch.object(DataService, "_BF_TICKER_REAL", staticmethod(T)):
            q=await DataService(db).fetch_quote("B13.NS")
        print({"has_52_week_high":"52_week_high" in q,"has_schema_week_52_high":"week_52_high" in q,"has_source":"source" in q})
    await engine.dispose()
asyncio.run(main())
