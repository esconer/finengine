"""Agent B B-14 baseline: AV HTTP exception text is logged with query/key."""
import asyncio, logging
from io import StringIO
from unittest.mock import patch
import requests
from app.services.alpha_vantage_service import AlphaVantageService, KeyPool
class Resp:
    status_code=401
    def raise_for_status(self): raise requests.HTTPError("401 Client Error: https://www.alphavantage.co/query?function=GLOBAL_QUOTE&apikey=FAKE_SECRET")
    def json(self): return {}
async def main():
    stream=StringIO(); h=logging.StreamHandler(stream); h.setLevel(logging.WARNING)
    log=logging.getLogger("app.services.alpha_vantage_service"); log.addHandler(h); log.setLevel(logging.WARNING)
    s=AlphaVantageService(); s.pool=KeyPool(["FAKE_SECRET"],25,5)
    with patch("app.services.alpha_vantage_service.requests.get", return_value=Resp()):
        try: await s._make_request("GLOBAL_QUOTE", {"symbol":"B14"})
        except Exception: pass
    text=stream.getvalue(); print({"log_contains_secret":"FAKE_SECRET" in text,"log_contains_query":"apikey=" in text})
    log.removeHandler(h)
asyncio.run(main())
