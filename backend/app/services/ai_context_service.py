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
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import analytics as analytics_api
from app.api import data as data_api
from app.api import portfolio as portfolio_api
from app.api.analytics import (
    ACTIVE_WEIGHT_BASIS,
    DATA_STATUS_VOCABULARY,
    # Shared deterministic ticker ordering (request order first, extras sorted).
    _ordered_universe as _order_universe,
)
from app.models.schemas import StressTestRequest
from app.services.ai_context_india import compose_india_composite
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


SCHEMA_VERSION = "2.0"
# Set once per export so a "written during this run" timestamp can be recognised.
_EXPORT_STARTED_AT: List[Optional[datetime]] = [None]
# Public section-status vocabulary, mirrored by AIContextSection.status.
# A section that was not requested is absent from the export; it is never
# serialized as a `not_requested` placeholder row.
SECTION_STATUS_VOCABULARY: Tuple[str, ...] = (
    "available",
    "partial",
    "unavailable",
)
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

#: The stress composite is a set of scenarios, each measured over its own
#: delivered frame. It dates itself by the OLDEST of them, which is the
#: envelope's own composite rule: a section is only as fresh as its stalest leg,
#: so a scenario that happened to receive a newer bar cannot make the whole
#: section - including its worst loss - look fresher than it is.
STRESS_AS_OF_SEMANTICS = "oldest_scenario_latest_observation_date"
STRESS_AS_OF_BASIS = (
    "min over scenarios of each scenario's latest_observation_date, which is the "
    "newest bar in the frame its volatility factors were measured over; "
    "scenario_observation_dates publishes the per-scenario values"
)


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
    cached_sections: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    active_tickers: List[str] = field(default_factory=list)


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
    if isinstance(value, (list, tuple, set)) and not value:
        return "unavailable"
    if isinstance(value, Mapping):
        components = value.get("components")
        if isinstance(components, Mapping) and any(
            isinstance(component, Mapping)
            and component.get("status") in {"available", "partial", "unavailable"}
            for component in components.values()
        ):
            return _group_status(components)
        declared = _normalize_data_status(value.get("data_status"))
        if declared in {"unavailable", "partial"}:
            return declared
        if value.get("zero_metrics") is True:
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


# Declared statuses mapped onto the public data_status vocabulary.  Endpoints
# that already publish `available|partial|unavailable` pass straight through;
# anything else is normalized here so no section can leak a coverage word such
# as `complete` or `unknown` into a documented field.
_DATA_STATUS_ALIASES: Dict[str, str] = {
    "available": "available",
    "complete": "available",
    "ok": "available",
    "success": "available",
    "partial": "partial",
    "degraded": "partial",
    "limited": "partial",
    "unavailable": "unavailable",
    "unknown": "unavailable",
    "error": "unavailable",
    "failed": "unavailable",
    "not_available": "unavailable",
}


def _normalize_data_status(value: Any) -> Optional[str]:
    """Map a declared status onto the public data_status vocabulary.

    Returns None when nothing recognizable was declared so the caller can fall
    back to its own material-data/error rules instead of guessing.
    """
    if not isinstance(value, str):
        return None
    return _DATA_STATUS_ALIASES.get(value.strip().lower())


def _normalize_public_data_status(value: Any) -> Any:
    """Rewrite every published data_status in a payload to the vocabulary.

    Undocumented values are dropped (they are not translatable into an honest
    status) instead of being published as-is.
    """
    if isinstance(value, Mapping):
        for key, item in list(value.items()):
            if key == "data_status":
                if isinstance(item, str):
                    normalized = _normalize_data_status(item)
                    if normalized is None:
                        value.pop(key, None)
                    elif normalized != item:
                        value[key] = normalized
                continue
            _normalize_public_data_status(item)
    elif isinstance(value, list):
        for item in value:
            _normalize_public_data_status(item)
    return value


def _as_of_text(value: Any) -> Optional[str]:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


# Freshness keys, best-first.  An actual observation date always outranks a
# cache/update timestamp, and `generated_at` is only used when the payload
# declared nothing better.
_AS_OF_KEYS = (
    "latest_observation_date",
    "as_of",
    "last_updated",
    "updated_at",
    "generated_at",
)
# A dated record inside a series (e.g. one performance-history row) publishes its
# own freshness; payload-level `date` is treated as a request echo instead.
_SERIES_AS_OF_KEYS = _AS_OF_KEYS + ("date",)


def _declared_as_of(value: Any, keys: Tuple[str, ...] = _AS_OF_KEYS) -> Optional[str]:
    """First declared timestamp of one payload, or the freshest series record."""
    if isinstance(value, Mapping):
        for key in keys:
            candidate = _as_of_text(value.get(key))
            if candidate:
                return candidate
        return None
    if isinstance(value, (list, tuple)):
        stamps = [
            text
            for text in (_declared_as_of(item, _SERIES_AS_OF_KEYS) for item in value)
            if text
        ]
        return max(stamps) if stamps else None
    return None


def _as_of(value: Any) -> Optional[str]:
    """Resolve one section's freshness with explicit, testable rules.

    1. a timestamp the payload declares itself (observation date first);
    2. the same lookup inside a nested `data` payload;
    3. for a composite, the OLDEST component timestamp - a composite section is
       only as fresh as its stalest leg, so an unrelated newer quote (for
       example a portfolio snapshot beside a year-old return series) can never
       become the section's `as_of`.

    Nothing is invented: a payload that declares no freshness stays None rather
    than falling back to the export's own `generated_at` or the requested
    window end.
    """
    if not isinstance(value, Mapping):
        return _declared_as_of(value)
    own = _declared_as_of(value)
    if own:
        return own
    nested = value.get("data")
    if isinstance(nested, Mapping):
        candidate = _declared_as_of(nested)
        if candidate:
            return candidate
    components = value.get("components")
    if isinstance(components, Mapping):
        stamps = []
        for component in components.values():
            component_data = (
                component.get("data") if isinstance(component, Mapping) else component
            )
            candidate = _declared_as_of(component_data)
            if candidate:
                stamps.append(candidate)
        if stamps:
            return min(stamps)
    return None


def _component_status(value: Any) -> str:
    return _payload_status(value)


_CURRENCY_KEYS = ("currency", "base_currency", "portfolio_value_currency", "value_currency")


def _declared_currency(source: Any) -> Optional[str]:
    if not isinstance(source, Mapping):
        return None
    for key in _CURRENCY_KEYS:
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return None


def _component_currencies(data: Any) -> List[str]:
    """Monetary units declared by a composite payload's components."""
    components = data.get("components") if isinstance(data, Mapping) else None
    if not isinstance(components, Mapping):
        return []
    found: List[str] = []
    for component in components.values():
        component_data = component.get("data") if isinstance(component, Mapping) else component
        if isinstance(component_data, Mapping):
            candidate = _declared_currency(component_data)
            if candidate:
                found.append(candidate)
        elif isinstance(component_data, (list, tuple)):
            for row in component_data:
                candidate = _declared_currency(row)
                if candidate:
                    found.append(candidate)
    return found


def _infer_currency(data: Any, inputs: Mapping[str, Any]) -> Optional[str]:
    """Resolve one section's monetary unit with explicit precedence.

    1. the unit the section payload declares (analytics sections keep their own
       endpoint-declared monetary unit);
    2. a nested `data` payload that declares one;
    3. a composite payload, only when every measured component agrees;
    4. the requested unit recorded in the section inputs (for example the
       portfolio snapshot's `base_currency` request).

    Conflicting components, or a payload that declares nothing, resolve to None
    and are reported as a warning by the caller: a mixed-unit section must not
    be labelled with one arbitrary component's currency or with the requested
    unit the components contradict.
    """
    own = _declared_currency(data)
    if own:
        return own
    nested = data.get("data") if isinstance(data, Mapping) else None
    nested_currency = _declared_currency(nested)
    if nested_currency:
        return nested_currency
    component_currencies = _component_currencies(data)
    if component_currencies:
        distinct = set(component_currencies)
        # A conflict is terminal: the requested input unit must not paper over a
        # composite that genuinely mixes monetary units.
        return distinct.pop() if len(distinct) == 1 else None
    return _declared_currency(inputs)


def _mixed_currency_units(data: Any) -> List[str]:
    """Distinct component currencies of a composite, sorted, when mixed."""
    units = sorted(set(_component_currencies(data)))
    return units if len(units) > 1 else []


def _collect_warnings(value: Any) -> List[str]:
    warnings: List[str] = []
    if isinstance(value, Mapping):
        for raw in (value.get("warnings"), value.get("alerts")):
            if not isinstance(raw, list):
                continue
            for item in raw:
                if item is None:
                    continue
                if isinstance(item, Mapping):
                    ticker = str(item.get("ticker")).strip() if item.get("ticker") else ""
                    message = str(item.get("message") or item.get("detail") or "").strip()
                    # A structured warning already carries a `ticker` field, and
                    # the message it ships with frequently opens with that same
                    # ticker ("NIFTYIETF.NS: 20 own return observations ...").
                    # Prefixing again renders "NIFTYIETF.NS: NIFTYIETF.NS: ...".
                    already_prefixed = bool(ticker) and message.startswith(f"{ticker}:")
                    if ticker and message and not already_prefixed:
                        text = f"{ticker}: {message}"
                    else:
                        text = message or (ticker or str(item))
                else:
                    text = str(item)
                if text:
                    warnings.append(text)
        if value.get("error") and not value.get("warnings") and not value.get("alerts"):
            warnings.append(str(value["error"]))
        components = value.get("components")
        if isinstance(components, Mapping):
            for component in components.values():
                if isinstance(component, Mapping):
                    warnings.extend(_collect_warnings(component.get("data")))
                    if component.get("error"):
                        warnings.append(str(component["error"]))
    return warnings


def _ticker_list(value: Any) -> List[str]:
    if value is None or isinstance(value, (str, bytes)):
        return []
    try:
        iterator = iter(value)
    except TypeError:
        return []
    output: List[str] = []
    seen = set()
    for item in iterator:
        if not isinstance(item, str):
            continue
        ticker = item.strip().upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            output.append(ticker)
    return output


def _available_tickers_for_section(key: str, data: Any) -> Optional[List[str]]:
    """Extract the universe that actually produced a section result."""
    if not isinstance(data, Mapping):
        return None

    def mapping_keys(field: str) -> Optional[List[str]]:
        value = data.get(field)
        if isinstance(value, Mapping):
            return _ticker_list(value.keys())
        return None

    if key in {"realized_risk", "forecast_risk", "factor_exposure"}:
        return mapping_keys("positions")
    if key == "liquidity":
        return mapping_keys("by_position")
    if key == "concentration":
        return mapping_keys("by_weight")
    if key == "volatility_sizing":
        return mapping_keys("volatility_sources") or mapping_keys("recommended_weights")
    if key == "optimization":
        return mapping_keys("weights")
    if key == "risk_contribution":
        positions = data.get("positions")
        if isinstance(positions, Mapping):
            available = set()
            for model in ("volatility", "cvar_tail"):
                available.update(_ticker_list((positions.get(model) or {}).keys()))
            return sorted(available)
    if key == "pairs":
        pair_rows = data.get("pairs")
        if isinstance(pair_rows, list):
            available = set()
            for row in pair_rows:
                if isinstance(row, Mapping):
                    available.update(_ticker_list([row.get("ticker_a"), row.get("ticker_b")]))
            return sorted(available)
        return None
    if key == "tear_sheet":
        return mapping_keys("holdings")
    if key == "stress_testing":
        available = set()
        scenarios = data.get("scenarios")
        if isinstance(scenarios, Mapping):
            for scenario in scenarios.values():
                if isinstance(scenario, Mapping):
                    available.update(_ticker_list((scenario.get("position_impacts") or {}).keys()))
        return sorted(available)
    if key == "risk_studio":
        components = data.get("components")
        if isinstance(components, Mapping):
            risk_contribution = components.get("risk_contribution")
            if isinstance(risk_contribution, Mapping):
                return _available_tickers_for_section("risk_contribution", risk_contribution.get("data"))
        return None
    if key == "portfolio":
        positions = data.get("positions")
        if isinstance(positions, list):
            return _ticker_list(
                position.get("ticker") for position in positions if isinstance(position, Mapping)
            )
    return None


def _section_coverage(key: str, inputs: Mapping[str, Any], data: Any) -> Optional[Dict[str, Any]]:
    """Resolve one section's universe coverage from the canonical result.

    The endpoint's own `universe_coverage` block stays authoritative, including
    a conditional `weight_basis`: the exporter never invents an allocation basis
    for a section it cannot prove was renormalized, and weightless analyses stay
    basis-free. Requested order drives every list so a repeated universe exports
    identically, and the coverage vocabulary (complete | partial | unavailable |
    unknown) is kept separate from the public `data_status` vocabulary.
    """
    requested = _ticker_list(inputs.get("tickers"))
    explicit: Optional[Dict[str, Any]] = None
    if isinstance(data, Mapping) and isinstance(data.get("universe_coverage"), Mapping):
        candidate = _jsonable(data["universe_coverage"])
        if isinstance(candidate, dict):
            explicit = candidate

    if explicit is not None:
        declared_requested = _ticker_list(explicit.get("requested_tickers"))
        requested = list(dict.fromkeys(requested + declared_requested))
        raw_available = _ticker_list(explicit.get("available_tickers"))
        declared_missing = _ticker_list(explicit.get("missing_tickers"))
        if key == "risk_contribution":
            excluded = data.get("excluded_assets")
            if isinstance(excluded, Mapping):
                for values in excluded.values():
                    declared_missing.extend(_ticker_list(values))
        declared_missing_set = set(declared_missing)
        effective_available = _order_universe(
            requested, set(raw_available) - declared_missing_set
        )
        effective_available_set = set(effective_available)
        covered = [ticker for ticker in requested if ticker in effective_available_set]
        # Requested order first, then any endpoint-declared extra, so the same
        # universe always renders the same list.
        missing = [ticker for ticker in requested if ticker not in effective_available_set]
        missing += sorted(declared_missing_set - effective_available_set - set(requested))
        if set(raw_available) - effective_available_set:
            explicit["raw_available_tickers"] = raw_available
        if not requested:
            coverage_status = "unknown"
        elif not covered:
            coverage_status = "unavailable"
        elif missing:
            coverage_status = "partial"
        else:
            coverage_status = "complete"
        explicit.update({
            "requested_tickers": requested,
            "available_tickers": effective_available,
            "covered_tickers": covered,
            "missing_tickers": missing,
            "requested_count": len(requested),
            "available_count": len(covered),
            "coverage_ratio": round(len(covered) / len(requested), 6) if requested else None,
            "complete": not missing if requested else None,
            "status": coverage_status,
        })
        if explicit.get("weight_basis") is not None:
            explicit["weight_basis"] = str(explicit["weight_basis"])
        return explicit

    available = _available_tickers_for_section(key, data)
    if not requested:
        return None
    if available is None:
        # Coverage is unmeasured: counts are omitted rather than published as
        # null sentinels, matching the documented optional coverage fields.
        return {
            "requested_tickers": requested,
            "available_tickers": None,
            "missing_tickers": None,
            "coverage_ratio": None,
            "complete": None,
            "status": "unknown",
        }
    available_set = set(available)
    ordered_available = _order_universe(requested, available_set)
    covered = [ticker for ticker in requested if ticker in available_set]
    missing = [ticker for ticker in requested if ticker not in available_set]
    if not requested:
        status = "unknown"
    elif not covered:
        status = "unavailable"
    elif missing:
        status = "partial"
    else:
        status = "complete"
    return {
        "requested_tickers": requested,
        "available_tickers": ordered_available,
        "covered_tickers": covered,
        "missing_tickers": missing,
        "requested_count": len(requested),
        "available_count": len(covered),
        "coverage_ratio": round(len(covered) / len(requested), 6) if requested else None,
        "complete": not missing,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Dashboard composition helpers
#
# The dashboard page is a composition of independent analytics endpoints, so it
# must disclose each leg's own delivered window instead of inheriting one
# unrelated timestamp (a portfolio quote) for the whole page.  These helpers
# are dashboard-local: the shared status/coverage/as-of contract helpers above
# stay the single policy and are reused rather than re-implemented.
# ---------------------------------------------------------------------------

# Window the dashboard performance chart requests.  A shorter delivery is only
# judgeable because the request is published beside the delivered rows.
PERFORMANCE_HISTORY_DAYS = 90

# Documented freshness rule for one performance component.
#   available   -> the endpoint published a measured expectation, the delivered
#                  observations cover at least PERFORMANCE_COVERAGE_FLOOR of it,
#                  and it flagged neither truncation nor staleness;
#   partial     -> coverage below that floor, or the endpoint declared the
#                  window truncated/stale;
#   unavailable -> no observation was delivered at all;
#   unknown     -> the endpoint published no expectation (the legacy bare-array
#                  response), so the window is neither provably complete nor
#                  provably cut, and the exporter claims neither.
PERFORMANCE_COVERAGE_FLOOR = 0.8

# Composite as-of policy label.  A composite is only as fresh as its stalest
# leg, which is exactly what the shared `_as_of` composite rule implements, so
# the export publishes the policy name instead of a second date policy.
COMPOSITE_AS_OF_SEMANTICS = "oldest_component_observation"

# Severity order used when a component's payload status and its measured
# freshness disagree: the worse of the two is published, never the kinder.
_STATUS_SEVERITY: Dict[str, int] = {
    "available": 0,
    "unknown": 0,
    "partial": 1,
    "unavailable": 2,
}

# Reason vocabulary for the dashboard summary's field-level linkage.
_SUMMARY_REASON_LINKED = "linked_from_canonical_sibling"
_SUMMARY_REASON_ALREADY_PUBLISHED = "source_value_already_published"
_SUMMARY_REASON_SECTION_PARTIAL = "source_section_partial"
_SUMMARY_REASON_SECTION_UNAVAILABLE = "source_section_unavailable"
_SUMMARY_REASON_VALUE_MISSING = "source_value_not_published"
_SUMMARY_REASON_VALUE_NOT_FINITE = "source_value_not_finite"

# The risk-score route hardcodes `change: 0` because no previous score is
# persisted, so there is no genuine delta behind the number.  The route is not
# owned by this ticket, so the export refuses to publish the zero as a measured
# change: it becomes null with a machine-readable reason.
#
# Recommended backend one-liner (NOT applied here - app/api/analytics.py is
# owned by the performance-history change): persist the previous score and
# publish a real delta, e.g.
#   "change": None if previous_score is None else previous_score - overall_score,
#   "prior_score": previous_score,
RISK_SCORE_UNMEASURED_REASON = "no_persisted_prior_score"
# Any of these alongside `change` proves the zero is a measured delta.
_RISK_SCORE_CHANGE_EVIDENCE = ("change_status", "prior_score", "change_basis")


def _finite_number(value: Any) -> Optional[float]:
    """Finite float or None; bools and numeric strings are not measurements."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _optional_int(value: Any) -> Optional[int]:
    number = _finite_number(value)
    if number is None:
        return None
    return int(number)


def _date_text(value: Any) -> Optional[str]:
    """ISO date portion of a declared timestamp, or None."""
    text = _as_of_text(value)
    return text[:10] if text else None


def _parse_iso_timestamp(value: Any) -> Optional[datetime]:
    """Parse a declared ISO timestamp, tolerating a trailing `Z`.

    Returns `None` rather than guessing when the text is not a real timestamp;
    a date-only value is midnight, which is honest for a date comparison.
    """
    text = _as_of_text(value)
    if not text:
        return None
    candidate = text.strip()
    if candidate.endswith(("Z", "z")):
        candidate = candidate[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        pass
    try:
        return datetime.strptime(candidate[:10], "%Y-%m-%d")
    except ValueError:
        return None


# Which declared field produced an as-of, so freshness is self-describing.  The
# keys mirror `_AS_OF_KEYS`; a series resolves through its newest record date.
_AS_OF_SEMANTICS: Dict[str, str] = {
    "latest_observation_date": "latest_observation_date",
    "as_of": "declared_as_of",
    "last_updated": "last_updated",
    "updated_at": "updated_at",
    "generated_at": "generated_at",
    "date": "series_record_date",
}


def _declared_as_of_semantics(value: Any, resolved: Optional[str]) -> Optional[str]:
    if not resolved:
        return None
    if isinstance(value, Mapping):
        for key in _AS_OF_KEYS:
            if _as_of_text(value.get(key)) == resolved:
                return _AS_OF_SEMANTICS[key]
        return _AS_OF_SEMANTICS["as_of"]
    if isinstance(value, (list, tuple)):
        return _AS_OF_SEMANTICS["date"]
    return _AS_OF_SEMANTICS["as_of"]


def _payload_as_of_semantics(data: Any, resolved: Optional[str]) -> Optional[str]:
    """What the resolved `as_of` measures, for the section as a whole.

    A payload may declare its own meaning (`liquidity_component_only`,
    `latest_available_observation`, ...). Honour it first: the exporter must not
    overwrite a precise label with a generic one. Otherwise derive the label from
    the key the date came from, so a bare date never ships unlabelled.
    """
    if not resolved:
        return None
    for source in _semantics_sources(data):
        declared = source.get("as_of_semantics")
        if isinstance(declared, str) and declared.strip():
            return declared.strip()
    return _declared_as_of_semantics(data, resolved)


def _semantics_sources(data: Any) -> List[Mapping[str, Any]]:
    """Containers that may carry a declared `as_of_semantics`, nearest first."""
    sources: List[Mapping[str, Any]] = []
    if isinstance(data, Mapping):
        sources.append(data)
        nested = data.get("data")
        if isinstance(nested, Mapping):
            sources.append(nested)
    return sources


# A date inside this envelope's own collection window is a value the run just
# wrote, not a prior measurement.
_RUN_TIMESTAMP_SLACK_SECONDS = 300


def _run_timestamp_as_of(data: Any, resolved: Optional[str]) -> Optional[str]:
    """Warn when `as_of` was produced during this export, not observed before it.

    A portfolio quote is re-stamped every time the export refreshes it, so its
    timestamp necessarily lands inside the collection window. That is honest data
    with an honest meaning — it is just NOT a historical observation date, and a
    consumer reading `as_of` alone would assume it was. Disclosing the
    distinction is cheaper than pretending the distinction does not exist.
    """
    if not resolved:
        return None
    stamp = _parse_iso_timestamp(resolved)
    if stamp is None:
        return None
    started = _parse_iso_timestamp(_EXPORT_STARTED_AT[0])
    if started is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    age = (started - stamp).total_seconds()
    if not (-_RUN_TIMESTAMP_SLACK_SECONDS <= age <= _RUN_TIMESTAMP_SLACK_SECONDS):
        return None
    return (
        f"as_of {resolved} is a quote/update timestamp written during this export "
        "(it falls inside the collection window), so it marks when the value was "
        "refreshed, not a historical observation date"
    )


#: The same bound the audit's ENV-012 staleness arm applies.  Mirrored rather
#: than imported: `app.debugging` is a diagnostic tool and production code must
#: not depend on it. `tests/test_ai_context_freshness_disclosure.py` asserts the
#: two constants agree, so the mirror cannot drift.
AS_OF_STALENESS_DAYS = 7.0

#: Tokens that make an existing warning a staleness disclosure. Same vocabulary
#: the audit rule accepts, so a section that already says so is not told twice.
_STALE_DISCLOSURE_TOKENS = ("stale", "outdated", "not current")


def _stale_as_of_warning(resolved: Optional[str]) -> Optional[str]:
    """Name the measured age of an `as_of` older than the freshness bound.

    A reader who does not know the age cannot weigh the section, and an
    observation more than `AS_OF_STALENESS_DAYS` behind this export's own start
    cannot be the newest one behind it. Measured from the export clock, never
    assumed: a payload with no `as_of`, or one whose age is inside the bound,
    produces nothing.
    """
    if not resolved:
        return None
    stamp = _parse_iso_timestamp(resolved)
    started = _parse_iso_timestamp(_EXPORT_STARTED_AT[0])
    if stamp is None or started is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    age_days = (started - stamp).total_seconds() / 86400.0
    if age_days <= AS_OF_STALENESS_DAYS:
        return None
    return (
        f"as_of {resolved} is {age_days:.2f} calendar days older than this "
        f"export's own start, past the {AS_OF_STALENESS_DAYS:g}-day freshness "
        "bound: it is the newest observation this payload declared, but it is "
        "stale, and the section's numbers should be aged accordingly"
    )


# --- ENV-016: a section that publishes a degradation has to name it ----------
# The rule fires whenever a section is degraded OR its payload carries a
# degradation marker, whatever its own `status` says. Every warning below is
# derived from a fact the payload or the section already computed - a gate, an
# error, an omission, a component that produced nothing, a measured window
# shortfall - so adding one can never invent a degradation, and the exit costs a
# sentence rather than a changed number.
_DEGRADED_PAYLOAD_STATUSES = frozenset({"partial", "unavailable"})

#: Blocks whose keys carry a real short-history disclosure, in the order the
#: sentence prefers them.
_WINDOW_BLOCK_KEYS = ("measured_window", "history_coverage", "holding_context")


def _execution_gate_degradation(data: Any) -> Optional[str]:
    """Name the execution gate a sizing payload already published.

    `execution.block_reasons` / `block_reason` are a degradation marker: the
    target was refused by the shared normalization rule. The sentence is built
    from that refusal plus the financing figure the same block measured, so it
    states the size of the problem rather than gesturing at it.
    """
    execution = data.get("execution") if isinstance(data, Mapping) else None
    if not isinstance(execution, Mapping):
        return None
    if execution.get("execution_eligible") is not False:
        return None
    reasons = [
        str(reason).strip()
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
    amount = ""
    try:
        magnitude = float(financing) if financing is not None else None
    except (TypeError, ValueError):
        magnitude = None
    if magnitude is not None and math.isfinite(magnitude) and magnitude > 0:
        unit = f" {currency}" if isinstance(currency, str) and currency.strip() else ""
        amount = f" ({magnitude:,.2f}{unit} of financing is required)"
    return (
        f"The recommended target is not executable as a normal rebalance: {detail}"
        f"{amount}. Every trades[*] record inherits this gate, so the published "
        "list is a financing-dependent target rather than an order set."
    )


def _component_degradations(data: Any) -> List[str]:
    """Composite components that produced no measurement, named individually.

    A composite that reports `partial` because one leg is `unavailable` and says
    nothing about which leg is the most misleading warning it can write: the
    reader cannot tell which number is missing.
    """
    components = data.get("components") if isinstance(data, Mapping) else None
    if not isinstance(components, Mapping):
        return []
    degraded: List[str] = []
    for name, component in components.items():
        if not isinstance(component, Mapping):
            continue
        status = component.get("status")
        component_error = component.get("error")
        if status not in _DEGRADED_PAYLOAD_STATUSES and not component_error:
            continue
        detail = str(component_error).strip() if component_error else (
            f"status {status!r}"
        )
        degraded.append(f"{name} ({detail})")
    return sorted(degraded)


def _window_degradation(data: Any) -> Optional[str]:
    """Name the measured shortfall behind a section's own degraded `data_status`.

    Prefers the window block the payload publishes (its truncation flag, the
    delivered day count, and the request it fell short of). With no window block
    to read, it falls back to the endpoint's own `data_status` value, which is
    still a fact the payload declares rather than one invented here.
    """
    if not isinstance(data, Mapping):
        return None
    for key in _WINDOW_BLOCK_KEYS:
        block = data.get(key)
        if not isinstance(block, Mapping):
            continue
        delivered = block.get("covered_days")
        if delivered is None:
            delivered = block.get("days")
        if delivered is None:
            delivered = block.get("observation_count")
        requested = data.get("requested_window")
        requested = requested if isinstance(requested, Mapping) else None
        if requested is not None and delivered is not None:
            span = _calendar_span_days(requested.get("start"), requested.get("end"))
            if span is not None and int(delivered) < span:
                flags = [
                    name
                    for name, value in block.items()
                    if isinstance(value, bool) and value and "truncat" in name
                ]
                return (
                    f"Only {int(delivered)} of the {span} requested days were "
                    "measured"
                    + (f" ({', '.join(flags)})" if flags else "")
                    + ": the delivered window is shorter than the request, so the "
                    "figures here describe the measured window only"
                )
        if block.get("truncated") is True and delivered is not None:
            return (
                f"The delivered history is truncated: {int(delivered)} day(s) "
                "measured, flagged truncated by the endpoint, so this section's "
                "statistics describe that window and not the requested one"
            )
    status = _normalize_data_status(data.get("data_status"))
    if status in _DEGRADED_PAYLOAD_STATUSES:
        return (
            f"The endpoint published data_status {status!r} for this payload, so "
            "its numbers come from a degraded result and not from a complete one"
        )
    return None


def _calendar_span_days(start: Any, end: Any) -> Optional[int]:
    """Inclusive calendar span of two ISO dates, or None when unreadable."""
    first = _date_text(start)
    last = _date_text(end)
    if not first or not last:
        return None
    try:
        return (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
    except ValueError:
        return None


def _degradation_warnings(
    data: Any,
    *,
    status: str,
    error: Optional[str],
    omitted: Sequence[str],
) -> List[str]:
    """Sentences naming the degradation this section already computes.

    Only ever called to fill an EMPTY warning list: a section that has already
    said something has discharged the obligation, and appending a second generic
    sentence to a disclosed section would be noise. Returns nothing when the
    payload carries no degradation to name, so it can never manufacture one.
    """
    warnings: List[str] = []
    if error:
        warnings.append(
            f"This section failed and publishes no measurement of it: {error}. "
            "Nothing in this payload is a measurement of the requested quantity."
        )
    gate = _execution_gate_degradation(data)
    if gate:
        warnings.append(gate)
    components = _component_degradations(data)
    if components:
        warnings.append(
            "Composite component(s) that produced no measurement: "
            + ", ".join(components)
        )
    if omitted:
        warnings.append(
            f"Summary compaction dropped {len(omitted)} field(s) from this "
            f"section ({', '.join(omitted)}); the payload is the compacted view, "
            "so request detail=full for the untrimmed one"
        )
    window = _window_degradation(data)
    if window:
        warnings.append(window)
    if not warnings and status in _DEGRADED_PAYLOAD_STATUSES:
        # Last resort, and still a fact rather than an invention: the section
        # resolved to a degraded status and the payload names no specific
        # shortfall to quote. Saying so beats shipping the status alone.
        warnings.append(
            f"This section is {status!r} and publishes no explanation of the "
            "shortfall; treat its numbers as a degraded result"
        )
    return list(dict.fromkeys(warnings))


def _component_as_of_entry(
    component: Any, declared_semantics: Optional[str] = None
) -> Dict[str, Optional[str]]:
    """One component's freshness, resolved by the shared `_as_of` policy.

    The composite's own as-of is the oldest leg, so the per-component map must
    use the same resolver; only the semantics label is added here.
    """
    data = component.get("data") if isinstance(component, Mapping) else component
    resolved = _as_of(data)
    return {
        "as_of": resolved,
        "as_of_semantics": declared_semantics or _declared_as_of_semantics(data, resolved),
    }


def _split_performance_response(value: Any) -> Tuple[List[Any], Optional[Dict[str, Any]]]:
    """Accept both the metadata envelope and the legacy bare array.

    The route keeps its bare-array default; the exporter opts into the envelope
    with `include_metadata=true`.  A bare array is still a valid delivery, it
    simply carries no measured window, so its freshness stays unknown instead
    of being called complete.
    """
    if isinstance(value, Mapping):
        rows = value.get("data")
        return (list(rows) if isinstance(rows, list) else []), dict(value)
    if isinstance(value, (list, tuple)):
        return list(value), None
    return [], None


def _window_text(start: Optional[str], end: Optional[str]) -> str:
    if start and end:
        return f"{start} to {end}"
    return end or start or "unknown"


def _performance_history_component(
    component: Dict[str, Any],
    requested_days: int = PERFORMANCE_HISTORY_DAYS,
) -> Dict[str, Any]:
    """Publish the delivered performance window beside the delivered rows.

    The component keeps the endpoint's rows as its series and gains the
    endpoint's own `history_coverage`, the as-of that actually measured those
    rows, and a deterministic warning naming requested versus delivered.  A
    materially short or stale delivery surfaces as `partial` instead of passing
    as a complete chart, and a delivery with no measured expectation stays
    `unknown` rather than being guessed either way.
    """
    rows, envelope = _split_performance_response(component.get("data"))
    coverage = envelope.get("history_coverage") if envelope else None
    coverage = coverage if isinstance(coverage, Mapping) else {}

    row_dates = [
        text
        for text in (_date_text(row.get("date")) for row in rows if isinstance(row, Mapping))
        if text
    ]
    declared_count = _optional_int(coverage.get("observation_count"))
    observation_count = declared_count if declared_count is not None else len(rows)
    expected = _optional_int(coverage.get("expected_observation_count"))
    ratio = _finite_number(coverage.get("coverage_ratio"))
    if ratio is None and expected:
        ratio = round(observation_count / expected, 6)
    delivered_start = _date_text(coverage.get("delivered_start")) or (min(row_dates) if row_dates else None)
    delivered_end = _date_text(coverage.get("delivered_end")) or (max(row_dates) if row_dates else None)
    truncated = coverage.get("truncated") if isinstance(coverage.get("truncated"), bool) else None
    stale = coverage.get("stale") if isinstance(coverage.get("stale"), bool) else None
    declared_status = _normalize_data_status(envelope.get("data_status") if envelope else None)

    if observation_count == 0:
        freshness = "unavailable"
    elif declared_status in {"partial", "unavailable"}:
        freshness = declared_status
    elif expected is None:
        # No measured expectation: the window is unmeasured, not complete.
        freshness = "unknown"
    elif ratio is not None and ratio < PERFORMANCE_COVERAGE_FLOOR:
        freshness = "partial"
    elif truncated is True or stale is True:
        freshness = "partial"
    else:
        freshness = "available"

    warnings: List[str] = []
    for item in (envelope.get("warnings") if envelope else None) or []:
        text = str(item).strip() if item is not None else ""
        if text:
            warnings.append(text)

    requested = _optional_int(coverage.get("requested_days")) or requested_days
    if freshness == "partial":
        warnings.append(
            "Performance history delivered "
            f"{observation_count} of {expected} observations for the requested "
            f"{requested}-day window ({_window_text(delivered_start, delivered_end)})"
            + (", flagged stale by the endpoint" if stale is True else "")
        )
    elif freshness == "unknown":
        warnings.append(
            f"Performance history delivered {observation_count} observation(s) for the requested "
            f"{requested}-day window; the endpoint published no expected observation count, "
            "so the delivered window is unmeasured"
        )
    elif freshness == "unavailable":
        warnings.append(
            "Performance history delivered no observations for the requested "
            f"{requested}-day window"
        )

    # The worse of the payload status and the measured freshness is published,
    # never the kinder one.  An unrecognizable status is not a measurement of
    # availability, so it resolves to `unavailable` instead of leaking through.
    payload_status = _normalize_data_status(component.get("status")) or "unavailable"
    status = max(
        (payload_status, freshness),
        key=lambda value: _STATUS_SEVERITY.get(value, 2),
    )

    as_of = _date_text(envelope.get("as_of")) if envelope else None
    as_of = as_of or delivered_end
    declared_semantics = envelope.get("as_of_semantics") if envelope else None
    if not isinstance(declared_semantics, str) or not declared_semantics.strip():
        declared_semantics = "last_delivered_observation" if as_of else None

    # Breadth travels WITH the series, not only inside history_coverage. A
    # portfolio return is only emitted on dates where every priced position has a
    # price, so a partial basket is refused rather than renormalised -- but a
    # reader of `data` alone cannot tell a full-basket day from a partial one
    # unless the constituent count sits beside the rows it qualifies. Projecting
    # it only into history_coverage put it one level too deep to be found.
    breadth = {
        "constituent_count": coverage.get("constituent_count"),
        "constituent_count_basis": coverage.get("constituent_count_basis"),
        "partial_basket_policy": coverage.get("partial_basket_policy"),
        "refused_partial_coverage_rows": coverage.get("refused_partial_coverage_price_rows"),
    }

    result: Dict[str, Any] = {
        "status": status,
        "data": rows,
        "as_of": as_of,
        "as_of_semantics": declared_semantics,
        **breadth,
        "history_coverage": {
            "requested_start": _date_text(coverage.get("requested_start")),
            "requested_end": _date_text(coverage.get("requested_end")),
            "requested_days": requested,
            "delivered_start": delivered_start,
            "delivered_end": delivered_end,
            "observation_count": observation_count,
            "expected_observation_count": expected,
            "first_observation": _date_text(coverage.get("first_observation")) or delivered_start,
            "last_observation": _date_text(coverage.get("last_observation")) or delivered_end,
            "coverage_ratio": ratio,
            "truncated": truncated,
            "stale": stale,
            **breadth,
            "status": "unknown" if freshness == "unknown" else freshness,
            "rule": (
                f"partial when coverage_ratio < {PERFORMANCE_COVERAGE_FLOOR} or the endpoint "
                "flags the window truncated/stale; unknown when the endpoint publishes no "
                "expected observation count"
            ),
        },
    }
    if component.get("error"):
        result["error"] = str(component["error"])
    if warnings:
        result["warnings"] = list(dict.fromkeys(warnings))
    return result


def _summary_source_value(component_name: str, data: Any) -> Tuple[Optional[float], str]:
    """Canonical sibling value for one summary field, plus how it was read."""
    if not isinstance(data, Mapping):
        return None, _SUMMARY_REASON_VALUE_MISSING
    if component_name == "forecast_risk":
        portfolio = data.get("portfolio")
        holders = (portfolio, data) if isinstance(portfolio, Mapping) else (data,)
        keys = ("volatility_forecast", "forecast_volatility")
    elif component_name == "liquidity":
        holders = (data,)
        keys = ("overall_score",)
    else:
        return None, _SUMMARY_REASON_VALUE_MISSING
    for holder in holders:
        for key in keys:
            if key in holder:
                raw = holder.get(key)
                if raw is None:
                    # Present but empty: the source published no measurement.
                    return None, _SUMMARY_REASON_VALUE_MISSING
                value = _finite_number(raw)
                if value is not None:
                    return value, _SUMMARY_REASON_LINKED
                return None, _SUMMARY_REASON_VALUE_NOT_FINITE
    return None, _SUMMARY_REASON_VALUE_MISSING


# (summary field, canonical source section) pairs.  The dashboard summary
# endpoint deliberately publishes these as null because it does not itself
# compute a forecast or a liquidity score; the export links the already
# canonical sibling result instead of leaving a null beside an available value.
_SUMMARY_CANONICAL_SOURCES: Tuple[Tuple[str, str], ...] = (
    ("forecast_volatility", "forecast_risk"),
    ("liquidity_score", "liquidity"),
)


def _link_dashboard_summary(components: Dict[str, Any]) -> List[str]:
    """Fill dashboard summary fields from canonical sibling results.

    The link is published only when the value is finite AND the sibling section
    is usable; otherwise the field stays null and a machine-readable
    `field_status` entry records the value, source section, source status and
    reason.  Every write goes to a deep copy, so a cached section is never
    mutated and repeated assembly stays deterministic.
    """
    summary = components.get("summary")
    if not isinstance(summary, Mapping):
        return []
    source = summary.get("data")
    if not isinstance(source, Mapping):
        return []

    data = copy.deepcopy(source)
    field_status: Dict[str, Any] = {}
    warnings: List[str] = []
    for field_name, component_name in _SUMMARY_CANONICAL_SOURCES:
        sibling = components.get(component_name)
        sibling_status = (
            str(sibling.get("status") or "unavailable") if isinstance(sibling, Mapping) else "unavailable"
        )
        sibling_data = sibling.get("data") if isinstance(sibling, Mapping) else None
        value, reason = _summary_source_value(component_name, sibling_data)
        published = _finite_number(data.get(field_name))
        if published is not None:
            # The endpoint already published a measurement: keep it.
            value, reason = published, _SUMMARY_REASON_ALREADY_PUBLISHED
        elif sibling_status != "available":
            # A partial/unavailable sibling never becomes a summary headline.
            value, reason = None, (
                _SUMMARY_REASON_SECTION_PARTIAL
                if sibling_status == "partial"
                else _SUMMARY_REASON_SECTION_UNAVAILABLE
            )
        if reason == _SUMMARY_REASON_LINKED and value is not None:
            data[field_name] = value
        elif reason == _SUMMARY_REASON_ALREADY_PUBLISHED:
            pass
        else:
            value = None
            data[field_name] = None
            warnings.append(
                f"Dashboard summary {field_name} is unavailable: canonical {component_name} "
                f"section is {sibling_status} ({reason})"
            )
        field_status[field_name] = {
            "value": value,
            "source_section": component_name,
            "source_status": sibling_status,
            "reason": reason,
        }

    summary["data"] = data
    summary["field_status"] = field_status
    return warnings


def _normalize_risk_score_change(component: Dict[str, Any]) -> List[str]:
    """Stop publishing the risk score's hardcoded `change: 0` as a delta.

    The route cannot compute a change because no prior score is persisted, so
    an exact zero with no accompanying evidence is unmeasured, not unchanged.
    The value becomes null with a reason instead of an invented delta; the
    score itself is never compared against the summary's score, which would
    fabricate a delta from two different measurements.
    """
    data = component.get("data")
    if not isinstance(data, Mapping) or "change" not in data:
        return []
    change = _finite_number(data.get("change"))
    if change is None or change != 0.0:
        return []
    if any(key in data for key in _RISK_SCORE_CHANGE_EVIDENCE):
        return []

    payload = copy.deepcopy(data)
    payload["change"] = None
    payload["change_status"] = "unavailable"
    payload["change_reason"] = RISK_SCORE_UNMEASURED_REASON
    component["data"] = payload
    return [
        "Risk-score change is unmeasured ("
        f"{RISK_SCORE_UNMEASURED_REASON}): the risk-score route publishes a hardcoded 0 "
        "with no persisted prior score"
    ]


def _snapshot_consistency_measured(
    sections: Mapping[str, Any], portfolio_payload: Any
) -> Dict[str, Any]:
    """AD-16, the envelope half: the EVIDENCE beside the collection-mode claim.

    `snapshot_consistency` at the envelope is a collection-mode word -
    `best_effort` or `frozen` - and it stays exactly that. It says how the
    export was collected. It does not say whether the collected prices
    actually agreed, and a reviewer counted 31 mismatching (ticker, price)
    pairs up to 3.5% apart for the same 14 holdings while the envelope still
    read `best_effort`.

    Those are two different axes and they get two keys. Overwriting the
    Literal with a dict would have broken the schema, the TypeScript union and
    the Markdown renderer to make a sentence shorter, and would have thrown
    away a real distinction: a `frozen` export whose prices still disagree is
    not the same finding as a `best_effort` one that happens to agree. So the
    claim keeps its key and the measurement arrives beside it.

    Compact by design - the full block, including per-ticker attribution and
    what it invalidates, stays where it was measured, in the portfolio
    section's own `data`.
    """
    block: Any = None
    for source in (sections.get("portfolio"), portfolio_payload):
        if isinstance(source, Mapping):
            data = source.get("data")
            candidate = data.get("snapshot_consistency") if isinstance(data, Mapping) else None
            # A Mapping alone is not a measurement. An empty dict, or one that
            # publishes no `status`, would otherwise be promoted into a
            # measurement whose status is null -- the same move the whole rule
            # exists to prevent, one level up.
            if isinstance(candidate, Mapping) and candidate.get("status"):
                block = candidate
                break
    if not isinstance(block, Mapping):
        # The count keys are published as null rather than omitted so a consumer
        # iterating the shape cannot hit a KeyError. `null` is the honest value
        # for "not measured", and `status` plus `reason` say so explicitly.
        return {
            "status": "unmeasured",
            "distinct_price_instants": None,
            "distinct_delivered_bar_dates": None,
            "mark_instant_spread_seconds": None,
            "delivered_bar_spread_calendar_days": None,
            "reason": (
                "The portfolio section published no measured price-clock block, so "
                "this export asserts no agreement between its price instants."
            ),
            "detail_at": "sections.portfolio.data.snapshot_consistency",
        }
    return {
        "status": block.get("status"),
        "distinct_price_instants": block.get("distinct_price_instants"),
        "distinct_delivered_bar_dates": block.get("distinct_delivered_bar_dates"),
        "mark_instant_spread_seconds": block.get("mark_instant_spread_seconds"),
        "delivered_bar_spread_calendar_days": block.get(
            "delivered_bar_spread_calendar_days"
        ),
        "per_position_price_as_of_at": (
            "sections.portfolio.data.snapshot_consistency.per_position_price_as_of"
        ),
        "what_this_invalidates_at": (
            "sections.portfolio.data.snapshot_consistency.what_this_invalidates"
        ),
        "detail_at": "sections.portfolio.data.snapshot_consistency",
    }


#: Section-envelope keys a referenced dashboard component keeps inline.  These
#: are the cheap, per-section facts a consumer needs to decide whether it wants
#: the payload at all, and they are the keys on which the component and its twin
#: are required to agree.
COMPONENT_REFERENCE_METADATA = (
    "as_of",
    "as_of_semantics",
    "currency",
    "detail",
    "error",
    "inputs",
    "omitted_fields",
    "status",
    "warnings",
)

COMPONENT_REFERENCE_POLICY = (
    "A dashboard component with `data_inline: false` does not republish its "
    "payload. Its `data` is the `data` of the section named by `data_ref`, "
    "which is a dot-separated path into THIS document (read `<data_ref>.data`); "
    "`data_ref_status: \"referenced\"` says the component is a pointer, not a "
    "measurement. The component's own `status`, `as_of`, `as_of_semantics`, "
    "`currency`, `detail`, `error`, `inputs`, `omitted_fields` and `warnings` "
    "are copies of the referenced section's, so the two paths cannot disagree "
    "about the same section. `data_inline: true` means the component is the only "
    "publication of that payload in this document and its `data` is the data."
)


def _reference_dashboard_components(sections: Dict[str, Any]) -> None:
    """Replace duplicated dashboard component payloads with pointers.

    The default export already publishes eight of the dashboard's eleven
    components as their own top-level sections, so inlining their payloads a
    second time republished ~28% of the document byte-for-byte.  The component
    map is a documented shape and a dashboard-shaped consumer depends on it, so
    the map stays; only the duplicated bytes go.

    Two things this must not do.  It must not point at anything: a component
    whose twin is absent from the document (the risk score, the summary and
    performance history have no standalone section) keeps its payload inline,
    because a pointer to a section this export never published would be worse
    than a duplicate.  And it must not let the two paths drift: the two copies
    already had, and the drift cost a disclosure - `sections.portfolio.data`
    carries `aggregates_not_produced` naming the book-level aggregates the
    endpoint never produced, and the dashboard's copy of the same section did
    not, so a consumer reading the portfolio through the dashboard saw a
    section that looked complete with an empty omissions ledger.

    The metadata is therefore copied FROM the referenced section rather than
    left to the component, which makes the agreement structural: there is one
    source for those keys, so no edit can make the two paths disagree.  This
    runs after every section is built, so the dashboard's own status, currency,
    freshness, coverage and warnings were all derived from the full payload and
    none of them moves.
    """
    dashboard = sections.get("dashboard")
    data = dashboard.get("data") if isinstance(dashboard, Mapping) else None
    components = data.get("components") if isinstance(data, Mapping) else None
    if not isinstance(components, Mapping):
        return
    for name, component in list(components.items()):
        if not isinstance(component, dict):
            continue
        twin = sections.get(name)
        if not isinstance(twin, Mapping) or "data" not in twin:
            component["data_inline"] = True
            continue
        reference = f"sections.{name}"
        # `data_ref_status`, never `data_status`: `data_status` is a declared
        # contract key with its own normalized vocabulary (`available`,
        # `partial`, `unavailable`) and a rule that audits every publication of
        # it. Borrowing the name for "this is a pointer" put a word outside that
        # vocabulary into the document.
        projected = {
            "data_inline": False,
            "data_ref": reference,
            "data_ref_status": "referenced",
        }
        for key in COMPONENT_REFERENCE_METADATA:
            if key in twin:
                projected[key] = twin[key]
        if "status" not in projected:
            # A twin that somehow publishes no status must not cost the
            # component the status it already had.
            projected["status"] = component.get("status", "unavailable")
        components[name] = projected
    if isinstance(data, dict):
        data["component_reference_policy"] = COMPONENT_REFERENCE_POLICY


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
        _EXPORT_STARTED_AT[0] = generated_at
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
        # Normalize the roster once so the requested universe, the section
        # inputs and every coverage list share one order and one spelling.
        tickers = _ticker_list(
            position.get("ticker")
            for position in positions
            if isinstance(position, Mapping) and position.get("ticker")
        )
        active_tickers: List[str] = []
        for position in positions:
            if not isinstance(position, Mapping) or not position.get("ticker"):
                continue
            raw_value = position.get("market_value_base")
            if raw_value is None:
                raw_value = position.get("market_value")
            try:
                if math.isfinite(float(raw_value or 0.0)) and float(raw_value or 0.0) > 0:
                    active_tickers.append(str(position["ticker"]).strip().upper())
            except (TypeError, ValueError):
                continue
        if tickers and not active_tickers and not any(
            isinstance(position, Mapping)
            and ("market_value_base" in position or "market_value" in position)
            for position in positions
        ):
            # Lightweight test/adapter payloads may omit value fields; retain
            # their explicit ticker roster rather than treating it as empty.
            active_tickers = list(tickers)
        ticker_csv = ",".join(tickers) if tickers else None
        total_value = float(portfolio_json.get("total_value", 0.0) or 0.0) if isinstance(portfolio_json, Mapping) else 0.0
        context = _BuildContext(
            options=options,
            base_currency=options.base_currency,
            portfolio=portfolio_json,
            tickers=tickers,
            ticker_csv=ticker_csv,
            total_value=total_value,
            active_tickers=active_tickers,
        )

        sections: Dict[str, Dict[str, Any]] = {}
        if "portfolio" in selected:
            sections["portfolio"] = self._make_section(
                key="portfolio",
                data=portfolio_json,
                inputs={
                    "currency": options.base_currency,
                    "force_refresh": False,
                    "tickers": tickers,
                },
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
        elif not active_tickers:
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
                        inputs={"tickers": tickers},
                        error=(
                            "No positive portfolio value available for analytics"
                            if tickers else "No portfolio positions found"
                        ),
                        detail=options.detail,
                    )
        else:
            # Collect non-dashboard sections first so the dashboard can reuse
            # the exact canonical results instead of issuing duplicate live
            # calculations for the same page components.
            for key in selected:
                if key in {"portfolio", "dashboard"}:
                    continue
                section = await self._collect_section(key, context)
                sections[key] = section
                context.cached_sections[key] = section
                if "data" in section:
                    context.cached[key] = section.get("data")

            if "dashboard" in selected:
                dashboard = await self._collect_dashboard(context)
                sections["dashboard"] = self._make_section(
                    key="dashboard",
                    data=dashboard.data,
                    inputs=dashboard.inputs,
                    warnings=dashboard.warnings,
                    error=dashboard.error,
                    status=dashboard.status,
                    detail=options.detail,
                )
                # A composite page is only as fresh as its stalest leg, so the
                # published date stays the shared `_as_of` composite result and
                # only its policy is labelled here.
                sections["dashboard"]["as_of_semantics"] = COMPOSITE_AS_OF_SEMANTICS
                context.cached_sections["dashboard"] = sections["dashboard"]

        # Keep the envelope's section order aligned with the requested/default
        # catalog even though dashboard collection is intentionally deferred.
        sections = {key: sections[key] for key in selected if key in sections}

        environment: Dict[str, Any]
        try:
            environment = _jsonable(
                await data_api.get_api_config(db=self.db, cache_service=self.cache_service)
            )
        except Exception as exc:
            environment = {}
            warnings.append(f"Data-source metadata unavailable: {_safe_error(exc)}")
            logger.error("AI context environment metadata failed: %s", type(exc).__name__)
        if isinstance(environment, dict):
            environment["source_semantics"] = "primary_source is preference order, not per-observation vendor proof"

        completed_at = _now()
        # Last, and only here: the dashboard's own status, currency, freshness,
        # coverage, omissions and warnings were all derived above from the full
        # component payloads, so dropping the duplicated copies cannot move any
        # of them. This is the published-document step and nothing reads it back.
        _reference_dashboard_components(sections)
        return {
            "schema_version": SCHEMA_VERSION,
            "export_id": f"portfolio-{uuid.uuid4().hex[:12]}",
            "generated_at": generated_at,
            "completed_at": completed_at,
            "snapshot_consistency": "best_effort",
            # AD-16: the claim above is the collection mode; this is whether the
            # prices that came back actually agreed. A `best_effort` export
            # whose clocks line up and one whose clocks do not are different
            # findings, so the evidence gets its own key rather than overwriting
            # a documented Literal. See _snapshot_consistency_measured.
            "snapshot_consistency_measured": _snapshot_consistency_measured(
                sections, portfolio_json
            ),
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
        compact_data = _normalize_public_data_status(compact_data)
        resolved_status = status or _payload_status(compact_data)
        if error is None and isinstance(compact_data, Mapping) and compact_data.get("error"):
            error = str(compact_data["error"])
        coverage = _section_coverage(key, inputs, compact_data)
        if error and resolved_status == "available":
            resolved_status = "partial"
        currency = _infer_currency(compact_data, inputs)
        mixed_units = _mixed_currency_units(compact_data)
        section_warnings = list(warnings or [])
        section_warnings.extend(_collect_warnings(compact_data))
        if coverage:
            if coverage.get("status") in {"partial", "unavailable"} and resolved_status == "available":
                resolved_status = str(coverage["status"])
            if coverage.get("missing_tickers"):
                if resolved_status == "available":
                    resolved_status = "partial"
                missing = ", ".join(coverage["missing_tickers"])
                section_warnings.append(
                    f"Result coverage is missing requested ticker(s): {missing}"
                )
        if mixed_units:
            section_warnings.append(
                "Section mixes monetary units ("
                + ", ".join(mixed_units)
                + "); no single currency is declared for the composite"
            )
        resolved_as_of = _as_of(compact_data)
        as_of_semantics = _payload_as_of_semantics(compact_data, resolved_as_of)
        run_freshness = _run_timestamp_as_of(compact_data, resolved_as_of)
        if run_freshness:
            # A "freshness" date that lands inside this export's own collection
            # window is a quote refresh that happened DURING the run, not a
            # historical measurement. Saying so beats implying an observation
            # precision the source never had.
            section_warnings.append(run_freshness)
        if not section_warnings:
            # ENV-016: a section that publishes a degradation must name it, and
            # the obligation does not stop at this list being empty. Filled from
            # the degradations this payload actually computed - a gate, an
            # error, an omission, a component that produced nothing, a measured
            # window shortfall - so no number anywhere has to change to comply.
            section_warnings.extend(
                _degradation_warnings(
                    compact_data,
                    status=resolved_status,
                    error=error,
                    omitted=omitted,
                )
            )
        if resolved_as_of and not any(
            token in str(warning).lower()
            for warning in section_warnings
            for token in _STALE_DISCLOSURE_TOKENS
        ):
            # A section that gained an `as_of` has to be readable as fresh or as
            # old; publishing the date without its measured age is what leaves a
            # consumer to guess. Derived from the export's own clock.
            stale = _stale_as_of_warning(resolved_as_of)
            if stale:
                section_warnings.append(stale)
        section_warnings = list(dict.fromkeys(section_warnings))
        section = {
            "key": key,
            "title": SECTION_CATALOG[key]["title"],
            "route": SECTION_CATALOG[key]["route"],
            "status": resolved_status,
            "detail": detail,
            "generated_at": _now(),
            "as_of": resolved_as_of,
            "as_of_semantics": as_of_semantics,
            "currency": currency,
            "inputs": _jsonable(inputs),
            "coverage": coverage,
            "data": compact_data,
            "omitted_fields": omitted,
            "warnings": section_warnings,
        }
        if error:
            # A successful section carries no error field at all; the API
            # boundary drops the response model's null error sentinel.
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
            coverage = json_value.get("universe_coverage") if isinstance(json_value, Mapping) else None
            if isinstance(coverage, Mapping) and status == "available":
                if coverage.get("status") in {"partial", "unavailable"}:
                    status = str(coverage["status"])
                elif coverage.get("missing_tickers"):
                    status = "partial"
            result: Dict[str, Any] = {"status": status, "data": json_value}
            if status != "available" and isinstance(json_value, Mapping) and json_value.get("error"):
                result["error"] = str(json_value["error"])
            return result
        except Exception as exc:
            await self._rollback_quietly()
            logger.error("AI context component %s failed: %s", name, type(exc).__name__)
            return {"status": "unavailable", "data": None, "error": _safe_error(exc)}

    async def _performance_history_request(self, context: _BuildContext) -> Any:
        """Request the delivered-window envelope, tolerating a legacy signature.

        The route keeps its bare-array default; the exporter opts in with
        `include_metadata=true` so a short delivery is measurable.  If the route
        does not accept the flag yet, retry the plain call rather than failing
        the whole dashboard - the delivered window then stays unmeasured instead
        of being assumed complete.
        """
        try:
            return await analytics_api.get_performance_history(
                days=PERFORMANCE_HISTORY_DAYS,
                tickers=context.ticker_csv,
                db=self.db,
                data_service=self.data_service,
                benchmark_service=self.benchmark_service,
                include_metadata=True,
            )
        except TypeError as exc:
            if "include_metadata" not in str(exc):
                raise
            logger.debug("performance-history envelope unsupported; using the array response")
            return await analytics_api.get_performance_history(
                days=PERFORMANCE_HISTORY_DAYS,
                tickers=context.ticker_csv,
                db=self.db,
                data_service=self.data_service,
                benchmark_service=self.benchmark_service,
            )

    async def _collect_dashboard(self, context: _BuildContext) -> _Collected:
        """Collect the dashboard's visible data without duplicating sections.

        The dashboard page is a composition of several analytics endpoints. The
        default export also requests those endpoints as named sections, so
        reuse their canonical section envelopes here. Components that have no
        standalone export section (risk score and the dashboard summary) are
        fetched once and kept request-scoped. Every component keeps its own
        freshness evidence, so the page-level as-of is the oldest measured leg
        rather than an unrelated portfolio quote.
        """
        async def cached_or_fetch(
            name: str,
            section_key: Optional[str],
            callback: Callable[[], Awaitable[Any]],
        ) -> Dict[str, Any]:
            if section_key and section_key in context.cached_sections:
                section = context.cached_sections[section_key]
                result: Dict[str, Any] = {
                    "status": section.get("status", "unavailable"),
                    "data": section.get("data"),
                }
                if section.get("error"):
                    result["error"] = section["error"]
                return result
            if section_key and section_key in context.cached:
                cached_data = _jsonable(context.cached[section_key])
                cached_status = _component_status(cached_data)
                coverage = (
                    cached_data.get("universe_coverage")
                    if isinstance(cached_data, Mapping)
                    else None
                )
                if isinstance(coverage, Mapping):
                    if coverage.get("status") in {"partial", "unavailable"} and cached_status == "available":
                        cached_status = str(coverage["status"])
                    if coverage.get("missing_tickers") and cached_status == "available":
                        cached_status = "partial"
                result = {"status": cached_status, "data": cached_data}
                if cached_status != "available" and isinstance(cached_data, Mapping) and cached_data.get("error"):
                    result["error"] = str(cached_data["error"])
                return result
            result = await self._component(name, callback)
            # Dashboard-only calls are not standalone sections, but retaining
            # them makes a second dashboard assembly deterministic and cheap.
            context.cached_sections[f"_dashboard_{name}"] = result
            return result

        components: Dict[str, Any] = {}
        components["portfolio"] = {
            "status": _component_status(context.portfolio),
            "data": _jsonable(context.portfolio),
        }
        components["summary"] = await cached_or_fetch(
            "summary",
            None,
            lambda: analytics_api.get_analytics_summary(
                db=self.db,
                data_service=self.data_service,
                analytics_engine=self.analytics_engine,
                benchmark_service=self.benchmark_service,
            ),
        )
        components["performance_history"] = _performance_history_component(
            await self._component(
                "performance_history",
                lambda: self._performance_history_request(context),
            ),
            PERFORMANCE_HISTORY_DAYS,
        )
        components["realized_risk"] = await cached_or_fetch(
            "realized_risk",
            "realized_risk",
            lambda: analytics_api.get_realized_risk(
                tickers=context.ticker_csv,
                start=None,
                end=None,
                db=self.db,
                data_service=self.data_service,
                analytics_engine=self.analytics_engine,
            ),
        )
        components["forecast_risk"] = await cached_or_fetch(
            "forecast_risk",
            "forecast_risk",
            lambda: analytics_api.get_forecast_risk(
                model=context.options.forecast_model,
                horizon=context.options.forecast_horizon,
                tickers=context.ticker_csv,
                start=None,
                end=None,
                db=self.db,
                data_service=self.data_service,
                analytics_engine=self.analytics_engine,
            ),
        )
        components["factor_exposure"] = await cached_or_fetch(
            "factor_exposure",
            "factor_exposure",
            lambda: analytics_api.get_factor_exposure(
                tickers=context.ticker_csv,
                lookback_days=context.options.factor_lookback_days,
                db=self.db,
                data_service=self.data_service,
                benchmark_service=self.benchmark_service,
                analytics_engine=self.analytics_engine,
            ),
        )
        components["concentration"] = await cached_or_fetch(
            "concentration",
            "concentration",
            lambda: analytics_api.get_concentration_metrics(
                db=self.db,
                data_service=self.data_service,
                analytics_engine=self.analytics_engine,
            ),
        )
        components["liquidity"] = await cached_or_fetch(
            "liquidity",
            "liquidity",
            lambda: analytics_api.get_liquidity_metrics(
                db=self.db,
                data_service=self.data_service,
                analytics_engine=self.analytics_engine,
            ),
        )
        components["risk_score"] = await cached_or_fetch(
            "risk_score",
            None,
            lambda: analytics_api.get_risk_score(
                db=self.db,
                data_service=self.data_service,
                analytics_engine=self.analytics_engine,
                benchmark_service=self.benchmark_service,
            ),
        )
        components["regime"] = await cached_or_fetch(
            "regime",
            "regime",
            lambda: analytics_api.get_regime(
                lookback_days=1100,
                with_portfolio=bool(context.tickers),
                db=self.db,
                data_service=self.data_service,
                benchmark=self.benchmark_service,
            ),
        )
        components["risk_contribution"] = await cached_or_fetch(
            "risk_contribution",
            "risk_contribution",
            lambda: analytics_api.get_risk_contribution(
                tickers=context.ticker_csv,
                db=self.db,
                data_service=self.data_service,
            ),
        )
        data = {"components": components}
        # Summary linkage and the risk-score delta both need every component to
        # be collected first, because they read canonical sibling results.
        warnings: List[str] = []
        warnings.extend(_link_dashboard_summary(components))
        warnings.extend(_normalize_risk_score_change(components.get("risk_score") or {}))
        # Component-level warnings (the delivered performance window, the
        # unmeasured risk delta) live beside their component's data, so they are
        # lifted onto the section here for human-readable disclosures.
        for component in components.values():
            if isinstance(component, Mapping):
                warnings.extend(str(item) for item in component.get("warnings") or [])
        declared_semantics = {
            "performance_history": components["performance_history"].get("as_of_semantics")
        }
        data["component_as_of"] = {
            name: _component_as_of_entry(component, declared_semantics.get(name))
            for name, component in components.items()
        }
        # Label the composite policy beside the per-component map. The date
        # itself stays owned by the shared `_as_of` composite rule (oldest
        # component wins), so no second as-of policy can drift from it.
        data["as_of_semantics"] = COMPOSITE_AS_OF_SEMANTICS
        for component_name in ("risk_contribution", "summary", "realized_risk"):
            component = components.get(component_name)
            if not isinstance(component, Mapping):
                continue
            component_data = component.get("data")
            coverage = component_data.get("universe_coverage") if isinstance(component_data, Mapping) else None
            if isinstance(coverage, Mapping):
                data["universe_coverage"] = coverage
                break
        return _Collected(
            data=data,
            inputs={"performance_days": PERFORMANCE_HISTORY_DAYS, "tickers": context.tickers},
            status=_group_status(components),
            warnings=warnings,
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
        scenario_universes = []
        for scenario in results.values():
            coverage = scenario.get("universe_coverage") if isinstance(scenario, Mapping) else None
            if isinstance(coverage, Mapping):
                scenario_universes.append(set(_ticker_list(coverage.get("available_tickers"))))
        if scenario_universes:
            available = sorted(set.intersection(*scenario_universes))
            missing = [ticker for ticker in context.tickers if ticker not in set(available)]
            data["universe_coverage"] = {
                "requested_tickers": _ticker_list(context.tickers),
                "available_tickers": available,
                "covered_tickers": [ticker for ticker in context.tickers if ticker in set(available)],
                "missing_tickers": missing,
                "requested_count": len(context.tickers),
                "available_count": len(available),
                "coverage_ratio": round(len(available) / len(context.tickers), 6) if context.tickers else None,
                "complete": not missing if context.tickers else None,
                "status": "unavailable" if context.tickers and not available else "partial" if missing else "complete" if context.tickers else "unknown",
            }
        coverage = data.get("universe_coverage", {}) if isinstance(data, Mapping) else {}
        status = (
            "unavailable" if results and coverage.get("status") == "unavailable"
            else "available" if results and not failures and not coverage.get("missing_tickers")
            else "partial" if results else "unavailable"
        )
        # DI-2: every scenario's loss is scaled by a MEASURED annualized
        # volatility over that scenario's own delivered frame, so a -54% loss
        # published with no date and no window cannot be aged. The composite is
        # only as fresh as its stalest leg, so the section dates itself by the
        # OLDEST scenario observation and names that rule in the semantics label
        # - a newer leg must never make the section look fresher than the leg
        # that produced the worst number in it.
        scenario_dates = {
            name: _date_text(scenario.get("latest_observation_date"))
            for name, scenario in results.items()
            if isinstance(scenario, Mapping)
        }
        measured = sorted({value for value in scenario_dates.values() if value})
        if measured:
            data["as_of"] = measured[0]
            data["as_of_semantics"] = STRESS_AS_OF_SEMANTICS
            data["scenario_observation_dates"] = {
                name: value for name, value in sorted(scenario_dates.items()) if value
            }
            data["scenario_observation_date_basis"] = STRESS_AS_OF_BASIS
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
        if "risk_contribution" in context.cached:
            data = context.cached["risk_contribution"]
            return _Collected(
                data=data,
                inputs={"tickers": context.tickers},
                status=_component_status(data),
            )
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
            cached_status = _component_status(cached)
            cached_coverage = cached.get("universe_coverage") if isinstance(cached, Mapping) else None
            if isinstance(cached_coverage, Mapping) and cached_status == "available":
                if cached_coverage.get("status") in {"partial", "unavailable"}:
                    cached_status = str(cached_coverage["status"])
                elif cached_coverage.get("missing_tickers"):
                    cached_status = "partial"
            components["risk_contribution"] = {
                "status": cached_status,
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
            context.cached["risk_contribution"] = components["risk_contribution"].get("data")
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
        data = {"components": components}
        coverage_candidates = []
        for component in components.values():
            if not isinstance(component, Mapping):
                continue
            component_data = component.get("data")
            coverage = component_data.get("universe_coverage") if isinstance(component_data, Mapping) else None
            if isinstance(coverage, Mapping):
                coverage_candidates.append(coverage)
        if coverage_candidates:
            requested = _ticker_list(context.tickers)
            available_sets = [set(_ticker_list(candidate.get("available_tickers"))) for candidate in coverage_candidates]
            available = sorted(set.intersection(*available_sets)) if available_sets else []
            missing = [ticker for ticker in requested if ticker not in set(available)]
            data["universe_coverage"] = {
                "requested_tickers": requested,
                "available_tickers": available,
                "covered_tickers": [ticker for ticker in requested if ticker in set(available)],
                "missing_tickers": missing,
                "requested_count": len(requested),
                "available_count": len(available),
                "coverage_ratio": round(len(available) / len(requested), 6) if requested else None,
                "complete": not missing if requested else None,
                "status": "unavailable" if requested and not available else "partial" if missing else "complete" if requested else "unknown",
            }
        return _Collected(
            data=data,
            inputs={
                "tickers": context.tickers,
                "lookback_days": 756,
                "component_lookbacks": {
                    "risk_contribution": 365,
                    "tail_dependence": 756,
                    "volatility_cone": 756,
                    "correlation_stability": 756,
                },
            },
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
        composite = compose_india_composite(
            tickers=context.tickers,
            flows=components["institutional_flows"].get("data"),
            delivery=components["delivery_anomalies"].get("data"),
            liquidity=components["liquidity_limits"].get("data"),
            flow_lookback_days=30,
            delivery_lookback_days=20,
            delivery_sigma_threshold=2.0,
            components=components,
        )
        _drop_unmeasured_coverage_ratios(composite)
        return _Collected(
            data=composite,
            inputs={
                "tickers": context.tickers,
                "component_inputs": composite["component_inputs"],
            },
            status=composite["data_status"],
        )


#: Count keys a coverage ratio is asserted over. Mirrors the audit's
#: `COVERAGE_COUNT_KEYS`; asserted equal in the freshness test so the two lists
#: cannot drift apart.
COVERAGE_COUNT_KEYS = (
    "covered_count",
    "available_count",
    "delivered_count",
    "observed_count",
    "measured_count",
)


def _iter_mappings(value: Any, path: str = "payload") -> Iterable[Tuple[str, Any]]:
    """Every mutable mapping in a payload tree, paired with its path, in order.

    Yields the live object, not a copy, so a caller can normalise in place. Only
    plain dicts are yielded: a read-only mapping cannot be corrected by writing
    to it, and pretending otherwise would hide the defect.
    """
    if isinstance(value, dict):
        yield path, value
        for key, item in value.items():
            yield from _iter_mappings(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            yield from _iter_mappings(item, f"{path}[{index}]")


def _drop_unmeasured_coverage_ratios(payload: Any) -> None:
    """A ratio asserted over a count that was never taken is a fabricated number.

    `0` is a measurement: it says zero of fourteen symbols had usable delivery
    history. `null` is an absence: it says the count was never taken because no
    bhavcopy delivery history was ingested. Shipping the first beside the second
    - which is what the india-flows component coverage did for
    `delivery_anomalies` - hands a consumer multiplying a ratio by a universe a
    confident `0` instead of "unknown", and the sibling `institutional_flows`
    block already gets this right by publishing no ratio at all.

    The count is never invented: where it is null the ratio is dropped and the
    reason is recorded, so the honest absence survives the edit. Where a real
    count is present the ratio stands, because that is the measurement it
    describes.
    """
    for _path, node in _iter_mappings(payload, "payload"):
        ratio = node.get("coverage_ratio")
        if not (isinstance(ratio, (int, float)) and math.isfinite(ratio)):
            continue
        nulls = [key for key in COVERAGE_COUNT_KEYS if key in node and node[key] is None]
        if not nulls:
            continue
        node["coverage_ratio"] = None
        node["coverage_ratio_status"] = "unavailable"
        node["coverage_ratio_unavailable_reason"] = (
            "coverage_ratio is not published because "
            + ", ".join(sorted(nulls))
            + " is null: the coverage count was never taken, so a ratio over it "
            "would be a measurement of nothing"
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
                # Trimming the series must not leave the declared coverage
                # describing a longer window than the rows a consumer can see.
                # Recompute the count/first-observation from the delivered rows
                # and say the series was shortened, rather than publishing an
                # observation_count with no matching data behind it.
                coverage = performance.get("history_coverage")
                if isinstance(coverage, dict):
                    coverage["observation_count"] = len(performance["data"])
                    first = performance["data"][0] if performance["data"] else None
                    if isinstance(first, dict):
                        coverage["first_observation"] = first.get("date", coverage.get("first_observation"))
                    coverage["series_trimmed_in_summary"] = True
                    coverage["series_trimmed_observation_count"] = len(values)
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
            series = correlation["data"].get("series")
            if isinstance(series, list) and len(series) > 60:
                correlation["data"]["series"] = series[-60:]
                # `omitted_fields` says a field was OMITTED, but this one is
                # still present (just shorter). Listing the bare path made a
                # consumer skip a field that exists. Name the real path, state
                # how much was dropped, and say plainly that it was shortened
                # rather than removed.
                correlation["data"]["series_trimmed_in_summary"] = True
                correlation["data"]["series_observations"] = len(series)
                correlation["data"]["series_retained"] = 60
                omitted.append("components.correlation_stability.data.series")
    elif key == "india_flows":
        components = compact.get("components") if isinstance(compact, dict) else None
        flows = components.get("institutional_flows") if isinstance(components, dict) else None
        if isinstance(flows, dict) and isinstance(flows.get("data"), dict):
            values = flows["data"].get("flows")
            if isinstance(values, list) and len(values) > 30:
                flows["data"]["flows"] = values[-30:]
                omitted.append("components.institutional_flows.flows")
    elif key == "portfolio" and isinstance(compact, dict):
        # DI-5: `omitted_fields` is read as "nothing was dropped from this
        # section", and for `portfolio` that read is wrong in a second way: the
        # ledger is a COMPACTION ledger, so it stayed `[]` while the endpoint
        # never produced the book-level aggregates a reader needs to reconcile
        # `total_value` at all. Compaction is not the only way a field goes
        # missing, so the absent aggregates are named here with the reason,
        # rather than leaving an empty list to imply the ledger is complete.
        # Book level means the payload's own top level: `total_cost` exists on
        # every position row, and that per-leg figure is exactly what is NOT the
        # book-level total the section is missing.
        absent = [
            name for name in PORTFOLIO_AGGREGATES_NOT_PRODUCED if name not in compact
        ]
        if absent:
            compact["aggregates_not_produced"] = {
                "fields": sorted(absent),
                "reason": PORTFOLIO_AGGREGATES_ABSENT_REASON,
            }
            omitted.extend(sorted(absent))

    return compact, sorted(set(omitted))


#: Book-level aggregates the portfolio endpoint does not compute. Named here
#: because the export is what promises a reader that `omitted_fields` is a
#: complete account of what is not in the payload.
PORTFOLIO_AGGREGATES_NOT_PRODUCED = (
    "total_cost",
    "total_pnl",
    "day_change",
    "previous_close",
)

PORTFOLIO_AGGREGATES_ABSENT_REASON = (
    "The portfolio endpoint publishes per-position cost, P&L and market value "
    "but no previous close, so it cannot produce a book-level day change, and it "
    "publishes no book-level cost or unrealized-P&L total. These are absent from "
    "the endpoint, not dropped by compaction; a reader who needs them must sum "
    "the per-position rows, and cannot derive day_change at all because no "
    "previous_close is published."
)


def render_markdown(payload: Mapping[str, Any]) -> str:
    """Render a stable Markdown view from the canonical JSON payload."""
    safe_payload = _jsonable(payload)
    lines: List[str] = [
        "# FinEngine Portfolio AI Context",
        "",
        f"- Generated: `{safe_payload.get('generated_at', '')}`",
        f"- Completed: `{safe_payload.get('completed_at', '')}`",
        f"- Snapshot consistency: `{safe_payload.get('snapshot_consistency', 'unknown')}`",
        (
            "- Price clocks measured: "
            f"`{(safe_payload.get('snapshot_consistency_measured') or {}).get('status', 'unmeasured')}` "
            f"({(safe_payload.get('snapshot_consistency_measured') or {}).get('distinct_price_instants', '?')}"
            " price instant(s), "
            f"{(safe_payload.get('snapshot_consistency_measured') or {}).get('distinct_delivered_bar_dates', '?')}"
            " delivered bar date(s)) - full block at "
            "`sections.portfolio.data.snapshot_consistency`"
        ),
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
    lines.extend(
        [
            "## Contract",
            "",
            f"- Section status: `{'`, `'.join(SECTION_STATUS_VOCABULARY)}`",
            f"- Data status: `{'`, `'.join(DATA_STATUS_VOCABULARY)}` (was there measured data?)",
            "- Universe completeness stays in `coverage.status`: `complete`, `partial`, `unavailable`, `unknown`",
            f"- `coverage.weight_basis` appears only when an active leg was dropped and the surviving weights were renormalized (`{ACTIVE_WEIGHT_BASIS}`)",
            "- `currency` follows the section payload's declared unit, then its inputs; a mixed-unit composite declares no currency",
            "- `as_of` is a declared observation date, or the oldest component date for a composite; it is never the request window end",
            "- Ticker lists follow request order, so repeated universes export identically",
            "",
        ]
    )
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
            coverage = section.get("coverage")
            if isinstance(coverage, Mapping):
                if coverage.get("status"):
                    lines.append(f"- Coverage: `{coverage['status']}`")
                if coverage.get("missing_tickers"):
                    lines.append(
                        "- Missing result tickers: `"
                        + ", ".join(coverage["missing_tickers"])
                        + "`"
                    )
                if coverage.get("weight_basis"):
                    lines.append(f"- Weight basis: `{coverage['weight_basis']}`")
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
