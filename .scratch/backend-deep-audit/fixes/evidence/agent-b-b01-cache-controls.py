"""Agent B B-01 baseline: persisted enable_cache is ignored by DataService."""
import asyncio
from unittest.mock import AsyncMock, patch
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
from app.models.database import AppSetting, StockTimeseries
from app.services.data_service import DataService

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        db.add(AppSetting(key="enable_cache", value="false"))
        db.add(StockTimeseries(ticker="B01.NS", date=pd.Timestamp("2025-01-02").to_pydatetime(), open=1, high=2, low=0.5, close=1.5, adj_close=1.5, volume=10, fetched_on=pd.Timestamp("2020-01-01").to_pydatetime()))
        await db.commit()
        DataService._in_memory_df_cache.clear()
        svc = DataService(db)
        vendor_frame = pd.DataFrame({
            "Open": [1.0, 1.1], "High": [2.0, 2.1], "Low": [0.5, 0.6],
            "Close": [1.5, 1.6], "Adj Close": [1.5, 1.6], "Volume": [10, 11],
        }, index=pd.to_datetime(["2025-01-02", "2025-01-03"]))
        vendor_frame.index.name = "Date"
        vendor = AsyncMock(return_value=vendor_frame)
        with patch.object(svc, "_download_with_timeout", new=vendor):
            out = await svc.fetch_historical_data("B01.NS", "2025-01-01", "2025-01-03")
        rows = (await db.execute(select(StockTimeseries))).scalars().all()
        print({"enable_cache": False, "served": out is not None, "vendor_calls": vendor.await_count, "persisted_rows": len(rows), "persisted_fetched_on_unchanged": str(rows[0].fetched_on).startswith("2020-01-01")})
    await engine.dispose()

asyncio.run(main())
