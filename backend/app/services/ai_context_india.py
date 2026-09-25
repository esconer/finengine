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

Because that promotion describes only one of the three components, the promoted
block also carries ``covers_components``, ``coverage_completeness_scope`` and a
composite-scoped ``composite_coverage_status``/``composite_coverage_status_reason``,
so a mixed-universe composite can never be read as universally covered from
``status``/``complete`` alone.  The composite's own ``warnings`` state, in plain
sentences, that it is only as complete as its weakest component and which
component is degraded and why - derived from the real component statuses and
coverage reasons, never from a hardcoded component name.

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

# The composite is only as complete as its weakest component.  Two machine facts
# describe that: ``data_status`` (was there measured data?) and the coverage
# vocabulary (was every named universe actually covered?).
COMPOSITE_WEAKNESS_POLICY = (
    "The composite is only as complete as its weakest component; the section "
    "coverage status below describes the promoted component's own universe only."
)

# Machine reason -> plain sentence.  A warning must read as something a human can
# act on, so every ``coverage_status_reason`` this module emits gets a gloss.
# Keys are the exact tokens produced by the component coverage functions above;
# an unrecognized token is quoted verbatim rather than dropped or invented.
_COVERAGE_REASON_PROSE: Dict[str, str] = {
    "market_wide_aggregate_has_no_ticker_universe": (
        "ticker coverage does not apply to it and no portfolio weight was "
        "renormalized for it"
    ),
    "no_requested_symbol_had_usable_delivery_history": (
        "no requested symbol had a stored delivery history in the ingested NSE "
        "bhavcopy records"
    ),
    "requested_symbols_without_usable_delivery_history": (
        "the requested symbols had no stored delivery history in the ingested "
        "NSE bhavcopy records"
    ),
    "delivery_symbol_universe_not_reported_by_the_source": (
        "the source published no symbol universe for it, so its coverage is unmeasured"
    ),
    "every_requested_symbol_has_usable_delivery_history": (
        "every requested symbol had a usable stored delivery history"
    ),
    "every_portfolio_position_had_price_history": (
        "every portfolio position had usable price history"
    ),
    "portfolio_positions_without_price_history": (
        "some portfolio positions had no usable price history"
    ),
    "no_portfolio_position_had_price_history": (
        "no portfolio position had usable price history"
    ),
    "liquidity_universe_not_reported_by_the_source": (
        "the source published no universe for it, so its coverage is unmeasured"
    ),
}

# How each scope reads in a sentence, so a market-wide aggregate is never
# described as though it had been measured over a ticker roster.
_SCOPE_PROSE: Dict[str, str] = {
    SCOPE_MARKET_WIDE: (
        "it is a market-wide aggregate measured over the whole market and has no "
        "ticker universe"
    ),
    SCOPE_SYMBOL_SCOPED: "it is measured symbol-scoped over the requested scrip roster",
    SCOPE_PORTFOLIO_POSITIONS: "it is measured over portfolio positions",
}


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


def normalize_coverage_status(value: Any) -> str:
    """Map a declared coverage word onto the coverage vocabulary.

    An unrecognized or absent declaration resolves to ``unknown``: a universe
    that never said it was covered is unmeasured, not covered.  A data_status
    word is deliberately *not* aliased onto a coverage word - ``available`` data
    is not ``complete`` coverage.
    """
    if not isinstance(value, str):
        return "unknown"
    text = value.strip().lower()
    return text if text in COVERAGE_STATUS_VOCABULARY else "unknown"


def aggregate_coverage_status(statuses: Sequence[str]) -> str:
    """The composite's own coverage: complete only when every component is.

    A heterogeneous composite is ``complete`` only when every component reported
    ``complete``; otherwise it is ``partial`` as soon as at least one component
    measured a universe, ``unavailable`` when nothing was measured and a leg is
    known to be unavailable, and ``unknown`` when nothing was measured at all.
    """
    values = [normalize_coverage_status(status) for status in statuses if status]
    if not values:
        return "unknown"
    if all(status == "complete" for status in values):
        return "complete"
    if any(status in {"complete", "partial"} for status in values):
        return "partial"
    if any(status == "unavailable" for status in values):
        return "unavailable"
    return "unknown"


def _coverage_status_detail(component_coverage: Mapping[str, Any]) -> List[str]:
    """``name=status (reason)`` for every component that is not fully covered."""
    detail: List[str] = []
    for name in INDIA_COMPONENTS:
        block = _as_mapping(component_coverage.get(name))
        status = normalize_coverage_status(block.get("coverage_status"))
        if status == "complete":
            continue
        reason = str(block.get("coverage_status_reason") or "").strip()
        detail.append(f"{name}={status}" + (f" ({reason})" if reason else ""))
    return detail


def composite_coverage(component_coverage: Mapping[str, Any]) -> Dict[str, Any]:
    """Composite-scoped coverage status, machine reason, and per-component detail.

    Returned in published component order so repeated exports are identical.
    """
    statuses = [
        normalize_coverage_status(_as_mapping(component_coverage.get(name)).get("coverage_status"))
        for name in INDIA_COMPONENTS
    ]
    status = aggregate_coverage_status(statuses)
    detail = _coverage_status_detail(component_coverage)
    reason = (
        "every_named_component_reported_complete_coverage"
        if status == "complete"
        else "not_every_named_component_reported_complete_coverage: " + "; ".join(detail)
    )
    return {"status": status, "reason": reason, "detail": detail}


def _reason_prose(coverage: Mapping[str, Any]) -> str:
    """Gloss a component's machine coverage reason as a plain sentence."""
    token = str(coverage.get("coverage_status_reason") or "").strip()
    if not token:
        return "the source reported no coverage reason for it"
    return _COVERAGE_REASON_PROSE.get(token, f"its reported coverage reason is {token!r}")


def _coverage_counts_prose(coverage: Mapping[str, Any]) -> str:
    """Measured coverage counts, when the component reported a universe."""
    requested = coverage.get("requested_count")
    covered = coverage.get("covered_count")
    if not isinstance(requested, int) or not isinstance(covered, int):
        return ""
    return f" ({covered} of {requested} in its universe were covered)"


def _coverage_claims_no_gap(coverage: Mapping[str, Any]) -> bool:
    """Whether a component's own coverage reason asserts zero missing coverage.

    Read off the reason token this module emits for a gap-free universe
    (``every_...``); an unrecognised or absent token claims nothing.
    """
    token = str(coverage.get("coverage_status_reason") or "").strip()
    return token.startswith("every_")


def _component_measurement_clause(status: str, coverage: Mapping[str, Any]) -> str:
    """Why this component is short, without ever upgrading an unavailable leg.

    A component that published no measurement cannot be excused by a coverage
    block that reports no gap, so that disagreement is stated rather than
    smoothed over.
    """
    if status == "unavailable" and _coverage_claims_no_gap(coverage):
        return (
            "the component published no measurement, so its coverage block reporting no "
            f"gap ({coverage.get('coverage_status_reason')}) does not mean any "
            "observation is available"
        )
    if status == "partial" and _coverage_claims_no_gap(coverage):
        return (
            "the component published only partial data, so its coverage block reporting "
            f"no gap ({coverage.get('coverage_status_reason')}) does not mean every "
            "observation is available"
        )
    if status == "unavailable":
        return f"no measurement was published; {_reason_prose(coverage)}"
    if status == "partial":
        return f"only partial data was published; {_reason_prose(coverage)}"
    return f"{_reason_prose(coverage)}{_coverage_counts_prose(coverage)}"


def _component_warning(name: str, status: str, coverage: Mapping[str, Any]) -> str:
    """One sentence naming a degraded component, its scope, and why it is short."""
    scope = str(coverage.get("scope") or "").strip()
    scope_prose = _SCOPE_PROSE.get(
        scope, "the source reported no scope for it, so its universe is unstated"
    )
    return (
        f"{name} is {status}: {scope_prose}; "
        f"{_component_measurement_clause(status, coverage)}."
    )


def composite_warnings(
    *,
    component_status: Mapping[str, Any],
    component_coverage: Mapping[str, Any],
    composite_coverage_detail: Sequence[str],
) -> List[str]:
    """Plain, deterministic statements about what the composite is missing.

    Every clause is derived from the component's own ``data_status`` and from the
    coverage status/reason it published; no component name or reason is written
    into this function.  Per-component lines appear only for a degraded leg, so a
    section whose components all measured data carries no defect line - but the
    composite-coverage line survives as long as any leg's coverage is not
    ``complete``, which is always true while the market-wide flow leg has no
    ticker universe by construction.
    """
    warnings: List[str] = []
    statuses = {
        name: normalize_data_status(component_status.get(name)) for name in INDIA_COMPONENTS
    }
    degraded = [name for name in INDIA_COMPONENTS if statuses[name] != "available"]
    if degraded:
        detail = ", ".join(f"{name}={statuses[name]}" for name in degraded)
        warnings.append(
            "Composite data status is only as complete as its weakest component: "
            f"{aggregate_data_status([statuses[name] for name in INDIA_COMPONENTS])}; "
            f"degraded components ({len(degraded)} of {len(INDIA_COMPONENTS)}): {detail}."
        )
        for name in degraded:
            warnings.append(
                _component_warning(name, statuses[name], _as_mapping(component_coverage.get(name)))
            )
    if composite_coverage_detail:
        warnings.append(
            "Composite coverage is only as complete as its weakest component: "
            + "; ".join(composite_coverage_detail)
            + "."
        )
    return warnings


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
    composite: Mapping[str, Any],
) -> Dict[str, Any]:
    """Promote the nested liquidity coverage for the section-level block.

    The promotion is explicit about its origin so a consumer cannot mistake it
    for flow or delivery ticker coverage.  An unavailable liquidity component
    stays unavailable - the context roster is never substituted as coverage.

    ``status``/``complete``/``coverage_ratio`` keep describing the promoted
    component's own universe; the composite-scoped fields say how far that
    status actually reaches, so a heterogeneous composite is never read as
    universally covered from those two keys alone.
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
    # The promoted status describes the promoted component's universe and nothing
    # else, so name that universe and publish the composite's own coverage next
    # to it rather than letting `complete` stand in for the whole section.
    covers_components = [LIQUIDITY_LIMITS]
    promoted.update({
        "source_component": LIQUIDITY_LIMITS,
        "scope": SCOPE_PORTFOLIO_POSITIONS,
        "coverage_semantics": (
            "Price-history coverage of portfolio positions, measured by the "
            "liquidity_limits component only."
        ),
        "coverage_completeness_scope": LIQUIDITY_LIMITS,
        "covers_components": covers_components,
        "not_applicable_components": [
            name for name in INDIA_COMPONENTS if name not in covers_components
        ],
        "composite_coverage_status": str(composite.get("status") or "unknown"),
        "composite_coverage_status_reason": str(composite.get("reason") or ""),
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
        ``as_of``/``as_of_semantics``, ``universe_coverage``, ``data_status``,
        the composite-scoped ``coverage_status``, and ``warnings`` naming every
        degraded component and why.
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

    component_coverage: Dict[str, Any] = {
        INSTITUTIONAL_FLOWS: flow_coverage,
        DELIVERY_ANOMALIES: delivery_coverage,
        LIQUIDITY_LIMITS: liquidity_coverage,
    }
    component_status: Dict[str, str] = {
        INSTITUTIONAL_FLOWS: flow_status,
        DELIVERY_ANOMALIES: delivery_status,
        LIQUIDITY_LIMITS: liquidity_status,
    }
    # The composite's own coverage, stated beside the promoted one: the promoted
    # status answers "was this component's universe covered", this one answers
    # "was every component the section names covered".
    composite_cov = composite_coverage(component_coverage)

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
        "coverage_status": composite_cov["status"],
        "component_status": component_status,
        "component_inputs": component_inputs,
        "component_coverage": component_coverage,
        "component_as_of": component_as_of,
        "as_of": as_of,
        "as_of_semantics": as_of_semantics,
        "as_of_note": as_of_note,
        "universe_coverage": _liquidity_universe_coverage(
            liquidity_payload,
            liquidity_coverage_status=str(liquidity_coverage["coverage_status"]),
            fallback_requested=roster,
            composite=composite_cov,
        ),
        "coverage_notes": [
            "Section coverage is the liquidity component's portfolio-position price "
            "history; see component_coverage for the market-wide flow and "
            "symbol-scoped delivery universes.",
            COMPOSITE_WEAKNESS_POLICY,
            _MARKET_WIDE_COVERAGE_POLICY,
        ],
        # A degraded section must say why: without these, a consumer sees a
        # partial composite with no stated reason and a `complete` coverage block
        # covering one of three components.
        "warnings": composite_warnings(
            component_status=component_status,
            component_coverage=component_coverage,
            composite_coverage_detail=composite_cov["detail"],
        ),
    }
    return composite
