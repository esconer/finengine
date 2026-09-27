"""The dashboard component map must not republish a section it points at.

The default export publishes eight of the dashboard's eleven components as their
own top-level sections, and the component map used to inline all eight payloads
a second time -- ~28% of a 998 KB artifact, byte-for-byte. The map is a
documented shape a dashboard-shaped consumer depends on, so it stays; the
duplicated bytes go, replaced by a pointer into this same document.

Two things are proved here, and the second is the one that matters:

1. every pointer resolves, and resolves to exactly the payload the component
   used to inline (checked by building the same export twice, once scoped so
   the twins are absent and every component must therefore stay inline);
2. the two paths CANNOT diverge. Not "they agree today" -- the component's
   metadata is read out of the twin at publish time, so there is one source for
   those keys. `aggregates_not_produced` is the case that proves the point: the
   dashboard's copy of the portfolio section shipped without it, so a consumer
   reading the portfolio through the dashboard saw a section that looked
   complete with an empty omissions ledger.
"""
from __future__ import annotations

import contextlib
import copy
import json
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.debugging import context_audit as ca
from app.services.ai_context_service import (
    COMPONENT_REFERENCE_METADATA,
    ContextOptions,
    PortfolioContextService,
    _reference_dashboard_components,
)

#: The components the default export also publishes as top-level sections.
REFERENCED_COMPONENTS = (
    "concentration",
    "factor_exposure",
    "forecast_risk",
    "liquidity",
    "portfolio",
    "realized_risk",
    "regime",
    "risk_contribution",
)

#: The components with no standalone section. They have no twin, so they must
#: keep their payload -- a pointer to a section this export never published
#: would be worse than a duplicate.
INLINE_ONLY_COMPONENTS = ("performance_history", "risk_score", "summary")

POINTER_KEYS = {"data_inline", "data_ref", "data_ref_status"}

#: Keys a second collection legitimately moves. The audit keeps the same list
#: (`ca.VOLATILE_PATTERNS`): a collection clock and a per-collection identity are
#: not a published value, so comparing them across two builds proves nothing.
VOLATILE_KEYS = {"export_id", "generated_at", "completed_at", "snapshot_consistency"}

SCOPE_WITH_TWINS = ("portfolio", "dashboard") + tuple(
    name for name in REFERENCED_COMPONENTS if name != "portfolio"
)


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
def _service() -> PortfolioContextService:
    return PortfolioContextService(
        db=Mock(),
        data_service=Mock(),
        analytics_engine=Mock(),
        benchmark_service=Mock(),
        cache_service=Mock(),
    )


def _endpoint_payloads() -> dict[str, Any]:
    return {
        "portfolio": {
            "positions": [{"ticker": "AAPL", "market_value": 1000.0}],
            "total_value": 1000.0,
            "currency": "INR",
        },
        "summary": {"portfolio_value": 1000.0, "currency": "INR"},
        "performance_history": [
            {"date": "2025-01-01", "portfolio_value": 1000.0, "return": 0.0}
        ],
        "realized_risk": {
            "portfolio": {"annual_return": 0.1},
            "positions": {"AAPL": {}},
            "estimate_uncertainty": {"standard_error": 0.02},
            "history_coverage": {
                "covered_days_scope": "holding_window_aligned_return_rows",
                "covered_days": 39,
                "intersection_start": "2026-08-03",
            },
        },
        "forecast_risk": {
            "portfolio": {"volatility_forecast": 0.1},
            "positions": {"AAPL": {}},
        },
        "factor_exposure": {
            "portfolio": {"market": 1.0, "alpha_std_error": 0.03},
            "positions": {"AAPL": {}},
        },
        "concentration": {"by_weight": {"AAPL": 1.0}},
        "liquidity": {"by_position": {"AAPL": {}}},
        "risk_score": {"overall_score": 50, "risk_level": "Medium"},
        "regime": {
            "current_regime": "normal",
            "history_coverage": {
                "covered_days_scope": "portfolio_return_observations",
                "covered_days": 39,
                "intersection_start": "2026-08-03",
            },
        },
        "risk_contribution": {
            "positions": {
                "volatility": {"AAPL": {}},
                "cvar_tail": {"AAPL": {}},
            }
        },
    }


def _patches(payloads: dict[str, Any]):
    return [
        patch(
            "app.services.ai_context_service.portfolio_api.get_portfolio",
            new=AsyncMock(return_value=payloads["portfolio"]),
        ),
        patch(
            "app.services.ai_context_service.data_api.get_api_config",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "app.services.ai_context_service.analytics_api.get_analytics_summary",
            new=AsyncMock(return_value=payloads["summary"]),
        ),
        patch(
            "app.services.ai_context_service.analytics_api.get_performance_history",
            new=AsyncMock(return_value=payloads["performance_history"]),
        ),
        patch(
            "app.services.ai_context_service.analytics_api.get_realized_risk",
            new=AsyncMock(return_value=payloads["realized_risk"]),
        ),
        patch(
            "app.services.ai_context_service.analytics_api.get_forecast_risk",
            new=AsyncMock(return_value=payloads["forecast_risk"]),
        ),
        patch(
            "app.services.ai_context_service.analytics_api.get_factor_exposure",
            new=AsyncMock(return_value=payloads["factor_exposure"]),
        ),
        patch(
            "app.services.ai_context_service.analytics_api.get_concentration_metrics",
            new=AsyncMock(return_value=payloads["concentration"]),
        ),
        patch(
            "app.services.ai_context_service.analytics_api.get_liquidity_metrics",
            new=AsyncMock(return_value=payloads["liquidity"]),
        ),
        patch(
            "app.services.ai_context_service.analytics_api.get_risk_score",
            new=AsyncMock(return_value=payloads["risk_score"]),
        ),
        patch(
            "app.services.ai_context_service.analytics_api.get_regime",
            new=AsyncMock(return_value=payloads["regime"]),
        ),
        patch(
            "app.services.ai_context_service.analytics_api.get_risk_contribution",
            new=AsyncMock(return_value=payloads["risk_contribution"]),
        ),
    ]


async def _build(include: tuple[str, ...]) -> dict[str, Any]:
    payloads = _endpoint_payloads()
    with contextlib.ExitStack() as stack:
        for entered in _patches(payloads):
            stack.enter_context(entered)
        return await _service().build(ContextOptions(include=include))


@pytest.fixture
async def referenced_export() -> dict[str, Any]:
    """A full-scope export: every dashboard component that can be, is."""
    return await _build(SCOPE_WITH_TWINS)


@pytest.fixture
async def inline_export() -> dict[str, Any]:
    """Dashboard only. No twins exist, so every component must stay inline."""
    return await _build(("dashboard",))


def _components(export: dict[str, Any]) -> dict[str, Any]:
    return export["sections"]["dashboard"]["data"]["components"]


def _resolve(document: Any, path: str) -> Any:
    node = document
    for token in path.split("."):
        node = node[token]
    return node


def _settled(section: dict[str, Any]) -> dict[str, Any]:
    """A section with the collection clock and identity removed."""
    return {k: v for k, v in section.items() if k not in VOLATILE_KEYS}


# --------------------------------------------------------------------------
# 1. the pointer replaces the duplicate
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_referenced_component_publishes_a_pointer_and_no_second_copy(
    referenced_export,
):
    components = _components(referenced_export)
    assert set(components) == set(REFERENCED_COMPONENTS) | set(INLINE_ONLY_COMPONENTS)

    for name in REFERENCED_COMPONENTS:
        component = components[name]
        assert component["data_inline"] is False, name
        assert component["data_ref"] == f"sections.{name}", name
        assert component["data_ref_status"] == "referenced", name
        # The heavy payload is gone from this path, and only from this path.
        assert "data" not in component, name


@pytest.mark.asyncio
async def test_a_component_with_no_twin_keeps_its_payload_and_points_at_nothing(
    referenced_export,
):
    components = _components(referenced_export)
    for name in INLINE_ONLY_COMPONENTS:
        component = components[name]
        assert component["data_inline"] is True, name
        assert "data" in component, name
        assert component["data"] is not None, name
        # Never fabricate: a pointer to a section this export did not publish
        # would be a worse defect than the duplicate it replaced.
        assert "data_ref" not in component, name
        assert name not in referenced_export["sections"], name


@pytest.mark.asyncio
async def test_every_data_ref_resolves_to_a_section_that_is_actually_published(
    referenced_export,
):
    for name, component in _components(referenced_export).items():
        if component["data_inline"]:
            continue
        target = _resolve(referenced_export, component["data_ref"])
        assert isinstance(target, dict), name
        assert target["key"] == name
        assert "data" in target, name


# --------------------------------------------------------------------------
# 2. the pointer resolves to what the component used to inline
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_pointer_resolves_to_exactly_what_the_component_used_to_inline(
    referenced_export, inline_export
):
    """The strong form: a second export with no twins, so every payload inlines.

    `inline_export` is the same document built with `include=dashboard`, where
    none of the eight twins exists and every component is therefore forced to
    carry its own payload. That is what the referenced component used to publish.
    """
    referenced = _components(referenced_export)
    inlined = _components(inline_export)
    assert set(referenced) == set(inlined)

    identical = []
    for name in REFERENCED_COMPONENTS:
        component, before = referenced[name], inlined[name]
        assert component["data_inline"] is False, name
        assert before["data_inline"] is True, name
        target = _resolve(referenced_export, component["data_ref"])
        if name == "portfolio":
            # The one component that did NOT match, and the reason this change
            # exists. The pointer resolves to the twin's payload, which is the
            # inlined payload plus the disclosure the inlined copy was missing --
            # and nothing else. Anything more would mean the pointer and the
            # duplicate had diverged in some other way too.
            extra = set(target["data"]) - set(before["data"])
            assert extra == {"aggregates_not_produced"}, extra
            assert {
                k: v for k, v in target["data"].items() if k != "aggregates_not_produced"
            } == before["data"], name
            continue
        assert target["data"] == before["data"], name
        identical.append(name)

    # Seven of the eight were byte-identical duplicates; the eighth was the
    # divergent one. Pinning the count keeps a future ninth divergence loud.
    assert sorted(identical) == [
        "concentration",
        "factor_exposure",
        "forecast_risk",
        "liquidity",
        "realized_risk",
        "regime",
        "risk_contribution",
    ]


# --------------------------------------------------------------------------
# 3. the two paths cannot diverge
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_component_diverges_from_its_twin(referenced_export):
    """Generic, so a divergence in ANY section is caught -- not just portfolio.

    Two halves. Every metadata key a referenced component publishes must exist on
    its twin and carry the identical value. And every non-pointer key it
    publishes must be one the twin also publishes, so a key one path grows and
    the other does not is a failure here rather than a silent divergence.
    """
    for name, component in _components(referenced_export).items():
        if component["data_inline"]:
            continue
        twin = referenced_export["sections"][name]
        published = set(component) - POINTER_KEYS

        for key in sorted(published):
            assert key in twin, f"{name}.{key} is published on the component only"
            assert component[key] == twin[key], f"{name}.{key} disagrees with its twin"

        # The specific keys the brief named, asserted one by one so a failure
        # says which disclosure drifted.
        for key in ("status", "as_of", "warnings", "omitted_fields"):
            if key in twin:
                assert component.get(key) == twin[key], f"{name}.{key}"

        # Nothing beyond the documented metadata and the pointer keys.
        assert published <= set(COMPONENT_REFERENCE_METADATA), (
            f"{name} publishes {sorted(published - set(COMPONENT_REFERENCE_METADATA))}, "
            "which is neither a pointer key nor copied from the twin"
        )


@pytest.mark.asyncio
async def test_the_portfolio_disclosure_is_reachable_through_the_dashboard(referenced_export):
    """The regression that motivated this: `aggregates_not_produced` (DI-5).

    The top-level portfolio section names the book-level aggregates the endpoint
    never produced. The dashboard's copy of the same section shipped without
    them, so a consumer reading the portfolio through the dashboard saw a section
    that looked complete with an empty omissions ledger.
    """
    component = _components(referenced_export)["portfolio"]
    twin = referenced_export["sections"]["portfolio"]

    disclosure = twin["data"]["aggregates_not_produced"]
    assert disclosure["fields"], "the twin carries no fields, so this proves nothing"
    assert disclosure["reason"]

    # Reachable: the pointer lands on the section that carries the disclosure.
    target = _resolve(referenced_export, component["data_ref"])
    assert target["data"]["aggregates_not_produced"] == disclosure
    # And named: the component's own omissions ledger agrees with the twin's.
    assert component["omitted_fields"] == twin["omitted_fields"]
    assert set(disclosure["fields"]) <= set(component["omitted_fields"])


@pytest.mark.asyncio
async def test_divergence_is_impossible_by_construction_not_by_convention(
    referenced_export,
):
    """Change the twin and the component follows, because it is read FROM it.

    A hand-maintained copy of these values would satisfy
    `test_no_component_diverges_from_its_twin` today and drift the first time
    somebody edited a section. Here the metadata is re-projected after the twin
    is altered in place, so agreement is a property of the code path rather than
    a coincidence the test happens to observe.
    """
    document = copy.deepcopy(referenced_export)
    twin = document["sections"]["realized_risk"]
    twin["status"] = "unavailable"
    twin["as_of"] = "1999-01-01"
    twin["warnings"] = ["a warning only the twin knows"]
    twin["omitted_fields"] = ["positions.AAPL.series"]

    # Strip the component back to its pre-projection state, then re-project.
    component = document["sections"]["dashboard"]["data"]["components"]["realized_risk"]
    component.clear()
    component["status"] = "partial"
    component["data"] = {"stale": True}

    _reference_dashboard_components(document["sections"])

    component = document["sections"]["dashboard"]["data"]["components"]["realized_risk"]
    assert component["data_inline"] is False
    assert component["data_ref"] == "sections.realized_risk"
    assert "data" not in component
    assert component["status"] == "unavailable"
    assert component["as_of"] == "1999-01-01"
    assert component["warnings"] == ["a warning only the twin knows"]
    assert component["omitted_fields"] == ["positions.AAPL.series"]


# --------------------------------------------------------------------------
# 4. no published value moved
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_dashboards_own_derivation_is_identical_with_and_without_the_pointers(
    referenced_export, monkeypatch
):
    """Every dashboard key except the component payloads must be byte-identical.

    The dereference runs last, after the dashboard's status, currency, freshness,
    coverage, omissions and warnings were all derived from the full payloads.
    Currency inference and the degradation-marker warnings both read component
    payloads, so this is the assertion that dropping the duplicates moved
    nothing.
    """
    import app.services.ai_context_service as service_module

    with patch.object(service_module, "_reference_dashboard_components"):
        without = await _build(SCOPE_WITH_TWINS)

    after = referenced_export["sections"]["dashboard"]
    before = without["sections"]["dashboard"]
    for key in set(before) | set(after):
        if key == "data" or key in VOLATILE_KEYS:
            continue
        assert before.get(key) == after.get(key), f"sections.dashboard.{key} moved"

    for key in ("status", "currency", "as_of", "as_of_semantics", "coverage",
                "warnings", "omitted_fields", "inputs", "detail"):
        assert before.get(key) == after.get(key), key

    # The inline components are untouched, payload included.
    for name in INLINE_ONLY_COMPONENTS:
        assert before["data"]["components"][name]["data"] == (
            after["data"]["components"][name]["data"]
        ), name

    # And the referenced payloads were genuinely there to be dropped.
    for name in REFERENCED_COMPONENTS:
        assert "data" in before["data"]["components"][name], name


@pytest.mark.asyncio
async def test_the_whole_envelope_except_the_component_payloads_is_unchanged(
    referenced_export, monkeypatch
):
    import app.services.ai_context_service as service_module

    with patch.object(service_module, "_reference_dashboard_components"):
        without = await _build(SCOPE_WITH_TWINS)

    # Every non-dashboard section is bit-identical, including portfolio and the
    # realized-risk uncertainty blocks the dashboard used to republish.
    for name, section in without["sections"].items():
        if name == "dashboard":
            continue
        assert _settled(referenced_export["sections"][name]) == _settled(section), name


# --------------------------------------------------------------------------
# 5. the pointer is documented where a consumer meets it
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_reference_convention_is_published_inside_the_document(
    referenced_export,
):
    data = referenced_export["sections"]["dashboard"]["data"]
    policy = data["component_reference_policy"]
    assert "data_ref" in policy
    assert "data_inline" in policy
    assert "data_ref_status" in policy
    # A pointer convention that is not explained next to the pointers is a
    # convention. The explanation travels with the document.
    assert data["components"]["realized_risk"]["data_ref"] in policy or (
        "THIS document" in policy
    )

    # It also reaches the wire: `data` is typed `Any` on the section, so
    # FastAPI's re-serialisation against AIContextResponse keeps it. That is why
    # the policy lives here and not as a new top-level envelope key, which would
    # need app/models/schemas.py and would be dropped from the wire without it.
    from app.api.ai_context import AIContextExport

    body = AIContextExport.model_validate(referenced_export).model_dump(mode="json")
    assert "component_reference_policy" in body["sections"]["dashboard"]["data"]


@pytest.mark.asyncio
async def test_the_pointer_flag_never_reuses_the_audited_data_status_vocabulary(
    referenced_export,
):
    """`data_status` is a declared contract key with its own rule (ENV-007).

    Naming the pointer flag `data_status` published the word "referenced" under
    a key whose vocabulary is `available` / `partial` / `unavailable`, and the
    real audit flagged all eight of them. The flag is `data_ref_status`.
    """
    for name, component in _components(referenced_export).items():
        if component["data_inline"]:
            continue
        assert "data_status" not in component, name
        assert component["data_ref_status"] == "referenced"

    document = copy.deepcopy(referenced_export)
    _reference_dashboard_components(document["sections"])
    findings, errors = ca.run_rules(
        ca.Export(doc=document, raw=json.dumps(document))
    )
    assert not errors
    env_007 = [f for f in findings if f.rule_id == "ENV-007"]
    assert env_007 == [], [f.path for f in env_007]


# --------------------------------------------------------------------------
# 6. de-duplication did not blind a cross-section rule
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_xs_001_still_sees_a_holding_window_contradiction_at_the_canonical_path(
    referenced_export,
):
    """The rule the de-duplication could most plausibly have blinded.

    XS-001 compares every block claiming a holding-window scope. The dashboard
    used to contribute a second copy of several of those blocks, so half its
    evidence came from the component path. Move the contradiction into the
    CANONICAL block -- the only copy that exists after the change -- and require
    the rule to still fire. If the deleted copies had been the evidence, this
    would have gone green.
    """
    import app.services.ai_context_service as service_module

    assert ca.HOLDING_WINDOW_SCOPES  # the rule's own join vocabulary
    agreeing = ca.run_rules(ca.Export(doc=referenced_export, raw=json.dumps(referenced_export)))[0]
    assert not [f for f in agreeing if f.rule_id == "XS-001"], "fixture already disagrees"

    with patch.object(service_module, "_reference_dashboard_components"):
        duplicated = await _build(SCOPE_WITH_TWINS)

    for label, document in (("duplicated", duplicated), ("referenced", referenced_export)):
        # Publish the contradiction once, on realized_risk, the section the
        # dashboard used to republish -- and which the regime sibling contradicts.
        d = copy.deepcopy(document)
        d["sections"]["realized_risk"]["data"]["history_coverage"]["intersection_start"] = (
            "2020-01-01"
        )
        findings, errors = ca.run_rules(ca.Export(doc=d, raw=json.dumps(d)))
        assert not errors
        fired = [f for f in findings if f.rule_id == "XS-001"]
        assert fired, f"XS-001 went green on the {label} document"
        assert any("realized_risk" in f.message for f in fired), [f.message for f in fired]
        # Named at the canonical path, whichever document it is.
        assert "sections.realized_risk" in fired[0].message, fired[0].message


@pytest.mark.asyncio
async def test_de_duplication_deletes_no_evidence_path(referenced_export, monkeypatch):
    """Every path the pointers remove still exists at the canonical path.

    This is the general form of the XS-001 check: not "the rule still fires" but
    "no unique evidence left the document". It is the assertion that catches a
    future change that dereferences a component whose twin is missing.
    """
    import app.services.ai_context_service as service_module

    with patch.object(service_module, "_reference_dashboard_components"):
        before = await _build(SCOPE_WITH_TWINS)
    after = referenced_export

    def paths(export: dict[str, Any]) -> set[str]:
        return {p for p, _ in ca.Export(doc=export, raw=json.dumps(export)).nodes}

    before_paths, after_paths = paths(before), paths(after)
    removed = before_paths - after_paths
    assert removed, "nothing was removed; the fixture is not exercising the change"

    for path in sorted(removed):
        assert path.startswith("sections.dashboard.data.components."), path
        rest = path[len("sections.dashboard.data.components."):]
        name, _, tail = rest.partition(".")
        assert name in REFERENCED_COMPONENTS, path
        canonical = f"sections.{name}" + (f".{tail}" if tail else "")
        assert canonical in after_paths, f"{path} was deleted with no twin at {canonical}"
