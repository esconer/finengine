"""
Comprehensive test suite for DataService to achieve 100% coverage of app.services.data_service.
Tests caching, upsert, failovers, fallback quotes, batching, validation, storage error analysis, and integrity checks.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import numpy as np
import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.models.database import StockTimeseries, FetchLog
from app.services.data_service import DataService, GlobalDataService


def _sample_df(ticker="RELIANCE.NS", days=10):
    dates = pd.date_range("2025-01-01", periods=days, freq="B")
    close = np.linspace(2500.0, 2600.0, days)
    return pd.DataFrame({
        "date": dates,
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "adj_close": close,
        "volume": np.full(days, 100000),
        "ticker": ticker
    })


@pytest.mark.asyncio
class TestDataServiceNormalizationAndBasics:
    async def test_normalize_indian_ticker(self, test_db: AsyncSession):
        service = DataService(test_db)
        
        # Yahoo-native symbols pass through
        assert service._normalize_indian_ticker("^NSEI") == "^NSEI"
        assert service._normalize_indian_ticker("USDINR=X") == "USDINR=X"
        assert service._normalize_indian_ticker("INR=X") == "INR=X"
        
        # Already has exchange suffix
        assert service._normalize_indian_ticker("TCS.NS") == "TCS.NS"
        assert service._normalize_indian_ticker("TCS.BO") == "TCS.BO"
        
        # Known Indian stock without suffix
        assert service._normalize_indian_ticker("RELIANCE") == "RELIANCE.NS"
        assert service._normalize_indian_ticker("INFY") == "INFY.NS"
        assert service._normalize_indian_ticker("HDFCBANK") == "HDFCBANK.NS"
        
        # Default suffix addition
        assert service._normalize_indian_ticker("SOMEUNKNOWN") == "SOMEUNKNOWN.NS"

    async def test_is_indian_ticker(self, test_db: AsyncSession):
        service = DataService(test_db)
        assert service._is_indian_ticker("RELIANCE.NS") is True
        assert service._is_indian_ticker("TCS.BO") is True
        assert service._is_indian_ticker("INFY") is True
        assert service._is_indian_ticker("AAPL") is False

    async def test_popular_indian_stocks_and_market_info(self, test_db: AsyncSession):
        service = DataService(test_db)
        stocks = service.get_popular_indian_stocks()
        assert "RELIANCE.NS" in stocks
        assert len(stocks) == 20
        
        info = service.get_market_info()
        assert info["default_region"] == "IN"
        assert info["market_focus"] == "Indian (NSE/BSE)"
        assert "popular_indian_stocks" in info

    async def test_global_data_service(self, test_db: AsyncSession):
        global_service = GlobalDataService(test_db)
        service = global_service.get_service()
        assert isinstance(service, DataService)
        assert service.db == test_db


@pytest.mark.asyncio
class TestDataServiceHistoricalData:
    async def test_fetch_historical_data_cache_hit(self, test_db: AsyncSession):
        service = DataService(test_db)
        cached_df = _sample_df("TCS.NS", 5)
        
        with patch.object(service, "_get_cached_data", new=AsyncMock(return_value=cached_df)) as mock_cache:
            df = await service.fetch_historical_data("TCS.NS", "2025-01-01", "2025-01-05", force_refresh=False)
            assert df is not None
            assert len(df) == 5
            mock_cache.assert_awaited_once_with("TCS.NS", "2025-01-01", "2025-01-05")

    async def test_fetch_historical_data_yfinance_success(self, test_db: AsyncSession):
        service = DataService(test_db)
        raw_df = pd.DataFrame({
            "Open": [100.0, 101.0],
            "High": [105.0, 106.0],
            "Low": [99.0, 100.0],
            "Close": [104.0, 105.0],
            "Adj Close": [104.0, 105.0],
            "Volume": [10000, 12000]
        }, index=pd.to_datetime(["2025-01-01", "2025-01-02"]))
        raw_df.index.name = "Date"
        
        with patch.object(service, "_get_cached_data", new=AsyncMock(return_value=None)), \
             patch.object(service, "_download_with_timeout", new=AsyncMock(return_value=raw_df)), \
             patch.object(service, "_store_timeseries_data", new=AsyncMock()) as mock_store:
            df = await service.fetch_historical_data("INFY.NS", "2025-01-01", "2025-01-02", force_refresh=True)
            assert df is not None
            assert len(df) == 2
            assert "close" in df.columns
            mock_store.assert_awaited_once()

    async def test_fetch_historical_data_yfinance_retries_and_av_fallback(self, test_db: AsyncSession):
        service = DataService(test_db)
        av_df = _sample_df("INFY.NS", 3)
        
        # All 3 attempts fail with exception, then calls Alpha Vantage fallback
        with patch.object(service, "_get_cached_data", new=AsyncMock(return_value=None)), \
             patch.object(service, "_download_with_timeout", new=AsyncMock(side_effect=Exception("Network error"))), \
             patch.object(service, "_fetch_from_alpha_vantage", new=AsyncMock(return_value=av_df)) as mock_av, \
             patch("asyncio.sleep", new=AsyncMock()):
            df = await service.fetch_historical_data("INFY.NS", "2025-01-01", "2025-01-03")
            assert df is not None
            assert len(df) == 3
            mock_av.assert_awaited_once()

    async def test_fetch_historical_data_all_sources_fail(self, test_db: AsyncSession):
        service = DataService(test_db)
        
        with patch.object(service, "_get_cached_data", new=AsyncMock(return_value=None)), \
             patch.object(service, "_download_with_timeout", new=AsyncMock(return_value=None)), \
             patch.object(service, "_fetch_from_alpha_vantage", new=AsyncMock(return_value=None)):
            df = await service.fetch_historical_data("NONEXISTENT.NS", "2025-01-01", "2025-01-03")
            assert df is None

    async def test_fetch_historical_data_exception_handling(self, test_db: AsyncSession):
        service = DataService(test_db)
        with patch.object(service, "_normalize_indian_ticker", side_effect=Exception("Fatal crash")):
            df = await service.fetch_historical_data("CRASH", "2025-01-01", "2025-01-03")
            assert df is None


@pytest.mark.asyncio
class TestDataServiceQuotesAndValidation:
    async def test_fetch_quote_success(self, test_db: AsyncSession):
        service = DataService(test_db)
        mock_stock = MagicMock()
        mock_stock.info = {
            "marketCap": 1000000000,
            "sector": "Technology",
            "industry": "IT Services",
            "fiftyTwoWeekHigh": 1800.0,
            "fiftyTwoWeekLow": 1300.0,
            "trailingPE": 25.5,
            "dividendYield": 0.02
        }
        mock_stock.fast_info = {"last_price": 1600.0}
        mock_stock.history.return_value = pd.DataFrame({
            "Close": [1590.0, 1600.0],
            "Volume": [500000, 600000]
        }, index=pd.to_datetime(["2025-01-01", "2025-01-02"]))
        
        with patch("yfinance.Ticker", return_value=mock_stock):
            quote = await service.fetch_quote("INFY.NS")
            assert quote is not None
            assert quote["ticker"] == "INFY.NS"
            assert quote["current_price"] == 1600.0
            assert quote["volume"] == 600000
            assert quote["currency"] == "INR"
            assert quote["exchange"] == "NSE"
            assert quote["is_indian"] is True

    async def test_fetch_quote_empty_history_fallback(self, test_db: AsyncSession):
        service = DataService(test_db)
        mock_stock = MagicMock()
        mock_stock.info = {}
        mock_stock.history.return_value = pd.DataFrame()
        
        with patch("yfinance.Ticker", return_value=mock_stock), \
             patch.object(service, "_fallback_quote", new=AsyncMock(return_value={"ticker": "AAPL", "current_price": 180.0})) as mock_fb:
            quote = await service.fetch_quote("AAPL")
            assert quote is not None
            assert quote["current_price"] == 180.0
            mock_fb.assert_awaited_once()

    async def test_fetch_quote_exception_fallback(self, test_db: AsyncSession):
        service = DataService(test_db)
        with patch("yfinance.Ticker", side_effect=Exception("API limit")), \
             patch.object(service, "_fallback_quote", new=AsyncMock(return_value={"ticker": "AAPL", "current_price": 185.0})):
            quote = await service.fetch_quote("AAPL")
            assert quote is not None
            assert quote["current_price"] == 185.0

    async def test_validate_ticker_paths(self, test_db: AsyncSession):
        service = DataService(test_db)
        
        # Valid ticker
        mock_stock_valid = MagicMock()
        mock_stock_valid.history.return_value = pd.DataFrame({"Close": [100.0]})
        with patch("yfinance.Ticker", return_value=mock_stock_valid):
            assert await service.validate_ticker("RELIANCE") is True
        
        # Empty data ticker
        mock_stock_empty = MagicMock()
        mock_stock_empty.history.return_value = pd.DataFrame()
        with patch("yfinance.Ticker", return_value=mock_stock_empty):
            assert await service.validate_ticker("INVALID") is False
            
        # Exception during validation
        with patch("yfinance.Ticker", side_effect=Exception("Failed")):
            assert await service.validate_ticker("EXCEPTION") is False

    async def test_get_corporate_actions(self, test_db: AsyncSession):
        service = DataService(test_db)
        mock_stock = MagicMock()
        mock_stock.splits = pd.Series([2.0], index=[pd.Timestamp("2024-01-01")])
        mock_stock.dividends = pd.Series([10.0], index=[pd.Timestamp("2024-06-01")])
        
        with patch("yfinance.Ticker", return_value=mock_stock):
            actions = await service.get_corporate_actions("TCS.NS")
            assert actions["ticker"] == "TCS.NS"
            assert len(actions["splits"]) == 1
            assert len(actions["dividends"]) == 1
            assert actions["is_indian"] is True

        # Empty actions
        mock_stock_empty = MagicMock()
        mock_stock_empty.splits = pd.Series([], dtype=float)
        mock_stock_empty.dividends = pd.Series([], dtype=float)
        with patch("yfinance.Ticker", return_value=mock_stock_empty):
            actions_empty = await service.get_corporate_actions("INFY.NS")
            assert actions_empty["splits"] == {}
            assert actions_empty["dividends"] == {}

        # Exception
        with patch("yfinance.Ticker", side_effect=Exception("Network error")):
            actions_err = await service.get_corporate_actions("FAIL.NS")
            assert actions_err["splits"] == {}
            assert actions_err["dividends"] == {}


@pytest.mark.asyncio
class TestDataServiceBatchAndTimeout:
    async def test_fetch_ohlcv_batch_mixed_results(self, test_db: AsyncSession):
        service = DataService(test_db)
        df_a = _sample_df("STOCKA.NS", 5)
        
        async def mock_fetch(ticker, start, end, force_refresh=False):
            if "FAIL" in ticker:
                return None
            if "ERROR" in ticker:
                raise Exception("Boom")
            return df_a
            
        with patch.object(service, "fetch_historical_data", side_effect=mock_fetch), \
             patch("asyncio.sleep", new=AsyncMock()):
            res = await service.fetch_ohlcv_batch(
                ["STOCKA.NS", "FAIL.NS", "ERROR.NS"],
                start_date="2025-01-01",
                end_date="2025-01-05"
            )
            assert "STOCKA.NS" in res["data"]
            assert "FAIL.NS" in res["failed_tickers"]
            assert "ERROR.NS" in res["failed_tickers"]

    async def test_download_with_timeout_branches(self, test_db: AsyncSession):
        service = DataService(test_db)
        
        # Success
        sample_df = _sample_df("INFY.NS", 2)
        with patch("asyncio.wait_for", new=AsyncMock(return_value=sample_df)):
            df = await service._download_with_timeout("INFY.NS", "2025-01-01", "2025-01-02")
            assert df is not None
            assert len(df) == 2

        # TimeoutError
        with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError())):
            assert await service._download_with_timeout("TIMEOUT.NS", "2025-01-01", "2025-01-02") is None

        # General Exception
        with patch("asyncio.wait_for", new=AsyncMock(side_effect=Exception("Failed"))):
            assert await service._download_with_timeout("ERROR.NS", "2025-01-01", "2025-01-02") is None


@pytest.mark.asyncio
class TestDataServiceAlphaVantageFallbacks:
    async def test_fetch_from_alpha_vantage_branches(self, test_db: AsyncSession):
        service = DataService(test_db)
        
        # Disabled
        mock_av_disabled = Mock(enabled=False)
        with patch("app.services.data_service.get_alpha_vantage_service", return_value=mock_av_disabled):
            assert await service._fetch_from_alpha_vantage("INFY.NS", "INFY.NS", "2025-01-01", "2025-01-02") is None
            
        # Exception thrown
        mock_av_err = Mock(enabled=True, fetch_daily_ohlcv=AsyncMock(side_effect=Exception("Rate limit")))
        with patch("app.services.data_service.get_alpha_vantage_service", return_value=mock_av_err):
            assert await service._fetch_from_alpha_vantage("INFY.NS", "INFY.NS", "2025-01-01", "2025-01-02") is None
            
        # Returns empty df
        mock_av_empty = Mock(enabled=True, fetch_daily_ohlcv=AsyncMock(return_value=pd.DataFrame()))
        with patch("app.services.data_service.get_alpha_vantage_service", return_value=mock_av_empty):
            assert await service._fetch_from_alpha_vantage("INFY.NS", "INFY.NS", "2025-01-01", "2025-01-02") is None
            
        # Success
        sample_df = _sample_df("INFY.NS", 3)
        mock_av_success = Mock(enabled=True, fetch_daily_ohlcv=AsyncMock(return_value=sample_df))
        with patch("app.services.data_service.get_alpha_vantage_service", return_value=mock_av_success), \
             patch.object(service, "_store_timeseries_data", new=AsyncMock()) as mock_store:
            df = await service._fetch_from_alpha_vantage("INFY.NS", "INFY.NS", "2025-01-01", "2025-01-03")
            assert df is not None
            assert len(df) == 3
            mock_store.assert_awaited_once()

    async def test_fallback_quote_branches(self, test_db: AsyncSession):
        service = DataService(test_db)
        
        # Disabled
        mock_av_disabled = Mock(enabled=False)
        with patch("app.services.data_service.get_alpha_vantage_service", return_value=mock_av_disabled):
            assert await service._fallback_quote("AAPL", "AAPL") is None
            
        # Exception
        mock_av_err = Mock(enabled=True, fetch_global_quote=AsyncMock(side_effect=Exception("Err")))
        with patch("app.services.data_service.get_alpha_vantage_service", return_value=mock_av_err):
            assert await service._fallback_quote("AAPL", "AAPL") is None
            
        # Empty quote
        mock_av_empty = Mock(enabled=True, fetch_global_quote=AsyncMock(return_value={}))
        with patch("app.services.data_service.get_alpha_vantage_service", return_value=mock_av_empty):
            assert await service._fallback_quote("AAPL", "AAPL") is None
            
        # Success
        mock_av_ok = Mock(enabled=True, fetch_global_quote=AsyncMock(return_value={"ticker": "RELIANCE.BSE", "current_price": 2500.0}))
        with patch("app.services.data_service.get_alpha_vantage_service", return_value=mock_av_ok):
            q = await service._fallback_quote("RELIANCE.NS", "RELIANCE.BSE")
            assert q is not None
            assert q["current_price"] == 2500.0
            assert q["is_indian"] is True


@pytest.mark.asyncio
class TestDataServiceNormalizationAndStorage:
    def test_normalize_yfinance_data_branches(self, test_db: AsyncSession):
        service = DataService(test_db)
        
        # Multi-index columns
        arrays = [["Open", "High", "Low", "Close", "Adj Close", "Volume"], ["TCS", "TCS", "TCS", "TCS", "TCS", "TCS"]]
        tuples = list(zip(*arrays))
        multi_index = pd.MultiIndex.from_tuples(tuples)
        df_multi = pd.DataFrame([[100, 105, 95, 102, 102, 1000]], index=pd.date_range("2025-01-01", periods=1), columns=multi_index)
        df_multi.index.name = "Date"
        normalized = service._normalize_yfinance_data(df_multi, "TCS.NS")
        assert not normalized.empty
        assert "close" in normalized.columns
        assert normalized["ticker"].iloc[0] == "TCS.NS"
        
        # Missing columns
        df_missing = pd.DataFrame({"Open": [100], "Close": [102]})
        assert service._normalize_yfinance_data(df_missing, "TEST").empty
        
        # Exception during normalization
        assert service._normalize_yfinance_data(None, "TEST").empty

    async def test_get_cached_data_and_errors(self, test_db: AsyncSession):
        service = DataService(test_db)
        
        # Nonexistent ticker
        assert await service._get_cached_data("NONEXISTENT", "2025-01-01", "2025-01-02") is None
        
        # Database exception
        with patch.object(test_db, "execute", side_effect=Exception("DB down")):
            assert await service._get_cached_data("FAIL", "2025-01-01", "2025-01-02") is None

    async def test_store_timeseries_data_and_upsert(self, test_db: AsyncSession):
        service = DataService(test_db)
        await test_db.execute(delete(StockTimeseries).where(StockTimeseries.ticker == "WIPRO.NS"))
        await test_db.commit()

        df = _sample_df("WIPRO.NS", 3)
        
        # Store records
        await service._store_timeseries_data("WIPRO.NS", df)
        
        # Verify stored in DB
        res = await test_db.execute(select(StockTimeseries).where(StockTimeseries.ticker == "WIPRO.NS"))
        rows = res.scalars().all()
        assert len(rows) == 3
        
        # Test upsert with updated prices
        df_updated = _sample_df("WIPRO.NS", 3)
        df_updated["close"] = [500.0, 505.0, 510.0]
        df_updated["open"] = [498.0, 503.0, 508.0]
        df_updated["high"] = [510.0, 515.0, 520.0]
        df_updated["low"] = [490.0, 495.0, 500.0]
        df_updated["adj_close"] = [500.0, 505.0, 510.0]
        await service._store_timeseries_data("WIPRO.NS", df_updated)
        test_db.expire_all()

        res_updated = await test_db.execute(
            select(StockTimeseries).where(StockTimeseries.ticker == "WIPRO.NS").order_by(StockTimeseries.date)
        )
        rows_updated = res_updated.scalars().all()
        assert len(rows_updated) == 3
        assert rows_updated[0].close == 500.0

        # Clean up
        await test_db.execute(delete(StockTimeseries).where(StockTimeseries.ticker == "WIPRO.NS"))
        await test_db.commit()

    async def test_store_timeseries_data_exception_rollback(self, test_db: AsyncSession):
        service = DataService(test_db)
        df = _sample_df("FAIL.NS", 2)
        
        with patch.object(test_db, "execute", side_effect=Exception("Disk full")):
            await service._store_timeseries_data("FAIL.NS", df)
            # Rollback handled cleanly without throwing

    def test_validate_timeseries_data_issues(self, test_db: AsyncSession):
        service = DataService(test_db)
        
        # Missing columns
        bad_df1 = pd.DataFrame({"open": [100]})
        errs = service._validate_timeseries_data(bad_df1)
        assert any("Missing required columns" in e for e in errs)
        
        # Negative values & invalid OHLC & extreme movement (>50%) & duplicate dates & nulls
        dates = [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-01")]
        bad_df2 = pd.DataFrame({
            "date": dates,
            "open": [-10.0, 100.0],
            "high": [50.0, 80.0],   # high < open
            "low": [60.0, 90.0],    # low > high
            "close": [100.0, 200.0], # extreme movement > 50%
            "adj_close": [100.0, None], # null value
            "volume": [1000, 2000]
        })
        errs2 = service._validate_timeseries_data(bad_df2)
        assert any("negative values" in e for e in errs2)
        assert any("invalid OHLC" in e for e in errs2)
        assert any("extreme price movements" in e for e in errs2)
        assert any("duplicate dates" in e for e in errs2)
        assert any("null values" in e for e in errs2)

    async def test_log_storage_metrics_and_error_analysis(self, test_db: AsyncSession):
        service = DataService(test_db)
        
        # High replacement ratio
        await service._log_storage_metrics("TCS.NS", stored_count=1, replaced_count=5)
        
        # Exception during log metrics
        with patch.object(test_db, "add", side_effect=Exception("Log fail")):
            await service._log_storage_metrics("TCS.NS", 1, 1)
            
        # Error analysis tests
        df = _sample_df("TEST", 2)
        service._analyze_storage_error("TEST", df, Exception("UNIQUE constraint failed: ..."))
        service._analyze_storage_error("TEST", df, Exception("NOT NULL constraint failed: ..."))
        service._analyze_storage_error("TEST", df, Exception("CHECK constraint failed: ..."))
        service._analyze_storage_error("TEST", df, Exception("Other random error"))
        service._analyze_storage_error("TEST", None, Exception("Crash analysis"))

    async def test_check_data_integrity(self, test_db: AsyncSession):
        service = DataService(test_db)
        
        # Specific ticker check
        res_ticker = await service.check_data_integrity(ticker="INFY.NS")
        assert res_ticker["ticker"] == "INFY.NS"
        assert res_ticker["integrity_status"] == "GOOD"
        
        # Entire database check
        res_db = await service.check_data_integrity()
        assert res_db["database_status"] == "GOOD"
        
        # Exception path
        with patch.object(test_db, "execute", side_effect=Exception("DB query fail")):
            res_err = await service.check_data_integrity(ticker="INFY.NS")
            assert res_err["status"] == "CHECK_FAILED"
