"""AD-16, envelope half: the measured evidence must reach the HTTP wire.

`snapshot_consistency` at the envelope stayed exactly as it was -- a
collection-mode `Literal["best_effort", "frozen"]` -- and the measurement was
added beside it as `snapshot_consistency_measured`. Two axes, two keys:
overwriting the Literal with a dict would have broken the schema, the
TypeScript union and the Markdown renderer to save a sentence, and would have
discarded a real distinction (a `frozen` export whose clocks still disagree is
not the same finding as a `best_effort` one that happens to agree).

The failure this file exists to prevent is quieter than a crash. FastAPI
re-serialises a route's response against the DECLARED `response_model`, so a
key the exporter only adds at runtime is dropped from the HTTP wire while the
in-process exporter still sees it -- which would leave the audited path and the
wire silently disagreeing, exactly as `CointScannerResponse` documents at
`app/models/schemas.py:485`. So the declaration itself is asserted, not just
the value.
"""

from __future__ import annotations

import pytest

from app.api.ai_context import AIContextExport
from app.models.schemas import AIContextResponse
from app.services.ai_context_service import (
    _snapshot_consistency_measured,
    render_markdown,
)

MEASURED = "snapshot_consistency_measured"


def _block(**overrides):
    block = {
        "status": "multiple_instants",
        "distinct_price_instants": 3,
        "distinct_delivered_bar_dates": 2,
        "mark_instant_spread_seconds": 3,
        "delivered_bar_spread_calendar_days": 3,
        "per_position_price_as_of": {"AAA.NS": "2026-09-25", "BBB.NS": "2026-09-22"},
        "what_this_invalidates": ["the book is not a single simultaneous snapshot"],
    }
    block.update(overrides)
    return block


def test_measured_is_derived_from_the_portfolio_block():
    sections = {"portfolio": {"data": {"snapshot_consistency": _block()}}}
    out = _snapshot_consistency_measured(sections, None)
    assert out["status"] == "multiple_instants"
    assert out["distinct_price_instants"] == 3
    assert out["distinct_delivered_bar_dates"] == 2
    assert out["delivered_bar_spread_calendar_days"] == 3
    # Compact by design: the per-ticker map and the invalidation prose stay
    # where they were measured, and the envelope points at them.
    assert "per_position_price_as_of" not in out
    assert out["per_position_price_as_of_at"].startswith("sections.portfolio")


def test_the_collection_mode_key_is_untouched():
    """The documented Literal keeps its name, its type and its value."""
    fields = AIContextResponse.model_fields
    assert "snapshot_consistency" in fields
    literal = str(fields["snapshot_consistency"].annotation)
    assert "best_effort" in literal and "frozen" in literal
    assert "Dict" not in literal, "the collection mode must stay a mode, not a block"


def test_measured_reaches_the_wire_not_just_the_exporter():
    """Declared on the response model, so FastAPI cannot drop it.

    This is the regression test for the schemas.py:485 lesson. An undeclared
    key survives `model_dump()` in-process and vanishes on the HTTP route.
    """
    assert MEASURED in AIContextResponse.model_fields
    assert MEASURED in AIContextExport.model_fields
    payload = AIContextExport(
        schema_version="v1",
        export_id="portfolio-abc123",
        generated_at="2026-09-27T00:00:00Z",
        completed_at="2026-09-27T00:00:01Z",
        snapshot_consistency="best_effort",
        snapshot_consistency_measured=_snapshot_consistency_measured(
            {"portfolio": {"data": {"snapshot_consistency": _block()}}}, None
        ),
        base_currency="INR",
        currency_policy="p",
        detail="summary",
        scope=["portfolio"],
        sections={},
    )
    dumped = payload.model_dump()
    assert MEASURED in dumped, "the key was dropped in serialisation"
    assert dumped[MEASURED]["status"] == "multiple_instants"


def test_absent_block_is_declared_unmeasured_never_invented():
    """No block means no agreement is claimed -- and the reason says why."""
    out = _snapshot_consistency_measured({"portfolio": {"data": {}}}, None)
    assert out["status"] == "unmeasured"
    assert out["reason"]
    assert out["distinct_price_instants"] is None
    out2 = _snapshot_consistency_measured({}, None)
    assert out2["status"] == "unmeasured"


def test_a_non_mapping_block_is_not_mistaken_for_a_measurement():
    """The pre-fix payload carried the bare string `"best_effort"`.

    That is a claim, not a measurement, so it must not be promoted into one.
    """
    sections = {"portfolio": {"data": {"snapshot_consistency": "best_effort"}}}
    out = _snapshot_consistency_measured(sections, None)
    assert out["status"] == "unmeasured"


def test_markdown_shows_the_measurement_and_where_the_detail_lives():
    payload = {
        "schema_version": "v1",
        "generated_at": "2026-09-27T00:00:00Z",
        "completed_at": "2026-09-27T00:00:01Z",
        "snapshot_consistency": "best_effort",
        "snapshot_consistency_measured": _snapshot_consistency_measured(
            {"portfolio": {"data": {"snapshot_consistency": _block()}}}, None
        ),
        "base_currency": "INR",
        "currency_policy": "p",
        "detail": "summary",
        "scope": ["portfolio"],
        "sections": {},
    }
    md = render_markdown(payload)
    assert "Snapshot consistency: `best_effort`" in md
    assert "Price clocks measured" in md
    assert "multiple_instants" in md
    # The counts must be visible, not just the status word -- the whole point
    # of AD-16 was that one adjective carried no numbers.
    assert "3 price instant(s)" in md
    assert "sections.portfolio.data.snapshot_consistency" in md


def test_markdown_survives_a_missing_measurement():
    payload = {
        "snapshot_consistency": "best_effort",
        "base_currency": "INR",
        "currency_policy": "p",
        "detail": "summary",
        "scope": [],
        "sections": {},
    }
    md = render_markdown(payload)
    assert "unmeasured" in md


@pytest.mark.parametrize("block", [None, {}, "best_effort", 7, []])
def test_no_shape_of_unusable_block_can_produce_a_count(block):
    sections = {"portfolio": {"data": {"snapshot_consistency": block}}}
    out = _snapshot_consistency_measured(sections, None)
    assert out["status"] == "unmeasured"
    assert out.get("distinct_price_instants") is None
