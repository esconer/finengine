"""
Data API endpoints for market data fetching and management
"""

from datetime import date, datetime, timedelta
from typing import Any, List, Optional
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.database import get_db_session
from app.models.database import AnalyticsCache, AppSetting, StockTimeseries
from app.services.data_service import GlobalDataService, DataService, canonical_ticker
from app.services.cache_service import (
    GlobalCacheService,
    CacheService,
    clear_market_data_cache,
    advance_cache_generation,
    clear_service_memos,
    ProviderError,
)
from app.services.source_preference_service import (
    PREFERENCE_KEY,
    get_primary_source,
    get_setting,
    source_order_for,
    validate_source,
)
from app.services.indicators_service import IndicatorsService, SUPPORTED_INDICATORS, StaleMarketDataError
from app.services.company_data_service import get_company_data_service
from app.models.schemas import (
    StockDataResponse, StockQuoteResponse, BatchStockDataRequest, BatchStockDataResponse,
    ValidateTickerRequest, ValidateTickerResponse, APIConfigResponse, StockTimeseriesResponse
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Create router
router = APIRouter()

_MAX_COLLECTION_SIZE = 50
_MAX_INDICATORS = 20
_MAX_DATE_RANGE_DAYS = 3650


def _coerce_date(value: Any, field_name: str) -> Optional[date]:
    if value is None:
        return None
    if not isinstance(value, (str, date, datetime)):
        raise HTTPException(status_code=422, detail=f"{field_name} must be YYYY-MM-DD")
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} must be YYYY-MM-DD") from exc


def _date_window(start: Any, end: Any, default_days: int) -> tuple[str, str]:
    end_date = _coerce_date(end, "end") or datetime.now().date()
    start_date = _coerce_date(start, "start") or (end_date - timedelta(days=default_days))
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="start must be on or before end")
    if (end_date - start_date).days > _MAX_DATE_RANGE_DAYS:
        raise HTTPException(status_code=422, detail=f"date range must be at most {_MAX_DATE_RANGE_DAYS} days")
    return start_date.isoformat(), end_date.isoformat()


def _bounded_tickers(values: Any, *, field_name: str = "tickers", dedupe: bool = True) -> List[str]:
    if not isinstance(values, list) or not values:
        raise HTTPException(status_code=422, detail=f"{field_name} must contain at least one ticker")
    if len(values) > _MAX_COLLECTION_SIZE:
        raise HTTPException(status_code=422, detail=f"At most {_MAX_COLLECTION_SIZE} {field_name} are allowed")
    output: List[str] = []
    seen = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(status_code=422, detail=f"{field_name} entries must be non-empty strings")
        ticker = value.strip().upper()
        if dedupe and ticker in seen:
            continue
        seen.add(ticker)
        output.append(ticker)
    return output


def _raise_provider_http_error(exc: ProviderError) -> None:
    """Translate the shared provider taxonomy without leaking upstream text."""
    status_code = int(getattr(exc, "status_code", 502) or 502)
    if not 400 <= status_code <= 599:
        status_code = 502
    kind = str(getattr(exc, "kind", "provider_error"))
    detail = {
        "rate_limit": "Upstream data service rate limit",
        "auth": "Upstream data service unavailable",
        "unknown_ticker": "Requested ticker was not found",
        "invalid_input": "Invalid market-data request",
    }.get(kind, "Upstream data service unavailable")
    raise HTTPException(status_code=status_code, detail=detail) from exc


async def _frame_source_for_window(df: Any, canonical: str, db: AsyncSession) -> str:
    """Derive provenance from rows actually returned, not a newer out-of-window row."""
    attrs = getattr(df, "attrs", {}) or {}
    if isinstance(attrs.get("source"), str) and attrs["source"].strip():
        return attrs["source"].strip()
    raw_source = getattr(df, "_source", None)
    if isinstance(raw_source, str) and raw_source.strip():
        return raw_source.strip()
    try:
        source_column = df.get("source_used") if hasattr(df, "get") else None
        if source_column is not None:
            sources = {
                str(value).strip()
                for value in source_column.dropna().tolist()
                if str(value).strip()
            }
            if len(sources) == 1:
                return next(iter(sources))
            if len(sources) > 1:
                return "mixed"
    except Exception:
        pass

    # A normalized vendor frame may not carry source_used.  Restrict the
    # fallback lookup to the returned date span, never the latest row globally.
    try:
        dates = None
        if hasattr(df, "columns") and "date" in df.columns:
            dates = pd.to_datetime(df["date"], errors="coerce")
        elif isinstance(getattr(df, "index", None), pd.DatetimeIndex):
            dates = pd.Series(pd.to_datetime(df.index, errors="coerce"), index=df.index)
        if dates is not None:
            valid_dates = dates.dropna()
            if not valid_dates.empty:
                start = valid_dates.min()
                end = valid_dates.max()
                result = await db.execute(
                    select(StockTimeseries.source_used)
                    .where(
                        StockTimeseries.ticker == canonical,
                        StockTimeseries.date >= start.to_pydatetime(),
                        StockTimeseries.date <= end.to_pydatetime(),
                    )
                    .order_by(StockTimeseries.date)
                )
                sources = {
                    str(value).strip()
                    for value in result.scalars().all()
                    if value is not None and str(value).strip()
                }
                if len(sources) == 1:
                    return next(iter(sources))
                if len(sources) > 1:
                    return "mixed"
    except Exception:
        logger.debug("Stored source lookup unavailable")
    return "yfinance"


# Dependency injection
def get_data_service(db: AsyncSession = Depends(get_db_session)) -> DataService:
    """Get data service instance"""
    return GlobalDataService(db).get_service()


def get_cache_service(db: AsyncSession = Depends(get_db_session)) -> CacheService:
    """Get cache service instance"""
    return GlobalCacheService(db).get_service()


def get_indicators_service(db: AsyncSession = Depends(get_db_session)) -> IndicatorsService:
    """Get technical indicators service instance"""
    return IndicatorsService(db)


@router.get("/indicators/{ticker}")
async def get_technical_indicators(
    ticker: str,
    indicators: Optional[str] = Query(
        default=None,
        description=f"Comma-separated indicator names. Supported: {', '.join(SUPPORTED_INDICATORS)}"
    ),
    lookback_days: int = Query(default=90, ge=5, le=750, description="Window of records to return"),
    end_date: Optional[date] = Query(default=None, description="End date (YYYY-MM-DD), defaults to today"),
    indicators_service: IndicatorsService = Depends(get_indicators_service)
):
    """
    Compute technical indicators (stockstats engine) on cached OHLCV data.

    Adapted from TauricResearch/TradingAgents dataflows (Apache-2.0).
    """
    try:
        if indicators is not None:
            requested = [i.strip() for i in indicators.split(",") if i.strip()]
            if not requested or len(requested) > _MAX_INDICATORS:
                raise HTTPException(status_code=422, detail="indicators must contain 1-20 names")
        else:
            requested = None
        end_iso = _coerce_date(end_date, "end_date")
        return await indicators_service.compute_window(
            ticker, requested, lookback_days=lookback_days,
            end_date=end_iso.isoformat() if end_iso else None,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid data request")
    except StaleMarketDataError:
        raise HTTPException(status_code=409, detail="Market data is stale")
    except HTTPException:
        raise
    except Exception:
        logger.error("Indicator request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/verified-snapshot/{ticker}")
async def get_verified_snapshot(
    ticker: str,
    look_back_days: int = Query(default=30, ge=5, le=30, description="Recent closes to include"),
    end_date: Optional[str] = Query(default=None, description="Snapshot date (YYYY-MM-DD)"),
    indicators_service: IndicatorsService = Depends(get_indicators_service)
):
    """
    Deterministic ground-truth snapshot: latest OHLCV row + core indicators +
    recent closes, computed from the shared cache (no estimates).
    Pattern adapted from TauricResearch/TradingAgents market_data_validator.
    """
    try:
        end_iso = _coerce_date(end_date, "end_date")
        return await indicators_service.verified_snapshot(
            ticker,
            end_date=end_iso.isoformat() if end_iso else None,
            look_back_days=look_back_days,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Resource not found")
    except StaleMarketDataError:
        raise HTTPException(status_code=409, detail="Market data is stale")
    except HTTPException:
        raise
    except Exception:
        logger.error("Verified snapshot request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/fundamentals/{ticker}")
async def get_fundamentals(
    ticker: str,
    db: AsyncSession = Depends(get_db_session),
):
    """
    Curated fundamentals snapshot.
    Vendor cascade honors the user's primary-source preference
    (bfinance <-> yfinance per setting; Alpha Vantage N/A for fundamentals).
    Field list adapted from TauricResearch/TradingAgents (Apache-2.0).
    """
    try:
        source_order = source_order_for(await get_primary_source(db))
        return await get_company_data_service().get_fundamentals(ticker, source_order=source_order)
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except ValueError:
        raise HTTPException(status_code=404, detail="Resource not found")
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Upstream data service unavailable")
    except HTTPException:
        raise
    except Exception:
        logger.error("Fundamentals request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/financials/{ticker}")
async def get_financial_statements(
    ticker: str,
    statement: str = Query(default="income", description="income | balance | cashflow"),
    freq: str = Query(default="quarterly", description="quarterly | annual"),
    db: AsyncSession = Depends(get_db_session),
):
    """
    Structured financial statements (income / balance sheet / cash flow).
    Pattern adapted from TauricResearch/TradingAgents (Apache-2.0).
    """
    try:
        source_order = source_order_for(await get_primary_source(db))
        return await get_company_data_service().get_financial_statements(
            ticker, statement=statement, freq=freq, source_order=source_order
        )
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid data request")
    except HTTPException:
        raise
    except Exception:
        logger.error("Financial statements request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/insider/{ticker}")
async def get_insider_transactions(ticker: str):
    """Recent insider transactions; empty list is a normal response."""
    try:
        records = await get_company_data_service().get_insider_transactions(ticker)
        return {"ticker": ticker.upper(), "count": len(records), "transactions": records}
    except HTTPException:
        raise
    except Exception:
        logger.error("Insider transactions request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/config", response_model=APIConfigResponse)
async def get_api_config(
    db: AsyncSession = Depends(get_db_session),
    cache_service: CacheService = Depends(get_cache_service)
) -> APIConfigResponse:
    """
    Get API configuration: user-selected primary data source and cache settings.

    Declared BEFORE the dynamic /{ticker} route - route order previously
    shadowed this path with a 404.
    """
    try:
        # Get cache stats
        cache_stats = await cache_service.get_cache_stats()
        primary_source = await get_primary_source(db)
        # Persisted overrides win over live cache-service defaults.
        ttl_raw = await get_setting(db, "cache_ttl_minutes")
        enable_raw = await get_setting(db, "enable_cache")
        try:
            cache_ttl = int(ttl_raw) if ttl_raw is not None else int(cache_stats.get("ttl_minutes", 60))
        except (TypeError, ValueError):
            cache_ttl = 60
        enable_cache = (enable_raw.lower() == "true") if enable_raw is not None else True

        return APIConfigResponse(
            primary_source=primary_source,
            cache_ttl_minutes=cache_ttl,
            enable_cache=enable_cache
        )

    except HTTPException:
        raise
    except Exception:
        logger.error("API config read failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/config")
async def update_api_config(
    primary_source: Optional[str] = Query(None, description="Primary data vendor: bfinance | yfinance"),
    cache_ttl_minutes: Optional[int] = Query(None, ge=1, le=1440),
    enable_cache: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db_session),
    cache_service: CacheService = Depends(get_cache_service)
):
    """
    Update API configuration.

    `primary_source` swaps the vendor cascade order per user preference:
        bfinance primary -> bfinance, yfinance, Alpha Vantage (always last)
        yfinance primary -> yfinance, bfinance, Alpha Vantage (always last)
    """
    # Direct unit calls may receive FastAPI's Query sentinel when a parameter
    # is omitted; normalize that sentinel before deciding whether anything was
    # requested.
    if not isinstance(primary_source, (str, type(None))):
        primary_source = None
    if not isinstance(cache_ttl_minutes, (int, type(None))):
        cache_ttl_minutes = None
    if not isinstance(enable_cache, (bool, type(None))):
        enable_cache = None

    if primary_source is None and cache_ttl_minutes is None and enable_cache is None:
        raise HTTPException(status_code=400, detail="No configuration parameters provided")

    committed = False
    try:
        validated_source = validate_source(primary_source) if primary_source is not None else None
        previous_source = None
        source_changed = False
        if validated_source is not None:
            previous_source = await get_setting(db, PREFERENCE_KEY)
            previous_normalized = (previous_source or "bfinance").strip().lower()
            source_changed = previous_normalized != validated_source
        statements = []
        if validated_source is not None:
            stmt = sqlite_insert(AppSetting.__table__).values(
                key=PREFERENCE_KEY, value=validated_source,
            )
            statements.append(stmt.on_conflict_do_update(
                index_elements=[AppSetting.key],
                set_={"value": stmt.excluded.value, "updated_on": stmt.excluded.updated_on},
            ))
        if cache_ttl_minutes is not None:
            stmt = sqlite_insert(AppSetting.__table__).values(
                key="cache_ttl_minutes", value=str(cache_ttl_minutes),
            )
            statements.append(stmt.on_conflict_do_update(
                index_elements=[AppSetting.key],
                set_={"value": stmt.excluded.value},
            ))
        if enable_cache is not None:
            stmt = sqlite_insert(AppSetting.__table__).values(
                key="enable_cache", value=str(bool(enable_cache)),
            )
            statements.append(stmt.on_conflict_do_update(
                index_elements=[AppSetting.key],
                set_={"value": stmt.excluded.value},
            ))

        for statement in statements:
            await db.execute(statement)
        if source_changed:
            # Source identity is not part of StockTimeseries' natural key.
            # Fence in-flight work and remove rows/derived analytics under the
            # old cascade in this same transaction as the preference update.
            await db.execute(delete(StockTimeseries))
            await db.execute(delete(AnalyticsCache))
            advance_cache_generation("primary source preference changed")
            clear_service_memos()
        # One API-owned commit covers every setting.  The B-owned helper still
        # commits for standalone callers; it is intentionally not called here.
        await db.commit()
        committed = True
        if source_changed:
            # Repeat the process-local reset after durability so a fetch that
            # began during the settings transaction cannot leave a warm memo.
            clear_service_memos()
        expire_all = getattr(db, "expire_all", None)
        if callable(expire_all):
            try:
                expire_all()
            except Exception:
                logger.warning("API configuration cache refresh failed")

        settings = {}
        if validated_source is not None:
            settings["primary_source"] = validated_source
        if cache_ttl_minutes is not None:
            settings["cache_ttl_minutes"] = cache_ttl_minutes
        if enable_cache is not None:
            settings["enable_cache"] = bool(enable_cache)
        return {
            "updated": True,
            "settings": settings,
            "message": "Configuration updated successfully",
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsupported primary data source") from exc
    except HTTPException:
        raise
    except Exception as exc:
        if not committed:
            await db.rollback()
        logger.error("API configuration update failed")
        detail = "Configuration committed, but the response could not be prepared" if committed else "Configuration update failed"
        raise HTTPException(status_code=500, detail=detail) from exc


@router.post("/cache/clear")
async def clear_cache(
    db: AsyncSession = Depends(get_db_session)
):
    """
    Purge all cached market data (timeseries, analytics, fetch logs, NSE
    microstructure tables) plus in-process memo caches so fresh data is
    pulled from the configured vendor chain.

    Portfolio holdings (tickers, quantities, avg buy prices, weights) are
    user-owned truth and are never touched.
    """
    try:
        from app.api.analytics import clear_tails_cache
        result = await clear_market_data_cache(db)
        clear_tails_cache()
        return result
    except HTTPException:
        raise
    except Exception:
        logger.error("Market data cache clear failed")
        raise HTTPException(status_code=500, detail="Failed to clear cache")


@router.get("/{ticker}", response_model=StockTimeseriesResponse)
async def get_stock_data(
    ticker: str,
    start: Optional[date] = Query(default=None, description="Start date (YYYY-MM-DD)"),
    end: Optional[date] = Query(default=None, description="End date (YYYY-MM-DD)"),
    force_refresh: bool = Query(default=False, description="Force refresh from yfinance"),
    data_service: DataService = Depends(get_data_service),
    cache_service: CacheService = Depends(get_cache_service),
    db: AsyncSession = Depends(get_db_session)
) -> StockTimeseriesResponse:
    """
    Get historical OHLCV data for a ticker
    
    - **ticker**: Stock ticker symbol
    - **start**: Start date (YYYY-MM-DD), defaults to 1 year ago
    - **end**: End date (YYYY-MM-DD), defaults to today
    - **force_refresh**: Force refresh from yfinance instead of using cache
    """
    try:
        # Validate dates before probing cache or calling a vendor.
        start, end = _date_window(start, end, default_days=365)
        canonical = canonical_ticker(ticker)
        
        # Probe cache BEFORE fetch: fetch_historical_data stores fresh rows on a
        # vendor miss, so a post-fetch probe would mislabel vendor data as cached.
        cached_before = (
            None if force_refresh else await data_service._get_cached_data(canonical, start, end)
        )
        
        # Fetch data
        df = await data_service.fetch_historical_data(canonical, start, end, force_refresh)
        
        if df is None or df.empty:
            raise HTTPException(
                status_code=404,
                detail=f"No data found for ticker {ticker}"
            )
        
        from_cache = cached_before is not None and not cached_before.empty
        
        # Source of truth: derive from the frame actually returned.  Looking up
        # the latest row for the ticker can label an older requested window with
        # a newer source after a preference switch.
        source = await _frame_source_for_window(df, canonical, db)
        if source == "yfinance":
            frame_source = getattr(data_service, "_source_of_df", None)
            if callable(frame_source):
                candidate_source = frame_source(df)
                if isinstance(candidate_source, str) and candidate_source.strip():
                    source = candidate_source.strip()
        if not isinstance(source, str) or not source:
            source = "yfinance"
        
        # Get ticker metadata for response (skip None values - yfinance often
        # lacks sector/industry, and the schema forbids nulls here)
        quote_data = await data_service.fetch_quote(canonical)
        metadata = {}
        if quote_data:
            for meta_key in ("sector", "industry"):
                meta_val = quote_data.get(meta_key)
                if meta_val:
                    metadata[meta_key] = meta_val
        
        # Convert DataFrame to list of stock data points
        stock_data = []
        for _, row in df.iterrows():
            stock_data.append(StockDataResponse(
                ticker=canonical,
                date=row['date'].strftime('%Y-%m-%d'),
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                adj_close=float(row['adj_close']),
                volume=int(row['volume'])
            ))
        
        return StockTimeseriesResponse(
            ticker=canonical,
            data=stock_data,
            source=source,
            from_cache=from_cache,
            metadata=metadata
        )
        
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except HTTPException:
        raise
    except Exception:
        logger.error("Stock data request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


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
        
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except HTTPException:
        raise
    except Exception:
        logger.error("Stock quote request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/batch", response_model=BatchStockDataResponse)
async def get_batch_stock_data(
    request: BatchStockDataRequest,
    data_service: DataService = Depends(get_data_service)
) -> BatchStockDataResponse:
    """
    Get OHLCV data for multiple tickers efficiently
    """
    try:
        # Validate the entire request before vendor fan-out.
        start, end = _date_window(request.start, request.end, default_days=252)
        tickers = _bounded_tickers(request.tickers)
        
        # Fetch batch data
        results = await data_service.fetch_ohlcv_batch(
            tickers,
            start_date=start,
            end_date=end,
            force_refresh=request.force_refresh
        )
        
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
                        volume=int(row['volume'])
                    ))
                data_dict[ticker] = stock_responses
        
        return BatchStockDataResponse(
            data=data_dict,
            failed_tickers=results["failed_tickers"]
        )
        
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Batch stock data request failed")
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/validate", response_model=ValidateTickerResponse)
async def validate_ticker(
    request: ValidateTickerRequest,
    data_service: DataService = Depends(get_data_service)
) -> ValidateTickerResponse:
    """
    Validate if a ticker exists and has data
    """
    try:
        is_valid = await data_service.validate_ticker(request.ticker, strict_errors=True)
        
        return ValidateTickerResponse(
            valid=is_valid,
            message=f"Ticker {request.ticker} is valid" if is_valid else f"Ticker {request.ticker} not found"
        )
        
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except HTTPException:
        raise
    except Exception:
        logger.error("Ticker validation request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/refresh")
async def refresh_ticker_data(
    tickers: List[str],
    data_service: DataService = Depends(get_data_service)
):
    """
    Force refresh data for specified tickers
    """
    try:
        tickers = _bounded_tickers(tickers)
        refreshed_count = 0
        failed_count = 0
        
        # Set date range (last 1 year)
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=252)).strftime('%Y-%m-%d')
        
        for ticker in tickers:
            try:
                df = await data_service.fetch_historical_data(ticker, start, end, force_refresh=True)
                if df is not None and not getattr(df, "empty", False):
                    refreshed_count += 1
                else:
                    failed_count += 1
            except Exception:
                logger.error("Ticker refresh failed")
                failed_count += 1
        
        return {
            "refreshed": refreshed_count,
            "failed": failed_count,
            "message": f"Refreshed {refreshed_count} tickers successfully"
        }
        
    except HTTPException:
        raise
    except Exception:
        logger.error("Ticker refresh request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


