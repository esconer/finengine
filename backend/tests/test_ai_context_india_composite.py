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
portfolio quote date.  The v4 export audit added two more: a ``partial``
composite published with ``warnings: []``, and a promoted section coverage
(``status: complete``, 14/14) that read as universal coverage of a composite
whose other two components were unavailable.
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
    aggregate_coverage_status,
    aggregate_data_status,
    compose_india_composite,
    normalize_coverage_status,
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


# --------------------------------------------------------------------------
# v4 audit: a `partial` composite may not ship without a stated reason, and
# the promoted `complete` coverage may not read as coverage of all three legs.
# --------------------------------------------------------------------------
def _degraded_composite(**overrides):
    """The v4 export shape: only the liquidity leg measured anything.

    ``institutional_flows`` is a market-wide aggregate with no ticker universe
    and no stored rows, and no requested symbol has a stored delivery history,
    so both legs are genuinely unavailable - not a degraded measurement.
    """
    kwargs = {
        "flows": _flow_payload(),
        "delivery": _delivery_payload(
            status="unavailable", requested=SCRIPS, covered=[], missing=SCRIPS
        ),
        "liquidity": _liquidity_payload(),
    }
    kwargs.update(overrides)
    return _compose(**kwargs)


def test_degraded_composite_never_publishes_an_empty_warning_list():
    composite = _degraded_composite()

    assert composite["data_status"] == "partial"
    warnings = composite["warnings"]
    assert isinstance(warnings, list) and warnings
    assert all(isinstance(warning, str) and warning.strip() for warning in warnings)
    # The headline states the weakest-component rule in plain language.
    assert "only as complete as its weakest component" in warnings[0]
    assert "degraded components (2 of 3)" in warnings[0]


def test_warnings_name_each_unavailable_component_and_why():
    warnings = _degraded_composite()["warnings"]

    flow_line = next(w for w in warnings if w.startswith(f"{INSTITUTIONAL_FLOWS} is "))
    assert f"{INSTITUTIONAL_FLOWS} is unavailable" in flow_line
    # A market-wide aggregate is never described as having a ticker universe.
    assert "market-wide aggregate" in flow_line
    assert "has no ticker universe" in flow_line
    assert "no portfolio weight was renormalized" in flow_line

    delivery_line = next(w for w in warnings if w.startswith(f"{DELIVERY_ANOMALIES} is "))
    assert f"{DELIVERY_ANOMALIES} is unavailable" in delivery_line
    assert "stored delivery history" in delivery_line
    assert "bhavcopy" in delivery_line

    # The measured liquidity leg is not degraded, so it gets no defect line.
    assert not any(w.startswith(f"{LIQUIDITY_LIMITS} is ") for w in warnings)


def test_warnings_are_derived_from_the_components_not_hardcoded():
    # Degrade a different leg: the same builder must name liquidity, its own
    # reason, and nothing about the two legs that are fine.
    composite = _compose(
        flows=_flow_payload(status="available"),
        delivery=_delivery_payload(status="available"),
        liquidity=_liquidity_payload(status="unavailable", coverage_status="unavailable"),
    )

    warnings = composite["warnings"]
    assert "degraded components (1 of 3): liquidity_limits=unavailable" in warnings[0]
    liquidity_line = next(w for w in warnings if w.startswith(f"{LIQUIDITY_LIMITS} is "))
    assert "portfolio positions" in liquidity_line
    assert "price history" in liquidity_line
    assert not any(w.startswith(f"{INSTITUTIONAL_FLOWS} is ") for w in warnings)
    assert not any(w.startswith(f"{DELIVERY_ANOMALIES} is ") for w in warnings)


def test_warnings_never_upgrade_an_unavailable_leg_with_a_no_gap_coverage():
    # A sloppy upstream can report an unavailable component whose coverage
    # claims zero gaps; the warning must not launder that into "covered".
    composite = _compose(
        flows=_flow_payload(status="available"),
        delivery=_delivery_payload(status="unavailable"),  # covered=SCRIPS, status unavailable
    )

    delivery_line = next(
        w for w in composite["warnings"] if w.startswith(f"{DELIVERY_ANOMALIES} is ")
    )
    assert "published no measurement" in delivery_line
    assert "every_requested_symbol_has_usable_delivery_history" in delivery_line
    assert "does not mean any observation is available" in delivery_line


def test_warnings_are_stable_across_runs_and_published_component_order():
    first = _degraded_composite()["warnings"]
    second = _degraded_composite()["warnings"]

    assert first == second
    component_lines = [w for w in first if " is unavailable:" in w or " is partial:" in w]
    assert [w.split(" is ")[0] for w in component_lines] == [
        INSTITUTIONAL_FLOWS, DELIVERY_ANOMALIES
    ]


def test_measured_components_get_no_defect_warning():
    composite = _compose(
        flows=_flow_payload(status="available"),
        delivery=_delivery_payload(status="available"),
        liquidity=_liquidity_payload(status="available"),
    )

    assert composite["data_status"] == "available"
    # Nothing measured short, so no degraded-component lines at all.  The
    # market-wide flow leg's coverage is `unknown` by construction, so the
    # composite-coverage line is expected to stay (see
    # test_promoted_coverage_carries_a_composite_scoped_status).
    assert not any(" is unavailable:" in w or " is partial:" in w for w in composite["warnings"])
    assert not any("degraded components" in w for w in composite["warnings"])


def test_warnings_never_fabricate_a_missing_fii_dii_leg():
    flows = _flow_payload(status="partial", missing_categories=["DII"])
    flows["flows"] = [{"date": "2026-09-22", "fii_net_crores": -120.5, "dii_net_crores": None}]
    composite = _compose(flows=flows)

    flow_line = next(
        w for w in composite["warnings"] if w.startswith(f"{INSTITUTIONAL_FLOWS} is ")
    )
    assert f"{INSTITUTIONAL_FLOWS} is partial" in flow_line
    # The missing leg is still null, and the warning never reports it as zero.
    assert composite["components"][INSTITUTIONAL_FLOWS]["data"]["flows"][0]["dii_net_crores"] is None
    assert "zero" not in flow_line.lower()


def test_promoted_coverage_carries_a_composite_scoped_status():
    composite = _degraded_composite()

    coverage = composite["universe_coverage"]
    # The promoted status still describes the promoted component's universe...
    assert coverage["status"] == "complete"
    assert coverage["complete"] is True
    # ...and says so, machine-readably, next to the composite's own status.
    assert coverage["covers_components"] == [LIQUIDITY_LIMITS]
    assert coverage["coverage_completeness_scope"] == LIQUIDITY_LIMITS
    assert coverage["not_applicable_components"] == [INSTITUTIONAL_FLOWS, DELIVERY_ANOMALIES]
    assert coverage["composite_coverage_status"] == "partial"
    assert coverage["composite_coverage_status"] in COVERAGE_STATUS_VOCABULARY
    reason = coverage["composite_coverage_status_reason"]
    assert reason.startswith("not_every_named_component_reported_complete_coverage")
    assert f"{INSTITUTIONAL_FLOWS}=unknown" in reason
    assert f"{DELIVERY_ANOMALIES}=unavailable" in reason
    # A consumer reading only the two legacy keys sees the scope fields too.
    assert composite["coverage_status"] == "partial"
    assert composite["coverage_status"] != coverage["status"]


def test_promoted_coverage_is_complete_only_when_every_component_is():
    complete = _compose(
        flows=_flow_payload(status="available"),
        delivery=_delivery_payload(status="available"),
        liquidity=_liquidity_payload(status="available"),
    )["universe_coverage"]
    assert complete["composite_coverage_status"] == "partial"  # flow universe is unknown
    assert complete["composite_coverage_status_reason"] == (
        "not_every_named_component_reported_complete_coverage: "
        "institutional_flows=unknown (market_wide_aggregate_has_no_ticker_universe)"
    )
    # The market-wide leg is still never given a ticker universe or a basis.
    assert "requested_tickers" in complete
    assert "weight_basis" not in complete


def test_promoted_coverage_reports_unavailable_when_no_component_measured():
    composite = compose_india_composite(
        tickers=TICKERS,
        flows=_flow_payload(),
        delivery=_delivery_payload(status="unavailable", requested=SCRIPS, covered=[], missing=SCRIPS),
        liquidity=None,
    )

    coverage = composite["universe_coverage"]
    assert coverage["status"] == "unavailable"
    # The promoted status still refers to the liquidity universe, and the
    # composite's own status is the weakest of the three.
    assert coverage["covers_components"] == [LIQUIDITY_LIMITS]
    assert coverage["composite_coverage_status"] == "unavailable"
    assert composite["coverage_status"] == "unavailable"
    assert composite["warnings"]


def test_exporter_keeps_the_scoped_coverage_fields_next_to_a_complete_status():
    from app.services.ai_context_service import _section_coverage

    composite = _degraded_composite()
    coverage = _section_coverage(
        "india_flows", {"tickers": TICKERS, "flow_lookback_days": 30}, composite
    )

    # The exporter recomputes the ticker math of the promoted universe...
    assert coverage["status"] == "complete"
    assert coverage["complete"] is True
    # ...and the composite scope survives that recompute, so `complete` cannot
    # be read as coverage of the two legs that measured nothing.
    assert coverage["covers_components"] == [LIQUIDITY_LIMITS]
    assert coverage["coverage_completeness_scope"] == LIQUIDITY_LIMITS
    assert coverage["composite_coverage_status"] == "partial"
    assert coverage["not_applicable_components"] == [INSTITUTIONAL_FLOWS, DELIVERY_ANOMALIES]
    assert "weight_basis" not in coverage
    # The warnings travel with the section data, so the section reports them.
    assert composite["warnings"]


def test_coverage_status_vocabulary_rules():
    assert aggregate_coverage_status(["complete", "complete", "complete"]) == "complete"
    assert aggregate_coverage_status(["complete", "unknown"]) == "partial"
    assert aggregate_coverage_status(["partial", "complete"]) == "partial"
    assert aggregate_coverage_status(["unavailable", "unavailable", "unknown"]) == "unavailable"
    assert aggregate_coverage_status(["unknown", "unknown"]) == "unknown"
    assert aggregate_coverage_status([]) == "unknown"
    for status in aggregate_coverage_status(["complete"]), aggregate_coverage_status(["nonsense"]):
        assert status in COVERAGE_STATUS_VOCABULARY
    # A data_status word is never promoted onto a coverage word.
    assert normalize_coverage_status("available") == "unknown"
    assert normalize_coverage_status("Complete") == "complete"
    assert normalize_coverage_status(None) == "unknown"
