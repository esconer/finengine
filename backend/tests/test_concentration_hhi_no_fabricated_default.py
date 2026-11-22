"""The concentration route must not fabricate a Herfindahl index.

THE DEFECT.  `get_concentration_metrics` published, on its measured path,

    concentration_result.get("herfindahl_index", 0.0)

HHI = sum(w_i^2) >= 1/n > 0 for every non-empty book, so 0.0 is not a reachable
measurement: it is a third value sitting in a field whose only two real values
are 1.0 (one holding) and 0.25 (four equal holdings). On a single-holding book
it is not merely unreachable, it is WRONG - that book measures exactly 1.0.

Every other reader of this same field had already been made to refuse it.
`_empty_concentration` publishes `None` (WM-6), `risk_scoring` guards with an
explicit `is not None` (WM-4/WM-5), and the summary payload's
`concentration_score` reads it without a default. This line was the one the
campaign missed, so the route still carried the fabricated zero its siblings had
been fixed to withhold.

WHY THE DEFAULT COULD NOT FIRE - and why that is still the defect.
`concentration_analysis` returns exactly one of two shapes, the measured dict
and `_empty_concentration`, and BOTH carry `herfindahl_index`. A key PRESENT
with a stored `None` is what `.get(key, 0.0)` returns `None` from, not 0.0, so
the withholding path was already safe. That is exactly why the default was worth
removing: it was a live fabrication kept silent only because an invariant
elsewhere happened to hold. Break that invariant and this line converts "the key
is missing" into "diversification is 0.0".

SCOPE.  Removing the default changes nothing observable on either reachable
shape: the two published payloads are byte-identical. Only the ABSENT case
changes, and it now refuses rather than inventing - `KeyError` reaches the
route's own `except Exception`, which logs and returns 500. A book that
genuinely measures 1.0 still publishes 1.0.

No network: isolated in-memory DB.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Any, AsyncIterator, Dict

import pytest
from sqlalchemy import delete

from app.api import analytics as analytics_mod
from app.models.database import PortfolioPosition
from app.services.analytics_engine import AnalyticsEngine

#: The no-book concentration shape's key list, and its derivation, live in
#: exactly one place. Imported rather than restated -- see
#: `ROUTE_SUBSCRIPTED_CONCENTRATION_KEYS` below, which is the same nine keys and
#: used to be a second literal.
from tests.test_concentration_empty_hhi_absent import WITHHELD_ON_AN_EMPTY_BOOK

#: The two shapes `concentration_analysis` can return. Read off the engine itself
#: below rather than hand-copied, so this file cannot drift from the contract it
#: is pinning.
ENGINE_CONTRACT_SHAPES = ("measured", "empty")

#: The nine keys `get_concentration_metrics` reads by SUBSCRIPT off the engine's
#: result on its measured path (the eight converted from `.get(key, <number>)`
#: plus `herfindahl_index`). Listed here so a shape that drops any one of them
#: is caught by name rather than by whatever `KeyError` happens to surface.
#:
#: This is the invariant the route's subscripts rest on, and it is an invariant
#: about the ENGINE's return type -- not about every object that can be bound to
#: `get_analytics_engine`. The seam is `Depends`, so a substituted engine is
#: reachable, and a partial dict there is a broken stand-in rather than a third
#: engine shape. `test_a_missing_index_is_refused_rather_than_reported_as_zero`
#: below pins that such a dict is refused (non-200), never defaulted.
#:
#: It is the SAME nine keys the no-book shape withholds, and for the same
#: underlying reason: both were the set of statistics the route treated as
#: always-readable, one by subscript and one by value. This file used to write
#: them out a third time. It now aliases the derived tuple rather than holding a
#: second literal, so a key added to or removed from the shape cannot leave this
#: one behind -- a hand-written list is checked against nothing but itself, and
#: that is exactly how seven of these keys drifted while this file went green.
ROUTE_SUBSCRIPTED_CONCENTRATION_KEYS = WITHHELD_ON_AN_EMPTY_BOOK


async def _engine_shape(name: str) -> Dict[str, Any]:
    """One of the engine's two `concentration_analysis` return shapes."""
    engine = AnalyticsEngine()
    if name == "measured":
        return await engine.concentration_analysis({"ONLY.NS": 1.0})
    return engine._empty_concentration()


@contextlib.asynccontextmanager
async def _engine_returning(result: Dict[str, Any]) -> AsyncIterator[None]:
    """Bind the route's analytics engine to a fixed `concentration_analysis`."""
    from main import app

    class _Stub:
        async def concentration_analysis(self, weights):
            return result

    app.dependency_overrides[analytics_mod.get_analytics_engine] = lambda: _Stub()
    try:
        yield
    finally:
        app.dependency_overrides.pop(analytics_mod.get_analytics_engine, None)


async def _single_holding_book(test_db) -> None:
    """A one-holding book: the case that measures HHI == 1.0 exactly."""
    await test_db.execute(delete(PortfolioPosition))
    await test_db.commit()
    test_db.add(PortfolioPosition(
        ticker="ONLY.NS", weight=1.0, quantity=10.0, buy_price=100.0,
        last_price=100.0, market_value=1000.0,
        added_on=datetime(2024, 1, 2),
    ))
    await test_db.commit()


@pytest.mark.asyncio
async def test_both_engine_shapes_carry_the_key() -> None:
    """The invariant that makes the route's subscript safe.

    This is what `0.0` was leaning on without saying so: a total function over
    the engine's return type. Pinned here against the engine's own shapes, so
    dropping the default on the route cannot silently become a `KeyError` on a
    shape nobody checked.
    """
    shapes = {name: await _engine_shape(name) for name in ENGINE_CONTRACT_SHAPES}

    for name, result in shapes.items():
        assert "herfindahl_index" in result, (
            f"the engine's {name!r} shape no longer publishes the index; the "
            "route cannot read a key the engine has stopped writing"
        )
    # The two shapes must not agree on the value, or the refusal is not a
    # refusal - it is a second measurement of the same thing.
    assert shapes["measured"]["herfindahl_index"] == 1.0
    assert shapes["empty"]["herfindahl_index"] is None
    assert set(ENGINE_CONTRACT_SHAPES) == {"measured", "empty"}


@pytest.mark.asyncio
async def test_every_engine_shape_carries_every_key_the_route_reads() -> None:
    """The full key set, on every branch that can reach the route's projection.

    `test_both_engine_shapes_carry_the_key` above pins ONE key on the two
    shapes the author had in mind. That was not enough: a route reading nine
    keys by subscript needs all nine on every shape, and the engine has more
    ways into `_empty_concentration` than the obvious empty dict -- it filters
    to finite strictly-positive weights before normalizing, so an all-zero
    book, a negative weight and a non-finite weight all land on the refusal
    shape too, by three different lines.

    Those branches are enumerated here rather than reasoned about, because the
    failure they caused was silent: three test suites bound hand-rolled
    stand-ins carrying 2-3 of these keys, and the route refused them with a
    logged 500 instead of publishing the numbers they had fabricated.
    """
    engine = AnalyticsEngine()
    books = {
        "single_holding": {"ONLY.NS": 1.0},
        "multi_holding": {"A.NS": 0.4, "B.NS": 0.35, "C.NS": 0.25},
        "ten_or_more": {f"T{i}.NS": 0.1 for i in range(10)},
        "empty": {},
        "all_zero": {"A.NS": 0.0, "B.NS": 0.0},
        "negative_and_positive": {"A.NS": -1.0, "B.NS": 2.0},
        "non_finite": {"A.NS": float("nan"), "B.NS": float("inf")},
    }

    shapes = {
        name: await engine.concentration_analysis(weights)
        for name, weights in books.items()
    }

    for name, result in shapes.items():
        missing = [
            key for key in ROUTE_SUBSCRIPTED_CONCENTRATION_KEYS
            if key not in result
        ]
        assert not missing, (
            f"the {name!r} book reaches the route's projection without {missing}; "
            "the route subscripts those keys, so a missing one is a KeyError "
            "turned into an HTTP 500 rather than a published measurement"
        )

    # Three different lines reach the refusal shape, so the three must not be
    # able to drift apart: every book the engine cannot measure must publish
    # the same refusal, or `n_holdings` stops being a truthful reason for the
    # withheld index.
    #
    # `negative_and_positive` is deliberately NOT in this group. A negative
    # weight is filtered out as an inactive holding rather than refusing the
    # book, so it measures the single remaining holding -- a MEASURED shape
    # arriving at the same route projection. Both paths carry the full key set,
    # which is why all seven books are asserted above and only these three are
    # grouped here.
    refusals = ("empty", "all_zero", "non_finite")
    assert len({shapes[name]["n_holdings"] for name in refusals}) == 1
    assert all(shapes[name]["error"] for name in refusals)


@pytest.mark.asyncio
async def test_a_measured_book_still_publishes_one_point_zero(async_client, test_db) -> None:
    """THE MEASURED ARM. The removed default must not have moved this.

    A one-holding book is the case the fabricated 0.0 was most wrong about: the
    true value is 1.0, the most concentrated book there is.
    """
    await _single_holding_book(test_db)

    response = await async_client.get("/api/v1/analytics/concentration")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["herfindahl_index"] == 1.0, (
        f"a one-holding book measures exactly 1.0, got {data['herfindahl_index']!r}"
    )
    assert data["n_holdings"] == 1
    assert data["by_weight"] == {"ONLY.NS": 1.0}


@pytest.mark.asyncio
async def test_a_withheld_index_reaches_the_route_as_null_not_zero(async_client, test_db) -> None:
    """THE WITHHELD ARM, through the measured path this line actually guards.

    No existing test covered this: `test_concentration_empty_hhi_absent.py`
    empties the book, which takes the route's OWN `if not weights:` early return
    and never reaches the projection. Here the book is non-empty, so the route
    does call the engine, and the engine withholds - which is the one input that
    made `.get(key, 0.0)` a fabrication rather than a dead branch.

    Asserted with `is None`, not a comparison, so a reintroduced 0.0 fails.
    """
    await _single_holding_book(test_db)
    withheld = AnalyticsEngine()._empty_concentration()
    # Asserted over the imported list rather than the one key this test was
    # written around. A partial update here would have left eight statistics
    # forwarding a fabricated number through the very projection that was
    # corrected to forward a refusal.
    for key in WITHHELD_ON_AN_EMPTY_BOOK:
        assert key in withheld, f"{key} is missing from the engine's refusal shape"
        assert withheld[key] is None, (
            f"the engine's refusal moved: it publishes {withheld[key]!r} for "
            f"{key}; this test is checking the route's read of a shape that no "
            "longer withholds"
        )

    async with _engine_returning(withheld):
        response = await async_client.get("/api/v1/analytics/concentration")

    assert response.status_code == 200, response.text
    data = response.json()
    for key in WITHHELD_ON_AN_EMPTY_BOOK:
        assert key in data, (
            f"{key} is missing from the payload; a missing key reads as an "
            "unrecorded measurement, so the field must be present and null"
        )
        assert data[key] is None, (
            f"the route published {data[key]!r} for {key} on a book whose "
            "concentration was never measured. HHI = sum(w_i^2) >= 1/n > 0 for "
            "every non-empty book, and no book produces any of these values, so "
            "a number here is a stand-in, not a reading"
        )
    # A populated reason beside the absence, so a reader learns WHY without
    # having to re-derive it. Both are the route's own disclosure.
    assert data["n_holdings"] == 0, "the withholding reason: no holding was measured"
    assert data["data_status"] == "unavailable", "and the route says so"
    assert data["universe_coverage"]["status"] == "unavailable"
    assert data["by_weight"] == {}


@pytest.mark.asyncio
async def test_a_missing_index_is_refused_rather_than_reported_as_zero(async_client, test_db) -> None:
    """The regression pin: a broken engine contract must not publish 0.0.

    This is the case the removed default converted into a fabricated zero, and
    the only one that can distinguish the fix from a no-op - every other test
    here passes identically before and after it. Simulating the break is
    therefore the point, not a contrivance: it is the future edit that the
    silent `0.0` would have papered over.

    Refusing beats inventing. The route's own `except Exception` turns the
    `KeyError` into a logged 500, which is observable, where a 200 carrying
    `herfindahl_index: 0.0` would assert the safest book in the product.
    """
    await _single_holding_book(test_db)
    broken = AnalyticsEngine()._empty_concentration()
    del broken["herfindahl_index"]

    async with _engine_returning(broken):
        response = await async_client.get("/api/v1/analytics/concentration")

    assert response.status_code != 200, (
        "the route answered 200 for an engine result with no Herfindahl index. "
        "If the route must serve a partial payload, it must publish the field "
        "as null - never as 0.0, which no book can measure."
    )
    if response.status_code == 200:
        assert response.json()["herfindahl_index"] is None