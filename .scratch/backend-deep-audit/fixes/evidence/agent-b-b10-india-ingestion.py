"""Agent B B-10 baseline: missing bhavcopy values become zero and corrections are skipped."""
import asyncio
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
from app.models.database import NSEBhavcopy, NSEInstitutionalFlow
from app.services.india_data_service import IndiaDataService

async def main():
    engine=create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread":False})
    async with engine.begin() as c: await c.run_sync(Base.metadata.create_all)
    S=async_sessionmaker(engine, expire_on_commit=False)
    async with S() as db:
        d=datetime(2025,1,2)
        bad={"symbol":"B10","open":None,"high":2,"low":.5,"close":1.5,"prev_close":1,"avg_price":1.2,"ttl_trd_qnty":10,"turnover_lacs":1,"no_of_trades":2}
        good={"symbol":"B10G","open":1,"high":2,"low":.5,"close":1.5,"prev_close":1,"avg_price":1.2,"ttl_trd_qnty":10,"turnover_lacs":1,"no_of_trades":2}
        service = IndiaDataService(db)
        print({"inserted": await service.ingest_bhavcopy_records([bad, good, good], d)})
        corrected = dict(good, close=1.8, high=2.2)
        print({"correction_count": await service.ingest_bhavcopy_records([corrected], d)})
        await service.ingest_institutional_flow(d, "FII", 100, 40)
        await service.ingest_institutional_flow(d, "FII", 120, 50)
        rows=(await db.execute(select(NSEBhavcopy))).scalars().all()
        flows=(await db.execute(select(NSEInstitutionalFlow))).scalars().all()
        print({"rows":len(rows),"null_became_zero":any(r.symbol=="B10" and r.open==0 for r in rows),"duplicate_symbol_rows":len([r for r in rows if r.symbol=="B10G"]),"corrected_close":rows[0].close,"flow_net":flows[0].net_value_crores})
    await engine.dispose()
asyncio.run(main())
