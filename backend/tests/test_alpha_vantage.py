"""
Alpha Vantage multi-key rotation + budget guard tests.

All network I/O is mocked at the requests layer; scenarios mirror the
behaviors verified during ticket 22 implementation:
rotation on daily-limit, retire-until-midnight, frequency cooldown,
local budget guard (no wasted calls), no-key no-op, symbol bridge.
"""


import pytest

import app.services.alpha_vantage_service as avmod
from app.services.alpha_vantage_service import (
    AlphaVantageRateLimitError,
    AlphaVantageService,
    KeyPool,
    to_av_symbol,
)

RATE_DAILY = {"Information": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."}
RATE_FREQ = {"Note": "Thank you for using Alpha Vantage! Our standard API call frequency is 5 requests per minute."}
TIMESERIES = {
    "Time Series (Daily)": {
        "2026-08-24": {"1. open": "10", "2. high": "11", "3. low": "9", "4. close": "10.5", "5. volume": "1000"}
    }
}
QUOTE = {"Global Quote": {"01. symbol": "X", "05. price": "2500.55", "06. volume": "12345", "08. previous close": "2490.00"}}


class FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


@pytest.fixture
def calls(monkeypatch):
    """Record (function, apikey) per request; per-key payload map settable."""
    recorded = []
    holder = {"rates": {}}

    def fake_get(url, params=None, timeout=None):
        fn, key = params["function"], params["apikey"]
        recorded.append((fn, key))
        rate = holder["rates"].get(key)
        if rate:
            return FakeResp(rate)
        return FakeResp(TIMESERIES if fn == "TIME_SERIES_DAILY" else QUOTE)

    monkeypatch.setattr(avmod.requests, "get", fake_get)
    holder["recorded"] = recorded
    return holder


def test_symbol_bridge():
    assert to_av_symbol("RELIANCE.NS") == "RELIANCE.BSE"
    assert to_av_symbol("TATASTEEL.BO") == "TATASTEEL.BO"
    assert to_av_symbol("AAPL") == "AAPL"


@pytest.mark.asyncio
async def test_rotation_on_daily_limit(calls):
    calls["rates"]["KEY_A"] = RATE_DAILY
    svc = AlphaVantageService()
    svc.pool = KeyPool(["KEY_A", "KEY_B"], daily_limit=25, minute_limit=5)

    df = await svc.fetch_daily_ohlcv("RELIANCE.NS", "2026-08-20", "2026-08-25")

    assert [k for _, k in calls["recorded"]] == ["KEY_A", "KEY_B"]
    assert len(df) == 1 and df.iloc[0]["close"] == 10.5
    assert "adj_close" in df.columns  # unadjusted source mirrored


@pytest.mark.asyncio
async def test_retired_key_not_retried_same_day(calls):
    calls["rates"]["KEY_A"] = RATE_DAILY
    svc = AlphaVantageService()
    svc.pool = KeyPool(["KEY_A", "KEY_B", "KEY_C"], 25, 5)

    await svc.fetch_daily_ohlcv("AAPL", "2026-08-20", "2026-08-25")
    calls["recorded"].clear()

    quote = await svc.fetch_global_quote("AAPL")
    used = {k for _, k in calls["recorded"]}
    assert quote is not None and quote["current_price"] == 2500.55
    assert "KEY_A" not in used  # retired -> never contacted again today


def test_frequency_limit_cooldown_then_reuse():
    svc = AlphaVantageService()
    svc.pool = KeyPool(["K1", "K2"], 25, 1)

    # exhaust K1's one-per-minute slot via direct budget spend
    assert svc.pool.acquire().key == "K1"
    svc.pool.budgets[0].spend()
    # K1 now unavailable; K2 serves
    assert svc.pool.acquire().key == "K2"

    import time

    svc.pool.budgets[0]._minute_stamps.clear()  # simulate window passing
    time.sleep(0)  # cooldown path covered by mark_frequency_limited unit below
    svc.pool.mark_frequency_limited(svc.pool.budgets[0])
    assert not svc.pool.budgets[0].available()
    svc.pool.budgets[0].cooldown_until -= avmod.FREQUENCY_COOLDOWN_SECONDS + 1
    assert svc.pool.acquire().key == "K1"


@pytest.mark.asyncio
async def test_budget_guard_blocks_without_network(calls):
    tiny = AlphaVantageService()
    tiny.pool = KeyPool(["ONLY"], daily_limit=1, minute_limit=5)

    await tiny._make_request("GLOBAL_QUOTE", {"symbol": "AAPL"})
    with pytest.raises(AlphaVantageRateLimitError):
        await tiny._make_request("GLOBAL_QUOTE", {"symbol": "MSFT"})
    # second call must have been blocked locally: exactly one request total
    assert len(calls["recorded"]) == 1


def test_no_keys_configured_disabled():
    empty = AlphaVantageService()
    empty.pool = KeyPool([], 25, 5)
    assert empty.enabled is False
