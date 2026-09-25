"""Ticket 01: normalized AI export contract regressions.

Covers the shared contract seam used by every exported section:

* conditional ``weight_basis`` (only when an active leg was dropped);
* public ``data_status`` vocabulary, separate from coverage status;
* deterministic ticker ordering driven by the requested universe;
* explicit currency / freshness inference fallbacks;
* no null-error sentinel on successful sections at the API boundary.

All analytics calls use isolated in-memory seams and mocked providers.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pandas as pd
import pytest

from app.api.analytics import (
    ACTIVE_WEIGHT_BASIS,
    DATA_STATUS_VOCABULARY,
    OptimizeRequest,
    _data_status,
    _universe_coverage,
    get_concentration_metrics,
    run_optimization,)
from app.services.ai_context_service import (
    ContextOptions,
    PortfolioContextService,
    _as_of,
    _infer_currency,
    _normalize_data_status,
    _section_coverage,
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _DB:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    async def execute(self, _statement):
        return _Rows(self.rows)

    async def commit(self):
        return None

    async def rollback(self):
        return None

    def add(self, obj):
        self.rows.append(obj)


def _position(ticker, value=1000.0):
    return SimpleNamespace(
        ticker=ticker,
        region="IN" if ticker.endswith((".NS", ".BO")) else "US",
        quantity=1.0,
        last_price=value,
        market_value=value,
        weight=0.5,
        sector="Tech",
        buy_price=value,
        added_on=None,
        currency=None,
        quote_currency=None,
        position_currency=None,
        _quote_currency=None,
    )


def _service():
    return PortfolioContextService(
        db=Mock(),
        data_service=Mock(),
        analytics_engine=Mock(),
        benchmark_service=Mock(),
        cache_service=Mock(),
    )


class _StubFX:
    """Offline FX stub.

    Positions in this file are region="US" unless the ticker ends in .NS/.BO, so
    the allocation loader converts to the base currency. Without this stub the
    test reaches the live vendor and fails whenever USD/INR is unavailable,
    which is a network flake, not a contract regression.
    """

    async def get_exchange_rate(self, source, target):
        return SimpleNamespace(
            rate=80.0, provenance="live", source="stub-fx", is_fallback=False
        )

    async def convert_amount_with_provenance(self, amount, source, target):
        return {
            "amount": amount * 80.0,
            "rate": {
                "rate": 80.0,
                "provenance": "live",
                "source": "stub-fx",
                "is_fallback": False,
            },
        }

    async def convert_amount(self, amount, source, target):
        return amount * 80.0


# --------------------------------------------------------------------------
# weight_basis is conditional
# --------------------------------------------------------------------------
def test_weight_basis_is_absent_when_no_active_leg_was_dropped():
    coverage = _universe_coverage(["A.NS", "B.NS"], ["A.NS", "B.NS"], active=["A.NS", "B.NS"])

    assert "weight_basis" not in coverage
    assert coverage["status"] == "complete"


def test_weight_basis_appears_only_when_an_active_leg_was_dropped():
    coverage = _universe_coverage(["A.NS", "B.NS"], ["A.NS"], active=["A.NS", "B.NS"])

    assert coverage["weight_basis"] == ACTIVE_WEIGHT_BASIS
    assert coverage["missing_tickers"] == ["B.NS"]
    assert coverage["status"] == "partial"
    assert coverage["complete"] is False


def test_weightless_analysis_never_claims_an_allocation_basis():
    # No `active` universe (pair scanning is weightless) and a complete result.
    assert "weight_basis" not in _universe_coverage(["A.NS", "B.NS"], ["A.NS", "B.NS"])
    # A missing zero-value row is not a renormalization event either.
    coverage = _universe_coverage(["A.NS", "EXITED.NS"], ["A.NS"], active=["A.NS"])
    assert "weight_basis" not in coverage
    assert coverage["missing_tickers"] == ["EXITED.NS"]
    assert coverage["status"] == "partial"


def test_section_coverage_never_invents_a_weight_basis():
    # Pairs-like payload: universe inferred from the payload, no weight basis.
    coverage = _section_coverage(
        "pairs",
        {"tickers": ["B.NS", "A.NS"]},
        {"pairs": [{"ticker_a": "A.NS", "ticker_b": "B.NS"}]},
    )

    assert coverage is not None
    assert "weight_basis" not in coverage
    assert coverage["status"] == "complete"
    assert coverage["available_tickers"] == ["B.NS", "A.NS"]  # request order wins


def test_section_coverage_preserves_an_endpoint_declared_weight_basis():
    coverage = _section_coverage(
        "realized_risk",
        {"tickers": ["A.NS", "B.NS"]},
        {
            "portfolio": {"annual_return": 0.1},
            "positions": {"A.NS": {"annual_return": 0.1}},
            "universe_coverage": {
                "requested_tickers": ["A.NS", "B.NS"],
                "available_tickers": ["A.NS"],
                "missing_tickers": ["B.NS"],
                "status": "partial",
                "weight_basis": ACTIVE_WEIGHT_BASIS,
            },
        },
    )

    assert coverage["weight_basis"] == ACTIVE_WEIGHT_BASIS
    assert coverage["missing_tickers"] == ["B.NS"]


# --------------------------------------------------------------------------
# data_status vocabulary stays separate from coverage status
# --------------------------------------------------------------------------
def test_data_status_normalizes_coverage_vocabulary():
    assert _data_status({"status": "complete"}) == "available"
    assert _data_status({"status": "partial"}) == "partial"
    assert _data_status({"status": "unavailable"}) == "unavailable"
    # Market-wide payload with no ticker universe is not a data failure.
    assert _data_status({"status": "unknown"}) == "available"
    assert _data_status(None) == "available"
    assert _data_status({"status": "complete"}, partial=True) == "partial"
    assert _data_status({"status": "unknown"}, unavailable=True) == "unavailable"
    for status in ("complete", "unknown"):
        assert _data_status({"status": status}) in DATA_STATUS_VOCABULARY


def test_declared_data_status_aliases():
    assert _normalize_data_status("complete") == "available"
    assert _normalize_data_status("PARTIAL") == "partial"
    assert _normalize_data_status("unknown") == "unavailable"
    assert _normalize_data_status("bogus") is None
    assert _normalize_data_status(None) is None


@pytest.mark.asyncio
async def test_concentration_publishes_vocabulary_data_status_and_separate_coverage():
    engine = Mock()

    async def concentration_analysis(weights):
        return {
            "largest_position": max(weights.values()),
            "by_weight": dict(weights),
        }

    engine.concentration_analysis = concentration_analysis
    result = await get_concentration_metrics(
        db=_DB([_position("A.NS"), _position("B.NS")]),
        data_service=Mock(),
        analytics_engine=engine,
    )

    assert result["data_status"] == "available"
    assert result["data_status"] in DATA_STATUS_VOCABULARY
    assert result["universe_coverage"]["status"] == "complete"
    assert "weight_basis" not in result["universe_coverage"]


@pytest.mark.asyncio
async def test_optimizer_reports_weight_basis_only_for_a_dropped_leg():
    db = _DB([_position("A"), _position("B")])
    long_frame = pd.DataFrame(
        {"A": [0.001] * 400, "B": [-0.001] * 400},
        index=pd.date_range("2024-01-01", periods=400, freq="D"),
    )
    optimizer_result = {
        "weights": {"A": 0.6, "B": 0.4},
        "expected_annual_return": 0.1,
        "expected_annual_volatility": 0.2,
        "expected_sharpe": 0.5,
        "solver": "hrp",
    }

    with patch(
        "app.api.analytics._build_wide_returns",
        new=AsyncMock(return_value=(long_frame, None, {})),
    ), patch("app.api.analytics.optimize", return_value=optimizer_result), patch(
        "app.api.analytics.get_currency_service", return_value=_StubFX()
    ):
        full = await run_optimization(
            body=OptimizeRequest(strategy="hrp", tickers=["A", "B"]),
            tickers=None,
            db=db,
            data_service=Mock(),
        )

    assert "weight_basis" not in full
    assert full["universe_coverage"]["status"] == "complete"
    assert full["data_status"] == "available"

    dropped = long_frame[["A"]]
    with patch(
        "app.api.analytics._build_wide_returns",
        new=AsyncMock(return_value=(dropped, None, {})),
    ), patch("app.api.analytics.optimize", return_value=optimizer_result), patch(
        "app.api.analytics.get_currency_service", return_value=_StubFX()
    ):
        partial = await run_optimization(
            body=OptimizeRequest(strategy="hrp", tickers=["A", "B"]),
            tickers=None,
            db=db,
            data_service=Mock(),
        )

    assert partial["weight_basis"] == ACTIVE_WEIGHT_BASIS
    assert partial["universe_coverage"]["weight_basis"] == ACTIVE_WEIGHT_BASIS
    assert partial["universe_coverage"]["status"] == "partial"
    assert partial["data_status"] == "partial"
    assert partial["universe_coverage"]["missing_tickers"] == ["B"]


# --------------------------------------------------------------------------
# deterministic ordering
# --------------------------------------------------------------------------
def test_universe_ordering_is_deterministic_and_request_ordered():
    requested = ["B.NS", "A.NS", "C.NS"]
    first = _universe_coverage(requested, {"C.NS", "A.NS", "B.NS", "ZZ.NS"})
    second = _universe_coverage(requested, {"ZZ.NS", "A.NS", "C.NS", "B.NS"})

    assert first == second
    assert first["requested_tickers"] == requested
    assert first["available_tickers"] == ["B.NS", "A.NS", "C.NS", "ZZ.NS"]
    assert first["covered_tickers"] == requested
    assert first["missing_tickers"] == []


def test_section_coverage_orders_an_endpoint_universe_by_request():
    coverage = _section_coverage(
        "concentration",
        {"tickers": ["A.NS", "B.NS", "C.NS"]},
        {
            "by_weight": {"C.NS": 0.4, "A.NS": 0.6},
            "universe_coverage": {
                "requested_tickers": ["C.NS", "A.NS", "B.NS"],
                "available_tickers": ["C.NS", "A.NS"],
                "missing_tickers": ["B.NS"],
                "status": "partial",
            },
        },
    )

    assert coverage["requested_tickers"] == ["A.NS", "B.NS", "C.NS"]
    assert coverage["available_tickers"] == ["A.NS", "C.NS"]
    assert coverage["covered_tickers"] == ["A.NS", "C.NS"]
    assert coverage["missing_tickers"] == ["B.NS"]


def test_section_coverage_infers_counts_for_endpoints_without_coverage_metadata():
    coverage = _section_coverage(
        "concentration",
        {"tickers": ["A.NS", "B.NS"]},
        {"by_weight": {"A.NS": 1.0}},
    )

    assert coverage["requested_count"] == 2
    assert coverage["available_count"] == 1
    assert coverage["coverage_ratio"] == 0.5
    assert coverage["status"] == "partial"


# --------------------------------------------------------------------------
# explicit currency + freshness rules
# --------------------------------------------------------------------------
def test_currency_inference_prefers_the_payload_then_inputs():
    assert _infer_currency({"currency": "usd"}, {"currency": "INR"}) == "USD"
    assert _infer_currency({"data": {"base_currency": "inr"}}, {"currency": "USD"}) == "INR"
    assert _infer_currency({"metrics": {"x": 1}}, {"base_currency": "inr"}) == "INR"
    assert _infer_currency({"metrics": {"x": 1}}, {}) is None


def test_currency_inference_requires_agreeing_components():
    agreeing = {
        "components": {
            "summary": {"data": {"currency": "INR"}},
            "concentration": {"data": {"base_currency": "INR"}},
        }
    }
    mixed = {
        "components": {
            "portfolio": {"data": {"currency": "USD"}},
            "summary": {"data": {"currency": "INR"}},
        }
    }

    assert _infer_currency(agreeing, {}) == "INR"
    assert _infer_currency(mixed, {"currency": "INR"}) is None


def test_as_of_inference_uses_observations_then_oldest_component():
    # A real observation date outranks a cache/update stamp on the same payload.
    assert _as_of({"latest_observation_date": "2025-03-04", "last_updated": "2026-01-01"}) == "2025-03-04"
    # A dated series is as fresh as its newest record.
    assert _as_of([{"date": "2025-01-02"}, {"date": "2025-04-11"}]) == "2025-04-11"
    # A composite is only as fresh as its stalest leg: an unrelated newer quote
    # must not become the section as-of.
    composite = {
        "components": {
            "portfolio": {"data": {"as_of": "2026-09-24"}},
            "performance_history": {"data": [{"date": "2025-06-30"}]},
            "realized_risk": {"data": {"latest_observation_date": "2025-07-15"}},
        }
    }
    assert _as_of(composite) == "2025-06-30"
    # Nothing declared stays unknown; the window end is never substituted.
    assert _as_of({"window": {"start": "2025-01-01", "end": "2025-12-31"}}) is None
    assert _as_of(None) is None


# --------------------------------------------------------------------------
# exporter normalization + error omission
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_export_normalizes_payload_data_status_and_omits_error():
    service = _service()
    with patch(
        "app.services.ai_context_service.portfolio_api.get_portfolio",
        new=AsyncMock(return_value={
            "positions": [{"ticker": "A.NS", "market_value": 1000.0}],
            "total_value": 1000.0,
            "currency": "INR",
        }),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_concentration_metrics",
        new=AsyncMock(return_value={
            "by_weight": {"A.NS": 1.0},
            # Legacy coverage vocabulary leaking into the public data_status.
            "data_status": "complete",
            "universe_coverage": {
                "requested_tickers": ["A.NS"],
                "available_tickers": ["A.NS"],
                "covered_tickers": ["A.NS"],
                "missing_tickers": [],
                "status": "complete",
            },
        }),
    ), patch(
        "app.services.ai_context_service.data_api.get_api_config",
        new=AsyncMock(return_value={}),
    ):
        payload = await service.build(ContextOptions(include=("concentration",)))

    section = payload["sections"]["concentration"]
    assert section["data"]["data_status"] == "available"
    assert section["coverage"]["status"] == "complete"
    assert "weight_basis" not in section["coverage"]
    assert "error" not in section
    # Weight-only payload: no monetary unit is declared, so none is invented.
    assert section["currency"] is None
    assert section["as_of"] is None


@pytest.mark.asyncio
async def test_export_warns_and_declares_no_currency_for_a_mixed_unit_composite():
    service = _service()
    components = {
        "portfolio": {"status": "available", "data": {"currency": "USD", "total_value": 10.0}},
        "summary": {"status": "available", "data": {"currency": "INR", "portfolio_value": 10.0}},
    }
    section = service._make_section(
        key="dashboard",
        data={"components": components},
        inputs={"tickers": ["A.NS"]},
        detail="summary",
        status="available",
    )

    assert section["currency"] is None
    assert any("monetary units" in warning for warning in section["warnings"])


@pytest.mark.asyncio
async def test_api_boundary_omits_null_error_and_keeps_failed_error(async_client):
    from app.api.ai_context import AIContextExport
    from app.services.ai_context_service import SCHEMA_VERSION

    good = AIContextExport.model_validate(
        {
            "schema_version": SCHEMA_VERSION,
            "export_id": "test",
            "generated_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:00:01+00:00",
            "snapshot_consistency": "best_effort",
            "base_currency": "INR",
            "currency_policy": "policy",
            "detail": "summary",
            "scope": ["concentration"],
            "environment": {},
            "sections": {
                "concentration": {
                    "key": "concentration",
                    "title": "Concentration",
                    "route": "/dashboard/concentration",
                    "status": "available",
                    "detail": "summary",
                    "generated_at": "2026-01-01T00:00:00+00:00",
                    "data": {"by_weight": {"A.NS": 1.0}},
                },
                "liquidity": {
                    "key": "liquidity",
                    "title": "Liquidity",
                    "route": "/dashboard/liquidity",
                    "status": "unavailable",
                    "detail": "summary",
                    "generated_at": "2026-01-01T00:00:00+00:00",
                    "data": None,
                    "error": "No portfolio positions found",
                },
            },
            "warnings": [],
        }
    )
    body = good.model_dump(mode="json")

    assert "error" not in body["sections"]["concentration"]
    assert body["sections"]["liquidity"]["error"] == "No portfolio positions found"

    with patch(
        "app.api.ai_context.PortfolioContextService.build",
        new=AsyncMock(return_value=body),
    ):
        response = await async_client.get("/api/v1/ai/context?format=json")

    assert response.status_code == 200
    sections = response.json()["sections"]
    assert "error" not in sections["concentration"]
    assert sections["concentration"]["data"] == {"by_weight": {"A.NS": 1.0}}
    assert sections["liquidity"]["error"] == "No portfolio positions found"
    assert "error" not in sections["concentration"]


def test_markdown_documents_the_normalized_contract():
    from app.services.ai_context_service import render_markdown

    markdown = render_markdown(
        {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "base_currency": "INR",
            "sections": {
                "realized_risk": {
                    "title": "Realized Risk",
                    "status": "partial",
                    "coverage": {
                        "status": "partial",
                        "missing_tickers": ["B.NS"],
                        "weight_basis": ACTIVE_WEIGHT_BASIS,
                    },
                    "data": {},
                }
            },
        }
    )

    assert "## Contract" in markdown
    assert "complete`, `partial`, `unavailable`, `unknown" in markdown
    assert f"`{ACTIVE_WEIGHT_BASIS}`" in markdown
    assert f"- Weight basis: `{ACTIVE_WEIGHT_BASIS}`" in markdown
