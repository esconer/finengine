"""E2: the custom screener must not admit or exclude a name using a number
it invented for a fundamental the provider never returned.

Before (screener_service.py:317-320):

    roce = info.get("returnOnCapitalEmployed") or 0.0   # absent -> 0.0  -> FAILS min_roce
    roe  = (info.get("returnOnEquity") or 0.0) * 100     # absent -> 0.0  -> FAILS min_roe
    pe   = info.get("trailingPE") or 999.0               # absent -> 999  -> PASSES every max_pe

Two absent fundamentals, opposite verdicts, both fabricated. A name the
provider could not score was silently rejected on a fake 0.0 and silently
accepted on a fake 999.

Measured on 75 Indian symbols (NIFTY 50 + mid caps + thin small caps), 2026-10-03:
all five fields are present for 69 (92.0%) and absent for 6 (8.0%), with no
partial cases -- presence is all-or-nothing per ticker, driven by whether
bfinance resolves the symbol's fundamentals at all. `info` itself is a NON-empty
dict in all 75 cases, so the existing `if not info: return False` guard never
fires and the fabricated defaults are the only thing standing between an
unscored name and a result row. The 8% are real names (TATAMOTORS, ZOMATO,
EQUITASBN, SUBCAP) lost to symbol-resolution failure, so excluding them is a
known, disclosed cost -- not an empty result set.

Decision: (a) exclude on absence, but only for a threshold the caller
actually asked about. An unmeasured field cannot satisfy a constraint on that
field; a screen with no thresholds on it is not asking the question, so
absence stays irrelevant to the verdict and is merely recorded. This keeps
`run_custom_screen()` with all-None filters behaving exactly as before.

`dividendYield` measured 0.0 for 7 of 75 names (non-payers). That is a real
reading and must NOT be treated as absence -- hence the `is None` checks
rather than truthiness.

Side channel: `_filter` runs on a worker thread (asyncio.to_thread at
screener_service.py:364) and bfinance calls it once per ticker, so the missing
field map is mutated off the event loop. Written under a `threading.Lock`:
CPython makes dict `__setitem__` and `list.append` atomic under the GIL, but
nothing in the call signature (`filter_fn: Callable[[Ticker], bool]`, sync, no
error channel) rules out bfinance driving the predicate from a worker pool, and
a read-modify-write counter is lost-update-prone there. The lock is correct
whether the calls are serial on one thread or concurrent on many, and costs
nothing measurable.

All upstream I/O faked; bfinance's `Screen.run` is replaced by a driver that
reproduces its documented contract -- call `filter_fn` per ticker, keep the
truthy ones.
"""

import threading

import pandas as pd
import pytest

import app.services.screener_service as ss
from app.services.screener_service import ScreenerService


def _info(**over):
    """A fully-scored `info` dict; `over` sets or blanks single fields."""
    base = {
        "returnOnCapitalEmployed": 22.0,
        "returnOnEquity": 0.19,
        "trailingPE": 18.0,
        "marketCapInCr": 45000.0,
        "dividendYield": 1.4,
    }
    for k, v in over.items():
        if v is _ABSENT:
            base.pop(k, None)
        else:
            base[k] = v
    return base


class _Absent:
    def __repr__(self):
        return "<ABSENT>"


def _short(field: str) -> str:
    """Side-channel key a provider field is recorded under."""
    return {
        "returnOnCapitalEmployed": "roce",
        "returnOnEquity": "roe",
        "trailingPE": "pe",
        "marketCapInCr": "market_cap",
        "dividendYield": "dividend_yield",
    }[field]


_ABSENT = _Absent()

SCORED = _info()
NO_ROCE = _info(returnOnCapitalEmployed=_ABSENT)
NO_PE = _info(trailingPE=_ABSENT)
NO_MCAP = _info(marketCapInCr=_ABSENT)
NO_DIV = _info(dividendYield=_ABSENT)
# bfinance's empty-profile fallback shape. `info` is NOT an empty dict: in the
# 75-symbol sweep every symbol returned a populated dict, and the 6 unscored
# ones were missing the five fundamentals while still carrying descriptor keys.
# That distinction is the whole defect -- the pre-existing `if not info` guard
# never fires for a real unscored name.
EMPTY_PROFILE = {
    "symbol": "BARE", "shortName": "Bare Industries", "sector": "Industrials",
    "industry": "Conglomerates",
}
ZERO_DIV = _info(dividendYield=0.0)
LOSS_MAKER = _info(trailingPE=-4.0)

UNIVERSE = {
    "SCORED": SCORED,
    "NOROCE": NO_ROCE,
    "NOPE": NO_PE,
    "NOMCAP": NO_MCAP,
    "NODIV": NO_DIV,
    "BARE": EMPTY_PROFILE,
    "ZERODIV": ZERO_DIV,
    "LOSS": LOSS_MAKER,
}


class _FakeTicker:
    def __init__(self, symbol, info):
        self.symbol = symbol
        self._info = info

    @property
    def info(self):
        return self._info


class _DriverScreen:
    """Reproduces `bf.Screen`'s contract: run filter_fn per ticker, keep the
    truthy verdicts, hand back a frame. The predicate's only channel is
    truthiness, which is why "unscored" has to be surfaced out of band."""

    def __init__(self, *args, filter_fn=None, **kwargs):
        self.filter_fn = filter_fn

    def run(self, universe=None, max_stocks=None, **kwargs):
        syms = list(UNIVERSE) if universe is None else list(universe)
        kept = [s for s in syms if self.filter_fn(_FakeTicker(s, UNIVERSE[s]))]
        return pd.DataFrame([
            {
                "Symbol": s, "Name": s, "Price": 100.0, "MarketCap_Cr": 1000.0,
                "PE": 18.0, "ROCE_%": 22.0, "ROE_%": 19.0, "DivYield_%": 1.4,
            }
            for s in kept
        ])


@pytest.fixture(autouse=True)
def _driver(monkeypatch):
    ScreenerService._cache.clear()
    monkeypatch.setattr(ss.bf, "Screen", _DriverScreen)
    yield
    ScreenerService._cache.clear()


async def _screen(**kwargs):
    res = await ScreenerService().run_custom_screen(**kwargs)
    return [s["symbol"] for s in res["stocks"]], res


# --------------------------------------------------------------------------
# The defect: one absence, two opposite verdicts.
# --------------------------------------------------------------------------

async def test_unscored_pe_is_not_admitted_by_a_fabricated_999():
    """An absent P/E never satisfies an active max_pe.

    `max_pe=1000` is the shape that exposed the old `or 999.0`: 999 is just
    under a 1000 ceiling, so BARE passed on a number that was never measured.
    """
    kept, _ = await _screen(max_pe=1000.0)
    assert "BARE" not in kept


async def test_unscored_pe_is_excluded_even_when_other_passes():
    """The consistency assertion: ROCE and P/E on the same absent ticker now
    reach the same verdict. Before the fix, min_roce rejected BARE and
    max_pe accepted it."""
    on_roce, _ = await _screen(min_roce=10.0)
    on_pe, _ = await _screen(max_pe=1000.0)
    assert ("BARE" in on_roce) is ("BARE" in on_pe)


@pytest.mark.parametrize(
    "field,kwargs",
    [
        ("returnOnCapitalEmployed", {"min_roce": 10.0}),
        ("returnOnEquity", {"min_roe": 10.0}),
        ("trailingPE", {"max_pe": 30.0}),
        ("marketCapInCr", {"min_mcap_cr": 100.0}),
        ("dividendYield", {"min_div_yield": 0.5}),
    ],
)
async def test_every_field_excludes_on_absence_not_on_a_stand_in(field, kwargs):
    kept, res = await _screen(**kwargs)
    unscored = res["unscored"]

    assert "BARE" not in kept, f"unscored on {field} must not be scored on it"
    assert unscored["count"] >= 1
    missing = unscored["symbols"]["BARE"]
    assert _short(field) in missing, (field, missing)


# --------------------------------------------------------------------------
# Absent field, threshold NOT asked for -> absence must not change the verdict.
# --------------------------------------------------------------------------

async def test_no_thresholds_is_unaffected_by_absence():
    """A screen that asks nothing must not silently shrink: this is what
    stops decision (a) from emptying the result set on an unfiltered query."""
    kept, _ = await _screen()
    assert kept == list(UNIVERSE)


async def test_absence_does_not_exclude_when_that_field_is_not_screened():
    kept, res = await _screen(min_roce=10.0)
    # NOROCE is out (asked about ROCE); NOPE / NOMCAP / NODIV are in, because
    # no threshold was set on the fields they are missing.
    assert "NOROCE" not in kept
    assert {"NOPE", "NOMCAP", "NODIV", "SCORED", "ZERODIV", "LOSS"} <= set(kept)
    assert "NOPE" in res["unscored"]["symbols"]


async def test_scored_names_still_pass_every_active_threshold():
    kept, _ = await _screen(
        min_roce=10.0, min_roe=10.0, max_pe=30.0, min_mcap_cr=100.0, min_div_yield=0.5
    )
    assert kept == ["SCORED"]


# --------------------------------------------------------------------------
# A measured zero is a reading, not an absence.
# --------------------------------------------------------------------------

async def test_measured_zero_dividend_is_rejected_not_excluded_as_unscored():
    kept, res = await _screen(min_div_yield=2.0)
    assert "ZERODIV" not in kept, "a measured 0% yield must fail a 2% floor"
    assert "ZERODIV" not in res["unscored"]["symbols"], (
        "0.0 was measured, so the ticker is scored, not unscored"
    )


async def test_measured_loss_making_pe_is_rejected():
    kept, res = await _screen(max_pe=30.0)
    assert "LOSS" not in kept
    assert "LOSS" not in res["unscored"]["symbols"]


# --------------------------------------------------------------------------
# The side channel.
# --------------------------------------------------------------------------

async def test_side_channel_names_every_dropped_ticker_and_why():
    kept, res = await _screen(max_pe=1000.0)
    assert "BARE" not in kept
    symbols = res["unscored"]["symbols"]
    assert symbols["BARE"] == ["roce", "roe", "pe", "market_cap", "dividend_yield"]
    assert res["unscored"]["count"] == len(symbols)


async def test_side_channel_survives_concurrent_predicate_calls(monkeypatch):
    """`filter_fn` is handed to bfinance and called off the event loop. Drive
    it from 400 threads at once and assert no recorded entry is lost -- the
    property the threading.Lock in `_filter` exists to provide."""
    class _CountingScreen(_DriverScreen):
        def __init__(self, *args, filter_fn=None, **kwargs):
            super().__init__(*args, filter_fn=filter_fn, **kwargs)
            self.calls = 0

        def run(self, universe=None, max_stocks=None, **kwargs):
            syms = [f"T{i}" for i in range(400)]
            infos = {s: dict(EMPTY_PROFILE) for s in syms}
            threads = [
                threading.Thread(target=self.filter_fn, args=(_FakeTicker(s, infos[s]),))
                for s in syms
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            return pd.DataFrame()

    monkeypatch.setattr(ss.bf, "Screen", _CountingScreen)
    res = await ScreenerService().run_custom_screen(max_pe=50.0)
    seen = res["unscored"]["symbols"]
    assert len(seen) == 400, f"lost {400 - len(seen)} records under concurrency"
    assert res["unscored"]["count"] == 400