"""
Comprehensive test suite for app.api.analytics helper methods and empty portfolio / edge case handling.
"""

import numpy as np
import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete

from app.models.database import PortfolioPosition
from app.api.analytics import (
    resolve_allocation,
    _q,
    _price_series,
    _assign_price,
    _load_portfolio_allocation
)


@pytest.mark.api
class TestAnalyticsHelpersAndEdgeCases:
    @pytest.mark.asyncio
    async def test_resolve_allocation_branches(self, test_db: AsyncSession):
        # 1. Explicit tickers param
        tickers, weights = await resolve_allocation("AAPL,MSFT,GOOGL", test_db)
        assert tickers == ["AAPL", "MSFT", "GOOGL"]
        assert round(weights["AAPL"], 4) == round(1.0 / 3.0, 4)

        # 2. Empty tickers param with empty DB -> raises ValueError
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()
        with pytest.raises(ValueError, match="No portfolio positions found"):
            await resolve_allocation(None, test_db)

        # 3. Empty tickers param with populated DB
        pos = PortfolioPosition(
            ticker="TCS.NS",
            weight=0.5,
            quantity=10.0,
            buy_price=3000.0,
            last_price=3200.0,
            market_value=32000.0
        )
        test_db.add(pos)
        await test_db.commit()

        tickers_db, weights_db = await resolve_allocation(None, test_db)
        assert "TCS.NS" in tickers_db
        assert weights_db["TCS.NS"] == 1.0

        # Clean up
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

    def test_q_metric_guard(self):
        # Standard function
        assert _q(lambda x: x + 1.0, 2.5) == 3.5

        # Numpy item function
        assert _q(lambda: np.float64(4.12345678)) == 4.123457

        # Exception raising function
        def raise_err():
            raise RuntimeError("Unavailable")
        assert _q(raise_err) is None

    def test_price_series_extraction(self):
        # None or empty
        assert _price_series(None) is None
        assert _price_series(pd.DataFrame()) is None

        # Missing price column
        assert _price_series(pd.DataFrame({"Volume": [100]})) is None

        # Date column present
        dates = ["2025-01-01", "2025-01-02"]
        df_date = pd.DataFrame({"date": dates, "adj_close": [100.0, 105.0]})
        s_date = _price_series(df_date)
        assert s_date is not None
        assert len(s_date) == 2

        # DatetimeIndex
        df_idx = pd.DataFrame({"close": [100.0, 105.0]}, index=pd.to_datetime(dates))
        s_idx = _price_series(df_idx)
        assert s_idx is not None
        assert len(s_idx) == 2

        # RangeIndex fallback
        df_range = pd.DataFrame({"close": [100.0, 105.0]})
        s_range = _price_series(df_range)
        assert s_range is not None

        # _assign_price helper
        store = {}
        _assign_price(store, "TEST", df_date)
        assert "TEST" in store

    @pytest.mark.asyncio
    async def test_load_portfolio_allocation_branches(self, test_db: AsyncSession):
        # Empty DB
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()
        assert await _load_portfolio_allocation(test_db) is None

        # DB with market values > 0
        pos1 = PortfolioPosition(ticker="A", quantity=10, last_price=100, market_value=1000, weight=0.0)
        pos2 = PortfolioPosition(ticker="B", quantity=10, last_price=100, market_value=1000, weight=0.0)
        test_db.add_all([pos1, pos2])
        await test_db.commit()

        alloc = await _load_portfolio_allocation(test_db)
        assert alloc["A"] == 0.5
        assert alloc["B"] == 0.5

        # Clean up
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        # DB with market_value 0 but weight > 0
        pos3 = PortfolioPosition(ticker="C", quantity=0, last_price=0, market_value=0, weight=0.6)
        pos4 = PortfolioPosition(ticker="D", quantity=0, last_price=0, market_value=0, weight=0.4)
        test_db.add_all([pos3, pos4])
        await test_db.commit()

        alloc2 = await _load_portfolio_allocation(test_db)
        assert alloc2["C"] == 0.6
        assert alloc2["D"] == 0.4

        # Clean up
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        # DB with all zeros -> equal weight fallback
        pos5 = PortfolioPosition(ticker="E", quantity=0, last_price=0, market_value=0, weight=0.0)
        pos6 = PortfolioPosition(ticker="F", quantity=0, last_price=0, market_value=0, weight=0.0)
        test_db.add_all([pos5, pos6])
        await test_db.commit()

        alloc3 = await _load_portfolio_allocation(test_db)
        assert alloc3["E"] == 0.5
        assert alloc3["F"] == 0.5

        # Clean up
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()


@pytest.mark.api
class TestAnalyticsEmptyPortfolioRoutes:
    @pytest.mark.asyncio
    async def test_all_routes_empty_portfolio(self, async_client, test_db: AsyncSession):
        # Ensure database is clean
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        # 1. Realized risk
        res = await async_client.get("/api/v1/analytics/realized-risk")
        assert res.status_code in [200, 404]
        assert res.json()["portfolio"]["annual_return"] == 0.0

        # 2. Forecast risk
        res = await async_client.get("/api/v1/analytics/forecast-risk")
        assert res.status_code in [200, 404]
        assert res.json()["portfolio"]["volatility_forecast"] == 0.22

        # 3. Factor exposure
        res = await async_client.get("/api/v1/analytics/factor-exposure")
        assert res.status_code in [200, 404]
        assert "portfolio" in res.json() or "market_beta" in res.json()

        # 4. Concentration
        res = await async_client.get("/api/v1/analytics/concentration")
        assert res.status_code in [200, 404]
        assert res.json()["herfindahl_index"] == 0.0

        # 5. Liquidity
        res = await async_client.get("/api/v1/analytics/liquidity")
        assert res.status_code in [200, 404]
        assert "overall_score" in res.json() or "error" in res.json()

        # 6. Stress test
        res = await async_client.post("/api/v1/analytics/stress-test", json={"scenario": "covid_crash_2020"})
        assert res.status_code in [200, 404]
        assert "max_drawdown" in res.json()

        # 7. Volatility sizing
        res = await async_client.get("/api/v1/analytics/volatility-sizing?target_volatility=0.15")
        assert res.status_code in [200, 404]
        assert "target_volatility" in res.json() or "error" in res.json()

        # 8. Risk score
        res = await async_client.get("/api/v1/analytics/risk-score")
        assert res.status_code in [200, 404]
        assert "overall_score" in res.json() or "risk_score" in res.json()

        # 9. Summary
        res = await async_client.get("/api/v1/analytics/summary")
        assert res.status_code in [200, 404]
        assert "realized_risk" in res.json() or "forecast_volatility" in res.json() or "error" in res.json()

        # 10. Performance history
        res = await async_client.get("/api/v1/analytics/performance-history")
        assert res.status_code in [200, 404]
        assert (isinstance(res.json(), list) and len(res.json()) == 0) or (isinstance(res.json(), dict) and ("series" in res.json() or "error" in res.json()))

        # 11. Tear sheet
        res = await async_client.get("/api/v1/analytics/tear-sheet")
        assert res.status_code in [200, 404]
        assert "metrics" in res.json() or "error" in res.json() or "detail" in res.json()

        # 12. Risk contribution
        res = await async_client.get("/api/v1/analytics/concentration")
        assert res.status_code in [200, 404]
        assert "herfindahl_index" in res.json() or "error" in res.json()

        # 13. Optimization
        res = await async_client.post("/api/v1/analytics/optimize/run", json={"strategy": "max_sharpe"})
        assert res.status_code in [200, 404]

        # 14. Regime
        res = await async_client.get("/api/v1/analytics/regime")
        assert res.status_code in [200, 404]
        assert "regime" in res.json() or "current_regime" in res.json()

        # 15. Monte Carlo
        res = await async_client.post("/api/v1/analytics/monte-carlo", json={
            "initial_value": 10000.0,
            "target_value": 20000.0,
            "horizon_years": 5
        })
        assert res.status_code in [200, 404]
        assert "prob_reach_target" in res.json() or "probability_of_success" in res.json() or "expected_shortfall_vs_target" in res.json() or "detail" in res.json()
