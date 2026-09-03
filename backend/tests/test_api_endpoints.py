"""
API endpoint tests for Daisy Risk Engine
"""

import pytest
import json
from unittest.mock import AsyncMock, patch, Mock
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.api
class TestDataAPI:
    """Data endpoints; DataService mocked at the GlobalDataService seam with
    frames in the project's lowercase cache schema."""

    # Awaited seams every data endpoint may touch; overridable via kwargs.
    DEFAULT_ASYNC_RETURNS = {
        "_get_cached_data": None,
        "fetch_historical_data": None,
        "fetch_quote": None,
        "validate_ticker": False,
        "fetch_ohlcv_batch": {"data": {}, "failed_tickers": []},
    }

    def _patch_data_service(self, **method_returns):
        returns = {**self.DEFAULT_ASYNC_RETURNS, **method_returns}
        service = Mock()
        for name, value in returns.items():
            setattr(service.get_service.return_value, name, AsyncMock(return_value=value))
        self._last_service = service.get_service.return_value
        return patch("app.api.data.GlobalDataService", return_value=service)

    @pytest.mark.asyncio
    async def test_get_stock_data_success(self, async_client, ohlcv_frame_factory):
        frame = ohlcv_frame_factory()
        quote = {"ticker": "TEST", "current_price": 100.0, "sector": "Tech", "industry": "Soft"}
        with self._patch_data_service(fetch_historical_data=frame, fetch_quote=quote):
            resp = await async_client.get("/api/v1/data/TEST")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ticker"] == "TEST"
        assert len(data["data"]) > 0
        assert "metadata" in data

    @pytest.mark.asyncio
    async def test_get_stock_data_not_found(self, async_client):
        with self._patch_data_service(fetch_historical_data=None):
            resp = await async_client.get("/api/v1/data/INVALID")
        assert resp.status_code == 404
        assert "No data found" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_stock_data_forwards_params(self, async_client, ohlcv_frame_factory):
        frame = ohlcv_frame_factory()
        quote = {"ticker": "TEST", "current_price": 100.0}
        with self._patch_data_service(fetch_historical_data=frame, fetch_quote=quote):
            resp = await async_client.get(
                "/api/v1/data/TEST?start=2025-01-01&end=2025-12-31&force_refresh=true"
            )
        assert resp.status_code == 200, resp.text
        self._last_service.fetch_historical_data.assert_called_once_with(
            "TEST", "2025-01-01", "2025-12-31", True
        )

    @pytest.mark.asyncio
    async def test_get_stock_quote_success(self, async_client):
        quote = {
            "ticker": "TEST.NS", "current_price": 150.0, "volume": 1_000_000,
            "market_cap": None, "sector": "Technology", "industry": "Software",
            "52_week_high": 200.0, "52_week_low": 90.0,
            "pe_ratio": 25.5, "dividend_yield": 0.5,
        }
        with self._patch_data_service(fetch_quote=quote):
            resp = await async_client.get("/api/v1/data/quote/TEST")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["current_price"] == 150.0

    @pytest.mark.asyncio
    async def test_get_stock_quote_not_found(self, async_client):
        with self._patch_data_service(fetch_quote=None):
            resp = await async_client.get("/api/v1/data/quote/INVALID")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_batch_stock_data_success(self, async_client, ohlcv_frame_factory):
        batch = {"data": {"AAA": ohlcv_frame_factory(seed=1), "BBB": ohlcv_frame_factory(seed=2)}, "failed_tickers": []}
        with self._patch_data_service(fetch_ohlcv_batch=batch):
            resp = await async_client.post("/api/v1/data/batch", json={"tickers": ["AAA", "BBB"]})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert set(data["data"].keys()) == {"AAA", "BBB"}
        assert data["failed_tickers"] == []

    @pytest.mark.asyncio
    async def test_validate_ticker_success(self, async_client):
        with self._patch_data_service(validate_ticker=True):
            resp = await async_client.post("/api/v1/data/validate", json={"ticker": "AAPL"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_ticker_invalid(self, async_client):
        with self._patch_data_service(validate_ticker=False):
            resp = await async_client.post("/api/v1/data/validate", json={"ticker": "INVALID"})
        assert resp.status_code == 200
        assert resp.json()["valid"] is False

    @pytest.mark.asyncio
    async def test_refresh_ticker_data_bare_array_body(self, async_client, ohlcv_frame_factory):
        """Endpoint takes a bare JSON array body (matches frontend api.ts)."""
        frame = ohlcv_frame_factory()
        with self._patch_data_service(fetch_historical_data=frame):
            resp = await async_client.post("/api/v1/data/refresh", json=["AAA", "BBB"])
        assert resp.status_code == 200, resp.text
        assert resp.json()["refreshed"] == 2

    @pytest.mark.asyncio
    async def test_get_api_config_not_shadowed(self, async_client):
        """Regression: /config was shadowed by /{ticker} route order."""
        resp = await async_client.get("/api/v1/data/config")
        assert resp.status_code == 200, resp.text
        assert resp.json()["primary_source"] == "yfinance"


@pytest.mark.api
class TestPortfolioAPI:
    """Portfolio CRUD against the isolated test DB; market seam fully mocked."""

    def _patch_market_data(self, valid=True):
        svc = Mock()
        svc.get_service.return_value.validate_ticker = AsyncMock(return_value=valid)
        svc.get_service.return_value.fetch_quote = AsyncMock(return_value={
            "ticker": "TEST", "current_price": 150.0, "volume": 1000,
            "sector": "Technology", "industry": "Software",
            "52_week_high": 200.0, "52_week_low": 90.0,
            "pe_ratio": 20.0, "dividend_yield": 1.0,
        })
        return patch("app.api.portfolio.GlobalDataService", return_value=svc)

    @pytest.mark.asyncio
    async def test_get_portfolio_empty(self, async_client, test_db: AsyncSession):
        from app.models.database import PortfolioPosition
        from sqlalchemy import delete
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()
        resp = await async_client.get("/api/v1/portfolio")
        assert resp.status_code == 200
        assert resp.json()["positions"] == []

    @pytest.mark.asyncio
    async def test_add_position_success(self, async_client, test_db: AsyncSession):
        from app.models.database import PortfolioPosition
        from sqlalchemy import delete
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()
        with self._patch_market_data():
            resp = await async_client.post("/api/v1/portfolio/add", json={
                "ticker": "TEST", "weight": 0.5, "quantity": 10, "buy_price": 100,
            })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        # Unknown bare tickers pass through unmodified (P0-7: never
        # fabricate NSE listings); known Indian scrips still gain .NS.
        assert data["ticker"] == "TEST"
        assert data["last_price"] == 150.0
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

    @pytest.mark.asyncio
    async def test_add_duplicate_conflict(self, async_client, seeded_positions):
        with self._patch_market_data():
            resp = await async_client.post("/api/v1/portfolio/add", json={
                "ticker": "AAPL", "weight": 0.1, "quantity": 1, "buy_price": 100,
            })
        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_add_invalid_ticker_suggestions_400(self, async_client):
        with self._patch_market_data(valid=False):
            resp = await async_client.post("/api/v1/portfolio/add", json={
                "ticker": "APPL", "weight": 0.5, "quantity": 1, "buy_price": 100,
            })
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["error"] == "INVALID_TICKER"
        assert "AAPL" in detail["suggestions"]

    @pytest.mark.asyncio
    async def test_bulk_add_positions_success(self, async_client, test_db: AsyncSession):
        """Regression: module-level validator signature bug failed every row."""
        from app.models.database import PortfolioPosition
        from sqlalchemy import delete
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()
        with self._patch_market_data():
            resp = await async_client.post("/api/v1/portfolio/bulk_add", json={
                "positions": [
                    {"ticker": "AAA", "weight": 0.4, "quantity": 5, "buy_price": 100},
                    {"ticker": "BBB", "weight": 0.6, "quantity": 3, "buy_price": 200},
                ],
                "auto_normalize": False,
            })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["added"] == 2, data
        assert data["failed"] == 0
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

    @pytest.mark.asyncio
    async def test_get_position_includes_computed_fields(self, async_client, seeded_positions):
        with self._patch_market_data():
            resp = await async_client.get("/api/v1/portfolio/AAPL")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ticker"] == "AAPL"
        for field in ("quantity", "buy_price", "total_cost", "unrealized_gain_loss"):
            assert field in data

    @pytest.mark.asyncio
    async def test_update_position_weight(self, async_client, seeded_positions):
        resp = await async_client.put("/api/v1/portfolio/AAPL", json={"weight": 0.9})
        assert resp.status_code == 200, resp.text
        assert abs(resp.json()["weight"] - 0.9) < 1e-9

    @pytest.mark.asyncio
    async def test_update_position_invalid_weight_422(self, async_client, seeded_positions):
        # weight>1 rejected at the Pydantic schema layer before handler logic
        resp = await async_client.put("/api/v1/portfolio/AAPL", json={"weight": 1.5})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_delete_position(self, async_client, seeded_positions):
        resp = await async_client.delete("/api/v1/portfolio/AAPL")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_export_csv_contains_holdings(self, async_client, seeded_positions):
        resp = await async_client.get("/api/v1/portfolio/export/csv")
        assert resp.status_code == 200
        assert "AAPL" in resp.text

    @pytest.mark.asyncio
    async def test_normalize_weights(self, async_client, seeded_positions):
        resp = await async_client.post("/api/v1/portfolio/normalize")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


@pytest.mark.api
class TestAnalyticsAPI:
    """Analytics endpoints against real DB positions + real engine math.

    DataService is mocked at fetch_historical_data (the network seam) with
    schema-correct lowercase OHLCV frames; everything downstream is real.
    """

    def _patch_data_service(self, frame):
        """Patch the GlobalDataService name analytics.py actually resolves.

        analytics.py holds its own from-import bindings, so we must patch in
        ITS namespace with an explicitly built service mock.
        """
        service = Mock()
        service.get_service.return_value.fetch_historical_data = AsyncMock(
            return_value=frame
        )
        service.get_service.return_value.fetch_quote = AsyncMock(
            return_value={"market_cap": 100000000000.0}
        )
        return patch("app.api.analytics.GlobalDataService", return_value=service)

    @pytest.mark.asyncio
    async def test_realized_risk_uses_db_positions(self, async_client, seeded_positions, ohlcv_frame_factory):
        with self._patch_data_service(ohlcv_frame_factory()):
            resp = await async_client.get("/api/v1/analytics/realized-risk")
        assert resp.status_code == 200
        data = resp.json()
        assert set(data["positions"].keys()) == {"AAPL", "MSFT"}
        assert "annual_volatility" in data["portfolio"]

    @pytest.mark.asyncio
    async def test_realized_risk_explicit_tickers_override(self, async_client, seeded_positions, ohlcv_frame_factory):
        with self._patch_data_service(ohlcv_frame_factory()):
            resp = await async_client.get("/api/v1/analytics/realized-risk?tickers=INFY.NS")
        assert resp.status_code == 200
        assert set(resp.json()["positions"].keys()) == {"INFY.NS"}

    @pytest.mark.asyncio
    async def test_empty_portfolio_returns_clean_error(self, async_client, ohlcv_frame_factory):
        with self._patch_data_service(ohlcv_frame_factory()):
            resp = await async_client.get("/api/v1/analytics/realized-risk")
        assert resp.status_code == 200
        assert "positions found" in resp.json().get("error", "")

    @pytest.mark.asyncio
    async def test_forecast_risk_default_positions(self, async_client, seeded_positions, ohlcv_frame_factory):
        with self._patch_data_service(ohlcv_frame_factory()):
            resp = await async_client.get("/api/v1/analytics/forecast-risk?model=EWMA")
        assert resp.status_code == 200
        data = resp.json()
        assert data["portfolio"]["volatility_forecast"] >= 0
        assert set(data["positions"].keys()) == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_factor_exposure_structure(self, async_client, seeded_positions, ohlcv_frame_factory):
        with self._patch_data_service(ohlcv_frame_factory()):
            resp = await async_client.get("/api/v1/analytics/factor-exposure?lookback_days=120")
        assert resp.status_code == 200
        data = resp.json()
        assert "portfolio" in data and "r_squared" in data

    @pytest.mark.asyncio
    async def test_concentration_reflects_positions(self, async_client, seeded_positions):
        resp = await async_client.get("/api/v1/analytics/concentration")
        assert resp.status_code == 200
        data = resp.json()
        # market values 18k/21k -> largest weight 21/39
        assert abs(data["largest_position"] - 21000 / 39000) < 1e-6
        assert data["herfindahl_index"] > 0

    @pytest.mark.asyncio
    async def test_liquidity_handles_lowercase_volume(self, async_client, seeded_positions, ohlcv_frame_factory):
        with self._patch_data_service(ohlcv_frame_factory()):
            resp = await async_client.get("/api/v1/analytics/liquidity")
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_score" in data
        assert set(data["by_position"].keys()) == {"AAPL", "MSFT"}

    @pytest.mark.asyncio
    async def test_stress_test_post(self, async_client, seeded_positions, ohlcv_frame_factory):
        with self._patch_data_service(ohlcv_frame_factory()):
            resp = await async_client.post(
                "/api/v1/analytics/stress-test", json={"scenario": "2020_covid"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["scenario"] == "2020_covid"
        assert "max_drawdown" in data

    @pytest.mark.asyncio
    async def test_volatility_sizing_weights(self, async_client, seeded_positions, ohlcv_frame_factory):
        with self._patch_data_service(ohlcv_frame_factory()):
            resp = await async_client.get("/api/v1/analytics/volatility-sizing")
        assert resp.status_code == 200
        data = resp.json()
        rec = data["recommended_weights"]
        assert set(rec.keys()) == {"AAPL", "MSFT"}
        assert abs(sum(rec.values()) - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_risk_score_components(self, async_client, seeded_positions, ohlcv_frame_factory):
        with self._patch_data_service(ohlcv_frame_factory()):
            resp = await async_client.get("/api/v1/analytics/risk-score")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["overall_score"], (int, float))
        assert data["risk_level"] in {"LOW", "MEDIUM", "HIGH"}

    @pytest.mark.asyncio
    async def test_summary_counts_positions(self, async_client, seeded_positions, ohlcv_frame_factory):
        with self._patch_data_service(ohlcv_frame_factory()):
            resp = await async_client.get("/api/v1/analytics/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_positions"] == 2
        assert "risk_score" in data


@pytest.mark.api
class TestHealthAndStatus:
    """Test health check and status endpoints"""
    
    def test_health_check(self, client: TestClient):
        """Test health check endpoint"""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "service" in data
    
    def test_root_endpoint(self, client: TestClient):
        """Test root endpoint"""
        response = client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "Daisy Risk Engine" in data["message"]