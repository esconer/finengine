"""Agent B B-07 baseline: nullable quote metadata is returned unchanged."""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
from app.services.data_service import DataService

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        class T:
            def __init__(self, symbol): self.fast_info=SimpleNamespace(last_price=10.0, last_volume=2, market_cap=100, year_high=11, year_low=9); self.info={"sector":None,"industry":None}
        with patch("app.services.data_service.yf.Ticker", T), patch("app.services.data_service.bfinance.Ticker", T), patch.object(DataService, "_YF_TICKER_REAL", staticmethod(T)), patch.object(DataService, "_BF_TICKER_REAL", staticmethod(T)):
            q = await DataService(db).fetch_quote("B07.NS")
        print({"sector": q.get("sector"), "industry": q.get("industry"), "persistence_safe": bool(q.get("sector")) and bool(q.get("industry"))})
    await engine.dispose()
asyncio.run(main())
