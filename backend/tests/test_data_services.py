"""
Service-level tests for the TradingAgents-adopted data services (t21):
indicators_service (pure compute on frames) and company_data_service
(yfinance seam mocked — no network).
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pandas as pd
import pytest

from app.services.indicators_service import (
    IndicatorsService,
    StaleMarketDataError,
    _clean_dataframe,
    _compute_sync,
    assert_not_stale,
)
from app.services.company_data_service import CompanyDataService, _normalize


def _ohlcv_frame(days=200, end="2026-08-20", seed=3):
    dates = pd.date_range(end=end, periods=days, freq="B")
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, days)))
    return pd.DataFrame({
        "Date": dates,
        "Open": close * 0.995,
        "High": close * 1.008,
        "Low": close * 0.992,
        "Close": close,
        "Volume": rng.integers(1_000, 50_000, days).astype(float),
    })


@pytest.mark.api
class TestIndicatorsPure:
    def test_clean_dataframe_normalizes_columns(self):
        raw = _ohlcv_frame().rename(columns={
            "Date": "date", "Open": "open", "High": "high",
            "Low": "low", "Close": "close", "Volume": "volume",
        })
        df = _clean_dataframe(raw)
        for col in ("Date", "Open", "High", "Low", "Close", "Volume"):
            assert col in df.columns

    def test_assert_not_stale_rejects_old_data(self):
        df = _ohlcv_frame(end="2026-07-01")
        with pytest.raises(StaleMarketDataError):
            assert_not_stale(df, "2026-08-20")

    def test_assert_not_stale_accepts_fresh_data(self):
        df = _ohlcv_frame(end="2026-08-19")
        assert_not_stale(df, "2026-08-20")

    def test_compute_sync_keeps_base_columns_and_adds_indicators(self):
        df = _clean_dataframe(_ohlcv_frame())
        out = _compute_sync(df, ["close_13_ema", "close_50_sma"])
        assert len(out) == len(df)
        for col in ("Date", "Close", "Volume"):
            assert col in out.columns
        assert out["close_13_ema"].notna().sum() > 100
        # EMA tracks close closely on smooth series
        last = out.iloc[-1]
        assert abs(last["close_13_ema"] - last["Close"]) / last["Close"] < 0.05


@pytest.mark.asyncio
class TestIndicatorsServiceWindow:
    def _service(self, frame=None):
        seam = Mock()
        seam.fetch_historical_data = AsyncMock(
            return_value=frame if frame is not None else _ohlcv_frame()
        )
        with patch("app.services.indicators_service.DataService", return_value=seam):
            yield IndicatorsService(db_session=Mock())

    async def test_unknown_indicator_raises_value_error(self):
        gen = self._service()
        svc = next(gen)
        with pytest.raises(ValueError, match="Unsupported indicators"):
            await svc.compute_window("TEST.NS", ["moon_phase"])

    async def test_empty_frame_raises_value_error(self):
        gen = self._service(frame=pd.DataFrame())
        svc = next(gen)
        with pytest.raises(ValueError, match="No OHLCV data"):
            await svc.compute_window("TEST.NS")

    async def test_compute_window_shape_and_values(self):
        gen = self._service()
        svc = next(gen)
        out = await svc.compute_window("TEST.NS", ["close_10_ema"], lookback_days=30,
                                       end_date="2026-08-20")
        assert out["ticker"] == "TEST.NS"
        assert out["indicators"] == ["close_10_ema"]
        assert len(out["records"]) >= 20
        rec = out["records"][-1]
        assert rec["date"] <= "2026-08-20"
        assert rec["close"] > 0
        assert rec["close_10_ema"] is not None

    async def test_verified_snapshot_shape(self):
        gen = self._service()
        svc = next(gen)
        out = await svc.verified_snapshot("TEST.NS", end_date="2026-08-20", look_back_days=10)
        assert out["snapshot_date"] <= "2026-08-20"
        assert len(out["recent_closes"]) <= 10
        assert "close" in out["latest_row"]


@pytest.mark.api
class TestCompanyDataService:
    def test_normalize_bridges_plain_ticker(self):
        assert _normalize("RELIANCE") == "RELIANCE.NS"
        assert _normalize("reliance.ns") == "RELIANCE.NS"

    async def test_fundamentals_maps_curated_fields(self):
        info = {
            "longName": "Reliance Industries",
            "sector": "Energy",
            "marketCap": 1_900_000_000_000,
            "trailingPE": 24.5,
            "beta": 0.9,
        }
        with patch("yfinance.Ticker", return_value=Mock(info=info)):
            out = await CompanyDataService().get_fundamentals("RELIANCE")
        assert out["ticker"] == "RELIANCE.NS"
        assert out["name"] == "Reliance Industries"
        assert out["sector"] == "Energy"
        assert out["pe_ratio_ttm"] == 24.5
        assert "dividend_yield" not in out  # missing yf fields dropped

    async def test_fundamentals_stub_info_raises_value_error(self):
        with patch("yfinance.Ticker", return_value=Mock(info={"symbol": "RELIANCE.NS"})):
            with pytest.raises(ValueError, match="No fundamental fields"):
                await CompanyDataService().get_fundamentals("RELIANCE")

    async def test_fundamentals_upstream_failure_raises_runtime_error(self):
        with patch("yfinance.Ticker", side_effect=RuntimeError("401 Invalid Crumb")):
            with pytest.raises(RuntimeError, match="upstream unavailable"):
                await CompanyDataService().get_fundamentals("RELIANCE")

    async def test_statements_validation(self):
        svc = CompanyDataService()
        with pytest.raises(ValueError, match="statement must be"):
            await svc.get_financial_statements("X", statement="psychic")
        with pytest.raises(ValueError, match="freq must be"):
            await svc.get_financial_statements("X", freq="weekly")

    async def test_statements_lookahead_filter(self):
        past1 = pd.Timestamp("2026-03-31")
        past2 = pd.Timestamp("2025-12-31")
        future = pd.Timestamp("2026-12-31")
        frame = pd.DataFrame(
            {past1: [100.0, 10.0], past2: [90.0, 9.0], future: [999.0, 99.0]},
            index=["Total Revenue", "Net Income"],
        )
        ticker_mock = Mock()
        ticker_mock.quarterly_income_stmt = frame
        with patch("yfinance.Ticker", return_value=ticker_mock):
            out = await CompanyDataService().get_financial_statements(
                "TEST", statement="income", freq="quarterly", curr_date="2026-06-30"
            )
        assert set(out["metrics"]["Total Revenue"].keys()) == {"2026-03-31", "2025-12-31"}
        assert out["metrics"]["Total Revenue"]["2026-03-31"] == 100.0

    async def test_statements_empty_raises_value_error(self):
        ticker_mock = Mock()
        ticker_mock.quarterly_income_stmt = pd.DataFrame()
        with patch("yfinance.Ticker", return_value=ticker_mock):
            with pytest.raises(ValueError, match="No income statement"):
                await CompanyDataService().get_financial_statements("TEST")
