"""A refusal on `/analytics/correlation-stability` must reach the client.

THE DEFECT.  `compute_rolling_avg_correlation` refuses a book whose NEWEST
measurable date is short of all `C = N(N-1)/2` pairs, and it says exactly what
is missing:

    Cannot report average pairwise correlation for 2026-09-28: only 1 of 3 pairs
    have 30 pairwise-complete observations in the trailing 60-day window. An
    average over the remaining 1 pair(s) is not the book-wide figure, so none is
    published.

The route caught `ValueError` and replaced every character of it with
`"Invalid analytics request"`.  That is not merely unhelpful, it is FALSE:
nothing about the request was invalid. The service declined to publish a number
it could not compute, and the client was told its request was malformed.

WHY IT IS ROUTINE, NOT AN EDGE CASE.  The floor is `min(window_days, 30)`
pairwise-complete observations per pair at the newest date, so ANY book
containing a holding listed within roughly the last 30 trading days fails it.
One newly added position is enough. That is the normal state of a live book,
and the route answered it with a message that describes a client bug.

THE FIX, AND WHY IT IS SCOPED.  `detail=str(exc)` on the BLANKET `except
ValueError` that wraps the whole route body would return whatever any code in
that body raises - including a third-party `ValueError` from pandas or numpy
that can embed a repr, a column name or a path. That is a leak surface, so the
reason is surfaced at the ONE call that raises it (`analyze_correlation_stability`
inside `_run_cpu`) and the blanket arm keeps its generic text for everything
else. The five messages that can now reach a client have all been read in
`services/correlation_service.py`: they are composed of a date label, integer
counts, `min_periods` and `window_days`. No path, no token, no repr.

The proof below is on an HTTP RESPONSE BODY, not on a returned dict, because the
defect is that the reason never became bytes on the wire.

No network: seeded RNG only, isolated in-memory DB.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from unittest.mock import AsyncMock, Mock

from app.api import analytics as analytics_mod

#: Three names, so C = 3 pairs.  TWO have the full history and ONE was listed
#: ten sessions ago, which is the routine case: it leaves its two pairs short of
#: the 30-observation floor at the newest date while the third pair clears it.
TICKERS = ("AAA.NS", "BBB.NS", "NEW.NS")
DAYS = 500
NEW_LISTING_BARS = 10
START = "2024-01-02"


def _frame(ticker: str, *, bars: int, seed: int) -> pd.DataFrame:
    """The project's lowercase cache schema (DataService shape)."""
    dates = pd.bdate_range(start=START, periods=bars, freq="B")
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, bars)))
    return pd.DataFrame({
        "date": dates,
        "open": close * (1 + rng.normal(0, 0.004, bars)),
        "high": close * 1.008,
        "low": close * 0.992,
        "close": close,
        "adj_close": close,
        "volume": rng.integers(100_000, 1_000_000, bars).astype(float),
        "ticker": ticker,
    })


@pytest.fixture
def partly_listed_book():
    """A two-established-names book plus one name listed ten sessions ago.

    The short leg is placed on the SAME calendar as the long ones, so the wide
    frame is not ragged in the index - only in the pair denominator. That is the
    distinction the refusal is about.
    """
    frames = {
        TICKERS[0]: _frame(TICKERS[0], bars=DAYS, seed=7),
        TICKERS[1]: _frame(TICKERS[1], bars=DAYS, seed=13),
        TICKERS[2]: _frame(
            TICKERS[2], bars=NEW_LISTING_BARS, seed=21
        ).assign(date=lambda d: d["date"].tail(NEW_LISTING_BARS)),
    }
    # The short listing's bars must sit at the END of the shared calendar, so
    # rebuild it against the long frames' dates rather than the frame's own.
    long_dates = frames[TICKERS[0]]["date"]
    rng = np.random.default_rng(21)
    short_close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, NEW_LISTING_BARS)))
    frames[TICKERS[2]] = pd.DataFrame({
        "date": long_dates.tail(NEW_LISTING_BARS).to_numpy(),
        "open": short_close * 1.002,
        "high": short_close * 1.008,
        "low": short_close * 0.992,
        "close": short_close,
        "adj_close": short_close,
        "volume": 250_000.0,
        "ticker": TICKERS[2],
    })

    service = Mock()
    service.fetch_historical_data = AsyncMock(side_effect=lambda t, *a, **k: frames[t])
    return service


async def _get(async_client, service, query: str = ""):
    from main import app
    app.dependency_overrides[analytics_mod.get_data_service] = lambda: service
    try:
        return await async_client.get(
            f"/api/v1/analytics/correlation-stability?tickers={query}"
            f"{'&' if query else ''}lookback_days=756&window_days=60"
        )
    finally:
        app.dependency_overrides.pop(analytics_mod.get_data_service, None)


@pytest.mark.asyncio
async def test_the_client_receives_the_reason_the_pair_floor_refused(
    async_client, partly_listed_book
):
    """The reason has to be BYTES ON THE WIRE, not a returned object."""
    response = await _get(
        async_client, partly_listed_book, query=",".join(TICKERS)
    )

    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail != "Invalid analytics request", (
        "the route is still replacing a refusal with a claim that the client "
        "sent something invalid"
    )
    # The service's own words, which name the date, the shortfall and the rule.
    assert "Cannot report average pairwise correlation" in detail
    assert "1 of 3 pairs" in detail
    assert "30 pairwise-complete observations" in detail
    assert "60-day window" in detail


@pytest.mark.asyncio
async def test_the_refusal_does_not_blame_the_request(async_client, partly_listed_book):
    """Nothing in the body may describe the request as the cause.

    The refusal is a property of the BOOK and the WINDOW, both of which are
    server-side facts here: the tickers named in the query resolve to frames the
    service itself fetched.
    """
    response = await _get(
        async_client, partly_listed_book, query=",".join(TICKERS)
    )
    detail = response.json()["detail"].lower()
    for accusation in ("invalid", "malformed", "bad request", "unrecognized"):
        assert accusation not in detail, (
            f"the refusal still accuses the request: {detail!r}"
        )


@pytest.mark.asyncio
async def test_the_published_route_is_unaffected_when_the_floor_clears(async_client):
    """Non-vacuity: the same route on a measurable book still returns numbers.

    Without this, "the body is not 'Invalid analytics request'" would also be
    satisfied by a route that refuses everything.
    """
    frames = {
        ticker: _frame(ticker, bars=DAYS, seed=seed)
        for ticker, seed in zip(("AAA.NS", "BBB.NS", "CCC.NS"), (7, 13, 21))
    }
    service = Mock()
    service.fetch_historical_data = AsyncMock(side_effect=lambda t, *a, **k: frames[t])

    response = await _get(async_client, service, query="AAA.NS,BBB.NS,CCC.NS")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["current_avg_correlation"] is not None
    assert body["series"], "a cleared floor must publish the series it measured"