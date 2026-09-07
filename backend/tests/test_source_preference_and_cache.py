"""
Tests for user-selectable primary data source (DSP-01..DSP-05).

Covers:
- Source preference store: default, roundtrip, validation, cascade order
- DataService cascade honoring the preference for OHLCV and quotes
  (primary first, other vendor second, Alpha Vantage always last)
- Config API roundtrip (GET/PUT /data/config, 400 on invalid vendor)
- Cache purge endpoint wiping market-data stores while preserving
  portfolio positions (holdings truth)
- Fundamentals cascade in company_data_service
"""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select, func

from app.models.database import (
    AnalyticsCache, AppSetting, FetchLog, PortfolioPosition, StockTimeseries,
)
from app.services.company_data_service import CompanyDataService
from app.services.data_service import DataService
from app.services.source_preference_service import (
    DEFAULT_PRIMARY_SOURCE, PREFERENCE_KEY, get_primary_source,
    set_primary_source, source_order_for, validate_source,
)


# ---------------------------------------------------------------------------
# helpers / fixtures

def _yf_style_df(ticker: str = "RELIANCE.NS", days: int = 5) -> pd.DataFrame:
    """Raw vendor-style frame (TitleCase columns, 'Date'-named DatetimeIndex,
    exactly how bfinance/yfinance hand frames to _normalize_yfinance_data)."""
    dates = pd.date_range("2025-01-01", periods=days, freq="B")
    close = np.linspace(2500.0, 2540.0, days)
    df = pd.DataFrame(
        {
            "Open": close * 0.99,
            "High": close * 1.01,
            "Low": close * 0.98,
            "Close": close,
            "Adj Close": close,
            "Volume": np.full(days, 100000),
        },
        index=dates,
    )
    df.index.name = "Date"
    return df


def _lower_df(days: int = 5) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=days, freq="B")
    close = np.linspace(100.0, 104.0, days)
    return pd.DataFrame(
        {
            "date": dates,
            "open": close * 0.99,
            "high": close * 1.01,
            "low": close * 0.98,
            "close": close,
            "adj_close": close,
            "volume": np.full(days, 1000),
            "ticker": "RELIANCE.NS",
        }
    )


class _FakeAVService:
    """Alpha Vantage stand-in recording whether it was consulted."""

    def __init__(self, enabled: bool = True, df: pd.DataFrame | None = None):
        self.enabled = enabled
        self.df = df
        self.ohlcv_calls: list = []

    async def fetch_daily_ohlcv(self, ticker, start, end):
        self.ohlcv_calls.append((ticker, start, end))
        return self.df


class _FakeBfTicker:
    """bfinance.Ticker stand-in with fast_info/info surface."""

    last_price_val = 2600.5

    def __init__(self, symbol):
        self.symbol = symbol
        self.fast_info = SimpleNamespace(
            last_price=type(self).last_price_val,
            last_volume=12345,
            market_cap=8.9e12,
            year_high=2800.0,
            year_low=2200.0,
        )
        self.info = {
            "sector": "Energy",
            "industry": "Oil & Gas Refineries",
            "trailingPE": 24.5,
            "dividendYield": 0.8,
            "currentPrice": 0,  # force fast_info to be the price source
        }


@pytest.fixture(autouse=True)
def _clear_in_memory_caches():
    """Class-level memo caches must not leak across tests."""
    DataService._in_memory_df_cache.clear()
    yield
    DataService._in_memory_df_cache.clear()


# ---------------------------------------------------------------------------
# 1. preference store

class TestSourcePreferenceStore:
    async def test_default_when_unset(self, test_db):
        assert await get_primary_source(test_db) == DEFAULT_PRIMARY_SOURCE == "bfinance"

    async def test_roundtrip_persists(self, test_db):
        await set_primary_source(test_db, "yfinance")
        assert await get_primary_source(test_db) == "yfinance"

        rows = (await test_db.execute(
            select(AppSetting).where(AppSetting.key == PREFERENCE_KEY)
        )).scalars().all()
        assert len(rows) == 1, "upsert must keep a single preference row"
        assert rows[0].value == "yfinance"

        # switching vendors overwrites in place
        await set_primary_source(test_db, "bfinance")
        rows = (await test_db.execute(
            select(AppSetting).where(AppSetting.key == PREFERENCE_KEY)
        )).scalars().all()
        assert len(rows) == 1 and rows[0].value == "bfinance"

    async def test_rejection_of_non_interchangeable_vendor(self, test_db):
        with pytest.raises(ValueError):
            await set_primary_source(test_db, "alphavantage")
        with pytest.raises(ValueError):
            validate_source("not-a-vendor")

    async def test_cascade_orders(self):
        assert source_order_for("bfinance") == ["bfinance", "yfinance"]
        assert source_order_for("yfinance") == ["yfinance", "bfinance"]


# ---------------------------------------------------------------------------
# 2. OHLCV cascade

class TestHistoricalCascade:
    START, END = "2025-01-01", "2025-01-10"

    @staticmethod
    def _empty_download(*a, **k):
        # Plain function on purpose: a Mock here would flip the is_yf_mocked
        # guard inside _download_with_timeout and silently skip bfinance.
        return pd.DataFrame()

    async def test_bfinance_primary_hits_bfinance_first(self, test_db):
        await set_primary_source(test_db, "bfinance")
        service = DataService(test_db)

        bf_df = _yf_style_df()
        with patch("bfinance.download", Mock(return_value=bf_df)) as bf_dl, \
             patch("app.services.data_service.yf.download", self._empty_download):
            df = await service.fetch_historical_data("RELIANCE.NS", self.START, self.END, force_refresh=True)

        assert df is not None and not df.empty
        bf_dl.assert_called_once()

        rows = (await test_db.execute(select(StockTimeseries))).scalars().all()
        assert rows, "fetched frame must be cached"
        assert all(r.source_used == "bfinance" for r in rows)

    async def test_yfinance_primary_skips_bfinance(self, test_db):
        await set_primary_source(test_db, "yfinance")
        service = DataService(test_db)

        yf_df = _yf_style_df()
        with patch("bfinance.download") as bf_dl, \
             patch("app.services.data_service.yf.download", Mock(return_value=yf_df)):
            df = await service.fetch_historical_data("RELIANCE.NS", self.START, self.END, force_refresh=True)

        assert df is not None and not df.empty
        bf_dl.assert_not_called()

        rows = (await test_db.execute(select(StockTimeseries))).scalars().all()
        assert rows
        assert all(r.source_used == "yfinance" for r in rows)

    async def test_yfinance_failure_falls_back_to_bfinance(self, test_db):
        await set_primary_source(test_db, "yfinance")
        service = DataService(test_db)

        bf_df = _yf_style_df()
        with patch("bfinance.download", Mock(return_value=bf_df)) as bf_dl, \
             patch("app.services.data_service.yf.download", self._empty_download):
            df = await service.fetch_historical_data("RELIANCE.NS", self.START, self.END, force_refresh=True)

        assert df is not None and not df.empty
        bf_dl.assert_called_once()
        rows = (await test_db.execute(select(StockTimeseries))).scalars().all()
        assert rows
        assert all(r.source_used == "bfinance" for r in rows)

    async def test_alpha_vantage_is_always_last(self, test_db):
        await set_primary_source(test_db, "yfinance")
        service = DataService(test_db)

        av = _FakeAVService(enabled=True, df=_lower_df())
        call_order = []

        def _bf_dl(*a, **k):
            call_order.append("bfinance")
            return pd.DataFrame()

        def _yf_dl(*a, **k):
            call_order.append("yfinance")
            return pd.DataFrame()

        with patch("bfinance.download", _bf_dl), \
             patch("app.services.data_service.yf.download", _yf_dl), \
             patch("app.services.data_service.get_alpha_vantage_service", return_value=av):
            df = await service.fetch_historical_data("RELIANCE.NS", self.START, self.END, force_refresh=True)

        assert df is not None and not df.empty
        assert av.ohlcv_calls, "Alpha Vantage must be consulted when both vendors fail"
        assert call_order == ["yfinance", "bfinance"] * 3  # primary then secondary, each retry


# ---------------------------------------------------------------------------
# 3. quote cascade

class TestQuoteCascade:
    async def test_bfinance_primary_uses_bfinance_quote(self, test_db):
        await set_primary_source(test_db, "bfinance")
        service = DataService(test_db)

        class _NeverYf:
            def __init__(self, *a, **k):
                raise AssertionError("yfinance must not be called when bfinance succeeds")

        with patch("bfinance.Ticker", _FakeBfTicker), \
             patch("app.services.data_service.yf.Ticker", _NeverYf):
            quote = await service.fetch_quote("RELIANCE.NS")

        assert quote is not None
        assert quote["current_price"] == pytest.approx(2600.5)
        assert quote["exchange"] == "NSE"

    async def test_yfinance_primary_uses_yfinance_quote(self, test_db):
        await set_primary_source(test_db, "yfinance")
        service = DataService(test_db)

        class _FakeYfTicker:
            def __init__(self, symbol):
                self.fast_info = SimpleNamespace(
                    last_price=2501.0, last_volume=99, market_cap=9e12,
                    year_high=2700.0, year_low=2300.0,
                )
                self.info = {"sector": "Energy", "trailingPE": 23.1}

        bf_calls = []
        bf_orig = _FakeBfTicker

        def _spy_bf(symbol):
            bf_calls.append(symbol)
            return bf_orig(symbol)

        with patch("bfinance.Ticker", _spy_bf), \
             patch("app.services.data_service.yf.Ticker", _FakeYfTicker):
            quote = await service.fetch_quote("RELIANCE.NS")

        assert quote is not None
        assert quote["current_price"] == pytest.approx(2501.0)
        assert bf_calls == [], "bfinance must not be called when yfinance succeeds"

    async def test_yfinance_empty_falls_back_to_bfinance_quote(self, test_db):
        await set_primary_source(test_db, "yfinance")
        service = DataService(test_db)

        class _EmptyYfTicker:
            def __init__(self, symbol):
                self.fast_info = None
                self.info = {}

            def history(self, period=None):
                return pd.DataFrame()

        with patch("bfinance.Ticker", _FakeBfTicker), \
             patch("app.services.data_service.yf.Ticker", _EmptyYfTicker):
            quote = await service.fetch_quote("RELIANCE.NS")

        assert quote is not None
        assert quote["current_price"] == pytest.approx(2600.5)


# ---------------------------------------------------------------------------
# 4. fundamentals cascade

class _FakeBfProfileTicker:
    """bfinance.Ticker stand-in for fundamentals: ratios live on the profile,
    score/valuation helpers on the ticker (mirrors real bfinance layout)."""

    def __init__(self, symbol):
        self.info = {}
        self.piotroski_score = 7
        self.graham_number = 1900.0
        self.enterprise_value = 9.1e12
        self.ev_to_ebitda = 11.3
        self.interest_coverage = 12.0
        self._profile = SimpleNamespace(
            name="Reliance Industries", sector="Energy", industry_group="Energy",
            industry="Oil & Gas Refineries", sub_industry="Refineries",
            indices=["NIFTY 50"], about="Conglomerate.", analysis=None,
            ratios=SimpleNamespace(
                market_cap=8.9e12, stock_pe=24.5, peg_ratio=1.2, price_to_book=3.1,
                current_price=2600.0, book_value=840.0, eps_ttm=106.0, dividend_yield=0.8,
                high_52w=2800.0, low_52w=2200.0, roe=13.5, roce=16.2,
                debt_to_equity=0.4, face_value=10.0,
            ),
        )

    def _ensure_profile(self):
        return self._profile


class TestFundamentalsCascade:
    async def test_yfinance_first_does_not_touch_bfinance(self):
        class _FakeYfTicker:
            def __init__(self, symbol):
                pass
            @property
            def info(self):
                return {
                    "longName": "Reliance Industries Limited",
                    "trailingPE": 23.9,
                    "marketCap": 8.8e12,
                }

        class _NeverBf:
            def __init__(self, *a, **k):
                raise AssertionError("bfinance must not be called when yfinance succeeds first")

        with patch("bfinance.Ticker", _NeverBf):
            # yfinance.Ticker is imported inside get_fundamentals; patch the module attr
            import yfinance as yf_mod
            with patch.object(yf_mod, "Ticker", _FakeYfTicker):
                out = await CompanyDataService().get_fundamentals(
                    "RELIANCE.NS", source_order=["yfinance", "bfinance"]
                )

        assert out["name"] == "Reliance Industries Limited"
        assert out["pe_ratio_ttm"] == pytest.approx(23.9)

    async def test_bfinance_first_returns_bf_taxonomy(self):
        class _NeverYf:
            def __init__(self, *a, **k):
                raise AssertionError("yfinance must not be called when bfinance succeeds first")

        import yfinance as yf_mod
        with patch("bfinance.Ticker", _FakeBfProfileTicker), \
             patch.object(yf_mod, "Ticker", _NeverYf):
            out = await CompanyDataService().get_fundamentals(
                "RELIANCE.NS", source_order=["bfinance", "yfinance"]
            )

        assert out["name"] == "Reliance Industries"
        assert out["industry_group"] == "Energy"
        assert out["piotroski_score"] == 7

    async def test_yfinance_failure_falls_through_to_bfinance(self):
        class _BrokenYf:
            def __init__(self, *a, **k):
                raise RuntimeError("crumb 401")

        import yfinance as yf_mod
        with patch("bfinance.Ticker", _FakeBfProfileTicker), \
             patch.object(yf_mod, "Ticker", _BrokenYf):
            out = await CompanyDataService().get_fundamentals(
                "RELIANCE.NS", source_order=["yfinance", "bfinance"]
            )

        assert out["name"] == "Reliance Industries"

    async def test_all_vendors_exhausted_raises_value_error(self):
        class _EmptyYf:
            def __init__(self, symbol):
                pass
            @property
            def info(self):
                return {}

        class _NoProfileBf:
            def __init__(self, symbol):
                pass
            def _ensure_profile(self):
                return None

        import yfinance as yf_mod
        with patch("bfinance.Ticker", _NoProfileBf), \
             patch.object(yf_mod, "Ticker", _EmptyYf):
            with pytest.raises(ValueError):
                await CompanyDataService().get_fundamentals(
                    "RELIANCE.NS", source_order=["yfinance", "bfinance"]
                )


# ---------------------------------------------------------------------------
# 5. config API roundtrip + cache purge

class TestConfigAPI:
    async def test_get_config_default(self, async_client):
        resp = await async_client.get("/api/v1/data/config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["primary_source"] == "bfinance"
        assert "cache_ttl_minutes" in body and "enable_cache" in body

    async def test_put_config_roundtrip(self, async_client):
        resp = await async_client.put("/api/v1/data/config", params={"primary_source": "yfinance"})
        assert resp.status_code == 200
        assert resp.json()["settings"]["primary_source"] == "yfinance"

        resp = await async_client.get("/api/v1/data/config")
        assert resp.json()["primary_source"] == "yfinance"

    async def test_put_config_rejects_alphavantage(self, async_client):
        resp = await async_client.put("/api/v1/data/config", params={"primary_source": "alphavantage"})
        assert resp.status_code == 400
        assert "Unsupported primary data source" in resp.json()["detail"]


class TestCachePurgeAPI:
    async def test_clear_wipes_cache_preserves_positions(self, async_client, test_db):
        # Seed user-owned holdings and cache rows
        test_db.add_all([
            PortfolioPosition(ticker="RELIANCE.NS", weight=0.6, quantity=10, buy_price=2500.0),
            PortfolioPosition(ticker="TCS.NS", weight=0.4, quantity=5, buy_price=3800.0),
        ])
        d = pd.Timestamp("2025-01-02").to_pydatetime()
        test_db.add_all([
            StockTimeseries(ticker="RELIANCE.NS", date=d, open=1, high=2, low=0.5, close=1.5,
                            adj_close=1.5, volume=10, source_used="bfinance"),
            StockTimeseries(ticker="RELIANCE.NS", date=pd.Timestamp("2025-01-03").to_pydatetime(),
                            open=1, high=2, low=0.5, close=1.6, adj_close=1.6, volume=10,
                            source_used="yfinance"),
        ])
        test_db.add(AnalyticsCache(ticker="RELIANCE.NS", metric_name="sharpe", metric_value=1.2,
                                   calculation_date=d, expires_at=d))
        test_db.add(FetchLog(ticker="RELIANCE.NS", status="success", source_used="bfinance"))
        await test_db.commit()

        resp = await async_client.post("/api/v1/data/cache/clear")
        assert resp.status_code == 200
        body = resp.json()
        assert body["portfolio_preserved"] is True
        assert body["cleared"]["stock_timeseries"] == 2
        assert body["cleared"]["analytics_cache"] == 1
        assert body["cleared"]["fetch_logs"] == 1
        assert body["total_rows_cleared"] == 4

        # Holdings truth survives; market data gone
        positions = (await test_db.execute(select(PortfolioPosition))).scalars().all()
        assert {p.ticker for p in positions} == {"RELIANCE.NS", "TCS.NS"}
        assert all(p.buy_price > 0 for p in positions)

        for model in (StockTimeseries, AnalyticsCache, FetchLog):
            count = (await test_db.execute(select(func.count()).select_from(model))).scalar()
            assert count == 0

    async def test_clear_is_idempotent(self, async_client):
        resp1 = await async_client.post("/api/v1/data/cache/clear")
        resp2 = await async_client.post("/api/v1/data/cache/clear")
        assert resp1.status_code == resp2.status_code == 200
        assert resp2.json()["total_rows_cleared"] == 0
