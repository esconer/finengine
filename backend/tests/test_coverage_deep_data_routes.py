"""
Comprehensive test suite for app.api.data endpoints to achieve maximum coverage.
"""

from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime
import pandas as pd
import pytest
from app.services.indicators_service import StaleMarketDataError


@pytest.mark.api
class TestDataAPIRoutesDeep:
    @pytest.mark.asyncio
    async def test_all_data_routes(self, async_client):
        # 1. Config GET and PUT
        res_cfg = await async_client.get("/api/v1/data/config")
        assert res_cfg.status_code == 200

        res_put_cfg = await async_client.put("/api/v1/data/config?cache_ttl_minutes=120&enable_cache=true")
        assert res_put_cfg.status_code == 200
        assert res_put_cfg.json()["updated"] is True

        mock_ds = Mock()
        sample_df = pd.DataFrame({
            "date": pd.to_datetime(["2025-01-01", "2025-01-02"]),
            "open": [100.0, 101.0],
            "high": [105.0, 106.0],
            "low": [99.0, 100.0],
            "close": [104.0, 105.0],
            "adj_close": [104.0, 105.0],
            "volume": [10000, 12000]
        })
        mock_ds.fetch_historical_data = AsyncMock(return_value=sample_df)
        mock_ds._get_cached_data = AsyncMock(return_value=sample_df)
        mock_ds.fetch_quote = AsyncMock(return_value={
            "ticker": "INFY.NS",
            "current_price": 105.0,
            "open_price": 100.0,
            "high_price": 106.0,
            "low_price": 99.0,
            "previous_close": 104.0,
            "change": 1.0,
            "change_percent": 0.96,
            "volume": 12000,
            "market_cap": 500000000.0,
            "timestamp": datetime.utcnow(),
            "sector": "Technology",
            "industry": "IT"
        })
        mock_ds.validate_ticker = AsyncMock(return_value=True)
        mock_ds.fetch_ohlcv_batch = AsyncMock(return_value={"data": {"INFY.NS": sample_df}, "failed_tickers": []})

        with patch("app.api.data.GlobalDataService") as mock_gds:
            mock_gds.return_value.get_service.return_value = mock_ds

            # 2. Get stock data
            res_stock = await async_client.get("/api/v1/data/INFY.NS")
            assert res_stock.status_code == 200
            assert res_stock.json()["ticker"] == "INFY.NS"

            # 3. Get stock quote
            res_quote = await async_client.get("/api/v1/data/quote/INFY.NS")
            assert res_quote.status_code == 200
            assert res_quote.json()["ticker"] == "INFY.NS"

            # 4. Batch stock data
            res_batch = await async_client.post("/api/v1/data/batch", json={"tickers": ["INFY.NS"]})
            assert res_batch.status_code == 200
            assert "INFY.NS" in res_batch.json()["data"]

            # 5. Validate ticker
            res_val = await async_client.post("/api/v1/data/validate", json={"ticker": "INFY.NS"})
            assert res_val.status_code == 200
            assert res_val.json()["valid"] is True

            # 6. Refresh ticker data
            res_ref = await async_client.post("/api/v1/data/refresh", json=["INFY.NS", "FAIL.NS"])
            assert res_ref.status_code == 200
            assert res_ref.json()["refreshed"] >= 1
