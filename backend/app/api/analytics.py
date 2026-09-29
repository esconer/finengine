"""
Analytics API endpoints for risk calculations and portfolio analytics
"""

import asyncio
import inspect
import math
import time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError, validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import numpy as np
import pandas as pd

from app.db.database import get_db_session
from app.models.database import PortfolioPosition
from app.services.benchmark_service import BenchmarkService
from app.services.optimization_service import (
    no_estimate_uncertainty,
    optimizer_estimate_uncertainty,
    optimizer_no_sample_reason,
    optimize,
)
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
    AUTOCORRELATION_AR1_DECIMALS,
    AUTOCORRELATION_EFFECTIVE_N_DECIMALS,
    AUTOCORRELATION_EFFECTIVE_N_REPRODUCIBILITY_BASIS,
    EGARCH_VOL_CLIP_LOW,
    FORECAST_LEG_REFIT_RESAMPLES_WITHHELD,
    FORECAST_PORTFOLIO_REFIT_RESAMPLES,
    FORECAST_REFIT_COUNT_RULE,
    FORECAST_VOL_CLIP_HIGH,
    FORECAST_VOL_CLIP_LOW,
    GlobalAnalyticsEngine,
    AnalyticsEngine,
    TAIL_CLIP_HIGH,
    TAIL_CLIP_LOW,
    TAIL_ES_MULTIPLIER,
    TAIL_Z_MULTIPLIER,
    UNCERTAINTY_BOOTSTRAP_RESAMPLES,
    aggregate_active_returns,
    ar1_autocorrelation,
    effective_sample_size,
    engine_risk_statistics,
    effective_n_reproducibility_bound,
    market_model_statistics,
    market_model_witness,
    measure_estimate_uncertainty,
    quantstats_ratio_statistics,
    quantstats_returns_look_like_prices,
    volatility_forecast_statistics,
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
    gross_exposure,
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


# ---------------------------------------------------------------------------
# SI-5 -- estimator uncertainty for the tear sheet
# ---------------------------------------------------------------------------
# The tear sheet carries the numbers a reader ACTS on, and before this block
# every one of them - Sharpe 3.49, Sortino 5.31, Calmar 20.19, CAGR 43% - was a
# naked point estimate at 6 decimal places on as few as 20 daily observations.
# The block publishes a resampling interval beside each of them, or says why
# there is none.  It never invents one.
#
# The published numbers come from `quantstats`, so the statistics fed to the
# bootstrap are vectorised restatements of the SAME quantstats functions, and
# `measure_estimate_uncertainty` refuses to publish a band unless its own point
# value reproduces the published one.  The two things a Sharpe's interval has to
# say - how it was measured, and on how many observations - travel with it.
TEAR_SHEET_RISK_FREE_RATE = 0.02
#: The two shape statistics.  No honest interval, and a stated reason.
_SHAPE_STATISTIC_REASON = (
    "not computed: quantstats' skew and kurtosis are pandas bias-corrected "
    "shape statistics whose adjustment coefficients are not reimplemented here, "
    "so a resampling distribution over the SAME statistic cannot be produced. "
    "Re-deriving the correction by hand to satisfy an interval rule would trade "
    "a declared gap for a second, unverified implementation. The point estimate "
    "stands; its precision is declared absent rather than approximated."
)
#: quantstats' own gate: a series with min >= 0 and max > 1 is treated as
#: PRICES and differenced.  A daily equity return series does not look like
#: that, but "does not" is not "cannot" - if a window ever did, every ratio here
#: would silently change meaning, so the block is withheld with a reason.
_PRICE_RECLASSIFICATION_REASON = (
    "not computed: quantstats reclassifies this series as a PRICE series "
    "(min >= 0 and max > 1) and differences it before measuring, so the "
    "published value is a return of prices rather than a return of returns. "
    "Resampling it would describe a different statistic than the one published "
    "beside the band."
)


def _finite_return_values(frame: Any) -> np.ndarray:
    """A return series/frame as a finite ``(n,)`` or ``(n, k)`` float block."""
    if frame is None:
        return np.zeros((0, 1), dtype=float)
    values = (
        frame.to_numpy(dtype=float)
        if hasattr(frame, "to_numpy")
        else np.asarray(frame, dtype=float)
    )
    if values.ndim == 1:
        values = values.reshape(-1, 1)
    elif values.ndim != 2:
        return np.zeros((0, 1), dtype=float)
    return values[np.isfinite(values).all(axis=1)]


def _tear_sheet_uncertainty(
    frame: Any,
    published: Mapping[str, Any],
    *,
    scope: str,
    statistics: Optional[Mapping[str, Any]] = None,
    statistic_names: Optional[Mapping[str, str]] = None,
    not_computed: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """One tear-sheet block's precision disclosure.

    `statistics` defaults to the quantstats ratio suite; the relative block
    passes the market-model estimators instead, because beta and alpha are not
    quantstats functions.
    """
    values = _finite_return_values(frame)
    resolved = dict(not_computed or {})
    if quantstats_returns_look_like_prices(values):
        for field in published:
            resolved.setdefault(field, _PRICE_RECLASSIFICATION_REASON)
    return measure_estimate_uncertainty(
        np.zeros((0, 1)) if quantstats_returns_look_like_prices(values) else values,
        statistics if statistics is not None else quantstats_ratio_statistics(
            TEAR_SHEET_RISK_FREE_RATE
        ),
        published,
        scope=scope,
        # The tear sheet publishes its metrics at 6 dp, so half a display step
        # (5e-7) is the floor; the margin above it absorbs the vectorised
        # restatement's float noise without admitting a different estimator.
        point_tolerance=1e-5,
        not_computed=resolved,
        statistic_names=statistic_names,
        notes={
            "estimator": (
                "quantstats_ratio_statistics: vectorised restatements of the "
                "quantstats functions this route already calls, verified to "
                "reproduce each published metric before the band is attached"
            ),
            "risk_free_rate": TEAR_SHEET_RISK_FREE_RATE,
            "risk_free_rate_basis": (
                "the annualized rf this route passes to quantstats; quantstats "
                "deannualises it COMPOUNDED as (1 + rf) ** (1/252) - 1 and the "
                "resampling statistics use the same deannualisation"
            ),
            "annualization_periods": 252,
        },
    )


def _paired_return_columns(portfolio: Any, benchmark: Any) -> np.ndarray:
    """The ``(n, 2)`` market-model block, paired on DATE and never on position.

    `measure_estimate_uncertainty` drops rows where EITHER column is non-finite
    (`_finite_observation_block`), so all this has to do is put the two columns
    on one shared index and hand them over whole.

    It used to truncate both series to their common LENGTH and stack them
    positionally. Two series of different length then paired row-for-row as if
    they shared a calendar: the 307-session portfolio series against the OLDEST
    307 sessions of a 2620-session benchmark, roughly eight and a half years
    apart, and every resample described that other decade. The published point
    was never affected — the caller fits it on the same date intersection this
    block is now built from — but the BAND was, and the identity check in
    `measure_estimate_uncertainty` refused to publish it. An unlabelled
    position is not a weaker alignment; it is a different one, so it is gone.

    Two blocks with no index to align on can only be paired by position, so a
    length mismatch there yields no frame at all and the caller publishes the
    absence with the engine's own reason. Nothing is guessed.
    """
    if isinstance(portfolio, pd.Series) and isinstance(benchmark, pd.Series):
        if not portfolio.index.equals(benchmark.index):
            common = portfolio.index.intersection(benchmark.index)
            portfolio = portfolio.reindex(common)
            benchmark = benchmark.reindex(common)
        left = portfolio.to_numpy(dtype=float).ravel()
        right = benchmark.to_numpy(dtype=float).ravel()
    else:
        left = _finite_return_values(portfolio).ravel()
        right = _finite_return_values(benchmark).ravel()
        if left.size != right.size:
            return np.zeros((0, 2), dtype=float)
    if left.size == 0:
        return np.zeros((0, 2), dtype=float)
    return np.column_stack([left, right])


def _tear_sheet_relative_uncertainty(
    portfolio: Any,
    benchmark: Any,
    published: Mapping[str, Any],
    *,
    scope: str,
) -> Dict[str, Any]:
    """Beta and alpha precision over the ALIGNED window the two were fitted on.

    The pair is resampled jointly, so the co-movement that produces the
    estimate survives the resampling; resampling the two series separately would
    destroy the very covariance `beta_vs_nifty` is made of.

    The block is also handed an INDEPENDENT WITNESS: `market_model_witness`
    re-derives the published beta and alpha by `np.linalg.lstsq` on the
    `[1, b]` design matrix, which shares no arithmetic with the estimator's
    `cov(p, b) / var(b)`. When the two disagree, the witness says which side
    failed instead of the reason text accusing the published point.

    Both frames handed over are the SAME date-aligned block, and that is the
    point rather than a convenience. `witness_observations` defaults to
    `observations`, and on this route the estimator's frame IS the one a
    mis-pairing would corrupt, so the default would derive the witness from the
    very frame under suspicion: the witness would then agree with a mis-aligned
    ESTIMATOR rather than with the published point, the block would take the
    two-derivations-disagree branch, and a correct `beta_vs_nifty` would be
    published as `null`. Passing the same aligned frame explicitly makes the
    default and the explicit value agree, so the trap cannot be re-armed by
    forgetting an argument — the misalignment is fixed in the frame itself, at
    `_paired_return_columns`, and the witness only has to confirm the result.
    """
    frame = _paired_return_columns(portfolio, benchmark)
    return measure_estimate_uncertainty(
        frame,
        market_model_statistics(252),
        published,
        scope=scope,
        # beta and alpha are published at 4 dp, so half a display step is 5e-5;
        # the margin above it absorbs the restatement's float noise.
        point_tolerance=1e-4,
        statistic_names={"beta_vs_nifty": "beta"},
        witness=market_model_witness(252),
        witness_observations=frame,
        witness_basis=(
            "np.linalg.lstsq on the [1, b] design matrix, evaluated on the same "
            "date-aligned frame the resampling estimator was handed, which is "
            "the frame beta_vs_nifty and alpha_annualized were published from"
        ),
        notes={
            "estimator": (
                "market_model_statistics: the tear sheet's own closed form, "
                "beta = cov(p, b) / var(b) and alpha = (p.mean() - beta * "
                "b.mean()) * 252, both on ddof=1, with the portfolio and the "
                "benchmark resampled as aligned pairs"
            ),
            "resampling_basis": (
                "the portfolio and benchmark are resampled on the SAME index "
                "draw, so the joint distribution the covariance is estimated "
                "from is preserved inside every block"
            ),
            "alignment_basis": (
                "the two columns are paired on their shared DATE index and are "
                "never truncated to a common length, so a row of the frame is "
                "one session for both legs"
            ),
            "witness": (
                "market_model_witness: np.linalg.lstsq on the [1, b] design "
                "matrix, which shares no arithmetic with the estimator's closed "
                "form, evaluated on the same date-aligned frame. When the "
                "estimator's own point value misses the published one, this "
                "block names which side failed instead of asserting the "
                "published point is wrong; see estimates.<field>.point_status"
            ),
            "annualization_periods": 252,
        },
    )


# ---------------------------------------------------------------------------
# QM-2 -- which window each `relative_vs_nifty` field was measured on
# ---------------------------------------------------------------------------
# The block is not one sample, and it is published as if it were. Before this
# disclosure:
#
#   beta_vs_nifty / alpha_annualized  the holding-window portfolio returns and
#                                     the benchmark returns on their COMMON
#                                     dates -- a joint fit, so each side is
#                                     measured only where both were observed
#   benchmark_sharpe / _volatility /  the benchmark's own series over the
#   _max_drawdown / _total_return      REQUESTED window, bounded by how much
#                                     benchmark history is actually cached
#   (metrics, one level up)            the holding-window whole-book complete
#                                     return rows
#
# Three samples, one flat object, and a single `overlap_days` naming only the
# first of them. So a reader comparing `alpha_annualized` with the Sharpe beside
# it was comparing periods with nothing on the face of the block to say so.
#
# NONE of the three is recomputed here, and that is a decision, not an
# omission. The index has no holding period, so its standalone statistics have
# no holding window to be aligned to: slicing NIFTY down to the days *this
# user* owned the book answers a different question ("how did the index do
# while I held this?"), and on a 20-session holding window it annualises a
# handful of sessions into a Sharpe of -7. The four `benchmark_*` values are
# correct on the window they are already measured on, and re-slicing them
# would move four published numbers to make a block look tidy. What was missing
# is the answer to "over what window, on how many observations, aligned with
# what", per field -- so that is what this block publishes, and nothing else.
#
# A window that cannot be declared is a stated absence. This block never invents
# a window, never imputes an observation and never silences a field to make the
# object tidy: a `null` value with a reason beats a number with a hidden basis.

#: Key under which the disclosure travels, inside `relative_vs_nifty`.
RELATIVE_WINDOW_DISCLOSURE_KEY = "measurement_windows"

#: The three samples. Stable ids, so a consumer resolves a field to a window
#: without parsing prose.
RELATIVE_HOLDING_WINDOW_REF = "holding_window_metrics"
RELATIVE_MARKET_MODEL_WINDOW = "portfolio_benchmark_overlap"
RELATIVE_BENCHMARK_WINDOW = "requested_window_benchmark"

#: Which published field is measured on which sample. Kept as module constants
#: (rather than inline tuples at each use) so a field added to the statistics
#: without a window declaration is a missing mapping key, not a silent
#: unlabelled number.
RELATIVE_MARKET_MODEL_FIELDS = ("beta_vs_nifty", "alpha_annualized")
RELATIVE_BENCHMARK_FIELDS = (
    "benchmark_sharpe",
    "benchmark_volatility",
    "benchmark_max_drawdown",
    "benchmark_total_return",
)

_BENCHMARK_STATISTIC_NAMES = {
    "benchmark_sharpe": "sharpe",
    "benchmark_volatility": "volatility",
    "benchmark_max_drawdown": "max_drawdown",
    "benchmark_total_return": "total_return",
}

#: Why the index's own statistics stay on the requested window. Stated on the
#: face of the block, not only in a comment, because a reader comparing
#: `metrics.sharpe` with `benchmark_sharpe` deserves the answer to "is that
#: like for like?" before they do it.
RELATIVE_BENCHMARK_WINDOW_REASON = (
    "The index itself has no holding period, so its standalone statistics have "
    "no holding window to be aligned to. This sample is the requested window "
    "sliced back to the requested start and bounded by the benchmark history "
    "actually cached, which is generally LONGER than the holding window. "
    "Slicing it to the holding window instead would answer a different "
    "question - how the index performed on the days this book was held - and "
    "on a short holding window it would annualise a handful of sessions. The "
    "values are therefore published on the window they are correct on, not "
    "recomputed onto the window of the metrics block beside them."
)

_RELATIVE_COMPARISON_NOTE = (
    "This block is not on a single window. Compare a field only with a field "
    "whose `window_ref` matches: `metrics` and this block's holding-window "
    "sample are like for like, and nothing else here is. In particular a "
    "`metrics` ratio and a `benchmark_*` value are measured over different "
    "periods and their difference is not a skill gap."
)

_RELATIVE_NO_BENCHMARK_REASON = (
    "not computed: the benchmark return series was unavailable or too short to "
    "measure, so no portfolio/benchmark overlap and no index statistics exist. "
    "No window is declared because none was measured. The holding-window sample "
    "the metrics block was measured from is still declared below."
)


def _series_window_record(
    frame: Any,
    *,
    basis: str,
    description: str,
) -> Dict[str, Any]:
    """Window, observation count and date bounds of the series actually used.

    Built from the frame the estimates were computed from, so the published
    count cannot drift from the count the statistics saw.
    """
    index = getattr(frame, "index", None)
    observations = int(len(index)) if index is not None else 0
    first, last = _observation_bounds(frame)
    return {
        "basis": basis,
        "description": description,
        "observations": observations,
        "observation_count": observations,
        "window": {"start": first, "end": last, "days": observations},
    }


def _same_observations(left: Any, right: Any) -> bool:
    """True when two series are literally the same dated observations.

    Compares the index, not the counts: a benchmark window of the same LENGTH
    as the holding window is still a different sample, and telling a reader
    otherwise would be exactly the confusion this block exists to remove.
    """
    left_index = getattr(left, "index", None)
    right_index = getattr(right, "index", None)
    if left_index is None or right_index is None:
        return False
    if len(left_index) != len(right_index) or len(left_index) == 0:
        return False
    return bool(left_index.equals(right_index))


def _relative_window_disclosure(
    *,
    metrics_series: Any,
    metrics_basis: str,
    metrics_description: str,
    benchmark_series: Any,
    benchmark_window: Any,
    overlap_series: Any,
    overlap_observations: int,
    benchmark_available: bool,
    published_fields: Optional[Iterable[str]] = None,
    requested_window: Optional[Mapping[str, Any]] = None,
    metrics_block_path: str = "tear_sheet.metrics",
    observation_count_path: str = "tear_sheet.measured_window.observation_count",
) -> Dict[str, Any]:
    """Per-field window and observation count for a `relative_vs_nifty` block.

    Returns the disclosure only; the caller stores it under
    `RELATIVE_WINDOW_DISCLOSURE_KEY` so the estimates beside it keep their
    existing keys and values untouched.

    `published_fields` bounds the disclosure to the statistics the block
    actually carries. The full-history sibling publishes no `benchmark_*` field,
    and declaring four field records there would be a worse version of the
    defect this block removes: a reader would find a window for a number that
    was never measured. So a field with no published value is not described,
    and neither is a window no published field uses.

    `metrics_block_path` and `observation_count_path` are the JSON paths a
    reader can check this record against. They are parameters, not constants,
    because the full-depth sibling's counts are published at
    `tear_sheet.full_history.metrics.days` -- NOT at
    `tear_sheet.full_history.window`, which is a per-ticker price-frame row
    count over a different frame entirely and would send a reader to a number
    that does not match the window described here.
    """
    labelled = set(
        published_fields
        if published_fields is not None
        else RELATIVE_MARKET_MODEL_FIELDS + RELATIVE_BENCHMARK_FIELDS
    )
    metrics_record = _series_window_record(
        metrics_series,
        basis=metrics_basis,
        description=metrics_description,
    )
    metrics_record["same_sample_as"] = metrics_block_path
    metrics_record["published_also_at"] = observation_count_path

    if not benchmark_available:
        # No benchmark: nothing was measured against one. Publishing a window
        # with a zero count and no reason would read as "measured, found
        # nothing"; stating the absence reads as what it is.
        return {
            "status": "withheld",
            "reason": _RELATIVE_NO_BENCHMARK_REASON,
            "windows": {RELATIVE_HOLDING_WINDOW_REF: metrics_record},
            "fields": {},
            "comparison_note": _RELATIVE_COMPARISON_NOTE,
        }

    metrics_observations = int(metrics_record["observations"])

    benchmark_record = _series_window_record(
        benchmark_window,
        basis=RELATIVE_BENCHMARK_WINDOW,
        description=(
            "the benchmark's own daily return series, from the requested "
            "window start to the requested end, bounded by the benchmark "
            "history actually cached"
        ),
    )
    benchmark_record["reason_not_recomputed"] = RELATIVE_BENCHMARK_WINDOW_REASON
    if requested_window is not None:
        benchmark_record["requested_window"] = dict(requested_window)
    benchmark_record["shares_metrics_sample"] = _same_observations(
        benchmark_window, metrics_series
    )
    # The requested window is a request, and the cached benchmark history is
    # usually SHORTER than it (a 365-day request over 245 cached sessions).
    # Stating the shortfall is the difference between "measured over the
    # requested window" and "measured over what the cache could supply", and
    # the two are different claims.
    requested_start = (requested_window or {}).get("start")
    cached_first, _ = _observation_bounds(benchmark_series)
    try:
        truncated = bool(
            requested_start
            and cached_first
            and cached_first > str(requested_start)[:10]
        )
    except TypeError:
        truncated = False
    benchmark_record["truncated_by_cached_benchmark_depth"] = truncated
    if truncated:
        benchmark_record["cached_depth_start"] = cached_first
        benchmark_record["truncation_basis"] = (
            "the benchmark history cached from this date is shorter than the "
            "requested window, so the window above is what the cache could "
            "supply and not the whole requested span"
        )

    overlap_frame: Any = overlap_series
    overlap_count = int(overlap_observations)
    overlap_record = _series_window_record(
        overlap_frame,
        basis=RELATIVE_MARKET_MODEL_WINDOW,
        description=(
            "the portfolio returns and the benchmark returns on their COMMON "
            "dates only; beta and alpha are a joint covariance fit, so each "
            "side contributes only on dates both were observed"
        ),
    )
    # The overlap count is the gated quantity, so it must not be re-derived
    # from a frame that may hold more rows than were used.
    overlap_record["observations"] = overlap_count
    overlap_record["observation_count"] = overlap_count
    overlap_record["window"]["days"] = overlap_count
    overlap_record["minimum_observations_required"] = MIN_ANNUALIZE_DAYS
    overlap_record["below_minimum_observations_required"] = bool(
        overlap_count < MIN_ANNUALIZE_DAYS
    )
    overlap_record["gate_effect"] = (
        "withheld: fewer overlapping observations than the annualization "
        "policy requires, so beta and alpha are null and the point estimate "
        "is absent rather than annualised from a short sample"
        if overlap_count < MIN_ANNUALIZE_DAYS
        else "reported: the overlap clears the annualization policy minimum"
    )
    shares = _same_observations(overlap_frame, metrics_series)
    overlap_record["shares_metrics_sample"] = shares
    # The relation to the metrics sample is a property of the WINDOW, not of
    # each field measured on it, so it is stated once here rather than repeated
    # on every field record (which would be two sources of truth for one fact,
    # free to drift apart).
    overlap_record["relation_to_metrics_window_basis"] = (
        "every holding-window portfolio return observation also has a "
        "benchmark return, so a field fitted here uses exactly the rows the "
        "metrics block was measured from"
        if shares
        else "the benchmark was not observed on every holding-window session, "
        "so the joint fit is restricted to the common dates and is a SHORTER "
        "sample than the metrics block"
    )
    benchmark_record["relation_to_metrics_window_basis"] = (
        "the index series happens to carry the same dated observations as the "
        "metrics block"
        if benchmark_record["shares_metrics_sample"]
        else "the index series is a different, usually much longer, sample than "
        "the metrics block; a value measured here must not be compared with a "
        "`metrics` ratio as though it covered the holding window"
    )

    fields: Dict[str, Any] = {}
    for name in RELATIVE_MARKET_MODEL_FIELDS:
        if name not in labelled:
            continue
        fields[name] = {
            "window_ref": RELATIVE_MARKET_MODEL_WINDOW,
            "observations": overlap_count,
            "observations_short_of_metrics_window": (
                None if shares else max(0, metrics_observations - overlap_count)
            ),
            "shares_metrics_window": shares,
        }
    for name in RELATIVE_BENCHMARK_FIELDS:
        if name not in labelled:
            continue
        shares_bench = bool(benchmark_record["shares_metrics_sample"])
        fields[name] = {
            "window_ref": RELATIVE_BENCHMARK_WINDOW,
            "observations": int(benchmark_record["observations"]),
            "observations_short_of_metrics_window": (
                None
                if shares_bench
                else int(benchmark_record["observations"]) - metrics_observations
            ),
            "shares_metrics_window": shares_bench,
        }

    # Only the windows a published field actually rests on, plus the metrics
    # sample they are being compared against.
    records = {
        RELATIVE_HOLDING_WINDOW_REF: metrics_record,
        RELATIVE_MARKET_MODEL_WINDOW: overlap_record,
        RELATIVE_BENCHMARK_WINDOW: benchmark_record,
    }
    used = {record["window_ref"] for record in fields.values()}
    declared = sorted(used)
    windows = {
        ref: record
        for ref, record in records.items()
        if ref in used or ref == RELATIVE_HOLDING_WINDOW_REF
    }
    return {
        "status": "computed",
        "reason": None,
        "windows": windows,
        "fields": fields,
        "distinct_windows": len(windows),
        "windows_fields_rest_on": len(declared),
        "fields_sharing_the_metrics_window": sorted(
            name for name, record in fields.items() if record["shares_metrics_window"]
        ),
        "fields_not_on_the_metrics_window": sorted(
            name
            for name, record in fields.items()
            if not record["shares_metrics_window"]
        ),
        "comparison_note": _RELATIVE_COMPARISON_NOTE,
    }


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
    """Non-null return observations per ticker, measured from a PRICE frame.

    Mirrors the engine's own per-position sample (union index kept, so an
    interior gap stays a gap rather than becoming a synthetic multi-day
    return). A frame that is not a dated `DataFrame` measures nothing and
    returns an empty map rather than an invented count.

    Only ever call this with prices: it differences the frame to MAKE returns, so
    handing it a frame that is already a return frame measures the returns of
    those returns and reports a count two rows short of the truth.
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

# --- Which sample `model_observation_count` counts ---------------------------
# `history_coverage.model_observation_count` used to be a copy of
# `full_history.observation_count` - the ROWS OF THE INPUT FRAME - published
# under the name of the model's own sample. On the live book that published 175
# where the regression used 101, so a reader checking the count against the
# `r_squared` beside it (`adjusted_r_squared` is 1-(1-R^2)(n-1)/(n-2) and pins
# n=101) found a contradiction the export could not explain. A frame row is not
# a regression observation: the fit runs on the dates the PUBLISHED portfolio
# series contains, intersected with the benchmark, which is a subset of the
# frame whenever any leg is late-listed or the book is refused for partial
# coverage.
#
# So the count is now handed IN by the caller that knows it, with the population
# it describes. The two scopes below are populations, not labels: the fit's own
# sample, and the input frame that bounds it from above when the fit's own
# sample cannot be measured.
MODEL_SAMPLE_FITTED_SCOPE = "active_benchmark_overlap_return_rows"
MODEL_SAMPLE_FRAME_SCOPE = "input_return_rows_regression_subset_unmeasured"
MODEL_SAMPLE_COVARIANCE_FRAME_SCOPE = "full_exchange_history_return_frame_rows"
MODEL_SAMPLE_FITTED_NOTE = (
    "The regression's OWN sample: the dates the published portfolio return "
    "series contains, intersected with the benchmark. It is a subset of "
    "full_history.observation_count - the input frame the fit was handed - and "
    "is the same fit that produced r_squared/adjusted_r_squared and "
    "portfolio.observations on this section."
)
MODEL_SAMPLE_FRAME_NOTE = (
    "The input return frame the regression was handed, NOT a measured "
    "regression sample. The fit published no usable count of its own, so this "
    "number is an UPPER BOUND on the sample used and will read high whenever a "
    "leg is late-listed or the book is refused for partial coverage. Treat the "
    "count as a frame size, not as a sample size."
)
MODEL_SAMPLE_COVARIANCE_FRAME_NOTE = (
    "Rows of the wide per-leg return frame this section's covariance model was "
    "computed over. cov(min_periods=2) estimates each PAIR over the rows where "
    "both legs are priced, so the effective per-pair sample is at most this "
    "count; the complete-book portfolio series this section also publishes is "
    "counted separately as calculation_observations."
)


def _full_history_evidence(
    returns_frame: Any,
    *,
    requested_start: Optional[str],
    requested_end: Optional[str],
    declared_limited: Optional[Mapping[str, bool]] = None,
    coverage_reasons: Optional[Mapping[str, Optional[str]]] = None,
    metrics_series: Any = None,
) -> Dict[str, Any]:
    """Self-describing evidence for a model measured on full exchange history.

    Takes the RETURN frame the model actually consumed, so the published window
    and observation count describe the observations used and nothing is
    double-counted by re-deriving returns from an already-returned frame.

    Own window, own observation count, own latest observation and own
    annualization flag. Sparse or late-listed legs are published with their own
    usable observation count and limited-history flag instead of being averaged
    away by the rest of the book.

    `metrics_series` is the series the block's `metrics` were measured on, and
    it is almost never the frame above. This block is described by the WIDE
    per-ticker frame, whose row count is every date on which ANY leg was
    measurable, while the metrics beside it are computed from one portfolio
    return series that exists only on dates where the whole positive-weight book
    cleared coverage. Those are different populations and different lengths --
    2486 against 307 in the reviewed export -- so the block used to declare a
    2486-day window over metrics annualised on 307 days, and recomputing CAGR
    from the declared window was wrong by 9.11x. The frame is still what the
    window describes, so the frame keeps `window`/`observation_count`; the
    metrics' own count and bounds are published beside them as
    `metrics_observation_count` / `metrics_window` so the two can never be read
    as one sample.

    `annualized` is a statement about the FRAME's population -- the frame row
    count and the smallest per-ticker return count -- because that is what the
    flag has always tested. It is published with the two counts it tested rather
    than as a bare boolean, so a reader who takes it as a licence to annualize
    the `metrics` beside it can see that it never looked at those.
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
    min_ticker_count = int(min(counts.values())) if counts else None
    meets = bool(
        observations >= MIN_ANNUALIZE_DAYS
        and counts
        and min_ticker_count >= MIN_ANNUALIZE_DAYS
    )
    evidence = {
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
        "annualized_population": (
            "the wide per-ticker return frame: True when the frame itself has at "
            f"least {MIN_ANNUALIZE_DAYS} rows AND every ticker's own return "
            "observation count reaches that minimum. It is NOT a statement "
            "about the `metrics` block beside it, which is measured on a "
            "different and usually far shorter series -- read "
            "metrics_observation_count for that population."
        ),
        "annualization_tested_frame_observations": observations,
        "annualization_tested_minimum_ticker_return_observations": min_ticker_count,
        "minimum_observations_required": MIN_ANNUALIZE_DAYS,
        "model_used_tickers": [str(c) for c in frame.columns],
        "tickers": tickers,
        "holding_context_note": FULL_HISTORY_RELATION,
    }
    if metrics_series is not None:
        metrics_observations = int(len(metrics_series))
        metrics_first, metrics_last = _observation_bounds(metrics_series)
        evidence["metrics_observation_count"] = metrics_observations
        evidence["metrics_window"] = {
            "start": metrics_first,
            "end": metrics_last,
            "days": metrics_observations,
        }
        evidence["metrics_observation_count_basis"] = (
            "the portfolio return series this block's `metrics` were measured "
            "on, which is a DIFFERENT and usually far shorter population than "
            "observation_count above: that counts every date ANY leg was "
            "measurable on, this counts the dates the whole positive-weight "
            "book cleared coverage on. CAGR, Sharpe, Sortino, Calmar and "
            "volatility are annualised on THIS count, so "
            "(1 + total_return) ** (252 / metrics_observation_count) - 1 "
            "reproduces `metrics.cagr` and the same expression on "
            "observation_count does not."
        )
        evidence["metrics_meet_minimum_observations"] = bool(
            metrics_observations >= MIN_ANNUALIZE_DAYS
        )
    return evidence


# --- Risk contribution: what `positions.*` is a number OF --------------------
# `positions.volatility` and `positions.cvar_tail` are dimensionless SHARES of
# total portfolio risk, normalized to 1 and then rounded to six decimals, so they
# publish as 0.999998 and 0.999999. They sat in a payload that also carries
# `annualized: true` and `portfolio_volatility_annualized` (an absolute
# annualized volatility in return units) with nothing saying which was which, so a
# reader had no way to know the position rows were neither currency nor an
# annualized figure, and no way to see the residual. Both are published here.
CONTRIBUTION_UNIT = "fraction_of_portfolio_risk"
CONTRIBUTION_DECIMALS = 6

# ---------------------------------------------------------------------------
# One name per model, in every container of this section
# ---------------------------------------------------------------------------
# The section names its two models in FIVE places - `positions`, `excluded_assets`,
# `contribution_basis.per_model`, `sector_rollup` and
# `contribution_basis.sector_rollup_per_model` - plus
# `universe_coverage.model_used_tickers`.  It used to spell the tail model
# `cvar_tail` in three of them and `cvar` in two, for one model, in one object.  A
# consumer keying on either spelling silently misses half the block: `cvar_tail`
# misses `sector_rollup`, `cvar` misses `positions`, and neither failure is
# visible from the payload.  The arithmetic was never the problem - all fourteen
# legs roll into their sector with |d| = 0.0 for both models - so nothing here
# moves a share; the keys are made to agree.
#
# WHICH SPELLING IS KEPT, and why.  `cvar_tail`, on four counts rather than on
# taste: it is the spelling in the majority of containers; it is the spelling
# `universe_coverage.model_used_tickers` already used, so the coverage block and
# the share blocks now agree; it is the spelling this module's own header comment
# above documents; and bare `cvar` collides with the tail MEASURE
# (`portfolio_cvar_95_daily`, `tail_measure.cvar_forecast`,
# `cvar_to_var_ratio`) which is a different quantity in a different unit on the
# same payload.  A name that is already three other things is the wrong one to
# keep for a fourth.
CONTRIBUTION_MODEL_NAMES = ("volatility", "cvar_tail")

#: The retired spelling, kept as a POINTER rather than as a second key.  A second
#: key is exactly the defect: it would put both spellings for one model back into
#: the payload, which is the thing being fixed.  An alias map says which name to
#: read and where, so a consumer keying on `cvar` is redirected rather than left
#: silently empty.
CONTRIBUTION_MODEL_ALIASES = {"cvar": "cvar_tail"}

CONTRIBUTION_MODEL_NAME_BASIS = (
    "one model, one name, in every container of this section. "
    "positions, excluded_assets, contribution_basis.per_model, sector_rollup, "
    "contribution_basis.sector_rollup_per_model and "
    "universe_coverage.model_used_tickers are all keyed by the canonical names "
    "listed here, so a consumer can iterate one vocabulary across all of them. "
    "aliases maps every retired spelling to the name that replaced it: "
    + ", ".join(
        f"{old!r} -> {new!r}" for old, new in CONTRIBUTION_MODEL_ALIASES.items()
    )
    + ". No container publishes both spellings for the same model, because a "
    "reader could not then tell which of two keys was the real one and which was "
    "the copy. The section previously published 'cvar_tail' in positions, "
    "excluded_assets and contribution_basis.per_model and 'cvar' in sector_rollup "
    "and contribution_basis.sector_rollup_per_model, for one model, in one object; "
    "no published share changed, only which key carries it"
)

#: The two names `sector_rollup` and `contribution_basis.sector_rollup_per_model`
#: are built from.  Held as a constant rather than written at the call site so the
#: rename cannot be applied to one of the two containers and forgotten on the
#: other, which is how the two spellings diverged in the first place.
CONTRIBUTION_SECTOR_ROLLUP_NAMES = ("volatility", "cvar_tail")

# ---------------------------------------------------------------------------
# SI-5 -- precision of this section's two tail estimates
# ---------------------------------------------------------------------------
# `portfolio_var_95_daily` and `portfolio_cvar_95_daily` are order statistics of
# the published portfolio return series: a 5 % quantile, and the mean of the
# days at or below it.  Neither is a stable function of the window, so both
# carry a resampling standard error and interval - and the sample that supports
# them is the TAIL, not the window, which is stated rather than left for a
# reader to guess from a row count.
RISK_CONTRIBUTION_TAIL_SUPPORT_SCOPE = (
    "portfolio_return_days_at_or_below_the_published_var_95"
)
RISK_CONTRIBUTION_TAIL_SUPPORT_BASIS = (
    "the number of published portfolio return days at or below this section's "
    "own 5th percentile - the days the quantile is an order statistic OF, and "
    "the days the expected shortfall is the mean OF. It is not the window "
    "length: a 5 % quantile gains no information from the 95 % of days above "
    "it beyond the fact that they are above it, and a reader who priced a "
    "VaR as if it were estimated from 172 independent days would overstate its "
    "precision by roughly the square root of the ratio"
)
RISK_CONTRIBUTION_TAIL_EFFECTIVE_N_BASIS = (
    "the Quenouille/Bartlett AR(1) variance-inflation adjustment n * (1 - ar1) "
    "/ (1 + ar1) applied to the TAIL sample rather than to the window, because "
    "the tail is the sample this estimate was measured on, and then bounded by "
    "the tail count: the adjustment removes redundancy, and a 5 % order "
    "statistic cannot be informed by more days than the tail contains, so a "
    "negative AR(1) cannot inflate it past its own support (the uncapped figure "
    "is published as effective_n_uncapped). The window-level figure is "
    "published beside it at tail_support.window_effective_n and describes the "
    "resampling frame instead"
)


def _tail_support_reproducibility(
    tail_count: int,
    tail_ar1: Optional[float],
    tail_effective_raw: Optional[float],
) -> Dict[str, Any]:
    """Does this block's own formula reproduce its own published figure?

    Measured against the UNCAPPED figure, which is the one the formula produces.
    The cap at the tail count is a separate declared step applied afterwards
    (`effective_n_cap_applied` says whether it bound), and folding it in here
    would report a residual the declared rounding bound does not and should not
    cover - the bound is a statement about ROUNDING, not about the cap.

    `effective_n_reproducibility_bound` is the engine's own function, and it takes
    only published inputs (`n` and the rounded `ar1`), so this is the same bound
    the window-side `autocorrelation` block publishes rather than a second
    derivation of it.
    """
    if tail_ar1 is None or tail_effective_raw is None or not tail_count:
        return {
            "describes": "effective_n_uncapped",
            "recomputes_from_published_ar1": None,
            "recomputation_deviation": None,
            "recomputation_deviation_bound": None,
            "within_declared_bound": None,
            "bound_basis": None,
            "reason": (
                "not measured: no AR(1) slope and no effective sample size were "
                "published for this tail, so there is nothing to recompute. See "
                "tail_support.effective_n_reason"
            ),
        }
    published_ar1 = round(float(tail_ar1), AUTOCORRELATION_AR1_DECIMALS)
    published = round(
        float(tail_effective_raw), AUTOCORRELATION_EFFECTIVE_N_DECIMALS
    )
    recomputed = effective_sample_size(int(tail_count), published_ar1)
    deviation = (
        abs(float(recomputed) - published) if recomputed is not None else None
    )
    bound = effective_n_reproducibility_bound(int(tail_count), published_ar1)
    return {
        "describes": "effective_n_uncapped",
        "recomputes_from_published_ar1": (
            None if deviation is None else bool(deviation == 0.0)
        ),
        "recomputation_deviation": deviation,
        "recomputation_deviation_bound": bound,
        "within_declared_bound": (
            None if (deviation is None or bound is None)
            else bool(deviation <= bound)
        ),
        "bound_basis": AUTOCORRELATION_EFFECTIVE_N_REPRODUCIBILITY_BASIS,
        "reason": None,
    }


def _contribution_basis_block(
    positions: Mapping[str, Any],
    sector_rollup: Mapping[str, Any],
) -> Dict[str, Any]:
    """Unit, normalization rule and rounding residual for the share maps."""
    models: Dict[str, Any] = {}
    for model, shares in (positions or {}).items():
        values = list(shares.values()) if isinstance(shares, Mapping) else []
        try:
            numbers = [float(value) for value in values]
        except (TypeError, ValueError):
            numbers = []
        if not numbers:
            models[str(model)] = {
                "leg_count": len(values),
                "published_total": None,
                "rounding_residual": None,
            }
            continue
        total = round(sum(numbers), 12)
        models[str(model)] = {
            "leg_count": len(numbers),
            "published_total": total,
            "rounding_residual": round(1.0 - total, 12),
        }
    sectors: Dict[str, Any] = {}
    for model, roll in (sector_rollup or {}).items():
        values = list(roll.values()) if isinstance(roll, Mapping) else []
        try:
            total = round(sum(float(value) for value in values), 12)
        except (TypeError, ValueError):
            continue
        sectors[str(model)] = {
            "published_total": total,
            "rounding_residual": round(1.0 - total, 12),
        }
    return {
        "unit": CONTRIBUTION_UNIT,
        "field": "positions.* and sector_rollup.*",
        "model_names": {
            "canonical": list(CONTRIBUTION_MODEL_NAMES),
            "aliases": dict(CONTRIBUTION_MODEL_ALIASES),
            "basis": CONTRIBUTION_MODEL_NAME_BASIS,
        },
        "normalization": (
            "Each model's shares are normalized to 1.0 over the legs that model "
            "could support, then rounded to 6 decimals. A model that excluded a "
            "leg (see excluded_assets) normalizes over the legs it kept, so its "
            "shares sum to 1 over those legs and not over the whole book."
        ),
        "rounding_decimals": CONTRIBUTION_DECIMALS,
        "per_model": models,
        "sector_rollup_per_model": sectors,
        "sector_rollup_note": (
            "sector_rollup sums the per-leg shares of one model into their sector, "
            "rounded to the same 6 decimals, so it carries its own residual."
        ),
        "annualized_note": (
            "annualized and portfolio_volatility_annualized describe the "
            "VOLATILITY model's window in annualized return units. They do not "
            "apply to positions.* or sector_rollup.*, which are unitless shares of "
            "total portfolio risk, annualized or not."
        ),
    }


def _risk_contribution_tail_uncertainty(
    portfolio_returns: Any,
    *,
    var_95: Any,
    tail_mask: Any,
    published: Mapping[str, Any],
    scope: str,
) -> Dict[str, Any]:
    """Precision disclosure for this section's two tail estimates (SI-5).

    `portfolio_var_95_daily` is the 5th percentile of the portfolio's published
    daily return series and `portfolio_cvar_95_daily` is the mean of the days at
    or below it.  Both are order statistics of that series, and both were
    published as bare point estimates: a 5 % tail quantile read to six decimals
    off 172 autocorrelated daily returns, with nothing said about how much of
    that precision is real.

    THE BOOTSTRAP RESAMPLES THE WINDOW, THE EFFECTIVE n IS THE TAIL.  These are
    different populations and conflating them is the trap:

      * the resampling frame is the whole published portfolio series, because
        the statistic being resampled is the 5th percentile OF THAT SERIES.  A
        bootstrap over the tail days alone would measure the 5th percentile of
        the tail - a different number - and `measure_estimate_uncertainty`'s
        reproduction guard would refuse the band, correctly.
      * the effective sample size is the number of days that actually support
        the estimate: the tail.  A 5 % quantile cannot learn anything from the
        95 % of days that are above it, and the expected shortfall is literally
        the mean of the tail days and nothing else.  The entry's `effective_n` is
        therefore the AR(1)-adjusted TAIL count, and the window-level figure
        stays published beside it as `autocorrelation.effective_n` so the two
        cannot be confused for one another.

    `tail_mask` is the section's OWN mask - the same `port_ret <= var_95` that
    decided which days went into the expected shortfall - so the tail count here
    is the count that number was measured on and not a re-derived one.
    """
    series = (
        portfolio_returns.to_numpy(dtype=float).ravel()
        if hasattr(portfolio_returns, "to_numpy")
        else np.asarray(portfolio_returns, dtype=float).ravel()
    )
    series = series[np.isfinite(series)]
    if tail_mask is None or var_95 is None:
        tail_values = np.zeros(0, dtype=float)
    else:
        mask = np.asarray(tail_mask, dtype=bool).ravel()
        if mask.shape[0] == series.shape[0]:
            tail_values = series[mask]
        else:
            tail_values = np.zeros(0, dtype=float)
    tail_count = int(tail_values.size)
    tail_ar1 = ar1_autocorrelation(tail_values) if tail_count else None
    tail_effective_raw = effective_sample_size(tail_count, tail_ar1)
    # The Quenouille/Bartlett adjustment is a REDUNDANCY correction: a negative
    # AR(1) inflates it above n, which is real for the mean of a stationary
    # series and meaningless here. A 5 % order statistic cannot be informed by
    # more days than the tail contains, so the published figure is bounded by
    # the support and the uncapped one is published beside it. Both are shown;
    # neither is hidden.
    tail_effective = (
        None if tail_effective_raw is None
        else float(min(tail_effective_raw, float(tail_count)))
    )
    tail_reason = (
        None if tail_effective is not None else (
            f"the tail this estimate rests on is {tail_count} day(s) of a "
            f"{int(series.size)}-day window, which is too short - or has too "
            "little variation in the lagged series - to fit an AR(1) slope, so "
            "no effective sample size is published for it. The tail count above "
            "is the honest one; the AR(1)-adjusted figure is withheld rather "
            "than assumed to equal it"
        )
    )
    # The restatements are the engine's own `var_95` / `cvar_95`, which are
    # already vectorised versions of exactly the two expressions above
    # (`np.percentile(r, 5)` and the mean of `r <= var_95`).
    restatements = engine_risk_statistics(0.0)
    block = measure_estimate_uncertainty(
        series,
        {name: restatements[name] for name in ("var_95", "cvar_95")},
        dict(published),
        scope=scope,
        # Both points are published at 6 dp, so half a display step is 5e-7;
        # the margin above it absorbs the restatement's float noise.
        point_tolerance=1e-5,
        # One pair of estimators, two published names: this section publishes
        # the quantile and the shortfall under portfolio-prefixed keys.
        statistic_names={
            "portfolio_var_95_daily": "var_95",
            "portfolio_cvar_95_daily": "cvar_95",
        },
        not_applicable={
            field: reason
            for field, reason in (
                (
                    "portfolio_var_95_daily",
                    None
                    if published.get("portfolio_var_95_daily") is not None
                    else "not applicable: no 5th percentile was published for "
                    "this book, so there is no quantile to put an interval "
                    "around",
                ),
                (
                    "portfolio_cvar_95_daily",
                    None
                    if published.get("portfolio_cvar_95_daily") is not None
                    else "not applicable: the portfolio series published no day "
                    "at or below its own 5th percentile, so the expected "
                    "shortfall is undefined rather than zero",
                ),
            )
            if reason
        },
        notes={
            "estimator": (
                "engine_risk_statistics' var_95 / cvar_95: vectorised "
                "restatements of this section's own expressions - "
                "np.percentile(portfolio_returns, 5) and the mean of the days "
                "at or below it - so the band belongs to the published numbers"
            ),
            "tail_support_basis": RISK_CONTRIBUTION_TAIL_SUPPORT_BASIS,
            "tail_support_scope": RISK_CONTRIBUTION_TAIL_SUPPORT_SCOPE,
        },
    )
    # `effective_n` is replaced per entry, never silently: the block-level
    # `autocorrelation.effective_n` stays the WINDOW figure, and each entry says
    # which population its own number describes.  Rounded with the engine's own
    # declared decimal count rather than a literal 4, so this entry and
    # `tail_support` below cannot drift apart from the window-side block that
    # publishes the same formula.
    for field, entry in (block.get("estimates") or {}).items():
        entry["effective_n"] = (
            round(tail_effective, AUTOCORRELATION_EFFECTIVE_N_DECIMALS)
            if tail_effective is not None else None
        )
        entry["effective_n_decimals"] = AUTOCORRELATION_EFFECTIVE_N_DECIMALS
        entry["effective_n_basis"] = RISK_CONTRIBUTION_TAIL_EFFECTIVE_N_BASIS
        entry["effective_n_uncapped"] = (
            round(tail_effective_raw, AUTOCORRELATION_EFFECTIVE_N_DECIMALS)
            if tail_effective_raw is not None
            else None
        )
        entry["effective_n_reason"] = tail_reason
        entry["support_observations"] = tail_count
        entry["support_scope"] = RISK_CONTRIBUTION_TAIL_SUPPORT_SCOPE
        entry["resampling_observations"] = entry.get("observations")
        entry["resampling_scope"] = (
            "the whole published portfolio return series: the statistic being "
            "resampled is the 5th percentile OF that series, so the resampling "
            "frame is the series, not its tail"
        )
    block["tail_support"] = {
        "scope": RISK_CONTRIBUTION_TAIL_SUPPORT_SCOPE,
        "basis": RISK_CONTRIBUTION_TAIL_SUPPORT_BASIS,
        "tail_observations": tail_count,
        "window_observations": int(series.size),
        "ar1": (
            round(tail_ar1, AUTOCORRELATION_AR1_DECIMALS)
            if tail_ar1 is not None else None
        ),
        "ar1_decimals": AUTOCORRELATION_AR1_DECIMALS,
        "ar1_basis": (
            "OLS slope of r_t on r_(t-1) over the TAIL sample, not the window"
        ),
        "effective_n": (
            round(tail_effective, AUTOCORRELATION_EFFECTIVE_N_DECIMALS)
            if tail_effective is not None else None
        ),
        "effective_n_decimals": AUTOCORRELATION_EFFECTIVE_N_DECIMALS,
        "effective_n_uncapped": (
            round(tail_effective_raw, AUTOCORRELATION_EFFECTIVE_N_DECIMALS)
            if tail_effective_raw is not None
            else None
        ),
        "effective_n_formula": "n * (1 - ar1) / (1 + ar1)",
        # THE SAME CONVENTION `autocorrelation_disclosure` publishes, adopted
        # rather than re-invented.  This block was rounding `ar1` to 6 decimals
        # and `effective_n` to 4 - the same two numbers - while publishing
        # NEITHER count, so one object carried the same formula at a declared
        # precision on the window side (`autocorrelation`, which does declare it)
        # and an undeclared one here.  A reader checking the formula against the
        # published digits had no way to know which rounding they were allowed.
        #
        # It also states the scope exclusion the engine's own docstring draws:
        # `autocorrelation_disclosure` takes the observations and derives `n`
        # itself, and this block's whole point is a TAIL `n` the caller supplies,
        # so the function cannot be called here.  What IS reusable without it is
        # the convention and the bound, and the bound is a function of PUBLISHED
        # inputs only - which is what makes it the right thing to adopt.
        #
        # The bound is measured against `effective_n_uncapped`, NOT against the
        # published `effective_n`, and that distinction is load-bearing: the cap
        # below is a separate declared step applied AFTER the formula, so when it
        # binds, the residual between a recomputation and `effective_n` is the
        # CAP rather than rounding, and a rounding bound does not cover it.
        "effective_n_reproducibility": _tail_support_reproducibility(
            tail_count, tail_ar1, tail_effective_raw
        ),
        "effective_n_convention": (
            "app/services/analytics_engine.py: autocorrelation_disclosure - the "
            "same declared decimal counts, the same formula, and the same "
            "recomputation bound. That function derives its own observation count "
            "and so cannot be called for a TAIL, which is why this block adopts "
            "its convention and not its implementation; the bound is a function "
            "of published inputs only and is therefore reusable unchanged"
        ),
        "effective_n_cap_applied": (
            None if tail_effective is None else
            bool(tail_effective < tail_effective_raw)
        ),
        "effective_n_cap_basis": (
            "the adjustment is applied and then bounded by the tail: an order "
            "statistic cannot be informed by more days than the tail contains, "
            "whatever the tail's own AR(1) says. The cap is a step AFTER the "
            "formula, so effective_n_reproducibility is measured against "
            "effective_n_uncapped - the figure the formula itself produces - and "
            "effective_n_cap_applied says whether the published effective_n is "
            "that figure or the tail count"
        ),
        "effective_n_bound": (
            "the adjustment is a redundancy correction, so it is applied and then "
            "bounded by the tail: an order statistic cannot be informed by more "
            "days than the tail contains, whatever the tail's own AR(1) says. A "
            "negative AR(1) inflates the raw figure above the tail, and the raw "
            "figure is published as effective_n_uncapped rather than dropped"
        ),
        "effective_n_reason": tail_reason,
        "window_effective_n": (
            (block.get("autocorrelation") or {}).get("effective_n")
        ),
        "window_effective_n_basis": (
            "the same adjustment applied to the WINDOW, published as the "
            "autocorrelation block above. It describes the resampling frame, "
            "not the support of either estimate"
        ),
    }
    return block


def _model_history_coverage(
    holding_context: Mapping[str, Any],
    full_history: Mapping[str, Any],
    *,
    model_sample: Mapping[str, Any],
) -> Dict[str, Any]:
    """`history_coverage` for a full-history model: model evidence + ancillary holdings.

    `truncated` is `False` and `effective_start` is `None` at the top level
    because neither describes this model; the holding window is reachable only
    under `holding_context`, where its own `covered_days`/`annualized` describe
    the holding tenure rather than the model sample.

    `model_sample` is REQUIRED and is the caller's own count of the rows its
    model consumed, with the population that count describes. It is required
    because this builder is called BEFORE any fit exists at its old call sites,
    which is exactly how it came to publish the input frame's row count under
    the name of the regression's sample: a builder handed no sample filled the
    gap from the one number it did have, and that number was the frame. A
    caller that cannot measure its own sample must say so - pass the frame with
    `MODEL_SAMPLE_FRAME_SCOPE` - rather than let the block imply a measurement
    nobody took.
    """
    return {
        "scope": HOLDING_CONTEXT_SCOPE,
        "calculation_basis": full_history.get("basis", FULL_HISTORY_BASIS),
        "full_history": dict(full_history),
        "holding_context": dict(holding_context),
        "holding_window_days": holding_context.get("covered_days"),
        "holding_window_days_scope": holding_context.get("covered_days_scope"),
        "per_ticker_count_units": dict(
            holding_context.get("per_ticker_count_units") or PRICE_FRAME_COUNT_UNITS
        ),
        # Model-scoped mirrors. The holding window never writes these.
        "annualized": bool(full_history.get("annualized")),
        "truncated": False,
        "covered_days": full_history.get("observation_count"),
        "covered_days_scope": "model_return_observations",
        # NOT `full_history.observation_count`. `covered_days` above is the
        # input frame and stays that; the model's own sample is handed in.
        "model_observation_count": model_sample.get("count"),
        "model_observation_count_scope": model_sample.get("scope"),
        "model_observation_count_status": model_sample.get("status"),
        "model_observation_count_status_reason": model_sample.get("status_reason"),
        "model_observation_count_note": model_sample.get("note"),
        "model_window": full_history.get("window"),
        "effective_start": None,
        "intersection_start": holding_context.get("intersection_start"),
        "oldest_holding": holding_context.get("oldest_holding"),
        "requested_start": holding_context.get("requested_start"),
        "requested_end": holding_context.get("requested_end"),
        "tickers": holding_context.get("tickers", {}),
    }


def _factor_fit_sample(
    factor_result: Mapping[str, Any],
    full_history: Mapping[str, Any],
) -> Dict[str, Any]:
    """The portfolio regression's own sample, or a stated upper bound.

    `portfolio.observations` is `len(port_active)` from the fit itself - the
    published portfolio return series intersected with the benchmark - so it is
    the same sample that produced `r_squared`, `adjusted_r_squared` and the
    portfolio block's own coefficients. Reading it back here is what lets the
    count be the FIT's rather than the frame's.

    The engine publishes `observations: 0` on every not-fitted path (no
    benchmark window, fewer than ten active dates, or a failed regression), so
    zero and absent are both "no sample was measured". In that case the block
    degrades to the input frame's row count under a scope that says it is an
    upper bound - a stated ceiling, never a wrong sample.
    """
    portfolio = factor_result.get("portfolio")
    observations = portfolio.get("observations") if isinstance(portfolio, Mapping) else None
    fitted = (
        isinstance(observations, (int, float))
        and not isinstance(observations, bool)
        and float(observations) > 0.0
    )
    if fitted:
        return {
            "count": int(observations),
            "scope": MODEL_SAMPLE_FITTED_SCOPE,
            "status": "fitted",
            "status_reason": None,
            "note": MODEL_SAMPLE_FITTED_NOTE,
        }
    return {
        "count": full_history.get("observation_count"),
        "scope": MODEL_SAMPLE_FRAME_SCOPE,
        "status": "regression_sample_unavailable",
        "status_reason": (
            "The portfolio regression published no usable sample of its own "
            f"(portfolio.observations = {observations!r}), so the count below is "
            "the input return frame it was handed, which is an upper bound on the "
            "sample used and reads high whenever a leg is late-listed or the book "
            "is refused for partial coverage. See `data_status` and `error`."
        ),
        "note": MODEL_SAMPLE_FRAME_NOTE,
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

#: XS-001: `holding_window_observation_count` counts whatever frame it is
#: handed, so the same helper produces two different populations under one
#: scope name. The 12 sections that pass a whole-book PORTFOLIO series get 20 on
#: the audited book - only rows where every held leg had a return. The sections
#: that pass the wide per-leg return frame get 39, because that frame
#: deliberately RETAINS dates on which some leg was unpriced (its documented
#: contract: per-leg truth, NaN-masked dates kept, never narrowed to match the
#: portfolio series - see `PORTFOLIO_RETURN_MIN_COVERAGE`).
#:
#: Those are different populations, not a disagreement, so they must not share a
#: scope name. Renaming the minority is the honest fix: the counts are both
#: correct, and the alternative - narrowing the wide frame to 20 to make the
#: numbers agree - would destroy the per-leg truth the frame exists to carry.
HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE = (
    "holding_window_wide_return_rows_partial_dates_retained"
)

#: XS-001: a MEASURED window is a sub-window of the holding window, not the
#: holding window. It starts at the first date every held position had a
#: measurable return, which on a sparse book is later than the holding-window
#: start, and it counts only the whole-book complete rows inside it. Labelling
#: it with the holding-window scope made the audit rule read its start as the
#: holding-window start and compare 22 legitimately-later against 13 blocks that
#: were right. The block keeps `holding_window_start`, the day gap and
#: `measured_start_basis`, so the difference stays reconciled and visible.
MEASURED_WINDOW_COVERED_DAYS_SCOPE = (
    "holding_window_whole_book_complete_return_rows"
)

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


# --- Per-ticker observation counts: one key, one unit ------------------------
# `raw_days` / `masked_days` / `return_observations` are the names every section
# publishes per ticker, and the v4 export let three of them answer in three
# different units. Two rows from the same portfolio read:
#
#   regime            raw_days 746  masked_days 39  return_observations 38
#   risk_contribution raw_days 248  masked_days 38  return_observations 246
#
# The first two are PRICE rows (the regime frame is a price frame) and the third
# is a RETURN-row count, so `return_observations != raw_days - masked_days` for
# every ticker in the export - and a reader who assumed the identity was reading a
# nonsense number. Worse, `risk_contribution` measured its third count off a
# RETURNS frame, so it published the number of returns OF returns (246 where the
# frame holds 248 aligned return rows). The units are therefore declared per
# section, and the count that closes is published beside the one that does not.
PRICE_FRAME_COUNT_UNITS = {
    "raw_days": "delivered_price_rows_before_the_holding_window_mask",
    "masked_days": "delivered_price_rows_after_the_holding_window_mask",
    "return_observations": "aligned_return_rows_produced_by_those_price_rows",
    "counts_identity": (
        "raw_days - masked_days = the price rows the holding window removed. "
        "return_observations is measured in RETURN rows, not price rows, so it is "
        "NOT raw_days - masked_days: a return needs two held prices, and the bar "
        "on the start date is the first held price and produces none. A gapless "
        "leg therefore has return_observations == raw_days - 1, while the "
        "block's covered_days counts the PORTFOLIO series inside the same window. "
        "No per-ticker holding-window return count is published here: these "
        "sections publish the held price rows instead."
    ),
}

RETURN_FRAME_COUNT_UNITS = {
    "raw_days": "aligned_return_rows_in_the_delivered_model_frame",
    "masked_days": "aligned_return_rows_inside_the_canonical_holding_window",
    "return_observations": "aligned_return_rows_in_the_delivered_model_frame",
    "counts_identity": (
        "This section measures a RETURN frame, so raw_days and return_observations "
        "are the same population in the same unit. masked_days and "
        "holding_window_return_observations are that population cut to the "
        "canonical holding window, so raw_days - masked_days = the aligned return "
        "rows OUTSIDE the window. The block's covered_days counts the WIDE "
        "per-leg frame inside the window - the same population covered_days_scope "
        "declares - and is not a sum of the per-ticker rows: a leg that is "
        "unpriced on a date still contributes that date to covered_days, so "
        "covered_days can exceed the whole-book complete return rows the "
        "covariance and tail models consumed."
    ),
    "holding_window_return_observations": (
        "aligned_return_rows_inside_the_canonical_holding_window"
    ),
}


#: Scope label for the per-ticker price-row -> aligned-return-row reconciliation.
#: The two published counts are measured over DIFFERENT frames (held price rows vs
#: the portfolio-aligned return rows those prices produced), so the block states
#: the identity that relates them and publishes every term of it, measured.
PRICE_ROW_RECONCILIATION_SCOPE = "held_price_rows_to_aligned_return_rows"

PRICE_ROW_RECONCILIATION_IDENTITY = (
    "held_price_rows - first_held_price_yields_no_return - interior_price_gaps "
    "= own_return_observations, and own_return_observations - "
    "portfolio_alignment_dropped_rows = aligned_return_observations (the block's "
    "per-ticker return_observations). Every term is measured, never imputed: a leg "
    "with no interior gap and no alignment drop therefore reads held_price_rows = "
    "return_observations + 1 exactly, and a wider gap is a real missing-bar or "
    "portfolio-alignment loss rather than a different counting unit."
)


def _price_frame_count_reconciliation(
    per_ticker: Optional[Mapping[str, Mapping[str, Any]]],
    own_return_observations: Optional[Mapping[str, int]] = None,
) -> Dict[str, Any]:
    """The terms that close `masked_days` against `return_observations`.

    `masked_days` counts the ticker's HELD PRICE rows and `return_observations`
    counts the ALIGNED return rows those prices produced, so the two differ by a
    knowable amount:

    * the bar on the holding-window start date is the first held price and has no
      held predecessor, so it yields no return (0 or 1 rows);
    * an interior missing bar splits the held prices into runs and a return
      cannot cross a gap (`interior_price_gaps`);
    * rows the PORTFOLIO aggregate dropped are not attributable to this ticker at
      all (`portfolio_alignment_dropped_rows`).

    `own_return_observations` is the ticker's own-frame return count
    (`_own_return_observations`, which differences that ticker's held prices).
    A caller that supplies none falls back to the block's aligned count, which
    makes `interior_price_gaps` an UPPER bound on the missing bars; every caller
    of this helper passes its own counts, so that path is only a guard. A count
    that cannot be read at all leaves the ticker out rather than publishing a
    zero for it.
    """
    own_counts = own_return_observations or {}
    tickers: Dict[str, Any] = {}
    for ticker in sorted(per_ticker or {}):
        row = per_ticker.get(ticker)
        if not isinstance(row, Mapping):
            continue
        held = row.get("masked_days")
        aligned = row.get("return_observations")
        own = own_counts.get(ticker, aligned)
        try:
            held_rows = int(held)
            aligned_rows = int(aligned)
            own_rows = int(own)
        except (TypeError, ValueError):
            continue
        first_row = 1 if held_rows > 0 else 0
        interior = held_rows - first_row - own_rows
        dropped = own_rows - aligned_rows
        tickers[ticker] = {
            "held_price_rows": held_rows,
            "own_return_observations": own_rows,
            "aligned_return_observations": aligned_rows,
            "first_held_price_yields_no_return": first_row,
            "interior_price_gaps": interior,
            "portfolio_alignment_dropped_rows": dropped,
            "reconciles": bool(
                interior >= 0
                and dropped >= 0
                and held_rows - first_row - interior == own_rows
                and own_rows - dropped == aligned_rows
            ),
        }
    return {
        "scope": PRICE_ROW_RECONCILIATION_SCOPE,
        "identity": PRICE_ROW_RECONCILIATION_IDENTITY,
        "tickers": tickers,
    }


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
    per_ticker_count_units: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """The one holding-window payload every one of these sections publishes.

    `holding_coverage` (app/utils/holdings.py) does the work - starts,
    provenance, truncation, annualization. This adds the two fields that used
    to be decided per section: the unit the count is measured in, and the
    evidence window the starts were resolved against. So every published start
    arrives with the source that produced it, every count with its unit, and a
    section that resolved its starts without price evidence publishes the
    reason beside them instead of quietly disagreeing with the others.

    `per_ticker_count_units` declares the unit of each PER-TICKER count, because
    the block count is unified but the per-ticker keys are still three different
    questions: how many prices arrived, how many survived the holding mask, and
    how many returns those prices produced. A section that measures a return
    frame passes its own declaration, because the same key name legitimately means
    a different thing there.
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
    payload["per_ticker_count_units"] = dict(
        per_ticker_count_units or PRICE_FRAME_COUNT_UNITS
    )
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

#: Why the delivered series can start later than the holding window. The
#: holding mask is a DATE cut; a portfolio VALUE additionally needs a price on
#: every leg, so the first measurable date is the first holding-window session on
#: which the whole book was quoted. Sessions between the two that lack any leg
#: are refused, not renormalised, and the legs responsible are named beside this
#: sentence - an unexplained "the requested start was not delivered" reads as
#: missing data and sends a reader looking for a vendor problem that is not there.
PERFORMANCE_MEASURED_START_BASIS = (
    "first date on which every priced position had a price, so a whole-book "
    "portfolio value existed; earlier holding-window sessions had at least one "
    "leg without a price and were refused rather than renormalised into a "
    "partial-basket portfolio return"
)


def _refused_coverage_legs(
    price_df: pd.DataFrame,
    complete: pd.Series,
) -> List[Dict[str, Any]]:
    """Which legs, and how many holding-window sessions, each blocked a value.

    `complete` marks the dates on which `sum(min_count=len(legs))` produced a
    whole-book value. Every other date in the masked frame is a refused session,
    and a leg is named here only if it was actually missing a price on one of
    them - so the count is the cause of the late start, measured, not a guess
    about which position is illiquid. A leg quoted on every refused session
    cannot be the reason and is omitted.
    """
    if price_df is None or price_df.empty:
        return []
    refused = [stamp for stamp in price_df.index if not bool(complete.get(stamp, False))]
    if not refused:
        return []
    legs: List[Dict[str, Any]] = []
    for ticker in sorted(price_df.columns):
        column = price_df[ticker]
        missing = [stamp for stamp in refused if bool(pd.isna(column.get(stamp)))]
        if not missing:
            continue
        legs.append({
            "ticker": ticker,
            "refused_price_rows": len(missing),
            "held_price_rows": int(column.notna().sum()),
            "first_refused_date": _observation_date(missing[0]),
            "last_refused_date": _observation_date(missing[-1]),
        })
    legs.sort(key=lambda entry: (-entry["refused_price_rows"], entry["ticker"]))
    return legs


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


def _holding_start_gap_sentence(
    holding_block: Optional[Mapping[str, Any]],
    delivered_start: Optional[str],
) -> str:
    """The MEASURED reason a delivered start sits after the holding-window start.

    "The requested start was not delivered" states the gap and stops, so a reader
    infers missing data. On this book the data is present and the real cause is a
    refusal: a portfolio value needs a price on every leg, and the sessions
    between the holding-window start and the first whole-book quote were dropped
    rather than renormalised. The sentence names the window start, the number of
    refused sessions and the legs responsible, every term of which is also a
    number on `history_coverage.holding_window` — so it is checkable, not prose.
    Empty when no holding window was resolved: an unmeasured reason is never
    invented, and the gap sentence stands alone.
    """
    if not isinstance(holding_block, Mapping):
        return ""
    window_start = holding_block.get("intersection_start")
    if not isinstance(window_start, str) or not window_start:
        return ""
    gap_days = holding_block.get("holding_window_to_measured_start_gap_days")
    measured = holding_block.get("measured_start_basis")
    if not _declared(measured):
        return ""
    refused = holding_block.get("refused_partial_coverage_price_rows")
    legs = holding_block.get("refused_coverage_legs")
    parts = [
        f" The holding window starts {window_start}"
        + (f" ({gap_days} calendar days before the delivered start)" if _declared(gap_days) else "")
        + ", and the basis for measuring from a later date is: "
        + f"{measured}."
    ]
    if _declared(refused):
        parts.append(
            f" {int(refused)} holding-window session(s) were refused for partial coverage."
        )
    if isinstance(legs, list) and legs:
        named = ", ".join(
            f"{entry.get('ticker')} ({entry.get('refused_price_rows')} session(s) without a price)"
            for entry in legs
            if isinstance(entry, Mapping)
        )
        if named:
            parts.append(f" Legs missing a price on a refused session: {named}.")
    return "".join(parts)


def _declared(value: Any) -> bool:
    """A real measured value, not a `None`/blank placeholder."""
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def _performance_history_envelope(
    series: Any,
    *,
    requested_start: Any,
    requested_end: Any,
    warnings: Optional[Iterable[str]] = None,
    coverage_extra: Optional[Mapping[str, Any]] = None,
    holding_window: Optional[Mapping[str, Any]] = None,
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

    ``coverage_extra`` carries the caller's constituent-count disclosure. A
    portfolio value is only emitted on dates where every priced position has a
    price, so a partial basket is refused rather than renormalised — but a
    shortened series is indistinguishable from a thin one unless the refusal is
    counted and published.

    ``holding_window`` carries the holding-window declaration for the delivered
    series: the canonical window start with its provenance, the count in the
    sibling sections' unit, and the measured reason the delivered start can sit
    after the window start. It travels as ONE sub-mapping rather than being
    flattened into the coverage block, because ``history_coverage`` mixes two
    populations - the REQUESTED window (freshness) and the holding window
    (realized truth) - and a consumer that cannot tell them apart reads the
    requested start as a holding date. Without it the only sentence explaining
    a late start is "the requested start was not delivered", which reads as
    missing data rather than as the refusal it is. Always present, ``None``
    when no holding window was resolved, so the key set never depends on the
    call path.
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
    # The breadth keys are ALWAYS present, defaulted to None, rather than merged
    # only when the caller supplies them. A conditional merge made the envelope's
    # key set depend on the call path, which breaks the determinism guarantee
    # above: the same rows and window must always produce the same shape.
    coverage_extra = coverage_extra if isinstance(coverage_extra, Mapping) else {}
    for key in (
        "constituent_count",
        "constituent_count_basis",
        "partial_basket_policy",
        "measurable_price_rows",
        "complete_coverage_price_rows",
        "refused_partial_coverage_price_rows",
    ):
        history[key] = coverage_extra.get(key)
    # The holding-window declaration, or None. Published beside the freshness
    # axes rather than inside them, and defaulted like the breadth keys above so
    # the shape stays a function of the call, not of the data.
    holding_block = holding_window if isinstance(holding_window, Mapping) else None
    history["holding_window"] = holding_block

    messages: List[str] = [str(item) for item in (warnings or []) if item]
    if not observation_count:
        messages.append("No performance history was delivered for the requested window.")
    else:
        if truncated and delivered_start and isinstance(requested_start, str):
            late = _calendar_day_gap(delivered_start, requested_start)
            gap = _holding_start_gap_sentence(holding_block, delivered_start)
            messages.append(
                f"Delivered history starts {delivered_start}, {late} calendar days after "
                f"the requested {requested_start}; the requested start was not delivered."
                + gap
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
        # Breadth sits BESIDE the series, not only inside history_coverage,
        # because it describes the series rather than the window: it is the
        # answer to "how many positions was this number computed from?". A
        # reader of `data` alone must be able to tell a full-basket day from a
        # partial-basket day, and a count buried one level down is not beside
        # the thing it qualifies. Mirrored into history_coverage as well, so a
        # consumer reading only the coverage block still sees it.
        "constituent_count": (coverage_extra or {}).get("constituent_count"),
        "constituent_count_basis": (coverage_extra or {}).get("constituent_count_basis"),
        "partial_basket_policy": (coverage_extra or {}).get("partial_basket_policy"),
        "refused_partial_coverage_rows": (coverage_extra or {}).get(
            "refused_partial_coverage_price_rows"
        ),
    }


# --- Liquidity units, window and scoring disclosure (V3-09) ------------------
# The liquidity score is a dimensionless 0-10 index whose INPUTS are monetary,
# and the engine's tiers are fixed INR magnitudes. So the unit the score is
# expressed in is a property of the rule, not of a quote, and it is published as
# `derived` - never read off a market-cap payload and never invented per ticker.
LIQUIDITY_SCORING_CURRENCY = "INR"
LIQUIDITY_SCORE_PRECISION = 1
LIQUIDITY_SCORE_SCALE = {"min": 2.5, "max": 10.0, "unit": "index_0_to_10"}

# --- Liquidity: what the section-level band and the volume means aggregate ----
# `liquidation_time_days` is `_liquidity_band(overall_score)` and `overall_score`
# is the MEAN of the per-position published scores. So the section value is the
# band of a mean, while the per-leg `liquidation_days` values beside it are a
# distribution - on the live book the section reads "1-2" over legs distributed
# {1-2: 10, 2-5: 3, 5-10: 1}. Nothing in the export said which, so the two could
# not be reconciled by a reader. The rule is stated instead of the value being
# changed: the value is the engine's, and the aggregation is what it always was.
LIQUIDATION_TIME_AGGREGATION = (
    "band_of_the_mean_published_overall_score. The section's liquidation window "
    "is the band that the MEAN of the per-position published scores falls into "
    "(mean -> round to 1 decimal -> scoring.bands, the same mapping published "
    "under scoring.thresholds). It is NOT a worst case over the legs, NOT a "
    "median, and NOT the most common leg band: by_position.*.liquidation_days is "
    "the full per-leg distribution and is EXPECTED to disagree with this value, "
    "because band-of-a-mean is not a band of the legs."
)
LIQUIDITY_BANDS_ALIAS_OF = "bands"
LIQUIDITY_BANDS_ALIAS_NOTE = (
    "scoring.thresholds is the SAME mapping as scoring.bands, republished under "
    "its older name because a consumer reads it. It is one band table with one "
    "meaning, not a second rule: the two keys are the same object and the rule "
    "that banded any published score is `bands`."
)

# `avg_volume` is `np.mean` over the per-leg mean volumes, and the legs are means
# over UNEQUAL row counts - 20, 21 or 22 rows on the live book - so the section
# figure weights a 20-row leg exactly as heavily as a 22-row leg. It is not a
# weighted mean, not a median, and not a portfolio volume. The numbers stay as
# they are: `total_portfolio_volume` on the same block is the SUM of those same
# per-leg means, so changing one without the other would leave the block
# internally inconsistent. Both bases are stated here instead.
LIQUIDITY_AVG_VOLUME_BASIS = (
    "unweighted_mean_of_the_per_leg_mean_volumes: every measured position "
    "contributes its own mean daily volume with equal weight, REGARDLESS of how "
    "many rows that leg's mean was taken over. It is not a row-weighted mean, "
    "not a median, and not a portfolio volume. The per-leg row counts are "
    "published in avg_volume_leg_observations and each leg's own mean in "
    "by_position.*.avg_volume, so the inequality between the legs is visible "
    "rather than asserted."
)
LIQUIDITY_TOTAL_VOLUME_BASIS = (
    "sum_of_the_same_per_leg_mean_volumes. It is the cross-sectional SUM of the "
    "per-position mean daily volumes, so it is neither the book's own average "
    "daily volume over a common window nor a market-value-weighted quantity: it "
    "is not weighted by position size, and each term is itself a mean over that "
    "leg's own (unequal) row count. It carries the same weighting limitation as "
    "avg_volume, in the opposite direction."
)


# --- Liquidity: what `spread` and a capped `score_raw` actually are ---------
# `spread` sat in the payload as a bare number next to `score`/`score_raw`, and
# the obvious reading - |score - score_raw| - is wrong by two orders of magnitude
# (CIPLA: 0.040271 vs a published spread of 0.0004). It is an ASSUMED bid-ask
# spread derived from the position's average daily turnover by the tier formula
# the score itself uses: nothing is read from a quote or measured intraday. The
# formulas are restated here and RE-DERIVED from `avg_turnover`, so the
# declaration is a reproduction of the published value, not a paraphrase: a leg
# whose published spread the formulas do not reproduce publishes
# `spread_formula_confirmed: false` rather than inheriting a claim.
LIQUIDITY_SPREAD_UNIT = "fraction_of_price"
LIQUIDITY_SPREAD_DEFINITION = "assumed_bid_ask_spread_from_turnover_tier_formula"
LIQUIDITY_SPREAD_NOTE = (
    "by_position.*.spread is NOT abs(score - score_raw). It is an ASSUMED "
    "bid-ask spread as a fraction of price, computed from the position's average "
    "daily turnover (avg_volume * last close of the window) by the tier formula "
    "below. It is not read from a quote, not measured from intraday data and not "
    "derived from the score, and it is rounded to 4 decimals."
)

#: (id, turnover tier predicate, score formula, spread formula, plateau) mirroring
#: the engine's tier ladder. `plateau` is the avg_turnover above which the
#: formula's own clamp binds and stops responding to turnover.
LIQUIDITY_TIER_LADDER: Tuple[Dict[str, Any], ...] = (
    {
        "id": "tier_1",
        "applies_when": "avg_turnover >= 5e8 or market_cap >= 5e11",
        "score_raw": "min(10.0, 9.0 + min(1.0, (avg_turnover / 1e9) * 0.2))",
        "spread": "max(0.0002, 0.0006 - min(0.0003, (avg_turnover / 2e9) * 0.0003))",
        "score_plateau_turnover": 5e9,
        "spread_plateau_turnover": 2e9,
    },
    {
        "id": "tier_2",
        "applies_when": "avg_turnover >= 1e8 or market_cap >= 1e11",
        "score_raw": "min(8.9, 7.8 + (avg_turnover / 5e8) * 1.1)",
        "spread": "max(0.0006, 0.0014 - (avg_turnover / 5e8) * 0.0006)",
        "score_plateau_turnover": None,
        "spread_plateau_turnover": None,
    },
    {
        "id": "tier_3",
        "applies_when": "avg_turnover >= 2e7 or market_cap >= 1e10",
        "score_raw": "min(7.7, 6.2 + (avg_turnover / 1e8) * 0.15)",
        "spread": "max(0.0012, 0.0028 - (avg_turnover / 1e8) * 0.0012)",
        "score_plateau_turnover": None,
        "spread_plateau_turnover": None,
    },
    {
        "id": "tier_4",
        "applies_when": "otherwise (avg_turnover < 2e7 and market_cap < 1e10)",
        "score_raw": "max(2.5, min(5.9, 3.0 + (avg_turnover / 2e7) * 2.9))",
        "spread": "max(0.0025, 0.0060 - (avg_turnover / 2e7) * 0.0030)",
        "score_plateau_turnover": None,
        "spread_plateau_turnover": None,
    },
)


def _liquidity_tier_values(turnover: float) -> List[Tuple[str, float, float]]:
    """(tier_id, score_raw, spread) this turnover produces under every tier.

    Every tier is evaluated and the ones that reproduce the published values are
    the evidence, so a leg whose tier cannot be identified publishes `null`
    instead of the first tier that happens to fit.
    """
    rows: List[Tuple[str, float, float]] = []
    if turnover >= 500_000_000.0:
        rows.append((
            "tier_1",
            round(min(10.0, 9.0 + min(1.0, (turnover / 1e9) * 0.2)), 6),
            round(max(0.0002, 0.0006 - min(0.0003, (turnover / 2e9) * 0.0003)), 4),
        ))
    if turnover >= 100_000_000.0:
        rows.append((
            "tier_2",
            round(min(8.9, 7.8 + (turnover / 5e8) * 1.1), 6),
            round(max(0.0006, 0.0014 - (turnover / 5e8) * 0.0006), 4),
        ))
    if turnover >= 20_000_000.0:
        rows.append((
            "tier_3",
            round(min(7.7, 6.2 + (turnover / 1e8) * 0.15), 6),
            round(max(0.0012, 0.0028 - (turnover / 1e8) * 0.0012), 4),
        ))
    rows.append((
        "tier_4",
        round(max(2.5, min(5.9, 3.0 + (turnover / 2e7) * 2.9)), 6),
        round(max(0.0025, 0.0060 - (turnover / 2e7) * 0.0030), 4),
    ))
    return rows


def _liquidity_score_spread_disclosure(
    positions: Mapping[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Section-level spread/cap declaration plus the per-position evidence.

    Returns `(block, per_position)` so the route can stamp the per-position facts
    onto the rows they describe without a second pass over the engine result.
    """
    scale_max = LIQUIDITY_SCORE_SCALE["max"]
    block: Dict[str, Any] = {
        "field": "by_position.*.spread",
        "unit": LIQUIDITY_SPREAD_UNIT,
        "definition": LIQUIDITY_SPREAD_DEFINITION,
        "provenance": "model_assumed",
        "observed": False,
        "note": LIQUIDITY_SPREAD_NOTE,
        "published_decimals": 4,
        "tier_ladder": [dict(tier) for tier in LIQUIDITY_TIER_LADDER],
    }
    per_position: Dict[str, Dict[str, Any]] = {}
    confirmed: List[str] = []
    unconfirmed: List[str] = []
    capped: List[str] = []
    spread_plateau: List[str] = []
    for ticker, entry in sorted((positions or {}).items()):
        if not isinstance(entry, Mapping):
            continue
        try:
            turnover = float(entry.get("avg_turnover"))
        except (TypeError, ValueError):
            turnover = None
        published_score = entry.get("score_raw")
        published_spread = entry.get("spread")
        try:
            published_spread = float(published_spread)
        except (TypeError, ValueError):
            published_spread = None
        facts: Dict[str, Any] = {"spread_basis": LIQUIDITY_SPREAD_DEFINITION}
        tier_id = None
        recomputed_spread = None
        if turnover is not None and math.isfinite(turnover):
            ladder = _liquidity_tier_values(turnover)
            recomputed_spread = ladder[0][2]
            try:
                published_score = float(published_score)
            except (TypeError, ValueError):
                published_score = None
            if published_score is not None:
                matching = [row for row in ladder if row[1] == published_score]
                if len(matching) == 1:
                    tier_id = matching[0][0]
            spread_matches = (
                published_spread is not None
                and any(row[2] == published_spread for row in ladder)
            )
            facts["spread_tier"] = tier_id
            facts["spread_recomputed"] = recomputed_spread
            facts["spread_formula_confirmed"] = bool(spread_matches)
            facts["spread_tier_plateau_turnover"] = next(
                (
                    tier["spread_plateau_turnover"]
                    for tier in LIQUIDITY_TIER_LADDER
                    if tier["id"] == tier_id
                ),
                None,
            )
            facts["spread_at_tier_plateau"] = bool(
                tier_id
                and any(
                    tier["id"] == tier_id
                    and tier["spread_plateau_turnover"] is not None
                    and turnover >= float(tier["spread_plateau_turnover"])
                    for tier in LIQUIDITY_TIER_LADDER
                )
            )
        else:
            facts["spread_tier"] = None
            facts["spread_recomputed"] = None
            facts["spread_formula_confirmed"] = False
            facts["spread_tier_plateau_turnover"] = None
            facts["spread_at_tier_plateau"] = False
        if facts["spread_formula_confirmed"]:
            confirmed.append(str(ticker))
        else:
            unconfirmed.append(str(ticker))
        facts["score_ceiling_applied"] = bool(
            published_score is not None
            and math.isfinite(published_score)
            and published_score >= float(scale_max)
        )
        if facts["score_ceiling_applied"]:
            capped.append(str(ticker))
        if facts["spread_at_tier_plateau"]:
            spread_plateau.append(str(ticker))
        per_position[str(ticker)] = facts
    block["recomputed_from_avg_turnover"] = {
        "confirmed_count": len(confirmed),
        "unconfirmed_count": len(unconfirmed),
        "confirmed_tickers": confirmed,
        "unconfirmed_tickers": unconfirmed,
    }
    block["score_ceiling"] = {
        "scale_max": scale_max,
        "rule": (
            "tier_1's score formula is min(10.0, 9.0 + min(1.0, "
            "(avg_turnover / 1e9) * 0.2)), so score_raw stops responding to "
            "turnover at avg_turnover >= 5e9. A score_raw equal to the scale "
            "maximum is a CAPPED value, not a measurement of exactly 10.0."
        ),
        "positions_at_ceiling": capped,
        "positions_at_ceiling_count": len(capped),
    }
    block["spread_at_tier_plateau"] = {
        "positions": spread_plateau,
        "positions_count": len(spread_plateau),
        "note": (
            "At or above the tier's plateau turnover the spread formula's own "
            "clamp binds, so the published spread is the tier's floor and does "
            "not respond to further turnover."
        ),
    }
    return block, per_position


def _liquidity_volume_band_residual(
    volume_stats: Mapping[str, Any],
    *,
    positions: Mapping[str, Any],
) -> Dict[str, Any]:
    """Publish what the band percentages leave over, instead of renormalizing.

    `high/medium/low_volume_pct` are each one position count over the measured
    population, rounded to one decimal, so they sum to 99.9 or 100.1 rather than
    100. The residual and the population they were taken over are published
    beside them; nothing is redistributed to make the column close.
    """
    keys = ("high_volume_pct", "medium_volume_pct", "low_volume_pct")
    values: List[float] = []
    for key in keys:
        try:
            values.append(float(volume_stats.get(key)))
        except (TypeError, ValueError):
            continue
    if len(values) != len(keys):
        return {
            "volume_band_pct_total": None,
            "volume_band_rounding_residual": None,
            "volume_band_rounding_decimals": 1,
            "volume_band_basis": (
                "Share of measured positions in each published-score band. The "
                "residual is unavailable because the band column this export "
                "received is incomplete."
            ),
        }
    total = round(sum(values), 10)
    counts = {"High": 0, "Medium": 0, "Low": 0}
    for entry in (positions or {}).values():
        category = entry.get("category") if isinstance(entry, Mapping) else None
        if category in counts:
            counts[category] += 1
    return {
        "volume_band_pct_total": total,
        "volume_band_rounding_residual": round(100.0 - total, 10),
        "volume_band_rounding_decimals": 1,
        "volume_band_measured_positions": sum(counts.values()),
        "volume_band_position_counts": counts,
        "volume_band_basis": (
            "Each band percentage is (positions in that published-score band / "
            "measured positions) * 100, rounded to 1 decimal, so the column sums "
            "to 100 only up to that rounding. The band is the published score's "
            "band (see scoring.bands), never the raw score's."
        ),
    }


def _liquidity_volume_mean_basis(
    observation_window: Mapping[str, Any],
    *,
    positions: Mapping[str, Any],
) -> Dict[str, Any]:
    """Say what `avg_volume` averages, and publish the inequality it averages over.

    The section figure is an unweighted mean of the per-leg means, and the legs
    are means over unequal row counts, so the claim "unweighted mean of the
    per-leg means" is a claim a reader cannot check from the block alone. The
    per-leg row counts are therefore published with it, read from the delivered
    observation window this same response already carries - not recomputed from
    the frames - so the disclosure cannot drift from the window it describes.
    Nothing is reweighted and no mean is recomputed here.
    """
    per_ticker = (observation_window or {}).get("per_ticker")
    per_ticker = per_ticker if isinstance(per_ticker, Mapping) else {}
    leg_observations: Dict[str, int] = {}
    for ticker in (positions or {}):
        entry = per_ticker.get(ticker)
        entry = entry if isinstance(entry, Mapping) else {}
        try:
            count = int(entry.get("observations"))
        except (TypeError, ValueError):
            continue
        leg_observations[str(ticker)] = count
    counts = sorted(leg_observations.values())
    return {
        "avg_volume_basis": LIQUIDITY_AVG_VOLUME_BASIS,
        "avg_volume_leg_observations": leg_observations,
        "avg_volume_leg_observation_total": sum(counts) if counts else None,
        "avg_volume_leg_observation_min": counts[0] if counts else None,
        "avg_volume_leg_observation_max": counts[-1] if counts else None,
        "total_portfolio_volume_basis": LIQUIDITY_TOTAL_VOLUME_BASIS,
    }


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
        # The same object under its older name, kept because a consumer reads
        # it. One band table, not two: the alias says which key is canonical so
        # publishing it twice cannot read as publishing two rules.
        "thresholds": (rule or {}).get("bands") if isinstance(rule, Mapping) else None,
        "thresholds_alias_of": LIQUIDITY_BANDS_ALIAS_OF,
        "thresholds_alias_note": LIQUIDITY_BANDS_ALIAS_NOTE,
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
        "measured_positions_basis": (
            "Positions with a measured price and volume over the observation "
            "window. This is NOT a market-cap measurement: the market-cap "
            "provenance of every leg is counted in `market_cap_provenance`."
        ),
        "market_cap_provenance": _liquidity_market_cap_provenance_counts(positions),
        "unavailable_reason": (
            liquidity_result.get("error")
            if liquidity_result.get("overall_score") is None
            else None
        ),
        "score_basis": "turnover_and_market_cap_tiers",
    }


def _liquidity_floor_value(scoring_block: Mapping[str, Any]) -> float:
    """The published INR market-cap floor, read back from the scoring block.

    Read from the block the response already carries rather than repeated as a
    second literal, so the warning cannot name a different floor than the one
    the score was banded against.
    """
    floor = scoring_block.get("market_cap_floor")
    value = floor.get("value") if isinstance(floor, Mapping) else None
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _liquidity_market_cap_provenance_counts(positions: Mapping[str, Any]) -> Dict[str, int]:
    """How many legs' market caps came from a quote, an estimate, or the floor.

    Counted from the engine's own per-position `market_cap_provenance`, never
    re-derived: `estimated` (annualised from measured turnover) and `fallback`
    (the fixed INR 1bn floor) are both substitutes for a measurement, and a
    score banded partly on either is not a clean measurement of the book.
    """
    counts: Dict[str, int] = {}
    for row in positions.values():
        if not isinstance(row, Mapping) or "market_cap_provenance" not in row:
            continue
        label = str(row.get("market_cap_provenance") or "unknown").strip() or "unknown"
        counts[label] = counts.get(label, 0) + 1
    return {label: counts[label] for label in sorted(counts)}


def _liquidity_market_cap_estimate_disclosure(
    positions: Mapping[str, Any],
) -> Dict[str, Any]:
    """Section-level count and names for the non-measured market caps (D-03).

    Every leg already published `market_cap_provenance`/`is_estimate`, and the
    scoring block already published the INR 1bn floor, so the information
    existed - but the section HEADLINE aggregated none of it: 5 of 14 legs were
    estimated or floored and the section still read `data_status: available`
    with zero warnings. A score resting partly on a hard-coded floor is a
    fallback presented as a measurement, the same fabrication class as the
    original single-ticker finding one level up.

    Returns the disclosure block, or an empty mapping when the engine published
    no provenance at all: an unlabelled result is not counted as clean, and it
    is not counted as estimated either.
    """
    rows = {
        ticker: row
        for ticker, row in positions.items()
        if isinstance(row, Mapping) and "market_cap_provenance" in row
    }
    if not rows:
        return {}
    non_measured = sorted(
        ticker
        for ticker, row in rows.items()
        if row.get("market_cap_provenance") != "measured"
    )
    by_provenance: Dict[str, List[str]] = {}
    for ticker in non_measured:
        label = str(rows[ticker].get("market_cap_provenance") or "unknown").strip() or "unknown"
        by_provenance.setdefault(label, []).append(ticker)
    floored = by_provenance.get("fallback") or []
    return {
        "estimated_market_cap_count": len(non_measured),
        "measured_market_cap_count": len(rows) - len(non_measured),
        "market_cap_count": len(rows),
        "non_measured_market_caps": non_measured,
        "non_measured_by_provenance": {
            label: by_provenance[label] for label in sorted(by_provenance)
        },
        "fallback_market_cap_count": len(floored),
        "estimated_market_cap_basis": (
            "A leg is counted here unless a quote supplied its market cap: "
            "`estimated` caps are annualised from measured daily turnover and "
            "`fallback` caps are the fixed INR 1bn floor published in "
            "scoring.market_cap_floor. Each leg keeps its own provenance in "
            "by_position; this block only counts them for the section headline."
        ),
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
        "portfolio_value_role": "exact_budget_every_trade_amount_was_struck_from",
    }


# --- Volatility sizing: what the trade list is actually priced off ----------
# Two portfolio values describe one budget, and two dates describe one trade
# list. The share deltas are struck from `sizing_price` (the last close INSIDE
# the sizing window), so that price's date - not the section `as_of` - is the
# freshness of the executable list: a book whose sizing prices are three
# sessions stale needs three sessions of drift absorbed before a delta is
# correct. Both numbers are published with the rounding that relates them and
# with the measured gap, so a reader can see which one moved.
SIZING_PRICE_FRESHNESS_RULE = (
    "sizing_price is the last close delivered inside the sizing window and is the "
    "only price every share_delta was divided by, so sizing_price_as_of - not the "
    "section as_of - is the freshness of the trade list. portfolio_value is the "
    "exact base-currency budget the notionals were struck from; the section-level "
    "portfolio_value is that same budget published at portfolio_value_decimals."
)


def _sizing_price_freshness(
    sizing_price_as_of: Optional[str],
    latest_observation_date: Optional[str],
) -> Dict[str, Any]:
    """How stale the sizing prices are against the newest delivered bar.

    Measured, never assumed: a `sizing_price_as_of` the delivered frame cannot
    date publishes `unavailable` instead of a fabricated gap.
    """
    gap = _calendar_day_gap(latest_observation_date, sizing_price_as_of)
    return {
        "sizing_price_as_of": sizing_price_as_of,
        "latest_delivered_observation": latest_observation_date,
        "sizing_price_calendar_days_behind": gap,
        "sizing_price_as_of_status": "measured" if gap is not None else "unavailable",
        "rule": SIZING_PRICE_FRESHNESS_RULE,
    }


def _sizing_price_vs_position_last_price(
    sizing_prices: Optional[Mapping[str, Any]],
    positions: Iterable[Any],
) -> Dict[str, Any]:
    """How far each trade's sizing price sits from the stored `last_price`.

    The share deltas are struck from `sizing_price` while the position row
    carries its own `last_price`, and those two are different observations of the
    same scrip. The gap is measured per leg and never reconciled away: it is the
    size of the drift a rebalance would absorb before a published delta is
    correct. A leg with no comparable `last_price` publishes `null`.
    """
    prices = sizing_prices if isinstance(sizing_prices, Mapping) else {}
    last_prices: Dict[str, float] = {}
    for position in positions or ():
        ticker = getattr(position, "ticker", None)
        if not isinstance(ticker, str):
            continue
        try:
            value = float(getattr(position, "last_price", None))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value > 0:
            last_prices[ticker] = value
    gaps: Dict[str, Optional[float]] = {}
    for ticker, price in sorted(prices.items()):
        try:
            sizing_price = float(price)
        except (TypeError, ValueError):
            gaps[str(ticker)] = None
            continue
        stored = last_prices.get(str(ticker))
        if stored is None or not math.isfinite(sizing_price) or sizing_price <= 0:
            gaps[str(ticker)] = None
            continue
        gaps[str(ticker)] = round((sizing_price - stored) / stored, 6)
    measured = {t: g for t, g in gaps.items() if g is not None}
    worst = max(measured, key=lambda t: abs(measured[t]), default=None)
    return {
        "rule": (
            "(sizing_price - position.last_price) / position.last_price, per leg; "
            "a positive value means the sizing price is the higher of the two."
        ),
        "compared_legs": len(measured),
        "unavailable_legs": sorted(t for t, g in gaps.items() if g is None),
        "max_abs_relative_gap": abs(measured[worst]) if worst is not None else None,
        "max_abs_relative_gap_ticker": worst,
        "per_ticker_relative_gap": gaps,
    }


# --- Volatility sizing: reconciliation aggregates (V4) ---------------------
# The engine's reconciliation block published `max_rounding_tolerance` from the
# MINIMUM per-trade tolerance. A book whose widest tolerance was 1631.300049
# (MCX.NS) therefore published 11.77 - the narrowest one, MIDCAPIETF.NS - and
# understated the very bound the block certifies by ~139x. Every trade IS inside
# its own tolerance, so no trade was wrong; only the published summary was. The
# aggregates are recomputed here from the delivered trades, and each declares the
# population it was taken over, because a residual and a tolerance bound are not
# the same measurement: one is the money a whole-share rule could not trade, the
# other is the widest half-share value any leg could have moved.
TRADE_AGGREGATE_SCOPE = "all_priced_trades_with_a_sizing_price"
TRADE_AGGREGATE_NOTE = (
    "Aggregates are recomputed from the delivered trades over "
    f"{TRADE_AGGREGATE_SCOPE}. The residual is money the whole-share rule could "
    "not trade; the tolerance is half the share price, i.e. the largest value one "
    "leg's rounding could move. A trade is inside tolerance when ITS OWN residual "
    "is within ITS OWN tolerance, so a single maximum does not certify a single "
    "maximum: the widest tolerance in the book is reported beside the widest "
    "residual, and tolerance_breach_tickers is the per-trade check itself."
)


def _trade_reconciliation_disclosure(
    reconciliation: Optional[Mapping[str, Any]],
    trades: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Publish the reconciliation summary with true maxima and declared scopes.

    Nothing is invented: the per-trade residual and tolerance are the ones the
    engine already published, the notional quantum is read back from the block,
    and a leg with no sizing price contributes to no aggregate (it has no
    whole-share instruction to reconcile).
    """
    if not isinstance(reconciliation, Mapping):
        return {}
    block = dict(reconciliation)
    quantum = reconciliation.get("amount_rounding_quantum")
    try:
        quantum = abs(float(quantum)) if quantum is not None else 0.0
    except (TypeError, ValueError):
        quantum = 0.0
    residuals: List[Tuple[str, float]] = []
    tolerances: List[Tuple[str, float]] = []
    breaches: List[str] = []
    for ticker, entry in (trades or {}).items():
        if not isinstance(entry, Mapping):
            continue
        try:
            tolerance = float(entry.get("rounding_tolerance"))
        except (TypeError, ValueError):
            continue
        tolerances.append((str(ticker), tolerance))
        raw_residual = entry.get("rounding_residual")
        try:
            residual = abs(float(raw_residual)) if raw_residual is not None else None
        except (TypeError, ValueError):
            residual = None
        if residual is None:
            continue
        residuals.append((str(ticker), residual))
        if residual - (tolerance + quantum) > 1e-9:
            breaches.append(str(ticker))
    residual_max = max(residuals, key=lambda item: item[1], default=None)
    tolerance_max = max(tolerances, key=lambda item: item[1], default=None)
    tolerance_min = min(tolerances, key=lambda item: item[1], default=None)
    decimals = reconciliation.get("amount_decimals")
    block.update({
        "max_abs_rounding_residual": (
            round(residual_max[1], int(decimals)) if residual_max and isinstance(decimals, int)
            else reconciliation.get("max_abs_rounding_residual")
        ),
        "max_abs_rounding_residual_scope": TRADE_AGGREGATE_SCOPE,
        "max_abs_rounding_residual_ticker": residual_max[0] if residual_max else None,
        # The maximum tolerance, not the minimum: the field certifies the widest
        # bound the book has to live inside, so it must be the widest one.
        "max_rounding_tolerance": (
            round(tolerance_max[1], 6) if tolerance_max else reconciliation.get("max_rounding_tolerance")
        ),
        "max_rounding_tolerance_scope": TRADE_AGGREGATE_SCOPE,
        "max_rounding_tolerance_ticker": tolerance_max[0] if tolerance_max else None,
        # The previously published value, named for what it always was.
        "min_rounding_tolerance": (
            round(tolerance_min[1], 6) if tolerance_min else None
        ),
        "min_rounding_tolerance_scope": TRADE_AGGREGATE_SCOPE,
        "tolerance_breach_tickers": sorted(breaches),
        "aggregates_source": "recomputed_from_delivered_trades",
        "aggregate_note": TRADE_AGGREGATE_NOTE,
    })
    return block


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


#: Per-trade ``status`` values that assert the record can be placed as an order.
#: Mirrors the audit rule that reconciles a record against its section's gate.
EXECUTABLE_TRADE_STATUSES = frozenset(
    {"executable", "execute", "ready", "actionable", "tradable", "tradeable"}
)

#: The status a record carries when the SECTION refuses the target. It is not one
#: of the executable literals above, so nothing in the export can read it as
#: permission, and the engine's own per-leg verdict is preserved beside it.
BLOCKED_BY_SECTION_GATE_STATUS = "blocked_by_section_execution_gate"

#: The rule is a TEMPLATE and its counts are formatted from the records that
#: were actually restated. It used to carry a literal "13", written from one
#: book, inside a sentence published into every export: on any other book the
#: section's own rule text stated a count its own payload contradicted, which is
#: the one thing a rule sentence must never do. `restated_count` can legitimately
#: be below the leg count, so the template also says why - the legs that were not
#: restated are the ones that never claimed executability in the first place.
TRADE_GATE_RECONCILIATION_RULE = (
    "A per-trade status is the ENGINE's verdict on that leg alone: whether the "
    "notional buys a whole share at the sizing price. It is not permission to "
    "trade, because the target as a whole is gated by execution.execution_eligible. "
    "Where that gate is false, every leg's executable status is restated as "
    f"{BLOCKED_BY_SECTION_GATE_STATUS!r} with the engine's own reading kept in "
    "leg_status, and the record carries the gate itself, so a consumer iterating "
    "trades[] cannot collect {restated_count} order instructions out of "
    "{total_count} legs from a target the section says is not a normal rebalance. "
    "The legs that were not restated are the ones that never claimed "
    "executability: below_minimum_notional, immaterial_no_op, no_trade_required "
    "and unavailable keep their own status, which is why the restated count can "
    "be below the leg count."
)


def _reconcile_trade_status_with_gate(
    trades: Any, execution: Optional[Mapping[str, Any]]
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """Restate per-trade executability against the section's own execution gate.

    The engine labels a leg `executable` from the leg's own arithmetic, with no
    access to what the shared normalization rule decided about the target those
    legs add up to. So a target that requires financing publishes a gate saying
    so at section level and an instruction set that never mentions it, and the
    instruction set is the thing a consumer iterating `trades[]` reads.

    Nothing is recomputed and nothing is dropped: the engine's verdict moves to
    `leg_status`, the section's gate moves onto the record, and `status` becomes
    the gated literal. A leg that was never executable (`below_minimum_notional`,
    `immaterial_no_op`, `no_trade_required`, `unavailable`) keeps its own status,
    which never claimed permission in the first place - the gate still rides
    along on it.
    """
    if not isinstance(trades, Mapping):
        return {}, None
    eligible = None
    block_reason = None
    if isinstance(execution, Mapping):
        eligible = execution.get("execution_eligible")
        block_reason = execution.get("block_reason")
    if eligible is not False:
        return dict(trades), None
    reason = block_reason if isinstance(block_reason, str) and block_reason.strip() else None
    reconciled: Dict[str, Any] = {}
    restated: List[str] = []
    for ticker, record in trades.items():
        if not isinstance(record, Mapping):
            reconciled[ticker] = record
            continue
        entry = dict(record)
        status = entry.get("status")
        if isinstance(status, str) and status.strip().lower() in EXECUTABLE_TRADE_STATUSES:
            entry["leg_status"] = status
            entry["status"] = BLOCKED_BY_SECTION_GATE_STATUS
            restated.append(str(ticker))
        entry["execution_eligible"] = False
        entry["section_gate_reason"] = reason
        reconciled[ticker] = entry
    disclosure = None
    if restated:
        disclosure = {
            "restated_trade_tickers": sorted(restated),
            "restated_trade_count": len(restated),
            "gate_source": "execution.execution_eligible",
            "block_reason": reason,
            # Formatted from the counts this very disclosure carries, so the rule
            # sentence cannot state a leg count the payload contradicts.
            "rule": TRADE_GATE_RECONCILIATION_RULE.format(
                restated_count=len(restated), total_count=len(reconciled)
            ),
        }
    return reconciled, disclosure


def _execution_gate_warning(execution: Mapping[str, Any]) -> Optional[str]:
    """The section-level sentence for a target the shared rule refuses.

    Derived from the block the route already published: the reasons, the
    measured gross exposure and the financing requirement. A section that names
    its own gate in prose while its records read as orders is the defect this
    closes, so the sentence travels with the response rather than only with the
    exporter.
    """
    reasons = [
        str(reason)
        for reason in (execution.get("block_reasons") or [])
        if isinstance(reason, str) and reason.strip()
    ]
    block_reason = execution.get("block_reason")
    detail = (
        block_reason.strip()
        if isinstance(block_reason, str) and block_reason.strip()
        else "; ".join(reasons)
    )
    if not detail:
        return None
    financing = execution.get("financing_requirement")
    currency = execution.get("financing_requirement_currency")
    financing_text = ""
    if isinstance(financing, (int, float)) and math.isfinite(float(financing)) and float(financing) > 0:
        financing_text = (
            f" Financing of {float(financing):,.2f}"
            f"{f' {currency}' if isinstance(currency, str) and currency.strip() else ''}"
            " is required before any leg of it can be placed."
        )
    return (
        f"This target is not executable as published: {detail}. Every "
        "trades[*] record inherits that gate, so the list is a financing-dependent "
        "target rather than an order set."
        f"{financing_text}"
    )


# The rebalance workflow publishes this exact block for a submitted target; the
# optimizer publishes the same shape for the weights its solver produced, so one
# rule string describes both. Solver weights are published rounded to six
# decimals, so a long-only vector that sums to 1.0 can sit up to n / 2e6 above
# it (2.5e-5 for a 50-leg book); the shared rule's default 1e-6 tolerance would
# read that rounding as financing and refuse a legitimately funded target. The
# optimizer validates a solver output, not a user submission, so it validates at
# the precision it publishes, and 1e-4 still sits far below any real leverage.
_SOLVER_GROSS_TOLERANCE = 1e-4

#: Decimals every published optimizer weight is rounded to, and therefore the
#: precision a `trades_required` record is auditable at.
TRADE_WEIGHT_DECIMALS = 4


def _weight_normalization_block(
    weights: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Validate a target through the shared rule and report it like rebalance.

    The validated `weights` are not substituted into the response: this is a
    disclosure of what the shared rule measured about the published target, not
    a silent rewrite of a solver answer.

    `financing_required` is decided from the UNROUNDED gross exposure. The shared
    rule rounds its own answer to six decimals, so a solver target that sums to
    0.999998 published `gross_exposure: 1.0` and `financing_required: false` with
    a 2e-6 shortfall hidden inside that rounding - a book that is not quite fully
    funded, displayed as exactly funded. The residual is published so the two
    readings are reconcilable, and the decision no longer depends on the
    rounding.
    """
    normalization = normalize_rebalance_weights(weights, tolerance=_SOLVER_GROSS_TOLERANCE)
    measured_gross = gross_exposure(weights)
    published_gross = float(normalization["gross_exposure"])
    block = {
        "normalization_rule": WEIGHT_NORMALIZATION_RULE,
        "normalization_mode": normalization["normalization_mode"],
        "weights_normalized": normalization["weights_normalized"],
        "submitted_gross_exposure": normalization["submitted_gross_exposure"],
        "submitted_gross_exposure_measured": measured_gross,
        "gross_exposure": normalization["gross_exposure"],
        "gross_exposure_residual": round(measured_gross - published_gross, 12),
        "gross_exposure_tolerance": _SOLVER_GROSS_TOLERANCE,
        "execution_eligible": normalization["execution_eligible"],
        "financing_required": measured_gross > 1.0 + _SOLVER_GROSS_TOLERANCE,
        "financing_required_basis": "unrounded_submitted_gross_exposure",
        "net_cash_weight": round(1.0 - normalization["gross_exposure"], 6),
        "gross_exposure_residual_basis": (
            "submitted_gross_exposure_measured - gross_exposure. gross_exposure is "
            "the post-normalization value the shared rule produces (exactly 1.0 for "
            "a fully funded book), so this residual is the shortfall or surplus the "
            "normalization absorbs; it is negative for an under-funded target and "
            "zero for a full exit."
        ),
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
        # This section is the REFERENCE window the four sibling holding-window
        # sections are defined against, so it declares the unit of its block
        # count and the unit of every per-ticker count, and publishes the terms
        # that relate the two per-ticker frames (held price rows vs the return
        # rows they produced) instead of leaving `masked_days` and
        # `return_observations` as two numbers no reader can reconcile.
        history_coverage["per_ticker_count_units"] = dict(PRICE_FRAME_COUNT_UNITS)
        history_coverage["per_ticker_count_reconciliation"] = (
            _price_frame_count_reconciliation(per_ticker, own_return_observations)
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
        # The unit of that count: the active return observations the engine
        # measured inside the holding window. Published here because this is the
        # section `factor_exposure`, `risk_contribution`, `tear_sheet` and
        # `regime` are all defined against - a reference count with no unit is
        # the one number a consumer cannot compare with its siblings'.
        history_coverage["covered_days_scope"] = HOLDING_COVERED_DAYS_SCOPE
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
            "hit_ratio": metrics.get("hit_ratio"),
            # SI-5: the engine's precision block for exactly the ten fields
            # above, over exactly the series they were measured from. Forwarded
            # verbatim so the interval always names the same n the point
            # estimate did.
            "estimate_uncertainty": metrics.get("estimate_uncertainty"),
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
                # SI-5: this leg's own precision block, measured over this
                # leg's own return observations.
                "estimate_uncertainty": pos_metrics.get("estimate_uncertainty"),
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


# ---------------------------------------------------------------------------
# forecast_risk precision disclosure (ENV-020)
# ---------------------------------------------------------------------------
# This section publishes 26 estimated quantities and, before this block, not
# one of them carried a standard error, an interval or an effective sample size.
# Its entire precision content was three keys whose combined message to a reader
# was "there is no interval, and here is a paragraph explaining why" - which is
# a true statement about a DIFFERENT thing.  It is not a precision basis, and it
# was being read as one.
#
# The fix is not a better paragraph.  It is that the 26 numbers are three kinds
# of thing, and each kind admits a different disclosure:
#
#   ESTIMATED  - `volatility_forecast` (portfolio and every position leg).  A
#     conditional sigma fitted to a measured return series.  It has a sampling
#     distribution.  The PORTFOLIO leg's is MEASURED here, by re-fitting the
#     model on every moving-block resample; a position leg's is NOT, and each leg
#     says so with the cost that decided it.  One measured leg and thirteen
#     declared-unmeasured ones is the disclosure this export can afford; fifteen
#     measured ones is what broke it.
#
#   DERIVED    - `var_forecast`, `cvar_forecast`, `cvar_to_var_ratio`.  Each is
#     a published function of a published number, so it has no independent
#     uncertainty to report.  They publish the figure they inherit instead, and
#     the pointer is resolved by a test that walks it - including the legs whose
#     target is itself undisclosed, which resolve to a node that says so.
#
#   DECLARED   - the z / ES multipliers, the confidence level, the horizon.  The
#     quantiles of a normal distribution and a stated input.  A design constant
#     has no sampling distribution, and refusing to invent one is the point.
#
# Nothing here changes a published forecast value.  Every number on this section
# is computed exactly as it was before this block existed; the block only says
# what is known about how tightly each one was determined.
#
# WHAT THIS BLOCK COSTS, AND WHY IT IS SPENT THE WAY IT IS.  Measuring the
# precision of a fitted conditional sigma means RE-FITTING the model on every
# resample, and a GARCH(1,1) refit is a full optimiser run, not a vectorised
# reduction.  Measured on the real 14-position book through the real route: 3800
# refits, 74.2 s of route wall time, of which 68.6 s was the refits.  That does
# not survive contact with a whole export.  Each section is assembled under its
# own 180 s budget (`ai_context_service._SECTION_TIMEOUT_SECONDS`), sections are
# collected one after another, and a section that overruns is not merely slow:
# `asyncio.wait_for` cancels the coroutine but cannot cancel the thread the
# refits are already running on, so the optimiser keeps burning CPU against every
# section collected afterwards.  Measured on the export that way, three sections
# (factor_exposure, optimization, regime) were published `unavailable` and seven
# more degraded to `partial`, and the export stopped completing at all.
#
# So the cost was cut where it is largest and least informative.  The portfolio
# leg - the figure the section is named for - keeps the full re-fit measurement.
# The position legs stop being re-fitted and state the truth instead: estimated,
# measured on their own return series, not separately measured, with the
# observation count, the AR(1) and the effective sample size that ARE known.  A
# leg's forecast is derived from that leg's own inputs and its precision belongs
# to those inputs; a withheld figure with a stated reason is the honest outcome
# and an invented one would be the defect this whole block exists to prevent.

#: The prefix the precision rule builds its paths from.  Published on every
#: classification so a reader can locate the exact key being described without
#: reconstructing the artifact path by hand.
FORECAST_PRECISION_PATH_PREFIX = "sections.forecast_risk.data"

FORECAST_PRECISION_BASIS = (
    "the numbers this section publishes are three different kinds of thing, and "
    "a standard error is only a statement about one of them. volatility_forecast "
    "is a MODEL OUTPUT fitted to a measured return series. The PORTFOLIO leg's is "
    "MEASURED: the same model is re-fitted on every circular moving-block "
    "resample and the dispersion of the re-fitted value is the standard error. A "
    "POSITION leg's is NOT separately measured, and says so - a GARCH refit is a "
    "full optimiser run, so measuring every leg of the book cost this export "
    "three other sections their output, and the leg states what is known of its "
    "precision instead of a figure the export could not afford. "
    "var_forecast, cvar_forecast and cvar_to_var_ratio are DETERMINISTIC "
    "FUNCTIONS of numbers this section already publishes, so they carry no "
    "uncertainty of their own and name the figure they inherit. The z and ES "
    "multipliers, the confidence level and the horizon are DECLARED CONSTANTS: "
    "the quantiles of a normal distribution, and a stated input, chosen by "
    "design. A design constant has no sampling distribution, and inventing one "
    "to satisfy a disclosure rule would be the defect rather than the fix."
)

FORECAST_PRECISION_CLASSES = {
    "estimated": (
        "a model output computed from data. Carries a measured standard error and "
        "a 95 % interval where the measurement was affordable, and the effective "
        "sample size of the return series it was fitted on either way. Where it "
        "was not measured it says so, names the cost that decided it, and "
        "publishes a null standard error with a stated reason - never a narrower "
        "interval chosen to fit a budget, because a percentile interval narrowed "
        "past the point where its own tail means anything is worse than none"
    ),
    "deterministic_derivation": (
        "a published function of published numbers. Carries no standard error of "
        "its own - an interval on it would be a rescaled copy of an already "
        "published number's band - and names the figure it inherits through "
        "inherits_precision_from / inherits_precision_at, or states that its "
        "inputs' own precision is undisclosed."
    ),
    "declared_constant": (
        "a lookup constant or a stated input, never estimated from data. Carries "
        "a null standard error with the source named, because a design constant "
        "cannot be resampled and a band around it would describe nothing."
    ),
}

#: One shared string per class rather than one per key, so the payload does not
#: repeat a paragraph fourteen times and so there is exactly one place to amend
#: the wording if the disclosure is ever extended.
_DECLARED_CONSTANT_SE_REASON = (
    "not applicable: a declared constant. This value is read from a named table "
    "in app/services/analytics_engine.py or is a stated request parameter. It was "
    "never estimated from data, so it has no sampling distribution, no standard "
    "error and no interval; a figure here would be a fabrication rather than a "
    "measurement"
)
_DECLARED_CONSTANT_CI_REASON = (
    "not applicable: see standard_error_reason - a declared constant is not "
    "estimated, so there is no distribution to take a percentile of"
)

#: Multi-step EGARCH runs on arch's SIMULATION path.  That path is now
#: SEED-REPRODUCIBLE: arch 8.0.0's simulation branch never reads the
#: `random_state` this engine used to pass it (it is forwarded only to
#: `_bootstrap_forecast`), and instead draws from an `rng` callable seeded here
#: from the model's own distribution class.  So two forecasts on the same fitted
#: model now agree bit-for-bit, and the earlier reason - that they differed in
#: the 4th decimal - is no longer true.
#:
#: A band is still withheld, for a different and now structural reason.
#: `EGARCH_SIMULATION_SEED` is a LITERAL, not a per-call value, so every
#: resample of a block bootstrap re-runs the identical seeded simulation and
#: returns the identical number: the resampled distribution has ZERO dispersion,
#: and any interval built from it would be `[x, x]` - a constant multiple of the
#: point, which is the fabrication this disclosure exists to prevent and the
#: thing NUM-022 exists to catch.  Removing the withhold without changing the
#: seed's scope would therefore trade an honest absence for a fake band.
#:
#: The real uncertainty of a Monte-Carlo mean is the dispersion of its own
#: draws.  The engine runs `FORECAST_SIMULATIONS` of them and does not publish
#: their spread; that is the honest fix, and it is a separate change because it
#: needs the draw distribution rather than a resampling of the input series.
#: The reason is published rather than the estimator's generic "your point did
#: not reproduce" message, which would read as an accusation against a number
#: that is in fact perfectly reproducible.
_EGARCH_SIMULATED_NO_BAND = (
    "not computed: this forecast's conditional-variance path comes from arch's "
    "SIMULATION branch, and that branch is seeded and therefore reproducible - "
    "two forecasts on the same fitted model now agree exactly. No band is "
    "claimed anyway, and the reason is structural rather than a defect in the "
    "point: the seed is a fixed literal rather than a per-call value, so every "
    "resample of a block bootstrap re-runs the identical seeded simulation and "
    "returns the identical number. The resampled distribution has zero "
    "dispersion, so an interval built from it would be a constant multiple of "
    "this point and would describe no uncertainty that exists. The point is a "
    "Monte-Carlo mean over FORECAST_SIMULATIONS draws, and the quantity that "
    "would measure its precision is the spread of those draws, which the engine "
    "computes but does not publish; publishing that is the honest fix and is a "
    "separate change"
)

_TERM_STRUCTURE_BASIS = (
    "term_structure is the SAME fitted conditional-variance path at each of its "
    "intermediate horizon steps, and it is not resampled separately: only the "
    "terminal value carries a band. The intermediate steps are the same estimate "
    "at a shorter horizon, not a different statistic, and publishing fifteen "
    "correlated bands for one path would overstate how much independent "
    "information the path contains"
)

# ---------------------------------------------------------------------------
# The measured cost of the declined measurement, DERIVED rather than written
# ---------------------------------------------------------------------------
# The paragraph below once said "3800 refits in total" beside a portfolio leg of
# "1001 refits" and fourteen legs of "2800" - and 1001 + 2800 is 3801.  The
# sibling `precision.resample_count_rule` in the SAME block said 1000 for the
# portfolio leg, so one object carried two totals for one measurement.
#
# THE `+1`, now settled from the engine side and mirrored here rather than
# re-derived: the portfolio leg's 1001 is
# :data:`FORECAST_PORTFOLIO_REFIT_RESAMPLES` RESAMPLED fits PLUS the one original
# fit the section measured.  It is not a resample, it is not counted by
# `bootstrap_resamples`, and it is not a rounding artefact.  Naming it is the
# whole fix; the arithmetic below is what stops it drifting again.
#:
# The 14 is the leg count of the book this was measured on, not a module
# constant, so it is declared as one HERE rather than left as a literal buried
# in a sentence.  Every figure in the prose is interpolated from these, so a
# change to any of them moves the sentence and the structured block together.
FORECAST_WITHHELD_BOOK_LEGS = 14

#: Resampled fits, plus the one original fit.  See the note above.
#:
#: CAPTURED AT IMPORT, and that is load-bearing rather than incidental.  This
#: whole group is a record of a cost that was MEASURED, so it must not be
#: re-derived from module globals that a caller - or a test running with a reduced
#: draw count - can change underneath it.  The first version of the structured
#: block below mixed the two: it read `FORECAST_PORTFOLIO_REFIT_RESAMPLES` at
#: call time and the import-time total beside it, and under a reduced draw count
#: it published `portfolio_resamples: 60` next to `portfolio_fits: 1001`.  Every
#: figure here is therefore frozen at import, and the block quotes only these.
FORECAST_WITHHELD_PORTFOLIO_RESAMPLES = FORECAST_PORTFOLIO_REFIT_RESAMPLES
FORECAST_WITHHELD_PORTFOLIO_FITS = FORECAST_WITHHELD_PORTFOLIO_RESAMPLES + 1
FORECAST_WITHHELD_LEG_RESAMPLES = FORECAST_LEG_REFIT_RESAMPLES_WITHHELD
FORECAST_WITHHELD_LEG_FITS = (
    FORECAST_WITHHELD_LEG_RESAMPLES * FORECAST_WITHHELD_BOOK_LEGS
)
FORECAST_WITHHELD_TOTAL_FITS = (
    FORECAST_WITHHELD_PORTFOLIO_FITS + FORECAST_WITHHELD_LEG_FITS
)

#: Wall-clock, measured on the real 14-position book.  The seconds DO add up
#: (17.3 + 51.3 = 68.6) and are left exactly as measured; only the fit COUNTS are
#: derived above.
FORECAST_WITHHELD_PORTFOLIO_SECONDS = 17.3
FORECAST_WITHHELD_LEG_SECONDS = 51.3
FORECAST_WITHHELD_OPTIMISER_SECONDS = 68.6
FORECAST_WITHHELD_ROUTE_WALL_SECONDS = 74.2

#: The long form of "this leg's precision was not measured, and here is why",
#: published ONCE under `precision.measurements_withheld` rather than repeated on
#: every leg.  A paragraph that says the same thing fourteen times is fourteen
#: times the bytes and no more information, and the block is already the largest
#: thing on this section - the earlier fourteen-measured-legs version carried the
#: same words per leg and the payload grew 28 % while the disclosure shrank.
#:
#: The per-leg `estimator_withheld` is deliberately NOT this text and does not
#: need to be: it states the decision and points here, and the pointer is
#: resolved by the same test that resolves every other pointer on this block.
_FORECAST_LEG_MEASUREMENT_WITHHELD = (
    "not measured, and deliberately. A position leg's volatility_forecast is its "
    "own conditional-volatility model fit, and the precision of a fitted sigma is "
    "measured by RE-FITTING that model on every resample - a full ARCH optimiser "
    "run per draw, not a vectorised reduction, so a book of N legs costs N of "
    "them. Measured on the "
    f"{FORECAST_WITHHELD_BOOK_LEGS}-position book this was written against: "
    f"{FORECAST_WITHHELD_TOTAL_FITS} refits in total, "
    f"{FORECAST_WITHHELD_OPTIMISER_SECONDS} s of pure optimiser time and "
    f"{FORECAST_WITHHELD_ROUTE_WALL_SECONDS} s of route wall time, of which the "
    f"portfolio leg's {FORECAST_WITHHELD_PORTFOLIO_FITS} refits were "
    f"{FORECAST_WITHHELD_PORTFOLIO_SECONDS} s and the "
    f"{FORECAST_WITHHELD_BOOK_LEGS} legs' {FORECAST_WITHHELD_LEG_FITS} were the "
    f"remaining {FORECAST_WITHHELD_LEG_SECONDS} s. The portfolio leg's "
    f"{FORECAST_WITHHELD_PORTFOLIO_FITS} is the module's "
    f"{FORECAST_WITHHELD_PORTFOLIO_RESAMPLES} RESAMPLED fits plus the one ORIGINAL "
    "fit the section measured: the original fit is not a resample, is not counted "
    "by bootstrap_resamples, and is the +1 that an earlier version of this "
    "sentence dropped while leaving both of its parts in place. That does not fit "
    "the 180 s budget each "
    "section is assembled under, and overrunning it costs OTHER sections their "
    "output rather than merely making this one slow: the cancelled coroutine "
    "cannot cancel the thread its refits are already running on, so the "
    "optimiser keeps competing with every section collected afterwards.\n\n"
    "So the leg states what is known instead. It IS estimated, it is measured on "
    "this leg's OWN return observations rather than the portfolio's, and the "
    "observation count, the AR(1) and the effective sample size that implies are "
    "published on its block - those cost nothing and they are the part of this "
    "leg's precision that is genuinely known. What is not published is a standard "
    "error and an interval, and nothing has been substituted for them. Narrowing "
    "the draw count until the block fits was rejected for the same reason: a "
    "percentile interval narrowed past the point where its own 2.5 % tail means "
    "anything is a figure that describes nothing, which is the defect this whole "
    "disclosure exists to remove. A withheld figure with a stated reason is an "
    "honest outcome; an invented one is not.\n\n"
    "The measurement that was declined is published rather than deleted, so it is "
    "reproducible by anyone willing to pay for it: see each leg block's "
    "notes.estimator, which names the statistic that would have been evaluated."
)


# ---------------------------------------------------------------------------
# P1 - the annualized volatility clip bound, counted and measured
# ---------------------------------------------------------------------------
# `volatility_forecast_point` publishes a CLIPPED number: the raw terminal
# annualized volatility the fit produced goes through
# `np.clip(raw, clip_low, FORECAST_VOL_CLIP_HIGH)`, and the route published only
# the clipped side of that.  A reader who sees 1.20 therefore cannot tell a
# data-driven 95th percentile from the bound itself, and cannot tell how far a
# clipped value moved.
#
# WHAT ALREADY EXISTS AND IS NOT REBUILT HERE.  Every leg's `var_forecast` entry
# in `precision.derived_values` already carries `derivation_precondition`,
# `derivation_precondition_met` and `derivation_precondition_evidence`, whose
# evidence string reads "annualized_volatility_at_clip_bound is False: the
# published leg volatility is ... against bounds [...]".  That is a BOOLEAN about
# the POINT ESTIMATE.  What is missing is any statement about the BAND, and the
# MAGNITUDE the clip removed.
#
# WHY THERE IS NO THRESHOLD HERE, and this is a measurement rather than a
# preference (`.scratch/v5-review/13-overflow-discriminator.md` §2, on 5,185 real
# EGARCH(1,1) fits): thirty candidate discriminators were scored and 30 of 30
# are non-separable - there is no threshold on any of them at which the divergent
# set and the genuine-extreme set stop overlapping.  The best principled
# predicate, the model-implied ln E[sigma^2] exceeding ln DBL_MAX, wrongly
# refuses 6.0 % of genuine forecasts while missing 21.3 % of divergences, and the
# four quantities that do separate in-sample hold out at a coin flip
# (P(zero out-of-sample errors) 0.48-0.52 over 400 repeats).  The reason is
# structural: for any beta < 1 the EGARCH conditional variance is lognormal with
# a finite expectation, so no parameter set makes the model assert a
# nonexistent forecast, and beta approaching 1 asserts an arbitrarily large one
# continuously.  THE FIX IS TO PUBLISH WHAT WAS CLIPPED, NOT TO DETECT
# DIVERGENCE.
#:
# Gating arch's own ensemble rather than its mean was measured and declined too:
# it would score 0 false positives and 100 % false negatives for this defect, and
# it needs a private arch API the library does not expose.  It is not needed
# here either, because headline and band already run through the same
# `volatility_forecast_point`, so a bound active on the point is the same bound
# the restatements are measured against.
#:
# REACHABILITY, for the scale of what the count is reporting: on the real
# 14-position book at EGARCH h=3, 156 of 2,993 usable restatements (5.2 %)
# published exactly the bound, on 15 of 15 legs, and four legs carried
# restatements whose true raw value was between 1e6 and 1e54.  No published point
# estimate was clipped on that book - the headline's maximum raw was 0.4798
# against a bound of 1.20 - so this is a BAND disclosure and not a headline one.
CLIP_BOUND_COUNT_DENOMINATOR = (
    "a USABLE RESTATEMENT is one circular moving-block resample whose refitted "
    "terminal annualized volatility is finite - the same population the published "
    "standard error and conf_int are read off, and the same one whose failed draws "
    "are counted in the block's status rather than dropped. at_clip_bound is the "
    "number of usable restatements whose PUBLISHED value is exactly "
    f"{FORECAST_VOL_CLIP_HIGH}, which is the count of draws the clip bound moved. "
    "share is at_clip_bound divided by usable_restatements, and is null rather "
    "than 0 whenever the denominator is null: an unmeasured count is an absence, "
    "not a zero"
)

_CLIP_BOUND_UNMEASURED_REASON = (
    "not measured: this leg's re-fit estimator was not evaluated, so there are no "
    "restatements to count. The measurement that was declined and the cost that "
    "decided it are published at precision.measurements_withheld. A count of 0 "
    "here would assert that the clip bound was tested and never bound, which is "
    "the one claim this payload does not make"
)

_CLIP_BOUND_NO_CLIP_REASON = (
    "measured, and zero by construction rather than by result: this leg fell "
    "below the history gate, so its forecast is its own sample standard deviation "
    "and the fitted models' annualized clip bounds are not applied to it. The "
    "restatements were counted; the bound was never in play"
)


def _observed_volatility_statistics(
    model: str, horizon: int
) -> Tuple[Any, Dict[str, Any]]:
    """`volatility_forecast_statistics` wrapped so the clip is OBSERVED, not re-run.

    One ARCH fit already produces both sides of the clip for a draw - the engine's
    `volatility_forecast_point` returns `volatility_forecast` and
    `raw_volatility_forecast` from the same computation - and `fields` is an
    existing parameter of the engine's own factory.  So the raw costs nothing to
    ask for: this wrapper counts what the bound did and returns the engine's dict
    UNCHANGED, which is what keeps the band, the standard error and the
    reproduction guard the engine's own rather than a second implementation that
    could drift from them.

    `tally` is filled on the resampling pass only.  `measure_estimate_uncertainty`
    calls the statistic twice - once over the resample block, once over the
    original sample as the reproduction guard - and only the first of those is a
    population a count can be read off.

    THE BLOCK IS `(n, draws, k)`, TIME AXIS FIRST, so the draw count is axis 1
    and not axis 0.  Reading axis 0 here counts observations as if they were
    draws, which on the real book means a denominator of 175 for a band read off
    1,000 draws - a number that looks plausible and is simply the wrong
    population.  The reproduction guard's own call has `draws == 1`, and axis 1
    is what distinguishes the two passes.

    `return_space_volatility` is still requested, and the reason it is named here
    rather than left to the engine's default is that the portfolio leg's
    `var_forecast` and `cvar_forecast` INHERIT their precision from that field's
    band through `inherits_precision_at_path`.  Narrowing `fields` drops the field
    from the block, the pointer lands on nothing, and the disclosure silently
    becomes an unresolvable one - which is precisely the failure
    `test_the_pointer_resolves_to_a_node_carrying_a_real_figure` exists to catch.
    """
    tally: Dict[str, Any] = {"at_clip_bound": None, "usable_restatements": None,
                             "largest_removed_by_clip": None, "restatements": 0}
    inner = volatility_forecast_statistics(
        model, horizon,
        fields=(
            "volatility_forecast", "return_space_volatility",
            "raw_volatility_forecast",
        ),
    )

    def observed(block: Any) -> Dict[str, np.ndarray]:
        out = inner(block)
        shape = np.asarray(block).shape
        draws = int(shape[1]) if len(shape) > 1 else 0
        if draws <= 1:
            # the reproduction guard's own single-draw call, not a draw set
            return out
        published = np.asarray(out.get("volatility_forecast"), dtype=float)
        raw = np.asarray(out.get("raw_volatility_forecast"), dtype=float)
        finite = np.isfinite(published)
        bound = finite & (published >= FORECAST_VOL_CLIP_HIGH)
        moved = bound & np.isfinite(raw) & (raw > FORECAST_VOL_CLIP_HIGH)
        tally["restatements"] = draws
        tally["usable_restatements"] = int(finite.sum())
        tally["at_clip_bound"] = int(bound.sum())
        tally["largest_removed_by_clip"] = (
            float(np.max(raw[moved]) - FORECAST_VOL_CLIP_HIGH) if bool(moved.any())
            else 0.0
        )
        return out

    return observed, tally


def _observed_usable_count(
    statistic: Any, tally: Dict[str, Any]
) -> Any:
    """Count a vectorised statistic's finite draws, and return it UNCHANGED.

    The limited-history branch's estimator is a closed-form order statistic and
    never touches the clip bound, so its `at_clip_bound` is 0 by construction
    rather than by result.  Its DENOMINATOR still has to mean the same thing it
    means everywhere else - the finite restatements - so it is counted the same
    way rather than taken from `bootstrap_resamples`, which is the count
    REQUESTED and includes the draws that came back non-finite.
    """
    def observed(block: Any) -> np.ndarray:
        out = statistic(block)
        # `engine_risk_statistics` returns a `(draws,)` array, whose axis 0 IS
        # the draw count.  The guard's own single-draw call is a length-1 array
        # and is not recorded.
        if int(np.asarray(out).shape[0]) > 1:
            tally["restatements"] = int(np.asarray(out).shape[0])
            tally["usable_restatements"] = int(
                np.isfinite(np.asarray(out, dtype=float)).sum()
            )
        return out

    return observed


def _clip_restatement_record(
    *,
    status: str,
    at_clip_bound: Optional[int] = None,
    usable_restatements: Optional[int] = None,
    largest_removed_by_clip: Optional[float] = None,
    conf_int: Any = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """One leg's (or the portfolio's) clip-bound restatement tally.

    Every field is `None` together with a `reason` whenever the estimator did not
    run.  A count of 0 means the restatements were taken and the bound never bound
    them; a count of `None` means they were never taken.  Those are different
    facts and the payload must not be able to express one as the other.
    """
    record: Dict[str, Any] = {
        "status": status,
        "at_clip_bound": at_clip_bound,
        "usable_restatements": usable_restatements,
        "share_of_usable_restatements": (
            round(at_clip_bound / usable_restatements, 6)
            if at_clip_bound is not None and usable_restatements
            else None
        ),
        # The MAGNITUDE, not the boolean.  `largest_removed_by_clip` is how far the
        # furthest restatement was moved by the bound, so a draw that landed on
        # 1.20 and a draw that was merely 1.20 are different numbers and this is
        # the one that says which.
        "largest_removed_by_clip": largest_removed_by_clip,
        "published_interval": list(conf_int) if conf_int is not None else None,
        # The band-level statement the point-level `annualized_volatility_at_clip_
        # bound` evidence string cannot make: whether the PUBLISHED interval's far
        # end IS the bound.
        "published_interval_at_clip_bound": (
            bool(conf_int[-1] >= FORECAST_VOL_CLIP_HIGH)
            if conf_int is not None else None
        ),
        "reason": reason,
    }
    return record


def _unmeasured_clip_restatement_record(reason: str) -> Dict[str, Any]:
    """The record for a leg or leg-set whose restatements were never taken."""
    return _clip_restatement_record(status="not_measured", reason=reason)


def _forecast_sentences(*parts: str) -> str:
    """Join independently-written clauses into complete sentences.

    THE DEFECT THIS EXISTS FOR.  `inherits_precision_reason` for an unmeasured
    position leg ended with a path terminated by a period and then had a
    sentence fragment appended with `+`, producing on all fourteen legs:

        "...portfolio.estimates.the fitted leg's return-space sigma is its own
         published annualized volatility times sqrt(h / 252), which is ..."

    A path glued to a subject-less clause, ungrammatical, and the path it appears
    to name resolves to nothing.  The fragment was a well-formed sentence on its
    own; the defect was the missing boundary, not the words.

    Joining HERE rather than at each call site is the structural half of the fix:
    there is no `+` left to forget a boundary in, and every part is terminated
    before the next one is attached, so a future clause inherits the guarantee
    rather than having to remember it.
    """
    joined = ""
    for part in parts:
        text = " ".join(str(part).split())
        if not text:
            continue
        if not text.endswith((".", "!", "?")):
            text += "."
        joined = f"{joined} {text}" if joined else text
    return joined


def _forecast_declared_constant(

    name: str,
    value: Any,
    source: str,
    published_at: List[str],
) -> Dict[str, Any]:
    """One declared constant: a value with a source and no sampling distribution."""
    return {
        "name": name,
        "classification": "declared_constant",
        "value": value,
        "source": source,
        "published_at": list(published_at),
        "standard_error": None,
        "standard_error_reason": _DECLARED_CONSTANT_SE_REASON,
        "conf_int": None,
        "conf_int_reason": _DECLARED_CONSTANT_CI_REASON,
    }


def _forecast_derived_value(
    *,
    published_at: List[str],
    formula: str,
    inputs: Mapping[str, Any],
    inputs_classification: Mapping[str, Any],
    inherits_precision_from: Any,
    inherits_precision_at: Optional[Tuple[str, ...]],
    inheritance_status: str,
    inheritance_reason: str,
    precision_inheritance_factor: Optional[float] = None,
    derivation_residual: Optional[float] = None,
    derivation_precondition: Optional[str] = None,
    derivation_precondition_met: Optional[bool] = None,
    derivation_precondition_evidence: Optional[str] = None,
) -> Dict[str, Any]:
    """One deterministic function of published numbers.

    `inherits_precision_at` is a path into this same payload.  A pointer that
    lands on a node with no figure is worse than no pointer: it asserts an
    inheritance that does not exist.  So when the inputs are themselves
    undisclosed - which is the case for a ratio of two design constants - the
    pointer is `None`, `inheritance_status` says so, and `inheritance_reason`
    states the absence rather than pointing at it.

    `inheritance_status` has three values, and the third is why the test that
    walks these pointers has three branches rather than two:

      resolved                        the target is on the payload and carries a
                                      measured standard error or interval.
      inputs_are_declared_constants   there is no target at all - both inputs
                                      are design constants with no sampling
                                      distribution - so the pointer is None.
      target_is_itself_undisclosed    the target IS on the payload and the
                                      inheritance is real, but the target's own
                                      precision was not measured, so the pointer
                                      is KEPT and the status says there is no
                                      figure at the far end of it.

    The third is the one that could have been written two ways.  Dropping the
    pointer would have been tidier and less true: a leg's tail really does
    inherit whatever precision that leg's own sigma has, and the node naming it
    is right there on the payload saying so.  Claiming `resolved` would have been
    the defect.  So the pointer stays, the target states its own absence, and
    the status is the only thing distinguishing the two from a real inheritance.

    THE PATH IS A SEGMENT LIST, NOT A DOTTED STRING, because the keys it has to
    traverse are ticker symbols: `positions.CIPLA.NS` is one key, and a dotted
    string would split it into `CIPLA` and `NS` and resolve to nothing.  The
    readable dotted form is published beside it and is explicitly labelled
    non-authoritative, so nobody resolves through it by accident.
    """
    return {
        "classification": "deterministic_derivation",
        "published_at": list(published_at),
        "formula": formula,
        "inputs": dict(inputs),
        "inputs_classification": {
            name: dict(entry) for name, entry in inputs_classification.items()
        },
        "inputs_classification_basis": (
            "each restated input is classified in its own right. A formula that "
            "repeats a declared constant next to the number it multiplies "
            "publishes that constant a second time, and a key that appears "
            "twice on a payload is still a key - so it is classified, not left "
            "to be discovered by whichever rule reads it"
        ),
        "inherits_precision_from": inherits_precision_from,
        "inherits_precision_at": (
            None if inherits_precision_at is None
            else ".".join(inherits_precision_at)
        ),
        "inherits_precision_at_path": (
            None if inherits_precision_at is None
            else list(inherits_precision_at)
        ),
        "inherits_precision_at_basis": (
            "inherits_precision_at_path is the AUTHORITATIVE pointer: a list of "
            "keys walked from the root of this payload. The dotted "
            "inherits_precision_at beside it is the same pointer written for "
            "reading and is NOT resolvable by splitting on '.', because the "
            "position keys it traverses are ticker symbols such as CIPLA.NS and "
            "contain dots of their own"
        ),
        "inherits_precision_status": inheritance_status,
        "inherits_precision_reason": inheritance_reason,
        # The exact multiplier that carries the inherited standard error across
        # the formula.  Published so the propagation is a multiplication the
        # reader can do, rather than a figure this section declined to compute
        # and left to be guessed.
        "precision_inheritance_factor": precision_inheritance_factor,
        "precision_inheritance_factor_basis": (
            "the constant this formula multiplies its input by, so a reader can "
            "apply the inherited standard error to this value without this "
            "section publishing an interval that describes no new information"
            if precision_inheritance_factor is not None else None
        ),
        "derivation_residual": (
            None if derivation_residual is None
            else float(derivation_residual)
        ),
        "derivation_residual_basis": (
            "the published value minus this formula applied to the published "
            "inputs. It is zero to floating-point noise when the derivation is "
            "exact, and non-zero means a published clip bound is active on this "
            "leg - in which case the formula describes the UNCLIPPED relation and "
            "the residual is the clip, not an error"
        ),
        # A formula that only holds while some condition is met must publish the
        # condition.  An identity that silently stops holding is the kind of
        # derivation note that is true until the day it is not.
        "derivation_precondition": derivation_precondition,
        "derivation_precondition_met": derivation_precondition_met,
        "derivation_precondition_evidence": derivation_precondition_evidence,
        "standard_error": None,
        "standard_error_reason": (
            "not computed: this value is a deterministic function of numbers this "
            "section already publishes, so it has no independent uncertainty. A "
            "standard error here would be the inherited input's standard error "
            "rescaled by a constant, which describes the input and not this value. "
            "See inherits_precision_at for the figure this value does inherit"
        ),
        "conf_int": None,
        "conf_int_reason": (
            "not computed: see standard_error_reason - a deterministic function of "
            "an already-published number has no distribution of its own, and an "
            "interval scaled off the input's band would be the input's band again"
        ),
    }


def _forecast_portfolio_uncertainty(
    portfolio_returns: Any,
    model: str,
    horizon: int,
    forecast_result: Mapping[str, Any],
) -> Dict[str, Any]:
    """Measured precision for the portfolio leg's two fitted quantities.

    Both published values come out of ONE GARCH fit, so one re-fit per resample
    produces both; they are handed to `measure_estimate_uncertainty` as a single
    callable and the guard re-derives each one separately.
    """
    tail = forecast_result.get("tail_measure") or {}
    published = {
        "volatility_forecast": forecast_result.get("volatility_forecast"),
        "return_space_volatility": tail.get("return_space_volatility"),
    }
    scope = (
        "forecast_risk.portfolio: the terminal conditional sigma of the fitted "
        f"{model} model on the aggregated portfolio return series, and the "
        "return-space sigma the VaR/CVaR multipliers are applied to. Both are "
        "outputs of the same fit and are re-fitted together on every resample"
    )
    notes = {
        "estimator": (
            "volatility_forecast_statistics: on each circular moving-block "
            "resample of the portfolio return series, the engine's own "
            "volatility_forecast_point re-fits the same model with the same "
            "options and returns its terminal values. It is the SAME function the "
            "published forecast is computed by, so the band cannot drift off the "
            "published number"
        ),
        # As on a leg block: the rule covering both legs' counts is published
        # once at precision.resample_count_rule, not copied here.
        "resample_count_rule": "published once at precision.resample_count_rule",
        "term_structure": _TERM_STRUCTURE_BASIS,
    }
    not_computed = {}
    if (
        str(model).upper() == "EGARCH" and int(max(1, int(horizon))) > 1
    ):
        not_computed = {field: _EGARCH_SIMULATED_NO_BAND for field in published}
        notes["simulated_path"] = _EGARCH_SIMULATED_NO_BAND
    statistics, clip_tally = _observed_volatility_statistics(model, horizon)
    block = measure_estimate_uncertainty(
        _finite_return_values(portfolio_returns),
        statistics,
        published,
        scope=scope,
        resamples=FORECAST_PORTFOLIO_REFIT_RESAMPLES,
        # The published values are full float64 - this section does not round the
        # forecast - so the tolerance is the module's own, not a display step.
        point_tolerance=1e-6,
        not_computed=not_computed or None,
        notes=notes,
    )
    # The clip bound, counted on the same draws the band was read off.  Read out of
    # the block's OWN interval rather than restated, so `published_interval` and
    # `published_interval_at_clip_bound` cannot disagree with the conf_int beside
    # them.  `not_computed` wins over the tally: on that branch every restatement
    # is the identical seeded simulation, so a count taken over them would be a
    # count of one number repeated and would read as a measurement of a spread
    # that _EGARCH_SIMULATED_NO_BAND says does not exist.
    if not_computed:
        clip_record = _unmeasured_clip_restatement_record(
            "not measured: every restatement of this leg re-runs the identical "
            "seeded simulation and returns the identical number, so the "
            "resampled distribution has zero dispersion and there is no "
            "population of draws to count. See notes.simulated_path on this block"
        )
    else:
        clip_record = _clip_restatement_record(
            status="measured",
            at_clip_bound=clip_tally["at_clip_bound"],
            usable_restatements=clip_tally["usable_restatements"],
            largest_removed_by_clip=clip_tally["largest_removed_by_clip"],
            conf_int=(
                (block.get("estimates") or {}).get("volatility_forecast", {}).get(
                    "conf_int"
                )
            ),
            reason=(
                None if clip_tally["usable_restatements"] else
                "the resampling estimator produced no finite restatement on this "
                "sample, so the count is an absence rather than a zero"
            ),
        )
    block.setdefault("notes", {})["clip_bound_restatements"] = clip_record
    return block


def _forecast_leg_uncertainty(
    leg: Mapping[str, Any],
    leg_returns: Any,
    model: str,
    horizon: int,
) -> Optional[Dict[str, Any]]:
    """Precision for one position leg's `volatility_forecast`.

    The two branches of the route's leg loop are DIFFERENT statistics and are
    disclosed as such:

      limited - the leg fell below the history gate and its forecast is the leg's
        own sample standard deviation.  That is a closed-form order statistic of
        the measured series, so it needs no optimiser and IS resampled, through
        `engine_risk_statistics`' existing vectorised restatement, at the
        module's full standard draw count.

      fitted  - the leg ran the same model as the portfolio.  Measuring it would
        mean re-running the ARCH optimiser once per draw, and this export cannot
        afford that once per leg: see the module header.  So the estimator is
        NOT RUN, and the leg publishes the truth - estimated, measured on its own
        return series, not separately measured, with the reason and with the
        observation count, AR(1) and effective sample size that ARE known.  It
        returns a block of the same shape as a measured one, built by the same
        function, so a consumer's reader does not have to know which legs are
        which in order to read either.

    `None` means the leg published no finite forecast, so there is nothing to
    classify.  A null is an absence, not an estimate, and ENV-020 does not count
    it - the route publishes the reason under `coverage.withheld` instead.
    """
    published = leg.get("volatility_forecast")
    if not isinstance(published, (int, float)) or isinstance(published, bool):
        return None
    if not np.isfinite(float(published)):
        return None
    limited = bool(leg.get("is_limited_history"))
    withheld: Optional[str] = None
    #: Filled only on the limited branch, and read only there.  See
    #: `_observed_usable_count`: the fitted branch never runs its estimator, so it
    #: has no denominator to count.
    limited_tally: Dict[str, Any] = {"restatements": 0, "usable_restatements": None}
    if limited:
        # The mapping is keyed by the ESTIMATOR's own name, not by the published
        # one: `measure_estimate_uncertainty` looks the resampled distribution up
        # under the name `statistic_names` maps the published field to, so a
        # mapping keyed on the published field resolves to nothing and the guard
        # reports "no resampling estimator is registered". Keying it the other way
        # round is not a harmless no-op - it is a silently absent band.
        statistics: Any = {
            "annual_volatility": _observed_usable_count(
                engine_risk_statistics(0.0)["annual_volatility"], limited_tally
            )
        }
        names = {"volatility_forecast": "annual_volatility"}
        estimator = (
            "engine_risk_statistics' annual_volatility: the vectorised "
            "restatement of this leg's own expression, ticker_returns.std() * "
            "sqrt(252), taken because a limited-history leg's forecast is its own "
            "sample standard deviation and not a fitted model. A closed-form "
            "order statistic needs no optimiser, so this leg is resampled at the "
            "module's full standard draw count"
        )
    else:
        statistics = volatility_forecast_statistics(
            model, horizon, fields=("volatility_forecast",)
        )
        names = {}
        withheld = (
            "not measured: this leg's re-fit estimator was declared too expensive "
            "to run, so it was never evaluated rather than having run and failed. "
            "The measurement that was declined, the draw count it would have used "
            "and the cost that decided it are published once at "
            "precision.measurements_withheld. What this leg does publish, because "
            "it costs nothing and it is true, is on this block: the measured "
            "observation count, the AR(1) and the effective sample size"
        )
        estimator = (
            "NOT RUN. volatility_forecast_statistics would re-fit the same model "
            "on each circular moving-block resample of this leg's own return "
            "series through the engine's own volatility_forecast_point, and it is "
            "declared here rather than executed: see estimator_withheld on this "
            "block. The estimator is published rather than deleted so the "
            "measurement that was declined is reproducible by anyone who wants to "
            "pay for it"
        )
    block = measure_estimate_uncertainty(
        _finite_return_values(leg_returns),
        statistics,
        {"volatility_forecast": published},
        scope=(
            "forecast_risk.positions: this leg's own volatility_forecast, "
            "measured on the leg's own return observations and not the "
            "portfolio's"
        ),
        statistic_names=names,
        # A limited leg's statistic is a closed-form reduction, so it is cheap
        # and gets the module's full standard draw count.  A fitted leg's
        # statistic is an optimiser run, and this export cannot afford one per
        # leg - so it is not run at a reduced count either, because a percentile
        # interval narrowed past its own floor is a figure that describes
        # nothing.  The declined count and the rule that declined it are
        # published on the block, never silent.
        resamples=(
            UNCERTAINTY_BOOTSTRAP_RESAMPLES if limited
            else FORECAST_PORTFOLIO_REFIT_RESAMPLES
        ),
        estimator_withheld=withheld,
        notes={
            "estimator": estimator,
            "limited_history_branch": limited,
            # The rule is a shared sentence about both legs' counts, so it is
            # published ONCE at precision.resample_count_rule and named here
            # rather than copied into every block.  A payload that repeats a
            # policy fourteen times is not more auditable than one that states it
            # once and says where to read it.
            "resample_count_rule": None if limited else (
                "published once at precision.resample_count_rule"
            ),
        },
    )
    # The clip-bound tally, on the SAME three-way split the rest of this block uses
    # and for the same reason: a leg whose restatements were taken, a leg whose
    # restatements were taken over a statistic the clip never touches, and a leg
    # whose restatements were never taken are three different facts and 0 must not
    # be able to stand for all three.
    if withheld is not None:
        clip_record = _unmeasured_clip_restatement_record(
            _CLIP_BOUND_UNMEASURED_REASON
        )
    elif limited_tally["usable_restatements"] is None:
        # A leg can be on the limited branch and still be too short for the
        # resampler - the two gates are not the same gate.  Then no restatement
        # exists, and a `measured` record carrying a null denominator would be a
        # count of zero out of an unknown population, which is a fourth thing and
        # not one of the three.
        clip_record = _unmeasured_clip_restatement_record(
            "not measured: this leg's own sample is below the "
            "UNCERTAINTY_MIN_OBSERVATIONS a percentile interval needs, so the "
            "resampling estimator was never called and there are no restatements "
            "to count. The block's own reason for withholding the band is under "
            "estimates.volatility_forecast.reason"
        )
    else:
        entry = (block.get("estimates") or {}).get("volatility_forecast") or {}
        clip_record = _clip_restatement_record(
            status="measured",
            at_clip_bound=0,
            usable_restatements=limited_tally["usable_restatements"],
            largest_removed_by_clip=0.0,
            conf_int=entry.get("conf_int"),
            reason=_CLIP_BOUND_NO_CLIP_REASON,
        )
    block.setdefault("notes", {})["clip_bound_restatements"] = clip_record
    # An AR(1)-derived effective sample size legitimately EXCEEDS the observation
    # count when the series is negatively autocorrelated: the Quenouille figure
    # is n(1-rho)/(1+rho), and a leg of daily equity returns is often slightly
    # negative, so 71 effective observations out of 59 actual is the formula
    # behaving correctly - negative correlation genuinely raises the precision of
    # a mean.  It reads as an impossibility, though, so it is stated rather than
    # left for a reader to puzzle over.
    #
    # Deliberately NOT bounded by n.  Capping it would understate the precision
    # the formula reports, which is the opposite error.  The tail statistic in
    # risk_contribution IS bounded, and the two are not inconsistent: there the
    # population is a bounded SUBSET of the series, so an effective count above
    # that subset is an artefact of a small sample; here the population is the
    # whole sample and the excess is a property of a mean.
    if isinstance(block, dict):
        _obs = block.get("observations")
        _ar1 = (block.get("autocorrelation") or {}) if isinstance(
            block.get("autocorrelation"), dict
        ) else {}
        _eff = _ar1.get("effective_n")
        if (
            isinstance(_obs, (int, float))
            and isinstance(_eff, (int, float))
            and float(_eff) > float(_obs)
        ):
            block.setdefault("notes", {})
            if isinstance(block["notes"], dict):
                block["notes"]["effective_n_exceeds_observations"] = {
                    "effective_n": _eff,
                    "observations": _obs,
                    "ar1": _ar1.get("ar1"),
                    "explanation": (
                        "the AR(1) is negative, so the Quenouille effective "
                        "sample size n(1-rho)/(1+rho) exceeds n. That is the "
                        "formula behaving correctly - negatively autocorrelated "
                        "returns give a more precisely estimated mean - and the "
                        "figure is deliberately NOT capped at n, because capping "
                        "would understate the precision it reports."
                    ),
                }
    return block


def _forecast_finite(value: Any) -> Optional[float]:
    """`value` as a finite float, or ``None``.

    An absence, never 0.0.  A null forecast is a forecast that could not be
    produced, and turning that into a zero loss or a zero volatility is the
    defect this section's own history is a warning about.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if np.isfinite(float(value)) else None


def _forecast_tail_clip_high(model: str) -> float:
    """The loss-side ceiling the fitted models clip `var_forecast` at.

    EGARCH's log-variance recursion can reach a non-positive loss, so its tail is
    clipped at 0.0; GARCH and EWMA use the -0.001 floor.  Read from the same
    branch the engine takes rather than assumed, because publishing a formula
    with the wrong bound would make `derivation_residual` look like a defect.
    """
    return 0.0 if str(model).upper() == "EGARCH" else TAIL_CLIP_HIGH


def _clip_point_record(
    published: Any,
    raw: Any,
    *,
    raw_basis: str,
) -> Dict[str, Any]:
    """How far the clip moved ONE published point, and by how much.

    `annualized_volatility_at_clip_bound` already exists in the per-leg
    `derivation_precondition_evidence` prose and answers the boolean.  What a
    reader cannot do with a boolean is tell how far it moved, so the raw and the
    distance are published beside it here.  `clip_removed` is exactly 0.0 when the
    bound was not active, which is the case that makes the non-zero ones legible.
    """
    published_value = _forecast_finite(published)
    raw_value = _forecast_finite(raw)
    at_bound = (
        None if published_value is None else
        bool(published_value <= FORECAST_VOL_CLIP_LOW
             or published_value >= FORECAST_VOL_CLIP_HIGH)
    )
    return {
        "published": published_value,
        "raw_volatility_forecast": raw_value,
        "raw_volatility_forecast_basis": raw_basis,
        "at_clip_bound": at_bound,
        "clip_removed": (
            None if (published_value is None or raw_value is None)
            else float(raw_value - published_value)
        ),
    }


def _forecast_volatility_clip_block(
    *,
    model: str,
    forecast_result: Mapping[str, Any],
    positions: Mapping[str, Any],
    estimated: Mapping[str, Any],
    raw_volatility: Mapping[str, Any],
) -> Dict[str, Any]:
    """What the annualized volatility clip bound did - to the points and to the band.

    The clip is `np.clip(raw, FORECAST_VOL_CLIP_LOW, FORECAST_VOL_CLIP_HIGH)` in
    `volatility_forecast_point`, so it is applied to the published headline AND to
    every restatement the band is read off.  Both run through the same function, so
    the two cannot drift; what they could do - and did - was say nothing about it.

    `restatements` is read off the blocks' own `notes.clip_bound_restatements`
    rather than recounted here, so the count published on this node and the count
    published beside the interval it describes are the same object.  `point` reads
    the engine's pre-clip `raw_volatility_forecast`, which the route previously
    dropped entirely: a leg with no fitted model behind it has no raw, and that is
    published as a null with the reason rather than as a raw equal to its own
    published value.
    """
    raws = dict(raw_volatility or {})
    fitted_raw = (
        "the engine's own raw_volatility_forecast for this leg - the same fit, "
        "before np.clip. clip_removed is raw minus published and is exactly 0.0 "
        "when the bound was not active"
    )
    no_fit_raw = (
        "no raw: this leg fell below the history gate, so its volatility_forecast "
        "is its own sample standard deviation, computed without the fitted models' "
        "clip bounds, and there is no pre-clip value because no clip was applied"
    )
    portfolio_point = _clip_point_record(
        forecast_result.get("volatility_forecast"),
        forecast_result.get("raw_volatility_forecast"),
        raw_basis=(
            "the engine's own raw_volatility_forecast for the PORTFOLIO leg - the "
            "same fit, before np.clip. clip_removed is raw minus published and is "
            "exactly 0.0 when the bound was not active"
        ),
    )
    portfolio_record = (
        ((estimated.get("portfolio") or {}).get("notes") or {}).get(
            "clip_bound_restatements"
        )
    )
    leg_points: Dict[str, Any] = {}
    leg_records: Dict[str, Any] = {}
    for ticker, leg in (positions or {}).items():
        if not isinstance(leg, Mapping):
            continue
        limited = bool(leg.get("is_limited_history"))
        leg_points[ticker] = _clip_point_record(
            leg.get("volatility_forecast"),
            None if limited else raws.get(ticker),
            raw_basis=no_fit_raw if limited else fitted_raw,
        )
        leg_records[ticker] = (
            ((estimated.get("positions") or {}).get(ticker) or {}).get("notes") or {}
        ).get("clip_bound_restatements") or _unmeasured_clip_restatement_record(
            "not measured: this leg published no restatements, so there is no "
            "population of draws to count. See "
            "precision.estimated_statistics.positions.<ticker> for what it did "
            "publish"
        )
    measured = sorted(
        key for key, record in leg_records.items()
        if record.get("status") == "measured"
    )
    unmeasured = sorted(
        key for key, record in leg_records.items()
        if record.get("status") != "measured"
    )
    return {
        "bounds": {
            # The LOW bound is model-dependent and the HIGH bound is not, which is
            # why publishing one number for both would be wrong on an EGARCH
            # request.  Read through the same branch `volatility_forecast_point`
            # takes rather than restated.
            "low": (
                EGARCH_VOL_CLIP_LOW if str(model).upper() == "EGARCH"
                else FORECAST_VOL_CLIP_LOW
            ),
            "high": FORECAST_VOL_CLIP_HIGH,
            "model": model,
            "low_bound_basis": (
                "EGARCH's log-variance recursion can collapse, so its low bound is "
                "EGARCH_VOL_CLIP_LOW (0.0); GARCH and EWMA use "
                f"FORECAST_VOL_CLIP_LOW ({FORECAST_VOL_CLIP_LOW}). The high bound is "
                f"FORECAST_VOL_CLIP_HIGH ({FORECAST_VOL_CLIP_HIGH}) for all three. "
                "All read from app/services/analytics_engine.py, which is also "
                "where the legacy per-leg evidence string "
                "`annualized_volatility_at_clip_bound` is worded against the "
                "FORECAST pair - the two agree whenever the model is not EGARCH"
            ),
        },
        "declared_at": (
            "app/services/analytics_engine.py: FORECAST_VOL_CLIP_LOW / "
            "FORECAST_VOL_CLIP_HIGH, applied inside volatility_forecast_point, "
            "which is the single function the published headline and every "
            "restatement of it both run through"
        ),
        "denominator_rule": CLIP_BOUND_COUNT_DENOMINATOR,
        "no_divergence_threshold": (
            "no threshold on the size of a forecast is applied, and none is "
            "published, because none separates a genuine extreme from a divergent "
            "one. Measured on 5,185 real EGARCH(1,1) fits (.scratch/v5-review/"
            "13-overflow-discriminator.md §2): thirty candidate discriminators were "
            "scored and 30 of 30 are non-separable - no threshold on any of them "
            "puts the two sets in disjoint ranges. The best principled predicate, "
            "the model-implied ln E[sigma^2] exceeding ln DBL_MAX, wrongly refuses "
            "6.0 % of genuine forecasts while missing 21.3 % of divergences, and "
            "the four quantities that do separate in-sample hold out at a coin "
            "flip (P(zero out-of-sample errors) 0.48-0.52 over 400 repeats). The "
            "reason is structural: for any beta < 1 the EGARCH conditional "
            "variance is lognormal with a finite expectation, so no parameter set "
            "makes the model assert a nonexistent forecast, and beta approaching 1 "
            "asserts an arbitrarily large one continuously. THIS BLOCK PUBLISHES "
            "WHAT WAS CLIPPED RATHER THAN TRYING TO DETECT DIVERGENCE, which is "
            "the only one of the two that cannot be wrong about a real forecast"
        ),
        "point": {
            "portfolio": portfolio_point,
            "positions": leg_points,
            "at_clip_bound_portfolio": portfolio_point["at_clip_bound"],
            "at_clip_bound_positions": sorted(
                key for key, value in leg_points.items()
                if value.get("at_clip_bound")
            ),
            "point_basis": (
                "the BOOLEAN is already published, in prose, on each leg's "
                "precision.derived_values['positions.<ticker>.var_forecast']."
                "derivation_precondition_evidence, which reads "
                "'annualized_volatility_at_clip_bound is <bool>: the published leg "
                "volatility is <value> against bounds [...]'. What a boolean "
                "cannot say is HOW FAR the value moved, so raw_volatility_forecast "
                "and clip_removed are published here beside it"
            ),
        },
        "restatements": {
            "portfolio": portfolio_record,
            "positions": leg_records,
            "denominator_scope": (
                "usable restatements, per leg and per the portfolio leg, counted "
                "independently - they are not one pooled population, because each "
                "leg is re-fitted on its own return series at its own draw count"
            ),
            "legs_with_a_measured_count": measured,
            "legs_whose_count_is_unmeasured": unmeasured,
            "measured_leg_count": len(measured),
            "unmeasured_leg_count": len(unmeasured),
            "measured_leg_count_basis": (
                "read off each leg's own notes.clip_bound_restatements rather than "
                "restated, so a leg cannot be claimed as counted without its own "
                "block saying so"
            ),
        },
    }


def _forecast_measured_names(estimated: Mapping[str, Any]) -> List[str]:
    """Which fitted quantities actually carry a MEASURED interval, as dotted paths.

    Read off the blocks themselves rather than restated, so a leg whose forecast
    could not be produced drops out of the list instead of being claimed, and so a
    leg whose estimator was withheld is reported as NOT measured rather than
    counted as if it had been.  The second point is the reason this is not a
    hand-maintained list: a leg block exists for every leg that published a
    forecast, and existence is not measurement.
    """
    names: List[str] = []
    portfolio = (estimated.get("portfolio") or {}).get("estimates") or {}
    names.extend(
        f"portfolio.estimates.{name}" for name, entry in sorted(portfolio.items())
        if (entry or {}).get("status") == "computed"
    )
    for ticker, block in (estimated.get("positions") or {}).items():
        entry = ((block or {}).get("estimates") or {}).get("volatility_forecast")
        if (entry or {}).get("status") == "computed":
            names.append(f"positions.{ticker}.estimates.volatility_forecast")
    return sorted(names)


def _forecast_precision_block(
    *,
    model: str,
    horizon: int,
    forecast_result: Mapping[str, Any],
    positions: Mapping[str, Any],
    estimated: Mapping[str, Any],
    raw_volatility: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Assemble the three classes into the one `precision` node the route publishes.

    `estimated` is the measured half, already computed by
    `_forecast_portfolio_uncertainty` and `_forecast_leg_uncertainty` on their own
    threads.  This function only classifies the rest and records the coverage, so
    that the coverage figure cannot drift from what was actually classified: it is
    summed from the classifications themselves rather than asserted alongside them.

    `raw_volatility` is the pre-clip terminal annualized volatility the ENGINE
    already computed for each leg, keyed by ticker.  The route used to drop it, so
    a published 1.20 was indistinguishable from a genuine one; it is read here and
    never written back into `positions`, which stays exactly as it was.
    """
    tail = forecast_result.get("tail_measure") or {}
    h = int(max(1, int(horizon)))
    h_factor = float(np.sqrt(h / 252.0))
    z_multiplier = _forecast_finite(tail.get("var_z_multiplier")) or TAIL_Z_MULTIPLIER
    es_multiplier = _forecast_finite(tail.get("cvar_es_multiplier")) or TAIL_ES_MULTIPLIER
    return_space = _forecast_finite(tail.get("return_space_volatility"))
    clip_high = _forecast_tail_clip_high(model)

    derived: Dict[str, Any] = {}
    withheld: List[Dict[str, Any]] = []

    def add(key: str, entry: Dict[str, Any]) -> None:
        derived[key] = entry

    # -- the portfolio's two tail measures ------------------------------------
    for name, multiplier, source, target in (
        ("var_forecast", z_multiplier, "var_z_multiplier", return_space),
        ("cvar_forecast", es_multiplier, "cvar_es_multiplier", return_space),
    ):
        path = f"{FORECAST_PRECISION_PATH_PREFIX}.portfolio.{name}"
        published = _forecast_finite(forecast_result.get(name))
        if published is None or target is None:
            withheld.append({
                "at": path,
                "reason": (
                    "not classified: the value is null, so it is an absence rather "
                    "than a point estimate and carries no precision to disclose"
                ),
            })
            continue
        restated = float(
            np.clip(-target * multiplier, TAIL_CLIP_LOW, clip_high)
        )
        add(name, _forecast_derived_value(
            published_at=[path],
            formula=(
                f"clip(-return_space_volatility * {source}, "
                f"{TAIL_CLIP_LOW}, {clip_high})"
            ),
            inputs={
                "return_space_volatility": target,
                source: multiplier,
                "clip_bounds": [TAIL_CLIP_LOW, clip_high],
            },
            inputs_classification={
                "return_space_volatility": {
                    "classification": "estimated",
                    "published_at": [
                        f"{FORECAST_PRECISION_PATH_PREFIX}.portfolio.tail_measure"
                        f".return_space_volatility"
                    ],
                    "measured_at": [
                        "precision", "estimated_statistics", "portfolio",
                        "estimates", "return_space_volatility",
                    ],
                },
                source: {
                    "classification": "declared_constant",
                    "published_at": [
                        f"{FORECAST_PRECISION_PATH_PREFIX}.portfolio.tail_measure"
                        f".{source}"
                    ],
                    "declared_at": [
                        "precision", "declared_constants", "constants", source,
                    ],
                },
                "clip_bounds": {
                    "classification": "declared_constant",
                    "published_at": [
                        f"{FORECAST_PRECISION_PATH_PREFIX}.portfolio.tail_measure"
                        f".{source.replace('_multiplier', '_clip_bounds')}"
                    ],
                    "declared_at": [
                        "precision", "declared_constants", "table",
                    ],
                },
            },
            inherits_precision_from="return_space_volatility",
            inherits_precision_at=(
                "precision", "estimated_statistics", "portfolio",
                "estimates", "return_space_volatility",
            ),
            inheritance_status="resolved",
            inheritance_reason=(
                "the entire precision of this value is the precision of the fitted "
                "conditional sigma it multiplies, which is measured on "
                "precision.estimated_statistics.portfolio.estimates."
                "return_space_volatility. Nothing else is estimated here: the "
                f"multiplier is the declared {source} constant and the clip bounds "
                "are design limits"
            ),
            precision_inheritance_factor=multiplier,
            derivation_residual=published - restated,
        ))

    # -- each position leg's tail measure -------------------------------------
    for ticker, leg in positions.items():
        path = f"{FORECAST_PRECISION_PATH_PREFIX}.positions.{ticker}.var_forecast"
        published = _forecast_finite(leg.get("var_forecast"))
        vol = _forecast_finite(leg.get("volatility_forecast"))
        if published is None or vol is None:
            withheld.append({
                "at": path,
                "reason": (
                    "not classified: the leg's forecast is null, so there is no "
                    "point estimate and therefore no precision to disclose"
                ),
            })
            continue
        limited = bool(leg.get("is_limited_history"))
        # Whether the leg's own sigma was MEASURED is read off the leg's block
        # rather than assumed from the branch.  A pointer has to describe what
        # is actually at the far end of it, and the two can disagree: a leg whose
        # estimator was withheld still has a block, and inheriting from it means
        # inheriting an absence.  That is stated, not papered over.
        leg_entry = (
            ((estimated.get("positions") or {}).get(ticker) or {}).get("estimates")
            or {}
        ).get("volatility_forecast") or {}
        leg_measured = leg_entry.get("status") == "computed"
        if limited:
            # The limited branch computes its own tail from the sample standard
            # deviation and applies NO tail clip, so claiming one would put a
            # residual on the payload that is really a missing bound.
            restated = float(-vol * z_multiplier * h_factor)
            formula = (
                f"-volatility_forecast * {z_multiplier} * sqrt({h} / 252)"
            )
            clip_note = (
                "this leg fell below the history gate, so its forecast is its own "
                "sample standard deviation and its tail is computed without the "
                "fitted models' clip bounds"
            )
        else:
            restated = float(
                np.clip(-vol * z_multiplier * h_factor, TAIL_CLIP_LOW, clip_high)
            )
            formula = (
                f"clip(-volatility_forecast * var_z_multiplier * sqrt({h} / 252), "
                f"{TAIL_CLIP_LOW}, {clip_high})"
            )
            clip_note = (
                "the fitted leg's return-space sigma is its own published "
                "annualized volatility times sqrt(h / 252), which is an identity "
                "of the cumulative-variance path - exact unless the published "
                "annualized clip bounds are active on this leg, and "
                "derivation_residual says which case this is"
            )
        # The identity above reads the PUBLISHED (clipped) leg volatility.  The
        # clip only breaks it when the published value sits on a bound, so that is
        # published too and `derivation_residual` is the proof either way.
        clip_at_bound = bool(
            not limited and (
                vol <= FORECAST_VOL_CLIP_LOW or vol >= FORECAST_VOL_CLIP_HIGH
            )
        )
        add(
            f"positions.{ticker}.var_forecast",
            _forecast_derived_value(
                published_at=[path],
                formula=formula,
                inputs={
                    "volatility_forecast": vol,
                    "var_z_multiplier": z_multiplier,
                    "horizon_days": h,
                    "annualized_volatility_clip_bounds": [
                        FORECAST_VOL_CLIP_LOW, FORECAST_VOL_CLIP_HIGH,
                    ],
                    **({} if limited else {"clip_bounds": [TAIL_CLIP_LOW, clip_high]}),
                },
                # Whether the published leg volatility is sitting on a clip bound
                # is a property OF THE DERIVATION, not an input to it, so it is a
                # sibling of the formula rather than a restated number in it.
                derivation_precondition=(
                    "the identity return_space_volatility = "
                    "volatility_forecast * sqrt(h / 252) holds only while the "
                    "published annualized clip bounds are not active on this leg"
                ),
                derivation_precondition_met=not clip_at_bound,
                derivation_precondition_evidence=(
                    "annualized_volatility_at_clip_bound is "
                    f"{clip_at_bound}: the published leg volatility is "
                    f"{vol!r} against bounds [{FORECAST_VOL_CLIP_LOW}, "
                    f"{FORECAST_VOL_CLIP_HIGH}]. derivation_residual is the proof "
                    "either way - a zero residual means the identity held exactly"
                ),
                inputs_classification={
                    "volatility_forecast": {
                        "classification": "estimated",
                        "published_at": [
                            f"{FORECAST_PRECISION_PATH_PREFIX}.positions."
                            f"{ticker}.volatility_forecast"
                        ],
                        "measured_at": [
                            "precision", "estimated_statistics", "positions",
                            ticker, "estimates", "volatility_forecast",
                        ],
                        # `estimated` says what KIND of number this is, not that
                        # its precision was measured, and those are different
                        # claims. Publishing them as one is how a reader ends up
                        # believing a leg carries a band it does not, so the
                        # classification carries its own status and the reason it
                        # reads the leg's block rather than asserting either way.
                        "measurement_status": (
                            "measured" if leg_measured
                            else "estimated_but_not_separately_measured"
                        ),
                        "measurement_status_basis": (
                            "read off this leg's own block at measured_at; see "
                            "precision.measurements_withheld for the unmeasured "
                            "case"
                        ),
                    },
                    "var_z_multiplier": {
                        "classification": "declared_constant",
                        "published_at": [
                            f"{FORECAST_PRECISION_PATH_PREFIX}.portfolio."
                            f"tail_measure.var_z_multiplier"
                        ],
                        "declared_at": [
                            "precision", "declared_constants", "constants",
                            "var_z_multiplier",
                        ],
                    },
                    "horizon_days": {
                        "classification": "declared_constant",
                        "published_at": [
                            f"{FORECAST_PRECISION_PATH_PREFIX}.portfolio."
                            f"tail_measure.var_horizon_days"
                        ],
                        "declared_at": [
                            "precision", "declared_constants", "constants",
                            "var_horizon_days",
                        ],
                    },
                    "annualized_volatility_clip_bounds": {
                        "classification": "declared_constant",
                        "published_at": [
                            f"{FORECAST_PRECISION_PATH_PREFIX}.portfolio."
                            f"tail_measure.volatility_forecast_units"
                        ],
                        "declared_at": [
                            "precision", "declared_constants", "table",
                        ],
                    },
                    **({
                        "clip_bounds": {
                            "classification": "declared_constant",
                            "published_at": [
                                f"{FORECAST_PRECISION_PATH_PREFIX}.portfolio."
                                f"tail_measure.var_clip_bounds"
                            ],
                            "declared_at": [
                                "precision", "declared_constants", "table",
                            ],
                        }
                    } if not limited else {}),
                },
                inherits_precision_from="volatility_forecast",
                inherits_precision_at=(
                    "precision", "estimated_statistics", "positions", ticker,
                    "estimates", "volatility_forecast",
                ),
                # The pointer is KEPT even when the target is itself undisclosed.
                # Dropping it would be tidier and less true: the leg's tail really
                # does inherit whatever precision this leg's own sigma has, and the
                # target node is right there saying what that is.  What changes is
                # the STATUS, so nothing claims an inheritance that was not
                # measured.
                inheritance_status=(
                    "resolved" if leg_measured
                    else "target_is_itself_undisclosed"
                ),
                # `*` and not a bare tuple: passing the conditional as ONE
                # argument makes the joiner stringify a tuple, and the payload
                # then publishes a repr of a tuple of sentences.
                inheritance_reason=_forecast_sentences(
                    *((
                        "the entire precision of this value is the precision of this "
                        "leg's own fitted conditional sigma, measured on "
                        f"precision.estimated_statistics.positions.{ticker}."
                        "estimates.volatility_forecast",
                        clip_note,
                    ) if leg_measured else (
                        # NOT "there is no figure at the far end of it", which is
                        # what this said and which is FALSE: the target publishes
                        # the leg's own volatility_forecast as `point`, and it is
                        # the figure the primary fit produced.  What it does not
                        # publish is that figure's STANDARD ERROR and its INTERVAL,
                        # because this leg's re-fit estimator was never run.  An
                        # absent point and an absent interval are different
                        # absences, and the target's own `reason` says which this
                        # is - so this sentence had to agree with it.
                        #
                        # "ITSELF" is kept deliberately: `inherits_precision_status`
                        # is `target_is_itself_undisclosed`, and the reason has to
                        # explain the status word or a reader cannot tell which of
                        # the two absences the entry is reporting.
                        "the entire precision of this value would be the precision "
                        "of this leg's own fitted conditional sigma, at "
                        f"precision.estimated_statistics.positions.{ticker}."
                        "estimates.volatility_forecast - and that node is ITSELF "
                        "without a band, because this leg's estimator was withheld "
                        "rather than run, for the cost reason published at "
                        "precision.measurements_withheld",
                        "the pointer is kept because the inheritance is real and "
                        "the node it names is on this payload, and the point is "
                        "there: the target publishes this leg's own "
                        "volatility_forecast. What it does not publish is that "
                        "point's standard error and its interval, and an absent "
                        "interval is a different fact from an absent point - a "
                        "reader who took this sentence literally would conclude "
                        "the leg has no forecast at all, which is the opposite of "
                        "the case",
                        "the rest of the target's precision costs nothing and is "
                        "published: its observation count, its AR(1) and its "
                        "effective_n",
                        "the PORTFOLIO leg's sigma IS measured on this same "
                        "payload, at precision.estimated_statistics.portfolio."
                        "estimates.volatility_forecast",
                        clip_note,
                    ))
                ),
                precision_inheritance_factor=z_multiplier * h_factor,
                derivation_residual=published - restated,
            ),
        )

    # -- the ratio of the two declared multipliers ----------------------------
    # Read off the leg blocks rather than restated, so `measurements_withheld`
    # cannot claim a leg the leg's own block does not agree with.
    withheld_legs = sorted(
        ticker
        for ticker, block in (estimated.get("positions") or {}).items()
        if (block or {}).get("estimator_withheld")
    )
    ratio = _forecast_finite(tail.get("cvar_to_var_ratio"))
    ratio_paths = [
        f"{FORECAST_PRECISION_PATH_PREFIX}.portfolio.tail_measure.cvar_to_var_ratio",
        f"{FORECAST_PRECISION_PATH_PREFIX}.model_params.tail_measure.cvar_to_var_ratio",
    ]
    if ratio is None:
        withheld.extend(
            {"at": path, "reason": "not classified: the value is null"}
            for path in ratio_paths
        )
    else:
        add(
            "tail_measure.cvar_to_var_ratio",
            _forecast_derived_value(
                published_at=ratio_paths,
                formula="cvar_es_multiplier / var_z_multiplier",
                inputs={
                    "cvar_es_multiplier": es_multiplier,
                    "var_z_multiplier": z_multiplier,
                },
                inputs_classification={
                    "cvar_es_multiplier": {
                        "classification": "declared_constant",
                        "published_at": [
                            f"{FORECAST_PRECISION_PATH_PREFIX}.portfolio."
                            f"tail_measure.cvar_es_multiplier"
                        ],
                        "declared_at": [
                            "precision", "declared_constants", "constants",
                            "cvar_es_multiplier",
                        ],
                    },
                    "var_z_multiplier": {
                        "classification": "declared_constant",
                        "published_at": [
                            f"{FORECAST_PRECISION_PATH_PREFIX}.portfolio."
                            f"tail_measure.var_z_multiplier"
                        ],
                        "declared_at": [
                            "precision", "declared_constants", "constants",
                            "var_z_multiplier",
                        ],
                    },
                },
                inherits_precision_from=[
                    "cvar_es_multiplier", "var_z_multiplier",
                ],
                # Deliberately None, and this is the case the pointer test exists
                # to catch: both inputs are DECLARED CONSTANTS, so neither has a
                # sampling distribution and there is no figure anywhere to point
                # at. A path that resolved here would resolve onto another null.
                inherits_precision_at=None,
                inheritance_status="inputs_are_declared_constants",
                inheritance_reason=(
                    "not inheritable, and the absence is the answer rather than a "
                    "gap: this ratio is the ES multiplier divided by the z "
                    "multiplier, and both are declared constants read from "
                    "app/services/analytics_engine.py. Neither was estimated from "
                    "data, so neither has a sampling distribution, so there is no "
                    "figure to inherit. The ratio is exact rather than imprecise - "
                    "it is fixed by construction, which is what "
                    "cvar_to_var_ratio_fixed_by_construction already states - and a "
                    "null standard error describes that accurately"
                ),
                precision_inheritance_factor=None,
                derivation_residual=(
                    ratio - (es_multiplier / z_multiplier if z_multiplier else None)
                    if z_multiplier else None
                ),
            ),
        )

    # -- the declared constants -----------------------------------------------
    tail_paths = ("portfolio.tail_measure", "model_params.tail_measure")
    declared = {
        "classification": "declared_constant",
        "basis": (
            "the quantiles of a normal distribution and a stated request "
            "parameter. They are constants because the normal distribution's "
            "quantiles are constants, not because the risk was faked, and the "
            "engine has always published them - what was missing was any "
            "statement that they were never estimated from data"
        ),
        "table": (
            "app/services/analytics_engine.py: TAIL_CONFIDENCE_LEVEL, "
            "TAIL_Z_MULTIPLIER, TAIL_ES_MULTIPLIER, TAIL_CLIP_LOW, TAIL_CLIP_HIGH"
        ),
        "published_at": [
            f"{FORECAST_PRECISION_PATH_PREFIX}.{prefix}.{name}"
            for prefix in tail_paths
            for name in (
                "var_confidence_level", "var_horizon_days",
                "var_z_multiplier", "cvar_es_multiplier",
            )
        ],
        "constants": {
            "var_confidence_level": _forecast_declared_constant(
                "var_confidence_level",
                _forecast_finite(tail.get("var_confidence_level")),
                "app/services/analytics_engine.py: TAIL_CONFIDENCE_LEVEL - the "
                "normal quantile level the fitted models' tail is read at",
                [f"{FORECAST_PRECISION_PATH_PREFIX}.{p}.var_confidence_level"
                 for p in tail_paths],
            ),
            "var_horizon_days": _forecast_declared_constant(
                "var_horizon_days",
                tail.get("var_horizon_days"),
                "the `horizon` query parameter of GET /api/v1/analytics/"
                "forecast-risk, echoed as the number of days the tail covers. It "
                "is an input the caller chose, not a quantity this service "
                "estimated",
                [f"{FORECAST_PRECISION_PATH_PREFIX}.{p}.var_horizon_days"
                 for p in tail_paths],
            ),
            "var_z_multiplier": _forecast_declared_constant(
                "var_z_multiplier",
                z_multiplier,
                "app/services/analytics_engine.py: TAIL_Z_MULTIPLIER - the 95 % "
                "standard-normal quantile Phi^-1(0.05), applied to the fitted "
                "conditional sigma",
                [f"{FORECAST_PRECISION_PATH_PREFIX}.{p}.var_z_multiplier"
                 for p in tail_paths],
            ),
            "cvar_es_multiplier": _forecast_declared_constant(
                "cvar_es_multiplier",
                es_multiplier,
                "app/services/analytics_engine.py: TAIL_ES_MULTIPLIER - the normal "
                "expected-shortfall multiple of the same sigma, so it is the ES "
                "of the same N(0, sigma^2) the z multiplier reads",
                [f"{FORECAST_PRECISION_PATH_PREFIX}.{p}.cvar_es_multiplier"
                 for p in tail_paths],
            ),
        },
        "standard_error": None,
        "standard_error_reason": _DECLARED_CONSTANT_SE_REASON,
        "conf_int": None,
        "conf_int_reason": _DECLARED_CONSTANT_CI_REASON,
    }

    # -- coverage, summed from the classifications themselves -----------------
    # Restated inputs count.  `derived_values.var_forecast.inputs.var_z_multiplier`
    # is a second copy of a declared constant, and a key that appears twice on a
    # payload is still a key a rule will read, so it is classified rather than
    # left to be discovered by whichever rule happens to look.
    classified: List[str] = []
    restated: List[Dict[str, Any]] = []
    for name, entry in derived.items():
        classified.extend(entry["published_at"])
        for input_name, input_entry in (entry.get("inputs_classification")
                                        or {}).items():
            for at in input_entry.get("published_at") or ():
                classified.append(at)
            mirror = (
                f"{FORECAST_PRECISION_PATH_PREFIX}.precision.derived_values"
                f".{name}.inputs.{input_name}"
            )
            # The MIRROR path is what a rule reading this payload will flag, so
            # it is the mirror path that has to be classified - not only the
            # original it restates.
            classified.append(mirror)
            # NO per-entry `reason`.  The explanation is the same for every one of
            # these entries - there are ninety-odd of them on a 14-leg book - and
            # ninety-odd copies of a paragraph is ninety-odd times the bytes, the
            # drift risk, and none of the information.  It is published once as
            # `coverage.input_restatements_basis` and each entry carries the
            # FACTS that are actually specific to it: where the copy is, what it
            # restates, what kind of number it is and where that kind is
            # classified.
            restated.append({
                "at": mirror,
                "classification": input_entry.get("classification"),
                "restates": input_entry.get("published_at") or [],
                "declared_or_measured_at": input_entry.get(
                    "declared_at"
                ) or input_entry.get("measured_at"),
            })
    for entry in declared["constants"].values():
        classified.extend(entry["published_at"])
    classified.extend(declared["published_at"])
    classified = sorted(set(classified))

    return {
        "basis": FORECAST_PRECISION_BASIS,
        "classes": dict(FORECAST_PRECISION_CLASSES),
        "model": model,
        "horizon_days": h,
        "volatility_clip": _forecast_volatility_clip_block(
            model=model,
            forecast_result=forecast_result,
            positions=positions,
            estimated=estimated,
            raw_volatility=raw_volatility or {},
        ),
        "estimated_statistics": dict(estimated),
        "estimated_statistics_basis": (
            "one block per fitted quantity, each produced by "
            "measure_estimate_uncertainty over that quantity's OWN measured "
            "return series, and every block carries the same keys whether its "
            "estimator ran or was withheld - so a reader does not have to know "
            "which legs are which in order to read either. No band is published "
            "unless the re-fit estimator reproduces the published point first, so "
            "an interval on this section always describes the number printed "
            "beside it. A block whose estimator was declared too expensive to run "
            "says so on estimator_withheld, publishes bootstrap_resamples 0, and "
            "carries a null standard error with a stated reason; the declined "
            "measurement is named, not deleted"
        ),
        "derived_values": derived,
        "declared_constants": declared,
        # The one place a leg's withheld measurement is explained.  Every leg
        # block's `estimator_withheld` and every leg-derived value's
        # `inherits_precision_reason` point here rather than repeating the
        # paragraph, so the reason is stated once and the pointers to it are
        # themselves checked by the pointer test.
        "measurements_withheld": {
            "applies_to": sorted(withheld_legs),
            "applies_to_basis": (
                "the position legs whose volatility_forecast is classified "
                "estimated but was not measured. A leg that published no forecast "
                "is absent from this list because there was nothing to measure, and "
                "a leg whose estimator DID run - a limited-history leg, whose "
                "statistic is a closed-form order statistic rather than a model fit "
                "- is absent because its measurement is on "
                "precision.estimated_statistics.positions"
            ),
            "count": len(withheld_legs),
            "declined_draws_per_leg": FORECAST_LEG_REFIT_RESAMPLES_WITHHELD,
            "declared_at": [
                f"{FORECAST_PRECISION_PATH_PREFIX}.precision."
                "estimated_statistics.positions.<ticker>.estimates."
                "volatility_forecast"
            ],
            "estimator": (
                "the measurement that was declined: "
                "volatility_forecast_statistics(model, horizon) re-fitting the same "
                "model on every circular moving-block resample of that leg's own "
                "return series through the engine's own volatility_forecast_point. "
                "It is named on every leg block under notes.estimator, so the "
                "declined measurement is reproducible by anyone who wants to pay "
                "for it"
            ),
            "published_at_basis": (
                "each of these legs' own volatility_forecast, at "
                f"{FORECAST_PRECISION_PATH_PREFIX}.positions.<ticker>."
                "volatility_forecast. The list is read off the leg blocks' "
                "estimator_withheld rather than restated, so a leg cannot be "
                "claimed as withheld without its block saying so"
            ),
            "why_not_measured": _FORECAST_LEG_MEASUREMENT_WITHHELD,
            # The same cost as NUMBERS, so a reader does not have to parse a
            # paragraph to check it and a test does not have to trust a regex to
            # do so.  `why_not_measured` above is written from these, so the
            # sentence and the block cannot state different totals - which is the
            # defect this exists to make impossible rather than merely absent.
            "refit_arithmetic": {
                "scope": "measured_cost_of_the_declined_measurement",
                "book_leg_count": FORECAST_WITHHELD_BOOK_LEGS,
                "portfolio_resamples": FORECAST_WITHHELD_PORTFOLIO_RESAMPLES,
                # The original fit is not a resample.  This is the +1 that an
                # earlier version of the paragraph dropped.
                "portfolio_original_fits": 1,
                "portfolio_fits": FORECAST_WITHHELD_PORTFOLIO_FITS,
                "resamples_per_leg": FORECAST_WITHHELD_LEG_RESAMPLES,
                "leg_fits": FORECAST_WITHHELD_LEG_FITS,
                "total_fits": FORECAST_WITHHELD_TOTAL_FITS,
                "portfolio_seconds": FORECAST_WITHHELD_PORTFOLIO_SECONDS,
                "leg_seconds": FORECAST_WITHHELD_LEG_SECONDS,
                "optimiser_seconds": FORECAST_WITHHELD_OPTIMISER_SECONDS,
                "route_wall_seconds": FORECAST_WITHHELD_ROUTE_WALL_SECONDS,
                "basis": (
                    "measured on the real 14-position book, in "
                    "app/services/analytics_engine.py's own comment on "
                    "FORECAST_LEG_REFIT_RESAMPLES_WITHHELD, which derives the same "
                    "total. Every count here is interpolated into "
                    "why_not_measured rather than written into it, so the two "
                    "cannot disagree: portfolio_fits = portfolio_resamples + "
                    "portfolio_original_fits, leg_fits = resamples_per_leg * "
                    "book_leg_count, total_fits = portfolio_fits + leg_fits, and "
                    "optimiser_seconds = portfolio_seconds + leg_seconds. The "
                    "original fit is counted because it was really run and really "
                    "cost the time; it is not a resample, which is why "
                    "bootstrap_resamples on the portfolio block reads "
                    f"{FORECAST_WITHHELD_PORTFOLIO_RESAMPLES} and not "
                    f"{FORECAST_WITHHELD_PORTFOLIO_FITS}. These are the figures "
                    "the measurement was taken at, frozen at import: a caller "
                    "that reduces the live draw count changes what this section "
                    "SPENDS and must not change what it COST"
                ),
            },
        },
        "resample_count_rule": FORECAST_REFIT_COUNT_RULE,
        "coverage": {
            "basis": (
                "every key this section publishes that a precision-disclosure "
                "rule would read as an estimated quantity, classified. The list is "
                "summed from the classification entries themselves rather than "
                "asserted beside them, so a key cannot be classified in one place "
                "and forgotten in another"
            ),
            "classified_keys": classified,
            "classified_key_count": len(classified),
            "classes_used": {
                "estimated": _forecast_measured_names(estimated),
                "deterministic_derivation": sorted(derived),
                "declared_constant": sorted(
                    list(declared["constants"]) + ["tail_measure"]
                ),
            },
            "not_classified": withheld,
            "not_classified_basis": (
                "a null is an absence, not a point estimate, so it has no "
                "precision to disclose. Each is listed with its path so the "
                "absence is visible rather than inferred from a missing key. The "
                "key is named not_classified rather than withheld because a "
                "withheld FIELD is a different thing - a field the payload "
                "declined to publish at all - and a null is published"
            ),
            "input_restatements": restated,
            "input_restatements_basis": (
                "the numbers a formula repeats beside the value it produces. They "
                "are classified here so that the classified-key count covers every "
                "key on this section rather than only the ones a reader happened "
                "to look at. A formula restates its inputs so the derivation can "
                "be recomputed from the payload, and each restated copy is "
                "classified as the same kind of number as the original and points "
                "at where that classification is published. That explanation is "
                "stated HERE, once, rather than on every entry: this list has one "
                "entry per restated input - ninety on a 14-leg book - and the "
                "sentence is identical for all of them, so repeating it would buy "
                "bytes and drift risk and no information. Each entry carries what "
                "is actually specific to it: `at`, `restates`, `classification` "
                "and `declared_or_measured_at`"
            ),
        },
        "rule_limitation": (
            "a precision-disclosure rule keyed on key names alone cannot tell a "
            "declared constant from a derived value from a measured estimate: all "
            "three look like a number next to a name. This block separates them by "
            "classification, but it is still a disclosure and not a truth gate - it "
            "says how each number was determined and how tightly, not whether any "
            "of them is correct"
        ),
    }


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
        #: The series each leg's forecast was actually computed from, kept beside
        #: the published leg so the precision disclosure measures each leg on its
        #: OWN observations.  Not published: it is an input the disclosure
        #: consumes, and the leg already publishes its row counts.
        leg_returns: Dict[str, Any] = {}
        #: The PRE-CLIP terminal annualized volatility the engine computed for
        #: each fitted leg, kept for the same reason as `leg_returns` above: the
        #: precision disclosure has to say how far the clip moved a published
        #: value, and the route used to drop this number entirely, so a leg
        #: reading exactly `FORECAST_VOL_CLIP_HIGH` was indistinguishable from a
        #: leg that genuinely forecast 120 % annualized volatility.  A limited leg
        #: has no entry because its forecast is computed without the fitted
        #: models' clip bounds, so there is no pre-clip value to keep.
        leg_raw_volatility: Dict[str, Any] = {}
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
                leg_returns[ticker] = ticker_rets
                if not is_limited:
                    leg_raw_volatility[ticker] = ticker_forecast.get(
                        "raw_volatility_forecast"
                    )

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
                leg_returns.pop(ticker, None)
                leg_raw_volatility.pop(ticker, None)
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
        # The precision disclosure (ENV-020).  Every estimated quantity this
        # section publishes is one of three kinds of thing and admits a different
        # disclosure; see FORECAST_PRECISION_BASIS.  Built AFTER the response
        # skeleton so it can only read published values, never influence them,
        # and each measured block runs on its own thread because a re-fit
        # bootstrap is CPU-bound and would otherwise hold the event loop for the
        # better part of a minute.
        estimated_statistics: Dict[str, Any] = {}
        estimated_statistics["portfolio"] = await asyncio.to_thread(
            _forecast_portfolio_uncertainty,
            portfolio_returns, model, horizon, forecast_result,
        )
        estimated_statistics["positions"] = {}
        for ticker, leg in positions.items():
            leg_block = await asyncio.to_thread(
                _forecast_leg_uncertainty,
                leg, leg_returns.get(ticker), model, horizon,
            )
            if leg_block is not None:
                estimated_statistics["positions"][ticker] = leg_block
        # ENV-016: a section that withholds something must name it, whatever its
        # own status says.  The per-leg refit is declined deliberately and
        # declared inside the precision block, but a reader who looks only at
        # `status` and `warnings` - which is what a consumer deciding whether to
        # trust a number does - would see `available` beside an empty list and
        # conclude every leg was measured.  On this book 14 of 15 were not.  The
        # declaration was reachable only by knowing to go looking for
        # `estimator_withheld` under a ticker key, which is not a disclosure a
        # consumer can rely on finding.  Name it where the rest of this section's
        # degradations are named.
        leg_blocks = estimated_statistics["positions"]
        withheld_legs = sorted(
            ticker
            for ticker, block in leg_blocks.items()
            if isinstance(block, dict) and block.get("estimator_withheld")
        )
        if withheld_legs:
            warnings_list.append(
                {
                    "code": "forecast_precision_leg_refit_declined",
                    "legs_published": len(leg_blocks),
                    # Deliberately NOT named `..._interval` or anything else
                    # carrying an uncertainty token.  ENV-020 accepts a finite
                    # value on a token-matching key as a precision figure, and
                    # this is a COUNT of legs that declined one - so a name like
                    # `legs_without_a_measured_interval` satisfied the precision
                    # rule with a count, which is precisely the hollow pass that
                    # rule was just tightened to stop.  Caught by this section's
                    # own control test, which could no longer turn red.
                    "legs_with_declined_measurement": len(withheld_legs),
                    "tickers": withheld_legs,
                    "message": (
                        f"{len(withheld_legs)} of {len(leg_blocks)} leg "
                        "volatility forecasts publish no standard error and no "
                        "interval. Measuring one means re-fitting that leg's ARCH "
                        "model on every resample - a full optimiser run per draw - "
                        "and this export cannot afford one per leg: at the module's "
                        "own floor for a percentile interval to mean anything, the "
                        "14-position book spent ~51 s of extra refit time and the "
                        "section overran the 180 s budget it is assembled under, "
                        "which left three later sections published unavailable. "
                        "Each such leg publishes its own observation count, AR(1) "
                        "and effective sample size, and the declined measurement is "
                        "declared once at data.precision.measurements_withheld and "
                        "per leg at data.precision.estimated_statistics.positions."
                        "<ticker>.estimator_withheld. The PORTFOLIO leg is measured, "
                        "with a standard error, a 95% interval and an effective "
                        "sample size."
                    ),
                }
            )
        response = {
            "model": model,
            "horizon": horizon,
            "portfolio": {
                "volatility_forecast": forecast_result.get("volatility_forecast"),
                "var_forecast": forecast_result.get("var_forecast"),
                "cvar_forecast": forecast_result.get("cvar_forecast"),
                "confidence_interval": forecast_result.get("confidence_interval"),
                # WHY there is no interval. A `confidence_interval: null` with no
                # stated reason is indistinguishable from a bug, and a reader who
                # has been burned before assumes the worse one. The engine
                # computed no sampling distribution for a conditional-volatility
                # point estimate, and says so rather than inventing one.
                "confidence_interval_status": forecast_result.get(
                    "confidence_interval_status"
                ),
                "confidence_interval_reason": forecast_result.get(
                    "confidence_interval_reason"
                ),
                # Declares the level, units, horizon, sign convention and both
                # z-multipliers behind var_forecast/cvar_forecast, so the ratio
                # between them is explicable rather than a surprise.
                "tail_measure": forecast_result.get("tail_measure"),
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
            "methodology": f"Volatility forecasting using {model} model with {horizon}-day horizon",
            "precision": _forecast_precision_block(
                model=model,
                horizon=horizon,
                forecast_result=forecast_result,
                positions=positions,
                estimated=estimated_statistics,
                raw_volatility=leg_raw_volatility,
            ),
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
        # below still runs on the unmasked frame. The window is resolved by the
        # canonical rule - the same `holding_provenance` read every other section
        # makes - and the masked leg is handed the canonical start with the buy
        # price withheld, so this section can no longer infer a different date
        # from its own price window. It then counts the window in the unit every
        # other section uses (aligned return rows), not in held price rows, which
        # is what made this the one section that reported a holding window one
        # row longer than its three siblings.
        provenance = await holding_provenance(
            data_service, holdings, calculation_tickers, end=end,
        )
        holding_dict, _effectives, _local_detail = holding_window_detail(
            price_data_dict, canonical_holding_window_input(provenance["detail"])
        )
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
        holding_days, _holding_mask = holding_window_observation_count(
            holding_frame if not holding_frame.empty else None,
            provenance["start"],
        )
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
        holding_context = publish_holding_coverage(
            detail=provenance["detail"],
            per_ticker=per_ticker,
            requested_start=start,
            requested_end=end,
            covered_days=holding_days,
            evidence_window=provenance["evidence_window"],
            # XS-001: `port_ret` is the wide per-leg frame and keeps dates on
            # which some leg was unpriced, so `holding_days` counts a different
            # population from the 12 sections that publish a whole-book complete
            # count. Naming it accurately is what keeps 39 and 20 from reading
            # as a contradiction. The count itself is NOT changed - narrowing the
            # frame to make it match would discard the per-leg truth.
            covered_days_scope=HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE,
        )
        # The held PRICE-row count is kept beside the canonical count so nothing
        # is lost: it is one larger, because the bar on the start date is the
        # first held price and has no held predecessor to produce a return.
        holding_context["holding_window_price_rows"] = (
            int(len(holding_frame)) if not holding_frame.empty else 0
        )
        holding_context["holding_window_price_rows_scope"] = "held_price_rows_incl_start_bar"
        # Model evidence lives in its own object: a full-history regression is
        # not truncated to the holding window, so it publishes its own window,
        # observation count, latest observation and annualization flag. The
        # FRAME the regression was handed is described by `full_history`; the
        # SAMPLE it actually fitted on is a subset of that frame and is only
        # knowable once the fit has run, so `history_coverage` is built below
        # the fit rather than above it. Building it above the fit is what made
        # `model_observation_count` a copy of the frame's 175 rows while the
        # regression used 101 - the comment here used to assert that the counts
        # "are the observations the model used", and they were not.
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

        # Fetch benchmark returns via BenchmarkService (^NSEI)
        benchmark_returns = None
        try:
            benchmark_returns = await benchmark_service.get_returns(start=start, end=end)
        except Exception:
            logger.warning("Benchmark data unavailable")

        # Perform factor exposure analysis using analytics engine
        factor_result = await analytics_engine.factor_exposure_analysis(
            price_data, 
            benchmark_data=benchmark_returns,
            weights=factor_weights
        )

        # AFTER the fit, so the count is the fit's own sample rather than the
        # frame handed to it.
        history_coverage = _model_history_coverage(
            holding_context,
            full_history,
            model_sample=_factor_fit_sample(factor_result, full_history),
        )
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


#: What the concentration cross-section is measured over, and therefore why it
#: carries no `as_of`. Every number on this route is a function of ONE set of
#: market-value weights read from the live position rows, so the only clock the
#: inputs carry is the moment the quote was written. A refresh instant is not an
#: observation date, and the delivered daily bars this route never reads cannot
#: stand in for one.
CONCENTRATION_VALUATION_BASIS = (
    "cross_section_of_live_quoted_market_value_weights_normalized_to_100_percent"
)

CONCENTRATION_NO_VALUATION_DATE_WARNING = (
    "No valuation date: concentration is a cross-section of live-quoted "
    "market-value weights, and a quote publishes the instant it was refreshed "
    "rather than an observation date, so these concentration indices have no "
    "as_of to report. The daily close series the other analytics sections date "
    "themselves by was not read here; a reader who needs a dated book must read "
    "that series rather than treat this snapshot's clock as one."
)

# --- The scale `diversification_score` is read on ---------------------------
# `diversification_score` is a 0-100 index that the route used to publish with
# no scale, no `n` and no formula, so nothing said what 98.5 meant or what would
# make it 100. The ENGINE measures the index and now declares it
# (`analytics_engine.CONCENTRATION_DIVERSIFICATION_SCALE` and the two formula
# strings, published on both its measured and its empty result), so there is
# exactly ONE declaration of the scale and this route owns only the MAPPING of
# it into the payload.
#
# A second copy of that text here was shadowed dead weight: every measured and
# every engine-empty path forwarded the engine's object, so the only reader of
# the local copy was this route's own no-book early return, which never calls the
# engine. It has been deleted rather than kept "in case", because two texts for
# one scale is the same defect as one object published under two names. What the
# deleted copy said that the engine's does not is handed to the engine's owner
# in the wave report, not reimplemented here.
CONCENTRATION_DIVERSIFICATION_FORWARDED_KEYS = (
    "scale",
    "diversification_score_formula",
    "diversification_ratio_formula",
    "effective_positions_note",
)


def _concentration_diversification_disclosure(
    concentration_result: Mapping[str, Any],
) -> Dict[str, Any]:
    """The engine's scale, formulas and holding count, forwarded unchanged.

    The values are the engine's, and the objects are the engine's own objects:
    the `scale` dict is forwarded by reference, so the payload's scale and the
    scale the index was measured under cannot be two equal-but-separate objects
    that drift apart on a later edit. `n_holdings` is reconciled against
    `by_weight` - the same population this section already publishes - only when
    the engine published no count, so the denominator of the published formula
    and the keys of `by_weight` cannot disagree. Nothing here recomputes the
    index, and nothing here declares a scale: an absent declaration is the
    engine's to publish, not the route's to invent.
    """
    disclosure: Dict[str, Any] = {}
    for key in CONCENTRATION_DIVERSIFICATION_FORWARDED_KEYS:
        if concentration_result.get(key) is not None:
            disclosure[key] = concentration_result[key]
    by_weight = concentration_result.get("by_weight")
    by_weight = by_weight if isinstance(by_weight, Mapping) else {}
    holdings = concentration_result.get("n_holdings")
    if isinstance(holdings, bool) or not isinstance(holdings, int) or holdings < 0:
        holdings = len(by_weight)
    disclosure["n_holdings"] = holdings
    return disclosure


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
                # `n_holdings: 0` beside the 0.0 is what disambiguates this state:
                # the index is undefined with no holdings, so the 0.0 marks an
                # ABSENT book rather than a measured single-holding one. The scale
                # itself is the engine's declaration and is deliberately NOT
                # restated here - this branch never calls the engine, and a second
                # copy of that text is the defect a single implementation avoids.
                **_concentration_diversification_disclosure({"by_weight": {}}),
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
        # Read once: the coverage universe, the published `by_weight` and the
        # `n_holdings` the scale declares are the same population, and reading it
        # from three places is how they would come to disagree.
        by_weight = concentration_result.get("by_weight", {})
        by_weight = by_weight if isinstance(by_weight, Mapping) else {}
        coverage = _universe_coverage(
            requested_tickers,
            by_weight.keys(),
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
            # The score's scale, the two formulas and the `n` it was measured
            # over, so a reader can recompute the published index from the
            # published HHI instead of taking 98.5 on trust.
            **_concentration_diversification_disclosure(concentration_result),
            "diversification_ratio": concentration_result.get("diversification_ratio", 1.0),
            "gini_coefficient": concentration_result.get("gini_coefficient", 0.0),
            "by_weight": by_weight,
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
            # DI-2: these are cross-section statistics of a live-quoted book, and
            # a live quote carries a REFRESH instant, not an observation date, so
            # there is no real valuation date to publish. `as_of` stays null and
            # the reason is named, rather than borrowing a date from a price
            # series this payload never read. Stating the basis next to the
            # numbers is what lets a reader age the section themselves.
            "as_of": None,
            "as_of_semantics": None,
            "valuation_basis": CONCENTRATION_VALUATION_BASIS,
            "valuation_date_status": "unavailable",
            "valuation_date_unavailable_reason": (
                "concentration_is_a_cross_section_of_live_quoted_market_value_"
                "weights_and_a_quote_carries_a_refresh_instant_not_an_observation_"
                "date"
            ),
            "warnings": [CONCENTRATION_NO_VALUATION_DATE_WARNING],
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
                # A fresh yfinance fetch carries `date` as a COLUMN over an
                # integer row index. Read it off the DELIVERED frame, before the
                # price/volume projection below drops every column but the two
                # the engine needs: projected first, the only dated evidence is
                # gone and the frame keeps a positional RangeIndex, so every
                # delivered-window date and the section's `latest_observation_date`
                # come back null over ~20 real bars per leg. Promoted here, the
                # engine still sees the Close/Volume frame it expects and the
                # reported window describes observations rather than row numbers.
                # Never synthesise dates from a positional index.
                date_col = next((c for c in ("date", "Date") if c in df.columns), None)
                dated = (
                    pd.to_datetime(df[date_col], errors="coerce")
                    if date_col is not None
                    else None
                )
                if vol_col and price_col in df.columns:
                    frame = df[[price_col, vol_col]].rename(columns={vol_col: 'Volume', price_col: 'Close'})
                elif price_col in df.columns:
                    frame = df[[price_col]].rename(columns={price_col: 'Close'})
                else:
                    frame = None
                if frame is not None:
                    if dated is not None:
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
        by_position = liquidity_result.get("by_position", {})
        by_position = dict(by_position) if isinstance(by_position, Mapping) else {}
        spread_block, per_position_spread = _liquidity_score_spread_disclosure(
            by_position
        )
        for ticker, facts in per_position_spread.items():
            if isinstance(by_position.get(ticker), Mapping):
                by_position[ticker] = {**by_position[ticker], **facts}
        volume_stats = liquidity_result.get("volume_stats", {})
        volume_stats = dict(volume_stats) if isinstance(volume_stats, Mapping) else {}
        volume_stats.update(
            _liquidity_volume_band_residual(volume_stats, positions=by_position)
        )
        volume_stats.update(
            _liquidity_volume_mean_basis(delivered, positions=by_position)
        )
        scoring_block = _liquidity_scoring_block(
            liquidity_result,
            data_range={"start": start, "end": end},
            observation_window=delivered,
        )
        scoring_block["spread"] = spread_block

        # A score banded partly on an estimated or floored market cap is a
        # fallback, not a clean measurement, so the section says so instead of
        # reporting `available` over inputs it never measured. Each leg keeps
        # its own provenance in `by_position`; the section only counts them.
        estimate_disclosure = _liquidity_market_cap_estimate_disclosure(by_position)
        non_measured = list(estimate_disclosure.get("non_measured_market_caps") or [])

        result = {
            "overall_score": liquidity_result.get("overall_score"),
            "overall_score_raw": liquidity_result.get("overall_score_raw"),
            "overall_band": liquidity_result.get("overall_band"),
            "liquidation_time_days": liquidity_result.get("liquidation_time_days"),
            # The value is the engine's band of the mean score and is NOT
            # changed; what was missing was the rule that produced it, without
            # which the per-leg distribution beside it could not be reconciled.
            "liquidation_time_days_aggregation": LIQUIDATION_TIME_AGGREGATION,
            "risk_level": liquidity_result.get("risk_level"),
            "by_position": by_position,
            "volume_stats": volume_stats,
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
            "scoring": scoring_block,
            "universe_coverage": coverage,
            "data_status": _data_status(coverage, partial=bool(non_measured)),
            "methodology": "Liquidity scoring based on trading volume and market capitalization",
        }
        result.update(estimate_disclosure)
        if non_measured:
            # The warning is the section-level half of the disclosure: it is what
            # makes a reader of `data_status` alone see that the headline score
            # is not a clean measurement, and it is what the linked dashboard
            # summary reads when it declines to publish `liquidity_score`.
            floored = list(
                (estimate_disclosure.get("non_measured_by_provenance") or {}).get(
                    "fallback"
                )
                or []
            )
            result["warnings"] = [
                f"{len(non_measured)} of {estimate_disclosure['market_cap_count']} "
                "market caps the score was banded on are not measured ("
                f"{', '.join(non_measured)}): "
                + (
                    f"{len(floored)} sit on the fixed INR "
                    f"{_liquidity_floor_value(scoring_block):,.0f} floor "
                    f"({', '.join(floored)})"
                    if floored
                    else "each is annualised from measured daily turnover"
                )
                + ", so the published score, band and liquidation window are "
                "partly derived from a substitute for a measurement. Each leg "
                "keeps its own market_cap_provenance in by_position."
            ]
        return result

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
        # The `volatility_adjustment.factor` every shock was scaled by is a
        # MEASURED annualized volatility over this frame, so a scenario loss
        # published without the window it was measured over cannot be aged by a
        # reader. The window is measured from the delivered frame, not from the
        # 756-day request: a short delivery says so instead of borrowing the
        # requested end as evidence.
        measured_window = _history_window(
            start, end, price_data.pct_change(fill_method=None).iloc[1:],
            price_frame=price_data,
        )
        adjustment = (
            (stress_result.get("shock_inputs") or {}).get("volatility_adjustment")
            if isinstance(stress_result.get("shock_inputs"), Mapping)
            else None
        )
        adjustment = adjustment if isinstance(adjustment, Mapping) else {}
        stress_result["measurement_window"] = measured_window
        stress_result["latest_observation_date"] = _latest_observation_date(price_data)
        stress_result["volatility_adjustment_window"] = {
            "basis": "measured_annualized_volatility_over_this_frame",
            "min_observations": adjustment.get("min_observations"),
            "annualization_trading_days": adjustment.get("annualization_trading_days"),
            "window": measured_window,
            "note": (
                "The per-ticker factors in "
                "shock_inputs.volatility_adjustment.by_ticker were measured over "
                "this window, not over the requested one, so every scenario loss "
                "in this payload is only as old as the newest bar in it."
            ),
        }
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
        published_pv = round(float(resolved_pv), 2)
        response.update({
            "portfolio_value": published_pv,
            "portfolio_value_currency": base_currency,
            # The exact budget and its published form are one number, so the
            # rounding that relates them is stated instead of leaving two
            # `portfolio_value` readings to reconcile by eye.
            "portfolio_value_decimals": 2,
            "portfolio_value_rounding_residual": round(
                float(resolved_pv) - published_pv, 12
            ),
            "portfolio_value_exact": float(resolved_pv),
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
        response["sizing_basis"]["price_freshness"] = _sizing_price_freshness(
            response["sizing_basis"].get("sizing_price_as_of"),
            response.get("latest_observation_date"),
        )
        response["sizing_basis"]["position_last_price_comparison"] = (
            _sizing_price_vs_position_last_price(
                response["sizing_basis"].get("sizing_price"), positions_list
            )
        )
        # The engine's summary understated the tolerance bound it certifies; the
        # published aggregates are recomputed from the delivered trades instead.
        reconciliation = _trade_reconciliation_disclosure(
            sizing_result.get("trade_reconciliation"),
            sizing_result.get("trades"),
        )
        if reconciliation:
            response["trade_reconciliation"] = reconciliation
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
            # The gate and the records it governs are published together. A
            # consumer that iterates `trades[]` - the natural way to read a
            # sizing section - must not be able to collect order instructions
            # from a target this response says is not a normal rebalance.
            response["trades"], gate_disclosure = _reconcile_trade_status_with_gate(
                response.get("trades"), execution
            )
            if gate_disclosure is not None:
                response["trade_gate_reconciliation"] = gate_disclosure
            gate_warning = _execution_gate_warning(execution)
            if gate_warning:
                response["warnings"] = [
                    *(response.get("warnings") or []),
                    gate_warning,
                ]
        return response
        
    except HTTPException:
        raise
    except ProviderError as exc:
        _raise_provider_http_error(exc)
    except Exception:
        logger.error("Volatility sizing request failed")
        raise HTTPException(status_code=500, detail="Internal server error")


#: What the risk score's factor leg is fitted over. It is the SAME OLS-vs-market
#: model `get_factor_exposure` publishes an R-squared for, on a DIFFERENT sample:
#: the holding window's aligned return rows, not full exchange history. The basis
#: is published with the fit so the two R-squared values can never be read as
#: contradictory measurements of one window.
RISK_SCORE_FACTOR_BASIS = "holding_window_portfolio_return_vs_benchmark_regression"

RISK_SCORE_FACTOR_BASIS_NOTE = (
    "The factor leg is an OLS regression of the holding-window portfolio return "
    "series on the benchmark, fitted only on rows that overlap the benchmark AND "
    "carry a real constituent return. factor_exposure publishes the same model "
    "over full exchange history, so its R-squared describes a longer, different "
    "sample: compare the two only through this block's basis and window, never "
    "by their values alone."
)


def _factor_leg_evidence(
    price_frame: Any,
    benchmark: Any,
    *,
    r_squared: Any,
) -> Dict[str, Any]:
    """Window, sample and basis of the risk score's factor leg (D-06).

    The engine fits this leg on the masked holding-window price frame it is
    handed, so the frame IS the model's evidence: the window is that frame's own
    first/last dated price row, and the sample is measured exactly as the fit
    measures it - return rows that overlap the benchmark and carry a real
    constituent return. Nothing here is imputed: with no benchmark the leg is not
    fitted, and that is published as an exclusion rather than as a zero sample.
    """
    frame = price_frame if isinstance(price_frame, pd.DataFrame) else pd.DataFrame()
    clean = (
        frame.replace([np.inf, -np.inf], np.nan).sort_index() if not frame.empty else frame
    )
    returns = clean.pct_change(fill_method=None) if not clean.empty else clean
    if len(returns):
        returns = returns.iloc[1:]
    return_rows = int(len(returns))
    input_first, input_last = _observation_bounds(clean)
    block: Dict[str, Any] = {
        "basis": RISK_SCORE_FACTOR_BASIS,
        "note": RISK_SCORE_FACTOR_BASIS_NOTE,
        "published_fit_key": "factor_r_squared",
        "input_window": {"start": input_first, "end": input_last, "days": return_rows},
        "input_return_rows": return_rows,
        "model_used_tickers": [str(column) for column in clean.columns],
        "fitted": r_squared is not None,
    }
    if r_squared is None:
        block["status"] = "excluded_not_fitted"
        block["status_reason"] = (
            "No factor R-squared was measured for this request, so no regression "
            "sample exists. The engine excludes the leg and renormalizes the "
            "remaining components; no window or count is invented here."
        )
        block["model_window"] = None
        block["model_observation_count"] = None
        block["model_observation_count_scope"] = None
        block["benchmark_overlap_return_rows"] = None
        return block

    series = benchmark.dropna() if isinstance(benchmark, pd.Series) else pd.Series(dtype=float)
    if len(series) and bool(series.abs().gt(1.0).any()):
        series = series.pct_change(fill_method=None).dropna()
    common = returns.index.intersection(series.index) if (len(series) and return_rows) else returns.index[:0]
    aligned = returns.loc[common]
    traded = aligned.notna().any(axis=1) if len(common) else pd.Series(dtype=bool)
    active = traded[traded].index.intersection(series.index) if len(traded) else common[:0]
    observations = int(len(active))
    if observations:
        block["model_window"] = {
            "start": _observation_date(active[0]),
            "end": _observation_date(active[-1]),
            "days": observations,
        }
        block["model_observation_count"] = observations
        block["model_observation_count_scope"] = "active_benchmark_overlap_return_rows"
        block["status"] = "fitted"
    else:
        # The engine fitted, but the active subset is not reproducible from the
        # published inputs. Say which frame the count describes rather than
        # reporting a sample nobody can verify as the regression's own.
        block["model_window"] = {
            "start": input_first,
            "end": input_last,
            "days": return_rows,
        }
        block["model_observation_count"] = return_rows
        block["model_observation_count_scope"] = (
            "input_return_rows_regression_subset_unmeasured"
        )
        block["status"] = "fitted_regression_subset_unmeasured"
        block["status_reason"] = (
            "The active benchmark-overlap subset could not be re-measured from the "
            "published inputs, so the count below describes the whole input return "
            "frame the fit was handed, which is an upper bound on the sample used."
        )
    block["benchmark_overlap_return_rows"] = int(len(common))
    return block


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
        # This block measures a PRICE frame, so it declares the unit of every
        # per-ticker count and publishes the terms that relate the two frames
        # `masked_days` and `return_observations` are drawn from.
        history_coverage["per_ticker_count_units"] = dict(PRICE_FRAME_COUNT_UNITS)
        history_coverage["per_ticker_count_reconciliation"] = (
            _price_frame_count_reconciliation(per_ticker, return_observations)
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
        # D-06: the factor leg's window, sample and basis travel WITH the fit
        # statistic they explain. The engine's alert
        # ("High unexplained risk (low R-squared: ...)") is driven by this
        # number, so a reader has to be able to see it is a 39-observation
        # holding-window fit and not the 174-observation full-history fit
        # `factor_exposure` publishes beside it.
        factor_leg = _factor_leg_evidence(
            price_data, benchmark_returns,
            r_squared=risk_result.get("factor_r_squared"),
        )
        risk_result["factor_model"] = factor_leg
        risk_result["model_window"] = factor_leg.get("model_window")
        risk_result["model_observation_count"] = factor_leg.get("model_observation_count")
        risk_result["model_observation_count_scope"] = factor_leg.get(
            "model_observation_count_scope"
        )
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
        # This section measures a PRICE frame, so it publishes the same
        # per-ticker count units and reconciliation the other holding-window
        # sections do. Calling `holding_coverage` directly left its per-ticker
        # counts in undeclared units — the same ambiguity D-02 fixed everywhere
        # else, because the summary had no owner in that wave.
        history_coverage = publish_holding_coverage(
            detail=start_detail,
            per_ticker=per_ticker,
            requested_start=start,
            requested_end=end,
            covered_days=covered_days,
            evidence_window=holding_evidence_window(end),
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

    Row semantics a reader needs before trusting a point:

    * row 0 is the warm-up row (`warm_up: true`). It carries `return: null`,
      because its prior portfolio value lives in the undelivered first
      observation, and it is the date the benchmark is rebased onto the book -
      so `benchmark_value == portfolio_value` there by construction;
    * when a benchmark was measured, a row is delivered only where the
      benchmark was measured too, and a trailing portfolio session with no
      benchmark is withheld, counted and named on the last row (and in the
      envelope's `warnings`) instead of being delivered half-measured.
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

        # Populated once the holding window and the whole-book coverage are both
        # measured; read by `_deliver`, which several early returns reach before
        # that point and correctly report no holding window.
        holding_context: Dict[str, Any] = {}

        def _deliver(
            rows: List[Dict[str, Any]],
            extra: Optional[Iterable[str]] = None,
            coverage: Optional[Mapping[str, Any]] = None,
        ) -> Any:
            if not include_metadata:
                return rows
            return _performance_history_envelope(
                rows,
                requested_start=start,
                requested_end=end,
                warnings=extra,
                holding_window=holding_context or None,
                coverage_extra=coverage,
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
        # The holding leg is masked to the CANONICAL window start, resolved by the
        # one rule every other holding-window section uses, not to whatever this
        # route's own 90-day request implies. This function used to call
        # `holding_window` with the request's own price frames, so the buy-price
        # inference saw only `days` of evidence and could resolve a LATER
        # start for a position than every sibling section resolved for the same
        # stored `added_on` - the exact mechanism the v4 export used to carry
        # three holding dates for one portfolio (see the rule note above). The
        # canonical evidence window is anchored to the requested END, is read
        # cache-first through the same DataService this leg already used, and
        # `frames` is deliberately not passed: these frames are `days` wide, and
        # handing them over as "evidence in hand" would silently narrow the
        # evidence window while publishing that it was the canonical one.
        provenance = await holding_provenance(
            data_service, perf_holdings, list(perf_holdings), end=end,
        )
        unmasked_price_dict = {
            t: price_df[t] for t in price_df.columns if t in quantities
        }
        price_df_dict, _perf_effectives = holding_window(
            unmasked_price_dict, canonical_holding_window_input(provenance["detail"])
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
        # `min_count=len(q_series)` refuses any date where a priced position has
        # no price, so a partial basket is never rescaled into a whole-book
        # number. That refusal is correct but was invisible: a reader could not
        # tell a short series from a thin one. Count it and publish it.
        measurable_price_rows = int(len(price_df))
        constituent_count = int(len(q_series))
        complete_coverage = portfolio_series.notna()
        portfolio_series = portfolio_series.dropna()
        coverage_disclosure = {
            "constituent_count": constituent_count,
            "constituent_count_basis": "priced_positions_required_for_a_portfolio_value",
            "partial_basket_policy": "refused_not_renormalised",
            "measurable_price_rows": measurable_price_rows,
            "complete_coverage_price_rows": int(len(portfolio_series)),
            "refused_partial_coverage_price_rows": measurable_price_rows - int(len(portfolio_series)),
        }
        # Name the legs that actually blocked a whole-book value, so a delivered
        # start later than the holding-window start is attributable instead of
        # looking like absent data.
        refused_legs = _refused_coverage_legs(price_df, complete_coverage)
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

        # A comparison row is only a comparison where BOTH legs were measured on
        # that date.  The benchmark and the book are separate series with
        # separate coverage, and the newest session is exactly where they
        # disagree: the delivered rows ended with a portfolio value and no
        # benchmark point at all, so every chart drew a benchmark line that
        # stopped a day short of the series.  There is no measured benchmark
        # return for such a date, and inventing one (carrying the last level
        # forward, or growing it by the portfolio's own move) would be a
        # fabricated benchmark, so the incomparable rows are withheld from the
        # comparison and named rather than delivered half-measured.
        emitted_dates = list(daily_returns.index)
        withheld_dates: List[str] = []
        if bench_val_series is not None:
            comparable = [
                date_idx
                for date_idx in emitted_dates
                if date_idx in bench_val_series.index
            ]
            if comparable:
                withheld_dates = [
                    str(date_idx)[:10]
                    for date_idx in emitted_dates
                    if date_idx not in bench_val_series.index
                ]
                emitted_dates = comparable

        output = []
        for index, date_idx in enumerate(emitted_dates):
            date_str = str(date_idx)[:10]
            val = float(portfolio_series.loc[date_idx])
            item = {
                "date": date_str,
                "portfolio_value": round(val, 2),
                "portfolio_value_currency": target_currency,
                # The first delivered row has no return of its own: its prior
                # value sits in the undelivered warm-up observation, so any
                # number here is a return against a value this response never
                # published.  The key stays, with null, so every row keeps the
                # same shape and the absence is explicit rather than implied.
                "return": None if index == 0 else round(float(daily_returns.loc[date_idx]), 6),
                "currency": target_currency,
                "base_currency": target_currency,
                "currency_provenance": currency_provenance,
                # Row 0 is the series' warm-up row and the date the benchmark is
                # rebased onto the book: `benchmark_value` equals
                # `portfolio_value` here BY DEFINITION, because both series
                # start from that one anchor.  It is labelled so a reader can
                # tell a declared anchor from a coincidental copy.
                "warm_up": index == 0,
            }
            if index == 0:
                item["warm_up_reason"] = (
                    "first delivered row: no prior portfolio value was "
                    "delivered, so its return is null"
                    + (
                        ", and its portfolio value anchors the benchmark "
                        "rebasing, so benchmark_value equals portfolio_value "
                        "here by construction"
                        if bench_val_series is not None
                        else ""
                    )
                )
                if bench_val_series is None:
                    # No benchmark at all is a disclosed degradation, not a
                    # silently overlay-free chart: it is stated on the row every
                    # bare-array consumer reads first, and in the envelope.
                    item["benchmark_series_status"] = "unavailable"
                    item["benchmark_unavailable_reason"] = (
                        "the benchmark returned no usable returns for the "
                        "requested window, so no row carries a benchmark value"
                    )
            if bench_val_series is not None and date_idx in bench_val_series.index:
                item["benchmark_value"] = round(float(bench_val_series.loc[date_idx]), 2)
                item["benchmark_value_currency"] = target_currency
            if withheld_dates and index == len(emitted_dates) - 1:
                # The series stops here because the benchmark has no
                # measurement after it.  The withheld sessions are named on
                # the row a reader stops at, because the bare-array response
                # has nowhere else to say so.
                item["withheld_portfolio_observation_count"] = len(withheld_dates)
                item["withheld_portfolio_observations"] = list(withheld_dates)
                item["series_end_reason"] = (
                    "the benchmark was not measured on the withheld session(s), "
                    "so no benchmark value exists for them and they are not "
                    "delivered as comparison rows"
                )
            output.append(item)

        extra_warnings: List[str] = []
        if withheld_dates:
            extra_warnings.append(
                f"{len(withheld_dates)} portfolio observation(s) "
                f"({', '.join(withheld_dates)}) carry no measured benchmark and "
                "are not delivered as comparison rows; the benchmark value for "
                "those sessions was never measured and is not estimated here."
            )
        elif bench_val_series is None:
            extra_warnings.append(
                "No benchmark was measured for the requested window, so no row "
                "carries a benchmark value; the delivered series is the "
                "portfolio leg only."
            )
        # The holding-window declaration. The mask cutoff is the canonical
        # intersection every sibling section publishes, the count is in the
        # sibling unit (return observations, so the first held price row is
        # excluded), and the two dates are reconciled here rather than left for a
        # reader to notice: the window starts on one date and the series is
        # measurable from another, and both are true.
        window_start = provenance.get("start")
        if isinstance(window_start, str) and window_start:
            measured_start = _observation_date(output[0].get("date")) if output else None
            gap_days = _calendar_day_gap(measured_start, window_start)
            per_ticker = {}
            own_returns = price_df.pct_change(fill_method=None)
            for ticker in sorted(price_df.columns):
                held = price_df_dict.get(ticker)
                raw = unmasked_price_dict.get(ticker)
                # Frame attrs (the feed's own coverage declaration) live on the
                # per-ticker series, not on the column the wide frame was built
                # from, so they are read from the fetched series.
                fetched = price_data_dict.get(ticker)
                per_ticker[ticker] = {
                    "raw_days": int(len(raw)) if raw is not None else 0,
                    "masked_days": int(len(held)) if held is not None else 0,
                    "return_observations": int(own_returns[ticker].notna().sum()),
                    "coverage_reason": fetched.attrs.get("coverage_reason") if fetched is not None else None,
                    "limited_history": bool(fetched.attrs.get("limited_history", False)) if fetched is not None else False,
                }
            holding_context.update(publish_holding_coverage(
                detail=provenance["detail"],
                per_ticker=per_ticker,
                requested_start=start,
                requested_end=end,
                # The unit every holding-window section publishes: the measured
                # whole-book return observations, so the first held price row is
                # excluded. Counted on the measured series rather than on the
                # delivered rows, because a row withheld for want of a BENCHMARK
                # is still a measured portfolio return - counting deliveries would
                # make this section's number move with the benchmark leg and
                # disagree with its siblings for a reason that has nothing to do
                # with the holding window.
                covered_days=int(len(daily_returns)),
                evidence_window=provenance["evidence_window"],
            ))
            holding_context["holding_window_start"] = window_start
            holding_context["delivered_measured_start"] = measured_start
            holding_context["holding_window_to_measured_start_gap_days"] = gap_days
            holding_context["measured_start_basis"] = PERFORMANCE_MEASURED_START_BASIS
            holding_context["refused_coverage_legs"] = refused_legs
            holding_context["refused_partial_coverage_price_rows"] = coverage_disclosure[
                "refused_partial_coverage_price_rows"
            ]
        return _deliver(output, extra=extra_warnings, coverage=coverage_disclosure)

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
    # The mask cutoff is the intersection of the legs whose PRICE DATA this call
    # actually fetched, so the holdings that can set it are exactly those legs.
    # A persisted row carrying no active weight has no bars here: letting its
    # `added_on` into the intersection would move the window start later and mask
    # the book to a window it has no price data for (D-08).
    fetched_tickers = set(ticker_list)
    mask_holdings = {
        ticker: holding
        for ticker, holding in (holdings or {}).items()
        if ticker in fetched_tickers
    }
    masked_dict, effectives = holding_window(price_data_dict, mask_holdings)
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
    # This ticker's OWN returns, before the portfolio aggregate narrows the
    # frame, so the per-ticker reconciliation can separate a missing bar from a
    # row the portfolio dropped.
    own_return_observations = _own_return_observations(prices)
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
    # Drop only rows that are ENTIRELY missing.  A row where one leg has a real
    # return and another is NaN is a partial row, and it must survive here: the
    # prelisting mask is published AS a NaN so a reader can see which leg was not
    # yet held.  Slicing to `portfolio_returns.index` instead used to drop those
    # rows as a side effect, which silently converted "this leg is absent" into
    # "this date does not exist" and broke the absent-not-backfilled invariant.
    #
    # The two objects have deliberately different contracts and must not be
    # narrowed to each other:
    #   * `returns_df`     - per-leg truth. Every date with any measurable leg.
    #   * `portfolio_returns` - one number per date, so a date whose surviving
    #     weight coverage is short cannot become a portfolio return at all.
    # Downstream covariance/tail consumers that need complete rows must read the
    # coverage block, not a frame pre-sliced to the aggregate's index.
    measurable_rows = returns_df.notna().any(axis=1)
    returns_df = returns_df.loc[measurable_rows]
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
    # This leg measures a PRICE frame (`masked_days` is held price rows) and the
    # return frame it then aligns, so it declares both units and publishes the
    # terms that relate them. `covered_days` stays the aligned portfolio return
    # row count the caller measures; this block only explains the per-ticker
    # numbers, which are otherwise three questions under three names.
    coverage["per_ticker_count_units"] = dict(PRICE_FRAME_COUNT_UNITS)
    coverage["per_ticker_count_reconciliation"] = _price_frame_count_reconciliation(
        per_ticker, own_return_observations
    )
    # A date whose surviving weight coverage is short produces NO portfolio
    # return, because renormalising it would publish a half-book day as a whole
    # book. `covered_days` above is therefore lower than the number of dates the
    # price frame could have supported, and that difference has to be stated —
    # otherwise a shortened series reads as a data gap rather than a refusal.
    measurable_count = int(measurable_rows.sum())
    coverage["measurable_return_rows"] = measurable_count
    coverage["partial_coverage_days"] = measurable_count - int(len(portfolio_returns))
    coverage["partial_coverage_days_reason"] = (
        "dates where the surviving positive-weight constituents did not cover "
        "100% of gross weight were refused rather than renormalised into a "
        "partial-basket portfolio return"
    )
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
        # SI-5: precision for the eleven numbers above, over exactly the series
        # they were measured from. Built AFTER the annualization gate, so a
        # withheld metric reports "the point estimate itself is withheld"
        # rather than lending a band to a null.
        metrics_uncertainty = _tear_sheet_uncertainty(
            port_ret,
            {field: metrics.get(field) for field in (
                "total_return", "cagr", "sharpe", "sortino", "calmar", "omega",
                "tail_ratio", "volatility", "max_drawdown", "skew", "kurtosis",
            )},
            scope=(
                "tear_sheet metrics: the holding-window portfolio return series "
                "every metric in this block was computed from"
            ),
            not_computed={
                "skew": _SHAPE_STATISTIC_REASON,
                "kurtosis": _SHAPE_STATISTIC_REASON,
            },
        )

        # --- Full-history instrument risk (DSP-10) ---------------------------
        # CAGR/Sharpe/Sortino/Calmar and benchmark beta/alpha are asset-
        # characteristic questions: the current book measured over the full
        # cache depth (see full_start above). Realized P&L above stays
        # holding-truthed. The second build is cache-served (same frames as
        # the masked call).
        full_returns_df, full_port_ret, full_leg_coverage = await _build_wide_returns(
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
        full_metrics_uncertainty = _tear_sheet_uncertainty(
            full_port_ret,
            {field: full_metrics.get(field) for field in (
                "total_return", "cagr", "sharpe", "sortino", "calmar",
                "volatility", "max_drawdown",
            )},
            scope=(
                "tear_sheet full_history metrics: the hypothetical-current-"
                "weights portfolio return series over the full cache depth, "
                "which is a DIFFERENT sample from the holding-window block"
            ),
        )
        try:
            full_history_start = str(full_port_ret.index.min().date())
        except Exception:
            full_history_start = full_start
        # Same evidence shape Factor Exposure and Risk Contribution publish: the
        # full-history leg carries its own window, observation count, scope and
        # truncation flag, so it can never be read as the holding window and
        # the holding window can never be read as this model's sample.
        #
        # NEW-7: the shape was the problem. This block is described by
        # `full_returns_df` (2486 rows, every date ANY leg was measurable on)
        # while `full_metrics` above is measured on `full_port_ret` (307 rows,
        # every date the WHOLE positive-weight book cleared coverage). Declaring
        # the 2486-day window and annualising on 307 is a 9.11x recompute error
        # for anyone who trusts the declared window, so the block now publishes
        # the metrics' own count and bounds, and the coverage leg this route used
        # to discard into `_` explains exactly which dates the difference is.
        full_history_evidence = _full_history_evidence(
            full_returns_df,
            requested_start=start,
            requested_end=end,
            metrics_series=full_port_ret,
        )
        if isinstance(full_leg_coverage, Mapping):
            for key in (
                "measurable_return_rows",
                "partial_coverage_days",
                "partial_coverage_days_reason",
            ):
                if full_leg_coverage.get(key) is not None:
                    full_history_evidence[key] = full_leg_coverage[key]
        full_history_evidence["measurement_frame_note"] = (
            "`window`/`observation_count` describe the wide per-ticker return "
            "frame. `metrics_observation_count`/`metrics_window` describe the "
            "shorter portfolio return series the `metrics` block was measured "
            "on. The difference between the two counts is "
            "`partial_coverage_days`: dates on which the surviving "
            "positive-weight constituents did not cover 100% of gross weight, "
            "which were refused rather than renormalised into a partial-basket "
            "portfolio return."
        )

        full_relative: Dict[str, Any] = {}
        full_bench_available = bool(bench_ret is not None and len(bench_ret) > 20)
        # Both legs are pre-declared, not just the portfolio: the uncertainty
        # block below is handed the PAIR, and a benchmark that never arrived
        # must reach it as an explicit absence rather than an unbound name.
        full_overlap_p: Optional[pd.Series] = None
        full_overlap_b: Optional[pd.Series] = None
        full_overlap_days = 0
        if full_bench_available:
            common_full = full_port_ret.index.intersection(bench_ret.index)
            full_overlap_days = int(len(common_full))
            # The intersection frames are built whether or not the gate passes:
            # the disclosure below has to name the sample the gate judged, and a
            # window can only be described from the rows it would have used.
            full_overlap_p = full_port_ret.loc[common_full]
            full_overlap_b = bench_ret.loc[common_full]
            if full_overlap_days >= MIN_ANNUALIZE_DAYS:
                p, b = full_overlap_p, full_overlap_b
                var_b = float(b.var())
                beta = float(p.cov(b) / var_b) if var_b > 0 else None
                alpha_ann = float((p.mean() - beta * b.mean()) * 252) if beta is not None else None
                full_relative = {
                    "beta_vs_nifty": round(beta, 4) if beta is not None else None,
                    "alpha_annualized": round(alpha_ann, 4) if beta is not None else None,
                    "overlap_days": full_overlap_days,
                }
        # QM-2: this leg publishes only beta and alpha, but it is still a
        # two-sample block (the full-depth series and the joint overlap), so it
        # carries the same per-field disclosure. It declares no benchmark-window
        # record because it publishes no `benchmark_*` field, and a declared
        # window no field uses is one a reader will trust by mistake.
        full_relative[RELATIVE_WINDOW_DISCLOSURE_KEY] = _relative_window_disclosure(
            metrics_series=full_port_ret,
            metrics_basis=FULL_HISTORY_BASIS,
            metrics_description=(
                "the hypothetical-current-weights portfolio return series over "
                "the full cache depth, which is the same sample the "
                "full_history metrics block was measured from"
            ),
            benchmark_series=bench_ret,
            benchmark_window=bench_ret,
            overlap_series=full_overlap_p,
            overlap_observations=full_overlap_days,
            benchmark_available=full_bench_available,
            published_fields=RELATIVE_MARKET_MODEL_FIELDS,
            metrics_block_path="tear_sheet.full_history.metrics",
            observation_count_path="tear_sheet.full_history.metrics.days",
        )

        # Three different samples live in `relative_vs_nifty` and its full-
        # history sibling: the ALIGNED portfolio/benchmark pair, the benchmark
        # sliced back to the requested window, and (above) the aligned pair over
        # the full cache depth. Each gets its own block, because an interval
        # whose n belongs to a different window than its point estimate is the
        # defect this block exists to remove.
        #
        # The pair handed over is the SAME `common_full` intersection beta and
        # alpha were fitted on, not the full-depth series beside the full-depth
        # benchmark. Those are 307 against 2620 rows on disjoint calendars, so
        # the interval belonged to a different decade than the estimate it sat
        # beside. Both series are `None` when the benchmark is unavailable, and
        # the block then reports the absence rather than a band.
        full_relative_uncertainty = _tear_sheet_relative_uncertainty(
            full_overlap_p, full_overlap_b, full_relative,
            scope=(
                "tear_sheet full_history relative_vs_nifty: beta and alpha over "
                "the full-depth portfolio/benchmark overlap"
            ),
        )

        relative: Dict[str, Any] = {}
        relative_uncertainty: Dict[str, Any] = {
            "market_model": _tear_sheet_relative_uncertainty(
                None, None, {},
                scope=(
                    "tear_sheet relative_vs_nifty: beta and alpha over the "
                    "holding-window portfolio/benchmark overlap"
                ),
            ),
            "benchmark": _tear_sheet_uncertainty(
                None,
                {field: None for field in RELATIVE_BENCHMARK_FIELDS},
                scope=(
                    "tear_sheet relative_vs_nifty benchmark block: the NIFTY "
                    "return series sliced back to the requested window"
                ),
                statistic_names=dict(_BENCHMARK_STATISTIC_NAMES),
            ),
        }
        bench_available = bool(bench_ret is not None and len(bench_ret) > 20)
        bench_window: Any = None
        holding_overlap_p: Optional[pd.Series] = None
        overlap_days = 0
        if bench_available:
            # Holding leg stays on the requested window: slice the (possibly
            # deeper) benchmark back down. Benchmark standalone stats describe
            # the index over the requested window (no holding concept applies
            # to NIFTY itself) -- which is why QM-2 labels that window rather
            # than re-slicing the index onto this book's holding window.
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
            overlap_days = int(len(common))
            # The intersection slice is taken unconditionally: even when the
            # gate withholds the point estimate, the reader is owed the window
            # the gate judged and how far short of the policy minimum it fell.
            holding_overlap_p = port_ret.loc[common]
            aligned_p = aligned_b = None
            if overlap_days >= MIN_ANNUALIZE_DAYS:
                p, b = holding_overlap_p, bench_ret.loc[common]
                # The frames the interval will be built from are exactly the
                # frames the estimate was fitted on. When the gate withholds
                # beta/alpha they stay None, and the block then says the point
                # estimate is withheld rather than lending a band to a null.
                aligned_p, aligned_b = p, b
                var_b = float(b.var())
                beta = float(p.cov(b) / var_b) if var_b > 0 else None
                alpha_ann = float((p.mean() - beta * b.mean()) * 252) if beta is not None else None
                relative["beta_vs_nifty"] = round(beta, 4) if beta is not None else None
                relative["alpha_annualized"] = round(alpha_ann, 4) if alpha_ann is not None else None
            relative["overlap_days"] = overlap_days
            relative_uncertainty["market_model"] = _tear_sheet_relative_uncertainty(
                aligned_p, aligned_b,
                {
                    "beta_vs_nifty": relative.get("beta_vs_nifty"),
                    "alpha_annualized": relative.get("alpha_annualized"),
                },
                scope=(
                    "tear_sheet relative_vs_nifty: beta and alpha over the "
                    "holding-window portfolio/benchmark overlap"
                ),
            )
            relative_uncertainty["benchmark"] = _tear_sheet_uncertainty(
                bench_window,
                {field: relative.get(field) for field in RELATIVE_BENCHMARK_FIELDS},
                scope=(
                    "tear_sheet relative_vs_nifty benchmark block: the NIFTY "
                    "return series sliced back to the requested window"
                ),
                statistic_names=dict(_BENCHMARK_STATISTIC_NAMES),
            )
        # QM-2: the block publishes three different samples (the joint
        # portfolio/benchmark overlap, the index over the requested window, and
        # -- one level up -- the holding-window `metrics` block), and before
        # this disclosure the only one named was the first, via `overlap_days`.
        # No value above changed to get here: the estimates are computed on the
        # series they were always computed on, and this only says which.
        relative[RELATIVE_WINDOW_DISCLOSURE_KEY] = _relative_window_disclosure(
            metrics_series=port_ret,
            metrics_basis=MEASURED_WINDOW_COVERED_DAYS_SCOPE,
            metrics_description=(
                "the holding-window portfolio return series, measured on the "
                "whole-book complete return rows; this is the same sample the "
                "tear sheet's `metrics` block was measured from"
            ),
            benchmark_series=bench_ret,
            benchmark_window=bench_window,
            overlap_series=holding_overlap_p,
            overlap_observations=overlap_days,
            benchmark_available=bench_available,
            requested_window={"start": start, "end": end},
        )

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
        holding_window_start = history_coverage.get("intersection_start")
        # `start` here is the first date the WHOLE book was measurable on, which
        # is later than the holding window's own start whenever an early session
        # has a leg without a price. Both dates are true and they describe
        # different things, so publishing them side by side without the gap looks
        # like a contradiction. State the gap: it is the visible consequence of
        # refusing to renormalise a partial basket into a portfolio return.
        leading_gap_days = None
        if holding_window_start and measured_first:
            try:
                leading_gap_days = (
                    datetime.strptime(measured_first, "%Y-%m-%d")
                    - datetime.strptime(str(holding_window_start)[:10], "%Y-%m-%d")
                ).days
            except (TypeError, ValueError):
                leading_gap_days = None
        measured_window = {
            "start": measured_first,
            "end": measured_last or _latest_observation_date(port_ret),
            "days": int(covered_days),
            "observation_count": int(covered_days),
            "covered_days_scope": MEASURED_WINDOW_COVERED_DAYS_SCOPE,
            "truncated_to_holding_window": bool(history_coverage.get("truncated")),
            "holding_window_start": holding_window_start,
            "holding_window_to_measured_start_gap_days": leading_gap_days,
            "measured_start_basis": (
                "first date on which every held position had a measurable return; "
                "earlier holding-window sessions had at least one leg without a "
                "price and were refused rather than renormalised into a "
                "partial-basket portfolio return"
            ),
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
            # SI-5: one precision block per SAMPLE, not per section. The
            # holding-window, the full-depth and the benchmark-slice blocks sit
            # on three different series, so an interval can never be read
            # against a point estimate measured on another one.
            "estimate_uncertainty": {
                "metrics": metrics_uncertainty,
                "relative_vs_nifty": relative_uncertainty,
            },
            "full_history": {
                **full_history_evidence,
                "metrics": full_metrics,
                "universe_coverage": full_coverage,
                "relative_vs_nifty": full_relative,
                "estimate_uncertainty": {
                    "metrics": full_metrics_uncertainty,
                    "relative_vs_nifty": full_relative_uncertainty,
                },
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
        # The holding-context window is measured against the canonical
        # intersection start, so `covered_days` there describes the holding
        # tenure (return observations two held prices can produce) instead of
        # repeating the model's own observation count or the route's own date.
        #
        # It is measured on `returns_df`, the frame the per-ticker counts below
        # are cut from, because that is what `covered_days_scope` declares this
        # block measures (`HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE`) and what
        # `factor_exposure` - the other block carrying that scope - measures.
        # Measuring it on `port_ret` instead was not a slower path to the same
        # number: `port_ret.index` is a strict SUBSET of `returns_df.index` by
        # design, because `aggregate_active_returns` refuses every date whose
        # surviving positive weight did not cover the whole declared book while
        # the wide frame deliberately RETAINS those dates as NaN (the per-leg
        # truth contract, see `_build_wide_returns`). On a book with a single
        # leg that has a price gap the two indexes differ, and the boolean mask
        # built on `port_ret` cannot index `returns_df` at all: pandas raised
        # `IndexingError: Unalignable boolean Series provided as indexer`, the
        # blanket handler at the foot of this function turned it into a bare
        # 500, and the section has published `unavailable` with no data in every
        # export since the project began. The frame is NOT narrowed to make the
        # two agree - that would discard exactly the partially-covered dates the
        # wide frame exists to carry.
        holding_days, holding_mask = holding_window_observation_count(
            returns_df, provenance["start"],
        )
        # `returns_df` is already a RETURN frame here, so a ticker's own
        # observation count is its non-null return rows. Taking it through
        # `_own_return_observations` (which differences a frame to make returns)
        # measured the returns OF those returns and published 246 where the
        # frame holds 248: a count that was wrong by construction and published
        # under the same key the price-frame sections use.
        return_frame_counts = {
            ticker: int(returns_df[ticker].notna().sum())
            for ticker in returns_df.columns
        }
        holding_context = publish_holding_coverage(
            detail=start_detail,
            per_ticker={
                ticker: {
                    "raw_days": count,
                    "masked_days": int(returns_df[ticker][holding_mask].notna().sum())
                    if holding_mask is not None else count,
                    "return_observations": count,
                    "holding_window_return_observations": int(
                        returns_df[ticker][holding_mask].notna().sum()
                    ) if holding_mask is not None else count,
                }
                for ticker, count in return_frame_counts.items()
            },
            requested_start=start,
            requested_end=end,
            covered_days=holding_days,
            evidence_window=provenance["evidence_window"],
            per_ticker_count_units=RETURN_FRAME_COUNT_UNITS,
            # XS-001: same wide-per-leg-frame population as factor_exposure, for
            # the same reason. This section does not appear in the audited export
            # because it 500s there, so the disagreement it would raise is latent
            # rather than observed - which is exactly why it is fixed now instead
            # of waiting for it to show up on the first book where the section
            # succeeds.
            covered_days_scope=HOLDING_WIDE_FRAME_COVERED_DAYS_SCOPE,
        )
        # `holding_coverage` only knows the three legacy count keys, so the
        # window count this section measures is stamped on afterwards, in the
        # same unit the block-level `covered_days` uses.
        for ticker, row in holding_context.get("tickers", {}).items():
            if not isinstance(row, dict):
                continue
            row.setdefault(
                "holding_window_return_observations", row.get("masked_days")
            )
        full_history = _full_history_evidence(
            returns_df,
            requested_start=start,
            requested_end=end,
        )
        # `covered_days` used to be the model's own 252 observations published
        # under holding names, so a 39-day holding window read as a 252-day
        # holding coverage. The two windows are now separate objects.
        #
        # This section's model is the whole-book covariance, not a benchmark
        # regression, so its sample IS the frame it was computed over - there is
        # no smaller fitted subset to report. The count is unchanged and the
        # population is now named, because the same key on `factor_exposure`
        # means something narrower there and one reader cannot tell which.
        history_coverage = _model_history_coverage(
            holding_context,
            full_history,
            model_sample={
                "count": full_history.get("observation_count"),
                "scope": MODEL_SAMPLE_COVARIANCE_FRAME_SCOPE,
                "status": "covariance_frame",
                "status_reason": None,
                "note": MODEL_SAMPLE_COVARIANCE_FRAME_NOTE,
            },
        )
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
            # The tail is a PORTFOLIO question - the whole book's worst days
            # against the portfolio's own 5th percentile - so the population
            # stays exactly `port_ret`'s and is selected here BY LABEL. It used
            # to be `returns_df.loc[tail]`, a boolean mask carrying
            # `port_ret`'s index used to index the wide frame; the same
            # unalignable-index defect as the holding-window mask above, so the
            # same books never reached this line. Selecting by label rather
            # than by mask is also what keeps a date the aggregate refused from
            # silently entering the tail: it is absent from `port_ret`, so it is
            # not a portfolio day and cannot become a tail day. The wide frame
            # is still read whole - only these rows are cut from it, and a leg
            # unpriced on a tail day stays NaN below rather than contributing a
            # zero loss.
            tail_dates = port_ret.index[port_ret <= var_95]
            tail_returns = returns_df.loc[returns_df.index.isin(tail_dates)]
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

        # `cvar` -> `cvar_tail`, keyed here from the one constant so the two
        # sector_rollup containers below cannot be renamed apart again.  The
        # numbers are untouched: this loop computes each model's roll from its own
        # per-leg shares and nothing else changes which numbers it sums.
        sector_rollup: Dict[str, Dict[str, float]] = {
            name: {} for name in CONTRIBUTION_SECTOR_ROLLUP_NAMES
        }
        result = await db.execute(select(PortfolioPosition))
        sector_map = {p.ticker: (p.sector or "Unknown") for p in result.scalars().all()}
        if sector_map:
            for model_name, contribs in zip(
                CONTRIBUTION_SECTOR_ROLLUP_NAMES, (vol_rc, cvar_rc)
            ):
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
        # SI-5: the two tail estimates are order statistics, so their precision
        # is disclosed over the sample that supports them - the tail days - and
        # the bootstrap itself runs on the whole series those days are drawn
        # from. Built from the SAME `var_95` and `tail` the two published points
        # were computed from, so the band cannot belong to a different quantile.
        published_tail = {
            "portfolio_var_95_daily": round(var_95, 6),
            "portfolio_cvar_95_daily": (
                round(float(port_ret[tail].mean()), 6) if tail.any() else None
            ),
        }
        result = {
            "window": {"start": start, "end": end},
            "positions": {
                "volatility": vol_rc,
                "cvar_tail": cvar_rc,
            },
            "sector_rollup": sector_rollup,
            "contribution_basis": _contribution_basis_block(
                {"volatility": vol_rc, "cvar_tail": cvar_rc}, sector_rollup
            ),
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
            "portfolio_var_95_daily": published_tail["portfolio_var_95_daily"],
            "portfolio_cvar_95_daily": published_tail["portfolio_cvar_95_daily"],
            "estimate_uncertainty": _risk_contribution_tail_uncertainty(
                port_ret,
                var_95=var_95,
                tail_mask=tail,
                published=published_tail,
                scope=(
                    "risk_contribution: portfolio_var_95_daily and "
                    "portfolio_cvar_95_daily, measured on the same published "
                    "portfolio return series and its own tail"
                ),
            ),
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
                # SI-5: a single-holding record's triple is a one-asset sample
                # mean and standard deviation, so the block is built when one
                # exists and declared absent - never omitted - when it does not.
                "estimate_uncertainty": (
                    optimizer_estimate_uncertainty(
                        measured_returns.to_frame("A"),
                        np.array([1.0]),
                        {
                            "expected_annual_return": ann_ret,
                            "expected_annual_volatility": ann_vol,
                            "expected_sharpe": sharpe,
                        },
                        rf,
                        scope=(
                            "optimizer single-holding moment triple: one leg at "
                            "weight 1.0, moments are the sample mean and sample "
                            "standard deviation of that leg's own returns"
                        ),
                    )
                    if single_usable and measured_returns is not None
                    else no_estimate_uncertainty(
                        optimizer_no_sample_reason(
                            "this single-holding record has no usable return "
                            f"history ({len(rets) if prices is not None and len(prices) > 1 else 0} "
                            f"return rows, below the {MIN_ANNUALIZE_DAYS} required "
                            "to annualize)"
                        )
                    )
                ),
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
                # SI-5: no sample means no mu/cov, so every moment is null and
                # says so rather than leaving the interval question open.
                "estimate_uncertainty": no_estimate_uncertainty(
                    optimizer_no_sample_reason(
                        f"the common return frame holds {len(returns_df)} rows, "
                        f"below the {MIN_ANNUALIZE_DAYS} this route requires"
                    )
                ),
                "solver": None,
                "universe": ticker_list,
                "calculation_universe": [],
                "current_weights": {t: round(float(current_weights.get(t, 0.0)), TRADE_WEIGHT_DECIMALS) for t in ticker_list},
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
            # The incumbent book, scored on the SAME mu, cov, order, sample and
            # risk-free rate the recommendation is built from. Without this the
            # payload cannot answer the only question a reader has -- is this
            # better than what I already hold? -- because the recommended Sharpe
            # and the portfolio's own Sharpe were never on a common basis.
            current_weights=current_weights,
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
        published_current = {
            t: round(float(current_weights.get(t, 0.0)), TRADE_WEIGHT_DECIMALS)
            for t in calculation_universe
        }
        trades = {}
        for t in calculation_universe:
            cur = float(current_weights.get(t, 0.0))
            rec = reported_recommended[t]
            if abs(rec - cur) > 1e-6:
                # The delta is the difference of the two legs this record
                # PUBLISHES, not of the unrounded weights behind them: a trade
                # list exists to be executed and audited, so
                # `recommended_weight - current_weight == weight_delta` has to
                # hold in the numbers a reader can see. Deriving the delta from
                # the unrounded legs and then rounding it left 2 of 14 records
                # off by 1e-4 in exactly the fields an auditor adds up.
                trades[t] = {
                    "current_weight": published_current[t],
                    "recommended_weight": round(rec, TRADE_WEIGHT_DECIMALS),
                    "weight_delta": round(
                        round(rec, TRADE_WEIGHT_DECIMALS) - published_current[t],
                        TRADE_WEIGHT_DECIMALS,
                    ),
                }
        recommended_sum = round(
            sum(round(value, TRADE_WEIGHT_DECIMALS) for value in reported_recommended.values()),
            12,
        )
        current_sum = round(
            sum(published_current[t] for t in calculation_universe), 12
        )

        response = {
            **result,
            "weights": reported_recommended,
            "universe": ticker_list,
            "calculation_universe": calculation_universe,
            "current_weights": {
                t: round(float(current_weights.get(t, 0.0)), TRADE_WEIGHT_DECIMALS)
                for t in ticker_list
            },
            "trades_required": dict(sorted(trades.items(), key=lambda kv: abs(kv[1]["weight_delta"]), reverse=True)),
            "trades_required_basis": {
                "weight_decimals": TRADE_WEIGHT_DECIMALS,
                "weight_delta_rule": (
                    "weight_delta == round(recommended_weight - current_weight, 4) "
                    "over the PUBLISHED legs of the same record, so every trade "
                    "closes against the two weights printed beside it."
                ),
                "trade_count": len(trades),
                "current_weights_published_total": current_sum,
                "current_weights_rounding_residual": round(1.0 - current_sum, 12),
                "recommended_weights_published_total": recommended_sum,
                "recommended_weights_rounding_residual": round(1.0 - recommended_sum, 12),
                "totals_note": (
                    "Totals are sums of the published 4-decimal legs; the residual "
                    "is what that display rounding costs. They are a SECOND "
                    "rounding of the same vector as weight_normalization's "
                    "submitted_gross_exposure_measured, and the two differ by up to "
                    "n/2e4, so both are published rather than one standing in for "
                    "the other. The financing decision is made on the unrounded "
                    "figure and is published in weight_normalization."
                ),
            },
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


# --- Regime: what the published percentages are made of (V4) ----------------
# Three published percentage aggregates did not close: `states[].historical_days_pct`
# summed to 100.1, `regime_probabilities` to 99.9999, and `stability_pct` (96.7)
# to nothing at all. The first two are display rounding and are published with
# their residual. `stability_pct` is a genuine measurement - the label-flip rate
# of the decoded path over the FULL sample - but nothing said so, and the
# transition matrix's suspiciously exact uniform 96.0 diagonal reads as a
# configured matrix unless it declares that it IS one.
REGIME_PERCENTAGE_TOTAL = 100.0
STABILITY_PCT_RULE = (
    "stability_pct == 100 * (1 - share of consecutive observations in the decoded "
    "display-regime path whose label changed). It is measured over the FULL "
    "classification sample, not over recent_history, and it is not the mean "
    "diagonal of transition_matrix: the matrix is a prior (see "
    "transition_matrix_provenance) while this is a rate observed on the decoded "
    "path."
)
TRANSITION_MATRIX_PROVENANCE = {
    "source": "configured_sticky_prior",
    "estimated": False,
    "estimated_parameters": "means_and_covariances_only",
    "rule": (
        "The Gaussian HMM is fitted with params='mc', so only the emission means "
        "and covariances are estimated. transmat_ is set to a fixed "
        "sticky-persistence prior before fitting and is never re-estimated, so "
        "this matrix is that PRIOR published at 1 decimal - its uniform diagonal "
        "is the prior's persistence, not a persistence measured from the "
        "benchmark's regime path. Read the observed persistence from "
        "stability_pct instead."
    ),
    "rounding_decimals": 1,
    "read_this_as": "model prior; not a fitted transition matrix",
}


def _regime_percentage_residuals(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Publish the rounding each percentage aggregate leaves behind.

    Both aggregates are sums of individually rounded terms, so neither has to
    close on 100 and neither is renormalized to make it look as though it did.
    A missing aggregate publishes `unavailable` rather than a zero residual.
    """
    out: Dict[str, Any] = {}
    states = result.get("states")
    days_pct: List[float] = []
    if isinstance(states, list):
        for state in states:
            if not isinstance(state, Mapping):
                continue
            try:
                days_pct.append(float(state.get("historical_days_pct")))
            except (TypeError, ValueError):
                continue
    if days_pct:
        total = round(sum(days_pct), 10)
        out["historical_days_pct_total"] = total
        out["historical_days_pct_rounding_residual"] = round(
            REGIME_PERCENTAGE_TOTAL - total, 10
        )
        out["historical_days_pct_rounding_decimals"] = 1
        out["historical_days_pct_basis"] = (
            "Share of the classification sample assigned to each state; the "
            "per-state values are rounded to 1 decimal, so their sum is published "
            "beside them instead of being renormalized to 100."
        )
    probabilities = result.get("regime_probabilities")
    if isinstance(probabilities, Mapping) and probabilities:
        try:
            total = round(sum(float(value) for value in probabilities.values()), 10)
        except (TypeError, ValueError):
            total = None
        if total is not None:
            out["regime_probabilities_total"] = total
            out["regime_probabilities_rounding_residual"] = round(
                REGIME_PERCENTAGE_TOTAL - total, 10
            )
            out["regime_probabilities_rounding_decimals"] = 4
            out["regime_probabilities_basis"] = (
                "Filtered posterior of the final observation, per state, in "
                "percentage points; each value is rounded to 4 decimals, so the "
                "posterior's own rounding is published beside them."
            )
    matrix = result.get("transition_matrix")
    if isinstance(matrix, Mapping) and matrix:
        row_residuals = {}
        for state, row in matrix.items():
            if not isinstance(row, Mapping):
                continue
            try:
                row_residuals[str(state)] = round(
                    REGIME_PERCENTAGE_TOTAL - sum(float(value) for value in row.values()),
                    10,
                )
            except (TypeError, ValueError):
                continue
        if row_residuals:
            out["transition_matrix_row_residuals"] = row_residuals
            out["transition_matrix_row_residual_max_abs"] = max(
                abs(value) for value in row_residuals.values()
            )
    return out


def _regime_stability_disclosure(result: Mapping[str, Any]) -> Dict[str, Any]:
    """Say how `stability_pct` was measured, and re-measure the recent window.

    The full-sample rate is the classifier's own measurement and cannot be
    re-derived here (the decoded path is not republished in full), so its rule and
    scope are declared instead. The rate over the window that IS republished -
    `recent_history` - is recomputed and labelled as a different measurement, so
    the two can never be read as one number with two names.
    """
    observations = result.get("observations")
    out: Dict[str, Any] = {
        "stability_pct_rule": STABILITY_PCT_RULE,
        "stability_pct_scope": "full_classification_sample_consecutive_label_transitions",
        "stability_pct_unit": "percent_0_to_100",
        "stability_pct_observations": (
            int(observations) if isinstance(observations, int) else None
        ),
        "transition_matrix_provenance": dict(TRANSITION_MATRIX_PROVENANCE),
    }
    history = result.get("recent_history")
    labels: List[str] = []
    if isinstance(history, list):
        for row in history:
            if isinstance(row, Mapping) and isinstance(row.get("regime"), str):
                labels.append(str(row["regime"]))
    if len(labels) > 1:
        unchanged = sum(
            1 for before, after in zip(labels, labels[1:]) if before == after
        )
        out["recent_history_self_transition_pct"] = round(
            100.0 * unchanged / (len(labels) - 1), 4
        )
        out["recent_history_transitions"] = len(labels) - 1
        out["recent_history_self_transition_scope"] = (
            "last_120_observations_of_the_decoded_path"
        )
        out["recent_history_note"] = (
            "Recomputed from recent_history, which publishes the last 120 "
            "observations only. It is NOT stability_pct, which is measured over "
            "the full classification sample."
        )
    return out


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
        result.update(_regime_percentage_residuals(result))
        result.update(_regime_stability_disclosure(result))
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


def _pairs_test_agreement(
    pairs: Optional[Iterable[Any]],
    *,
    test_roles: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """How often the two cointegration tests agree, measured over delivered rows.

    `is_cointegrated` (Engle-Granger) and `johansen_cointegrated` are two
    different tests, and a consumer that sums them double counts: on the audited
    book 4 + 4 = 8 pairs, with ZERO overlap. The per-row
    `johansen_agrees_with_decision` flag answers the question one row at a time;
    this answers it for the whole scan, so the headline count and the diagnostic
    cannot be added together by accident.
    """
    rows = list(pairs or [])
    decision_positive: List[str] = []
    diagnostic_positive: List[str] = []
    agree: List[str] = []
    disagree: List[str] = []
    for pair in rows:
        key = f"{getattr(pair, 'ticker_a', None)}/{getattr(pair, 'ticker_b', None)}"
        decision = bool(getattr(pair, "is_cointegrated", False))
        diagnostic = bool(getattr(pair, "johansen_cointegrated", False))
        if decision:
            decision_positive.append(key)
        if diagnostic:
            diagnostic_positive.append(key)
        (agree if decision == diagnostic else disagree).append(key)
    flagged = set(decision_positive) | set(diagnostic_positive)
    return {
        "decision_test": "engle_granger",
        "diagnostic_test": "johansen",
        "test_roles": (
            dict(test_roles) if isinstance(test_roles, Mapping) else dict(TEST_ROLES)
        ),
        "counted_pairs": len(rows),
        "decision_positive_count": len(decision_positive),
        "diagnostic_positive_count": len(diagnostic_positive),
        "agreement_count": len(agree),
        "disagreement_count": len(disagree),
        "decision_positive_only_count": len(set(decision_positive) - set(diagnostic_positive)),
        "diagnostic_positive_only_count": len(set(diagnostic_positive) - set(decision_positive)),
        "decision_positive_pairs": sorted(decision_positive),
        "diagnostic_positive_pairs": sorted(diagnostic_positive),
        "summed_count_note": (
            "is_cointegrated and johansen_cointegrated are different tests and must "
            "NOT be added: a pair can carry both. is_cointegrated (engle_granger) is "
            "the published decision; johansen_cointegrated is diagnostic_only. "
            "Summing the two positive counts would report "
            f"{len(decision_positive) + len(diagnostic_positive)} pairs where only "
            f"{len(flagged)} are flagged by at least one test."
        ),
    }


# ---------------------------------------------------------------------------
# SI-5 -- the pairs section's precision, stated once for the whole group
# ---------------------------------------------------------------------------
# This section publishes ~180 estimates and they are NOT 180 independent
# measurements: they are the same two OLS coefficients, the same OU fit and the
# same standardised spread, recomputed on 91 overlapping windows. Manufacturing
# 91x3 intervals would look like coverage while saying nothing a reader can use,
# so the section states the BASIS for the group once and records, per family,
# either the estimator that would produce the interval or the reason there is
# none. A per-row band is also the wrong instrument here: a 95 % interval per
# pair, uncorrected across 91 simultaneous tests, understates the family-wise
# uncertainty by construction - the correction that does apply is published in
# `multiple_testing`.
_PAIRS_NO_PER_ROW_BAND_REASON = (
    "not computed per row: this family is one estimator re-run on every pair of "
    "a simultaneous scan, so a per-row band would understate the family-wise "
    "uncertainty by construction - at 91 tests an uncorrected 95 % interval is "
    "not a 95 % statement about any single pair. The correction that does apply "
    "is published once, over the whole family, in multiple_testing. The "
    "per-row standard error is computable from each row's own overlap "
    "(OLS, two coefficients, ddof=1, no autocorrelation correction) and is "
    "deliberately not published 91 times: the sample depths differ row by row, "
    "so a reader who needs one must recompute it from the row's "
    "overlap_observations, and a uniform-looking field would hide that spread."
)
_PAIRS_FAMILY_ALPHA_REASON = (
    "not applicable: family_alpha is the significance level the whole family of "
    "tests is declared at - a threshold chosen before any test ran, not a "
    "quantity estimated from data. An interval around a threshold would be a "
    "statement about the analyst's choice, not about the market."
)
_PAIRS_DECISION_REASON = (
    "not applicable: is_cointegrated and johansen_cointegrated are hypothesis "
    "VERDICTS, not estimates. Their uncertainty is the false-positive rate of "
    "the test, which is declared once in signal_policy and corrected once in "
    "multiple_testing; a per-row interval on a boolean would be meaningless."
)


def _pairs_family_entry(
    *,
    estimator: Optional[str],
    estimated_parameters: int,
    status: str,
    reason: str,
) -> Dict[str, Any]:
    """One pairs family's precision disclosure, in the shared entry shape.

    `conf_int` is present and null. The section publishes no per-row interval,
    and a consumer has to be able to SEE that it publishes none - an absent key
    is indistinguishable from a family whose uncertainty was never considered.
    """
    return {
        "point": None,
        "standard_error": None,
        "conf_int": None,
        "conf_int_level": None,
        "conf_int_method": None,
        "conf_int_basis": None,
        "point_within_conf_int": None,
        "point_within_conf_int_note": None,
        "observations": None,
        "effective_n": None,
        "status": status,
        "reason": reason,
        "estimator": estimator,
        "estimated_parameters": estimated_parameters,
    }


def _pairs_estimate_uncertainty(
    pairs: Sequence[Any],
    comparisons: Optional[int],
    p_value_threshold: float,
) -> Dict[str, Any]:
    """One precision declaration covering every estimated family in the scan."""
    rows = list(pairs or [])
    depths = [
        int(getattr(row, "overlap_observations", 0) or 0)
        for row in rows
    ]
    depths = [depth for depth in depths if depth > 0]
    families = {
        "hedge_ratio_beta": _pairs_family_entry(
            estimator=(
                "OLS slope of P_A on P_B (np.polyfit degree 1) over the pair's "
                "own overlapping window"
            ),
            estimated_parameters=2,
            status="not_computed",
            reason=_PAIRS_NO_PER_ROW_BAND_REASON,
        ),
        "intercept_alpha": _pairs_family_entry(
            estimator=(
                "OLS intercept of P_A on P_B, in the price space of the pair"
            ),
            estimated_parameters=2,
            status="not_computed",
            reason=_PAIRS_NO_PER_ROW_BAND_REASON,
        ),
        "ou_reversion_speed_theta": _pairs_family_entry(
            estimator=(
                "Ornstein-Uhlenbeck mean-reversion speed fitted to the OLS "
                "spread, ln(spread[t-1]/spread[t]) regressed on dt"
            ),
            estimated_parameters=1,
            status="not_computed",
            reason=_PAIRS_NO_PER_ROW_BAND_REASON,
        ),
        "ou_half_life_days": _pairs_family_entry(
            estimator="ln(2) / ou_reversion_speed_theta",
            estimated_parameters=0,
            status="not_computed",
            reason=(
                "not computed: this field is a deterministic transformation of "
                "ou_reversion_speed_theta, so it inherits that estimate's "
                "uncertainty rather than carrying an independent one. When theta "
                "is not positive the transform has no finite value and the field "
                "is null, which is an absence rather than a wide interval."
            ),
        ),
        "current_spread_zscore": _pairs_family_entry(
            estimator=(
                "the pair's last spread standardised by that pair's own sample "
                "mean and sample standard deviation (ddof=1)"
            ),
            estimated_parameters=2,
            status="not_computed",
            reason=_PAIRS_NO_PER_ROW_BAND_REASON,
        ),
        "engle_granger_pvalue": _pairs_family_entry(
            estimator="statsmodels Engle-Granger two-step cointegration p-value",
            estimated_parameters=0,
            status="not_applicable",
            reason=(
                "not applicable: a p-value is a hypothesis-test verdict already "
                "expressed on the probability scale, not a point estimate in the "
                "measured units. Its uncertainty is the test's power and its "
                "false-positive rate, both of which are declared in "
                "signal_policy and multiple_testing."
            ),
        ),
        "family_alpha": _pairs_family_entry(
            estimator=None,
            estimated_parameters=0,
            status="not_applicable",
            reason=_PAIRS_FAMILY_ALPHA_REASON,
        ),
        "is_cointegrated": _pairs_family_entry(
            estimator=None,
            estimated_parameters=0,
            status="not_applicable",
            reason=_PAIRS_DECISION_REASON,
        ),
        "johansen_cointegrated": _pairs_family_entry(
            estimator=None,
            estimated_parameters=0,
            status="not_applicable",
            reason=_PAIRS_DECISION_REASON,
        ),
    }
    declared_comparisons = (
        int(comparisons) if isinstance(comparisons, int) and comparisons > 0 else None
    )
    with_interval = [
        name for name, family in families.items() if family["status"] == "computed"
    ]
    return {
        "scope": (
            "every estimated family published by this scan, declared once for "
            "the group rather than repeated per pair row"
        ),
        "status": "computed" if with_interval else "not_computed",
        "reason": None if with_interval else (
            "no per-row interval is published for this family by design; each "
            "family states its estimator and its reason under "
            "estimates.<family>.reason"
        ),
        "method": None,
        "method_basis": (
            "no per-row resampling interval is published here. The section runs "
            f"{declared_comparisons} simultaneous tests on overlapping windows, "
            "so a per-row band would look like coverage while understating the "
            "family-wise error; the family-level correction is published once in "
            "multiple_testing instead."
        ),
        "confidence_level": None,
        "row_count": len(rows),
        "comparisons_made": declared_comparisons,
        "p_value_threshold": p_value_threshold,
        "delivered_row_observations": (
            {
                "min": min(depths),
                "max": max(depths),
                "field": "overlap_observations",
                "basis": (
                    "the sample depth of the delivered rows, which is the n an "
                    "estimator on any one of them rests on. The spread across "
                    "rows is the reason a single uniform interval is not "
                    "published for the group."
                ),
            }
            if depths
            else None
        ),
        "residual_gap": (
            "This section publishes a DECLARED ABSENCE, not a precision "
            "measurement, so a rule that requires a standard error, an interval "
            "or an effective-sample-size figure will keep flagging it. That is "
            "the correct outcome of an honest gap, not a rule to satisfy: the "
            "per-row OLS standard errors this block describes are not in the "
            "scan response contract, and manufacturing 91 intervals to make a "
            "check pass would convert a known gap into a false precision. The "
            "real fix is a standard-error field on the per-pair result."
        ),
        "estimates": families,
    }


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
    # route invented when the scan did not publish one. The signal-policy and
    # multiplicity constants come from the same place: a reader has to be able to
    # find where the +/-1.5 and the correction came from, and the engine is the
    # only thing that knows.
    from app.services.cointegration_service import (
        DECISION_TEST,
        DIAGNOSTIC_TEST,
        MULTIPLICITY_CORRECTION,
        SIGNAL_DIRECTIVE_HEADS,
        SIGNAL_NOTIONAL_CONVENTION,
        SIGNAL_ZSCORE_THRESHOLD,
        SIGNAL_ZSCORE_THRESHOLD_BASIS,
        MIN_PAIR_DEPTH_RATIO,
        multiplicity_report,
    )

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

    def _signal_head(signal: Any) -> str:
        """The classification token a `signal` string starts with.

        The string is a sentence, so a consumer reads the head to sort pairs
        and the rest to check the evidence. Splitting on the first space is
        exact: every head is a single token, and no head contains a space.
        """
        text = str(signal or "").strip()
        return text.split(" ", 1)[0] if text else ""

    def _directives(
        response: CointScannerResponse,
        family: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        """Every position-naming signal, restated with the numbers it needs.

        A directive is an instruction to trade, so it is the one field here a
        downstream agent may act on. Each entry carries the whole chain that
        allowed it - the two tests, the p-value, the corrected threshold, the
        comparison count, the z-score, its threshold, and the hedge ratio with
        the notional convention that gives it a size - so acting on an entry
        does not require re-deriving anything from prose.
        """
        corrected = family.get("corrected_threshold")
        published: List[Dict[str, Any]] = []
        for pair in list(getattr(response, "pairs", None) or []):
            if _signal_head(getattr(pair, "signal", None)) not in SIGNAL_DIRECTIVE_HEADS:
                continue
            published.append(
                {
                    "ticker_a": getattr(pair, "ticker_a", None),
                    "ticker_b": getattr(pair, "ticker_b", None),
                    "direction": _signal_head(getattr(pair, "signal", None)),
                    "engle_granger_pvalue": getattr(pair, "engle_granger_pvalue", None),
                    "decision_test": DECISION_TEST,
                    "diagnostic_test": DIAGNOSTIC_TEST,
                    "johansen_agrees_with_decision": getattr(
                        pair, "johansen_agrees_with_decision", None
                    ),
                    "comparisons_made": family.get("comparisons_made"),
                    "correction_applied": MULTIPLICITY_CORRECTION,
                    "corrected_p_value_threshold": corrected,
                    "survives_correction": True,
                    "spread_zscore": getattr(pair, "current_spread_zscore", None),
                    "zscore_threshold": SIGNAL_ZSCORE_THRESHOLD,
                    "hedge_ratio_beta": getattr(pair, "hedge_ratio_beta", None),
                    "notional_convention": (
                        f"1 unit of currency notional in {getattr(pair, 'ticker_a', None)} "
                        f"against {getattr(pair, 'hedge_ratio_beta', None)} units in "
                        f"{getattr(pair, 'ticker_b', None)}"
                    ),
                    "overlap_observations": getattr(pair, "overlap_observations", None),
                    "depth_status": getattr(pair, "depth_status", None),
                    "ou_half_life_days": getattr(pair, "ou_half_life_days", None),
                }
            )
        return published

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
        extras["test_agreement"] = _pairs_test_agreement(
            list(getattr(response, "pairs", None) or []),
            test_roles=getattr(response, "test_roles", None),
        )
        # SI-5: the section's precision, declared once for the whole scan. 91
        # per-row bands would look like coverage and understate the family-wise
        # error, so the families are named with their estimator and their reason
        # and the multiplicity that DOES apply stays in `multiple_testing`.
        extras["estimate_uncertainty"] = _pairs_estimate_uncertainty(
            list(getattr(response, "pairs", None) or []),
            comparisons=getattr(response, "scanned_pairs_count", None),
            p_value_threshold=p_value_threshold,
        )

        # --- multiplicity + signal policy (SI-1 / AD-1) ------------------
        # `scanned_pairs_count` is the family: the number of tests the scan
        # ran, which is not always the number of rows delivered. Everything
        # below is derived from that one number so the payload states its own
        # null expectation instead of leaving the reader to guess it.
        family = multiplicity_report(
            pairs,
            family_alpha=p_value_threshold,
            comparisons_made=getattr(response, "scanned_pairs_count", None),
        )
        extras["multiple_testing"] = family
        extras["signal_policy"] = {
            "zscore_threshold": SIGNAL_ZSCORE_THRESHOLD,
            "zscore_threshold_basis": SIGNAL_ZSCORE_THRESHOLD_BASIS,
            "zscore_threshold_provenance": "fixed_engine_constant_not_calibrated",
            "engle_granger_p_value_threshold": p_value_threshold,
            "p_value_threshold_comparison": "strictly_less_than",
            "engle_granger_role": "published_decision",
            "johansen_role": "diagnostic_only",
            "notional_convention": SIGNAL_NOTIONAL_CONVENTION,
            "gate": MULTIPLICITY_CORRECTION,
            "gate_rule": (
                "A signal names a position only when all of: Engle-Granger "
                "declared the pair cointegrated, the Johansen diagnostic agrees, "
                "hedge_ratio_beta is positive, the p-value survives the "
                f"{MULTIPLICITY_CORRECTION} correction over the whole family, and "
                f"the spread z-score is past +/-{SIGNAL_ZSCORE_THRESHOLD:g}. "
                "Every other state is published under its own non-action head and "
                "carries the reason inline."
            ),
            "action_naming_heads": list(SIGNAL_DIRECTIVE_HEADS),
        }
        directives = _directives(response, family)
        extras["directives"] = directives
        extras["directive_count"] = len(directives)
        withheld = [
            pair
            for pair in pairs
            if _signal_head(getattr(pair, "signal", None)) not in SIGNAL_DIRECTIVE_HEADS
        ]
        extras["directive_withheld_count"] = len(withheld)
        contested = sum(
            1
            for pair in pairs
            if _signal_head(getattr(pair, "signal", None)) == "CONTESTED_TESTS_DISAGREE"
        )
        extras["contested_pair_count"] = contested

        declared = family.get("declared_positive_count") or 0
        survivors = family.get("survivor_count") or 0
        comparisons = family.get("comparisons_made") or 0
        # "0 survive" / "1 survives": a disclosure sentence that reads wrong
        # is a sentence a reader discounts, and this one carries the number the
        # whole fix turns on.
        survive_text = (
            f"{survivors} survive{'s' if survivors == 1 else ''}"
        )
        pair_text = f"{declared} pair{'' if declared == 1 else 's'}"
        if comparisons and declared and not survivors:
            warnings.append(
                f"Multiple testing: {comparisons} simultaneous cointegration "
                f"tests were run at alpha={p_value_threshold:g}, so "
                f"{p_value_threshold * 100:g}% of them are expected to look "
                f"significant by chance alone "
                f"({p_value_threshold * comparisons:.2f} false positives "
                f"expected). {pair_text} {'was' if declared == 1 else 'were'} "
                f"declared cointegrated and {survive_text} "
                f"{MULTIPLICITY_CORRECTION} at p < "
                f"{family.get('corrected_threshold')}. The declared positives are "
                f"the null expectation, not a discovery, and no spread directive "
                f"is published for them."
            )
        elif comparisons and declared:
            warnings.append(
                f"Multiple testing: {comparisons} simultaneous cointegration "
                f"tests were run at alpha={p_value_threshold:g}, so "
                f"{p_value_threshold * 100:g}% of them are expected to look "
                f"significant by chance alone "
                f"({p_value_threshold * comparisons:.2f} false positives "
                f"expected). {pair_text} {'was' if declared == 1 else 'were'} "
                f"declared cointegrated and {survive_text} "
                f"{MULTIPLICITY_CORRECTION} at p < "
                f"{family.get('corrected_threshold')}; only the survivors may "
                f"carry a spread directive."
            )
        if contested:
            warnings.append(
                f"Contested pairs: {contested} pair{'' if contested == 1 else 's'} "
                f"{'is' if contested == 1 else 'are'} cointegrated under "
                f"engle_granger but not under the johansen diagnostic, so the "
                f"two tests disagree. A contested pair is not a trade and "
                f"publishes no direction; see test_agreement."
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
        # A scan whose declared cointegrations do not survive the family's
        # correction has not established what it says it established, so it is
        # `partial` on the same footing as limited depth: the numbers are real
        # and the conclusion they support is not. Demoted only when there is
        # something to demote (positives declared, none surviving); a clean
        # scan of 91 negatives is not degraded.
        family_report = multiplicity_report(
            list(result.pairs),
            family_alpha=p_value_threshold,
            comparisons_made=result.scanned_pairs_count,
        )
        multiplicity_unconfirmed = bool(
            (family_report.get("declared_positive_count") or 0)
            and not (family_report.get("survivor_count") or 0)
        )
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
                partial=(
                    bool(result.unpairable_tickers)
                    or depth_status == "partial"
                    or multiplicity_unconfirmed
                ),
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


# --- Tail risk: which level was fitted and which level is reported ----------
# Two numbers in this payload used to be read as the same thing. `threshold_u`
# sits at the POT threshold quantile (0.95 by default), so only the worst ~5% of
# the loss sample is fitted and 26 of 518 observations are the exceedances - yet
# `confidence_level` is 0.99 and the `evt_pot_var_99` field names read as though
# a 1% tail had been fitted. Both are legitimate and neither is wrong; what was
# missing is that they are different levels, so the threshold basis is published
# with the measured exceedance fraction beside it. The fit is not changed.
POT_THRESHOLD_BASIS_RULE = (
    "Peaks-over-threshold is FIT on the losses strictly above the empirical "
    "threshold_quantile of the return sample; the reported VaR/ES is the "
    "confidence_level quantile OF THAT FITTED TAIL. threshold_u and "
    "exceedance_fraction therefore describe the fitting threshold, while "
    "confidence_level and the *_99 fields describe the reported level. They are "
    "different levels on purpose: the tail is fitted where there are enough "
    "exceedances to be stable, and reported at the level the caller asked for."
)


def _pot_threshold_disclosure(
    evt_stats: Mapping[str, Any],
    *,
    confidence_level: Any,
    threshold_quantile: Any,
) -> Dict[str, Any]:
    """Declare the level the POT tail was fitted at, measured from the fit."""
    exceedances = evt_stats.get("exceedances_count")
    total = evt_stats.get("total_observations")
    try:
        exceedances = int(exceedances)
        total = int(total)
    except (TypeError, ValueError):
        exceedances = total = None
    fraction = (
        round(exceedances / total, 6)
        if exceedances is not None and total
        else None
    )
    return {
        "pot_threshold_basis": {
            "rule": POT_THRESHOLD_BASIS_RULE,
            "threshold_quantile": (
                float(threshold_quantile)
                if isinstance(threshold_quantile, (int, float))
                and not isinstance(threshold_quantile, bool)
                else None
            ),
            "reported_level": (
                float(confidence_level)
                if isinstance(confidence_level, (int, float))
                and not isinstance(confidence_level, bool)
                else evt_stats.get("confidence_level")
            ),
            "exceedance_fraction": fraction,
            "exceedances_count": exceedances,
            "total_observations": total,
            "threshold_u": evt_stats.get("threshold_u"),
            "level_fields": {
                "fitted": "threshold_u",
                "reported": "confidence_level",
            },
            "suffixed_field_rule": (
                "evt_pot_var_99 / evt_pot_es_99 / historical_var_99 / "
                "historical_es_99 are the same values as the unsuffixed fields, "
                "published only when confidence_level is exactly 0.99. The suffix "
                "names the REPORTED level; it is not the POT threshold level."
            ),
        },
    }


GPD_SHAPE_USAGE_RULE = (
    "evt_pot_var / evt_pot_es (and the historical floors they are max'd against) "
    "are computed from the CONSTRAINED GPD moments. gpd_shape_xi is the raw "
    "maximum-likelihood fit and gpd_shape_xi_constrained is the clipped value that "
    "produced those moments, so gpd_shape_xi_used is the parameter the reported "
    "risk was actually computed from."
)


def _gpd_shape_usage_disclosure(evt_stats: Mapping[str, Any]) -> Dict[str, Any]:
    """Name the GPD shape that produced the reported tail risk.

    The service publishes the raw MLE fit under `gpd_shape_xi` (deliberately: it
    is the unconstrained estimate) while computing the metrics from the clipped
    value, so the field a consumer reaches for first is not the one that produced
    the answer. The used value is published explicitly rather than by overwriting
    the raw one.
    """
    raw = evt_stats.get("gpd_shape_xi_raw")
    constrained = evt_stats.get("gpd_shape_xi_constrained")
    clipped = bool(evt_stats.get("gpd_shape_constrained"))
    if clipped and constrained is not None:
        used, basis = constrained, "constrained_clip"
    elif raw is not None:
        used, basis = raw, "raw_maximum_likelihood_fit"
    else:
        used, basis = None, "unavailable"
    return {
        "gpd_shape_xi_used": used,
        "gpd_shape_xi_used_basis": basis,
        "gpd_shape_xi_used_rule": GPD_SHAPE_USAGE_RULE,
        "gpd_shape_constraint_reason": evt_stats.get("constraint_reason"),
        "gpd_shape_xi_raw_field": "gpd_shape_xi_raw",
        "gpd_shape_xi_raw_equals_published_headline": (
            raw is not None and evt_stats.get("gpd_shape_xi") == round(float(raw), 4)
        ),
    }


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
            **_pot_threshold_disclosure(
                evt_stats, confidence_level=confidence_level,
                threshold_quantile=threshold_quantile,
            ),
            **_gpd_shape_usage_disclosure(evt_stats),
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

