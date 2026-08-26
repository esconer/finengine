import pytest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import PortfolioPosition
from app.api.analytics import _load_portfolio_allocation
from app.services.analytics_engine import AnalyticsEngine


class TestLoadPortfolioAllocationLadder:
    @pytest.mark.asyncio
    async def test_empty_positions_returns_none(self):
        db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute.return_value = mock_result

        weights = await _load_portfolio_allocation(db)
        assert weights is None

    @pytest.mark.asyncio
    async def test_market_value_ladder(self):
        db = AsyncMock(spec=AsyncSession)
        p1 = PortfolioPosition(ticker="AAA", market_value=30000.0, weight=0.5)
        p2 = PortfolioPosition(ticker="BBB", market_value=70000.0, weight=0.5)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [p1, p2]
        db.execute.return_value = mock_result

        weights = await _load_portfolio_allocation(db)
        assert weights == {"AAA": 0.3, "BBB": 0.7}

    @pytest.mark.asyncio
    async def test_quantity_price_fallback_when_market_value_zero(self):
        db = AsyncMock(spec=AsyncSession)
        p1 = PortfolioPosition(ticker="AAA", market_value=0.0, quantity=100.0, last_price=50.0, weight=0.8)  # mv=5000
        p2 = PortfolioPosition(ticker="BBB", market_value=0.0, quantity=50.0, last_price=100.0, weight=0.2)  # mv=5000
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [p1, p2]
        db.execute.return_value = mock_result

        weights = await _load_portfolio_allocation(db)
        assert weights == {"AAA": 0.5, "BBB": 0.5}

    @pytest.mark.asyncio
    async def test_weight_column_fallback_when_market_values_zero(self):
        db = AsyncMock(spec=AsyncSession)
        p1 = PortfolioPosition(ticker="AAA", market_value=0.0, quantity=0.0, last_price=0.0, weight=0.25)
        p2 = PortfolioPosition(ticker="BBB", market_value=0.0, quantity=0.0, last_price=0.0, weight=0.75)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [p1, p2]
        db.execute.return_value = mock_result

        weights = await _load_portfolio_allocation(db)
        assert weights == {"AAA": 0.25, "BBB": 0.75}

    @pytest.mark.asyncio
    async def test_equal_weight_fallback_when_all_zero(self):
        db = AsyncMock(spec=AsyncSession)
        p1 = PortfolioPosition(ticker="AAA", market_value=0.0, quantity=0.0, last_price=0.0, weight=0.0)
        p2 = PortfolioPosition(ticker="BBB", market_value=0.0, quantity=0.0, last_price=0.0, weight=0.0)
        p3 = PortfolioPosition(ticker="CCC", market_value=0.0, quantity=0.0, last_price=0.0, weight=0.0)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [p1, p2, p3]
        db.execute.return_value = mock_result

        weights = await _load_portfolio_allocation(db)
        assert pytest.approx(weights["AAA"], 1e-6) == 1.0 / 3.0
        assert pytest.approx(weights["BBB"], 1e-6) == 1.0 / 3.0
        assert pytest.approx(weights["CCC"], 1e-6) == 1.0 / 3.0


class TestRealizedMetricConventionsAndProperties:
    @pytest.fixture
    def engine(self):
        return AnalyticsEngine()

    def test_sharpe_and_sortino_properties(self, engine):
        # Deterministic returns series: mean positive return, with some negative days
        np.random.seed(42)
        r = pd.Series(np.random.normal(0.001, 0.015, 252))
        basic = engine._calculate_basic_metrics(r)
        
        annual_return = r.mean() * 252
        annual_vol = r.std() * np.sqrt(252)
        expected_sharpe = (annual_return - engine.risk_free_rate) / annual_vol
        assert pytest.approx(basic["sharpe_ratio"], rel=1e-4) == expected_sharpe

        downside = r[r < 0]
        downside_vol = downside.std() * np.sqrt(252)
        expected_sortino = (annual_return - engine.risk_free_rate) / downside_vol
        assert pytest.approx(basic["sortino_ratio"], rel=1e-4) == expected_sortino
        assert 0.0 <= basic["hit_ratio"] <= 1.0

    def test_var_and_cvar_conventions(self, engine):
        np.random.seed(42)
        r = pd.Series(np.random.normal(0.0, 0.02, 500))
        risk = engine._calculate_risk_metrics(r)

        var_95 = risk["var_95"]
        cvar_95 = risk["cvar_95"]
        
        # In returns space, negative numbers represent losses
        # CVaR (expected shortfall) is the mean of returns below VaR, so it must be <= VaR (more negative)
        assert cvar_95 <= var_95
        assert var_95 == np.percentile(r, 5)

    def test_max_drawdown_bounds(self, engine):
        # Monotonically increasing returns -> max drawdown = 0
        up_returns = pd.Series([0.01] * 50)
        dd_up = engine._calculate_drawdown_metrics(up_returns)
        assert dd_up["max_drawdown"] == 0.0

        # Drops from 1.0 to 0.5 -> max drawdown = -0.5
        drop_returns = pd.Series([0.0, -0.5] + [0.0] * 10)
        dd_drop = engine._calculate_drawdown_metrics(drop_returns)
        assert dd_drop["max_drawdown"] == -0.5

    @pytest.mark.asyncio
    async def test_concentration_hhi_properties(self, engine):
        # Single asset portfolio -> HHI = 1.0
        conc_single = await engine.concentration_analysis({"A": 1.0})
        assert pytest.approx(conc_single["herfindahl_index"], 1e-4) == 1.0
        assert conc_single["effective_positions"] == 1

        # 4 equal-weight assets -> HHI = 4 * (0.25)^2 = 0.25
        conc_four = await engine.concentration_analysis({"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
        assert pytest.approx(conc_four["herfindahl_index"], 1e-4) == 0.25
        assert conc_four["effective_positions"] == 4
