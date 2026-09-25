"""India composite contract for the AI context export (ticket 08 / V3-15).

The India section is a *composite* of three heterogeneous components:

* ``institutional_flows`` - market-wide FII/DII daily cash flows.  It has no
  ticker universe at all, so ticker coverage is meaningless for it and no
  portfolio weight was ever renormalized.
* ``delivery_anomalies`` - symbol-scoped delivery-% z-scores over a requested
  ticker roster.
* ``liquidity_limits`` - portfolio-position ADV / days-to-liquidate / Amihud
  limits, i.e. the only component with real ticker coverage.

The section-level contract therefore promotes the *liquidity* coverage (with an
explicit ``source_component``) instead of publishing ``unknown`` while a nested
14/14 coverage block sits right underneath it, and never claims a weight basis
for a market-wide leg.

This module is deliberately pure: it takes the three already-computed component
payloads as plain dicts and returns a plain dict.  It performs no IO, touches no
database, and fabricates nothing - a component that measured nothing stays
``unavailable`` and a missing FII/DII leg stays ``None``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.services.india_data_service import LIQUIDITY_ADV_LOOKBACK_SESSIONS

# Component names, in the order they are published.
INSTITUTIONAL_FLOWS = "institutional_flows"
DELIVERY_ANOMALIES = "delivery_anomalies"
LIQUIDITY_LIMITS = "liquidity_limits"
INDIA_COMPONENTS: tuple[str, ...] = (
    INSTITUTIONAL_FLOWS,
    DELIVERY_ANOMALIES,
    LIQUIDITY_LIMITS,
)

# Scope vocabulary.  One word per component so a consumer can never read a
# market-wide aggregate as a per-holding result.
SCOPE_MARKET_WIDE = "market_wide"
SCOPE_SYMBOL_SCOPED = "symbol_scoped"
SCOPE_PORTFOLIO_POSITIONS = "portfolio_positions"
COMPONENT_SCOPES: Dict[str, str] = {
    INSTITUTIONAL_FLOWS: SCOPE_MARKET_WIDE,
    DELIVERY_ANOMALIES: SCOPE_SYMBOL_SCOPED,
    LIQUIDITY_LIMITS: SCOPE_PORTFOLIO_POSITIONS,
}

# Public data_status vocabulary (measured data?) - never a coverage word.
DATA_STATUS_VOCABULARY: tuple[str, ...] = ("available", "partial", "unavailable")
# Coverage vocabulary (universe completeness) - kept strictly separate.
COVERAGE_STATUS_VOCABULARY: tuple[str, ...] = (
    "complete",
    "partial",
    "unavailable",
    "unknown",
)

# The composite as-of date is the liquidity component's observation date only.
# Flow and delivery legs are stored records with their own (older, absent, or
# unavailable) observation dates; the portfolio quote date is never the section's
# as-of because liquidity is priced off cached history, not the live snapshot.
AS_OF_SEMANTICS = "liquidity_component_only"

# Participation rates the liquidity component is measured against.
LIQUIDITY_PARTICIPATION_RATES: tuple[float, ...] = (0.10, 0.20)

_DELIVERY_SYMBOL_SUFFIXES = (".NS", ".BO")

_MISSING_CATEGORY_POLICY = (
    "A missing FII/DII leg is published as null; it is never converted to a zero flow."
)
_MARKET_WIDE_COVERAGE_POLICY = (
    "Market-wide institutional flows have no ticker universe, so ticker coverage is "
    "unknown and no portfolio weight was renormalized for this component."
)


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _string_list(value: Any) -> List[str]:
    """Ordered, de-duplicated, trimmed string list; empty when not a list."""
    if not isinstance(value, (list, tuple, set)):
        return []
    seen: Dict[str, None] = {}
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            seen.setdefault(text, None)
    return list(seen)


def bare_symbol(symbol: Any) -> str:
    """NSE scrip form used by the bhavcopy tables (no exchange suffix)."""
    text = str(symbol or "").strip().upper()
    for suffix in _DELIVERY_SYMBOL_SUFFIXES:
        if text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def bare_symbol_list(symbols: Any) -> List[str]:
    """De-duplicated bare scrip codes preserving first-seen order."""
    seen: Dict[str, None] = {}
    for symbol in _string_list(symbols):
        cleaned = bare_symbol(symbol)
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


def normalize_data_status(value: Any) -> str:
    """Map a declared component status onto the public data_status vocabulary.

    Unrecognized or absent declarations resolve to ``unavailable``: a component
    that never said it measured something must not be reported as available.
    """
    if not isinstance(value, str):
        return "unavailable"
    text = value.strip().lower()
    if text in {"available", "complete", "ok", "success"}:
        return "available"
    if text in {"partial", "degraded", "limited"}:
        return "partial"
    return "unavailable"


def aggregate_data_status(statuses: Sequence[str]) -> str:
    """All available -> available; all unavailable -> unavailable; else partial."""
    values = [status for status in statuses if status]
    if not values:
        return "unavailable"
    if all(status == "unavailable" for status in values):
        return "unavailable"
    if all(status == "available" for status in values):
        return "available"
    return "partial"


def coverage_status_for(
    requested: Sequence[str], covered: Sequence[str], *, measured: bool = True
) -> str:
    """Coverage status for a component with a real symbol universe."""
    if not measured or not requested:
        return "unknown"
    if not covered:
        return "unavailable"
    return "complete" if len(covered) == len(requested) else "partial"


def _declared_as_of(payload: Mapping[str, Any]) -> Optional[str]:
    """First freshness key the payload itself declares (observation date first)."""
    for key in ("latest_observation_date", "as_of"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _liquidity_positions(payload: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    positions = payload.get("positions")
    if not isinstance(positions, (list, tuple)):
        return []
    return [position for position in positions if isinstance(position, Mapping)]


def _liquidity_universe(payload: Mapping[str, Any]) -> Dict[str, Any]:
    return _as_mapping(payload.get("universe_coverage"))


def flow_component_coverage(
    flows: Mapping[str, Any], *, component_status: str
) -> Dict[str, Any]:
    """Coverage for a market-wide aggregate: unknown ticker coverage, no weight basis."""
    return {
        "scope": SCOPE_MARKET_WIDE,
        "status": component_status,
        # No ticker universe exists, so universe completeness is unmeasured.
        "coverage_status": "unknown",
        "coverage_status_reason": "market_wide_aggregate_has_no_ticker_universe",
        "requested_symbols": None,
        "covered_symbols": None,
        "missing_symbols": None,
        "requested_count": None,
        "covered_count": None,
        "available_categories": _string_list(flows.get("available_categories")),
        "missing_categories": _string_list(flows.get("missing_categories")),
        "incomplete_dates": _string_list(flows.get("incomplete_dates")),
        "missing_category_policy": _MISSING_CATEGORY_POLICY,
        "notes": [_MARKET_WIDE_COVERAGE_POLICY],
        # Deliberately no `weight_basis`: no portfolio weight was renormalized.
    }


def delivery_component_coverage(
    delivery: Mapping[str, Any], *, component_status: str
) -> Dict[str, Any]:
    """Coverage for the symbol-scoped delivery component, with the real roster."""
    requested = _string_list(delivery.get("requested_symbols"))
    covered = _string_list(delivery.get("covered_symbols"))
    missing = _string_list(delivery.get("missing_symbols"))
    if not missing and requested:
        missing = [symbol for symbol in requested if symbol not in set(covered)]
    measured = bool(requested) and "requested_symbols" in delivery
    status = coverage_status_for(requested, covered, measured=measured)
    if status == "unavailable" and component_status == "unavailable":
        reason = "no_requested_symbol_had_usable_delivery_history"
    elif status in {"partial", "unavailable"}:
        reason = "requested_symbols_without_usable_delivery_history"
    elif status == "unknown":
        reason = "delivery_symbol_universe_not_reported_by_the_source"
    else:
        reason = "every_requested_symbol_has_usable_delivery_history"
    return {
        "scope": SCOPE_SYMBOL_SCOPED,
        "status": component_status,
        "coverage_status": status,
        "coverage_status_reason": reason,
        "requested_symbols": requested or None,
        "covered_symbols": covered or None,
        "missing_symbols": missing or None,
        "requested_count": len(requested) or None,
        "covered_count": len(covered) or None,
        "coverage_ratio": (
            round(len(covered) / len(requested), 6) if requested and measured else None
        ),
        "notes": [
            "Coverage counts NSE delivery history only; it says nothing about "
            "institutional-flow or liquidity coverage."
        ],
    }


def liquidity_component_coverage(
    liquidity: Mapping[str, Any], *, component_status: str
) -> Dict[str, Any]:
    """Coverage for the portfolio-position liquidity component."""
    coverage = _liquidity_universe(liquidity)
    requested = _string_list(coverage.get("requested_tickers"))
    covered = _string_list(coverage.get("covered_tickers"))
    if not covered:
        covered = _string_list(coverage.get("available_tickers"))
    missing = _string_list(coverage.get("missing_tickers"))
    if not missing and requested:
        missing = [ticker for ticker in requested if ticker not in set(covered)]
    measured = bool(requested) and "requested_tickers" in coverage
    status = str(coverage.get("status") or "").strip().lower()
    if status not in COVERAGE_STATUS_VOCABULARY:
        status = coverage_status_for(requested, covered, measured=measured)
    if status == "complete":
        reason = "every_portfolio_position_had_price_history"
    elif status == "partial":
        reason = "portfolio_positions_without_price_history"
    elif status == "unavailable":
        reason = "no_portfolio_position_had_price_history"
    else:
        reason = "liquidity_universe_not_reported_by_the_source"
    return {
        "scope": SCOPE_PORTFOLIO_POSITIONS,
        "status": component_status,
        "coverage_status": status,
        "coverage_status_reason": reason,
        "requested_tickers": requested or None,
        "covered_tickers": covered or None,
        "missing_tickers": missing or None,
        "failed_tickers": _string_list(coverage.get("failed_tickers")) or None,
        "requested_count": len(requested) or None,
        "covered_count": len(covered) or None,
        "coverage_ratio": (
            coverage.get("coverage_ratio")
            if isinstance(coverage.get("coverage_ratio"), (int, float))
            else (round(len(covered) / len(requested), 6) if requested and measured else None)
        ),
        "portfolio_position_count": len(_liquidity_positions(liquidity)) or None,
        "notes": [
            "Coverage describes price history for portfolio positions; it is the "
            "only component in this section with a ticker universe."
        ],
    }


def _liquidity_universe_coverage(
    liquidity: Mapping[str, Any],
    *,
    liquidity_coverage_status: str,
    fallback_requested: Sequence[str],
) -> Dict[str, Any]:
    """Promote the nested liquidity coverage for the section-level block.

    The promotion is explicit about its origin so a consumer cannot mistake it
    for flow or delivery ticker coverage.  An unavailable liquidity component
    stays unavailable - the context roster is never substituted as coverage.
    """
    coverage = _liquidity_universe(liquidity)
    promoted: Dict[str, Any] = dict(coverage) if coverage else {}
    if not coverage:
        # An entirely missing component measured nothing: the section must not
        # borrow the context roster as coverage.
        requested = _string_list(fallback_requested)
        promoted = {
            "requested_tickers": requested or None,
            "available_tickers": [],
            "covered_tickers": [],
            "missing_tickers": requested or None,
            "requested_count": len(requested) or None,
            "available_count": 0,
            "coverage_ratio": 0.0 if requested else None,
            "complete": False if requested else None,
            "status": liquidity_coverage_status if liquidity else "unavailable",
        }
    # The source coverage vocabulary is authoritative where it declared one;
    # the derived component status is the fallback for slim payloads.
    declared_status = str(promoted.get("status") or "").strip().lower()
    promoted["status"] = (
        declared_status
        if declared_status in COVERAGE_STATUS_VOCABULARY
        else liquidity_coverage_status
    )
    # `weight_basis` survives only when the source coverage block declared one
    # (i.e. an active leg was actually dropped and weights were renormalized).
    if "weight_basis" not in coverage:
        promoted.pop("weight_basis", None)
    promoted.update({
        "source_component": LIQUIDITY_LIMITS,
        "scope": SCOPE_PORTFOLIO_POSITIONS,
        "coverage_semantics": (
            "Price-history coverage of portfolio positions, measured by the "
            "liquidity_limits component only."
        ),
        "not_applicable_components": [INSTITUTIONAL_FLOWS, DELIVERY_ANOMALIES],
    })
    return promoted


def compose_india_composite(
    *,
    tickers: Optional[Sequence[str]] = None,
    flows: Any = None,
    delivery: Any = None,
    liquidity: Any = None,
    flow_lookback_days: int = 30,
    delivery_lookback_days: int = 20,
    delivery_sigma_threshold: float = 2.0,
    components: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compose the three India component payloads into one honest section body.

    Args:
        tickers: the portfolio roster the section was requested for.  It is only
            ever used to describe an *unavailable* liquidity universe; it is
            never promoted as measured coverage.
        flows: ``/analytics/india-flows`` payload.
        delivery: ``/analytics/delivery-anomalies`` payload.
        liquidity: ``/analytics/liquidity-limits`` payload.
        components: the already-collected ``{name: {"status", "data"}}``
            envelopes.  When supplied they are passed through untouched and
            their ``status`` is honoured; otherwise envelopes are built here
            from the raw payloads.

    Returns:
        The composite section body: ``components`` (unchanged payloads),
        ``component_inputs``, ``component_coverage``, ``component_as_of``,
        ``as_of``/``as_of_semantics``, ``universe_coverage`` and ``data_status``.
    """
    flow_payload = _as_mapping(flows)
    delivery_payload = _as_mapping(delivery)
    liquidity_payload = _as_mapping(liquidity)
    roster = _string_list(tickers)

    flow_envelope = _as_mapping(components.get(INSTITUTIONAL_FLOWS)) if components else {}
    delivery_envelope = (
        _as_mapping(components.get(DELIVERY_ANOMALIES)) if components else {}
    )
    liquidity_envelope = _as_mapping(components.get(LIQUIDITY_LIMITS)) if components else {}

    def _status(envelope: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
        declared = envelope.get("status")
        if isinstance(declared, str) and declared.strip():
            return normalize_data_status(declared)
        if not payload:
            return "unavailable"
        return normalize_data_status(payload.get("data_status"))

    flow_status = _status(flow_envelope, flow_payload)
    delivery_status = _status(delivery_envelope, delivery_payload)
    liquidity_status = _status(liquidity_envelope, liquidity_payload)

    flow_coverage = flow_component_coverage(flow_payload, component_status=flow_status)
    delivery_coverage = delivery_component_coverage(
        delivery_payload, component_status=delivery_status
    )
    liquidity_coverage = liquidity_component_coverage(
        liquidity_payload, component_status=liquidity_status
    )

    # The delivery component's universe is exactly the roster it reported; the
    # context roster is only a fallback when the source published none.
    delivery_universe = _string_list(delivery_coverage.get("requested_symbols")) or (
        bare_symbol_list(roster) if delivery_payload else []
    )
    liquidity_universe = _string_list(liquidity_coverage.get("requested_tickers")) or (
        _string_list(position.get("ticker") for position in _liquidity_positions(liquidity_payload))
    )

    def _provenance(status: str) -> str:
        return "measured" if status == "available" else (
            "partial" if status == "partial" else "unavailable"
        )

    component_inputs: Dict[str, Any] = {
        INSTITUTIONAL_FLOWS: {
            "scope": SCOPE_MARKET_WIDE,
            "lookback_days": flow_lookback_days,
            "lookback_basis": "stored_trading_sessions",
            # A market-wide aggregate has no ticker universe; portfolio tickers
            # must never be presented as one.
            "symbol_universe": None,
            "categories": ["FII", "DII"],
            "value_unit": "INR_crores",
            "aggregation": "market_wide_daily_net_cash_flow",
            "provenance": _provenance(flow_status),
        },
        DELIVERY_ANOMALIES: {
            "scope": SCOPE_SYMBOL_SCOPED,
            "lookback_days": delivery_lookback_days,
            "lookback_basis": "trading_sessions_baseline",
            "sigma_threshold": delivery_sigma_threshold,
            "symbol_universe": delivery_universe or None,
            "requested_symbol_count": len(delivery_universe) or None,
            "provenance": _provenance(delivery_status),
        },
        LIQUIDITY_LIMITS: {
            "scope": SCOPE_PORTFOLIO_POSITIONS,
            "lookback_days": LIQUIDITY_ADV_LOOKBACK_SESSIONS,
            "lookback_basis": "trading_sessions",
            "adv_participation_rates": list(LIQUIDITY_PARTICIPATION_RATES),
            "symbol_universe": liquidity_universe or None,
            "universe_source": "all_portfolio_positions",
            "provenance": _provenance(liquidity_status),
        },
    }

    component_as_of: Dict[str, Optional[str]] = {
        INSTITUTIONAL_FLOWS: _declared_as_of(flow_payload),
        DELIVERY_ANOMALIES: _declared_as_of(delivery_payload),
        LIQUIDITY_LIMITS: _declared_as_of(liquidity_payload),
    }
    # Only the liquidity leg carries a current portfolio observation date.
    as_of = component_as_of[LIQUIDITY_LIMITS]
    if as_of is None:
        as_of_semantics = None
        as_of_note = (
            "No component published an observation date for this composite; the "
            "stored liquidity, delivery, and flow records do not provide one."
        )
    else:
        as_of_semantics = AS_OF_SEMANTICS
        as_of_note = (
            f"as_of is the {LIQUIDITY_LIMITS} component's newest price observation; "
            "the institutional-flow and delivery legs are stored records with their own "
            "dates in component_as_of, and the portfolio quote date is never used."
        )

    def _envelope(
        envelope: Mapping[str, Any], payload: Mapping[str, Any], status: str
    ) -> Dict[str, Any]:
        """Keep a collected envelope byte-identical; build one when absent."""
        if envelope:
            return dict(envelope)
        return {"status": status, "data": payload or None}

    composite: Dict[str, Any] = {
        "components": {
            INSTITUTIONAL_FLOWS: _envelope(flow_envelope, flow_payload, flow_status),
            DELIVERY_ANOMALIES: _envelope(
                delivery_envelope, delivery_payload, delivery_status
            ),
            LIQUIDITY_LIMITS: _envelope(
                liquidity_envelope, liquidity_payload, liquidity_status
            ),
        },
        "data_status": aggregate_data_status(
            [flow_status, delivery_status, liquidity_status]
        ),
        "component_status": {
            INSTITUTIONAL_FLOWS: flow_status,
            DELIVERY_ANOMALIES: delivery_status,
            LIQUIDITY_LIMITS: liquidity_status,
        },
        "component_inputs": component_inputs,
        "component_coverage": {
            INSTITUTIONAL_FLOWS: flow_coverage,
            DELIVERY_ANOMALIES: delivery_coverage,
            LIQUIDITY_LIMITS: liquidity_coverage,
        },
        "component_as_of": component_as_of,
        "as_of": as_of,
        "as_of_semantics": as_of_semantics,
        "as_of_note": as_of_note,
        "universe_coverage": _liquidity_universe_coverage(
            liquidity_payload,
            liquidity_coverage_status=str(liquidity_coverage["coverage_status"]),
            fallback_requested=roster,
        ),
        "coverage_notes": [
            "Section coverage is the liquidity component's portfolio-position price "
            "history; see component_coverage for the market-wide flow and "
            "symbol-scoped delivery universes.",
            _MARKET_WIDE_COVERAGE_POLICY,
        ],
    }
    return composite
