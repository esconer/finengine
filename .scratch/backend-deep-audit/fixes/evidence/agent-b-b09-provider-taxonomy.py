"""Agent B B-09 baseline: provider HTTP errors are collapsed into ValueError/raw text."""
import asyncio
from unittest.mock import patch
import requests
from app.services.alpha_vantage_service import AlphaVantageService, KeyPool

class Resp:
    status_code = 401
    def raise_for_status(self): raise requests.HTTPError("401 for url https://www.alphavantage.co/query?function=GLOBAL_QUOTE&apikey=SECRET_KEY")
    def json(self): return {}

async def main():
    svc = AlphaVantageService(); svc.pool = KeyPool(["SECRET_KEY"], 25, 5)
    with patch("app.services.alpha_vantage_service.requests.get", return_value=Resp()):
        try: await svc._make_request("GLOBAL_QUOTE", {"symbol":"B09"})
        except Exception as e: print({"type": type(e).__name__, "contains_secret": "SECRET_KEY" in str(e), "contains_query": "apikey=" in str(e)})
asyncio.run(main())
