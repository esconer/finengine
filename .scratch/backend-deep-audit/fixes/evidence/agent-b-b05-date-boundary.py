"""Agent B B-05 baseline: SQLite end-date comparison drops the requested final day."""
import asyncio
from datetime import datetime
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
        db.add(StockTimeseries(ticker="B05.NS", date=datetime(2025,1,3), open=1, high=2, low=.5, close=1.5, adj_close=1.5, volume=10))
        await db.commit()
        out = await DataService(db)._get_cached_data("B05.NS", "2025-01-01", "2025-01-03")
        print({"requested_end": "2025-01-03", "sqlite_rows": 0 if out is None else len(out), "boundary_included": out is not None and not out.empty})
    await engine.dispose()
asyncio.run(main())
