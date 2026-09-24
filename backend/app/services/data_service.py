"""
Data service for fetching market data via a user-selectable 3-tier cascade:
bfinance/yfinance (per source preference) first, Alpha Vantage last.
Indian market focus (.NS and .BO suffixes).
"""

import asyncio
import inspect
import math
import numbers
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import pandas as pd
import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
import bfinance
import yfinance as yf
from zoneinfo import ZoneInfo

from app.utils.logger import setup_logger
from app.services.cache_service import (
    CacheService,
    ProviderAuthError,
    ProviderError,
    ProviderInvalidInputError,
    ProviderRateLimitError,
    ProviderServerError,
    ProviderUnavailableError,
    UnknownTickerError,
    cache_generation_is_current,
    get_cache_generation,
)
from app.services.alpha_vantage_service import (
    AlphaVantageIdentityError,
    AlphaVantageNotConfiguredError,
    AlphaVantageUnknownTickerError,
    get_alpha_vantage_service,
)
from app.services.source_preference_service import get_primary_source, source_order_for
from app.models.database import StockTimeseries, AppSetting
from app.config import settings

logger = setup_logger(__name__)

# Indian market defaults
DEFAULT_REGION = 'IN'  # Default to India
INDIAN_EXCHANGES = ['.NS', '.BO']  # NSE and BSE
POPULAR_INDIAN_STOCKS = [
    'RELIANCE.NS', 'TCS.NS', 'INFY.NS', 'HDFCBANK.NS', 'ITC.NS',
    'BHARTIARTL.NS', 'LT.NS', 'KOTAKBANK.NS', 'ASIANPAINT.NS', 'MARUTI.NS',
    'HCLTECH.NS', 'WIPRO.NS', 'ULTRACEMCO.NS', 'TATAMOTORS.NS', 'NESTLEIND.NS',
    'BAJFINANCE.NS', 'HINDUNILVR.NS', 'POWERGRID.NS', 'NTPC.NS', 'ONGC.NS'
]

# Bare scrip names known to be Indian (suffixless user input maps to NSE).
_BARE_INDIAN_SCRIPS = frozenset(t.replace('.NS', '') for t in POPULAR_INDIAN_STOCKS)
_ACTIVE_REQUEST_START: ContextVar[Optional[str]] = ContextVar("data_service_request_start", default=None)


@dataclass(frozen=True)
class DateBounds:
    start: pd.Timestamp
    end: pd.Timestamp

    @property
    def end_exclusive(self) -> pd.Timestamp:
        return self.end + pd.Timedelta(days=1)


@dataclass(frozen=True)
class FrameAcceptance:
    """Typed result of the vendor coverage acceptance predicate."""

    accepted: bool
    reason: str
    requested_start: pd.Timestamp
    requested_end: pd.Timestamp
    frame_start: Optional[pd.Timestamp] = None
    frame_end: Optional[pd.Timestamp] = None
    rows_in_window: int = 0
    expected_business_days: int = 0
    coverage_ratio: float = 0.0


def _date_bounds(start: str, end: str) -> DateBounds:
    """Parse the public inclusive date contract once at the service boundary."""
    try:
        start_dt = pd.Timestamp(start).normalize()
        end_dt = pd.Timestamp(end).normalize()
    except (TypeError, ValueError) as exc:
        raise ProviderInvalidInputError("Invalid date bounds") from exc
    if pd.isna(start_dt) or pd.isna(end_dt) or start_dt > end_dt:
        raise ProviderInvalidInputError("Date bounds must be ordered and valid")
    return DateBounds(start_dt, end_dt)


def _frame_dates(df: Optional[pd.DataFrame]) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype="datetime64[ns]")
    if "date" in getattr(df, "columns", []):
        dates = pd.to_datetime(df["date"], errors="coerce", utc=True)
        return dates.dropna().dt.tz_localize(None).sort_values()
    if isinstance(getattr(df, "index", None), pd.DatetimeIndex):
        dates = pd.to_datetime(df.index, errors="coerce", utc=True)
        return pd.Series(dates.tz_localize(None), index=df.index).sort_values()
    return pd.Series(dtype="datetime64[ns]")


def accept_vendor_frame(
    df: Optional[pd.DataFrame], start: str, end: str
) -> FrameAcceptance:
    """Accept only a non-empty frame that meaningfully covers the request.

    The predicate is intentionally conservative about sparse/outside frames but
    permits a late-listed issuer when enough of the requested sessions exist.
    It never accepts a frame solely because it is non-empty.
    """
    bounds = _date_bounds(start, end)
    dates = _frame_dates(df)
    expected = max(1, len(pd.bdate_range(bounds.start, bounds.end)))
    if dates.empty:
        return FrameAcceptance(False, "empty_or_undated", bounds.start, bounds.end,
                              expected_business_days=expected)
    in_window = dates[(dates >= bounds.start) & (dates <= bounds.end)]
    frame_start, frame_end = dates.iloc[0], dates.iloc[-1]
    count = int(len(in_window))
    ratio = count / expected
    if count == 0:
        return FrameAcceptance(False, "outside_requested_window", bounds.start, bounds.end,
                              frame_start, frame_end, 0, expected, ratio)
    # A narrow window needs both edges; a long window permits normal exchange
    # holidays and late listings but rejects a one-row/mostly-empty response.
    edge_tolerance = pd.Timedelta(days=3 if expected > 5 else 1)
    covers_start = frame_start <= bounds.start + edge_tolerance
    covers_end = frame_end >= bounds.end - edge_tolerance
    minimum = 1 if expected <= 5 else max(3, int(expected * 0.30))
    if count < minimum or not (covers_start and covers_end):
        return FrameAcceptance(False, "sparse_or_outside_window", bounds.start, bounds.end,
                              frame_start, frame_end, count, expected, ratio)
    return FrameAcceptance(True, "accepted", bounds.start, bounds.end,
                          frame_start, frame_end, count, expected, ratio)


def _safe_numeric(value: Any) -> Optional[float]:
    """Convert real numeric provider values only; mocks/objects are not prices."""
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, (numbers.Real, str)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _provider_error(exc: Exception, provider: str) -> ProviderError:
    """Map common vendor exceptions to the safe shared taxonomy."""
    if isinstance(exc, ProviderError):
        return exc
    text = str(exc).lower()
    status = getattr(getattr(exc, "response", None), "status_code", None)
    try:
        status_code = int(status) if status is not None else None
    except (TypeError, ValueError):
        status_code = None
    if "429" in text or "rate limit" in text or "too many request" in text:
        return ProviderRateLimitError(f"{provider} rate limit", provider=provider)
    if status_code in (401, 403) or "401" in text or "403" in text or "crumb" in text or "auth" in text:
        return ProviderAuthError(f"{provider} authentication unavailable", provider=provider)
    if status_code == 404:
        return UnknownTickerError(f"{provider} symbol unavailable", provider=provider)
    if status_code and status_code >= 500:
        return ProviderServerError(f"{provider} server unavailable", provider=provider)
    if "unknown symbol" in text or "not found" in text or "no data" in text:
        return UnknownTickerError(f"{provider} symbol unavailable", provider=provider)
    if "invalid" in text or "date" in text or "argument" in text:
        return ProviderInvalidInputError(f"{provider} rejected the request", provider=provider)
    return ProviderUnavailableError(f"{provider} unavailable", provider=provider)


def canonical_ticker(ticker: str) -> str:
    """Canonical form of a ticker (used for quotes, caching, and storage).

    Callers storing positions must persist this form so the same scrip cannot
    be stored twice under different spellings (e.g. RELIANCE vs RELIANCE.NS).

    Bare symbols are suffixed with .NS only when they are known Indian
    scrips; anything else passes through untouched so US/global tickers
    (e.g. AAPL) are never fabricated into NSE listings (AAPL.NS).
    """
    t = ticker.upper().strip()

    # Yahoo-native symbols (^NSEI indices, INR=X fx) pass through untouched;
    # appending .NS to an index would fabricate a nonexistent ticker.
    if t.startswith("^") or t.endswith("=X"):
        return t

    # Already has an exchange suffix (suffix check, not substring).
    if t.endswith(".NS") or t.endswith(".BO"):
        return t

    # Known Indian scrips given bare default to NSE.
    if t in _BARE_INDIAN_SCRIPS:
        return f"{t}.NS"

    return t


class DataService:
    """Main data service for fetching market data"""

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        self.cache = CacheService(db_session, settings.cache_ttl_minutes)
        self.yfinance_timeout = settings.yfinance_timeout
        self._runtime_fingerprint: Optional[str] = None
        self.last_fetch_metadata: Dict[str, Any] = {}
        self._last_fallback_error: Optional[ProviderError] = None

        # Batch fetches run several concurrent workers that share this one
        # AsyncSession. SQLAlchemy sessions are not concurrency-safe: parallel
        # commits/rollbacks on one session collide ("commit() can't be called
        # here", "transaction is closed", ...). Network calls stay parallel;
        # only DB operations are serialized through this gate.
        self._db_lock = asyncio.Lock()

        # Indian market defaults
        self.default_region = DEFAULT_REGION
        self.indian_exchanges = INDIAN_EXCHANGES
        self.popular_indian_stocks = POPULAR_INDIAN_STOCKS

    async def _refresh_runtime_config(self):
        """Apply persisted cache controls before every public cache operation."""
        config = await self.cache.get_runtime_config()
        if self._runtime_fingerprint and self._runtime_fingerprint != config.fingerprint:
            self._in_memory_df_cache.clear()
            self._quote_memo.clear()
        self._runtime_fingerprint = config.fingerprint
        return config

    def _l1_ttl_seconds(self, config=None) -> float:
        ttl_minutes = getattr(config, "ttl_minutes", None) or 1
        return max(0.0, float(ttl_minutes) * 60.0)

    def _quote_ttl_seconds(self, config=None) -> float:
        # Quote memos are intentionally shorter than durable data, but the
        # persisted enable/TTL controls still govern whether they are used.
        ttl_minutes = getattr(config, "ttl_minutes", None) or 1
        return min(30.0, max(0.0, float(ttl_minutes) * 60.0))

    def _normalize_indian_ticker(self, ticker: str) -> str:
        """
        Normalize ticker to Indian format if it looks like an Indian stock

        Args:
            ticker: Raw ticker symbol

        Returns:
            Normalized ticker with proper exchange suffix
        """
        return canonical_ticker(ticker)
    
    def _is_indian_ticker(self, ticker: str) -> bool:
        """Check if ticker is an Indian stock"""
        t = ticker.upper().strip()
        return t.endswith((".NS", ".BO")) or t in _BARE_INDIAN_SCRIPS

    async def _resolve_source_order(self) -> List[str]:
        """Effective vendor cascade for OHLCV/quote fetches, honoring the user's
        primary-source preference. Alpha Vantage is appended last by callers."""
        async with self._db_lock:
            primary = await get_primary_source(self.db)
        return source_order_for(primary)

    @staticmethod
    def _source_of_df(df: Optional[pd.DataFrame]) -> str:
        """Actual vendor that produced a downloaded frame (bfinance marks its output)."""
        return "bfinance" if getattr(df, "_source", "") == "bfinance" else "yfinance"

    _in_memory_df_cache: Dict[str, Any] = {}

    # Short-TTL quote memo (canonical ticker -> (ts, payload)); cleared by clear_market_data_cache
    _quote_memo: Dict[str, Any] = {}
    _quote_sources: Dict[str, str] = {}
    _l1_sources: Dict[str, str] = {}
    _l1_preferences: Dict[str, str] = {}
    _quote_memo_ttl = 30.0

    # Module-load identities for mock detection (tests patch these attributes)
    _YF_TICKER_REAL = staticmethod(yf.Ticker)
    _YF_DOWNLOAD_REAL = staticmethod(yf.download)
    _BF_TICKER_REAL = staticmethod(bfinance.Ticker)
    _BF_DOWNLOAD_REAL = staticmethod(bfinance.download)

    # Deep-cache horizon: vendor-max backfills download up to 10y back from
    # `end`, regardless of the requested window. L1 keeps a 5-min TTL.
    DEEP_CACHE_YEARS = 10
    _L1_TTL_SECONDS = 300
    _l1_ttl = _L1_TTL_SECONDS

    @classmethod
    def _deep_start(cls, start: str, end: str) -> str:
        """Backfill floor for a vendor fetch: 10y back from `end`, extended
        further back when the caller explicitly asked for more (never shrink)."""
        try:
            floor = (pd.to_datetime(end) - pd.DateOffset(years=cls.DEEP_CACHE_YEARS)).strftime("%Y-%m-%d")
        except Exception:
            return start
        return min(start, floor)

    @staticmethod
    def _as_column_frame(df: pd.DataFrame) -> pd.DataFrame:
        """Canonical serve/L1 shape: normalized frame with a 'date' column.

        Fresh vendor frames already carry one; SQLite slices are date-indexed.
        """
        if df is None or "date" in getattr(df, "columns", []):
            return df
        try:
            return df.reset_index()
        except Exception:
            return df

    @staticmethod
    def _frame_bounds(df: pd.DataFrame):
        """(min, max) Timestamp of a frame's dates, None when undeterminable."""
        try:
            if "date" in getattr(df, "columns", []):
                d = pd.to_datetime(df["date"], errors="coerce", utc=True).dt.tz_localize(None)
            elif isinstance(getattr(df, "index", None), pd.DatetimeIndex):
                d = pd.to_datetime(df.index, errors="coerce", utc=True).tz_localize(None)
            else:
                return None
            if d.empty:
                return None
            return (d.min(), d.max())
        except Exception:
            return None

    @staticmethod
    def _slice_window(df: pd.DataFrame, req_start, req_end) -> pd.DataFrame:
        """Return the [start, end] slice of a column-shape frame."""
        d = pd.to_datetime(df["date"], errors="coerce", utc=True).dt.tz_localize(None)
        start = pd.Timestamp(req_start).tz_localize(None) if pd.Timestamp(req_start).tzinfo else pd.Timestamp(req_start)
        end = pd.Timestamp(req_end).tz_localize(None) if pd.Timestamp(req_end).tzinfo else pd.Timestamp(req_end)
        return df[(d >= start) & (d <= end)].copy()

    def _l1_slice(
        self,
        ticker: str,
        start: str,
        end: str,
        now_ts: float,
        *,
        source_key: Optional[str] = None,
        generation: Optional[int] = None,
        config=None,
    ) -> Optional[pd.DataFrame]:
        """Slice [start, end] from a generation/source/config-fenced L1 entry."""
        try:
            entry = self._in_memory_df_cache.get(ticker)
        except Exception:
            return None
        if not entry:
            return None
        cached_ts, full_df = entry[0], entry[1]
        cached_generation = entry[2] if len(entry) > 2 else None
        if full_df is None or now_ts - cached_ts >= self._l1_ttl_seconds(config):
            return None
        if generation is not None and cached_generation is not None and cached_generation != generation:
            return None
        if source_key is not None and self._l1_preferences.get(ticker) not in (None, source_key):
            return None
        try:
            req_start, req_end = _date_bounds(start, end).start, _date_bounds(start, end).end
        except ProviderError:
            return None
        bounds = self._frame_bounds(full_df)
        if bounds is None:
            return None
        lo, hi = bounds
        if req_start < lo or req_end > hi:
            return None
        if (req_end - hi).days >= 3 and (datetime.now(timezone.utc).replace(tzinfo=None) - req_end).days <= 2:
            return None
        try:
            return self._slice_window(self._as_column_frame(full_df), req_start, req_end)
        except Exception:
            return None

    async def get_coverage(self, ticker: str) -> Dict[str, Any]:
        """Cheap per-ticker cache census for Phase-2 consumers.

        Single aggregate query (no rows fetched). Dates are ISO strings;
        None/0 when the ticker has no cached rows. No new route.
        """
        normalized = self._normalize_indian_ticker(ticker)
        try:
            config = await self.cache.get_runtime_config()
            if not config.enabled:
                return {
                    "ticker": normalized.upper(), "cached_start": None,
                    "cached_end": None, "trading_days": 0,
                }
            query = select(
                func.min(StockTimeseries.date),
                func.max(StockTimeseries.date),
                func.count(StockTimeseries.id),
            ).where(StockTimeseries.ticker == normalized.upper())
            lo, hi, n = (await self.db.execute(query)).one()

            def _iso(v):
                if v is None:
                    return None
                try:
                    return pd.to_datetime(v).strftime("%Y-%m-%d")
                except Exception:
                    return str(v)[:10]

            return {
                "ticker": normalized.upper(),
                "cached_start": _iso(lo),
                "cached_end": _iso(hi),
                "trading_days": int(n or 0),
            }
        except Exception as exc:
            logger.error("Error getting coverage for %s: %s", ticker, type(exc).__name__)
            return {
                "ticker": normalized.upper(),
                "cached_start": None,
                "cached_end": None,
                "trading_days": 0,
            }

    async def _get_full_cached_frame(self, ticker: str) -> Optional[pd.DataFrame]:
        """Full-depth column-shape frame for one ticker (no window filter, no
        staleness heuristics — freshness is enforced by the window query that
        gates every call site, plus the L1 TTL). Populates ticker-keyed L1."""
        try:
            config = await self.cache.get_runtime_config()
            if not config.enabled:
                return None
            generation = get_cache_generation()
            query = select(StockTimeseries).where(
                StockTimeseries.ticker == canonical_ticker(ticker).upper()
            ).order_by(StockTimeseries.date)

            result = await self.db.execute(query)
            records = result.scalars().all()
            if not cache_generation_is_current(generation):
                return None

            if not records:
                return None

            data = []
            for record in records:
                data.append({
                    'date': record.date,
                    'open': record.open,
                    'high': record.high,
                    'low': record.low,
                    'close': record.close,
                    'adj_close': record.adj_close,
                    'volume': record.volume,
                    'ticker': record.ticker,
                    'source_used': record.source_used,
                    'fetched_on': record.fetched_on,
                })

            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            return df

        except Exception as exc:
            logger.error("Error getting full cached frame for %s: %s", ticker, type(exc).__name__)
            return None

    async def _serve_backfilled_slice(
        self,
        ticker: str,
        start: str,
        end: str,
        fallback_df: pd.DataFrame,
        now_ts: float,
        *,
        generation: Optional[int] = None,
        source_key: Optional[str] = None,
        source_name: Optional[str] = None,
        config=None,
    ) -> pd.DataFrame:
        """Serve the requested slice and fence L1 writes after a purge."""
        if generation is not None and not cache_generation_is_current(generation):
            return pd.DataFrame()
        if config is not None and not config.enabled:
            return self._slice_window(
                self._as_column_frame(fallback_df),
                _date_bounds(start, end).start,
                _date_bounds(start, end).end,
            )
        async with self._db_lock:
            served = await self._get_cached_data(ticker, start, end)
            full = await self._get_full_cached_frame(ticker)
        if served is not None:
            out = self._as_column_frame(served)
        else:
            out = self._slice_window(
                self._as_column_frame(fallback_df),
                _date_bounds(start, end).start,
                _date_bounds(start, end).end,
            )
        if generation is not None and not cache_generation_is_current(generation):
            return pd.DataFrame()
        base = full if full is not None else self._as_column_frame(fallback_df)
        self._in_memory_df_cache[ticker] = (now_ts, base, generation)
        if source_key is not None:
            self._l1_sources[ticker] = source_name or source_key.split("|", 1)[0]
            self._l1_preferences[ticker] = source_key
        return out

    async def _download_for_request(
        self, ticker: str, start: str, end: str, source_order: List[str]
    ) -> Optional[pd.DataFrame]:
        """Call the strict download seam while tolerating legacy test doubles."""
        method = self._download_with_timeout
        try:
            parameters = inspect.signature(method).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "strict_errors" in parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            return await method(ticker, start, end, source_order, strict_errors=True)
        return await method(ticker, start, end, source_order)

    async def fetch_historical_data(
        self,
        ticker: str,
        start: str,
        end: str,
        force_refresh: bool = False,
        source_order: Optional[List[str]] = None
    ) -> Optional[pd.DataFrame]:
        """Fetch inclusive OHLCV with runtime cache controls and a generation fence."""
        try:
            bounds = _date_bounds(start, end)
            normalized_ticker = self._normalize_indian_ticker(ticker)
        except ProviderError:
            raise
        except Exception as exc:
            logger.error("Unexpected historical request normalization failure: %s", type(exc).__name__)
            return None
        # Fence the whole fetch, including startup awaits.  A purge that begins
        # while runtime controls/source preferences are read must invalidate
        # this request rather than silently granting it the newer generation.
        generation = get_cache_generation()
        config = await self._refresh_runtime_config()
        now_ts = time.time()
        if source_order is None:
            source_order = await self._resolve_source_order()
        source_key = "|".join(source_order)
        self.last_fetch_metadata = {
            "ticker": normalized_ticker,
            "from_cache": False,
            "source": None,
        }

        if not force_refresh and config.enabled:
            l1_hit = self._l1_slice(
                normalized_ticker, start, end, now_ts,
                source_key=source_key, generation=generation, config=config,
            )
            if l1_hit is not None and not l1_hit.empty:
                if not cache_generation_is_current(generation):
                    return None
                self.last_fetch_metadata.update({"from_cache": True, "source": self._l1_sources.get(normalized_ticker)})
                l1_hit.attrs["source"] = self._l1_sources.get(normalized_ticker)
                l1_hit.attrs["requested_ticker"] = normalized_ticker
                return l1_hit

            async with self._db_lock:
                cached_data = await self._get_cached_data(normalized_ticker, start, end)
                l1_live = (
                    normalized_ticker in self._in_memory_df_cache
                    and now_ts - self._in_memory_df_cache[normalized_ticker][0] < self._l1_ttl_seconds(config)
                )
                full_frame = (
                    await self._get_full_cached_frame(normalized_ticker)
                    if cached_data is not None and not l1_live
                    else None
                )
            if cached_data is not None:
                if not cache_generation_is_current(generation):
                    return None
                served = self._as_column_frame(cached_data)
                cache_source = "sqlite"
                if "source_used" in served.columns and not served.empty:
                    source_values = {
                        str(value).strip()
                        for value in served["source_used"].dropna().tolist()
                        if str(value).strip()
                    }
                    if len(source_values) == 1:
                        cache_source = next(iter(source_values))
                    elif len(source_values) > 1:
                        cache_source = "mixed"
                if not l1_live and cache_generation_is_current(generation):
                    self._in_memory_df_cache[normalized_ticker] = (now_ts, full_frame if full_frame is not None else served, generation)
                    self._l1_sources[normalized_ticker] = cache_source
                    self._l1_preferences[normalized_ticker] = source_key
                served.attrs["source"] = cache_source
                served.attrs["requested_ticker"] = normalized_ticker
                self.last_fetch_metadata.update({"from_cache": True, "source": cache_source})
                return served

        dl_start = self._deep_start(bounds.start.strftime("%Y-%m-%d"), bounds.end.strftime("%Y-%m-%d"))
        errors: List[ProviderError] = []
        max_retries = 3
        for attempt in range(max_retries):
            token = _ACTIVE_REQUEST_START.set(start)
            try:
                raw = await self._download_for_request(
                    normalized_ticker,
                    dl_start,
                    bounds.end.strftime("%Y-%m-%d"),
                    source_order,
                )
                if raw is None or raw.empty:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0)
                    continue
                actual_source = self._source_of_df(raw)
                if not getattr(raw, "_source", "") and raw.attrs.get("source"):
                    actual_source = str(raw.attrs["source"])
                elif not getattr(raw, "_source", "") and len(source_order) == 1:
                    actual_source = source_order[0]
                normalized = self._normalize_yfinance_data(raw, normalized_ticker)
                if normalized.empty:
                    errors.append(ProviderUnavailableError("Vendor frame could not be normalized", provider=actual_source))
                    continue
                acceptance = accept_vendor_frame(normalized, start, end)
                if not acceptance.accepted:
                    logger.info(
                        "Rejecting %s frame for %s: %s (%s/%s rows)",
                        actual_source, normalized_ticker, acceptance.reason,
                        acceptance.rows_in_window, acceptance.expected_business_days,
                    )
                    errors.append(ProviderUnavailableError("Vendor frame did not cover the requested window", provider=actual_source))
                    continue
                valid, validation_errors = self._sanitize_timeseries_data(normalized)
                if not valid.empty:
                    errors.extend(self._structural_errors_only(validation_errors))
                if valid.empty:
                    errors.append(ProviderInvalidInputError("Vendor frame contained no structurally valid OHLCV rows", provider=actual_source))
                    continue
                valid_acceptance = accept_vendor_frame(valid, start, end)
                if not valid_acceptance.accepted:
                    errors.append(ProviderUnavailableError("Vendor frame had insufficient valid rows for the requested window", provider=actual_source))
                    continue
                if config.enabled and cache_generation_is_current(generation):
                    async with self._db_lock:
                        if cache_generation_is_current(generation):
                            persisted = await self._store_timeseries_data(
                                normalized_ticker, valid, source_used=actual_source,
                                generation=generation,
                            )
                            if not persisted:
                                errors.append(
                                    ProviderUnavailableError(
                                        "Market data was fetched but could not be persisted",
                                        provider=actual_source,
                                    )
                                )
                                continue
                            await self._set_backfill_marker(normalized_ticker)
                            await self.cache.log_fetch_attempt(
                                ticker=normalized_ticker, status="success", source_used=actual_source
                            )
                if not cache_generation_is_current(generation):
                    return None
                served = await self._serve_backfilled_slice(
                    normalized_ticker, start, end, valid, now_ts,
                    generation=generation, source_key=source_key, source_name=actual_source, config=config,
                )
                if not served.empty:
                    served.attrs["source"] = actual_source
                    served.attrs["requested_ticker"] = normalized_ticker
                    self.last_fetch_metadata.update({"source": actual_source})
                    logger.info("Successfully fetched %s records for %s via %s", len(valid), normalized_ticker, actual_source)
                    return served
            except ProviderError as exc:
                errors.append(exc)
                logger.warning("Attempt %s failed for %s: %s", attempt + 1, normalized_ticker, exc.safe_message)
            except Exception as exc:
                mapped = _provider_error(exc, "market data")
                errors.append(mapped)
                logger.warning("Attempt %s failed for %s: %s", attempt + 1, normalized_ticker, mapped.safe_message)
            finally:
                _ACTIVE_REQUEST_START.reset(token)
            if attempt < max_retries - 1:
                await asyncio.sleep(0)

        try:
            fallback_df = await self._fetch_from_alpha_vantage(
                normalized_ticker, ticker, dl_start, bounds.end.strftime("%Y-%m-%d"),
                generation=generation, config=config, strict_errors=True, persist=False,
            )
            if fallback_df is not None and not fallback_df.empty:
                acceptance = accept_vendor_frame(fallback_df, start, end)
                if not acceptance.accepted:
                    errors.append(ProviderUnavailableError("Alpha Vantage frame did not cover the requested window", provider="alphavantage"))
                else:
                    valid, validation_errors = self._sanitize_timeseries_data(fallback_df)
                    valid_acceptance = accept_vendor_frame(valid, start, end)
                    if valid.empty or not valid_acceptance.accepted:
                        errors.append(ProviderUnavailableError("Alpha Vantage frame had insufficient valid rows", provider="alphavantage"))
                        fallback_df = pd.DataFrame()
                    if not valid.empty and valid_acceptance.accepted and cache_generation_is_current(generation):
                        if config.enabled:
                            async with self._db_lock:
                                if cache_generation_is_current(generation):
                                    persisted = await self._store_timeseries_data(
                                        normalized_ticker, valid, source_used="alphavantage",
                                        generation=generation,
                                    )
                                    if not persisted:
                                        errors.append(
                                            ProviderUnavailableError(
                                                "Market data was fetched but could not be persisted",
                                                provider="alphavantage",
                                            )
                                        )
                                        fallback_df = pd.DataFrame()
                                    else:
                                        await self._set_backfill_marker(normalized_ticker)
                                        await self.cache.log_fetch_attempt(
                                            ticker=normalized_ticker, status="success", source_used="alphavantage",
                                            primary_attempt=False, fallback_attempt=True,
                                        )
                        if not fallback_df.empty:
                            served = await self._serve_backfilled_slice(
                                normalized_ticker, start, end, valid, now_ts,
                                generation=generation, source_key=source_key, source_name="alphavantage", config=config,
                            )
                            if not served.empty:
                                served.attrs["source"] = "alphavantage"
                                served.attrs["requested_ticker"] = normalized_ticker
                                self.last_fetch_metadata.update({"source": "alphavantage"})
                                return served
        except (AlphaVantageIdentityError, AlphaVantageUnknownTickerError) as exc:
            errors.append(exc)
        except ProviderError as exc:
            errors.append(exc)
        except Exception as exc:
            errors.append(_provider_error(exc, "alphavantage"))

        if config.enabled and errors:
            async with self._db_lock:
                await self.cache.log_fetch_attempt(
                    ticker=normalized_ticker, status="failed",
                    error_message=errors[-1].safe_message,
                    source_used="alphavantage",
                )
        coverage_only = bool(errors) and all(
            isinstance(error, ProviderUnavailableError)
            and "did not cover the requested window" in error.safe_message
            for error in errors
        )
        if coverage_only:
            raise ProviderUnavailableError(
                "No provider returned data covering the requested window",
                provider="market data",
            )
        if any(isinstance(error, ProviderUnavailableError) and not isinstance(error, UnknownTickerError) for error in errors):
            raise next(error for error in errors if isinstance(error, ProviderUnavailableError) and not isinstance(error, UnknownTickerError))
        if errors and all(isinstance(error, UnknownTickerError) for error in errors):
            raise UnknownTickerError("No provider returned data for the requested ticker", provider="market data")
        return None
    
    @staticmethod
    def _normalize_quote_payload(payload: Dict[str, Any], ticker: str) -> Dict[str, Any]:
        """Normalize metadata and reject contradictory provider identity."""
        out = dict(payload or {})
        canonical = canonical_ticker(ticker)
        provided_ticker = out.get("ticker")
        if provided_ticker not in (None, ""):
            try:
                provided_canonical = canonical_ticker(str(provided_ticker))
            except Exception as exc:
                raise ProviderInvalidInputError(
                    "Provider returned an invalid ticker identity", provider="market data"
                ) from exc
            if provided_canonical != canonical:
                raise ProviderInvalidInputError(
                    f"Provider returned {provided_ticker!r} for requested {ticker!r}",
                    provider="market data",
                )
        out["ticker"] = canonical.upper()
        for key in ("sector", "industry"):
            value = out.get(key)
            out[key] = value if isinstance(value, str) and value.strip() else "Unknown"
        # Keep both spellings: the persisted quote contract uses week_52_*,
        # while older consumers read 52_week_*.
        if "week_52_high" not in out:
            out["week_52_high"] = out.get("52_week_high")
        if "week_52_low" not in out:
            out["week_52_low"] = out.get("52_week_low")
        for key in ("market_cap", "52_week_high", "52_week_low", "week_52_high", "week_52_low", "pe_ratio", "dividend_yield"):
            value = out.get(key)
            out[key] = None if value is None else _safe_numeric(value)
        out["source"] = out.get("source") or "unknown"
        out["is_indian"] = out["ticker"].endswith((".NS", ".BO"))
        expected_currency = "INR" if out["is_indian"] else "USD"
        provided_currency = out.get("currency")
        if isinstance(provided_currency, str) and provided_currency.strip():
            if provided_currency.strip().upper() != expected_currency:
                raise ProviderInvalidInputError(
                    f"Provider currency {provided_currency!r} conflicts with {out['ticker']!r}",
                    provider="market data",
                )
        if not isinstance(out.get("currency"), str) or not out["currency"].strip():
            out["currency"] = "INR" if out["is_indian"] else "USD"
        if not isinstance(out.get("exchange"), str) or not out["exchange"].strip():
            out["exchange"] = "NSE" if out["ticker"].endswith(".NS") else "BSE" if out["ticker"].endswith(".BO") else "Other"
        return out

    async def fetch_quote(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch a quote with canonical metadata and source provenance."""
        normalized_ticker = self._normalize_indian_ticker(ticker)
        # Fence the whole request, including startup awaits.  A purge that
        # begins while runtime controls or source preferences are read must not
        # grant this request the newer generation and repopulate the quote memo.
        generation = get_cache_generation()
        config = await self._refresh_runtime_config()
        source_order = await self._resolve_source_order()
        source_key = "|".join(source_order)
        now_ts = time.time()
        memo = (
            self._quote_memo.get(normalized_ticker)
            if config.enabled and cache_generation_is_current(generation)
            else None
        )
        if (
            memo is not None
            and now_ts - memo[0] < self._quote_ttl_seconds(config)
            and self._quote_sources.get(normalized_ticker) in (None, source_key)
            and cache_generation_is_current(generation)
        ):
            return self._normalize_quote_payload(memo[1], normalized_ticker)

        errors: List[ProviderError] = []

        def _read(obj: Any, key: str, default=None):
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        def _fetch_bf_quote() -> Optional[Dict[str, Any]]:
            try:
                if not self._is_indian_ticker(normalized_ticker):
                    raise ProviderInvalidInputError(
                        "bfinance supports Indian listings only", provider="bfinance"
                    )
                bt = bfinance.Ticker(normalized_ticker)
                fast = getattr(bt, "fast_info", None)
                info = getattr(bt, "info", {}) or {}
                price = _safe_numeric(_read(fast, "last_price") or _read(fast, "regular_market_price") or _read(info, "currentPrice"))
                if price is None or price <= 0:
                    return None
                return {
                    "ticker": normalized_ticker,
                    "current_price": float(price),
                    "volume": int(_safe_numeric(_read(fast, "last_volume", 0) or _read(info, "volume", 0)) or 0),
                    "market_cap": _read(fast, "market_cap") or _read(info, "marketCap"),
                    "sector": _read(info, "sector") or getattr(bt, "sector", None),
                    "industry": _read(info, "industry") or getattr(bt, "industry", None),
                    "52_week_high": _read(fast, "year_high") or _read(info, "fiftyTwoWeekHigh"),
                    "52_week_low": _read(fast, "year_low") or _read(info, "fiftyTwoWeekLow"),
                    "pe_ratio": _read(info, "trailingPE"),
                    "dividend_yield": _read(info, "dividendYield"),
                    "currency": "INR" if self._is_indian_ticker(normalized_ticker) else "USD",
                    "exchange": "NSE" if normalized_ticker.endswith(".NS") else "BSE" if normalized_ticker.endswith(".BO") else "Other",
                    "source": "bfinance",
                    "timestamp": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
                }
            except Exception as exc:
                raise _provider_error(exc, "bfinance") from exc

        def _fetch_yf_quote() -> Optional[Dict[str, Any]]:
            try:
                stock = yf.Ticker(normalized_ticker)
                fast = getattr(stock, "fast_info", None)
                current_price = _safe_numeric(_read(fast, "last_price") or _read(fast, "regular_market_price"))
                market_cap = _read(fast, "market_cap")
                high_52 = _read(fast, "year_high")
                low_52 = _read(fast, "year_low")
                volume = _safe_numeric(_read(fast, "last_volume", 0)) or 0
                if current_price is None or float(current_price) <= 0:
                    hist = stock.history(period="2d")
                    if not hist.empty:
                        current_price = float(hist["Close"].iloc[-1])
                        volume = int(hist["Volume"].iloc[-1]) if "Volume" in hist else volume
                elif not volume:
                    # Some yfinance fast_info surfaces omit volume while the
                    # already-fetched two-day history still contains it.
                    try:
                        hist = stock.history(period="2d")
                        if not hist.empty and "Volume" in hist:
                            volume = int(hist["Volume"].iloc[-1])
                    except Exception:
                        pass
                if current_price is None or float(current_price) <= 0:
                    return None
                info = getattr(stock, "info", {}) or {}
                if not isinstance(info, dict):
                    info = {}
                return {
                    "ticker": normalized_ticker,
                    "current_price": float(current_price),
                    "volume": int(volume or 0),
                    "market_cap": market_cap or info.get("marketCap"),
                    "sector": info.get("sector"),
                    "industry": info.get("industry"),
                    "52_week_high": high_52 or info.get("fiftyTwoWeekHigh"),
                    "52_week_low": low_52 or info.get("fiftyTwoWeekLow"),
                    "pe_ratio": info.get("trailingPE"),
                    "dividend_yield": info.get("dividendYield"),
                    "currency": "INR" if self._is_indian_ticker(normalized_ticker) else "USD",
                    "exchange": "NSE" if normalized_ticker.endswith(".NS") else "BSE" if normalized_ticker.endswith(".BO") else "Other",
                    "source": "yfinance",
                    "timestamp": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
                }
            except Exception as exc:
                raise _provider_error(exc, "yfinance") from exc

        def _sync_fetch() -> tuple[Optional[Dict[str, Any]], List[ProviderError]]:
            local_errors: List[ProviderError] = []
            is_yf_mocked = yf.Ticker is not DataService._YF_TICKER_REAL or yf.download is not DataService._YF_DOWNLOAD_REAL
            is_bf_mocked = bfinance.Ticker is not DataService._BF_TICKER_REAL or bfinance.download is not DataService._BF_DOWNLOAD_REAL
            effective_order = source_order
            if is_yf_mocked and not is_bf_mocked:
                effective_order = [source for source in source_order if source == "yfinance"]
            for source in effective_order:
                try:
                    if source == "bfinance":
                        quote = _fetch_bf_quote()
                    elif source == "yfinance":
                        quote = _fetch_yf_quote()
                    else:
                        raise ProviderInvalidInputError("Unknown source in quote cascade", provider=source)
                except ProviderError as exc:
                    local_errors.append(exc)
                    continue
                if quote:
                    return quote, local_errors
            return None, local_errors

        quote_data, sync_errors = await asyncio.to_thread(_sync_fetch)
        errors.extend(sync_errors)
        if quote_data is None:
            self._last_fallback_error = None
            if cache_generation_is_current(generation):
                try:
                    quote_data = await self._fallback_quote(ticker, normalized_ticker)
                except (AlphaVantageIdentityError, AlphaVantageNotConfiguredError) as exc:
                    errors.append(exc)
                except ProviderError as exc:
                    errors.append(exc)
        if quote_data is None and not cache_generation_is_current(generation):
            return None
        if quote_data is None and self._last_fallback_error is not None:
            errors.append(self._last_fallback_error)
        if quote_data is None:
            unavailable = next((e for e in errors if isinstance(e, ProviderUnavailableError)), None)
            if unavailable is not None:
                raise unavailable
            raise UnknownTickerError("No provider returned a quote for the requested ticker", provider="market data")
        normalized_quote = self._normalize_quote_payload(quote_data, normalized_ticker)
        price = _safe_numeric(normalized_quote.get("current_price"))
        if price is None or price <= 0:
            raise UnknownTickerError("Provider returned no valid quote price", provider="market data")
        normalized_quote["current_price"] = price
        if config.enabled and cache_generation_is_current(generation):
            self._quote_memo[normalized_ticker] = (now_ts, normalized_quote)
            self._quote_sources[normalized_ticker] = source_key
        return normalized_quote
    
    async def fetch_ohlcv_batch(
        self, 
        tickers: List[str], 
        days: int = 252,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        Fetch OHLCV data for multiple tickers efficiently
        
        Args:
            tickers: List of ticker symbols
            days: Number of days to fetch (if start_date not provided)
            start_date: Optional start date string (YYYY-MM-DD)
            end_date: Optional end date string (YYYY-MM-DD)
            force_refresh: Whether to bypass cache
            
        Returns:
            Dictionary mapping ticker to DataFrame and list of failed tickers
        """
        logger.info(f"Fetching batch data for {len(tickers)} tickers")

        # Calculate date range if not provided
        resolved_end = end_date or datetime.now().strftime('%Y-%m-%d')
        resolved_start = start_date or (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        # Resolve the vendor cascade once per batch: one preference read
        # instead of N, and every ticker in the batch uses the same chain
        # even if the user flips the setting mid-batch.
        batch_source_order = await self._resolve_source_order()

        results = {}
        failed_tickers = []

        # Process tickers with controlled concurrency (max 5 simultaneous requests)
        sem = asyncio.Semaphore(5)

        async def fetch_one(ticker: str):
            canonical = self._normalize_indian_ticker(ticker)
            async with sem:
                try:
                    df = await self.fetch_historical_data(
                        canonical, resolved_start, resolved_end,
                        force_refresh=force_refresh, source_order=batch_source_order
                    )
                    return canonical, df
                except ProviderError as exc:
                    logger.warning("Batch fetch unavailable for %s: %s", canonical, exc.safe_message)
                    return canonical, None
                except Exception as exc:
                    logger.error("Batch fetch failed for %s: %s", canonical, type(exc).__name__)
                    return canonical, None
        
        fetch_results = await asyncio.gather(*[fetch_one(t) for t in tickers])
        
        for ticker, df in fetch_results:
            if df is not None and not df.empty:
                results[ticker] = df
            else:
                failed_tickers.append(ticker)
        
        logger.info(f"Batch fetch completed: {len(results)} successful, {len(failed_tickers)} failed")
        
        return {
            "data": results,
            "failed_tickers": failed_tickers
        }
    
    async def validate_ticker(self, ticker: str, *, strict_errors: bool = False) -> bool:
        """Return false for an unknown ticker; raise typed outage errors."""
        normalized_ticker = self._normalize_indian_ticker(ticker)
        source_order = await self._resolve_source_order()
        errors: List[ProviderError] = []
        is_yf_mocked = yf.Ticker is not DataService._YF_TICKER_REAL or yf.download is not DataService._YF_DOWNLOAD_REAL
        is_bf_mocked = bfinance.Ticker is not DataService._BF_TICKER_REAL or bfinance.download is not DataService._BF_DOWNLOAD_REAL
        for source in source_order:
            try:
                if source == "bfinance":
                    if not self._is_indian_ticker(normalized_ticker):
                        raise ProviderInvalidInputError(
                            "bfinance supports Indian listings only", provider="bfinance"
                        )
                    if is_yf_mocked and not is_bf_mocked:
                        continue
                    def _bf_validate() -> bool:
                        bt = bfinance.Ticker(normalized_ticker)
                        fast = getattr(bt, "fast_info", None)
                        price = getattr(fast, "last_price", None) or getattr(fast, "regular_market_price", None)
                        return bool(price and float(price) > 0)
                    valid = await asyncio.to_thread(_bf_validate)
                elif source == "yfinance":
                    def _yf_validate() -> bool:
                        stock = yf.Ticker(normalized_ticker)
                        return not stock.history(period="5d").empty
                    valid = await asyncio.to_thread(_yf_validate)
                else:
                    raise ProviderInvalidInputError("Unknown source in validation cascade", provider=source)
                if valid:
                    return True
            except ProviderError as exc:
                errors.append(exc)
            except Exception as exc:
                errors.append(_provider_error(exc, source))
        if any(isinstance(error, ProviderUnavailableError) for error in errors):
            if strict_errors:
                raise next(error for error in errors if isinstance(error, ProviderUnavailableError))
            return False
        return False
    
    async def get_corporate_actions(
        self, ticker: str, *, strict_errors: bool = False
    ) -> Dict[str, Any]:
        """Get corporate actions; strict callers receive a typed outage."""
        normalized_ticker = self._normalize_indian_ticker(ticker)
        try:
            stock = yf.Ticker(normalized_ticker)
            def _fetch_actions():
                return stock.splits, stock.dividends
            splits, dividends = await asyncio.to_thread(_fetch_actions)
            return {
                "ticker": normalized_ticker.upper(),
                "source": "yfinance",
                "splits": splits.to_dict() if not splits.empty else {},
                "dividends": dividends.to_dict() if not dividends.empty else {},
                "is_indian": self._is_indian_ticker(normalized_ticker),
                "note": "yfinance adj_close is already adjusted for splits and dividends",
            }
        except Exception as exc:
            logger.warning("Corporate-actions provider unavailable: %s", type(exc).__name__)
            if strict_errors:
                raise ProviderUnavailableError(
                    "Corporate-actions provider unavailable", provider="yfinance"
                ) from exc
            return {
                "ticker": normalized_ticker.upper(),
                "source": "yfinance",
                "splits": {},
                "dividends": {},
                "is_indian": self._is_indian_ticker(normalized_ticker),
                "note": "Corporate-actions provider unavailable",
                "data_status": "unavailable",
            }
    
    def get_popular_indian_stocks(self) -> List[str]:
        """Get list of popular Indian stocks for suggestions"""
        return self.popular_indian_stocks.copy()
    
    def get_market_info(self) -> Dict[str, Any]:
        """Get information about the current market configuration"""
        return {
            "default_region": self.default_region,
            "supported_exchanges": self.indian_exchanges,
            "popular_indian_stocks": self.popular_indian_stocks,
            "market_focus": "Indian (NSE/BSE)"
        }
    
    async def _download_with_timeout(
        self,
        ticker: str,
        start: str,
        end: str,
        source_order: Optional[List[str]] = None,
        *,
        strict_errors: bool = False,
    ) -> Optional[pd.DataFrame]:
        """Try each vendor until the typed coverage predicate accepts a frame."""
        order = source_order or ["bfinance", "yfinance"]
        coverage_start = _ACTIVE_REQUEST_START.get() or start
        errors: List[ProviderError] = []
        saw_vendor_call = False
        loop = asyncio.get_event_loop()

        def download() -> Optional[pd.DataFrame]:
            nonlocal saw_vendor_call
            is_yf_mocked = yf.download is not DataService._YF_DOWNLOAD_REAL
            is_bf_mocked = bfinance.download is not DataService._BF_DOWNLOAD_REAL
            for source in order:
                try:
                    if source == "bfinance":
                        if is_yf_mocked and not is_bf_mocked:
                            continue
                        saw_vendor_call = True
                        vendor_end = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                        frame = bfinance.download(
                            ticker, start=start, end=vendor_end, progress=False, auto_adjust=False
                        )
                    elif source == "yfinance":
                        saw_vendor_call = True
                        # yfinance's end bound is exclusive; the public contract
                        # is inclusive, so request the following calendar day.
                        yfinance_end = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                        frame = yf.download(
                            ticker, start=start, end=yfinance_end, progress=False, auto_adjust=False
                        )
                    else:
                        raise ProviderInvalidInputError("Unknown market-data source", provider=source)
                    if frame is None or frame.empty:
                        continue
                    if source == "bfinance":
                        frame._source = "bfinance"
                    acceptance = accept_vendor_frame(frame, coverage_start, end)
                    if not acceptance.accepted:
                        logger.info(
                            "Vendor %s frame rejected for %s: %s", source, ticker, acceptance.reason
                        )
                        continue
                    return frame
                except ProviderError as exc:
                    errors.append(exc)
                except Exception as exc:
                    errors.append(_provider_error(exc, source))
            return None

        try:
            frame = await asyncio.wait_for(
                loop.run_in_executor(None, download), timeout=self.yfinance_timeout
            )
            if frame is None:
                if errors and strict_errors:
                    raise errors[0]
                if saw_vendor_call and strict_errors:
                    raise UnknownTickerError("No vendor returned data for the requested ticker", provider="market data")
                return None
            return frame
        except asyncio.TimeoutError as exc:
            if strict_errors:
                raise ProviderUnavailableError("Market-data request timed out", provider="market data") from exc
            return None
        except ProviderError:
            if strict_errors:
                raise
            return None
        except Exception as exc:
            if strict_errors:
                raise _provider_error(exc, "market data") from exc
            return None

    async def _fetch_from_alpha_vantage(
        self,
        normalized_ticker: str,
        original_ticker: str,
        start: str,
        end: str,
        *,
        generation: Optional[int] = None,
        config=None,
        strict_errors: bool = False,
        persist: bool = True,
    ) -> Optional[pd.DataFrame]:
        """Fetch Alpha Vantage data; the caller performs acceptance and writes."""
        av = get_alpha_vantage_service()
        if not av.enabled:
            return None
        try:
            df = await av.fetch_daily_ohlcv(normalized_ticker, start, end)
        except (AlphaVantageIdentityError, AlphaVantageUnknownTickerError):
            if strict_errors:
                raise
            return None
        except Exception as exc:
            if isinstance(exc, ProviderError):
                if strict_errors:
                    raise
                return None
            mapped = _provider_error(exc, "alphavantage")
            if strict_errors:
                raise mapped from exc
            return None
        if generation is not None and not cache_generation_is_current(generation):
            return None
        if df is None or df.empty:
            return None
        normalized = self._as_column_frame(df)
        # Alpha's own client validates the provider symbol, but keep the
        # identity fence at this adapter boundary too.  A mocked/legacy caller
        # must not relabel a returned BSE frame as the requested NSE listing.
        if "ticker" in normalized.columns and not normalized.empty:
            returned_identities = {
                canonical_ticker(str(value)).upper()
                for value in normalized["ticker"].dropna().tolist()
            }
            requested_identity = canonical_ticker(normalized_ticker).upper()
            if returned_identities and returned_identities != {requested_identity}:
                raise AlphaVantageIdentityError(
                    "Alpha Vantage returned a different security identity"
                )
        # Preserve the historical private-helper contract for direct callers;
        # the public fetch path passes persist=False because it owns the
        # generation-fenced write and acceptance checks.
        if persist and (config is None or config.enabled):
            stored = await self._store_timeseries_data(
                normalized_ticker, normalized, source_used="alphavantage",
                generation=generation,
            )
            if not stored:
                return None
        return normalized

    async def _fallback_quote(
        self,
        original_ticker: str,
        normalized_ticker: str,
        *,
        strict_errors: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Partial quote fallback; provider identity errors remain typed."""
        av = get_alpha_vantage_service()
        if not av.enabled:
            return None
        try:
            quote = await av.fetch_global_quote(normalized_ticker)
        except (AlphaVantageIdentityError, AlphaVantageNotConfiguredError) as exc:
            self._last_fallback_error = exc
            if strict_errors:
                raise
            return None
        except Exception as exc:
            if isinstance(exc, ProviderError):
                self._last_fallback_error = exc
                if strict_errors:
                    raise
                return None
            mapped = _provider_error(exc, "alphavantage")
            self._last_fallback_error = mapped
            if strict_errors:
                raise mapped from exc
            return None
        if not quote:
            return None
        returned_ticker = quote.get("ticker") if isinstance(quote, dict) else None
        if returned_ticker:
            returned_identity = canonical_ticker(str(returned_ticker)).upper()
            requested_identity = canonical_ticker(normalized_ticker).upper()
            if returned_identity != requested_identity:
                identity_error = AlphaVantageIdentityError(
                    "Alpha Vantage returned a different security identity"
                )
                self._last_fallback_error = identity_error
                if strict_errors:
                    raise identity_error
                return None
        async with self._db_lock:
            await self.cache.log_fetch_attempt(
                ticker=normalized_ticker, status="success",
                primary_attempt=False, fallback_attempt=True, source_used="alphavantage",
            )
        return self._normalize_quote_payload(quote, normalized_ticker)
    
    def _normalize_yfinance_data(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """
        Normalize yfinance data to handle multi-index columns
        
        yfinance v0.2.51+ returns multi-index columns for multiple tickers
        For single ticker, we need to flatten the column names
        """
        try:
            # Handle multi-index columns (new yfinance behavior)
            if isinstance(df.columns, pd.MultiIndex):
                # For single ticker, flatten to single level
                df.columns = df.columns.get_level_values(0)
            elif isinstance(df.columns, pd.Index):
                # Column names are already strings
                pass
            else:
                logger.warning(f"Unexpected column structure for {ticker}")
            
            # Ensure we have the required columns
            required_columns = ['Open', 'High', 'Low', 'Close', 'Adj Close', 'Volume']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                logger.warning(f"Missing columns for {ticker}: {missing_columns}")
                return pd.DataFrame()  # Return empty DataFrame
            
            # Reset index to make Date a column
            df = df.reset_index()
            
            # Rename columns for consistency
            df = df.rename(columns={
                'Date': 'date',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Adj Close': 'adj_close',
                'Volume': 'volume'
            })
            
            # Ensure ticker column
            df['ticker'] = ticker.upper()
            
            # Convert data types
            numeric_columns = ['open', 'high', 'low', 'close', 'adj_close']
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
            df['date'] = pd.to_datetime(df['date'])
            
            # Remove rows with NaN values
            df = df.dropna()
            
            logger.debug(f"Normalized data for {ticker}: {len(df)} records")
            return df
            
        except Exception as exc:
            logger.error("Error normalizing data for %s: %s", ticker, type(exc).__name__)
            return pd.DataFrame()
    
    async def _get_cached_data(
        self, 
        ticker: str, 
        start: str, 
        end: str
    ) -> Optional[pd.DataFrame]:
        """Get cached timeseries data"""
        try:
            config = await self.cache.get_runtime_config()
            if not config.enabled:
                return None
            generation = get_cache_generation()
            bounds = _date_bounds(start, end)
            query = select(StockTimeseries).where(
                StockTimeseries.ticker == canonical_ticker(ticker).upper(),
                StockTimeseries.date >= bounds.start,
                StockTimeseries.date < bounds.end_exclusive
            ).order_by(StockTimeseries.date)
            
            result = await self.db.execute(query)
            records = result.scalars().all()
            if not cache_generation_is_current(generation):
                return None
            
            if not records:
                return None
            
            # Check if cached data covers the requested start date
            req_start = bounds.start
            req_end = bounds.end
            req_days = (req_end - req_start).days
            earliest_cached = pd.to_datetime(records[0].date)
            # If caller requested >60 days but cached data starts more than 30 days after requested start,
            # or if cached count is too sparse for requested window, check if we fetched recently (within 1 hour)
            if req_days > 60:
                start_gap_too_big = (earliest_cached - req_start).days > 30
                too_sparse = len(records) < min(30, int(req_days * 0.3))
                if start_gap_too_big or too_sparse:
                    # Deep backfill marker: after a successful 10y download the
                    # coverage is authoritative even if the asset's real history
                    # starts late (IPO/new ETF). Wall-clock grace alone left
                    # partial-history tickers in a perpetual refetch loop.
                    marker_key = f"deep_backfill:{ticker}"
                    marker_q = await self.db.execute(
                        select(AppSetting).where(AppSetting.key == marker_key)
                    )
                    marker = marker_q.scalar_one_or_none()
                    marker_ok = False
                    if marker and marker.value:
                        try:
                            marker_ok = datetime.fromisoformat(marker.value) >= earliest_cached
                        except ValueError:
                            marker_ok = False
                    latest_fetched = max((r.fetched_on for r in records if r.fetched_on), default=None)
                    if marker_ok:
                        logger.debug(f"Deep-backfill marker covers start gap for {ticker}")
                    elif latest_fetched and (datetime.now(timezone.utc).replace(tzinfo=None) - latest_fetched).total_seconds() < 3600:
                        logger.debug(f"Using recent partial cache for {ticker} ({len(records)} records)")
                    else:
                        logger.info(f"Cache miss for {ticker}: cached has {len(records)} records from {earliest_cached.date()}, requested from {req_start.date()}")
                        return None

            # Check if cached data is stale at the end (missing latest 3+ days when req_end is recent)
            latest_cached = pd.to_datetime(records[-1].date)
            if (req_end - latest_cached).days >= 3 and (datetime.now(timezone.utc).replace(tzinfo=None) - req_end).days <= 2:
                latest_fetched = max((r.fetched_on for r in records if r.fetched_on), default=None)
                if not latest_fetched or (datetime.now(timezone.utc).replace(tzinfo=None) - latest_fetched).total_seconds() >= 3600:
                    logger.info(f"Cache stale for {ticker}: latest cached date is {latest_cached.date()}, requested up to {req_end.date()}")
                    return None
            
            # Convert to DataFrame
            data = []
            for record in records:
                data.append({
                    'date': record.date,
                    'open': record.open,
                    'high': record.high,
                    'low': record.low,
                    'close': record.close,
                    'adj_close': record.adj_close,
                    'volume': record.volume,
                    'ticker': record.ticker,
                    'source_used': record.source_used,
                    'fetched_on': record.fetched_on,
                })
            
            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            
            logger.debug(f"Retrieved {len(df)} cached records for {ticker}")
            return df
            
        except Exception as exc:
            logger.error("Error getting cached data for %s: %s", ticker, type(exc).__name__)
            return None
    
    @staticmethod
    def _structural_invalid_mask(df: pd.DataFrame) -> pd.Series:
        """Return a row mask for values that must never reach persistence."""
        required = ["open", "high", "low", "close", "adj_close", "volume"]
        if any(column not in df.columns for column in required):
            return pd.Series(True, index=df.index)
        work = df.copy()
        for column in required:
            work[column] = pd.to_numeric(work[column], errors="coerce")
        invalid = work[required].isna().any(axis=1)
        numeric = work[required].to_numpy(dtype=float)
        invalid |= ~pd.Series(np.isfinite(numeric).all(axis=1), index=work.index)
        price_columns = ["open", "high", "low", "close", "adj_close"]
        invalid |= (work[price_columns] <= 0).any(axis=1)
        invalid |= (work["volume"] < 0)
        invalid |= (work["high"] < work[["open", "close", "low"]].max(axis=1))
        invalid |= (work["low"] > work[["open", "close", "high"]].min(axis=1))
        if "date" in work.columns:
            dates = pd.to_datetime(work["date"], errors="coerce")
            invalid |= dates.isna()
        return invalid

    def _sanitize_timeseries_data(self, df: pd.DataFrame) -> tuple[pd.DataFrame, List[str]]:
        """Quarantine structural errors while preserving valid rows/warnings."""
        if df is None or df.empty:
            return pd.DataFrame(), ["empty frame"]
        if "date" not in df.columns and isinstance(getattr(df, "index", None), pd.DatetimeIndex):
            df = df.reset_index()
        required = ["open", "high", "low", "close", "adj_close", "volume"]
        missing = [column for column in required if column not in df.columns]
        if missing:
            return pd.DataFrame(), [f"Missing required columns: {missing}"]
        work = df.copy()
        for column in required:
            work[column] = pd.to_numeric(work[column], errors="coerce")
        if "date" not in work.columns:
            return pd.DataFrame(), ["Missing required columns: ['date']"]
        work["date"] = pd.to_datetime(work["date"], errors="coerce")
        invalid = self._structural_invalid_mask(work)
        valid = work.loc[~invalid].copy()
        errors: List[str] = []
        invalid_count = int(invalid.sum())
        if invalid_count:
            errors.append(f"Quarantined {invalid_count} structurally invalid OHLCV rows")
        duplicate_count = int(valid["date"].duplicated(keep="last").sum())
        if duplicate_count:
            valid = valid.drop_duplicates("date", keep="last").copy()
            errors.append(f"Collapsed {duplicate_count} duplicate dates")
        if len(valid) > 1:
            changes = valid.sort_values("date")["close"].pct_change().abs()
            large_moves = int((changes > 0.5).sum())
            if large_moves:
                errors.append(f"Warning: {large_moves} extreme price movements (>50%)")
        return valid.reset_index(drop=True), errors

    @staticmethod
    def _structural_errors_only(errors: List[str]) -> List[ProviderError]:
        result: List[ProviderError] = []
        for error in errors:
            if "extreme price movements" in error or "duplicate dates" in error:
                continue
            result.append(ProviderInvalidInputError("OHLCV structural validation rejected rows"))
        return result

    async def _store_timeseries_data(
        self,
        ticker: str,
        df: pd.DataFrame,
        source_used: str = "yfinance",
        generation: Optional[int] = None,
    ) -> bool:
        """Persist valid rows under the caller's captured cache generation."""
        try:
            # Direct helper callers get the same pre-await fence as the public
            # fetch path; fetch callers pass the generation captured at entry.
            write_generation = get_cache_generation() if generation is None else int(generation)
            if not cache_generation_is_current(write_generation):
                return False
            config = await self.cache.get_runtime_config()
            if not config.enabled or not cache_generation_is_current(write_generation):
                return False
            valid, validation_errors = self._sanitize_timeseries_data(df)
            if validation_errors:
                logger.warning("OHLCV validation for %s: %s", ticker, "; ".join(validation_errors))
            if valid.empty:
                logger.warning("No valid OHLCV rows to persist for %s", ticker)
                return False
            fetched_on = datetime.now(timezone.utc).replace(tzinfo=None)
            records = [
                {
                    "ticker": canonical_ticker(ticker).upper(),
                    "date": row["date"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "adj_close": float(row["adj_close"]),
                    "volume": int(row["volume"]),
                    "source_used": source_used,
                    "fetch_status": "fresh",
                    "fetched_on": fetched_on,
                }
                for row in valid.to_dict("records")
            ]
            if source_used.lower() == "alphavantage" and records:
                # Alpha's daily endpoint is unadjusted.  Never replace an
                # existing adjusted Yahoo/bfinance row with that fallback;
                # retain the prior row and let genuinely new dates be stored
                # with their explicit Alpha provenance.
                existing_result = await self.db.execute(
                    select(StockTimeseries.date, StockTimeseries.source_used).where(
                        StockTimeseries.ticker == canonical_ticker(ticker).upper(),
                        StockTimeseries.date.in_([record["date"] for record in records]),
                    )
                )
                existing_sources = {
                    pd.Timestamp(row.date).normalize(): str(row.source_used or "").lower()
                    for row in existing_result.all()
                }
                records = [
                    record
                    for record in records
                    if existing_sources.get(pd.Timestamp(record["date"]).normalize(), "alphavantage")
                    == "alphavantage"
                ]
                if not records:
                    logger.info("Preserved existing adjusted rows for %s; no Alpha overwrite", ticker)
                    return True
            if not cache_generation_is_current(write_generation):
                return False
            stmt = sqlite_insert(StockTimeseries.__table__).values(records)
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker", "date"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "adj_close": stmt.excluded.adj_close,
                    "volume": stmt.excluded.volume,
                    "source_used": stmt.excluded.source_used,
                    "fetch_status": stmt.excluded.fetch_status,
                    "fetched_on": stmt.excluded.fetched_on,
                },
            )
            await self.db.execute(stmt)
            if not cache_generation_is_current(write_generation):
                await self.db.rollback()
                return False
            await self.db.commit()
            logger.info("Successfully atomic upserted %s valid records for %s", len(records), ticker)
            return True
        except Exception as exc:
            logger.error("Error storing timeseries data for %s: %s", ticker, type(exc).__name__)
            await self.db.rollback()
            self._analyze_storage_error(ticker, df, exc)
            return False
    def _validate_timeseries_data(self, df: pd.DataFrame) -> List[str]:
        """Return structural errors and a separate large-move warning."""
        if df is None:
            return ["Validation error: missing frame"]
        required = ["open", "high", "low", "close", "adj_close", "volume"]
        errors: List[str] = []
        missing = [column for column in required if column not in getattr(df, "columns", [])]
        if missing:
            return [f"Missing required columns: {missing}"]
        work = df.copy()
        for column in required:
            work[column] = pd.to_numeric(work[column], errors="coerce")
        null_counts = work[required].isna().sum()
        if (null_counts > 0).any():
            errors.append(f"Found null values in columns: {null_counts[null_counts > 0].to_dict()}")
        for column in required:
            negative_count = int((work[column] < 0).sum())
            if negative_count:
                errors.append(f"Found {negative_count} negative values in {column}")
        invalid_ohlc = int((
            (work["high"] < work["low"])
            | (work["high"] < work["open"])
            | (work["high"] < work["close"])
            | (work["low"] > work["open"])
            | (work["low"] > work["close"])
        ).sum())
        if invalid_ohlc:
            errors.append(f"Found {invalid_ohlc} records with invalid OHLC relationships")
        if "date" in work.columns:
            duplicate_count = int(work["date"].duplicated().sum())
            if duplicate_count:
                errors.append(f"Found {duplicate_count} duplicate dates in input DataFrame")
        if len(work) > 1 and "date" in work.columns:
            changes = work.sort_values("date")["close"].pct_change().abs()
            extreme = int((changes > 0.5).sum())
            if extreme:
                errors.append(f"Found {extreme} records with extreme price movements (>50%)")
        return errors
    
    async def _set_backfill_marker(self, ticker: str) -> None:
        """Persist a deep-backfill marker when cache writes are enabled."""
        try:
            config = await self.cache.get_runtime_config()
            if not config.enabled:
                return
            generation = get_cache_generation()
            if not cache_generation_is_current(generation):
                return
            marker_key = f"deep_backfill:{ticker}"
            now_iso = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
            stmt = sqlite_insert(AppSetting).values(key=marker_key, value=now_iso)
            stmt = stmt.on_conflict_do_update(
                index_elements=['key'], set_={'value': now_iso}
            )
            await self.db.execute(stmt)
            if not cache_generation_is_current(generation):
                await self.db.rollback()
                return
            await self.db.commit()
        except Exception as exc:
            logger.debug("Could not write backfill marker for %s: %s", ticker, type(exc).__name__)
            await self.db.rollback()

    def _analyze_storage_error(self, ticker: str, df: pd.DataFrame, error: Exception) -> None:
        """Log structural context without copying raw DB/provider messages."""
        try:
            logger.error("Storage error analysis for %s: type=%s", ticker, type(error).__name__)
            if df is not None:
                logger.error("Storage error frame shape=%s columns=%s", df.shape, list(df.columns))
            error_name = type(error).__name__
            if "IntegrityError" in error_name:
                logger.error("Storage integrity conflict for %s", ticker)
            else:
                logger.error("Unexpected storage failure for %s", ticker)
        except Exception as analysis_error:
            logger.error("Error in storage error analysis: %s", type(analysis_error).__name__)
            
    async def check_data_integrity(self, ticker: Optional[str] = None) -> Dict[str, Any]:
        """Check data integrity for specified ticker or entire database"""
        try:
            if ticker:
                # Check specific ticker
                query = select(func.count()).select_from(StockTimeseries).where(
                    StockTimeseries.ticker == ticker.upper()
                )
                result = await self.db.execute(query)
                record_count = result.scalar()
                
                # Check for duplicates
                duplicate_query = select(func.count()).select_from(
                    StockTimeseries
                ).where(
                    StockTimeseries.ticker == ticker.upper()
                ).group_by(
                    StockTimeseries.ticker, StockTimeseries.date
                ).having(func.count() > 1)
                duplicate_result = await self.db.execute(duplicate_query)
                duplicate_count = len(duplicate_result.fetchall())
                
                return {
                    "ticker": ticker.upper(),
                    "total_records": record_count,
                    "duplicate_records": duplicate_count,
                    "integrity_status": "GOOD" if duplicate_count == 0 else "ISSUES_FOUND",
                    "recommendation": "No action needed" if duplicate_count == 0 else f"Clean up {duplicate_count} duplicate combinations"
                }
            else:
                # Check entire database
                total_query = select(func.count()).select_from(StockTimeseries)
                total_result = await self.db.execute(total_query)
                total_records = total_result.scalar()
                
                # Check for any duplicates
                all_duplicates_query = select(
                    StockTimeseries.ticker,
                    StockTimeseries.date,
                    func.count()
                ).select_from(StockTimeseries).group_by(
                    StockTimeseries.ticker, StockTimeseries.date
                ).having(func.count() > 1)
                duplicate_result = await self.db.execute(all_duplicates_query)
                duplicates = duplicate_result.fetchall()
                
                return {
                    "database_status": "GOOD" if len(duplicates) == 0 else "ISSUES_FOUND",
                    "total_records": total_records,
                    "duplicate_combinations": len(duplicates),
                    "duplicate_details": [{"ticker": d[0], "date": d[1], "count": d[2]} for d in duplicates[:5]],
                    "recommendation": "Database integrity is good" if len(duplicates) == 0 else f"Found {len(duplicates)} ticker/date combinations with duplicates"
                }
                
        except Exception as exc:
            logger.error("Error checking data integrity: %s", type(exc).__name__)
            return {
                "error": "CHECK_FAILED",
                "status": "CHECK_FAILED"
            }


# Global data service instance
class GlobalDataService:
    """Global data service for dependency injection"""
    
    def __init__(self, db_session: AsyncSession):
        self._data_service = DataService(db_session)
    
    def get_service(self) -> DataService:
        return self._data_service