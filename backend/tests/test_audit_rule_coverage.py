"""Does the 57-rule audit gate CATCH wrong numbers, or only self-consistent ones?

`57/57` is a consistency signal, not a correctness one.  A perfectly
self-consistent export of entirely wrong numbers passes all 57 rules, because
every rule in the table is an identity between two published fields or a
disclosure obligation -- never a check that a field is the *right* number.  The
gate proves the export does not contradict itself.  It does not prove the
numbers are right, and `overall_score` moving 12.8 -> 13.0 -> 13.1 across three
exports as the cache refreshed demonstrates the second point better than any
argument: a risk model on a moving portfolio cannot show progress against
anything.

The one measurement here that has a fixed point is therefore mutation
coverage.  For each of the sections in ``SECTION_CATALOG``, corrupt one leaf
value in a way a consumer would act on, run all 57 rules, and record which ones
fired.  A rule that never fires on injected-wrong data is decoration.  This file
is that measurement, and it is a gate: it exits non-zero when a section's
injected error is caught by zero rules, naming the section and the class.

The precondition that decides whether the numbers mean anything is that a
mutation must not disturb the envelope.  If a mutation made the document
schema-invalid, the 21 envelope rules would fire on every corrupted export and
"this rule never fires" would become a false conclusion.  So every mutation here
writes ONE leaf inside ``sections.<key>.data`` and nothing else, and
``test_every_mutation_touches_only_section_data`` proves it byte for byte
against the base document: the envelope, and every section's own
``status``/``coverage``/``as_of``/``warnings`` scaffolding, must be identical
after the mutation.

A mutation is also required to be PLAUSIBLE -- a value no real system would
emit is caught by a substring check and teaches nothing.  Every injected value
below is either a digit transposed, a unit flipped (fraction published as a
percentage), two fields that should close left apart, or a label that
contradicts the number beside it.

Verdicts, and why they are three and not one:

  * a rule in ``expects`` fired                      -> the right class was caught
  * some rule fired but none in ``expects``          -> COLLATERAL: a rule that
    fires for a different reason, which is weaker than a hit and stronger than
    nothing
  * no rule fired                                    -> UNCOVERED: a gap

Both of the latter two are frozen sets, and both are asserted.  Adding a rule
that closes a gap makes this file go red with "gap closed, update the frozen
set" rather than silently improving a number nobody reads.  That asymmetry is
deliberate: a coverage harness that quietly reports better coverage after a
rule is added has stopped measuring.

Base document: a real, complete, schema-valid export of every section in the
catalog under the temp directory, named :data:`BASE_EXPORT` below.  Navigate it
with Python; never dump it.

Read-only on purpose.  ``app/debugging/context_audit.py`` is parent-owned; when
a mutation below is UNCOVERED the rule it wants is written up in the report that
accompanies this file rather than added to the table, because a rule added while
measuring the table is indistinguishable from a rule added to silence it.
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import numpy as np

from app.debugging import context_audit as ca
from app.services.ai_context_service import SECTION_CATALOG

#: The reference export this measurement is taken against: a real, complete,
#: schema-valid export of every section in the catalog, 0 unavailable.
BASE_EXPORT = Path(r"C:\Users\Sayanti\AppData\Local\Temp\opencode\v27.json")

#: Sentinel for "remove this key".  A key REMOVED is as schema-valid as a key
#: changed, and a dropped disclosure is a real defect class, so deletions are
#: in scope; the envelope-integrity test still holds because the key being
#: removed is inside ``data``.
DELETE = object()

#: Keys of a section that are scaffolding rather than payload.  A mutation that
#: touched one of these would be changing the envelope, not the data.
SECTION_SCAFFOLD_KEYS = frozenset(
    {
        "key", "title", "route", "status", "detail", "generated_at", "as_of",
        "as_of_semantics", "currency", "inputs", "coverage", "omitted_fields",
        "warnings",
    }
)


@dataclass(frozen=True)
class Mutation:
    """One injected defect: a section, an error class, and the writes that cause it.

    ``expects`` names the rules that SHOULD catch this class.  An empty tuple is
    a claim that no rule targets the class, and the mutation is then either in
    :data:`KNOWN_UNCOVERED` (nothing fired) or :data:`KNOWN_COLLATERAL`
    (something else fired) -- both asserted, neither silently tolerated.
    """

    section: str
    cls: str
    writes: tuple[tuple[tuple[Any, ...], Any], ...]
    expects: tuple[str, ...] = ()
    note: str = ""


# --------------------------------------------------------------------------
# The mutation set
# --------------------------------------------------------------------------
#: centre * 0.8 / centre * 1.2, written out because the whole point of the
#: SI-3 defect is that the endpoints are the centre times a round constant.
_FC_CENTRE = 0.09607232695819766
_RR_VAR_LO, _RR_VAR_HI = -0.015101, -0.010981
_RR_VAR_CENTRE = (_RR_VAR_LO + _RR_VAR_HI) / 2.0

MUTATIONS: tuple[Mutation, ...] = (
    # ---- portfolio -------------------------------------------------------
    Mutation(
        "portfolio", "total_does_not_equal_sum_of_parts",
        ((( "total_value",), 42598.20),),
        ("NUM-001",),
        "total_value 42598.2 against sum(market_value) 42624.5: a stale total "
        "carried across a partial re-mark, off by one session's move.",
    ),
    Mutation(
        "portfolio", "weight_published_as_percentage",
        ((("positions", 0, "weight"), 6.4718),),
        ("NUM-001",),
        "weight 0.0647 emitted as 6.4718: the fraction/percent flip. Caught, but "
        "as a sum(weight)!=1 failure, not as a unit error.",
    ),
    Mutation(
        "portfolio", "position_count_does_not_match_its_list",
        ((("total_positions",), 13),),
        (),
        "total_positions 13 against 14 rows in positions[]: a count that does "
        "not describe its own list. No rule reads it.",
    ),
    Mutation(
        "portfolio", "sector_weights_do_not_sum_to_position_weights",
        ((("sectors", "Healthcare"), 0.1647),),
        (),
        "sectors.Healthcare 0.1647 against the position-level 0.0647 it "
        "aggregates. No rule reconciles the two views of the same number.",
    ),

    # ---- dashboard --------------------------------------------------------
    Mutation(
        "dashboard", "component_as_of_contradicts_the_sections_own_semantics",
        ((("component_as_of", "summary", "as_of"), "2026-10-06"),),
        (),
        "the section declares as_of_semantics 'oldest_component_observation' at "
        "2026-09-25 while a component claims 2026-10-06, a date after the "
        "export's own completed_at. No rule orders component_as_of against the "
        "section clock or against each other.",
    ),
    Mutation(
        "dashboard", "component_reference_pointer_names_the_wrong_section",
        ((("components", "portfolio", "data_ref"), "sections.risk_studio"),),
        (),
        "the component map promises 'sections.portfolio' and points at "
        "sections.risk_studio. The pointer is the whole mechanism after the "
        "byte-for-byte inline payloads were removed, and nothing resolves it.",
    ),
    Mutation(
        "dashboard", "warm_up_row_relabelled_as_an_observation",
        (
            (("components", "performance_history", "data", 0, "return"), 0.0184),
            (("components", "performance_history", "data", 0, "warm_up"), DELETE),
            (("components", "performance_history", "data", 0, "warm_up_reason"), DELETE),
        ),
        ("NUM-019",),
        "row 0 loses its warm-up marker and publishes a return derived from a "
        "prior portfolio value that was never delivered. The marker has to be "
        "DELETED, not set false: NUM-019's _is_flagged is key-based, so a "
        "`warm_up: false` still reads as flagged.",
    ),
    Mutation(
        "dashboard", "newest_row_has_no_benchmark_point",
        ((("components", "performance_history", "data", 22, "benchmark_value"), None),),
        ("NUM-019",),
        "the newest observation drops its benchmark, which is the one row a "
        "reader compares against.",
    ),
    Mutation(
        "dashboard", "short_window_reported_as_available",
        ((("components", "performance_history", "status"), "available"),),
        ("NUM-020",),
        "performance_history delivers 35% of its requested days and says "
        "'available'.",
    ),
    Mutation(
        "dashboard", "return_series_breadth_aggregate_removed",
        (
            (("components", "performance_history", "constituent_count"), DELETE),
            (("components", "performance_history", "partial_basket_policy"), DELETE),
            (("components", "performance_history", "constituent_count_basis"), DELETE),
        ),
        ("NUM-021",),
        "the only breadth disclosure in the document is deleted from a return "
        "series that renormalises the surviving weights on every date.",
    ),
    Mutation(
        "dashboard", "unmeasured_sub_score_floored_to_zero",
        ((("components", "risk_score", "data", "components", "volatility"), 0.0),),
        ("NUM-018",),
        "the volatility sub-score is floored to a hard 0 while "
        "excluded_components is empty and the component publishes no "
        "measurement behind that leg. The D-04 defect. (`correlation` is "
        "deliberately NOT used here: _SUB_SCORE_EVIDENCE already publishes "
        "avg_pairwise_correlation beside it, so a hard 0 there is a measured "
        "zero and the rule is right to stay quiet -- see the "
        "correlation_floor_is_a_measured_zero mutation.)",
    ),
    Mutation(
        "dashboard", "correlation_floor_is_a_measured_zero",
        ((("components", "risk_score", "data", "components", "correlation"), 0.0),),
        (),
        "the same floor applied to the ONE sub-score the evidence registry "
        "covers. NUM-018 correctly declines, because the component publishes "
        "avg_pairwise_correlation 0.1241 beside it. Listed so the table shows "
        "the registry is load-bearing: adding a key to _SUB_SCORE_EVIDENCE "
        "silences this rule, which is why that registry is not touched by this "
        "harness.",
    ),

    # ---- realized_risk ----------------------------------------------------
    Mutation(
        "realized_risk", "expected_shortfall_better_than_the_var_it_derives_from",
        ((("portfolio", "cvar_95"), -0.0051),),
        ("NUM-026",),
        "cvar_95 -0.0051 against var_95 -0.00643: the tail mean is less bad "
        "than the quantile it is the mean of. Mathematically impossible, and "
        "no rule compares the two.",
    ),
    Mutation(
        "realized_risk", "var_published_as_percentage",
        ((("portfolio", "var_95"), -0.643209),),
        (),
        "var_95 -0.00643 emitted as -0.643209: a 100x unit slip in a loss sign "
        "convention, published beside a bootstrap interval in the same block "
        "that is still on the fraction scale.",
    ),
    Mutation(
        "realized_risk", "confidence_interval_is_a_fixed_band",
        (
            (("positions", "CIPLA.NS", "estimate_uncertainty", "estimates",
              "var_95", "conf_int"),
             [_RR_VAR_CENTRE * 1.2, _RR_VAR_CENTRE * 0.8]),
        ),
        (),
        "THE BIGGEST BLIND SPOT IN THE TABLE. The export publishes 244 "
        "intervals under the key `conf_int`; NUM-022 matches its intervals on "
        "INTERVAL_KEY_TOKENS = ('confidence_interval', 'interval', '_ci', "
        "'ci_'), and 'conf_int' contains none of them. The rule written "
        "specifically to catch a hardcoded +/-20% band is therefore blind to "
        "every interval the system actually emits, and only reaches the two it "
        "would recognise by name. The rule IS live -- see "
        "forecast_risk/confidence_interval_is_a_fixed_band -- so this is a "
        "key-name mismatch, not a broken rule.",
    ),
    Mutation(
        "realized_risk", "interval_broader_than_its_own_estimate",
        (
            (("positions", "CIPLA.NS", "estimate_uncertainty", "estimates",
              "var_95", "conf_int"),
             [-0.015101, -0.010981]),
            (("positions", "CIPLA.NS", "estimate_uncertainty", "estimates",
              "var_95", "point_estimate"), -0.0002),
        ),
        (),
        "a point estimate published far outside its own published interval: "
        "the estimate is -0.0002 while the interval runs -0.0151..-0.0110. "
        "NUM-022 only rejects a CONSTANT band; it never checks that an "
        "interval contains the estimate it is an interval of.",
    ),
    Mutation(
        "realized_risk", "covered_days_disagrees_with_every_sibling",
        ((("history_coverage", "covered_days"), 39),),
        ("XS-001",),
        "the holding-window pool is 22 days in tear_sheet, regime and the "
        "dashboard; realized_risk says 39.",
    ),
    Mutation(
        "realized_risk", "count_published_without_a_scope",
        ((("history_coverage", "covered_days_scope"), "  "),),
        ("XS-002",),
        "a bare count with a whitespace scope.",
    ),
    Mutation(
        "realized_risk", "inferred_start_no_longer_names_what_it_displaced",
        ((("history_coverage", "inferred_start_tickers"), DELETE),),
        ("XS-003",),
        "effective_start_source stays 'buy_price_inferred' but the four tickers "
        "the inference displaced are no longer named, and the node publishes no "
        "stored_added_on to fall back on.",
    ),
    Mutation(
        "realized_risk", "start_contradicts_the_stored_date_it_claims",
        ((("history_coverage", "tickers", "ARROWGREEN.NS", "analytics_start"), "2025-11-04"),),
        ("XS-004",),
        "ARROWGREEN.NS declares analytics_start_source 'stored_added_on' with "
        "stored_added_on 2025-08-20 beside it, and now dates its own analytics "
        "start three months later than the date it says it came from.",
    ),
    Mutation(
        "realized_risk", "per_ticker_counts_left_in_mixed_units",
        ((("history_coverage", "per_ticker_count_units"), DELETE),),
        ("XS-005",),
        "the D-02 defect: the block stops saying which frame each per-ticker "
        "count is measured over, leaving raw_days 175, masked_days 42 and "
        "return_observations 41 -- counts 92 apart that no single row frame "
        "explains.",
    ),

    # ---- forecast_risk ----------------------------------------------------
    Mutation(
        "forecast_risk", "volatility_published_as_percentage",
        ((("portfolio", "volatility_forecast"), 9.6072326),),
        (),
        "volatility_forecast 0.0961 emitted as 9.607: annualized sigma 961%.",
    ),
    Mutation(
        "forecast_risk", "confidence_interval_is_a_fixed_band",
        ((("portfolio", "confidence_interval"),
          [_FC_CENTRE * 0.8, _FC_CENTRE * 1.2]),),
        ("NUM-022",),
        "the field whose own companion key says "
        "confidence_interval_status='not_computed' is filled with the +/-20% "
        "band the v5 review found hardcoded.",
    ),
    Mutation(
        "forecast_risk", "horizon_label_contradicts_the_horizon_beside_it",
        ((("horizon",), 21),),
        (),
        "data.horizon 21 against model_params.tail_measure.var_horizon_days 1 "
        "in the same payload: a 21-day VaR published beside a 1-day one.",
    ),
    Mutation(
        "forecast_risk", "model_declared_does_not_match_the_model_fitted",
        ((("model",), "EGARCH"),),
        (),
        "model 'EGARCH' beside model_params.type 'GARCH'. Both are in the "
        "allowed vocabulary, so no vocabulary rule can see it.",
    ),

    # ---- factor_exposure --------------------------------------------------
    Mutation(
        "factor_exposure", "adjusted_r_squared_exceeds_r_squared",
        ((("adjusted_r_squared",), 0.75),),
        (),
        "adj R2 0.75 > R2 0.7051, which no least-squares fit can produce. "
        "XS-009 fires, but only because the two figures now read as two "
        "competing fits -- a collateral catch, not the arithmetic one.",
    ),
    Mutation(
        "factor_exposure", "r_squared_above_one",
        ((("r_squared",), 1.0731),),
        (),
        "R2 > 1 is impossible for a fit with an intercept. Same collateral "
        "XS-009 catch as above.",
    ),
    Mutation(
        "factor_exposure", "fit_window_contradicts_its_observation_count",
        ((("model_window", "days"), 251),),
        (),
        "model_window.days 251 while history_coverage and full_history both "
        "say 174 observations over the same start/end.",
    ),

    # ---- concentration ----------------------------------------------------
    Mutation(
        "concentration", "score_published_as_fraction",
        ((("diversification_score",), 0.985),),
        (),
        "diversification_score 98.5 emitted as 0.985 while the "
        "diversification_score_formula string published in the SAME block says "
        "'* 100'.",
    ),
    Mutation(
        "concentration", "effective_positions_contradicts_its_own_hhi",
        ((("effective_positions",), 9.8),),
        ("NUM-026",),
        "N_eff = 1/HHI = 1/0.0856 = 11.68; the block publishes 9.8. The "
        "project's own CONTEXT invariant states N_eff = 1/HHI, and the block "
        "prints that formula nowhere, so nothing checks it.",
    ),
    Mutation(
        "concentration", "sector_total_does_not_equal_the_sum_of_its_parts",
        ((("by_sector_published_total",), 0.9998),),
        ("NUM-002",),
        "the published total and the rounding residual both disagree with the "
        "seven sector weights printed beside them.",
    ),
    Mutation(
        "concentration", "top_3_does_not_match_the_position_weights",
        ((("top_3",), 0.8765),),
        (),
        "the published top-3 concentration is not reproducible from the "
        "positions the portfolio section publishes for the same book.",
    ),

    # ---- liquidity --------------------------------------------------------
    Mutation(
        "liquidity", "band_contradicts_its_own_score",
        ((("by_position", "CIPLA.NS", "score"), 5.4),),
        ("NUM-004",),
        "score 5.4 with category 'High' under the section's own band table.",
    ),
    Mutation(
        "liquidity", "liquidation_window_contradicts_its_own_band",
        ((("liquidation_time_days",), "5-10"),),
        (),
        "the headline liquidation window is '5-10' while overall_band 'High' "
        "carries liquidation_days '1-2' in the band's own row.",
    ),
    Mutation(
        "liquidity", "estimated_market_cap_count_understated",
        ((("estimated_market_cap_count",), 1),),
        (),
        "1 of 14 market caps disclosed as estimated while 5 rows carry "
        "market_cap_provenance != 'measured' and the warning names all five.",
    ),
    Mutation(
        "liquidity", "unavailable_result_publishes_a_plausible_mid_score",
        ((("data_status",), "unavailable"),),
        ("NUM-005",),
        "data_status 'unavailable' with overall_score 8.0 still standing. The "
        "section-level status stays 'partial' and its warnings are unchanged, "
        "so this is a payload leaf and not a scaffolding edit.",
    ),
    Mutation(
        "liquidity", "clean_score_over_undisclosed_estimated_inputs",
        (
            (("data_status",), "available"),
            (("estimated_market_cap_count",), 1),
        ),
        ("NUM-006",),
        "the D-03 defect: the section declares itself available and "
        "understates the estimated market caps at 1 of 5. (NUM-006's escape is "
        "`status == partial and warned`, which the honest export takes, so both "
        "halves of the defect have to move together to reach the rule.)",
    ),

    # ---- stress_testing ---------------------------------------------------
    Mutation(
        "stress_testing", "drawdown_breaks_its_own_identity",
        ((("scenarios", "Market Crash", "max_drawdown"), -0.4728),),
        ("NUM-007",),
        "max_drawdown restated as the raw impact, dropping the 1.15 shock "
        "multiplier that max_drawdown_formula publishes in the same row.",
    ),
    Mutation(
        "stress_testing", "drawdown_basis_withheld",
        ((("scenarios", "Market Crash", "max_drawdown_basis"), "  "),),
        ("NUM-007",),
        "the second arm of NUM-007: a drawdown with no declared basis.",
    ),
    Mutation(
        "stress_testing", "as_of_contradicts_the_scenario_dates_beside_it",
        ((("as_of",), "2026-09-27"),),
        (),
        "as_of_semantics says 'oldest_scenario_latest_observation_date' and "
        "all four scenario_observation_dates are 2026-09-29, but as_of is "
        "2026-09-27. STRESS_AS_OF_SEMANTICS is a published constant in the "
        "exporter and no rule enforces it.",
    ),
    Mutation(
        "stress_testing", "degradation_published_with_no_warning",
        ((("block_reason",), "one scenario's factor loadings were unavailable"),
         ),
        ("ENV-016",),
        "the section header carries warnings: [] and the payload now names a "
        "block reason. A degradation the header does not mention.",
    ),

    # ---- volatility_sizing ------------------------------------------------
    Mutation(
        "volatility_sizing", "achieved_value_restates_its_own_target",
        ((("achieved_volatility",), 0.15),),
        ("NUM-023",),
        "achieved_volatility == target_volatility to the bit beside a "
        "published scale_factor: the QM-4 restatement.",
    ),
    Mutation(
        "volatility_sizing", "trade_amount_does_not_reconcile_to_its_legs",
        ((("trades", "CIPLA.NS", "shares_delta"), 3),),
        ("NUM-008",),
        "shares_delta 3 against an amount still priced off 2 shares.",
    ),
    Mutation(
        "volatility_sizing", "sub_lot_trade_rounded_to_zero_shares",
        ((("trades", "CIPLA.NS", "shares_delta"), 0),),
        ("NUM-009",),
        "shares_delta 0 with the 2483.36 notional preserved and no "
        "sub-lot status.",
    ),
    Mutation(
        "volatility_sizing", "published_maximum_is_really_a_minimum",
        ((("trade_reconciliation", "max_abs_rounding_residual"), 316.04),),
        ("NUM-010",),
        "the min-in-a-max bug: 316.04 published as the maximum residual.",
    ),
    Mutation(
        "volatility_sizing", "financing_requirement_contradicts_its_fraction",
        ((("exposure", "financing_requirement"), 11250.0),),
        (),
        "financing_requirement 11250.0 against financing_fraction 0.217796 of "
        "portfolio_value 42624.5, which is 9283.45. NUM-012 reads the "
        "optimizer's weight_normalization, not this block.",
    ),
    Mutation(
        "volatility_sizing", "current_volatility_is_not_the_volatility_used",
        ((("current_volatility",), 0.1475377059530436),),
        (),
        "current_volatility 0.1475 is published beside sizing_volatility "
        "0.1232 and both carry a *_basis key; nothing checks that the "
        "headline 'current' figure is the one the sizing ran on.",
    ),
    Mutation(
        "volatility_sizing", "record_claims_executable_inside_a_gated_section",
        (
            (("trades", "CIPLA.NS", "status"), "executable"),
            (("trades", "CIPLA.NS", "execution_eligible"), DELETE),
        ),
        ("ENV-019",),
        "the AD-5/G3 defect its own docstring calls the most dangerous kind of "
        "contradiction in this export: the section's exposure block publishes "
        "execution_eligible false and block_reasons ['financing_required'], and "
        "a trade record now claims 'executable'. The record's own gate key has "
        "to be removed as well -- a record that carries its own gate is "
        "disclosing the conflict rather than asserting against it, which is the "
        "escape the rule intends.",
    ),

    # ---- tear_sheet -------------------------------------------------------
    Mutation(
        "tear_sheet", "observation_count_contradicts_its_own_window",
        ((("observation_count",), 365),),
        (),
        "observation_count 365 beside measured_window.days 22, "
        "measured_window.observation_count 22 and history_coverage."
        "covered_days 22: the requested count published as the measured one.",
    ),
    Mutation(
        "tear_sheet", "total_return_published_as_percentage",
        ((("metrics", "total_return"), 4.0399),),
        (),
        "total_return 0.0404 emitted as 4.0399 while every other metric in "
        "the same block is a fraction and annualized is false.",
    ),
    Mutation(
        "tear_sheet", "window_start_contradicts_its_own_reconciliation",
        (
            (("measured_window", "start"), "2026-08-04"),
            (("measured_window", "holding_window_to_measured_start_gap_days"), 1),
        ),
        (),
        "the start moves a day but holding_window_start stays 2026-08-03, and "
        "the stale measured_start_basis prose still describes a 22-day gap. "
        "XS-010 is satisfied by the presence of a gap figure, not its "
        "arithmetic, so it stays quiet.",
    ),
    Mutation(
        "tear_sheet", "window_reconciliation_removed_between_two_dates",
        (
            (("measured_window", "holding_window_to_measured_start_gap_days"), DELETE),
            (("measured_window", "measured_start_basis"), DELETE),
        ),
        (),
        "XS-010 is structurally unreachable on this block. The block publishes "
        "start 2026-08-25 and holding_window_start 2026-08-03 with no "
        "reconciliation left to excuse the gap -- and _holding_window_start "
        "returns (None, None) for it, because XS-010 reads the block's own "
        "start only under `intersection_start`, or under `start`/`end` when "
        "covered_days_scope is a holding-window scope, and this block's scope "
        "is 'holding_window_whole_book_complete_return_rows'. The rule returns "
        "early on the very block its own docstring names as the motivating "
        "case. See holding_window_start_contradicts_its_own_intersection_start "
        "for the same rule firing on a block it CAN read.",
    ),
    Mutation(
        "tear_sheet", "holding_window_start_contradicts_its_own_intersection",
        ((("history_coverage", "holding_window_start"), "2026-08-18"),),
        ("XS-010",),
        "the same rule, on a block it can read: history_coverage declares "
        "intersection_start 2026-08-03 and now also a holding_window_start of "
        "2026-08-18, with no gap figure and no basis reconciling them.",
    ),
    Mutation(
        "tear_sheet", "full_history_stops_declaring_its_window",
        ((("full_history", "scope"), "  "),),
        ("XS-006",),
        "a 2488-observation full-history block with no declared scope.",
    ),

    # ---- risk_contribution ------------------------------------------------
    Mutation(
        "risk_contribution", "shares_do_not_sum_to_the_published_total",
        ((("positions", "volatility", "ARROWGREEN.NS"), 0.128049),),
        ("NUM-003",),
        "one leg's risk contribution restated, so the fourteen published "
        "shares no longer sum to published_total.",
    ),
    Mutation(
        "risk_contribution", "portfolio_volatility_contradicts_its_own_var",
        ((("portfolio_var_95_daily",), -0.027846),),
        (),
        "a 1.645-sigma daily VaR equal to the CVaR beside it: the tail mean "
        "cannot sit exactly on the quantile that selects it.",
    ),
    Mutation(
        "risk_contribution", "volatility_level_contradicts_its_own_shares",
        ((("portfolio_volatility_annualized",), 0.2641),),
        (),
        "portfolio volatility restated while every published contribution "
        "share and the excluded_assets ledger stay as they were.",
    ),

    # ---- risk_studio ------------------------------------------------------
    Mutation(
        "risk_studio", "tail_dependence_matrix_not_symmetric",
        (
            (("components", "tail_dependence", "data",
              "tail_dependence_matrix", "matrix", 0, 1), 0.2193),
        ),
        ("NUM-016",),
        "one off-diagonal cell of a symmetric coefficient matrix.",
    ),
    Mutation(
        "risk_studio", "evt_metrics_without_a_declared_xi",
        (
            (("components", "tail_dependence", "data", "gpd_shape_xi_used"),
             -0.45),
        ),
        ("NUM-017",),
        "gpd_shape_xi_used -0.45 matches none of the published xi values, so "
        "the VaR/ES beside it cannot be reproduced.",
    ),
    Mutation(
        "risk_studio", "alert_contradicts_the_correlation_beside_it",
        (
            (("components", "correlation_stability", "data",
              "current_avg_correlation"), 0.3481),
        ),
        ("NUM-026",),
        "current_avg_correlation 0.3481 sits just above the 10th percentile "
        "(0.2179) while alert_level stays 'ELEVATED', alert_direction stays "
        "'lower_tail_collapse', is_regime_break stays true and the message "
        "still says 'is at or below the 10th percentile'.",
    ),
    Mutation(
        "risk_studio", "volatility_cone_percentiles_out_of_order",
        (
            (("components", "volatility_cone", "data", "windows", 0, "min"),
             0.2442),
        ),
        (),
        "cone min 0.2442 above p25 0.1058: the fan is no longer a fan and "
        "percentile_rank 14.7 is no longer derivable from it.",
    ),

    # ---- optimization -----------------------------------------------------
    Mutation(
        "optimization", "weight_delta_does_not_close_against_its_legs",
        ((("trades_required", "CIPLA.NS", "weight_delta"), 0.5),),
        ("NUM-011",),
        "the trade record publishes two weights and a delta that is neither "
        "their difference nor anything close to it.",
    ),
    Mutation(
        "optimization", "gross_exposure_residual_contradicts_its_legs",
        ((("weight_normalization", "gross_exposure_residual"), 0.0),),
        ("NUM-012",),
        "the residual the normalization absorbed is restated as exactly zero "
        "while submitted_gross_exposure_measured is 0.999998 against a "
        "published gross_exposure of 1.0.",
    ),
    Mutation(
        "optimization", "recommended_weights_do_not_sum_to_their_published_total",
        ((("weights", "CIPLA.NS"), 0.35),),
        (),
        "one recommended leg restated so the 14 weights no longer sum to the "
        "recommended_weights_published_total printed in trades_required_basis.",
    ),
    Mutation(
        "optimization", "sharpe_contradicts_its_own_return_and_volatility",
        ((("expected_annual_volatility",), 0.28),),
        ("NUM-026",),
        "expected_annual_volatility doubled to 0.28 while expected_sharpe "
        "stays 1.0102, which is (0.1614 - 0.02) / 0.14. The section publishes "
        "risk_free_rate and moments_basis, so the identity is checkable; no "
        "rule checks it.",
    ),

    # ---- regime -----------------------------------------------------------
    Mutation(
        "regime", "probabilities_do_not_sum_to_the_published_total",
        ((("regime_probabilities", "crisis"), 94.0),),
        ("NUM-015",),
        "one probability restated; the published total no longer closes.",
    ),
    Mutation(
        "regime", "transition_row_does_not_sum_to_100",
        (
            (("transition_matrix", "bull", "bull"), 94.0),
            (("transition_matrix_row_residuals", "bull"), 2.0),
        ),
        ("NUM-015",),
        "a row that sums to 98 with the residual honestly published as 2.0.",
    ),
    Mutation(
        "regime", "current_state_contradicts_its_own_distribution",
        ((("current_regime",), "bull"),),
        ("NUM-025",),
        "current_regime 'bull' beside regime_probabilities.crisis 99.9967: "
        "the state label is wrong by a factor of a million on the model's own "
        "posterior, and a consumer acting on it goes long in a crisis.",
    ),
    Mutation(
        "regime", "conditional_coverage_is_the_holding_pool_not_the_sample",
        ((("portfolio_in_current_regime", "history_coverage", "covered_days"), 22),),
        ("XS-007",),
        "the conditional block claims 22 covered days against its own 20 "
        "observations, making a 20-sample number read as a 22-sample one.",
    ),

    # ---- monte_carlo ------------------------------------------------------
    Mutation(
        "monte_carlo", "quantiles_not_monotone",
        ((("terminal_percentiles", "p25"), 165000.0),),
        ("NUM-013",),
        "p25 above p50 in the terminal distribution.",
    ),
    Mutation(
        "monte_carlo", "success_probability_contradicts_its_own_distribution",
        ((("prob_success",), 0.42),),
        ("NUM-026",),
        "prob_success 0.42 while p25 of the terminal distribution is 117447 "
        "against a target of 85249: at least 75% of the mass is already above "
        "target, so 0.42 is arithmetically impossible. The percentiles, the "
        "target and the probability are all published in one block.",
    ),
    Mutation(
        "monte_carlo", "fan_row_quantiles_not_monotone",
        ((("fan", 1, "p25"), 62000.0),),
        ("NUM-013",),
        "the year-0.5 fan row's p25 above its own p50.",
    ),
    Mutation(
        "monte_carlo", "initial_value_contradicts_the_fan_origin",
        ((("initial_value",), 51200.0),),
        ("NUM-026",),
        "initial_value 51200.0 while every fan row at year 0 reads 42624.5, "
        "which is the portfolio total the whole simulation starts from.",
    ),

    # ---- pairs ------------------------------------------------------------
    Mutation(
        "pairs", "scanned_count_is_not_n_choose_2",
        ((("scanned_pairs_count",), 90),),
        ("NUM-014",),
        "a dropped pair in the scan count.",
    ),
    Mutation(
        "pairs", "decision_contradicts_its_own_p_value",
        ((("pairs", 0, "engle_granger_pvalue"), 0.513557),),
        ("NUM-026",),
        "is_cointegrated stays true with a p-value of 0.51 on a 91-test scan; "
        "the record's own signal string still quotes the old 0.013557.",
    ),
    Mutation(
        "pairs", "agreement_counts_do_not_reconcile",
        ((("test_agreement", "agreement_count"), 80),),
        ("NUM-014",),
        "80 + 6 != 91 counted_pairs.",
    ),
    Mutation(
        "pairs", "shallow_leg_scan_reported_as_available",
        ((("data_status",), "available"),),
        ("NUM-014",),
        "one shallow leg is disclosed and the section still reads 'available' "
        "for the scan. The section-level status is untouched.",
    ),
    Mutation(
        "pairs", "actionable_directive_with_no_published_basis",
        ((("recommendation",), "LONG_SPREAD (Long JKIL.NS, Short NIFTYIETF.NS)"),),
        ("NUM-024",),
        "NUM-024 has nothing to check on the honest export: every signal string "
        "the exporter publishes says 'No direction is published', so the "
        "directive vocabulary the rule scans for is absent by design. This "
        "mutation puts the SI-1/G9 directive back and the rule catches it -- so "
        "it is a live regression guard with nothing to guard today, which is a "
        "different thing from a working rule and worth knowing.",
    ),

    # ---- india_flows ------------------------------------------------------
    Mutation(
        "india_flows", "hard_zero_ratio_beside_a_null_count",
        (
            (("component_coverage", "delivery_anomalies", "coverage_ratio"), 0.0),
        ),
        ("ENV-021",),
        "coverage_ratio 0 beside covered_count null and covered_symbols null: "
        "a ratio asserted over a count that was never taken. Caught by an "
        "envelope-CATEGORY rule, but ENV-021 is written for exactly this class "
        "and discriminates (it fires on this mutation and no other in the set).",
    ),
    Mutation(
        "india_flows", "coverage_ratio_contradicts_a_complete_status",
        (
            (("component_coverage", "liquidity_limits", "coverage_ratio"), 0.87),
        ),
        (),
        "coverage_status 'complete' with the reason "
        "'every_portfolio_position_had_price_history' beside a 0.87 ratio. "
        "ENV-021 only fires on a hard 0.",
    ),
    Mutation(
        "india_flows", "covered_count_contradicts_the_covered_list",
        (
            (("component_coverage", "liquidity_limits", "covered_count"), 12),
        ),
        (),
        "covered_count 12 beside a covered_tickers list of 14 and a "
        "coverage_ratio of 1.0.",
    ),
    Mutation(
        "india_flows", "unavailable_component_claims_zero_records_as_a_result",
        ((("components", "institutional_flows", "data", "count"), 14),),
        (),
        "count 14 in a component whose own status is 'unavailable', whose "
        "flows array is empty and whose coverage says "
        "'market_wide_aggregate_has_no_ticker_universe'.",
    ),
)

#: Mutations on which NO rule fired.  Frozen, and asserted: a rule added later
#: that closes one of these makes this file red with an instruction to update
#: the set, so improved coverage cannot pass unnoticed.
#:
#: Read the list by SHAPE, not by section.  They fall into six families, and the
#: two largest are not per-section defects at all:
#:
#: 1. a unit flip (3) -- a fraction published as a percentage, or a
#:    percentage as a fraction.  Nothing in the table knows a field's unit;
#:    every rule is an identity between two numbers the system emitted
#:    together, and a 100x slip is consistent with all of them.
#: 2. a statistic that contradicts another statistic of the same family
#:    (6) -- ES better than its own VaR, current_regime against its own
#:    posterior, prob_success against its own percentile table, Sharpe
#:    against its own return and volatility, N_eff against its own HHI, an
#:    alert_level against its own correlation.  These are the identities
#:    a consumer acts on, and they are exactly the ones with no rule.
#: 3. a head/tail/rank figure not reproducible from the series it summarises
#:    (5) -- top_3 against the position weights, the volatility cone, the
#:    financing requirement, the observed count against the covered list.
#: 4. a provenance label removed or a pointer misdirected (2) -- the
#:    dashboard's `data_ref` is the entire mechanism left after the inline
#:    payloads were deleted, and nothing resolves it.
#: 5. a declared constant not enforced (4) -- STRESS_AS_OF_SEMANTICS,
#:    the dashboard's 'oldest_component_observation', a model name, a
#:    horizon.  All four are published strings with an exact meaning and
#:    no rule reads them.
#: 6. rule blind spots found while measuring (5) -- see the per-entry notes.
KNOWN_UNCOVERED: frozenset[tuple[str, str]] = frozenset({
    # --- 1. unit flips: no rule knows a field's unit
    ("concentration", "score_published_as_fraction"),
    ("forecast_risk", "volatility_published_as_percentage"),
    ("tear_sheet", "total_return_published_as_percentage"),
    # --- 2. a statistic contradicting another statistic of the same family
    # CLOSED, deliberately, entry by entry -- see the notes on the
    # mutations themselves and KNOWN_COLLATERAL below.  Each of these was
    # read, the covering rule was confirmed to be the RIGHT rule for that
    # class (not a rule that happened to fire), and only then removed.
    #
    #   effective_positions vs HHI        -> NUM-026, the identity itself
    #   success_probability vs percentiles-> NUM-026, the identity itself
    #   Sharpe vs its own moments          -> NUM-026, the identity itself
    #   pairs verdict vs its own p-value   -> NUM-026, the identity itself
    #   ES vs the VaR it derives from      -> NUM-026, the identity itself
    #   simulation origin vs its own fan   -> NUM-026, the identity itself
    #   current state vs its own posterior -> NUM-025, the identity itself
    #
    # NOT closed: var_published_as_percentage stays below.  A 100x unit
    # slip is only visible there because it happens to break a COMPANION
    # identity (a var_95 at -0.643 makes the cvar_95 beside it look milder
    # than the tail it is the mean of).  That is a real catch and the wrong
    # REASON for the class, so it is recorded as collateral rather than
    # counted as unit coverage.
    ("risk_contribution", "portfolio_volatility_contradicts_its_own_var"),
    # --- 3. head/tail/rank figures not reproducible from their own series
    ("concentration", "top_3_does_not_match_the_position_weights"),
    ("india_flows", "covered_count_contradicts_the_covered_list"),
    ("risk_contribution", "volatility_level_contradicts_its_own_shares"),
    ("risk_studio", "volatility_cone_percentiles_out_of_order"),
    ("volatility_sizing", "financing_requirement_contradicts_its_fraction"),
    # --- 4. provenance label removed / pointer misdirected
    ("dashboard", "component_reference_pointer_names_the_wrong_section"),
    ("dashboard", "component_as_of_contradicts_the_sections_own_semantics"),
    # --- 5. a declared constant published with an exact meaning, unenforced
    ("forecast_risk", "horizon_label_contradicts_the_horizon_beside_it"),
    ("forecast_risk", "model_declared_does_not_match_the_model_fitted"),
    ("stress_testing", "as_of_contradicts_the_scenario_dates_beside_it"),
    ("factor_exposure", "fit_window_contradicts_its_observation_count"),
    ("tear_sheet", "observation_count_contradicts_its_own_window"),
    ("tear_sheet", "window_start_contradicts_its_own_reconciliation"),
    # --- 6. rule blind spots found while measuring these
    # NUM-022 is keyed on ('confidence_interval', 'interval', '_ci', 'ci_')
    # and the export publishes 244 intervals under 'conf_int'.
    ("realized_risk", "confidence_interval_is_a_fixed_band"),
    # NUM-022 only rejects a CONSTANT band; it never checks containment.
    ("realized_risk", "interval_broader_than_its_own_estimate"),
    # XS-010 cannot read tear_sheet.measured_window's own start: the block's
    # covered_days_scope is not in HOLDING_WINDOW_SCOPES, so _holding_window_start
    # returns (None, None) and the rule returns early on its own docstring case.
    ("tear_sheet", "window_reconciliation_removed_between_two_dates"),
    # Correct silence, listed so the table is not read as a gap: the component
    # publishes avg_pairwise_correlation, so the floor is a measured zero.
    ("dashboard", "correlation_floor_is_a_measured_zero"),
    # No rule reconciles the two views of one number, or a count with its list.
    ("portfolio", "position_count_does_not_match_its_list"),
    ("portfolio", "sector_weights_do_not_sum_to_position_weights"),
    ("liquidity", "liquidation_window_contradicts_its_own_band"),
    ("liquidity", "estimated_market_cap_count_understated"),
    ("india_flows", "coverage_ratio_contradicts_a_complete_status"),
    ("india_flows", "unavailable_component_claims_zero_records_as_a_result"),
    ("optimization", "recommended_weights_do_not_sum_to_their_published_total"),
    ("volatility_sizing", "current_volatility_is_not_the_volatility_used"),
})

#: Mutations on which a rule fired but not one in ``expects`` -- a rule
#: catching a different defect than the one injected.  Weaker than a hit and
#: stronger than nothing, so it is reported rather than counted.
#:
#: Both are the same case.  ``adjusted_r_squared > r_squared`` and
#: ``r_squared > 1`` are arithmetic impossibilities, and XS-009 catches neither
#: on those grounds: it sees two R-squared figures that now disagree over one
#: declared basis and reports them as two competing fits needing distinct
#: windows.  That is a true statement about the mutated document, and it is not
#: the defect that was injected.
KNOWN_COLLATERAL: frozenset[tuple[str, str]] = frozenset({
    ("factor_exposure", "adjusted_r_squared_exceeds_r_squared"),
    # A unit flip caught by a companion identity, which is a true
    # statement about the mutated document and not the class injected.
    # The tail-mean relation fires because var_95 at -0.643209 (100x the
    # published -0.00643209) makes the cvar_95 beside it look MILDER than
    # the quantile that selects its tail.  Nothing in the table knows a
    # field unit, so a 100x slip on a field with no companion relation is
    # still invisible; the seven other unit flips stay in KNOWN_UNCOVERED
    # for exactly that reason.  Counting this one as unit coverage would be
    # the exact error this file exists to catch.
    ("realized_risk", "var_published_as_percentage"),
    ("factor_exposure", "r_squared_above_one"),
})


#: Findings the REFERENCE DOCUMENT itself carries, as ``(rule_id, path)``.
#: Frozen and asserted in both directions, and SUBTRACTED from every mutation
#: ledger by :func:`_subtract` so they can never be credited to a mutation.
#:
#: This set exists because the harness's precondition -- a base with no findings,
#: so every finding is attributable to a mutation -- is right about the ATTRIBUTE
#: and wrong as an absolute.  The precondition is really "only credit a mutation
#: with what the mutation introduced", and subtraction delivers that against a
#: base that carries a real defect.  Measured: with the finding recorded below
#: left in, the ``monte_carlo`` mutations ``quantiles_not_monotone`` and
#: ``fan_row_quantiles_not_monotone`` each showed NUM-026 firing on a path the
#: mutation never touched, which is a false catch in the ledger.
#:
#: The set is now EMPTY, and the entry that was retired from it is the reason
#: this file's central measurement had to be re-derived rather than trusted:
#:
#:   sections.monte_carlo.data.prob_success   (NUM-026)   -- RETIRED
#:
#: The note that accompanied the entry asserted that a p95 of 301465.64 clears
#: ``target_value: 85249.0``, "so at most 5% of those paths finished below the
#: target, so prob_success must be at least 0.95".  That is the same mirrored
#: derivation the rule itself was making, and it was wrong.  The share of paths
#: that clear the target is the share AT OR ABOVE the clearing percentile, so
#: the level enters COMPLEMENTED: p95 above the target puts a FLOOR of 0.05
#: under the share, not a floor of 0.95, and p25 at 117447.13 -- the SMALLEST
#: published level above the target -- puts the tightest floor there is,
#: 1 - 25/100 = 0.75.  p5 at 79001.08, below the target, puts a ceiling of
#: 1 - 5/100 = 0.95 on it.  So the bracket the published table requires is
#: [0.75, 0.95] and the published 0.922 is inside it.  The export was never
#: wrong; the note and the rule were, and they were wrong in the same way and
#: for the same reason -- each read the level as the share instead of as the
#: complement of the share.
#:
#: The entry is retired rather than reworded because the measurement it was
#: frozen against no longer exists.  It is left here in full because a frozen
#: set that quietly shrinks is how a coverage harness stops measuring, and this
#: one is the entry a reader would otherwise assume was quietly dropped.
#:
#: What this also retires is a second claim in the same note -- that
#: ``terminal_percentiles`` might be "a parametric fit (the block says
#: ``method: student_t``)" rather than order statistics of the same 2000 paths,
#: and that the section published no ``terminal_percentiles_basis`` to say so.
#: The first was a guess produced by a rule that could not be made to fit the
#: figure, and it is false: the service writes ``terminal_percentiles`` and
#: ``prob_success`` from ONE ``terminal`` array in the same expression, so they
#: are one sample by construction.  The second is stale -- the exporter now
#: publishes ``terminal_percentiles_basis`` and
#: ``terminal_percentiles_basis_detail``, which declare the basis this rule's
#: derivation rests on.  Neither fact changes anything in the table above.
KNOWN_BASE_FINDINGS: frozenset[tuple[str, str]] = frozenset()

# --------------------------------------------------------------------------
# Harness
def _subtract(
    fired: dict[str, list[str]],
    baseline: set[tuple[str, str, str]],
) -> dict[str, list[str]]:
    """Drop the findings the reference document already had.

    Keyed on ``(rule_id, path, message)``.  The path alone is NOT enough, and
    the harness proved it on itself: while the base document carried
    ``(NUM-026, sections.monte_carlo.data.prob_success)`` -- the finding
    retired above -- the mutation
    ``success_probability_contradicts_its_own_distribution`` wrote
    ``prob_success = 0.42`` at that SAME node.  Keyed on the path the mutation's
    finding was indistinguishable from the base's, got subtracted, and a real
    catch read as a gap -- coverage falling for the mirror image of the reason
    it rose.  The message names the values, so the two differ and only the
    base's finding is removed.

    :data:`KNOWN_BASE_FINDINGS` is empty now, so against today's reference
    export this function is a no-op and the hazard it guards is dormant rather
    than gone: it returns the moment a new base defect appears, and the key has
    to stay three-wide until then.

    A rule whose every finding was a base finding is REMOVED from the mapping
    rather than left holding an empty list.  Every verdict below is ``if fired``,
    and a dict holding an empty list is truthy, so leaving one behind would
    report all 82 mutations as caught by whatever the base happened to fail.
    """
    survivors: dict[str, list[str]] = {}
    for rule_id, messages in fired.items():
        kept = [
            message for message in messages
            if (rule_id, *message.split(" :: ", 1)) not in baseline
        ]
        if kept:
            survivors[rule_id] = kept
    return survivors


def _base_document() -> dict[str, Any]:
    if not BASE_EXPORT.is_file():
        pytest.fail(
            f"the reference export is missing: {BASE_EXPORT}. This harness "
            f"measures rule coverage against a real export; skipping would "
            f"leave the gate reporting nothing while exiting 0, which is the "
            f"exact failure mode it exists to detect."
        )
    return json.loads(BASE_EXPORT.read_text(encoding="utf-8"))


def _apply(document: dict[str, Any], mutation: Mutation) -> dict[str, Any]:
    """Apply one mutation to a deep copy, touching only ``sections.*.data``."""
    mutated = copy.deepcopy(document)
    data = mutated["sections"][mutation.section]["data"]
    for path, value in mutation.writes:
        node = data
        for part in path[:-1]:
            node = node[part]
        if value is DELETE:
            del node[path[-1]]
        else:
            node[path[-1]] = copy.deepcopy(value)
    return mutated


def _fire(
    document: dict[str, Any],
) -> tuple[dict[str, list[str]], list[str], set[tuple[str, str]]]:
    """Every rule that fires on this document, keyed by rule id, plus rule errors."""
    export = ca.Export(doc=document, raw=json.dumps(document))
    findings, errors = ca.run_rules(export)
    fired: dict[str, list[str]] = {}
    for finding in findings:
        fired.setdefault(finding.rule_id, []).append(
            f"{finding.path} :: {finding.message}"
        )
    return (
        fired,
        [f"{rule.rule_id}: {message}" for rule, message in errors],
        {(f.rule_id, f.path, f.message) for f in findings},
    )


def _ledger(document: dict[str, Any]) -> dict[tuple[str, str], dict[str, list[str]]]:
    """``(section, error class) -> {rule_id: [messages]}`` for every mutation.

    Memoised on the document's identity: 57 rules over 82 mutations of a 1 MB
    tree costs real seconds, and every assertion below reads the same ledger.
    """
    global _LEDGER_CACHE
    if _LEDGER_CACHE is None:
        _baseline = _fire(document)[2]
        _LEDGER_CACHE = {
            (mutation.section, mutation.cls): _subtract(
                _fire(
                    _apply(document, mutation)
                )[0],
                _baseline,
            )
            for mutation in MUTATIONS
        }
    return _LEDGER_CACHE


_LEDGER_CACHE: dict[tuple[str, str], dict[str, list[str]]] | None = None


def _table(ledger: dict[tuple[str, str], dict[str, list[str]]]) -> str:
    """The measurement, as a table.  Asserted on, not just printed."""
    width = max(len(f"{s}/{c}") for s, c in ledger)
    lines = [
        f"{'section/class'.ljust(width)}  verdict    rules fired",
        f"{'-' * width}  ---------  -----------",
    ]
    for (section, cls), fired in ledger.items():
        expected = next(
            m.expects for m in MUTATIONS if (m.section, m.cls) == (section, cls)
        )
        if expected:
            verdict = "RIGHT" if set(expected) & set(fired) else "WRONG-CLASS"
        elif fired:
            verdict = "COLLATERAL"
        else:
            verdict = "UNCOVERED"
        lines.append(
            f"{f'{section}/{cls}'.ljust(width)}  {verdict:<9}  "
            f"{','.join(sorted(fired)) or '(none)'}"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------
def test_base_export_is_clean_and_complete():
    """The reference must cover the whole catalog, and its own findings must
    be KNOWN.

    The original precondition was 'the base has no findings at all', and the
    reasoning behind it still holds: a base that already fails cannot attribute
    a finding to a mutation, because every rule would be 'firing' on all of
    them at once and the measurement would be measuring the base.

    What changed is that a base defect is no longer disqualifying, because the
    reasoning is about ATTRIBUTION and not about perfection.  :func:`_subtract`
    removes the base's own findings -- keyed on rule, path AND message -- from
    every mutation ledger, so they can never be credited to a mutation.  What
    IS disqualifying is a base whose redness is unrecorded, which is why the
    findings are asserted EQUAL to :data:`KNOWN_BASE_FINDINGS` rather than
    merely tolerated: a new base defect is red, and so is a base defect that
    has been fixed, which is the signal to retire the entry.
    """
    document = _base_document()
    catalog = tuple(SECTION_CATALOG)
    assert set(catalog) == set(document["sections"]), (
        f"the reference export publishes {sorted(document['sections'])} but the "
        f"catalog declares {sorted(catalog)}; the measurement would not cover "
        f"the document it is pointed at"
    )
    assert len(catalog) == 17, (
        f"SECTION_CATALOG now declares {len(catalog)} sections, not the 17 this "
        f"harness was written against: {sorted(catalog)}"
    )
    assert ca.Export(doc=document, raw=json.dumps(document)).strict_error is None

    baseline, errors, _identity = _fire(document)
    assert not errors, f"a rule raised on the unmodified export: {errors}"
    known = {(rid, m.split(" :: ")[0]) for rid, msgs in baseline.items()
              for m in msgs}
    assert known == KNOWN_BASE_FINDINGS, (
        "the reference export's own findings have changed."
        + f"  new (the base has a defect nobody recorded): "
        f"{sorted(known - KNOWN_BASE_FINDINGS)}"
        + f"  fixed (retire the entry, the defect is gone): "
        f"{sorted(KNOWN_BASE_FINDINGS - known)}"
        + "A base finding is SUBTRACTED from every mutation ledger by"
        " _subtract, so it can never be credited to a mutation.  A base"
        " that is red is still usable here; a base whose redness is"
        " unrecorded is not."
    )


def test_every_mutation_touches_only_section_data():
    """The precondition: a mutation must not make the document schema-invalid.

    If the envelope moved, the 21 envelope rules would fire on every corrupted
    export and 'no rule caught this' would become a statement about the
    mutation, not about the rule table.
    """
    document = _base_document()
    for mutation in MUTATIONS:
        mutated = _apply(document, mutation)

        assert {k: v for k, v in mutated.items() if k != "sections"} == {
            k: v for k, v in document.items() if k != "sections"
        }, f"{mutation.section}/{mutation.cls} changed the envelope"

        assert mutated["sections"].keys() == document["sections"].keys()
        for name, section in document["sections"].items():
            after = mutated["sections"][name]
            assert after.keys() == section.keys(), (
                f"{mutation.section}/{mutation.cls} changed the key set of "
                f"sections.{name}"
            )
            for key in section:
                if key == "data":
                    continue
                assert after[key] == section[key], (
                    f"{mutation.section}/{mutation.cls} changed "
                    f"sections.{name}.{key}, which is outside the mutation zone"
                    + (
                        " (section scaffolding)"
                        if key in SECTION_SCAFFOLD_KEYS
                        else ""
                    )
                )


def test_every_catalog_section_has_a_caught_mutation():
    """THE PASS CONDITION: zero rules on an injected error fails the suite.

    A harness that prints '0 rules fired' and exits 0 has measured nothing.
    """
    document = _base_document()
    ledger = _ledger(document)

    caught = {section for (section, _cls), fired in ledger.items() if fired}
    uncovered_sections = sorted(set(SECTION_CATALOG) - caught)
    assert not uncovered_sections, (
        "injected errors caught by ZERO of the 57 rules, by section:\n"
        + "\n".join(
            f"  sections.{uncovered}: "
            + ", ".join(
                f"{cls} (rules fired: "
                f"{','.join(sorted(ledger[(uncovered, cls)])) or 'none'})"
                for owner, cls in ledger
                if owner == uncovered
            )
            for uncovered in uncovered_sections
        )
        + f"\n\n{_table(ledger)}"
    )

    # The table is the deliverable; assert it has one row per section so a
    # silently empty measurement cannot pass as a passing one.
    table = _table(ledger)
    for name in SECTION_CATALOG:
        assert f"{name}/" in table, f"the coverage table has no row for {name}"


def test_declared_right_class_is_a_rule_that_fired():
    """Where a class is claimed to be covered, the claimed rule must be the one that fired."""
    ledger = _ledger(_base_document())
    misses = [
        f"  sections.{section}/{cls}: expects {list(expected)}, "
        f"fired {sorted(fired) or 'nothing'}"
        for (section, cls), fired in ledger.items()
        for expected in [next(m.expects for m in MUTATIONS
                              if (m.section, m.cls) == (section, cls))]
        if expected and not set(expected) & set(fired)
    ]
    assert not misses, (
        "a class the harness claims is covered, where the covering rule did not "
        "fire:\n" + "\n".join(misses)
    )


def test_known_uncovered_set_is_accurate():
    """The gap list is frozen: a new rule closing a gap must turn this red.

    A coverage harness that quietly reports better coverage after a rule is
    added has stopped measuring.  Closing a gap is good news and still has to
    be acknowledged in the frozen set.

    The two labels below were SWAPPED until this was read carefully, and the
    swap is the reason a previous task on ``context_audit.py`` was reported as a
    REGRESSION when it was in fact a large improvement.  ``actual`` is the set
    that is uncovered NOW, so:

      * ``actual - KNOWN_UNCOVERED`` is a gap nobody had recorded -- something
        is newly UNCOVERED, which is a regression, and it is the alarming one;
      * ``KNOWN_UNCOVERED - actual`` is a frozen entry that is no longer
        uncovered -- something is newly COVERED, which is good news.

    Printed under each other's names, a rule being ADDED reads as coverage going
    DOWN: that is the one misreading that would have had eight correctly-caught
    injected errors struck from the table on the strength of a label.
    """
    ledger = _ledger(_base_document())
    actual = frozenset(
        (section, cls)
        for (section, cls), fired in ledger.items()
        if not fired
    )
    assert actual == KNOWN_UNCOVERED, (
        "the set of mutations no rule catches has changed.\n"
        f"  REGRESSION -- newly UNCOVERED (was caught, no longer is): "
        f"{sorted(actual - KNOWN_UNCOVERED)}\n"
        f"  IMPROVEMENT -- newly COVERED (was in KNOWN_UNCOVERED, now caught): "
        f"{sorted(KNOWN_UNCOVERED - actual)}\n"
        "A newly UNCOVERED entry is a regression to FIX, never a new baseline to "
        "accept.  A newly COVERED entry must be closed deliberately: read it, "
        "confirm the covering rule is the RIGHT one for that class, and record "
        "why in the mutation note and in KNOWN_COLLATERAL if it fired for a "
        "different reason."
    )


def test_known_collateral_set_is_accurate():
    """Rules that fired for a different reason than the class injected."""
    ledger = _ledger(_base_document())
    actual = frozenset(
        (section, cls)
        for (section, cls), fired in ledger.items()
        if fired
        and not set(
            next(m.expects for m in MUTATIONS if (m.section, m.cls) == (section, cls))
        ) & set(fired)
    )
    assert actual == KNOWN_COLLATERAL, (
        "the set of mutations caught by a rule other than the expected one has "
        f"changed.\n  now: {sorted(actual)}\n  frozen: {sorted(KNOWN_COLLATERAL)}"
    )


def test_no_uncovered_mutation_was_caught_by_a_broad_envelope_rule():
    """Guards the false-positive reading of this table.

    'A mutation caught only by an envelope rule that fires on everything' is a
    false positive, not a catch.  ENV-021 legitimately fires from the envelope
    CATEGORY while being written for exactly one class, so the test is not
    'was it an envelope rule' but 'did an envelope rule fire on more than one
    mutation' -- a discriminating rule cannot.
    """
    ledger = _ledger(_base_document())
    per_rule: dict[str, list[str]] = {}
    for (section, cls), fired in ledger.items():
        for rule_id in fired:
            per_rule.setdefault(rule_id, []).append(f"{section}/{cls}")

    broad = {
        rule_id: hits
        for rule_id, hits in per_rule.items()
        if rule_id.startswith("ENV-") and len(hits) > 1
    }
    assert not broad, (
        "envelope rules fired on more than one mutation, so a finding from one "
        f"of them is not evidence about the other:\n{broad}"
    )

    # And the specific claim: no envelope-category rule may be the sole catcher
    # of a class that is not itself an envelope contract class.
    sole_envelope = [
        f"  sections.{section}/{cls}: {sorted(fired)}"
        for (section, cls), fired in ledger.items()
        if fired
        and all(rule_id.startswith("ENV-") for rule_id in fired)
        and not set(
            next(m.expects for m in MUTATIONS if (m.section, m.cls) == (section, cls))
        )
    ]
    assert not sole_envelope, (
        "these mutations were caught ONLY by an envelope rule that was not the "
        "declared cover for the class, which is a false positive:\n"
        + "\n".join(sole_envelope)
    )


def test_measurement_is_printed():
    """Emit the table on every run; the assertions above are what make it count."""
    ledger = _ledger(_base_document())
    print()
    print(_table(ledger))
    print()
    never = sorted(r.rule_id for r in ca.RULES
                   if r.rule_id not in {i for f in ledger.values() for i in f})
    print(f"rules that never fired across all {len(MUTATIONS)} mutations: "
          f"{len(never)}/{len(ca.RULES)}")
    print(f"  {', '.join(never)}")
    sys.stdout.flush()
    assert len(ledger) == len(MUTATIONS) > 0


# --------------------------------------------------------------------------
# NUM-026 -- probability_bounded_by_its_own_percentiles
# --------------------------------------------------------------------------
#: The counterexample, as an ARRAY rather than a hand-written table: 200 of 2000
#: simulated paths end at 0.5 and 1800 end at 10.0, with the target at 5.0 in
#: the gap between them.  ``prob_success`` is that array's own mean indicator
#: and the levels are ``numpy.percentile`` of that same array -- the estimator
#: the exporter uses -- so the figure and the distribution published beside it
#: are one sample and both are correct by construction.
#:
#: This is the document that made the rule's floor visible.  The floor was
#: derived as ``max(at_or_above)/100``: the share that clears a target the
#: percentile clears is the share ABOVE that percentile, so the level has to
#: enter COMPLEMENTED, and the tightest such floor comes from the SMALLEST
#: clearing level.  On this array ``at_or_above`` is ``[25, 50, 75, 95]``, so
#: the bracket is ``[1 - 25/100, 1 - 5/100] = [0.75, 0.95]`` and 0.9 is
#: inside it.  The mirrored derivation reported ``[0.95, 0.95]`` and rejected
#: the figure -- on the live export it rejected 0.922, which is why NUM-026 was
#: red on a correct document.
_TWO_TONE_TERMINALS = np.array([0.5] * 200 + [10.0] * 1800)
_TWO_TONE_LEVEL_KEYS = ("p5", "p25", "p50", "p75", "p95")
_TWO_TONE_TARGET = 5.0


def _two_tone_levels(terminals: Any) -> dict[str, float]:
    """The published table for ``terminals``, from the exporter's own estimator."""
    published = np.percentile(terminals, [5, 25, 50, 75, 95])
    return {
        key: float(value) for key, value in zip(_TWO_TONE_LEVEL_KEYS, published)
    }


def _monte_carlo_firing(writes: tuple[tuple[tuple[Any, ...], Any], ...]) -> dict[str, list[str]]:
    """Run every rule on the REAL export with ``writes`` applied to monte_carlo.

    The base document is used rather than a hand-built one so that "no rule
    fired" is a statement about the whole 57-rule table and not about a
    fixture that happens to be small enough to pass.  ``_apply`` is the
    harness's own mutation applier, so these writes get the same envelope
    guarantee as :data:`MUTATIONS`.
    """
    document = _apply(
        _base_document(),
        Mutation("monte_carlo", "local_num026_probe", tuple(writes)),
    )
    fired, errors, _identity = _fire(document)
    assert not errors, f"a rule raised on the probe document: {errors}"
    return fired


def _two_tone_writes(
    prob_success: Any,
    *,
    levels: dict[str, float] | None = None,
    terminals: Any = _TWO_TONE_TERMINALS,
    num_paths: Any = None,
) -> tuple[tuple[tuple[Any, ...], Any], ...]:
    """The counterexample as writes; ``num_paths`` may be :data:`DELETE`."""
    table = _two_tone_levels(terminals) if levels is None else levels
    writes: list[tuple[tuple[Any, ...], Any]] = [
        (("terminal_percentiles",), table),
        (("target_value",), _TWO_TONE_TARGET),
        (("prob_success",), prob_success),
    ]
    if num_paths is not None:
        writes.append((("num_paths",), num_paths))
    return tuple(writes)


def test_num026_accepts_a_success_probability_its_own_table_supports():
    """THE COUNTEREXAMPLE.  Red before the floor was re-derived, green after.

    ``prob_success`` here is the array's own mean indicator and the table beside
    it is the array's own percentile fan, so there is nothing to reject.  The
    rule derived the floor as ``max(at_or_above)/100`` and reported the bracket
    ``[0.95, 0.95]``, which put 0.9 outside a bracket no correct pair can
    produce; the assertion below is what that bug looked like from outside.
    """
    levels = _two_tone_levels(_TWO_TONE_TERMINALS)
    assert levels == {"p5": 0.5, "p25": 10.0, "p50": 10.0,
                      "p75": 10.0, "p95": 10.0}, (
        "numpy no longer publishes these levels for this array, so the case "
        f"below is not the case this test claims it is: {levels}"
    )
    truth = float(np.mean(_TWO_TONE_TERMINALS >= _TWO_TONE_TARGET))
    assert truth == 0.9, "the array's own mean indicator is not 0.9"

    fired = _monte_carlo_firing(_two_tone_writes(truth, num_paths=2000))
    assert fired == {}, (
        "a correct success probability was rejected by the distribution "
        f"published beside it: {fired}"
    )


def test_num026_accepts_the_same_shape_without_a_single_tied_path():
    """The same bracket on a tie-free sample, where interpolation is strictest.

    The two-tone array puts 200 paths on exactly 0.5, and a numpy percentile
    between two equal order statistics returns that shared value -- so the
    counterexample above lands exactly on a tie.  This one has no ties at all,
    which is what 2000 continuously simulated wealth paths actually look like,
    and asserts the same verdict.  A relation that only survived the tied case
    would be measuring the tie.
    """
    rng = np.random.default_rng(20260930)
    terminals = np.concatenate([
        0.5 - rng.random(200) * 0.4,
        10.0 + rng.random(1800) * 0.4,
    ])
    truth = round(float(np.mean(terminals >= _TWO_TONE_TARGET)), 4)
    fired = _monte_carlo_firing(_two_tone_writes(truth, terminals=terminals,
                                                 num_paths=2000))
    assert fired == {}, (
        "a correct success probability was rejected on a tie-free sample: "
        f"{fired}"
    )


def test_num026_the_bracket_is_seven_five_to_nine_five_and_still_fires_outside_it():
    """The corrected bracket, pinned by the message, and load-bearing on both edges.

    Asserting silence alone would pass for a rule that had stopped judging, so
    each edge is walked outward: inside it the rule is silent, one path beyond
    it the rule fires and NAMES the bracket it derived.  ``[0.75, 0.95]`` is
    what ``at_or_above = [25, 50, 75, 95]`` and ``below = [5]`` require on this
    table; ``[0.95, 0.95]`` was the mirrored derivation.
    """
    one_path = 1.0 / 2000
    for inside in (0.76, 0.94, 0.75 - one_path, 0.95 + one_path):
        assert _monte_carlo_firing(_two_tone_writes(inside, num_paths=2000)) == {}, (
            f"the rule rejected {inside}, which its own table permits"
        )
    for outside in (0.74, 0.96, 0.75 - 2 * one_path, 0.95 + 2 * one_path):
        fired = _monte_carlo_firing(_two_tone_writes(outside, num_paths=2000))
        assert set(fired) == {"NUM-026"}, (
            f"{outside} is outside [0.75, 0.95] and no rule rejected it: {fired}"
        )
        assert "lies outside [0.75, 0.95]" in fired["NUM-026"][0], (
            "the message does not name the bracket the derivation requires: "
            f"{fired['NUM-026']}"
        )
        assert "so at least 75% of the paths clear it" in fired["NUM-026"][0], (
            "the floor clause does not state the derivation it rests on: "
            f"{fired['NUM-026']}"
        )


def test_num026_the_degenerate_tables_bracket_what_they_can_and_decline_what_they_cannot():
    """Target above every level, below every level, no table at all, no figure.

    None of these four may raise, and the two that carry no information may
    produce no finding rather than a guess.  A target above every published
    level leaves the table no floor but still a ceiling (nothing above p95 can
    clear it); a target below every level leaves it a floor but no ceiling.
    """
    levels = {"p5": 0.5, "p25": 10.0, "p50": 10.0, "p75": 10.0, "p95": 10.0}
    common = (("terminal_percentiles",), levels)

    above = _monte_carlo_firing((common, (("target_value",), 20.0),
                                 (("prob_success",), 0.95)))
    assert above == {}, f"0.95 clears a target above every published level: {above}"
    below_edge = _monte_carlo_firing((common, (("target_value",), 20.0),
                                      (("prob_success",), 0.96)))
    assert "lies outside [0, 0.95]" in below_edge["NUM-026"][0], below_edge
    assert "the table puts no floor under prob_success" in \
        below_edge["NUM-026"][0], below_edge

    under = _monte_carlo_firing((common, (("target_value",), 0.0),
                                 (("prob_success",), 0.95)))
    assert under == {}, f"0.95 clears a target below every published level: {under}"
    under_edge = _monte_carlo_firing((common, (("target_value",), 0.0),
                                      (("prob_success",), 0.94)))
    assert "lies outside [0.95, 1]" in under_edge["NUM-026"][0], under_edge
    assert "the table puts no ceiling on prob_success" in \
        under_edge["NUM-026"][0], under_edge

    no_table = _monte_carlo_firing(((("terminal_percentiles",), DELETE),
                                    (("target_value",), 5.0),
                                    (("prob_success",), 0.9)))
    assert "NUM-026" not in no_table, (
        f"the rule judged a share against a table it cannot read: {no_table}"
    )
    no_figure = _monte_carlo_firing((common, (("target_value",), 5.0),
                                     (("prob_success",), None)))
    assert "NUM-026" not in no_figure, (
        f"the rule judged a figure it was not given: {no_figure}"
    )


def test_num026_the_bracket_is_one_path_of_the_mass_wide_and_no_wider():
    """The interpolation tolerance, derived rather than fitted.

    A published level is a blend of the two order statistics numpy puts either
    side of it, so the mass under it can sit up to one path away from the
    ``a/100`` its nominal level names, and the derived bound moves with it: one
    path of the mass, ``1/num_paths``.  At this table's 2000 paths that is
    0.0005 against a 0.20-wide bracket.  The tolerance is asserted from BOTH
    sides, and with ``num_paths`` removed it is asserted to vanish, which is
    what makes it a derived width rather than a number tuned until a hard case
    passed.

    Zero width is the wrong default for a block that does declare a path count
    and unsound to invent one for a block that does not, so the fallback is
    asserted here rather than left to be discovered: a future export that drops
    ``num_paths`` gets the exact bracket, not a guessed one.
    """
    edge = 0.75 - 1.0 / 2000
    assert _monte_carlo_firing(_two_tone_writes(edge, num_paths=2000)) == {}, (
        "one path inside the floor is still inside it"
    )
    beyond = _monte_carlo_firing(
        _two_tone_writes(edge - 1e-6, num_paths=2000)
    )
    assert "NUM-026" in beyond, (
        "a figure more than one path outside the floor was accepted"
    )
    undeclared = _monte_carlo_firing(_two_tone_writes(edge, num_paths=DELETE))
    assert "NUM-026" in undeclared, (
        "a block that publishes no path count must be checked with NO width, "
        f"not with an assumed one: {undeclared}"
    )

