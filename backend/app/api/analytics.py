"""
Analytics API endpoints for risk calculations and portfolio analytics
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import numpy as np
import pandas as pd

from app.db.database import get_db_session
from app.models.database import PortfolioPosition
from app.services.benchmark_service import BenchmarkService
from app.services.optimization_service import STRATEGIES, optimize
from app.services.regime_service import detect_regime
from app.services.monte_carlo_service import simulate_goal
from app.services.data_service import GlobalDataService, DataService
from app.services.cache_service import GlobalCacheService, CacheService
from app.services.analytics_engine import GlobalAnalyticsEngine, AnalyticsEngine
from app.models.schemas import (
    RealizedRiskMetrics, ForecastRiskMetrics, FactorExposure, ConcentrationMetrics,
    LiquidityMetrics, RiskScore, StressTestRequest, StressTestResponse,
    VolatilitySizingRequest, VolatilitySizingResponse
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Create router
router = APIRouter()


# Dependency injection
def get_data_service(db: AsyncSession = Depends(get_db_session)) -> DataService:
    """Get data service instance"""
    return GlobalDataService(db).get_service()


def get_cache_service(db: AsyncSession = Depends(get_db_session)) -> CacheService:
    """Get cache service instance"""
    return GlobalCacheService(db).get_service()


def get_analytics_engine() -> AnalyticsEngine:
    """Get analytics engine instance"""
    return GlobalAnalyticsEngine().get_engine()


def get_benchmark_service(db: AsyncSession = Depends(get_db_session)) -> BenchmarkService:
    """Get NIFTY benchmark service instance"""
    return BenchmarkService(db)


async def resolve_allocation(
    tickers_param: Optional[str],
    db: AsyncSession,
) -> tuple[List[str], Dict[str, float]]:
    """Shared allocation resolution: explicit tickers (equal weight) or DB positions."""
    if tickers_param:
        ticker_list = [t.strip().upper() for t in tickers_param.split(",") if t.strip()]
        eq = 1.0 / len(ticker_list)
        return ticker_list, {t: eq for t in ticker_list}
    weights = await _load_portfolio_allocation(db)
    if not weights:
        raise ValueError("No portfolio positions found")
    return list(weights.keys()), weights


def _q(metric_fn, *args, **kwargs):
    """Guard a single quantstats metric call; API drift must not kill the sheet."""
    try:
        val = metric_fn(*args, **kwargs)
        if hasattr(val, "item"):
            val = val.item()
        return round(float(val), 6)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"quantstats metric unavailable ({metric_fn.__name__}): {e}")
        return None


def _price_series(df: pd.DataFrame) -> Optional[pd.Series]:
    """Extract the close-price series indexed by DATE from any DataService shape.

    Fresh yfinance fetches carry 'date' as a column (integer row index);
    cache hits return a DatetimeIndex. Stress scenarios filter returns by
    date, so every analytics consumer must receive a date-indexed series.
    """
    if df is None or df.empty:
        return None
    price_col = next(
        (c for c in ("adj_close", "close", "Adj Close", "Close") if c in df.columns),
        None,
    )
    if price_col is None:
        return None
    values = df[price_col]
    for dcol in ("date", "Date"):
        if dcol in df.columns:
            idx = pd.to_datetime(df[dcol], errors="coerce")
            return pd.Series(values.values, index=idx, name=price_col).dropna()
    if isinstance(df.index, pd.DatetimeIndex):
        out = values.copy()
        out.index = pd.to_datetime(df.index)
        return out
    return pd.Series(values.values, index=pd.RangeIndex(len(values)), name=price_col)


def _assign_price(store: Dict[str, pd.Series], ticker: str, df: pd.DataFrame) -> None:
    series = _price_series(df)
    if series is not None:
        store[ticker] = series


async def _load_portfolio_allocation(db: AsyncSession) -> Optional[Dict[str, float]]:
    """
    Load {ticker: weight} from actual portfolio positions.

    Prefers market-value-derived weights (quantity x last_price); falls back to the
    stored weight column, then equal weights. Returns None when the portfolio is empty.
    """
    result = await db.execute(select(PortfolioPosition))
    positions = result.scalars().all()
    if not positions:
        return None

    mv_weights = {}
    total_mv = 0.0
    for pos in positions:
        mv = pos.market_value or 0.0
        if mv <= 0:
            mv = (pos.quantity or 0.0) * (pos.last_price or 0.0)
        mv_weights[pos.ticker] = mv
        total_mv += mv

    if total_mv > 0:
        return {t: v / total_mv for t, v in mv_weights.items()}

    total_weight = sum(pos.weight or 0.0 for pos in positions)
    if total_weight > 0:
        return {pos.ticker: (pos.weight or 0.0) / total_weight for pos in positions}

    n = len(positions)
    return {pos.ticker: 1.0 / n for pos in positions}


@router.get("/realized-risk")
async def get_realized_risk(
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers or 'portfolio'"),
    start: Optional[str] = Query(default=None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(default=None, description="End date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    cache_service: CacheService = Depends(get_cache_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Get realized risk metrics for portfolio or individual assets
    """
    try:
        # Default date range (last 252 trading days)
        if not end:
            end = datetime.now().strftime('%Y-%m-%d')
        if not start:
            start = (datetime.now() - timedelta(days=252)).strftime('%Y-%m-%d')

        # Resolve tickers + weights: explicit param wins, else actual DB positions
        if tickers:
            ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
            equal_weight = 1.0 / len(ticker_list)
            weights = {ticker: equal_weight for ticker in ticker_list}
        else:
            weights = await _load_portfolio_allocation(db)
            if not weights:
                return {
                    "portfolio": {
                        "annual_return": 0.0,
                        "annual_volatility": 0.20,
                        "sharpe_ratio": 0.0,
                        "sortino_ratio": 0.0,
                        "skewness": 0.0,
                        "kurtosis": 3.0,
                        "max_drawdown": 0.0,
                        "var_95": -0.032,
                        "cvar_95": -0.047,
                        "hit_ratio": 0.5
                    },
                    "positions": {},
                    "error": "No portfolio positions found"
                }
            ticker_list = list(weights.keys())

        # Fetch price data for all tickers
        price_data_dict = {}
        for ticker in ticker_list:
            df = await data_service.fetch_historical_data(ticker, start, end)
            if df is not None and not df.empty:
                _assign_price(price_data_dict, ticker, df)

        if not price_data_dict:
            logger.warning("No price data available for tickers")
            return {
                "portfolio": {
                    "annual_return": 0.0,
                    "annual_volatility": 0.20,
                    "sharpe_ratio": 0.0,
                    "sortino_ratio": 0.0,
                    "skewness": 0.0,
                    "kurtosis": 3.0,
                    "max_drawdown": 0.0,
                    "var_95": -0.032,
                    "cvar_95": -0.047,
                    "hit_ratio": 0.5
                },
                "positions": {},
                "error": "No price data available"
            }
        
        # Combine price data
        price_data = pd.DataFrame(price_data_dict)
        
        # Calculate portfolio metrics using analytics engine
        metrics = await analytics_engine.calculate_portfolio_metrics(price_data, weights)
        
        # Format response
        portfolio_metrics = {
            "annual_return": metrics.get("annual_return", 0),
            "annual_volatility": metrics.get("annual_volatility", 0.20),
            "sharpe_ratio": metrics.get("sharpe_ratio", 0),
            "sortino_ratio": metrics.get("sortino_ratio", 0),
            "skewness": metrics.get("skewness", 0),
            "kurtosis": metrics.get("kurtosis", 3),
            "max_drawdown": metrics.get("max_drawdown", 0),
            "var_95": metrics.get("var_95", -0.032),
            "cvar_95": metrics.get("cvar_95", -0.047),
            "hit_ratio": metrics.get("hit_ratio", 0.5)
        }
        
        # Position-level metrics
        positions = {}
        for ticker, pos_metrics in metrics.get("positions", {}).items():
            positions[ticker] = {
                "annual_return": pos_metrics.get("annual_return", 0),
                "annual_volatility": pos_metrics.get("annual_volatility", 0.20),
                "sharpe_ratio": pos_metrics.get("sharpe_ratio", 0),
                "max_drawdown": pos_metrics.get("max_drawdown", 0),
                "var_95": pos_metrics.get("var_95", -0.032),
                "weight": pos_metrics.get("weight", 0)
            }
        
        return {
            "portfolio": portfolio_metrics,
            "positions": positions,
            "data_range": {"start": start, "end": end},
            "methodology": "Real-time calculations using quantstats and statistical models"
        }
        
    except Exception as e:
        logger.error(f"Error in get_realized_risk: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/forecast-risk")
async def get_forecast_risk(
    model: str = Query(default="GARCH", description="Risk model: EWMA, GARCH, or EGARCH"),
    horizon: int = Query(default=1, ge=1, le=30, description="Forecast horizon in days"),
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    cache_service: CacheService = Depends(get_cache_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Get forecast risk metrics using specified model
    """
    try:
        # Resolve tickers: explicit param wins, else actual DB positions
        if tickers:
            ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        else:
            allocation = await _load_portfolio_allocation(db)
            if not allocation:
                return {
                    "model": model,
                    "horizon": horizon,
                    "portfolio": {
                        "volatility_forecast": 0.22,
                        "var_forecast": -0.028,
                        "cvar_forecast": -0.041,
                        "confidence_interval": [0.18, 0.26]
                    },
                    "positions": {},
                    "model_params": {"p": 1, "q": 1, "type": model},
                    "error": "No portfolio positions found"
                }
            ticker_list = list(allocation.keys())
        
        # Default date range for sufficient historical data
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=252)).strftime('%Y-%m-%d')
        
        # Fetch price data for all tickers
        price_data_dict = {}
        for ticker in ticker_list:
            df = await data_service.fetch_historical_data(ticker, start, end)
            if df is not None and not df.empty:
                _assign_price(price_data_dict, ticker, df)
        
        if not price_data_dict:
            return {
                "model": model,
                "horizon": horizon,
                "portfolio": {
                    "volatility_forecast": 0.22,
                    "var_forecast": -0.028,
                    "cvar_forecast": -0.041,
                    "confidence_interval": [0.18, 0.26]
                },
                "positions": {},
                "model_params": {"p": 1, "q": 1, "type": model},
                "error": "No price data available for forecast"
            }
        
        # Combine price data
        price_data = pd.DataFrame(price_data_dict)

        # Calculate portfolio returns
        returns = price_data.pct_change().dropna()

        # Weight asset returns by the DB allocation when positions were resolved;
        # explicit-ticker requests have no weights and stay equal-weighted.
        portfolio_returns = returns.mean(axis=1)
        if not tickers:
            matched = {t: w for t, w in (allocation or {}).items() if t in returns.columns}
            total_w = sum(matched.values())
            if matched and total_w > 0:
                norm = pd.Series({t: w / total_w for t, w in matched.items()})
                portfolio_returns = returns[norm.index].mul(norm, axis=1).sum(axis=1)

        # Calculate portfolio volatility forecast using analytics engine
        forecast_result = await analytics_engine.forecast_volatility(portfolio_returns, model, horizon)
        
        # Position-level forecasts
        positions = {}
        for ticker in returns.columns:
            try:
                ticker_forecast = await analytics_engine.forecast_volatility(returns[ticker], model, horizon)
                positions[ticker] = {
                    "volatility_forecast": ticker_forecast.get("volatility_forecast", 0.25),
                    "var_forecast": ticker_forecast.get("var_forecast", -0.032)
                }
            except:
                positions[ticker] = {
                    "volatility_forecast": 0.25,
                    "var_forecast": -0.032
                }
        
        return {
            "model": model,
            "horizon": horizon,
            "portfolio": {
                "volatility_forecast": forecast_result.get("volatility_forecast", 0.22),
                "var_forecast": forecast_result.get("var_forecast", -0.028),
                "cvar_forecast": forecast_result.get("cvar_forecast", -0.041),
                "confidence_interval": forecast_result.get("confidence_interval", [0.18, 0.26])
            },
            "positions": positions,
            "model_params": forecast_result.get("model_params", {"p": 1, "q": 1, "type": model}),
            "data_range": {"start": start, "end": end},
            "methodology": f"Volatility forecasting using {model} model with {horizon}-day horizon"
        }
        
    except Exception as e:
        logger.error(f"Error in get_forecast_risk: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/factor-exposure")
async def get_factor_exposure(
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers"),
    lookback_days: int = Query(default=252, ge=30, le=756, description="Lookback period in days"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Get factor exposure analysis
    """
    try:
        # Resolve tickers: explicit param wins, else actual DB positions
        if tickers:
            ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
        else:
            allocation = await _load_portfolio_allocation(db)
            if not allocation:
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
                    "error": "No portfolio positions found"
                }
            ticker_list = list(allocation.keys())
        
        # Calculate date range
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        
        # Fetch price data for all tickers
        price_data_dict = {}
        for ticker in ticker_list:
            df = await data_service.fetch_historical_data(ticker, start, end)
            if df is not None and not df.empty:
                _assign_price(price_data_dict, ticker, df)
        
        if not price_data_dict:
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
                "error": "No price data available for factor analysis"
            }
        
        # Combine price data
        price_data = pd.DataFrame(price_data_dict)
        
        # Perform factor exposure analysis using analytics engine
        factor_result = await analytics_engine.factor_exposure_analysis(price_data)
        
        return {
            "portfolio": factor_result.get("portfolio", {}),
            "positions": factor_result.get("positions", {}),
            "r_squared": factor_result.get("r_squared", 0.5),
            "adjusted_r_squared": factor_result.get("adjusted_r_squared", 0.48),
            "data_range": {"start": start, "end": end},
            "lookback_days": lookback_days,
            "methodology": "Statistical factor model with market benchmark regression"
        }
        
    except Exception as e:
        logger.error(f"Error in get_factor_exposure: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/concentration")
async def get_concentration_metrics(
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Get portfolio concentration metrics
    """
    try:
        # Actual DB positions
        weights = await _load_portfolio_allocation(db)
        if not weights:
            return {
                "largest_position": 0.0,
                "top_3": 0.0,
                "top_5": 0.0,
                "top_10": 0.0,
                "herfindahl_index": 0.0,
                "effective_positions": 0.0,
                "diversification_ratio": 1.0,
                "by_weight": {},
                "by_sector": {},
                "error": "No portfolio positions found"
            }
        
        # Calculate concentration metrics using analytics engine
        concentration_result = await analytics_engine.concentration_analysis(weights)
        
        # Sector allocation from actual position metadata
        sector_result = await db.execute(select(PortfolioPosition))
        positions = sector_result.scalars().all()
        total_position_weight = sum(pos.weight or 0.0 for pos in positions) or 1.0
        by_sector = {}
        for pos in positions:
            sector = pos.sector or "Unknown"
            by_sector[sector] = round(
                by_sector.get(sector, 0.0) + (pos.weight or 0.0) / total_position_weight, 4
            )
        
        return {
            "largest_position": concentration_result.get("largest_position", 0.25),
            "top_3": concentration_result.get("top_3", 0.75),
            "top_5": concentration_result.get("top_5", 1.0),
            "top_10": concentration_result.get("top_10", 1.0),
            "herfindahl_index": concentration_result.get("herfindahl_index", 0.25),
            "effective_positions": concentration_result.get("effective_positions", 4.0),
            "diversification_ratio": concentration_result.get("diversification_ratio", 1.0),
            "by_weight": concentration_result.get("by_weight", {}),
            "by_sector": by_sector,
            "methodology": "Concentration analysis using Herfindahl-Hirschman Index and effective number of positions"
        }
        
    except Exception as e:
        logger.error(f"Error in get_concentration_metrics: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/liquidity")
async def get_liquidity_metrics(
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Get portfolio liquidity analysis
    """
    try:
        # Actual DB positions
        allocation = await _load_portfolio_allocation(db)
        if not allocation:
            return {
                "overall_score": 5.0,
                "liquidation_time_days": "5-10",
                "risk_level": "Medium",
                "by_position": {},
                "volume_stats": {"avg_volume": 0, "total_portfolio_volume": 0, "high_volume_pct": 0, "medium_volume_pct": 0, "low_volume_pct": 100},
                "error": "No portfolio positions found"
            }
        tickers = list(allocation.keys())
        
        # Fetch price and volume data for liquidity analysis
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        price_data_dict = {}
        for ticker in tickers:
            df = await data_service.fetch_historical_data(ticker, start, end)
            if df is not None and not df.empty:
                # Include volume data for liquidity analysis
                price_col = 'adj_close' if 'adj_close' in df.columns else 'close'
                vol_col = 'Volume' if 'Volume' in df.columns else ('volume' if 'volume' in df.columns else None)
                if vol_col and price_col in df.columns:
                    price_data_dict[ticker] = df[[price_col, vol_col]].rename(columns={vol_col: 'Volume', price_col: 'Close'})
                else:
                    # Fallback: just price data if volume not available
                    price_data_dict[ticker] = df[[price_col]].rename(columns={price_col: 'Close'})
        
        if not price_data_dict:
            return {
                "overall_score": 5.0,
                "liquidation_time_days": "5-10",
                "risk_level": "Medium",
                "by_position": {},
                "volume_stats": {"avg_volume": 0, "total_portfolio_volume": 0, "high_volume_pct": 0, "medium_volume_pct": 0, "low_volume_pct": 100},
                "error": "No price data available for liquidity analysis"
            }
        
        # Calculate liquidity metrics using analytics engine
        liquidity_result = await analytics_engine.liquidity_analysis(price_data_dict)
        
        return {
            "overall_score": liquidity_result.get("overall_score", 7.8),
            "liquidation_time_days": liquidity_result.get("liquidation_time_days", "2-5"),
            "risk_level": liquidity_result.get("risk_level", "Medium"),
            "by_position": liquidity_result.get("by_position", {}),
            "volume_stats": liquidity_result.get("volume_stats", {}),
            "methodology": "Liquidity scoring based on trading volume and market capitalization"
        }
        
    except Exception as e:
        logger.error(f"Error in get_liquidity_metrics: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/stress-test")
async def run_stress_test(
    request: StressTestRequest,
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Run stress test on portfolio
    """
    try:
        # Actual DB positions (request-level tickers override)
        weights = await _load_portfolio_allocation(db)
        if not weights:
            return {
                "scenario": request.scenario,
                "max_drawdown": -0.20,
                "portfolio_impact": -0.17,
                "position_impacts": {},
                "recovery_time": 30,
                "error": "No portfolio positions found for stress testing"
            }
        
        # Fetch price data for stress testing
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=756)).strftime('%Y-%m-%d')  # 3 years for stress testing
        
        price_data_dict = {}
        for ticker in weights.keys():
            df = await data_service.fetch_historical_data(ticker, start, end)
            if df is not None and not df.empty:
                _assign_price(price_data_dict, ticker, df)
        
        if not price_data_dict:
            return {
                "scenario": request.scenario,
                "max_drawdown": -0.20,
                "portfolio_impact": -0.17,
                "position_impacts": {ticker: -0.20 for ticker in weights.keys()},
                "recovery_time": 30,
                "error": "No price data available for stress testing"
            }
        
        # Combine price data
        price_data = pd.DataFrame(price_data_dict)
        
        # Run stress test using analytics engine
        stress_result = await analytics_engine.stress_test(price_data, weights, request.scenario)
        
        return stress_result
        
    except Exception as e:
        logger.error(f"Error in run_stress_test: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/volatility-sizing")
async def get_volatility_sizing(
    model: str = Query(default="EWMA", description="Volatility model"),
    target_volatility: float = Query(default=0.15, gt=0, lt=1, description="Target volatility"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Get volatility-adjusted position sizing recommendations
    """
    try:
        # Actual DB positions
        weights = await _load_portfolio_allocation(db)
        if not weights:
            return {
                "current_weights": {},
                "recommended_weights": {},
                "trades": {},
                "target_volatility": target_volatility,
                "error": "No portfolio positions found for volatility sizing"
            }
        
        # Fetch price data for volatility sizing
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=252)).strftime('%Y-%m-%d')  # 1 year
        
        price_data_dict = {}
        for ticker in weights.keys():
            df = await data_service.fetch_historical_data(ticker, start, end)
            if df is not None and not df.empty:
                _assign_price(price_data_dict, ticker, df)
        
        if not price_data_dict:
            return {
                "current_weights": weights,
                "recommended_weights": weights,
                "trades": {ticker: {"shares_delta": 0, "amount": 0} for ticker in weights.keys()},
                "target_volatility": target_volatility,
                "error": "No price data available for volatility sizing"
            }
        
        # Combine price data
        price_data = pd.DataFrame(price_data_dict)
        
        # Calculate volatility sizing using analytics engine
        sizing_result = await analytics_engine.volatility_sizing(price_data, weights, model, target_volatility)
        
        return sizing_result
        
    except Exception as e:
        logger.error(f"Error in get_volatility_sizing: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/risk-score")
async def get_risk_score(
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Get overall portfolio risk score
    """
    try:
        # Actual DB positions
        weights = await _load_portfolio_allocation(db)
        if not weights:
            return {
                "overall_score": 25.0,
                "risk_level": "MEDIUM",
                "change": 0,
                "components": {"concentration": 15.0, "volatility": 15.0, "correlation": 10.0, "factor_risk": 20.0, "market_risk": 10.0},
                "alerts": ["No portfolio positions found for risk scoring"],
                "error": "No portfolio positions found"
            }
        
        # Fetch price data for risk scoring
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=252)).strftime('%Y-%m-%d')  # 1 year
        
        price_data_dict = {}
        for ticker in weights.keys():
            df = await data_service.fetch_historical_data(ticker, start, end)
            if df is not None and not df.empty:
                _assign_price(price_data_dict, ticker, df)
        
        if not price_data_dict:
            return {
                "overall_score": 25.0,
                "risk_level": "MEDIUM",
                "change": 0,
                "components": {"concentration": 15.0, "volatility": 15.0, "correlation": 10.0, "factor_risk": 20.0, "market_risk": 10.0},
                "alerts": ["Insufficient data for comprehensive risk analysis"],
                "error": "No price data available for risk scoring"
            }
        
        # Combine price data
        price_data = pd.DataFrame(price_data_dict)
        
        # Calculate risk score using analytics engine
        risk_result = await analytics_engine.risk_scoring(price_data, weights)
        
        return risk_result
        
    except Exception as e:
        logger.error(f"Error in get_risk_score: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/summary")
async def get_analytics_summary(
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Get analytics summary for dashboard
    """
    try:
        # Actual DB positions
        weights = await _load_portfolio_allocation(db)
        if not weights:
            return {
                "portfolio_value": 100000.0,
                "total_positions": 0,
                "realized_volatility": 0.20,
                "forecast_volatility": 0.22,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "risk_score": 25.0,
                "risk_level": "MEDIUM",
                "liquidity_score": 5.0,
                "concentration_score": 15.0,
                "last_updated": datetime.utcnow().isoformat(),
                "error": "No portfolio positions found for summary"
            }
        
        # Fetch price data for summary
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=252)).strftime('%Y-%m-%d')  # 1 year
        
        price_data_dict = {}
        for ticker in weights.keys():
            df = await data_service.fetch_historical_data(ticker, start, end)
            if df is not None and not df.empty:
                _assign_price(price_data_dict, ticker, df)
        
        if not price_data_dict:
            return {
                "portfolio_value": 100000.0,
                "total_positions": 4,
                "realized_volatility": 0.20,
                "forecast_volatility": 0.22,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "risk_score": 25.0,
                "risk_level": "MEDIUM",
                "liquidity_score": 5.0,
                "concentration_score": 15.0,
                "last_updated": datetime.utcnow().isoformat(),
                "error": "No price data available for summary"
            }
        
        # Combine price data
        price_data = pd.DataFrame(price_data_dict)
        
        # Calculate portfolio metrics for summary
        metrics = await analytics_engine.calculate_portfolio_metrics(price_data, weights)
        concentration_result = await analytics_engine.concentration_analysis(weights)
        risk_result = await analytics_engine.risk_scoring(price_data, weights)
        
        # Generate summary
        summary = {
            "portfolio_value": 100000.0,  # Simplified portfolio value
            "total_positions": len(weights),
            "realized_volatility": metrics.get("annual_volatility", 0.20),
            "forecast_volatility": 0.22,  # Simplified forecast
            "sharpe_ratio": metrics.get("sharpe_ratio", 0),
            "max_drawdown": metrics.get("max_drawdown", 0),
            "risk_score": risk_result.get("overall_score", 25.0),
            "risk_level": risk_result.get("risk_level", "MEDIUM"),
            "liquidity_score": 7.8,  # Simplified liquidity score
            "concentration_score": concentration_result.get("herfindahl_index", 0.25) * 100,
            "last_updated": datetime.utcnow().isoformat(),
            "methodology": "Real-time portfolio analytics summary with multi-factor risk assessment"
        }
        
        return summary
        
    except Exception as e:
        logger.error(f"Error in get_analytics_summary: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
# ---------------------------------------------------------------------------
# Phase 1+2 endpoints: tear-sheet, risk contribution, optimizer, regime
# ---------------------------------------------------------------------------


async def _build_wide_returns(
    ticker_list: List[str],
    weights: Dict[str, float],
    start: str,
    end: str,
    data_service: DataService,
) -> tuple[pd.DataFrame, pd.Series]:
    """Wide per-asset returns frame + weighted portfolio return series."""
    price_data_dict: Dict[str, pd.Series] = {}
    for ticker in ticker_list:
        df = await data_service.fetch_historical_data(ticker, start, end)
        if df is not None and not df.empty:
            _assign_price(price_data_dict, ticker, df)
    if not price_data_dict:
        raise ValueError("No price data available for the requested window")
    prices = pd.DataFrame(price_data_dict).dropna(how="all")
    returns_df = prices.pct_change().dropna(how="all")
    portfolio_returns = (returns_df.fillna(0.0) * pd.Series(weights)).sum(axis=1)
    return returns_df, portfolio_returns


@router.get("/tear-sheet")
async def get_tear_sheet(
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers"),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    benchmark: BenchmarkService = Depends(get_benchmark_service),
) -> Dict:
    """
    Pro-style performance tear-sheet for the real holdings vs NIFTY.
    Metrics via quantstats; every metric degrades to null independently.
    """
    import quantstats as qs

    try:
        if not end:
            end = datetime.now().strftime("%Y-%m-%d")
        if not start:
            start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        try:
            ticker_list, weights = await resolve_allocation(tickers, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

        returns_df, port_ret = await _build_wide_returns(ticker_list, weights, start, end, data_service)

        bench_ret = await benchmark.get_returns(start=start, end=end, days=756)

        metrics = {
            "total_return": _q(qs.stats.comp, port_ret),
            "cagr": _q(qs.stats.cagr, port_ret),
            "sharpe": _q(qs.stats.sharpe, port_ret, rf=0.02),
            "sortino": _q(qs.stats.sortino, port_ret, rf=0.02),
            "calmar": _q(qs.stats.calmar, port_ret),
            "omega": _q(qs.stats.omega, port_ret),
            "tail_ratio": _q(qs.stats.tail_ratio, port_ret),
            "volatility": _q(qs.stats.volatility, port_ret),
            "max_drawdown": _q(qs.stats.max_drawdown, port_ret),
            "skew": _q(qs.stats.skew, port_ret),
            "kurtosis": _q(qs.stats.kurtosis, port_ret),
        }

        relative: Dict[str, Any] = {}
        if bench_ret is not None and len(bench_ret) > 20:
            common = port_ret.index.intersection(bench_ret.index)
            p, b = port_ret.loc[common], bench_ret.loc[common]
            var_b = float(b.var())
            beta = float(p.cov(b) / var_b) if var_b > 0 else None
            alpha_ann = float((p.mean() - beta * b.mean()) * 252) if beta is not None else None
            relative = {
                "beta_vs_nifty": round(beta, 4) if beta is not None else None,
                "alpha_annualized": round(alpha_ann, 4) if alpha_ann is not None else None,
                "benchmark_sharpe": _q(qs.stats.sharpe, b, rf=0.02),
                "benchmark_volatility": _q(qs.stats.volatility, b),
                "benchmark_max_drawdown": _q(qs.stats.max_drawdown, b),
                "benchmark_total_return": _q(qs.stats.comp, b),
            }

        monthly: Dict[str, Dict[str, float]] = {}
        try:
            mdf = qs.stats.monthly_returns(port_ret)
            monthly = {
                str(year): {str(m): round(float(v), 6) for m, v in row.items() if pd.notna(v)}
                for year, row in mdf.iterrows()
            }
        except Exception as e:  # noqa: BLE001
            logger.debug(f"monthly_returns unavailable: {e}")

        underwater = []
        try:
            dd = qs.stats.to_drawdown_series(port_ret)
            for ts, val in list(dd.items())[-250:]:
                underwater.append({"date": str(ts)[:10], "drawdown": round(float(val), 6)})
        except Exception as e:  # noqa: BLE001
            logger.debug(f"drawdown series unavailable: {e}")

        return {
            "window": {"start": start, "end": end},
            "holdings": weights,
            "metrics": metrics,
            "relative_vs_nifty": relative,
            "monthly_returns": monthly,
            "underwater": underwater,
            "methodology": "quantstats metric suite over cached OHLCV adj-close returns",
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error building tear-sheet: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/risk-contribution")
async def get_risk_contribution(
    tickers: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
) -> Dict:
    """
    Euler decomposition of portfolio risk per position.

    volatility model : RC_i = w_i * (Sigma w)_i / sigma_p   (exact, analytic)
    cvar model       : mean asset loss on the portfolio's worst-5% days,
                       scaled by weight and normalized to 100%.
    """
    try:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        try:
            ticker_list, weights = await resolve_allocation(tickers, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

        returns_df, port_ret = await _build_wide_returns(ticker_list, weights, start, end, data_service)
        assets = list(returns_df.columns)
        w = np.array([weights.get(a, 0.0) for a in assets])

        cov = returns_df.cov() * 252
        sigma_p = float(np.sqrt(max(0.0, w @ cov.values @ w)))
        vol_rc = {}
        if sigma_p > 0:
            mrc = cov.values @ w
            contrib = w * mrc / sigma_p
            contrib = contrib / contrib.sum()
            vol_rc = {a: round(float(c), 6) for a, c in zip(assets, contrib)}

        var_95 = float(np.percentile(port_ret, 5))
        tail = port_ret <= var_95
        cvar_rc = {}
        if tail.any():
            comp = []
            for a in assets:
                comp_es = float(returns_df.loc[tail, a].fillna(0.0).mean()) * w[assets.index(a)]
                comp.append(comp_es)
            total = sum(abs(c) for c in comp)
            # comp values are negative (tail-day losses); normalize to positive loss-shares
            cvar_rc = {a: round(float(-c) / total, 6) for a, c in zip(assets, comp)} if total > 0 else {}

        sector_rollup: Dict[str, Dict[str, float]] = {"volatility": {}, "cvar": {}}
        result = await db.execute(select(PortfolioPosition))
        sector_map = {p.ticker: (p.sector or "Unknown") for p in result.scalars().all()}
        if sector_map:
            for model_name, contribs in (("volatility", vol_rc), ("cvar", cvar_rc)):
                roll: Dict[str, float] = {}
                for a, c in contribs.items():
                    roll[sector_map.get(a, "Unknown")] = round(
                        roll.get(sector_map.get(a, "Unknown"), 0.0) + c, 6
                    )
                sector_rollup[model_name] = roll

        return {
            "window": {"start": start, "end": end},
            "positions": {
                "volatility": vol_rc,
                "cvar_tail": cvar_rc,
            },
            "sector_rollup": sector_rollup,
            "portfolio_volatility_annualized": round(sigma_p, 4),
            "portfolio_var_95_daily": round(var_95, 6),
            "portfolio_cvar_95_daily": round(float(port_ret[tail].mean()), 6) if tail.any() else None,
            "methodology": "Euler decomposition (volatility) + historical tail attribution (CVaR)",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in risk-contribution: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/optimize/run")
async def run_optimization(
    body: Dict = Body(default={}),
    tickers: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
) -> Dict:
    """
    Optimize allocations across the user's universe (default: current holdings).

    Strategies: hrp | min_vol | max_sharpe | min_cvar
    (numpy/cvxpy implementations - see services/optimization_service.py header
    for why riskfolio/pypfopt are bypassed on this dependency stack).
    """
    try:
        strategy = str(body.get("strategy", "hrp")).lower()
        rf = float(body.get("risk_free_rate", 0.02))

        requested = body.get("tickers") or tickers
        requested_csv = ",".join(requested) if isinstance(requested, list) else requested
        try:
            ticker_list, current_weights = await resolve_allocation(requested_csv, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        returns_df, _ = await _build_wide_returns(ticker_list, current_weights, start, end, data_service)

        result = optimize(returns_df, strategy=strategy, risk_free_rate=rf)

        recommended = result["weights"]
        trades = {}
        for t in ticker_list:
            cur = float(current_weights.get(t, 0.0))
            rec = float(recommended.get(t, 0.0))
            if abs(rec - cur) > 1e-6:
                trades[t] = {
                    "current_weight": round(cur, 4),
                    "recommended_weight": round(rec, 4),
                    "weight_delta": round(rec - cur, 4),
                }

        return {
            **result,
            "universe": ticker_list,
            "current_weights": {t: round(float(current_weights.get(t, 0.0)), 4) for t in ticker_list},
            "trades_required": dict(sorted(trades.items(), key=lambda kv: abs(kv[1]["weight_delta"]), reverse=True)),
            "disclaimer": "Educational optimization output; not investment advice.",
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in optimize/run: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/regime")
async def get_regime(
    lookback_days: int = Query(default=1100, ge=300, le=3000),
    with_portfolio: bool = Query(default=True, description="Include conditional portfolio stats"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    benchmark: BenchmarkService = Depends(get_benchmark_service),
) -> Dict:
    """
    HMM market-regime classification (calm/volatile/crisis) over NIFTY returns,
    plus the portfolio's historical behavior inside the CURRENT regime.
    """
    try:
        port_ret: Optional[pd.Series] = None
        if with_portfolio:
            try:
                _, weights = await resolve_allocation(None, db)
                end = datetime.now().strftime("%Y-%m-%d")
                start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
                _, port_ret = await _build_wide_returns(list(weights.keys()), weights, start, end, data_service)
            except (ValueError, HTTPException):
                port_ret = None  # regime itself still works without holdings

        result = await detect_regime(db, lookback_days=lookback_days, portfolio_returns=port_ret)
        return result
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Error detecting regime: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/monte-carlo")
async def run_monte_carlo(
    body: Dict = Body(...),
    tickers: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
) -> Dict:
    """
    Goal-probability simulation over the user's portfolio return history.

    body: {
      target_value: float (required),
      horizon_years: int (required, 1-40),
      initial_value: float (optional; defaults to current DB market value),
      method: "gbm" | "student_t" | "bootstrap" (default gbm),
      num_paths: int (default 2000, cap 20000),
      seed: int (optional, for reproducibility)
    }
    """
    try:
        try:
            target_value = float(body["target_value"])
            horizon_years = int(body["horizon_years"])
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(
                status_code=422,
                detail="target_value and horizon_years are required numbers",
            ) from e

        initial_value = body.get("initial_value")
        if initial_value is not None:
            initial_value = float(initial_value)
        else:
            result = await db.execute(select(PortfolioPosition))
            positions = result.scalars().all()
            initial_value = sum(float(p.market_value or 0.0) for p in positions)
            if initial_value <= 0:
                raise HTTPException(
                    status_code=404,
                    detail="Portfolio has no market value yet; pass initial_value explicitly",
                )

        try:
            ticker_list, weights = await resolve_allocation(tickers, db)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        _, port_ret = await _build_wide_returns(ticker_list, weights, start, end, data_service)

        return simulate_goal(
            portfolio_returns=port_ret,
            initial_value=initial_value,
            target_value=target_value,
            horizon_years=horizon_years,
            method=str(body.get("method", "gbm")).lower(),
            num_paths=int(body.get("num_paths", 2000)),
            seed=body.get("seed"),
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error in monte-carlo: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
