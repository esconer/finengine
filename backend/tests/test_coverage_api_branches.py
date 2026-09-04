"""
Comprehensive branch tests for portfolio, analytics, and data APIs to push coverage above 80%.
"""

from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime
import pandas as pd
import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete

from app.models.database import PortfolioPosition


def _sample_ohlcv(days=120, ticker="SBIN.NS"):
    dates = pd.date_range("2024-01-01", periods=days, freq="B")
    close = 600.0 + np.cumsum(np.random.normal(0, 3, days))
    return pd.DataFrame({
        "date": dates,
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "adj_close": close,
        "Volume": np.full(days, 500000.0),
        "volume": np.full(days, 500000.0),
        "ticker": ticker
    })


@pytest.mark.api
class TestAPIBranchesCoverage:
    @pytest.mark.asyncio
    async def test_portfolio_branches_and_validation(self, async_client, test_db: AsyncSession):
        # 1. Empty portfolio summary
        await test_db.execute(delete(PortfolioPosition))
        await test_db.commit()

        res_empty = await async_client.get("/api/v1/portfolio")
        assert res_empty.status_code == 200
        assert res_empty.json()["total_positions"] == 0

        # 2. Add position validation errors
        # Invalid weight (> 1)
        res_bad_wt = await async_client.post("/api/v1/portfolio/add", json={
            "ticker": "SBIN.NS", "quantity": 10.0, "buy_price": 500.0, "weight": 1.5
        })
        assert res_bad_wt.status_code == 422

        # Invalid quantity (<= 0)
        res_bad_qty = await async_client.post("/api/v1/portfolio/add", json={
            "ticker": "SBIN.NS", "quantity": -5.0, "buy_price": 500.0, "weight": 0.5
        })
        assert res_bad_qty.status_code == 422

        # Invalid price (<= 0)
        res_bad_pr = await async_client.post("/api/v1/portfolio/add", json={
            "ticker": "SBIN.NS", "quantity": 10.0, "buy_price": -500.0, "weight": 0.5
        })
        assert res_bad_pr.status_code == 422

        mock_ds = Mock()
        mock_ds.validate_ticker = AsyncMock(return_value=True)
        mock_ds.fetch_quote = AsyncMock(return_value={
            "ticker": "SBIN.NS", "current_price": 600.0, "open_price": 590.0,
            "high_price": 605.0, "low_price": 585.0, "previous_close": 595.0,
            "change": 5.0, "change_percent": 0.84, "volume": 100000,
            "market_cap": 500000000000.0, "timestamp": datetime.utcnow(),
            "sector": "Financial Services", "industry": "Banking"
        })

        with patch("app.api.portfolio.GlobalDataService") as mock_gds:
            mock_gds.return_value.get_service.return_value = mock_ds

            # Add valid position
            res_add = await async_client.post("/api/v1/portfolio/add", json={
                "ticker": "SBIN.NS", "quantity": 100.0, "buy_price": 500.0, "weight": 0.5
            })
            assert res_add.status_code == 200

            # Update position: not found
            res_put_404 = await async_client.put("/api/v1/portfolio/NOTFOUND.NS", json={
                "quantity": 200.0, "buy_price": 520.0, "weight": 0.5
            })
            assert res_put_404.status_code == 404

            # Normalize on non-empty
            res_norm = await async_client.post("/api/v1/portfolio/normalize")
            assert res_norm.status_code == 200

            # Summary on populated portfolio
            res_sum = await async_client.get("/api/v1/portfolio")
            assert res_sum.status_code == 200
            assert res_sum.json()["total_positions"] >= 1

    @pytest.mark.asyncio
    async def test_analytics_branches_coverage(self, async_client, test_db: AsyncSession):
        pos = PortfolioPosition(
            ticker="SBIN.NS", weight=1.0, quantity=100.0, buy_price=500.0,
            last_price=600.0, market_value=60000.0, region="IN", sector="Financial Services",
            added_on=datetime(2020, 1, 1),
        )
        test_db.add(pos)
        await test_db.commit()

        df_sbin = _sample_ohlcv(150, "SBIN.NS")
        mock_ds = Mock()
        mock_ds.fetch_historical_data = AsyncMock(return_value=df_sbin)

        with patch("app.api.analytics.GlobalDataService") as mock_gds,              patch("app.api.analytics.BenchmarkService") as mock_bs:
            
            mock_gds.return_value.get_service.return_value = mock_ds
            mock_bs.return_value.get_returns = AsyncMock(
                return_value=pd.Series(np.random.normal(0.0005, 0.01, 150), index=df_sbin["date"])
            )

            # Realized risk default
            res_rr = await async_client.get("/api/v1/analytics/realized-risk")
            assert res_rr.status_code == 200

            # Forecast risk with EGARCH
            res_fr = await async_client.get("/api/v1/analytics/forecast-risk?model=GARCH&horizon=5")
            assert res_fr.status_code == 200

            # Factor exposure default
            res_fe = await async_client.get("/api/v1/analytics/factor-exposure")
            assert res_fe.status_code == 200

            # Concentration default
            res_conc = await async_client.get("/api/v1/analytics/concentration")
            assert res_conc.status_code == 200

            # Liquidity default
            res_liq = await async_client.get("/api/v1/analytics/liquidity")
            assert res_liq.status_code == 200

            # Volatility sizing default
            res_vs = await async_client.get("/api/v1/analytics/volatility-sizing?target_volatility=0.12")
            assert res_vs.status_code == 200

            # Risk score default
            res_rs = await async_client.get("/api/v1/analytics/risk-score")
            assert res_rs.status_code == 200

            # Performance history default
            res_ph = await async_client.get("/api/v1/analytics/performance-history?timeframe=6M")
            assert res_ph.status_code == 200

            # Summary default
            res_sum = await async_client.get("/api/v1/analytics/summary")
            assert res_sum.status_code == 200

            # Tear sheet default
            res_ts = await async_client.get("/api/v1/analytics/tear-sheet")
            assert res_ts.status_code == 200

            # Regime default
            res_reg = await async_client.get("/api/v1/analytics/regime")
            assert res_reg.status_code == 200
