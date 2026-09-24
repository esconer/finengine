"""Agent B B-06 baseline: invalid OHLCV rows are warned about but persisted."""
import asyncio
from datetime import datetime
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
from app.models.database import StockTimeseries
from app.services.data_service import DataService

async def main():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn: await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as db:
        frame = pd.DataFrame({"date": [datetime(2025,1,2), datetime(2025,1,3)], "open": [1., -1.], "high": [2., 0.], "low": [.5, -2.], "close": [1.5, -1.], "adj_close": [1.5, -1.], "volume": [10, -3.], "ticker": ["B06.NS"]*2})
        await DataService(db)._store_timeseries_data("B06.NS", frame)
        rows = (await db.execute(select(StockTimeseries))).scalars().all()
        print({"input_rows": len(frame), "persisted_rows": len(rows), "invalid_persisted": sum(r.open < 0 or r.volume < 0 for r in rows)})
    await engine.dispose()
asyncio.run(main())
