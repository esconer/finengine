"""
Real-time Analytics Engine for Portfolio Risk Calculations
Implements comprehensive financial analytics using quantstats, arch, and statsmodels
"""

import asyncio
import re

import numpy as np
import pandas as pd
from typing import Dict, Optional, Any
import warnings

# Financial analytics libraries
from arch import arch_model
try:
    from arch.utility.exceptions import ConvergenceWarning
    warnings.filterwarnings('ignore', category=ConvergenceWarning)
except ImportError:  # pragma: no cover - arch layout guard
    ConvergenceWarning = None
import statsmodels.api as sm

from app.config import settings
from app.utils.allocations import (
    build_sizing_basis,
    build_trade_instructions,
    normalization_block,
    sizing_history_block,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _finite_weight(weights: Optional[Dict[str, Any]], ticker: str) -> float:
    """Current weight of `ticker` as a finite float; 0.0 when unusable.

    A malformed or non-finite stored weight must not poison a weight delta.
    """
    try:
        value = float((weights or {}).get(ticker, 0.0))
    except (TypeError, ValueError):
        return 0.0
    return value if np.isfinite(value) else 0.0


def aggregate_active_returns(
    returns: pd.DataFrame, weights: Dict[str, float]
) -> pd.Series:
    """Aggregate returns using the shared active positive-weight contract.

    A date is usable only when at least one positive-weight constituent has a
    finite return.  On that date, the available positive weights are
    renormalised; dates with no active exposure are omitted rather than
    converted into synthetic zero returns.  Keeping this helper at module
    scope lets API orchestration use exactly the same rule as the service.
    """
    if not isinstance(returns, pd.DataFrame) or returns.empty:
        return pd.Series(dtype=float)

    clean = returns.replace([np.inf, -np.inf], np.nan)
    usable_weights: Dict[str, float] = {}
    for column in clean.columns:
        try:
            weight = float(weights.get(column, 0.0))
        except (TypeError, ValueError):
            continue
        if np.isfinite(weight) and weight > 0.0:
            usable_weights[column] = weight
    if not usable_weights:
        return pd.Series(dtype=float)

    weight_frame = pd.Series(usable_weights).reindex(clean.columns, fill_value=0.0)
    active = clean.notna() & (weight_frame > 0.0)
    active_weight = active.mul(weight_frame, axis=1).sum(axis=1)
    numerator = clean.where(active, 0.0).mul(weight_frame, axis=1).sum(axis=1)
    portfolio = numerator.loc[active_weight > 0.0] / active_weight.loc[active_weight > 0.0]
    return portfolio.replace([np.inf, -np.inf], np.nan).dropna().astype(float)


# ---------------------------------------------------------------------------
# liquidity: one documented score-band contract (V3-09)
# ---------------------------------------------------------------------------
# The published `score` is the raw score rounded once, and the band is a
# function of THAT published value.  Deriving the band from the unrounded score
# let a raw 7.96 publish `score=8.0` with a "Medium" band while the volume
# distribution counted the same position as high.  Every band label, every
# liquidation window and every high/medium/low count now reads the published
# score through the single table below.
LIQUIDITY_SCORE_PRECISION = 1

# (band, inclusive lower bound on the published score, liquidation window)
LIQUIDITY_SCORE_BANDS = (
    ("High", 8.0, "1-2"),
    ("Medium", 6.0, "2-5"),
    ("Low", None, "5-10"),
)

# Risk level inverts the score band: a high liquidity score is a low risk.
LIQUIDITY_BAND_RISK_LEVEL = {"High": "Low", "Medium": "Medium", "Low": "High"}

LIQUIDITY_SCORE_BAND_RULE = {
    "raw_score_field": "score_raw",
    "published_score_field": "score",
    "rounding": "round(raw_score, 1) applied once; `score` is that rounded value",
    "band_source": "published_score",
    "score_range": [0.0, 10.0],
    "bands": [
        {
            "band": "High",
            "min_published_score": 8.0,
            "max_published_score": None,
            "liquidation_days": "1-2",
            "volume_stats_bucket": "high",
        },
        {
            "band": "Medium",
            "min_published_score": 6.0,
            "max_published_score": 8.0,
            "liquidation_days": "2-5",
            "volume_stats_bucket": "medium",
        },
        {
            "band": "Low",
            "min_published_score": None,
            "max_published_score": 6.0,
            "liquidation_days": "5-10",
            "volume_stats_bucket": "low",
        },
    ],
    "volume_stats_basis": "positions per published-score band, as a share of measured positions",
    "risk_level_rule": "inverted band: High->Low, Medium->Medium, Low->High",
}

# Market cap provenance (V3-09).  The only market-cap input is the quote the
# route supplies; a missing cap is either annualised from measured turnover or
# floored, and both substitutes must be labelled instead of looking measured.
LIQUIDITY_MARKET_CAP_FLOOR_INR = 1_000_000_000.0
LIQUIDITY_IMPLIED_TURNOVER_DAYS = 250

# Stress shock-proxy configuration (V3-10).  These are the inputs behind the
# deterministic factor proxy; they travel with the result so a reader can see
# that the published drawdown is a proxy, not a simulated statistic.
STRESS_VOL_REFERENCE = 0.22
STRESS_VOL_ADJ_MIN = 0.85
STRESS_VOL_ADJ_MAX = 1.25
STRESS_VOL_MIN_OBSERVATIONS = 20
STRESS_DRAWDOWN_UPLIFT = 1.15
STRESS_CONFIDENCE_LABEL = 0.95


def _liquidity_band(published_score: float) -> tuple[str, str]:
    """Band label and liquidation window for an ALREADY-ROUNDED published score."""
    for band, floor, window in LIQUIDITY_SCORE_BANDS:
        if floor is None or published_score >= floor:
            return band, window
    last_band, _floor, last_window = LIQUIDITY_SCORE_BANDS[-1]
    return last_band, last_window


def _market_cap_provenance(
    supplied: Any, daily_turnover: float
) -> tuple[float, str, str]:
    """Resolve `(market_cap, provenance, source)` for one position.

    `measured` means a quote supplied a finite positive market cap.
    `estimated` means the cap was annualised from measured daily turnover, and
    `fallback` means the fixed INR 1bn floor was used because turnover was not
    measured at all.  The last two are estimates; neither is a measured cap.
    """
    try:
        candidate = float(supplied)
    except (TypeError, ValueError):
        candidate = 0.0
    if np.isfinite(candidate) and candidate > 0.0:
        return candidate, "measured", "quote"

    implied = float(daily_turnover) * LIQUIDITY_IMPLIED_TURNOVER_DAYS
    if np.isfinite(implied) and implied > LIQUIDITY_MARKET_CAP_FLOOR_INR:
        return implied, "estimated", "implied_annual_turnover"
    return LIQUIDITY_MARKET_CAP_FLOOR_INR, "fallback", "fixed_floor_1e9_inr"


class AnalyticsEngine:
    """
    Comprehensive analytics engine for portfolio risk calculations
    """
    
    def __init__(self):
        self.risk_free_rate = settings.risk_free_rate  # Settings default: 2% annual
        
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
            
            # Preserve the active-price mask.  Back-filling a newly listed
            # instrument with its first future price creates a flat synthetic
            # history; zero-filling the resulting gaps creates a different
            # synthetic history.  Returns remain NaN until both endpoints of a
            # price observation are available.
            cleaned_prices = price_data.replace([np.inf, -np.inf], np.nan).sort_index()
            returns = cleaned_prices.pct_change(fill_method=None)
            if returns.empty or len(returns) < 2:
                return self._empty_metrics()
            returns = returns.iloc[1:]

            # Handle only finite, strictly positive weights.  The active-mask
            # aggregation below renormalises the positive weights on each date
            # for which at least one constituent has a real return.
            if weights is None:
                weights = {col: 1.0 / len(returns.columns) for col in returns.columns}
            else:
                weights = {
                    key: float(value)
                    for key, value in weights.items()
                    if key in returns.columns
                    and np.isfinite(float(value))
                    and float(value) > 0.0
                }
                weight_sum = sum(weights.values())
                if weight_sum <= 0:
                    return self._empty_metrics()
                weights = {key: value / weight_sum for key, value in weights.items()}

            portfolio_returns = self._calculate_portfolio_returns(returns, weights)
            if portfolio_returns.empty:
                return self._empty_metrics()

            metrics = {
                "observations": int(len(portfolio_returns)),
                "active_observations": int(len(portfolio_returns)),
            }
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
                return self._empty_forecast(model=model.upper())
            
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
            return self._empty_forecast(model=model.upper())
    
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
            
            # Keep raw NaN so the regression active mask can separate
            # pre-listing gaps from genuine 0% return days.
            returns = price_data.sort_index().pct_change(fill_method=None)
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
            results = {
                'portfolio': exposures_result.get('portfolio') or {'alpha': None, 'market': None},
                'positions': exposures_result.get('positions', {}),
                'r_squared': exposures_result.get('r_squared'),
                'adjusted_r_squared': exposures_result.get('adjusted_r_squared'),
            }
            if exposures_result.get('error'):
                results['error'] = exposures_result['error']
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

            # Zero/negative/non-finite rows are not active holdings and must
            # not dilute the HHI denominator or diversification baseline.
            weights = {
                key: float(value)
                for key, value in weights.items()
                if np.isfinite(float(value)) and float(value) > 0.0
            }
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

        The published `score` is the raw tier score rounded once, and the
        category, liquidation window and high/medium/low counts are all derived
        from that published score through `LIQUIDITY_SCORE_BAND_RULE`, which is
        returned with the result so the threshold is discoverable.  A market cap
        that was annualised from turnover or floored at INR 1bn is reported with
        its provenance and `is_estimate=True` instead of passing as measured.

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

                # Market cap / AUM dynamic resolution, with its provenance.  A
                # missing or unusable cap is never allowed to look measured: the
                # annualised-turnover substitute and the INR 1bn floor are both
                # reported as estimates, because that is what they are.
                mc, mc_provenance, mc_source = _market_cap_provenance(
                    (market_caps or {}).get(ticker), daily_turnover
                )

                # Institutional Turnover & Market Cap Liquidity Scoring (0 - 10)
                # Tier 1: Mega / Large Turnover (> 50 Cr/day) or Mega Cap (> 50,000 Cr)
                if daily_turnover >= 500000000.0 or mc >= 500000000000.0:
                    score_raw = min(10.0, 9.0 + min(1.0, (daily_turnover / 1e9) * 0.2))
                    spread = round(max(0.0002, 0.0006 - min(0.0003, (daily_turnover / 2e9) * 0.0003)), 4)
                # Tier 2: Liquid Midcap / Top ETF (Turnover 10 Cr - 50 Cr/day) or Cap 10,000 Cr - 50,000 Cr
                elif daily_turnover >= 100000000.0 or mc >= 100000000000.0:
                    score_raw = min(8.9, 7.8 + (daily_turnover / 5e8) * 1.1)
                    spread = round(max(0.0006, 0.0014 - (daily_turnover / 5e8) * 0.0006), 4)
                # Tier 3: Moderate Turnover (Turnover 2 Cr - 10 Cr/day)
                elif daily_turnover >= 20000000.0 or mc >= 10000000000.0:
                    score_raw = min(7.7, 6.2 + (daily_turnover / 1e8) * 0.15)
                    spread = round(max(0.0012, 0.0028 - (daily_turnover / 1e8) * 0.0012), 4)
                # Tier 4: Smallcap / Lower Turnover (< 2 Cr/day)
                else:
                    score_raw = max(2.5, min(5.9, 3.0 + (daily_turnover / 2e7) * 2.9))
                    spread = round(max(0.0025, 0.0060 - (daily_turnover / 2e7) * 0.0030), 4)

                # Round once, then band the published score.  Banding the raw
                # score is what let a raw 7.96 publish score=8.0 as "Medium".
                score = round(float(score_raw), LIQUIDITY_SCORE_PRECISION)
                category, liquidation_days = _liquidity_band(score)

                liquidity_scores[ticker] = {
                    'score': score,
                    'score_raw': round(float(score_raw), 6),
                    'avg_volume': volume,
                    'avg_turnover': daily_turnover,
                    'market_cap': mc,
                    'market_cap_provenance': mc_provenance,
                    'market_cap_source': mc_source,
                    'is_estimate': mc_provenance in ('estimated', 'fallback'),
                    'category': category,
                    'spread': spread,
                    'liquidation_days': liquidation_days
                }
                
                volume_stats['volumes'].append(volume)
                volume_stats['total_volume'] += volume
            
            # Calculate overall metrics
            if liquidity_scores:
                published_scores = [data['score'] for data in liquidity_scores.values()]
                overall_score_raw = float(np.mean(published_scores))
                overall_score = round(overall_score_raw, LIQUIDITY_SCORE_PRECISION)
                avg_volume = float(np.mean(volume_stats['volumes'])) if volume_stats['volumes'] else 0.0

                # Volume & Score distribution: buckets follow the same published
                # score band as `category`, so a position cannot be "High" here
                # and "Medium" there.
                bands = [_liquidity_band(value)[0] for value in published_scores]
                high_count = bands.count("High")
                medium_count = bands.count("Medium")
                low_count = bands.count("Low")
                total_positions = len(liquidity_scores)
                
                volume_pct = lambda x: (x / total_positions * 100.0) if total_positions > 0 else 0.0
                
                # Liquidation time and risk level come from the same band rule
                overall_band, liquidation_time = _liquidity_band(overall_score)
                risk_level = LIQUIDITY_BAND_RISK_LEVEL[overall_band]
                
                return {
                    "overall_score": overall_score,
                    "overall_score_raw": round(overall_score_raw, 6),
                    "liquidation_time_days": liquidation_time,
                    "risk_level": risk_level,
                    "overall_band": overall_band,
                    "score_band_rule": dict(LIQUIDITY_SCORE_BAND_RULE),
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

        This is a deterministic factor shock proxy, not a simulation: no price
        paths are sampled, `max_drawdown` is `portfolio_impact * 1.15` on that
        same proxy, and `confidence_level` is a nominal label.  Every published
        figure therefore ships with a `*_basis` tag, the `shock_inputs` it was
        built from, and its `units`, so a reader cannot read a proxy as a
        simulated statistic (V3-10).

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
                if scenario_key and (k in scenario_key or scenario_key in k):
                    matched_scenario = (k, cfg)
                    break
            
            if not matched_scenario:
                # Custom shock: parse a signed percentage if present, else fixed -20%
                shock_match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*%', scenario or "")
                custom_shock = float(shock_match.group(1)) / 100.0 if shock_match else -0.20
                shock_basis = (
                    "parsed_from_scenario_text" if shock_match else "default_minus_20pct"
                )
                matched_scenario = ("custom_stress", {
                    "market_shock": custom_shock,
                    "recovery_months": 12,
                    "description": scenario or "Custom Scenario Shock",
                    "sectors": {}
                })
            else:
                shock_basis = "scenario_config"

            sc_name, sc_cfg = matched_scenario
            market_shock = sc_cfg["market_shock"]
            recovery_months = sc_cfg["recovery_months"]
            description = sc_cfg["description"]
            sector_table = sc_cfg.get("sectors", {})

            # Keep the active observation mask; missing prices are not economic
            # zero returns and must not influence the volatility adjustment.
            cleaned_prices = price_data.replace([np.inf, -np.inf], np.nan).sort_index()
            returns = cleaned_prices.pct_change(fill_method=None)
            if returns.empty or len(returns) < 2:
                return self._empty_stress_test()
            returns = returns.iloc[1:]
            
            position_impacts: Dict[str, float] = {}
            weighted_impact = 0.0
            sectors_map = sectors or {}
            instrument_overrides: Dict[str, Any] = {}
            volatility_adjustment: Dict[str, Any] = {}

            for ticker, weight in weights.items():
                sec = sectors_map.get(ticker, "Exchange Traded Fund")
                sec_mult = sector_table.get(sec, 1.0)
                elasticity_basis = (
                    "scenario_sector_table" if sec in sector_table
                    else "default_elasticity_1.0"
                )
                
                # Special instrument sensitivity
                if ticker == "MAFANG.NS" and sc_name == "tech_sector_correction":
                    sec_mult = 2.0
                    elasticity_basis = "instrument_override_mafang_tech_correction"
                elif ticker == "MIDCAPIETF.NS" and sc_name in ["market_crash", "volatility_spike"]:
                    sec_mult = 1.30
                    elasticity_basis = "instrument_override_midcap_etf"
                elif ticker == "SELECTIPO.NS":
                    sec_mult = 1.15
                    elasticity_basis = "instrument_override_selectipo"

                if elasticity_basis.startswith("instrument_override"):
                    instrument_overrides[ticker] = {
                        "sector": sec,
                        "sector_elasticity": sec_mult,
                        "basis": elasticity_basis,
                    }

                # Idiosyncratic volatility factor adjustment (bounded between 0.85 and 1.25)
                vol_adj = 1.0
                vol_basis = "unavailable_no_price_window"
                if ticker in returns.columns:
                    s = returns[ticker]
                    non_zero = s[s != 0.0].clip(lower=-0.20, upper=0.20)
                    if len(non_zero) >= STRESS_VOL_MIN_OBSERVATIONS:
                        ticker_vol = float(non_zero.std() * np.sqrt(252))
                        vol_adj = (
                            max(STRESS_VOL_ADJ_MIN, min(STRESS_VOL_ADJ_MAX, ticker_vol / STRESS_VOL_REFERENCE))
                            if ticker_vol > 0 else 1.0
                        )
                        vol_basis = (
                            "measured_annualized_volatility_over_reference"
                            if ticker_vol > 0 else "unavailable_zero_dispersion"
                        )
                    else:
                        vol_basis = "unavailable_insufficient_observations"
                volatility_adjustment[ticker] = {
                    "factor": round(float(vol_adj), 4),
                    "basis": vol_basis,
                }

                ticker_impact = float(market_shock * sec_mult * vol_adj)
                ticker_impact = max(-0.75, min(-0.02, ticker_impact)) if market_shock < 0 else ticker_impact
                
                position_impacts[ticker] = round(ticker_impact, 4)
                weighted_impact += ticker_impact * weight

            portfolio_impact = round(weighted_impact, 4)
            max_drawdown = round(portfolio_impact * STRESS_DRAWDOWN_UPLIFT, 4)

            # The published drawdown is a fixed 1.15 uplift on the same
            # deterministic factor proxy, and the confidence is a nominal
            # label: neither is a simulated statistic, so the inputs and units
            # ship with the result instead of the word "simulation".
            shock_inputs = {
                "market_shock": market_shock,
                "market_shock_basis": shock_basis,
                "sector_elasticity_table": dict(sector_table),
                "sector_elasticity_basis": "static_configured_table",
                "sector_elasticity_default": 1.0,
                "default_sector": "Exchange Traded Fund",
                "instrument_overrides": instrument_overrides,
                "position_impact_clip": [-0.75, -0.02],
                "position_impact_clip_basis": "configured_bounds_not_simulated",
                "volatility_adjustment": {
                    "basis": "measured_annualized_volatility_over_reference",
                    "reference_annualized_volatility": STRESS_VOL_REFERENCE,
                    "bounds": [STRESS_VOL_ADJ_MIN, STRESS_VOL_ADJ_MAX],
                    "min_observations": STRESS_VOL_MIN_OBSERVATIONS,
                    "return_clip": [-0.20, 0.20],
                    "annualization_trading_days": 252,
                    "by_ticker": volatility_adjustment,
                },
            }
            units = {
                "market_shock": "fraction_return_signed",
                "portfolio_impact": "fraction_of_portfolio_value",
                "position_impacts": "fraction_of_position_value",
                "max_drawdown": "fraction_of_portfolio_value",
                "recovery_time": "months",
                "confidence_level": "unitless_nominal_label",
            }
            methodology = (
                "Deterministic factor shock proxy; no path sampling and no simulation. "
                "position_impact = market_shock * sector_elasticity (static scenario "
                "table or a named instrument override) * volatility_adjustment "
                "(measured annualized volatility divided by "
                f"{STRESS_VOL_REFERENCE}, clipped to "
                f"[{STRESS_VOL_ADJ_MIN}, {STRESS_VOL_ADJ_MAX}]) and clipped to "
                "[-0.75, -0.02] for a negative shock; portfolio_impact = sum of "
                "position_impact * weight; max_drawdown = portfolio_impact * 1.15, a "
                "fixed uplift on that same proxy, not a simulated peak-to-trough "
                "path; recovery_time is the scenario's configured month estimate, "
                "not a simulated recovery path; confidence_level is a nominal 0.95 "
                "label with no simulated distribution behind it"
            )

            return {
                "scenario": scenario,
                "scenario_description": description,
                "max_drawdown": max_drawdown,
                "max_drawdown_basis": "derived_from_shock_proxy",
                "max_drawdown_formula": f"portfolio_impact * {STRESS_DRAWDOWN_UPLIFT}",
                "portfolio_impact": portfolio_impact,
                "impact_basis": "deterministic_factor_proxy",
                "position_impacts": position_impacts,
                "recovery_time": recovery_months,
                "recovery_time_basis": "configured_recovery_estimate_not_simulated",
                "confidence_level": STRESS_CONFIDENCE_LABEL,
                "confidence_basis": "nominal_label_not_simulated",
                "shock_inputs": shock_inputs,
                "units": units,
                "methodology": methodology
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
        portfolio_value: Optional[float] = None,
        price_currency: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Calculate volatility-adjusted position sizing

        The analytical target is inverse-volatility risk parity scaled to
        `target_volatility`, so the legs sum to the scale factor rather than to
        1.0. That gross exposure is preserved (renormalizing a risk-parity
        target to 100 % would delete the leverage it was asked to quantify) and
        reported through the shared normalization rule consumed by the rebalance
        workflow: `execution` states gross exposure, the financing it needs, and
        whether the target may be applied as a plain rebalance.

        Trade instructions are pinned to ONE aligned sizing price date and
        whole shares are derived from the reported notional with a documented
        half-up rule, so amount, `shares_delta`, and `sizing_price` reconcile.

        Args:
            price_data: Historical price data
            weights: Current portfolio weights
            model: Volatility model
            target_volatility: Target portfolio volatility
            portfolio_value: Budget for notional sizing; without it no trade
                amount is computable and instructions report `unavailable`
                instead of a fabricated zero
            price_currency: Currency of `price_data`; the engine cannot infer
                it, so it stays `unavailable` when the caller omits it
        
        Returns:
            Dictionary with sizing recommendations
        """
        try:
            if price_data.empty or not weights:
                return self._empty_volatility_sizing()
            
            # Missing observations remain missing.  The inverse-volatility
            # calculation uses each asset's active history and pairwise
            # correlation rather than manufacturing pre-listing zeroes.
            cleaned_prices = price_data.replace([np.inf, -np.inf], np.nan).sort_index()
            returns = cleaned_prices.pct_change(fill_method=None)
            if returns.empty or len(returns) < 2:
                return self._empty_volatility_sizing()
            returns = returns.iloc[1:]
            
            # Calculate volatilities using the selected model (EWMA, GARCH, EGARCH).
            # Keep the source of each estimate visible: a model that cannot fit a
            # short sample may use a measured sample-volatility fallback, but
            # never an invented constant.
            annualized_vols = {}
            daily_vols = {}
            volatility_sources = {}
            model_type = (model or "EWMA").upper()

            for ticker in returns.columns:
                series = returns[ticker].replace([np.inf, -np.inf], np.nan).dropna()
                if model_type == "EWMA" and len(series) < 2:
                    # A single return has no sample dispersion; do not turn the
                    # model's zero convention into a fabricated allocation.
                    continue
                sample_vol = (
                    float(series.std(ddof=1) * np.sqrt(252))
                    if len(series) > 1 else None
                )
                if sample_vol is not None and (not np.isfinite(sample_vol) or sample_vol < 0):
                    sample_vol = None
                vol_ann = None
                source = model_type
                try:
                    if model_type == "GARCH":
                        res = await self._garch_forecast(series, 1)
                    elif model_type == "EGARCH":
                        res = await self._egarch_forecast(series, 1)
                    else:
                        res = self._ewma_forecast(series, 1)
                    # Use the un-floored model estimate for inverse-volatility
                    # parity.  The public forecast remains clipped for stable
                    # UI bounds, but a 1% asset must not become a 5% peer.
                    raw_value = res.get("raw_volatility_forecast")
                    if raw_value is None:
                        raw_value = res.get("volatility_forecast")
                    if raw_value is not None:
                        candidate = float(raw_value)
                        if np.isfinite(candidate) and candidate >= 0.0:
                            vol_ann = candidate
                except Exception:
                    vol_ann = None
                if vol_ann is None and sample_vol is not None:
                    vol_ann = sample_vol
                    source = "sample_fallback"
                if vol_ann is None:
                    # No finite estimate means no inverse-volatility allocation;
                    # retaining a made-up floor would distort relative sizing.
                    continue
                annualized_vols[ticker] = float(vol_ann)
                daily_vols[ticker] = float(vol_ann) / np.sqrt(252)
                volatility_sources[ticker] = source

            available_tickers = list(returns.columns)
            current_tickers = []
            current_weight_values = []
            current_vol_values = []
            for ticker in available_tickers:
                try:
                    weight = float(weights.get(ticker, 0.0))
                    vol = float(annualized_vols.get(ticker, np.nan))
                except (TypeError, ValueError):
                    continue
                if weight > 0.0 and np.isfinite(weight) and np.isfinite(vol) and vol >= 0.0:
                    current_tickers.append(ticker)
                    current_weight_values.append(weight)
                    current_vol_values.append(vol / np.sqrt(252))
            current_volatility = None
            if current_tickers:
                current_corr = returns[current_tickers].corr()
                current_corr = current_corr.replace([np.inf, -np.inf], np.nan).fillna(0.0)
                current_corr_values = current_corr.to_numpy(dtype=float).copy()
                np.fill_diagonal(current_corr_values, 1.0)
                current_cov = current_corr_values * np.outer(current_vol_values, current_vol_values)
                current_vec = np.asarray(current_weight_values, dtype=float)
                variance = float(current_vec @ current_cov @ current_vec)
                if np.isfinite(variance):
                    current_volatility = float(np.sqrt(max(0.0, variance)) * np.sqrt(252))

            # Calculate true inverse-volatility risk parity weights for
            # positive, finite target holdings: w_i \propto 1 / \sigma_i.
            # Zero-weight positions must not receive a synthetic allocation.
            inv_vols = {}
            for ticker, weight in weights.items():
                sigma = annualized_vols.get(ticker)
                try:
                    weight = float(weight)
                    sigma = float(sigma)
                except (TypeError, ValueError):
                    continue
                if (
                    ticker in returns.columns
                    and weight > 0.0
                    and np.isfinite(weight)
                    and np.isfinite(sigma)
                    and sigma > 0.0
                ):
                    inv_vols[ticker] = 1.0 / sigma
            sum_inv_vol = sum(inv_vols.values())

            if sum_inv_vol <= 0:
                return self._empty_volatility_sizing()
            recommended_weights = {k: v / sum_inv_vol for k, v in inv_vols.items()}

            # Scale-to-target using only the recommended, positive-volatility
            # legs.  Excluding a zero-variance leg is not enough if its NaN
            # correlation remains in the matrix: 0 * NaN would still poison the
            # quadratic form.
            rec_tickers = list(recommended_weights)
            rec_vec = np.asarray([recommended_weights[ticker] for ticker in rec_tickers], dtype=float)
            rec_vol_vec = np.asarray([annualized_vols[ticker] / np.sqrt(252) for ticker in rec_tickers], dtype=float)
            if len(rec_tickers) == 1:
                rec_vol_ann = float(rec_vol_vec[0] * np.sqrt(252))
            else:
                rec_corr = returns[rec_tickers].corr()
                rec_corr = rec_corr.replace([np.inf, -np.inf], np.nan).fillna(0.0)
                rec_corr_values = rec_corr.to_numpy(dtype=float).copy()
                np.fill_diagonal(rec_corr_values, 1.0)
                rec_cov = rec_corr_values * np.outer(rec_vol_vec, rec_vol_vec)
                rec_variance = float(rec_vec @ rec_cov @ rec_vec)
                rec_vol_ann = (
                    float(np.sqrt(max(0.0, rec_variance)) * np.sqrt(252))
                    if np.isfinite(rec_variance) else 0.0
                )
            if not np.isfinite(rec_vol_ann) or rec_vol_ann <= 0.0:
                return self._empty_volatility_sizing()
            scale = float(target_volatility / rec_vol_ann)
            scaled_weights = {k: round(v * scale, 6) for k, v in recommended_weights.items()}

            # One documented normalization rule, shared with the rebalance
            # workflow.  The analytical target keeps its gross exposure and
            # reports the financing that exposure requires; `cash_weight` is the
            # signed net cash weight, so a 129 % book can no longer read as
            # "zero cash" with no financing leg anywhere.
            execution = normalization_block(
                scaled_weights,
                portfolio_value=portfolio_value,
                currency=price_currency,
                weights_normalized=False,
            )
            leveraged = bool(execution["financing_required"])
            # Signed net cash weight: a 129 % book reports -0.29 here, never 0.
            # `execution.net_cash_weight` is the same quantity derived from the
            # rounded published legs; the two agree to the published precision.
            cash_weight = round(1.0 - scale, 6)
            achieved_vol = float(rec_vol_ann * scale)

            history = sizing_history_block(
                returns, price_frame=cleaned_prices, model=model_type
            )
            basis = build_sizing_basis(
                cleaned_prices, list(returns.columns), currency=price_currency
            )
            instructions = build_trade_instructions(
                {
                    ticker: scaled_weights.get(ticker, 0.0) - _finite_weight(weights, ticker)
                    for ticker in returns.columns
                },
                basis["sizing_price"],
                portfolio_value=portfolio_value,
                currency=price_currency,
                sizing_price_as_of=basis["sizing_price_as_of"],
                sizing_price_provenance=basis["sizing_price_provenance"],
            )
            trades = instructions["trades"]

            financing_text = (
                f"financing required {execution['financing_requirement']} "
                f"{price_currency or 'in the sizing currency'}"
                if execution["financing_requirement"] is not None
                else "financing required (unquantified: no portfolio value)"
            )
            methodology = (
                f"{model} inverse-volatility risk parity scaled to target volatility "
                f"{target_volatility} (scale={round(scale, 4)}, "
                f"gross_exposure={execution['gross_exposure']}, cash={cash_weight}, "
                f"achieved_vol={round(achieved_vol, 4)}"
                + (
                    f", {financing_text}; not executable as a normal rebalance"
                    if leveraged
                    else ", unlevered long-only + cash"
                )
                + "; not full ERC: no Euler RC_i decomposition)"
            )
            return {
                "current_weights": weights,
                "recommended_weights": scaled_weights,
                "trades": trades,
                "target_volatility": target_volatility,
                "current_volatility": current_volatility,
                "volatilities": annualized_vols,
                "volatility_sources": volatility_sources,
                "scale_factor": round(scale, 6),
                "cash_weight": cash_weight,
                "leveraged": leveraged,
                "achieved_volatility": round(achieved_vol, 6),
                "methodology": methodology,
                "execution": execution,
                "sizing_history": history,
                "trade_instructions_status": instructions["status"],
                "trade_reconciliation": instructions["reconciliation"],
                "sizing_price": basis["sizing_price"],
                "sizing_price_as_of": basis["sizing_price_as_of"],
                "sizing_price_currency": basis["sizing_price_currency"],
                "sizing_price_provenance": basis["sizing_price_provenance"],
                "sizing_price_unavailable_reason": basis["sizing_price_unavailable_reason"],
                "sizing_price_missing_tickers": basis["missing_tickers"],
                "sizing_price_unpriced_tickers": basis["unpriced_tickers"],
                "price_currency_provenance": (
                    "measured" if price_currency else "unavailable"
                ),
            }
            
        except Exception as e:
            logger.error(f"Error in volatility sizing: {e}")
            return self._empty_volatility_sizing()
    
    async def risk_scoring(
        self, 
        price_data: pd.DataFrame, 
        weights: Dict[str, float],
        benchmark_data: Optional[pd.Series] = None
    ) -> Dict[str, Any]:
        """
        Calculate comprehensive risk score

        Args:
            price_data: Historical price data
            weights: Portfolio weights
            benchmark_data: Optional benchmark returns (or prices) for the
                factor leg. Without it the factor leg is excluded and the
                remaining legs renormalized (never a silent R²=0 → max score).

        Returns:
            Dictionary with risk score and components
        """
        try:
            if price_data.empty or not weights:
                return self._empty_risk_score()
            
            cleaned_prices = price_data.replace([np.inf, -np.inf], np.nan).sort_index()
            returns = cleaned_prices.pct_change(fill_method=None)
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
                corr_values = returns.corr().values
                avg_correlation = corr_values[np.triu_indices_from(corr_values, k=1)].mean()
                correlation_score = min(30, max(0, (avg_correlation - 0.3) * 50))  # High correlation = high risk
            else:
                avg_correlation = 0.0
                correlation_score = 0
            scores['correlation'] = correlation_score
            
            # Factor risk (25% weight) — only with a real benchmark. Calling
            # factor_exposure_analysis without one yields R²=0 always, which
            # would pin this leg at max risk, so exclude + renormalize instead.
            excluded: list[str] = []
            if benchmark_data is not None and not benchmark_data.empty:
                factor_result = await self.factor_exposure_analysis(
                    price_data, benchmark_data=benchmark_data, weights=weights
                )
                r_squared = factor_result.get('r_squared')
                if r_squared is None:
                    factor_score = None
                    excluded.append('factor_risk')
                else:
                    factor_score = min(30, (1 - r_squared) * 100)
            else:
                r_squared = None
                factor_score = None
                excluded.append('factor_risk')
            scores['factor_risk'] = factor_score
            
            # Market risk (10% weight) - based on recent volatility
            recent_returns = portfolio_returns.tail(60)  # Last 60 days
            recent_vol = recent_returns.std() * np.sqrt(252)
            market_score = min(30, recent_vol * 100)
            scores['market_risk'] = market_score
            
            # Calculate overall score (weighted average; excluded legs are
            # dropped and the remaining weights renormalized to sum to 1)
            weights_scores = {
                'concentration': 0.20,
                'volatility': 0.25,
                'correlation': 0.20,
                'factor_risk': 0.25,
                'market_risk': 0.10
            }
            active_weights = {k: w for k, w in weights_scores.items() if k not in excluded}
            w_total = sum(active_weights.values()) or 1.0
            active_weights = {k: w / w_total for k, w in active_weights.items()}

            overall_score = sum(scores[component] * active_weights[component]
                              for component in active_weights)
            
            # Determine risk level (stateless: no cross-request score memory,
            # so no singleton bleed or async race; change is always 0)
            if overall_score < 15:
                risk_level = "LOW"
            elif overall_score < 25:
                risk_level = "MEDIUM"
            else:
                risk_level = "HIGH"
            change = 0
            
            # Generate alerts
            alerts = []
            if concentration_score > 20:
                alerts.append(f"High concentration risk (HHI: {concentration_result.get('herfindahl_index', 0):.3f})")
            if volatility_score > 20:
                alerts.append(f"High volatility risk ({portfolio_vol:.1%} annualized)")
            if correlation_score > 15:
                alerts.append(f"High correlation risk (avg correlation: {avg_correlation:.2f})")
            if factor_score is not None and factor_score > 15:
                alerts.append(f"High unexplained risk (low R-squared: {r_squared:.2f})")
            if excluded:
                alerts.append("Factor leg excluded: no benchmark supplied (remaining legs renormalized)")
            
            return {
                "overall_score": round(overall_score, 1),
                "risk_level": risk_level,
                "change": change,
                "components": {k: (round(v, 1) if v is not None else None) for k, v in scores.items()},
                "alerts": alerts,
                "excluded_components": excluded,
                "factor_r_squared": r_squared,
                "methodology": "Multi-factor risk scoring with weighted components (stateless; factor leg requires a benchmark, else excluded + renormalized)"
            }
            
        except Exception as e:
            logger.error(f"Error in risk scoring: {e}")
            return self._empty_risk_score()
    
    # Helper methods for calculations
    
    def _calculate_portfolio_returns(self, returns: pd.DataFrame, weights: Dict[str, float]) -> pd.Series:
        """Delegate to the shared active positive-weight aggregation contract."""
        try:
            return aggregate_active_returns(returns, weights)
        except Exception:
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
                
                # Sortino ratio (Sortino & Price 1994): downside deviation of the
                # full return series below a target, not std of negative subsample.
                # Target matches the numerator (annual rf -> daily equivalent).
                target = self.risk_free_rate / 252
                downside = np.minimum(0.0, returns.to_numpy(dtype=float) - target)
                downside_deviation = float(np.sqrt(np.mean(downside ** 2)) * np.sqrt(252)) if len(returns) else 0.0
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
        except Exception:
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
        except Exception:
            return {}
    
    def _calculate_drawdown_metrics(self, returns: pd.Series) -> Dict[str, float]:
        """Calculate baseline-aware drawdown metrics.

        Initial wealth of 1.0 is a valid peak before the first return.  Without
        that baseline, a first-day loss appears to have no drawdown.
        """
        try:
            clean = pd.Series(returns).replace([np.inf, -np.inf], np.nan).dropna()
            if clean.empty:
                return {}

            wealth = (1.0 + clean).cumprod()
            wealth_with_baseline = pd.concat(
                [pd.Series([1.0]), wealth], ignore_index=True
            )
            running_max = wealth_with_baseline.cummax()
            drawdown = (wealth_with_baseline - running_max) / running_max

            return {
                "max_drawdown": float(drawdown.min())
            }
        except Exception:
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
        except Exception:
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
                    raw_s = raw_prices[ticker].replace([np.inf, -np.inf], np.nan)
                    if raw_s.notna().sum() >= 2:
                        # Keep missing dates in the index while calculating
                        # returns; dropping them first would create a return
                        # spanning an unobserved interval.
                        ticker_returns = raw_s.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna()
                    else:
                        ticker_returns = returns[ticker].replace([np.inf, -np.inf], np.nan).dropna()
                else:
                    ticker_returns = returns[ticker].replace([np.inf, -np.inf], np.nan).dropna()

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
                        "history_warning": f"Only {data_points} trading days in the analyzed window" if is_limited else None
                    }
            
            return position_metrics
        except Exception:
            return {}
            
    @staticmethod
    def _forecast_variance_path(forecast: Any, horizon: int, simulated: bool = False) -> np.ndarray:
        """Return the per-period variance path from an arch forecast.

        ``arch`` reports analytic GARCH variance as ``(1, horizon)`` and
        EGARCH simulation variance as ``(1, horizon, simulations)``.  The
        simulation axis is an ensemble dimension, not a time dimension, so it
        must be averaged before the caller cumulatively sums the periods.
        """
        values = np.asarray(forecast.variance.values, dtype=float)
        if values.ndim == 0:
            values = values.reshape(1)
        if simulated and values.ndim >= 3:
            values = values.mean(axis=tuple(range(2, values.ndim)))
        elif simulated and values.ndim == 2:
            # A few arch-compatible adapters drop the leading origin axis and
            # return ``(horizon, simulations)`` instead.  Distinguish that
            # from the ordinary analytic ``(1, horizon)`` shape.
            if values.shape[0] != 1 and values.shape[-1] >= values.shape[0]:
                values = values.mean(axis=-1)
        values = np.squeeze(values)
        if values.ndim == 0:
            path = values.reshape(1)
        elif values.ndim == 1:
            path = values
        else:
            # Analytic forecasts have one origin row; retain the last origin
            # row if a test double supplies more than one.
            path = values[-1]
        return np.asarray(path, dtype=float).reshape(-1)[: max(1, int(horizon))]

    @staticmethod
    def _cumulative_forecast_volatility(
        variance_path: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Convert per-period arch variances to cumulative horizon units.

        ``arch`` returns one conditional variance for each future period, not
        a cumulative terminal variance.  The public volatility field remains
        annualized (the h-day cumulative variance divided by h and scaled by
        252), while the return-space path is the unscaled h-day sigma used for
        VaR/ES.
        """
        values = np.maximum(np.asarray(variance_path, dtype=float), 0.0)
        cumulative = np.cumsum(values)
        steps = np.arange(1, len(cumulative) + 1, dtype=float)
        annualized = np.sqrt(cumulative * 252.0 / steps) / 100.0
        return_space = np.sqrt(cumulative) / 100.0
        return annualized, return_space

    async def _garch_forecast(self, returns: pd.Series, horizon: int) -> Dict[str, Any]:
        """GARCH volatility forecast with cumulative-horizon tail units.

        ``arch`` returns one conditional variance per future period.  The
        adapter sums that path before converting to return-space VaR/CVaR;
        applying a second ``sqrt(horizon / 252)`` would double-count time.
        """
        h = int(max(1, horizon))
        try:
            clean_returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
            clean_returns = clean_returns.clip(lower=-0.20, upper=0.20)
            if len(clean_returns) < 20:
                return self._empty_forecast(h, "GARCH")

            # Scale returns by 100 for arch optimizer numerical convergence stability.
            scaled_returns = clean_returns * 100.0
            model = arch_model(scaled_returns, vol='Garch', p=1, q=1, dist='normal', rescale=False)
            fitted_model = await asyncio.to_thread(
                lambda: model.fit(disp='off', show_warning=False, options={'maxiter': 100})
            )

            forecast = await asyncio.to_thread(
                lambda: fitted_model.forecast(horizon=h, method='analytic')
            )
            variance_path = self._forecast_variance_path(forecast, h)
            if variance_path.size == 0 or not np.isfinite(variance_path).all():
                raise ValueError("arch returned no finite GARCH variance path")
            variance_path = np.maximum(variance_path, 0.0)

            # arch supplies per-period conditional variances.  Aggregate
            # them before converting to the h-day return-space tail units.
            volatility_path, return_space_path = self._cumulative_forecast_volatility(
                variance_path
            )
            raw_vol_final = float(volatility_path[-1])
            vol_final = float(np.clip(raw_vol_final, 0.05, 1.20))
            return_space_vol = float(return_space_path[-1])
            var_forecast = float(np.clip(-return_space_vol * 1.645, -0.99, -0.001))
            cvar_forecast = float(np.clip(-return_space_vol * 2.06, -0.99, -0.001))

            return {
                "model": "GARCH",
                "horizon": h,
                "volatility_forecast": vol_final,
                "raw_volatility_forecast": raw_vol_final,
                "var_forecast": var_forecast,
                "cvar_forecast": cvar_forecast,
                "confidence_interval": [
                    max(0.0, float(vol_final * 0.8)),
                    float(vol_final * 1.2)
                ],
                "term_structure": [float(np.clip(v, 0.05, 1.20)) for v in volatility_path],
                "model_params": {
                    "p": 1,
                    "q": 1,
                    "type": "GARCH",
                    "forecast_method": "analytic",
                },
            }
        except Exception as e:
            logger.error(f"GARCH forecast error: {e}")
            return self._empty_forecast(
                h, "GARCH", error="GARCH forecast failed"
            )

    async def _egarch_forecast(self, returns: pd.Series, horizon: int) -> Dict[str, Any]:
        """EGARCH forecast using analytic h=1 and seeded simulation for h>1."""
        h = int(max(1, horizon))
        try:
            clean_returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
            clean_returns = clean_returns.clip(lower=-0.20, upper=0.20)
            if len(clean_returns) < 20:
                return self._empty_forecast(h, "EGARCH")

            scaled_returns = clean_returns * 100.0
            model = arch_model(scaled_returns, vol='EGARCH', p=1, q=1, dist='normal', rescale=False)
            fitted_model = await asyncio.to_thread(
                lambda: model.fit(disp='off', show_warning=False)
            )

            if h == 1:
                forecast = await asyncio.to_thread(
                    lambda: fitted_model.forecast(horizon=1, method='analytic')
                )
                simulated = False
                method = "analytic"
            else:
                # arch 8.x does not provide analytic multi-step EGARCH
                # forecasts.  Simulation is a supported path; fixing the seed
                # makes the returned path deterministic for tests and clients.
                forecast = await asyncio.to_thread(
                    lambda: fitted_model.forecast(
                        horizon=h,
                        method="simulation",
                        simulations=2000,
                        random_state=100,
                    )
                )
                simulated = True
                method = "simulation"

            variance_path = self._forecast_variance_path(forecast, h, simulated=simulated)
            if variance_path.size == 0 or not np.isfinite(variance_path).all():
                raise ValueError("arch returned no finite EGARCH variance path")
            variance_path = np.maximum(variance_path, 0.0)
            volatility_path, return_space_path = self._cumulative_forecast_volatility(
                variance_path
            )
            raw_vol_final = float(volatility_path[-1])
            vol_final = float(np.clip(raw_vol_final, 0.0, 1.20))
            return_space_vol = float(return_space_path[-1])

            return {
                "model": "EGARCH",
                "horizon": h,
                "volatility_forecast": vol_final,
                "raw_volatility_forecast": raw_vol_final,
                "var_forecast": float(np.clip(-return_space_vol * 1.645, -0.99, 0.0)),
                "cvar_forecast": float(np.clip(-return_space_vol * 2.06, -0.99, 0.0)),
                "confidence_interval": [
                    max(0.0, float(vol_final * 0.8)),
                    float(vol_final * 1.2)
                ],
                "term_structure": [float(np.clip(v, 0.0, 1.20)) for v in volatility_path],
                "model_params": {
                    "p": 1,
                    "q": 1,
                    "type": "EGARCH",
                    "forecast_method": method,
                    "simulations": 2000 if simulated else None,
                    "random_state": 100 if simulated else None,
                },
            }
        except Exception as e:
            logger.error(f"EGARCH forecast error: {e}")
            return self._empty_forecast(
                h, "EGARCH", error="EGARCH forecast failed"
            )
    
    def _ewma_forecast(self, returns: pd.Series, horizon: int) -> Dict[str, Any]:
        """EWMA volatility forecast (RiskMetrics 1996 single-pass recursion)."""
        try:
            h = max(1, horizon)
            clean_returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
            clean_returns = clean_returns.clip(lower=-0.20, upper=0.20)
            lambda_val = 0.94  # Standard RiskMetrics decay factor

            # Single-pass recursion: sigma^2_t = lambda*sigma^2_{t-1} + (1-lambda)*r^2_{t-1}
            r = clean_returns.to_numpy(dtype=float)
            var = float(np.var(r)) if len(r) else 0.0
            for x in r[-min(len(r), 60):]:
                var = lambda_val * var + (1.0 - lambda_val) * x * x

            raw_forecast_volatility = float(np.sqrt(max(0.0, var) * 252))
            forecast_volatility = float(np.clip(raw_forecast_volatility, 0.05, 1.20))
            # RiskMetrics has no mean reversion: flat h-step term structure
            term_structure = [forecast_volatility] * h
            h_factor = np.sqrt(h / 252.0)
            
            return {
                "model": "EWMA",
                "horizon": h,
                "volatility_forecast": forecast_volatility,
                "raw_volatility_forecast": raw_forecast_volatility,
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
            return self._empty_forecast(h, "EWMA")
    
    def _calculate_factor_exposures(
        self, 
        returns: pd.DataFrame, 
        benchmark_returns: pd.Series, 
        weights: Dict[str, float]
    ) -> Dict[str, Any]:
        """Calculate factor exposures using OLS regression against market benchmark"""
        err_portfolio = {
            'alpha': None, 'annualized_alpha': None, 'market': None,
            'is_limited_history': False, 'history_warning': None,
            'data_points': 0, 'error': 'insufficient data for factor regression'
        }
        try:
            if returns.empty:
                return {
                    'portfolio': dict(err_portfolio), 'positions': {},
                    'r_squared': None, 'adjusted_r_squared': None,
                    'error': 'insufficient data for factor regression'
                }

            positions_exp: Dict[str, Any] = {}
            if not benchmark_returns.empty and len(benchmark_returns) > 10:
                common_dates = returns.index.intersection(benchmark_returns.index)
                if len(common_dates) > 10:
                    aligned_returns = returns.loc[common_dates]
                    aligned_benchmark = benchmark_returns.loc[common_dates]

                    for ticker in aligned_returns.columns:
                        try:
                            s = aligned_returns[ticker]
                            # dropna, not `!= 0.0`: keeps genuine 0% days, drops
                            # pre-listing/no-trade NaN gaps
                            active = s.dropna().index.intersection(aligned_benchmark.index)
                            data_pts = int(len(active))
                            is_limited = data_pts < 30

                            if data_pts >= 10:
                                # Active-history filter: regress only on days the asset
                                # actually traded (zero-filled pre-listing rows would
                                # attenuate beta toward 0). HAC SEs, statsmodels-local.
                                X = sm.add_constant(aligned_benchmark.loc[active])
                                y = s.loc[active]
                                try:
                                    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
                                except Exception:
                                    model = sm.OLS(y, X).fit()
                                alpha = float(model.params.iloc[0]) if len(model.params) > 0 else None
                                beta = float(model.params.iloc[1]) if len(model.params) > 1 else None
                            else:
                                alpha = None
                                beta = None

                            positions_exp[ticker] = {
                                'alpha': round(alpha, 6) if alpha is not None else None,
                                'annualized_alpha': round(alpha * 252.0, 4) if alpha is not None else None,
                                'market': round(beta, 4) if beta is not None else None,
                                'is_limited_history': is_limited,
                                'history_warning': f"Only {data_pts} active trading days in the analyzed window" if is_limited else None,
                                'data_points': data_pts,
                                **({'error': 'insufficient history for factor regression'} if alpha is None else {})
                            }
                        except Exception:
                            positions_exp[ticker] = {
                                'alpha': None, 'annualized_alpha': None, 'market': None,
                                'is_limited_history': False, 'history_warning': None,
                                'data_points': 0, 'error': 'factor regression failed'
                            }

                    port_returns = self._calculate_portfolio_returns(aligned_returns, weights).dropna()
                    if not port_returns.empty:
                        try:
                            # Portfolio is active when any constituent has a real
                            # (non-NaN) return that day; 0% is a valid observation
                            traded = aligned_returns.notna().any(axis=1)
                            port_active = traded[traded].index.intersection(aligned_benchmark.index)
                            if len(port_active) < 10:
                                raise ValueError("insufficient active portfolio history")
                            X_port = sm.add_constant(aligned_benchmark.loc[port_active])
                            try:
                                port_model = sm.OLS(port_returns.loc[port_active], X_port).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
                            except Exception:
                                port_model = sm.OLS(port_returns.loc[port_active], X_port).fit()
                            port_alpha = float(port_model.params.iloc[0]) if len(port_model.params) > 0 else None
                            port_beta = float(port_model.params.iloc[1]) if len(port_model.params) > 1 else None
                            r_squared = round(float(port_model.rsquared), 4)
                            adj_r_squared = round(float(max(0.0, port_model.rsquared_adj)), 4)
                            return {
                                'portfolio': {
                                    'alpha': round(port_alpha, 6) if port_alpha is not None else None,
                                    'annualized_alpha': round(port_alpha * 252.0, 4) if port_alpha is not None else None,
                                    'market': round(port_beta, 4) if port_beta is not None else None
                                },
                                'positions': positions_exp,
                                'r_squared': r_squared,
                                'adjusted_r_squared': adj_r_squared
                            }
                        except Exception as pe:
                            logger.warning(f"Portfolio factor regression failed: {pe}")
                            return {
                                'portfolio': dict(err_portfolio),
                                'positions': positions_exp,
                                'r_squared': None, 'adjusted_r_squared': None,
                                'error': 'portfolio factor regression failed'
                            }

            # No usable benchmark window: fill ONLY tickers not already computed
            for ticker in returns.columns:
                if ticker not in positions_exp:
                    positions_exp[ticker] = {
                        'alpha': None, 'annualized_alpha': None, 'market': None,
                        'is_limited_history': False, 'history_warning': None,
                        'data_points': 0, 'error': 'insufficient data for factor regression'
                    }
            return {
                'portfolio': dict(err_portfolio),
                'positions': positions_exp,
                'r_squared': None, 'adjusted_r_squared': None,
                'error': 'insufficient data for factor regression'
            }
        except Exception as e:
            logger.error(f"Factor exposure calculation error: {e}")
            return {
                'portfolio': dict(err_portfolio), 'positions': {},
                'r_squared': None, 'adjusted_r_squared': None,
                'error': 'factor exposure calculation failed'
            }

    # Empty result methods for error handling
    
    def _empty_metrics(self) -> Dict[str, Any]:
        return {
            "annual_return": None,
            "annual_volatility": None,
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "skewness": None,
            "kurtosis": None,
            "max_drawdown": None,
            "var_95": None,
            "cvar_95": None,
            "hit_ratio": None,
            "observations": 0,
            "active_observations": 0,
            "positions": {},
            "error": "Insufficient data for calculations"
        }
    
    def _empty_forecast(
        self,
        horizon: int = 1,
        model: str = "GARCH",
        error: str = "Insufficient data for forecast",
    ) -> Dict[str, Any]:
        h = max(1, horizon)
        return {
            "model": model,
            "horizon": h,
            "volatility_forecast": None,
            "var_forecast": None,
            "cvar_forecast": None,
            "confidence_interval": None,
            "term_structure": None,
            "model_params": None,
            "error": error
        }
    
    def _empty_factor_exposure(self) -> Dict[str, Any]:
        return {
            "portfolio": {
                "alpha": None,
                "market": None
            },
            "positions": {},
            "r_squared": None,
            "adjusted_r_squared": None,
            "error": "Insufficient data for factor analysis"
        }
    
    def _empty_concentration(self) -> Dict[str, Any]:
        return {
            "largest_position": 0.0,
            "top_3": 0.0,
            "top_5": 0.0,
            "top_10": 0.0,
            "herfindahl_index": 0.0,
            "effective_positions": 0.0,
            "diversification_score": 0.0,
            "diversification_ratio": 1.0,
            "gini_coefficient": 0.0,
            "by_weight": {},
            "error": "No position data available"
        }
    
    def _empty_liquidity(self) -> Dict[str, Any]:
        # An unavailable result claims nothing.  Returning a plausible
        # overall_score=5.0 / risk_level="Medium" / "5-10" made an absence
        # indistinguishable from a measured mid-liquidity portfolio (V3-09).
        # The volume split is all zeros because no position was measured:
        # publishing `low_volume_pct=100` asserted a worst-case book nobody
        # observed.
        return {
            "overall_score": None,
            "overall_score_raw": None,
            "liquidation_time_days": None,
            "risk_level": None,
            "overall_band": None,
            "by_position": {},
            "volume_stats": {
                "avg_volume": 0,
                "total_portfolio_volume": 0,
                "high_volume_pct": 0,
                "medium_volume_pct": 0,
                "low_volume_pct": 0
            },
            "score_band_rule": dict(LIQUIDITY_SCORE_BAND_RULE),
            "error": "No liquidity data available"
        }
    
    def _empty_stress_test(self) -> Dict[str, Any]:
        # Mirrors the success payload key-for-key with None values: with no
        # price history there is no proxy, no recovery estimate, no confidence
        # label and no shock input to report.
        return {
            "scenario": "unknown",
            "scenario_description": None,
            "max_drawdown": None,
            "max_drawdown_basis": None,
            "max_drawdown_formula": None,
            "portfolio_impact": None,
            "impact_basis": None,
            "position_impacts": {},
            "recovery_time": None,
            "recovery_time_basis": None,
            "confidence_level": None,
            "confidence_basis": None,
            "shock_inputs": None,
            "units": None,
            "methodology": None,
            "error": "Insufficient data for stress testing"
        }
    
    def _empty_volatility_sizing(self) -> Dict[str, Any]:
        return {
            "current_weights": {},
            "recommended_weights": {},
            "trades": {},
            "target_volatility": 0.15,
            "current_volatility": None,
            "error": "Insufficient data for volatility sizing"
        }
    
    def _empty_risk_score(self) -> Dict[str, Any]:
        return {
            "overall_score": None,
            "risk_level": None,
            "change": None,
            "components": {
                "concentration": None,
                "volatility": None,
                "correlation": None,
                "factor_risk": None,
                "market_risk": None
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