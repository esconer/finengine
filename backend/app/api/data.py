"""
Data API endpoints for market data fetching and management
"""

from datetime import datetime, timedelta
from typing import List, Optional
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db_session
from app.services.data_service import GlobalDataService, DataService
from app.services.cache_service import GlobalCacheService, CacheService
from app.models.schemas import (
    StockDataResponse, StockQuoteResponse, BatchStockDataRequest, BatchStockDataResponse,
    ValidateTickerRequest, ValidateTickerResponse, APIConfigResponse
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


from app.models.schemas import (
    StockDataResponse, StockTimeseriesResponse, StockQuoteResponse, BatchStockDataRequest, BatchStockDataResponse,
    ValidateTickerRequest, ValidateTickerResponse, APIConfigResponse
)

@router.get("/{ticker}", response_model=StockTimeseriesResponse)
async def get_stock_data(
    ticker: str,
    start: Optional[str] = Query(default=None, description="Start date (YYYY-MM-DD)"),
    end: Optional[str] = Query(default=None, description="End date (YYYY-MM-DD)"),
    force_refresh: bool = Query(default=False, description="Force refresh from yfinance"),
    data_service: DataService = Depends(get_data_service),
    cache_service: CacheService = Depends(get_cache_service)
) -> StockTimeseriesResponse:
    """
    Get historical OHLCV data for a ticker
    
    - **ticker**: Stock ticker symbol
    - **start**: Start date (YYYY-MM-DD), defaults to 1 year ago
    - **end**: End date (YYYY-MM-DD), defaults to today
    - **force_refresh**: Force refresh from yfinance instead of using cache
    """
    try:
        # Set default dates
        if not end:
            end = datetime.now().strftime('%Y-%m-%d')
        if not start:
            start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        
        # Fetch data
        df = await data_service.fetch_historical_data(ticker, start, end, force_refresh)
        
        if df is None or df.empty:
            raise HTTPException(
                status_code=404,
                detail=f"No data found for ticker {ticker}"
            )
        
        # Determine if data is from cache
        from_cache = not force_refresh and await data_service._get_cached_data(ticker, start, end) is not None
        
        # Get ticker metadata for response
        quote_data = await data_service.fetch_quote(ticker)
        metadata = {}
        if quote_data:
            metadata = {
                "sector": quote_data.get("sector"),
                "industry": quote_data.get("industry")
            }
        
        # Convert DataFrame to list of stock data points
        stock_data = []
        for _, row in df.iterrows():
            stock_data.append(StockDataResponse(
                ticker=ticker.upper(),
                date=row['date'].strftime('%Y-%m-%d'),
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                adj_close=float(row['adj_close']),
                volume=int(row['volume'])
            ))
        
        return StockTimeseriesResponse(
            ticker=ticker.upper(),
            data=stock_data,
            source="yfinance",
            from_cache=from_cache,
            metadata=metadata
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_stock_data for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/quote/{ticker}", response_model=StockQuoteResponse)
async def get_stock_quote(
    ticker: str,
    data_service: DataService = Depends(get_data_service)
) -> StockQuoteResponse:
    """
    Get latest quote and metadata for a ticker
    """
    try:
        quote_data = await data_service.fetch_quote(ticker)
        
        if quote_data is None:
            raise HTTPException(
                status_code=404,
                detail=f"No quote data found for ticker {ticker}"
            )
        
        return StockQuoteResponse(**quote_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_stock_quote for {ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/batch", response_model=BatchStockDataResponse)
async def get_batch_stock_data(
    request: BatchStockDataRequest,
    data_service: DataService = Depends(get_data_service)
) -> BatchStockDataResponse:
    """
    Get OHLCV data for multiple tickers efficiently
    """
    try:
        # Set default dates
        end = request.end or datetime.now().strftime('%Y-%m-%d')
        start = request.start or (datetime.now() - timedelta(days=252)).strftime('%Y-%m-%d')
        
        # Convert tickers to uppercase
        tickers = [ticker.upper() for ticker in request.tickers]
        
        # Fetch batch data
        results = await data_service.fetch_ohlcv_batch(tickers, days=252)
        
        # Convert DataFrames to response format
        data_dict = {}
        for ticker, df in results["data"].items():
            if not df.empty:
                stock_responses = []
                for _, row in df.iterrows():
                    stock_responses.append(StockDataResponse(
                        ticker=ticker,
                        date=row['date'],
                        open=float(row['open']),
                        high=float(row['high']),
                        low=float(row['low']),
                        close=float(row['close']),
                        adj_close=float(row['adj_close']),
                        volume=int(row['volume']),
                        source_used='yfinance',
                        fetch_status='fresh'
                    ))
                data_dict[ticker] = stock_responses
        
        return BatchStockDataResponse(
            data=data_dict,
            failed_tickers=results["failed_tickers"]
        )
        
    except Exception as e:
        logger.error(f"Error in get_batch_stock_data: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/validate", response_model=ValidateTickerResponse)
async def validate_ticker(
    request: ValidateTickerRequest,
    data_service: DataService = Depends(get_data_service)
) -> ValidateTickerResponse:
    """
    Validate if a ticker exists and has data
    """
    try:
        is_valid = await data_service.validate_ticker(request.ticker)
        
        return ValidateTickerResponse(
            valid=is_valid,
            message=f"Ticker {request.ticker} is valid" if is_valid else f"Ticker {request.ticker} not found"
        )
        
    except Exception as e:
        logger.error(f"Error validating ticker {request.ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/refresh")
async def refresh_ticker_data(
    tickers: List[str],
    data_service: DataService = Depends(get_data_service)
):
    """
    Force refresh data for specified tickers
    """
    try:
        refreshed_count = 0
        failed_count = 0
        
        # Set date range (last 1 year)
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=252)).strftime('%Y-%m-%d')
        
        for ticker in tickers:
            try:
                df = await data_service.fetch_historical_data(ticker, start, end, force_refresh=True)
                if df is not None:
                    refreshed_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                logger.error(f"Error refreshing {ticker}: {e}")
                failed_count += 1
        
        return {
            "refreshed": refreshed_count,
            "failed": failed_count,
            "message": f"Refreshed {refreshed_count} tickers successfully"
        }
        
    except Exception as e:
        logger.error(f"Error in refresh_ticker_data: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/config", response_model=APIConfigResponse)
async def get_api_config(
    cache_service: CacheService = Depends(get_cache_service)
) -> APIConfigResponse:
    """
    Get API configuration and cache settings
    """
    try:
        # Get cache stats
        cache_stats = await cache_service.get_cache_stats()
        
        return APIConfigResponse(
            primary_source="yfinance",
            cache_ttl_minutes=cache_stats.get("ttl_minutes", 60),
            enable_cache=True
        )
        
    except Exception as e:
        logger.error(f"Error getting API config: {e}")
        # Return default config on error
        return APIConfigResponse(
            primary_source="yfinance",
            cache_ttl_minutes=60,
            enable_cache=True
        )


@router.put("/config")
async def update_api_config(
    cache_ttl_minutes: Optional[int] = Query(None, ge=1, le=1440),
    enable_cache: Optional[bool] = Query(None),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Update API configuration (placeholder for future implementation)
    """
    # This is a placeholder endpoint - in a real implementation,
    # you would update settings and persist them
    
    updated_settings = {}
    
    if cache_ttl_minutes is not None:
        updated_settings["cache_ttl_minutes"] = cache_ttl_minutes
    
    if enable_cache is not None:
        updated_settings["enable_cache"] = enable_cache
    
    return {
        "updated": True,
        "settings": updated_settings,
        "message": "Configuration updated successfully"
    }