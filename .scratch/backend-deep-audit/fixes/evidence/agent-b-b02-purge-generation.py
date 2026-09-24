"""Agent B B-02 baseline: purge misses coint/company memos and permits late repopulation."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
import pandas as pd
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy import select
from app.db.database import Base
from app.models.database import StockTimeseries
from app.services.cache_service import clear_market_data_cache
from app.services.data_service import DataService
from app.services import cointegration_service
from app.services.company_data_service import get_company_data_service

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        db.add(StockTimeseries(ticker="B02.NS", date=datetime(2025, 1, 2), open=1, high=2, low=.5, close=1.5, adj_close=1.5, volume=10))
        await db.commit()
        DataService._in_memory_df_cache["B02.NS"] = (9999999999.0, pd.DataFrame({"date": [pd.Timestamp("2025-01-02")], "close": [1.5]}))
        DataService._quote_memo["B02.NS"] = (9999999999.0, {"current_price": 1.5})
        cointegration_service._IN_MEMORY_COINT_CACHE["old"] = (datetime.now(timezone.utc).replace(tzinfo=None), {"x": 1})
        get_company_data_service()._yf_fundamentals_cache["B02.NS"] = (9999999999.0, {"ticker": "B02.NS"})
        await clear_market_data_cache(db)
        print({"data_memo": len(DataService._in_memory_df_cache), "coint_memo": len(cointegration_service._IN_MEMORY_COINT_CACHE), "company_memo": len(get_company_data_service()._yf_fundamentals_cache)})

        started = asyncio.Event()
        release = asyncio.Event()
        frame = pd.DataFrame({
            "Open": [10.0, 10.5], "High": [11.0, 11.5], "Low": [9.0, 9.5],
            "Close": [10.5, 11.0], "Adj Close": [10.5, 11.0], "Volume": [100, 101],
        }, index=pd.to_datetime(["2025-01-02", "2025-01-03"]))
        frame.index.name = "Date"
        service = DataService(db)
        async def delayed_vendor(*args, **kwargs):
            started.set()
            await release.wait()
            return frame
        service._download_with_timeout = delayed_vendor
        task = asyncio.create_task(service.fetch_historical_data("B02RACE.NS", "2025-01-02", "2025-01-03", source_order=["yfinance"]))
        await started.wait()
        await clear_market_data_cache(db)
        release.set()
        result = await task
        rows = (await db.execute(select(StockTimeseries))).scalars().all()
        print({"inflight_result_empty": result is None or result.empty, "inflight_rows": len(rows), "inflight_l1": len(DataService._in_memory_df_cache)})
    await engine.dispose()

asyncio.run(main())
