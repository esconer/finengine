"""Opt-in freshness envelope for `get_performance_history` (ticket 02, one fn).

The route returned a bare `List[Dict]`, which six consumers assume, so the
default shape is frozen. `include_metadata=true` opts into an envelope that
measures the DELIVERED window against the REQUESTED one:

    truncated  = delivered_start > requested_start + 3 calendar days
    stale      = requested_end - delivered_end >= 3 calendar days
    partial    = non-empty and (truncated or stale or coverage_ratio < 0.50)
    unavailable + as_of=null  = nothing delivered

v3 evidence: the dashboard asked for 90 performance days and got 20 rows ending
2026-09-22, with no warning, while the dashboard `as_of` read 2026-09-25. The
envelope makes that measurable instead of invisible, and never substitutes the
requested end for `as_of` or backfills a missing observation.

The helper under test is a private pure function so the exporter can import it
without going through HTTP.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import numpy as np
import pandas as pd
import pytest

from app.api.analytics import (
    PERFORMANCE_AS_OF_SEMANTICS,
    PERFORMANCE_HISTORY_MIN_COVERAGE_RATIO,
    PERFORMANCE_HISTORY_TOLERANCE_DAYS,
    _performance_history_envelope,
    get_performance_history,
)

ENVELOPE_KEYS = {
    "data", "data_status", "as_of", "as_of_semantics", "history_coverage", "warnings",
    # QM-1 breadth disclosure, ADDITIVE. The default bare-array response is
    # unchanged and the six original keys keep their names, types and positions;
    # these four qualify the series itself, so they sit beside `data` rather than
    # only inside `history_coverage`.
    "constituent_count", "constituent_count_basis", "partial_basket_policy",
    "refused_partial_coverage_rows",
}
COVERAGE_KEYS = {
    "requested_start", "requested_end", "requested_days", "delivered_start",
    "delivered_end", "observation_count", "expected_observation_count",
    "first_observation", "last_observation", "coverage_ratio", "truncated",
    "stale", "status",
    "constituent_count", "constituent_count_basis", "partial_basket_policy",
    "measurable_price_rows", "complete_coverage_price_rows",
    "refused_partial_coverage_price_rows",
    # XS-001/MY-1: always present, None when no holding window was resolved, so
    # the key set stays a function of the call rather than of the data. This pure
    # helper is called without a holding window here, so it publishes None.
    "holding_window",
}


def _rows(dates, *, start_value=1000.0):
    return [
        {
            "date": str(day.date()),
            "portfolio_value": round(start_value * (1.0 + i * 0.001), 2),
            "return": 0.001,
            "currency": "INR",
        }
        for i, day in enumerate(dates)
    ]


def _bdays(periods, end="2026-09-25"):
    return pd.bdate_range(end=end, periods=periods)


# ---------------------------------------------------------------------------
# the pure helper
# ---------------------------------------------------------------------------
def test_envelope_publishes_exactly_the_documented_keys():
    envelope = _performance_history_envelope(
        _rows(_bdays(40)),
        requested_start="2026-06-27",
        requested_end="2026-09-25",
    )

    assert set(envelope) == ENVELOPE_KEYS
    assert set(envelope["history_coverage"]) == COVERAGE_KEYS
    assert envelope["as_of_semantics"] == PERFORMANCE_AS_OF_SEMANTICS


def test_full_delivery_is_available_with_no_flags():
    dates = _bdays(60)
    envelope = _performance_history_envelope(
        _rows(dates),
        requested_start=str(dates[0].date()),
        requested_end=str(dates[-1].date()),
    )

    coverage = envelope["history_coverage"]
    assert envelope["data_status"] == "available"
    assert coverage["truncated"] is False
    assert coverage["stale"] is False
    assert coverage["status"] == "available"
    assert coverage["delivered_start"] == coverage["requested_start"]
    assert coverage["delivered_end"] == coverage["requested_end"]
    assert coverage["observation_count"] == 60
    assert coverage["coverage_ratio"] == 1.0
    assert envelope["as_of"] == str(dates[-1].date())
    assert envelope["warnings"] == []


def test_v3_shape_is_partial_truncated_and_stale():
    """v3 evidence: 90 days requested, 20 rows, ending three days early."""
    dates = _bdays(20, end="2026-09-22")
    envelope = _performance_history_envelope(
        _rows(dates),
        requested_start="2026-06-27",
        requested_end="2026-09-25",
    )

    coverage = envelope["history_coverage"]
    assert envelope["data_status"] == "partial"
    assert coverage["truncated"] is True
    assert coverage["stale"] is True
    assert coverage["status"] == "partial"
    assert coverage["observation_count"] == 20
    assert coverage["delivered_start"] == str(dates[0].date())
    assert coverage["delivered_end"] == "2026-09-22"
    assert coverage["requested_days"] == 90
    assert coverage["coverage_ratio"] < PERFORMANCE_HISTORY_MIN_COVERAGE_RATIO
    # as_of is the last DELIVERED observation, never the requested end.
    assert envelope["as_of"] == "2026-09-22"
    assert envelope["as_of"] != coverage["requested_end"]
    assert any("requested start was not delivered" in w for w in envelope["warnings"])
    assert any("stale" in w for w in envelope["warnings"])


def test_short_but_fresh_delivery_is_partial_on_coverage_alone():
    """A young book's short delivery is disclosed even with no staleness."""
    dates = _bdays(20, end="2026-09-25")
    envelope = _performance_history_envelope(
        _rows(dates),
        requested_start="2026-06-27",
        requested_end="2026-09-25",
    )

    coverage = envelope["history_coverage"]
    assert coverage["stale"] is False
    assert coverage["truncated"] is True
    assert coverage["coverage_ratio"] < PERFORMANCE_HISTORY_MIN_COVERAGE_RATIO
    assert envelope["data_status"] == "partial"
    assert any("expected observations" in w for w in envelope["warnings"])


def test_tolerance_absorbs_only_three_calendar_days():
    """The rule boundary is numeric and exact, not a vibe."""
    start = "2026-09-01"
    end = "2026-09-30"

    def _starting(day: str):
        return [
            {"date": f"2026-09-{day}", "portfolio_value": 1.0, "return": 0.0},
            {"date": end, "portfolio_value": 1.0, "return": 0.0},
        ]

    # Exactly `tolerance` days late is NOT truncated; one more is.
    inside = _performance_history_envelope(
        _starting("04"), requested_start=start, requested_end=end
    )
    outside = _performance_history_envelope(
        _starting("05"), requested_start=start, requested_end=end
    )

    assert inside["history_coverage"]["truncated"] is False
    assert outside["history_coverage"]["truncated"] is True
    assert PERFORMANCE_HISTORY_TOLERANCE_DAYS == 3


def test_staleness_boundary_is_inclusive_at_three_days():
    end = "2026-09-30"
    three_days_early = _rows(_bdays(20, end="2026-09-27"))
    two_days_early = _rows(_bdays(20, end="2026-09-28"))

    assert _performance_history_envelope(
        three_days_early, requested_start="2026-09-01", requested_end=end
    )["history_coverage"]["stale"] is True
    assert _performance_history_envelope(
        two_days_early, requested_start="2026-09-01", requested_end=end
    )["history_coverage"]["stale"] is False


def test_empty_delivery_is_unavailable_with_a_null_as_of():
    envelope = _performance_history_envelope(
        [], requested_start="2026-06-27", requested_end="2026-09-25"
    )

    coverage = envelope["history_coverage"]
    assert envelope["data_status"] == "unavailable"
    assert envelope["as_of"] is None
    assert coverage["status"] == "unavailable"
    assert coverage["observation_count"] == 0
    assert coverage["delivered_start"] is None
    assert coverage["delivered_end"] is None
    assert coverage["truncated"] is False
    assert coverage["stale"] is False
    assert envelope["warnings"]


def test_unmeasurable_dates_are_partial_not_assumed_complete():
    rows = [{"date": "not-a-date", "portfolio_value": 1.0}]
    envelope = _performance_history_envelope(
        rows, requested_start="2026-06-27", requested_end="2026-09-25"
    )

    assert envelope["data_status"] == "partial"
    assert envelope["as_of"] is None
    coverage = envelope["history_coverage"]
    assert coverage["delivered_start"] is None
    assert coverage["delivered_end"] is None
    assert coverage["first_observation"] is None
    assert coverage["last_observation"] is None
    # The row count is still a real measurement, but it cannot be placed in
    # time, so freshness is unmeasured rather than assumed complete.
    assert coverage["observation_count"] == 1
    assert coverage["coverage_ratio"] is not None
    assert any("not ISO dates" in w for w in envelope["warnings"])


def test_unparseable_request_publishes_null_expectation():
    dates = _bdays(20)
    envelope = _performance_history_envelope(
        _rows(dates), requested_start=None, requested_end=None
    )

    coverage = envelope["history_coverage"]
    assert coverage["expected_observation_count"] is None
    assert coverage["requested_start"] is None
    assert coverage["requested_days"] is None
    assert coverage["coverage_ratio"] is None
    # Nothing is invented when the request cannot be measured: the delivery is
    # reported, and it is reported as unmeasured rather than complete.
    assert envelope["data_status"] == "partial"
    assert coverage["truncated"] is False
    assert coverage["stale"] is False


def test_envelope_is_deterministic_and_strict_json():
    dates = _bdays(20, end="2026-09-22")
    kwargs = dict(requested_start="2026-06-27", requested_end="2026-09-25")
    first = _performance_history_envelope(_rows(dates), **kwargs)
    second = _performance_history_envelope(_rows(dates), **kwargs)

    assert first == second
    json.dumps(first, allow_nan=False)


def test_extra_route_warnings_are_preserved():
    dates = _bdays(20, end="2026-09-22")
    envelope = _performance_history_envelope(
        _rows(dates),
        requested_start="2026-06-27",
        requested_end="2026-09-25",
        warnings=["A position carried no usable share quantity."],
    )

    assert envelope["warnings"][0] == "A position carried no usable share quantity."


# ---------------------------------------------------------------------------
# the route: opt-in only
# ---------------------------------------------------------------------------
def _position(ticker, *, quantity=1.0, last_price=100.0, added_on=None):
    return SimpleNamespace(
        ticker=ticker, region="IN", quantity=quantity, last_price=last_price,
        market_value=quantity * last_price, buy_price=None, added_on=added_on,
    )


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        inner = self

        class _Scalars:
            def all(self_inner):
                return inner._rows

        return _Scalars()


def _db(rows):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=lambda *_a, **_k: _Rows(rows))
    return db


class _Market:
    def __init__(self, dates):
        self.dates = dates
        self.fetch_historical_data = AsyncMock(side_effect=self._fetch)

    async def _fetch(self, _ticker, start, end):
        window = self.dates[
            (self.dates >= pd.Timestamp(start)) & (self.dates <= pd.Timestamp(end))
        ]
        values = 100.0 * np.exp(np.arange(len(window)) * 0.001)
        return pd.DataFrame({"close": values}, index=window)


def _bench():
    return SimpleNamespace(
        get_returns=AsyncMock(return_value=pd.Series(dtype=float))
    )


@pytest.mark.asyncio
async def test_default_response_is_still_the_bare_array():
    """Six existing consumers assume an array; the default must not change."""
    dates = _bdays(40)

    result = await get_performance_history(
        days=90, tickers="AAA.NS", db=_db([_position("AAA.NS")]),
        data_service=_Market(dates), benchmark_service=_bench(),
    )

    assert isinstance(result, list)
    assert result and set(result[0]) >= {"date", "portfolio_value", "return"}


@pytest.mark.asyncio
async def test_query_placeholder_is_not_treated_as_an_opt_in():
    """A direct in-process call passes the FastAPI `Query` placeholder."""
    dates = _bdays(40)
    from fastapi import Query as FastAPIQuery

    default = FastAPIQuery(default=False)

    result = await get_performance_history(
        days=90, tickers="AAA.NS", include_metadata=default,
        db=_db([_position("AAA.NS")]),
        data_service=_Market(dates), benchmark_service=_bench(),
    )

    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_opt_in_returns_the_envelope():
    dates = _bdays(40)

    result = await get_performance_history(
        days=90, tickers="AAA.NS", include_metadata=True,
        db=_db([_position("AAA.NS")]),
        data_service=_Market(dates), benchmark_service=_bench(),
    )

    assert set(result) == ENVELOPE_KEYS
    assert isinstance(result["data"], list) and result["data"]
    assert result["data_status"] in {"available", "partial", "unavailable"}
    assert result["as_of"] == result["data"][-1]["date"]
    coverage = result["history_coverage"]
    assert coverage["observation_count"] == len(result["data"])
    assert coverage["last_observation"] == result["as_of"]


@pytest.mark.asyncio
async def test_opt_in_envelope_reports_a_stale_short_delivery():
    """The v3 dashboard shape: 90 requested, far fewer delivered, 3 days stale."""
    dates = _bdays(20, end="2026-09-22")
    position = _position("AAA.NS", added_on=pd.Timestamp("2026-08-20").to_pydatetime())

    result = await get_performance_history(
        days=90, tickers="AAA.NS", include_metadata=True,
        db=_db([position]), data_service=_Market(dates), benchmark_service=_bench(),
    )

    coverage = result["history_coverage"]
    assert result["data_status"] == "partial"
    assert coverage["truncated"] is True
    assert coverage["stale"] is True
    assert result["as_of"] == "2026-09-22"
    assert result["warnings"]


@pytest.mark.asyncio
async def test_opt_in_envelope_for_an_empty_delivery():
    result = await get_performance_history(
        days=90, tickers=None, include_metadata=True,
        db=_db([]), data_service=Mock(), benchmark_service=_bench(),
    )

    assert result["data"] == []
    assert result["data_status"] == "unavailable"
    assert result["as_of"] is None
    assert result["history_coverage"]["observation_count"] == 0
    assert result["warnings"]


@pytest.mark.asyncio
async def test_opt_in_envelope_never_invents_a_date_for_an_undated_frame():
    """A frame with no dates delivers rows, and freshness stays unmeasured."""
    frame = pd.DataFrame({"close": [100.0, 101.0]}, index=pd.RangeIndex(2))

    class _NoDates:
        fetch_historical_data = AsyncMock(return_value=frame)
        fetch_quote = AsyncMock(return_value={})

    result = await get_performance_history(
        days=90, tickers="AAA.NS", include_metadata=True,
        db=_db([_position("AAA.NS")]), data_service=_NoDates(),
        benchmark_service=_bench(),
    )

    assert result["data_status"] == "partial"
    assert result["as_of"] is None
    assert any("not ISO dates" in w for w in result["warnings"])
