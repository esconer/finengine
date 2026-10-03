"""`/analytics/factor-exposure` must publish which benchmark it measured on.

THE DEFECT.  `services/benchmark_service.py` names what its price leg is -
`BENCHMARK_RETURN_BASIS = "price_index"`, the column it actually resolved, the
symbol and the name - and stamps all of it on the objects it returns, in
`attrs`. `get_benchmark_df` and `get_returns` both do it, and the service's own
tests pin that the return series carries it.

The factor-exposure payloads published NO benchmark block at all. Every alpha,
beta and R-squared on that route is a regression AGAINST this index, and a
reader had to infer which one it was from the word "market" in the
methodology string. The disclosure existed, travelled one service hop, and died
there.

WHY THE BASIS MATTERS SPECIFICALLY HERE.  `price_index` says dividends are NOT
in the leg. A beta fitted against a price index and a beta fitted against a
total-return index are different numbers, and nothing on the payload said which
one was published. The data half - sourcing a TRI - is deferred for a stated
reason (no `^NSEI` TRI on the available feed, and an ETF proxy is a different
index, not the same one with dividends), so the basis is the whole disclosure.

THE BLOCK IS THE SERVICE'S, NOT A RESTATEMENT.  `benchmark_basis_disclosure(df)`
is the service's single source for the block's shape and its column resolution.
This route holds the RETURNS LEG rather than the frame, and
`benchmark_basis_disclosure` takes a frame - so the block is read off the attrs
the service stamped onto that leg, through the service's own attribute-key
constants. `test_the_route_block_is_the_services_own_disclosure_for_the_same_frame`
pins the two against each other on a real `get_returns` call, so the route
cannot drift from `benchmark_basis_disclosure`'s output.

Calling `get_benchmark_df()` instead was rejected: it re-fetches
`fetch_historical_data` over a DIFFERENT window (1100 days vs the route's
lookback), so on a cold cache it is a second vendor request for the same index,
on a route whose disclosure is supposed to change no value and cost nothing.

THE `price_column: None` CASE IS PUBLISHED, NOT DROPPED.  No close column in the
served frame means the measurement was never taken, and the null says so. A
missing key would read as an unrecorded disclosure.

No network: seeded RNG only, isolated in-memory DB.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.api import analytics as analytics_mod
from app.models.database import PortfolioPosition
from app.services.analytics_engine import AnalyticsEngine
from app.services.benchmark_service import (
    BENCHMARK_NAME,
    BENCHMARK_PRICE_COLUMN_ATTR,
    BENCHMARK_RETURN_BASIS,
    BENCHMARK_RETURN_BASIS_ATTR,
    BENCHMARK_SYMBOL,
    benchmark_basis_disclosure,
)

TICKERS = ("AAA.NS", "BBB.NS", "CCC.NS")
DAYS = 320
START = "2024-01-02"
SEEDS = {"AAA.NS": 7, "BBB.NS": 13, "CCC.NS": 21}
#: The benchmark leg has to cover the window the ROUTE asks for, which is
#: `datetime.now() - lookback_days .. datetime.now()`. A frame anchored to a
#: fixed 2024 date lies entirely outside it, the service slices it to nothing
#: and returns None - a correct refusal that would make this file's assertions
#: vacuous. Anchored to today instead, so a leg is really served.
BENCHMARK_DAYS = 400


def _frame(
    ticker: str, *, days: int = DAYS, seed: int = 3, end: Optional[str] = None
) -> pd.DataFrame:
    dates = (
        pd.bdate_range(end=end, periods=days, freq="B")
        if end
        else pd.bdate_range(start=START, periods=days, freq="B")
    )
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, days)))
    return pd.DataFrame({
        "date": dates,
        "open": close * (1 + rng.normal(0, 0.004, days)),
        "high": close * 1.008,
        "low": close * 0.992,
        "close": close,
        "adj_close": close,
        "volume": rng.integers(100_000, 1_000_000, days).astype(float),
        "ticker": ticker,
    })


def _benchmark_frame(seed: int = 99) -> pd.DataFrame:
    """A benchmark leg spanning the trailing window the factor route requests."""
    return _frame(
        BENCHMARK_SYMBOL,
        days=BENCHMARK_DAYS,
        seed=seed,
        end=pd.Timestamp.now().normalize().strftime("%Y-%m-%d"),
    )


def _returns_from_frame(frame: pd.DataFrame) -> pd.Series:
    """What the service returns for that frame: close -> returns, attrs stamped."""
    from app.services.benchmark_service import _attach_basis_disclosure

    prices = frame.set_index("date")["close"]
    returns = prices.pct_change(fill_method=None).dropna()
    returns.name = "benchmark"
    _attach_basis_disclosure(returns, "adj_close")
    return returns


@pytest.fixture
def book_and_services():
    frames = {ticker: _frame(ticker, seed=SEEDS[ticker]) for ticker in TICKERS}
    bench_frame = _benchmark_frame()

    class _Data:
        async def fetch_historical_data(self, ticker, start=None, end=None):
            if ticker == BENCHMARK_SYMBOL:
                return bench_frame
            return frames[ticker]

    class _Benchmark:
        async def get_returns(self, start=None, end=None, days=756):
            return _returns_from_frame(bench_frame)

        async def get_benchmark_df(self, days=1100):
            return bench_frame

    return _Data(), _Benchmark()


async def _book(test_db) -> None:
    await test_db.execute(delete(PortfolioPosition))
    for index, ticker in enumerate(TICKERS):
        test_db.add(PortfolioPosition(
            ticker=ticker, weight=1.0 / len(TICKERS), quantity=10.0,
            buy_price=100.0, last_price=100.0,
            market_value=1000.0 / len(TICKERS),
            added_on=pd.Timestamp(START).to_pydatetime(),
        ))
    await test_db.commit()


async def _factor_exposure(async_client, data, benchmark):
    from main import app
    app.dependency_overrides[analytics_mod.get_data_service] = lambda: data
    app.dependency_overrides[analytics_mod.get_benchmark_service] = lambda: benchmark
    app.dependency_overrides[analytics_mod.get_analytics_engine] = lambda: AnalyticsEngine()
    try:
        return await async_client.get("/api/v1/analytics/factor-exposure")
    finally:
        for dependency in (
            analytics_mod.get_data_service,
            analytics_mod.get_benchmark_service,
            analytics_mod.get_analytics_engine,
        ):
            app.dependency_overrides.pop(dependency, None)


@pytest.mark.asyncio
async def test_the_payload_names_the_benchmark_it_was_measured_against(
    async_client, test_db, book_and_services
):
    await _book(test_db)
    data, benchmark = book_and_services

    response = await _factor_exposure(async_client, data, benchmark)

    assert response.status_code == 200, response.text
    body = response.json()
    assert "benchmark" in body, (
        "the payload publishes no benchmark block, so a reader has to infer "
        "which index every alpha and beta was fitted against"
    )
    block = body["benchmark"]
    assert block["symbol"] == BENCHMARK_SYMBOL
    assert block["name"] == BENCHMARK_NAME
    assert block["return_basis"] == BENCHMARK_RETURN_BASIS
    assert block["price_column"] == "adj_close"
    # Non-vacuity: the block is beside real figures, not on a refused section.
    assert body["portfolio"]


@pytest.mark.asyncio
async def test_a_benchmark_that_never_arrived_claims_no_basis(
    async_client, test_db, book_and_services
):
    """No leg served means no basis to state.

    The service stamps `price_column` even when it is None, because "no close
    column was present" is the answer a reader needs. A route that filled the
    basis in anyway would be asserting a property of a leg that does not exist.
    """
    await _book(test_db)
    data, _ = book_and_services

    class _NoBenchmark:
        async def get_returns(self, start=None, end=None, days=756):
            return None

    response = await _factor_exposure(async_client, data, _NoBenchmark())

    assert response.status_code == 200, response.text
    block = response.json()["benchmark"]
    assert block["return_basis"] is None
    assert block["price_column"] is None


@pytest.mark.asyncio
async def test_an_absent_close_column_is_published_as_null(
    async_client, test_db, book_and_services
):
    """The `price_column: None` case reaches the payload rather than vanishing."""
    await _book(test_db)
    data, _ = book_and_services
    bare = _benchmark_frame().drop(columns=["close", "adj_close"])

    class _Benchmark:
        async def get_returns(self, start=None, end=None, days=756):
            from app.services.benchmark_service import _attach_basis_disclosure

            returns = pd.Series(
                np.random.default_rng(4).normal(0.0003, 0.01, len(bare)),
                index=pd.to_datetime(bare["date"]),
                name="benchmark",
            )
            _attach_basis_disclosure(returns, None)
            return returns

        async def get_benchmark_df(self, days=1100):
            return bare

    response = await _factor_exposure(async_client, data, _Benchmark())

    assert response.status_code == 200, response.text
    block = response.json()["benchmark"]
    assert "price_column" in block
    assert block["price_column"] is None


@pytest.mark.asyncio
async def test_a_refused_section_publishes_no_benchmark_block(
    async_client, book_and_services
):
    """No book means no regression, so there is no benchmark to describe."""
    data, benchmark = book_and_services

    response = await _factor_exposure(async_client, data, benchmark)

    assert response.status_code == 200, response.text
    assert response.json()["benchmark"] is None


@pytest.mark.asyncio
async def test_the_route_block_is_the_services_own_disclosure_for_the_same_frame(
    async_client, test_db, book_and_services
):
    """The block is the service's disclosure, not a second copy of it.

    Driven through the service's OWN `get_returns` - the attrs the route reads
    are stamped by `_attach_basis_disclosure`, not by this test - and then
    compared against `benchmark_basis_disclosure` on the same frame. If the
    route's block and the service's function ever disagree, one of them is wrong
    and this goes red. That is the guard that lets the route read `attrs`
    instead of calling the function: the shape and the column resolution have one
    owner, and the route is checked against it.
    """
    from app.services.benchmark_service import BenchmarkService

    await _book(test_db)
    data, _ = book_and_services
    frame = _benchmark_frame()

    class _DataOnly:
        async def fetch_historical_data(self, ticker, start=None, end=None):
            assert ticker == BENCHMARK_SYMBOL
            return frame

    real_service = BenchmarkService.__new__(BenchmarkService)
    real_service.data_service = _DataOnly()

    from main import app
    app.dependency_overrides[analytics_mod.get_data_service] = lambda: data
    app.dependency_overrides[analytics_mod.get_benchmark_service] = lambda: real_service
    app.dependency_overrides[analytics_mod.get_analytics_engine] = lambda: AnalyticsEngine()
    try:
        response = await async_client.get("/api/v1/analytics/factor-exposure")
    finally:
        for dependency in (
            analytics_mod.get_data_service,
            analytics_mod.get_benchmark_service,
            analytics_mod.get_analytics_engine,
        ):
            app.dependency_overrides.pop(dependency, None)

    assert response.status_code == 200, response.text
    published = response.json()["benchmark"]
    expected = benchmark_basis_disclosure(frame)

    assert published == expected, (
        "the route's benchmark block is not the service's disclosure for the "
        f"frame it was served: {published} != {expected}"
    )
    assert expected == {
        "symbol": BENCHMARK_SYMBOL,
        "name": BENCHMARK_NAME,
        "price_column": "adj_close",
        "return_basis": BENCHMARK_RETURN_BASIS,
    }
    # And the attrs really came from the service, not from this test.
    returns = await real_service.get_returns(
        start=frame["date"].iloc[0].strftime("%Y-%m-%d"),
        end=frame["date"].iloc[-1].strftime("%Y-%m-%d"),
    )
    assert returns is not None
    assert returns.attrs[BENCHMARK_PRICE_COLUMN_ATTR] == "adj_close"
    assert returns.attrs[BENCHMARK_RETURN_BASIS_ATTR] == BENCHMARK_RETURN_BASIS


@pytest.mark.asyncio
async def test_the_block_moves_no_published_figure(
    async_client, test_db, book_and_services, monkeypatch
):
    """A disclosure is a disclosure: every other key must be untouched."""
    import json

    await _book(test_db)
    data, benchmark = book_and_services
    before = (await _factor_exposure(async_client, data, benchmark)).json()
    assert "benchmark" in before, "there is no block to hold to a no-change rule"
    monkeypatch.setattr(
        analytics_mod, "_benchmark_basis_block", lambda *_a, **_k: {}, raising=False
    )
    after = (await _factor_exposure(async_client, data, benchmark)).json()

    assert set(before) - {"benchmark"} == set(after) - {"benchmark"}
    stripped_before = {k: v for k, v in before.items() if k != "benchmark"}
    stripped_after = {k: v for k, v in after.items() if k != "benchmark"}
    assert json.dumps(stripped_before, sort_keys=True, default=repr) == json.dumps(
        stripped_after, sort_keys=True, default=repr
    ), "the benchmark block changed a published figure"