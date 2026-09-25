"""
Analytics API endpoints for risk calculations and portfolio analytics
"""

import asyncio
import inspect
import math
import time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError, validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import numpy as np
import pandas as pd

from app.db.database import get_db_session
from app.models.database import PortfolioPosition
from app.services.benchmark_service import BenchmarkService
from app.services.optimization_service import optimize
from app.services.backtest_service import run_walk_forward_backtest
from app.services.regime_service import detect_regime
from app.services.monte_carlo_service import simulate_goal
from app.services.data_service import GlobalDataService, DataService
from app.services.cache_service import (
    GlobalCacheService,
    CacheService,
    ProviderError,
)
from app.services.currency_service import (
    CurrencyUnavailableError,
    coerce_live_fx_rate,
    get_currency_service,
)
from app.services.analytics_engine import (
    GlobalAnalyticsEngine,
    AnalyticsEngine,
    aggregate_active_returns,
)
from app.models.schemas import (
    StressTestRequest, CorrelationStabilityResponse, CointScannerResponse
)
from app.services.correlation_service import analyze_correlation_stability
from app.services.cointegration_service import CointegrationService
from app.utils.holdings import (
    MIN_ANNUALIZE_DAYS,
    apply_annualization_gate,
    coerce_holding_date,
    effective_starts,
    holding_coverage,
    holding_window,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Create router
router = APIRouter()


_MAX_TICKERS = 50
_MAX_COINT_TICKERS = 30
_MAX_HISTORY_DAYS = 3650
_OPTIMIZATION_STRATEGIES = frozenset({"hrp", "min_vol", "max_sharpe", "min_cvar", "black_litterman"})
_BACKTEST_STRATEGIES = frozenset(_OPTIMIZATION_STRATEGIES | {"equal_weight"})
_MONTE_CARLO_METHODS = frozenset({"gbm", "student_t", "bootstrap"})
_VOLATILITY_MODELS = frozenset({"GARCH", "EGARCH", "EWMA"})


class OptimizeRequest(BaseModel):
    """Bounded API-local contract; schemas.py remains foundation-owned."""

    strategy: str = "hrp"
    risk_free_rate: float = Field(default=0.02, ge=-1.0, le=1.0, allow_inf_nan=False)
    tickers: Optional[List[str]] = Field(default=None, max_length=_MAX_TICKERS)
    views: Optional[Dict[str, float]] = None
    relative_views: Optional[List[Dict[str, Any]]] = Field(default=None, max_length=_MAX_TICKERS)

    @validator("strategy", pre=True)
    def normalize_strategy(cls, value):
        return str(value or "hrp").strip().lower()

    @validator("views")
    def finite_views(cls, value):
        if value is not None:
            if len(value) > _MAX_TICKERS:
                raise ValueError("too many views")
            for number in value.values():
                if not math.isfinite(float(number)):
                    raise ValueError("view values must be finite")
        return value

    @validator("relative_views")
    def finite_relative_views(cls, value):
        if value is not None:
            for view in value:
                for key in ("diff", "expected_return"):
                    if key in view and not math.isfinite(float(view[key])):
                        raise ValueError("relative view values must be finite")
        return value


class BacktestRequest(BaseModel):
    strategy: str = "hrp"
    rebalance_freq_days: int = Field(default=21, ge=1, le=2520)
    lookback_days: int = Field(default=252, ge=20, le=2520)
    transaction_cost_bps: float = Field(default=10.0, ge=0.0, le=1000.0, allow_inf_nan=False)
    risk_free_rate: float = Field(default=0.02, ge=-1.0, le=1.0, allow_inf_nan=False)
    history_days: int = Field(default=750, ge=30, le=_MAX_HISTORY_DAYS)
    tickers: Optional[List[str]] = Field(default=None, max_length=_MAX_TICKERS)

    @validator("strategy", pre=True)
    def normalize_strategy(cls, value):
        return str(value or "hrp").strip().lower()


class MonteCarloRequest(BaseModel):
    target_value: float = Field(..., gt=0.0, allow_inf_nan=False)
    horizon_years: float = Field(..., ge=1.0, le=40.0, allow_inf_nan=False)
    initial_value: Optional[float] = Field(default=None, gt=0.0, allow_inf_nan=False)
    method: str = "gbm"
    # Preserve the service's historical 100..20000 normalization for ordinary
    # callers, while rejecting absurd values before any vendor/simulation work.
    num_paths: int = Field(default=2000, ge=1, le=1_000_000)
    seed: Optional[int] = Field(default=None, ge=0, le=2**32 - 1)
    tickers: Optional[List[str]] = Field(default=None, max_length=_MAX_TICKERS)

    @validator("method", pre=True)
    def normalize_method(cls, value):
        return str(value or "gbm").strip().lower()


# One semaphore per event loop keeps CPU offload bounded without sharing a
# loop-affine primitive across TestClient/application loops.
_cpu_semaphores: Dict[Any, asyncio.Semaphore] = {}


def _cpu_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _cpu_semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(2)
        _cpu_semaphores[loop] = semaphore
    return semaphore


async def _run_cpu(function, /, *args, **kwargs):
    """Run a pure synchronous computation in a bounded worker thread."""
    async with _cpu_semaphore():
        result = await asyncio.to_thread(function, *args, **kwargs)
    if inspect.isawaitable(result):
        result = await result
    return result


def _coerce_request(model: type[BaseModel], value: Any) -> BaseModel:
    """Accept direct dict calls in tests while keeping HTTP validation strict."""
    if isinstance(value, model):
        return value
    try:
        return model.model_validate(value)
    except (ValidationError, TypeError, ValueError) as exc:
        fields = []
        if isinstance(exc, ValidationError):
            errors = exc.errors()
            fields = [
                {"field": ".".join(str(part) for part in error.get("loc", ())), "message": error.get("msg", "invalid")}
                for error in errors
            ]
            if any(error.get("loc", ("",))[0] in {"strategy", "method"} for error in errors):
                raise HTTPException(status_code=400, detail="Invalid strategy or method") from exc
        raise HTTPException(status_code=422, detail={"message": "Invalid request parameters", "fields": fields}) from exc


def _raise_provider_http_error(exc: ProviderError) -> None:
    """Translate typed provider failures without exposing upstream details."""
    status_code = int(getattr(exc, "status_code", 502) or 502)
    if not 400 <= status_code <= 599:
        status_code = 502
    if str(getattr(exc, "provider", "")).strip().lower() == "currency":
        raise HTTPException(status_code=503, detail="Live FX unavailable") from exc
    kind = str(getattr(exc, "kind", "provider_error"))
    detail = {
        "rate_limit": "Upstream data service rate limit",
        "auth": "Upstream data service unavailable",
        "unknown_ticker": "Requested ticker was not found",
        "invalid_input": "Invalid market-data request",
    }.get(kind, "Upstream data service unavailable")
    raise HTTPException(status_code=status_code, detail=detail) from exc


def _parse_tickers(value: Any, *, max_items: int = _MAX_TICKERS) -> Optional[str]:
    if value is None or not isinstance(value, str):
        return None
    items = []
    seen = set()
    for raw in value.split(","):
        ticker = raw.strip().upper()
        if not ticker or ticker in seen:
            continue
        if len(items) >= max_items:
            raise HTTPException(status_code=422, detail=f"At most {max_items} tickers are allowed")
        seen.add(ticker)
        items.append(ticker)
    return ",".join(items) if items else None


def _universe_coverage(requested: Iterable[str], available: Iterable[str]) -> Dict[str, Any]:
    """Describe the exact requested/available ticker universe for a result."""
    requested_list = list(dict.fromkeys(str(item).strip().upper() for item in requested if str(item).strip()))
    available_list = list(dict.fromkeys(str(item).strip().upper() for item in available if str(item).strip()))
    available_set = set(available_list)
    covered = [ticker for ticker in requested_list if ticker in available_set]
    missing = [ticker for ticker in requested_list if ticker not in available_set]
    if not requested_list:
        status = "unknown"
    elif not covered:
        status = "unavailable"
    elif missing:
        status = "partial"
    else:
        status = "complete"
    return {
        "requested_tickers": requested_list,
        "available_tickers": available_list,
        "covered_tickers": covered,
        "missing_tickers": missing,
        "requested_count": len(requested_list),
        "available_count": len(covered),
        "coverage_ratio": round(len(covered) / len(requested_list), 6) if requested_list else None,
        "complete": not missing if requested_list else None,
        "status": status,
        "weight_basis": "active_weights_renormalized_to_100_percent",
    }


def _active_weight_tickers(weights: Mapping[str, Any]) -> List[str]:
    """Calculation universe: only positive, finite portfolio weights."""
    active: List[str] = []
    for ticker, weight in weights.items():
        try:
            numeric = float(weight or 0.0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(numeric) and numeric > 0.0:
            active.append(str(ticker).upper())
    return active


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


def _date_window(
    start: Any,
    end: Any,
    *,
    default_days: int,
    max_days: int = _MAX_HISTORY_DAYS,
) -> tuple[str, str]:
    end_date = _coerce_date(end, "end") or datetime.now().date()
    start_date = _coerce_date(start, "start") or (end_date - timedelta(days=default_days))
    if start_date > end_date:
        raise HTTPException(status_code=422, detail="start must be on or before end")
    if (end_date - start_date).days > max_days:
        raise HTTPException(status_code=422, detail=f"date range must be at most {max_days} days")
    return start_date.isoformat(), end_date.isoformat()


def _validate_model_name(value: Any, allowed: frozenset[str], field_name: str = "model") -> str:
    if not isinstance(value, str):
        raise HTTPException(status_code=422, detail=f"{field_name} is required")
    normalized = value.strip().upper()
    if normalized not in allowed:
        raise HTTPException(status_code=422, detail=f"Unsupported {field_name}")
    return normalized


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


async def _load_portfolio_tickers(db: AsyncSession) -> List[str]:
    """Return every persisted holding ticker, including zero-value rows."""
    result = await db.execute(select(PortfolioPosition))
    tickers: List[str] = []
    seen = set()
    for position in result.scalars().all():
        ticker = str(getattr(position, "ticker", "") or "").strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            tickers.append(ticker)
    return tickers


async def resolve_allocation(
    tickers_param: Optional[str],
    db: AsyncSession,
) -> tuple[List[str], Dict[str, float]]:
    """Shared allocation resolution: DB positions with real market-value weights, or custom tickers.

    `tickers_param="portfolio"` is the documented sentinel for "use the full
    book" (same as omitting the param).
    """
    try:
        db_weights = await _load_portfolio_allocation(db)
    except ProviderError as exc:
        _raise_provider_http_error(exc)

    full_book = not (isinstance(tickers_param, str) and tickers_param.strip())
    if isinstance(tickers_param, str) and tickers_param.strip():
        parsed = _parse_tickers(tickers_param)
        ticker_list = [t.strip().upper() for t in (parsed or "").split(",") if t.strip()]
        if not ticker_list:
            raise ValueError("No tickers specified")
        if ticker_list == ["PORTFOLIO"]:
            full_book = True
        else:
            if db_weights:
                known = set(db_weights)
                if any(ticker not in known for ticker in ticker_list):
                    known.update(await _load_portfolio_tickers(db))
                subset = {t: db_weights.get(t, 0.0) for t in ticker_list if t in known}
                if subset and sum(subset.values()) > 0:
                    tot = sum(subset.values())
                    return ticker_list, {t: v / tot for t, v in subset.items()}
            # Fallback for ad-hoc / external tickers not in DB
            eq = 1.0 / len(ticker_list)
            return ticker_list, {t: eq for t in ticker_list}

    if not db_weights and not full_book:
        raise ValueError("No portfolio positions found")
    requested_tickers = await _load_portfolio_tickers(db) if full_book else list(db_weights.keys())
    if not requested_tickers and not db_weights:
        raise ValueError("No portfolio positions found")
    return requested_tickers or list(db_weights.keys()), db_weights


def _q(metric_fn, *args, **kwargs):
    """Guard a single quantstats metric call; API drift must not kill the sheet."""
    try:
        val = metric_fn(*args, **kwargs)
        if hasattr(val, "item"):
            val = val.item()
        val = float(val)
        if not math.isfinite(val):
            return None
        return round(val, 6)
    except Exception:  # noqa: BLE001
        logger.debug("quantstats metric unavailable")
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
            out = pd.Series(values.values, index=idx, name=price_col).dropna()
            out.attrs.update(df.attrs)
            return out
    if isinstance(df.index, pd.DatetimeIndex):
        out = values.copy()
        out.index = pd.to_datetime(df.index)
        out.attrs.update(df.attrs)
        return out
    out = pd.Series(values.values, index=pd.RangeIndex(len(values)), name=price_col)
    out.attrs.update(df.attrs)
    return out


def _assign_price(store: Dict[str, pd.Series], ticker: str, df: pd.DataFrame) -> None:
    series = _price_series(df)
    if series is not None:
        store[ticker] = series


async def _fetch_price_series_dict(
    data_service: DataService,
    ticker_list: List[str],
    start: str,
    end: str
) -> Dict[str, pd.Series]:
    """Fetch historical prices for multiple tickers concurrently."""
    sem = asyncio.Semaphore(5)

    async def fetch_one(ticker: str):
        async with sem:
            try:
                res = data_service.fetch_historical_data(ticker, start, end)
                if asyncio.iscoroutine(res):
                    df = await res
                else:
                    df = res
                return ticker, df
            except Exception as exc:
                logger.warning("Historical data fetch failed for %s: %s", ticker, type(exc).__name__)
                return ticker, None

    results = await asyncio.gather(*[fetch_one(t) for t in ticker_list])
    price_data_dict: Dict[str, pd.Series] = {}
    for ticker, df in results:
        if df is not None and not df.empty:
            _assign_price(price_data_dict, ticker, df)
    return price_data_dict


def _latest_observation_date(price_data: Any) -> Optional[str]:
    """Return the newest actual price observation, never the requested end."""
    if price_data is None:
        return None

    def _frame_date(frame: pd.DataFrame) -> Optional[str]:
        for column in ("date", "Date", "datetime", "Datetime", "timestamp"):
            if column in frame.columns:
                parsed = pd.to_datetime(frame[column], errors="coerce").dropna()
                if not parsed.empty:
                    return pd.Timestamp(parsed.max()).strftime("%Y-%m-%d")
        if isinstance(frame.index, pd.DatetimeIndex):
            values = frame.index.dropna()
            return pd.Timestamp(values.max()).strftime("%Y-%m-%d") if len(values) else None
        return None

    if isinstance(price_data, pd.DataFrame):
        latest = _frame_date(price_data)
        return latest
    if isinstance(price_data, pd.Series):
        if isinstance(price_data.index, pd.DatetimeIndex):
            values = price_data.index.dropna()
            return pd.Timestamp(values.max()).strftime("%Y-%m-%d") if len(values) else None
        return None
    if isinstance(price_data, Mapping):
        dates: List[str] = []
        for value in price_data.values():
            if isinstance(value, pd.DataFrame):
                latest = _frame_date(value)
            elif isinstance(value, pd.Series):
                if isinstance(value.index, pd.DatetimeIndex):
                    valid = value.index.dropna()
                    latest = pd.Timestamp(valid.max()).strftime("%Y-%m-%d") if len(valid) else None
                else:
                    latest = None
            else:
                latest = None
            if latest:
                dates.append(latest)
        return max(dates) if dates else None
    return None


def _analytics_position_currency(position: Any) -> str:
    """Infer the position's native cash-equity currency for analytics math."""
    for attr in ("currency", "position_currency", "quote_currency", "_quote_currency"):
        value = getattr(position, attr, None)
        if isinstance(value, str) and value.strip():
            code = value.strip().upper()
            if code in {"INR", "USD"}:
                return code
            raise ProviderError("Unsupported position currency", provider="portfolio")
    ticker = str(getattr(position, "ticker", "")).upper()
    region = str(getattr(position, "region", "")).upper()
    return "INR" if ticker.endswith((".NS", ".BO")) or region in {"IN", "IND", "INDIA", "INR"} else "USD"


async def _get_live_fx_rate(
    service: Any,
    source_currency: str,
    target_currency: str,
) -> tuple[float, Dict[str, Any]]:
    """Return one verified live rate, normalizing every FX outage to 503."""
    try:
        seam = getattr(service, "convert_amount_with_provenance", None)
        if callable(seam):
            result = seam(1.0, source_currency, target_currency)
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                raise CurrencyUnavailableError()
            return coerce_live_fx_rate(result.get("rate"))

        get_rate = getattr(service, "get_exchange_rate", None)
        if not callable(get_rate):
            raise CurrencyUnavailableError()
        candidate = get_rate(source_currency, target_currency)
        if inspect.isawaitable(candidate):
            candidate = await candidate
        return coerce_live_fx_rate(candidate)
    except CurrencyUnavailableError:
        raise
    except Exception as exc:
        raise CurrencyUnavailableError() from exc


def _native_position_value(position: Any) -> float:
    """Read a live position value without reviving an explicitly exited row."""
    try:
        quantity_raw = getattr(position, "quantity", None)
        quantity = float(quantity_raw) if quantity_raw is not None else None
    except (TypeError, ValueError):
        quantity = None
    if quantity is not None and quantity <= 0:
        return 0.0
    try:
        price = float(getattr(position, "last_price", 0.0) or 0.0)
    except (TypeError, ValueError):
        price = 0.0
    live_value = (quantity or 0.0) * price
    if math.isfinite(live_value) and live_value > 0:
        return live_value
    try:
        stored = float(getattr(position, "market_value", 0.0) or 0.0)
    except (TypeError, ValueError):
        stored = 0.0
    return stored if math.isfinite(stored) and stored > 0 else 0.0


async def _convert_analytics_positions(
    positions: List[Any],
    *,
    target_currency: str = "INR",
) -> tuple[Dict[str, float], Dict[str, Any]]:
    """Return INR values plus explicit, per-position FX provenance.

    Every non-INR holding is converted before any value is aggregated, including
    a uniform-USD book.  Relative weights would not need FX, but returning INR
    values/provenance under a declared INR base does; a native USD number must
    never be labelled as INR.
    """
    target = str(target_currency or "INR").strip().upper()
    native_values: Dict[str, float] = {}
    source_currencies: Dict[str, str] = {}
    for position in positions:
        live_value = _native_position_value(position)
        if live_value <= 0:
            # Fully exited/zero-value rows remain visible in the portfolio
            # snapshot, but must not trigger FX or enter an active allocation.
            continue
        native_values[position.ticker] = live_value
        source_currencies[position.ticker] = _analytics_position_currency(position)

    unique_sources = set(source_currencies.values())
    needs_conversion = any(source != target for source in unique_sources)
    converted = dict(native_values)
    provenance: Dict[str, Any] = {
        "base_currency": target,
        "source_currencies": sorted(unique_sources),
        "supported_currencies": ["INR", "USD"],
        "aggregation": (
            "empty" if not native_values
            else "per_position_conversion" if needs_conversion
            else "native_uniform"
        ),
        "pairs": {},
        "rate_provider": "currency_service",
    }
    if not needs_conversion:
        for source in unique_sources:
            provenance["pairs"][f"{source}->{target}"] = {
                "rate": 1.0,
                "provenance": "identity",
                "source": "identity",
                "is_fallback": False,
            }
        return converted, provenance

    service = get_currency_service()
    for ticker, value in native_values.items():
        source = source_currencies[ticker]
        if source == target:
            provenance["pairs"][f"{source}->{target}"] = {
                "rate": 1.0,
                "provenance": "identity",
                "source": "identity",
                "is_fallback": False,
            }
            continue
        rate, rate_metadata = await _get_live_fx_rate(
            service, source, target
        )
        converted[ticker] = value * rate
        provenance["pairs"][f"{source}->{target}"] = {
            "rate": rate,
            **rate_metadata,
        }
    if not all(math.isfinite(value) for value in converted.values()):
        raise CurrencyUnavailableError()
    return converted, provenance


async def _load_portfolio_allocation(db: AsyncSession) -> Optional[Dict[str, float]]:
    """
    Load target-currency {ticker: weight} values from actual positions.

    Every non-INR book is converted before aggregation, including a uniform-USD
    book, so the declared INR base and FX provenance remain truthful. Stored or
    equal weights are compatibility fallbacks only when no usable market value
    exists.
    """
    result = await db.execute(select(PortfolioPosition))
    positions = result.scalars().all()
    if not positions:
        return None

    values, _provenance = await _convert_analytics_positions(positions)
    total_mv = sum(value for value in values.values() if math.isfinite(value) and value > 0)
    if total_mv > 0:
        return {t: value / total_mv for t, value in values.items() if value > 0}

    positive_weights: Dict[str, float] = {}
    for position in positions:
        try:
            weight = float(getattr(position, "weight", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if math.isfinite(weight) and weight > 0:
            positive_weights[position.ticker] = weight
    total_weight = sum(positive_weights.values())
    if total_weight > 0:
        return {
            ticker: weight / total_weight
            for ticker, weight in positive_weights.items()
        }

    return {}


def _position_has_positive_value(position: Any) -> bool:
    return _native_position_value(position) > 0


async def _has_positive_portfolio_value(db: AsyncSession) -> bool:
    result = await db.execute(select(PortfolioPosition))
    return any(_position_has_positive_value(position) for position in result.scalars().all())


@router.get("/realized-risk")
async def get_realized_risk(
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers or 'portfolio'"),
    start: Optional[date] = None,
    end: Optional[date] = None,
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Get realized risk metrics for portfolio or individual assets
    """
    try:
        # Validate the complete window before any vendor call.
        start, end = _date_window(start, end, default_days=252)

        # Resolve tickers + weights via resolve_allocation
        try:
            ticker_list, weights = await resolve_allocation(tickers, db)
        except ValueError:
            return {
                "portfolio": {
                    "annual_return": None,
                    "annual_volatility": None,
                    "sharpe_ratio": None,
                    "sortino_ratio": None,
                    "skewness": None,
                    "kurtosis": None,
                    "max_drawdown": None,
                    "var_95": None,
                    "cvar_95": None,
                    "hit_ratio": None
                },
                "positions": {},
                "error": "No portfolio positions found"
            }

        calculation_tickers = _active_weight_tickers(weights)
        if not calculation_tickers:
            return {
                "portfolio": {
                    "annual_return": None,
                    "annual_volatility": None,
                    "sharpe_ratio": None,
                    "sortino_ratio": None,
                    "skewness": None,
                    "kurtosis": None,
                    "max_drawdown": None,
                    "var_95": None,
                    "cvar_95": None,
                    "hit_ratio": None
                },
                "positions": {},
                "universe_coverage": _universe_coverage(ticker_list, []),
                "data_status": "unavailable",
                "error": "No active portfolio weights available for realized risk",
            }

        # Fetch price data for active weights only; the full persisted roster
        # remains the requested coverage universe.
        price_data_dict = await _fetch_price_series_dict(data_service, calculation_tickers, start, end)

        if not price_data_dict:
            logger.warning("No price data available for tickers")
            return {
                "portfolio": {
                    "annual_return": None,
                    "annual_volatility": None,
                    "sharpe_ratio": None,
                    "sortino_ratio": None,
                    "skewness": None,
                    "kurtosis": None,
                    "max_drawdown": None,
                    "var_95": None,
                    "cvar_95": None,
                    "hit_ratio": None
                },
                "positions": {},
                "universe_coverage": _universe_coverage(ticker_list, []),
                "data_status": "unavailable",
                "error": "No price data available"
            }
        
        # Combine price data, restricted to actual holding history so
        # pre-purchase price action is never attributed to the portfolio.
        holdings = await resolve_holdings(db, calculation_tickers)
        masked_dict, effectives = holding_window(price_data_dict, holdings)
        wiped = sorted(set(price_data_dict) - set(masked_dict))
        price_data = pd.DataFrame(masked_dict)
        if price_data.empty:
            return {
                "portfolio": {
                    "annual_return": None,
                    "annual_volatility": None,
                    "sharpe_ratio": None,
                    "sortino_ratio": None,
                    "skewness": None,
                    "kurtosis": None,
                    "max_drawdown": None,
                    "var_95": None,
                    "cvar_95": None,
                    "hit_ratio": None
                },
                "positions": {},
                "universe_coverage": _universe_coverage(ticker_list, []),
                "data_status": "unavailable",
                "error": "No price data within the current holding period",
            }
        covered_days = int(len(price_data))
        per_ticker = {
            t: {
                "raw_days": int(len(s)) if s is not None else 0,
                "masked_days": int(len(masked_dict[t])) if t in masked_dict and masked_dict[t] is not None else 0,
                "limited_history": bool(getattr(s, "attrs", {}).get("limited_history", False)),
                "coverage_reason": getattr(s, "attrs", {}).get("coverage_reason"),
            }
            for t, s in price_data_dict.items()
        }
        history_coverage = holding_coverage(effectives, start, end, covered_days, per_ticker)

        # --- Instrument risk on FULL exchange history (DSP-10) --------------
        # Risk characteristics belong to the assets, not the ownership
        # tenure: the covariance/vol/Sharpe of NTPC.NS does not change with
        # when the user bought it. Realized P&L above stays holding-truthed;
        # this block measures the current book on the full fetched window
        # (~1Y), so a young portfolio no longer renders N/A risk metrics.
        full_df = pd.DataFrame({
            t: s for t, s in price_data_dict.items()
            if isinstance(s, pd.Series) and len(s) > 1
        })
        instrument_risk: Dict[str, Any] = {}
        full_days = int(len(full_df)) if not full_df.empty else 0
        if full_days >= 2:
            full_metrics = await analytics_engine.calculate_portfolio_metrics(full_df, weights)
            full_portfolio = {
                "annual_return": full_metrics.get("annual_return"),
                "annual_volatility": full_metrics.get("annual_volatility"),
                "sharpe_ratio": full_metrics.get("sharpe_ratio"),
                "sortino_ratio": full_metrics.get("sortino_ratio"),
                "max_drawdown": full_metrics.get("max_drawdown"),
                "var_95": full_metrics.get("var_95"),
                "days": full_days,
            }
            apply_annualization_gate(
                full_portfolio,
                ["annual_return", "annual_volatility", "sharpe_ratio", "sortino_ratio"],
                full_days,
            )
            full_positions: Dict[str, Any] = {}
            for tkr, pm in (full_metrics.get("positions") or {}).items():
                own_series = price_data_dict.get(tkr)
                own_days = int(len(own_series)) if own_series is not None else 0
                total_ret = None
                if own_series is not None and len(own_series) > 1:
                    s0 = float(pd.Series(own_series).iloc[0])
                    s1 = float(pd.Series(own_series).iloc[-1])
                    total_ret = round((s1 / s0) - 1.0, 6) if s0 else None
                row = {
                    "annual_volatility": pm.get("annual_volatility"),
                    "sharpe_ratio": pm.get("sharpe_ratio"),
                    "max_drawdown": pm.get("max_drawdown"),
                    "total_return": total_ret,
                    "data_points": own_days,
                }
                apply_annualization_gate(row, ["annual_volatility", "sharpe_ratio"], own_days)
                full_positions[tkr] = row
            instrument_risk = {"portfolio": full_portfolio, "positions": full_positions}

        history_coverage["full_history_days"] = full_days
        if full_days:
            try:
                history_coverage["full_history_start"] = str(full_df.index.min().date())
            except Exception:
                history_coverage["full_history_start"] = None
        else:
            history_coverage["full_history_start"] = None

        # Calculate portfolio metrics using analytics engine
        metrics = await analytics_engine.calculate_portfolio_metrics(price_data, weights)
        # Coverage describes measured return observations, not merely the union
        # of price rows.  An interior gap contributes no return and must not
        # make a short active sample look fully covered.
        covered_days = int(metrics.get("active_observations") or metrics.get("observations") or 0)
        history_coverage["covered_days"] = covered_days
        history_coverage["annualized"] = covered_days >= MIN_ANNUALIZE_DAYS
        
        # Format response — absent engine keys are None, never fabricated constants.
        portfolio_metrics = {
            "annual_return": metrics.get("annual_return"),
            "annual_volatility": metrics.get("annual_volatility"),
            "sharpe_ratio": metrics.get("sharpe_ratio"),
            "sortino_ratio": metrics.get("sortino_ratio"),
            "skewness": metrics.get("skewness"),
            "kurtosis": metrics.get("kurtosis"),
            "max_drawdown": metrics.get("max_drawdown"),
            "var_95": metrics.get("var_95"),
            "cvar_95": metrics.get("cvar_95"),
            "hit_ratio": metrics.get("hit_ratio")
        }
        
        # Position-level metrics & data quality warnings
        positions = {}
        warnings_list = []
        intersection = history_coverage.get("intersection_start") or history_coverage.get("effective_start")
        for ticker, pos_metrics in metrics.get("positions", {}).items():
            is_limited = pos_metrics.get("is_limited_history", False)
            data_pts = pos_metrics.get("data_points", 0)
            if is_limited:
                own_start = effectives.get(ticker)
                raw_s = price_data_dict.get(ticker)
                raw_len = int(len(raw_s)) if raw_s is not None else 0
                masked_s = masked_dict.get(ticker)
                masked_len = int(len(masked_s)) if masked_s is not None else 0
                if raw_len and raw_len < MIN_ANNUALIZE_DAYS:
                    notice = (
                        f"{ticker} has only {data_pts} trading days of data available on exchange feeds. "
                        "Historical risk ratios are constrained."
                    )
                elif masked_len < raw_len and intersection and own_start and intersection > own_start:
                    notice = (
                        f"{ticker} realized P&L covers {covered_days} trading days "
                        f"since {intersection}; {ticker} held since {own_start}; instrument risk "
                        f"uses full {history_coverage.get('full_history_days')} trading days "
                        "of exchange history."
                    )
                elif history_coverage.get("truncated"):
                    notice = (
                        f"{ticker} realized P&L covers only {data_pts} trading days "
                        f"(held since {history_coverage.get('effective_start')}); instrument risk "
                        f"metrics use the full {history_coverage.get('full_history_days')} trading days "
                        "of exchange history."
                    )
                else:
                    notice = (
                        f"{ticker} has only {data_pts} trading days of data available on exchange feeds. "
                        "Historical risk ratios are constrained."
                    )
                warnings_list.append({
                    "ticker": ticker,
                    "data_points": data_pts,
                    "message": notice,
                })
            positions[ticker] = {
                "annual_return": pos_metrics.get("annual_return"),
                "annual_volatility": pos_metrics.get("annual_volatility"),
                "sharpe_ratio": pos_metrics.get("sharpe_ratio"),
                "max_drawdown": pos_metrics.get("max_drawdown"),
                "var_95": pos_metrics.get("var_95"),
                "weight": pos_metrics.get("weight", 0),
                "data_points": data_pts,
                "is_limited_history": is_limited,
                "history_warning": pos_metrics.get("history_warning")
            }

        # Short holding history must not annualize into triple-digit artefacts.
        apply_annualization_gate(
            portfolio_metrics,
            ["annual_return", "annual_volatility", "sharpe_ratio", "sortino_ratio"],
            covered_days,
        )
        for pos_payload in positions.values():
            apply_annualization_gate(
                pos_payload,
                ["annual_return", "annual_volatility", "sharpe_ratio"],
                int(pos_payload.get("data_points", 0) or 0),
            )
        for ticker in wiped:
            warnings_list.append({
                "ticker": ticker,
                "data_points": 0,
                "message": (
                    f"{ticker} has no price data within the current holding period "
                    f"(held since {effectives.get(ticker) or history_coverage.get('effective_start')}); "
                    "excluded from realized metrics."
                ),
            })

        usable_tickers = [
            ticker
            for ticker, position in positions.items()
            if int(position.get("data_points", 0) or 0) >= 2
        ]
        coverage = _universe_coverage(ticker_list, usable_tickers)
        limited_history = any(
            bool(position.get("is_limited_history"))
            for position in positions.values()
            if isinstance(position, Mapping)
        )
        if coverage["status"] == "unavailable":
            data_status = "unavailable"
        elif coverage["status"] == "partial" or limited_history:
            data_status = "partial"
        else:
            data_status = "available"
        return {
            "portfolio": portfolio_metrics,
            "positions": positions,
            "instrument_risk": instrument_risk,
            "universe_coverage": coverage,
            "data_status": data_status,
            "warnings": warnings_list,
            "data_range": {"start": start, "end": end},
            "latest_observation_date": _latest_observation_date(price_data),
            "history_coverage": history_coverage,
            "methodology": "Real-time calculations using quantstats and statistical models"
        }
        
    except HTTPException:
        raise
    except Exception:
        logger.error("Realized risk request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/forecast-risk")
async def get_forecast_risk(
    model: str = Query(default="GARCH", description="Risk model: EWMA, GARCH, or EGARCH"),
    horizon: int = Query(default=1, ge=1, le=30, description="Forecast horizon in days"),
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers"),
    start: Optional[date] = None,
    end: Optional[date] = None,
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """Get forecast risk metrics using a validated model name."""
    try:
        model = _validate_model_name(model, _VOLATILITY_MODELS)
        start, end = _date_window(start, end, default_days=252)
        # Resolve tickers & allocation via resolve_allocation
        try:
            ticker_list, allocation = await resolve_allocation(tickers, db)
        except ValueError:
            return {
                "model": model,
                "horizon": horizon,
                "portfolio": {
                    "volatility_forecast": None,
                    "var_forecast": None,
                    "cvar_forecast": None,
                    "confidence_interval": None
                },
                "positions": {},
                "model_params": {"p": 1, "q": 1, "type": model},
                "error": "No portfolio positions found"
            }
        
        calculation_tickers = _active_weight_tickers(allocation)
        if not calculation_tickers:
            return {
                "model": model,
                "horizon": horizon,
                "portfolio": {
                    "volatility_forecast": None,
                    "var_forecast": None,
                    "cvar_forecast": None,
                    "confidence_interval": None
                },
                "positions": {},
                "universe_coverage": _universe_coverage(ticker_list, []),
                "data_status": "unavailable",
                "error": "No active portfolio weights available for forecast",
            }

        # Fetch price data for active weights only; the full persisted roster
        # remains the requested coverage universe.
        price_data_dict = await _fetch_price_series_dict(data_service, calculation_tickers, start, end)
        
        if not price_data_dict:
            return {
                "model": model,
                "horizon": horizon,
                "portfolio": {
                    "volatility_forecast": None,
                    "var_forecast": None,
                    "cvar_forecast": None,
                    "confidence_interval": None
                },
                "positions": {},
                "model_params": {"p": 1, "q": 1, "type": model},
                "universe_coverage": _universe_coverage(ticker_list, []),
                "data_status": "unavailable",
                "error": "No price data available for forecast"
            }
        
        # Combine price data
        price_data = pd.DataFrame(price_data_dict)

        # Preserve the active-price mask for the forecast leg as well.  A
        # pre-listing or interior missing price is not an economic 0% return.
        cleaned_prices = price_data.sort_index().replace([np.inf, -np.inf], np.nan)
        returns = cleaned_prices.pct_change(fill_method=None).iloc[1:]
        portfolio_returns = aggregate_active_returns(returns, allocation or {})

        # Calculate portfolio volatility forecast using analytics engine
        forecast_result = await analytics_engine.forecast_volatility(portfolio_returns, model, horizon)
        
        # Position-level forecasts using active price history
        positions = {}
        warnings_list = []
        for ticker in price_data.columns:
            try:
                raw_s = price_data[ticker].replace([np.inf, -np.inf], np.nan)
                data_pts = int(raw_s.notna().sum())
                if data_pts >= 30:
                    # Keep the original union index so an interior gap does
                    # not become a synthetic multi-day return.
                    ticker_rets = raw_s.pct_change(fill_method=None).dropna()
                    ticker_forecast = await analytics_engine.forecast_volatility(ticker_rets, model, horizon)
                    vol_fc = ticker_forecast.get("volatility_forecast")
                    var_fc = ticker_forecast.get("var_forecast")
                    is_limited = False
                    warning = None
                else:
                    ticker_rets = raw_s.pct_change(fill_method=None).dropna()
                    h_factor = np.sqrt(max(1, horizon) / 252.0)
                    vol_fc = float(ticker_rets.std() * np.sqrt(252)) if len(ticker_rets) > 1 else None
                    var_fc = float(-vol_fc * 1.645 * h_factor) if vol_fc is not None else None
                    is_limited = True
                    warning = f"Only {data_pts} trading days available on exchange feed"
                    warnings_list.append({
                        "ticker": ticker,
                        "data_points": data_pts,
                        "message": f"{ticker} has only {data_pts} trading days available. Forecast volatility uses sample volatility."
                    })
                
                positions[ticker] = {
                    "volatility_forecast": vol_fc,
                    "var_forecast": var_fc,
                    "is_limited_history": is_limited,
                    "history_warning": warning,
                    "data_points": data_pts
                }
            except Exception:
                logger.error("Volatility forecast leg failed")
                positions[ticker] = {
                    "volatility_forecast": None,
                    "var_forecast": None,
                    "is_limited_history": True,
                    "history_warning": "Forecast unavailable",
                    "data_points": 0
                }
        
        usable_positions = [
            ticker for ticker, position in positions.items()
            if int(position.get("data_points", 0) or 0) >= 2
            and (
                position.get("volatility_forecast") is not None
                or position.get("var_forecast") is not None
            )
        ]
        coverage = _universe_coverage(ticker_list, usable_positions)
        limited_history = any(
            bool(position.get("is_limited_history"))
            for position in positions.values()
            if isinstance(position, Mapping)
        )
        portfolio_forecast_usable = any(
            forecast_result.get(field) is not None
            for field in ("volatility_forecast", "var_forecast", "cvar_forecast")
        )
        response = {
            "model": model,
            "horizon": horizon,
            "portfolio": {
                "volatility_forecast": forecast_result.get("volatility_forecast"),
                "var_forecast": forecast_result.get("var_forecast"),
                "cvar_forecast": forecast_result.get("cvar_forecast"),
                "confidence_interval": forecast_result.get("confidence_interval"),
                "term_structure": forecast_result.get("term_structure", [])
            },
            "positions": positions,
            "universe_coverage": coverage,
            "data_status": (
                "unavailable" if coverage["status"] == "unavailable"
                else "partial" if coverage["status"] == "partial" or limited_history or forecast_result.get("error") or not portfolio_forecast_usable
                else "available"
            ),
            "warnings": warnings_list,
            "model_params": forecast_result.get("model_params", {"p": 1, "q": 1, "type": model}),
            "data_range": {"start": start, "end": end},
            "latest_observation_date": _latest_observation_date(price_data),
            "methodology": f"Volatility forecasting using {model} model with {horizon}-day horizon"
        }
        if forecast_result.get("error"):
            response["error"] = forecast_result["error"]
        return response
        
    except HTTPException:
        raise
    except Exception:
        logger.error("Forecast risk request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/factor-exposure")
async def get_factor_exposure(
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers"),
    lookback_days: int = Query(default=252, ge=30, le=756, description="Lookback period in days"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    benchmark_service: BenchmarkService = Depends(get_benchmark_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Get factor exposure analysis
    """
    try:
        # Resolve tickers & allocation via resolve_allocation
        try:
            ticker_list, allocation = await resolve_allocation(tickers, db)
        except ValueError:
            return {
                "portfolio": {
                    "alpha": None,
                    "market": None
                },
                "positions": {},
                "r_squared": None,
                "adjusted_r_squared": None,
                "universe_coverage": _universe_coverage([], []),
                "data_status": "unavailable",
                "error": "No portfolio positions found"
            }
        
        calculation_tickers = _active_weight_tickers(allocation)
        if not calculation_tickers:
            return {
                "portfolio": {"alpha": None, "market": None},
                "positions": {},
                "r_squared": None,
                "adjusted_r_squared": None,
                "universe_coverage": _universe_coverage(ticker_list, []),
                "data_status": "unavailable",
                "error": "No active portfolio weights available for factor analysis",
            }

        # Calculate date range
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=lookback_days)).strftime('%Y-%m-%d')
        
        # Fetch price data for active weights only; the full persisted roster
        # remains the requested coverage universe.
        price_data_dict = await _fetch_price_series_dict(data_service, calculation_tickers, start, end)
        
        if not price_data_dict:
            return {
                "portfolio": {
                    "alpha": None,
                    "market": None
                },
                "positions": {},
                "r_squared": None,
                "adjusted_r_squared": None,
                "universe_coverage": _universe_coverage(ticker_list, []),
                "data_status": "unavailable",
                "error": "No price data available for factor analysis"
            }
        
        # Factor exposure is an instrument-characteristic question: beta and
        # R² describe how the ASSETS co-move with the market, independent of
        # when the user bought them (DSP-10). Regressing on the holding-window
        # mask left ~6 observations, which collapsed into the engine's
        # degenerate fallback (beta exactly 1.0, R² 0.0) rendered as
        # "Market-Like" for every position. Compute on full history; the
        # holding window stays disclosed via history_coverage.
        holdings = await resolve_holdings(db, calculation_tickers)
        _, effectives = holding_window(price_data_dict, holdings)
        price_data = pd.DataFrame(price_data_dict)
        factor_weights = {
            ticker: float(weight)
            for ticker, weight in allocation.items()
            if ticker in price_data.columns
        }
        factor_weight_total = sum(factor_weights.values())
        if factor_weight_total > 0:
            factor_weights = {
                ticker: weight / factor_weight_total
                for ticker, weight in factor_weights.items()
            }
        per_ticker = {
            ticker: {
                "raw_days": int(len(series)) if series is not None else 0,
                "masked_days": int(len(series)) if series is not None else 0,
            }
            for ticker, series in price_data_dict.items()
        }
        history_coverage = holding_coverage(
            effectives, start, end, int(len(price_data)), per_ticker
        )

        # Fetch benchmark returns via BenchmarkService (^NSEI)
        benchmark_returns = None
        try:
            benchmark_returns = await benchmark_service.get_returns(start=start, end=end)
        except Exception:
            logger.warning("Benchmark data unavailable")
        history_coverage["calculation_basis"] = "full_exchange_history_current_weights"
        if benchmark_returns is not None:
            benchmark_series = benchmark_returns
            if isinstance(benchmark_series, pd.DataFrame):
                benchmark_series = benchmark_series.iloc[:, 0]
            if isinstance(benchmark_series, pd.Series):
                if benchmark_series.abs().gt(1.0).any():
                    benchmark_series = benchmark_series.pct_change(fill_method=None).dropna()
                asset_returns = price_data.pct_change(fill_method=None).iloc[1:]
                history_coverage["benchmark_overlap_observations"] = int(
                    len(asset_returns.index.intersection(benchmark_series.index))
                )

        # Perform factor exposure analysis using analytics engine
        factor_result = await analytics_engine.factor_exposure_analysis(
            price_data, 
            benchmark_data=benchmark_returns,
            weights=factor_weights
        )

        # Collect warnings for assets with limited history
        warnings_list = [
            {
                "ticker": t,
                "data_points": p.get("data_points", 0),
                "message": f"{t} has only {p.get('data_points', 0)} trading days. Factor regression beta and alpha may be constrained."
            }
            for t, p in factor_result.get("positions", {}).items()
            if p.get("is_limited_history")
        ]
        
        factor_positions = factor_result.get("positions", {}) or {}
        usable_positions = {
            ticker: position
            for ticker, position in factor_positions.items()
            if isinstance(position, Mapping)
            and int(position.get("data_points", 0) or 0) > 0
            and not position.get("error")
            and any(
                position.get(field) is not None
                for field in ("alpha", "beta", "market", "r_squared")
            )
        }
        coverage = _universe_coverage(ticker_list, usable_positions.keys())
        limited_history = any(
            bool(position.get("is_limited_history"))
            for position in factor_positions.values()
            if isinstance(position, Mapping)
        )
        portfolio_factor = factor_result.get("portfolio", {})
        portfolio_factor_usable = isinstance(portfolio_factor, Mapping) and any(
            portfolio_factor.get(field) is not None
            for field in ("alpha", "market", "beta", "r_squared")
        )
        if coverage["status"] == "unavailable":
            data_status = "unavailable"
        elif coverage["status"] == "partial" or limited_history or not portfolio_factor_usable or factor_result.get("error"):
            data_status = "partial"
        else:
            data_status = "available"
        return {
            "portfolio": factor_result.get("portfolio", {}),
            "positions": factor_result.get("positions", {}),
            "universe_coverage": coverage,
            "data_status": data_status,
            "warnings": warnings_list,
            "r_squared": factor_result.get("r_squared", 0.0),
            "adjusted_r_squared": factor_result.get("adjusted_r_squared", 0.0),
            "data_range": {"start": start, "end": end},
            "latest_observation_date": _latest_observation_date(price_data),
            "history_coverage": history_coverage,
            "lookback_days": lookback_days,
            "methodology": "Statistical factor model with market benchmark regression"
        }
        
    except HTTPException:
        raise
    except Exception:
        logger.error("Factor exposure request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


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
        requested_tickers = await _load_portfolio_tickers(db)
        if not weights:
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
                "by_sector": {},
                "error": "No portfolio positions found",
                "data_status": "unavailable",
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "zero_metrics": True
            }
        
        # Calculate concentration metrics using analytics engine
        concentration_result = await analytics_engine.concentration_analysis(weights)
        
        # Sector allocation from actual position metadata, weighted by the SAME
        # market-value weights the metrics above use (stored `weight` can be stale).
        sector_result = await db.execute(select(PortfolioPosition))
        positions = sector_result.scalars().all()
        by_sector = {}
        for pos in positions:
            w = weights.get(pos.ticker, 0.0)
            if w <= 0:
                continue
            sector = pos.sector or "Unknown"
            by_sector[sector] = round(by_sector.get(sector, 0.0) + w, 4)
        
        coverage = _universe_coverage(requested_tickers, concentration_result.get("by_weight", {}).keys())
        return {
            "largest_position": concentration_result.get("largest_position", 0.0),
            "top_3": concentration_result.get("top_3", 0.0),
            "top_5": concentration_result.get("top_5", 0.0),
            "top_10": concentration_result.get("top_10", 0.0),
            "herfindahl_index": concentration_result.get("herfindahl_index", 0.0),
            "effective_positions": concentration_result.get("effective_positions", 0.0),
            "diversification_score": concentration_result.get("diversification_score", 0.0),
            "diversification_ratio": concentration_result.get("diversification_ratio", 1.0),
            "gini_coefficient": concentration_result.get("gini_coefficient", 0.0),
            "by_weight": concentration_result.get("by_weight", {}),
            "by_sector": by_sector,
            "universe_coverage": coverage,
            "data_status": coverage["status"],
            "methodology": "Concentration analysis using Herfindahl-Hirschman Index (HHI), Effective Positions (N_eff), and Lorenz Gini Coefficient"
        }
        
    except HTTPException:
        raise
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except Exception:
        logger.error("Concentration request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


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
        requested_tickers = await _load_portfolio_tickers(db)
        if not allocation:
            return {
                "overall_score": None,
                "liquidation_time_days": None,
                "risk_level": None,
                "by_position": {},
                "volume_stats": {},
                "error": "No portfolio positions found",
                "data_status": "unavailable",
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "zero_metrics": True
            }
        if not await _has_positive_portfolio_value(db):
            return {
                "overall_score": None,
                "liquidation_time_days": None,
                "risk_level": None,
                "by_position": {},
                "volume_stats": {},
                "error": "No positive portfolio market value available for liquidity analysis",
                "data_status": "unavailable",
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "zero_metrics": True,
            }
        tickers = _active_weight_tickers(allocation)
        
        # Fetch price and volume data + market caps for liquidity analysis concurrently
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        sem = asyncio.Semaphore(5)
        async def fetch_liq(ticker: str):
            async with sem:
                try:
                    df = await data_service.fetch_historical_data(ticker, start, end)
                except Exception:
                    logger.error("Liquidity price history fetch failed for %s", ticker)
                    df = None
                try:
                    quote = await data_service.fetch_quote(ticker)
                except Exception:
                    logger.error("Liquidity quote fetch failed for %s", ticker)
                    quote = None
                mc = quote.get('market_cap') if isinstance(quote, dict) else None
                return ticker, df, mc

        liq_results = await asyncio.gather(*[fetch_liq(t) for t in tickers])
        price_data_dict = {}
        market_caps_dict = {}
        for ticker, df, mc in liq_results:
            if mc:
                market_caps_dict[ticker] = mc
            if df is not None and not df.empty:
                price_col = next(
                    (c for c in ("adj_close", "close", "Adj Close", "Close") if c in df.columns),
                    None,
                )
                vol_col = 'Volume' if 'Volume' in df.columns else ('volume' if 'volume' in df.columns else None)
                if vol_col and price_col in df.columns:
                    price_data_dict[ticker] = df[[price_col, vol_col]].rename(columns={vol_col: 'Volume', price_col: 'Close'})
                elif price_col in df.columns:
                    price_data_dict[ticker] = df[[price_col]].rename(columns={price_col: 'Close'})
        
        if not price_data_dict:
            return {
                "overall_score": None,
                "liquidation_time_days": None,
                "risk_level": None,
                "by_position": {},
                "volume_stats": {},
                "error": "No price data available for liquidity analysis",
                "data_status": "unavailable",
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "zero_metrics": True
            }
        
        # Calculate liquidity metrics using analytics engine
        liquidity_result = await analytics_engine.liquidity_analysis(price_data_dict, market_caps=market_caps_dict)
        coverage = _universe_coverage(requested_tickers, liquidity_result.get("by_position", {}).keys())

        return {
            "overall_score": liquidity_result.get("overall_score"),
            "liquidation_time_days": liquidity_result.get("liquidation_time_days"),
            "risk_level": liquidity_result.get("risk_level"),
            "by_position": liquidity_result.get("by_position", {}),
            "volume_stats": liquidity_result.get("volume_stats", {}),
            "universe_coverage": coverage,
            "data_status": coverage["status"],
            "methodology": "Liquidity scoring based on trading volume and market capitalization"
        }
        
    except HTTPException:
        raise
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except Exception:
        logger.error("Liquidity request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


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
        if request.tickers is not None and len(request.tickers) > _MAX_TICKERS:
            raise HTTPException(status_code=422, detail=f"At most {_MAX_TICKERS} tickers are allowed")
        requested_csv = ",".join(request.tickers) if request.tickers else None
        try:
            ticker_list, weights = await resolve_allocation(requested_csv, db)
        except ValueError:
            return {
                "scenario": request.scenario,
                "max_drawdown": None,
                "portfolio_impact": None,
                "position_impacts": {},
                "recovery_time": None,
                "error": "No portfolio positions found"
            }
        if not weights:
            return {
                "scenario": request.scenario,
                "max_drawdown": None,
                "portfolio_impact": None,
                "position_impacts": {},
                "recovery_time": None,
                "error": "No portfolio positions found for stress testing"
            }
        
        # Fetch price data for stress testing concurrently
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=756)).strftime('%Y-%m-%d')  # 3 years for stress testing
        
        price_data_dict = await _fetch_price_series_dict(data_service, ticker_list, start, end)
        
        if not price_data_dict:
            return {
                "scenario": request.scenario,
                "max_drawdown": None,
                "portfolio_impact": None,
                "position_impacts": {},
                "recovery_time": None,
                "error": "No price data available for stress testing"
            }
        
        # Combine price data
        price_data = pd.DataFrame(price_data_dict)
        
        # Query position sectors from DB
        pos_res = await db.execute(select(PortfolioPosition))
        positions_db = pos_res.scalars().all()
        sectors = {p.ticker: (p.sector or "Exchange Traded Fund") for p in positions_db}
        
        # Run multi-factor sector-elastic stress test using analytics engine
        stress_result = await analytics_engine.stress_test(price_data, weights, request.scenario, sectors=sectors)
        stress_result = dict(stress_result)
        stress_result["universe_coverage"] = _universe_coverage(ticker_list, price_data_dict.keys())
        stress_result["data_status"] = (
            "available"
            if not stress_result["universe_coverage"]["missing_tickers"]
            else "partial"
        )
        return stress_result
        
    except HTTPException:
        raise
    except Exception:
        logger.error("Stress test request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/volatility-sizing")
async def get_volatility_sizing(
    model: str = Query(default="EWMA", description="Volatility model"),
    target_volatility: float = Query(default=0.15, gt=0, lt=1, description="Target volatility"),
    portfolio_value: Optional[float] = Query(
        default=None,
        gt=0,
        description="Explicit INR portfolio value for sizing calculation",
    ),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine)
) -> Dict:
    """
    Get volatility-adjusted position sizing recommendations
    """
    try:
        model = _validate_model_name(model, _VOLATILITY_MODELS)
        if not math.isfinite(float(target_volatility)) or not 0 < float(target_volatility) < 1:
            raise HTTPException(status_code=422, detail="target_volatility must be finite and between 0 and 1")
        if portfolio_value is not None and (
            not math.isfinite(float(portfolio_value)) or float(portfolio_value) <= 0
        ):
            raise HTTPException(status_code=422, detail="portfolio_value must be positive and finite")
        pos_result = await db.execute(select(PortfolioPosition))
        positions_list = pos_result.scalars().all()
        requested_tickers = [position.ticker for position in positions_list]
        if not positions_list:
            return {
                "current_weights": {},
                "recommended_weights": {},
                "trades": {},
                "target_volatility": target_volatility,
                "currency": "INR",
                "base_currency": "INR",
                "currency_provenance": {
                    "base_currency": "INR",
                    "aggregation": "empty",
                    "source_currencies": [],
                    "pairs": {},
                },
                "error": "No portfolio positions found for volatility sizing"
            }

        # Use one FX snapshot for both current weights and the INR valuation
        # budget.  Re-querying/re-converting could otherwise split the trade
        # sizing basis when live rates move between calls.
        converted_position_values, allocation_provenance = await _convert_analytics_positions(
            positions_list, target_currency="INR"
        )
        converted_total = sum(
            value for value in converted_position_values.values()
            if math.isfinite(value) and value > 0
        )
        if converted_total > 0:
            weights = {
                ticker: value / converted_total
                for ticker, value in converted_position_values.items()
                if value > 0
            }
        else:
            stored_total = sum(float(position.weight or 0.0) for position in positions_list)
            if stored_total > 0:
                weights = {
                    position.ticker: float(position.weight or 0.0) / stored_total
                    for position in positions_list
                }
            else:
                equal_weight = 1.0 / len(positions_list)
                weights = {position.ticker: equal_weight for position in positions_list}

        # Calculate actual INR portfolio value from DB if not explicitly passed.
        if portfolio_value is None:
            resolved_pv = converted_total
            currency_provenance = allocation_provenance
        else:
            resolved_pv = portfolio_value
            currency_provenance = {
                "base_currency": "INR",
                "aggregation": "explicit_input",
                "source_currencies": ["INR"],
                "pairs": {
                    "INR->INR": {
                        "rate": 1.0,
                        "provenance": "explicit_input",
                        "source": "caller",
                        "is_fallback": False,
                    }
                },
            }
        if resolved_pv is None or resolved_pv <= 0:
            return {
                "current_weights": weights,
                "recommended_weights": weights,
                "trades": {ticker: {"shares_delta": 0, "amount": 0.0} for ticker in weights.keys()},
                "target_volatility": target_volatility,
                "currency": "INR",
                "base_currency": "INR",
                "currency_provenance": currency_provenance,
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "data_unavailable_tickers": list(requested_tickers),
                "error": "Portfolio market value unavailable; pass an explicit portfolio_value or refresh position prices"
            }
        
        # Fetch price data for volatility sizing concurrently
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=252)).strftime('%Y-%m-%d')  # 1 year
        
        calculation_tickers = _active_weight_tickers(weights)
        price_data_dict = await _fetch_price_series_dict(data_service, calculation_tickers, start, end)
        
        if not price_data_dict:
            return {
                "current_weights": weights,
                "recommended_weights": weights,
                "trades": {ticker: {"shares_delta": 0, "amount": 0} for ticker in weights.keys()},
                "target_volatility": target_volatility,
                "currency": "INR",
                "base_currency": "INR",
                "currency_provenance": currency_provenance,
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "data_unavailable_tickers": list(requested_tickers),
                "error": "No price data available for volatility sizing"
            }
        
        # Combine price data and remove legs with no measured return.
        price_data = pd.DataFrame(price_data_dict)
        sizing_returns = price_data.pct_change(fill_method=None).iloc[1:]
        return_observations = {
            ticker: int(sizing_returns[ticker].notna().sum())
            for ticker in price_data.columns
        }
        usable_tickers = [ticker for ticker, count in return_observations.items() if count >= 2]
        if not usable_tickers:
            return {
                "current_weights": weights,
                "recommended_weights": weights,
                "trades": {ticker: {"shares_delta": 0, "amount": 0} for ticker in weights.keys()},
                "target_volatility": target_volatility,
                "currency": "INR",
                "base_currency": "INR",
                "currency_provenance": currency_provenance,
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "data_unavailable_tickers": list(requested_tickers),
                "error": "No finite return observations for volatility sizing",
            }
        price_data = price_data.loc[:, usable_tickers]
        sizing_weights = {
            ticker: float(weights[ticker])
            for ticker in usable_tickers
            if ticker in weights
        }
        sizing_weight_total = sum(sizing_weights.values())
        if sizing_weight_total > 0:
            sizing_weights = {
                ticker: weight / sizing_weight_total
                for ticker, weight in sizing_weights.items()
            }
        
        # Calculate volatility sizing using analytics engine
        sizing_result = await analytics_engine.volatility_sizing(
            price_data, 
            sizing_weights,
            model, 
            target_volatility, 
            portfolio_value=resolved_pv
        )
        if not isinstance(sizing_result, dict):
            raise RuntimeError("Volatility sizing result unavailable")
        response = dict(sizing_result)
        recommended_tickers = list((sizing_result.get("recommended_weights") or {}).keys())
        available_tickers = [
            ticker for ticker in usable_tickers
            if not recommended_tickers or ticker in recommended_tickers
        ]
        if not available_tickers:
            available_tickers = [
                ticker for ticker in recommended_tickers if ticker in usable_tickers
            ]
        coverage = _universe_coverage(requested_tickers, available_tickers)
        limited_history = any(
            count < MIN_ANNUALIZE_DAYS for count in return_observations.values()
        )
        sizing_status = (
            "unavailable" if coverage["status"] == "unavailable"
            else "partial" if coverage["status"] == "partial" or limited_history or sizing_result.get("error")
            else "available"
        )
        response.update({
            "portfolio_value": round(float(resolved_pv), 2),
            "portfolio_value_currency": "INR",
            "currency": "INR",
            "base_currency": "INR",
            "currency_provenance": currency_provenance,
            "universe_coverage": coverage,
            "data_status": sizing_status,
            "data_unavailable_tickers": coverage["missing_tickers"],
            "weight_basis": "available_universe_renormalized" if coverage["missing_tickers"] else "full_universe",
        })
        return response
        
    except HTTPException:
        raise
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except Exception:
        logger.error("Volatility sizing request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/risk-score")
async def get_risk_score(
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine),
    benchmark_service: BenchmarkService = Depends(get_benchmark_service)
) -> Dict:
    """
    Get overall portfolio risk score
    """
    try:
        # Actual DB positions
        weights = await _load_portfolio_allocation(db)
        requested_tickers = await _load_portfolio_tickers(db)
        if not weights:
            return {
                "overall_score": None,
                "risk_level": None,
                "change": 0,
                "components": {},
                "alerts": ["No portfolio positions found for risk scoring"],
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "error": "No portfolio positions found"
            }
        if not await _has_positive_portfolio_value(db):
            return {
                "overall_score": None,
                "risk_level": None,
                "change": 0,
                "components": {},
                "alerts": ["No positive portfolio market value available for risk scoring"],
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "error": "No positive portfolio market value available for risk scoring",
            }
        
        # Fetch price data for risk scoring
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=252)).strftime('%Y-%m-%d')  # 1 year
        
        price_data_dict = {}
        calculation_tickers = _active_weight_tickers(weights)
        for ticker in calculation_tickers:
            try:
                df = await data_service.fetch_historical_data(ticker, start, end)
            except Exception:
                logger.warning("Risk-score history unavailable for %s", ticker)
                continue
            if df is not None and not df.empty:
                _assign_price(price_data_dict, ticker, df)
        
        if not price_data_dict:
            return {
                "overall_score": None,
                "risk_level": None,
                "change": 0,
                "components": {},
                "alerts": ["Insufficient data for comprehensive risk analysis"],
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "error": "No price data available for risk scoring"
            }
        
        # Combine price data, restricted to actual holding history.
        raw_price_data_dict = dict(price_data_dict)
        holdings = await resolve_holdings(db, calculation_tickers)
        price_data_dict, effectives = holding_window(price_data_dict, holdings)
        price_data = pd.DataFrame(price_data_dict)
        if price_data.empty:
            return {
                "overall_score": None,
                "risk_level": None,
                "change": 0,
                "components": {},
                "alerts": ["Insufficient data for comprehensive risk analysis"],
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "error": "No usable price data within the holding window for risk scoring",
            }
        per_ticker = {
            ticker: {
                "raw_days": int(len(raw_price_data_dict.get(ticker))) if ticker in raw_price_data_dict and raw_price_data_dict.get(ticker) is not None else 0,
                "masked_days": int(len(price_data_dict.get(ticker))) if ticker in price_data_dict and price_data_dict.get(ticker) is not None else 0,
                "limited_history": bool(getattr(raw_price_data_dict.get(ticker), "attrs", {}).get("limited_history", False)),
                "coverage_reason": getattr(raw_price_data_dict.get(ticker), "attrs", {}).get("coverage_reason"),
            }
            for ticker in requested_tickers
        }
        risk_returns = price_data.pct_change(fill_method=None).iloc[1:]
        return_observations = {
            ticker: int(risk_returns[ticker].notna().sum())
            for ticker in requested_tickers
            if ticker in risk_returns.columns
        }
        usable_tickers = [ticker for ticker, count in return_observations.items() if count >= 2]
        if not usable_tickers:
            return {
                "overall_score": None,
                "risk_level": None,
                "change": 0,
                "components": {},
                "alerts": ["Insufficient data for comprehensive risk analysis"],
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "error": "No finite return observations for risk scoring",
            }
        price_data = price_data.loc[:, usable_tickers]
        for ticker, count in return_observations.items():
            per_ticker.setdefault(ticker, {})["return_observations"] = count
        history_coverage = holding_coverage(
            effectives, start, end, int(len(price_data)), per_ticker
        )

        # Benchmark returns for the factor leg (best-effort: without them the
        # engine excludes + renormalizes instead of scoring a silent R²=0).
        benchmark_returns = None
        try:
            benchmark_returns = await benchmark_service.get_returns(start=start, end=end)
        except Exception:
            logger.warning("Benchmark data unavailable")

        # Calculate risk score using analytics engine
        risk_weights = {
            ticker: float(weight)
            for ticker, weight in weights.items()
            if ticker in usable_tickers
        }
        risk_weight_total = sum(risk_weights.values())
        if risk_weight_total > 0:
            risk_weights = {
                ticker: weight / risk_weight_total
                for ticker, weight in risk_weights.items()
            }
        risk_result = await analytics_engine.risk_scoring(price_data, risk_weights, benchmark_data=benchmark_returns)
        if not isinstance(risk_result, Mapping) or risk_result.get("overall_score") is None:
            return {
                "overall_score": None,
                "risk_level": None,
                "change": 0,
                "components": {},
                "alerts": ["Insufficient data for comprehensive risk analysis"],
                "universe_coverage": _universe_coverage(requested_tickers, usable_tickers),
                "data_status": "partial" if usable_tickers else "unavailable",
                "error": "Risk score unavailable for the measured return sample",
            }
        risk_result["history_coverage"] = history_coverage
        coverage = _universe_coverage(requested_tickers, usable_tickers)
        limited_history = any(
            count < MIN_ANNUALIZE_DAYS for count in return_observations.values()
        )
        risk_result["universe_coverage"] = coverage
        risk_result["data_status"] = (
            "unavailable" if coverage["status"] == "unavailable"
            else "partial" if coverage["status"] == "partial" or limited_history or risk_result.get("error")
            else "available"
        )

        return risk_result
        
    except HTTPException:
        raise
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except Exception:
        logger.error("Risk score request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/summary")
async def get_analytics_summary(
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    analytics_engine: AnalyticsEngine = Depends(get_analytics_engine),
    benchmark_service: BenchmarkService = Depends(get_benchmark_service),
) -> Dict:
    """
    Get analytics summary for dashboard
    """
    try:
        # Actual DB positions
        weights = await _load_portfolio_allocation(db)
        requested_tickers = await _load_portfolio_tickers(db)
        if not weights:
            return {
                "portfolio_value": 0.0,
                "portfolio_value_currency": "INR",
                "currency": "INR",
                "base_currency": "INR",
                "currency_provenance": {
                    "base_currency": "INR",
                    "aggregation": "empty",
                    "source_currencies": [],
                    "pairs": {},
                },
                "total_positions": 0,
                "realized_volatility": None,
                "forecast_volatility": None,
                "sharpe_ratio": None,
                "max_drawdown": None,
                "risk_score": None,
                "risk_level": None,
                "liquidity_score": None,
                "concentration_score": None,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "error": "No portfolio positions found for summary"
            }
        
        # Fetch price data for summary concurrently
        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=252)).strftime('%Y-%m-%d')  # 1 year
        
        calculation_tickers = _active_weight_tickers(weights)
        price_data_dict = await _fetch_price_series_dict(data_service, calculation_tickers, start, end)
        
        # Compute real portfolio value from DB positions
        pos_result = await db.execute(select(PortfolioPosition))
        positions_list = pos_result.scalars().all()
        converted_values, currency_provenance = await _convert_analytics_positions(
            positions_list, target_currency="INR"
        )
        portfolio_value = sum(converted_values.values())
        if not math.isfinite(float(portfolio_value)) or portfolio_value <= 0:
            return {
                "portfolio_value": 0.0,
                "portfolio_value_currency": "INR",
                "currency": "INR",
                "base_currency": "INR",
                "currency_provenance": currency_provenance,
                "total_positions": len(weights),
                "realized_volatility": None,
                "instrument_volatility": None,
                "forecast_volatility": None,
                "sharpe_ratio": None,
                "max_drawdown": None,
                "risk_score": None,
                "risk_level": None,
                "liquidity_score": None,
                "concentration_score": None,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "error": "No positive portfolio market value available for summary",
            }
        
        if not price_data_dict:
            return {
                "portfolio_value": round(portfolio_value, 2),
                "portfolio_value_currency": "INR",
                "currency": "INR",
                "base_currency": "INR",
                "currency_provenance": currency_provenance,
                "total_positions": len(weights),
                "realized_volatility": None,
                "forecast_volatility": None,
                "sharpe_ratio": None,
                "max_drawdown": None,
                "risk_score": None,
                "risk_level": None,
                "liquidity_score": None,
                "concentration_score": None,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "error": "No price data available for summary"
            }
        
        # Combine price data, restricted to actual holding history. The
        # unmasked dict is kept for instrument (asset) volatility below.
        holdings = await resolve_holdings(db, calculation_tickers)
        unmasked_dict = price_data_dict
        price_data_dict, effectives = holding_window(price_data_dict, holdings)
        price_data = pd.DataFrame(price_data_dict)
        if price_data.empty:
            return {
                "portfolio_value": round(portfolio_value, 2),
                "portfolio_value_currency": "INR",
                "currency": "INR",
                "base_currency": "INR",
                "currency_provenance": currency_provenance,
                "total_positions": len(weights),
                "realized_volatility": None,
                "instrument_volatility": None,
                "forecast_volatility": None,
                "sharpe_ratio": None,
                "max_drawdown": None,
                "risk_score": None,
                "risk_level": None,
                "liquidity_score": None,
                "concentration_score": None,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "error": "No usable price data within the holding window for summary",
            }
        covered_days = int(len(price_data))
        per_ticker = {
            ticker: {
                "raw_days": int(len(unmasked_dict.get(ticker))) if ticker in unmasked_dict and unmasked_dict[ticker] is not None else 0,
                "masked_days": int(len(price_data_dict.get(ticker))) if ticker in price_data_dict and price_data_dict[ticker] is not None else 0,
                "limited_history": bool(getattr(unmasked_dict.get(ticker), "attrs", {}).get("limited_history", False)),
                "coverage_reason": getattr(unmasked_dict.get(ticker), "attrs", {}).get("coverage_reason"),
            }
            for ticker in requested_tickers
        }
        history_coverage = holding_coverage(effectives, start, end, covered_days, per_ticker)

        # Calculate portfolio metrics for summary
        metrics = await analytics_engine.calculate_portfolio_metrics(price_data, weights)
        # Report measured return coverage rather than the union length of the
        # price frame; missing/interior bars are not covered observations.
        covered_days = int(metrics.get("active_observations") or metrics.get("observations") or 0)
        history_coverage["covered_days"] = covered_days
        history_coverage["annualized"] = covered_days >= MIN_ANNUALIZE_DAYS
        concentration_result = await analytics_engine.concentration_analysis(weights)
        # Same best-effort benchmark leg as /risk-score so scores agree.
        benchmark_returns = None
        try:
            benchmark_returns = await benchmark_service.get_returns(start=start, end=end)
        except Exception:
            logger.warning("Benchmark data unavailable")
        summary_return_counts = price_data.pct_change(fill_method=None).iloc[1:].notna().sum()
        summary_usable_tickers = [
            ticker for ticker in weights
            if ticker in summary_return_counts.index and int(summary_return_counts[ticker]) > 0
        ]
        summary_weights = {
            ticker: float(weights[ticker])
            for ticker in summary_usable_tickers
        }
        summary_weight_total = sum(summary_weights.values())
        if summary_weight_total > 0:
            summary_weights = {
                ticker: weight / summary_weight_total
                for ticker, weight in summary_weights.items()
            }
        risk_result = await analytics_engine.risk_scoring(price_data, summary_weights, benchmark_data=benchmark_returns)

        # Instrument volatility on the UNMASKED window (same asset-risk logic
        # as realized-risk): never N/A-gated by intersection length.
        full_iv_df = pd.DataFrame({
            t: s for t, s in unmasked_dict.items()
            if isinstance(s, pd.Series) and len(s) > 1
        })
        instrument_volatility = None
        instrument_volatility_days = int(len(full_iv_df)) if not full_iv_df.empty else 0
        if instrument_volatility_days >= 2:
            iv_metrics = await analytics_engine.calculate_portfolio_metrics(full_iv_df, weights)
            iv_payload = {"instrument_volatility": iv_metrics.get("annual_volatility")}
            apply_annualization_gate(iv_payload, ["instrument_volatility"], instrument_volatility_days)
            instrument_volatility = iv_payload["instrument_volatility"]

        # Generate summary (annualized ratios suppressed on short history).
        return_frame = price_data.pct_change(fill_method=None).iloc[1:]
        return_observations = {
            ticker: int(return_frame[ticker].notna().sum())
            for ticker in requested_tickers
            if ticker in return_frame.columns
        }
        for ticker, count in return_observations.items():
            per_ticker.setdefault(ticker, {})["return_observations"] = count
        history_coverage["tickers"].update({
            ticker: {
                **history_coverage["tickers"].get(ticker, {}),
                "return_observations": count,
            }
            for ticker, count in return_observations.items()
        })
        available_tickers = [
            ticker for ticker, count in return_observations.items() if count >= 2
        ]
        limited_history = any(
            count < MIN_ANNUALIZE_DAYS for count in return_observations.values()
        )
        coverage = _universe_coverage(requested_tickers, available_tickers)
        if coverage["status"] == "unavailable":
            summary_status = "unavailable"
        elif coverage["status"] == "partial" or limited_history or risk_result.get("error") or risk_result.get("overall_score") is None:
            summary_status = "partial"
        else:
            summary_status = "available"
        summary = {
            "portfolio_value": round(portfolio_value, 2),
            "portfolio_value_currency": "INR",
            "currency": "INR",
            "base_currency": "INR",
            "currency_provenance": currency_provenance,
            "total_positions": len(weights),
            "realized_volatility": metrics.get("annual_volatility"),
            "instrument_volatility": instrument_volatility,
            "instrument_volatility_days": instrument_volatility_days,
            "forecast_volatility": None,
            "sharpe_ratio": metrics.get("sharpe_ratio"),
            "max_drawdown": metrics.get("max_drawdown"),
            "risk_score": risk_result.get("overall_score"),
            "risk_level": risk_result.get("risk_level"),
            "liquidity_score": None,
            "concentration_score": (
                concentration_result.get("herfindahl_index") * 100
                if concentration_result.get("herfindahl_index") is not None else None
            ),
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "latest_observation_date": _latest_observation_date(price_data),
            "history_coverage": history_coverage,
            "universe_coverage": coverage,
            "data_status": summary_status,
            "methodology": "Real-time portfolio analytics summary with multi-factor risk assessment"
        }
        apply_annualization_gate(summary, ["realized_volatility", "sharpe_ratio"], covered_days)

        return summary
        
    except HTTPException:
        raise
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except Exception:
        logger.error("Analytics summary request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/performance-history")
async def get_performance_history(
    days: int = Query(default=90, ge=7, le=1825, description="Lookback window in days"),
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    benchmark_service: BenchmarkService = Depends(get_benchmark_service),
) -> List[Dict[str, Any]]:
    """
    Historical portfolio value series (price x quantity) over time from cached OHLCV.
    """
    try:
        # Resolve positions & quantities
        result = await db.execute(select(PortfolioPosition))
        db_positions = {p.ticker: p for p in result.scalars().all()}

        if isinstance(tickers, str) and tickers.strip():
            parsed = _parse_tickers(tickers)
            ticker_list = [t for t in (parsed or "").split(",") if t]
        else:
            ticker_list = list(db_positions.keys())
        if len(ticker_list) > _MAX_TICKERS:
            raise HTTPException(status_code=422, detail=f"At most {_MAX_TICKERS} tickers are allowed")

        if not ticker_list:
            return []

        quantities = {}
        for t in ticker_list:
            p = db_positions.get(t)
            if p:
                q = p.quantity if (p.quantity and p.quantity > 0) else 0.0
                if q == 0.0 and p.market_value and p.last_price and p.last_price > 0:
                    q = p.market_value / p.last_price
                if q <= 0:
                    # Degenerate row: no qty and nothing to derive it from.
                    # Never fabricate a share (price x 1.0 = phantom value).
                    logger.warning(f"performance-history: excluding {t} (no usable quantity)")
                    continue
                quantities[t] = q
            else:
                quantities[t] = 1.0

        if not quantities:
            return []

        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        # Fetch price data concurrently
        price_data_dict = await _fetch_price_series_dict(data_service, list(quantities), start, end)

        if not price_data_dict:
            return []

        price_df = pd.DataFrame(price_data_dict)
        # Drop pre-holding dates: quantity x past-price before import is phantom
        # value. db_positions is already loaded above, so no extra query.
        perf_holdings: Dict[str, Dict[str, Any]] = {}
        for t in quantities:
            pos = db_positions.get(t)
            if pos is None:
                continue
            try:
                buy = float(pos.buy_price) if pos.buy_price else None
            except (TypeError, ValueError):
                buy = None
            perf_holdings[t] = {
                "added_on": coerce_holding_date(pos.added_on),
                "buy_price": buy,
            }
        price_df_dict, _perf_effectives = holding_window(
            {t: price_df[t] for t in price_df.columns if t in quantities}, perf_holdings
        )
        # Do not backfill or zero-fill a position before/inside its actual
        # history.  A portfolio value is emitted only for dates where every
        # priced column is usable, so a listing gap cannot create a phantom
        # flat segment.
        price_df = pd.DataFrame(price_df_dict).sort_index().replace([np.inf, -np.inf], np.nan)
        if price_df.empty:
            return []
        source_currencies: Dict[str, str] = {}
        for ticker in quantities:
            position = db_positions.get(ticker)
            if position is None:
                position = SimpleNamespace(ticker=ticker, region="")
            source_currencies[ticker] = _analytics_position_currency(position)
        target_currency = "INR"
        active_currencies = {
            source_currencies[ticker]
            for ticker in price_df.columns
            if ticker in source_currencies
        }
        rates = {currency: 1.0 for currency in active_currencies}
        fx_pairs: Dict[str, Dict[str, Any]] = {}
        for currency in active_currencies:
            pair_key = f"{currency}->{target_currency}"
            if currency == target_currency:
                fx_pairs[pair_key] = {
                    "rate": 1.0,
                    "provenance": "identity",
                    "source": "identity",
                    "is_fallback": False,
                }
                continue
            rate, rate_metadata = await _get_live_fx_rate(
                get_currency_service(), currency, target_currency
            )
            rates[currency] = rate
            fx_pairs[pair_key] = {"rate": rate, **rate_metadata}
        currency_provenance = {
            "base_currency": target_currency,
            "aggregation": (
                "per_position_conversion"
                if any(currency != target_currency for currency in active_currencies)
                else "native_uniform"
            ),
            "source_currencies": sorted(active_currencies),
            "pairs": fx_pairs,
            "rate_provider": "currency_service",
        }
        q_series = pd.Series({
            t: quantities.get(t, 1.0) * rates.get(source_currencies.get(t, target_currency), 1.0)
            for t in price_df.columns
        })
        portfolio_series = price_df.mul(q_series, axis=1).sum(axis=1, min_count=len(q_series))
        portfolio_series = portfolio_series.dropna()
        if portfolio_series.empty:
            return []

        # The first observation has no measured return.  Omit it rather than
        # publishing a synthetic 0.0% return; the remaining series retains the
        # exact value/return pairs consumed by the chart.
        daily_returns = portfolio_series.pct_change(fill_method=None).dropna()

        # Benchmark comparison
        bench_val_series = None
        try:
            bench_ret = await benchmark_service.get_returns(start=start, end=end, days=days)
            if bench_ret is not None and not bench_ret.empty:
                common_dates = portfolio_series.index.intersection(bench_ret.index)
                if not common_dates.empty:
                    # Anchor the benchmark to the first date actually emitted
                    # below (the first return needs a prior portfolio value).
                    anchor_date = (
                        daily_returns.index[0]
                        if len(daily_returns) and daily_returns.index[0] in common_dates
                        else common_dates[0]
                    )
                    initial_val = float(portfolio_series.loc[anchor_date])
                    cum_bench = (1.0 + bench_ret.loc[common_dates]).cumprod()
                    anchor_factor = float(cum_bench.loc[anchor_date])
                    if anchor_factor != 0:
                        cum_bench = cum_bench / anchor_factor
                    bench_val_series = initial_val * cum_bench
        except Exception:
            logger.debug("Benchmark data unavailable")

        output = []
        for date_idx in daily_returns.index:
            date_str = str(date_idx)[:10]
            val = float(portfolio_series.loc[date_idx])
            ret = float(daily_returns.loc[date_idx])
            item = {
                "date": date_str,
                "portfolio_value": round(val, 2),
                "portfolio_value_currency": target_currency,
                "return": round(ret, 6),
                "currency": target_currency,
                "base_currency": target_currency,
                "currency_provenance": currency_provenance,
            }
            if bench_val_series is not None and date_idx in bench_val_series.index:
                item["benchmark_value"] = round(float(bench_val_series.loc[date_idx]), 2)
                item["benchmark_value_currency"] = target_currency
            output.append(item)

        return output

    except HTTPException:
        raise
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except Exception:
        logger.error("Performance history request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# ---------------------------------------------------------------------------
# Phase 1+2 endpoints: tear-sheet, risk contribution, optimizer, regime
# ---------------------------------------------------------------------------


async def _build_wide_returns(
    ticker_list: List[str],
    weights: Dict[str, float],
    start: str,
    end: str,
    data_service: DataService,
    holdings: Optional[Dict[str, Dict[str, Any]]] = None,
) -> tuple[pd.DataFrame, pd.Series, Dict[str, Any]]:
    """Wide per-asset returns frame + weighted portfolio returns + coverage.

    When holdings ({ticker: {"added_on", "buy_price"}}) is given, history is
    restricted to actual holding time via buy-implied effective starts, so
    realized analytics never attribute pre-purchase price action.
    Hypothetical tools (optimize/backtest/monte-carlo) omit it on purpose.
    """
    requested_ticker_list = list(dict.fromkeys(ticker_list))
    if weights:
        active_set = set(_active_weight_tickers(weights))
        if active_set:
            requested_ticker_list = [
                ticker for ticker in requested_ticker_list
                if str(ticker).upper() in active_set
            ]
    if not requested_ticker_list:
        raise ValueError("No active portfolio weights available for the requested window")
    ticker_list = requested_ticker_list
    price_data_dict = await _fetch_price_series_dict(data_service, ticker_list, start, end)
    if not price_data_dict:
        raise ValueError("No price data available for the requested window")
    raw_price_data_dict = dict(price_data_dict)
    masked_dict, effectives = holding_window(price_data_dict, holdings)
    if not masked_dict:
        raise ValueError("No price data within actual holding period")
    # Preserve the active-price mask.  Back-filling a newly listed instrument
    # with its first future price creates a flat synthetic history; zero-filling
    # the resulting gaps creates a different synthetic history.  The shared
    # active-weight helper also renormalises around an interior data gap.
    prices = pd.DataFrame(masked_dict).sort_index().replace([np.inf, -np.inf], np.nan)
    returns_df = prices.pct_change(fill_method=None)
    if len(returns_df) > 1:
        returns_df = returns_df.iloc[1:]
    finite_columns = [
        ticker for ticker in returns_df.columns
        if returns_df[ticker].notna().any()
    ]
    if not finite_columns:
        raise ValueError("No finite return observations for the requested window")
    returns_df = returns_df.loc[:, finite_columns]
    portfolio_returns = aggregate_active_returns(returns_df, weights)
    if portfolio_returns.empty:
        raise ValueError("No active return observations for the requested window")
    # Return only dates that can contribute to the active portfolio rule so
    # downstream covariance/tail consumers cannot reintroduce all-missing rows.
    returns_df = returns_df.loc[portfolio_returns.index]
    per_ticker = {
        ticker: {
            "raw_days": int(len(raw_price_data_dict[ticker])) if ticker in raw_price_data_dict and raw_price_data_dict[ticker] is not None else 0,
            "masked_days": int(len(masked_dict[ticker])) if ticker in masked_dict and masked_dict[ticker] is not None else 0,
            "return_observations": int(returns_df[ticker].notna().sum()) if ticker in returns_df.columns else 0,
            "limited_history": bool(getattr(raw_price_data_dict.get(ticker), "attrs", {}).get("limited_history", False)),
            "coverage_reason": getattr(raw_price_data_dict.get(ticker), "attrs", {}).get("coverage_reason"),
        }
        for ticker in ticker_list
    }
    coverage = holding_coverage(effectives, start, end, len(portfolio_returns), per_ticker)
    coverage["model_used_tickers"] = list(returns_df.columns)
    return returns_df, portfolio_returns, coverage


async def resolve_holdings(
    db: AsyncSession,
    tickers: List[str],
) -> Dict[str, Dict[str, Any]]:
    """{ticker: {"added_on": ISO|None, "buy_price": float|None}} for DB positions.

    Tickers absent from the DB (ad-hoc universes) are missing from the map
    and never constrain the window — those paths stay hypothetical.
    """
    if not tickers:
        return {}
    result = await db.execute(select(PortfolioPosition).where(PortfolioPosition.ticker.in_(tickers)))
    out: Dict[str, Dict[str, Any]] = {}
    for p in result.scalars().all():
        try:
            buy = float(p.buy_price) if p.buy_price else None
        except (TypeError, ValueError):
            buy = None
        out[p.ticker] = {"added_on": coerce_holding_date(p.added_on), "buy_price": buy}
    return out


@router.get("/tear-sheet")
async def get_tear_sheet(
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers"),
    start: Optional[date] = None,
    end: Optional[date] = None,
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
        start, end = _date_window(start, end, default_days=365)

        try:
            ticker_list, weights = await resolve_allocation(tickers, db)
        except ValueError:
            raise HTTPException(status_code=404, detail="Requested resource not found")

        holdings = await resolve_holdings(db, ticker_list)
        returns_df, port_ret, history_coverage = await _build_wide_returns(
            ticker_list, weights, start, end, data_service,
            holdings=holdings,
        )

        # Full-history spans entire cache depth (Phase 1 get_coverage), not
        # the 365d request window — ends the 251-vs-175 confusion. The
        # holding-truthed leg above stays on the requested window.
        full_start = start
        try:
            get_cov = getattr(data_service, "get_coverage", None)
            if callable(get_cov):
                cached_starts = []
                for t in ticker_list:
                    cov = await get_cov(t)
                    cs = cov.get("cached_start") if isinstance(cov, dict) else None
                    if isinstance(cs, str) and cs:
                        cached_starts.append(cs)
                if cached_starts:
                    earliest = min(cached_starts)
                    if earliest < full_start:
                        full_start = earliest
        except Exception:
            full_start = start

        try:
            bench_days = max(756, (pd.to_datetime(end) - pd.to_datetime(full_start)).days + 30)
        except Exception:
            bench_days = 756
        try:
            bench_ret = await benchmark.get_returns(start=full_start, end=end, days=bench_days)
        except Exception:
            logger.warning("Benchmark data unavailable")
            bench_ret = None

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
        apply_annualization_gate(
            metrics, ["cagr", "sharpe", "sortino", "calmar", "volatility"], len(port_ret)
        )

        # --- Full-history instrument risk (DSP-10) ---------------------------
        # CAGR/Sharpe/Sortino/Calmar and benchmark beta/alpha are asset-
        # characteristic questions: the current book measured over the full
        # cache depth (see full_start above). Realized P&L above stays
        # holding-truthed. The second build is cache-served (same frames as
        # the masked call).
        full_returns_df, full_port_ret, _ = await _build_wide_returns(
            ticker_list, weights, full_start, end, data_service,
        )
        full_metrics = {
            "total_return": _q(qs.stats.comp, full_port_ret),
            "cagr": _q(qs.stats.cagr, full_port_ret),
            "sharpe": _q(qs.stats.sharpe, full_port_ret, rf=0.02),
            "sortino": _q(qs.stats.sortino, full_port_ret, rf=0.02),
            "calmar": _q(qs.stats.calmar, full_port_ret),
            "volatility": _q(qs.stats.volatility, full_port_ret),
            "max_drawdown": _q(qs.stats.max_drawdown, full_port_ret),
            "days": int(len(full_port_ret)),
        }
        apply_annualization_gate(
            full_metrics, ["cagr", "sharpe", "sortino", "calmar", "volatility"], len(full_port_ret)
        )
        try:
            full_history_start = str(full_port_ret.index.min().date())
        except Exception:
            full_history_start = full_start

        full_relative: Dict[str, Any] = {}
        if bench_ret is not None and len(bench_ret) > 20:
            common_full = full_port_ret.index.intersection(bench_ret.index)
            if len(common_full) >= MIN_ANNUALIZE_DAYS:
                p, b = full_port_ret.loc[common_full], bench_ret.loc[common_full]
                var_b = float(b.var())
                beta = float(p.cov(b) / var_b) if var_b > 0 else None
                alpha_ann = float((p.mean() - beta * b.mean()) * 252) if beta is not None else None
                full_relative = {
                    "beta_vs_nifty": round(beta, 4) if beta is not None else None,
                    "alpha_annualized": round(alpha_ann, 4) if beta is not None else None,
                    "overlap_days": int(len(common_full)),
                }

        relative: Dict[str, Any] = {}
        if bench_ret is not None and len(bench_ret) > 20:
            # Holding leg stays on the requested window: slice the (possibly
            # deeper) benchmark back down. Benchmark standalone stats describe
            # the index over the requested window (no holding concept applies
            # to NIFTY itself).
            bench_window = bench_ret
            try:
                bench_window = bench_ret[bench_ret.index >= start]
            except Exception:
                bench_window = bench_ret
            relative = {
                "beta_vs_nifty": None,
                "alpha_annualized": None,
                "benchmark_sharpe": _q(qs.stats.sharpe, bench_window, rf=0.02),
                "benchmark_volatility": _q(qs.stats.volatility, bench_window),
                "benchmark_max_drawdown": _q(qs.stats.max_drawdown, bench_window),
                "benchmark_total_return": _q(qs.stats.comp, bench_window),
            }
            # Beta/alpha genuinely need joint history: gate on the common
            # window so a handful of overlapping days never annualizes noise.
            common = port_ret.index.intersection(bench_ret.index)
            if len(common) >= MIN_ANNUALIZE_DAYS:
                p, b = port_ret.loc[common], bench_ret.loc[common]
                var_b = float(b.var())
                beta = float(p.cov(b) / var_b) if var_b > 0 else None
                alpha_ann = float((p.mean() - beta * b.mean()) * 252) if beta is not None else None
                relative["beta_vs_nifty"] = round(beta, 4) if beta is not None else None
                relative["alpha_annualized"] = round(alpha_ann, 4) if alpha_ann is not None else None
            relative["overlap_days"] = int(len(common))

        monthly: Dict[str, Dict[str, float]] = {}
        try:
            if not port_ret.empty:
                m_series = (1.0 + port_ret).groupby([port_ret.index.year, port_ret.index.month]).prod() - 1.0
                for (y, m), val in m_series.items():
                    ys = str(y)
                    ms = str(m)
                    if ys not in monthly:
                        monthly[ys] = {}
                    monthly[ys][ms] = round(float(val), 6)
        except Exception:  # noqa: BLE001
            logger.debug("Monthly returns unavailable")

        underwater = []
        try:
            dd = qs.stats.to_drawdown_series(port_ret)
            for ts, val in list(dd.items())[-250:]:
                underwater.append({"date": str(ts)[:10], "drawdown": round(float(val), 6)})
        except Exception:  # noqa: BLE001
            logger.debug("Drawdown series unavailable")

        coverage = _universe_coverage(ticker_list, returns_df.columns)
        full_coverage = _universe_coverage(ticker_list, full_returns_df.columns)
        tear_sheet_status = (
            "unavailable" if coverage["status"] == "unavailable"
            else "partial" if coverage["status"] == "partial" or len(port_ret) < MIN_ANNUALIZE_DAYS
            else "available"
        )
        return {
            "window": {"start": start, "end": end},
            "holdings": weights,
            "universe_coverage": coverage,
            "data_status": tear_sheet_status,
            "latest_observation_date": _latest_observation_date(port_ret),
            "calculation_basis": {
                "realized": "holding_truthed_current_composition",
                "full_history": "hypothetical_current_weights",
            },
            "metrics": metrics,
            "full_history": {
                "metrics": full_metrics,
                "universe_coverage": full_coverage,
                "relative_vs_nifty": full_relative,
                "start": full_history_start,
            },
            "relative_vs_nifty": relative,
            "monthly_returns": monthly,
            "underwater": underwater,
            "history_coverage": history_coverage,
            "methodology": "quantstats metric suite over cached OHLCV adj-close returns",
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail="Requested resource not found")
    except Exception:
        logger.error("Tear-sheet request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


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
        except ValueError:
            raise HTTPException(status_code=404, detail="Requested resource not found")

        holdings = await resolve_holdings(db, ticker_list)
        # Euler risk contribution is an asset-risk question: the covariance of
        # the CURRENT book comes from full exchange history (DSP-10). Masking
        # to the ~6-day holding window degenerated contributions and N/A'd the
        # portfolio vol. Holding-period truncation stays disclosed.
        returns_df, port_ret, _ = await _build_wide_returns(
            ticker_list, weights, start, end, data_service,
        )
        effectives = effective_starts(holdings, None)
        holding_context = holding_coverage(effectives, start, end, len(port_ret))
        history_coverage = {
            **holding_context,
            "calculation_basis": "full_exchange_history_current_weights",
            "calculation_observations": len(port_ret),
            "holding_context": holding_context,
        }
        assets = list(returns_df.columns)
        missing_assets = [ticker for ticker in ticker_list if ticker not in set(assets)]
        w = np.array([weights.get(a, 0.0) for a in assets])
        volatility_excluded_assets = set(missing_assets)
        cvar_excluded_assets = set(missing_assets)
        vol_assets = []
        for asset, weight in zip(assets, w):
            observations = int(returns_df[asset].notna().sum()) if asset in returns_df else 0
            finite_weight = bool(np.isfinite(weight) and weight > 0.0)
            finite_variance = False
            if asset in returns_df and observations > 1:
                finite_variance = bool(np.isfinite(returns_df[asset].std(ddof=1)) and returns_df[asset].std(ddof=1) > 0.0)
            if finite_weight and observations >= 2 and finite_variance:
                vol_assets.append(asset)
            else:
                volatility_excluded_assets.add(asset)
                # Preserve the existing sparse/invalid-data gate for both
                # models; covariance-pair removals below are volatility-only.
                cvar_excluded_assets.add(asset)

        # Pairwise covariance needs at least two shared observations.  Remove
        # any remaining underdetermined pair rather than allowing NaN * zero to
        # silently turn portfolio risk into zero.
        while len(vol_assets) > 1:
            candidate_cov = returns_df[vol_assets].cov(min_periods=2) * 252
            candidate_values = candidate_cov.to_numpy(dtype=float)
            if np.isfinite(candidate_values).all():
                break
            invalid_counts = np.sum(~np.isfinite(candidate_values), axis=1)
            remove_index = int(np.argmax(invalid_counts))
            removed = vol_assets.pop(remove_index)
            volatility_excluded_assets.add(removed)
        if not vol_assets:
            cov = pd.DataFrame()
            vol_w = np.array([], dtype=float)
            sigma_p = 0.0
            vol_rc = {}
        else:
            cov = returns_df[vol_assets].cov(min_periods=2) * 252
            vol_w = np.array([float(weights.get(asset, 0.0)) for asset in vol_assets], dtype=float)
            vol_w = vol_w / vol_w.sum() if vol_w.sum() > 0 else vol_w
            cov_values = cov.to_numpy(dtype=float)
            sigma_p = float(np.sqrt(max(0.0, vol_w @ cov_values @ vol_w)))
            vol_rc = {}
            if sigma_p > 0 and np.isfinite(sigma_p):
                mrc = cov_values @ vol_w
                contrib = vol_w * mrc / sigma_p
                if np.isfinite(contrib).all() and float(contrib.sum()) != 0.0:
                    contrib = contrib / contrib.sum()
                    vol_rc = {asset: round(float(value), 6) for asset, value in zip(vol_assets, contrib)}
                else:
                    volatility_excluded_assets.update(vol_assets)
                    vol_assets = []
                    sigma_p = 0.0

        var_95 = float(np.percentile(port_ret, 5))
        tail = port_ret <= var_95
        cvar_rc = {}
        if tail.any():
            tail_returns = returns_df.loc[tail]
            weight_frame = pd.Series({a: float(w[i]) for i, a in enumerate(assets)})
            weight_frame = weight_frame.where(np.isfinite(weight_frame) & (weight_frame > 0.0), 0.0)
            active_weight = tail_returns.notna().mul(weight_frame, axis=1).sum(axis=1)
            comp = []
            comp_assets = []
            for a in assets:
                if a in cvar_excluded_assets:
                    continue
                # NaN remains unavailable; it is never converted into a zero
                # loss contribution before the active-weight denominator.
                contribution = tail_returns[a].mul(float(w[assets.index(a)]))
                contribution = contribution.div(active_weight.where(active_weight > 0.0))
                valid_contribution = contribution.replace([np.inf, -np.inf], np.nan).dropna()
                if valid_contribution.empty:
                    cvar_excluded_assets.add(a)
                    continue
                comp_es = float(valid_contribution.mean())
                if np.isfinite(comp_es):
                    comp.append(comp_es)
                    comp_assets.append(a)
                else:
                    cvar_excluded_assets.add(a)
            total = sum(abs(c) for c in comp)
            # comp values are negative (tail-day losses); normalize to positive loss-shares
            cvar_rc = {a: round(float(-c) / total, 6) for a, c in zip(comp_assets, comp)} if total > 0 else {}

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

        coverage = _universe_coverage(ticker_list, assets)
        excluded_union = sorted(set(volatility_excluded_assets) | set(cvar_excluded_assets))
        if excluded_union:
            coverage["raw_available_tickers"] = coverage["available_tickers"]
            coverage["available_tickers"] = [
                ticker for ticker in coverage["available_tickers"]
                if ticker not in set(excluded_union)
            ]
            coverage["missing_tickers"] = sorted(set(coverage["missing_tickers"]) | set(excluded_union))
            coverage["covered_tickers"] = [
                ticker for ticker in coverage["requested_tickers"]
                if ticker not in set(excluded_union)
            ]
            coverage["available_count"] = len(coverage["covered_tickers"])
            coverage["coverage_ratio"] = round(
                len(coverage["covered_tickers"]) / len(coverage["requested_tickers"]), 6
            ) if coverage["requested_tickers"] else None
            coverage["complete"] = False
            coverage["status"] = "partial"
        coverage["model_used_tickers"] = {
            "volatility": sorted(vol_assets),
            "cvar_tail": sorted(cvar_rc),
        }
        result = {
            "window": {"start": start, "end": end},
            "positions": {
                "volatility": vol_rc,
                "cvar_tail": cvar_rc,
            },
            "sector_rollup": sector_rollup,
            "universe_coverage": coverage,
            "data_status": (
                "unavailable" if coverage["status"] == "unavailable"
                else "partial" if coverage["status"] == "partial" or len(port_ret) < MIN_ANNUALIZE_DAYS
                else "available"
            ),
            "latest_observation_date": _latest_observation_date(port_ret),
            "calculation_window": {"start": start, "end": end, "days": len(port_ret)},
            # A leg can support one model while its history is underdetermined for the other.
            "excluded_assets": {
                "volatility": sorted(volatility_excluded_assets),
                "cvar_tail": sorted(cvar_excluded_assets),
            },
            "portfolio_volatility_annualized": round(sigma_p, 4),
            "portfolio_var_95_daily": round(var_95, 6),
            "portfolio_cvar_95_daily": round(float(port_ret[tail].mean()), 6) if tail.any() else None,
            "history_coverage": history_coverage,
            "methodology": "Euler decomposition (volatility) + historical tail attribution (CVaR)",
        }
        return apply_annualization_gate(result, ["portfolio_volatility_annualized"], len(port_ret))
    except HTTPException:
        raise
    except Exception:
        logger.error("Risk contribution request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/optimize/run")
async def run_optimization(
    body: OptimizeRequest = Body(default_factory=OptimizeRequest),
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
        request = _coerce_request(OptimizeRequest, body)
        if request.strategy not in _OPTIMIZATION_STRATEGIES:
            raise HTTPException(status_code=400, detail="Invalid optimization strategy")
        strategy = request.strategy
        rf = request.risk_free_rate
        views = request.views
        relative_views = request.relative_views

        requested = request.tickers or tickers
        requested_csv = ",".join(requested) if isinstance(requested, list) else _parse_tickers(requested)
        try:
            ticker_list, current_weights = await resolve_allocation(requested_csv, db)
        except ValueError:
            raise HTTPException(status_code=404, detail="Requested resource not found")

        if len(ticker_list) == 1:
            single_t = ticker_list[0]
            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
            prices = (await _fetch_price_series_dict(data_service, [single_t], start, end)).get(single_t)
            ann_ret = ann_vol = sharpe = None
            if prices is not None and len(prices) > 1:
                rets = prices.replace([np.inf, -np.inf], np.nan).pct_change(fill_method=None).dropna()
                if len(rets) > 0:
                    ann_ret = float(rets.mean() * 252)
                    ann_vol = float(rets.std(ddof=1) * np.sqrt(252)) if len(rets) > 1 else None
                    if ann_vol and ann_vol > 0:
                        sharpe = float((ann_ret - rf) / ann_vol)
            single_usable = prices is not None and len(prices) > 1 and len(rets) >= MIN_ANNUALIZE_DAYS
            coverage = _universe_coverage(ticker_list, [single_t] if single_usable else [])
            if single_usable:
                single_status = "available"
                single_error = None
            else:
                ann_ret = ann_vol = sharpe = None
                single_status = "unavailable" if coverage["status"] == "unavailable" else "partial"
                single_error = "Insufficient return history for optimization"
            return {
                "strategy": strategy,
                "weights": {single_t: 1.0},
                "expected_annual_return": ann_ret,
                "expected_annual_volatility": ann_vol,
                "expected_sharpe": sharpe,
                "solver": "single-holding",
                "universe": ticker_list,
                "current_weights": {single_t: 1.0},
                "trades_required": {},
                "universe_coverage": coverage,
                "data_status": single_status,
                "error": single_error,
                "disclaimer": "Single holding portfolio: weight is 100.00%.",
            }

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        returns_df, _, _ = await _build_wide_returns(ticker_list, current_weights, start, end, data_service)
        # Optimizers require a finite common sample.  Dropping incomplete
        # observations is explicit; never impute a pre-listing return.
        returns_df = returns_df.dropna(how="any")
        if returns_df.empty or len(returns_df) < MIN_ANNUALIZE_DAYS:
            coverage = _universe_coverage(ticker_list, [])
            return {
                "strategy": strategy,
                "weights": {},
                "expected_annual_return": None,
                "expected_annual_volatility": None,
                "expected_sharpe": None,
                "solver": None,
                "universe": ticker_list,
                "calculation_universe": [],
                "current_weights": {t: round(float(current_weights.get(t, 0.0)), 4) for t in ticker_list},
                "trades_required": {},
                "universe_coverage": coverage,
                "data_status": "unavailable" if coverage["status"] == "unavailable" else "partial",
                "data_unavailable_tickers": coverage["missing_tickers"],
                "error": "Insufficient common return history for optimization",
            }

        result = await _run_cpu(
            optimize,
            returns_df,
            strategy=strategy,
            risk_free_rate=rf,
            views=views,
            relative_views=relative_views,
        )

        recommended = result["weights"]
        calculation_universe = list(returns_df.columns)
        coverage = _universe_coverage(ticker_list, calculation_universe)
        missing_tickers = set(coverage["missing_tickers"])
        reported_recommended = {
            ticker: float(recommended.get(ticker, 0.0))
            for ticker in calculation_universe
        }
        trades = {}
        for t in calculation_universe:
            cur = float(current_weights.get(t, 0.0))
            rec = reported_recommended[t]
            if abs(rec - cur) > 1e-6:
                trades[t] = {
                    "current_weight": round(cur, 4),
                    "recommended_weight": round(rec, 4),
                    "weight_delta": round(rec - cur, 4),
                }

        return {
            **result,
            "weights": reported_recommended,
            "universe": ticker_list,
            "calculation_universe": calculation_universe,
            "current_weights": {t: round(float(current_weights.get(t, 0.0)), 4) for t in ticker_list},
            "trades_required": dict(sorted(trades.items(), key=lambda kv: abs(kv[1]["weight_delta"]), reverse=True)),
            "universe_coverage": coverage,
            "data_status": "partial" if missing_tickers or result.get("error") else coverage["status"],
            "data_unavailable_tickers": sorted(missing_tickers),
            "weight_basis": "available_universe_renormalized" if missing_tickers else "full_universe",
            "disclaimer": "Educational optimization output; not investment advice.",
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid analytics request")
    except Exception:
        logger.error("Optimization request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/backtest")
async def run_backtest(
    body: BacktestRequest = Body(default_factory=BacktestRequest),
    tickers: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
) -> Dict[str, Any]:
    """
    Run walk-forward out-of-sample backtest with rolling rebalances and transaction friction.
    """
    try:
        request = _coerce_request(BacktestRequest, body)
        if request.strategy not in _BACKTEST_STRATEGIES:
            raise HTTPException(status_code=400, detail="Invalid backtest strategy")
        strategy = request.strategy
        rebalance_freq = request.rebalance_freq_days
        lookback = request.lookback_days
        cost_bps = request.transaction_cost_bps
        rf = request.risk_free_rate

        requested = request.tickers or tickers
        requested_csv = ",".join(requested) if isinstance(requested, list) else _parse_tickers(requested)
        try:
            ticker_list, current_weights = await resolve_allocation(requested_csv, db)
        except ValueError:
            raise HTTPException(status_code=404, detail="Requested resource not found")

        # Fetch 3 years (1100 days) for deep walk-forward history
        total_history_days = min(
            _MAX_HISTORY_DAYS,
            max(lookback + rebalance_freq + 60, request.history_days),
        )
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=total_history_days)).strftime("%Y-%m-%d")
        returns_df, _, _ = await _build_wide_returns(ticker_list, current_weights, start, end, data_service)
        returns_df = returns_df.dropna(how="any")
        if returns_df.empty or len(returns_df) < MIN_ANNUALIZE_DAYS:
            raise HTTPException(status_code=422, detail="Insufficient common return history for backtest")

        res = await _run_cpu(
            run_walk_forward_backtest,
            returns=returns_df,
            strategy=strategy,
            rebalance_freq_days=rebalance_freq,
            lookback_days=lookback,
            transaction_cost_bps=cost_bps,
            risk_free_rate=rf,
        )

        return {
            **res,
            "universe": ticker_list,
            "history_days_analyzed": len(returns_df),
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid analytics request")
    except Exception:
        logger.error("Backtest request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


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
        history_coverage: Optional[Dict[str, Any]] = None
        portfolio_tickers: List[str] = []
        if with_portfolio:
            try:
                portfolio_tickers, weights = await resolve_allocation(None, db)
                calculation_tickers = _active_weight_tickers(weights)
                if calculation_tickers:
                    end = datetime.now().strftime("%Y-%m-%d")
                    start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
                    _, port_ret, history_coverage = await _build_wide_returns(
                        calculation_tickers, weights, start, end, data_service,
                        holdings=await resolve_holdings(db, calculation_tickers),
                    )
            except (ValueError, HTTPException):
                logger.debug("Regime portfolio leg unavailable")
                port_ret = None

        result = await detect_regime(db, lookback_days=lookback_days, portfolio_returns=port_ret)
        if history_coverage is not None and "portfolio_in_current_regime" in result:
            result["portfolio_in_current_regime"]["history_coverage"] = history_coverage
        if history_coverage is not None:
            # Top-level copy lets the UI distinguish "no overlap" from
            # "no positions / no price data" (both omit the regime block).
            result.setdefault("history_coverage", history_coverage)
            result["universe_coverage"] = _universe_coverage(
                portfolio_tickers,
                history_coverage.get("model_used_tickers", []),
            )
            result["data_status"] = (
                "unavailable" if result["universe_coverage"]["status"] == "unavailable"
                else "partial" if result["universe_coverage"]["status"] == "partial" or (0 if port_ret is None else len(port_ret)) < MIN_ANNUALIZE_DAYS
                else "available"
            )
        elif with_portfolio:
            result["universe_coverage"] = _universe_coverage(portfolio_tickers, [])
            result["portfolio_data_status"] = "unavailable"
            result["data_status"] = "unavailable"
        return result
    except ValueError:
        raise HTTPException(status_code=409, detail="Analytics request could not be completed")
    except HTTPException:
        raise
    except Exception:
        logger.error("Regime request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/monte-carlo")
async def run_monte_carlo(
    body: MonteCarloRequest = Body(...),
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
        request = _coerce_request(MonteCarloRequest, body)
        if request.method not in _MONTE_CARLO_METHODS:
            raise HTTPException(status_code=400, detail="Invalid Monte Carlo method")
        target_value = request.target_value
        horizon_years = request.horizon_years
        initial_value = request.initial_value
        if initial_value is None:
            result = await db.execute(select(PortfolioPosition))
            positions = result.scalars().all()
            initial_value = sum(_native_position_value(p) for p in positions)
        if not math.isfinite(float(initial_value)) or initial_value <= 0:
            raise HTTPException(
                status_code=404,
                detail="Portfolio has no market value yet; pass initial_value explicitly",
            )

        requested = request.tickers or tickers
        requested_csv = ",".join(requested) if isinstance(requested, list) else _parse_tickers(requested)
        try:
            ticker_list, weights = await resolve_allocation(requested_csv, db)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="No portfolio positions found") from exc

        position_rows = await db.execute(select(PortfolioPosition))
        active_currencies = {
            _analytics_position_currency(position)
            for position in position_rows.scalars().all()
            if _position_has_positive_value(position)
        }
        if len(active_currencies) > 1:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Mixed-currency Monte Carlo is unavailable until base-currency "
                    "total-return history is available"
                ),
            )

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
        _, port_ret, history_coverage = await _build_wide_returns(
            ticker_list, weights, start, end, data_service
        )
        if len(port_ret) < MIN_ANNUALIZE_DAYS:
            raise HTTPException(
                status_code=422,
                detail="Insufficient common return history for Monte Carlo simulation",
            )

        result = await _run_cpu(
            simulate_goal,
            portfolio_returns=port_ret,
            initial_value=initial_value,
            target_value=target_value,
            horizon_years=horizon_years,
            method=request.method,
            # The service owns the 100..20000 compatibility clamp; values above
            # the API's hard bound have already been rejected above.
            num_paths=min(max(int(request.num_paths), 100), 20000),
            seed=request.seed,
        )
        if isinstance(result, dict):
            coverage = _universe_coverage(
                ticker_list,
                history_coverage.get("model_used_tickers", []),
            )
            result["universe_coverage"] = coverage
            result["data_status"] = (
                "unavailable" if coverage["status"] == "unavailable"
                else "partial" if coverage["status"] == "partial" or len(port_ret) < MIN_ANNUALIZE_DAYS
                else "available"
            )
        return result
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid analytics request")
    except Exception:
        logger.error("Monte Carlo request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/correlation-stability", response_model=CorrelationStabilityResponse)
async def get_correlation_stability(
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers or portfolio"),
    lookback_days: int = Query(default=756, ge=60, le=2520, description="Historical lookback window in days"),
    window_days: int = Query(default=60, ge=10, le=252, description="Rolling pairwise correlation window size"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
) -> CorrelationStabilityResponse:
    """
    Rolling 60-day average pairwise correlation monitor with 2-year 90th-percentile
    regime break alerts and diversification breakdown detection.
    """
    try:
        try:
            ticker_list, weights = await resolve_allocation(tickers, db)
        except ValueError:
            raise HTTPException(status_code=404, detail="Requested resource not found")

        if len(ticker_list) < 2:
            coverage = _universe_coverage(ticker_list, [])
            return CorrelationStabilityResponse(
                as_of=datetime.now().strftime("%Y-%m-%d"),
                current_avg_correlation=None,
                historical_threshold_90th=None,
                historical_threshold_75th=None,
                historical_median=None,
                is_regime_break=False,
                alert_level="NORMAL",
                message="Single holding portfolio: pairwise correlation is undefined.",
                series=[],
                requested_tickers=coverage["requested_tickers"],
                available_tickers=coverage["available_tickers"],
                missing_tickers=coverage["missing_tickers"],
                data_status="unavailable",
                universe_coverage=coverage,
            )

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        try:
            returns_df, _, history_coverage = await _build_wide_returns(
                ticker_list, weights, start, end, data_service
            )
        except ValueError:
            raise HTTPException(status_code=404, detail="Requested resource not found")

        if len(returns_df.columns) < 2:
            raise HTTPException(
                status_code=400,
                detail="At least 2 assets with valid price history are required",
            )

        result = await _run_cpu(
            analyze_correlation_stability,
            returns_df=returns_df,
            window_days=window_days,
        )
        coverage = _universe_coverage(
            ticker_list,
            history_coverage.get("model_used_tickers", returns_df.columns),
        )
        return result.model_copy(
            update={
                "requested_tickers": coverage["requested_tickers"],
                "available_tickers": coverage["available_tickers"],
                "missing_tickers": coverage["missing_tickers"],
                "data_status": (
                    "unavailable" if coverage["status"] == "unavailable"
                    else "partial" if coverage["status"] == "partial" or len(returns_df) < MIN_ANNUALIZE_DAYS
                    else "available"
                ),
                "universe_coverage": coverage,
            }
        )
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid analytics request")
    except Exception:
        logger.error("Correlation stability request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/coint", response_model=CointScannerResponse)
async def get_cointegration_pairs(
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers or portfolio"),
    lookback_days: int = Query(default=756, ge=60, le=2520, description="Historical price lookback"),
    p_value_threshold: float = Query(default=0.05, gt=0, le=1.0, description="Cointegration p-value threshold"),
    max_half_life: Optional[int] = Query(default=60, ge=1, le=1000, description="Max OU half-life filter"),
    include_spread_series: bool = Query(default=False, description="Include historical spread series"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    cache_service: CacheService = Depends(get_cache_service),
) -> CointScannerResponse:
    """
    Pairs cointegration scanner across holdings/watchlists implementing Engle-Granger,
    Johansen rank tests, OLS hedge ratios, Ornstein-Uhlenbeck mean-reversion half-life,
    and spread z-scores.
    """
    try:
        if isinstance(tickers, str) and tickers.strip():
            parsed = _parse_tickers(tickers, max_items=_MAX_COINT_TICKERS)
            ticker_list = [ticker for ticker in (parsed or "").split(",") if ticker]
        else:
            try:
                ticker_list, _ = await resolve_allocation(None, db)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail="No portfolio positions found") from exc
            if len(ticker_list) > _MAX_COINT_TICKERS:
                raise HTTPException(status_code=422, detail=f"At most {_MAX_COINT_TICKERS} tickers are allowed")

        if len(ticker_list) < 2:
            coverage = _universe_coverage(ticker_list, [])
            return CointScannerResponse(
                as_of=datetime.now().strftime("%Y-%m-%d"),
                latest_observation_date=None,
                as_of_semantics="latest_available_observation",
                universe_size=len(ticker_list),
                requested_universe_size=len(ticker_list),
                requested_tickers=coverage["requested_tickers"],
                available_tickers=coverage["available_tickers"],
                missing_tickers=coverage["missing_tickers"],
                universe_coverage=coverage,
                scanned_pairs_count=0,
                analyzed_pairs_count=0,
                cointegrated_pairs_count=0,
                returned_pairs_count=0,
                returned_cointegrated_pairs_count=0,
                returned_non_cointegrated_pairs_count=0,
                data_status="unavailable",
                pairs=[],
            )

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        # Fetch price data concurrently
        price_data_dict = await _fetch_price_series_dict(data_service, ticker_list, start, end)

        if len(price_data_dict) < 2:
            coverage = _universe_coverage(ticker_list, price_data_dict.keys())
            return CointScannerResponse(
                as_of=end,
                as_of_semantics="request_end_no_usable_price_data",
                latest_observation_date=_latest_observation_date(price_data_dict),
                universe_size=len(ticker_list),
                requested_universe_size=len(ticker_list),
                requested_tickers=coverage["requested_tickers"],
                available_tickers=coverage["available_tickers"],
                missing_tickers=coverage["missing_tickers"],
                universe_coverage=coverage,
                scanned_pairs_count=0,
                analyzed_pairs_count=0,
                cointegrated_pairs_count=0,
                returned_pairs_count=0,
                returned_cointegrated_pairs_count=0,
                returned_non_cointegrated_pairs_count=0,
                unpairable_tickers=[],
                data_status=coverage["status"],
                pairs=[],
                error="Insufficient price data available for at least 2 tickers",
            )

        coint_service = CointegrationService(db_session=db, cache_service=cache_service)
        result = await coint_service.scan_pairs(
            price_data=price_data_dict,
            p_value_threshold=p_value_threshold,
            max_half_life=max_half_life,
            include_spread_series=include_spread_series,
            lookback_days=lookback_days,
        )
        coverage = _universe_coverage(ticker_list, price_data_dict.keys())
        returned_cointegrated = sum(1 for pair in result.pairs if pair.is_cointegrated)
        return result.model_copy(
            update={
                "requested_tickers": coverage["requested_tickers"],
                "available_tickers": coverage["available_tickers"],
                "missing_tickers": coverage["missing_tickers"],
                "requested_universe_size": len(ticker_list),
                "analyzed_pairs_count": result.scanned_pairs_count,
                "returned_pairs_count": len(result.pairs),
                "returned_cointegrated_pairs_count": returned_cointegrated,
                "returned_non_cointegrated_pairs_count": len(result.pairs) - returned_cointegrated,
                "data_status": "partial" if coverage["status"] == "partial" or result.unpairable_tickers else coverage["status"],
                "universe_coverage": coverage,
                "error": result.error if hasattr(result, "error") else None,
            }
        )
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid analytics request")
    except Exception:
        logger.error("Cointegration request failed")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/india-flows")
async def get_india_institutional_flows(
    lookback_days: int = Query(default=30, ge=5, le=365, description="Lookback window for FII/DII flows"),
    db: AsyncSession = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    Retrieve daily FII / DII institutional net cash flows across the last N trading sessions.
    """
    try:
        from app.services.india_data_service import IndiaDataService
        india_svc = IndiaDataService(db=db)
        flow_result = await india_svc.get_institutional_flows(
            lookback_days=lookback_days, return_metadata=True
        )
        if isinstance(flow_result, list):
            # Compatibility with older injected service doubles.
            flows = flow_result
            flow_result = {
                "flows": flows,
                "count": len(flows),
                "as_of": flows[-1].get("date") if flows else None,
                "available_categories": [],
                "missing_categories": ["FII", "DII"],
                "incomplete_dates": [flow.get("date") for flow in flows],
                "data_status": "partial" if flows else "unavailable",
            }
        return {
            "lookback_days": lookback_days,
            **flow_result,
        }
    except Exception:
        logger.error("Institutional flows request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/delivery-anomalies")
async def get_delivery_anomalies(
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers or portfolio"),
    lookback_days: int = Query(default=20, ge=5, le=60, description="Rolling baseline window"),
    sigma_threshold: float = Query(default=2.0, ge=1.0, le=5.0, description="Z-score threshold for anomaly flag"),
    db: AsyncSession = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    Detect delivery percentage spikes (> N sigma over 20-day mean) across portfolio holdings.
    """
    try:
        if isinstance(tickers, str) and tickers.strip():
            parsed = _parse_tickers(tickers)
            symbol_list = [t for t in (parsed or "").split(",") if t]
        else:
            symbol_list = await _load_portfolio_tickers(db)

        if not symbol_list:
            return {
                "anomalies": [],
                "count": 0,
                "message": "No tickers found",
                "data_status": "unavailable",
                "as_of": None,
            }

        from app.services.india_data_service import IndiaDataService
        india_svc = IndiaDataService(db=db)
        delivery_result = await india_svc.get_delivery_anomalies(
            symbols=symbol_list,
            lookback_days=lookback_days,
            sigma_threshold=sigma_threshold,
            return_metadata=True,
        )
        if isinstance(delivery_result, list):
            # Preserve compatibility with older injected service doubles while
            # still exposing an explicit status to the exporter.
            delivery_result = {
                "anomalies": delivery_result,
                "count": len(delivery_result),
                "data_status": "available" if delivery_result else "unavailable",
                "as_of": None,
            }
        return {
            "lookback_days": lookback_days,
            "sigma_threshold": sigma_threshold,
            **delivery_result,
        }
    except HTTPException:
        raise
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except Exception:
        logger.error("Delivery anomalies request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/liquidity-limits")
async def get_liquidity_limits(
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers or portfolio"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service)
) -> Dict[str, Any]:
    """
    Compute participation-based liquidation limits (days-to-liquidate @ 10% & 20% ADV),
    Amihud illiquidity metric, and maximum sane position sizing.
    """
    try:
        if isinstance(tickers, str) and tickers.strip():
            parsed = _parse_tickers(tickers)
            ticker_list = [t for t in (parsed or "").split(",") if t]
            positions = [
                PortfolioPosition(ticker=t, weight=1.0 / len(ticker_list), quantity=100.0, buy_price=100.0, last_price=100.0, market_value=10000.0)
                for t in ticker_list
            ]
            ad_hoc = True
        else:
            result = await db.execute(select(PortfolioPosition))
            positions = result.scalars().all()
            ad_hoc = False

        if not positions:
            return {
                "portfolio_value": 0.0,
                "currency": "INR",
                "base_currency": "INR",
                "currency_provenance": {
                    "aggregation": "empty",
                    "base_currency": "INR",
                },
                "portfolio_weighted_days_to_liquidate_10pct": 0.0,
                "portfolio_weighted_days_to_liquidate_20pct": 0.0,
                "portfolio_amihud_score": 0.0,
                "positions": [],
                "message": "No positions found",
                "data_status": "unavailable",
                "universe_coverage": _universe_coverage([], []),
                "zero_metrics": True
            }

        converted_values, currency_provenance = await _convert_analytics_positions(
            positions
        )
        fx_rates = {}
        for position in positions:
            source_currency = _analytics_position_currency(position)
            pair = currency_provenance.get("pairs", {}).get(
                f"{source_currency}->INR", {}
            )
            fx_rates[position.ticker] = float(pair.get("rate", 1.0) or 1.0)

        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')

        price_dfs = {}
        fetch_failures: Dict[str, str] = {}
        for p in positions:
            try:
                df = await data_service.fetch_historical_data(p.ticker, start, end)
            except Exception as exc:
                fetch_failures[p.ticker] = type(exc).__name__
                logger.warning("Liquidity history unavailable for %s: %s", p.ticker, type(exc).__name__)
                continue
            if df is not None and not df.empty:
                price_dfs[p.ticker] = df

        from app.services.india_data_service import IndiaDataService
        india_svc = IndiaDataService(db=db)
        result_payload = await india_svc.calculate_portfolio_liquidity_limits(
            positions=positions,
            price_history=price_dfs,
            converted_values=converted_values,
            fx_rates=fx_rates,
            base_currency="INR",
            currency_provenance=currency_provenance,
        )
        requested_tickers = [p.ticker for p in positions]
        coverage = _universe_coverage(requested_tickers, price_dfs.keys())
        coverage["failed_tickers"] = sorted(fetch_failures)
        result_payload["universe_coverage"] = coverage
        result_payload["latest_observation_date"] = _latest_observation_date(price_dfs)
        if fetch_failures:
            result_payload.setdefault("warnings", []).append(
                "Missing price history: " + ", ".join(sorted(fetch_failures))
            )
        if coverage["status"] == "unavailable":
            result_payload["data_status"] = "unavailable"
        elif coverage["status"] == "partial":
            result_payload["data_status"] = "partial"
        if ad_hoc:
            # Synthetic per-ticker placeholders must not masquerade as a real
            # portfolio valuation.
            result_payload["mode"] = "ad_hoc"
            result_payload["portfolio_value"] = None
        return result_payload
    except HTTPException:
        raise
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except Exception:
        logger.error("Liquidity limits request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/vol-cone")
async def get_volatility_cone(
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers or portfolio"),
    lookback_days: int = Query(default=756, ge=60, le=2520, description="Lookback window in days"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
) -> Dict[str, Any]:
    """
    Realized volatility term structure cone (10, 21, 63, 126, 252d quantile bands)
    and current GARCH(1,1) forward volatility forecast.
    """
    try:
        try:
            ticker_list, weights = await resolve_allocation(tickers, db)
        except ValueError:
            raise HTTPException(status_code=404, detail="Requested resource not found")

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        _, port_ret, history_coverage = await _build_wide_returns(
            ticker_list, weights, start, end, data_service
        )

        if len(port_ret) < 30:
            raise HTTPException(status_code=400, detail="Insufficient return history for volatility cone")

        from app.services.volatility_service import VolatilityService
        cone_data = await _run_cpu(VolatilityService.calculate_volatility_cone, port_ret)
        coverage = _universe_coverage(
            ticker_list,
            history_coverage.get("model_used_tickers", []),
        )
        if isinstance(cone_data, dict):
            cone_data["universe_coverage"] = coverage
            cone_data["data_status"] = (
                "unavailable" if coverage["status"] == "unavailable"
                else "partial" if coverage["status"] == "partial" or len(port_ret) < MIN_ANNUALIZE_DAYS
                else "available"
            )
            cone_data["latest_observation_date"] = _latest_observation_date(port_ret)
        return cone_data
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid analytics request")
    except HTTPException:
        raise
    except Exception:
        logger.error("Volatility cone request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


# /tails response memoization — the pairwise copula fit is O(n²) (~12s for 14
# assets) and Risk Studio fires it on every load. Date-keyed: `end` rolls over
# daily, so staleness is bounded by the calendar day.
_TAILS_CACHE_TTL_SECONDS = 900
_TAILS_RESPONSE_CONTRACT_VERSION = 2
_TAILS_RESPONSE_CACHE: Dict[Tuple, Tuple[float, Dict[str, Any]]] = {}
_TAILS_CACHE_GENERATION = 0

# Max live entries: different lookback/confidence keys would otherwise grow unbounded.
_TAILS_CACHE_MAX_ENTRIES = 32


def _normalised_weights_key(weights: Dict[str, float]) -> Tuple[Tuple[str, float], ...]:
    """Stable allocation identity for weight-dependent memo entries."""
    total = sum(max(0.0, float(value or 0.0)) for value in weights.values())
    if total <= 0:
        normalised = {str(ticker).upper(): 0.0 for ticker in weights}
    else:
        normalised = {
            str(ticker).upper(): max(0.0, float(value or 0.0)) / total
            for ticker, value in weights.items()
        }
    return tuple(sorted((ticker, round(value, 12)) for ticker, value in normalised.items()))


def clear_tails_cache() -> None:
    """Drop memoized tails and invalidate computations already in flight."""
    global _TAILS_CACHE_GENERATION
    _TAILS_CACHE_GENERATION += 1
    _TAILS_RESPONSE_CACHE.clear()


@router.get("/tail-dependence")
@router.get("/tails")
async def get_tail_risk_and_copula(
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers or portfolio"),
    lookback_days: int = Query(default=756, ge=60, le=2520, description="Lookback window in days"),
    confidence_level: float = Query(default=0.99, ge=0.90, le=0.999, description="Confidence level for EVT VaR"),
    threshold_quantile: float = Query(default=0.95, ge=0.80, le=0.98, description="POT threshold quantile"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
) -> Dict[str, Any]:
    """
    Extreme Value Theory (EVT) Peaks-Over-Threshold 99% VaR/Expected Shortfall
    and pairwise Student-t Copula lower-tail dependence crash comovement matrix.
    """
    try:
        try:
            ticker_list, weights = await resolve_allocation(tickers, db)
        except ValueError:
            raise HTTPException(status_code=404, detail="Requested resource not found")

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        cache_key = (
            _TAILS_RESPONSE_CONTRACT_VERSION,
            tuple(ticker_list), start, end, confidence_level,
            threshold_quantile, _normalised_weights_key(weights),
        )
        cache_generation = _TAILS_CACHE_GENERATION
        cached = _TAILS_RESPONSE_CACHE.get(cache_key)
        if cached is not None and (time.monotonic() - cached[0]) < _TAILS_CACHE_TTL_SECONDS:
            return cached[1]
        wide_ret, port_ret, _ = await _build_wide_returns(ticker_list, weights, start, end, data_service)

        if len(port_ret) < 30:
            raise HTTPException(status_code=400, detail="Insufficient return history for tail risk modeling")

        from app.services.tail_risk_service import TailRiskService

        def _calculate_tail_sync():
            evt = TailRiskService.calculate_evt_pot_var_es(
                port_ret, confidence_level=confidence_level, threshold_quantile=threshold_quantile
            )
            matrix = TailRiskService.calculate_tail_dependence_matrix(wide_ret)
            return evt, matrix

        evt_stats, tail_copula_matrix = await _run_cpu(_calculate_tail_sync)

        matrix_tickers = list((tail_copula_matrix or {}).get("tickers", []))
        coverage = _universe_coverage(ticker_list, matrix_tickers)
        response = {
            **evt_stats,
            "tail_dependence_matrix": tail_copula_matrix,
            # Keep the legacy top-level list aligned with the matrix it describes.
            "tickers": matrix_tickers,
            "requested_tickers": ticker_list,
            "universe_coverage": coverage,
            "data_status": coverage["status"],
            "observations": len(port_ret),
        }
        if cache_generation == _TAILS_CACHE_GENERATION:
            _TAILS_RESPONSE_CACHE[cache_key] = (time.monotonic(), response)
            # Evict oldest entries beyond the cap (insertion order == age order).
            while len(_TAILS_RESPONSE_CACHE) > _TAILS_CACHE_MAX_ENTRIES:
                _TAILS_RESPONSE_CACHE.pop(next(iter(_TAILS_RESPONSE_CACHE)))
        return response
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid analytics request")
    except Exception:
        logger.error("Tail dependence request failed")
        raise HTTPException(status_code=500, detail="Internal server error")

