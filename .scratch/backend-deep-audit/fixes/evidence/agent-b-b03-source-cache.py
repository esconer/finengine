"""Agent B B-03 baseline: source preference change leaves warm ticker cache authoritative."""
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch
import pandas as pd
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
from app.models.database import StockTimeseries
from app.services.data_service import DataService
from app.services.source_preference_service import set_primary_source

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        db.add(StockTimeseries(ticker="B03.NS", date=datetime(2025, 1, 2), open=1, high=2, low=.5, close=1.5, adj_close=1.5, volume=10, source_used="bfinance"))
        await db.commit()
        DataService._in_memory_df_cache.clear()
        svc = DataService(db)
        await set_primary_source(db, "yfinance")
        vendor = AsyncMock(return_value=pd.DataFrame())
        with patch.object(svc, "_download_with_timeout", new=vendor):
            out = await svc.fetch_historical_data("B03.NS", "2025-01-01", "2025-01-03")
        print({"source": "yfinance", "served_old_cache": out is not None, "vendor_calls": vendor.await_count})
    await engine.dispose()

asyncio.run(main())
