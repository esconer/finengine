"""
Comprehensive API test suite for app.api.analytics covering all endpoints and edge cases.
"""

from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete

from app.models.database import PortfolioPosition


def _sample_ohlcv(days=200, ticker="TCS.NS"):
    dates = pd.date_range("2024-06-01", periods=days, freq="B")
    close = 3500.0 + np.cumsum(np.random.normal(0, 15, days))
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
class TestDeepAnalyticsRoutes:
    @pytest.mark.asyncio
    async def test_all_analytics_endpoints_and_params(self, async_client, test_db: AsyncSession):
        pos1 = PortfolioPosition(
            ticker="TCS.NS",
            weight=0.6,
            quantity=15.0,
            buy_price=3400.0,
            last_price=3500.0,
            market_value=52500.0,
            region="IN",
            sector="Technology",
            added_on=datetime(2020, 1, 1),
        )
        pos2 = PortfolioPosition(
            ticker="INFY.NS",
            weight=0.4,
            quantity=25.0,
            buy_price=1500.0,
            last_price=1600.0,
            market_value=40000.0,
            region="IN",
            sector="Technology",
            added_on=datetime(2020, 1, 1),
        )
        test_db.add_all([pos1, pos2])
        await test_db.commit()

        df_tcs = _sample_ohlcv(200, "TCS.NS")
        df_infy = _sample_ohlcv(200, "INFY.NS")
        
        mock_ds = Mock()
        async def _fetch(ticker, start, end, force_refresh=False):
            if "TCS" in ticker:
                return df_tcs
            return df_infy
        mock_ds.fetch_historical_data = AsyncMock(side_effect=_fetch)

        try:
            with patch("app.api.analytics.GlobalDataService") as mock_gds,                  patch("app.api.analytics.BenchmarkService") as mock_bs:
                
                mock_gds.return_value.get_service.return_value = mock_ds
                mock_bs.return_value.get_returns = AsyncMock(
                    return_value=pd.Series(np.random.normal(0.0005, 0.01, 200), index=df_tcs["date"])
                )

                # 1. Summary
                res = await async_client.get("/api/v1/analytics/summary")
                assert res.status_code == 200

                # 2. Realized risk across lookback intervals
                res = await async_client.get("/api/v1/analytics/realized-risk?lookback_days=30")
                assert res.status_code == 200

                # 3. Forecast risk across models
                res = await async_client.get("/api/v1/analytics/forecast-risk?model=EWMA&horizon=10")
                assert res.status_code == 200

                # 4. Volatility sizing with target vol
                res = await async_client.get("/api/v1/analytics/volatility-sizing?target_volatility=0.10&model=EWMA")
                assert res.status_code == 200

                # 5. Stress test
                res = await async_client.post("/api/v1/analytics/stress-test", json={"scenario": "covid_crash_2020"})
                assert res.status_code == 200

                # 6. Concentration
                res = await async_client.get("/api/v1/analytics/concentration")
                assert res.status_code == 200

                # 7. Liquidity
                res = await async_client.get("/api/v1/analytics/liquidity")
                assert res.status_code == 200

                # 8. Risk score
                res = await async_client.get("/api/v1/analytics/risk-score")
                assert res.status_code == 200

                # 9. Factor exposure
                res = await async_client.get("/api/v1/analytics/factor-exposure")
                assert res.status_code == 200

                # 10. Performance history
                res = await async_client.get("/api/v1/analytics/performance-history?timeframe=1M")
                assert res.status_code == 200

                # 11. Optimization
                res = await async_client.post("/api/v1/analytics/optimize/run", json={"strategy": "hrp"})
                assert res.status_code == 200

                # 12. Monte Carlo simulations
                res = await async_client.post("/api/v1/analytics/monte-carlo", json={
                    "initial_value": 100000.0,
                    "target_value": 150000.0,
                    "horizon_years": 3,
                    "method": "gbm",
                    "num_paths": 100
                })
                assert res.status_code == 200

                # 13. Tear sheet
                res = await async_client.get("/api/v1/analytics/tear-sheet")
                assert res.status_code == 200

                # 14. Correlation stability
                res_cs = await async_client.get("/api/v1/analytics/correlation-stability?lookback_days=180&window_days=30")
                assert res_cs.status_code in [200, 400]

                # 15. Cointegration pairs
                res_coint = await async_client.get("/api/v1/analytics/coint?lookback_days=180")
                assert res_coint.status_code in [200, 400]

        finally:
            await test_db.execute(delete(PortfolioPosition))
            await test_db.commit()
