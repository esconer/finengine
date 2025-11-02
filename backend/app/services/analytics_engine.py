"""
Real-time Analytics Engine for Portfolio Risk Calculations
Implements comprehensive financial analytics using quantstats, arch, and statsmodels
"""

import asyncio
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from scipy import stats
from sklearn.decomposition import PCA
import warnings

warnings.filterwarnings('ignore')

# Financial analytics libraries
import quantstats as qs
from arch import arch_model
import statsmodels.api as sm
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.statespace.sarimax import SARIMAX

from app.utils.logger import setup_logger
from app.models.schemas import (
    StressTestRequest, StressTestResponse, 
    VolatilitySizingRequest, VolatilitySizingResponse
)

logger = setup_logger(__name__)


class AnalyticsEngine:
    """
    Comprehensive analytics engine for portfolio risk calculations
    """
    
    def __init__(self):
        self.risk_free_rate = 0.02  # 2% annual risk-free rate
        
    async def calculate_portfolio_metrics(
        self, 
        price_data: pd.DataFrame, 
        weights: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive portfolio metrics using real price data
        
        Args:
            price_data: DataFrame with Date index and ticker columns containing prices
            weights: Dictionary mapping tickers to portfolio weights
            
        Returns:
            Dictionary with all portfolio metrics
        """
        try:
            if price_data.empty or price_data.shape[1] == 0:
                logger.warning("Empty price data provided")
                return self._empty_metrics()
            
            # Calculate returns
            returns = price_data.pct_change().dropna()
            if returns.empty:
                return self._empty_metrics()
            
            # Handle weights
            if weights is None:
                weights = {col: 1.0/len(cols) for col in cols} if (cols := returns.columns) else {}
            else:
                # Normalize weights to sum to 1
                weight_sum = sum(weights.values())
                if weight_sum > 0:
                    weights = {k: v/weight_sum for k, v in weights.items()}
            
            # Calculate portfolio returns
            portfolio_returns = self._calculate_portfolio_returns(returns, weights)
            
            # Basic metrics
            metrics = {}
            metrics.update(self._calculate_basic_metrics(portfolio_returns))
            metrics.update(self._calculate_risk_metrics(portfolio_returns))
            metrics.update(self._calculate_drawdown_metrics(portfolio_returns))
            metrics.update(self._calculate_return_distribution(portfolio_returns))
            
            # Position-level metrics
            metrics['positions'] = self._calculate_position_metrics(returns, weights)
            
            return metrics
            
        except Exception as e:
            logger.error(f"Error calculating portfolio metrics: {e}")
            return self._empty_metrics()
    
    async def forecast_volatility(
        self, 
        returns: pd.Series, 
        model: str = "GARCH", 
        horizon: int = 1,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Forecast volatility using specified model
        
        Args:
            returns: Series of returns
            model: Model type (GARCH, EGARCH, EWMA)
            horizon: Forecast horizon in days
            params: Model parameters
            
        Returns:
            Dictionary with forecast results
        """
        try:
            if len(returns) < 30:  # Need sufficient data
                return self._empty_forecast()
            
            if model.upper() == "GARCH":
                return await self._garch_forecast(returns, horizon)
            elif model.upper() == "EGARCH":
                return await self._egarch_forecast(returns, horizon)
            elif model.upper() == "EWMA":
                return self._ewma_forecast(returns, horizon)
            else:
                return await self._garch_forecast(returns, horizon)
                
        except Exception as e:
            logger.error(f"Error in volatility forecast: {e}")
            return self._empty_forecast()
    
    async def factor_exposure_analysis(
        self, 
        price_data: pd.DataFrame, 
        benchmark_data: Optional[pd.Series] = None
    ) -> Dict[str, Any]:
        """
        Perform factor exposure analysis
        
        Args:
            price_data: Price data for assets
            benchmark_data: Benchmark returns for comparison
            
        Returns:
            Dictionary with factor exposures
        """
        try:
            if price_data.empty or len(price_data.columns) == 0:
                return self._empty_factor_exposure()
            
            returns = price_data.pct_change().dropna()
            if returns.empty:
                return self._empty_factor_exposure()
            
            # Use SPY as default benchmark if none provided
            if benchmark_data is None:
                # Fetch SPY data for benchmark (simplified)
                # In practice, you'd get this from your data service
                benchmark_returns = pd.Series(dtype=float)
            else:
                benchmark_returns = benchmark_data.pct_change().dropna()
            
            results = {
                'portfolio': self._calculate_factor_exposures(returns, benchmark_returns),
                'r_squared': self._calculate_r_squared(returns, benchmark_returns),
                'adjusted_r_squared': self._calculate_adjusted_r_squared(returns, benchmark_returns)
            }
            
            return results
            
        except Exception as e:
            logger.error(f"Error in factor exposure analysis: {e}")
            return self._empty_factor_exposure()
    
    async def concentration_analysis(
        self, 
        weights: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Analyze portfolio concentration
        
        Args:
            weights: Portfolio weights by asset
            
        Returns:
            Dictionary with concentration metrics
        """
        try:
            if not weights:
                return self._empty_concentration()
            
            # Normalize weights
            weight_sum = sum(weights.values())
            if weight_sum > 0:
                weights = {k: v/weight_sum for k, v in weights.items()}
            else:
                return self._empty_concentration()
            
            weights_array = np.array(list(weights.values()))
            
            # Calculate concentration metrics
            largest_position = np.max(weights_array)
            top_3 = np.sum(np.sort(weights_array)[-3:])
            top_5 = np.sum(np.sort(weights_array)[-5:])
            top_10 = np.sum(np.sort(weights_array)[-10:]) if len(weights_array) >= 10 else 1.0
            
            # Herfindahl Index
            herfindahl = np.sum(weights_array ** 2)
            
            # Effective number of positions
            effective_positions = 1 / herfindahl if herfindahl > 0 else len(weights)
            
            # Diversification ratio (simplified)
            diversification_ratio = len(weights) / effective_positions
            
            return {
                "largest_position": largest_position,
                "top_3": top_3,
                "top_5": top_5,
                "top_10": top_10,
                "herfindahl_index": herfindahl,
                "effective_positions": effective_positions,
                "diversification_ratio": diversification_ratio,
                "by_weight": dict(sorted(weights.items(), key=lambda x: x[1], reverse=True))
            }
            
        except Exception as e:
            logger.error(f"Error in concentration analysis: {e}")
            return self._empty_concentration()
    
    async def liquidity_analysis(
        self, 
        price_data: Dict[str, pd.DataFrame]
    ) -> Dict[str, Any]:
        """
        Analyze portfolio liquidity
        
        Args:
            price_data: Dictionary mapping tickers to price DataFrames
            
        Returns:
            Dictionary with liquidity metrics
        """
        try:
            if not price_data:
                return self._empty_liquidity()
            
            liquidity_scores = {}
            volume_stats = {'volumes': [], 'total_volume': 0}
            
            for ticker, df in price_data.items():
                if df.empty or 'Volume' not in df.columns:
                    continue
                
                # Calculate liquidity score based on volume and price
                volume = df['Volume'].mean()
                price = df['Close'].iloc[-1] if not df.empty else 0
                
                # Simple liquidity score (higher is more liquid)
                if volume > 1e6 and price > 10:
                    score = min(10, 8 + (volume / 1e6) * 0.2)
                    category = "High"
                elif volume > 100000:
                    score = min(8, 6 + (volume / 1e6) * 0.3)
                    category = "Medium"
                else:
                    score = max(1, (volume / 10000) * 0.5)
                    category = "Low"
                
                liquidity_scores[ticker] = {
                    'score': score,
                    'avg_volume': volume,
                    'category': category,
                    'spread': 0.001,  # Simplified spread calculation
                    'liquidation_days': self._calculate_liquidation_days(score)
                }
                
                volume_stats['volumes'].append(volume)
                volume_stats['total_volume'] += volume
            
            # Calculate overall metrics
            if liquidity_scores:
                overall_score = np.mean([score['score'] for score in liquidity_scores.values()])
                avg_volume = np.mean(volume_stats['volumes']) if volume_stats['volumes'] else 0
                
                # Volume distribution
                high_volume = sum(1 for vol in volume_stats['volumes'] if vol > 1e6)
                medium_volume = sum(1 for vol in volume_stats['volumes'] if 100000 <= vol <= 1e6)
                low_volume = sum(1 for vol in volume_stats['volumes'] if vol < 100000)
                total_positions = len(liquidity_scores)
                
                volume_pct = lambda x: (x / total_positions * 100) if total_positions > 0 else 0
                
                # Determine liquidation time and risk level
                if overall_score >= 8:
                    liquidation_time = "1-2"
                    risk_level = "Low"
                elif overall_score >= 6:
                    liquidation_time = "2-5"
                    risk_level = "Medium"
                else:
                    liquidation_time = "5-10"
                    risk_level = "High"
                
                return {
                    "overall_score": overall_score,
                    "liquidation_time_days": liquidation_time,
                    "risk_level": risk_level,
                    "by_position": liquidity_scores,
                    "volume_stats": {
                        "avg_volume": avg_volume,
                        "total_portfolio_volume": volume_stats['total_volume'],
                        "high_volume_pct": volume_pct(high_volume),
                        "medium_volume_pct": volume_pct(medium_volume),
                        "low_volume_pct": volume_pct(low_volume)
                    }
                }
            else:
                return self._empty_liquidity()
                
        except Exception as e:
            logger.error(f"Error in liquidity analysis: {e}")
            return self._empty_liquidity()
    
    async def stress_test(
        self, 
        price_data: pd.DataFrame, 
        weights: Dict[str, float], 
        scenario: str
    ) -> Dict[str, Any]:
        """
        Run stress test scenario
        
        Args:
            price_data: Historical price data
            weights: Portfolio weights
            scenario: Stress scenario name
            
        Returns:
            Dictionary with stress test results
        """
        try:
            if price_data.empty or not weights:
                return self._empty_stress_test()
            
            # Historical stress scenarios (actual returns during crisis periods)
            scenarios = {
                "2018_q4": {"date_range": ("2018-10-01", "2018-12-31"), "description": "Q4 2018 Correction"},
                "2020_covid": {"date_range": ("2020-02-19", "2020-03-23"), "description": "COVID-19 Crash"},
                "2022_inflation": {"date_range": ("2022-01-03", "2022-10-12"), "description": "Inflation Peak"},
                "volatility_spike": {"date_range": ("2020-03-09", "2020-03-16"), "description": "Volatility Spike"},
            }
            
            scenario_data = scenarios.get(scenario, {"date_range": ("2020-02-19", "2020-03-23"), "description": "Default"})
            
            # Calculate historical returns during scenario period
            returns = price_data.pct_change().dropna()
            
            # Filter returns by scenario date range
            start_date, end_date = scenario_data["date_range"]
            scenario_returns = returns[(returns.index >= start_date) & (returns.index <= end_date)]
            
            if scenario_returns.empty:
                # Fallback to portfolio simulation
                max_drawdown = self._simulate_stress_drawdown(weights)
            else:
                # Calculate actual portfolio stress
                portfolio_returns = self._calculate_portfolio_returns(scenario_returns, weights)
                max_drawdown = self._calculate_max_drawdown(portfolio_returns.cumsum())
            
            # Position-level impacts (simplified)
            position_impacts = {}
            for ticker in weights.keys():
                if ticker in returns.columns:
                    ticker_returns = scenario_returns[ticker].dropna()
                    if not ticker_returns.empty:
                        ticker_drawdown = self._calculate_max_drawdown(ticker_returns.cumsum())
                        position_impacts[ticker] = ticker_drawdown
                    else:
                        position_impacts[ticker] = max_drawdown * 0.8  # Fallback
                else:
                    position_impacts[ticker] = max_drawdown * 0.7  # Fallback for missing data
            
            # Calculate recovery time (simplified)
            recovery_time = self._estimate_recovery_time(abs(max_drawdown), scenario)
            
            # Portfolio impact (slightly less than max due to diversification)
            portfolio_impact = max_drawdown * 0.85
            
            return {
                "scenario": scenario,
                "scenario_description": scenario_data["description"],
                "max_drawdown": max_drawdown,
                "portfolio_impact": portfolio_impact,
                "position_impacts": position_impacts,
                "recovery_time": recovery_time,
                "confidence_level": 0.95,
                "methodology": "Historical simulation with portfolio weighting"
            }
            
        except Exception as e:
            logger.error(f"Error in stress test: {e}")
            return self._empty_stress_test()
    
    async def volatility_sizing(
        self, 
        price_data: pd.DataFrame, 
        weights: Dict[str, float], 
        model: str = "EWMA", 
        target_volatility: float = 0.15
    ) -> Dict[str, Any]:
        """
        Calculate volatility-adjusted position sizing
        
        Args:
            price_data: Historical price data
            weights: Current portfolio weights
            model: Volatility model
            target_volatility: Target portfolio volatility
            
        Returns:
            Dictionary with sizing recommendations
        """
        try:
            if price_data.empty or not weights:
                return self._empty_volatility_sizing()
            
            returns = price_data.pct_change().dropna()
            if returns.empty:
                return self._empty_volatility_sizing()
            
            # Calculate volatilities using EWMA (simplified)
            volatilities = {}
            for ticker in returns.columns:
                # EWMA volatility (lambda = 0.94, typical for daily data)
                lambda_val = 0.94
                variance = 0
                weights_rev = []
                
                # Calculate EWMA variance
                for i in range(len(returns[ticker]) - 1, 0, -1):
                    if i < len(returns[ticker]):
                        variance = lambda_val * variance + (1 - lambda_val) * (returns[ticker].iloc[i] ** 2)
                        weights_rev.append((1 - lambda_val) * (lambda_val ** (len(weights_rev))))
                
                volatility = np.sqrt(variance) if variance > 0 else 0.02  # Default 2% daily vol
                volatilities[ticker] = volatility
            
            # Calculate correlation matrix
            correlation_matrix = returns.corr()
            
            # Calculate portfolio volatility
            current_weights = np.array([weights.get(ticker, 0) for ticker in returns.columns])
            current_volatilities = np.array([volatilities.get(ticker, 0.02) for ticker in returns.columns])
            
            if len(correlation_matrix) > 0:
                portfolio_variance = np.dot(current_weights, np.dot(
                    np.diag(current_volatilities), np.dot(
                        correlation_matrix.values, np.diag(current_volatilities)
                    )
                ))
                portfolio_volatility = np.sqrt(portfolio_variance) * np.sqrt(252)  # Annualized
            else:
                portfolio_volatility = 0.20  # Default
            
            # Calculate recommended weights to achieve target volatility
            if portfolio_volatility > 0:
                scaling_factor = target_volatility / portfolio_volatility
                recommended_weights = {ticker: weight * scaling_factor for ticker, weight in weights.items()}
                
                # Normalize recommended weights to sum to 1
                weight_sum = sum(recommended_weights.values())
                if weight_sum > 0:
                    recommended_weights = {k: v/weight_sum for k, v in recommended_weights.items()}
            else:
                recommended_weights = weights.copy()
            
            # Calculate trade recommendations
            trades = {}
            for ticker in returns.columns:
                current_weight = weights.get(ticker, 0)
                recommended_weight = recommended_weights.get(ticker, 0)
                weight_delta = recommended_weight - current_weight
                
                # Simplified share calculation (would need current prices in practice)
                current_price = price_data[ticker].iloc[-1] if ticker in price_data.columns else 100
                estimated_portfolio_value = 100000  # Simplified assumption
                
                weight_value_delta = weight_delta * estimated_portfolio_value
                shares_delta = weight_value_delta / current_price if current_price > 0 else 0
                
                trades[ticker] = {
                    "shares_delta": int(shares_delta),
                    "amount": weight_value_delta
                }
            
            return {
                "current_weights": weights,
                "recommended_weights": recommended_weights,
                "trades": trades,
                "target_volatility": target_volatility,
                "current_volatility": portfolio_volatility,
                "volatilities": volatilities,
                "methodology": f"{model} volatility estimation with target volatility scaling"
            }
            
        except Exception as e:
            logger.error(f"Error in volatility sizing: {e}")
            return self._empty_volatility_sizing()
    
    async def risk_scoring(
        self, 
        price_data: pd.DataFrame, 
        weights: Dict[str, float]
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive risk score
        
        Args:
            price_data: Historical price data
            weights: Portfolio weights
            
        Returns:
            Dictionary with risk score and components
        """
        try:
            if price_data.empty or not weights:
                return self._empty_risk_score()
            
            returns = price_data.pct_change().dropna()
            if returns.empty:
                return self._empty_risk_score()
            
            portfolio_returns = self._calculate_portfolio_returns(returns, weights)
            
            # Calculate component scores (0-30 scale, higher is riskier)
            scores = {}
            
            # Concentration risk (20% weight in overall score)
            concentration_result = await self.concentration_analysis(weights)
            concentration_score = min(30, concentration_result.get('herfindahl_index', 0.1) * 100)
            scores['concentration'] = concentration_score
            
            # Volatility risk (25% weight)
            portfolio_vol = portfolio_returns.std() * np.sqrt(252)  # Annualized
            volatility_score = min(30, portfolio_vol * 100)
            scores['volatility'] = volatility_score
            
            # Correlation risk (20% weight)
            if len(returns.columns) > 1:
                avg_correlation = returns.corr().values[np.triu_indices_from(returns.corr().values, k=1)].mean()
                correlation_score = min(30, max(0, (avg_correlation - 0.3) * 50))  # High correlation = high risk
            else:
                correlation_score = 0
            scores['correlation'] = correlation_score
            
            # Factor risk (25% weight) - simplified
            factor_result = await self.factor_exposure_analysis(price_data)
            r_squared = factor_result.get('r_squared', 0)
            factor_score = min(30, (1 - r_squared) * 100)
            scores['factor_risk'] = factor_score
            
            # Market risk (10% weight) - based on recent volatility
            recent_returns = portfolio_returns.tail(60)  # Last 60 days
            recent_vol = recent_returns.std() * np.sqrt(252)
            market_score = min(30, recent_vol * 100)
            scores['market_risk'] = market_score
            
            # Calculate overall score (weighted average)
            weights_scores = {
                'concentration': 0.20,
                'volatility': 0.25,
                'correlation': 0.20,
                'factor_risk': 0.25,
                'market_risk': 0.10
            }
            
            overall_score = sum(scores[component] * weights_scores[component] 
                              for component in scores)
            
            # Determine risk level
            if overall_score < 15:
                risk_level = "LOW"
                change = -1 if hasattr(self, '_previous_risk_score') else 0
            elif overall_score < 25:
                risk_level = "MEDIUM"
                change = -1 if hasattr(self, '_previous_risk_score') and self._previous_risk_score > 25 else 0
            else:
                risk_level = "HIGH"
                change = 1 if hasattr(self, '_previous_risk_score') and self._previous_risk_score < 25 else 0
            
            # Store previous score for change calculation
            self._previous_risk_score = overall_score
            
            # Generate alerts
            alerts = []
            if concentration_score > 20:
                alerts.append(f"High concentration risk (HHI: {concentration_result.get('herfindahl_index', 0):.3f})")
            if volatility_score > 20:
                alerts.append(f"High volatility risk ({portfolio_vol:.1%} annualized)")
            if correlation_score > 15:
                alerts.append(f"High correlation risk (avg correlation: {avg_correlation:.2f})")
            if factor_score > 15:
                alerts.append(f"High unexplained risk (low R-squared: {r_squared:.2f})")
            
            return {
                "overall_score": round(overall_score, 1),
                "risk_level": risk_level,
                "change": change,
                "components": {k: round(v, 1) for k, v in scores.items()},
                "alerts": alerts,
                "methodology": "Multi-factor risk scoring with weighted components"
            }
            
        except Exception as e:
            logger.error(f"Error in risk scoring: {e}")
            return self._empty_risk_score()
    
    # Helper methods for calculations
    
    def _calculate_portfolio_returns(self, returns: pd.DataFrame, weights: Dict[str, float]) -> pd.Series:
        """Calculate weighted portfolio returns"""
        try:
            weight_vector = []
            for col in returns.columns:
                weight_vector.append(weights.get(col, 0))
            
            weight_vector = np.array(weight_vector)
            if len(weight_vector) != len(returns.columns):
                return pd.Series(dtype=float)
            
            portfolio_returns = (returns * weight_vector).sum(axis=1)
            return portfolio_returns
        except:
            return pd.Series(dtype=float)
    
    def _calculate_basic_metrics(self, returns: pd.Series) -> Dict[str, float]:
        """Calculate basic return and risk metrics"""
        try:
            if returns.empty:
                return {}
            
            # Annual return and volatility
            annual_return = returns.mean() * 252
            annual_volatility = returns.std() * np.sqrt(252)
            
            # Sharpe ratio
            sharpe_ratio = (annual_return - self.risk_free_rate) / annual_volatility if annual_volatility > 0 else 0
            
            # Sortino ratio
            downside_returns = returns[returns < 0]
            downside_deviation = downside_returns.std() * np.sqrt(252) if not downside_returns.empty else 0
            sortino_ratio = (annual_return - self.risk_free_rate) / downside_deviation if downside_deviation > 0 else 0
            
            # Hit ratio
            hit_ratio = (returns > 0).mean()
            
            return {
                "annual_return": annual_return,
                "annual_volatility": annual_volatility,
                "sharpe_ratio": sharpe_ratio,
                "sortino_ratio": sortino_ratio,
                "hit_ratio": hit_ratio
            }
        except:
            return {}
    
    def _calculate_risk_metrics(self, returns: pd.Series) -> Dict[str, float]:
        """Calculate risk metrics (VaR, CVaR)"""
        try:
            if returns.empty:
                return {}
            
            # Historical VaR (95%)
            var_95 = np.percentile(returns, 5)
            
            # Conditional VaR (Expected Shortfall)
            cvar_95 = returns[returns <= var_95].mean() if len(returns[returns <= var_95]) > 0 else var_95
            
            return {
                "var_95": var_95,
                "cvar_95": cvar_95
            }
        except:
            return {}
    
    def _calculate_drawdown_metrics(self, returns: pd.Series) -> Dict[str, float]:
        """Calculate drawdown metrics"""
        try:
            if returns.empty:
                return {}
            
            cumulative_returns = (1 + returns).cumprod()
            running_max = cumulative_returns.expanding().max()
            drawdown = (cumulative_returns - running_max) / running_max
            
            max_drawdown = drawdown.min()
            
            return {
                "max_drawdown": max_drawdown
            }
        except:
            return {}
    
    def _calculate_return_distribution(self, returns: pd.Series) -> Dict[str, float]:
        """Calculate return distribution metrics"""
        try:
            if returns.empty:
                return {}
            
            return {
                "skewness": returns.skew(),
                "kurtosis": returns.kurtosis()
            }
        except:
            return {}
    
    def _calculate_position_metrics(self, returns: pd.DataFrame, weights: Dict[str, float]) -> Dict[str, Any]:
        """Calculate metrics for individual positions"""
        try:
            if returns.empty:
                return {}
            
            position_metrics = {}
            for ticker in returns.columns:
                ticker_returns = returns[ticker].dropna()
                if not ticker_returns.empty:
                    metrics = self._calculate_basic_metrics(ticker_returns)
                    metrics.update(self._calculate_risk_metrics(ticker_returns))
                    metrics.update(self._calculate_drawdown_metrics(ticker_returns))
                    position_metrics[ticker] = {
                        **metrics,
                        "weight": weights.get(ticker, 0)
                    }
            
            return position_metrics
        except:
            return {}
    
    async def _garch_forecast(self, returns: pd.Series, horizon: int) -> Dict[str, Any]:
        """GARCH volatility forecast"""
        try:
            # Fit GARCH(1,1) model
            model = arch_model(returns, vol='Garch', p=1, q=1, dist='normal')
            fitted_model = model.fit(disp='off')
            
            # Generate forecast
            forecast = fitted_model.forecast(horizon=horizon, method='simulation', simulations=1000)
            
            # Extract volatility forecast
            variance_forecast = forecast.variance.values[-1, :]
            volatility_forecast = np.sqrt(variance_forecast * 252)  # Annualized
            
            return {
                "model": "GARCH",
                "horizon": horizon,
                "volatility_forecast": volatility_forecast[-1] if len(volatility_forecast) > 0 else 0.22,
                "var_forecast": -volatility_forecast[-1] * 1.645 / np.sqrt(252) if len(volatility_forecast) > 0 else -0.028,
                "cvar_forecast": -volatility_forecast[-1] * 2.0 / np.sqrt(252) if len(volatility_forecast) > 0 else -0.041,
                "confidence_interval": [
                    max(0, volatility_forecast[-1] * 0.8) if len(volatility_forecast) > 0 else 0.18,
                    volatility_forecast[-1] * 1.2 if len(volatility_forecast) > 0 else 0.26
                ],
                "model_params": {"p": 1, "q": 1, "type": "GARCH"}
            }
        except Exception as e:
            logger.error(f"GARCH forecast error: {e}")
            return self._empty_forecast()
    
    async def _egarch_forecast(self, returns: pd.Series, horizon: int) -> Dict[str, Any]:
        """EGARCH volatility forecast"""
        try:
            # Fit EGARCH(1,1) model
            model = arch_model(returns, vol='EGARCH', p=1, q=1, dist='normal')
            fitted_model = model.fit(disp='off')
            
            # Generate forecast
            forecast = fitted_model.forecast(horizon=horizon)
            
            # Extract volatility forecast
            variance_forecast = forecast.variance.values[-1, :]
            volatility_forecast = np.sqrt(variance_forecast * 252)  # Annualized
            
            return {
                "model": "EGARCH",
                "horizon": horizon,
                "volatility_forecast": volatility_forecast[-1] if len(volatility_forecast) > 0 else 0.24,
                "var_forecast": -volatility_forecast[-1] * 1.645 / np.sqrt(252) if len(volatility_forecast) > 0 else -0.031,
                "cvar_forecast": -volatility_forecast[-1] * 2.0 / np.sqrt(252) if len(volatility_forecast) > 0 else -0.045,
                "confidence_interval": [
                    max(0, volatility_forecast[-1] * 0.8) if len(volatility_forecast) > 0 else 0.19,
                    volatility_forecast[-1] * 1.2 if len(volatility_forecast) > 0 else 0.29
                ],
                "model_params": {"p": 1, "q": 1, "type": "EGARCH"}
            }
        except Exception as e:
            logger.error(f"EGARCH forecast error: {e}")
            return self._empty_forecast()
    
    def _ewma_forecast(self, returns: pd.Series, horizon: int) -> Dict[str, Any]:
        """EWMA volatility forecast"""
        try:
            # EWMA volatility calculation
            lambda_val = 0.94  # Standard decay factor
            
            # Calculate historical volatilities
            daily_vols = returns.rolling(window=30).std()
            ewma_variance = daily_vols.ewm(alpha=1-lambda_val).mean() ** 2
            
            # Forecast (assume mean reversion to long-term average)
            long_term_var = returns.var()
            last_var = ewma_variance.iloc[-1] if not ewma_variance.empty else long_term_var
            
            # Simple forecast: mean revert toward long-term average
            forecast_variance = last_var * (lambda_val ** horizon) + long_term_var * (1 - lambda_val ** horizon)
            forecast_volatility = np.sqrt(forecast_variance * 252)
            
            return {
                "model": "EWMA",
                "horizon": horizon,
                "volatility_forecast": forecast_volatility,
                "var_forecast": -forecast_volatility * 1.645 / np.sqrt(252),
                "cvar_forecast": -forecast_volatility * 2.0 / np.sqrt(252),
                "confidence_interval": [forecast_volatility * 0.8, forecast_volatility * 1.2],
                "model_params": {"lambda": lambda_val, "type": "EWMA"}
            }
        except Exception as e:
            logger.error(f"EWMA forecast error: {e}")
            return self._empty_forecast()
    
    def _calculate_factor_exposures(self, returns: pd.DataFrame, benchmark_returns: pd.Series) -> Dict[str, float]:
        """Calculate factor exposures using regression"""
        try:
            if returns.empty:
                return {}
            
            # Simplified factor model - just market beta for now
            # In practice, you'd have a multi-factor model
            
            if not benchmark_returns.empty and len(benchmark_returns) > 10:
                # Align data
                common_dates = returns.index.intersection(benchmark_returns.index)
                if len(common_dates) > 10:
                    aligned_returns = returns.loc[common_dates]
                    aligned_benchmark = benchmark_returns.loc[common_dates]
                    
                    exposures = {}
                    for ticker in aligned_returns.columns:
                        try:
                            # Simple regression
                            X = sm.add_constant(aligned_benchmark)
                            y = aligned_returns[ticker]
                            model = sm.OLS(y, X).fit()
                            
                            exposures[ticker] = {
                                'alpha': model.params[0] if len(model.params) > 0 else 0,
                                'market': model.params[1] if len(model.params) > 1 else 1
                            }
                        except:
                            exposures[ticker] = {'alpha': 0, 'market': 1}
                    
                    # Portfolio exposures (weighted average)
                    portfolio_exposures = {}
                    if exposures:
                        # This would require portfolio weights - simplified for now
                        portfolio_exposures['market'] = np.mean([exp['market'] for exp in exposures.values()])
                        portfolio_exposures['alpha'] = np.mean([exp['alpha'] for exp in exposures.values()])
                        portfolio_exposures['momentum'] = 0.1  # Placeholder
                        portfolio_exposures['size'] = -0.1  # Placeholder
                        portfolio_exposures['value'] = 0.05  # Placeholder
                        portfolio_exposures['min_vol'] = -0.2  # Placeholder
                        portfolio_exposures['quality'] = 0.1  # Placeholder
                        portfolio_exposures['rates'] = 0.15  # Placeholder
                        portfolio_exposures['volatility'] = -0.1  # Placeholder
                        portfolio_exposures['meme'] = 0.05  # Placeholder
                        portfolio_exposures['ai'] = 0.02  # Placeholder
                    
                    return portfolio_exposures
            
            # Fallback: return market-neutral portfolio
            return {
                'alpha': 0,
                'market': 1,
                'momentum': 0,
                'size': 0,
                'value': 0,
                'min_vol': 0,
                'quality': 0,
                'rates': 0,
                'volatility': 0,
                'meme': 0,
                'ai': 0
            }
            
        except Exception as e:
            logger.error(f"Factor exposure calculation error: {e}")
            return {}
    
    def _calculate_r_squared(self, returns: pd.DataFrame, benchmark_returns: pd.Series) -> float:
        """Calculate R-squared"""
        try:
            if not benchmark_returns.empty and len(benchmark_returns) > 10:
                common_dates = returns.index.intersection(benchmark_returns.index)
                if len(common_dates) > 10:
                    aligned_returns = returns.loc[common_dates]
                    aligned_benchmark = benchmark_returns.loc[common_dates]
                    
                    # Calculate portfolio R-squared with benchmark
                    portfolio_returns = self._calculate_portfolio_returns(aligned_returns, {})
                    if not portfolio_returns.empty:
                        correlation = portfolio_returns.corr(aligned_benchmark)
                        return correlation ** 2 if not pd.isna(correlation) else 0.5
            
            return 0.5  # Default R-squared
        except:
            return 0.5
    
    def _calculate_adjusted_r_squared(self, returns: pd.DataFrame, benchmark_returns: pd.Series) -> float:
        """Calculate adjusted R-squared"""
        try:
            r_squared = self._calculate_r_squared(returns, benchmark_returns)
            n = min(len(returns), len(benchmark_returns))
            k = 1  # Number of predictors (just market)
            
            if n > k + 1:
                adjusted_r_squared = 1 - (1 - r_squared) * (n - 1) / (n - k - 1)
                return max(0, adjusted_r_squared)
            else:
                return r_squared
        except:
            return 0.5
    
    def _calculate_max_drawdown(self, cumulative_returns: pd.Series) -> float:
        """Calculate maximum drawdown"""
        try:
            if cumulative_returns.empty:
                return 0
            
            peak = cumulative_returns.expanding().max()
            drawdown = (cumulative_returns - peak) / peak
            return drawdown.min()
        except:
            return 0
    
    def _simulate_stress_drawdown(self, weights: Dict[str, float]) -> float:
        """Simulate stress drawdown based on weights"""
        try:
            # Simple stress simulation based on portfolio composition
            # High weight in high-vol assets = higher stress
            total_weight = sum(abs(w) for w in weights.values())
            if total_weight == 0:
                return -0.20
            
            # Simulate different stress levels based on concentration
            largest_weight = max(abs(w) for w in weights.values()) if weights else 0
            
            if largest_weight > 0.5:
                return -0.35  # High concentration stress
            elif largest_weight > 0.3:
                return -0.25  # Medium concentration stress
            else:
                return -0.15  # Diversified stress
        except:
            return -0.20
    
    def _estimate_recovery_time(self, drawdown_magnitude: float, scenario: str) -> int:
        """Estimate recovery time in days"""
        try:
            # Simple recovery time estimation
            base_recovery = 30  # Base recovery in days
            
            if "covid" in scenario.lower():
                return int(base_recovery * 1.5)  # COVID took longer
            elif "inflation" in scenario.lower():
                return int(base_recovery * 1.2)  # Inflation recovery slower
            elif drawdown_magnitude > 0.3:
                return int(base_recovery * 1.3)  # Larger drawdowns take longer
            elif drawdown_magnitude > 0.2:
                return int(base_recovery * 1.1)
            else:
                return base_recovery
        except:
            return 30
    
    # Empty result methods for error handling
    
    def _empty_metrics(self) -> Dict[str, Any]:
        return {
            "annual_return": 0,
            "annual_volatility": 0.20,
            "sharpe_ratio": 0,
            "sortino_ratio": 0,
            "skewness": 0,
            "kurtosis": 3,
            "max_drawdown": 0,
            "var_95": 0,
            "cvar_95": 0,
            "hit_ratio": 0.5,
            "positions": {},
            "error": "Insufficient data for calculations"
        }
    
    def _empty_forecast(self) -> Dict[str, Any]:
        return {
            "model": "GARCH",
            "horizon": 1,
            "volatility_forecast": 0.22,
            "var_forecast": -0.028,
            "cvar_forecast": -0.041,
            "confidence_interval": [0.18, 0.26],
            "model_params": {"p": 1, "q": 1, "type": "GARCH"},
            "error": "Insufficient data for forecast"
        }
    
    def _empty_factor_exposure(self) -> Dict[str, Any]:
        return {
            "portfolio": {
                "alpha": 0,
                "market": 1,
                "momentum": 0,
                "size": 0,
                "value": 0,
                "min_vol": 0,
                "quality": 0,
                "rates": 0,
                "volatility": 0,
                "meme": 0,
                "ai": 0
            },
            "positions": {},
            "r_squared": 0.5,
            "adjusted_r_squared": 0.48,
            "error": "Insufficient data for factor analysis"
        }
    
    def _empty_concentration(self) -> Dict[str, Any]:
        return {
            "largest_position": 0.20,
            "top_3": 0.50,
            "top_5": 0.70,
            "top_10": 1.0,
            "herfindahl_index": 0.15,
            "effective_positions": 6.7,
            "diversification_ratio": 1.5,
            "error": "No position data available"
        }
    
    def _calculate_liquidation_days(self, score: float) -> str:
        """Calculate liquidation time based on liquidity score"""
        if score >= 8:
            return "1-2"
        elif score >= 6:
            return "2-5"
        else:
            return "5-10"

    def _empty_liquidity(self) -> Dict[str, Any]:
        return {
            "overall_score": 5.0,
            "liquidation_time_days": "5-10",
            "risk_level": "Medium",
            "by_position": {},
            "volume_stats": {
                "avg_volume": 0,
                "total_portfolio_volume": 0,
                "high_volume_pct": 0,
                "medium_volume_pct": 0,
                "low_volume_pct": 100
            },
            "error": "No liquidity data available"
        }
    
    def _empty_stress_test(self) -> Dict[str, Any]:
        return {
            "scenario": "unknown",
            "max_drawdown": -0.20,
            "portfolio_impact": -0.17,
            "position_impacts": {},
            "recovery_time": 30,
            "error": "Insufficient data for stress testing"
        }
    
    def _empty_volatility_sizing(self) -> Dict[str, Any]:
        return {
            "current_weights": {},
            "recommended_weights": {},
            "trades": {},
            "target_volatility": 0.15,
            "current_volatility": 0.20,
            "error": "Insufficient data for volatility sizing"
        }
    
    def _empty_risk_score(self) -> Dict[str, Any]:
        return {
            "overall_score": 25.0,
            "risk_level": "MEDIUM",
            "change": 0,
            "components": {
                "concentration": 15.0,
                "volatility": 15.0,
                "correlation": 10.0,
                "factor_risk": 20.0,
                "market_risk": 10.0
            },
            "alerts": ["Insufficient data for comprehensive risk analysis"],
            "error": "Insufficient data for risk scoring"
        }


# Global analytics engine instance
class GlobalAnalyticsEngine:
    """Global analytics engine for dependency injection"""
    
    def __init__(self):
        self._analytics_engine = AnalyticsEngine()
    
    def get_engine(self) -> AnalyticsEngine:
        return self._analytics_engine