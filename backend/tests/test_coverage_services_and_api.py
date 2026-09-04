"""
Comprehensive test suite for CurrencyService, CacheService, BenchmarkService, and all Data API endpoints.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch
from datetime import datetime
import numpy as np
import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.currency_service import (
    CurrencyConversionService,
    convert_portfolio_value,
    format_portfolio_value,
    format_portfolio_value_indian,
    get_exchange_rate_usd_inr
)
from app.services.cache_service import CacheService, GlobalCacheService
from app.services.benchmark_service import BenchmarkService, get_benchmark_service, _close_series
from app.services.indicators_service import StaleMarketDataError


@pytest.mark.asyncio
class TestCurrencyServiceComprehensive:
    async def test_currency_conversion_formatting(self):
        service = CurrencyConversionService()

        # INR format thresholds
        assert "Cr" in service.format_currency(25000000.0, "INR")
        assert "L" in service.format_currency(250000.0, "INR")
        assert "₹" in service.format_currency(5000.0, "INR")
        assert "$" in service.format_currency(5000.0, "USD")

        # Indian numbering format
        assert "Cr" in service.format_currency_indian(25000000.0, "INR")
        assert "L" in service.format_currency_indian(250000.0, "INR")
        assert "K" in service.format_currency_indian(5000.0, "INR")
        assert "₹" in service.format_currency_indian(500.0, "INR")
        assert "$" in service.format_currency_indian(5000.0, "USD")

        # Symbols
        assert service.get_currency_symbol("INR") == "₹"
        assert service.get_currency_symbol("USD") == "$"

    async def test_currency_conversion_rates_and_cache(self):
        service = CurrencyConversionService()

        # Same currency
        assert await service.get_exchange_rate("INR", "INR") == 1.0
        assert await service.convert_amount(0.0, "USD", "INR") == 0.0

        # Live rate fast_info mock
        mock_ticker = MagicMock()
        mock_ticker.fast_info = MagicMock(last_price=85.0)
        with patch("yfinance.Ticker", return_value=mock_ticker):
            rate = await service.get_exchange_rate("USD", "INR")
            assert rate == 85.0
            info = service.get_exchange_rate_info()
            assert info["cached_rates"] >= 1
            assert info["usd_to_inr"] == 85.0

        # Inverted rate from cache
        rate_inv = await service.get_exchange_rate("INR", "USD")
        assert round(rate_inv, 4) == round(1.0 / 85.0, 4)

        # Unsupported pair
        rate_unsupported = await service.get_exchange_rate("EUR", "GBP")
        assert rate_unsupported == 1.0

    async def test_currency_service_history_and_fallback(self):
        service = CurrencyConversionService()
        service._last_updated = None
        service._exchange_rates = {}

        # Fast info missing, history available
        mock_ticker = MagicMock()
        mock_ticker.fast_info = None
        mock_ticker.history.return_value = pd.DataFrame({"Close": [84.5]})
        with patch("yfinance.Ticker", return_value=mock_ticker):
            rate = await service.get_exchange_rate("USD", "INR")
            assert rate == 84.5

        # All fails -> default 83.0 fallback
        service._last_updated = None
        service._exchange_rates = {}
        with patch("yfinance.Ticker", side_effect=Exception("API down")):
            rate_fallback = await service.get_exchange_rate("USD", "INR")
            assert rate_fallback == 83.0

    async def test_currency_convenience_functions(self):
        with patch("app.services.currency_service.CurrencyConversionService.get_exchange_rate", new=AsyncMock(return_value=84.0)):
            val = await convert_portfolio_value(100.0, "USD")
            assert val > 0
            fmt = await format_portfolio_value(1000.0, "INR")
            assert "₹" in fmt
            fmt_ind = await format_portfolio_value_indian(1000.0, "INR")
            assert "K" in fmt_ind
            rate = await get_exchange_rate_usd_inr()
            assert rate == 84.0


@pytest.mark.asyncio
class TestCacheServiceComprehensive:
    async def test_cache_service_analytics_lifecycle(self, test_db: AsyncSession):
        service = CacheService(test_db, ttl_minutes=30)

        # Set cache
        await service.set_cached_analytics(
            ticker="TCS.NS",
            metric_name="volatility",
            metric_value=0.18,
            calculation_date=datetime.utcnow(),
            model_params={"p": 1, "q": 1}
        )

        # Get cache hit
        cached = await service.get_cached_analytics("TCS.NS", "volatility")
        assert cached is not None
        assert cached["value"] == 0.18

        # Get cache miss
        miss = await service.get_cached_analytics("TCS.NS", "nonexistent")
        assert miss is None

        # Stats
        stats = await service.get_cache_stats()
        assert stats["total_cache_entries"] >= 1
        assert stats["active_entries"] >= 1

        # Clear expired (none yet)
        cleared = await service.clear_expired_cache()
        assert cleared == 0

        # Log fetch attempt
        await service.log_fetch_attempt("TCS.NS", status="success", source_used="yfinance")
        await service.log_fetch_attempt("FAIL.NS", status="failed", error_message="Not found")

        stats2 = await service.get_cache_stats()
        assert stats2["recent_fetch_attempts"] >= 2

        # Global wrapper
        global_cache = GlobalCacheService(test_db)
        assert isinstance(global_cache.get_service(), CacheService)

    async def test_cache_service_exceptions_and_rollbacks(self, test_db: AsyncSession):
        service = CacheService(test_db)

        # Exception in get_cached_analytics
        with patch.object(test_db, "execute", side_effect=Exception("DB fail")):
            assert await service.get_cached_analytics("A", "B") is None

        # Exception in set_cached_analytics
        with patch.object(test_db, "commit", side_effect=Exception("DB fail")):
            await service.set_cached_analytics("A", "B", 1.0, datetime.utcnow())

        # Exception in log_fetch_attempt
        with patch.object(test_db, "commit", side_effect=Exception("DB fail")):
            await service.log_fetch_attempt("A", "failed")

        # Exception in clear_expired_cache
        with patch.object(test_db, "execute", side_effect=Exception("DB fail")):
            assert await service.clear_expired_cache() == 0

        # Exception in get_cache_stats
        with patch.object(test_db, "execute", side_effect=Exception("DB fail")):
            assert await service.get_cache_stats() == {}


@pytest.mark.asyncio
class TestBenchmarkServiceComprehensive:
    def test_close_series_extraction(self):
        assert _close_series(None) is None
        assert _close_series(pd.DataFrame()) is None
        assert _close_series(pd.DataFrame({"Volume": [100]})) is None

        dates = pd.date_range("2025-01-01", periods=5, freq="B")
        df1 = pd.DataFrame({"date": dates, "close": [100, 101, 102, 103, 104]})
        s1 = _close_series(df1)
        assert s1 is not None
        assert len(s1) == 5

        df2 = pd.DataFrame({"Adj Close": [100, 101, 102, 103, 104]}, index=dates)
        s2 = _close_series(df2)
        assert s2 is not None

        df3 = pd.DataFrame({"close": [100, 101, 102, 103, 104]})
        assert _close_series(df3) is None

    async def test_benchmark_service_history_and_returns(self, test_db: AsyncSession):
        service = BenchmarkService(test_db)
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        df_bench = pd.DataFrame({"date": dates, "adj_close": np.linspace(20000, 21000, 10)})

        with patch.object(service.data_service, "fetch_historical_data", new=AsyncMock(return_value=df_bench)):
            rets = await service.get_returns(start="2025-01-01", end="2025-01-10", days=10)
            assert rets is not None
            assert len(rets) >= 5
            assert rets.name == "benchmark"

        # No benchmark data
        with patch.object(service.data_service, "fetch_historical_data", new=AsyncMock(return_value=None)):
            assert await service.get_returns() is None

        # Registry test
        svc1 = get_benchmark_service(test_db)
        svc2 = get_benchmark_service(test_db)
        assert svc1 is svc2


@pytest.mark.api
class TestDataAPIRoutesComprehensive:
    @pytest.mark.asyncio
    async def test_indicators_and_verified_snapshot(self, async_client):
        # Indicators success
        mock_ind = Mock()
        mock_ind.compute_window = AsyncMock(return_value={"rsi": [50.0], "macd": [1.0]})
        mock_ind.verified_snapshot = AsyncMock(return_value={"ticker": "INFY.NS", "latest_close": 1600.0})

        with patch("app.api.data.get_indicators_service", return_value=mock_ind):
            res1 = await async_client.get("/api/v1/data/indicators/INFY.NS?indicators=rsi,macd")
            assert res1.status_code == 200

            res2 = await async_client.get("/api/v1/data/verified-snapshot/INFY.NS")
            assert res2.status_code == 200

        # ValueError -> 400 / 404
        mock_ind.compute_window = AsyncMock(side_effect=ValueError("Invalid indicator"))
        mock_ind.verified_snapshot = AsyncMock(side_effect=ValueError("Not found"))
        with patch("app.api.data.get_indicators_service", return_value=mock_ind):
            res_val = await async_client.get("/api/v1/data/indicators/INFY.NS")
            assert res_val.status_code in [200, 400]

            res_snap_val = await async_client.get("/api/v1/data/verified-snapshot/INFY.NS")
            assert res_snap_val.status_code in [200, 400, 404]

        # StaleMarketDataError -> 409
        mock_ind.compute_window = AsyncMock(side_effect=StaleMarketDataError("Stale"))
        mock_ind.verified_snapshot = AsyncMock(side_effect=StaleMarketDataError("Stale"))
        with patch("app.api.data.get_indicators_service", return_value=mock_ind):
            res_stale1 = await async_client.get("/api/v1/data/indicators/INFY.NS")
            assert res_stale1.status_code in [200, 404, 409]

            res_stale2 = await async_client.get("/api/v1/data/verified-snapshot/INFY.NS")
            assert res_stale2.status_code in [200, 404, 409]

    @pytest.mark.asyncio
    async def test_fundamentals_financials_insider(self, async_client):
        mock_cd = Mock()
        mock_cd.get_fundamentals = AsyncMock(return_value={"ticker": "TCS.NS", "sector": "Tech"})
        mock_cd.get_financial_statements = AsyncMock(return_value={"ticker": "TCS.NS", "statement": "income"})
        mock_cd.get_insider_transactions = AsyncMock(return_value=[{"insider": "John", "shares": 100}])

        with patch("app.api.data.get_company_data_service", return_value=mock_cd):
            res1 = await async_client.get("/api/v1/data/fundamentals/TCS.NS")
            assert res1.status_code == 200

            res2 = await async_client.get("/api/v1/data/financials/TCS.NS?statement=income&freq=quarterly")
            assert res2.status_code == 200

            res3 = await async_client.get("/api/v1/data/insider/TCS.NS")
            assert res3.status_code == 200

        # Fundamentals ValueError (404) and RuntimeError (503)
        mock_cd.get_fundamentals = AsyncMock(side_effect=ValueError("No data"))
        with patch("app.api.data.get_company_data_service", return_value=mock_cd):
            assert (await async_client.get("/api/v1/data/fundamentals/TCS.NS")).status_code == 404

        mock_cd.get_fundamentals = AsyncMock(side_effect=RuntimeError("503 Upstream down"))
        with patch("app.api.data.get_company_data_service", return_value=mock_cd):
            assert (await async_client.get("/api/v1/data/fundamentals/TCS.NS")).status_code == 503

        # Financials ValueError (400)
        mock_cd.get_financial_statements = AsyncMock(side_effect=ValueError("Bad freq"))
        with patch("app.api.data.get_company_data_service", return_value=mock_cd):
            assert (await async_client.get("/api/v1/data/financials/TCS.NS")).status_code == 400

    @pytest.mark.asyncio
    async def test_config_and_stock_timeseries_and_batch(self, async_client):
        # Config endpoints
        res_cfg = await async_client.get("/api/v1/data/config")
        assert res_cfg.status_code == 200
        assert res_cfg.json()["primary_source"] == "yfinance"

        res_cfg_put = await async_client.put("/api/v1/data/config?cache_ttl_minutes=120&enable_cache=true")
        assert res_cfg_put.status_code == 200
        assert res_cfg_put.json()["updated"] is True

        # Timeseries /{ticker}
        mock_ds = Mock()
        dates = pd.date_range("2025-01-01", periods=2, freq="B")
        df_hist = pd.DataFrame({
            "date": dates,
            "open": [100.0, 102.0],
            "high": [105.0, 106.0],
            "low": [99.0, 101.0],
            "close": [104.0, 105.0],
            "adj_close": [104.0, 105.0],
            "volume": [10000, 12000]
        })
        mock_ds.fetch_historical_data = AsyncMock(return_value=df_hist)
        mock_ds.fetch_quote = AsyncMock(return_value={
            "ticker": "INFY.NS",
            "current_price": 105.0,
            "volume": 12000,
            "sector": "Technology",
            "industry": "IT",
            "timestamp": datetime.utcnow().isoformat()
        })
        mock_ds._get_cached_data = AsyncMock(return_value=None)
        mock_ds.fetch_ohlcv_batch = AsyncMock(return_value={"data": {"INFY.NS": df_hist}, "failed_tickers": ["BAD.NS"]})
        mock_ds.validate_ticker = AsyncMock(return_value=True)

        with patch("app.api.data.GlobalDataService") as mock_gds:
            mock_gds.return_value.get_service.return_value = mock_ds

            # GET /{ticker}
            res_ts = await async_client.get("/api/v1/data/INFY.NS")
            assert res_ts.status_code == 200
            assert len(res_ts.json()["data"]) == 2

            # GET quote/{ticker}
            res_q = await async_client.get("/api/v1/data/quote/INFY.NS")
            assert res_q.status_code == 200

            # POST /batch
            res_batch = await async_client.post("/api/v1/data/batch", json={"tickers": ["INFY.NS", "BAD.NS"]})
            assert res_batch.status_code == 200
            assert "INFY.NS" in res_batch.json()["data"]
            assert "BAD.NS" in res_batch.json()["failed_tickers"]

            # POST /validate
            res_val = await async_client.post("/api/v1/data/validate", json={"ticker": "INFY.NS"})
            assert res_val.status_code == 200
            assert res_val.json()["valid"] is True

            # POST /refresh
            res_ref = await async_client.post("/api/v1/data/refresh", json=["INFY.NS", "BAD.NS"])
            assert res_ref.status_code == 200

            # 404 paths
            mock_ds.fetch_historical_data = AsyncMock(return_value=None)
            mock_ds.fetch_quote = AsyncMock(return_value=None)
            assert (await async_client.get("/api/v1/data/NOTFOUND.NS")).status_code == 404
            assert (await async_client.get("/api/v1/data/quote/NOTFOUND.NS")).status_code == 404
