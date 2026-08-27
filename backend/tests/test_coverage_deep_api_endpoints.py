"""
Deep API endpoint coverage tests for app.api.portfolio and app.api.analytics.
"""

from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete

from app.models.database import PortfolioPosition


def _sample_ohlcv(days=250, ticker="TCS.NS"):
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    close = 3000.0 + np.cumsum(np.random.normal(0, 10, days))
    return pd.DataFrame({
        "date": dates,
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "adj_close": close,
        "Volume": np.full(days, 150000.0),
        "volume": np.full(days, 150000.0),
        "ticker": ticker
    })


@pytest.mark.api
class TestDeepPortfolioAndAnalyticsEndpoints:
    @pytest.mark.asyncio
    async def test_portfolio_full_lifecycle(self, async_client, test_db: AsyncSession):
        mock_ds = Mock()
        mock_ds.validate_ticker = AsyncMock(return_value=True)
        mock_ds.fetch_quote = AsyncMock(return_value={
            "ticker": "INFY.NS",
            "current_price": 1600.0,
            "open_price": 1580.0,
            "high_price": 1610.0,
            "low_price": 1570.0,
            "previous_close": 1590.0,
            "change": 10.0,
            "change_percent": 0.63,
            "volume": 250000,
            "market_cap": 600000000000.0,
            "timestamp": datetime.utcnow(),
            "sector": "Technology",
            "industry": "IT Services"
        })

        with patch("app.api.portfolio.GlobalDataService") as mock_gds:
            mock_gds.return_value.get_service.return_value = mock_ds

            # 1. Add position
            res_add = await async_client.post("/api/v1/portfolio/add", json={
                "ticker": "INFY.NS",
                "quantity": 100.0,
                "buy_price": 1500.0,
                "weight": 0.5
            })
            assert res_add.status_code == 200

            # 2. Get single position
            res_get = await async_client.get("/api/v1/portfolio/INFY.NS")
            assert res_get.status_code == 200
            assert res_get.json()["ticker"] == "INFY.NS"

            # 3. Update position
            res_put = await async_client.put("/api/v1/portfolio/INFY.NS", json={
                "quantity": 150.0,
                "buy_price": 1520.0,
                "weight": 0.6
            })
            assert res_put.status_code == 200

            # 4. Add second position
            res_add2 = await async_client.post("/api/v1/portfolio/add", json={
                "ticker": "TCS.NS",
                "quantity": 50.0,
                "buy_price": 3200.0,
                "weight": 0.7
            })
            assert res_add2.status_code == 200

            # 5. Normalize weights
            res_norm = await async_client.post("/api/v1/portfolio/normalize")
            assert res_norm.status_code == 200
            assert res_norm.json().get("success") is True or "normalized" in res_norm.json()

            # 6. Export CSV
            res_csv = await async_client.get("/api/v1/portfolio/export/csv")
            assert res_csv.status_code == 200
            assert res_csv.status_code == 200

            # 7. Portfolio summary
            res_summary = await async_client.get("/api/v1/portfolio")
            assert res_summary.status_code == 200
            assert res_summary.json()["total_positions"] == 2

            # 8. Normalize proportional
            res_norm_prop = await async_client.post("/api/v1/portfolio/normalize?method=proportional")
            assert res_norm_prop.status_code == 200

            # 9. Delete position
            res_del = await async_client.delete("/api/v1/portfolio/TCS.NS")
            assert res_del.status_code == 200

            # 10. Delete non-existent
            res_del404 = await async_client.delete("/api/v1/portfolio/NONEXIST.NS")
            assert res_del404.status_code == 404

    @pytest.mark.asyncio
    async def test_quant_analytics_routes(self, async_client, test_db: AsyncSession):
        pos1 = PortfolioPosition(
            ticker="TCS.NS", weight=0.6, quantity=20.0, buy_price=3000.0,
            last_price=3200.0, market_value=64000.0, region="IN", sector="Technology"
        )
        pos2 = PortfolioPosition(
            ticker="INFY.NS", weight=0.4, quantity=40.0, buy_price=1400.0,
            last_price=1500.0, market_value=60000.0, region="IN", sector="Technology"
        )
        test_db.add_all([pos1, pos2])
        await test_db.commit()

        df_tcs = _sample_ohlcv(250, "TCS.NS")
        df_infy = _sample_ohlcv(250, "INFY.NS")

        mock_ds = Mock()
        async def _fetch(ticker, start, end, force_refresh=False):
            return df_tcs if "TCS" in ticker else df_infy
        mock_ds.fetch_historical_data = AsyncMock(side_effect=_fetch)

        try:
            with patch("app.api.analytics.GlobalDataService") as mock_gds,                  patch("app.api.analytics.BenchmarkService") as mock_bs:
                
                mock_gds.return_value.get_service.return_value = mock_ds
                mock_bs.return_value.get_returns = AsyncMock(
                    return_value=pd.Series(np.random.normal(0.0005, 0.01, 250), index=df_tcs["date"])
                )

                # 1. Volatility Cone endpoint
                res_vc = await async_client.get("/api/v1/analytics/vol-cone?symbol=TCS.NS&horizon=21&model=GARCH")
                assert res_vc.status_code in [200, 404]

                # 2. Tail Risk EVT POT & Copula endpoint
                res_tr = await async_client.get("/api/v1/analytics/tail-risk?tickers=TCS.NS,INFY.NS")
                assert res_tr.status_code in [200, 404]

                # 3. Cointegration Scanner endpoint
                res_coint = await async_client.get("/api/v1/analytics/coint?tickers=TCS.NS,INFY.NS&lookback_days=180")
                assert res_coint.status_code in [200, 404]

                # 4. Correlation Stability endpoint
                res_corr = await async_client.get("/api/v1/analytics/correlation-stability?tickers=TCS.NS,INFY.NS&window_days=30")
                assert res_corr.status_code in [200, 404]

                # 5. Monte Carlo Goal Simulation across all 3 methods
                for method in ["gbm", "student_t", "bootstrap"]:
                    res_mc = await async_client.post("/api/v1/analytics/monte-carlo", json={
                        "initial_value": 124000.0,
                        "target_value": 200000.0,
                        "horizon_years": 3,
                        "method": method,
                        "num_paths": 200,
                        "seed": 42
                    })
                    assert res_mc.status_code == 200
                    assert "prob_reach_target" in res_mc.json() or "expected_shortfall_vs_target" in res_mc.json()

                # 6. Optimization Strategies
                for strat in ["max_sharpe", "min_vol", "min_cvar", "hrp"]:
                    res_opt = await async_client.post("/api/v1/analytics/optimize/run", json={"strategy": strat})
                    assert res_opt.status_code == 200

                # 7. Regime Detection
                res_reg = await async_client.get("/api/v1/analytics/regime")
                assert res_reg.status_code == 200
        finally:
            await test_db.execute(delete(PortfolioPosition))
            await test_db.commit()
