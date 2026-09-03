"""
Comprehensive test suite for AlphaVantageService, KeyPool, and CompanyDataService.
"""

from unittest.mock import AsyncMock, MagicMock, Mock, patch
from datetime import date, datetime
import pandas as pd
import pytest
import time
import requests
from yfinance.exceptions import YFRateLimitError

from app.services.alpha_vantage_service import (
    AlphaVantageService,
    KeyPool,
    _KeyBudget,
    _classify_notice,
    _configured_keys,
    to_av_symbol,
    get_alpha_vantage_service,
    AlphaVantageNotConfiguredError,
    AlphaVantageRateLimitError
)
from app.services.company_data_service import (
    CompanyDataService,
    _normalize,
    _yf_retry,
    get_company_data_service
)


class TestAlphaVantageServiceComprehensive:
    def test_to_av_symbol_conversions(self):
        assert to_av_symbol("RELIANCE.NS") == "RELIANCE.BSE"
        assert to_av_symbol("TCS.BO") == "TCS.BO"
        assert to_av_symbol("AAPL") == "AAPL"
        assert to_av_symbol("  msft  ") == "MSFT"

    def test_classify_notice_taxonomy(self):
        assert _classify_notice("Thank you for using Alpha Vantage! Our standard API call frequency is 5 calls per minute") == "frequency"
        assert _classify_notice("Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day") == "daily"
        assert _classify_notice("Invalid API key") == "invalid_key"
        assert _classify_notice("Please upgrade to premium") == "daily"
        assert _classify_notice("Some other informational text") == "other"

    def test_key_budget_logic(self):
        budget = _KeyBudget(key="demo_key", daily_limit=2, minute_limit=2)
        assert budget.available() is True
        assert budget.remaining_today() == 2

        budget.spend()
        assert budget.remaining_today() == 1

        budget.spend()
        assert budget.remaining_today() == 0
        assert budget.available() is False

        # Minute limit throttling
        budget2 = _KeyBudget(key="demo_key_2", daily_limit=100, minute_limit=1)
        budget2.spend()
        assert budget2.available() is False

        # Retired on today
        budget3 = _KeyBudget(key="demo_key_3", daily_limit=100, minute_limit=10)
        budget3.retired_on = date.today()
        assert budget3.available() is False

        # Cooldown active
        budget4 = _KeyBudget(key="demo_key_4", daily_limit=100, minute_limit=10)
        budget4.cooldown_until = time.monotonic() + 100
        assert budget4.available() is False

    def test_key_pool_operations(self):
        pool = KeyPool(keys=["key1", "key2"], daily_limit=5, minute_limit=2)
        assert pool.enabled is True
        assert pool.total_remaining_today() == 10

        b1 = pool.acquire()
        assert b1.key == "key1"
        b2 = pool.acquire()
        assert b2.key == "key2"

        pool.mark_daily_exhausted(b1)
        assert b1.available() is False

        pool.mark_frequency_limited(b2)
        assert b2.cooldown_until > time.monotonic()

        pool.drop_invalid(b1)
        assert len(pool.budgets) == 1

        # When all unavailable
        pool_empty = KeyPool(keys=[], daily_limit=5, minute_limit=2)
        assert pool_empty.enabled is False
        assert pool_empty.acquire() is None

    def test_configured_keys_helper(self):
        with patch("app.config.settings.alpha_vantage_api_key", "SINGLE_KEY"), \
             patch("app.config.settings.alpha_vantage_api_keys", "KEY_A, KEY_B; KEY_C"):
            keys = _configured_keys()
            assert "SINGLE_KEY" in keys
            assert "KEY_A" in keys
            assert "KEY_B" in keys
            assert "KEY_C" in keys

    @pytest.mark.asyncio
    async def test_make_request_handling(self):
        with patch("app.services.alpha_vantage_service._configured_keys", return_value=["key1"]):
            service = AlphaVantageService()

            # 1. Success response
            mock_resp = Mock(status_code=200)
            mock_resp.json.return_value = {"Global Quote": {"05. price": "150.0"}}
            with patch("requests.get", return_value=mock_resp):
                res = await service._make_request("GLOBAL_QUOTE", {"symbol": "AAPL"})
                assert "Global Quote" in res

            # 2. Rate limit notice daily
            mock_resp_daily = Mock(status_code=200)
            mock_resp_daily.json.return_value = {"Information": "requests per day limit reached"}
            with patch("requests.get", return_value=mock_resp_daily):
                with pytest.raises((AlphaVantageRateLimitError, AlphaVantageNotConfiguredError)):
                    await service._make_request("GLOBAL_QUOTE", {"symbol": "AAPL"})

            # 3. Rate limit notice frequency
            service.pool = KeyPool(["key2"], 10, 5)
            mock_resp_freq = Mock(status_code=200)
            mock_resp_freq.json.return_value = {"Note": "call frequency 5 calls per minute"}
            with patch("requests.get", return_value=mock_resp_freq):
                with pytest.raises((AlphaVantageRateLimitError, AlphaVantageNotConfiguredError)):
                    await service._make_request("GLOBAL_QUOTE", {"symbol": "AAPL"})

            # 4. Invalid key error
            service.pool = KeyPool(["key3"], 10, 5)
            mock_resp_err = Mock(status_code=200)
            mock_resp_err.json.return_value = {"Error Message": "the specified api key is invalid"}
            with patch("requests.get", return_value=mock_resp_err):
                with pytest.raises((AlphaVantageRateLimitError, AlphaVantageNotConfiguredError)):
                    await service._make_request("GLOBAL_QUOTE", {"symbol": "AAPL"})

            # 5. Unknown notice -> ValueError
            service.pool = KeyPool(["key4"], 10, 5)
            mock_resp_other = Mock(status_code=200)
            mock_resp_other.json.return_value = {"Information": "Unknown notice message"}
            with patch("requests.get", return_value=mock_resp_other):
                with pytest.raises(ValueError, match="Alpha Vantage notice"):
                    await service._make_request("GLOBAL_QUOTE", {"symbol": "AAPL"})

            # 6. Not configured error
            service_disabled = AlphaVantageService()
            service_disabled.pool = KeyPool([], 0, 0)
            with pytest.raises(AlphaVantageNotConfiguredError):
                await service_disabled._make_request("GLOBAL_QUOTE", {})

    @pytest.mark.asyncio
    async def test_fetch_daily_ohlcv_and_global_quote(self):
        with patch("app.services.alpha_vantage_service._configured_keys", return_value=["key1"]):
            service = AlphaVantageService()

            # fetch_daily_ohlcv success
            mock_ts = {
                "Time Series (Daily)": {
                    "2025-01-02": {"1. open": "100", "2. high": "105", "3. low": "98", "4. close": "104", "5. volume": "1000"},
                    "2025-01-01": {"1. open": "98", "2. high": "101", "3. low": "97", "4. close": "100", "5. volume": "800"}
                }
            }
            with patch.object(service, "_make_request", new=AsyncMock(return_value=mock_ts)):
                df = await service.fetch_daily_ohlcv("TCS.NS", "2025-01-01", "2025-01-02")
                assert df is not None
                assert len(df) == 2
                assert "close" in df.columns

            # fetch_daily_ohlcv empty
            with patch.object(service, "_make_request", new=AsyncMock(return_value={})):
                df_empty = await service.fetch_daily_ohlcv("TCS.NS", "2025-01-01", "2025-01-02")
                assert df_empty is None

            # fetch_global_quote success
            mock_gq = {
                "Global Quote": {
                    "01. symbol": "AAPL",
                    "05. price": "180.5",
                    "06. volume": "5000000",
                    "09. change": "2.5",
                    "10. change percent": "1.4%"
                }
            }
            with patch.object(service, "_make_request", new=AsyncMock(return_value=mock_gq)):
                q = await service.fetch_global_quote("AAPL")
                assert q is not None
                assert q["current_price"] == 180.5
                assert q["volume"] == 5000000

            # fetch_global_quote empty
            with patch.object(service, "_make_request", new=AsyncMock(return_value={})):
                q_empty = await service.fetch_global_quote("AAPL")
                assert q_empty is None

            # Global singleton
            assert get_alpha_vantage_service() is not None


class TestCompanyDataServiceComprehensive:
    def test_normalize_and_yf_retry(self):
        assert _normalize("INFY") == "INFY.NS"
        assert _normalize("AAPL") == "AAPL"

        # yf_retry success
        assert _yf_retry(lambda: 42) == 42

        # yf_retry retries on YFRateLimitError then succeeds
        attempts = [0]
        def flake():
            attempts[0] += 1
            if attempts[0] == 1:
                raise YFRateLimitError()
            return "ok"
        with patch("time.sleep"):
            assert _yf_retry(flake, max_retries=2, base_delay=0.01) == "ok"

    @pytest.mark.asyncio
    async def test_get_fundamentals(self):
        service = CompanyDataService()

        # Success
        mock_stock = MagicMock()
        mock_stock.info = {
            "longName": "Infosys Limited",
            "sector": "Technology",
            "industry": "IT Services",
            "marketCap": 80000000000,
            "trailingPE": 26.0
        }
        with patch("yfinance.Ticker", return_value=mock_stock):
            res = await service.get_fundamentals("INFY.NS")
            assert res["name"] == "Infosys Limited"
            assert res["sector"] == "Technology"
            assert res["pe_ratio_ttm"] == 26.0

        # Upstream 401 / crumb error
        with patch("yfinance.Ticker", side_effect=Exception("Invalid Crumb 401")):
            with pytest.raises(RuntimeError, match="Fundamentals upstream unavailable"):
                await service.get_fundamentals("INFY.NS")

        # Empty info
        mock_stock_empty = MagicMock()
        mock_stock_empty.info = {}
        with patch("yfinance.Ticker", return_value=mock_stock_empty):
            with pytest.raises(ValueError, match="No fundamentals returned"):
                await service.get_fundamentals("INFY.NS")

        # Stub info
        mock_stock_stub = MagicMock()
        mock_stock_stub.info = {"randomKey": "val"}
        with patch("yfinance.Ticker", return_value=mock_stock_stub):
            with pytest.raises(ValueError, match="No fundamental fields returned"):
                await service.get_fundamentals("INFY.NS")

    @pytest.mark.asyncio
    async def test_get_financial_statements(self):
        service = CompanyDataService()

        # Invalid statement or freq
        with pytest.raises(ValueError, match="statement must be one of"):
            await service.get_financial_statements("TCS.NS", statement="invalid")

        with pytest.raises(ValueError, match="freq must be"):
            await service.get_financial_statements("TCS.NS", freq="daily")

        # Success with curr_date filtering
        mock_stock = MagicMock()
        cols = [pd.Timestamp("2024-03-31"), pd.Timestamp("2024-06-30"), pd.Timestamp("2024-09-30")]
        mock_df = pd.DataFrame({
            cols[0]: [1000.0, 800.0],
            cols[1]: [1100.0, 850.0],
            cols[2]: [1200.0, 900.0]
        }, index=["Total Revenue", "Operating Expense"])
        mock_stock.quarterly_income_stmt = mock_df

        with patch("yfinance.Ticker", return_value=mock_stock):
            res = await service.get_financial_statements("TCS.NS", statement="income", freq="quarterly", curr_date="2024-07-01")
            assert res["ticker"] == "TCS.NS"
            assert len(res["periods"]) == 2
            assert "Total Revenue" in res["metrics"]

        # Empty statement data
        mock_stock_empty = MagicMock()
        mock_stock_empty.quarterly_income_stmt = pd.DataFrame()
        with patch("yfinance.Ticker", return_value=mock_stock_empty):
            with pytest.raises(ValueError, match="No income statement data"):
                await service.get_financial_statements("TCS.NS", statement="income", freq="quarterly")

    @pytest.mark.asyncio
    async def test_get_insider_transactions(self):
        service = CompanyDataService()

        # Empty insider transactions
        mock_stock_empty = MagicMock()
        mock_stock_empty.insider_transactions = None
        with patch("yfinance.Ticker", return_value=mock_stock_empty):
            assert await service.get_insider_transactions("AAPL") == []

        # Populated insider transactions
        mock_stock = MagicMock()
        mock_df = pd.DataFrame([
            {"Date": pd.Timestamp("2025-01-15"), "Insider": "Cook Tim", "Shares": 50000, "Notes": None}
        ])
        mock_stock.insider_transactions = mock_df
        with patch("yfinance.Ticker", return_value=mock_stock):
            txs = await service.get_insider_transactions("AAPL")
            assert len(txs) == 1
            assert txs[0]["Insider"] == "Cook Tim"
            assert txs[0]["Notes"] is None

        # Global singleton
        assert get_company_data_service() is not None
