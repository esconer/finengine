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
from app.services.cointegration_service import (
    TEST_ROLES,
    UNIVERSE_SCOPES,
    CointegrationService,
    shallow_tickers,
    usable_observations_by_ticker,
)
from app.utils.allocations import (
    WEIGHT_NORMALIZATION_RULE,
    normalization_block,
    normalize_rebalance_weights,
    sizing_history_block,
)
from app.utils.holdings import (
    MIN_ANNUALIZE_DAYS,
    analytics_start_claim,
    annualizable,
    apply_annualization_gate,
    coerce_holding_date,
    effective_start,
    effective_start_detail,
    holding_coverage,
    holding_window,
    holding_window_detail,
    position_history_note,
    position_limited_history,
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


# Shared export vocabulary (see docs/ai-context.md).
#   data_status  -> available | partial | unavailable   (was there measured data?)
#   coverage     -> complete | partial | unavailable | unknown (universe completeness)
# The two are independent: coverage completeness stays inside `universe_coverage`
# and never leaks into the public `data_status` field.
DATA_STATUS_AVAILABLE = "available"
DATA_STATUS_PARTIAL = "partial"
DATA_STATUS_UNAVAILABLE = "unavailable"
DATA_STATUS_VOCABULARY = (
    DATA_STATUS_AVAILABLE,
    DATA_STATUS_PARTIAL,
    DATA_STATUS_UNAVAILABLE,
)
_COVERAGE_TO_DATA_STATUS = {
    "complete": DATA_STATUS_AVAILABLE,
    "partial": DATA_STATUS_PARTIAL,
    "unavailable": DATA_STATUS_UNAVAILABLE,
}
# One canonical weight-basis claim: a positive-weight leg was dropped and the
# surviving active weights were renormalized back to 100%.
ACTIVE_WEIGHT_BASIS = "active_weights_renormalized_to_100_percent"

# Risk scoring is stateless — no prior score is persisted — so a period-over-period
# delta cannot be computed. Every unavailable branch published `change: 0`, which
# reads as a measured "unchanged" score. The honest state is an explicit null with
# a machine-readable reason, so a consumer never mistakes it for a real delta.
RISK_SCORE_CHANGE_UNAVAILABLE: Dict[str, Any] = {
    "change": None,
    "change_status": "unavailable",
    "change_reason": "no_persisted_prior_score",
}


def _ticker_sequence(value: Optional[Iterable[Any]]) -> List[str]:
    """Uppercased, de-duplicated ticker list that preserves first-seen order."""
    if value is None:
        return []
    ordered: List[str] = []
    seen = set()
    for item in value:
        ticker = str(item).strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            ordered.append(ticker)
    return ordered


def _ordered_universe(requested: List[str], available: Iterable[str]) -> List[str]:
    """Deterministic ticker order: request order first, extras sorted."""
    available_set = set(available)
    extras = sorted(available_set - set(requested))
    return [ticker for ticker in requested if ticker in available_set] + extras


def _data_status(
    coverage: Optional[Mapping[str, Any]] = None,
    *,
    partial: bool = False,
    unavailable: bool = False,
) -> str:
    """Return a public `data_status` from the documented vocabulary.

    `coverage` supplies the universe-completeness signal; `partial` names an
    extra degradation (limited history, engine error, short sample) and
    `unavailable` forces the explicit no-measured-data state. An `unknown`
    coverage status (market-wide payload with no ticker universe) is not a
    data failure, so it contributes no demotion on its own.
    """
    status = DATA_STATUS_AVAILABLE
    if isinstance(coverage, Mapping):
        status = _COVERAGE_TO_DATA_STATUS.get(
            str(coverage.get("status") or "").strip().lower(),
            DATA_STATUS_AVAILABLE,
        )
    if unavailable:
        return DATA_STATUS_UNAVAILABLE
    if partial and status == DATA_STATUS_AVAILABLE:
        return DATA_STATUS_PARTIAL
    return status


def _universe_coverage(
    requested: Iterable[str],
    available: Iterable[str],
    *,
    active: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Describe the exact requested/available ticker universe for a result.

    Ordering is deterministic: `requested_tickers` keeps first-seen request
    order and every other list follows that order (extras appended sorted), so
    a repeated universe exports identically.

    `weight_basis` is emitted only when a weight-bearing leg (an entry of
    `active`, i.e. a positive finite portfolio weight) was actually dropped
    from the delivered universe, which is exactly when the surviving active
    weights were renormalized to 100%. Weightless analyses and coverage gaps
    made up only of zero-value rows never claim an allocation basis.
    """
    requested_list = _ticker_sequence(requested)
    available_set = set(_ticker_sequence(available))
    available_list = _ordered_universe(requested_list, available_set)
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
    coverage: Dict[str, Any] = {
        "requested_tickers": requested_list,
        "available_tickers": available_list,
        "covered_tickers": covered,
        "missing_tickers": missing,
        "requested_count": len(requested_list),
        "available_count": len(covered),
        "coverage_ratio": round(len(covered) / len(requested_list), 6) if requested_list else None,
        "complete": not missing if requested_list else None,
        "status": status,
    }
    if active is not None:
        active_list = _ticker_sequence(active)
        if any(ticker not in available_set for ticker in active_list):
            coverage["weight_basis"] = ACTIVE_WEIGHT_BASIS
    return coverage


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


def _observation_date(label: Any) -> Optional[str]:
    """ISO date for a real date-ish index label, else None.

    A RangeIndex label is a row number, not a date. Converting it would
    fabricate the freshness claim the history blocks exist to make, so a
    positional label yields None exactly like `app.utils.allocations` does.
    """
    if label is None or isinstance(label, bool):
        return None
    if isinstance(label, (int, float, np.integer, np.floating)):
        return None
    try:
        stamp = pd.Timestamp(label)
    except (ValueError, TypeError, OverflowError):
        return None
    if pd.isna(stamp):
        return None
    return stamp.date().isoformat()


def _observation_bounds(frame: Any) -> Tuple[Optional[str], Optional[str]]:
    """First and last dated observation of a frame or series index."""
    index = getattr(frame, "index", None)
    if index is None or len(index) == 0:
        return None, None
    return _observation_date(index[0]), _observation_date(index[-1])


def _return_observation_counts(returns: Any) -> Dict[str, int]:
    """Measured return count per ticker; nothing is imputed for a gap."""
    if isinstance(returns, pd.DataFrame):
        return {str(ticker): int(returns[ticker].notna().sum()) for ticker in returns.columns}
    if isinstance(returns, pd.Series):
        name = str(returns.name) if returns.name is not None else "series"
        return {name: int(returns.notna().sum())}
    return {}


def _history_window(
    requested_start: Optional[str],
    requested_end: Optional[str],
    returns: Any,
    *,
    price_frame: Any = None,
) -> Dict[str, Any]:
    """The window that was asked for next to the window that was measured.

    `requested_end` is a request, never evidence: `first_observation` and
    `latest_observation` are the delivered price dates and
    `return_observations` counts the returns actually computed, so a caller can
    tell a 2-day answer from a 252-day one without trusting the request. The
    minimum-sample gate matches the annualization gate used everywhere else, so
    "short history" means one thing across sizing and realized risk.
    """
    counts = _return_observation_counts(returns)
    observations = (
        int(len(returns)) if isinstance(returns, (pd.DataFrame, pd.Series)) else 0
    )
    first, latest = _observation_bounds(price_frame)
    if first is None or latest is None:
        return_first, return_latest = _observation_bounds(returns)
        first = first if first is not None else return_first
        latest = latest if latest is not None else return_latest
    meets = bool(
        counts
        and observations >= MIN_ANNUALIZE_DAYS
        and min(counts.values()) >= MIN_ANNUALIZE_DAYS
    )
    return {
        "requested_start": requested_start,
        "requested_end": requested_end,
        "first_observation": first,
        "latest_observation": latest,
        "return_observations": observations,
        "per_ticker_return_observations": counts,
        "minimum_observations_required": MIN_ANNUALIZE_DAYS,
        "meets_minimum_sample": meets,
    }


# --- Per-position own-sample measurement (V3-06) -----------------------------
# A position's annualization gate, its limited-history flag and every number in
# its disclosure line are read from THIS function's output: the non-null returns
# that ticker itself produced. Portfolio-wide and global counts are never
# consulted, because a 176-observation book does not make a 20-observation leg
# "full history" - that mislabelling is exactly what the gate exists to stop.
def _own_return_observations(frame: Any) -> Dict[str, int]:
    """Non-null return observations per ticker, measured from `frame` itself.

    Mirrors the engine's own per-position sample (union index kept, so an
    interior gap stays a gap rather than becoming a synthetic multi-day
    return). A frame that is not a dated `DataFrame` measures nothing and
    returns an empty map rather than an invented count.
    """
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {}
    cleaned = frame.replace([np.inf, -np.inf], np.nan).sort_index()
    returns = cleaned.pct_change(fill_method=None)
    if len(returns) < 2:
        return {}
    returns = returns.iloc[1:]
    return {str(ticker): int(returns[ticker].notna().sum()) for ticker in returns.columns}


def _holding_window_row_mask(
    frame: Any,
    effectives: Mapping[str, Optional[str]],
) -> Tuple[int, pd.Series]:
    """Rows of a delivered frame that fall inside the holding window.

    Counted on the delivered index against the stored intersection start, so a
    route that runs its model on full history can still state how much of that
    index the user actually held. A dateless frame carries no holding
    information, so every row counts and the tenure stays hypothetical rather
    than guessed.
    """
    index = getattr(frame, "index", None)
    if not isinstance(index, pd.DatetimeIndex) or len(index) == 0:
        return (int(len(index)) if index is not None else 0,
                pd.Series(True, index=index if index is not None else []))
    known = [value for value in (effectives or {}).values() if isinstance(value, str)]
    if not known:
        return len(index), pd.Series(True, index=index)
    try:
        cutoff = pd.Timestamp(max(known)).normalize()
    except (TypeError, ValueError, OverflowError):
        return len(index), pd.Series(True, index=index)
    mask = index.normalize() >= cutoff
    return int(mask.sum()), mask


def _position_provenance(detail: Optional[Mapping[str, Any]], ticker: str) -> Dict[str, Any]:
    """One ticker's holding-window start with the source that produced it."""
    entry = detail.get(ticker) if isinstance(detail, Mapping) else None
    entry = entry if isinstance(entry, Mapping) else {}
    return {
        "analytics_start": entry.get("analytics_start"),
        "analytics_start_source": entry.get("analytics_start_source"),
        "stored_added_on": entry.get("stored_added_on"),
        "buy_price_inferred": entry.get("buy_price_inferred"),
    }


# --- Full-history model evidence (V3-05) -------------------------------------
# Factor Exposure and Risk Contribution are hypothetical current-weight
# questions answered over FULL exchange history. They must never publish a
# holding `effective_start`/`truncated` flag: doing so claims a model window was
# cut to a holding window it never used. So the model's own evidence lives in a
# SEPARATE object and the holding window stays explicitly ancillary.
FULL_HISTORY_BASIS = "full_exchange_history_current_weights"
HOLDING_CONTEXT_SCOPE = "holding_context_ancillary"
FULL_HISTORY_RELATION = (
    "Holding context is ancillary: it never shortens, lengthens or "
    "annualizes this model window."
)


def _full_history_evidence(
    returns_frame: Any,
    *,
    requested_start: Optional[str],
    requested_end: Optional[str],
    declared_limited: Optional[Mapping[str, bool]] = None,
    coverage_reasons: Optional[Mapping[str, Optional[str]]] = None,
) -> Dict[str, Any]:
    """Self-describing evidence for a model measured on full exchange history.

    Takes the RETURN frame the model actually consumed, so the published window
    and observation count describe the observations used and nothing is
    double-counted by re-deriving returns from an already-returned frame.

    Own window, own observation count, own latest observation and own
    annualization flag. Sparse or late-listed legs are published with their own
    usable observation count and limited-history flag instead of being averaged
    away by the rest of the book.
    """
    frame = returns_frame if isinstance(returns_frame, pd.DataFrame) else pd.DataFrame()
    clean = frame.replace([np.inf, -np.inf], np.nan) if not frame.empty else frame
    counts = (
        {str(ticker): int(clean[ticker].notna().sum()) for ticker in clean.columns}
        if not clean.empty
        else {}
    )
    finite = (
        {
            str(ticker): int(np.isfinite(clean[ticker].to_numpy(dtype=float)).sum())
            for ticker in clean.columns
        }
        if not clean.empty
        else {}
    )
    first, last = _observation_bounds(frame)
    observations = int(len(frame))
    flags = declared_limited or {}
    reasons = coverage_reasons or {}
    tickers: Dict[str, Any] = {}
    for ticker in sorted(set(counts) | set(finite)):
        count = int(counts.get(ticker, 0))
        tickers[ticker] = {
            "return_observations": count,
            "usable_observations": int(finite.get(ticker, count)),
            "limited_history": position_limited_history(
                count, bool(flags.get(ticker, False))
            ),
            "coverage_reason": reasons.get(ticker),
        }
    meets = bool(
        observations >= MIN_ANNUALIZE_DAYS
        and counts
        and min(counts.values()) >= MIN_ANNUALIZE_DAYS
    )
    return {
        "basis": FULL_HISTORY_BASIS,
        "scope": "full_exchange_history",
        "truncated_to_holding_window": False,
        "requested_window": {"start": requested_start, "end": requested_end},
        "window": {"start": first, "end": last, "days": observations},
        "first_observation": first,
        "last_observation": last,
        "latest_observation_date": _latest_observation_date(frame),
        "observation_count": observations,
        "per_ticker_return_observations": counts,
        "annualized": meets,
        "minimum_observations_required": MIN_ANNUALIZE_DAYS,
        "model_used_tickers": [str(c) for c in frame.columns],
        "tickers": tickers,
        "holding_context_note": FULL_HISTORY_RELATION,
    }


def _model_history_coverage(
    holding_context: Mapping[str, Any],
    full_history: Mapping[str, Any],
) -> Dict[str, Any]:
    """`history_coverage` for a full-history model: model evidence + ancillary holdings.

    `truncated` is `False` and `effective_start` is `None` at the top level
    because neither describes this model; the holding window is reachable only
    under `holding_context`, where its own `covered_days`/`annualized` describe
    the holding tenure rather than the model sample.
    """
    return {
        "scope": HOLDING_CONTEXT_SCOPE,
        "calculation_basis": full_history.get("basis", FULL_HISTORY_BASIS),
        "full_history": dict(full_history),
        "holding_context": dict(holding_context),
        "holding_window_days": holding_context.get("covered_days"),
        # Model-scoped mirrors. The holding window never writes these.
        "annualized": bool(full_history.get("annualized")),
        "truncated": False,
        "covered_days": full_history.get("observation_count"),
        "covered_days_scope": "model_return_observations",
        "model_observation_count": full_history.get("observation_count"),
        "model_window": full_history.get("window"),
        "effective_start": None,
        "intersection_start": holding_context.get("intersection_start"),
        "oldest_holding": holding_context.get("oldest_holding"),
        "requested_start": holding_context.get("requested_start"),
        "requested_end": holding_context.get("requested_end"),
        "tickers": holding_context.get("tickers", {}),
    }


def _conditional_regime_coverage(
    regime_summary: Mapping[str, Any],
    holding_context: Mapping[str, Any],
) -> Dict[str, Any]:
    """Coverage for the CURRENT-REGIME conditional sample (V3-05).

    The conditional block measures the portfolio return days the classifier
    assigned to the current regime - 19 days where the holding window holds 39
    and the HMM model holds 252. Publishing the holding window's numbers there
    described a sample that was never taken, so `covered_days`, `annualized`
    and `truncated` all read the conditional sample and the holding window is
    demoted to an explicitly labelled pool.
    """
    try:
        sample = int(regime_summary.get("days"))
    except (TypeError, ValueError):
        sample = 0
    try:
        pool = int(holding_context.get("covered_days") or 0)
    except (TypeError, ValueError):
        pool = 0
    return {
        "scope": "conditional_current_regime",
        "conditional": True,
        "sample_basis": (
            "Portfolio return days classified into the current regime; the "
            "holding window below is the pool it was drawn from, not the sample."
        ),
        "observations": sample,
        "covered_days": sample,
        "covered_days_scope": "conditional_regime_return_days",
        "annualized": annualizable(sample),
        "minimum_observations_required": MIN_ANNUALIZE_DAYS,
        # A conditional sample can only be as long as the pool it is drawn
        # from; that gap is what `truncated` reports here.
        "truncated": bool(pool and sample < pool),
        "holding_window_days": pool or None,
        "requested_start": holding_context.get("requested_start"),
        "requested_end": holding_context.get("requested_end"),
        "effective_start": None,
        "intersection_start": holding_context.get("intersection_start"),
        "oldest_holding": holding_context.get("oldest_holding"),
        "holding_context": dict(holding_context),
    }


# --- Canonical holding-window publication (V3-08) ---------------------------
# ONE rule for "when did this composition start?", used by every section that
# publishes a holding window. The v4 export answered it three ways and the same
# portfolio then carried three different holding dates:
#
#   * the buy-price inference was fed whatever price frames the SECTION
#     happened to fetch, so a 1100-day regime window inferred a date 10.7
#     months earlier than a 252-day realized-risk window did for the very same
#     stored `added_on` (and published it as a bare `effective_start`, with no
#     source, so it read as a holding date nobody had stored);
#   * the counts were measured in different units - masked price rows, aligned
#     return rows, model return observations - and one section held no price
#     frames at all, so it answered with the stored date and moved the window
#     start by a day;
#   * nothing declared the unit of a count, so 39 and 40 were both "the
#     holding window" in one export.
#
# The rule, in one place: a position's window start is its stored import date,
# or an earlier buy-price match found INSIDE the canonical evidence window
# (HOLDING_PROVENANCE_LOOKBACK_DAYS days ending at the section's requested
# end). The evidence window is a function of the request's END, never of the
# route's own analytics window, so a 1100-day HMM window and a 365-day
# tear-sheet request resolve the same date for the same stored position.
# Counts are return observations that two HELD prices can produce, under one
# label. Provenance is attached to every start, and a section that could not
# read the evidence says so with a reason instead of answering differently.
#
# `get_realized_risk` (the reference section) resolves the same rule from its
# own requested window; that window and the canonical one coincide whenever it
# is asked for its default horizon, and `provenance_evidence_window` publishes
# the window a section actually used so any difference is declared, not silent.

#: Calendar days of price evidence the buy-price inference may look at, anchored
#: to the section's requested end. Mirrors the realized-risk default horizon
#: (`_date_window(..., default_days=252)`), so the reference section and every
#: publisher of a holding window resolve a position from the same bars. A wider
#: or narrower analytics window cannot change a holding date.
HOLDING_PROVENANCE_LOOKBACK_DAYS = 252

#: The unit of a holding window's observation count, used by every section: the
#: return observations that fall entirely inside the holding window. The bar on
#: the start date is the first HELD price and has no held predecessor, so it
#: cannot produce one - which is why 40 price rows are 39 return observations.
#: Publishing a price-row count and a return-row count under the same name is
#: how one portfolio reported 39 days in one section and 40 in another.
HOLDING_COVERED_DAYS_SCOPE = "holding_window_aligned_return_rows"

HOLDING_PROVENANCE_RULE = (
    "One window start per position for every section: the stored import date, "
    "or an earlier close within tolerance of the buy price found inside the "
    f"canonical evidence window ({HOLDING_PROVENANCE_LOOKBACK_DAYS} calendar "
    "days ending at the section's requested end). A start that differs from the "
    "stored import date is always published as buy_price_inferred beside that "
    "stored date, and the evidence window used is published with it."
)

#: `evidence_source` values, so a consumer can tell a resolved start from a
#: degraded one without parsing prose.
HOLDING_EVIDENCE_IN_HAND = "in_hand_price_frames"
HOLDING_EVIDENCE_CANONICAL = "canonical_window_price_frames"
HOLDING_EVIDENCE_STORED_ONLY = "stored_dates_only"


def holding_evidence_window(
    end: Any,
    *,
    lookback_days: int = HOLDING_PROVENANCE_LOOKBACK_DAYS,
) -> Dict[str, Any]:
    """The canonical buy-price evidence window for one requested end date.

    Deterministic and clock-free: no `now()` read, so re-running the same
    request with the same end reproduces the same holding dates. An
    unparseable end yields a `None` start and the caller answers with stored
    dates - a window is never guessed.
    """
    end_s = end if isinstance(end, str) and end else None
    start: Optional[str] = None
    days: Optional[int] = None
    if end_s:
        try:
            stamp = pd.Timestamp(end_s)
        except (TypeError, ValueError, OverflowError):
            stamp = None
        if stamp is not None and not pd.isna(stamp):
            days = int(lookback_days)
            start = (stamp - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    return {"start": start, "end": end_s, "days": days}


def _evidence_frames(
    frames: Optional[Dict[str, pd.Series]],
    window: Mapping[str, Any],
) -> Dict[str, pd.Series]:
    """Price frames cut to the canonical evidence window.

    A section may hand over the wide frames it already holds (the regime model
    window is 1100 days); the inference only ever sees the canonical slice, so
    a wider window cannot resolve an earlier date than a narrower one. A
    dateless or empty series carries no date evidence and is dropped rather
    than guessed at.
    """
    start = window.get("start") if isinstance(window, Mapping) else None
    if not frames or not isinstance(start, str):
        return {}
    try:
        cutoff = pd.Timestamp(start).normalize()
    except (TypeError, ValueError, OverflowError):
        return {}
    out: Dict[str, pd.Series] = {}
    for ticker, series in frames.items():
        index = getattr(series, "index", None)
        if series is None or not isinstance(index, pd.DatetimeIndex) or len(index) == 0:
            continue
        if index.tz is not None:
            index = index.tz_localize(None)
        sliced = series.loc[index.normalize() >= cutoff]
        if len(sliced):
            out[ticker] = sliced
    return out


async def holding_provenance(
    data_service: DataService,
    holdings: Optional[Dict[str, Dict[str, Any]]],
    tickers: Optional[Iterable[str]],
    *,
    end: Any,
    frames: Optional[Dict[str, pd.Series]] = None,
) -> Dict[str, Any]:
    """THE holding-window start rule, for every section that publishes one.

    Returns the `effective_start_detail` map, the per-ticker starts, the block
    start and the evidence window that produced them - one answer per position,
    whichever section asked.

    `frames` are price frames the caller already holds; only their canonical
    slice feeds the inference. When the caller holds none, the canonical window
    is read through the same cache-first `DataService` that section's own leg
    already used. It is a strict sub-window of the request every one of these
    sections makes, so the read is served from the cache that leg populated
    rather than from the vendor - and it is what removes the "no price frames,
    so answer with the stored date" downgrade. A read that yields nothing
    degrades to stored import dates and declares it (`evidence_source` =
    `stored_dates_only`, plus a `provenance_divergence_reason` on the payload),
    because quietly answering differently is the defect this removes.
    """
    window = holding_evidence_window(end)
    evidence = _evidence_frames(frames, window)
    source = HOLDING_EVIDENCE_IN_HAND
    if not evidence and tickers and isinstance(window.get("start"), str):
        ordered = list(dict.fromkeys(tickers or []))
        fetched: Dict[str, pd.Series] = {}
        if ordered:
            try:
                fetched = await _fetch_price_series_dict(
                    data_service, ordered, window["start"], window["end"]
                )
            except Exception:  # noqa: BLE001 - provenance never fails a route
                logger.warning(
                    "Holding provenance evidence unavailable; answering with stored dates",
                    exc_info=True,
                )
        evidence = _evidence_frames(fetched, window)
        source = HOLDING_EVIDENCE_CANONICAL if evidence else HOLDING_EVIDENCE_STORED_ONLY
    detail = effective_start_detail(holdings, evidence)
    effectives = {
        ticker: entry.get("analytics_start")
        for ticker, entry in detail.items()
        if isinstance(entry, Mapping)
    }
    return {
        "detail": detail,
        "effectives": effectives,
        "start": effective_start(effectives),
        "evidence_window": {**window, "source": source},
    }


def canonical_holding_window_input(
    detail: Optional[Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Holdings map that pins a masked leg to the canonical start.

    The canonical start is handed over AS the import date and the buy price is
    withheld, so `_build_wide_returns` masks at the canonical cutoff and no
    second inference - however wide that leg's own price window is - can move
    the date afterwards. Unknown starts stay absent, exactly as before: they
    never constrain the window.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for ticker, entry in (detail or {}).items():
        if not isinstance(entry, Mapping):
            continue
        start = entry.get("analytics_start")
        if isinstance(start, str):
            out[ticker] = {"added_on": start, "buy_price": None}
    return out


def holding_window_observation_count(
    frame: Any,
    start: Optional[str],
    *,
    measured_count: Optional[int] = None,
    measured_start: Optional[str] = None,
) -> Tuple[int, Optional[pd.Series]]:
    """(count, mask) of the return observations inside the holding window.

    The unit every section publishes: a return needs two HELD prices, and the
    bar on `start` is the first held price, so only rows strictly after `start`
    count. An unknown start or a dateless frame carries no holding
    information - every row counts and the tenure stays hypothetical rather
    than guessed.

    `measured_count` / `measured_start` let a caller whose frame was already
    masked at this very start hand its own measurement in rather than
    re-deriving one; a frame masked to a different start is measured here, and
    the returned mask is what the caller re-cuts the frame to.
    """
    index = getattr(frame, "index", None)
    if index is None:
        return (int(measured_count) if isinstance(measured_count, int) else 0), None
    if not isinstance(index, pd.DatetimeIndex) or len(index) == 0 or not isinstance(start, str):
        return int(len(index)), pd.Series(True, index=index)
    try:
        cutoff = pd.Timestamp(start).normalize()
    except (TypeError, ValueError, OverflowError):
        return int(len(index)), pd.Series(True, index=index)
    normalized = index.tz_localize(None) if index.tz is not None else index
    mask = pd.Series(normalized.normalize() > cutoff, index=index)
    if measured_start == start and isinstance(measured_count, int):
        # The frame was masked at this very start, so its count IS this count.
        return measured_count, mask
    return int(mask.sum()), mask


def _coverage_per_ticker(
    coverage: Optional[Mapping[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Per-ticker measured counts carried by a `_build_wide_returns` coverage."""
    entries = coverage.get("tickers") if isinstance(coverage, Mapping) else None
    out: Dict[str, Dict[str, Any]] = {}
    for ticker, entry in (entries or {}).items():
        if not isinstance(entry, Mapping):
            continue
        out[ticker] = {
            key: entry[key]
            for key in (
                "raw_days", "masked_days", "return_observations",
                "limited_history", "coverage_reason",
            )
            if key in entry
        }
    return out


def publish_holding_coverage(
    *,
    detail: Mapping[str, Any],
    per_ticker: Optional[Mapping[str, Mapping[str, Any]]],
    requested_start: Any,
    requested_end: Any,
    covered_days: int,
    evidence_window: Mapping[str, Any],
    covered_days_scope: str = HOLDING_COVERED_DAYS_SCOPE,
) -> Dict[str, Any]:
    """The one holding-window payload every one of these sections publishes.

    `holding_coverage` (app/utils/holdings.py) does the work - starts,
    provenance, truncation, annualization. This adds the two fields that used
    to be decided per section: the unit the count is measured in, and the
    evidence window the starts were resolved against. So every published start
    arrives with the source that produced it, every count with its unit, and a
    section that resolved its starts without price evidence publishes the
    reason beside them instead of quietly disagreeing with the others.
    """
    starts = {
        ticker: entry.get("analytics_start")
        for ticker, entry in (detail or {}).items()
        if isinstance(entry, Mapping)
    }
    counts = {
        ticker: dict(counts) for ticker, counts in (per_ticker or {}).items()
        if isinstance(counts, Mapping)
    }
    payload = holding_coverage(
        starts,
        requested_start,
        requested_end,
        int(covered_days),
        counts,
        provenance=detail or {},
    )
    payload["covered_days_scope"] = covered_days_scope
    payload["provenance_rule"] = HOLDING_PROVENANCE_RULE
    payload["provenance_evidence_window"] = dict(evidence_window or {})
    if requested_end is not None:
        payload["requested_end"] = requested_end
    if (evidence_window or {}).get("source") == HOLDING_EVIDENCE_STORED_ONLY:
        payload["provenance_divergence_reason"] = (
            "No price evidence was readable for the canonical window, so every "
            "start here is the stored import date. A section that could read the "
            "evidence may resolve an earlier buy-price match for the same "
            "position; the stored dates are still published, so the difference "
            "is visible rather than silent."
        )
    return payload


# --- Performance-history freshness (ticket 02) ------------------------------
# The delivered window is measured against the requested one with a numeric,
# deterministic rule. A 3-calendar-day tolerance absorbs a weekend/holiday
# edge without excusing a materially shorter or staler series, and no gap is
# ever backfilled to make a series look complete.
PERFORMANCE_HISTORY_TOLERANCE_DAYS = 3
#: Below this delivered fraction of the requested business days the series is
#: `partial` even when it is not truncated and not stale.
PERFORMANCE_HISTORY_MIN_COVERAGE_RATIO = 0.50
PERFORMANCE_AS_OF_SEMANTICS = (
    "Last delivered portfolio-value observation date; never the requested "
    "window end, and never backfilled."
)


def _expected_observation_count(requested_start: Any, requested_end: Any) -> Optional[int]:
    """Mon-Fri calendar days in the requested window, or None if unparseable.

    Exchange holidays make a complete series land slightly below this count, so
    the ratio is a coverage floor rather than an exact expectation. Nothing is
    invented when the request is unparseable: the field is `None` and the
    caller reports it.
    """
    if requested_start is None or requested_end is None:
        return None
    try:
        start = pd.Timestamp(requested_start).normalize()
        end = pd.Timestamp(requested_end).normalize()
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(start) or pd.isna(end) or start > end:
        return None
    return int(len(pd.bdate_range(start=start, end=end)))


def _calendar_day_gap(later: Any, earlier: Any) -> Optional[int]:
    """Whole calendar days from `earlier` to `later`, or None if unparseable."""
    if later is None or earlier is None:
        return None
    try:
        a = pd.Timestamp(earlier).normalize()
        b = pd.Timestamp(later).normalize()
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(a) or pd.isna(b):
        return None
    return int((b - a).days)


def _performance_history_envelope(
    series: Any,
    *,
    requested_start: Any,
    requested_end: Any,
    warnings: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Opt-in metadata envelope for one delivered performance-history series.

    Pure and deterministic: the same delivered rows and the same requested
    window always produce the same envelope, with no clock read and no vendor
    call. Freshness rule, all comparisons on calendar days:

    * ``truncated``  - ``delivered_start`` is more than 3 calendar days after
      ``requested_start``;
    * ``stale``      - ``delivered_end`` is at least 3 calendar days before
      ``requested_end``;
    * ``partial``    - the series is non-empty and either flag is set, or fewer
      than 50% of the requested Mon-Fri days were delivered;
    * ``unavailable`` - nothing was delivered, and then ``as_of`` is ``None``.

    ``as_of`` is the last delivered observation or ``None``. The requested end
    is never substituted for it and a missing observation is never backfilled.
    """
    rows = [row for row in (series or []) if isinstance(row, Mapping)]
    # Only a genuinely dated row is an observation. A positional label or an
    # unparseable string is not a date, so it never becomes `as_of`.
    dated: List[Tuple[str, str]] = []
    for row in rows:
        stamp = _observation_date(row.get("date"))
        if stamp is not None:
            dated.append((stamp, str(row.get("date"))))
    has_dates = len(dated) == len(rows)
    delivered_start = dated[0][0] if dated else None
    delivered_end = dated[-1][0] if dated else None
    observation_count = len(rows)
    expected = _expected_observation_count(requested_start, requested_end)
    if expected and observation_count:
        coverage_ratio = round(min(1.0, observation_count / expected), 6)
    else:
        coverage_ratio = None

    truncated = False
    stale = False
    unmeasurable = False
    if delivered_start and delivered_end and has_dates:
        late_start = _calendar_day_gap(delivered_start, requested_start)
        if late_start is None:
            unmeasurable = True
        else:
            truncated = late_start > PERFORMANCE_HISTORY_TOLERANCE_DAYS
        gap_to_end = _calendar_day_gap(requested_end, delivered_end)
        if gap_to_end is None:
            unmeasurable = True
        else:
            stale = gap_to_end >= PERFORMANCE_HISTORY_TOLERANCE_DAYS
    elif observation_count:
        unmeasurable = True

    short = bool(
        coverage_ratio is not None
        and coverage_ratio < PERFORMANCE_HISTORY_MIN_COVERAGE_RATIO
    )
    if not observation_count:
        status = DATA_STATUS_UNAVAILABLE
    elif truncated or stale or short or unmeasurable:
        status = DATA_STATUS_PARTIAL
    else:
        status = DATA_STATUS_AVAILABLE

    history: Dict[str, Any] = {
        "requested_start": requested_start if isinstance(requested_start, str) else None,
        "requested_end": requested_end if isinstance(requested_end, str) else None,
        "requested_days": (
            _calendar_day_gap(requested_end, requested_start)
            if requested_start is not None and requested_end is not None
            else None
        ),
        "delivered_start": delivered_start,
        "delivered_end": delivered_end,
        "observation_count": observation_count,
        "expected_observation_count": expected,
        "first_observation": delivered_start,
        "last_observation": delivered_end,
        "coverage_ratio": coverage_ratio,
        "truncated": truncated,
        "stale": stale,
        "status": status,
    }

    messages: List[str] = [str(item) for item in (warnings or []) if item]
    if not observation_count:
        messages.append("No performance history was delivered for the requested window.")
    else:
        if truncated and delivered_start and isinstance(requested_start, str):
            late = _calendar_day_gap(delivered_start, requested_start)
            messages.append(
                f"Delivered history starts {delivered_start}, {late} calendar days after "
                f"the requested {requested_start}; the requested start was not delivered."
            )
        if stale and delivered_end and isinstance(requested_end, str):
            gap = _calendar_day_gap(requested_end, delivered_end)
            messages.append(
                f"Last delivered observation is {delivered_end}, {gap} calendar days before "
                f"the requested end {requested_end}; the series is stale."
            )
        if short and coverage_ratio is not None and expected:
            messages.append(
                f"Delivered {observation_count} of {expected} expected observations "
                f"({coverage_ratio:.0%} of the requested window)."
            )
        if unmeasurable:
            messages.append(
                "Delivered observation dates are not ISO dates; freshness could not be measured."
            )

    return {
        "data": rows,
        "data_status": status,
        "as_of": delivered_end,
        "as_of_semantics": PERFORMANCE_AS_OF_SEMANTICS,
        "history_coverage": history,
        "warnings": messages,
    }


# --- Liquidity units, window and scoring disclosure (V3-09) ------------------
# The liquidity score is a dimensionless 0-10 index whose INPUTS are monetary,
# and the engine's tiers are fixed INR magnitudes. So the unit the score is
# expressed in is a property of the rule, not of a quote, and it is published as
# `derived` - never read off a market-cap payload and never invented per ticker.
LIQUIDITY_SCORING_CURRENCY = "INR"
LIQUIDITY_SCORE_PRECISION = 1
LIQUIDITY_SCORE_SCALE = {"min": 2.5, "max": 10.0, "unit": "index_0_to_10"}


def _liquidity_observation_window(frames: Mapping[str, Any]) -> Dict[str, Any]:
    """Delivered liquidity range measured from the fetched frames themselves.

    `data_range` is the request; this is what arrived. Nothing is substituted:
    an undated frame contributes no bound, and the union end is the newest bar
    any leg delivered.
    """
    bounds: Dict[str, Tuple[Optional[str], Optional[str]]] = {}
    for ticker, frame in (frames or {}).items():
        if not isinstance(frame, (pd.DataFrame, pd.Series)) or len(frame) == 0:
            continue
        first, last = _observation_bounds(frame)
        bounds[str(ticker)] = (first, last)
    starts = [first for first, _ in bounds.values() if first]
    ends = [last for _, last in bounds.values() if last]
    return {
        "start": min(starts) if starts else None,
        "end": max(ends) if ends else None,
        "ticker_count": len(bounds),
        "per_ticker": {
            ticker: {"start": first, "end": last, "observations": int(len(frames[ticker]))}
            for ticker, (first, last) in sorted(bounds.items())
        },
    }


def _liquidity_scoring_block(
    liquidity_result: Mapping[str, Any],
    *,
    data_range: Mapping[str, Any],
    observation_window: Mapping[str, Any],
) -> Dict[str, Any]:
    """How the score, the band and the inputs were produced.

    Republishes the engine's own band rule so a consumer can check the published
    score against the threshold that banded it, and names the window the
    turnover/price inputs were measured over. A result the engine refused
    publishes `None` scores and a null rule rather than a plausible default.
    """
    rule = liquidity_result.get("score_band_rule")
    positions = liquidity_result.get("by_position")
    positions = positions if isinstance(positions, Mapping) else {}
    return {
        "scale": dict(LIQUIDITY_SCORE_SCALE),
        "score_precision": LIQUIDITY_SCORE_PRECISION,
        "raw_score_field": "score_raw",
        "published_score_field": "score",
        "band_source": (rule or {}).get("band_source") if isinstance(rule, Mapping) else None,
        "bands": (rule or {}).get("bands") if isinstance(rule, Mapping) else None,
        "thresholds": (rule or {}).get("bands") if isinstance(rule, Mapping) else None,
        "currency": LIQUIDITY_SCORING_CURRENCY,
        "currency_provenance": "derived",
        "monetary_unit": "rupees",
        "volume_unit": "shares",
        "turnover_unit": "rupees_per_session",
        "market_cap_floor": {
            "value": 1_000_000_000.0,
            "currency": LIQUIDITY_SCORING_CURRENCY,
            "provenance": "fallback",
            "note": (
                "Applied only when a quote cap and the annualised-turnover "
                "estimate are both unavailable; positions using it publish "
                "market_cap_provenance='fallback' and is_estimate=true."
            ),
        },
        "requested_window": dict(data_range),
        "observation_window": dict(observation_window),
        "measured_positions": sorted(positions),
        "unavailable_reason": (
            liquidity_result.get("error")
            if liquidity_result.get("overall_score") is None
            else None
        ),
        "score_basis": "turnover_and_market_cap_tiers",
    }


def _sizing_basis_block(
    engine_result: Mapping[str, Any],
    *,
    base_currency: str,
    portfolio_value: Optional[float],
) -> Dict[str, Any]:
    """One block for the price and currency the share deltas came from.

    Notionals are struck in the base currency and share deltas are whole shares,
    so the price that converts one into the other has to be the same
    base-currency price the budget was struck in. A basis the engine could not
    measure stays `unavailable` with an empty price map and a reason: the
    retired 100.0 placeholder is precisely the fabricated price this replaces.
    """
    prices = engine_result.get("sizing_price")
    prices = dict(prices) if isinstance(prices, Mapping) else {}
    as_of = engine_result.get("sizing_price_as_of")
    currency = engine_result.get("sizing_price_currency")
    currency = (
        str(currency).strip().upper()
        if isinstance(currency, str) and currency.strip()
        else base_currency
    )
    currency_provenance = engine_result.get("price_currency_provenance")
    if not isinstance(currency_provenance, str) or not currency_provenance.strip():
        currency_provenance = "measured" if currency else "unavailable"
    price_provenance = engine_result.get("sizing_price_provenance")
    if not isinstance(price_provenance, str) or not price_provenance.strip():
        price_provenance = "unavailable"
    reason = engine_result.get("sizing_price_unavailable_reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = None if price_provenance == "measured" else "no_aligned_price_snapshot"
    return {
        "sizing_price": prices,
        "sizing_price_as_of": as_of if isinstance(as_of, str) and as_of.strip() else None,
        "sizing_price_currency": currency,
        "price_currency": currency,
        "price_currency_provenance": currency_provenance,
        "sizing_price_provenance": price_provenance,
        "sizing_price_unavailable_reason": reason,
        "missing_tickers": list(engine_result.get("sizing_price_missing_tickers") or []),
        "unpriced_tickers": list(engine_result.get("sizing_price_unpriced_tickers") or []),
        "portfolio_value": float(portfolio_value) if portfolio_value is not None else None,
        "portfolio_value_currency": base_currency,
    }


def _exposure_projection(
    execution: Mapping[str, Any], result: Mapping[str, Any]
) -> Dict[str, Any]:
    """Flat exposure read-out projected from the shared `execution` block.

    One measurement, two shapes: `exposure` republishes what `execution` and
    the engine's scale factor already measured so a flat consumer does not have
    to walk a nested block. It never recomputes gross exposure or financing.
    """
    gross = execution.get("gross_exposure")
    try:
        gross_value = float(gross) if gross is not None else None
    except (TypeError, ValueError):
        gross_value = None
    return {
        "normalization_rule": execution.get("normalization_rule") or WEIGHT_NORMALIZATION_RULE,
        "gross_exposure": gross,
        "net_cash_weight": execution.get("net_cash_weight"),
        "cash_weight": result.get("cash_weight"),
        "scale_factor": result.get("scale_factor"),
        "financing_required": bool(execution.get("financing_required")),
        "financing_fraction": (
            round(gross_value - 1.0, 6)
            if gross_value is not None and gross_value > 1.0
            else 0.0
        ),
        "financing_requirement": execution.get("financing_requirement"),
        "financing_requirement_currency": execution.get("financing_requirement_currency"),
        "execution_eligible": bool(execution.get("execution_eligible")),
        "block_reason": execution.get("block_reason"),
    }


# The rebalance workflow publishes this exact block for a submitted target; the
# optimizer publishes the same shape for the weights its solver produced, so one
# rule string describes both. Solver weights are published rounded to six
# decimals, so a long-only vector that sums to 1.0 can sit up to n / 2e6 above
# it (2.5e-5 for a 50-leg book); the shared rule's default 1e-6 tolerance would
# read that rounding as financing and refuse a legitimately funded target. The
# optimizer validates a solver output, not a user submission, so it validates at
# the precision it publishes, and 1e-4 still sits far below any real leverage.
_SOLVER_GROSS_TOLERANCE = 1e-4


def _weight_normalization_block(
    weights: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Validate a target through the shared rule and report it like rebalance.

    The validated `weights` are not substituted into the response: this is a
    disclosure of what the shared rule measured about the published target, not
    a silent rewrite of a solver answer.
    """
    normalization = normalize_rebalance_weights(weights, tolerance=_SOLVER_GROSS_TOLERANCE)
    block = {
        "normalization_rule": WEIGHT_NORMALIZATION_RULE,
        "normalization_mode": normalization["normalization_mode"],
        "weights_normalized": normalization["weights_normalized"],
        "submitted_gross_exposure": normalization["submitted_gross_exposure"],
        "gross_exposure": normalization["gross_exposure"],
        "execution_eligible": normalization["execution_eligible"],
        "financing_required": normalization["financing_required"],
        "net_cash_weight": round(1.0 - normalization["gross_exposure"], 6),
    }
    if normalization["rejection"] is not None:
        # Never silent: a target the rebalance workflow would refuse is named
        # here too, whatever the solver believed.
        block["rejection"] = normalization["rejection"]
    return block


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


def _fx_rates_by_ticker(
    positions: Iterable[Any],
    *,
    base_currency: str,
    provenance: Any,
) -> Dict[str, Optional[float]]:
    """Native-to-base rate per ticker from the FX snapshot already verified.

    The rates are the ones `_convert_analytics_positions` used to value the
    book, so a second refresh cannot split the valuation budget from the prices
    derived from it. A leg with no verified rate is reported as `None` instead
    of falling back to 1.0, which would price a foreign book as if it were
    already in the base currency.
    """
    pairs = provenance.get("pairs") if isinstance(provenance, Mapping) else None
    rates: Dict[str, Optional[float]] = {}
    for position in positions:
        ticker = str(getattr(position, "ticker", "") or "")
        if not ticker:
            continue
        source = _analytics_position_currency(position)
        if source == base_currency:
            rates[ticker] = 1.0
            continue
        pair = pairs.get(f"{source}->{base_currency}") if isinstance(pairs, Mapping) else None
        rate: Optional[float] = None
        if isinstance(pair, Mapping):
            try:
                candidate = float(pair.get("rate"))
            except (TypeError, ValueError):
                candidate = None
            if candidate is not None and math.isfinite(candidate) and candidate > 0:
                rate = candidate
        rates[ticker] = rate
    return rates


def _base_currency_price_series(
    price_data_dict: Mapping[str, pd.Series],
    rates: Mapping[str, Optional[float]],
) -> Dict[str, pd.Series]:
    """Re-express delivered price series in the base currency.

    Scaling a whole series by one constant leaves its returns - and therefore
    every volatility the sizing engine measures - unchanged, while making the
    exported `sizing_price` the same unit as the notional it is divided into.
    A leg with no verified rate has no truthful base-currency price, so it is
    left out of the sizing universe instead of being priced as INR.
    """
    converted: Dict[str, pd.Series] = {}
    for ticker, series in (price_data_dict or {}).items():
        rate = rates.get(ticker)
        if rate is None:
            continue
        try:
            factor = float(rate)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(factor) or factor <= 0:
            continue
        converted[ticker] = series if factor == 1.0 else series * factor
    return converted


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
        masked_dict, effectives, start_detail = holding_window_detail(price_data_dict, holdings)
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
        # Each ticker's OWN return observations, measured from its own masked
        # series. Seeding them before `holding_coverage` is what lets the
        # per-position `limited_history` flag derive from the position itself
        # instead of from a portfolio or global count.
        own_return_observations = _own_return_observations(price_data)
        per_ticker = {
            t: {
                "raw_days": int(len(s)) if s is not None else 0,
                "masked_days": int(len(masked_dict[t])) if t in masked_dict and masked_dict[t] is not None else 0,
                "limited_history": bool(getattr(s, "attrs", {}).get("limited_history", False)),
                "coverage_reason": getattr(s, "attrs", {}).get("coverage_reason"),
            }
            for t, s in price_data_dict.items()
        }
        for ticker, count in own_return_observations.items():
            per_ticker.setdefault(ticker, {})["return_observations"] = int(count)
        history_coverage = holding_coverage(
            effectives, start, end, covered_days, per_ticker, provenance=start_detail
        )

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
        for ticker, pos_metrics in metrics.get("positions", {}).items():
            engine_limited = bool(pos_metrics.get("is_limited_history", False))
            data_pts = pos_metrics.get("data_points", 0)
            own_observations = own_return_observations.get(ticker)
            # The gate reads this position's own sample; the engine's flag is
            # only the feed's own declaration.
            is_limited = position_limited_history(own_observations, engine_limited)
            provenance = _position_provenance(start_detail, ticker)
            if is_limited:
                raw_s = price_data_dict.get(ticker)
                raw_len = int(len(raw_s)) if raw_s is not None else 0
                attrs = getattr(raw_s, "attrs", {})
                notice = position_history_note(
                    ticker,
                    return_observations=own_observations,
                    analytics_start=provenance["analytics_start"],
                    analytics_start_source=provenance["analytics_start_source"],
                    stored_added_on=provenance["stored_added_on"],
                    buy_price_inferred=provenance["buy_price_inferred"],
                    coverage_reason=attrs.get("coverage_reason"),
                    full_history_days=full_days,
                    declared_limited=True if attrs.get("limited_history") else None,
                )
                # Every count in a per-ticker line is that ticker's own.
                if raw_len and raw_len < MIN_ANNUALIZE_DAYS:
                    notice += (
                        f" Only {raw_len} trading days of data are available on "
                        "exchange feeds; historical risk ratios are constrained."
                    )
                elif own_observations is not None:
                    notice += (
                        f" Its {int(own_observations)} own return observations are fewer "
                        f"than the {MIN_ANNUALIZE_DAYS} required to annualize, so its "
                        "annualized ratios are withheld."
                    )
                warnings_list.append({
                    "ticker": ticker,
                    "data_points": data_pts,
                    "return_observations": own_observations,
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
                "return_observations": own_observations,
                "is_limited_history": is_limited,
                "history_warning": pos_metrics.get("history_warning"),
                **provenance,
            }

        # Short holding history must not annualize into triple-digit artefacts.
        apply_annualization_gate(
            portfolio_metrics,
            ["annual_return", "annual_volatility", "sharpe_ratio", "sortino_ratio"],
            covered_days,
        )
        for ticker, pos_payload in positions.items():
            apply_annualization_gate(
                pos_payload,
                ["annual_return", "annual_volatility", "sharpe_ratio"],
                pos_payload.get("return_observations")
                if pos_payload.get("return_observations") is not None
                else int(pos_payload.get("data_points", 0) or 0),
            )
        for ticker in wiped:
            provenance = _position_provenance(start_detail, ticker)
            warnings_list.append({
                "ticker": ticker,
                "data_points": 0,
                "return_observations": 0,
                "message": (
                    f"{ticker}: no price data within the current holding period "
                    f"— {analytics_start_claim(
                        provenance['analytics_start'],
                        provenance['analytics_start_source'],
                        provenance['stored_added_on'],
                    )}; excluded from realized metrics."
                ),
            })

        usable_tickers = [
            ticker
            for ticker, position in positions.items()
            if int(position.get("data_points", 0) or 0) >= 2
        ]
        coverage = _universe_coverage(
            ticker_list, usable_tickers, active=calculation_tickers
        )
        limited_history = any(
            bool(position.get("is_limited_history"))
            for position in positions.values()
            if isinstance(position, Mapping)
        )
        data_status = _data_status(coverage, partial=limited_history)
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
                    "confidence_interval": None,
                    "observations": 0,
                    "annualized": False,
                    "minimum_observations_required": MIN_ANNUALIZE_DAYS,
                },
                "positions": {},
                "portfolio_observations": 0,
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
                    "confidence_interval": None,
                    "observations": 0,
                    "annualized": False,
                    "minimum_observations_required": MIN_ANNUALIZE_DAYS,
                },
                "positions": {},
                "portfolio_observations": 0,
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
                    "confidence_interval": None,
                    "observations": 0,
                    "annualized": False,
                    "minimum_observations_required": MIN_ANNUALIZE_DAYS,
                },
                "positions": {},
                "portfolio_observations": 0,
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
        
        # Position-level forecasts using active price history.  The gate reads
        # the position's OWN measured return observations: 30 price rows are 29
        # returns, and a model fitted to 29 observations is the same thin
        # sample the annualization gate exists to refuse.
        positions = {}
        warnings_list = []
        own_return_observations = _own_return_observations(price_data)
        for ticker in price_data.columns:
            try:
                raw_s = price_data[ticker].replace([np.inf, -np.inf], np.nan)
                data_pts = int(raw_s.notna().sum())
                own_observations = own_return_observations.get(ticker)
                is_limited = position_limited_history(own_observations, False)
                if not is_limited:
                    # Keep the original union index so an interior gap does
                    # not become a synthetic multi-day return.
                    ticker_rets = raw_s.pct_change(fill_method=None).dropna()
                    ticker_forecast = await analytics_engine.forecast_volatility(ticker_rets, model, horizon)
                    vol_fc = ticker_forecast.get("volatility_forecast")
                    var_fc = ticker_forecast.get("var_forecast")
                    warning = None
                else:
                    ticker_rets = raw_s.pct_change(fill_method=None).dropna()
                    h_factor = np.sqrt(max(1, horizon) / 252.0)
                    vol_fc = float(ticker_rets.std() * np.sqrt(252)) if len(ticker_rets) > 1 else None
                    var_fc = float(-vol_fc * 1.645 * h_factor) if vol_fc is not None else None
                    warning = (
                        f"Only {own_observations} own return observations available "
                        f"from {data_pts} exchange-feed price rows"
                    )
                    warnings_list.append({
                        "ticker": ticker,
                        "data_points": data_pts,
                        "return_observations": own_observations,
                        "message": (
                            f"{ticker} has {own_observations} own return observations "
                            f"from {data_pts} exchange-feed price rows. Forecast "
                            "volatility uses sample volatility."
                        )
                    })
                
                positions[ticker] = {
                    "volatility_forecast": vol_fc,
                    "var_forecast": var_fc,
                    "is_limited_history": is_limited,
                    "history_warning": warning,
                    "data_points": data_pts,
                    "return_observations": own_observations,
                }
            except Exception:
                logger.error("Volatility forecast leg failed")
                positions[ticker] = {
                    "volatility_forecast": None,
                    "var_forecast": None,
                    "is_limited_history": True,
                    "history_warning": "Forecast unavailable",
                    "data_points": 0,
                    "return_observations": own_return_observations.get(ticker),
                }
        
        usable_positions = [
            ticker for ticker, position in positions.items()
            if int(position.get("data_points", 0) or 0) >= 2
            and (
                position.get("volatility_forecast") is not None
                or position.get("var_forecast") is not None
            )
        ]
        coverage = _universe_coverage(
            ticker_list, usable_positions, active=calculation_tickers
        )
        limited_history = any(
            bool(position.get("is_limited_history"))
            for position in positions.values()
            if isinstance(position, Mapping)
        )
        portfolio_forecast_usable = any(
            forecast_result.get(field) is not None
            for field in ("volatility_forecast", "var_forecast", "cvar_forecast")
        )
        # The portfolio forecast is fitted to the aggregated portfolio return
        # series, so its sample is that series' length - never a position count
        # and never the number of tickers that happened to clear a per-leg gate.
        portfolio_observations = int(portfolio_returns.notna().sum())
        response = {
            "model": model,
            "horizon": horizon,
            "portfolio": {
                "volatility_forecast": forecast_result.get("volatility_forecast"),
                "var_forecast": forecast_result.get("var_forecast"),
                "cvar_forecast": forecast_result.get("cvar_forecast"),
                "confidence_interval": forecast_result.get("confidence_interval"),
                "term_structure": forecast_result.get("term_structure", []),
                "observations": portfolio_observations,
                "annualized": annualizable(portfolio_observations),
                "minimum_observations_required": MIN_ANNUALIZE_DAYS,
            },
            "positions": positions,
            "portfolio_observations": portfolio_observations,
            "universe_coverage": coverage,
            "data_status": _data_status(
                coverage,
                partial=limited_history
                or bool(forecast_result.get("error"))
                or not portfolio_forecast_usable,
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
        # The mask is measured only to describe the holding tenure; the model
        # below still runs on the unmasked frame.
        holding_dict, effectives, start_detail = holding_window_detail(price_data_dict, holdings)
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
        holding_frame = pd.DataFrame(holding_dict)
        holding_days = int(len(holding_frame)) if not holding_frame.empty else 0
        own_return_observations = _own_return_observations(price_data)
        per_ticker = {
            ticker: {
                "raw_days": int(len(series)) if series is not None else 0,
                "masked_days": int(len(holding_dict.get(ticker))) if ticker in holding_dict and holding_dict[ticker] is not None else 0,
                "return_observations": int(own_return_observations.get(ticker, 0)),
                "limited_history": bool(getattr(series, "attrs", {}).get("limited_history", False)),
                "coverage_reason": getattr(series, "attrs", {}).get("coverage_reason"),
            }
            for ticker, series in price_data_dict.items()
        }
        holding_context = holding_coverage(
            effectives, start, end, holding_days, per_ticker, provenance=start_detail
        )
        # Model evidence lives in its own object: a full-history regression is
        # not truncated to the holding window, so it publishes its own window,
        # observation count, latest observation and annualization flag. The
        # return frame the regression consumes is the thing described, so the
        # counts are the observations the model used.
        model_returns = price_data.pct_change(fill_method=None).iloc[1:]
        full_history = _full_history_evidence(
            model_returns,
            requested_start=start,
            requested_end=end,
            declared_limited={
                ticker: bool(getattr(series, "attrs", {}).get("limited_history", False))
                for ticker, series in price_data_dict.items()
            },
            coverage_reasons={
                ticker: getattr(series, "attrs", {}).get("coverage_reason")
                for ticker, series in price_data_dict.items()
            },
        )
        history_coverage = _model_history_coverage(holding_context, full_history)

        # Fetch benchmark returns via BenchmarkService (^NSEI)
        benchmark_returns = None
        try:
            benchmark_returns = await benchmark_service.get_returns(start=start, end=end)
        except Exception:
            logger.warning("Benchmark data unavailable")
        history_coverage["calculation_basis"] = FULL_HISTORY_BASIS
        if benchmark_returns is not None:
            benchmark_series = benchmark_returns
            if isinstance(benchmark_series, pd.DataFrame):
                benchmark_series = benchmark_series.iloc[:, 0]
            if isinstance(benchmark_series, pd.Series):
                if benchmark_series.abs().gt(1.0).any():
                    benchmark_series = benchmark_series.pct_change(fill_method=None).dropna()
                history_coverage["benchmark_overlap_observations"] = int(
                    len(model_returns.index.intersection(benchmark_series.index))
                )

        # Perform factor exposure analysis using analytics engine
        factor_result = await analytics_engine.factor_exposure_analysis(
            price_data, 
            benchmark_data=benchmark_returns,
            weights=factor_weights
        )

        # Collect warnings for assets with limited history. `data_points` is the
        # benchmark-overlap sample the regression actually used; the full
        # exchange-history return count is published beside it so a late-listed
        # leg reads as sparse rather than as a short book.
        warnings_list = [
            {
                "ticker": t,
                "data_points": p.get("data_points", 0),
                "return_observations": own_return_observations.get(t),
                "usable_observations": p.get("data_points", 0),
                "limited_history": position_limited_history(
                    own_return_observations.get(t), bool(p.get("is_limited_history"))
                ),
                "message": (
                    f"{t} has {own_return_observations.get(t)} own return observations "
                    f"over the full exchange window, of which {p.get('data_points', 0)} "
                    "overlap the benchmark. Factor regression beta and alpha may be "
                    "constrained."
                ),
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
        coverage = _universe_coverage(
            ticker_list, usable_positions.keys(), active=calculation_tickers
        )
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
        data_status = _data_status(
            coverage,
            partial=limited_history
            or not portfolio_factor_usable
            or bool(factor_result.get("error")),
        )
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
            "model_window": full_history.get("window"),
            "full_history": full_history,
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
                # No book means no weight mass and no rounding to disclose.
                "by_sector_total": 0.0,
                "by_sector_published_total": 0.0,
                "by_sector_rounding_residual": None,
                "by_sector_rounding_decimals": 4,
                "sector_weight_basis": None,
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
        sector_totals: Dict[str, float] = {}
        for pos in positions:
            w = weights.get(pos.ticker, 0.0)
            if w <= 0:
                continue
            sector = pos.sector or "Unknown"
            sector_totals[sector] = sector_totals.get(sector, 0.0) + w

        # Round ONCE, at the end.  Rounding a running partial sum per position
        # let each of N positions add up to 5e-5 of error, so a sector published
        # 0.0984 where the exact weight is 0.0983 and the displayed map summed
        # to 1.0001. Ordering is by weight descending (ties by name) so a
        # repeated export is byte-identical; nothing is renormalized, and the
        # display-only rounding residual is published instead of being folded
        # back into the largest sector.
        by_sector = {
            sector: round(weight, 4)
            for sector, weight in sorted(
                sector_totals.items(), key=lambda item: (-item[1], item[0])
            )
        }
        sector_weight_total = float(sum(sector_totals.values()))
        sector_published_total = float(sum(by_sector.values()))
        sector_rounding_residual = round(1.0 - sector_published_total, 12)
        coverage = _universe_coverage(
            requested_tickers,
            concentration_result.get("by_weight", {}).keys(),
            active=_active_weight_tickers(weights),
        )
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
            "by_sector_total": round(sector_weight_total, 12),
            "by_sector_published_total": round(sector_published_total, 12),
            "by_sector_rounding_residual": sector_rounding_residual,
            "by_sector_rounding_decimals": 4,
            "sector_weight_basis": (
                "market_value_weights_normalized_to_100_percent"
            ),
            "universe_coverage": coverage,
            "data_status": _data_status(coverage),
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
                "overall_score_raw": None,
                "overall_band": None,
                "liquidation_time_days": None,
                "risk_level": None,
                "by_position": {},
                "volume_stats": {},
                "currency": LIQUIDITY_SCORING_CURRENCY,
                "base_currency": LIQUIDITY_SCORING_CURRENCY,
                "currency_provenance": "derived",
                "monetary_unit": "rupees",
                "volume_unit": "shares",
                "turnover_unit": "rupees_per_session",
                "latest_observation_date": None,
                "observation_window": {"start": None, "end": None, "ticker_count": 0, "per_ticker": {}},
                "error": "No portfolio positions found",
                "data_status": "unavailable",
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "zero_metrics": True
            }
        if not await _has_positive_portfolio_value(db):
            return {
                "overall_score": None,
                "overall_score_raw": None,
                "overall_band": None,
                "liquidation_time_days": None,
                "risk_level": None,
                "by_position": {},
                "volume_stats": {},
                "currency": LIQUIDITY_SCORING_CURRENCY,
                "base_currency": LIQUIDITY_SCORING_CURRENCY,
                "currency_provenance": "derived",
                "monetary_unit": "rupees",
                "volume_unit": "shares",
                "turnover_unit": "rupees_per_session",
                "latest_observation_date": None,
                "observation_window": {"start": None, "end": None, "ticker_count": 0, "per_ticker": {}},
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
                    frame = df[[price_col, vol_col]].rename(columns={vol_col: 'Volume', price_col: 'Close'})
                elif price_col in df.columns:
                    frame = df[[price_col]].rename(columns={price_col: 'Close'})
                else:
                    frame = None
                if frame is not None:
                    # A fresh yfinance fetch carries `date` as a COLUMN over an
                    # integer row index, so slicing the frame keeps a RangeIndex
                    # and every delivered-window date comes out null. Promote the
                    # real date column to the index so the liquidity engine still
                    # sees the Close/Volume frame it expects, while the reported
                    # observation window describes actual observations rather than
                    # row numbers. Never synthesise dates from a positional index.
                    date_col = next((c for c in ("date", "Date") if c in frame.columns), None)
                    if date_col is not None:
                        dated = pd.to_datetime(frame[date_col], errors="coerce")
                        frame = frame.drop(columns=[date_col])
                        keep = ~dated.isna()
                        frame = frame[keep.to_numpy()]
                        frame.index = pd.DatetimeIndex(dated[keep.to_numpy()], name=frame.index.name)
                    price_data_dict[ticker] = frame
        
        if not price_data_dict:
            return {
                "overall_score": None,
                "overall_score_raw": None,
                "overall_band": None,
                "liquidation_time_days": None,
                "risk_level": None,
                "by_position": {},
                "volume_stats": {},
                "currency": LIQUIDITY_SCORING_CURRENCY,
                "base_currency": LIQUIDITY_SCORING_CURRENCY,
                "currency_provenance": "derived",
                "monetary_unit": "rupees",
                "volume_unit": "shares",
                "turnover_unit": "rupees_per_session",
                "data_range": {"start": start, "end": end},
                "observation_window": {"start": None, "end": None, "ticker_count": 0, "per_ticker": {}},
                "latest_observation_date": None,
                "error": "No price data available for liquidity analysis",
                "data_status": "unavailable",
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "zero_metrics": True
            }
        
        # Calculate liquidity metrics using analytics engine
        liquidity_result = await analytics_engine.liquidity_analysis(price_data_dict, market_caps=market_caps_dict)
        coverage = _universe_coverage(
            requested_tickers,
            liquidity_result.get("by_position", {}).keys(),
            active=tickers,
        )
        # The delivered range is measured from the frames that were actually
        # handed to the engine, not from the requested window: a 30-day request
        # whose newest bar is three days old must publish that gap rather than
        # the request end as its freshness.
        delivered = _liquidity_observation_window(price_data_dict)
        latest_observation_date = _latest_observation_date(price_data_dict)

        return {
            "overall_score": liquidity_result.get("overall_score"),
            "overall_score_raw": liquidity_result.get("overall_score_raw"),
            "overall_band": liquidity_result.get("overall_band"),
            "liquidation_time_days": liquidity_result.get("liquidation_time_days"),
            "risk_level": liquidity_result.get("risk_level"),
            "by_position": liquidity_result.get("by_position", {}),
            "volume_stats": liquidity_result.get("volume_stats", {}),
            "currency": LIQUIDITY_SCORING_CURRENCY,
            "base_currency": LIQUIDITY_SCORING_CURRENCY,
            "currency_provenance": "derived",
            "currency_basis": (
                "The liquidity score is computed against fixed INR-denominated "
                "thresholds (turnover tiers in Cr/day, market-cap tiers in Cr, "
                "INR 1bn floor), so INR is the unit the score is expressed in; "
                "it is not read from a quote."
            ),
            "monetary_unit": "rupees",
            "volume_unit": "shares",
            "turnover_unit": "rupees_per_session",
            "data_range": {"start": start, "end": end},
            "observation_window": delivered,
            "requested_days": int(
                _calendar_day_gap(end, start) or 0
            ),
            "latest_observation_date": latest_observation_date,
            "scoring": _liquidity_scoring_block(
                liquidity_result,
                data_range={"start": start, "end": end},
                observation_window=delivered,
            ),
            "universe_coverage": coverage,
            "data_status": _data_status(coverage),
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
        stress_result["universe_coverage"] = _universe_coverage(
            ticker_list, price_data_dict.keys(), active=_active_weight_tickers(weights)
        )
        stress_result["data_status"] = _data_status(stress_result["universe_coverage"])
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

    The response is one executable contract: the weights, the gross exposure
    and financing they require under the shared normalization rule, the
    base-currency price and date every share delta was derived from, and the
    history window that was actually measured. Nothing here is inferred: a
    price, currency, or window the data cannot supply stays `unavailable`.
    """
    try:
        base_currency = "INR"
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
                "currency": base_currency,
                "base_currency": base_currency,
                "execution_normalization_rule": WEIGHT_NORMALIZATION_RULE,
                "latest_observation_date": None,
                "currency_provenance": {
                    "base_currency": base_currency,
                    "aggregation": "empty",
                    "source_currencies": [],
                    "pairs": {},
                },
                "error": "No portfolio positions found for volatility sizing"
            }

        # Use one FX snapshot for both current weights and the base-currency
        # valuation budget.  Re-querying/re-converting could otherwise split the
        # trade sizing basis when live rates move between calls.
        converted_position_values, allocation_provenance = await _convert_analytics_positions(
            positions_list, target_currency=base_currency
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

        # Calculate actual base-currency portfolio value from DB if not
        # explicitly passed.
        if portfolio_value is None:
            resolved_pv = converted_total
            currency_provenance = allocation_provenance
        else:
            resolved_pv = portfolio_value
            currency_provenance = {
                "base_currency": base_currency,
                "aggregation": "explicit_input",
                "source_currencies": [base_currency],
                "pairs": {
                    f"{base_currency}->{base_currency}": {
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
                "currency": base_currency,
                "base_currency": base_currency,
                "execution_normalization_rule": WEIGHT_NORMALIZATION_RULE,
                "latest_observation_date": None,
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
                "currency": base_currency,
                "base_currency": base_currency,
                "execution_normalization_rule": WEIGHT_NORMALIZATION_RULE,
                "latest_observation_date": None,
                "currency_provenance": currency_provenance,
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "data_unavailable_tickers": list(requested_tickers),
                "error": "No price data available for volatility sizing"
            }

        # Every notional below is struck in the base currency, and a share
        # delta is the notional divided by a price, so that price has to be in
        # the base currency too.  Re-expressing the delivered series with the
        # one FX snapshot already used to value the book leaves the measured
        # returns (and therefore every volatility) unchanged while making the
        # exported sizing price the same unit as the amounts it is divided into.
        # A leg with no verified rate has no truthful base-currency price, so it
        # leaves the sizing universe rather than being priced as if it were INR.
        fx_rates = _fx_rates_by_ticker(
            positions_list, base_currency=base_currency, provenance=allocation_provenance
        )
        unconvertible = sorted(
            ticker for ticker in price_data_dict if fx_rates.get(ticker) is None
        )
        if unconvertible:
            logger.warning(
                "Volatility sizing dropped legs with no verified %s rate: %s",
                base_currency,
                ", ".join(unconvertible),
            )
        price_data_dict = _base_currency_price_series(price_data_dict, fx_rates)
        if not price_data_dict:
            return {
                "current_weights": weights,
                "recommended_weights": weights,
                "trades": {ticker: {"shares_delta": 0, "amount": 0} for ticker in weights.keys()},
                "target_volatility": target_volatility,
                "currency": base_currency,
                "base_currency": base_currency,
                "execution_normalization_rule": WEIGHT_NORMALIZATION_RULE,
                "latest_observation_date": None,
                "currency_provenance": currency_provenance,
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "data_unavailable_tickers": list(requested_tickers),
                "error": "No base-currency price data available for volatility sizing",
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
                "currency": base_currency,
                "base_currency": base_currency,
                "execution_normalization_rule": WEIGHT_NORMALIZATION_RULE,
                "latest_observation_date": _latest_observation_date(price_data),
                "history_window": _history_window(start, end, sizing_returns, price_frame=price_data),
                "currency_provenance": currency_provenance,
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "data_unavailable_tickers": list(requested_tickers),
                "error": "No finite return observations for volatility sizing",
            }
        price_data = price_data.loc[:, usable_tickers]
        # Returns measured over the delivered universe only; the history blocks
        # below report from this frame so a dropped leg cannot inflate the
        # evidence for the legs that stayed.
        delivered_returns = sizing_returns.loc[
            :, [ticker for ticker in usable_tickers if ticker in sizing_returns.columns]
        ]
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
        
        # Calculate volatility sizing using analytics engine.  The base
        # currency is passed explicitly because the engine cannot infer it: it
        # is what makes `sizing_price_currency` and its provenance `measured`
        # instead of `unavailable`.
        sizing_result = await analytics_engine.volatility_sizing(
            price_data, 
            sizing_weights,
            model, 
            target_volatility, 
            portfolio_value=resolved_pv,
            price_currency=base_currency,
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
        coverage = _universe_coverage(
            requested_tickers, available_tickers, active=_active_weight_tickers(weights)
        )
        limited_history = any(
            count < MIN_ANNUALIZE_DAYS for count in return_observations.values()
        )
        sizing_status = _data_status(
            coverage,
            partial=limited_history or bool(sizing_result.get("error")),
        )
        response.update({
            "portfolio_value": round(float(resolved_pv), 2),
            "portfolio_value_currency": base_currency,
            "currency": base_currency,
            "base_currency": base_currency,
            "currency_provenance": currency_provenance,
            "universe_coverage": coverage,
            "data_status": sizing_status,
            "data_unavailable_tickers": coverage["missing_tickers"],
        })
        if coverage["missing_tickers"]:
            # A leg without usable returns left the calculation universe, so the
            # surviving active weights were renormalized. Nothing was dropped in
            # the full-universe case, so no allocation basis is claimed.
            response["weight_basis"] = ACTIVE_WEIGHT_BASIS

        # One rule string, cited by the export and the UI without reaching into
        # a nested block, and the same rule the rebalance workflow enforces.
        response["execution_normalization_rule"] = WEIGHT_NORMALIZATION_RULE
        # Freshness is the newest delivered observation, never the requested end.
        response["latest_observation_date"] = _latest_observation_date(price_data)
        response["history_window"] = _history_window(
            start, end, delivered_returns, price_frame=price_data
        )
        # The engine's own measured sample, or the same block rebuilt from the
        # delivered frame when the engine published none: a window is never
        # claimed without the frame that produced it.
        response["sizing_history"] = (
            dict(sizing_result["sizing_history"])
            if isinstance(sizing_result.get("sizing_history"), Mapping)
            else sizing_history_block(delivered_returns, price_frame=price_data, model=model)
        )
        response["sizing_basis"] = _sizing_basis_block(
            sizing_result, base_currency=base_currency, portfolio_value=resolved_pv
        )
        execution = sizing_result.get("execution")
        if not isinstance(execution, Mapping):
            # A degraded engine published no rule block, but the target it did
            # publish still has to be measured against the same rule. With no
            # target at all there is nothing to normalize, and the engine's
            # fail-closed result stands on its own.
            execution = (
                normalization_block(
                    response.get("recommended_weights") or {},
                    portfolio_value=resolved_pv,
                    currency=base_currency,
                    weights_normalized=False,
                )
                if response.get("recommended_weights")
                else None
            )
        if execution is not None:
            execution = dict(execution)
            response["execution"] = execution
            response["exposure"] = _exposure_projection(execution, response)
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
                **RISK_SCORE_CHANGE_UNAVAILABLE,
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
                **RISK_SCORE_CHANGE_UNAVAILABLE,
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
                **RISK_SCORE_CHANGE_UNAVAILABLE,
                "components": {},
                "alerts": ["Insufficient data for comprehensive risk analysis"],
                "universe_coverage": _universe_coverage(requested_tickers, []),
                "data_status": "unavailable",
                "error": "No price data available for risk scoring"
            }
        
        # Combine price data, restricted to actual holding history.
        raw_price_data_dict = dict(price_data_dict)
        holdings = await resolve_holdings(db, calculation_tickers)
        price_data_dict, effectives, start_detail = holding_window_detail(price_data_dict, holdings)
        price_data = pd.DataFrame(price_data_dict)
        if price_data.empty:
            return {
                "overall_score": None,
                "risk_level": None,
                **RISK_SCORE_CHANGE_UNAVAILABLE,
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
                **RISK_SCORE_CHANGE_UNAVAILABLE,
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
            effectives, start, end, int(len(price_data)), per_ticker,
            provenance=start_detail,
        )
        history_coverage["position_observations"] = {
            ticker: {
                **_position_provenance(start_detail, ticker),
                "return_observations": int(count),
                "limited_history": position_limited_history(
                    int(count),
                    bool(per_ticker.get(ticker, {}).get("limited_history", False)),
                ),
            }
            for ticker, count in return_observations.items()
        }

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
        # The score is driven by the aggregated portfolio return series, so its
        # sample is that series' length - published next to the per-position
        # counts so neither can be read as the other.
        portfolio_observations = int(
            aggregate_active_returns(
                risk_returns.loc[:, [t for t in usable_tickers if t in risk_returns.columns]],
                risk_weights,
            ).notna().sum()
        )
        history_coverage["portfolio_return_observations"] = portfolio_observations
        history_coverage["covered_days"] = portfolio_observations
        history_coverage["covered_days_scope"] = "portfolio_return_observations"
        history_coverage["annualized"] = annualizable(portfolio_observations)
        if not isinstance(risk_result, Mapping) or risk_result.get("overall_score") is None:
            return {
                "overall_score": None,
                "risk_level": None,
                **RISK_SCORE_CHANGE_UNAVAILABLE,
                "components": {},
                "alerts": ["Insufficient data for comprehensive risk analysis"],
                "universe_coverage": _universe_coverage(
                    requested_tickers, usable_tickers, active=_active_weight_tickers(weights)
                ),
                "data_status": "partial" if usable_tickers else "unavailable",
                "error": "Risk score unavailable for the measured return sample",
            }
        risk_result["history_coverage"] = history_coverage
        coverage = _universe_coverage(
            requested_tickers, usable_tickers, active=_active_weight_tickers(weights)
        )
        limited_history = any(
            count < MIN_ANNUALIZE_DAYS for count in return_observations.values()
        )
        risk_result["universe_coverage"] = coverage
        risk_result["data_status"] = _data_status(
            coverage,
            partial=limited_history or bool(risk_result.get("error")),
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
        price_data_dict, effectives, start_detail = holding_window_detail(price_data_dict, holdings)
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
        # Measured BEFORE the coverage call so the per-position gate can read
        # each ticker's own return observations; patching them on afterwards
        # (as this route used to) left `limited_history` on the feed's generic
        # declaration instead of the position's own sample.
        return_frame = price_data.pct_change(fill_method=None).iloc[1:]
        return_observations = {
            ticker: int(return_frame[ticker].notna().sum())
            for ticker in requested_tickers
            if ticker in return_frame.columns
        }
        per_ticker = {
            ticker: {
                "raw_days": int(len(unmasked_dict.get(ticker))) if ticker in unmasked_dict and unmasked_dict[ticker] is not None else 0,
                "masked_days": int(len(price_data_dict.get(ticker))) if ticker in price_data_dict and price_data_dict[ticker] is not None else 0,
                "return_observations": int(return_observations.get(ticker, 0)),
                "limited_history": bool(getattr(unmasked_dict.get(ticker), "attrs", {}).get("limited_history", False)),
                "coverage_reason": getattr(unmasked_dict.get(ticker), "attrs", {}).get("coverage_reason"),
            }
            for ticker in requested_tickers
        }
        history_coverage = holding_coverage(
            effectives, start, end, covered_days, per_ticker, provenance=start_detail
        )

        # Calculate portfolio metrics for summary
        metrics = await analytics_engine.calculate_portfolio_metrics(price_data, weights)
        # Report measured return coverage rather than the union length of the
        # price frame; missing/interior bars are not covered observations.
        covered_days = int(metrics.get("active_observations") or metrics.get("observations") or 0)
        history_coverage["covered_days"] = covered_days
        history_coverage["covered_days_scope"] = "portfolio_return_observations"
        history_coverage["portfolio_return_observations"] = covered_days
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
        # `return_observations` was measured before the coverage call above, so
        # the per-ticker gate below and the published per-ticker
        # `limited_history` flags read the same own-sample numbers.
        history_coverage["position_observations"] = {
            ticker: {
                **_position_provenance(start_detail, ticker),
                "return_observations": int(count),
                "limited_history": position_limited_history(
                    int(count),
                    bool(per_ticker.get(ticker, {}).get("limited_history", False)),
                ),
            }
            for ticker, count in return_observations.items()
        }
        available_tickers = [
            ticker for ticker, count in return_observations.items() if count >= 2
        ]
        limited_history = any(
            position_limited_history(count, False)
            for count in return_observations.values()
        )
        coverage = _universe_coverage(
            requested_tickers, available_tickers, active=_active_weight_tickers(weights)
        )
        summary_status = _data_status(
            coverage,
            partial=limited_history
            or bool(risk_result.get("error"))
            or risk_result.get("overall_score") is None,
        )
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
            "portfolio_return_observations": covered_days,
            "instrument_risk": {
                "basis": FULL_HISTORY_BASIS,
                "observations": instrument_volatility_days,
                "window": {
                    "start": _observation_bounds(full_iv_df)[0],
                    "end": _observation_bounds(full_iv_df)[1],
                    "days": instrument_volatility_days,
                },
                "holding_context_note": FULL_HISTORY_RELATION,
            },
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


# `response_model=None` keeps the default response the bare array the existing
# consumers assume, without coercing the opt-in envelope into it.
@router.get("/performance-history", response_model=None)
async def get_performance_history(
    days: int = Query(default=90, ge=7, le=1825, description="Lookback window in days"),
    tickers: Optional[str] = Query(default=None, description="Comma-separated tickers"),
    db: AsyncSession = Depends(get_db_session),
    data_service: DataService = Depends(get_data_service),
    benchmark_service: BenchmarkService = Depends(get_benchmark_service),
    include_metadata: bool = Query(
        default=False,
        description=(
            "Opt-in freshness envelope: return {data, data_status, as_of, "
            "as_of_semantics, history_coverage, warnings} instead of the bare "
            "array. The default response is unchanged."
        ),
    ),
) -> Any:
    """
    Historical portfolio value series (price x quantity) over time from cached OHLCV.

    Returns a bare `List[Dict]` by default - the shape every existing consumer
    (frontend hook, chart, backend tests) assumes. `include_metadata=true` opts
    into an envelope that adds the delivered window, the observation count, the
    last delivered observation and a documented freshness verdict; see
    `_performance_history_envelope` for the exact numeric rule. The request is
    never substituted for the delivery: `as_of` is the last delivered
    observation, and no gap is backfilled.
    """
    try:
        # A direct in-process call (backend unit tests) hands this function the
        # FastAPI `Query` placeholder rather than a bool, and that placeholder is
        # truthy. Only an explicit boolean opts in, so the default response stays
        # the bare array for every caller that does not ask for the envelope.
        if not isinstance(include_metadata, bool):
            include_metadata = False

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

        end = datetime.now().strftime('%Y-%m-%d')
        start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        def _deliver(rows: List[Dict[str, Any]], extra: Optional[Iterable[str]] = None) -> Any:
            if not include_metadata:
                return rows
            return _performance_history_envelope(
                rows, requested_start=start, requested_end=end, warnings=extra
            )

        if not ticker_list:
            return _deliver(
                [], extra=["No positions resolved for the requested tickers."]
            )

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
            return _deliver(
                [], extra=["No position carried a usable share quantity."]
            )

        # Fetch price data concurrently
        price_data_dict = await _fetch_price_series_dict(data_service, list(quantities), start, end)

        if not price_data_dict:
            return _deliver([], extra=["No price data was delivered for the requested window."])

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
            return _deliver(
                [], extra=["No price data falls inside the current holding window."]
            )
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
            return _deliver(
                [], extra=["No date had a usable price for every priced position."]
            )

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

        return _deliver(output)

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
        # The holding leg is masked to the canonical window start (one rule for
        # every section), not to whatever the 365-day request implies, and the
        # start it used is published with its provenance.
        provenance = await holding_provenance(
            data_service, holdings, _active_weight_tickers(weights), end=end,
        )
        returns_df, port_ret, leg_coverage = await _build_wide_returns(
            ticker_list, weights, start, end, data_service,
            holdings=canonical_holding_window_input(provenance["detail"]),
        )
        covered_days, mask = holding_window_observation_count(
            port_ret,
            provenance["start"],
            measured_count=leg_coverage.get("covered_days"),
            measured_start=leg_coverage.get("intersection_start"),
        )
        if mask is not None and leg_coverage.get("intersection_start") != provenance["start"]:
            port_ret = port_ret[mask]
        history_coverage = publish_holding_coverage(
            detail=provenance["detail"],
            per_ticker=_coverage_per_ticker(leg_coverage),
            requested_start=start,
            requested_end=end,
            covered_days=covered_days,
            evidence_window=provenance["evidence_window"],
        )
        history_coverage["model_used_tickers"] = list(
            leg_coverage.get("model_used_tickers") or []
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
        # Same evidence shape Factor Exposure and Risk Contribution publish: the
        # full-history leg carries its own window, observation count, scope and
        # truncation flag, so it can never be read as the holding window and
        # the holding window can never be read as this model's sample.
        full_history_evidence = _full_history_evidence(
            full_returns_df, requested_start=start, requested_end=end,
        )

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

        active_tickers = _active_weight_tickers(weights)
        coverage = _universe_coverage(ticker_list, returns_df.columns, active=active_tickers)
        full_coverage = _universe_coverage(
            ticker_list, full_returns_df.columns, active=active_tickers
        )
        tear_sheet_status = _data_status(
            coverage, partial=len(port_ret) < MIN_ANNUALIZE_DAYS
        )
        # `window` is the REQUEST. The metrics beside it are measured over the
        # holding window, so the request is labelled as such and the measured
        # window and its observation count are published next to it: a 365-day
        # request must never sit on 39 days of numbers unlabelled.
        measured_first, measured_last = _observation_bounds(port_ret)
        measured_window = {
            "start": measured_first,
            "end": measured_last or _latest_observation_date(port_ret),
            "days": int(covered_days),
            "observation_count": int(covered_days),
            "covered_days_scope": HOLDING_COVERED_DAYS_SCOPE,
            "truncated_to_holding_window": bool(history_coverage.get("truncated")),
            "holding_window_start": history_coverage.get("intersection_start"),
        }
        return {
            "window": {
                "start": start,
                "end": end,
                "kind": "requested_analytics_window",
            },
            "requested_window": {"start": start, "end": end},
            "measured_window": measured_window,
            "observation_count": int(covered_days),
            "annualized": annualizable(covered_days),
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
                **full_history_evidence,
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
        # portfolio vol. Holding-period truncation stays disclosed, but only as
        # clearly ancillary context: the model evidence carries its own window,
        # observation count and annualization flag.
        returns_df, port_ret, _ = await _build_wide_returns(
            ticker_list, weights, start, end, data_service,
        )
        # The holding window is the SAME question every section answers, so it
        # is resolved by the same rule rather than from the stored import dates
        # alone - the buy-price inference needs price evidence, and answering
        # with stored stamps instead is what moved this section's window start a
        # day away from every other section. The read is issued after the leg
        # above and asks for a strict sub-window of it, so the cache-first
        # DataService serves it from what that leg just loaded: no extra vendor
        # request, and no inferred date is ever dropped for want of a frame.
        provenance = await holding_provenance(
            data_service, holdings, _active_weight_tickers(weights), end=end,
        )
        start_detail = provenance["detail"]
        own_return_observations = _own_return_observations(returns_df)
        # The holding-context window is measured on the delivered portfolio
        # return series against the canonical intersection start, so
        # `covered_days` there describes the holding tenure (return
        # observations two held prices can produce) instead of repeating the
        # model's own observation count or the route's own date.
        holding_days, holding_mask = holding_window_observation_count(
            port_ret, provenance["start"],
        )
        holding_context = publish_holding_coverage(
            detail=start_detail,
            per_ticker={
                ticker: {
                    "raw_days": int(returns_df[ticker].notna().sum()),
                    "masked_days": int(returns_df[ticker][holding_mask].notna().sum())
                    if holding_mask is not None else int(returns_df[ticker].notna().sum()),
                    "return_observations": int(count),
                }
                for ticker, count in own_return_observations.items()
            },
            requested_start=start,
            requested_end=end,
            covered_days=holding_days,
            evidence_window=provenance["evidence_window"],
        )
        full_history = _full_history_evidence(
            returns_df,
            requested_start=start,
            requested_end=end,
        )
        # `covered_days` used to be the model's own 252 observations published
        # under holding names, so a 39-day holding window read as a 252-day
        # holding coverage. The two windows are now separate objects.
        history_coverage = _model_history_coverage(holding_context, full_history)
        history_coverage["calculation_observations"] = int(len(port_ret))
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

        coverage = _universe_coverage(
            ticker_list, assets, active=_active_weight_tickers(weights)
        )
        excluded_union = sorted(set(volatility_excluded_assets) | set(cvar_excluded_assets))
        if excluded_union:
            excluded_set = set(excluded_union)
            effective_available = [
                ticker for ticker in coverage["available_tickers"]
                if ticker not in excluded_set
            ]
            coverage["raw_available_tickers"] = coverage["available_tickers"]
            coverage["available_tickers"] = effective_available
            effective_available_set = set(effective_available)
            # Requested order stays authoritative so a repeated universe exports
            # identically; a leg with no return history is never re-counted as
            # covered just because it was excluded from one model.
            coverage["covered_tickers"] = [
                ticker for ticker in coverage["requested_tickers"]
                if ticker in effective_available_set
            ]
            coverage["missing_tickers"] = [
                ticker for ticker in coverage["requested_tickers"]
                if ticker not in effective_available_set
            ] + sorted(excluded_set - set(coverage["requested_tickers"]))
            coverage["available_count"] = len(coverage["covered_tickers"])
            coverage["coverage_ratio"] = round(
                len(coverage["covered_tickers"]) / len(coverage["requested_tickers"]), 6
            ) if coverage["requested_tickers"] else None
            coverage["complete"] = False
            coverage["status"] = "partial"
            if excluded_set & set(_active_weight_tickers(weights)):
                coverage["weight_basis"] = ACTIVE_WEIGHT_BASIS
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
            "data_status": _data_status(coverage, partial=len(port_ret) < MIN_ANNUALIZE_DAYS),
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
            "full_history": full_history,
            "history_coverage": history_coverage,
            "methodology": "Euler decomposition (volatility) + historical tail attribution (CVaR)",
        }
        result = apply_annualization_gate(result, ["portfolio_volatility_annualized"], len(port_ret))
        # The gate above writes a portfolio-level `annualized`; the model's own
        # verdict stays in `full_history` and is never overwritten by it.
        result["full_history"] = full_history
        return result
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

    The solved target is reported next to the shared weight-normalization block,
    the risk-free rate actually used, and the history window that was measured,
    so a reader can check that the weights are fundable from the book's own cash
    and that the Sharpe numerator is the one they think it is.
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
            measured_returns = None
            if prices is not None and len(prices) > 1:
                rets = prices.replace([np.inf, -np.inf], np.nan).pct_change(fill_method=None).dropna()
                measured_returns = rets
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
                # The same rule the rebalance workflow enforces, applied to the
                # published target, plus the rate and window behind the numbers.
                "weight_normalization": _weight_normalization_block({single_t: 1.0}),
                "risk_free_rate": rf,
                "latest_observation_date": _latest_observation_date(prices),
                "history_window": _history_window(
                    start, end, measured_returns, price_frame=prices
                ),
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
                "data_status": _data_status(coverage, unavailable=not coverage["covered_tickers"]),
                "data_unavailable_tickers": coverage["missing_tickers"],
                "weight_normalization": _weight_normalization_block({}),
                "risk_free_rate": rf,
                "latest_observation_date": _latest_observation_date(returns_df),
                "history_window": _history_window(start, end, returns_df),
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
        coverage = _universe_coverage(
            ticker_list, calculation_universe, active=_active_weight_tickers(current_weights)
        )
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

        response = {
            **result,
            "weights": reported_recommended,
            "universe": ticker_list,
            "calculation_universe": calculation_universe,
            "current_weights": {t: round(float(current_weights.get(t, 0.0)), 4) for t in ticker_list},
            "trades_required": dict(sorted(trades.items(), key=lambda kv: abs(kv[1]["weight_delta"]), reverse=True)),
            "universe_coverage": coverage,
            "data_status": _data_status(
                coverage, partial=bool(missing_tickers) or bool(result.get("error"))
            ),
            "data_unavailable_tickers": sorted(missing_tickers),
            # The solved target is measured against the same rule the rebalance
            # workflow enforces, so a reader can tell a normal rebalance from a
            # target the book cannot fund. The published weights are the
            # solver's answer and are never rewritten by the check.
            "weight_normalization": _weight_normalization_block(reported_recommended),
            "risk_free_rate": rf,
            "latest_observation_date": _latest_observation_date(returns_df),
            "history_window": _history_window(start, end, returns_df),
            "disclaimer": "Educational optimization output; not investment advice.",
        }
        if missing_tickers:
            # Target weights are solved over the delivered universe only; the
            # dropped active leg means the allocation basis is not the full book.
            response["weight_basis"] = ACTIVE_WEIGHT_BASIS
        return response
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
        calculation_tickers: List[str] = []
        if with_portfolio:
            try:
                portfolio_tickers, weights = await resolve_allocation(None, db)
                calculation_tickers = _active_weight_tickers(weights)
                if calculation_tickers:
                    end = datetime.now().strftime("%Y-%m-%d")
                    start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
                    holdings = await resolve_holdings(db, calculation_tickers)
                    # The HMM window below is 1100 days wide; the holding window
                    # is a question about the PORTFOLIO, not about that model
                    # window. Its start therefore comes from the canonical rule
                    # (one evidence window for every section) and the model leg
                    # is masked to it, so a wider regime window can no longer
                    # resolve an earlier buy-price date than realized risk does
                    # for the same stored `added_on`.
                    provenance = await holding_provenance(
                        data_service, holdings, calculation_tickers, end=end,
                    )
                    _, port_ret, leg_coverage = await _build_wide_returns(
                        calculation_tickers, weights, start, end, data_service,
                        holdings=canonical_holding_window_input(provenance["detail"]),
                    )
                    covered_days, mask = holding_window_observation_count(
                        port_ret,
                        provenance["start"],
                        measured_count=leg_coverage.get("covered_days"),
                        measured_start=leg_coverage.get("intersection_start"),
                    )
                    if mask is not None and leg_coverage.get("intersection_start") != provenance["start"]:
                        # Defensive: the leg was masked to a start this section
                        # no longer publishes, so its rows are re-cut here and
                        # the published count keeps describing the frame.
                        port_ret = port_ret[mask]
                    history_coverage = publish_holding_coverage(
                        detail=provenance["detail"],
                        per_ticker=_coverage_per_ticker(leg_coverage),
                        requested_start=start,
                        requested_end=end,
                        covered_days=covered_days,
                        evidence_window=provenance["evidence_window"],
                    )
                    history_coverage["model_used_tickers"] = list(
                        leg_coverage.get("model_used_tickers") or []
                    )
            except (ValueError, HTTPException):
                logger.debug("Regime portfolio leg unavailable")
                port_ret = None

        result = await detect_regime(db, lookback_days=lookback_days, portfolio_returns=port_ret)
        if history_coverage is not None and "portfolio_in_current_regime" in result:
            # The conditional block measured the days the classifier assigned
            # to the CURRENT regime, so it gets a coverage object describing
            # that sample - not the holding window it was drawn from.
            result["portfolio_in_current_regime"]["history_coverage"] = (
                _conditional_regime_coverage(
                    result["portfolio_in_current_regime"], history_coverage
                )
            )
        if history_coverage is not None:
            # Top-level copy lets the UI distinguish "no overlap" from
            # "no positions / no price data" (both omit the regime block). It
            # is the holding-window POOL the conditional sample is drawn from.
            result.setdefault("history_coverage", history_coverage)
            result.setdefault("holding_context", history_coverage)
            result["universe_coverage"] = _universe_coverage(
                portfolio_tickers,
                history_coverage.get("model_used_tickers", []),
                active=calculation_tickers,
            )
            result["data_status"] = _data_status(
                result["universe_coverage"],
                partial=(0 if port_ret is None else len(port_ret)) < MIN_ANNUALIZE_DAYS,
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
                active=_active_weight_tickers(weights),
            )
            result["universe_coverage"] = coverage
            # `active_currencies` is a single-element set here (mixed-currency
            # books were rejected above), so this is the unit the wealth levels
            # are denominated in. The returns are a ratio, so the FX level
            # cancels; the value unit and the return unit are published apart.
            result["currency"] = next(iter(active_currencies), None)
            result["returns_currency"] = next(iter(active_currencies), None)
            result["value_currency_basis"] = (
                "explicit_initial_value" if initial_value is not None else "db_native_market_value"
            )
            result["latest_observation_date"] = _latest_observation_date(port_ret)
            result["data_status"] = _data_status(
                coverage, partial=len(port_ret) < MIN_ANNUALIZE_DAYS
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
            active=_active_weight_tickers(weights),
        )
        return result.model_copy(
            update={
                "requested_tickers": coverage["requested_tickers"],
                "available_tickers": coverage["available_tickers"],
                "missing_tickers": coverage["missing_tickers"],
                "data_status": _data_status(
                    coverage, partial=len(returns_df) < MIN_ANNUALIZE_DAYS
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
    # The shared depth threshold, so the warning below never quotes a number this
    # route invented when the scan did not publish one.
    from app.services.cointegration_service import MIN_PAIR_DEPTH_RATIO

    class _PairsDisclosure(CointScannerResponse):
        """The scanner response plus the fields this route owes its consumers.

        `CointScannerResponse` is a closed contract (foundation-owned schema, and
        the DB cache rebuilds rows from it), and `model_copy(update=...)` on it
        writes unknown keys into `__dict__` only to have the serializer drop
        them again. So the currency/degradation declarations ride on an
        `extra="allow"` subclass: every declared field keeps its own type,
        default and validation, `isinstance` still holds, and `model_dump()` -
        exactly what the AI-context exporter serialises - keeps the new fields.
        """

        model_config = {"extra": "allow"}

        def __getattr__(self, name: str) -> Any:
            # A clean scan publishes NO `error` key at all (see `_publish`),
            # so the pre-existing `result.error` read stays safe and falsy
            # instead of raising.
            if name == "error":
                return None
            return super().__getattr__(name)

    def _publish(
        response: CointScannerResponse,
        *,
        extras: Optional[Mapping[str, Any]] = None,
    ) -> CointScannerResponse:
        """Attach the declared extras and guarantee no `error: null` ships.

        A literal `error: null` is the same misleading null-sentinel the export
        envelope forbids: it reads as "a failure that has no message" rather
        than "no failure". Absent means absent.
        """
        error = getattr(response, "error", None)
        if not (isinstance(error, str) and error.strip()):
            error = None
        payload = response.model_dump()
        if error is None:
            payload.pop("error", None)
        published = _PairsDisclosure(**payload, **dict(extras or {}))
        if error is None:
            # `error` is declared on the parent model, so the constructor puts
            # it back as None; drop it again so the key cannot be serialized.
            published.__dict__.pop("error", None)
        return published

    def _quote_unit(ticker: str) -> str:
        """Native quote currency of one scanned scrip.

        The platform's own quote contract (`DataService._normalize_quote_payload`
        and `_analytics_position_currency`) treats an NSE/BSE scrip as rupee
        quoted and anything else as dollar quoted, and the pair scan applies no
        FX conversion to the prices it fits, so that is the unit those prices
        are expressed in.
        """
        return "INR" if ticker.endswith((".NS", ".BO")) else "USD"

    def _depth_warning(
        response: CointScannerResponse,
        depth_by_ticker: Mapping[str, int],
        shallow: List[str],
    ) -> str:
        """One measured sentence naming why a depth-limited scan is `partial`."""
        threshold = getattr(response, "minimum_depth_ratio", None)
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            threshold = MIN_PAIR_DEPTH_RATIO
        pairs = list(getattr(response, "pairs", None) or [])
        limited = getattr(response, "depth_limited_pair_count", None)
        if isinstance(limited, bool) or not isinstance(limited, int):
            # Recount from the delivered rows rather than print a made-up count.
            limited = sum(
                1 for pair in pairs if getattr(pair, "depth_status", None) == "partial"
            )
        counts = {
            ticker: value
            for ticker, value in (depth_by_ticker or {}).items()
            if not isinstance(value, bool) and isinstance(value, int)
        }
        deepest = max(counts.values()) if counts else None

        def describe(ticker: str) -> str:
            value = counts.get(ticker)
            if value is None or not deepest:
                return f"{ticker} (usable observation count not measured)"
            return (
                f"{ticker} ({value} of {deepest} usable price observations, "
                f"{value / deepest:.0%})"
            )

        if shallow and deepest:
            named = ", ".join(describe(ticker) for ticker in sorted(shallow))
        else:
            named = (
                "no single ticker is individually below the threshold, so the "
                "limited pairs are the ones whose overlapping window is shorter "
                "than the deepest pair's"
            )
        return (
            f"Depth-limited pairs: {limited} of {len(pairs)} delivered pairs ran "
            f"on less than {threshold:.0%} of the deepest pair's overlap "
            f"(minimum_depth_ratio {threshold}). Shallow history: {named}. "
            f"Their Engle-Granger p-values, Johansen ranks and OU half-lives rest "
            f"on that shorter sample, so they are weaker evidence than the "
            f"full-depth pairs and the scan is reported as partial."
        )

    def _disclosure(
        response: CointScannerResponse,
        *,
        depth_by_ticker: Optional[Mapping[str, int]] = None,
        shallow: Optional[List[str]] = None,
        depth_status: str = "unavailable",
    ) -> Dict[str, Any]:
        """Declare the payload's monetary unit and any degradation, measured.

        Every monetary value this payload carries is a price: `last_price_a`,
        `last_price_b`, and the price-space OLS intercept `intercept_alpha`,
        which shares their unit. `hedge_ratio_beta`, the spread z-score and the
        OU half-life are ratios of those prices and stay dimensionless. The unit
        is therefore resolved from the tickers whose prices actually reached the
        payload, and declared only when they agree.
        """
        pairs = list(getattr(response, "pairs", None) or [])
        tickers = sorted(
            {
                str(getattr(pair, leg, "") or "").strip().upper()
                for pair in pairs
                for leg in ("ticker_a", "ticker_b")
                if getattr(pair, leg, None)
            }
        )
        units = sorted({_quote_unit(ticker) for ticker in tickers})
        warnings: List[str] = []
        extras: Dict[str, Any] = {}

        if len(units) == 1:
            unit = units[0]
            extras["currency"] = unit
            extras["currency_provenance"] = "derived"
            extras["currency_basis"] = (
                f"last_price_a, last_price_b and the price-space "
                f"intercept_alpha are the raw native quote prices of the "
                f"{len(tickers)} scanned scrips, so {unit} is the unit this fit "
                f"is expressed in; it follows from the scrips' exchange suffix "
                f"and is a property of the calculation's input prices rather "
                f"than a field read off a quote payload. No FX conversion is "
                f"applied."
            )
        elif units:
            # A genuine cross-currency fit has no single unit to declare, and
            # picking one of the two would mislabel the other.
            extras["currency_provenance"] = "mixed"
            extras["currency_basis"] = (
                f"The delivered pair prices span {' and '.join(units)} and the "
                f"scan applies no FX conversion, so hedge_ratio_beta and "
                f"intercept_alpha are a fit across two monetary units and no "
                f"single currency is declared for this payload."
            )
            warnings.append(
                f"Pair prices from {' and '.join(units)} were fitted together "
                f"without FX conversion, so no single monetary unit is declared "
                f"for this scan."
            )
        else:
            extras["currency_provenance"] = "unavailable"
            extras["currency_basis"] = (
                "No pair row was delivered, so this payload publishes no "
                "monetary value and no unit is declared for it."
            )

        if depth_status == "partial":
            warnings.append(
                _depth_warning(response, depth_by_ticker or {}, list(shallow or []))
            )
        if warnings:
            extras["warnings"] = warnings
        return extras

    try:
        if isinstance(tickers, str) and tickers.strip():
            parsed = _parse_tickers(tickers, max_items=_MAX_COINT_TICKERS)
            ticker_list = [ticker for ticker in (parsed or "").split(",") if ticker]
            explicit_universe = True
        else:
            try:
                ticker_list, _ = await resolve_allocation(None, db)
            except ValueError as exc:
                raise HTTPException(status_code=404, detail="No portfolio positions found") from exc
            if len(ticker_list) > _MAX_COINT_TICKERS:
                raise HTTPException(status_code=422, detail=f"At most {_MAX_COINT_TICKERS} tickers are allowed")
            explicit_universe = False

        if len(ticker_list) < 2:
            coverage = _universe_coverage(ticker_list, [])
            response = CointScannerResponse(
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
                universe_scope=UNIVERSE_SCOPES[1] if explicit_universe else UNIVERSE_SCOPES[0],
                depth_status="unavailable",
                test_roles=TEST_ROLES,
                pairs=[],
            )
            return _publish(response, extras=_disclosure(response))

        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

        # Fetch price data concurrently
        price_data_dict = await _fetch_price_series_dict(data_service, ticker_list, start, end)

        if len(price_data_dict) < 2:
            coverage = _universe_coverage(ticker_list, price_data_dict.keys())
            response = CointScannerResponse(
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
                data_status=_data_status(coverage),
                universe_scope=UNIVERSE_SCOPES[1] if explicit_universe else UNIVERSE_SCOPES[0],
                depth_status="unavailable",
                test_roles=TEST_ROLES,
                pairs=[],
                error="Insufficient price data available for at least 2 tickers",
            )
            return _publish(response, extras=_disclosure(response))

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
        # Per-ticker observation depth: a pair scanned off a materially shorter
        # history is a weaker result, so a shallow leg makes the whole scan
        # partial instead of quietly `complete`.
        depth_by_ticker = usable_observations_by_ticker(price_data_dict)
        depth_status = getattr(result, "depth_status", None) or "unavailable"
        shallow = list(getattr(result, "shallow_tickers", None) or [])
        if depth_status != "unavailable" and not shallow and depth_by_ticker:
            shallow = shallow_tickers(depth_by_ticker)
            if shallow:
                depth_status = "partial"
        coverage = {
            **coverage,
            "depth_status": depth_status,
            "shallow_tickers": shallow,
            "usable_observations_by_ticker": depth_by_ticker,
        }
        update: Dict[str, Any] = {
            "requested_tickers": coverage["requested_tickers"],
            "available_tickers": coverage["available_tickers"],
            "missing_tickers": coverage["missing_tickers"],
            "requested_universe_size": len(ticker_list),
            "analyzed_pairs_count": result.scanned_pairs_count,
            "returned_pairs_count": len(result.pairs),
            "returned_cointegrated_pairs_count": returned_cointegrated,
            "returned_non_cointegrated_pairs_count": len(result.pairs) - returned_cointegrated,
            "universe_scope": UNIVERSE_SCOPES[1] if explicit_universe else UNIVERSE_SCOPES[0],
            "depth_status": depth_status,
            "shallow_tickers": shallow,
            "usable_observations_by_ticker": depth_by_ticker,
            "test_roles": TEST_ROLES,
            # Pair scanning is weightless: it never renormalizes portfolio
            # weights, so its coverage must not claim a weight basis.
            "data_status": _data_status(
                coverage,
                partial=bool(result.unpairable_tickers) or depth_status == "partial",
            ),
            "universe_coverage": coverage,
        }
        # `error` is absent from a clean scan on purpose: passing the model's
        # `None` default through would publish a literal `error: null`, which
        # reads as "a failure with no message" instead of "no failure". Only a
        # real, non-blank failure earns the key.
        scan_error = getattr(result, "error", None)
        if isinstance(scan_error, str) and scan_error.strip():
            update["error"] = scan_error
        response = result.model_copy(update=update)
        return _publish(
            response,
            extras=_disclosure(
                response,
                depth_by_ticker=depth_by_ticker,
                shallow=shallow,
                depth_status=depth_status,
            ),
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
            active=_active_weight_tickers(weights),
        )
        if isinstance(cone_data, dict):
            cone_data["universe_coverage"] = coverage
            cone_data["data_status"] = _data_status(
                coverage, partial=len(port_ret) < MIN_ANNUALIZE_DAYS
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
        coverage = _universe_coverage(
            ticker_list, matrix_tickers, active=_active_weight_tickers(weights)
        )
        response = {
            **evt_stats,
            "tail_dependence_matrix": tail_copula_matrix,
            # Keep the legacy top-level list aligned with the matrix it describes.
            "tickers": matrix_tickers,
            "requested_tickers": ticker_list,
            "universe_coverage": coverage,
            "data_status": _data_status(coverage),
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

