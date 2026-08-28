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
            herfindahl = float(np.sum(weights_array ** 2))
            
            # Effective number of positions
            effective_positions = float(1 / herfindahl if herfindahl > 0 else len(weights))
            
            # Diversification score (normalized against theoretical maximum 1 - 1/N)
            n_assets = len(weights)
            diversification_score = float(((1 - herfindahl) / (1 - 1/n_assets)) * 100) if n_assets > 1 else 0.0
            diversification_ratio = float(effective_positions / n_assets) if n_assets > 0 else 1.0
            
            # Gini Inequality Coefficient
            sorted_w = np.sort(weights_array)
            gini = float((2 * np.sum((np.arange(1, n_assets + 1) * sorted_w)) - (n_assets + 1)) / n_assets) if n_assets > 1 else 0.0

            return {
                "largest_position": float(largest_position),
                "top_3": float(top_3),
                "top_5": float(top_5),
                "top_10": float(top_10),
                "herfindahl_index": round(herfindahl, 4),
                "effective_positions": round(effective_positions, 2),
                "diversification_score": round(diversification_score, 1),
                "diversification_ratio": round(diversification_ratio, 2),
                "gini_coefficient": round(gini, 3),
                "by_weight": dict(sorted(weights.items(), key=lambda x: x[1], reverse=True))
            }
            
        except Exception as e:
            logger.error(f"Error in concentration analysis: {e}")
            return self._empty_concentration()
    
    async def liquidity_analysis(
        self, 
        price_data: Dict[str, pd.DataFrame],
        market_caps: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """
        Analyze portfolio liquidity using turnover (volume * price), market cap, and empirical spreads.
        
        Args:
            price_data: Dictionary mapping tickers to price DataFrames
            market_caps: Optional mapping of tickers to market cap in INR
            
        Returns:
            Dictionary with liquidity metrics
        """
        try:
            if not price_data:
                return self._empty_liquidity()
            
            liquidity_scores = {}
            volume_stats = {'volumes': [], 'total_volume': 0}
            
            for ticker, df in price_data.items():
                if df is None or df.empty:
                    continue
                
                vol_col = 'Volume' if 'Volume' in df.columns else ('volume' if 'volume' in df.columns else None)
                close_col = 'Close' if 'Close' in df.columns else ('close' if 'close' in df.columns else None)
                
                if not vol_col:
                    continue
                
                # Calculate liquidity score based on volume, price, and daily turnover
                volume = float(df[vol_col].mean())
                price = float(df[close_col].iloc[-1]) if close_col and not df.empty else 0.0
                daily_turnover = volume * price
                
                # Market cap / AUM dynamic resolution
                mc = 0.0
                if market_caps and ticker in market_caps and market_caps[ticker]:
                    mc = float(market_caps[ticker])
                
                # If market cap is missing (e.g. ETFs or unlisted fund units), compute dynamic implied annual capitalization
                if mc <= 0.0:
                    mc = max(1000000000.0, daily_turnover * 250.0)
                
                # Institutional Turnover & Market Cap Liquidity Scoring (0 - 10)
                # Tier 1: Mega / Large Turnover (> 50 Cr/day) or Mega Cap (> 50,000 Cr)
                if daily_turnover >= 500000000.0 or mc >= 500000000000.0:
                    score = min(10.0, 9.0 + min(1.0, (daily_turnover / 1e9) * 0.2))
                    category = "High"
                    spread = round(max(0.0002, 0.0006 - min(0.0003, (daily_turnover / 2e9) * 0.0003)), 4)
                    liquidation_days = "1-2"
                # Tier 2: Liquid Midcap / Top ETF (Turnover 10 Cr - 50 Cr/day) or Cap 10,000 Cr - 50,000 Cr
                elif daily_turnover >= 100000000.0 or mc >= 100000000000.0:
                    score = min(8.9, 7.8 + (daily_turnover / 5e8) * 1.1)
                    category = "High" if score >= 8.0 else "Medium"
                    spread = round(max(0.0006, 0.0014 - (daily_turnover / 5e8) * 0.0006), 4)
                    liquidation_days = "1-2" if score >= 8.0 else "2-3"
                # Tier 3: Moderate Turnover (Turnover 2 Cr - 10 Cr/day)
                elif daily_turnover >= 20000000.0 or mc >= 10000000000.0:
                    score = min(7.7, 6.2 + (daily_turnover / 1e8) * 0.15)
                    category = "Medium"
                    spread = round(max(0.0012, 0.0028 - (daily_turnover / 1e8) * 0.0012), 4)
                    liquidation_days = "2-5"
                # Tier 4: Smallcap / Lower Turnover (< 2 Cr/day)
                else:
                    score = max(2.5, min(5.9, 3.0 + (daily_turnover / 2e7) * 2.9))
                    category = "Low" if score < 6.0 else "Medium"
                    spread = round(max(0.0025, 0.0060 - (daily_turnover / 2e7) * 0.0030), 4)
                    liquidation_days = "5-10"
                
                liquidity_scores[ticker] = {
                    'score': round(score, 1),
                    'avg_volume': volume,
                    'avg_turnover': daily_turnover,
                    'market_cap': mc,
                    'category': category,
                    'spread': spread,
                    'liquidation_days': liquidation_days
                }
                
                volume_stats['volumes'].append(volume)
                volume_stats['total_volume'] += volume
            
            # Calculate overall metrics
            if liquidity_scores:
                overall_score = float(np.mean([score_data['score'] for score_data in liquidity_scores.values()]))
                avg_volume = float(np.mean(volume_stats['volumes'])) if volume_stats['volumes'] else 0.0
                
                # Volume & Score distribution
                high_count = sum(1 for s in liquidity_scores.values() if s['score'] >= 8.0)
                medium_count = sum(1 for s in liquidity_scores.values() if 6.0 <= s['score'] < 8.0)
                low_count = sum(1 for s in liquidity_scores.values() if s['score'] < 6.0)
                total_positions = len(liquidity_scores)
                
                volume_pct = lambda x: (x / total_positions * 100.0) if total_positions > 0 else 0.0
                
                # Determine liquidation time and risk level
                if overall_score >= 8.0:
                    liquidation_time = "1-2"
                    risk_level = "Low"
                elif overall_score >= 6.0:
                    liquidation_time = "2-5"
                    risk_level = "Medium"
                else:
                    liquidation_time = "5-10"
                    risk_level = "High"
                
                return {
                    "overall_score": round(overall_score, 1),
                    "liquidation_time_days": liquidation_time,
                    "risk_level": risk_level,
                    "by_position": liquidity_scores,
                    "volume_stats": {
                        "avg_volume": avg_volume,
                        "total_portfolio_volume": volume_stats['total_volume'],
                        "high_volume_pct": round(volume_pct(high_count), 1),
                        "medium_volume_pct": round(volume_pct(medium_count), 1),
                        "low_volume_pct": round(volume_pct(low_count), 1)
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
        scenario: str,
        sectors: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Run multi-factor sector-elastic stress test scenario
        
        Args:
            price_data: Historical price data
            weights: Portfolio weights
            scenario: Stress scenario name
            sectors: Optional dictionary mapping ticker to sector
            
        Returns:
            Dictionary with stress test results
        """
        try:
            if price_data.empty or not weights:
                return self._empty_stress_test()
            
            scenario_key = (scenario or "").lower().strip().replace(" ", "_").replace("-", "_")

            # Multi-Factor Macro & Sector Elasticity Matrix
            scenarios_config = {
                "market_crash": {
                    "market_shock": -0.35, 
                    "recovery_months": 24, 
                    "description": "Global Financial Crisis / Severe Market Crash (-35% NIFTY shock)",
                    "sectors": {
                        "Healthcare": 0.55, "Utilities": 0.50, "Technology": 1.10,
                        "Financial Services": 1.45, "Consumer Cyclical": 1.55, "Industrials": 1.40,
                        "Exchange Traded Fund": 1.00
                    }
                },
                "interest_rate_shock": {
                    "market_shock": -0.15, 
                    "recovery_months": 9, 
                    "description": "300bp RBI / Global Central Bank Interest Rate Hike (-15% shock)",
                    "sectors": {
                        "Healthcare": 0.50, "Utilities": 0.70, "Technology": 1.10,
                        "Financial Services": 1.50, "Consumer Cyclical": 1.35, "Industrials": 1.40,
                        "Exchange Traded Fund": 1.00
                    }
                },
                "volatility_spike": {
                    "market_shock": -0.22, 
                    "recovery_months": 5, 
                    "description": "COVID-19 style VIX > 40 Sudden Volatility Spike (-22% shock)",
                    "sectors": {
                        "Healthcare": 0.40, "Utilities": 0.55, "Technology": 0.95,
                        "Financial Services": 1.30, "Consumer Cyclical": 1.50, "Industrials": 1.45,
                        "Exchange Traded Fund": 1.05
                    }
                },
                "tech_sector_correction": {
                    "market_shock": -0.18, 
                    "recovery_months": 12, 
                    "description": "Broad Tech & Growth Multiple De-rating (-18% shock)",
                    "sectors": {
                        "Healthcare": 0.25, "Utilities": 0.20, "Technology": 1.80,
                        "Financial Services": 0.50, "Consumer Cyclical": 0.60, "Industrials": 0.45,
                        "Exchange Traded Fund": 0.60
                    }
                },
                "2020_covid": {
                    "market_shock": -0.28, 
                    "recovery_months": 6, 
                    "description": "March 2020 COVID Market Crash",
                    "sectors": {
                        "Healthcare": 0.45, "Utilities": 0.60, "Technology": 0.90,
                        "Financial Services": 1.40, "Consumer Cyclical": 1.50, "Industrials": 1.45,
                        "Exchange Traded Fund": 1.05
                    }
                },
                "2022_inflation": {
                    "market_shock": -0.16, 
                    "recovery_months": 10, 
                    "description": "2022 Global Inflationary Tightening",
                    "sectors": {
                        "Healthcare": 0.60, "Utilities": 0.80, "Technology": 1.50,
                        "Financial Services": 1.10, "Consumer Cyclical": 1.20, "Industrials": 1.10,
                        "Exchange Traded Fund": 1.00
                    }
                },
                "2018_q4": {
                    "market_shock": -0.14, 
                    "recovery_months": 7, 
                    "description": "Q4 2018 Market Correction",
                    "sectors": {
                        "Healthcare": 0.70, "Utilities": 0.50, "Technology": 1.40,
                        "Financial Services": 1.20, "Consumer Cyclical": 1.10, "Industrials": 1.00,
                        "Exchange Traded Fund": 1.00
                    }
                },
            }

            matched_scenario = None
            for k, cfg in scenarios_config.items():
                if k in scenario_key or scenario_key in k:
                    matched_scenario = (k, cfg)
                    break
            
            if not matched_scenario:
                # Custom shock if present in scenario string
                matched_scenario = ("custom_stress", {
                    "market_shock": -0.20,
                    "recovery_months": 12,
                    "description": scenario or "Custom Scenario Shock",
                    "sectors": {}
                })

            sc_name, sc_cfg = matched_scenario
            market_shock = sc_cfg["market_shock"]
            recovery_months = sc_cfg["recovery_months"]
            description = sc_cfg["description"]
            sector_table = sc_cfg.get("sectors", {})

            # Clean and calculate asset returns
            cleaned_prices = price_data.sort_index().ffill().bfill()
            returns = cleaned_prices.pct_change(fill_method=None).fillna(0.0)
            if returns.empty or len(returns) < 2:
                return self._empty_stress_test()
            returns = returns.iloc[1:]
            
            position_impacts: Dict[str, float] = {}
            weighted_impact = 0.0
            sectors_map = sectors or {}

            for ticker, weight in weights.items():
                sec = sectors_map.get(ticker, "Exchange Traded Fund")
                sec_mult = sector_table.get(sec, 1.0)
                
                # Special instrument sensitivity
                if ticker == "MAFANG.NS" and sc_name == "tech_sector_correction":
                    sec_mult = 2.0
                elif ticker == "MIDCAPIETF.NS" and sc_name in ["market_crash", "volatility_spike"]:
                    sec_mult = 1.30
                elif ticker == "SELECTIPO.NS":
                    sec_mult = 1.15

                # Idiosyncratic volatility factor adjustment (bounded between 0.85 and 1.25)
                vol_adj = 1.0
                if ticker in returns.columns:
                    s = returns[ticker]
                    non_zero = s[s != 0.0].clip(lower=-0.20, upper=0.20)
                    if len(non_zero) >= 20:
                        ticker_vol = float(non_zero.std() * np.sqrt(252))
                        vol_adj = max(0.85, min(1.25, ticker_vol / 0.22)) if ticker_vol > 0 else 1.0

                ticker_impact = float(market_shock * sec_mult * vol_adj)
                ticker_impact = max(-0.75, min(-0.02, ticker_impact)) if market_shock < 0 else ticker_impact
                
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
            clean_returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
            clean_returns = clean_returns.clip(lower=-0.20, upper=0.20)
            if len(clean_returns) < 20:
                return self._empty_forecast(h)

            # Scale returns by 100 for arch optimizer numerical convergence stability
            scaled_returns = clean_returns * 100.0
            model = arch_model(scaled_returns, vol='Garch', p=1, q=1, dist='normal', rescale=False)
            fitted_model = model.fit(disp='off', show_warning=False, options={'maxiter': 100})
            
            # Generate analytical forecast (fast O(1) computation instead of 1000 simulation paths)
            forecast = fitted_model.forecast(horizon=h, method='analytic')
            
            # Extract volatility forecast and unscale
            variance_forecast = forecast.variance.values[-1, :]
            volatility_forecast = np.sqrt(variance_forecast * 252) / 100.0  # Annualized
            vol_final = float(np.clip(volatility_forecast[-1], 0.05, 1.20)) if len(volatility_forecast) > 0 else 0.22
            h_factor = np.sqrt(h / 252.0)
            
            return {
                "model": "GARCH",
                "horizon": h,
                "volatility_forecast": vol_final,
                "var_forecast": float(np.clip(-vol_final * 1.645 * h_factor, -0.99, -0.001)),
                "cvar_forecast": float(np.clip(-vol_final * 2.06 * h_factor, -0.99, -0.001)),
                "confidence_interval": [
                    max(0.0, float(vol_final * 0.8)),
                    float(vol_final * 1.2)
                ],
                "term_structure": [float(np.clip(v, 0.05, 1.20)) for v in volatility_forecast],
                "model_params": {"p": 1, "q": 1, "type": "GARCH"}
            }
        except Exception as e:
            logger.error(f"GARCH forecast error: {e}")
            return self._empty_forecast(h)
    
    async def _egarch_forecast(self, returns: pd.Series, horizon: int) -> Dict[str, Any]:
        """EGARCH volatility forecast"""
        try:
            h = max(1, horizon)
            clean_returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
            clean_returns = clean_returns.clip(lower=-0.20, upper=0.20)
            if len(clean_returns) < 20:
                return self._empty_forecast(h)

            # Scale returns by 100 for arch optimizer numerical convergence stability
            scaled_returns = clean_returns * 100.0
            model = arch_model(scaled_returns, vol='EGARCH', p=1, q=1, dist='normal', rescale=False)
            fitted_model = model.fit(disp='off', show_warning=False)
            
            # Generate forecast
            forecast = fitted_model.forecast(horizon=h)
            
            # Extract volatility forecast and unscale
            variance_forecast = forecast.variance.values[-1, :]
            volatility_forecast = np.sqrt(variance_forecast * 252) / 100.0  # Annualized
            vol_final = float(np.clip(volatility_forecast[-1], 0.05, 1.20)) if len(volatility_forecast) > 0 else 0.24
            h_factor = np.sqrt(h / 252.0)
            
            return {
                "model": "EGARCH",
                "horizon": h,
                "volatility_forecast": vol_final,
                "var_forecast": float(np.clip(-vol_final * 1.645 * h_factor, -0.99, -0.001)),
                "cvar_forecast": float(np.clip(-vol_final * 2.06 * h_factor, -0.99, -0.001)),
                "confidence_interval": [
                    max(0.0, float(vol_final * 0.8)),
                    float(vol_final * 1.2)
                ],
                "term_structure": [float(np.clip(v, 0.05, 1.20)) for v in volatility_forecast],
                "model_params": {"p": 1, "q": 1, "type": "EGARCH"}
            }
        except Exception as e:
            logger.error(f"EGARCH forecast error: {e}")
            return self._empty_forecast(h)
    
    def _ewma_forecast(self, returns: pd.Series, horizon: int) -> Dict[str, Any]:
        """EWMA volatility forecast"""
        try:
            h = max(1, horizon)
            clean_returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
            clean_returns = clean_returns.clip(lower=-0.20, upper=0.20)
            lambda_val = 0.94  # Standard RiskMetrics decay factor
            
            # Calculate historical volatilities
            daily_vols = clean_returns.rolling(window=min(30, len(clean_returns))).std().fillna(clean_returns.std())
            ewma_variance = daily_vols.ewm(alpha=1-lambda_val).mean() ** 2
            
            # Forecast (assume mean reversion to long-term average)
            long_term_var = float(clean_returns.var())
            last_var = float(ewma_variance.iloc[-1]) if not ewma_variance.empty else long_term_var
            
            term_structure = []
            for step in range(1, h + 1):
                step_var = last_var * (lambda_val ** step) + long_term_var * (1 - lambda_val ** step)
                term_structure.append(float(np.clip(np.sqrt(step_var * 252), 0.05, 1.20)))
                
            forecast_volatility = term_structure[-1] if term_structure else float(np.clip(np.sqrt(last_var * 252), 0.05, 1.20))
            h_factor = np.sqrt(h / 252.0)
            
            return {
                "model": "EWMA",
                "horizon": h,
                "volatility_forecast": forecast_volatility,
                "var_forecast": float(np.clip(-forecast_volatility * 1.645 * h_factor, -0.99, -0.001)),
                "cvar_forecast": float(np.clip(-forecast_volatility * 2.06 * h_factor, -0.99, -0.001)),
                "confidence_interval": [
                    max(0.0, float(forecast_volatility * 0.8)),
                    float(forecast_volatility * 1.2)
                ],
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
                return {'portfolio': {'alpha': 0.0, 'annualized_alpha': 0.0, 'market': 1.0}, 'positions': {}}

            positions_exp = {}
            if not benchmark_returns.empty and len(benchmark_returns) > 10:
                common_dates = returns.index.intersection(benchmark_returns.index)
                if len(common_dates) > 10:
                    aligned_returns = returns.loc[common_dates]
                    aligned_benchmark = benchmark_returns.loc[common_dates]

                    for ticker in aligned_returns.columns:
                        try:
                            s = aligned_returns[ticker]
                            non_zero = s[s != 0.0]
                            data_pts = len(non_zero)
                            is_limited = data_pts < 30

                            if data_pts >= 10:
                                valid_idx = s.index
                                X = sm.add_constant(aligned_benchmark.loc[valid_idx])
                                y = s.loc[valid_idx]
                                model = sm.OLS(y, X).fit()
                                alpha = float(model.params.iloc[0]) if len(model.params) > 0 else 0.0
                                beta = float(model.params.iloc[1]) if len(model.params) > 1 else 1.0
                            else:
                                alpha = 0.0
                                beta = 1.0

                            positions_exp[ticker] = {
                                'alpha': round(alpha, 6),
                                'annualized_alpha': round(alpha * 252.0, 4),
                                'market': round(beta, 4),
                                'is_limited_history': is_limited,
                                'history_warning': f"Only {data_pts} active trading days on exchange feed" if is_limited else None,
                                'data_points': data_pts
                            }
                        except Exception:
                            positions_exp[ticker] = {
                                'alpha': 0.0,
                                'annualized_alpha': 0.0,
                                'market': 1.0,
                                'is_limited_history': False,
                                'history_warning': None,
                                'data_points': 0
                            }

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
                                    'annualized_alpha': round(port_alpha * 252.0, 4),
                                    'market': round(port_beta, 4)
                                },
                                'positions': positions_exp
                            }
                        except Exception:
                            pass

            for ticker in returns.columns:
                positions_exp[ticker] = {
                    'alpha': 0.0,
                    'annualized_alpha': 0.0,
                    'market': 1.0,
                    'is_limited_history': False,
                    'history_warning': None,
                    'data_points': 0
                }
            return {
                'portfolio': {'alpha': 0.0, 'annualized_alpha': 0.0, 'market': 1.0},
                'positions': positions_exp
            }
        except Exception as e:
            logger.error(f"Factor exposure calculation error: {e}")
            return {'portfolio': {'alpha': 0.0, 'annualized_alpha': 0.0, 'market': 1.0}, 'positions': {}}

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