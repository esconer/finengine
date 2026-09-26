"""Tests for the AI-context export audit CLI.

Every fixture is built INLINE as a small dict.  Nothing here touches a live
server or a real portfolio, and no export artifact is read from disk except the
ones a test writes itself into ``tmp_path``.

The shape of these tests is deliberate: for each rule there is a minimal export
that must PASS it and a targeted mutation that must FAIL *with that exact rule
id*.  A rule that cannot be made to fail is a rule that does not work.
"""

from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from app.debugging import context_audit as ca

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


def _coverage(tickers: list[str], *, missing: list[str] | None = None) -> dict[str, Any]:
    missing = missing or []
    covered = [t for t in tickers if t not in missing]
    return {
        "requested_tickers": list(tickers),
        "available_tickers": list(tickers),
        "covered_tickers": covered,
        "missing_tickers": list(missing),
        "requested_count": len(tickers),
        "available_count": len(covered),
        "coverage_ratio": 1.0 if not missing else len(covered) / len(tickers),
        "complete": not missing,
        "status": "complete" if not missing else "partial",
    }


def _section(
    key: str,
    data: dict[str, Any] | None,
    *,
    status: str = "available",
    coverage: dict[str, Any] | None = None,
    as_of: str | None = "2026-09-25",
    semantics: str | None = "latest_observation_date",
    currency: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    section: dict[str, Any] = {
        "key": key,
        "title": key.replace("_", " ").title(),
        "route": f"/{key}",
        "status": status,
        "detail": "summary",
        "generated_at": "2026-09-26T05:57:43.164091Z",
        "inputs": {},
        "coverage": coverage,
        "data": data,
        "as_of": as_of,
        "as_of_semantics": semantics,
        "currency": currency,
        "warnings": warnings if warnings is not None else [],
    }
    return section


def make_export(sections: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """A minimal envelope that passes EVERY rule.

    Sections are passed in scope order.  ``dict`` preserves insertion order, so
    ENV-003 (scope order == sections order) holds by construction.
    """
    sections = sections if sections is not None else {"portfolio": _section("portfolio", {})}
    return {
        "schema_version": ca.EXPECTED_SCHEMA_VERSION,
        "export_id": "portfolio-test0000",
        "generated_at": "2026-09-26T05:57:43.164091Z",
        "completed_at": "2026-09-26T05:58:16.698733Z",
        "snapshot_consistency": "best_effort",
        "base_currency": "INR",
        "detail": "summary",
        "scope": list(sections),
        "sections": sections,
        "warnings": [],
    }


def run(export: dict[str, Any]) -> list[ca.Finding]:
    return ca.run_rules(ca.Export(doc=export, raw=json.dumps(export)))[0]


def rule_ids(export: dict[str, Any]) -> set[str]:
    return {finding.rule_id for finding in run(export)}


def find_for(export: dict[str, Any], rule_id: str) -> list[ca.Finding]:
    return [f for f in run(export) if f.rule_id == rule_id]


def assert_only(export: dict[str, Any], rule_id: str) -> None:
    """The export fails, and it fails on exactly ``rule_id``.

    Pinning the WHOLE failure set is what stops a rule from silently
    cannibalising another: if a mutation trips two ids, the assertion says so.
    """
    assert rule_ids(export) == {rule_id}, f"expected only {rule_id}, got {sorted(rule_ids(export))}"


def clone(export: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(export))


# --------------------------------------------------------------------------
# The minimal export really is clean
# --------------------------------------------------------------------------


class TestBaselineFixture:
    def test_minimal_export_passes_every_rule(self) -> None:
        assert run(make_export()) == []

    def test_rule_table_has_no_duplicate_ids(self) -> None:
        ids = [rule.rule_id for rule in ca.RULES]
        assert len(ids) == len(set(ids))

    def test_every_rule_id_is_exercised_by_at_least_one_test(self) -> None:
        """Guards against a rule being added to the table and never asserted."""
        exercised = EXERCISED_RULE_IDS
        table = {rule.rule_id for rule in ca.RULES}
        assert table - exercised == set(), f"never exercised: {sorted(table - exercised)}"
        assert exercised - table == set(), f"exercised but absent: {sorted(exercised - table)}"

    def test_rule_categories_cover_the_three_documented_buckets(self) -> None:
        by_category: dict[str, list[str]] = {}
        for rule in ca.RULES:
            by_category.setdefault(rule.category, []).append(rule.rule_id)
        assert set(by_category) == set(ca.CATEGORY_ORDER)
        assert [r for r in by_category[ca.CATEGORY_ENVELOPE] if r.startswith("ENV-")] == [
            r.rule_id for r in ca.RULES if r.category == ca.CATEGORY_ENVELOPE
        ]
        # Cross-section is its own block on purpose: it caught the most.
        assert len(by_category[ca.CATEGORY_CROSS_SECTION]) >= 8

    def test_rules_command_prints_every_id(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert ca.main(["rules"]) == 0
        printed = capsys.readouterr().out
        for rule in ca.RULES:
            assert rule.rule_id in printed
            assert rule.description in printed


# --------------------------------------------------------------------------
# ENV-001 .. ENV-018
# --------------------------------------------------------------------------


class TestEnvelopeRules:
    def test_env001_wrong_schema_version(self) -> None:
        export = make_export()
        export["schema_version"] = "1.0"
        assert_only(export, "ENV-001")

    def test_env002_completed_before_generated(self) -> None:
        export = make_export()
        export["generated_at"] = "2026-09-26T05:59:00.000000Z"
        export["completed_at"] = "2026-09-26T05:58:00.000000Z"
        assert_only(export, "ENV-002")

    def test_env003_scope_key_set_mismatch(self) -> None:
        export = make_export({"portfolio": _section("portfolio", {})})
        export["scope"] = ["portfolio", "concentration"]
        assert_only(export, "ENV-003")

    def test_env003_scope_order_mismatch_keeps_the_set_equal(self) -> None:
        export = make_export(
            {
                "a_one": _section("a_one", {}),
                "b_two": _section("b_two", {}),
            }
        )
        export["sections"] = {
            "b_two": export["sections"]["b_two"],
            "a_one": export["sections"]["a_one"],
        }
        export["scope"] = ["a_one", "b_two"]
        messages = [f.message for f in find_for(export, "ENV-003")]
        assert any("order" in m for m in messages)

    def test_env004_unknown_section_status(self) -> None:
        export = make_export({"portfolio": _section("portfolio", {}, status="ok")})
        assert_only(export, "ENV-004")

    def test_env005_not_requested_literal(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["data"]["upstream_status"] = "not_requested"
        assert_only(export, "ENV-005")

    def test_env005_not_requested_as_a_key(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["not_requested"] = True
        assert_only(export, "ENV-005")

    def test_env006_null_error_omitted_is_clean(self) -> None:
        export = make_export()
        assert "error" not in export["sections"]["portfolio"]

    def test_env006_null_error_fails_at_any_depth(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["data"]["nested"] = {"deeper": {"error": None}}
        assert_only(export, "ENV-006")

    def test_env007_data_status_using_a_coverage_word(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["data"]["data_status"] = "complete"
        assert_only(export, "ENV-007")

    def test_env008_coverage_status_vocabulary(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["data"]["history_coverage"] = {
            "status": "mostly_there",
            "covered_tickers": [],
            "missing_tickers": [],
        }
        assert_only(export, "ENV-008")

    def test_env008_india_style_component_coverage_is_not_a_coverage_block(self) -> None:
        """``status`` on a component_coverage entry is the DATA axis."""
        export = make_export()
        export["sections"]["portfolio"]["data"]["component_coverage"] = {
            "institutional_flows": {
                "scope": "market_wide",
                "status": "unavailable",
                "coverage_status": "unknown",
                "missing_categories": ["DII", "FII"],
            }
        }
        assert rule_ids(export) == set()

    def test_env009_weight_basis_without_missing_tickers(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["data"]["history_coverage"] = {
            "covered_tickers": ["AAA.NS"],
            "missing_tickers": [],
            "weight_basis": ca.CANONICAL_WEIGHT_BASIS,
        }
        assert_only(export, "ENV-009")

    def test_env009_non_canonical_weight_basis_literal(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["data"]["history_coverage"] = {
            "covered_tickers": ["AAA.NS"],
            "missing_tickers": ["BBB.NS"],
            "weight_basis": "sector_weight_basis_v2",
        }
        assert_only(export, "ENV-009")

    def test_env010_covered_and_missing_do_not_partition_requested(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["data"]["history_coverage"] = {
            "requested_tickers": ["AAA.NS", "BBB.NS", "CCC.NS"],
            "covered_tickers": ["AAA.NS"],
            "missing_tickers": ["BBB.NS"],
        }
        assert_only(export, "ENV-010")

    def test_env010_covered_out_of_request_order(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["data"]["history_coverage"] = {
            "requested_tickers": ["AAA.NS", "BBB.NS"],
            "covered_tickers": ["BBB.NS", "AAA.NS"],
            "missing_tickers": [],
        }
        assert_only(export, "ENV-010")

    def test_env011_available_outside_requested(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["data"]["history_coverage"] = {
            "requested_tickers": ["AAA.NS"],
            "available_tickers": ["AAA.NS", "ZZZ.NS"],
            "covered_tickers": ["AAA.NS"],
            "missing_tickers": [],
        }
        assert_only(export, "ENV-011")

    def test_env011_raw_available_tickers_documents_the_extras(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["data"]["history_coverage"] = {
            "requested_tickers": ["AAA.NS"],
            "available_tickers": ["AAA.NS", "ZZZ.NS"],
            "raw_available_tickers": ["AAA.NS", "ZZZ.NS"],
            "covered_tickers": ["AAA.NS"],
            "missing_tickers": [],
        }
        assert rule_ids(export) == set()

    def test_env012_as_of_inside_the_collection_window(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["as_of"] = "2026-09-26T05:58:00.000000Z"
        assert_only(export, "ENV-012")

    def test_env012_refresh_timestamp_disclosed_in_warnings(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["as_of"] = "2026-09-26T05:58:00.000000Z"
        export["sections"]["portfolio"]["warnings"] = [
            "as_of is a quote REFRESH timestamp, not an observation date"
        ]
        assert rule_ids(export) == set()

    def test_env013_null_as_of_with_dated_payload(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["as_of"] = None
        export["sections"]["portfolio"]["as_of_semantics"] = None
        export["sections"]["portfolio"]["data"]["latest_observation_date"] = "2026-09-25"
        assert_only(export, "ENV-013")

    def test_env013_null_as_of_with_only_a_requested_range_is_clean(self) -> None:
        """``data_range`` is a request, not an observation, so it does not count."""
        export = make_export()
        export["sections"]["portfolio"]["as_of"] = None
        export["sections"]["portfolio"]["as_of_semantics"] = None
        export["sections"]["portfolio"]["data"]["data_range"] = {
            "start": "2026-08-27",
            "end": "2026-09-26",
        }
        assert rule_ids(export) == set()

    def test_env014_as_of_without_semantics(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["as_of_semantics"] = ""
        assert_only(export, "ENV-014")

    def test_env015_money_without_a_declared_currency(self) -> None:
        export = make_export(
            {"liquidity": _section("liquidity", {"currency": "INR"}, currency=None)}
        )
        assert_only(export, "ENV-015")

    def test_env015_declared_currency_passes(self) -> None:
        export = make_export(
            {"liquidity": _section("liquidity", {"currency": "INR"}, currency="INR")}
        )
        assert rule_ids(export) == set()

    def test_env015_weightless_section_may_leave_currency_null(self) -> None:
        export = make_export(
            {
                "factor_exposure": _section(
                    "factor_exposure",
                    {
                        "r_squared": 0.65,
                        "model_window": {"start": "2026-01-20", "end": "2026-09-25"},
                        "model_observation_count": 174,
                    },
                    currency=None,
                )
            }
        )
        assert rule_ids(export) == set()

    def test_env016_partial_section_with_no_warning(self) -> None:
        export = make_export(
            {"pairs": _section("pairs", {}, status="partial", warnings=[])}
        )
        assert_only(export, "ENV-016")

    def test_env016_unavailable_section_with_no_warning(self) -> None:
        export = make_export(
            {"pairs": _section("pairs", {}, status="unavailable", warnings=[])}
        )
        assert_only(export, "ENV-016")

    def test_env017_nan_anywhere(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["data"]["ratio"] = float("nan")
        assert_only(export, "ENV-017")

    def test_env017_bare_nan_token_in_the_bytes(self) -> None:
        """``json.loads`` accepts bare NaN, so only the strict re-parse catches it."""
        raw = '{"schema_version": "2.0", "ratio": NaN}'
        export = ca.Export(doc=json.loads(raw), raw=raw)
        export.strict_error = "non-finite JSON constant 'NaN'"
        assert {f.rule_id for f in ca.env_017_strict_finite_json(export)} == {"ENV-017"}
        assert any("not strict JSON" in f.message for f in ca.env_017_strict_finite_json(export))
        assert any("non-finite" in f.message for f in ca.env_017_strict_finite_json(export))

    def test_env017_infinity_token_is_strict_json_rejected(self) -> None:
        raw = '{"a": Infinity}'
        with pytest.raises(ValueError):
            ca._strict_loads(raw)

    def test_env018_duplicate_object_keys(self) -> None:
        raw = '{"a": 1, "a": 2}'
        duplicates: list[tuple[str, str]] = []

        def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            seen: set[str] = set()
            for key, _ in pairs:
                if key in seen:
                    duplicates.append(("<document>", key))
                seen.add(key)
            return dict(pairs)

        json.loads(raw, object_pairs_hook=hook)
        export = ca.Export(doc={"a": 2}, raw=raw, duplicate_keys=tuple(duplicates))
        assert [f.rule_id for f in ca.env_018_no_duplicate_keys(export)] == ["ENV-018"]


# --------------------------------------------------------------------------
# XS-001 .. XS-009
# --------------------------------------------------------------------------


def _holding_block(
    *,
    covered_days: int = 39,
    scope: str = "holding_window_aligned_return_rows",
    start: str = "2026-08-03",
) -> dict[str, Any]:
    return {
        "intersection_start": start,
        "covered_days": covered_days,
        "covered_days_scope": scope,
    }


class TestCrossSectionRules:
    def test_xs001_holding_window_agreement(self) -> None:
        sections = {
            "realized_risk": _section("realized_risk", {"history_coverage": _holding_block()}),
            "tear_sheet": _section(
                "tear_sheet",
                {
                    "history_coverage": _holding_block(
                        covered_days=39, scope="portfolio_return_observations"
                    )
                },
            ),
        }
        assert rule_ids(make_export(sections)) == set()

    def test_xs001_disagreeing_covered_days(self) -> None:
        sections = {
            "realized_risk": _section("realized_risk", {"history_coverage": _holding_block()}),
            "tear_sheet": _section(
                "tear_sheet", {"history_coverage": _holding_block(covered_days=31)}
            ),
        }
        assert_only(make_export(sections), "XS-001")

    def test_xs001_disagreeing_intersection_start(self) -> None:
        sections = {
            "realized_risk": _section("realized_risk", {"history_coverage": _holding_block()}),
            "tear_sheet": _section(
                "tear_sheet",
                {"history_coverage": _holding_block(start="2026-07-01")},
            ),
        }
        assert_only(make_export(sections), "XS-001")

    def test_xs001_model_window_is_not_compared_with_the_holding_window(self) -> None:
        """A 174-observation model window legitimately disagrees with 39."""
        sections = {
            "factor_exposure": _section(
                "factor_exposure",
                {
                    "history_coverage": _holding_block(
                        covered_days=174, scope="model_return_observations"
                    )
                },
            ),
            "tear_sheet": _section("tear_sheet", {"history_coverage": _holding_block()}),
        }
        assert rule_ids(make_export(sections)) == set()

    def test_xs002_covered_days_without_a_scope_catches_d01(self) -> None:
        block = _holding_block()
        del block["covered_days_scope"]
        export = make_export({"realized_risk": _section("realized_risk", {"history_coverage": block})})
        assert_only(export, "XS-002")

    def test_xs002_empty_scope_string_is_still_a_failure(self) -> None:
        block = _holding_block(scope="")
        export = make_export({"realized_risk": _section("realized_risk", {"history_coverage": block})})
        assert_only(export, "XS-002")

    def test_xs003_effective_start_without_provenance(self) -> None:
        export = make_export(
            {"realized_risk": _section("realized_risk", {"history_coverage": {"effective_start": "2026-08-03"}})}
        )
        assert_only(export, "XS-003")

    def test_xs003_inferred_start_without_the_stored_date(self) -> None:
        export = make_export(
            {
                "realized_risk": _section(
                    "realized_risk",
                    {
                        "history_coverage": {
                            "effective_start": "2026-06-01",
                            "analytics_start_source": "buy_price_inferred",
                        }
                    },
                )
            }
        )
        assert_only(export, "XS-003")

    def test_xs003_provenance_prose_is_not_a_date(self) -> None:
        """``holding_date_provenance`` publishes prose UNDER an effective_start key."""
        export = make_export(
            {
                "portfolio": _section(
                    "portfolio",
                    {"holding_date_provenance": {"effective_start": "the earliest valid added_on"}},
                )
            }
        )
        assert rule_ids(export) == set()

    def test_xs004_stored_source_contradicting_the_stored_date(self) -> None:
        export = make_export(
            {
                "realized_risk": _section(
                    "realized_risk",
                    {
                        "history_coverage": {
                            "tickers": {
                                "AAA.NS": {
                                    "analytics_start": "2026-01-01",
                                    "stored_added_on": "2026-05-05",
                                    "analytics_start_source": "stored_added_on",
                                }
                            }
                        }
                    },
                )
            }
        )
        assert_only(export, "XS-004")

    def test_xs004_inferred_start_with_its_stored_date_passes(self) -> None:
        export = make_export(
            {
                "realized_risk": _section(
                    "realized_risk",
                    {
                        "history_coverage": {
                            "tickers": {
                                "AAA.NS": {
                                    "analytics_start": "2026-01-01",
                                    "stored_added_on": "2026-05-05",
                                    "buy_price_inferred": "2026-01-01",
                                    "analytics_start_source": "buy_price_inferred",
                                }
                            }
                        }
                    },
                )
            }
        )
        assert rule_ids(export) == set()

    def test_xs005_reconcilable_counts_pass(self) -> None:
        export = make_export(
            {
                "realized_risk": _section(
                    "realized_risk",
                    {
                        "history_coverage": {
                            "tickers": {
                                "AAA.NS": {
                                    "raw_days": 100,
                                    "masked_days": 39,
                                    "return_observations": 37,
                                }
                            }
                        }
                    },
                )
            }
        )
        assert rule_ids(export) == set()

    def test_xs005_mixed_units_catch_d02(self) -> None:
        export = make_export(
            {
                "realized_risk": _section(
                    "realized_risk",
                    {
                        "history_coverage": {
                            "tickers": {
                                "AAA.NS": {
                                    "raw_days": 108,
                                    "masked_days": 23,
                                    "return_observations": 20,
                                }
                            }
                        }
                    },
                )
            }
        )
        assert_only(export, "XS-005")

    def test_xs005_declared_count_units_excuse_the_gap(self) -> None:
        export = make_export(
            {
                "realized_risk": _section(
                    "realized_risk",
                    {
                        "history_coverage": {
                            "per_ticker_count_units": {
                                "masked_days": "price rows after the mask",
                                "return_observations": "return rows",
                            },
                            "tickers": {
                                "AAA.NS": {
                                    "raw_days": 172,
                                    "masked_days": 39,
                                    "return_observations": 171,
                                }
                            },
                        }
                    },
                )
            }
        )
        assert rule_ids(export) == set()

    def test_xs005_masked_exceeding_raw_is_caught(self) -> None:
        export = make_export(
            {
                "realized_risk": _section(
                    "realized_risk",
                    {
                        "history_coverage": {
                            "tickers": {
                                "AAA.NS": {
                                    "raw_days": 10,
                                    "masked_days": 39,
                                    "return_observations": 37,
                                }
                            }
                        }
                    },
                )
            }
        )
        assert_only(export, "XS-005")

    def test_xs006_full_history_without_a_scope(self) -> None:
        export = make_export(
            {
                "tear_sheet": _section(
                    "tear_sheet",
                    {
                        "full_history": {
                            "observation_count": 174,
                            "window": {"start": "2026-01-20", "end": "2026-09-25"},
                        }
                    },
                )
            }
        )
        assert_only(export, "XS-006")

    def test_xs006_full_history_without_a_window(self) -> None:
        export = make_export(
            {
                "tear_sheet": _section(
                    "tear_sheet",
                    {"full_history": {"scope": "full_exchange_history", "observation_count": 174}},
                )
            }
        )
        assert_only(export, "XS-006")

    def test_xs006_complete_full_history_block_passes(self) -> None:
        export = make_export(
            {
                "tear_sheet": _section(
                    "tear_sheet",
                    {
                        "full_history": {
                            "scope": "full_exchange_history",
                            "observation_count": 174,
                            "window": {"start": "2026-01-20", "end": "2026-09-25"},
                        }
                    },
                )
            }
        )
        assert rule_ids(export) == set()

    def test_xs007_conditional_coverage_using_the_holding_pool(self) -> None:
        export = make_export(
            {
                "regime": _section(
                    "regime",
                    {
                        "portfolio_in_current_regime": {
                            "history_coverage": {
                                "conditional": True,
                                "observations": 19,
                                "covered_days": 39,
                                "covered_days_scope": "conditional_regime_return_days",
                            }
                        }
                    },
                )
            }
        )
        assert_only(export, "XS-007")

    def test_xs007_conditional_block_claiming_the_holding_scope(self) -> None:
        export = make_export(
            {
                "regime": _section(
                    "regime",
                    {
                        "portfolio_in_current_regime": {
                            "history_coverage": {
                                "conditional": True,
                                "observations": 19,
                                "covered_days": 19,
                                "covered_days_scope": "holding_window_aligned_return_rows",
                            }
                        }
                    },
                )
            }
        )
        assert_only(export, "XS-007")

    def test_xs007_conditional_sample_agrees(self) -> None:
        export = make_export(
            {
                "regime": _section(
                    "regime",
                    {
                        "portfolio_in_current_regime": {
                            "history_coverage": {
                                "conditional": True,
                                "observations": 19,
                                "covered_days": 19,
                                "covered_days_scope": "conditional_regime_return_days",
                            }
                        }
                    },
                )
            }
        )
        assert rule_ids(export) == set()

    def test_xs008_composite_reading_complete_beside_an_unavailable_component(self) -> None:
        export = make_export(
            {
                "india_flows": _section(
                    "india_flows",
                    {
                        "component_status": {
                            "institutional_flows": "unavailable",
                            "liquidity_limits": "available",
                        }
                    },
                    coverage={"status": "complete", "covered_tickers": [], "missing_tickers": []},
                )
            }
        )
        assert_only(export, "XS-008")

    def test_xs008_composite_naming_its_components_passes(self) -> None:
        export = make_export(
            {
                "india_flows": _section(
                    "india_flows",
                    {
                        "component_status": {
                            "institutional_flows": "unavailable",
                            "liquidity_limits": "available",
                        },
                        "coverage_status": "partial",
                        "coverage_notes": ["section coverage is the liquidity component"],
                    },
                    coverage={
                        "status": "complete",
                        "source_component": "liquidity_limits",
                        "covered_tickers": [],
                        "missing_tickers": [],
                    },
                )
            }
        )
        assert rule_ids(export) == set()

    def test_xs009_r_squared_without_a_window_catches_d06(self) -> None:
        export = make_export(
            {
                "dashboard": _section(
                    "dashboard",
                    {"components": {"risk_score": {"factor_r_squared": 0.2391}}},
                    status="partial",
                    warnings=["risk score component"],
                )
            }
        )
        assert_only(export, "XS-009")

    def test_xs009_r_squared_with_a_window_and_observation_count_passes(self) -> None:
        export = make_export(
            {
                "factor_exposure": _section(
                    "factor_exposure",
                    {
                        "r_squared": 0.6511,
                        "model_window": {"start": "2026-01-20", "end": "2026-09-25"},
                        "model_observation_count": 174,
                    },
                )
            }
        )
        assert rule_ids(export) == set()

    def test_xs009_two_fits_over_different_windows_do_not_contradict(self) -> None:
        """A 174-observation full-history fit and a 39-observation holding-window
        fit are EXPECTED to disagree — that difference is the disclosure working.
        Flagging it would force a real disclosure to be deleted to silence the
        check, or worse, invite fabricating one fit to match the other."""
        export = make_export(
            {
                "factor_exposure": _section(
                    "factor_exposure",
                    {
                        "r_squared": 0.6511,
                        "model_window": {"start": "2026-01-20", "end": "2026-09-25"},
                        "model_observation_count": 174,
                        "full_history": {
                            "observation_count": 174,
                            "window": {"start": "2026-01-20", "end": "2026-09-25"},
                            "scope": "full_exchange_history",
                        },
                    },
                ),
                "dashboard": _section(
                    "dashboard",
                    {
                        "components": {
                            "risk_score": {
                                "factor_r_squared": 0.2391,
                                "model_window": {
                                    "start": "2026-08-04",
                                    "end": "2026-09-25",
                                },
                                "model_observation_count": 39,
                                "factor_model": {
                                    "basis": "holding_window_current_composition"
                                },
                            }
                        }
                    },
                    status="partial",
                    warnings=["risk score component"],
                ),
            }
        )
        assert rule_ids(export) == set()

    def test_xs009_two_fits_claiming_the_same_basis_and_disagreeing_catches(self) -> None:
        """Same declared window, same count, same basis, different value: at least
        one of them is wrong, and that is a genuine contradiction."""
        shared = {
            "model_window": {"start": "2026-01-20", "end": "2026-09-25"},
            "model_observation_count": 174,
            "factor_model": {"basis": "full_exchange_history"},
        }
        export = make_export(
            {
                "factor_exposure": _section(
                    "factor_exposure",
                    {
                        **shared,
                        "r_squared": 0.6511,
                        "full_history": {
                            "observation_count": 174,
                            "scope": "full_exchange_history",
                            "window": {"start": "2026-01-20", "end": "2026-09-25"},
                        },
                    },
                ),
                "dashboard": _section(
                    "dashboard",
                    {"components": {"risk_score": {**shared, "factor_r_squared": 0.2391}}},
                    status="partial",
                    warnings=["risk score component"],
                ),
            }
        )
        assert_only(export, "XS-009")


# --------------------------------------------------------------------------
# NUM-001 .. NUM-020
# --------------------------------------------------------------------------


class TestNumericRules:
    def test_num001_market_values_not_summing_to_total(self) -> None:
        export = make_export(
            {
                "portfolio": _section(
                    "portfolio",
                    {
                        "total_value": 300.0,
                        "positions": [
                            {"market_value": 100.0, "weight": 0.5},
                            {"market_value": 100.0, "weight": 0.5},
                        ],
                    },
                    currency="INR",
                )
            }
        )
        assert_only(export, "NUM-001")

    def test_num001_weights_not_summing_to_one(self) -> None:
        export = make_export(
            {
                "portfolio": _section(
                    "portfolio",
                    {
                        "total_value": 200.0,
                        "positions": [
                            {"market_value": 100.0, "weight": 0.4},
                            {"market_value": 100.0, "weight": 0.4},
                        ],
                    },
                    currency="INR",
                )
            }
        )
        assert_only(export, "NUM-001")

    def test_num001_balanced_portfolio_passes(self) -> None:
        export = make_export(
            {
                "portfolio": _section(
                    "portfolio",
                    {
                        "total_value": 200.0,
                        "positions": [
                            {"market_value": 100.0, "weight": 0.5},
                            {"market_value": 100.0, "weight": 0.5},
                        ],
                    },
                    currency="INR",
                )
            }
        )
        assert rule_ids(export) == set()

    def test_num002_published_total_must_equal_the_sum(self) -> None:
        export = make_export(
            {
                "concentration": _section(
                    "concentration",
                    {
                        "by_sector": {"Tech": 0.6, "Energy": 0.3},
                        "by_sector_published_total": 1.0,
                        "by_sector_rounding_residual": 0.0,
                        "by_sector_rounding_decimals": 4,
                    },
                )
            }
        )
        assert_only(export, "NUM-002")

    def test_num002_residual_must_equal_one_minus_total(self) -> None:
        export = make_export(
            {
                "concentration": _section(
                    "concentration",
                    {
                        "by_sector": {"Tech": 0.6, "Energy": 0.3999},
                        "by_sector_published_total": 0.9999,
                        "by_sector_rounding_residual": 0.0,
                        "by_sector_rounding_decimals": 4,
                    },
                )
            }
        )
        assert_only(export, "NUM-002")

    def test_num002_sector_weights_renormalized_to_one(self) -> None:
        """Forcing 1.0 with no declared rounding is the defect."""
        export = make_export(
            {
                "concentration": _section(
                    "concentration",
                    {
                        "by_sector": {"Tech": 0.5, "Energy": 0.5},
                        "by_sector_published_total": 0.9994,
                        "by_sector_rounding_residual": 0.0006,
                        "by_sector_rounding_decimals": 0,
                    },
                )
            }
        )
        assert_only(export, "NUM-002")

    def test_num002_declared_rounding_residual_passes(self) -> None:
        export = make_export(
            {
                "concentration": _section(
                    "concentration",
                    {
                        "by_sector": {"Tech": 0.5555, "Energy": 0.4439},
                        "by_sector_published_total": 0.9994,
                        "by_sector_rounding_residual": 0.0006,
                        "by_sector_rounding_decimals": 4,
                    },
                )
            }
        )
        assert rule_ids(export) == set()

    def test_num003_contributions_without_a_unit(self) -> None:
        export = make_export(
            {
                "risk_contribution": _section(
                    "risk_contribution",
                    {
                        "contribution_basis": {"per_model": {}},
                        "positions": {},
                    },
                )
            }
        )
        assert_only(export, "NUM-003")

    def test_num003_contributions_not_summing_to_one(self) -> None:
        export = make_export(
            {
                "risk_contribution": _section(
                    "risk_contribution",
                    {
                        "contribution_basis": {
                            "unit": "fraction_of_portfolio_risk",
                            "per_model": {
                                "volatility": {"published_total": 0.8, "rounding_residual": 0.2}
                            },
                        },
                        "positions": {"volatility": {"AAA.NS": 0.8}},
                    },
                )
            }
        )
        assert_only(export, "NUM-003")

    def test_num003_published_total_must_match_the_published_legs(self) -> None:
        export = make_export(
            {
                "risk_contribution": _section(
                    "risk_contribution",
                    {
                        "contribution_basis": {
                            "unit": "fraction_of_portfolio_risk",
                            "per_model": {
                                "volatility": {"published_total": 1.0, "rounding_residual": 0.0}
                            },
                        },
                        "positions": {"volatility": {"AAA.NS": 0.4, "BBB.NS": 0.4}},
                    },
                )
            }
        )
        assert_only(export, "NUM-003")

    def test_num003_consistent_contributions_pass(self) -> None:
        export = make_export(
            {
                "risk_contribution": _section(
                    "risk_contribution",
                    {
                        "contribution_basis": {
                            "unit": "fraction_of_portfolio_risk",
                            "per_model": {
                                "volatility": {"published_total": 1.0, "rounding_residual": 0.0}
                            },
                        },
                        "positions": {"volatility": {"AAA.NS": 0.4, "BBB.NS": 0.6}},
                    },
                )
            }
        )
        assert rule_ids(export) == set()

    def _liquidity(self, **overrides: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "data_status": "available",
            "overall_score": 8.0,
            "overall_band": "High",
            "scoring": {
                "bands": [
                    {"band": "High", "min_published_score": 8.0, "max_published_score": None},
                    {"band": "Medium", "min_published_score": 6.0, "max_published_score": 8.0},
                    {"band": "Low", "min_published_score": None, "max_published_score": 6.0},
                ]
            },
            "by_position": {
                "AAA.NS": {"score": 8.0, "category": "High", "market_cap_provenance": "measured"},
                "BBB.NS": {"score": 6.0, "category": "Medium", "market_cap_provenance": "measured"},
            },
        }
        data.update(overrides)
        return make_export({"liquidity": _section("liquidity", data, currency="INR")})

    def test_num004_category_disagrees_with_the_recomputed_band(self) -> None:
        export = self._liquidity()
        export["sections"]["liquidity"]["data"]["by_position"]["AAA.NS"]["category"] = "Medium"
        assert_only(export, "NUM-004")

    def test_num004_overall_band_disagrees_with_the_recomputed_band(self) -> None:
        export = self._liquidity(overall_score=8.0, overall_band="Low")
        assert_only(export, "NUM-004")

    def test_num004_consistent_bands_pass(self) -> None:
        assert rule_ids(self._liquidity()) == set()

    def test_num005_unavailable_liquidity_with_a_mid_score(self) -> None:
        export = self._liquidity(data_status="unavailable", risk_level="Low")
        assert_only(export, "NUM-005")

    def test_num005_unavailable_liquidity_with_null_score_passes(self) -> None:
        export = self._liquidity(
            data_status="unavailable", overall_score=None, risk_level=None
        )
        assert rule_ids(export) == set()

    def test_num006_estimated_market_caps_undisclosed_catches_d03(self) -> None:
        export = self._liquidity()
        export["sections"]["liquidity"]["data"]["by_position"]["BBB.NS"][
            "market_cap_provenance"
        ] = "fallback"
        assert_only(export, "NUM-006")

    def test_num006_disclosed_count_clears_the_finding(self) -> None:
        export = self._liquidity(estimated_market_cap_count=1)
        export["sections"]["liquidity"]["data"]["by_position"]["BBB.NS"][
            "market_cap_provenance"
        ] = "fallback"
        assert rule_ids(export) == set()

    def test_num006_wrong_disclosed_count_still_fails(self) -> None:
        export = self._liquidity(estimated_market_cap_count=7)
        export["sections"]["liquidity"]["data"]["by_position"]["BBB.NS"][
            "market_cap_provenance"
        ] = "fallback"
        assert_only(export, "NUM-006")

    def test_num006_demoted_to_partial_with_a_warning_clears_the_finding(self) -> None:
        export = self._liquidity(data_status="partial", warnings=["one cap is a floor"])
        export["sections"]["liquidity"]["data"]["by_position"]["BBB.NS"][
            "market_cap_provenance"
        ] = "fallback"
        assert rule_ids(export) == set()

    def _stress(self, **overrides: Any) -> dict[str, Any]:
        row = {
            "scenario": "Market Crash",
            "portfolio_impact": -0.4742,
            "max_drawdown": -0.5453,
            "max_drawdown_basis": "derived_from_shock_proxy",
        }
        row.update(overrides)
        return make_export({"stress_testing": _section("stress_testing", {"scenarios": {"Market Crash": row}})})

    def test_num007_drawdown_not_the_declared_identity(self) -> None:
        assert_only(self._stress(max_drawdown=-0.60), "NUM-007")

    def test_num007_drawdown_without_a_basis(self) -> None:
        assert_only(self._stress(max_drawdown_basis=""), "NUM-007")

    def test_num007_consistent_scenario_passes(self) -> None:
        assert rule_ids(self._stress()) == set()

    def _sizing(self, trade_overrides: dict[str, Any] | None = None,
                 reconciliation: dict[str, Any] | None = None) -> dict[str, Any]:
        trade = {
            "shares_delta": 2,
            "amount": 2349.21,
            "sizing_price": 1384.0999755859375,
            "rounding_residual": -418.99,
            "rounding_tolerance": 692.05,
            "status": "executable",
        }
        trade.update(trade_overrides or {})
        data: dict[str, Any] = {
            "data_status": "available",
            "sizing_basis": {"sizing_price": {"AAA.NS": 1384.0999755859375}},
            "trades": {"AAA.NS": trade},
        }
        if reconciliation is not None:
            data["trade_reconciliation"] = reconciliation
        return make_export(
            {"volatility_sizing": _section("volatility_sizing", data, currency="INR")}
        )

    def test_num008_amount_not_reconciling_to_shares_times_price(self) -> None:
        export = self._sizing(trade_overrides={"amount": 9999.0})
        assert_only(export, "NUM-008")

    def test_num008_priced_trade_without_a_residual(self) -> None:
        trade = {
            "shares_delta": 2,
            "amount": 2768.2,
            "sizing_price": 1384.0999755859375,
            "rounding_tolerance": 692.05,
            "status": "executable",
        }
        export = make_export(
            {
                "volatility_sizing": _section(
                    "volatility_sizing",
                    {
                        "sizing_basis": {"sizing_price": {"AAA.NS": 1384.0999755859375}},
                        "trades": {"AAA.NS": trade},
                    },
                    currency="INR",
                )
            }
        )
        assert_only(export, "NUM-008")

    def test_num008_reconciling_trade_passes(self) -> None:
        assert rule_ids(self._sizing()) == set()

    def test_num009_unlabelled_zero_share_trade(self) -> None:
        export = self._sizing(
            trade_overrides={"shares_delta": 0, "amount": -1109.62, "status": "executable"}
        )
        assert_only(export, "NUM-009")

    def test_num009_labelled_zero_share_trade_preserves_its_notional(self) -> None:
        export = self._sizing(
            trade_overrides={
                "shares_delta": None,
                "amount": -1109.62,
                "status": "below_minimum_notional",
            }
        )
        assert rule_ids(export) == set()

    def test_num009_zero_amount_with_real_shares_is_caught(self) -> None:
        export = self._sizing(trade_overrides={"amount": 0, "rounding_residual": -2768.2})
        assert_only(export, "NUM-009")

    def test_num010_max_tolerance_is_not_the_maximum(self) -> None:
        export = self._sizing(
            reconciliation={
                "max_abs_rounding_residual": 418.99,
                "max_abs_rounding_residual_ticker": "AAA.NS",
                "max_abs_rounding_residual_scope": "all_priced_trades_with_a_sizing_price",
                "max_rounding_tolerance": 11.77,
                "max_rounding_tolerance_ticker": "AAA.NS",
                "max_rounding_tolerance_scope": "all_priced_trades_with_a_sizing_price",
            }
        )
        assert_only(export, "NUM-010")

    def test_num010_named_max_ticker_is_not_the_argmax(self) -> None:
        export = self._sizing(
            reconciliation={
                "max_abs_rounding_residual": 418.99,
                "max_abs_rounding_residual_ticker": "ZZZ.NS",
                "max_abs_rounding_residual_scope": "all_priced_trades_with_a_sizing_price",
                "max_rounding_tolerance": 692.05,
                "max_rounding_tolerance_ticker": "AAA.NS",
                "max_rounding_tolerance_scope": "all_priced_trades_with_a_sizing_price",
            }
        )
        assert_only(export, "NUM-010")

    def test_num010_maxima_over_different_populations(self) -> None:
        export = self._sizing(
            reconciliation={
                "max_abs_rounding_residual": 418.99,
                "max_abs_rounding_residual_ticker": "AAA.NS",
                "max_abs_rounding_residual_scope": "all_priced_trades_with_a_sizing_price",
                "max_rounding_tolerance": 692.05,
                "max_rounding_tolerance_ticker": "AAA.NS",
                "max_rounding_tolerance_scope": "only_trades_above_the_notional_floor",
            }
        )
        assert_only(export, "NUM-010")

    def test_num010_consistent_reconciliation_passes(self) -> None:
        export = self._sizing(
            reconciliation={
                "max_abs_rounding_residual": 418.99,
                "max_abs_rounding_residual_ticker": "AAA.NS",
                "max_abs_rounding_residual_scope": "all_priced_trades_with_a_sizing_price",
                "max_rounding_tolerance": 692.05,
                "max_rounding_tolerance_ticker": "AAA.NS",
                "max_rounding_tolerance_scope": "all_priced_trades_with_a_sizing_price",
            }
        )
        assert rule_ids(export) == set()

    def _optimizer(self, **overrides: Any) -> dict[str, Any]:
        normalization = {
            "normalization_rule": "divide_all_legs_by_gross_exposure",
            "submitted_gross_exposure_measured": 0.999998,
            "gross_exposure": 1.0,
            "gross_exposure_residual": -2e-06,
            "financing_required": False,
            "financing_required_basis": "unrounded_submitted_gross_exposure",
        }
        normalization.update(overrides.pop("normalization", {}))
        data: dict[str, Any] = {
            "data_status": "available",
            "weights": {"AAA.NS": 0.5, "BBB.NS": 0.499998},
            "weight_normalization": normalization,
            "trades_required": {
                "AAA.NS": {
                    "current_weight": 0.4,
                    "recommended_weight": 0.5,
                    "weight_delta": 0.1,
                }
            },
        }
        data.update(overrides)
        return make_export({"optimization": _section("optimization", data)})

    def test_num011_weight_delta_drift(self) -> None:
        export = self._optimizer()
        export["sections"]["optimization"]["data"]["trades_required"]["AAA.NS"][
            "weight_delta"
        ] = 0.11
        assert_only(export, "NUM-011")

    def test_num011_closing_weight_delta_passes(self) -> None:
        assert rule_ids(self._optimizer()) == set()

    def test_num012_missing_gross_exposure_residual(self) -> None:
        """No residual at all: the amount the normalization absorbs is hidden."""
        export = make_export(
            {
                "optimization": _section(
                    "optimization",
                    {
                        "data_status": "available",
                        "weights": {"AAA.NS": 1.0},
                        "weight_normalization": {
                            "submitted_gross_exposure_measured": 0.999998,
                            "gross_exposure": 1.0,
                            "financing_required": False,
                            "financing_required_basis": "unrounded_submitted_gross_exposure",
                        },
                    },
                )
            }
        )
        assert_only(export, "NUM-012")

    def test_num012_residual_not_the_measured_minus_gross(self) -> None:
        assert_only(
            self._optimizer(normalization={"gross_exposure_residual": 0.5}), "NUM-012"
        )

    def test_num012_financing_required_derived_from_a_rounded_figure(self) -> None:
        export = self._optimizer(
            normalization={
                "submitted_gross_exposure_measured": 1.0000004,
                "financing_required": False,
            }
        )
        assert_only(export, "NUM-012")

    def test_num012_financing_required_basis_must_name_the_unrounded_figure(self) -> None:
        export = self._optimizer(normalization={"financing_required_basis": "gross_exposure"})
        assert_only(export, "NUM-012")

    def test_num012_consistent_optimizer_passes(self) -> None:
        assert rule_ids(self._optimizer()) == set()

    def _monte_carlo(self, **overrides: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "data_status": "available",
            "prob_success": 0.37,
            "success_definition": "terminal_wealth_above_target",
            "terminal_percentiles": {"p5": 1.0, "p25": 2.0, "p50": 3.0, "p75": 4.0, "p95": 5.0},
        }
        data.update(overrides)
        return make_export({"monte_carlo": _section("monte_carlo", data, currency="INR")})

    def test_num013_quantiles_out_of_order(self) -> None:
        export = self._monte_carlo(
            terminal_percentiles={"p5": 1.0, "p25": 9.0, "p50": 3.0, "p75": 4.0, "p95": 5.0}
        )
        assert_only(export, "NUM-013")

    def test_num013_fan_row_out_of_order(self) -> None:
        export = self._monte_carlo(
            fan=[{"year": 0.0, "p5": 1.0, "p25": 2.0, "p50": 0.5, "p75": 4.0, "p95": 5.0}]
        )
        assert_only(export, "NUM-013")

    def test_num013_missing_success_definition(self) -> None:
        export = self._monte_carlo()
        del export["sections"]["monte_carlo"]["data"]["success_definition"]
        assert_only(export, "NUM-013")

    def test_num013_consistent_monte_carlo_passes(self) -> None:
        assert rule_ids(self._monte_carlo()) == set()

    def _pairs(self, **overrides: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "data_status": "available",
            "universe_size": 4,
            "scanned_pairs_count": 6,
            "shallow_tickers": [],
            "test_agreement": {
                "agreement_count": 5,
                "disagreement_count": 1,
                "counted_pairs": 6,
            },
        }
        data.update(overrides)
        status = "partial" if overrides.get("shallow_tickers") else "available"
        warnings = ["a leg is shallow"] if status == "partial" else []
        return make_export({"pairs": _section("pairs", data, status=status, warnings=warnings, currency="INR")})

    def test_num014_scanned_count_is_not_the_combination_count(self) -> None:
        assert_only(self._pairs(scanned_pairs_count=5), "NUM-014")

    def test_num014_shallow_leg_must_force_partial(self) -> None:
        export = self._pairs(shallow_tickers=["AAA.NS"])
        export["sections"]["pairs"]["status"] = "available"
        export["sections"]["pairs"]["warnings"] = []
        assert_only(export, "NUM-014")

    def test_num014_missing_agreement_counts(self) -> None:
        export = self._pairs()
        del export["sections"]["pairs"]["data"]["test_agreement"]
        assert_only(export, "NUM-014")

    def test_num014_agreement_counts_that_do_not_add_up(self) -> None:
        assert_only(
            self._pairs(
                test_agreement={
                    "agreement_count": 2,
                    "disagreement_count": 1,
                    "counted_pairs": 6,
                }
            ),
            "NUM-014",
        )

    def test_num014_consistent_pairs_passes(self) -> None:
        assert rule_ids(self._pairs()) == set()

    def _regime(self, **overrides: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "data_status": "available",
            "regime_probabilities": {"calm": 50.0, "bull": 49.9},
            "regime_probabilities_total": 99.9,
            "regime_probabilities_rounding_residual": 0.1,
            "transition_matrix": {"calm": {"calm": 96.0, "bull": 4.0}, "bull": {"calm": 4.0, "bull": 96.0}},
            "transition_matrix_row_residuals": {"calm": 0.0, "bull": 0.0},
            "stability_pct": 96.0,
            "stability_pct_rule": "share of unchanged decoded labels",
            "stability_pct_scope": "full_classification_sample",
        }
        data.update(overrides)
        return make_export({"regime": _section("regime", data)})

    def test_num015_probabilities_without_a_published_total(self) -> None:
        export = self._regime()
        del export["sections"]["regime"]["data"]["regime_probabilities_total"]
        assert_only(export, "NUM-015")

    def test_num015_transition_rows_without_residuals(self) -> None:
        export = self._regime()
        del export["sections"]["regime"]["data"]["transition_matrix_row_residuals"]
        assert_only(export, "NUM-015")

    def test_num015_transition_row_not_summing_to_a_hundred(self) -> None:
        assert_only(
            self._regime(
                transition_matrix={"calm": {"calm": 96.0, "bull": 2.0}},
                transition_matrix_row_residuals={"calm": 0.0},
            ),
            "NUM-015",
        )

    def test_num015_stability_pct_without_its_rule(self) -> None:
        export = self._regime()
        del export["sections"]["regime"]["data"]["stability_pct_rule"]
        assert_only(export, "NUM-015")

    def test_num015_consistent_regime_passes(self) -> None:
        assert rule_ids(self._regime()) == set()

    def _tail(self, matrix: list[list[float]]) -> dict[str, Any]:
        return make_export(
            {
                "risk_studio": _section(
                    "risk_studio",
                    {
                        "components": {
                            "tail_dependence": {
                                "data_status": "available",
                                "tickers": ["AAA.NS", "BBB.NS"],
                                "tail_dependence_matrix": {"tickers": ["AAA.NS", "BBB.NS"], "matrix": matrix},
                            }
                        }
                    },
                )
            }
        )

    def test_num016_asymmetric_matrix(self) -> None:
        assert_only(self._tail([[1.0, 0.2], [0.1, 1.0]]), "NUM-016")

    def test_num016_non_unit_diagonal(self) -> None:
        assert_only(self._tail([[0.9, 0.2], [0.2, 1.0]]), "NUM-016")

    def test_num016_ticker_count_must_match_the_matrix(self) -> None:
        export = self._tail([[1.0, 0.2], [0.2, 1.0]])
        export["sections"]["risk_studio"]["data"]["components"]["tail_dependence"][
            "tail_dependence_matrix"
        ]["tickers"] = ["AAA.NS"]
        assert_only(export, "NUM-016")

    def test_num016_well_formed_matrix_passes(self) -> None:
        assert rule_ids(self._tail([[1.0, 0.2], [0.2, 1.0]])) == set()

    def _evt(self, **overrides: Any) -> dict[str, Any]:
        data: dict[str, Any] = {
            "data_status": "available",
            "evt_pot_var_99": -0.04,
            "gpd_shape_xi": -0.7068,
            "gpd_shape_xi_raw": -0.70676185,
            "gpd_shape_xi_constrained": -0.5,
            "gpd_shape_xi_used": -0.5,
            "gpd_shape_xi_used_basis": "constrained_clip",
        }
        data.update(overrides)
        return make_export({"risk_studio": _section("risk_studio", data)})

    def test_num017_evt_without_a_used_xi(self) -> None:
        export = self._evt()
        del export["sections"]["risk_studio"]["data"]["gpd_shape_xi_used"]
        assert_only(export, "NUM-017")

    def test_num017_used_xi_matching_nothing_published(self) -> None:
        assert_only(self._evt(gpd_shape_xi_used=-0.9), "NUM-017")

    def test_num017_declared_evt_basis_passes(self) -> None:
        assert rule_ids(self._evt()) == set()

    def test_num018_hard_zero_sub_score_catches_d04(self) -> None:
        export = make_export(
            {
                "dashboard": _section(
                    "dashboard",
                    {
                        "components": {
                            "risk_score": {
                                "overall_score": 12.7,
                                "components": {
                                    "concentration": 8.6,
                                    "volatility": 9.8,
                                    "correlation": 0,
                                },
                                "excluded_components": [],
                            }
                        }
                    },
                    status="partial",
                    warnings=["component"],
                )
            }
        )
        assert_only(export, "NUM-018")

    def test_num018_zero_sub_score_listed_as_excluded_passes(self) -> None:
        export = make_export(
            {
                "dashboard": _section(
                    "dashboard",
                    {
                        "components": {
                            "risk_score": {
                                "overall_score": 12.7,
                                "components": {"correlation": 0},
                                "excluded_components": ["correlation"],
                            }
                        }
                    },
                    status="partial",
                    warnings=["component"],
                )
            }
        )
        assert rule_ids(export) == set()

    def test_num018_measured_zero_sub_score_passes(self) -> None:
        """A genuinely uncorrelated portfolio also measures 0 — that is a real
        result, not a floored placeholder. When the payload publishes the
        measurement behind the sub-score, the rule must not fire, or the only
        way to silence it would be to fabricate an epsilon floor."""
        export = make_export(
            {
                "dashboard": _section(
                    "dashboard",
                    {
                        "components": {
                            "risk_score": {
                                "overall_score": 9.0,
                                "components": {
                                    "concentration": 8.6,
                                    "volatility": 9.8,
                                    "correlation": 0,
                                },
                                "avg_pairwise_correlation": 0.0,
                                "excluded_components": [],
                            }
                        }
                    },
                    status="partial",
                    warnings=["component"],
                )
            }
        )
        assert rule_ids(export) == set()

    def _performance(self, rows: list[dict[str, Any]], **component: Any) -> dict[str, Any]:
        performance: dict[str, Any] = {
            "status": "partial",
            "warnings": ["delivered 2 of 90 expected observations"],
            "history_coverage": {
                "requested_days": 90,
                "delivered_start": "2026-08-25",
                "observation_count": len(rows),
                "expected_observation_count": 65,
                "coverage_ratio": 0.31,
                "truncated": True,
                "stale": True,
                "status": "partial",
            },
            "data": rows,
        }
        performance.update(component)
        return make_export(
            {
                "dashboard": _section(
                    "dashboard",
                    {"components": {"performance_history": performance}},
                    status="partial",
                    warnings=["performance window short"],
                )
            }
        )

    def test_num019_first_row_return(self) -> None:
        export = self._performance(
            [
                {"date": "2026-08-25", "portfolio_value": 100.0, "return": 0.001, "benchmark_value": 99.0},
                {"date": "2026-08-26", "portfolio_value": 101.0, "return": 0.01, "benchmark_value": 100.0},
            ]
        )
        assert_only(export, "NUM-019")

    def test_num019_first_row_benchmark_copies_the_portfolio(self) -> None:
        export = self._performance(
            [
                {"date": "2026-08-25", "portfolio_value": 100.0, "benchmark_value": 100.0},
                {"date": "2026-08-26", "portfolio_value": 101.0, "benchmark_value": 100.0},
            ]
        )
        assert_only(export, "NUM-019")

    def test_num019_newest_row_has_no_benchmark(self) -> None:
        export = self._performance(
            [
                {"date": "2026-08-25", "portfolio_value": 100.0, "benchmark_value": 99.0},
                {"date": "2026-08-26", "portfolio_value": 101.0},
            ]
        )
        assert_only(export, "NUM-019")

    def test_num019_well_formed_series_passes(self) -> None:
        export = self._performance(
            [
                {"date": "2026-08-25", "portfolio_value": 100.0, "benchmark_value": 99.0},
                {"date": "2026-08-26", "portfolio_value": 101.0, "return": 0.01, "benchmark_value": 100.0},
            ]
        )
        assert rule_ids(export) == set()

    def test_num020_short_window_reported_as_available(self) -> None:
        export = self._performance(
            [
                {"date": "2026-08-25", "portfolio_value": 100.0, "benchmark_value": 99.0},
                {"date": "2026-08-26", "portfolio_value": 101.0, "benchmark_value": 100.0},
            ],
            status="available",
        )
        export["sections"]["dashboard"]["data"]["components"]["performance_history"][
            "warnings"
        ] = []
        assert_only(export, "NUM-020")

    def test_num020_short_window_without_a_warning(self) -> None:
        export = self._performance(
            [
                {"date": "2026-08-25", "portfolio_value": 100.0, "benchmark_value": 99.0},
                {"date": "2026-08-26", "portfolio_value": 101.0, "benchmark_value": 100.0},
            ]
        )
        export["sections"]["dashboard"]["data"]["components"]["performance_history"][
            "warnings"
        ] = []
        assert_only(export, "NUM-020")

    def test_num020_dashboard_must_reflect_a_short_window(self) -> None:
        export = self._performance(
            [
                {"date": "2026-08-25", "portfolio_value": 100.0, "benchmark_value": 99.0},
                {"date": "2026-08-26", "portfolio_value": 101.0, "benchmark_value": 100.0},
            ]
        )
        export["sections"]["dashboard"]["status"] = "available"
        export["sections"]["dashboard"]["warnings"] = []
        assert_only(export, "NUM-020")

    def test_num020_short_window_correctly_reported_passes(self) -> None:
        export = self._performance(
            [
                {"date": "2026-08-25", "portfolio_value": 100.0, "benchmark_value": 99.0},
                {"date": "2026-08-26", "portfolio_value": 101.0, "benchmark_value": 100.0},
            ]
        )
        assert rule_ids(export) == set()

    def test_num020_holding_window_truncation_is_not_a_short_series(self) -> None:
        """``truncated`` on a holding-window block means clipped, not short."""
        export = make_export(
            {
                "tear_sheet": _section(
                    "tear_sheet",
                    {
                        "history_coverage": {
                            "intersection_start": "2026-08-03",
                            "covered_days": 39,
                            "covered_days_scope": "holding_window_aligned_return_rows",
                            "truncated": True,
                        }
                    },
                )
            }
        )
        assert rule_ids(export) == set()


# --------------------------------------------------------------------------
# diff
# --------------------------------------------------------------------------


def _write(path: Path, doc: dict[str, Any]) -> Path:
    path.write_bytes(json.dumps(doc).encode("utf-8"))
    return path


class TestDiff:
    def test_rerun_differing_only_in_allowlisted_fields_reports_nothing(
        self, tmp_path: Path
    ) -> None:
        base = make_export()
        head = clone(base)
        head["export_id"] = "portfolio-999988887777"
        head["generated_at"] = "2026-09-26T06:10:00.000000Z"
        head["completed_at"] = "2026-09-26T06:11:00.000000Z"
        head["snapshot_consistency"] = "frozen"
        head["sections"]["portfolio"]["generated_at"] = "2026-09-26T06:10:00.000000Z"
        head["sections"]["portfolio"]["as_of"] = "2026-09-26T06:10:00.000000Z"

        base_path = _write(tmp_path / "base.json", base)
        head_path = _write(tmp_path / "head.json", head)
        entries = ca.diff_exports(ca.load_export(base_path), ca.load_export(head_path))
        assert entries == []

    def test_positions_updated_on_is_allowlisted(self, tmp_path: Path) -> None:
        base = make_export()
        head = clone(base)
        base["sections"]["portfolio"]["data"]["positions"] = [
            {"ticker": "AAA.NS", "updated_on": "2026-09-26T05:00:00"}
        ]
        head["sections"]["portfolio"]["data"]["positions"] = [
            {"ticker": "AAA.NS", "updated_on": "2026-09-26T06:00:00"}
        ]
        base_path = _write(tmp_path / "base.json", base)
        head_path = _write(tmp_path / "head.json", head)
        assert ca.diff_exports(ca.load_export(base_path), ca.load_export(head_path)) == []

    def test_a_real_field_change_is_reported_with_old_and_new(
        self, tmp_path: Path
    ) -> None:
        base = make_export()
        head = clone(base)
        base["sections"]["portfolio"]["data"]["total_value"] = 43608.67
        head["sections"]["portfolio"]["data"]["total_value"] = 51234.89
        base_path = _write(tmp_path / "base.json", base)
        head_path = _write(tmp_path / "head.json", head)

        entries = ca.diff_exports(ca.load_export(base_path), ca.load_export(head_path))
        assert len(entries) == 1
        entry = entries[0]
        assert entry.kind == "changed"
        assert entry.path == "sections.portfolio.data.total_value"
        assert entry.old == 43608.67
        assert entry.new == 51234.89

    def test_added_and_removed_paths(self, tmp_path: Path) -> None:
        base = make_export()
        head = clone(base)
        base["sections"]["portfolio"]["data"]["gone"] = 1
        head["sections"]["portfolio"]["data"]["arrived"] = 2
        base_path = _write(tmp_path / "base.json", base)
        head_path = _write(tmp_path / "head.json", head)
        entries = ca.diff_exports(ca.load_export(base_path), ca.load_export(head_path))
        assert {(e.kind, e.path) for e in entries} == {
            ("removed", "sections.portfolio.data.gone"),
            ("added", "sections.portfolio.data.arrived"),
        }

    def test_dict_key_reordering_is_not_a_diff(self, tmp_path: Path) -> None:
        base = make_export()
        head = clone(base)
        base["sections"]["portfolio"]["data"] = {"a": 1, "b": 2}
        head["sections"]["portfolio"]["data"] = {"b": 2, "a": 1}
        base_path = _write(tmp_path / "base.json", base)
        head_path = _write(tmp_path / "head.json", head)
        assert ca.diff_exports(ca.load_export(base_path), ca.load_export(head_path)) == []

    def test_rendered_diff_prints_the_allowlist(self, tmp_path: Path) -> None:
        base = make_export()
        head = clone(base)
        base["sections"]["portfolio"]["data"] = {"total_value": 43608.67}
        head["sections"]["portfolio"]["data"] = {"total_value": 1}
        base_path = _write(tmp_path / "base.json", base)
        head_path = _write(tmp_path / "head.json", head)
        rendered = ca.render_diff(
            ca.load_export(base_path),
            ca.load_export(head_path),
            ca.diff_exports(ca.load_export(base_path), ca.load_export(head_path)),
            summary_only=False, truncate=160, include_volatile=False,
        )
        for entry in ca.VOLATILE_PATTERNS:
            assert entry.label in rendered
            assert entry.why in rendered
        assert "sections.portfolio.data.total_value" in rendered
        assert "old: 43608.67" in rendered
        assert "new: 1" in rendered

    def test_summary_only_omits_the_per_path_lines(self, tmp_path: Path) -> None:
        base = make_export()
        head = clone(base)
        base["sections"]["portfolio"]["data"] = {"total_value": 43608.67}
        head["sections"]["portfolio"]["data"] = {"total_value": 1}
        base_path = _write(tmp_path / "base.json", base)
        head_path = _write(tmp_path / "head.json", head)
        rendered = ca.render_diff(
            ca.load_export(base_path),
            ca.load_export(head_path),
            ca.diff_exports(ca.load_export(base_path), ca.load_export(head_path)),
            summary_only=True, truncate=160, include_volatile=False,
        )
        assert "changed 1" in rendered
        assert "sections.portfolio.data.total_value" not in rendered

    def test_include_volatile_surfaces_the_excluded_changes(self, tmp_path: Path) -> None:
        base = make_export()
        head = clone(base)
        head["export_id"] = "portfolio-changed"
        base_path = _write(tmp_path / "base.json", base)
        head_path = _write(tmp_path / "head.json", head)
        loaded_base, loaded_head = ca.load_export(base_path), ca.load_export(head_path)
        entries = ca.diff_exports(loaded_base, loaded_head, include_volatile=True)
        assert [e.path for e in entries] == ["export_id"]
        assert entries[0].volatile == "export_id"

    def test_diff_command_reports_a_missing_file_without_a_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base_path = _write(tmp_path / "base.json", make_export())
        assert ca.main(["diff", str(base_path), str(tmp_path / "nope.json")]) == 2
        assert "error: head" in capsys.readouterr().err

    def test_diff_command_reports_unreadable_json_without_a_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        base_path = _write(tmp_path / "base.json", make_export())
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert ca.main(["diff", str(base_path), str(bad)]) == 2
        assert "error: head" in capsys.readouterr().err

    def test_diff_command_fail_on_change(self, tmp_path: Path) -> None:
        base = make_export()
        head = clone(base)
        head["sections"]["portfolio"]["data"]["total_value"] = 1
        base_path = _write(tmp_path / "base.json", base)
        head_path = _write(tmp_path / "head.json", head)
        assert ca.main(["diff", str(base_path), str(head_path), "--fail-on-change"]) == 1


# --------------------------------------------------------------------------
# generate -- the mojibake regression
# --------------------------------------------------------------------------


_MOJIBAKE_SENTINEL = "reconciled — not renormalized, “exactly” 1.0"


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class TestGenerate:
    def test_multi_byte_characters_round_trip_byte_for_byte(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The PowerShell Latin-1 regression, as a test.

        ``Invoke-WebRequest`` decodes UTF-8 as Latin-1, so an em dash arrives as
        ``\\u00e2\\u0080\\u0094``.  The whole point of writing BYTES is that the
        exact payload the server sent is the exact payload on disk.
        """
        doc = make_export()
        doc["sections"]["portfolio"]["data"]["methodology"] = _MOJIBAKE_SENTINEL
        raw = json.dumps(doc, ensure_ascii=False).encode("utf-8")
        assert b"\xe2\x80\x94" in raw  # the em dash, as UTF-8 bytes

        def fake_urlopen(request: object, timeout: float = 0) -> _FakeResponse:
            del request, timeout
            return _FakeResponse(raw)

        monkeypatch.setattr(ca.urllib.request, "urlopen", fake_urlopen)
        out_dir = tmp_path / "exports"
        assert ca.main(["generate", "--dir", str(out_dir)]) == 0

        written = list(out_dir.glob("*.json"))
        assert len(written) == 1
        on_disk = written[0].read_bytes()
        assert on_disk == raw, "the bytes on disk differ from the bytes served"
        assert _MOJIBAKE_SENTINEL.encode("utf-8") in on_disk
        # And it is not the mojibake a Latin-1 decode would have produced.
        assert json.loads(on_disk.decode("utf-8"))["sections"]["portfolio"]["data"][
            "methodology"
        ] == _MOJIBAKE_SENTINEL

    def test_generate_reports_path_bytes_export_id_and_section_count(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        doc = make_export({"portfolio": _section("portfolio", {}), "regime": _section("regime", {})})
        doc["export_id"] = "portfolio-abc123"
        raw = json.dumps(doc).encode("utf-8")
        monkeypatch.setattr(
            ca.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(raw)
        )
        out_dir = tmp_path / "exports"
        assert ca.main(["generate", "--dir", str(out_dir)]) == 0
        printed = capsys.readouterr().out
        assert "bytes        : " in printed
        assert f"bytes        : {len(raw)}" in printed
        assert "portfolio-abc123" in printed
        assert "sections     : 2" in printed

    def test_generate_never_overwrites_without_force(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        raw = json.dumps(make_export()).encode("utf-8")
        monkeypatch.setattr(
            ca.urllib.request, "urlopen", lambda *a, **k: _FakeResponse(raw)
        )
        out_dir = tmp_path / "exports"
        assert ca.main(["generate", "--dir", str(out_dir)]) == 0
        assert ca.main(["generate", "--dir", str(out_dir)]) == 2
        assert "--force" in capsys.readouterr().err
        assert ca.main(["generate", "--dir", str(out_dir), "--force"]) == 0

    def test_generate_is_read_only_against_the_app(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Only a GET of the read-only context endpoint is ever attempted.

        Output goes to ``tmp_path``: a test must never drop a real export into
        the working tree, where it would be one `git add -A` away from being
        committed.
        """
        seen: list[object] = []

        def fake_urlopen(request: object, timeout: float = 0) -> _FakeResponse:
            seen.append(request)
            return _FakeResponse(json.dumps(make_export()).encode("utf-8"))

        monkeypatch.setattr(ca.urllib.request, "urlopen", fake_urlopen)
        assert ca.main(["generate", "--dir", str(tmp_path)]) == 0
        capsys.readouterr()
        assert len(seen) == 1
        request = seen[0]
        assert getattr(request, "method", "GET") == "GET"
        assert getattr(request, "full_url", "").startswith(ca.DEFAULT_EXPORT_URL)
        assert list(tmp_path.glob("*.json"))

    def test_generate_warns_when_writing_outside_the_gitignored_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A non-default target inside the repo gets a loud holdings warning."""
        monkeypatch.setattr(
            ca.urllib.request, "urlopen",
            lambda *a, **k: _FakeResponse(json.dumps(make_export()).encode("utf-8")),
        )
        stray = ca.REPO_ROOT / "backend" / "tests" / "_stray_export_for_test.json"
        assert ca.main(["generate", "--out", str(stray)]) == 0
        try:
            err = capsys.readouterr().err
            assert "live holdings" in err
        finally:
            stray.unlink(missing_ok=True)

    def test_unreachable_server_says_so_and_suggests_how_to_start_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def fake_urlopen(*_a: object, **_k: object) -> _FakeResponse:
            raise urllib.error.URLError(ConnectionRefusedError("connection refused"))

        monkeypatch.setattr(ca.urllib.request, "urlopen", fake_urlopen)
        assert ca.main(["generate", "--dir", str(tmp_path)]) == 2
        err = capsys.readouterr().err
        assert "could not reach" in err
        assert "uvicorn main:app --host 127.0.0.1 --port 8000" in err
        assert "cd backend" in err
        assert not list(tmp_path.glob("*.json"))


# --------------------------------------------------------------------------
# check command surface
# --------------------------------------------------------------------------


class TestCheckCommand:
    def test_clean_export_exits_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _write(tmp_path / "ok.json", make_export())
        assert ca.main(["check", "--export", str(path)]) == 0
        assert "failed      : 0" in capsys.readouterr().out

    def test_failing_export_exits_one(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        export = make_export()
        export["schema_version"] = "1.0"
        path = _write(tmp_path / "bad.json", export)
        assert ca.main(["check", "--export", str(path)]) == 1
        out = capsys.readouterr().out
        assert "ENV-001" in out
        assert "FAIL" in out

    def test_rule_subset(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        export = make_export()
        export["schema_version"] = "1.0"
        path = _write(tmp_path / "bad.json", export)
        assert ca.main(["check", "--export", str(path), "--rule", "NUM-001"]) == 0
        out = capsys.readouterr().out
        assert "1 selected of" in out
        assert "ENV-001" not in out

    def test_unknown_rule_id_is_rejected(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _write(tmp_path / "ok.json", make_export())
        assert ca.main(["check", "--export", str(path), "--rule", "NOPE-999"]) == 2
        assert "unknown rule id" in capsys.readouterr().err

    def test_json_output_is_parseable_and_carries_counts(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        export = make_export()
        export["schema_version"] = "1.0"
        path = _write(tmp_path / "bad.json", export)
        assert ca.main(["check", "--export", str(path), "--json"]) == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["counts"]["rules_run"] == len(ca.RULES)
        assert payload["counts"]["rules_failed"] == 1
        assert payload["rules_failed"] == ["ENV-001"]
        assert payload["findings"][0]["rule_id"] == "ENV-001"

    def test_missing_export_file_is_a_message_not_a_traceback(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert ca.main(["check", "--export", str(tmp_path / "nope.json")]) == 2
        assert "error: export not found" in capsys.readouterr().err

    def test_a_crashing_rule_is_reported_not_swallowed(
        self, monkeypatch: pytest.CaptureFixture[str] | pytest.MonkeyPatch,
    ) -> None:
        def boom(_export: ca.Export) -> list[ca.Finding]:
            raise RuntimeError("deliberate")

        original = {rule.rule_id: rule.fn for rule in ca.RULES}
        monkeypatch.setattr(
            ca, "RULES", tuple(
                ca.Rule(r.rule_id, r.category, r.description, boom if r.rule_id == "ENV-004" else r.fn)
                for r in ca.RULES
            )
        )
        findings, errors = ca.run_rules(ca.Export(doc=make_export(), raw="{}"))
        assert findings == []
        assert [r.rule_id for r, _ in errors] == ["ENV-004"]
        assert "deliberate" in errors[0][1]
        assert set(original) == {r.rule_id for r in ca.RULES}

    def test_output_is_grouped_by_category(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = _write(tmp_path / "ok.json", make_export())
        ca.main(["check", "--export", str(path)])
        out = capsys.readouterr().out
        assert out.index("ENVELOPE  (18 rules)") < out.index("CROSS-SECTION")
        assert out.index("CROSS-SECTION") < out.index("NUMERIC")
        assert "PER-SECTION VERDICT" in out
        assert "SUMMARY" in out


# --------------------------------------------------------------------------
# Every rule id must be claimed by at least one test above.
# Built by hand from the test bodies so adding a rule without a test is a
# visible failure rather than a silent coverage hole.
# --------------------------------------------------------------------------

EXERCISED_RULE_IDS: set[str] = {
    # envelope
    "ENV-001", "ENV-002", "ENV-003", "ENV-004", "ENV-005", "ENV-006",
    "ENV-007", "ENV-008", "ENV-009", "ENV-010", "ENV-011", "ENV-012",
    "ENV-013", "ENV-014", "ENV-015", "ENV-016", "ENV-017", "ENV-018",
    # cross-section
    "XS-001", "XS-002", "XS-003", "XS-004", "XS-005", "XS-006", "XS-007",
    "XS-008", "XS-009",
    # numeric
    "NUM-001", "NUM-002", "NUM-003", "NUM-004", "NUM-005", "NUM-006",
    "NUM-007", "NUM-008", "NUM-009", "NUM-010", "NUM-011", "NUM-012",
    "NUM-013", "NUM-014", "NUM-015", "NUM-016", "NUM-017", "NUM-018",
    "NUM-019", "NUM-020",
}
