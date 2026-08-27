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
            
            # Calculate returns with defensive forward/back filling for mixed inception dates
            cleaned_prices = price_data.sort_index().ffill().bfill()
            returns = cleaned_prices.pct_change(fill_method=None).fillna(0.0)
            if returns.empty or len(returns) < 2:
                return self._empty_metrics()
            returns = returns.iloc[1:]
            
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
            
            # Position-level metrics using active price series
            metrics['positions'] = self._calculate_position_metrics(returns, weights, raw_prices=price_data)
            
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
        benchmark_data: Optional[pd.Series] = None,
        weights: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Perform factor exposure analysis
        
        Args:
            price_data: Price data for assets
            benchmark_data: Benchmark returns (or prices) for comparison
            weights: Portfolio weights dictionary
            
        Returns:
            Dictionary with factor exposures (alpha, market beta, r_squared)
        """
        try:
            if price_data.empty or len(price_data.columns) == 0:
                return self._empty_factor_exposure()
            
            cleaned_prices = price_data.sort_index().ffill().bfill()
            returns = cleaned_prices.pct_change(fill_method=None).fillna(0.0)
            if returns.empty or len(returns) < 2:
                return self._empty_factor_exposure()
            returns = returns.iloc[1:]

            if weights is None:
                eq = 1.0 / len(returns.columns)
                weights = {col: eq for col in returns.columns}
            else:
                w_sum = sum(weights.values())
                if w_sum > 0:
                    weights = {k: v / w_sum for k, v in weights.items()}
                else:
                    eq = 1.0 / len(returns.columns)
                    weights = {col: eq for col in returns.columns}
            
            # Benchmark returns
            if benchmark_data is None or benchmark_data.empty:
                benchmark_returns = pd.Series(dtype=float)
            else:
                if (benchmark_data.abs() > 1.0).any():
                    benchmark_returns = benchmark_data.pct_change(fill_method=None).dropna()
                else:
                    benchmark_returns = benchmark_data.dropna()
            
            exposures_result = self._calculate_factor_exposures(returns, benchmark_returns, weights)
            r2 = self._calculate_r_squared(returns, benchmark_returns, weights)
            adj_r2 = self._calculate_adjusted_r_squared(returns, benchmark_returns, weights)

            results = {
                'portfolio': exposures_result.get('portfolio', {'alpha': 0.0, 'market': 1.0}),
                'positions': exposures_result.get('positions', {}),
                'r_squared': r2,
                'adjusted_r_squared': adj_r2
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
            
            scenario_key = (scenario or "").lower().strip().replace(" ", "_").replace("-", "_")

            # Standard institutional stress test scenarios
            scenarios_config = {
                "market_crash": {"market_shock": -0.35, "recovery_months": 24, "description": "Global Financial Crisis / Severe Market Crash (-35% NIFTY shock)"},
                "interest_rate_shock": {"market_shock": -0.15, "recovery_months": 9, "description": "300bp RBI / Global Central Bank Interest Rate Hike (-15% shock)"},
                "volatility_spike": {"market_shock": -0.22, "recovery_months": 5, "description": "COVID-19 style VIX > 40 Sudden Volatility Spike (-22% shock)"},
                "tech_sector_correction": {"market_shock": -0.18, "recovery_months": 12, "description": "Broad Tech & Growth Multiple De-rating (-18% shock)"},
                "2020_covid": {"market_shock": -0.28, "recovery_months": 6, "description": "March 2020 COVID Market Crash"},
                "2022_inflation": {"market_shock": -0.16, "recovery_months": 10, "description": "2022 Global Inflationary Tightening"},
                "2018_q4": {"market_shock": -0.14, "recovery_months": 7, "description": "Q4 2018 Market Correction"},
            }

            matched_scenario = None
            for k, cfg in scenarios_config.items():
                if k in scenario_key or scenario_key in k:
                    matched_scenario = (k, cfg)
                    break
            
            if not matched_scenario:
                # Check for custom shock if present in scenario string (e.g. -25)
                matched_scenario = ("custom_stress", {
                    "market_shock": -0.20,
                    "recovery_months": 12,
                    "description": scenario or "Custom Scenario Shock"
                })

            sc_name, sc_cfg = matched_scenario
            market_shock = sc_cfg["market_shock"]
            recovery_months = sc_cfg["recovery_months"]
            description = sc_cfg["description"]

            # Calculate asset-level beta vs market or volatility scaling
            cleaned_prices = price_data.sort_index().ffill().bfill()
            returns = cleaned_prices.pct_change(fill_method=None).fillna(0.0)
            if returns.empty or len(returns) < 2:
                return self._empty_stress_test()
            returns = returns.iloc[1:]
            position_impacts: Dict[str, float] = {}
            weighted_impact = 0.0

            for ticker, weight in weights.items():
                if ticker in returns.columns and len(returns[ticker].dropna()) > 20:
                    ticker_ret = returns[ticker].dropna()
                    # Relative volatility vs market proxy
                    ticker_vol = float(ticker_ret.std() * np.sqrt(252))
                    vol_factor = max(0.6, min(2.5, ticker_vol / 0.16)) if ticker_vol > 0 else 1.0
                    ticker_impact = float(market_shock * vol_factor)
                else:
                    ticker_impact = float(market_shock)
                
                position_impacts[ticker] = round(ticker_impact, 4)
                weighted_impact += ticker_impact * weight

            portfolio_impact = round(weighted_impact, 4)
            max_drawdown = round(portfolio_impact * 1.15, 4)

            return {
                "scenario": scenario,
                "scenario_description": description,
                "max_drawdown": max_drawdown,
                "portfolio_impact": portfolio_impact,
                "position_impacts": position_impacts,
                "recovery_time": recovery_months,
                "confidence_level": 0.95,
                "methodology": "Factor beta and volatility scaled stress shock simulation"
            }
            
        except Exception as e:
            logger.error(f"Error in stress test: {e}")
            return self._empty_stress_test()
    
    async def volatility_sizing(
        self, 
        price_data: pd.DataFrame, 
        weights: Dict[str, float], 
        model: str = "EWMA", 
        target_volatility: float = 0.15,
        portfolio_value: Optional[float] = None
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
            
            cleaned_prices = price_data.sort_index().ffill().bfill()
            returns = cleaned_prices.pct_change(fill_method=None).fillna(0.0)
            if returns.empty or len(returns) < 2:
                return self._empty_volatility_sizing()
            returns = returns.iloc[1:]
            
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
                # Quadratic form w' (D C D) w — the original expression stopped
                # at the row vector w' M, so `if portfolio_volatility > 0`
                # raised on array truthiness and every request degraded to the
                # empty fallback. Bug surfaced by ticket-01 test suite.
                cov_matrix = correlation_matrix.values * np.outer(
                    current_volatilities, current_volatilities
                )
                portfolio_variance = float(current_weights @ cov_matrix @ current_weights)
                portfolio_volatility = np.sqrt(portfolio_variance) * np.sqrt(252)  # Annualized
            else:
                portfolio_volatility = 0.20  # Default
            
            # Calculate inverse-volatility risk parity weights
            annualized_vols = {k: float(v * np.sqrt(252)) for k, v in volatilities.items()}
            inv_vols = {ticker: (1.0 / max(v, 1e-4)) for ticker, v in annualized_vols.items() if ticker in weights}
            sum_inv_vol = sum(inv_vols.values())
            
            if sum_inv_vol > 0:
                recommended_weights = {k: round(v / sum_inv_vol, 6) for k, v in inv_vols.items()}
            else:
                recommended_weights = weights.copy()
            
            # Calculate trade recommendations
            trades = {}
            for ticker in returns.columns:
                current_weight = weights.get(ticker, 0)
                recommended_weight = recommended_weights.get(ticker, 0)
                weight_delta = recommended_weight - current_weight
                
                current_price = float(price_data[ticker].iloc[-1]) if ticker in price_data.columns else 100.0
                estimated_portfolio_value = portfolio_value if (portfolio_value is not None and portfolio_value > 0) else 100000.0
                
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
                "volatilities": annualized_vols,
                "methodology": f"{model} inverse-volatility risk parity with target volatility scaling"
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
            
            cleaned_prices = price_data.sort_index().ffill().bfill()
            returns = cleaned_prices.pct_change(fill_method=None).fillna(0.0)
            if returns.empty or len(returns) < 2:
                return self._empty_risk_score()
            returns = returns.iloc[1:]
            
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
            
            if len(returns) < 10:
                # Insufficient sample size for reliable annualization: return period cumulative return and 0 Sharpe
                annual_return = float(returns.sum())
                annual_volatility = float(returns.std() * np.sqrt(252)) if len(returns) > 1 else 0.0
                sharpe_ratio = 0.0
                sortino_ratio = 0.0
            else:
                # Annual return and volatility
                annual_return = float(returns.mean() * 252)
                annual_volatility = float(returns.std() * np.sqrt(252))
                
                # Sharpe ratio
                sharpe_ratio = float((annual_return - self.risk_free_rate) / annual_volatility) if annual_volatility > 0 else 0.0
                
                # Sortino ratio
                downside_returns = returns[returns < 0]
                downside_deviation = float(downside_returns.std() * np.sqrt(252)) if not downside_returns.empty else 0.0
                sortino_ratio = float((annual_return - self.risk_free_rate) / downside_deviation) if downside_deviation > 0 else 0.0
            
            # Hit ratio
            hit_ratio = float((returns > 0).mean())
            
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
    
    def _calculate_position_metrics(
        self,
        returns: pd.DataFrame,
        weights: Dict[str, float],
        raw_prices: Optional[pd.DataFrame] = None
    ) -> Dict[str, Any]:
        """Calculate metrics for individual positions based on active price history"""
        try:
            if returns.empty:
                return {}
            
            position_metrics = {}
            for ticker in returns.columns:
                # Use raw active price series if available to avoid artificial zero-dilution on newly listed assets
                if raw_prices is not None and ticker in raw_prices.columns:
                    raw_s = raw_prices[ticker].dropna()
                    if len(raw_s) >= 2:
                        ticker_returns = raw_s.pct_change(fill_method=None).dropna()
                    else:
                        ticker_returns = returns[ticker].dropna()
                else:
                    ticker_returns = returns[ticker].dropna()

                if not ticker_returns.empty:
                    data_points = len(ticker_returns)
                    is_limited = data_points < 30
                    metrics = self._calculate_basic_metrics(ticker_returns)
                    metrics.update(self._calculate_risk_metrics(ticker_returns))
                    metrics.update(self._calculate_drawdown_metrics(ticker_returns))
                    position_metrics[ticker] = {
                        **metrics,
                        "weight": weights.get(ticker, 0),
                        "data_points": data_points,
                        "is_limited_history": is_limited,
                        "history_warning": f"Only {data_points} trading days available on exchange feed" if is_limited else None
                    }
            
            return position_metrics
        except:
            return {}
    
    async def _garch_forecast(self, returns: pd.Series, horizon: int) -> Dict[str, Any]:
        """GARCH volatility forecast"""
        try:
            h = max(1, horizon)
            # Scale returns by 100 for arch optimizer numerical convergence stability
            scaled_returns = returns * 100.0
            model = arch_model(scaled_returns, vol='Garch', p=1, q=1, dist='normal', rescale=False)
            fitted_model = model.fit(disp='off', show_warning=False, options={'maxiter': 100})
            
            # Generate analytical forecast (fast O(1) computation instead of 1000 simulation paths)
            forecast = fitted_model.forecast(horizon=h, method='analytic')
            
            # Extract volatility forecast and unscale
            variance_forecast = forecast.variance.values[-1, :]
            volatility_forecast = np.sqrt(variance_forecast * 252) / 100.0  # Annualized
            vol_final = float(volatility_forecast[-1]) if len(volatility_forecast) > 0 else 0.22
            h_factor = np.sqrt(h / 252.0)
            
            return {
                "model": "GARCH",
                "horizon": h,
                "volatility_forecast": vol_final,
                "var_forecast": float(-vol_final * 1.645 * h_factor),
                "cvar_forecast": float(-vol_final * 2.06 * h_factor),
                "confidence_interval": [
                    max(0.0, float(vol_final * 0.8)),
                    float(vol_final * 1.2)
                ],
                "term_structure": [float(v) for v in volatility_forecast],
                "model_params": {"p": 1, "q": 1, "type": "GARCH"}
            }
        except Exception as e:
            logger.error(f"GARCH forecast error: {e}")
            return self._empty_forecast(h)
    
    async def _egarch_forecast(self, returns: pd.Series, horizon: int) -> Dict[str, Any]:
        """EGARCH volatility forecast"""
        try:
            h = max(1, horizon)
            # Scale returns by 100 for arch optimizer numerical convergence stability
            scaled_returns = returns * 100.0
            model = arch_model(scaled_returns, vol='EGARCH', p=1, q=1, dist='normal', rescale=False)
            fitted_model = model.fit(disp='off', show_warning=False)
            
            # Generate forecast
            forecast = fitted_model.forecast(horizon=h)
            
            # Extract volatility forecast and unscale
            variance_forecast = forecast.variance.values[-1, :]
            volatility_forecast = np.sqrt(variance_forecast * 252) / 100.0  # Annualized
            vol_final = float(volatility_forecast[-1]) if len(volatility_forecast) > 0 else 0.24
            h_factor = np.sqrt(h / 252.0)
            
            return {
                "model": "EGARCH",
                "horizon": h,
                "volatility_forecast": vol_final,
                "var_forecast": float(-vol_final * 1.645 * h_factor),
                "cvar_forecast": float(-vol_final * 2.06 * h_factor),
                "confidence_interval": [
                    max(0.0, float(vol_final * 0.8)),
                    float(vol_final * 1.2)
                ],
                "term_structure": [float(v) for v in volatility_forecast],
                "model_params": {"p": 1, "q": 1, "type": "EGARCH"}
            }
        except Exception as e:
            logger.error(f"EGARCH forecast error: {e}")
            return self._empty_forecast(h)
    
    def _ewma_forecast(self, returns: pd.Series, horizon: int) -> Dict[str, Any]:
        """EWMA volatility forecast"""
        try:
            h = max(1, horizon)
            lambda_val = 0.94  # Standard RiskMetrics decay factor
            
            # Calculate historical volatilities
            daily_vols = returns.rolling(window=min(30, len(returns))).std()
            ewma_variance = daily_vols.ewm(alpha=1-lambda_val).mean() ** 2
            
            # Forecast (assume mean reversion to long-term average)
            long_term_var = float(returns.var())
            last_var = float(ewma_variance.iloc[-1]) if not ewma_variance.empty else long_term_var
            
            term_structure = []
            for step in range(1, h + 1):
                step_var = last_var * (lambda_val ** step) + long_term_var * (1 - lambda_val ** step)
                term_structure.append(float(np.sqrt(step_var * 252)))
                
            forecast_volatility = term_structure[-1] if term_structure else float(np.sqrt(last_var * 252))
            h_factor = np.sqrt(h / 252.0)
            
            return {
                "model": "EWMA",
                "horizon": h,
                "volatility_forecast": float(forecast_volatility),
                "var_forecast": float(-forecast_volatility * 1.645 * h_factor),
                "cvar_forecast": float(-forecast_volatility * 2.06 * h_factor),
                "confidence_interval": [float(forecast_volatility * 0.8), float(forecast_volatility * 1.2)],
                "term_structure": term_structure,
                "model_params": {"lambda": lambda_val, "type": "EWMA"}
            }
        except Exception as e:
            logger.error(f"EWMA forecast error: {e}")
            return self._empty_forecast(h)
    
    def _calculate_factor_exposures(
        self, 
        returns: pd.DataFrame, 
        benchmark_returns: pd.Series, 
        weights: Dict[str, float]
    ) -> Dict[str, Any]:
        """Calculate factor exposures using OLS regression against market benchmark"""
        try:
            if returns.empty:
                return {'portfolio': {'alpha': 0.0, 'market': 1.0}, 'positions': {}}

            positions_exp = {}
            if not benchmark_returns.empty and len(benchmark_returns) > 10:
                common_dates = returns.index.intersection(benchmark_returns.index)
                if len(common_dates) > 10:
                    aligned_returns = returns.loc[common_dates]
                    aligned_benchmark = benchmark_returns.loc[common_dates]

                    for ticker in aligned_returns.columns:
                        try:
                            X = sm.add_constant(aligned_benchmark)
                            y = aligned_returns[ticker]
                            model = sm.OLS(y, X).fit()
                            alpha = float(model.params.iloc[0]) if len(model.params) > 0 else 0.0
                            beta = float(model.params.iloc[1]) if len(model.params) > 1 else 1.0
                            positions_exp[ticker] = {
                                'alpha': round(alpha, 6),
                                'market': round(beta, 4)
                            }
                        except Exception:
                            positions_exp[ticker] = {'alpha': 0.0, 'market': 1.0}

                    port_returns = self._calculate_portfolio_returns(aligned_returns, weights)
                    if not port_returns.empty:
                        try:
                            X_port = sm.add_constant(aligned_benchmark)
                            port_model = sm.OLS(port_returns, X_port).fit()
                            port_alpha = float(port_model.params.iloc[0]) if len(port_model.params) > 0 else 0.0
                            port_beta = float(port_model.params.iloc[1]) if len(port_model.params) > 1 else 1.0
                            return {
                                'portfolio': {
                                    'alpha': round(port_alpha, 6),
                                    'market': round(port_beta, 4)
                                },
                                'positions': positions_exp
                            }
                        except Exception:
                            pass

            for ticker in returns.columns:
                positions_exp[ticker] = {'alpha': 0.0, 'market': 1.0}
            return {
                'portfolio': {'alpha': 0.0, 'market': 1.0},
                'positions': positions_exp
            }
        except Exception as e:
            logger.error(f"Factor exposure calculation error: {e}")
            return {'portfolio': {'alpha': 0.0, 'market': 1.0}, 'positions': {}}

    def _calculate_r_squared(
        self, 
        returns: pd.DataFrame, 
        benchmark_returns: pd.Series, 
        weights: Dict[str, float]
    ) -> float:
        """Calculate portfolio R-squared against benchmark"""
        try:
            if not benchmark_returns.empty and len(benchmark_returns) > 10:
                common_dates = returns.index.intersection(benchmark_returns.index)
                if len(common_dates) > 10:
                    aligned_returns = returns.loc[common_dates]
                    aligned_benchmark = benchmark_returns.loc[common_dates]
                    
                    portfolio_returns = self._calculate_portfolio_returns(aligned_returns, weights)
                    if not portfolio_returns.empty:
                        X = sm.add_constant(aligned_benchmark)
                        model = sm.OLS(portfolio_returns, X).fit()
                        return round(float(model.rsquared), 4)
            return 0.0
        except Exception:
            return 0.0

    def _calculate_adjusted_r_squared(
        self, 
        returns: pd.DataFrame, 
        benchmark_returns: pd.Series, 
        weights: Dict[str, float]
    ) -> float:
        """Calculate adjusted R-squared against benchmark"""
        try:
            if not benchmark_returns.empty and len(benchmark_returns) > 10:
                common_dates = returns.index.intersection(benchmark_returns.index)
                if len(common_dates) > 10:
                    aligned_returns = returns.loc[common_dates]
                    aligned_benchmark = benchmark_returns.loc[common_dates]
                    
                    portfolio_returns = self._calculate_portfolio_returns(aligned_returns, weights)
                    if not portfolio_returns.empty:
                        X = sm.add_constant(aligned_benchmark)
                        model = sm.OLS(portfolio_returns, X).fit()
                        return round(float(max(0.0, model.rsquared_adj)), 4)
            return 0.0
        except Exception:
            return 0.0
    
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
    
    def _empty_forecast(self, horizon: int = 1) -> Dict[str, Any]:
        h = max(1, horizon)
        h_factor = np.sqrt(h / 252.0)
        base_vol = 0.22
        return {
            "model": "GARCH",
            "horizon": h,
            "volatility_forecast": base_vol,
            "var_forecast": float(-base_vol * 1.645 * h_factor),
            "cvar_forecast": float(-base_vol * 2.06 * h_factor),
            "confidence_interval": [0.18, 0.26],
            "term_structure": [base_vol] * h,
            "model_params": {"p": 1, "q": 1, "type": "GARCH"},
            "error": "Insufficient data for forecast"
        }
    
    def _empty_factor_exposure(self) -> Dict[str, Any]:
        return {
            "portfolio": {
                "alpha": 0.0,
                "market": 1.0
            },
            "positions": {},
            "r_squared": 0.0,
            "adjusted_r_squared": 0.0,
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