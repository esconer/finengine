"""
Wave 2 verification: Real endpoints, Factor Exposure, FX, Performance History,
and full Empty -> Populated portfolio lifecycle transitions.
"""

from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime
import numpy as np
import pandas as pd
import pytest
from sqlalchemy import delete

from app.models.database import PortfolioPosition, StockTimeseries
from app.services.currency_service import CurrencyConversionService
from app.services.analytics_engine import AnalyticsEngine

# The no-book concentration shape is one contract, derived once in
# `test_concentration_empty_hhi_absent.py`. This file used to hand-write
# `largest_position == 0.0` for the empty half of this transition, which is a
# number no book can measure - and a hand-written key is checked against
# nothing but itself, so it survived the shape moving under it.
from tests.test_concentration_empty_hhi_absent import (
    WITHHELD_ON_AN_EMPTY_BOOK,
    ZERO_VALUED_ON_AN_EMPTY_BOOK,
)


def _make_ohlcv(days=120, seed=42, ticker="TCS.NS", base_price=3000.0):
    dates = pd.date_range("2025-01-01", periods=days, freq="B")
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0005, 0.015, days)
    prices = base_price * np.cumprod(1.0 + returns)
    return pd.DataFrame({
        "date": dates,
        "open": prices * 0.995,
        "high": prices * 1.01,
        "low": prices * 0.99,
        "close": prices,
        "adj_close": prices,
        "Volume": np.full(days, 500_000),
        "volume": np.full(days, 500_000),
        "ticker": ticker,
    })


def _benchmark_returns(days=400, seed=11):
    """Synthetic ^NSEI daily returns for the mocked BenchmarkService.

    Seeded so the benchmark leg of the analytics endpoints is reproducible.
    """
    index = pd.date_range("2024-01-01", periods=days, freq="B")
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0004, 0.011, days), index=index)


@pytest.mark.asyncio
async def test_currency_conversion_live_fx_or_fallback():
    """W2#6: Test USDINR=X retrieval and graceful fallback."""
    service = CurrencyConversionService()

    # _fetch_exchange_rate returns (rate, is_fallback) since the B-07 never-cache rule
    with patch.object(service, "_fetch_exchange_rate", return_value=(83.5, False)):
        converted = await service.convert_amount(100.0, "USD", "INR")
        assert converted == pytest.approx(8350.0)

        usd = await service.convert_amount(8350.0, "INR", "USD")
        assert usd == pytest.approx(100.0)


@pytest.mark.asyncio
async def test_factor_exposure_statistical_model():
    """W2#7: Test factor exposure regression against benchmark returns."""
    engine = AnalyticsEngine()
    
    dates = pd.date_range("2025-01-01", periods=100, freq="B")
    bench_returns = pd.Series(np.random.normal(0.0005, 0.01, 100), index=dates)
    
    # Asset with beta ~ 1.5
    asset_returns = 1.5 * bench_returns + np.random.normal(0.0001, 0.005, 100)
    prices = 100.0 * np.cumprod(1.0 + asset_returns)
    price_df = pd.DataFrame({"INFY.NS": prices}, index=dates)
    
    result = await engine.factor_exposure_analysis(
        price_data=price_df,
        benchmark_data=bench_returns,
        weights={"INFY.NS": 1.0}
    )
    
    assert "portfolio" in result
    assert "alpha" in result["portfolio"]
    assert "market" in result["portfolio"]
    assert result["portfolio"]["market"] == pytest.approx(1.5, abs=0.2)
    assert result["r_squared"] > 0.5
    for fake in ["momentum", "size", "value", "min_vol", "quality", "rates", "volatility", "meme", "ai"]:
        assert fake not in result["portfolio"]


@pytest.mark.api
class TestEmptyToPopulatedTransition:
    """
    Test every endpoint under empty DB state, then add positions and test populated state.
    Proves zero 500 errors occur across state transitions.
    """

    @pytest.mark.asyncio
    async def test_lifecycle_empty_to_populated(self, async_client, test_db):
        # Clear positions to ensure 100% empty DB state initially
        await test_db.execute(delete(StockTimeseries))
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        # 1. Health check endpoints
        health_resp = await async_client.get("/health")
        assert health_resp.status_code == 200
        assert health_resp.json()["status"] == "healthy"

        v1_health = await async_client.get("/api/v1/health")
        assert v1_health.status_code == 200
        assert v1_health.json()["status"] == "healthy"

        # 2. Empty state queries on analytics endpoints (must never 500)
        # factor-exposure, summary, performance-history and risk-score each take
        # BenchmarkService as an injected dependency, so on an empty book they
        # still resolved ^NSEI against the live vendor. Mocked here so no unit
        # test performs real network I/O.
        bench = Mock()
        bench.get_benchmark_df = AsyncMock(return_value=None)
        bench.get_returns = AsyncMock(return_value=_benchmark_returns())
        with patch("app.api.analytics.BenchmarkService", return_value=bench):
            rr_resp = await async_client.get("/api/v1/analytics/realized-risk")
            assert rr_resp.status_code == 200
            assert "error" in rr_resp.json() or "portfolio" in rr_resp.json()

            fr_resp = await async_client.get("/api/v1/analytics/forecast-risk")
            assert fr_resp.status_code == 200
            assert "portfolio" in fr_resp.json()

            fe_resp = await async_client.get("/api/v1/analytics/factor-exposure")
            assert fe_resp.status_code == 200
            fe_body = fe_resp.json()
            assert fe_body["portfolio"]["market"] is None
            assert "error" in fe_body

            conc_resp = await async_client.get("/api/v1/analytics/concentration")
            assert conc_resp.status_code == 200
            conc_empty = conc_resp.json()
            # The empty half of the transition must not merely answer 200 - it
            # must be a state a reader can tell apart from the populated half
            # asserted below. Every concentration statistic is withheld rather
            # than published as 0.0: `largest_position` was the one this file
            # hand-copied, and 0.0 is not a value any book produces on that
            # field, so it identified nothing. Looped from the derived list so
            # the remaining eight cannot drift the way that one did.
            for key in WITHHELD_ON_AN_EMPTY_BOOK:
                assert key in conc_empty, f"{key} was dropped from the no-book shape"
                assert conc_empty[key] is None, (
                    f"the route published {conc_empty[key]!r} for {key} on a book "
                    "with no holdings, so the empty state reads as a measured one"
                )
            # The count is what actually carries the transition, because a count
            # of zero is a measurement and the numbers above are not.
            for key in ZERO_VALUED_ON_AN_EMPTY_BOOK:
                assert key in conc_empty, f"{key} was dropped from the no-book shape"
                assert conc_empty[key] == 0, (
                    f"{key} must stay 0 on an empty book, got {conc_empty[key]!r}"
                )

            liq_resp = await async_client.get("/api/v1/analytics/liquidity")
            assert liq_resp.status_code == 200

            sum_resp = await async_client.get("/api/v1/analytics/summary")
            assert sum_resp.status_code == 200
            assert sum_resp.json()["total_positions"] == 0

            ph_resp = await async_client.get("/api/v1/analytics/performance-history")
            assert ph_resp.status_code == 200
            assert ph_resp.json() == []

            rs_resp = await async_client.get("/api/v1/analytics/risk-score")
            assert rs_resp.status_code == 200

        try:
            # 3. Populate portfolio positions in DB
            pos1 = PortfolioPosition(
                ticker="TCS.NS",
                weight=0.6,
                quantity=10.0,
                buy_price=3500.0,
                last_price=3600.0,
                market_value=36000.0,
                region="IN",
                sector="Technology",
                added_on=datetime(2020, 1, 1),
            )
            pos2 = PortfolioPosition(
                ticker="INFY.NS",
                weight=0.4,
                quantity=20.0,
                buy_price=1500.0,
                last_price=1600.0,
                market_value=32000.0,
                region="IN",
                sector="Technology",
                added_on=datetime(2020, 1, 1),
            )
            test_db.add_all([pos1, pos2])
            await test_db.commit()

            # Mock data service for historical prices
            df_tcs = _make_ohlcv(days=120, seed=1, ticker="TCS.NS", base_price=3600.0)
            df_infy = _make_ohlcv(days=120, seed=2, ticker="INFY.NS", base_price=1600.0)

            mock_data_service = Mock()
            async def _fetch(ticker, start, end):
                if "TCS" in ticker:
                    return df_tcs
                return df_infy
            mock_data_service.fetch_historical_data = AsyncMock(side_effect=_fetch)

            with patch("app.api.analytics.GlobalDataService") as mock_gds, \
                 patch("app.api.analytics.BenchmarkService", return_value=bench):
                mock_gds.return_value.get_service.return_value = mock_data_service

                # 4. Query populated state
                pop_ph = await async_client.get("/api/v1/analytics/performance-history?days=90")
                assert pop_ph.status_code == 200
                ph_data = pop_ph.json()
                assert isinstance(ph_data, list)
                assert len(ph_data) > 0
                assert "portfolio_value" in ph_data[0]
                assert "date" in ph_data[0]

                pop_conc = await async_client.get("/api/v1/analytics/concentration")
                assert pop_conc.status_code == 200
                assert pop_conc.json()["largest_position"] > 0.5

                pop_sum = await async_client.get("/api/v1/analytics/summary")
                assert pop_sum.status_code == 200
                assert pop_sum.json()["total_positions"] == 2
                assert pop_sum.json()["portfolio_value"] == pytest.approx(68000.0)
        finally:
            await test_db.execute(delete(StockTimeseries))
            await test_db.execute(delete(PortfolioPosition))
            await test_db.commit()
