"""Public contract tests for the portfolio AI context export."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest


def _payload():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "1.0",
        "export_id": "test-export",
        "generated_at": now,
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
    assert body["schema_version"] == "1.0"
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
            "positions": {},
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
