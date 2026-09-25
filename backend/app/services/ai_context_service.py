"""
Portfolio AI context export.

Builds one stable, AI-readable snapshot from the same portfolio and analytics
services that power the dashboard.  The exporter never rebalances, clears
caches, or changes holdings; normal quote/cache refresh performed by the
underlying read endpoints may still occur.  JSON is the canonical
representation; Markdown is rendered from it.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import analytics as analytics_api
from app.api import data as data_api
from app.api import portfolio as portfolio_api
from app.models.schemas import StressTestRequest
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


SCHEMA_VERSION = "1.0"
DEFAULT_SECTIONS: Tuple[str, ...] = (
    "portfolio",
    "dashboard",
    "realized_risk",
    "forecast_risk",
    "factor_exposure",
    "concentration",
    "liquidity",
    "stress_testing",
    "volatility_sizing",
    "tear_sheet",
    "risk_contribution",
    "risk_studio",
    "optimization",
    "regime",
    "monte_carlo",
    "pairs",
    "india_flows",
)

SECTION_CATALOG: Dict[str, Dict[str, str]] = {
    "portfolio": {
        "title": "Portfolio Management",
        "route": "/portfolio/manage",
    },
    "dashboard": {
        "title": "Portfolio Dashboard",
        "route": "/dashboard",
    },
    "realized_risk": {
        "title": "Realized Risk",
        "route": "/dashboard/realized-risk",
    },
    "forecast_risk": {
        "title": "Forecast Risk",
        "route": "/dashboard/forecast-risk",
    },
    "factor_exposure": {
        "title": "Factor Exposure",
        "route": "/dashboard/factor-exposure",
    },
    "concentration": {
        "title": "Concentration",
        "route": "/dashboard/concentration",
    },
    "liquidity": {
        "title": "Liquidity",
        "route": "/dashboard/liquidity",
    },
    "stress_testing": {
        "title": "Stress Testing",
        "route": "/dashboard/stress-testing",
    },
    "volatility_sizing": {
        "title": "Volatility Sizing",
        "route": "/dashboard/volatility-sizing",
    },
    "tear_sheet": {
        "title": "Tear Sheet",
        "route": "/dashboard/tear-sheet",
    },
    "risk_contribution": {
        "title": "Risk Contribution",
        "route": "/dashboard/risk-contribution",
    },
    "risk_studio": {
        "title": "Risk Studio",
        "route": "/dashboard/risk-studio",
    },
    "optimization": {
        "title": "Optimizer",
        "route": "/dashboard/optimize",
    },
    "regime": {
        "title": "Market Regime",
        "route": "/dashboard/regime",
    },
    "monte_carlo": {
        "title": "Goal Probability",
        "route": "/dashboard/monte-carlo",
    },
    "pairs": {
        "title": "Pairs Scanner",
        "route": "/dashboard/pairs",
    },
    "india_flows": {
        "title": "India Market Microstructure",
        "route": "/dashboard/india-flows",
    },
}

_SECTION_ALIASES = {
    "portfolio_management": "portfolio",
    "manage": "portfolio",
    "risk-studio": "risk_studio",
    "realized-risk": "realized_risk",
    "forecast-risk": "forecast_risk",
    "factor-exposure": "factor_exposure",
    "stress-testing": "stress_testing",
    "volatility-sizing": "volatility_sizing",
    "tear-sheet": "tear_sheet",
    "risk-contribution": "risk_contribution",
    "monte-carlo": "monte_carlo",
    "india-flows": "india_flows",
}

_ALLOWED_CURRENCIES = frozenset({"INR", "USD"})
_ALLOWED_MODELS = frozenset({"GARCH", "EGARCH", "EWMA"})
_ALLOWED_STRATEGIES = frozenset({"hrp", "min_vol", "max_sharpe", "min_cvar", "black_litterman"})
_ALLOWED_METHODS = frozenset({"gbm", "student_t", "bootstrap"})
_STRESS_SCENARIOS: Tuple[str, ...] = (
    "Market Crash",
    "Interest Rate Shock",
    "Volatility Spike",
    "Tech Sector Correction",
)
_SECTION_TIMEOUT_SECONDS = 180.0


@dataclass(frozen=True)
class ContextOptions:
    """Validated inputs used to build one context export."""

    detail: str = "summary"
    include: Tuple[str, ...] = DEFAULT_SECTIONS
    base_currency: str = "INR"
    forecast_model: str = "GARCH"
    forecast_horizon: int = 1
    factor_lookback_days: int = 252
    optimization_strategy: str = "hrp"
    monte_carlo_method: str = "student_t"
    monte_carlo_horizon_years: float = 5.0
    monte_carlo_target_value: Optional[float] = None
    monte_carlo_seed: int = 42


@dataclass
class _Collected:
    data: Any
    inputs: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    status: Optional[str] = None
    error: Optional[str] = None


@dataclass
class _BuildContext:
    options: ContextOptions
    base_currency: str
    portfolio: Any
    tickers: List[str]
    ticker_csv: Optional[str]
    total_value: float
    cached: Dict[str, Any] = field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    """Convert route/service values into strict JSON-safe primitives."""
    if isinstance(value, BaseModel):
        if hasattr(value, "model_dump"):
            return _jsonable(value.model_dump(mode="json"))
        return _jsonable(value.dict())
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        try:
            return _jsonable(tolist())
        except Exception:
            pass
    # numpy scalar values expose item(); avoid importing numpy just for JSON.
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _jsonable(item())
        except Exception:
            pass
    return value


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
        return f"Analytics request failed ({exc.status_code})"
    return "Analytics result unavailable"


def parse_include(value: Optional[str]) -> Tuple[str, ...]:
    """Parse and validate the optional comma-separated section selector."""
    if value is None or not value.strip():
        return DEFAULT_SECTIONS

    requested: List[str] = []
    seen = set()
    for raw in value.split(","):
        item = raw.strip().lower()
        if not item:
            continue
        item = _SECTION_ALIASES.get(item, item)
        if item not in SECTION_CATALOG:
            raise ValueError(f"Unknown AI context section: {raw.strip()}")
        if item not in seen:
            seen.add(item)
            requested.append(item)
    if not requested:
        raise ValueError("At least one AI context section is required")
    return tuple(key for key in DEFAULT_SECTIONS if key in seen)


def _validate_options(options: ContextOptions) -> ContextOptions:
    detail = str(options.detail or "summary").strip().lower()
    if detail not in {"summary", "full"}:
        raise ValueError("detail must be summary or full")

    currency = str(options.base_currency or "INR").strip().upper()
    if currency not in _ALLOWED_CURRENCIES:
        raise ValueError("base_currency must be INR or USD")

    model = str(options.forecast_model or "GARCH").strip().upper()
    if model not in _ALLOWED_MODELS:
        raise ValueError("forecast_model must be GARCH, EGARCH, or EWMA")

    strategy = str(options.optimization_strategy or "hrp").strip().lower()
    if strategy not in _ALLOWED_STRATEGIES:
        raise ValueError("optimization_strategy is not supported")

    method = str(options.monte_carlo_method or "student_t").strip().lower()
    if method not in _ALLOWED_METHODS:
        raise ValueError("monte_carlo_method is not supported")

    if not 1 <= int(options.forecast_horizon) <= 30:
        raise ValueError("forecast_horizon must be between 1 and 30")
    if not 30 <= int(options.factor_lookback_days) <= 756:
        raise ValueError("factor_lookback_days must be between 30 and 756")
    if not 1 <= float(options.monte_carlo_horizon_years) <= 40:
        raise ValueError("monte_carlo_horizon_years must be between 1 and 40")
    if options.monte_carlo_target_value is not None:
        target = float(options.monte_carlo_target_value)
        if not math.isfinite(target) or target <= 0:
            raise ValueError("monte_carlo_target_value must be positive and finite")
    if not 0 <= int(options.monte_carlo_seed) <= 2**32 - 1:
        raise ValueError("monte_carlo_seed must fit an unsigned 32-bit integer")

    return ContextOptions(
        detail=detail,
        include=tuple(options.include),
        base_currency=currency,
        forecast_model=model,
        forecast_horizon=int(options.forecast_horizon),
        factor_lookback_days=int(options.factor_lookback_days),
        optimization_strategy=strategy,
        monte_carlo_method=method,
        monte_carlo_horizon_years=float(options.monte_carlo_horizon_years),
        monte_carlo_target_value=(
            float(options.monte_carlo_target_value)
            if options.monte_carlo_target_value is not None
            else None
        ),
        monte_carlo_seed=int(options.monte_carlo_seed),
    )


def _has_material_data(value: Any) -> bool:
    """Whether a payload contains more than an error/null placeholder."""
    ignored = {"error", "errors", "methodology", "warnings", "data_range", "status", "message"}
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in ignored:
                continue
            if _has_material_data(item):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_has_material_data(item) for item in value)
    if value is None or value is False:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (int, float)) and value == 0:
        return False
    return True


def _payload_status(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, Mapping):
        if "components" in value:
            return _group_status(value.get("components"))
        if value.get("zero_metrics") and not _has_material_data(value):
            return "unavailable"
        if value.get("error") and not _has_material_data(value):
            return "unavailable"
        if value.get("error"):
            return "partial"
    return "available"


def _group_status(components: Any) -> str:
    if not isinstance(components, Mapping) or not components:
        return "unavailable"
    statuses = []
    for component in components.values():
        if isinstance(component, Mapping) and component.get("status") in {
            "available", "partial", "unavailable"
        }:
            statuses.append(str(component["status"]))
    if not statuses or all(status == "unavailable" for status in statuses):
        return "unavailable"
    if any(status != "available" for status in statuses):
        return "partial"
    return "available"


def _as_of(value: Any) -> Optional[str]:
    if not isinstance(value, Mapping):
        return None
    for key in ("as_of", "last_updated", "generated_at", "updated_at"):
        candidate = value.get(key)
        if isinstance(candidate, (str, datetime, date)) and str(candidate).strip():
            return candidate.isoformat() if isinstance(candidate, (datetime, date)) else str(candidate)
    for key in ("data_range", "window"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            candidate = nested.get("end")
            if candidate:
                return str(candidate)
    return None


def _component_status(value: Any) -> str:
    return _payload_status(value)


def _infer_currency(data: Any, inputs: Mapping[str, Any]) -> Optional[str]:
    for source in (inputs, data if isinstance(data, Mapping) else {}):
        for key in (
            "currency",
            "base_currency",
            "portfolio_value_currency",
            "value_currency",
        ):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip().upper()
    return None


def _collect_warnings(value: Any) -> List[str]:
    warnings: List[str] = []
    if isinstance(value, Mapping):
        raw = value.get("warnings")
        if isinstance(raw, list):
            for item in raw:
                if item is None:
                    continue
                if isinstance(item, Mapping):
                    ticker = str(item.get("ticker")).strip() if item.get("ticker") else ""
                    message = str(item.get("message") or item.get("detail") or "").strip()
                    text = f"{ticker}: {message}" if ticker and message else message or str(item)
                else:
                    text = str(item)
                if text:
                    warnings.append(text)
        components = value.get("components")
        if isinstance(components, Mapping):
            for component in components.values():
                if isinstance(component, Mapping):
                    warnings.extend(_collect_warnings(component.get("data")))
    return warnings


class PortfolioContextService:
    """Collect the portfolio pages into one stable AI-facing document."""

    def __init__(
        self,
        db: AsyncSession,
        data_service: Any = None,
        analytics_engine: Any = None,
        benchmark_service: Any = None,
        cache_service: Any = None,
    ) -> None:
        self.db = db
        self.data_service = data_service or analytics_api.get_data_service(db)
        self.analytics_engine = analytics_engine or analytics_api.get_analytics_engine()
        self.benchmark_service = benchmark_service or analytics_api.get_benchmark_service(db)
        self.cache_service = cache_service or analytics_api.get_cache_service(db)

    async def _rollback_quietly(self) -> None:
        try:
            result = self.db.rollback()
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.debug("AI context database rollback failed", exc_info=True)

    async def build(self, options: Optional[ContextOptions] = None) -> Dict[str, Any]:
        options = _validate_options(options or ContextOptions())
        selected = parse_include(",".join(options.include))
        generated_at = _now()
        warnings: List[str] = []

        portfolio_data: Any = None
        portfolio_error: Optional[str] = None
        try:
            portfolio_data = await asyncio.wait_for(
                self._collect_portfolio(options.base_currency),
                timeout=_SECTION_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            await self._rollback_quietly()
            portfolio_error = _safe_error(exc)
            logger.error("AI context portfolio snapshot failed: %s", type(exc).__name__)

        portfolio_json = _jsonable(portfolio_data)
        positions = portfolio_json.get("positions", []) if isinstance(portfolio_json, Mapping) else []
        tickers = [
            str(position.get("ticker"))
            for position in positions
            if isinstance(position, Mapping) and position.get("ticker")
        ]
        ticker_csv = ",".join(tickers) if tickers else None
        total_value = float(portfolio_json.get("total_value", 0.0) or 0.0) if isinstance(portfolio_json, Mapping) else 0.0
        context = _BuildContext(
            options=options,
            base_currency=options.base_currency,
            portfolio=portfolio_json,
            tickers=tickers,
            ticker_csv=ticker_csv,
            total_value=total_value,
        )

        sections: Dict[str, Dict[str, Any]] = {}
        if "portfolio" in selected:
            sections["portfolio"] = self._make_section(
                key="portfolio",
                data=portfolio_json,
                inputs={"currency": options.base_currency, "force_refresh": False},
                error=portfolio_error,
                detail=options.detail,
            )

        if portfolio_error:
            for key in selected:
                if key == "portfolio":
                    continue
                sections[key] = self._make_section(
                    key=key,
                    data=None,
                    inputs={},
                    error=portfolio_error,
                    detail=options.detail,
                )
        elif not tickers:
            # Market-context pages can still be useful without holdings. Do not
            # launch every portfolio calculation only to return the same empty
            # contract for each one.
            for key in selected:
                if key == "portfolio":
                    continue
                if key in {"regime", "india_flows"}:
                    sections[key] = await self._collect_section(key, context)
                else:
                    sections[key] = self._make_section(
                        key=key,
                        data=None,
                        inputs={},
                        error="No portfolio positions found",
                        detail=options.detail,
                    )
        else:
            for key in selected:
                if key == "portfolio":
                    continue
                sections[key] = await self._collect_section(key, context)

        environment: Dict[str, Any]
        try:
            environment = _jsonable(
                await data_api.get_api_config(db=self.db, cache_service=self.cache_service)
            )
        except Exception as exc:
            environment = {}
            warnings.append(f"Data-source metadata unavailable: {_safe_error(exc)}")
            logger.error("AI context environment metadata failed: %s", type(exc).__name__)

        return {
            "schema_version": SCHEMA_VERSION,
            "export_id": f"portfolio-{uuid.uuid4().hex[:12]}",
            "generated_at": generated_at,
            "base_currency": options.base_currency,
            "currency_policy": (
                "Portfolio section uses the requested base_currency; analytics sections "
                "retain their endpoint-declared monetary units."
            ),
            "detail": options.detail,
            "scope": list(selected),
            "environment": environment,
            "sections": sections,
            "warnings": warnings,
        }

    async def _collect_section(self, key: str, context: _BuildContext) -> Dict[str, Any]:
        collector = getattr(self, f"_collect_{key}", None)
        if collector is None:
            return self._make_section(
                key=key,
                data=None,
                inputs={},
                error="AI context section is not implemented",
                detail=context.options.detail,
            )
        try:
            result = await asyncio.wait_for(collector(context), timeout=_SECTION_TIMEOUT_SECONDS)
        except Exception as exc:
            await self._rollback_quietly()
            logger.error("AI context section %s failed: %s", key, type(exc).__name__)
            return self._make_section(
                key=key,
                data=None,
                inputs={},
                error=_safe_error(exc),
                detail=context.options.detail,
            )
        return self._make_section(
            key=key,
            data=result.data,
            inputs=result.inputs,
            warnings=result.warnings,
            error=result.error,
            status=result.status,
            detail=context.options.detail,
        )

    def _make_section(
        self,
        *,
        key: str,
        data: Any,
        inputs: Dict[str, Any],
        detail: str,
        warnings: Optional[Iterable[str]] = None,
        error: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        compact_data, omitted = _compact_detail(key, _jsonable(data), detail)
        resolved_status = status or _payload_status(compact_data)
        if error is None and isinstance(compact_data, Mapping) and compact_data.get("error"):
            error = str(compact_data["error"])
        if error and resolved_status == "available":
            resolved_status = "partial"
        section_warnings = list(warnings or [])
        section_warnings.extend(_collect_warnings(compact_data))
        section_warnings = list(dict.fromkeys(section_warnings))
        section = {
            "key": key,
            "title": SECTION_CATALOG[key]["title"],
            "route": SECTION_CATALOG[key]["route"],
            "status": resolved_status,
            "detail": detail,
            "generated_at": _now(),
            "as_of": _as_of(compact_data),
            "currency": _infer_currency(compact_data, inputs),
            "inputs": _jsonable(inputs),
            "data": compact_data,
            "omitted_fields": omitted,
            "warnings": section_warnings,
        }
        if error:
            section["error"] = error
        return section

    async def _collect_portfolio(self, base_currency: str) -> Any:
        return await portfolio_api.get_portfolio(
            region=None,
            sector=None,
            currency=base_currency,
            force_refresh=False,
            db=self.db,
            data_service=self.data_service,
        )

    async def _component(self, name: str, callback: Callable[[], Awaitable[Any]]) -> Dict[str, Any]:
        try:
            value = await callback()
            json_value = _jsonable(value)
            status = _component_status(json_value)
            result: Dict[str, Any] = {"status": status, "data": json_value}
            if status != "available" and isinstance(json_value, Mapping) and json_value.get("error"):
                result["error"] = str(json_value["error"])
            return result
        except Exception as exc:
            await self._rollback_quietly()
            logger.error("AI context component %s failed: %s", name, type(exc).__name__)
            return {"status": "unavailable", "data": None, "error": _safe_error(exc)}

    async def _collect_dashboard(self, context: _BuildContext) -> _Collected:
        components = {
            "summary": await self._component(
                "summary",
                lambda: analytics_api.get_analytics_summary(
                    db=self.db,
                    data_service=self.data_service,
                    analytics_engine=self.analytics_engine,
                ),
            ),
            "performance_history": await self._component(
                "performance_history",
                lambda: analytics_api.get_performance_history(
                    days=90,
                    tickers=context.ticker_csv,
                    db=self.db,
                    data_service=self.data_service,
                    benchmark_service=self.benchmark_service,
                ),
            ),
        }
        data = {"components": components}
        return _Collected(
            data=data,
            inputs={"performance_days": 90, "tickers": context.tickers},
            status=_group_status(components),
        )

    async def _collect_realized_risk(self, context: _BuildContext) -> _Collected:
        data = await analytics_api.get_realized_risk(
            tickers=context.ticker_csv,
            start=None,
            end=None,
            db=self.db,
            data_service=self.data_service,
            analytics_engine=self.analytics_engine,
        )
        return _Collected(data=data, inputs={"tickers": context.tickers, "lookback_days": 252})

    async def _collect_forecast_risk(self, context: _BuildContext) -> _Collected:
        options = context.options
        data = await analytics_api.get_forecast_risk(
            model=options.forecast_model,
            horizon=options.forecast_horizon,
            tickers=context.ticker_csv,
            start=None,
            end=None,
            db=self.db,
            data_service=self.data_service,
            analytics_engine=self.analytics_engine,
        )
        return _Collected(
            data=data,
            inputs={
                "tickers": context.tickers,
                "model": options.forecast_model,
                "horizon_days": options.forecast_horizon,
            },
        )

    async def _collect_factor_exposure(self, context: _BuildContext) -> _Collected:
        options = context.options
        data = await analytics_api.get_factor_exposure(
            tickers=context.ticker_csv,
            lookback_days=options.factor_lookback_days,
            db=self.db,
            data_service=self.data_service,
            benchmark_service=self.benchmark_service,
            analytics_engine=self.analytics_engine,
        )
        return _Collected(
            data=data,
            inputs={"tickers": context.tickers, "lookback_days": options.factor_lookback_days},
        )

    async def _collect_concentration(self, context: _BuildContext) -> _Collected:
        data = await analytics_api.get_concentration_metrics(
            db=self.db,
            data_service=self.data_service,
            analytics_engine=self.analytics_engine,
        )
        return _Collected(data=data, inputs={"tickers": context.tickers})

    async def _collect_liquidity(self, context: _BuildContext) -> _Collected:
        data = await analytics_api.get_liquidity_metrics(
            db=self.db,
            data_service=self.data_service,
            analytics_engine=self.analytics_engine,
        )
        return _Collected(data=data, inputs={"tickers": context.tickers, "lookback_days": 30})

    async def _collect_stress_testing(self, context: _BuildContext) -> _Collected:
        results: Dict[str, Any] = {}
        failures: Dict[str, str] = {}
        for scenario in _STRESS_SCENARIOS:
            try:
                results[scenario] = await analytics_api.run_stress_test(
                    StressTestRequest(scenario=scenario, tickers=context.tickers or None),
                    db=self.db,
                    data_service=self.data_service,
                    analytics_engine=self.analytics_engine,
                )
            except Exception as exc:
                await self._rollback_quietly()
                failures[scenario] = _safe_error(exc)
        data = {"scenarios": results, "failures": failures}
        status = "available" if results and not failures else "partial" if results else "unavailable"
        return _Collected(
            data=data,
            inputs={"tickers": context.tickers, "scenarios": list(_STRESS_SCENARIOS)},
            status=status,
            warnings=[f"{scenario}: {message}" for scenario, message in failures.items()],
        )

    async def _collect_volatility_sizing(self, context: _BuildContext) -> _Collected:
        data = await analytics_api.get_volatility_sizing(
            model="EWMA",
            target_volatility=0.15,
            portfolio_value=None,
            db=self.db,
            data_service=self.data_service,
            analytics_engine=self.analytics_engine,
        )
        return _Collected(
            data=data,
            inputs={"model": "EWMA", "target_volatility": 0.15, "tickers": context.tickers},
        )

    async def _collect_tear_sheet(self, context: _BuildContext) -> _Collected:
        data = await analytics_api.get_tear_sheet(
            tickers=context.ticker_csv,
            start=None,
            end=None,
            db=self.db,
            data_service=self.data_service,
            benchmark=self.benchmark_service,
        )
        return _Collected(data=data, inputs={"tickers": context.tickers, "lookback_days": 365})

    async def _collect_risk_contribution(self, context: _BuildContext) -> _Collected:
        data = await analytics_api.get_risk_contribution(
            tickers=context.ticker_csv,
            db=self.db,
            data_service=self.data_service,
        )
        context.cached["risk_contribution"] = data
        return _Collected(data=data, inputs={"tickers": context.tickers})

    async def _collect_risk_studio(self, context: _BuildContext) -> _Collected:
        components: Dict[str, Any] = {}
        if "risk_contribution" in context.cached:
            cached = _jsonable(context.cached["risk_contribution"])
            components["risk_contribution"] = {
                "status": _component_status(cached),
                "data": cached,
            }
        else:
            components["risk_contribution"] = await self._component(
                "risk_contribution",
                lambda: analytics_api.get_risk_contribution(
                    tickers=context.ticker_csv,
                    db=self.db,
                    data_service=self.data_service,
                ),
            )
        components["tail_dependence"] = await self._component(
            "tail_dependence",
            lambda: analytics_api.get_tail_risk_and_copula(
                tickers=context.ticker_csv,
                lookback_days=756,
                confidence_level=0.99,
                threshold_quantile=0.95,
                db=self.db,
                data_service=self.data_service,
            ),
        )
        components["volatility_cone"] = await self._component(
            "volatility_cone",
            lambda: analytics_api.get_volatility_cone(
                tickers=context.ticker_csv,
                lookback_days=756,
                db=self.db,
                data_service=self.data_service,
            ),
        )
        components["correlation_stability"] = await self._component(
            "correlation_stability",
            lambda: analytics_api.get_correlation_stability(
                tickers=context.ticker_csv,
                lookback_days=756,
                window_days=60,
                db=self.db,
                data_service=self.data_service,
            ),
        )
        return _Collected(
            data={"components": components},
            inputs={"tickers": context.tickers, "lookback_days": 756},
            status=_group_status(components),
        )

    async def _collect_optimization(self, context: _BuildContext) -> _Collected:
        options = context.options
        request = analytics_api.OptimizeRequest(
            strategy=options.optimization_strategy,
            tickers=context.tickers or None,
        )
        data = await analytics_api.run_optimization(
            body=request,
            tickers=context.ticker_csv,
            db=self.db,
            data_service=self.data_service,
        )
        return _Collected(
            data=data,
            inputs={"tickers": context.tickers, "strategy": options.optimization_strategy},
        )

    async def _collect_regime(self, context: _BuildContext) -> _Collected:
        data = await analytics_api.get_regime(
            lookback_days=1100,
            with_portfolio=bool(context.tickers),
            db=self.db,
            data_service=self.data_service,
            benchmark=self.benchmark_service,
        )
        return _Collected(
            data=data,
            inputs={"lookback_days": 1100, "with_portfolio": bool(context.tickers)},
        )

    async def _collect_monte_carlo(self, context: _BuildContext) -> _Collected:
        options = context.options
        if options.monte_carlo_target_value is not None:
            target = float(options.monte_carlo_target_value)
            target_policy = "explicit"
        else:
            target = float(context.total_value or 0.0) * 2.0
            target_policy = "2x_current_portfolio_value"
        if not math.isfinite(target) or target <= 0:
            data = {
                "error": "Portfolio market value unavailable; provide a positive Monte Carlo target",
                "target_value": target,
            }
            return _Collected(
                data=data,
                inputs={
                    "method": options.monte_carlo_method,
                    "horizon_years": options.monte_carlo_horizon_years,
                    "target_value": target,
                    "target_policy": target_policy,
                    "seed": options.monte_carlo_seed,
                },
            )
        request = analytics_api.MonteCarloRequest(
            target_value=target,
            horizon_years=options.monte_carlo_horizon_years,
            initial_value=context.total_value if context.total_value > 0 else None,
            method=options.monte_carlo_method,
            num_paths=2000,
            seed=options.monte_carlo_seed,
            tickers=context.tickers or None,
        )
        data = await analytics_api.run_monte_carlo(
            body=request,
            tickers=context.ticker_csv,
            db=self.db,
            data_service=self.data_service,
        )
        return _Collected(
            data=data,
            inputs={
                "method": options.monte_carlo_method,
                "horizon_years": options.monte_carlo_horizon_years,
                "target_value": target,
                "target_policy": target_policy,
                "initial_value": context.total_value if context.total_value > 0 else None,
                "num_paths": 2000,
                "seed": options.monte_carlo_seed,
                "tickers": context.tickers,
            },
        )

    async def _collect_pairs(self, context: _BuildContext) -> _Collected:
        data = await analytics_api.get_cointegration_pairs(
            tickers=context.ticker_csv,
            lookback_days=252,
            p_value_threshold=0.05,
            max_half_life=60,
            include_spread_series=context.options.detail == "full",
            db=self.db,
            data_service=self.data_service,
            cache_service=self.cache_service,
        )
        return _Collected(
            data=data,
            inputs={
                "tickers": context.tickers,
                "lookback_days": 252,
                "p_value_threshold": 0.05,
                "max_half_life_days": 60,
                "include_spread_series": context.options.detail == "full",
            },
        )

    async def _collect_india_flows(self, context: _BuildContext) -> _Collected:
        components = {
            "institutional_flows": await self._component(
                "institutional_flows",
                lambda: analytics_api.get_india_institutional_flows(
                    lookback_days=30,
                    db=self.db,
                ),
            ),
            "delivery_anomalies": await self._component(
                "delivery_anomalies",
                lambda: analytics_api.get_delivery_anomalies(
                    tickers=context.ticker_csv,
                    lookback_days=20,
                    sigma_threshold=2.0,
                    db=self.db,
                ),
            ),
            "liquidity_limits": await self._component(
                "liquidity_limits",
                lambda: analytics_api.get_liquidity_limits(
                    tickers=None,
                    db=self.db,
                    data_service=self.data_service,
                ),
            ),
        }
        return _Collected(
            data={"components": components},
            inputs={"tickers": context.tickers, "flow_lookback_days": 30},
            status=_group_status(components),
        )


def _compact_detail(key: str, data: Any, detail: str) -> Tuple[Any, List[str]]:
    """Keep the default export token-dense while preserving full opt-in data."""
    if detail == "full" or data is None:
        return data, []

    compact = copy.deepcopy(data)
    omitted: List[str] = []

    def trim_list(container: Mapping[str, Any], field: str, limit: int) -> None:
        value = container.get(field) if isinstance(container, Mapping) else None
        if isinstance(value, list) and len(value) > limit:
            container[field] = value[-limit:]  # type: ignore[index]
            omitted.append(field)

    if key == "dashboard":
        components = compact.get("components") if isinstance(compact, dict) else None
        performance = components.get("performance_history") if isinstance(components, dict) else None
        if isinstance(performance, dict):
            values = performance.get("data")
            if isinstance(values, list) and len(values) > 90:
                performance["data"] = values[-90:]
                omitted.append("components.performance_history.data")
    elif key == "tear_sheet" and isinstance(compact, dict):
        monthly = compact.get("monthly_returns")
        if isinstance(monthly, dict) and len(monthly) > 24:
            compact["monthly_returns"] = dict(list(monthly.items())[-24:])
            omitted.append("monthly_returns")
        trim_list(compact, "underwater", 90)
    elif key == "monte_carlo" and isinstance(compact, dict):
        trim_list(compact, "fan", 12)
    elif key == "pairs" and isinstance(compact, dict):
        for pair in compact.get("pairs", []) if isinstance(compact.get("pairs"), list) else []:
            if isinstance(pair, dict):
                trim_list(pair, "spread_series", 90)
                if omitted and omitted[-1] == "spread_series":
                    omitted[-1] = "pairs.spread_series"
    elif key == "risk_studio":
        components = compact.get("components") if isinstance(compact, dict) else None
        correlation = components.get("correlation_stability") if isinstance(components, dict) else None
        if isinstance(correlation, dict) and isinstance(correlation.get("data"), dict):
            trim_list(correlation["data"], "series", 60)
            if omitted and omitted[-1] == "series":
                omitted[-1] = "components.correlation_stability.series"
    elif key == "india_flows":
        components = compact.get("components") if isinstance(compact, dict) else None
        flows = components.get("institutional_flows") if isinstance(components, dict) else None
        if isinstance(flows, dict) and isinstance(flows.get("data"), dict):
            values = flows["data"].get("flows")
            if isinstance(values, list) and len(values) > 30:
                flows["data"]["flows"] = values[-30:]
                omitted.append("components.institutional_flows.flows")

    return compact, sorted(set(omitted))


def render_markdown(payload: Mapping[str, Any]) -> str:
    """Render a stable Markdown view from the canonical JSON payload."""
    safe_payload = _jsonable(payload)
    lines: List[str] = [
        "# FinEngine Portfolio AI Context",
        "",
        f"- Generated: `{safe_payload.get('generated_at', '')}`",
        f"- Base currency: `{safe_payload.get('base_currency', '')}`",
        f"- Currency policy: {safe_payload.get('currency_policy', '')}",
        f"- Detail: `{safe_payload.get('detail', 'summary')}`",
        f"- Schema: `{safe_payload.get('schema_version', SCHEMA_VERSION)}`",
        f"- Sections: `{', '.join(safe_payload.get('scope', []))}`",
        "",
        "Values marked unavailable or partial are intentionally not inferred or filled with placeholders.",
        "",
    ]

    environment = safe_payload.get("environment")
    if environment:
        lines.extend(["## Environment", "", "```json", _pretty(environment), "```", ""])

    sections = safe_payload.get("sections", {})
    if isinstance(sections, Mapping):
        for key, section in sections.items():
            if not isinstance(section, Mapping):
                continue
            lines.extend(
                [
                    f"## {section.get('title', key)}",
                    "",
                    f"- Key: `{key}`",
                    f"- Route: `{section.get('route', '')}`",
                    f"- Status: `{section.get('status', 'unavailable')}`",
                ]
            )
            if section.get("as_of"):
                lines.append(f"- As of: `{section['as_of']}`")
            if section.get("currency"):
                lines.append(f"- Monetary unit: `{section['currency']}`")
            if section.get("inputs"):
                lines.extend(["", "### Inputs", "", "```json", _pretty(section["inputs"]), "```"])
            if section.get("error"):
                lines.extend(["", f"**Error:** {section['error']}"])
            if section.get("warnings"):
                lines.extend(["", "### Warnings", ""])
                lines.extend(f"- {warning}" for warning in section["warnings"])
            if section.get("omitted_fields"):
                lines.extend(
                    [
                        "",
                        "### Summary-mode omissions",
                        "",
                        "The following raw series were shortened; use `detail=full` to retain them:",
                    ]
                )
                lines.extend(f"- `{field}`" for field in section["omitted_fields"])
            if section.get("data") is not None:
                lines.extend(["", "### Data", "", "```json", _pretty(section["data"]), "```"])
            lines.append("")

    if safe_payload.get("warnings"):
        lines.extend(["## Export warnings", ""])
        lines.extend(f"- {warning}" for warning in safe_payload["warnings"])
        lines.append("")

    return "\n".join(lines)


def _pretty(value: Any) -> str:
    return json.dumps(_jsonable(value), ensure_ascii=False, indent=2, allow_nan=False)
