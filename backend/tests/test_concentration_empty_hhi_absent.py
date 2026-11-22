"""The concentration route's no-book branch must publish no concentration statistic.

THE DEFECT.  `AnalyticsEngine._empty_concentration` was fixed to publish
`herfindahl_index: None` (WM-6). The ROUTE's own `if not weights:` early return
never calls the engine, so it kept `0.0` - and its comment defended the choice:

    `n_holdings: 0` beside the 0.0 is what disambiguates this state

which is the argument the engine-level fix overturns. `HHI = sum(w_i^2) >= 1/n`
is strictly positive for every NON-EMPTY book, so `0.0` is not a reachable
measurement at all: it is a third value, sitting in the same field as the two
that can occur (1.0 for one holding, 0.25 for four equal holdings), and a reader
has to consult `n_holdings` to learn which of the three they are holding.

It was not cosmetic. `risk_scoring` fed this field straight into
`min(30, herfindahl_index * 100)`, so on the refusal branch the concentration leg
scored 0 - the BEST possible value on a 0-30 scale where 30 is the most
concentrated book there is - while not being excluded, dragging `overall_score`
down by up to six points. An unmeasured measurement reported as the safest book
there is.

THE SECOND HALF, and why this file is about all nine keys. The engine corrected
ONE key on the no-book shape and left its eight siblings publishing
`0.0`/`1.0`. The asymmetry was the tell: the same dict had been fixed once and
left alone eight times, so the question was never "is this value reachable" but
"which key did someone remember". Each of the eight is a value a real book
measures, and eight of them - all but the index, which WM-6 already took - were
being published by a branch that measured no book at all.

THE TRAP THIS FILE EXISTS TO AVOID.  Three of those eight are ALSO the correct
reading at `n == 1`: `diversification_score` measures 0.0, `gini_coefficient`
measures 0.0 and `diversification_ratio` measures 1.0 on a single-holding book.
The repo's invariant is that a single-holding portfolio must strictly render 0%
diversification, because that IS what the scale reads there. So the correction is
scoped to the `n == 0` shape and the two are pinned SIDE BY SIDE, key by key,
below: `n == 0 -> None` and `n == 1 -> the real number`. A file that pinned only
the `n == 0` arm would pass while the one-holding invariant silently broke.

SCOPE.  `n == 0` only. The measured branch is the engine's and is untouched.

No network: isolated in-memory DB.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import delete

from app.models.database import PortfolioPosition
from app.services.analytics_engine import AnalyticsEngine

#: Every concentration statistic the no-book shape publishes, and the shape's
#: answer for all nine is the same: withhold the value, keep the key.
#:
#: A key present with a stored `None` is what `.get(key, 0.0)` returns `None`
#: from, not 0.0 - so these are still PUBLISHED, not dropped. Dropping one would
#: turn every reader of this shape into a `KeyError` or a silent re-default.
WITHHELD_ON_AN_EMPTY_BOOK = (
    "largest_position",
    "top_3",
    "top_5",
    "top_10",
    "herfindahl_index",
    "effective_positions",
    "diversification_score",
    "diversification_ratio",
    "gini_coefficient",
)

#: What the MEASURED engine branch publishes for each of those keys on a book of
#: exactly one holding - a single name carrying the entire portfolio. This is the
#: arm the fix must not touch, written down rather than implied, because three of
#: these values (`diversification_score`, `diversification_ratio`,
#: `gini_coefficient`) are exactly the numbers the no-book shape used to publish.
MEASURED_AT_ONE_HOLDING = {
    "largest_position": 1.0,
    "top_3": 1.0,
    "top_5": 1.0,
    "top_10": 1.0,
    "herfindahl_index": 1.0,
    "effective_positions": 1.0,
    "diversification_score": 0.0,
    "diversification_ratio": 1.0,
    "gini_coefficient": 0.0,
}

#: RE-DERIVED, not carried over. The question each entry has to answer is no
#: longer "is this key zero on the empty book?" - all nine above used to be, and
#: that was the defect. It is now "ON THE NO-BOOK SHAPE, IS 0 A MEASUREMENT OR A
#: STAND-IN?", asked of every key the shape still publishes:
#:
#:   largest_position      stand-in  - strictly > 0 on every measured book
#:   top_3 / top_5         stand-in  - strictly > 0 on every measured book
#:   top_10                stand-in  - strictly > 0, and 1.0 whenever the book
#                                      has fewer than ten holdings
#:   herfindahl_index      stand-in  - HHI >= 1/n > 0 for n >= 1 (WM-6)
#:   effective_positions   stand-in  - 1/HHI in [1, n]; 0.0 is out of range
#:   diversification_score stand-in HERE, a MEASUREMENT at n == 1, which is why
#                                      it is withheld here and not there
#:   diversification_ratio stand-in HERE, a MEASUREMENT (1.0) at n == 1
#:   gini_coefficient      stand-in HERE, a MEASUREMENT (0.0) at n == 1
#:   n_holdings            MEASUREMENT - a count of zero IS the measurement, and
#:                                      it is the reason the nine above are null
#:   by_sector_total       MEASUREMENT - total sector weight mass really is zero
#:   by_sector_published_  MEASUREMENT - the same total after display rounding
#:   total
#:
#: So the survivors are the count and the two weight totals, and they survive
#: precisely because zero is a true statement about an absent book. Asserted
#: against the route payload; a blanket conversion of the whole shape to `None`
#: would fail this, which is what keeps the list from becoming a tautology - and
#: `WITHHELD_ON_AN_EMPTY_BOOK` above is asserted alongside it, so neither list
#: can be emptied by deleting entries.
ZERO_VALUED_ON_AN_EMPTY_BOOK = (
    "n_holdings",
    "by_sector_total",
    "by_sector_published_total",
)


async def _one_holding_book(test_db) -> None:
    """A book of exactly one holding: the shape that measures the values above."""
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    test_db.add(PortfolioPosition(
        ticker="ONLY.NS", weight=1.0, quantity=10.0, buy_price=100.0,
        last_price=100.0, market_value=1000.0,
        added_on=datetime(2024, 1, 2),
    ))
    await test_db.commit()


@pytest.mark.asyncio
async def test_the_empty_route_publishes_no_measured_concentration_statistic(
    async_client, test_db
):
    """The route's no-book branch must match the engine's no-book shape."""
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()

    response = await async_client.get("/api/v1/analytics/concentration")

    assert response.status_code == 200, response.text
    data = response.json()
    for key in WITHHELD_ON_AN_EMPTY_BOOK:
        assert key in data, (
            f"{key} is missing from the no-book shape; a missing key reads as an "
            "unrecorded measurement, so the field must be present and null"
        )
        assert data[key] is None, (
            f"the route published {data[key]!r} for {key} on a book with no "
            "holdings. Every one of these nine is a value some book measures, so "
            "none of them is a reachable MEASUREMENT here"
        )
    # What survives is what zero is a true statement about: the count, and the
    # two weight totals it explains.
    for key in ZERO_VALUED_ON_AN_EMPTY_BOOK:
        assert key in data, f"{key} was dropped from the no-book shape"
        assert data[key] == 0, f"{key} must stay 0, got {data[key]}"
    assert set(ZERO_VALUED_ON_AN_EMPTY_BOOK).isdisjoint(
        WITHHELD_ON_AN_EMPTY_BOOK
    )
    assert data["n_holdings"] == 0
    assert data["data_status"] == "unavailable"


@pytest.mark.asyncio
async def test_the_empty_branch_cannot_be_mistaken_for_a_measured_book(
    async_client, test_db
):
    """The refusal and the measurement must be distinguishable on every axis.

    This is what the deleted comment claimed `n_holdings: 0` was doing on its
    own. It is not enough: with the index at 0.0 the two differed only in a
    count, so any consumer reading the number - which is what every consumer
    reads - saw a third value no book can produce.
    """
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()

    empty = (await async_client.get("/api/v1/analytics/concentration")).json()

    await _one_holding_book(test_db)

    single = (await async_client.get("/api/v1/analytics/concentration")).json()

    assert empty["n_holdings"] == 0
    assert single["n_holdings"] == 1
    assert single["herfindahl_index"] == 1.0, (
        "the measured branch moved: one holding IS a measurable HHI of 1.0"
    )
    assert empty["herfindahl_index"] != single["herfindahl_index"]
    # And the n == 1 invariant the campaign carries as hard.
    assert single["diversification_score"] == 0.0, (
        "a single-holding book must strictly render 0% diversification score"
    )


@pytest.mark.asyncio
async def test_no_zero_is_published_where_no_book_was_measured(async_client, test_db):
    """Nothing on this branch may carry a value the engine's shape also refuses.

    Read off the engine's own empty result rather than a hand-copied list, so
    this test cannot drift from the shape it is checking the route against - and
    over all nine keys, because the route's early return never calls the engine
    and so publishes its no-book shape INDEPENDENTLY of the engine's. That
    independence is the whole reason a fix applied to only one copy leaves the
    defect standing.
    """
    engine_empty = AnalyticsEngine()._empty_concentration()
    for key in WITHHELD_ON_AN_EMPTY_BOOK:
        assert engine_empty[key] is None, (
            f"the engine's no-book shape publishes {engine_empty[key]!r} for "
            f"{key}; the route cannot be aligned to a shape that still "
            "fabricates a value no book can measure"
        )

    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    route_empty = (await async_client.get("/api/v1/analytics/concentration")).json()

    for key in WITHHELD_ON_AN_EMPTY_BOOK:
        assert route_empty[key] == engine_empty[key], (
            f"{key}: route publishes {route_empty[key]!r}, the engine's empty "
            f"shape publishes {engine_empty[key]!r}"
        )


@pytest.mark.asyncio
async def test_the_no_book_refusal_and_the_one_holding_measurement_side_by_side(
    async_client, test_db
):
    """`n == 0 -> None` and `n == 1 -> the real number`, key by key, together.

    THE TEST THIS TASK EXISTS TO FORCE.  Every other test here asserts one arm.
    An `n == 0`-only file passes green while `diversification_score` at one
    holding is quietly converted to `None` - which would throw away a genuine
    measurement, and would break the repo invariant that a single-holding
    portfolio must strictly render 0% diversification. So both arms are
    asserted in one body, against values read off the real measured branch
    rather than off a hand-written copy of them.
    """
    engine = AnalyticsEngine()
    measured_one_holding = await engine.concentration_analysis({"ONLY.NS": 1.0})

    # The arm that must NOT have moved. Read off the engine's own measured
    # branch, so a blanket `None` in the empty shape cannot be "fixed" here by
    # editing the same wrong number twice.
    assert measured_one_holding["n_holdings"] == 1
    for key, expected in MEASURED_AT_ONE_HOLDING.items():
        assert measured_one_holding[key] == expected, (
            f"the measured branch moved at n == 1: {key} is "
            f"{measured_one_holding[key]!r}, not {expected!r}. "
            "analytics_engine.concentration_analysis is the source of truth for "
            "this arm; the no-book refusal is not"
        )

    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    empty_route = (await async_client.get("/api/v1/analytics/concentration")).json()
    empty_engine = AnalyticsEngine()._empty_concentration()

    await _one_holding_book(test_db)
    single_route = (await async_client.get("/api/v1/analytics/concentration")).json()

    assert empty_route["n_holdings"] == 0
    assert single_route["n_holdings"] == 1

    for key, expected in MEASURED_AT_ONE_HOLDING.items():
        assert empty_engine[key] is None, (
            f"the engine's no-book shape publishes {empty_engine[key]!r} for "
            f"{key}. At one holding this same key measures {expected!r}, so on "
            "the no-book shape it is a stand-in wearing a measurement's key"
        )
        assert empty_route[key] is None, (
            f"the route publishes {empty_route[key]!r} for {key} at n == 0"
        )
        # ... and the arm that MUST still measure.
        assert single_route[key] == expected, (
            f"the measured route moved at n == 1: {key} is "
            f"{single_route[key]!r}, not {expected!r}. A one-holding book really "
            "does measure this, so withholding it would delete a measurement "
            "rather than correct a stand-in"
        )
        assert empty_route[key] != single_route[key], (
            f"{key}: the refusal and the measurement are the same value, so the "
            "two shapes are indistinguishable on this key"
        )

    # The repo invariant, named rather than left implied by the dict above.
    assert single_route["diversification_score"] == 0.0, (
        "a single-holding portfolio must strictly render 0% diversification; "
        "it is the bottom of the scale there, not an absent reading"
    )