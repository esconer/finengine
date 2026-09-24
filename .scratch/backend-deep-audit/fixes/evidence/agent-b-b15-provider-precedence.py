"""Agent B B-15 baseline: source provenance is absent from owned fundamentals/statements."""
import asyncio
from unittest.mock import Mock, patch
from app.services.company_data_service import CompanyDataService
async def main():
    info={"longName":"B15","marketCap":100.0,"returnOnEquity":.1}
    with patch("yfinance.Ticker", return_value=Mock(info=info)):
        out=await CompanyDataService().get_fundamentals("B15", source_order=["yfinance"])
    print({"source_order":["yfinance"],"returned_source":out.get("source"),"ticker":out.get("ticker")})
asyncio.run(main())
