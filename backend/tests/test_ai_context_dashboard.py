"""Ticket 02: dashboard freshness, composition and canonical linking.

Covers the dashboard half of the AI export:

* the delivered performance window is published beside the delivered rows and
  a materially short/stale delivery surfaces as ``partial``;
* a legacy bare-array delivery stays usable but is never called complete;
* the page ``as_of`` is the oldest measured component, published with a
  per-component ``component_as_of`` map, never inherited from the portfolio
  quote;
* dashboard summary fields link to canonical sibling results, or stay null with
  a machine-readable ``field_status`` reason;
* the risk score's hardcoded ``change: 0`` is exported as unmeasured, and the
  cached sibling sections are never mutated by the linking step.

All analytics calls use mocked providers; no live market data is required.
"""
from __future__ import annotations

import contextlib
from datetime import date, timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.services.ai_context_service import (
    COMPOSITE_AS_OF_SEMANTICS,
    PERFORMANCE_COVERAGE_FLOOR,
    PERFORMANCE_HISTORY_DAYS,
    RISK_SCORE_UNMEASURED_REASON,
    ContextOptions,
    PortfolioContextService,
    _BuildContext,
    _as_of,
    _normalize_risk_score_change,
    _performance_history_component,
)

TICKER = "AAPL"

# 20 delivered observations inside a 90-day request: the exact shape of the v3
# artifact (2026-08-25..2026-09-22 requested from a 2026-09-25 window end).
DELIVERED_WINDOW = ("2026-08-25", "2026-09-22")


def _rows(count: int = 20, start: str = DELIVERED_WINDOW[0], end: str = DELIVERED_WINDOW[1]):
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    step = (last - first).days / max(1, count - 1)
    return [
        {
            "date": (first + timedelta(days=round(index * step))).isoformat(),
            "portfolio_value": 1000.0 + index,
            "portfolio_value_currency": "INR",
            "return": 0.001,
            "currency": "INR",
        }
        for index in range(count)
    ]


def _truncated_envelope(rows=None, **overrides):
    """The metadata envelope a 90-day request delivers as 20 observations."""
    rows = _rows() if rows is None else rows
    envelope = {
        "data": rows,
        "data_status": "partial",
        "as_of": DELIVERED_WINDOW[1],
        "as_of_semantics": "last_delivered_observation_date",
        "history_coverage": {
            "requested_start": "2026-06-27",
            "requested_end": "2026-09-25",
            "requested_days": 90,
            "delivered_start": DELIVERED_WINDOW[0],
            "delivered_end": DELIVERED_WINDOW[1],
            "observation_count": len(rows),
            "expected_observation_count": 62,
            "first_observation": rows[0]["date"],
            "last_observation": rows[-1]["date"],
            "coverage_ratio": round(len(rows) / 62, 6),
            "truncated": True,
            "stale": True,
            "status": "partial",
        },
        "warnings": ["Price cache only covers part of the requested window"],
    }
    envelope.update(overrides)
    return envelope


def _service() -> PortfolioContextService:
    return PortfolioContextService(
        db=Mock(),
        data_service=Mock(),
        analytics_engine=Mock(),
        benchmark_service=Mock(),
        cache_service=Mock(),
    )


def _context(service: PortfolioContextService, **cached) -> _BuildContext:
    """A build context whose sibling sections are already collected."""
    context = _BuildContext(
        options=ContextOptions(include=("dashboard",)),
        base_currency="INR",
        portfolio={
            "positions": [{"ticker": TICKER, "market_value": 1000.0}],
            "total_value": 1000.0,
            "currency": "INR",
            "last_updated": "2026-09-25T10:00:00+00:00",
        },
        tickers=[TICKER],
        ticker_csv=TICKER,
        total_value=1000.0,
    )
    context.cached_sections.update(cached)
    return context


COMPONENT_SECTIONS = (
    "realized_risk",
    "forecast_risk",
    "factor_exposure",
    "concentration",
    "liquidity",
    "regime",
    "risk_contribution",
)


def _sibling_sections(forecast_volatility=0.174786, liquidity_score=8, statuses=None):
    statuses = statuses or {}
    payloads = {
        "realized_risk": {"latest_observation_date": "2026-09-24", "portfolio": {"annual_return": 0.1}},
        "forecast_risk": {"portfolio": {"volatility_forecast": forecast_volatility}},
        "factor_exposure": {"portfolio": {"market": 1.0}},
        "concentration": {"by_weight": {TICKER: 1.0}},
        "liquidity": {"overall_score": liquidity_score},
        "regime": {"current_regime": "normal"},
        "risk_contribution": {"positions": {"volatility": {TICKER: 0.5}}},
    }
    return {
        key: {
            "key": key,
            "status": statuses.get(key, "available"),
            "data": payloads[key],
            "warnings": [],
        }
        for key in COMPONENT_SECTIONS
    }


@contextlib.contextmanager
def _patched_dashboard_only(summary=None, performance=None, risk_score=None):
    """Patch the three endpoints that have no standalone export section.

    Yields the performance mock so a test can assert the metadata opt-in.
    """
    summary_payload = (
        {"portfolio_value": 1000.0, "forecast_volatility": None, "liquidity_score": None}
        if summary is None
        else summary
    )
    performance_payload = [] if performance is None else performance
    risk_score_payload = (
        {"overall_score": 42, "risk_level": "Medium", "change": 0} if risk_score is None else risk_score
    )
    with patch(
        "app.services.ai_context_service.analytics_api.get_analytics_summary",
        new=AsyncMock(return_value=summary_payload),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_performance_history",
        new=AsyncMock(return_value=performance_payload),
    ) as performance_mock, patch(
        "app.services.ai_context_service.analytics_api.get_risk_score",
        new=AsyncMock(return_value=risk_score_payload),
    ):
        yield {"performance": performance_mock}


# --------------------------------------------------------------------------
# performance freshness
# --------------------------------------------------------------------------
def test_short_delivered_window_is_partial_with_requested_versus_delivered():
    component = _performance_history_component(
        {"status": "available", "data": _truncated_envelope()},
        90,
    )

    coverage = component["history_coverage"]
    assert component["status"] == "partial"
    assert coverage["status"] == "partial"
    assert coverage["requested_days"] == 90
    assert coverage["delivered_start"] == DELIVERED_WINDOW[0]
    assert coverage["delivered_end"] == DELIVERED_WINDOW[1]
    assert coverage["observation_count"] == 20
    assert coverage["expected_observation_count"] == 62
    assert coverage["first_observation"] == DELIVERED_WINDOW[0]
    assert coverage["last_observation"] == DELIVERED_WINDOW[1]
    assert coverage["coverage_ratio"] < PERFORMANCE_COVERAGE_FLOOR
    assert coverage["truncated"] is True
    assert coverage["stale"] is True
    # The rows stay the series: coverage metadata never replaces delivered data.
    assert len(component["data"]) == 20
    # as-of is the last delivered observation, never the request window end.
    assert component["as_of"] == DELIVERED_WINDOW[1]
    assert component["as_of_semantics"] == "last_delivered_observation_date"
    # One deterministic warning naming requested vs delivered, plus the
    # endpoint's own warning, both surfaced on the section.
    assert any("20 of 62 observations" in warning for warning in component["warnings"])
    assert any("90-day window" in warning for warning in component["warnings"])
    assert any("Price cache" in warning for warning in component["warnings"])


def test_complete_delivered_window_stays_available():
    rows = _rows(60, "2026-07-01", "2026-09-22")
    envelope = {
        "data": rows,
        "data_status": "available",
        "as_of": "2026-09-22",
        "as_of_semantics": "last_delivered_observation_date",
        "history_coverage": {
            "requested_days": 90,
            "observation_count": 60,
            "expected_observation_count": 62,
            "delivered_start": "2026-07-01",
            "delivered_end": "2026-09-22",
            "coverage_ratio": round(60 / 62, 6),
            "truncated": False,
            "stale": False,
            "status": "complete",
        },
        "warnings": [],
    }

    component = _performance_history_component({"status": "available", "data": envelope}, 90)

    assert component["status"] == "available"
    assert component["history_coverage"]["status"] == "available"
    assert not any("delivered" in warning.lower() for warning in component.get("warnings", []))


def test_legacy_bare_array_is_usable_but_never_called_complete():
    component = _performance_history_component(
        {"status": "available", "data": _rows()},
        90,
    )

    coverage = component["history_coverage"]
    # Measured counts are published; completeness is not claimed either way.
    assert coverage["status"] == "unknown"
    assert coverage["expected_observation_count"] is None
    assert coverage["coverage_ratio"] is None
    assert coverage["truncated"] is None
    assert coverage["stale"] is None
    assert coverage["observation_count"] == 20
    assert coverage["delivered_start"] == DELIVERED_WINDOW[0]
    assert coverage["delivered_end"] == DELIVERED_WINDOW[1]
    assert len(component["data"]) == 20
    # No measured expectation means no truncation claim, so the payload status
    # is not downgraded and the window is disclosed as unmeasured.
    assert component["status"] == "available"
    assert any("unmeasured" in warning for warning in component["warnings"])


def test_empty_delivery_is_unavailable_not_a_chart_with_no_data():
    component = _performance_history_component({"status": "available", "data": []}, 90)

    assert component["status"] == "unavailable"
    assert component["history_coverage"]["status"] == "unavailable"
    assert component["history_coverage"]["observation_count"] == 0
    assert component["as_of"] is None
    assert component["as_of_semantics"] is None
    assert any("no observations" in warning for warning in component["warnings"])


def test_declared_partial_is_published_even_without_a_ratio():
    envelope = {
        "data": _rows(30),
        "data_status": "partial",
        "as_of": DELIVERED_WINDOW[1],
        "history_coverage": {
            "observation_count": 30,
            "expected_observation_count": None,
            "truncated": True,
            "stale": None,
        },
        "warnings": [],
    }

    component = _performance_history_component({"status": "partial", "data": envelope}, 90)

    assert component["status"] == "partial"
    assert component["history_coverage"]["status"] == "partial"
    assert any("30 of None observations" in warning for warning in component["warnings"])


def test_declared_unavailable_is_never_upgraded_by_delivered_rows():
    envelope = {
        "data": _rows(20),
        "data_status": "unavailable",
        "history_coverage": {"observation_count": 20, "expected_observation_count": 20},
        "warnings": [],
    }

    component = _performance_history_component({"status": "unavailable", "data": envelope}, 90)

    assert component["status"] == "unavailable"


# --------------------------------------------------------------------------
# per-component as-of map
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dashboard_as_of_is_the_oldest_measured_component_not_the_quote():
    service = _service()
    context = _context(service, **_sibling_sections())
    # The portfolio quote is the newest thing on the page; the realized-risk
    # leg is a day older and the delivered series is a day older still.
    context.cached_sections["realized_risk"]["data"]["latest_observation_date"] = "2026-09-24"

    with _patched_dashboard_only(performance=_truncated_envelope()):
        collected = await service._collect_dashboard(context)

    data = collected.data
    component_as_of = data["component_as_of"]

    assert set(component_as_of) == set(data["components"])
    assert component_as_of["performance_history"] == {
        "as_of": DELIVERED_WINDOW[1],
        "as_of_semantics": "last_delivered_observation_date",
    }
    assert component_as_of["realized_risk"]["as_of"] == "2026-09-24"
    assert component_as_of["realized_risk"]["as_of_semantics"] == "latest_observation_date"
    assert component_as_of["portfolio"]["as_of"] == "2026-09-25T10:00:00+00:00"
    assert component_as_of["portfolio"]["as_of_semantics"] == "last_updated"
    # Components that measure nothing publish a null pair, never a guess.
    assert component_as_of["risk_score"] == {"as_of": None, "as_of_semantics": None}

    measured = [entry["as_of"] for entry in component_as_of.values() if entry["as_of"]]
    # A composite is only as fresh as its stalest leg.
    assert _as_of(data) == min(measured) == DELIVERED_WINDOW[1]
    assert data["as_of_semantics"] == COMPOSITE_AS_OF_SEMANTICS
    assert "as_of" not in data


@pytest.mark.asyncio
async def test_section_publishes_the_composite_as_of_policy():
    service = _service()
    with patch(
        "app.services.ai_context_service.portfolio_api.get_portfolio",
        new=AsyncMock(return_value={
            "positions": [{"ticker": TICKER, "market_value": 1000.0}],
            "total_value": 1000.0,
            "currency": "INR",
            "last_updated": "2026-09-25T10:00:00+00:00",
        }),
    ), patch(
        "app.services.ai_context_service.data_api.get_api_config",
        new=AsyncMock(return_value={}),
    ), _patched_dashboard_only(performance=_truncated_envelope()):
        payload = await service.build(ContextOptions(include=("dashboard",)))

    section = payload["sections"]["dashboard"]
    assert section["as_of"] == DELIVERED_WINDOW[1]
    assert section["as_of_semantics"] == COMPOSITE_AS_OF_SEMANTICS
    assert section["inputs"]["performance_days"] == PERFORMANCE_HISTORY_DAYS


@pytest.mark.asyncio
async def test_dashboard_asks_for_the_metadata_envelope():
    service = _service()
    context = _context(service, **_sibling_sections())

    with _patched_dashboard_only(performance=_truncated_envelope()) as calls:
        await service._collect_dashboard(context)

    # get_performance_history must be called with the opt-in metadata flag.
    assert calls["performance"].await_args.kwargs["include_metadata"] is True
    assert calls["performance"].await_args.kwargs["days"] == PERFORMANCE_HISTORY_DAYS


@pytest.mark.asyncio
async def test_legacy_endpoint_signature_falls_back_without_failing_the_page():
    service = _service()
    context = _context(service, **_sibling_sections())

    calls = []

    async def _legacy(**kwargs):
        calls.append(kwargs)
        if "include_metadata" in kwargs:
            raise TypeError(
                "get_performance_history() got an unexpected keyword argument 'include_metadata'"
            )
        return _rows()

    with patch(
        "app.services.ai_context_service.analytics_api.get_analytics_summary",
        new=AsyncMock(return_value={"portfolio_value": 1000.0}),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_performance_history",
        new=_legacy,
    ), patch(
        "app.services.ai_context_service.analytics_api.get_risk_score",
        new=AsyncMock(return_value={"overall_score": 42, "change": 0}),
    ):
        collected = await service._collect_dashboard(context)

    assert [("include_metadata" in kwargs) for kwargs in calls] == [True, False]
    component = collected.data["components"]["performance_history"]
    assert component["history_coverage"]["status"] == "unknown"
    assert collected.status != "unavailable"


# --------------------------------------------------------------------------
# canonical summary linking
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_summary_links_canonical_forecast_and_liquidity_results():
    service = _service()
    siblings = _sibling_sections(forecast_volatility=0.174786, liquidity_score=8)
    context = _context(service, **siblings)

    with _patched_dashboard_only():
        collected = await service._collect_dashboard(context)

    summary = collected.data["components"]["summary"]
    assert summary["data"]["forecast_volatility"] == 0.174786
    assert summary["data"]["liquidity_score"] == 8
    assert summary["field_status"]["forecast_volatility"] == {
        "value": 0.174786,
        "source_section": "forecast_risk",
        "source_status": "available",
        "reason": "linked_from_canonical_sibling",
    }
    assert summary["field_status"]["liquidity_score"]["source_section"] == "liquidity"
    assert summary["field_status"]["liquidity_score"]["value"] == 8


@pytest.mark.asyncio
async def test_summary_linking_does_not_mutate_the_cached_sibling_sections():
    service = _service()
    siblings = _sibling_sections()
    forecast_before = dict(siblings["forecast_risk"]["data"])
    liquidity_before = dict(siblings["liquidity"]["data"])
    context = _context(service, **siblings)

    with _patched_dashboard_only():
        first = await service._collect_dashboard(context)
        second = await service._collect_dashboard(context)

    assert siblings["forecast_risk"]["data"] == forecast_before
    assert siblings["liquidity"]["data"] == liquidity_before
    # A deepcopy keeps repeated assembly deterministic.
    assert first.data["components"]["summary"]["data"] == second.data["components"]["summary"]["data"]


@pytest.mark.asyncio
async def test_partial_sibling_keeps_the_summary_field_null_with_a_reason():
    service = _service()
    siblings = _sibling_sections(statuses={"liquidity": "partial"})
    context = _context(service, **siblings)

    with _patched_dashboard_only():
        collected = await service._collect_dashboard(context)

    summary = collected.data["components"]["summary"]
    # A partial sibling result is never promoted into a summary headline.
    assert summary["data"]["liquidity_score"] is None
    assert summary["data"]["forecast_volatility"] == 0.174786
    assert summary["field_status"]["liquidity_score"] == {
        "value": None,
        "source_section": "liquidity",
        "source_status": "partial",
        "reason": "source_section_partial",
    }
    assert any("liquidity_score is unavailable" in warning for warning in collected.warnings)


@pytest.mark.asyncio
async def test_missing_sibling_value_is_reported_not_fabricated():
    service = _service()
    siblings = _sibling_sections(forecast_volatility=None, liquidity_score=None)
    context = _context(service, **siblings)

    with _patched_dashboard_only():
        collected = await service._collect_dashboard(context)

    summary = collected.data["components"]["summary"]
    assert summary["data"]["forecast_volatility"] is None
    assert summary["data"]["liquidity_score"] is None
    for field in ("forecast_volatility", "liquidity_score"):
        status = summary["field_status"][field]
        assert status["value"] is None
        assert status["reason"] == "source_value_not_published"
        assert status["source_status"] == "available"


@pytest.mark.asyncio
async def test_summary_link_never_overwrites_a_published_value():
    service = _service()
    context = _context(service, **_sibling_sections())

    with _patched_dashboard_only(
        summary={"portfolio_value": 1000.0, "liquidity_score": 3, "forecast_volatility": None},
    ):
        collected = await service._collect_dashboard(context)

    summary = collected.data["components"]["summary"]
    assert summary["data"]["liquidity_score"] == 3
    assert summary["field_status"]["liquidity_score"]["reason"] == "source_value_already_published"


# --------------------------------------------------------------------------
# risk-score delta
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_hardcoded_zero_change_is_exported_as_unmeasured():
    service = _service()
    context = _context(service, **_sibling_sections())

    with _patched_dashboard_only(
        risk_score={"overall_score": 42, "risk_level": "Medium", "change": 0},
    ):
        collected = await service._collect_dashboard(context)

    risk_score = collected.data["components"]["risk_score"]
    assert risk_score["data"]["change"] is None
    assert risk_score["data"]["change_status"] == "unavailable"
    assert risk_score["data"]["change_reason"] == RISK_SCORE_UNMEASURED_REASON
    # The score itself is untouched; only the unmeasured delta is withdrawn.
    assert risk_score["data"]["overall_score"] == 42
    assert any(RISK_SCORE_UNMEASURED_REASON in warning for warning in collected.warnings)


def test_measured_zero_change_with_evidence_is_kept():
    component = {"status": "available", "data": {"overall_score": 42, "change": 0, "prior_score": 42}}

    assert _normalize_risk_score_change(component) == []
    assert component["data"]["change"] == 0


def test_nonzero_change_is_left_alone():
    component = {"status": "available", "data": {"overall_score": 42, "change": -3}}

    assert _normalize_risk_score_change(component) == []
    assert component["data"]["change"] == -3
