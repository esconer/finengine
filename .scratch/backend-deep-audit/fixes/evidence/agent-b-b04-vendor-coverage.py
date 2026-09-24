"""Agent B B-04 baseline: first non-empty vendor frame is accepted without coverage predicate."""
import asyncio
from unittest.mock import patch
import numpy as np
import pandas as pd
from app.services.data_service import DataService

async def main():
    outside = pd.DataFrame({"Open":[1.], "High":[2.], "Low":[.5], "Close":[1.5], "Adj Close":[1.5], "Volume":[10]}, index=pd.to_datetime(["2020-01-01"]))
    outside.index.name = "Date"
    valid = pd.DataFrame({"Open":[1., 1.1], "High":[2., 2.1], "Low":[.5, .6], "Close":[1.5, 1.6], "Adj Close":[1.5, 1.6], "Volume":[10, 11]}, index=pd.to_datetime(["2025-01-02", "2025-01-03"]))
    valid.index.name = "Date"
    calls=[]
    def bf(*a, **k): calls.append("bfinance"); return outside
    def yf(*a, **k): calls.append("yfinance"); return valid
    svc = DataService.__new__(DataService)
    svc.yfinance_timeout = 30
    with patch("app.services.data_service.bfinance.download", bf), patch("app.services.data_service.yf.download", yf):
        out = await svc._download_with_timeout("B04.NS", "2025-01-01", "2025-01-03", ["bfinance", "yfinance"])
    print({"calls": calls, "accepted_dates": [str(x.date()) for x in out.index]})
asyncio.run(main())
