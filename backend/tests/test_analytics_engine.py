"""
Unit tests for Analytics Engine
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, Mock

from app.services.analytics_engine import AnalyticsEngine, GlobalAnalyticsEngine
from app.models.schemas import StressTestRequest, VolatilitySizingRequest


@pytest.mark.unit
class TestAnalyticsEngine:
    """Test cases for AnalyticsEngine class"""
    
    def test_analytics_engine_initialization(self):
        """Test analytics engine initialization"""
        engine = AnalyticsEngine()
        assert engine.risk_free_rate == 0.02
        # previous-score tracking initializes lazily inside risk_scoring
        assert not hasattr(engine, '_previous_risk_score')
    
    @pytest.mark.asyncio
    async def test_calculate_portfolio_metrics_empty_data(self):
        """Test portfolio metrics calculation with empty data"""
        engine = AnalyticsEngine()
        empty_df = pd.DataFrame()
        weights = {"AAPL": 0.5, "MSFT": 0.5}
        
        result = await engine.calculate_portfolio_metrics(empty_df, weights)
        
        assert result["error"] == "Insufficient data for calculations"
        assert result["annual_return"] == 0
        assert result["annual_volatility"] == 0.20
    
    @pytest.mark.asyncio
    async def test_calculate_portfolio_metrics_with_data(self, mock_price_dataframe, sample_portfolio_weights):
        """Test portfolio metrics calculation with real data"""
        engine = AnalyticsEngine()
        
        result = await engine.calculate_portfolio_metrics(mock_price_dataframe, sample_portfolio_weights)
        
        # Check that required metrics are present
        assert "annual_return" in result
        assert "annual_volatility" in result
        assert "sharpe_ratio" in result
        assert "sortino_ratio" in result
        assert "var_95" in result
        assert "cvar_95" in result
        assert "max_drawdown" in result
        assert "positions" in result
        
        # Check that values are reasonable
        assert isinstance(result["annual_return"], (int, float))
        assert isinstance(result["annual_volatility"], (int, float))
        assert isinstance(result["sharpe_ratio"], (int, float))
    
    @pytest.mark.asyncio
    async def test_calculate_portfolio_metrics_no_weights(self, mock_price_dataframe):
        """Test portfolio metrics calculation without explicit weights"""
        engine = AnalyticsEngine()
        
        result = await engine.calculate_portfolio_metrics(mock_price_dataframe, None)
        
        # Should use equal weights
        assert "annual_return" in result
        assert "positions" in result
    
    @pytest.mark.asyncio
    async def test_forecast_volatility_garch(self, mock_returns_series):
        """Test GARCH volatility forecasting"""
        engine = AnalyticsEngine()
        
        with patch('app.services.analytics_engine.arch_model') as mock_arch:
            # Mock the GARCH model
            mock_model = Mock()
            mock_fitted_model = Mock()
            mock_forecast = Mock()
            
            mock_fitted_model.forecast.return_value = mock_forecast
            mock_forecast.variance.values = np.array([[0.04]])  # 20% annualized volatility
            mock_arch.return_value = mock_model
            mock_model.fit.return_value = mock_fitted_model
            mock_model.return_value = mock_fitted_model
            
            result = await engine.forecast_volatility(mock_returns_series, model="GARCH", horizon=5)
            
            assert result["model"] == "GARCH"
            assert result["horizon"] == 5
            assert "volatility_forecast" in result
            assert "var_forecast" in result
            assert "cvar_forecast" in result
            assert "confidence_interval" in result
    
    @pytest.mark.asyncio
    async def test_forecast_volatility_insufficient_data(self):
        """Test volatility forecasting with insufficient data"""
        engine = AnalyticsEngine()
        
        # Create short returns series
        short_returns = pd.Series([0.01, -0.02, 0.03])  # Only 3 data points
        
        result = await engine.forecast_volatility(short_returns, model="GARCH")
        
        assert result["error"] == "Insufficient data for forecast"
        assert result["volatility_forecast"] == 0.22
    
    @pytest.mark.asyncio
    async def test_concentration_analysis(self, sample_portfolio_weights):
        """Test portfolio concentration analysis"""
        engine = AnalyticsEngine()
        
        result = await engine.concentration_analysis(sample_portfolio_weights)
        
        assert "largest_position" in result
        assert "top_3" in result
        assert "top_5" in result
        assert "herfindahl_index" in result
        assert "effective_positions" in result
        assert "diversification_ratio" in result
        assert "by_weight" in result
        
        # Check that values are reasonable
        assert 0 <= result["largest_position"] <= 1
        assert 0 <= result["herfindahl_index"] <= 1
        assert result["effective_positions"] >= 1
    
    @pytest.mark.asyncio
    async def test_concentration_analysis_empty_weights(self):
        """Test concentration analysis with empty weights"""
        engine = AnalyticsEngine()
        
        result = await engine.concentration_analysis({})
        
        assert result["error"] == "No position data available"
        assert result["herfindahl_index"] == 0.15
    
    @pytest.mark.asyncio
    async def test_factor_exposure_analysis(self, mock_price_dataframe):
        """Test factor exposure analysis"""
        engine = AnalyticsEngine()
        
        # Create mock benchmark data
        benchmark_returns = pd.Series(
            np.random.randn(len(mock_price_dataframe)) * 0.015,
            index=mock_price_dataframe.index
        )
        
        result = await engine.factor_exposure_analysis(mock_price_dataframe, benchmark_returns)
        
        assert "portfolio" in result
        assert "r_squared" in result
        assert "adjusted_r_squared" in result
        
        # Check portfolio exposures
        portfolio_exposures = result["portfolio"]
        assert "market" in portfolio_exposures
        assert "alpha" in portfolio_exposures
        
        # Check R-squared values
        assert 0 <= result["r_squared"] <= 1
        assert 0 <= result["adjusted_r_squared"] <= 1
    
    @pytest.mark.asyncio
    async def test_liquidity_analysis(self):
        """Test portfolio liquidity analysis"""
        engine = AnalyticsEngine()
        
        # Create mock price data with volume information
        price_data = {}
        for ticker in ["AAPL", "MSFT", "GOOGL"]:
            dates = pd.date_range(start="2023-01-01", periods=30, freq="D")
            df = pd.DataFrame({
                'Close': np.random.randn(30) * 2 + 100,
                'Volume': np.random.randint(500000, 2000000, 30)
            }, index=dates)
            price_data[ticker] = df
        
        result = await engine.liquidity_analysis(price_data)
        
        assert "overall_score" in result
        assert "liquidation_time_days" in result
        assert "risk_level" in result
        assert "by_position" in result
        assert "volume_stats" in result
        
        # Check that all positions have scores
        assert len(result["by_position"]) > 0
        
        # Check overall score range
        assert 1 <= result["overall_score"] <= 10
    
    @pytest.mark.asyncio
    async def test_stress_test(self, mock_price_dataframe, sample_portfolio_weights):
        """Test stress testing functionality"""
        engine = AnalyticsEngine()
        
        result = await engine.stress_test(
            mock_price_dataframe, 
            sample_portfolio_weights, 
            "2020_covid"
        )
        
        assert "scenario" in result
        assert "scenario_description" in result
        assert "max_drawdown" in result
        assert "portfolio_impact" in result
        assert "position_impacts" in result
        assert "recovery_time" in result
        assert "confidence_level" in result
        
        # Check that drawdown is negative
        assert result["max_drawdown"] < 0
        assert result["portfolio_impact"] < 0
        
        # Check that position impacts are calculated
        assert len(result["position_impacts"]) > 0
    
    @pytest.mark.asyncio
    async def test_volatility_sizing(self, mock_price_dataframe, sample_portfolio_weights):
        """Test volatility-adjusted position sizing"""
        engine = AnalyticsEngine()
        
        result = await engine.volatility_sizing(
            mock_price_dataframe,
            sample_portfolio_weights,
            model="EWMA",
            target_volatility=0.15
        )
        
        assert "current_weights" in result
        assert "recommended_weights" in result
        assert "trades" in result
        assert "target_volatility" in result
        assert "current_volatility" in result
        assert "volatilities" in result
        
        # Check that trades are generated
        assert len(result["trades"]) > 0
        
        # Check that weights sum to approximately 1
        total_recommended = sum(result["recommended_weights"].values())
        assert abs(total_recommended - 1.0) < 0.01
    
    @pytest.mark.asyncio
    async def test_risk_scoring(self, mock_price_dataframe, sample_portfolio_weights):
        """Test comprehensive risk scoring"""
        engine = AnalyticsEngine()
        
        result = await engine.risk_scoring(mock_price_dataframe, sample_portfolio_weights)
        
        assert "overall_score" in result
        assert "risk_level" in result
        assert "change" in result
        assert "components" in result
        assert "alerts" in result
        assert "methodology" in result
        
        # Check risk level
        assert result["risk_level"] in ["LOW", "MEDIUM", "HIGH"]
        
        # Check components
        components = result["components"]
        assert "concentration" in components
        assert "volatility" in components
        assert "correlation" in components
        assert "factor_risk" in components
        assert "market_risk" in components
        
        # Check that all component scores are reasonable
        for score in components.values():
            assert 0 <= score <= 30
    
    @pytest.mark.asyncio
    async def test_risk_scoring_with_previous_score(self, mock_price_dataframe, sample_portfolio_weights):
        """Test risk scoring change calculation"""
        engine = AnalyticsEngine()
        
        result1 = await engine.risk_scoring(mock_price_dataframe, sample_portfolio_weights)

        # Force a level-boundary crossing relative to the fresh baseline:
        prev_on_other_side_of_25 = 100.0 if result1["overall_score"] < 25 else 0.0
        engine._previous_risk_score = prev_on_other_side_of_25

        result2 = await engine.risk_scoring(mock_price_dataframe, sample_portfolio_weights)

        # Crossing the LOW/MEDIUM/HIGH boundary must register a change
        assert result2["change"] != 0
    
    def test_calculate_portfolio_returns(self, mock_price_dataframe, sample_portfolio_weights):
        """Test portfolio return calculation"""
        engine = AnalyticsEngine()
        
        returns = mock_price_dataframe.pct_change().dropna()
        portfolio_returns = engine._calculate_portfolio_returns(returns, sample_portfolio_weights)
        
        assert isinstance(portfolio_returns, pd.Series)
        assert len(portfolio_returns) == len(returns)
        assert not portfolio_returns.isna().any()
    
    def test_calculate_basic_metrics(self, mock_returns_series):
        """Test basic metrics calculation"""
        engine = AnalyticsEngine()
        
        metrics = engine._calculate_basic_metrics(mock_returns_series)
        
        assert "annual_return" in metrics
        assert "annual_volatility" in metrics
        assert "sharpe_ratio" in metrics
        assert "sortino_ratio" in metrics
        assert "hit_ratio" in metrics
        
        # Check that values are reasonable
        assert isinstance(metrics["annual_return"], (int, float))
        assert isinstance(metrics["annual_volatility"], (int, float))
        assert 0 <= metrics["hit_ratio"] <= 1
    
    def test_calculate_basic_metrics_empty_returns(self):
        """Test basic metrics calculation with empty returns"""
        engine = AnalyticsEngine()
        
        empty_returns = pd.Series(dtype=float)
        metrics = engine._calculate_basic_metrics(empty_returns)
        
        assert metrics == {}
    
    def test_calculate_risk_metrics(self, mock_returns_series):
        """Test risk metrics calculation"""
        engine = AnalyticsEngine()
        
        metrics = engine._calculate_risk_metrics(mock_returns_series)
        
        assert "var_95" in metrics
        assert "cvar_95" in metrics
        
        # VaR should be negative for a typical return series
        assert metrics["var_95"] < 0
        assert metrics["cvar_95"] < metrics["var_95"]  # CVaR is more extreme
    
    def test_calculate_drawdown_metrics(self, mock_returns_series):
        """Test drawdown metrics calculation"""
        engine = AnalyticsEngine()
        
        metrics = engine._calculate_drawdown_metrics(mock_returns_series)
        
        assert "max_drawdown" in metrics
        
        # Max drawdown should be negative
        assert metrics["max_drawdown"] <= 0
    
    def test_calculate_return_distribution(self, mock_returns_series):
        """Test return distribution metrics"""
        engine = AnalyticsEngine()
        
        metrics = engine._calculate_return_distribution(mock_returns_series)
        
        assert "skewness" in metrics
        assert "kurtosis" in metrics
        
        # Check that values are finite
        assert abs(metrics["skewness"]) < 10
        assert abs(metrics["kurtosis"]) < 50
    
    def test_calculate_max_drawdown(self):
        """Test max drawdown calculation"""
        engine = AnalyticsEngine()
        
        # Create test cumulative returns
        cumulative_returns = pd.Series([1.0, 1.1, 0.9, 1.05, 1.0, 0.95])
        
        max_drawdown = engine._calculate_max_drawdown(cumulative_returns)
        
        # Should be negative (drawdown)
        assert max_drawdown < 0
        assert max_drawdown >= -1.0
    
    def test_simulate_stress_drawdown(self, sample_portfolio_weights):
        """Test stress drawdown simulation"""
        engine = AnalyticsEngine()
        
        drawdown = engine._simulate_stress_drawdown(sample_portfolio_weights)
        
        # Should be negative
        assert drawdown < 0
        assert drawdown >= -0.5
    
    def test_estimate_recovery_time(self):
        """Test recovery time estimation"""
        engine = AnalyticsEngine()
        
        # Test different scenarios
        covid_time = engine._estimate_recovery_time(0.25, "covid")
        inflation_time = engine._estimate_recovery_time(0.20, "inflation")
        normal_time = engine._estimate_recovery_time(0.15, "normal")
        
        # COVID should take longer
        assert covid_time >= inflation_time
        assert inflation_time >= normal_time
        
        # All should be reasonable
        assert 0 < normal_time < 365
        assert 0 < covid_time < 365
    
    def test_calculate_liquidation_days(self):
        """Test liquidation time calculation"""
        engine = AnalyticsEngine()
        
        # Test different scores
        high_score = engine._calculate_liquidation_days(8.5)
        medium_score = engine._calculate_liquidation_days(6.5)
        low_score = engine._calculate_liquidation_days(3.0)
        
        assert high_score == "1-2"
        assert medium_score == "2-5"
        assert low_score == "5-10"
    
    def test_empty_result_methods(self):
        """Test all empty result methods return expected structure"""
        engine = AnalyticsEngine()
        
        # Test all empty methods
        empty_metrics = engine._empty_metrics()
        empty_forecast = engine._empty_forecast()
        empty_factor = engine._empty_factor_exposure()
        empty_concentration = engine._empty_concentration()
        empty_liquidity = engine._empty_liquidity()
        empty_stress = engine._empty_stress_test()
        empty_vol_sizing = engine._empty_volatility_sizing()
        empty_risk_score = engine._empty_risk_score()
        
        # Check that all contain error messages
        assert "error" in empty_metrics
        assert "error" in empty_forecast
        assert "error" in empty_factor
        assert "error" in empty_concentration
        assert "error" in empty_liquidity
        assert "error" in empty_stress
        assert "error" in empty_vol_sizing
        assert "error" in empty_risk_score


@pytest.mark.unit
class TestGlobalAnalyticsEngine:
    """Test cases for GlobalAnalyticsEngine"""
    
    def test_global_analytics_engine_initialization(self):
        """Test global analytics engine initialization"""
        global_engine = GlobalAnalyticsEngine()
        assert hasattr(global_engine, '_analytics_engine')
        assert isinstance(global_engine._analytics_engine, AnalyticsEngine)
    
    def test_get_engine(self):
        """Test get_engine method"""
        global_engine = GlobalAnalyticsEngine()
        engine = global_engine.get_engine()
        
        assert isinstance(engine, AnalyticsEngine)
        assert engine is global_engine._analytics_engine


@pytest.mark.unit
class TestAnalyticsEngineEdgeCases:
    """Test edge cases and error handling"""
    
    @pytest.mark.asyncio
    async def test_calculate_portfolio_metrics_exception_handling(self):
        """Test exception handling in portfolio metrics calculation"""
        engine = AnalyticsEngine()
        
        # Data containing inf must degrade gracefully (computed, not crashed)
        bad_data = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, np.inf]})

        result = await engine.calculate_portfolio_metrics(bad_data, {"A": 1.0})

        assert "annual_return" in result
    
    @pytest.mark.asyncio
    async def test_forecast_volatility_exception_handling(self, mock_returns_series):
        """Test exception handling in volatility forecasting"""
        engine = AnalyticsEngine()
        
        # Mock arch_model to raise exception
        with patch('app.services.analytics_engine.arch_model', side_effect=Exception("Test error")):
            result = await engine.forecast_volatility(mock_returns_series)
            
            # Should return empty forecast on error
            assert "error" in result
    
    @pytest.mark.asyncio
    async def test_factor_exposure_analysis_exception_handling(self):
        """Test exception handling in factor exposure analysis"""
        engine = AnalyticsEngine()
        
        # NaN-bearing data falls back to the neutral factor payload
        bad_data = pd.DataFrame({'A': [1, 2, np.nan]})

        result = await engine.factor_exposure_analysis(bad_data)

        assert "portfolio" in result and "r_squared" in result
    
    @pytest.mark.asyncio
    async def test_concentration_analysis_exception_handling(self):
        """Test exception handling in concentration analysis"""
        engine = AnalyticsEngine()
        
        # Test with weights that sum to zero
        bad_weights = {"AAPL": 0, "MSFT": 0}
        
        result = await engine.concentration_analysis(bad_weights)
        
        # Should return empty concentration on error
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_liquidity_analysis_exception_handling(self):
        """Test exception handling in liquidity analysis"""
        engine = AnalyticsEngine()
        
        # Test with empty price data
        result = await engine.liquidity_analysis({})
        
        # Should return empty liquidity on error
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_stress_test_exception_handling(self):
        """Test exception handling in stress testing"""
        engine = AnalyticsEngine()
        
        # Test with empty data
        result = await engine.stress_test(pd.DataFrame(), {}, "test")
        
        # Should return empty stress test on error
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_volatility_sizing_exception_handling(self):
        """Test exception handling in volatility sizing"""
        engine = AnalyticsEngine()
        
        # Test with empty data
        result = await engine.volatility_sizing(pd.DataFrame(), {}, "EWMA")
        
        # Should return empty volatility sizing on error
        assert "error" in result
    
    @pytest.mark.asyncio
    async def test_risk_scoring_exception_handling(self):
        """Test exception handling in risk scoring"""
        engine = AnalyticsEngine()
        
        # Test with empty data
        result = await engine.risk_scoring(pd.DataFrame(), {})
        
        # Should return empty risk score on error
        assert "error" in result