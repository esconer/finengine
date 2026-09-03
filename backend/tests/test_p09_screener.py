"""P0-9 contract tests: screener returns correct (not stale/truncated/mislabeled) results.

Regression gates for BACKEND_REVIEW P0-9: cache key omitted universe,
max_stocks truncated the universe pre-filter, numeric BSE scrips were
forced .NS, and debt_free never checked debt. All upstream I/O faked.
"""

import pandas as pd
import pytest

import app.services.screener_service as ss
from app.services.screener_service import ScreenerService


@pytest.fixture(autouse=True)
def _cold_cache():
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


def _row(sym, **over):
    base = {
        "Symbol": sym, "Name": sym, "Price": 100.0, "MarketCap_Cr": 10000.0,
        "PE": 15.0, "ROCE_%": 25.0, "ROE_%": 20.0, "DivYield_%": 1.0,
        "BookValue": 50.0,
    }
    base.update(over)
    return base


async def test_cache_isolates_universes(monkeypatch):
    seen = []
    svc = ScreenerService()
    monkeypatch.setitem(
        ScreenerService.STRATEGIES["coffee_can"], "screen_getter",
        lambda: _FakeScreen(pd.DataFrame([_row("AAA")]), seen),
    )
    r1 = await svc.run_screen("coffee_can", universe=["AAA"], max_stocks=50)
    assert [s["symbol"] for s in r1["stocks"]] == ["AAA"]
    monkeypatch.setitem(
        ScreenerService.STRATEGIES["coffee_can"], "screen_getter",
        lambda: _FakeScreen(pd.DataFrame([_row("BBB")]), seen),
    )
    r2 = await svc.run_screen("coffee_can", universe=["BBB"], max_stocks=50)
    assert [s["symbol"] for s in r2["stocks"]] == ["BBB"]  # not stale AAA


async def test_max_stocks_caps_results_not_universe(monkeypatch):
    seen = []
    df = pd.DataFrame([_row(f"S{i:02d}") for i in range(10)])
    monkeypatch.setitem(
        ScreenerService.STRATEGIES["coffee_can"], "screen_getter",
        lambda: _FakeScreen(df, seen),
    )
    svc = ScreenerService()
    res = await svc.run_screen("coffee_can", universe=[f"S{i:02d}" for i in range(10)], max_stocks=3)
    assert seen[-1]["max_stocks"] is None  # full universe scanned upstream
    assert seen[-1]["universe"] is not None and len(seen[-1]["universe"]) == 10
    assert res["count"] == 3


async def test_numeric_symbol_maps_to_bo(monkeypatch):
    seen = []
    df = pd.DataFrame([_row("500112"), _row("TCS")])
    monkeypatch.setitem(
        ScreenerService.STRATEGIES["coffee_can"], "screen_getter",
        lambda: _FakeScreen(df, seen),
    )
    svc = ScreenerService()
    res = await svc.run_screen("coffee_can")
    tickers = {s["symbol"]: s["ticker"] for s in res["stocks"]}
    assert tickers["500112"] == "500112.BO"
    assert tickers["TCS"] == "TCS.NS"


async def test_debt_free_enforces_leverage(monkeypatch):
    seen = []
    df = pd.DataFrame([_row("LOW"), _row("HIGH"), _row("NODATA")])
    monkeypatch.setitem(
        ScreenerService.STRATEGIES["debt_free"], "screen_getter",
        lambda: _FakeScreen(df, seen),
    )
    debt = {"LOW": 0.1, "HIGH": 0.5, "NODATA": None}

    class _FakeTicker:
        def __init__(self, sym):
            self._sym = sym

        @property
        def info(self):
            return {"debtToEquity": debt[self._sym]}

    monkeypatch.setattr(ss.bf, "Ticker", _FakeTicker)
    svc = ScreenerService()
    res = await svc.run_screen("debt_free")
    assert [s["symbol"] for s in res["stocks"]] == ["LOW"]


async def test_custom_screen_slice_and_ticker(monkeypatch):
    seen = []

    class _FakeCustomScreen:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, max_stocks=None, **kwargs):
            seen.append({"max_stocks": max_stocks})
            return pd.DataFrame([_row(f"C{i:02d}") for i in range(6)] + [_row("500112")])

    monkeypatch.setattr(ss.bf, "Screen", _FakeCustomScreen)
    svc = ScreenerService()
    res = await svc.run_custom_screen(max_stocks=3)
    assert seen[-1]["max_stocks"] is None
    assert res["count"] == 3
