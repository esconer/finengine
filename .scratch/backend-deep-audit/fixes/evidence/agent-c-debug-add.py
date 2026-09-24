import asyncio, traceback
from unittest.mock import AsyncMock, Mock, patch
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.database import Base
from app.models.database import PortfolioPosition
from app.models.schemas import PortfolioPositionCreate
from app.api.portfolio import add_portfolio_position

async def main():
    e=create_async_engine('sqlite+aiosqlite:///:memory:',poolclass=StaticPool,connect_args={'check_same_thread':False})
    async with e.begin() as c: await c.run_sync(Base.metadata.create_all)
    s=async_sessionmaker(e,expire_on_commit=False)()
    s.add(PortfolioPosition(ticker='TCS.NS',weight=.5,quantity=10,buy_price=3500,last_price=3600,market_value=36000,region='IN',sector='Technology'))
    await s.commit()
    svc=Mock(); svc.validate_ticker=AsyncMock(return_value=True)
    with patch('app.api.portfolio.GlobalDataService',return_value=svc):
      try:
       await add_portfolio_position(PortfolioPositionCreate(ticker='TCS.NS',weight=.5,quantity=10,buy_price=3500,region='IN'),db=s,data_service=svc)
      except BaseException as ex:
       print(type(ex),repr(ex)); traceback.print_exc()
    await s.close(); await e.dispose()
asyncio.run(main())
