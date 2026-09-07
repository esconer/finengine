"""L2 persistent screen-cache regression tests (issue 07).

L1 is process memory (300s); L2 is DB-backed via CacheService (~24h TTL,
cointegration precedent). Second run with cleared L1 (fresh instance, same
L2) must be served from L2 without recomputation — asserted via
screen_getter call counts (timing-independent) plus L2 row existence.
All upstream I/O faked; screening math untouched.
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest

from app.services.screener_service import (
    SCREENER_DB_TICKER,
    ScreenerService,
    _db_cache_keys,
)


@pytest.fixture(autouse=True)
def _cold_l1():
    ScreenerService._cache.clear()
    yield
    ScreenerService._cache.clear()


class _FakeScreen:
    def __init__(self, df, seen):
        self._df = df
        self._seen = seen

    def run(self, universe=None, max_stocks=None, **kwargs):
        self._seen.append({"universe": universe, "max_stocks": max_stocks})
        return self._df


class _FakeL2:
    """Dict-backed CacheService double with TTL expiry."""

    def __init__(self, ttl_minutes=24 * 60):
        self._rows = {}
        self._ttl = timedelta(minutes=ttl_minutes)

    async def get_cached_analytics(self, ticker, metric_name):
        row = self._rows.get((ticker, metric_name))
        if not row or row["expires_at"] <= datetime.utcnow():
            return None
        return {
            "value": row["metric_value"],
            "calculation_date": row["calculation_date"],
            "model_params": row["model_params"],
        }

    async def set_cached_analytics(self, ticker, metric_name, metric_value, calculation_date, model_params=None):
        self._rows[(ticker, metric_name)] = {
            "metric_value": metric_value,
            "calculation_date": calculation_date,
            "expires_at": datetime.utcnow() + self._ttl,
            "model_params": model_params or {},
        }


class _ExplodingL2:
    async def get_cached_analytics(self, *args, **kwargs):
        raise RuntimeError("db down")

    async def set_cached_analytics(self, *args, **kwargs):
        raise RuntimeError("db down")


def _row(sym, **over):
    base = {
        "Symbol": sym, "Name": sym, "Price": 100.0, "MarketCap_Cr": 10000.0,
        "PE": 15.0, "ROCE_%": 25.0, "ROE_%": 20.0, "DivYield_%": 1.0,
        "BookValue": 50.0,
    }
    base.update(over)
    return base


def _install(monkeypatch, seen, rows):
    df = pd.DataFrame(rows)
    monkeypatch.setitem(
        ScreenerService.STRATEGIES["coffee_can"], "screen_getter",
        lambda: _FakeScreen(df, seen),
    )


async def test_second_run_served_from_l2_without_recompute(monkeypatch):
    seen = []
    _install(monkeypatch, seen, [_row("AAA"), _row("BBB")])
    l2 = _FakeL2()

    r1 = await ScreenerService(cache_service=l2).run_screen("coffee_can", universe=["AAA"], max_stocks=50)
    assert len(seen) == 1
    assert len(l2._rows) == 1  # L2 row written on compute
    (ticker, metric), = l2._rows.keys()
    assert ticker == SCREENER_DB_TICKER == "SCREENER"
    assert metric.startswith("screen_coffee_can_") and metric.endswith(datetime.utcnow().strftime("%Y-%m-%d"))

    ScreenerService._cache.clear()  # wipe L1; fresh instance, same L2
    r2 = await ScreenerService(cache_service=l2).run_screen("coffee_can", universe=["AAA"], max_stocks=50)
    assert len(seen) == 1  # no recomputation
    assert r2 == r1  # identical payload


async def test_l2_preserves_universe_isolation(monkeypatch):
    seen = []
    _install(monkeypatch, seen, [_row("AAA")])
    l2 = _FakeL2()
    svc = ScreenerService(cache_service=l2)

    await svc.run_screen("coffee_can", universe=["AAA"], max_stocks=50)
    ScreenerService._cache.clear()
    await svc.run_screen("coffee_can", universe=["BBB"], max_stocks=50)
    assert len(seen) == 2  # different universe => different L2 key => recompute
    assert len(l2._rows) == 2


async def test_l1_still_serves_without_recompute(monkeypatch):
    seen = []
    _install(monkeypatch, seen, [_row("AAA")])
    svc = ScreenerService(cache_service=_FakeL2())

    r1 = await svc.run_screen("coffee_can", universe=["AAA"], max_stocks=50)
    r2 = await svc.run_screen("coffee_can", universe=["AAA"], max_stocks=50)
    assert len(seen) == 1
    assert r2 == r1


async def test_broken_l2_fails_open_to_compute(monkeypatch):
    seen = []
    _install(monkeypatch, seen, [_row("AAA")])
    res = await ScreenerService(cache_service=_ExplodingL2()).run_screen("coffee_can", universe=["AAA"])
    assert len(seen) == 1
    assert [s["symbol"] for s in res["stocks"]] == ["AAA"]


def test_db_keys_fit_column_sizes():
    for strat in ScreenerService.STRATEGIES:
        ticker, metric = _db_cache_keys(strat, "0123456789ab", "2026-09-07")
        assert len(ticker) <= 10, (strat, ticker)  # AnalyticsCache.ticker String(10)
        assert len(metric) <= 50, (strat, metric)  # AnalyticsCache.metric_name String(50)
