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


@pytest.mark.api
class TestDataAPI:
    """Test data API endpoints"""
    
    @pytest.mark.asyncio
    async def test_get_stock_data_success(self, async_client: AsyncClient, mock_price_dataframe):
        """Test successful stock data retrieval"""
        with patch('app.services.data_service.DataService.fetch_historical_data') as mock_fetch:
            mock_fetch.return_value = mock_price_dataframe
            with patch('app.services.data_service.DataService.fetch_quote') as mock_quote:
                mock_quote.return_value = {
                    "current_price": 150.0,
                    "sector": "Technology",
                    "industry": "Consumer Electronics"
                }
                
                response = await async_client.get("/api/v1/data/AAPL")
                
                assert response.status_code == 200
                data = response.json()
                assert data["ticker"] == "AAPL"
                assert "data" in data
                assert "metadata" in data
                assert len(data["data"]) > 0
    
    @pytest.mark.asyncio
    async def test_get_stock_data_not_found(self, async_client: AsyncClient):
        """Test stock data retrieval for non-existent ticker"""
        with patch('app.services.data_service.DataService.fetch_historical_data') as mock_fetch:
            mock_fetch.return_value = None
            
            response = await async_client.get("/api/v1/data/INVALID")
            
            assert response.status_code == 404
            assert "No data found" in response.json()["detail"]
    
    @pytest.mark.asyncio
    async def test_get_stock_data_with_date_range(self, async_client: AsyncClient, mock_price_dataframe):
        """Test stock data retrieval with custom date range"""
        with patch('app.services.data_service.DataService.fetch_historical_data') as mock_fetch:
            mock_fetch.return_value = mock_price_dataframe
            
            start_date = "2023-01-01"
            end_date = "2023-12-31"
            
            response = await async_client.get(
                f"/api/v1/data/AAPL?start={start_date}&end={end_date}&force_refresh=true"
            )
            
            assert response.status_code == 200
            mock_fetch.assert_called_once_with("AAPL", start_date, end_date, True)
    
    @pytest.mark.asyncio
    async def test_get_stock_quote_success(self, async_client: AsyncClient):
        """Test successful stock quote retrieval"""
        with patch('app.services.data_service.DataService.fetch_quote') as mock_quote:
            mock_quote.return_value = {
                "current_price": 150.0,
                "previous_close": 149.0,
                "change": 1.0,
                "change_percent": 0.67,
                "volume": 1000000,
                "market_cap": "2.5T",
                "pe_ratio": 25.5,
                "dividend_yield": 0.5,
                "sector": "Technology",
                "industry": "Consumer Electronics"
            }
            
            response = await async_client.get("/api/v1/data/quote/AAPL")
            
            assert response.status_code == 200
            data = response.json()
            assert data["ticker"] == "AAPL"
            assert data["current_price"] == 150.0
    
    @pytest.mark.asyncio
    async def test_get_stock_quote_not_found(self, async_client: AsyncClient):
        """Test stock quote retrieval for non-existent ticker"""
        with patch('app.services.data_service.DataService.fetch_quote') as mock_quote:
            mock_quote.return_value = None
            
            response = await async_client.get("/api/v1/data/quote/INVALID")
            
            assert response.status_code == 404
            assert "No quote data found" in response.json()["detail"]
    
    @pytest.mark.asyncio
    async def test_batch_stock_data_success(self, async_client: AsyncClient, mock_price_dataframe):
        """Test successful batch stock data retrieval"""
        with patch('app.services.data_service.DataService.fetch_ohlcv_batch') as mock_batch:
            mock_batch.return_value = {
                "data": {"AAPL": mock_price_dataframe, "MSFT": mock_price_dataframe},
                "failed_tickers": []
            }
            
            request_data = {"tickers": ["AAPL", "MSFT"]}
            
            response = await async_client.post("/api/v1/data/batch", json=request_data)
            
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert "failed_tickers" in data
            assert "AAPL" in data["data"]
            assert "MSFT" in data["data"]
    
    @pytest.mark.asyncio
    async def test_validate_ticker_success(self, async_client: AsyncClient):
        """Test successful ticker validation"""
        with patch('app.services.data_service.DataService.validate_ticker') as mock_validate:
            mock_validate.return_value = True
            
            request_data = {"ticker": "AAPL"}
            
            response = await async_client.post("/api/v1/data/validate", json=request_data)
            
            assert response.status_code == 200
            data = response.json()
            assert data["valid"] is True
            assert "AAPL is valid" in data["message"]
    
    @pytest.mark.asyncio
    async def test_validate_ticker_invalid(self, async_client: AsyncClient):
        """Test ticker validation for invalid ticker"""
        with patch('app.services.data_service.DataService.validate_ticker') as mock_validate:
            mock_validate.return_value = False
            
            request_data = {"ticker": "INVALID"}
            
            response = await async_client.post("/api/v1/data/validate", json=request_data)
            
            assert response.status_code == 200
            data = response.json()
            assert data["valid"] is False
            assert "not found" in data["message"]
    
    @pytest.mark.asyncio
    async def test_refresh_ticker_data(self, async_client: AsyncClient):
        """Test ticker data refresh"""
        with patch('app.services.data_service.DataService.fetch_historical_data') as mock_fetch:
            mock_fetch.return_value = pd.DataFrame()  # Non-empty DataFrame
            
            request_data = {"tickers": ["AAPL", "MSFT"]}
            
            response = await async_client.post("/api/v1/data/refresh", json=request_data)
            
            assert response.status_code == 200
            data = response.json()
            assert "refreshed" in data
            assert "failed" in data
            assert data["refreshed"] >= 0
    
    @pytest.mark.asyncio
    async def test_get_api_config(self, async_client: AsyncClient):
        """Test API configuration retrieval"""
        with patch('app.services.cache_service.CacheService.get_cache_stats') as mock_stats:
            mock_stats.return_value = {"ttl_minutes": 60}
            
            response = await async_client.get("/api/v1/data/config")
            
            assert response.status_code == 200
            data = response.json()
            assert data["primary_source"] == "yfinance"
            assert data["cache_ttl_minutes"] == 60
            assert data["enable_cache"] is True
    
    @pytest.mark.asyncio
    async def test_update_api_config(self, async_client: AsyncClient):
        """Test API configuration update"""
        response = await async_client.put("/api/v1/data/config?cache_ttl_minutes=120")
        
        assert response.status_code == 200
        data = response.json()
        assert data["updated"] is True
        assert "cache_ttl_minutes" in data["settings"]


@pytest.mark.api
class TestPortfolioAPI:
    """Test portfolio API endpoints"""
    
    @pytest.mark.asyncio
    async def test_get_portfolio_empty(self, async_client: AsyncClient):
        """Test empty portfolio retrieval"""
        with patch('app.db.database.get_db_session') as mock_db:
            # Mock empty database session
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_session.__aexit__.return_value = None
            mock_session.execute.return_value.scalars.return_value.all.return_value = []
            mock_db.return_value = mock_session
            
            with patch('app.services.data_service.DataService') as mock_service:
                mock_service.return_value.get_service.return_value = AsyncMock()
                
                response = await async_client.get("/api/v1/portfolio")
                
                assert response.status_code == 200
                data = response.json()
                assert data["positions"] == []
                assert data["total_value"] == 0
                assert data["total_positions"] == 0
    
    @pytest.mark.asyncio
    async def test_add_portfolio_position_success(self, async_client: AsyncClient, portfolio_position_factory):
        """Test successful portfolio position addition"""
        with patch('app.db.database.get_db_session') as mock_db:
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_session.__aexit__.return_value = None
            mock_db.return_value = mock_session
            
            with patch('app.services.data_service.DataService') as mock_service_class:
                mock_service = AsyncMock()
                mock_service.validate_ticker.return_value = True
                mock_service.fetch_quote.return_value = {
                    "current_price": 150.0,
                    "sector": "Technology",
                    "industry": "Consumer Electronics"
                }
                mock_service_class.return_value.get_service.return_value = mock_service
                
                # Mock database query for duplicate check
                mock_session.execute.return_value.scalar_one_or_none.return_value = None
                
                # Mock position creation
                position = portfolio_position_factory("AAPL", 0.1)
                position.id = 1
                position.added_on = datetime.utcnow()
                position.updated_on = datetime.utcnow()
                mock_session.add.return_value = None
                mock_session.commit.return_value = None
                mock_session.refresh.return_value = None
                
                request_data = {
                    "ticker": "AAPL",
                    "weight": 0.1,
                    "region": "US",
                    "custom_name": ""
                }
                
                response = await async_client.post("/api/v1/portfolio/add", json=request_data)
                
                assert response.status_code == 200
                data = response.json()
                assert data["ticker"] == "AAPL"
                assert data["weight"] == 0.1
    
    @pytest.mark.asyncio
    async def test_add_portfolio_position_invalid_ticker(self, async_client: AsyncClient):
        """Test portfolio position addition with invalid ticker"""
        with patch('app.services.data_service.DataService') as mock_service_class:
            mock_service = AsyncMock()
            mock_service.validate_ticker.return_value = False
            mock_service_class.return_value.get_service.return_value = mock_service
            
            request_data = {
                "ticker": "INVALID",
                "weight": 0.1,
                "region": "US"
            }
            
            response = await async_client.post("/api/v1/portfolio/add", json=request_data)
            
            assert response.status_code == 400
            assert "not valid" in response.json()["detail"]
    
    @pytest.mark.asyncio
    async def test_add_portfolio_position_duplicate(self, async_client: AsyncClient):
        """Test portfolio position addition with duplicate ticker"""
        with patch('app.db.database.get_db_session') as mock_db:
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_db.return_value = mock_session
            
            with patch('app.services.data_service.DataService') as mock_service_class:
                mock_service = AsyncMock()
                mock_service.validate_ticker.return_value = True
                mock_service_class.return_value.get_service.return_value = mock_service
                
                # Mock existing position
                mock_session.execute.return_value.scalar_one_or_none.return_value = Mock()
                
                request_data = {
                    "ticker": "AAPL",
                    "weight": 0.1,
                    "region": "US"
                }
                
                response = await async_client.post("/api/v1/portfolio/add", json=request_data)
                
                assert response.status_code == 409
                assert "already exists" in response.json()["detail"]
    
    @pytest.mark.asyncio
    async def test_bulk_add_positions_success(self, async_client: AsyncClient):
        """Test successful bulk position addition"""
        with patch('app.db.database.get_db_session') as mock_db:
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_session.__aexit__.return_value = None
            mock_db.return_value = mock_session
            
            with patch('app.services.data_service.DataService') as mock_service_class:
                mock_service = AsyncMock()
                mock_service.validate_ticker.return_value = True
                mock_service.fetch_quote.return_value = {
                    "current_price": 150.0,
                    "sector": "Technology",
                    "industry": "Consumer Electronics"
                }
                mock_service_class.return_value.get_service.return_value = mock_service
                
                # Mock no existing positions
                mock_session.execute.return_value.scalars.return_value.all.return_value = []
                
                request_data = {
                    "positions": [
                        {"ticker": "AAPL", "weight": 0.25, "region": "US"},
                        {"ticker": "MSFT", "weight": 0.25, "region": "US"}
                    ],
                    "auto_normalize": False
                }
                
                response = await async_client.post("/api/v1/portfolio/bulk_add", json=request_data)
                
                assert response.status_code == 200
                data = response.json()
                assert data["added"] == 2
                assert data["failed"] == 0
                assert len(data["positions"]) == 2
    
    @pytest.mark.asyncio
    async def test_get_portfolio_position(self, async_client: AsyncClient, portfolio_position_factory):
        """Test specific portfolio position retrieval"""
        with patch('app.db.database.get_db_session') as mock_db:
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_db.return_value = mock_session
            
            with patch('app.services.data_service.DataService') as mock_service_class:
                mock_service = AsyncMock()
                mock_service.fetch_quote.return_value = {"current_price": 150.0}
                mock_service_class.return_value.get_service.return_value = mock_service
                
                # Mock existing position
                position = portfolio_position_factory("AAPL", 0.1)
                position.id = 1
                position.added_on = datetime.utcnow()
                position.updated_on = datetime.utcnow()
                mock_session.execute.return_value.scalar_one_or_none.return_value = position
                mock_session.commit.return_value = None
                
                response = await async_client.get("/api/v1/portfolio/AAPL")
                
                assert response.status_code == 200
                data = response.json()
                assert data["ticker"] == "AAPL"
    
    @pytest.mark.asyncio
    async def test_get_portfolio_position_not_found(self, async_client: AsyncClient):
        """Test non-existent portfolio position retrieval"""
        with patch('app.db.database.get_db_session') as mock_db:
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_db.return_value = mock_session
            
            # Mock no existing position
            mock_session.execute.return_value.scalar_one_or_none.return_value = None
            
            response = await async_client.get("/api/v1/portfolio/INVALID")
            
            assert response.status_code == 404
            assert "not found" in response.json()["detail"]
    
    @pytest.mark.asyncio
    async def test_update_portfolio_position(self, async_client: AsyncClient, portfolio_position_factory):
        """Test portfolio position update"""
        with patch('app.db.database.get_db_session') as mock_db:
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_db.return_value = mock_session
            
            with patch('app.services.data_service.DataService') as mock_service_class:
                mock_service = AsyncMock()
                mock_service_class.return_value.get_service.return_value = mock_service
                
                # Mock existing position
                position = portfolio_position_factory("AAPL", 0.1)
                position.id = 1
                position.added_on = datetime.utcnow()
                position.updated_on = datetime.utcnow()
                mock_session.execute.return_value.scalar_one_or_none.return_value = position
                mock_session.commit.return_value = None
                mock_session.refresh.return_value = None
                
                request_data = {"weight": 0.15}
                
                response = await async_client.put("/api/v1/portfolio/AAPL", json=request_data)
                
                assert response.status_code == 200
                data = response.json()
                assert data["weight"] == 0.15
    
    @pytest.mark.asyncio
    async def test_update_portfolio_position_invalid_weight(self, async_client: AsyncClient):
        """Test portfolio position update with invalid weight"""
        with patch('app.db.database.get_db_session') as mock_db:
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_db.return_value = mock_session
            
            with patch('app.services.data_service.DataService') as mock_service_class:
                mock_service = AsyncMock()
                mock_service_class.return_value.get_service.return_value = mock_service
                
                # Mock existing position
                position = Mock()
                mock_session.execute.return_value.scalar_one_or_none.return_value = position
                
                request_data = {"weight": 2.0}  # Invalid weight > 1.0
                
                response = await async_client.put("/api/v1/portfolio/AAPL", json=request_data)
                
                assert response.status_code == 400
                assert "between 0 and 1" in response.json()["detail"]
    
    @pytest.mark.asyncio
    async def test_delete_portfolio_position(self, async_client: AsyncClient, portfolio_position_factory):
        """Test portfolio position deletion"""
        with patch('app.db.database.get_db_session') as mock_db:
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_db.return_value = mock_session
            
            # Mock existing position
            position = portfolio_position_factory("AAPL", 0.1)
            mock_session.execute.return_value.scalar_one_or_none.return_value = position
            mock_session.delete.return_value = None
            mock_session.commit.return_value = None
            
            response = await async_client.delete("/api/v1/portfolio/AAPL")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "deleted successfully" in data["message"]
    
    @pytest.mark.asyncio
    async def test_delete_portfolio_position_not_found(self, async_client: AsyncClient):
        """Test deletion of non-existent portfolio position"""
        with patch('app.db.database.get_db_session') as mock_db:
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_db.return_value = mock_session
            
            # Mock no existing position
            mock_session.execute.return_value.scalar_one_or_none.return_value = None
            
            response = await async_client.delete("/api/v1/portfolio/INVALID")
            
            assert response.status_code == 404
            assert "not found" in response.json()["detail"]
    
    @pytest.mark.asyncio
    async def test_export_portfolio_csv(self, async_client: AsyncClient, portfolio_position_factory):
        """Test portfolio CSV export"""
        with patch('app.db.database.get_db_session') as mock_db:
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_db.return_value = mock_session
            
            # Mock positions
            positions = [
                portfolio_position_factory("AAPL", 0.25),
                portfolio_position_factory("MSFT", 0.25)
            ]
            positions[0].added_on = datetime.utcnow()
            positions[0].updated_on = datetime.utcnow()
            positions[1].added_on = datetime.utcnow()
            positions[1].updated_on = datetime.utcnow()
            mock_session.execute.return_value.scalars.return_value.all.return_value = positions
            
            response = await async_client.get("/api/v1/portfolio/export/csv")
            
            assert response.status_code == 200
            csv_content = response.text
            assert "ticker,weight" in csv_content
            assert "AAPL" in csv_content
            assert "MSFT" in csv_content
    
    @pytest.mark.asyncio
    async def test_export_portfolio_csv_empty(self, async_client: AsyncClient):
        """Test portfolio CSV export with no positions"""
        with patch('app.db.database.get_db_session') as mock_db:
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_db.return_value = mock_session
            
            # Mock empty positions
            mock_session.execute.return_value.scalars.return_value.all.return_value = []
            
            response = await async_client.get("/api/v1/portfolio/export/csv")
            
            assert response.status_code == 404
            assert "No positions to export" in response.json()["detail"]
    
    @pytest.mark.asyncio
    async def test_normalize_portfolio_weights(self, async_client: AsyncClient, portfolio_position_factory):
        """Test portfolio weight normalization"""
        with patch('app.db.database.get_db_session') as mock_db:
            mock_session = AsyncMock()
            mock_session.__aenter__.return_value = mock_session
            mock_db.return_value = mock_session
            
            # Mock positions
            positions = [
                portfolio_position_factory("AAPL", 0.6),
                portfolio_position_factory("MSFT", 0.4)
            ]
            positions[0].added_on = datetime.utcnow()
            positions[0].updated_on = datetime.utcnow()
            positions[1].added_on = datetime.utcnow()
            positions[1].updated_on = datetime.utcnow()
            mock_session.execute.return_value.scalars.return_value.all.return_value = positions
            mock_session.commit.return_value = None
            
            response = await async_client.post("/api/v1/portfolio/normalize")
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "normalized" in data["message"]


@pytest.mark.api
class TestAnalyticsAPI:
    """Test analytics API endpoints"""
    
    @pytest.mark.asyncio
    async def test_get_analytics_summary(self, async_client: AsyncClient, mock_price_dataframe):
        """Test analytics summary endpoint"""
        with patch('app.services.data_service.DataService') as mock_service_class:
            mock_service = AsyncMock()
            mock_service.fetch_ohlcv_batch.return_value = {"data": {"AAPL": mock_price_dataframe}}
            mock_service_class.return_value.get_service.return_value = mock_service
            
            with patch('app.services.analytics_engine.GlobalAnalyticsEngine') as mock_engine_class:
                mock_engine = AsyncMock()
                mock_engine.get_engine.return_value.calculate_portfolio_metrics.return_value = {
                    "annual_return": 0.08,
                    "annual_volatility": 0.20,
                    "sharpe_ratio": 0.3,
                    "max_drawdown": -0.15
                }
                mock_engine_class.return_value.get_engine.return_value = mock_engine.get_engine.return_value
                
                response = await async_client.get("/api/v1/analytics/summary")
                
                assert response.status_code == 200
                data = response.json()
                assert "annual_return" in data
                assert "annual_volatility" in data
                assert "sharpe_ratio" in data
    
    @pytest.mark.asyncio
    async def test_get_realized_risk(self, async_client: AsyncClient, mock_price_dataframe):
        """Test realized risk endpoint"""
        with patch('app.services.data_service.DataService') as mock_service_class:
            mock_service = AsyncMock()
            mock_service.fetch_ohlcv_batch.return_value = {"data": {"AAPL": mock_price_dataframe}}
            mock_service_class.return_value.get_service.return_value = mock_service
            
            with patch('app.services.analytics_engine.GlobalAnalyticsEngine') as mock_engine_class:
                mock_engine = AsyncMock()
                mock_engine.get_engine.return_value.calculate_portfolio_metrics.return_value = {
                    "annual_volatility": 0.20,
                    "var_95": -0.025,
                    "cvar_95": -0.035
                }
                mock_engine_class.return_value.get_engine.return_value = mock_engine.get_engine.return_value
                
                response = await async_client.get("/api/v1/analytics/realized-risk?tickers=AAPL")
                
                assert response.status_code == 200
                data = response.json()
                assert "annual_volatility" in data
                assert "var_95" in data
    
    @pytest.mark.asyncio
    async def test_get_forecast_risk(self, async_client: AsyncClient, mock_returns_series):
        """Test forecast risk endpoint"""
        with patch('app.services.data_service.DataService') as mock_service_class:
            mock_service = AsyncMock()
            mock_service.fetch_ohlcv_batch.return_value = {
                "data": {"AAPL": pd.DataFrame({"Close": [100, 101, 102]})}
            }
            mock_service_class.return_value.get_service.return_value = mock_service
            
            with patch('app.services.analytics_engine.GlobalAnalyticsEngine') as mock_engine_class:
                mock_engine = AsyncMock()
                mock_engine.get_engine.return_value.forecast_volatility.return_value = {
                    "volatility_forecast": 0.22,
                    "model": "GARCH"
                }
                mock_engine_class.return_value.get_engine.return_value = mock_engine.get_engine.return_value
                
                response = await async_client.get("/api/v1/analytics/forecast-risk?tickers=AAPL")
                
                assert response.status_code == 200
                data = response.json()
                assert "volatility_forecast" in data
                assert "model" in data
    
    @pytest.mark.asyncio
    async def test_get_factor_exposure(self, async_client: AsyncClient, mock_price_dataframe):
        """Test factor exposure endpoint"""
        with patch('app.services.data_service.DataService') as mock_service_class:
            mock_service = AsyncMock()
            mock_service.fetch_ohlcv_batch.return_value = {"data": {"AAPL": mock_price_dataframe}}
            mock_service_class.return_value.get_service.return_value = mock_service
            
            with patch('app.services.analytics_engine.GlobalAnalyticsEngine') as mock_engine_class:
                mock_engine = AsyncMock()
                mock_engine.get_engine.return_value.factor_exposure_analysis.return_value = {
                    "portfolio": {"market": 1.1, "alpha": 0.02},
                    "r_squared": 0.85
                }
                mock_engine_class.return_value.get_engine.return_value = mock_engine.get_engine.return_value
                
                response = await async_client.get("/api/v1/analytics/factor-exposure?tickers=AAPL")
                
                assert response.status_code == 200
                data = response.json()
                assert "portfolio" in data
                assert "r_squared" in data
    
    @pytest.mark.asyncio
    async def test_get_concentration(self, async_client: AsyncClient, sample_portfolio_weights):
        """Test concentration analysis endpoint"""
        with patch('app.services.analytics_engine.GlobalAnalyticsEngine') as mock_engine_class:
            mock_engine = AsyncMock()
            mock_engine.get_engine.return_value.concentration_analysis.return_value = {
                "largest_position": 0.25,
                "herfindahl_index": 0.15,
                "effective_positions": 6.7
            }
            mock_engine_class.return_value.get_engine.return_value = mock_engine.get_engine.return_value
            
            response = await async_client.get("/api/v1/analytics/concentration")
            
            assert response.status_code == 200
            data = response.json()
            assert "largest_position" in data
            assert "herfindahl_index" in data
    
    @pytest.mark.asyncio
    async def test_get_liquidity(self, async_client: AsyncClient, mock_price_dataframe):
        """Test liquidity analysis endpoint"""
        with patch('app.services.data_service.DataService') as mock_service_class:
            mock_service = AsyncMock()
            mock_service.fetch_ohlcv_batch.return_value = {"data": {"AAPL": mock_price_dataframe}}
            mock_service_class.return_value.get_service.return_value = mock_service
            
            with patch('app.services.analytics_engine.GlobalAnalyticsEngine') as mock_engine_class:
                mock_engine = AsyncMock()
                mock_service = AsyncMock()
                liquidity_data = {
                    "overall_score": 7.5,
                    "liquidation_time_days": "2-5",
                    "risk_level": "Medium"
                }
                mock_engine.get_engine.return_value.liquidity_analysis.return_value = liquidity_data
                mock_service_class.return_value.get_service.return_value = mock_service
                mock_engine_class.return_value.get_engine.return_value = mock_engine.get_engine.return_value
                
                response = await async_client.get("/api/v1/analytics/liquidity")
                
                assert response.status_code == 200
                data = response.json()
                assert "overall_score" in data
                assert "liquidation_time_days" in data
    
    @pytest.mark.asyncio
    async def test_get_stress_test(self, async_client: AsyncClient, mock_price_dataframe):
        """Test stress testing endpoint"""
        with patch('app.services.data_service.DataService') as mock_service_class:
            mock_service = AsyncMock()
            mock_service.fetch_ohlcv_batch.return_value = {"data": {"AAPL": mock_price_dataframe}}
            mock_service_class.return_value.get_service.return_value = mock_service
            
            with patch('app.services.analytics_engine.GlobalAnalyticsEngine') as mock_engine_class:
                mock_engine = AsyncMock()
                stress_data = {
                    "scenario": "2020_covid",
                    "max_drawdown": -0.25,
                    "recovery_time": 45
                }
                mock_engine.get_engine.return_value.stress_test.return_value = stress_data
                mock_engine_class.return_value.get_engine.return_value = mock_engine.get_engine.return_value
                
                response = await async_client.get("/api/v1/analytics/stress-testing?scenario=2020_covid")
                
                assert response.status_code == 200
                data = response.json()
                assert "max_drawdown" in data
                assert "scenario" in data
    
    @pytest.mark.asyncio
    async def test_get_volatility_sizing(self, async_client: AsyncClient, mock_price_dataframe):
        """Test volatility sizing endpoint"""
        with patch('app.services.data_service.DataService') as mock_service_class:
            mock_service = AsyncMock()
            mock_service.fetch_ohlcv_batch.return_value = {"data": {"AAPL": mock_price_dataframe}}
            mock_service_class.return_value.get_service.return_value = mock_service
            
            with patch('app.services.analytics_engine.GlobalAnalyticsEngine') as mock_engine_class:
                mock_engine = AsyncMock()
                sizing_data = {
                    "recommended_weights": {"AAPL": 0.3},
                    "trades": {"AAPL": {"shares_delta": 10}},
                    "target_volatility": 0.15
                }
                mock_engine.get_engine.return_value.volatility_sizing.return_value = sizing_data
                mock_engine_class.return_value.get_engine.return_value = mock_engine.get_engine.return_value
                
                response = await async_client.get("/api/v1/analytics/volatility-sizing")
                
                assert response.status_code == 200
                data = response.json()
                assert "recommended_weights" in data
                assert "trades" in data
    
    @pytest.mark.asyncio
    async def test_get_risk_score(self, async_client: AsyncClient, mock_price_dataframe):
        """Test risk scoring endpoint"""
        with patch('app.services.data_service.DataService') as mock_service_class:
            mock_service = AsyncMock()
            mock_service.fetch_ohlcv_batch.return_value = {"data": {"AAPL": mock_price_dataframe}}
            mock_service_class.return_value.get_service.return_value = mock_service
            
            with patch('app.services.analytics_engine.GlobalAnalyticsEngine') as mock_engine_class:
                mock_engine = AsyncMock()
                risk_data = {
                    "overall_score": 25.0,
                    "risk_level": "MEDIUM",
                    "components": {"volatility": 15.0, "concentration": 10.0}
                }
                mock_engine.get_engine.return_value.risk_scoring.return_value = risk_data
                mock_engine_class.return_value.get_engine.return_value = mock_engine.get_engine.return_value
                
                response = await async_client.get("/api/v1/analytics/risk-score")
                
                assert response.status_code == 200
                data = response.json()
                assert "overall_score" in data
                assert "risk_level" in data
                assert "components" in data


@pytest.mark.api
class TestHealthAndStatus:
    """Test health check and status endpoints"""
    
    def test_health_check(self, client: TestClient):
        """Test health check endpoint"""
        response = client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "timestamp" in data
    
    def test_root_endpoint(self, client: TestClient):
        """Test root endpoint"""
        response = client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "Daisy Risk Engine" in data["message"]