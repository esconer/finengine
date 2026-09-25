"""Public contract tests for the portfolio AI context export."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest


def _payload():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.1",
        "export_id": "test-export",
        "generated_at": now,
        "completed_at": now,
        "snapshot_consistency": "best_effort",
        "base_currency": "INR",
        "currency_policy": "Portfolio section uses the requested base_currency; analytics sections retain endpoint units.",
        "detail": "summary",
        "scope": ["portfolio", "realized_risk"],
        "environment": {"primary_source": "bfinance"},
        "sections": {
            "portfolio": {
                "key": "portfolio",
                "title": "Portfolio Management",
                "route": "/portfolio/manage",
                "status": "available",
                "detail": "summary",
                "generated_at": now,
                "as_of": now,
                "inputs": {"currency": "INR"},
                "data": {"total_value": 1000.0, "positions": []},
                "warnings": [],
            },
            "realized_risk": {
                "key": "realized_risk",
                "title": "Realized Risk",
                "route": "/dashboard/realized-risk",
                "status": "unavailable",
                "detail": "summary",
                "generated_at": now,
                "as_of": None,
                "inputs": {},
                "data": None,
                "warnings": [],
                "error": "No portfolio positions found",
            },
        },
        "warnings": [],
    }


@pytest.mark.asyncio
async def test_ai_context_endpoint_returns_json_contract(async_client):
    payload = _payload()
    with patch(
        "app.api.ai_context.PortfolioContextService.build",
        new=AsyncMock(return_value=payload),
    ):
        response = await async_client.get("/api/v1/ai/context?format=json")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1.1"
    assert body["base_currency"] == "INR"
    assert set(body["sections"]) == {"portfolio", "realized_risk"}
    assert body["sections"]["portfolio"]["status"] == "available"


@pytest.mark.asyncio
async def test_ai_context_endpoint_can_return_markdown(async_client):
    from app.services.ai_context_service import render_markdown

    payload = _payload()
    with patch(
        "app.api.ai_context.PortfolioContextService.build",
        new=AsyncMock(return_value=payload),
    ):
        response = await async_client.get("/api/v1/ai/context?format=markdown")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.text == render_markdown(payload)
    assert "# FinEngine Portfolio AI Context" in response.text
    assert "Equity Research" not in response.text


@pytest.mark.asyncio
async def test_service_marks_missing_result_tickers_as_partial():
    from app.services.ai_context_service import ContextOptions, PortfolioContextService

    portfolio = {
        "positions": [{"ticker": "AAPL"}, {"ticker": "NIFTYIETF.NS"}],
        "total_value": 1000.0,
        "currency": "INR",
    }
    service = PortfolioContextService(
        db=Mock(),
        data_service=Mock(),
        analytics_engine=Mock(),
        benchmark_service=Mock(),
        cache_service=Mock(),
    )
    with patch(
        "app.services.ai_context_service.portfolio_api.get_portfolio",
        new=AsyncMock(return_value=portfolio),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_realized_risk",
        new=AsyncMock(return_value={
            "portfolio": {"annual_return": 0.1},
            "positions": {"AAPL": {"annual_return": 0.1}},
        }),
    ), patch(
        "app.services.ai_context_service.data_api.get_api_config",
        new=AsyncMock(return_value={"primary_source": "yfinance"}),
    ):
        payload = await service.build(ContextOptions(include=("realized_risk",)))

    section = payload["sections"]["realized_risk"]
    assert section["status"] == "partial"
    assert section["coverage"]["missing_tickers"] == ["NIFTYIETF.NS"]
    assert any("NIFTYIETF.NS" in warning for warning in section["warnings"])


@pytest.mark.asyncio
async def test_service_does_not_trust_a_narrower_explicit_coverage_claim():
    from app.services.ai_context_service import ContextOptions, PortfolioContextService

    service = PortfolioContextService(
        db=Mock(),
        data_service=Mock(),
        analytics_engine=Mock(),
        benchmark_service=Mock(),
        cache_service=Mock(),
    )
    with patch(
        "app.services.ai_context_service.portfolio_api.get_portfolio",
        new=AsyncMock(return_value={
            "positions": [{"ticker": "AAPL"}, {"ticker": "NIFTYIETF.NS"}],
            "total_value": 1000.0,
        }),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_realized_risk",
        new=AsyncMock(return_value={
            "portfolio": {"annual_return": 0.1},
            "universe_coverage": {
                "requested_tickers": ["AAPL"],
                "available_tickers": ["AAPL"],
                "missing_tickers": [],
                "status": "complete",
            },
        }),
    ), patch(
        "app.services.ai_context_service.data_api.get_api_config",
        new=AsyncMock(return_value={}),
    ):
        payload = await service.build(ContextOptions(include=("realized_risk",)))

    section = payload["sections"]["realized_risk"]
    assert section["status"] == "partial"
    assert section["coverage"]["requested_tickers"] == ["AAPL", "NIFTYIETF.NS"]
    assert section["coverage"]["missing_tickers"] == ["NIFTYIETF.NS"]


def test_numeric_risk_score_components_are_not_mistaken_for_group_envelopes():
    from app.services.ai_context_service import _component_status

    assert _component_status({
        "overall_score": 13.1,
        "components": {"volatility": 11, "factor_risk": 30},
    }) == "available"


@pytest.mark.asyncio
async def test_dashboard_reuses_risk_contribution_cached_by_risk_studio():
    from app.services.ai_context_service import (
        ContextOptions,
        PortfolioContextService,
        _BuildContext,
    )

    service = PortfolioContextService(
        db=Mock(), data_service=Mock(), analytics_engine=Mock(),
        benchmark_service=Mock(), cache_service=Mock(),
    )
    context = _BuildContext(
        options=ContextOptions(include=("dashboard",)),
        base_currency="INR",
        portfolio={"positions": [{"ticker": "A"}], "total_value": 100.0},
        tickers=["A"], ticker_csv="A", total_value=100.0,
        cached={
            "risk_contribution": {
                "positions": {"volatility": {"A": 0.5}, "cvar_tail": {"A": 0.5}},
                "universe_coverage": {
                    "requested_tickers": ["A"], "available_tickers": ["A"],
                    "missing_tickers": [], "status": "complete",
                },
            }
        },
    )
    section_data = {
        key: {"data": {"value": 1}, "status": "available"}
        for key in ("realized_risk", "forecast_risk", "factor_exposure", "concentration", "liquidity", "regime")
    }
    context.cached_sections.update(section_data)

    with patch(
        "app.services.ai_context_service.analytics_api.get_analytics_summary",
        new=AsyncMock(return_value={"value": 1}),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_performance_history",
        new=AsyncMock(return_value=[]),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_risk_score",
        new=AsyncMock(return_value={"overall_score": 1}),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_risk_contribution",
        new=AsyncMock(return_value={"unexpected": True}),
    ) as rc:
        result = await service._collect_dashboard(context)

    assert result.data["components"]["risk_contribution"]["data"]["positions"]
    rc.assert_not_awaited()


@pytest.mark.asyncio
async def test_dashboard_contains_visible_component_contract():
    from app.services.ai_context_service import ContextOptions, PortfolioContextService

    service = PortfolioContextService(
        db=Mock(),
        data_service=Mock(),
        analytics_engine=Mock(),
        benchmark_service=Mock(),
        cache_service=Mock(),
    )
    portfolio = {
        "positions": [{"ticker": "AAPL"}],
        "total_value": 1000.0,
        "currency": "INR",
    }
    components = {
        "summary": {"portfolio_value": 1000.0, "currency": "INR"},
        "performance_history": [],
        "realized_risk": {"portfolio": {"annual_return": 0.1}, "positions": {"AAPL": {}}},
        "forecast_risk": {"portfolio": {"volatility_forecast": 0.1}, "positions": {"AAPL": {}}},
        "factor_exposure": {"portfolio": {"market": 1.0}, "positions": {"AAPL": {}}},
        "concentration": {"by_weight": {"AAPL": 1.0}},
        "liquidity": {"by_position": {"AAPL": {}}},
        "risk_score": {"overall_score": 50, "risk_level": "Medium"},
        "regime": {"current_regime": "normal"},
        "risk_contribution": {"positions": {"volatility": {"AAPL": {}}, "cvar_tail": {"AAPL": {}}}},
    }
    with patch(
        "app.services.ai_context_service.portfolio_api.get_portfolio",
        new=AsyncMock(return_value=portfolio),
    ), patch(
        "app.services.ai_context_service.data_api.get_api_config",
        new=AsyncMock(return_value={}),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_analytics_summary",
        new=AsyncMock(return_value=components["summary"]),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_performance_history",
        new=AsyncMock(return_value=components["performance_history"]),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_realized_risk",
        new=AsyncMock(return_value=components["realized_risk"]),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_forecast_risk",
        new=AsyncMock(return_value=components["forecast_risk"]),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_factor_exposure",
        new=AsyncMock(return_value=components["factor_exposure"]),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_concentration_metrics",
        new=AsyncMock(return_value=components["concentration"]),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_liquidity_metrics",
        new=AsyncMock(return_value=components["liquidity"]),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_risk_score",
        new=AsyncMock(return_value=components["risk_score"]),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_regime",
        new=AsyncMock(return_value=components["regime"]),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_risk_contribution",
        new=AsyncMock(return_value=components["risk_contribution"]),
    ):
        payload = await service.build(ContextOptions(include=("dashboard",)))

    dashboard = payload["sections"]["dashboard"]
    assert dashboard["status"] == "available"
    assert set(dashboard["data"]["components"]) == {
        "portfolio", "summary", "performance_history", "realized_risk",
        "forecast_risk", "factor_exposure", "concentration", "liquidity",
        "risk_score", "regime", "risk_contribution",
    }


@pytest.mark.asyncio
async def test_service_collects_a_selected_analytics_section():
    from app.services.ai_context_service import ContextOptions, PortfolioContextService

    portfolio = {
        "positions": [{"ticker": "AAPL"}],
        "total_value": 1000.0,
        "currency": "INR",
    }
    service = PortfolioContextService(
        db=Mock(),
        data_service=Mock(),
        analytics_engine=Mock(),
        benchmark_service=Mock(),
        cache_service=Mock(),
    )
    with patch(
        "app.services.ai_context_service.portfolio_api.get_portfolio",
        new=AsyncMock(return_value=portfolio),
    ), patch(
        "app.services.ai_context_service.analytics_api.get_realized_risk",
        new=AsyncMock(return_value={
            "portfolio": {"annual_return": 0.1},
            "positions": {"AAPL": {"annual_return": 0.1}},
            "warnings": [{"ticker": "AAPL", "message": "Short history"}],
        }),
    ) as realized, patch(
        "app.services.ai_context_service.data_api.get_api_config",
        new=AsyncMock(return_value={"primary_source": "bfinance"}),
    ):
        payload = await service.build(ContextOptions(include=("realized_risk",)))

    assert payload["scope"] == ["realized_risk"]
    assert payload["sections"]["realized_risk"]["status"] == "available"
    assert payload["sections"]["realized_risk"]["warnings"] == ["AAPL: Short history"]
    assert realized.await_count == 1


@pytest.mark.asyncio
async def test_service_can_build_a_selected_portfolio_only_context():
    from app.services.ai_context_service import ContextOptions, PortfolioContextService

    portfolio = {
        "positions": [{"ticker": "AAPL"}],
        "total_value": 1000.0,
        "currency": "INR",
    }
    service = PortfolioContextService(
        db=Mock(),
        data_service=Mock(),
        analytics_engine=Mock(),
        benchmark_service=Mock(),
        cache_service=Mock(),
    )
    with patch(
        "app.services.ai_context_service.portfolio_api.get_portfolio",
        new=AsyncMock(return_value=portfolio),
    ), patch(
        "app.services.ai_context_service.data_api.get_api_config",
        new=AsyncMock(return_value={"primary_source": "bfinance"}),
    ):
        payload = await service.build(ContextOptions(include=("portfolio",)))

    assert payload["scope"] == ["portfolio"]
    assert payload["sections"]["portfolio"]["status"] == "available"
    assert payload["sections"]["portfolio"]["data"]["total_value"] == 1000.0


@pytest.mark.asyncio
async def test_ai_context_endpoint_rejects_excluded_section(async_client):
    response = await async_client.get("/api/v1/ai/context?include=equity_research")

    assert response.status_code == 400
    assert "Unknown AI context section" in response.text


@pytest.mark.asyncio
async def test_ai_context_empty_portfolio_returns_a_structured_snapshot(async_client):
    response = await async_client.get("/api/v1/ai/context?include=portfolio")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == ["portfolio"]
    assert body["sections"]["portfolio"]["status"] == "available"
    assert body["sections"]["portfolio"]["data"]["positions"] == []


def test_context_scope_rejects_excluded_pages():
    from app.services.ai_context_service import DEFAULT_SECTIONS, parse_include

    assert "equity_research" not in DEFAULT_SECTIONS
    assert "screener_studio" not in DEFAULT_SECTIONS
    assert parse_include("portfolio,realized-risk") == ("portfolio", "realized_risk")
    with pytest.raises(ValueError, match="Unknown AI context section"):
        parse_include("equity_research")


def test_markdown_renderer_marks_unavailable_sections():
    from app.services.ai_context_service import render_markdown

    markdown = render_markdown(_payload())

    assert "## Portfolio Management" in markdown
    assert "Status: `available`" in markdown
    assert "Status: `unavailable`" in markdown
    assert "No portfolio positions found" in markdown
    assert "```json" in markdown
