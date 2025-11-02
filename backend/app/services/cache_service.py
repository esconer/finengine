"""
Cache service for data storage and retrieval
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
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
                AnalyticsCache.expires_at > datetime.utcnow()
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
        """Set cached analytics data"""
        try:
            # Calculate expiration
            expires_at = datetime.utcnow() + timedelta(minutes=self.ttl_minutes)
            
            cache_entry = AnalyticsCache(
                ticker=ticker,
                metric_name=metric_name,
                metric_value=metric_value,
                calculation_date=calculation_date,
                expires_at=expires_at,
                model_params=model_params or {}
            )
            
            self.db.add(cache_entry)
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
        """Clear expired cache entries"""
        try:
            query = select(AnalyticsCache).where(
                AnalyticsCache.expires_at <= datetime.utcnow()
            )
            
            result = await self.db.execute(query)
            expired_entries = result.scalars().all()
            
            for entry in expired_entries:
                await self.db.delete(entry)
            
            await self.db.commit()
            
            count = len(expired_entries)
            if count > 0:
                logger.info(f"Cleared {count} expired cache entries")
            
            return count
            
        except Exception as e:
            logger.error(f"Error clearing expired cache: {e}")
            await self.db.rollback()
            return 0
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        try:
            # Total cache entries
            total_query = select(AnalyticsCache)
            total_result = await self.db.execute(total_query)
            total_entries = len(total_result.scalars().all())
            
            # Active cache entries
            active_query = select(AnalyticsCache).where(
                AnalyticsCache.expires_at > datetime.utcnow()
            )
            active_result = await self.db.execute(active_query)
            active_entries = len(active_result.scalars().all())
            
            # Expired cache entries
            expired_query = select(AnalyticsCache).where(
                AnalyticsCache.expires_at <= datetime.utcnow()
            )
            expired_result = await self.db.execute(expired_query)
            expired_entries = len(expired_result.scalars().all())
            
            # Recent fetch logs
            recent_logs_query = select(FetchLog).where(
                FetchLog.timestamp > datetime.utcnow() - timedelta(hours=24)
            )
            recent_logs_result = await self.db.execute(recent_logs_query)
            recent_logs = recent_logs_result.scalars().all()
            
            # Success rate
            successful_logs = [log for log in recent_logs if log.status == "success"]
            success_rate = len(successful_logs) / len(recent_logs) * 100 if recent_logs else 0
            
            return {
                "total_cache_entries": total_entries,
                "active_entries": active_entries,
                "expired_entries": expired_entries,
                "recent_fetch_attempts": len(recent_logs),
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