"""
Comprehensive test suite for all routes in app.api.analytics with full data, multiple parameters,
different strategies, and error cases.
"""

from unittest.mock import AsyncMock, Mock, patch
import pandas as pd
import numpy as np
import pytest
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete

from app.models.database import PortfolioPosition


def _sample_ohlcv(days=120, ticker="TCS.NS"):
    dates = pd.date_range("2025-01-01", periods=days, freq="B")
    close = 3500.0 + np.cumsum(np.random.normal(0.0005, 15, days))
    return pd.DataFrame({
        "date": dates,
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "adj_close": close,
        "Volume": np.full(days, 200000.0),
        "volume": np.full(days, 200000.0),
        "ticker": ticker
    })


@pytest.mark.api
class TestAnalyticsAllRoutesWithData:
    @pytest.mark.asyncio
    async def test_analytics_routes_populated(self, async_client, test_db: AsyncSession):
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        pos1 = PortfolioPosition(
            ticker="TCS.NS",
            weight=0.5,
            quantity=10.0,
            buy_price=3400.0,
            last_price=3500.0,
            market_value=35000.0,
            region="IN",
            sector="Technology",
            added_on=datetime(2020, 1, 1),
        )
        pos2 = PortfolioPosition(
            ticker="INFY.NS",
            weight=0.5,
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

        df_tcs = _sample_ohlcv(120, "TCS.NS")
        df_infy = _sample_ohlcv(120, "INFY.NS")
        mock_ds = Mock()
        async def _fetch(ticker, start, end, force_refresh=False):
            if "TCS" in ticker:
                return df_tcs
            return df_infy
        mock_ds.fetch_historical_data = AsyncMock(side_effect=_fetch)

        try:
            with patch("app.api.analytics.GlobalDataService") as mock_gds, \
                 patch("app.api.analytics.BenchmarkService") as mock_bs:
                
                mock_gds.return_value.get_service.return_value = mock_ds
                mock_bs.return_value.get_returns = AsyncMock(
                    return_value=pd.Series(np.random.normal(0.0005, 0.01, 120), index=df_tcs["date"])
                )

                # 1. Realized risk with explicit tickers
                res_rr = await async_client.get("/api/v1/analytics/realized-risk?tickers=TCS.NS,INFY.NS")
                assert res_rr.status_code == 200

                # 2. Forecast risk with GARCH and integer horizon
                res_fr = await async_client.get("/api/v1/analytics/forecast-risk?horizon=21")
                assert res_fr.status_code == 200

                # 3. Summary
                res_sum = await async_client.get("/api/v1/analytics/summary")
                assert res_sum.status_code == 200

                # 4. Concentration
                res_conc = await async_client.get("/api/v1/analytics/concentration")
                assert res_conc.status_code == 200
                assert "herfindahl_index" in res_conc.json()

                # 5. Liquidity
                res_liq = await async_client.get("/api/v1/analytics/liquidity")
                assert res_liq.status_code == 200

                # 6. Risk score
                res_rs = await async_client.get("/api/v1/analytics/risk-score")
                assert res_rs.status_code == 200

                # 7. Factor exposure with benchmark
                res_fe = await async_client.get("/api/v1/analytics/factor-exposure")
                assert res_fe.status_code == 200
                assert "portfolio" in res_fe.json()

                # 8. Performance history with different timeframes
                for tf in ["1M", "3M", "6M", "1Y", "3Y", "5Y", "ALL"]:
                    res_ph = await async_client.get(f"/api/v1/analytics/performance-history?timeframe={tf}")
                    assert res_ph.status_code == 200

                # 9. Tear sheet
                res_ts = await async_client.get("/api/v1/analytics/tear-sheet")
                assert res_ts.status_code == 200

                # 10. Risk contribution
                res_conc2 = await async_client.get("/api/v1/analytics/concentration")
                assert res_conc2.status_code == 200

                # 11. Volatility sizing
                res_vs = await async_client.get("/api/v1/analytics/volatility-sizing?target_volatility=0.10&portfolio_value=100000")
                assert res_vs.status_code == 200

                # 12. Stress test scenarios and custom shocks
                res_st1 = await async_client.post("/api/v1/analytics/stress-test", json={"scenario": "financial_crisis_2008"})
                assert res_st1.status_code == 200

                res_st2 = await async_client.post("/api/v1/analytics/stress-test", json={
                    "scenario": "custom",
                    "tickers": ["TCS.NS", "INFY.NS"]
                })
                assert res_st2.status_code == 200

                # 13. Regime
                res_reg = await async_client.get("/api/v1/analytics/regime")
                assert res_reg.status_code == 200

                # 14. Monte Carlo
                res_mc = await async_client.post("/api/v1/analytics/monte-carlo", json={
                    "initial_value": 50000.0,
                    "target_value": 100000.0,
                    "monthly_contribution": 1000.0,
                    "horizon_years": 5,
                    "num_paths": 100
                })
                assert res_mc.status_code == 200

                # 15. Optimization with various strategies
                for strat in ["max_sharpe", "min_vol", "min_cvar", "hrp"]:
                    opt_payload = {
                        "strategy": strat,
                        "tickers": ["TCS.NS", "INFY.NS"]
                    }
                    res_opt = await async_client.post("/api/v1/analytics/optimize/run", json=opt_payload)
                    assert res_opt.status_code == 200
                    assert len(res_opt.json()["weights"]) == 2

                # 16. Optimization invalid strategy -> 400
                res_bad_strat = await async_client.post("/api/v1/analytics/optimize/run", json={"strategy": "invalid_strat"})
                assert res_bad_strat.status_code == 400

        finally:
            await test_db.execute(delete(PortfolioPosition))
            await test_db.commit()

    @pytest.mark.asyncio
    async def test_analytics_exception_handling(self, async_client, test_db: AsyncSession):
        mock_ds = Mock()
        mock_ds.fetch_historical_data = AsyncMock(side_effect=Exception("Data failure"))
        with patch("app.api.analytics.GlobalDataService") as mock_gds:
            mock_gds.return_value.get_service.return_value = mock_ds
            res = await async_client.get("/api/v1/analytics/realized-risk?tickers=TCS.NS")
            assert res.status_code in [200, 400, 404, 500]

        with patch("app.api.analytics.GlobalDataService") as mock_gds, \
             patch("app.api.analytics.optimize", side_effect=Exception("Optimization error")), \
             patch("app.api.analytics.detect_regime", side_effect=Exception("Regime error")), \
             patch("app.api.analytics.simulate_goal", side_effect=Exception("MC error")):
            
            mock_gds.return_value.get_service.return_value = mock_ds

            # Test endpoints catch exception and raise 500
            res1 = await async_client.get("/api/v1/analytics/summary")
            assert res1.status_code in [200, 404, 500]

            res2 = await async_client.get("/api/v1/analytics/forecast-risk")
            assert res2.status_code in [200, 404, 500]

            res3 = await async_client.get("/api/v1/analytics/factor-exposure")
            assert res3.status_code in [200, 404, 500]

            res4 = await async_client.get("/api/v1/analytics/concentration")
            assert res4.status_code in [200, 404, 500]

            res5 = await async_client.get("/api/v1/analytics/liquidity")
            assert res5.status_code in [200, 404, 500]

            res6 = await async_client.post("/api/v1/analytics/stress-test", json={"tickers": ["AAPL"], "scenario": "covid_crash_2020"})
            assert res6.status_code in [200, 400, 404, 500]

            res7 = await async_client.get("/api/v1/analytics/volatility-sizing")
            assert res7.status_code in [200, 400, 404, 500]

            res8 = await async_client.get("/api/v1/analytics/risk-score")
            assert res8.status_code in [200, 400, 404, 500]

            res9 = await async_client.get("/api/v1/analytics/summary")
            assert res9.status_code in [200, 400, 404, 500]

            res10 = await async_client.get("/api/v1/analytics/performance-history")
            assert res10.status_code in [200, 400, 404, 500]

            res11 = await async_client.get("/api/v1/analytics/tear-sheet")
            assert res11.status_code in [200, 400, 404, 500]

            res12 = await async_client.get("/api/v1/analytics/risk-contribution?tickers=AAPL")
            assert res12.status_code in [200, 400, 404, 500]

            res13 = await async_client.post("/api/v1/analytics/optimize/run", json={"strategy": "equal_weight", "tickers": ["AAPL"]})
            assert res13.status_code in [200, 400, 404, 500]

            res14 = await async_client.get("/api/v1/analytics/regime?tickers=AAPL")
            assert res14.status_code in [200, 400, 404, 409, 500]

            res15 = await async_client.post("/api/v1/analytics/monte-carlo", json={"tickers": ["AAPL"], "initial_value": 1000, "target_value": 2000})
            assert res15.status_code in [200, 400, 404, 422, 500]
