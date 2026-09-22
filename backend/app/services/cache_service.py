"""
Cache service for data storage and retrieval
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from app.models.database import AnalyticsCache, FetchLog
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class CacheService:
    """Cache service for managing data caching"""
    
    def __init__(self, db_session: AsyncSession, ttl_minutes: int = 60):
        self.db = db_session
        self.ttl_minutes = ttl_minutes
    
    async def get_cached_analytics(
        self, 
        ticker: str, 
        metric_name: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached analytics data"""
        try:
            query = select(AnalyticsCache).where(
                AnalyticsCache.ticker == ticker,
                AnalyticsCache.metric_name == metric_name,
                        AnalyticsCache.expires_at > datetime.now(timezone.utc).replace(tzinfo=None)
            )
            
            result = await self.db.execute(query)
            cache_entry = result.scalar_one_or_none()
            
            if cache_entry:
                logger.debug(f"Cache hit for {ticker}:{metric_name}")
                return {
                    "value": cache_entry.metric_value,
                    "calculation_date": cache_entry.calculation_date,
                    "model_params": cache_entry.model_params
                }
            
            logger.debug(f"Cache miss for {ticker}:{metric_name}")
            return None
            
        except Exception as e:
            logger.error(f"Error getting cached analytics: {e}")
            return None
    
    async def set_cached_analytics(
        self,
        ticker: str,
        metric_name: str,
        metric_value: float,
        calculation_date: datetime,
        model_params: Dict[str, Any] = None
    ) -> None:
        """Set cached analytics data (race-safe upsert on ticker+metric).

        Uses UNIQUE(ticker, metric_name) + ON CONFLICT DO UPDATE so two
        concurrent writers cannot leave duplicate rows (which made
        get_cached_analytics raise MultipleResultsFound -> perpetual miss).
        """
        try:
            # Calculate expiration
            expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=self.ttl_minutes)

            stmt = sqlite_insert(AnalyticsCache).values(
                ticker=ticker,
                metric_name=metric_name,
                metric_value=metric_value,
                calculation_date=calculation_date,
                expires_at=expires_at,
                model_params=model_params or {}
            ).on_conflict_do_update(
                index_elements=["ticker", "metric_name"],
                set_={
                    "metric_value": metric_value,
                    "calculation_date": calculation_date,
                    "expires_at": expires_at,
                    "model_params": model_params or {},
                },
            )
            await self.db.execute(stmt)
            await self.db.commit()
            
            logger.debug(f"Cached {ticker}:{metric_name} = {metric_value}")
            
        except Exception as e:
            logger.error(f"Error caching analytics: {e}")
            await self.db.rollback()
    
    async def log_fetch_attempt(
        self,
        ticker: str,
        status: str,
        primary_attempt: bool = True,
        fallback_attempt: bool = False,
        error_message: str = None,
        source_used: str = "yfinance"
    ) -> None:
        """Log data fetch attempt"""
        try:
            fetch_log = FetchLog(
                ticker=ticker,
                status=status,
                primary_attempt=primary_attempt,
                fallback_attempt=fallback_attempt,
                error_message=error_message,
                source_used=source_used
            )
            
            self.db.add(fetch_log)
            await self.db.commit()
            
        except Exception as e:
            logger.error(f"Error logging fetch attempt: {e}")
            await self.db.rollback()
    
    async def clear_expired_cache(self) -> int:
        """Clear expired cache entries with a single set-based DELETE."""
        try:
            result = await self.db.execute(
                delete(AnalyticsCache).where(
                        AnalyticsCache.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None)
                )
            )
            await self.db.commit()
            
            count = result.rowcount or 0
            if count > 0:
                logger.info(f"Cleared {count} expired cache entries")
            
            return count
            
        except Exception as e:
            logger.error(f"Error clearing expired cache: {e}")
            await self.db.rollback()
            return 0
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics (COUNT aggregates; never materializes rows)."""
        try:
            total_entries = (
                await self.db.execute(select(func.count()).select_from(AnalyticsCache))
            ).scalar() or 0
            active_entries = (
                await self.db.execute(
                    select(func.count()).select_from(AnalyticsCache).where(
                AnalyticsCache.expires_at > datetime.now(timezone.utc).replace(tzinfo=None)
                    )
                )
            ).scalar() or 0
            expired_entries = (
                await self.db.execute(
                    select(func.count()).select_from(AnalyticsCache).where(
                    AnalyticsCache.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None)
                    )
                )
            ).scalar() or 0
            
            recent_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
            recent_total = (
                await self.db.execute(
                    select(func.count()).select_from(FetchLog).where(
                        FetchLog.timestamp > recent_cutoff
                    )
                )
            ).scalar() or 0
            recent_success = (
                await self.db.execute(
                    select(func.count()).select_from(FetchLog).where(
                        FetchLog.timestamp > recent_cutoff,
                        FetchLog.status == "success",
                    )
                )
            ).scalar() or 0
            success_rate = (recent_success / recent_total * 100) if recent_total else 0
            
            return {
                "total_cache_entries": total_entries,
                "active_entries": active_entries,
                "expired_entries": expired_entries,
                "recent_fetch_attempts": recent_total,
                "success_rate_24h": round(success_rate, 2),
                "ttl_minutes": self.ttl_minutes
            }
            
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return {}


# Global cache service instance
class GlobalCacheService:
    """Global cache service for dependency injection"""
    
    def __init__(self, db_session: AsyncSession):
        self._cache_service = CacheService(db_session)
    
    def get_service(self) -> CacheService:
        return self._cache_service


# ---------------------------------------------------------------- cache purge

async def clear_market_data_cache(db: AsyncSession) -> Dict[str, Any]:
    """Wipe every cached market-data store so fresh data is pulled on next use.

    Deletes SQLite cache tables (timeseries, analytics, fetch logs, NSE
    microstructure) and resets in-process memo caches. User-owned portfolio
    truth (`portfolio_positions`: tickers, quantities, avg buy prices,
    weights) is NEVER touched.

    Returns per-store cleared row counts.
    """
    from app.models.database import (
        StockTimeseries, AnalyticsCache, FetchLog,
        NSEBhavcopy, NSEInstitutionalFlow, NSEBulkBlockDeal, NSEShareholdingPattern,
    )
    from app.services.data_service import DataService
    from app.services.screener_service import ScreenerService
    from app.services.currency_service import get_currency_service
    from sqlalchemy import func

    cleared: Dict[str, Any] = {}
    total = 0

    table_stores = {
        "stock_timeseries": StockTimeseries,
        "analytics_cache": AnalyticsCache,
        "fetch_logs": FetchLog,
        "nse_bhavcopy": NSEBhavcopy,
        "nse_institutional_flows": NSEInstitutionalFlow,
        "nse_bulk_block_deals": NSEBulkBlockDeal,
        "nse_shareholding_patterns": NSEShareholdingPattern,
    }

    try:
        for name, model in table_stores.items():
            count_result = await db.execute(select(func.count()).select_from(model))
            count = count_result.scalar() or 0
            await db.execute(delete(model))
            cleared[name] = count
            total += count

        await db.commit()
    except Exception as e:
        logger.error(f"Error clearing market data cache tables: {e}")
        await db.rollback()
        raise

    # In-process memo caches (would otherwise outlive the DB wipe)
    in_memory_reset = []
    try:
        DataService._in_memory_df_cache.clear()
        if hasattr(DataService, "_quote_memo"):
            DataService._quote_memo.clear()
            in_memory_reset.append("data_service_quotes")
        in_memory_reset.append("data_service_frames")
    except Exception as e:
        logger.warning(f"Could not reset data service in-memory cache: {e}")
    try:
        ScreenerService._cache.clear()
        in_memory_reset.append("screener_results")
    except Exception as e:
        logger.warning(f"Could not reset screener cache: {e}")
    try:
        currency = get_currency_service()
        currency._exchange_rates.clear()
        currency._last_updated = None
        in_memory_reset.append("fx_rates")
    except Exception as e:
        logger.warning(f"Could not reset currency cache: {e}")

    cleared["in_memory_caches"] = len(in_memory_reset)
    logger.info(f"Market data cache cleared: {total} rows purged; portfolio positions preserved")

    return {
        "cleared": cleared,
        "total_rows_cleared": total,
        "portfolio_preserved": True,
    }