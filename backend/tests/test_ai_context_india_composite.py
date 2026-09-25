"""Ticket 08: honest India composite coverage, inputs, and as-of (V3-15).

The India section composes three heterogeneous components:

* market-wide FII/DII flows - no ticker universe, no weight renormalization;
* symbol-scoped delivery anomalies - a requested roster with real gaps;
* portfolio-position liquidity - the only component with ticker coverage.

``compose_india_composite`` is pure: it takes the three component payloads as
plain dicts, so every case here is exercised without a database, a network, or
a provider.  The regression it guards is the v3 artifact's ``status: unknown``
section coverage (while nested liquidity coverage was 14/14) plus a bogus
``weight_basis`` claim, and a composite ``as_of`` that silently borrowed the
portfolio quote date.
"""
from __future__ import annotations

import copy

from app.services.ai_context_india import (
    AS_OF_SEMANTICS,
    COVERAGE_STATUS_VOCABULARY,
    DELIVERY_ANOMALIES,
    INDIA_COMPONENTS,
    INSTITUTIONAL_FLOWS,
    LIQUIDITY_LIMITS,
    SCOPE_MARKET_WIDE,
    SCOPE_PORTFOLIO_POSITIONS,
    SCOPE_SYMBOL_SCOPED,
    aggregate_data_status,
    compose_india_composite,
)
from app.services.india_data_service import LIQUIDITY_ADV_LOOKBACK_SESSIONS

TICKERS = ["SBIN.NS", "TCS.NS", "INFY.NS", "RELIANCE.NS"]
# The delivery component addresses NSE scrip codes (no exchange suffix).
SCRIPS = ["SBIN", "TCS", "INFY", "RELIANCE"]


def _liquidity_payload(*, status="available", coverage_status="complete", as_of="2026-09-24"):
    """4/4-style nested liquidity coverage - the usable nested block."""
    if coverage_status == "complete":
        covered, missing = list(TICKERS), []
    elif coverage_status == "unavailable":
        covered, missing = [], list(TICKERS)
    else:
        covered, missing = [t for t in TICKERS if t != TICKERS[-1]], [TICKERS[-1]]
    return {
        "portfolio_value": 1_000_000.0,
        "currency": "INR",
        "base_currency": "INR",
        "adv_lookback_sessions": LIQUIDITY_ADV_LOOKBACK_SESSIONS,
        "portfolio_weighted_days_to_liquidate_10pct": 0.4,
        "portfolio_amihud_score": 0.0001,
        "data_status": status,
        "latest_observation_date": as_of,
        "positions": [
            {
                "ticker": ticker,
                "position_value": 250_000.0,
                "weight": 0.25,
                "adv_30d_rupees": 90_000_000.0,
                "days_to_liquidate_10pct_adv": 0.28,
                "days_to_liquidate_20pct_adv": 0.14,
                "amihud_illiquidity": 0.0001,
                "liquidity_tier": "HIGHLY_LIQUID",
                "data_status": "available" if ticker in covered else "unavailable",
            }
            for ticker in TICKERS
        ],
        "universe_coverage": {
            "requested_tickers": list(TICKERS),
            "available_tickers": covered,
            "covered_tickers": covered,
            "missing_tickers": missing,
            "requested_count": len(TICKERS),
            "available_count": len(covered),
            "coverage_ratio": round(len(covered) / len(TICKERS), 6),
            "complete": not missing,
            "status": coverage_status,
        },
    }


def _flow_payload(*, status="unavailable", missing_categories=None, as_of=None):
    return {
        "lookback_days": 30,
        "lookback_basis": "stored_trading_sessions",
        "scope": "market_wide",
        "flows": [],
        "count": 0,
        "as_of": as_of,
        "available_categories": [] if missing_categories is None else [
            category for category in ("DII", "FII") if category not in missing_categories
        ],
        "missing_categories": ["FII", "DII"] if missing_categories is None else list(missing_categories),
        "incomplete_dates": [],
        "data_status": status,
    }


def _delivery_payload(
    *,
    status="unavailable",
    anomalies=None,
    requested=None,
    covered=None,
    missing=None,
    as_of=None,
):
    return {
        "lookback_days": 20,
        "sigma_threshold": 2.0,
        "scope": "symbol_scoped",
        "anomalies": list(anomalies or []),
        "count": len(anomalies or []),
        "requested_symbols": list(SCRIPS) if requested is None else list(requested),
        "covered_symbols": list(SCRIPS) if covered is None else list(covered),
        "missing_symbols": [] if missing is None else list(missing),
        "as_of": as_of,
        "data_status": status,
    }


def _compose(**overrides):
    kwargs = {
        "tickers": TICKERS,
        "flows": _flow_payload(),
        "delivery": _delivery_payload(),
        "liquidity": _liquidity_payload(),
    }
    kwargs.update(overrides)
    return compose_india_composite(**kwargs)


# --------------------------------------------------------------------------
# The v3 regression: nested 4/4 liquidity coverage published as `unknown`.
# --------------------------------------------------------------------------
def test_section_coverage_promotes_nested_liquidity_coverage():
    composite = _compose()

    coverage = composite["universe_coverage"]
    assert coverage["status"] == "complete"
    assert coverage["requested_tickers"] == TICKERS
    assert coverage["available_count"] == len(TICKERS)
    # The promotion must be self-describing so it cannot be read as flow or
    # delivery ticker coverage.
    assert coverage["source_component"] == LIQUIDITY_LIMITS
    assert coverage["scope"] == SCOPE_PORTFOLIO_POSITIONS
    assert INSTITUTIONAL_FLOWS in coverage["not_applicable_components"]
    assert DELIVERY_ANOMALIES in coverage["not_applicable_components"]
    assert coverage["status"] in COVERAGE_STATUS_VOCABULARY


def test_no_component_or_section_claims_a_weight_basis():
    composite = _compose()

    # Market-wide flows: no ticker universe, therefore no renormalization.
    flow_coverage = composite["component_coverage"][INSTITUTIONAL_FLOWS]
    assert "weight_basis" not in flow_coverage
    assert flow_coverage["scope"] == SCOPE_MARKET_WIDE
    assert flow_coverage["coverage_status"] == "unknown"
    assert flow_coverage["coverage_status_reason"] == (
        "market_wide_aggregate_has_no_ticker_universe"
    )
    assert flow_coverage["requested_symbols"] is None
    assert flow_coverage["covered_symbols"] is None
    assert flow_coverage["missing_symbols"] is None
    assert "weight_basis" not in composite["universe_coverage"]
    # Portfolio tickers are never injected into a market-wide flow universe.
    assert composite["component_inputs"][INSTITUTIONAL_FLOWS]["symbol_universe"] is None


def test_weight_basis_survives_only_when_the_source_coverage_declared_it():
    liquidity = _liquidity_payload(coverage_status="partial")
    liquidity["universe_coverage"]["weight_basis"] = "active_weights_renormalized"
    composite = _compose(liquidity=liquidity)

    # Declared by the source coverage block -> carried through untouched.
    assert composite["universe_coverage"]["weight_basis"] == "active_weights_renormalized"
    assert composite["universe_coverage"]["status"] == "partial"


# --------------------------------------------------------------------------
# Per-component inputs: scope, lookback, threshold, symbol universe.
# --------------------------------------------------------------------------
def test_component_inputs_declare_scope_lookback_threshold_and_universe():
    composite = _compose()

    inputs = composite["component_inputs"]
    assert set(inputs) == set(INDIA_COMPONENTS)

    flows = inputs[INSTITUTIONAL_FLOWS]
    assert flows["scope"] == SCOPE_MARKET_WIDE
    assert flows["lookback_days"] == 30
    assert flows["symbol_universe"] is None
    assert flows["categories"] == ["FII", "DII"]

    delivery = inputs[DELIVERY_ANOMALIES]
    assert delivery["scope"] == SCOPE_SYMBOL_SCOPED
    assert delivery["lookback_days"] == 20
    assert delivery["sigma_threshold"] == 2.0
    # Delivery is symbol-scoped and names the roster it was actually asked about.
    assert delivery["symbol_universe"] == SCRIPS
    assert delivery["requested_symbol_count"] == 4

    liquidity = inputs[LIQUIDITY_LIMITS]
    assert liquidity["scope"] == SCOPE_PORTFOLIO_POSITIONS
    assert liquidity["lookback_days"] == LIQUIDITY_ADV_LOOKBACK_SESSIONS
    assert liquidity["universe_source"] == "all_portfolio_positions"
    assert liquidity["symbol_universe"] == TICKERS
    assert liquidity["adv_participation_rates"] == [0.10, 0.20]


def test_delivery_component_coverage_reports_real_symbol_gaps():
    composite = _compose(
        delivery=_delivery_payload(
            status="partial",
            anomalies=[
                {
                    "symbol": "TCS",
                    "current_delivery_pct": 70.0,
                    "avg_20d_delivery_pct": 50.0,
                    "z_score": 2.4,
                    "is_anomaly": True,
                    "signal": "ACCUMULATION_SPIKE",
                }
            ],
            covered=["SBIN", "TCS", "INFY"],
            missing=["RELIANCE"],
        )
    )

    coverage = composite["component_coverage"][DELIVERY_ANOMALIES]
    assert coverage["scope"] == SCOPE_SYMBOL_SCOPED
    assert coverage["coverage_status"] == "partial"
    assert coverage["requested_symbols"] == SCRIPS
    assert coverage["covered_symbols"] == ["SBIN", "TCS", "INFY"]
    assert coverage["missing_symbols"] == ["RELIANCE"]
    assert coverage["requested_count"] == 4
    assert coverage["covered_count"] == 3
    assert "weight_basis" not in coverage


def test_delivery_unavailable_when_no_requested_symbol_has_history():
    composite = _compose(
        delivery=_delivery_payload(
            status="unavailable", requested=["SBIN"], covered=[], missing=["SBIN"]
        )
    )

    coverage = composite["component_coverage"][DELIVERY_ANOMALIES]
    assert coverage["coverage_status"] == "unavailable"
    assert coverage["status"] == "unavailable"
    assert coverage["missing_symbols"] == ["SBIN"]


def test_delivery_coverage_is_unknown_when_source_reports_no_universe():
    payload = _delivery_payload(status="unavailable")
    payload.pop("requested_symbols")
    composite = _compose(delivery=payload)

    coverage = composite["component_coverage"][DELIVERY_ANOMALIES]
    assert coverage["coverage_status"] == "unknown"
    # ...and the roster is not invented from the context tickers either.
    assert coverage["requested_symbols"] is None


# --------------------------------------------------------------------------
# as_of: liquidity component only, plus per-component dates.
# --------------------------------------------------------------------------
def test_composite_as_of_is_the_liquidity_observation_date():
    composite = _compose(
        flows=_flow_payload(status="available", as_of="2026-09-22"),
        delivery=_delivery_payload(status="available", as_of="2026-09-23"),
        liquidity=_liquidity_payload(as_of="2026-09-24"),
    )

    assert composite["as_of"] == "2026-09-24"
    assert composite["as_of_semantics"] == AS_OF_SEMANTICS == "liquidity_component_only"
    assert composite["component_as_of"] == {
        INSTITUTIONAL_FLOWS: "2026-09-22",
        DELIVERY_ANOMALIES: "2026-09-23",
        LIQUIDITY_LIMITS: "2026-09-24",
    }
    assert LIQUIDITY_LIMITS in composite["as_of_note"]


def test_composite_as_of_never_borrows_an_older_or_newer_leg():
    # A fresher flow record must not become the section's as_of, and a
    # portfolio quote date is never consulted at all.
    composite = _compose(
        flows=_flow_payload(status="available", as_of="2026-09-25"),
        delivery=_delivery_payload(status="available", as_of="2026-09-25"),
        liquidity=_liquidity_payload(as_of="2026-09-10"),
    )

    assert composite["as_of"] == "2026-09-10"
    assert composite["as_of_semantics"] == AS_OF_SEMANTICS


def test_missing_liquidity_observation_leaves_as_of_unstated():
    composite = _compose(liquidity=_liquidity_payload(as_of=None))

    assert composite["as_of"] is None
    assert composite["as_of_semantics"] is None
    assert "do not provide one" in composite["as_of_note"]


# --------------------------------------------------------------------------
# Composite data_status: aggregation of the three components, never coverage.
# --------------------------------------------------------------------------
def test_data_status_aggregates_component_statuses():
    available = _compose(
        flows=_flow_payload(status="available"),
        delivery=_delivery_payload(status="available"),
        liquidity=_liquidity_payload(status="available"),
    )
    assert available["data_status"] == "available"
    assert available["component_status"] == {
        INSTITUTIONAL_FLOWS: "available",
        DELIVERY_ANOMALIES: "available",
        LIQUIDITY_LIMITS: "available",
    }

    partial = _compose(flows=_flow_payload(status="partial"))
    assert partial["data_status"] == "partial"

    all_missing = _compose(
        flows=_flow_payload(status="unavailable"),
        delivery=_delivery_payload(status="unavailable"),
        liquidity=_liquidity_payload(status="unavailable", coverage_status="unavailable"),
    )
    assert all_missing["data_status"] == "unavailable"


def test_data_status_never_leaks_coverage_vocabulary():
    composite = _compose()

    assert composite["data_status"] in {"available", "partial", "unavailable"}
    for component in composite["component_coverage"].values():
        assert component["status"] in {"available", "partial", "unavailable"}
        assert component["coverage_status"] in COVERAGE_STATUS_VOCABULARY
        assert component["coverage_status"] not in {
            composite["data_status"],
        } or component["coverage_status"] == "complete"


def test_coverage_status_words_are_normalized_out_of_data_status():
    # A sloppy upstream `complete`/`unknown` declaration is a data_status alias,
    # never a published coverage word in the wrong field.
    composite = _compose(
        flows=_flow_payload(status="complete"),
        delivery=_delivery_payload(status="unknown"),
    )

    assert composite["component_status"][INSTITUTIONAL_FLOWS] == "available"
    assert composite["component_status"][DELIVERY_ANOMALIES] == "unavailable"
    assert composite["data_status"] == "partial"


def test_aggregate_data_status_rules():
    assert aggregate_data_status(["available", "available"]) == "available"
    assert aggregate_data_status(["available", "partial"]) == "partial"
    assert aggregate_data_status(["available", "unavailable"]) == "partial"
    assert aggregate_data_status(["unavailable", "unavailable"]) == "unavailable"
    assert aggregate_data_status([]) == "unavailable"


# --------------------------------------------------------------------------
# Missing FII/DII legs and unavailable liquidity stay explicit.
# --------------------------------------------------------------------------
def test_missing_fii_dii_legs_stay_null_and_are_listed():
    flows = _flow_payload(status="partial", missing_categories=["DII"])
    flows["flows"] = [
        {
            "date": "2026-09-22",
            "fii_net_crores": -120.5,
            "dii_net_crores": None,
            "total_net_crores": None,
            "available_categories": ["FII"],
        }
    ]
    composite = _compose(flows=flows)

    coverage = composite["component_coverage"][INSTITUTIONAL_FLOWS]
    assert coverage["available_categories"] == ["FII"]
    assert coverage["missing_categories"] == ["DII"]
    assert "null" in coverage["missing_category_policy"]
    # The raw leg is untouched: no fabricated zero.
    assert composite["components"][INSTITUTIONAL_FLOWS]["data"]["flows"][0]["dii_net_crores"] is None


def test_unavailable_liquidity_never_falls_back_to_context_tickers():
    composite = _compose(
        flows=_flow_payload(status="available"),
        delivery=_delivery_payload(status="available"),
        liquidity=_liquidity_payload(status="unavailable", coverage_status="unavailable"),
    )

    coverage = composite["universe_coverage"]
    assert coverage["status"] == "unavailable"
    assert coverage["covered_tickers"] == []
    assert coverage["available_count"] == 0
    # The requested roster is still described, but nothing claims to be covered.
    assert coverage["requested_tickers"] == TICKERS
    assert "weight_basis" not in coverage
    assert composite["data_status"] == "partial"


def test_missing_liquidity_payload_yields_unavailable_coverage():
    composite = compose_india_composite(
        tickers=TICKERS,
        flows=_flow_payload(),
        delivery=_delivery_payload(),
        liquidity=None,
    )

    coverage = composite["universe_coverage"]
    assert coverage["status"] == "unavailable"
    assert coverage["source_component"] == LIQUIDITY_LIMITS
    assert coverage["covered_tickers"] == []
    assert composite["data_status"] == "unavailable"


# --------------------------------------------------------------------------
# Composition hygiene.
# --------------------------------------------------------------------------
def test_supplied_component_envelopes_are_passed_through_untouched():
    envelopes = {
        INSTITUTIONAL_FLOWS: {"status": "unavailable", "data": {"flows": [], "data_status": "unavailable"}},
        DELIVERY_ANOMALIES: {"status": "partial", "data": {"anomalies": [], "data_status": "partial"}},
        LIQUIDITY_LIMITS: {"status": "available", "data": _liquidity_payload()},
    }
    composite = compose_india_composite(
        tickers=TICKERS,
        flows=_flow_payload(),
        delivery=_delivery_payload(status="partial"),
        liquidity=_liquidity_payload(),
        components=envelopes,
    )

    assert composite["components"] == envelopes
    assert composite["component_status"] == {
        INSTITUTIONAL_FLOWS: "unavailable",
        DELIVERY_ANOMALIES: "partial",
        LIQUIDITY_LIMITS: "available",
    }
    assert composite["data_status"] == "partial"


def test_composition_does_not_mutate_its_inputs():
    flows = _flow_payload()
    delivery = _delivery_payload()
    liquidity = _liquidity_payload()
    before = (copy.deepcopy(flows), copy.deepcopy(delivery), copy.deepcopy(liquidity))

    _compose(flows=flows, delivery=delivery, liquidity=liquidity)

    assert (flows, delivery, liquidity) == before


def test_composite_is_json_serializable_and_deterministic():
    import json

    first = json.dumps(_compose(), sort_keys=True, default=str)
    second = json.dumps(_compose(), sort_keys=True, default=str)
    assert first == second


# --------------------------------------------------------------------------
# Exporter compatibility (read-only): the promotion must survive the section
# envelope the integrator wires this into.
# --------------------------------------------------------------------------
def test_exporter_resolves_as_of_and_coverage_from_the_composite():
    from app.services.ai_context_service import _as_of, _payload_status, _section_coverage

    composite = _compose(
        flows=_flow_payload(status="available", as_of="2026-09-25"),
        delivery=_delivery_payload(status="available", as_of="2026-09-25"),
        liquidity=_liquidity_payload(as_of="2026-09-24"),
    )

    # Freshness: the composite's own declared as_of wins over fresher legs.
    assert _as_of(composite) == "2026-09-24"

    # Section status: the exporter aggregates the same three component statuses.
    assert _payload_status(composite) == composite["data_status"] == "available"

    # Coverage: the exporter merges the requested roster with the promoted
    # liquidity block and must land on complete, not the v3 `unknown`.
    coverage = _section_coverage(
        "india_flows", {"tickers": TICKERS, "flow_lookback_days": 30}, composite
    )
    assert coverage["status"] == "complete"
    assert coverage["available_count"] == len(TICKERS)
    assert coverage["missing_tickers"] == []
    assert coverage["source_component"] == LIQUIDITY_LIMITS
    assert "weight_basis" not in coverage
