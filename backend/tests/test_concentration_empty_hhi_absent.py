"""The concentration route's no-book branch must publish no Herfindahl index.

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

SCOPE.  `n == 0` only. The measured branch is the engine's and is untouched, so
the repo invariant "a single-holding portfolio must strictly render 0%
diversification score" still holds at `n == 1` - pinned below, next to the
`n == 0` case, so the change cannot erode into it.

No network: isolated in-memory DB.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import delete

from app.models.database import PortfolioPosition

#: The fields the ENGINE's empty shape keeps at 0.0, mirrored here so this file
#: fails if a future edit moves one of them too. Zero weight mass is a true
#: statement about an absent book; an unreachable index is not.
ZERO_VALUED_ON_AN_EMPTY_BOOK = (
    "largest_position",
    "top_3",
    "top_5",
    "top_10",
    "effective_positions",
    "diversification_score",
    "gini_coefficient",
)


@pytest.mark.asyncio
async def test_the_empty_route_publishes_no_herfindahl_index(async_client, test_db):
    """The route's no-book branch must match the engine's no-book shape."""
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()

    response = await async_client.get("/api/v1/analytics/concentration")

    assert response.status_code == 200, response.text
    data = response.json()
    assert "herfindahl_index" in data, (
        "a missing key reads as an unrecorded measurement; the field must be "
        "present and null"
    )
    assert data["herfindahl_index"] is None, (
        f"the route published {data['herfindahl_index']!r} for a book with no "
        "holdings. HHI = sum(w_i^2) >= 1/n > 0 for every non-empty book, so no "
        "book can produce this value"
    )
    # Everything the engine keeps at 0.0 stays at 0.0 - this is scoped to the
    # index, and the invariant below is scoped to n == 1.
    for key in ZERO_VALUED_ON_AN_EMPTY_BOOK:
        assert data[key] == 0.0, f"{key} must be 0.0, got {data[key]}"
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

    test_db.add(PortfolioPosition(
        ticker="ONLY.NS", weight=1.0, quantity=10.0, buy_price=100.0,
        last_price=100.0, market_value=1000.0,
        added_on=datetime(2024, 1, 2),
    ))
    await test_db.commit()

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
    """Nothing on this branch may carry a 0.0 the engine's shape also refuses.

    Read off the engine's own empty result rather than a hand-copied list, so
    this test cannot drift from the shape it is checking the route against.
    """
    from app.services.analytics_engine import AnalyticsEngine

    engine_empty = AnalyticsEngine()._empty_concentration()
    assert engine_empty["herfindahl_index"] is None, (
        "the engine's no-book shape no longer refuses the index; the route "
        "cannot be aligned to a shape that has moved"
    )

    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    route_empty = (await async_client.get("/api/v1/analytics/concentration")).json()

    for key in ("largest_position", "top_3", "effective_positions",
                "diversification_score", "gini_coefficient"):
        assert route_empty[key] == engine_empty[key], (
            f"{key}: route publishes {route_empty[key]!r}, the engine's empty "
            f"shape publishes {engine_empty[key]!r}"
        )
    assert route_empty["herfindahl_index"] == engine_empty["herfindahl_index"]