"""
Cache service for data storage and retrieval
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from threading import Lock
from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from app.models.database import AnalyticsCache, AppSetting, FetchLog
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


# --------------------------------------------------------------------------------------
# Shared cache/runtime state
# --------------------------------------------------------------------------------------
# These values are process-local by design.  SQLite remains the durable cache; the
# generation is the fencing token for work that started before a purge.  A fetch that
# captured generation N must not write after a purge has advanced the token to N+1.
_CACHE_GENERATION = 0
_GENERATION_LOCK = Lock()
_RUNTIME_CONFIG_FINGERPRINT: Optional[str] = None


def _safe_provider_message(message: Any) -> str:
    text = str(message or "")
    text = re.sub(r"(?i)(apikey|api_key|key)=([^&\s]+)", r"\1=<REDACTED>", text)
    return text[:240]


class ProviderError(Exception):
    """Safe, typed provider failure shared by market-data service seams.

    ``message`` is intentionally a short operator-safe string.  Callers must not
    attach request URLs, query parameters, API keys, or raw upstream exception text.
    """

    kind = "provider_error"
    retryable = False
    status_code = 502

    def __init__(
        self,
        message: str,
        *,
        provider: str = "provider",
        status_code: Optional[int] = None,
        retryable: Optional[bool] = None,
    ) -> None:
        self.provider = provider
        self.safe_message = _safe_provider_message(message)
        if status_code is not None:
            self.status_code = status_code
        if retryable is not None:
            self.retryable = retryable
        super().__init__(self.safe_message)


class ProviderUnavailableError(ProviderError, RuntimeError):
    kind = "unavailable"
    retryable = True
    status_code = 503


class ProviderInvalidInputError(ProviderError, ValueError):
    kind = "invalid_input"
    retryable = False
    status_code = 400


class UnknownTickerError(ProviderError, ValueError):
    kind = "unknown_ticker"
    retryable = False
    status_code = 404


class ProviderRateLimitError(ProviderUnavailableError):
    kind = "rate_limit"
    retryable = True
    status_code = 429


class ProviderAuthError(ProviderUnavailableError):
    kind = "auth"
    retryable = False
    status_code = 503


class ProviderServerError(ProviderUnavailableError):
    kind = "server"
    retryable = True
    status_code = 502


@dataclass(frozen=True)
class RuntimeCacheConfig:
    """Effective cache controls for one request/runtime."""

    ttl_minutes: int
    enabled: bool
    fingerprint: str


_RUNTIME_CONFIG_SNAPSHOT: Optional[RuntimeCacheConfig] = None


def get_runtime_cache_snapshot() -> Optional[RuntimeCacheConfig]:
    """Return the last persisted controls observed by any cache-aware service."""
    return _RUNTIME_CONFIG_SNAPSHOT


def get_cache_generation() -> int:
    """Return the current market-cache generation."""
    return _CACHE_GENERATION


def advance_cache_generation(reason: str = "") -> int:
    """Advance the fencing token used to reject pre-purge writes."""
    global _CACHE_GENERATION
    with _GENERATION_LOCK:
        _CACHE_GENERATION += 1
        generation = _CACHE_GENERATION
    if reason:
        logger.debug("Advanced market cache generation to %s (%s)", generation, reason)
    return generation


def cache_generation_is_current(generation: int) -> bool:
    return get_cache_generation() == generation


def clear_service_memos() -> list[str]:
    """Clear every known service-owned in-process memo without touching portfolio truth.

    Imports are lazy to avoid the cache/data/company import cycle.  Unknown or
    optional services are best-effort: a missing module must not make a successful
    database purge fail.
    """
    cleared: list[str] = []

    try:
        from app.services.data_service import DataService

        DataService._in_memory_df_cache.clear()
        if hasattr(DataService, "_quote_memo"):
            DataService._quote_memo.clear()
        if hasattr(DataService, "_l1_sources"):
            DataService._l1_sources.clear()
        if hasattr(DataService, "_l1_preferences"):
            DataService._l1_preferences.clear()
        if hasattr(DataService, "_quote_sources"):
            DataService._quote_sources.clear()
        cleared.extend(["data_service_frames", "data_service_quotes"])
    except Exception as exc:  # pragma: no cover - defensive import boundary
        logger.warning("Could not reset data service memos: %s", type(exc).__name__)

    try:
        from app.services.screener_service import ScreenerService

        ScreenerService._cache.clear()
        cleared.append("screener_results")
    except Exception as exc:  # pragma: no cover - defensive import boundary
        logger.warning("Could not reset screener memo: %s", type(exc).__name__)

    try:
        from app.services.currency_service import get_currency_service

        currency = get_currency_service()
        currency._exchange_rates.clear()
        currency._rate_metadata.clear()
        currency._last_rate_metadata = None
        currency._last_rate_value = None
        currency._last_updated = None
        cleared.append("fx_rates")
    except Exception as exc:  # pragma: no cover - defensive import boundary
        logger.warning("Could not reset FX memo: %s", type(exc).__name__)

    try:
        from app.services.company_data_service import get_company_data_service

        get_company_data_service()._yf_fundamentals_cache.clear()
        cleared.append("company_fundamentals")
    except Exception as exc:  # pragma: no cover - defensive import boundary
        logger.warning("Could not reset company memo: %s", type(exc).__name__)

    # Cointegration is not owned by this service, but its L1 is a market-data memo.
    # Clearing it here keeps the purge contract true without editing the quant service.
    try:
        from app.services import cointegration_service

        cointegration_service._IN_MEMORY_COINT_CACHE.clear()
        cleared.append("coint_results")
    except Exception as exc:  # pragma: no cover - defensive import boundary
        logger.warning("Could not reset cointegration memo: %s", type(exc).__name__)

    # Tail responses are weight/source dependent.  Keep their memo inside the
    # same invalidation boundary so a source switch cannot serve old-provider
    # EVT results for the TTL window.
    try:
        from app.api.analytics import clear_tails_cache

        clear_tails_cache()
        cleared.append("tail_responses")
    except Exception as exc:  # pragma: no cover - defensive import boundary
        logger.warning("Could not reset tail response memo: %s", type(exc).__name__)

    return cleared


def _note_runtime_config(fingerprint: str) -> None:
    """Invalidate memos when persisted cache controls change."""
    global _RUNTIME_CONFIG_FINGERPRINT, _RUNTIME_CONFIG_SNAPSHOT
    if _RUNTIME_CONFIG_FINGERPRINT is not None and _RUNTIME_CONFIG_FINGERPRINT != fingerprint:
        advance_cache_generation("runtime cache settings changed")
        clear_service_memos()
    _RUNTIME_CONFIG_FINGERPRINT = fingerprint
    try:
        ttl_text, enabled_text = fingerprint.split(":", 1)
        _RUNTIME_CONFIG_SNAPSHOT = RuntimeCacheConfig(
            ttl_minutes=int(ttl_text), enabled=enabled_text == "true", fingerprint=fingerprint
        )
    except (TypeError, ValueError):
        _RUNTIME_CONFIG_SNAPSHOT = None


class CacheService:
    """Cache service for managing data caching"""
    
    def __init__(self, db_session: AsyncSession, ttl_minutes: int = 60):
        self.db = db_session
        self.ttl_minutes = max(1, int(ttl_minutes))
        self._runtime_fingerprint: Optional[str] = None

    async def get_runtime_config(self) -> RuntimeCacheConfig:
        """Read persisted cache controls for this operation.

        The API persists these values in ``app_settings``; services must not
        freeze them at construction time.  Invalid persisted values fail closed
        to the injected safe default.
        """
        ttl = self.ttl_minutes
        enabled = True
        try:
            result = await self.db.execute(
                select(AppSetting.key, AppSetting.value).where(
                    AppSetting.key.in_(("cache_ttl_minutes", "enable_cache"))
                )
            )
            values = {str(key): value for key, value in result.all()}
            raw_ttl = values.get("cache_ttl_minutes")
            if raw_ttl is not None:
                try:
                    ttl = max(1, int(raw_ttl))
                except (TypeError, ValueError):
                    logger.warning("Ignoring invalid persisted cache TTL")
            raw_enabled = values.get("enable_cache")
            if raw_enabled is not None:
                enabled = str(raw_enabled).strip().lower() in {"1", "true", "yes", "on"}
            fingerprint = f"{ttl}:{str(enabled).lower()}"
            _note_runtime_config(fingerprint)
            self._runtime_fingerprint = fingerprint
        except Exception as exc:
            # A settings read failure must not silently enable a disabled cache.
            # Preserve the last known/effective default and continue without
            # exposing raw database text.
            logger.warning("Could not read runtime cache settings: %s", type(exc).__name__)
            fingerprint = f"{ttl}:{str(enabled).lower()}"
            self._runtime_fingerprint = fingerprint
        return RuntimeCacheConfig(ttl_minutes=ttl, enabled=enabled, fingerprint=fingerprint)

    async def get_cached_analytics(
        self, 
        ticker: str, 
        metric_name: str
    ) -> Optional[Dict[str, Any]]:
        """Get cached analytics data when the runtime cache is enabled."""
        try:
            config = await self.get_runtime_config()
            if not config.enabled:
                logger.debug("Cache disabled; analytics read bypassed")
                return None
            generation = get_cache_generation()
            query = select(AnalyticsCache).where(
                AnalyticsCache.ticker == ticker,
                AnalyticsCache.metric_name == metric_name,
                AnalyticsCache.expires_at > datetime.now(timezone.utc).replace(tzinfo=None)
            )
            
            result = await self.db.execute(query)
            cache_entry = result.scalar_one_or_none()
            if not cache_generation_is_current(generation):
                return None
            if cache_entry:
                # ``expires_at`` is the durable write's authoritative expiry;
                # the current runtime TTL is applied by ``set_cached_analytics``
                # and a settings fingerprint change clears affected memos.
                logger.debug("Cache hit for %s:%s", ticker, metric_name)
                return {
                    "value": cache_entry.metric_value,
                    "calculation_date": cache_entry.calculation_date,
                    "model_params": cache_entry.model_params
                }
            
            logger.debug("Cache miss for %s:%s", ticker, metric_name)
            return None
            
        except Exception as exc:
            logger.error("Error getting cached analytics: %s", type(exc).__name__)
            await self.db.rollback()
            return None
    
    async def set_cached_analytics(
        self,
        ticker: str,
        metric_name: str,
        metric_value: float,
        calculation_date: datetime,
        model_params: Dict[str, Any] = None
    ) -> None:
        """Set cached analytics data with a generation fence and runtime TTL."""
        try:
            config = await self.get_runtime_config()
            if not config.enabled:
                return
            generation = get_cache_generation()
            expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
                minutes=config.ttl_minutes
            )

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
            if not cache_generation_is_current(generation):
                await self.db.rollback()
                return
            await self.db.commit()
            logger.debug("Cached %s:%s", ticker, metric_name)
            
        except Exception as exc:
            logger.error("Error caching analytics: %s", type(exc).__name__)
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
        """Log a fetch attempt when cache writes are enabled."""
        try:
            config = await self.get_runtime_config()
            if not config.enabled:
                return
            generation = get_cache_generation()
            fetch_log = FetchLog(
                ticker=ticker,
                status=status,
                primary_attempt=primary_attempt,
                fallback_attempt=fallback_attempt,
                error_message=(_safe_provider_message(error_message) if error_message else None),
                source_used=source_used
            )
            self.db.add(fetch_log)
            if not cache_generation_is_current(generation):
                await self.db.rollback()
                return
            await self.db.commit()
            
        except Exception as exc:
            logger.error("Error logging fetch attempt: %s", type(exc).__name__)
            await self.db.rollback()
    
    async def clear_expired_cache(self) -> int:
        """Clear expired cache entries with a single set-based DELETE."""
        try:
            config = await self.get_runtime_config()
            if not config.enabled:
                return 0
            result = await self.db.execute(
                delete(AnalyticsCache).where(
                        AnalyticsCache.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None)
                )
            )
            await self.db.commit()
            
            count = result.rowcount or 0
            if count > 0:
                logger.info("Cleared %s expired cache entries", count)
            
            return count
            
        except Exception as exc:
            logger.error("Error clearing expired cache: %s", type(exc).__name__)
            await self.db.rollback()
            return 0
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics (COUNT aggregates; never materializes rows)."""
        try:
            config = await self.get_runtime_config()
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
                "ttl_minutes": config.ttl_minutes,
                "enable_cache": config.enabled,
            }
            
        except Exception as exc:
            logger.error("Error getting cache stats: %s", type(exc).__name__)
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
    """Wipe market data and fence writes that started before the purge."""
    from app.models.database import (
        StockTimeseries, AnalyticsCache, FetchLog,
        NSEBhavcopy, NSEInstitutionalFlow, NSEBulkBlockDeal, NSEShareholdingPattern,
    )
    from sqlalchemy import func

    generation = advance_cache_generation("market data purge")
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
    except Exception as exc:
        logger.error("Error clearing market data cache tables: %s", type(exc).__name__)
        await db.rollback()
        raise

    in_memory_reset = clear_service_memos()
    cleared["in_memory_caches"] = len(in_memory_reset)
    logger.info(
        "Market data cache cleared: %s rows purged at generation %s; portfolio positions preserved",
        total,
        generation,
    )
    return {
        "cleared": cleared,
        "total_rows_cleared": total,
        "portfolio_preserved": True,
        "cache_generation": generation,
    }


async def invalidate_market_data_for_source_change(db: AsyncSession) -> None:
    """Invalidate market rows/memos after a persisted source preference change."""
    await clear_market_data_cache(db)
