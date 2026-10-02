"""Tests for the AI-context export audit CLI.

Every fixture is built INLINE as a small dict.  Nothing here touches a live
server or a real portfolio, and no export artifact is read from disk except the
ones a test writes itself into ``tmp_path``.

The shape of these tests is deliberate: for each rule there is a minimal export
that must PASS it and a targeted mutation that must FAIL *with that exact rule
id*.  A rule that cannot be made to fail is a rule that does not work.
"""

from __future__ import annotations

import ast
import json
import re
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
        """Guards against a rule being added to the table and never asserted.

        STRENGTHENED.  This used to compare the rule table against
        ``EXERCISED_RULE_IDS``, a hand-written list of 57 id strings, which
        made the guard a statement that somebody had written the ids down.  It
        could not fail for the reason it existed: all 57 ids could be listed
        with every corresponding test body stubbed to assert nothing, and the
        set difference stayed empty.  ``EXERCISED_RULE_IDS`` is now DERIVED by
        parsing this file (see ``_asserted_ids_by_test``), so a test that
        stops asserting on its id stops claiming it, and the difference below
        goes non-empty naming the rule whose exercise went missing.

        Both original assertions are kept, not weakened: the first still
        catches a rule added with no test, the second still catches an id
        claimed for a rule that is not in the table.
        """
        exercised = EXERCISED_RULE_IDS
        table = {rule.rule_id for rule in ca.RULES}
        assert table - exercised == set(), f"never exercised: {sorted(table - exercised)}"
        assert exercised - table == DECLARED_NON_RULE_IDS, (
            f"exercised but absent: {sorted(exercised - table)}"
        )

    def test_every_exercised_id_names_a_real_test_that_asserts_it(self) -> None:
        """The witness for each id must be a test in THIS file, not a claim.

        ``_asserted_ids_by_test`` maps id -> test names.  A name that is not a
        test function of this module would mean the map was built from
        something other than the tests, which is the property the whole guard
        now rests on.  This is cheap and it is the check that would notice the
        derivation silently widening to "any string in the file".
        """
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        real_tests = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test")
        }
        for rule_id, witnesses in sorted(_asserted_ids_by_test().items()):
            assert witnesses, f"{rule_id} is claimed by no test"
            assert witnesses <= real_tests, (
                f"{rule_id} claimed by non-test names: {sorted(witnesses - real_tests)}"
            )

    def test_every_claimed_id_is_either_a_rule_or_a_declared_stranger(self) -> None:
        """Holds the one hand-maintained exception to exactly what is needed.

        ``DECLARED_NON_RULE_IDS`` is the only part of the coverage picture
        that cannot be derived, because intent is not in the source: ``NOPE-999``
        is asserted absent on purpose, to prove the CLI rejects an unknown
        ``--rule``.  Declaring it is honest; leaving it unconstrained would let
        the declaration absorb a real coverage hole.  So the set must be
        exactly the ids the tests need declared -- no more.
        """
        claimed_strangers = EXERCISED_RULE_IDS - {rule.rule_id for rule in ca.RULES}
        assert claimed_strangers == set(DECLARED_NON_RULE_IDS)
        for stranger in DECLARED_NON_RULE_IDS:
            assert stranger in _asserted_ids_by_test(), (
                f"{stranger} is declared but no test asserts on it; "
                f"the declaration has gone stale"
            )

    def test_the_rule_id_shape_covers_every_rule_in_the_table(self) -> None:
        """The scan is keyed on a regex; a new id outside it would go unscanned.

        Without this, adding e.g. ``NUMERIC-1`` to ``RULES`` would leave it out
        of ``EXERCISED_RULE_IDS`` and the guard would report it as uncovered for
        the wrong reason -- or, if it also happened to be listed, would not
        notice at all.
        """
        mis_shaped = [
            rule.rule_id for rule in ca.RULES if not _RULE_ID_SHAPE.fullmatch(rule.rule_id)
        ]
        assert mis_shaped == [], f"rule ids outside the scan's shape: {mis_shaped}"

    def test_the_claim_scanner_tells_a_real_test_from_a_hollow_one(self) -> None:
        """Locks the discrimination the coverage guard depends on.

        Every case here is a way the id can appear in this file WITHOUT a test
        exercising the rule.  They are written out as synthetic sources so the
        predicate is pinned against a real edit rather than against my reading
        of it: a future change that widens the scan to "any string in the file"
        turns several of these red, which is the point.  The last two are the
        real defects the old guard could not see -- an id surviving on the
        strength of the assertion that DENIES it.
        """
        cases = {
            # name: (source, should the id be claimed?)
            "positive_in": ('def test_x():\n    assert "NUM-001" in out\n', True),
            "positive_eq": ('def test_x():\n    assert ids == ["NUM-001"]\n', True),
            "positive_assert_only": ('def test_x():\n    assert_only(export, "NUM-001")\n', True),
            "negative_not_in": ('def test_x():\n    assert "NUM-001" not in out\n', False),
            "negative_not_equals": ('def test_x():\n    assert ids != ["NUM-001"]\n', False),
            "negative_not_wrapper": ('def test_x():\n    assert not ("NUM-001" in out)\n', False),
            "docstring_only": ('def test_x():\n    """about NUM-001"""\n    assert ok\n', False),
            "comment_only": ("def test_x():\n    # about NUM-001\n    assert ok\n", False),
            "assignment_only": ('def test_x():\n    rid = "NUM-001"\n    assert ok\n', False),
            "not_a_test_function": ('def helper():\n    assert "NUM-001" in out\n', False),
            "helper_inside_test": (
                'def test_x():\n    def helper():\n        assert "NUM-001" in out\n    assert ok\n',
                False,
            ),
        }
        for name, (source, expected) in cases.items():
            claimed = _claimed_ids_in_source(source)
            assert ("NUM-001" in claimed) is expected, (
                f"{name}: expected claimed={expected}, got {sorted(claimed)}"
            )

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
                        "r_squared_standard_error": 0.04,
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

    def test_env016_available_section_with_a_block_reason_must_warn(self) -> None:
        """AGENT-05 / ENV-016 repair.

        The old rule only obliged partial/unavailable, which made ``available``
        a promise that nothing needed saying — and ``available`` is the status
        every P0 in the v5 review carries.  A payload that publishes
        ``block_reasons`` is degraded whether or not the section admits it.
        """
        export = make_export(
            {
                "volatility_sizing": _section(
                    "volatility_sizing",
                    {
                        "execution": {
                            "execution_eligible": False,
                            "block_reasons": ["financing_required"],
                            "block_reason": "gross 1.295 > 1.0; not a normal rebalance",
                        }
                    },
                )
            }
        )
        assert_only(export, "ENV-016")
        assert any("block_reason" in f.message for f in find_for(export, "ENV-016"))

    def test_env016_available_section_with_omitted_fields_must_warn(self) -> None:
        export = make_export({"risk_studio": _section("risk_studio", {})})
        export["sections"]["risk_studio"]["omitted_fields"] = ["components.series"]
        assert_only(export, "ENV-016")

    def test_env016_disclosed_degradation_passes_on_an_available_section(self) -> None:
        """The exit is a sentence an engineer can write truthfully. No value in
        the export has to change, so this rule cannot be silenced by making a
        number up."""
        export = make_export(
            {
                "volatility_sizing": _section(
                    "volatility_sizing",
                    {"execution": {"execution_eligible": False,
                                   "block_reasons": ["financing_required"]}},
                    warnings=["this target borrows 29.5% and is not a normal rebalance"],
                )
            }
        )
        assert rule_ids(export) == set()

    def test_env016_empty_exclusion_map_is_not_a_degradation(self) -> None:
        """``excluded_assets={"volatility": [], "cvar_tail": []}`` says two
        exclusions were considered and neither happened. It is not a marker,
        and flagging it would be noise on every section that publishes the
        shape."""
        export = make_export(
            {
                "risk_contribution": _section(
                    "risk_contribution",
                    {"excluded_assets": {"volatility": [], "cvar_tail": []}},
                )
            }
        )
        assert rule_ids(export) == set()

    def test_env012_as_of_five_months_in_the_future_catches(self) -> None:
        """AGENT-03 mutation: the old rule only tested MEMBERSHIP in the
        collector's own clock window, so a future date sailed through."""
        export = make_export()
        export["sections"]["portfolio"]["as_of"] = "2027-03-01"
        assert_only(export, "ENV-012")
        assert any("AFTER completed_at" in f.message
                   for f in find_for(export, "ENV-012"))

    def test_env012_as_of_ten_years_stale_catches(self) -> None:
        """The second half of the same mutation: a 2016 observation is not the
        newest observation behind a 2026 export."""
        export = make_export()
        export["sections"]["portfolio"]["as_of"] = "2016-01-01"
        assert_only(export, "ENV-012")
        message = find_for(export, "ENV-012")[0].message
        assert "calendar days older" in message
        assert "AS_OF_STALENESS_DAYS" not in message
        assert f"{ca.AS_OF_STALENESS_DAYS:g}" in message

    def test_env012_a_disclosed_stale_as_of_passes(self) -> None:
        """Disclosed staleness is an honest exit; the section is not hiding it."""
        export = make_export()
        export["sections"]["portfolio"]["as_of"] = "2016-01-01"
        export["sections"]["portfolio"]["warnings"] = [
            "the newest observation is 2016-01-01; this series is stale"
        ]
        assert rule_ids(export) == set()

    def test_env012_a_future_refresh_clock_disclosed_passes(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["as_of"] = "2026-09-27"
        export["sections"]["portfolio"]["as_of_semantics"] = "quote_refresh_timestamp"
        assert rule_ids(export) == set()

    def test_env012_a_recent_observation_date_is_clean(self) -> None:
        """Ordered before the collection started but inside the staleness bound:
        a perfectly normal observation date."""
        export = make_export()
        export["sections"]["portfolio"]["as_of"] = "2026-09-24"
        assert rule_ids(export) == set()

    def test_env012_a_null_as_of_is_not_this_rules_business(self) -> None:
        export = make_export()
        export["sections"]["portfolio"]["as_of"] = None
        export["sections"]["portfolio"]["as_of_semantics"] = None
        assert rule_ids(export) == set()

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
                    {
                        "components": {
                            "risk_score": {
                                "factor_r_squared": 0.2391,
                                "factor_r_squared_standard_error": 0.05,
                            }
                        }
                    },
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
                        "r_squared_standard_error": 0.03,
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
                        "r_squared_standard_error": 0.03,
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
                                "factor_r_squared_standard_error": 0.05,
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
                        "r_squared_standard_error": 0.03,
                        "full_history": {
                            "observation_count": 174,
                            "scope": "full_exchange_history",
                            "window": {"start": "2026-01-20", "end": "2026-09-25"},
                        },
                    },
                ),
                "dashboard": _section(
                    "dashboard",
                    {
                        "components": {
                            "risk_score": {
                                **shared,
                                "factor_r_squared": 0.2391,
                                "factor_r_squared_standard_error": 0.05,
                            }
                        }
                    },
                    status="partial",
                    warnings=["risk score component"],
                ),
            }
        )
        assert_only(export, "XS-009")


# --------------------------------------------------------------------------
# ENV-019 .. ENV-021 -- the v5-review envelope rules
# --------------------------------------------------------------------------


class TestV5EnvelopeRules:
    def _gated_sizing(self, trade_status: str, **gate: Any) -> dict[str, Any]:
        return make_export(
            {
                "volatility_sizing": _section(
                    "volatility_sizing",
                    {
                        "execution": {"execution_eligible": False, **gate},
                        "trades": {
                            "AAA.NS": {"shares_delta": 2, "status": trade_status},
                            "BBB.NS": {"shares_delta": -1, "status": trade_status},
                        },
                    },
                )
            }
        )

    # ---- ENV-019 (AD-5 / G3)

    def test_env019_executable_record_inside_a_gated_section_catches(self) -> None:
        export = self._gated_sizing("executable")
        assert_only(export, "ENV-019")
        message = find_for(export, "ENV-019")[0].message
        assert "2 record(s)" in message
        assert "execution_eligible is false" in message

    def test_env019_the_gate_open_passes(self) -> None:
        export = make_export(
            {
                "volatility_sizing": _section(
                    "volatility_sizing",
                    {
                        "execution": {"execution_eligible": True},
                        "trades": {"AAA.NS": {"shares_delta": 2,
                                              "status": "executable"}},
                    },
                )
            }
        )
        assert rule_ids(export) == set()

    def test_env019_a_record_carrying_its_own_gate_is_disclosing(self) -> None:
        """A per-record ``execution_eligible: false`` alongside the section gate
        is the honest shape: the record explains itself instead of asserting
        against the gate."""
        export = make_export(
            {
                "volatility_sizing": _section(
                    "volatility_sizing",
                    {
                        "execution": {"execution_eligible": False},
                        "trades": {
                            "AAA.NS": {"shares_delta": 2, "status": "executable",
                                       "execution_eligible": False},
                        },
                    },
                )
            }
        )
        assert rule_ids(export) == set()

    def test_env019_a_non_executable_status_passes(self) -> None:
        export = self._gated_sizing("below_minimum_notional")
        assert rule_ids(export) == set()

    def test_env019_an_executable_record_in_an_ungated_section_passes(self) -> None:
        """No gate means no contradiction. ``optimization`` publishes an
        executable trade set and says nothing against it."""
        export = make_export(
            {
                "optimization": _section(
                    "optimization",
                    {
                        "trades_required": {
                            "AAA.NS": {"weight_delta": 0.01, "status": "executable"}
                        }
                    },
                )
            }
        )
        assert rule_ids(export) == set()

    # ---- ENV-020 (SI-5)

    def _estimates(self, **extra: Any) -> dict[str, Any]:
        return make_export(
            {"realized_risk": _section("realized_risk",
                                        {"sharpe_ratio": 3.49, **extra})}
        )

    def test_env020_naked_sharpe_catches(self) -> None:
        export = self._estimates()
        assert_only(export, "ENV-020")
        assert "sharpe_ratio" in find_for(export, "ENV-020")[0].message

    def test_env020_a_standard_error_silences_it(self) -> None:
        """The exit is one true number, not a changed one."""
        assert rule_ids(self._estimates(sharpe_ratio_standard_error=0.42)) == set()

    def test_env020_an_interval_silences_it(self) -> None:
        assert rule_ids(
            self._estimates(sharpe_ratio_confidence_interval=[-9.77, 16.75])
        ) == set()

    def test_env020_an_effective_sample_size_silences_it(self) -> None:
        """39 autocorrelated daily returns are not 39 independent observations;
        publishing the effective n is the disclosure that makes a point estimate
        readable."""
        assert rule_ids(self._estimates(effective_n=11.4)) == set()

    def test_env020_a_raw_observation_count_does_not_silence_it(self) -> None:
        """Pinned deliberately.  ``covered_days: 39`` and ``observations: 174``
        appear on every estimate-bearing section of the v5 artifact, so
        accepting a row count as uncertainty would have made this rule green on
        an export that discloses no uncertainty at all."""
        export = self._estimates(observations=174)
        assert_only(export, "ENV-020")

    def test_env020_a_p_value_does_not_silence_it(self) -> None:
        """``engle_granger_pvalue`` is a hypothesis verdict, not a statement
        about the precision of the ``hedge_ratio_beta`` beside it."""
        export = make_export(
            {
                "pairs": _section(
                    "pairs",
                    {"pairs": [{"hedge_ratio_beta": 0.27,
                                "engle_granger_pvalue": 0.04}]},
                    status="partial",
                    warnings=["depth limited"],
                )
            }
        )
        assert_only(export, "ENV-020")

    def test_env020_a_section_with_no_estimate_passes(self) -> None:
        export = make_export(
            {"concentration": _section("concentration",
                                        {"portfolio_position_count": 14})}
        )
        assert rule_ids(export) == set()

    def test_env020_the_disclosure_may_sit_anywhere_in_the_section(self) -> None:
        """Checked over the whole subtree, not one key: a standard error nested
        two components deep is still a disclosure for the section."""
        export = make_export(
            {
                "risk_studio": _section(
                    "risk_studio",
                    {
                        "components": {
                            "a": {"metrics": {"sharpe_ratio": 2.0}},
                            "b": {"precision": {"sharpe_ratio_standard_error": 0.8}},
                        }
                    },
                )
            }
        )
        assert rule_ids(export) == set()

    # ---- ENV-021 (AD-10 / G4)

    def _coverage_block(self, ratio: Any, count: Any) -> dict[str, Any]:
        return make_export(
            {
                "india_flows": _section(
                    "india_flows",
                    {
                        "component_coverage": {
                            "delivery_anomalies": {
                                "scope": "symbol_scoped",
                                "status": "unavailable",
                                "requested_count": 14,
                                "covered_count": count,
                                "coverage_ratio": ratio,
                            }
                        }
                    },
                    status="partial",
                    warnings=["no delivery history"],
                )
            }
        )

    def test_env021_zero_ratio_beside_a_null_count_catches(self) -> None:
        export = self._coverage_block(0, None)
        assert_only(export, "ENV-021")
        assert "covered_count" in find_for(export, "ENV-021")[0].message

    def test_env021_a_measured_zero_count_silences_it(self) -> None:
        """``covered_count: 0`` is the measurement the ratio already asserts."""
        assert rule_ids(self._coverage_block(0, 0)) == set()

    def test_env021_omitting_the_ratio_silences_it(self) -> None:
        """The sibling ``institutional_flows`` block publishes a null count and
        no ratio at all. That is the honest spelling and it must pass."""
        assert rule_ids(self._coverage_block(None, None)) == set()

    def test_env021_a_null_count_in_another_block_does_not_fire(self) -> None:
        """Both keys must be in the SAME mapping: a ratio in one block and a
        null count in a sibling is not a contradiction."""
        export = make_export(
            {
                "india_flows": _section(
                    "india_flows",
                    {
                        "component_coverage": {
                            "a": {"coverage_ratio": 0, "covered_count": 0}
                        },
                        "summary": {"covered_count": None},
                    },
                    status="partial",
                    warnings=["component unavailable"],
                )
            }
        )
        assert rule_ids(export) == set()

    def test_env021_a_nonzero_ratio_beside_a_null_count_passes(self) -> None:
        assert rule_ids(self._coverage_block(0.5, None)) == set()


# --------------------------------------------------------------------------
# XS-010 -- MY-1
# --------------------------------------------------------------------------


class TestHoldingWindowStartSelfConsistency:
    def _sizing(self, start: str, declared: str | None,
                *, sibling: bool = True,
                reconcile: bool | str = False) -> dict[str, Any]:
        measured: dict[str, Any] = {
            "start": start,
            "end": "2026-09-25",
            "days": 39,
            "covered_days_scope": "holding_window_aligned_return_rows",
        }
        if declared is not None:
            measured["holding_window_start"] = declared
        if reconcile:
            measured["holding_window_to_measured_start_gap_days"] = 22
            if reconcile != "gap_only":
                measured["measured_start_basis"] = (
                    "first date on which every held position had a measurable return"
                )
        sections: dict[str, Any] = {
            "tear_sheet": _section("tear_sheet", {"measured_window": measured})
        }
        if sibling:
            sections["realized_risk"] = _section(
                "realized_risk",
                {
                    "history_coverage": {
                        "intersection_start": "2026-08-03",
                        "covered_days": 39,
                        "covered_days_scope": "holding_window_aligned_return_rows",
                    }
                },
                status="partial",
                warnings=["holding window truncated"],
            )
        return make_export(sections)

    def test_xs010_start_contradicting_its_own_holding_window_start_catches(self) -> None:
        """The block states the contradiction itself: it publishes
        ``holding_window_start: 2026-08-03`` and its own ``start: 2026-08-04``.
        With no sibling holding-window block for XS-001 to compare against, this
        is XS-010 alone."""
        export = self._sizing("2026-08-04", "2026-08-03", sibling=False)
        assert_only(export, "XS-010")
        assert "2026-08-04" in find_for(export, "XS-010")[0].message

    def test_xs010_agreeing_starts_pass(self) -> None:
        assert rule_ids(self._sizing("2026-08-03", "2026-08-03")) == set()

    def test_xs010_reconciled_gap_passes(self) -> None:
        """A block may hold both dates when they describe DIFFERENT things and it
        reconciles them. A portfolio return is only measurable once every held leg
        has a price, so the first measurable date is legitimately later than the
        holding window's start. Publishing the gap and its basis resolves the
        contradiction; publishing both dates silently does not."""
        export = self._sizing("2026-08-25", "2026-08-03", sibling=False, reconcile=True)
        assert rule_ids(export) == set()

    def test_xs010_gap_without_a_basis_still_catches(self) -> None:
        """Half the reconciliation is not a reconciliation: a number with no
        explanation of what produced it is exactly the silent two-date case."""
        export = self._sizing("2026-08-25", "2026-08-03", sibling=False, reconcile="gap_only")
        assert_only(export, "XS-010")
        assert "measured_start_basis" in find_for(export, "XS-010")[0].message

    def test_xs010_no_declared_holding_window_start_passes(self) -> None:
        """Without a published ``holding_window_start`` there is nothing to
        contradict; XS-001 is the rule that compares siblings."""
        assert rule_ids(self._sizing("2026-08-03", None)) == set()

    def test_xs001_compares_a_measured_window_start_not_only_intersection_start(self) -> None:
        """MY-1, the hole in my own rule: a block that dates its holding window
        under any other key used to drop out of the comparison set instead of
        contradicting it."""
        export = self._sizing("2026-08-04", None)
        assert_only(export, "XS-001")

    def test_xs001_a_delivered_start_on_a_holding_window_block_is_compared(self) -> None:
        export = make_export(
            {
                "realized_risk": _section(
                    "realized_risk",
                    {
                        "history_coverage": {
                            "intersection_start": "2026-08-03",
                            "covered_days": 39,
                            "covered_days_scope": "holding_window_aligned_return_rows",
                        }
                    },
                    status="partial",
                    warnings=["truncated"],
                ),
                "regime": _section(
                    "regime",
                    {
                        "history_coverage": {
                            "delivered_start": "2026-08-25",
                            "covered_days": 39,
                            "covered_days_scope": "holding_window_aligned_return_rows",
                        }
                    },
                ),
            }
        )
        assert_only(export, "XS-001")
        assert "delivered_start" in find_for(export, "XS-001")[0].message

    def test_xs001_a_delivered_series_with_no_holding_window_scope_is_not_compared(self) -> None:
        """``dashboard``'s ``performance_history`` publishes
        ``delivered_start: 2026-08-25`` for a 90-day requested DASHBOARD window
        it already reports as partial/truncated/stale, and it publishes no
        ``covered_days_scope``. It is a different population, not a
        contradiction, and admitting it would be a false positive that no
        honest fix could silence."""
        export = make_export(
            {
                "realized_risk": _section(
                    "realized_risk",
                    {
                        "history_coverage": {
                            "intersection_start": "2026-08-03",
                            "covered_days": 39,
                            "covered_days_scope": "holding_window_aligned_return_rows",
                        }
                    },
                    status="partial",
                    warnings=["truncated"],
                ),
                "dashboard": _section(
                    "dashboard",
                    {
                        "components": {
                            "performance_history": {
                                "status": "partial",
                                "warnings": ["short window"],
                                "history_coverage": {
                                    "requested_days": 90,
                                    "delivered_start": "2026-08-25",
                                    "delivered_end": "2026-09-21",
                                    "observation_count": 19,
                                    "expected_observation_count": 65,
                                    "coverage_ratio": 0.29,
                                    "truncated": True,
                                    "stale": True,
                                    "status": "partial",
                                },
                                "data": [
                                    {"date": "2026-08-25", "portfolio_value": 42981.74,
                                     "return": None, "constituent_count": 14,
                                     "warm_up": True, "benchmark_value": 40000.0},
                                    {"date": "2026-08-26", "portfolio_value": 43000.0,
                                     "return": 0.0004, "constituent_count": 14,
                                     "benchmark_value": 40010.0},
                                ],
                            }
                        }
                    },
                    status="partial",
                    warnings=["performance window short"],
                ),
            }
        )
        assert rule_ids(export) == set()



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

    # ------------------------------------------------------------------
    # The third bucket. `johansen_cointegrated` is a tri-state: `null`
    # means the statistic was not computable, so there is no second
    # verdict to compare the decision against and the pair is neither
    # agreement nor disagreement. The identity below used to be a two-bucket
    # one, so it fired on every honest export carrying a refusal - the pair of
    # changes that would have left the gate permanently red.
    # ------------------------------------------------------------------

    def test_num014_a_refused_diagnostic_is_a_third_bucket(self) -> None:
        """The case the two-bucket identity could not express: 4 + 1 + 1 == 6.

        Before the relaxation this fired, which is the red proof that the rule
        was reading a refusal as a missing count.
        """
        assert rule_ids(
            self._pairs(
                test_agreement={
                    "agreement_count": 4,
                    "disagreement_count": 1,
                    "unavailable_count": 1,
                    "counted_pairs": 6,
                }
            )
        ) == set()

    def test_num014_an_unavailable_count_that_does_not_close_still_fires(self) -> None:
        """The negative half, and the reason the relaxation is not decoration.

        Relaxing an identity is only sound if it can still fail. Here the three
        buckets do not account for every counted pair: a refused pair was
        dropped from all three and `counted_pairs` still says 6.
        """
        assert_only(
            self._pairs(
                test_agreement={
                    "agreement_count": 4,
                    "disagreement_count": 1,
                    "unavailable_count": 0,
                    "counted_pairs": 6,
                }
            ),
            "NUM-014",
        )

    def test_num014_an_overstated_unavailable_count_still_fires(self) -> None:
        """The mirror of the previous case, because a relaxation that only
        catches under-counting is half a rule: claiming three refusals on a
        six-pair book whose buckets sum to seven is as wrong as losing one."""
        assert_only(
            self._pairs(
                test_agreement={
                    "agreement_count": 4,
                    "disagreement_count": 1,
                    "unavailable_count": 3,
                    "counted_pairs": 6,
                }
            ),
            "NUM-014",
        )

    def test_num014_an_unpublished_unavailable_count_still_fires(self) -> None:
        """`unavailable_count` is defaulted to 0 when the key is ABSENT, so a
        pre-tri-state export still passes. It is not defaulted when the key is
        present and null: that is a count the exporter claimed to publish and
        did not."""
        assert_only(
            self._pairs(
                test_agreement={
                    "agreement_count": 4,
                    "disagreement_count": 1,
                    "unavailable_count": None,
                    "counted_pairs": 6,
                }
            ),
            "NUM-014",
        )

    def test_num014_a_pre_tristate_export_still_passes(self) -> None:
        """The compatibility half. An artifact generated before the tri-state
        had no refused diagnostic to count, so 0 is the TRUE value of the field
        for one; requiring the key would fail every such export on a disclosure
        rather than on an inconsistency."""
        export = self._pairs()
        assert "unavailable_count" not in export["sections"]["pairs"]["data"][
            "test_agreement"
        ]
        assert rule_ids(export) == set()

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
            "evt_pot_var_99_standard_error": 0.006,
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
                                "avg_pairwise_correlation_standard_error": 0.02,
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
                                "avg_pairwise_correlation_standard_error": 0.02,
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
                                "avg_pairwise_correlation_standard_error": 0.0,
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
            # NUM-021 requires the basket size per observation; publish it so
            # these fixtures test the series rules and not the breadth rule.
            "data": [{**row, "constituent_count": 2} for row in rows],
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

    # ---- NUM-021 (QM-1)

    def _series(self, rows: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        history: dict[str, Any] = {
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
        history.update(extra)
        return make_export(
            {
                "dashboard": _section(
                    "dashboard",
                    {"components": {"performance_history": history}},
                    status="partial",
                    warnings=["performance window short"],
                )
            }
        )

    def test_num021_a_series_with_no_breadth_catches(self) -> None:
        export = self._series(
            [
                {"date": "2026-08-25", "portfolio_value": 100.0, "return": None,
                 "warm_up": True, "benchmark_value": 99.0},
                {"date": "2026-08-26", "portfolio_value": 101.0, "return": 0.01,
                 "benchmark_value": 100.0},
            ]
        )
        assert_only(export, "NUM-021")
        assert "constituent count on 0 rows" in find_for(export, "NUM-021")[0].message

    def test_num021_a_per_row_constituent_count_passes(self) -> None:
        export = self._series(
            [
                {"date": "2026-08-25", "portfolio_value": 100.0, "return": None,
                 "constituent_count": 14, "warm_up": True, "benchmark_value": 99.0},
                {"date": "2026-08-26", "portfolio_value": 101.0, "return": 0.01,
                 "constituent_count": 1, "benchmark_value": 100.0},
            ]
        )
        assert rule_ids(export) == set()

    def test_num021_an_aggregate_beside_the_series_passes(self) -> None:
        """``analytics_engine`` renormalises per date, so the cheapest honest
        disclosure is an aggregate: how many days were a partial basket."""
        export = self._series(
            [
                {"date": "2026-08-25", "portfolio_value": 100.0, "return": None,
                 "warm_up": True, "benchmark_value": 99.0},
                {"date": "2026-08-26", "portfolio_value": 101.0, "return": 0.01,
                 "benchmark_value": 100.0},
            ],
            partial_basket_days=20,
        )
        assert rule_ids(export) == set()

    def test_num021_a_renormalisation_declaration_passes(self) -> None:
        """An engineer who genuinely stops renormalising says so in one line."""
        export = self._series(
            [
                {"date": "2026-08-25", "portfolio_value": 100.0, "return": None,
                 "warm_up": True, "benchmark_value": 99.0},
                {"date": "2026-08-26", "portfolio_value": 101.0, "return": 0.01,
                 "benchmark_value": 100.0},
            ],
            renormalization="not_applied_every_observation_used_the_full_universe",
        )
        assert rule_ids(export) == set()

    def test_num021_a_universe_size_is_not_a_breadth_disclosure(self) -> None:
        """``portfolio_position_count: 14`` says how many legs COULD have been
        in the basket, which is not the number the defect is about."""
        export = self._series(
            [
                {"date": "2026-08-25", "portfolio_value": 100.0, "return": None,
                 "warm_up": True, "benchmark_value": 99.0},
                {"date": "2026-08-26", "portfolio_value": 101.0, "return": 0.01,
                 "benchmark_value": 100.0},
            ],
            portfolio_position_count=14,
        )
        assert_only(export, "NUM-021")

    def test_num021_a_series_with_no_measured_return_passes(self) -> None:
        export = self._series(
            [
                {"date": "2026-08-25", "portfolio_value": 100.0, "return": None,
                 "warm_up": True, "benchmark_value": 99.0},
            ]
        )
        assert rule_ids(export) == set()

    # ---- NUM-022 (SI-3 / QM-3)

    def _forecast(self, interval: Any) -> dict[str, Any]:
        return make_export(
            {
                "forecast_risk": _section(
                    "forecast_risk",
                    {
                        "portfolio": {
                            "volatility_forecast": 0.13767283267201857,
                            "var_forecast": -0.014266383036982124,
                            "cvar_forecast": -0.01786550094600801,
                            "confidence_interval": interval,
                            "observations": 174,
                            "annualized": True,
                        }
                    },
                )
            }
        )

    def test_num022_the_exact_v5_band_catches(self) -> None:
        """The reproduced defect: ``midpoint*0.8`` and ``midpoint*1.2`` hold to
        exact float equality, so no sample produced this interval."""
        export = self._forecast([0.11013826613761486, 0.16520739920642227])
        assert_only(export, "NUM-022")
        message = find_for(export, "NUM-022")[0].message
        assert "[0.8, 1.2]" in message

    def test_num022_a_computed_symmetric_interval_passes(self) -> None:
        """Symmetry alone is NOT the finding. This is a real Sharpe 95% CI that
        is symmetric and NOT a round multiple, and it must pass — otherwise the
        only way to silence the rule would be to break the symmetry of a
        correctly computed interval."""
        export = self._forecast([0.0952, 0.2146])
        assert rule_ids(export) == set()

    def test_num022_an_asymmetric_interval_passes(self) -> None:
        assert rule_ids(self._forecast([0.0901, 0.2408])) == set()

    def test_num022_a_non_round_symmetric_interval_passes(self) -> None:
        """Endpoints at 0.6429x and 1.3571x the centre: symmetric, off-grid, and
        exactly what a computed interval looks like."""
        centre = 0.14
        export = self._forecast([round(centre * 0.6429, 12),
                                 round(centre * 1.3571, 12)])
        assert rule_ids(export) == set()

    def test_num022_an_interval_containing_zero_passes(self) -> None:
        """A VaR or Sharpe interval may straddle zero; a negative endpoint is
        not a positive round multiple and the rule stays out of the way."""
        assert rule_ids(self._forecast([-9.77, 16.75])) == set()

    def test_num022_a_two_element_list_that_is_not_an_interval_passes(self) -> None:
        export = make_export(
            {
                "regime": _section(
                    "regime", {"term_structure": [0.1, 0.2]}
                )
            }
        )
        assert rule_ids(export) == set()

    def test_num022_the_estimate_itself_is_not_an_interval(self) -> None:
        """``[x, x]`` would be a 1.0 multiple; a degenerate list must not be
        read as a fabricated band."""
        assert rule_ids(self._forecast([0.1377, 0.1377])) == set()

    # ---- NUM-023 (QM-4)

    def _vol_sizing(self, **extra: Any) -> dict[str, Any]:
        return make_export(
            {
                "volatility_sizing": _section(
                    "volatility_sizing",
                    {
                        "target_volatility": 0.15,
                        "current_volatility": 0.145465131056991,
                        "scale_factor": 1.295309,
                        "achieved_volatility": 0.15,
                        **extra,
                    },
                )
            }
        )

    def test_num023_achieved_equal_to_target_catches(self) -> None:
        export = self._vol_sizing()
        assert_only(export, "NUM-023")
        assert "restatement" in find_for(export, "NUM-023")[0].message

    def test_num023_a_genuinely_achieved_value_passes(self) -> None:
        """0.1158 is what rec_vol x scale actually is, and publishing THAT next
        to a 0.15 target is the honest version of the same section."""
        export = self._vol_sizing(achieved_volatility=0.11580248)
        assert rule_ids(export) == set()

    def test_num023_no_scale_factor_means_no_identity_is_claimed(self) -> None:
        """Without a published scaling step the equality could be a real
        coincidence of a re-measurement, and the rule stays quiet."""
        export = make_export(
            {
                "volatility_sizing": _section(
                    "volatility_sizing",
                    {"target_volatility": 0.15, "achieved_volatility": 0.15},
                )
            }
        )
        assert rule_ids(export) == set()

    def test_num023_a_tautology_on_another_quantity_catches(self) -> None:
        """Not special-cased to volatility: any ``achieved_<x>`` beside its own
        ``target_<x>`` with a scale factor is the same restatement."""
        export = make_export(
            {
                "sizing": _section(
                    "sizing",
                    {
                        "target_beta": 0.8,
                        "achieved_beta": 0.8,
                        "scale_factor": 1.1,
                        "beta_standard_error": 0.2,
                    },
                )
            }
        )
        assert_only(export, "NUM-023")

    def test_num023_near_miss_is_not_a_tautology(self) -> None:
        """A real re-measurement differs in the ninth decimal, which is six
        orders of magnitude outside the 1e-12 identity band. Publishing
        ``rec_vol * scale`` to that precision is a measurement."""
        assert rule_ids(
            self._vol_sizing(achieved_volatility=0.15 + 1e-9)
        ) == set()

    def test_num023_inside_the_identity_band_is_still_the_identity(self) -> None:
        """Pinned so the tolerance is a stated choice rather than an accident.
        1e-12 absolute on a 0.15 volatility is ~7e-12 relative, far tighter than
        any rounding the exporter actually applies, so it can only ever match an
        algebraic identity and never a measurement."""
        assert_only(self._vol_sizing(achieved_volatility=0.15 + 1e-13), "NUM-023")

    # ---- NUM-024 (SI-1 / G9)

    def _signal_scan(self, signal: str, **record: Any) -> dict[str, Any]:
        return make_export(
            {
                "pairs": _section(
                    "pairs",
                    {
                        "universe_size": 14,
                        "scanned_pairs_count": 91,
                        "test_agreement": {
                            "decision_test": "engle_granger",
                            "counted_pairs": 91,
                            "agreement_count": 83,
                            "disagreement_count": 8,
                        },
                        "pairs": [
                            {
                                "ticker_a": "AAA.NS",
                                "ticker_b": "BBB.NS",
                                "engle_granger_pvalue": 0.042,
                                "hedge_ratio_beta": 0.008606,
                                "hedge_ratio_beta_standard_error": 0.0021,
                                "signal": signal,
                                **record,
                            }
                        ],
                    },
                    status="partial",
                    warnings=["depth limited"],
                )
            }
        )

    def test_num024_a_directive_without_its_basis_catches(self) -> None:
        export = self._signal_scan("LONG_SPREAD (Long AAA.NS, Short BBB.NS)")
        assert_only(export, "NUM-024")
        message = find_for(export, "NUM-024")[0].message
        assert "decision threshold" in message
        assert "multiplicity correction" in message
        # These two ARE published, and the message must not claim otherwise.
        assert "size ratio" not in message
        assert "number of comparisons" not in message

    def test_num024_a_directive_with_its_full_basis_passes(self) -> None:
        export = self._signal_scan(
            "SHORT_SPREAD (Short AAA.NS, Long BBB.NS)",
            johansen_agrees_with_decision=True,
            entry_z_threshold=1.5,
        )
        export["sections"]["pairs"]["data"]["bonferroni_alpha"] = 0.00054945
        export["sections"]["pairs"]["data"]["comparisons_made"] = 91
        assert rule_ids(export) == set()

    def test_num024_a_scan_level_basis_is_not_duplicated_per_record(self) -> None:
        """One honest constant beside the record list is enough for every record
        in it; the rule must not demand 91 copies."""
        export = self._signal_scan(
            "LONG_SPREAD (Long AAA.NS, Short BBB.NS)",
            johansen_agrees_with_decision=False,
        )
        data = export["sections"]["pairs"]["data"]
        data["entry_z_threshold"] = 1.5
        data["bonferroni_alpha"] = 0.00054945
        data["comparisons_made"] = 91
        data["hedge_ratio"] = {"AAA.NS/BBB.NS": 0.008606}
        assert rule_ids(export) == set()

    def test_num024_a_neutral_label_is_not_a_directive(self) -> None:
        """``NOT_COINTEGRATED`` and ``NEUTRAL`` say nothing actionable, and 89 of
        the 91 v5 records read that way. Flagging them would be noise on the
        overwhelming majority of the scan."""
        for label in ("NEUTRAL", "NOT_COINTEGRATED", "COINTEGRATED", "HOLD"):
            assert rule_ids(self._signal_scan(label)) == set()

    def test_num024_prose_mentioning_a_verb_is_not_a_directive(self) -> None:
        """Only directive-NAMED keys are read, so a ``methodology`` sentence
        that happens to contain "buy" cannot trip this rule."""
        export = make_export(
            {
                "pairs": _section(
                    "pairs",
                    {
                        "methodology": "buy_price_inferred starts shift the window",
                        "universe_size": 14,
                        "scanned_pairs_count": 91,
                        "test_agreement": {
                            "decision_test": "engle_granger",
                            "counted_pairs": 91,
                            "agreement_count": 83,
                            "disagreement_count": 8,
                        },
                        "pairs": [{"ticker_a": "AAA.NS", "ticker_b": "BBB.NS",
                                   "hedge_ratio_beta": 0.27,
                                   "hedge_ratio_beta_standard_error": 0.06,
                                   "signal": "NEUTRAL"}],
                    },
                    status="partial",
                    warnings=["depth limited"],
                )
            }
        )
        assert rule_ids(export) == set()

    def test_num024_a_directive_field_naming_the_action_is_caught_too(self) -> None:
        export = make_export(
            {
                "pairs": _section(
                    "pairs",
                    {"directive": "Short AAA.NS against BBB.NS"},
                    status="partial",
                    warnings=["depth limited"],
                )
            }
        )
        assert_only(export, "NUM-024")

    # ---- NUM-025 (a state label against the posterior beside it)

    def _posterior(self, posterior: dict[str, Any], **overrides: Any) -> dict[str, Any]:
        """A regime block publishing a settled state label beside the posterior
        that decides it.

        ``regime_probabilities_total`` and the rounding residual are published
        because NUM-015 requires them, so the only thing a red case changes is
        the relation NUM-025 is about.
        """
        data: dict[str, Any] = {
            "data_status": "available",
            "current_regime": "crisis",
            "regime_probabilities": posterior,
            "regime_probabilities_total": 100.0,
            "regime_probabilities_rounding_residual": 0.0,
            "stability_pct": 96.0,
            "stability_pct_rule": "share of unchanged decoded labels",
            "stability_pct_scope": "full_classification_sample",
            **overrides,
        }
        return make_export({"regime": _section("regime", data)})

    def test_num025_a_state_label_must_be_the_argmax_of_its_own_posterior(self) -> None:
        """The one regime field a consumer acts on, against the distribution the
        model published beside it.

        Every rule above this one asks whether two fields the exporter emitted
        TOGETHER are consistent.  This is the case where they are consistent and
        the label is still wrong: ``current_regime='bull'`` beside ``crisis:
        99.9967`` is an internally consistent document -- a string and a mapping
        -- so nothing else in the table could see it.  Four of the five red arms
        are the ways a posterior that does not single out a state gets a settled
        one published against it anyway.
        """
        healthy = {"bull": 0.5, "crisis": 99.0, "calm": 0.5}
        # The label IS the argmax.  Asserted silent FIRST and on its own line:
        # a rule that fires here fires on everything, and every red case below
        # is only meaningful because this one stays quiet.
        assert rule_ids(self._posterior(healthy)) == set()

        # 1/5 the reproduced defect: the label is wrong by a factor of a million
        # on the model's own posterior.
        contradiction = self._posterior(
            {"bull": 0.0001, "crisis": 99.9967, "calm": 0.0032},
            current_regime="bull",
        )
        assert_only(contradiction, "NUM-025")
        message = find_for(contradiction, "NUM-025")[0].message
        assert "wrong by a factor of" in message
        assert "'crisis' at 99.9967" in message

        # 2/5 a tie for the maximum.  The posterior does not single out a state,
        # so publishing one as settled is an overclaim -- the label is not even
        # checkable, let alone correct.
        tied = self._posterior({"bull": 50.0, "crisis": 50.0, "calm": 0.0})
        assert_only(tied, "NUM-025")
        assert "tied at the top" in find_for(tied, "NUM-025")[0].message

        # 3/5 an entirely null posterior: the state is undetermined, not correct.
        nulled = self._posterior({"bull": None, "crisis": None, "calm": None})
        assert_only(nulled, "NUM-025")
        assert "undetermined, not correct" in find_for(nulled, "NUM-025")[0].message

        # 4/5 no posterior beside the label at all.  The label is then an
        # UNVERIFIED action input, which is the one thing this rule must never
        # report as a pass.
        unverified = self._posterior(healthy)
        del unverified["sections"]["regime"]["data"]["regime_probabilities"]
        assert_only(unverified, "NUM-025")
        assert "unverified" in find_for(unverified, "NUM-025")[0].message

        # 5/5 a state the posterior does not name.
        unnamed = self._posterior(healthy, current_regime="melt_up")
        assert_only(unnamed, "NUM-025")
        assert "is not a state the posterior names" in find_for(unnamed, "NUM-025")[0].message

    # ---- NUM-026 (a point estimate against the companion it summarises)

    def _tail_mean(
        self,
        section: str,
        point: str,
        quantile: str,
        *,
        tail: float = -0.00874386,
        cutoff: float = -0.00643209,
    ) -> dict[str, Any]:
        """A block publishing a conditional tail mean beside the quantile that
        selects that tail, under either section's own vocabulary.

        INERT SCAFFOLDING, NOT A MEASUREMENT.  ``var_95_standard_error`` below
        is INVENTED -- it is not a standard error of anything, was not measured
        off any series, and is not a figure the v5 exporter has ever published
        (the real artifact carries exactly one interval, and NUM-022 exists to
        reject it).  It is here solely as ENV-020's price of admission: a
        section of naked point estimates fails ENV-020 whatever this rule says,
        and ENV-020 firing alongside NUM-026 would make ``assert_only`` fail for
        the wrong reason and hide the identity under test.

        It must never be read as a real disclosure, and nothing about it is
        asserted -- no rule is exercised on its value.  Verified: delete it and
        this helper's exports fail ENV-020 instead of NUM-026.
        """
        return make_export(
            {
                section: _section(
                    section,
                    {
                        "data_status": "available",
                        point: tail,
                        quantile: cutoff,
                        # INVENTED, inert, ENV-020 admission price -- see docstring.
                        f"{quantile}_standard_error": 0.001187,
                    },
                )
            }
        )

    def _prob_success_table(self) -> tuple[float, dict[str, float]]:
        """The synthetic terminal-percentile table the prob_success cases stand on.

        Purely an input to :meth:`_prob_success_bracket`; nothing here is a
        measurement.  Two properties are load-bearing and are checked on their
        own terms by ``test_num026_the_percentile_table_the_prob_success_cases_
        stand_on_is_consistent``, which runs first: the table is monotone, like
        any table the exporter can publish (NUM-013's own precondition), and the
        target sits STRICTLY inside the published range with a level on each
        side of it, so neither the floor nor the ceiling is vacuous.
        """
        return 2.5, {"p5": 1.0, "p25": 2.0, "p50": 3.0, "p75": 4.0, "p95": 5.0}

    @staticmethod
    def _prob_success_bracket(
        target: float, percentiles: dict[str, float]
    ) -> tuple[tuple[float, float], tuple[float, float]]:
        """The bracket the published table requires, derived HERE from that table.

        A SECOND, independent reading of the same published numbers.  It is not
        the rule's bracket and never sees it; it exists so the assertions can be
        about the RELATION -- do the rule's verdicts agree with what the table
        implies? -- instead of about the rule's prose.  No expected bracket is
        written down anywhere in this file, because the floor of this relation
        has been re-derived twice and both times it was pinned in a test
        assertion first, which is how an assertion about a number gets made and
        how it then breaks the moment the number is corrected.

        ``p_c`` is the published ``c``-th percentile of the terminal values of
        the very paths ``prob_success`` counts, and ``t`` the published target.
        The defining property of a quantile gives two inclusions:

        * ``P(T <= p_c) >= c/100``, so mass at or BELOW a level that falls short
          of ``t`` is mass that fails to clear it.  Every ``c`` with ``p_c < t``
          therefore yields the CEILING ``1 - c/100``, and the weakest of them --
          the one every correct derivation must respect whatever else it assumes
          -- is the SMALLEST such ``c``.
        * ``P(T < p_c) <= c/100``, so a level at or above ``t`` has at least
          ``1 - c/100`` of the mass at or above it, and all of that mass clears
          ``t``.  Every ``c`` with ``p_c >= t`` therefore yields the FLOOR
          ``1 - c/100``, and the weakest of them is the LARGEST such ``c``.

        Every floor in ``[1 - max/100, 1 - min/100]`` over the clearing levels,
        and every ceiling in ``[1 - min/100, 1 - max/100]`` over the short ones,
        is a correct reading of the same table, and which of them a rule chooses
        is its own business.  So this returns the two extremes of that family --
        ``(loose, tight)`` -- and the tests below only probe where the family
        AGREES: inside ``tight`` the rule must stay silent under any correct
        derivation, and outside ``loose`` it must fire.  The gap between them is
        deliberately left unprobed: there, the verdict is a property of the
        derivation the rule's owner owns, not of the published table.
        """
        below: list[float] = []
        at_or_above: list[float] = []
        for key, value in percentiles.items():
            level = re.fullmatch(r"p(\d+(?:\.\d+)?)", str(key))
            assert level is not None, f"{key!r} is not a published percentile level"
            assert isinstance(value, (int, float)) and not isinstance(value, bool)
            assert float("-inf") < float(value) < float("inf"), (
                f"{key!r}={value!r} is not a finite terminal value"
            )
            (at_or_above if float(value) >= target else below).append(
                float(level.group(1))
            )
        assert below and at_or_above, (
            "the table has no level on one side of the target, so one bound is "
            f"vacuous: below={sorted(below)} at_or_above={sorted(at_or_above)}"
        )
        tight = (1.0 - min(at_or_above) / 100.0, 1.0 - max(below) / 100.0)
        loose = (1.0 - max(at_or_above) / 100.0, 1.0 - min(below) / 100.0)
        return loose, tight

    def test_num026_the_percentile_table_the_prob_success_cases_stand_on_is_consistent(
        self,
    ) -> None:
        """The table is a distribution, not numbers picked until a rule went quiet.

        Every prob_success case is decided by comparing a figure against a
        bracket derived from this table, so if the table were incoherent the
        comparison would be meaningless and the red cases would prove nothing.
        A table with no level at or above the target has no floor at all, so an
        arbitrary ``prob_success`` would sit inside it; a table that is not
        monotone is not a table the exporter could publish.  So the fixture is
        checked on its own terms here, before anything is asserted from it.
        """
        target, table = self._prob_success_table()

        # 1/4 every key is a real percentile level, strictly inside (0, 100),
        #     and no level is published twice.
        levels: list[tuple[str, float]] = []
        for key in table:
            match = re.fullmatch(r"p(\d+(?:\.\d+)?)", str(key))
            assert match is not None, f"{key!r} is not a published percentile level"
            level = float(match.group(1))
            assert 0.0 < level < 100.0, f"{key!r} is not an interior percentile"
            levels.append((str(key), level))
        assert len({level for _, level in levels}) == len(levels), (
            f"duplicate levels: {sorted(level for _, level in levels)}"
        )

        # 2/4 the table is non-decreasing in its level, which is the very
        #     precondition NUM-013 enforces on a published one.
        ordered = sorted((level, float(table[key])) for key, level in levels)
        for (low_level, low), (high_level, high) in zip(ordered, ordered[1:]):
            assert low <= high, (
                f"p{low_level:g}={low} exceeds p{high_level:g}={high}; a "
                "percentile table that is not monotone is not a table"
            )

        # 3/4 the target is strictly inside the published range, so the table
        #     really brackets it and the relation is testable in both directions.
        values = [value for _, value in ordered]
        assert values[0] < target < values[-1], (
            f"target_value={target} is not strictly inside the published range "
            f"[{values[0]}, {values[-1]}], so one bound is vacuous"
        )

        # 4/4 the two derivations of the bracket are well ordered and enclose a
        #     band of real width -- not a point, and not an inverted interval.
        loose, tight = self._prob_success_bracket(target, table)
        assert 0.0 <= loose[0] < tight[0] <= tight[1] < loose[1] <= 1.0, (
            f"the bracket the table requires is not well ordered: "
            f"loose={loose} tight={tight}"
        )

    def test_num026_a_point_estimate_must_agree_with_its_companion(self) -> None:
        """Every identity in ``COMPANION_MAP``, one red case each.

        These are the identities a consumer ACTS on, and they are the ones with
        no other rule: a string, a boolean or a single number is internally
        consistent with everything the document says, so the table had nothing to
        compare it against.  Each red case corrupts ONE leaf of its own healthy
        document, and each healthy document is asserted silent -- a rule that
        fires on all eight of them fires on anything.
        """
        # 1/8 prob_success against the percentile table of the same paths.
        #
        # NOT a restatement of the bracket the rule derives.  The bracket is
        # derived here, by ``_prob_success_bracket``, from this fixture's own
        # ``terminal_percentiles``; the rule derives its own from the same
        # numbers; and what is asserted is that the two VERDICTS agree.  No
        # expected bracket string appears anywhere in this test: the floor of
        # this relation has been re-derived twice and both times it was pinned
        # in an assertion here first, which is how an assertion about a number
        # gets made and then breaks the moment the number is corrected.
        #
        # So the three probes are placed against the DERIVATION, in the two
        # regions where every correct reading of the table gives the same
        # answer: one inside the tightest bracket any of them can produce, and
        # one outside the loosest.  Where they land is stated by assertion, so
        # a fixture change that moved the table would be caught here instead of
        # quietly turning the "silent" case into a meaningless one.
        target_value, terminal_percentiles = self._prob_success_table()
        monte_carlo = {
            "target_value": target_value,
            "terminal_percentiles": terminal_percentiles,
            "prob_success_units": "fraction_of_paths_ending_at_or_above_target",
            "initial_value": 42624.5,
            "fan": [
                {"year": 0.0, "p5": 42624.5, "p25": 42624.5, "p50": 42624.5,
                 "p75": 42624.5, "p95": 42624.5},
                {"year": 1.0, "p5": 40000.0, "p25": 45000.0, "p50": 52000.0,
                 "p75": 60000.0, "p95": 70000.0},
            ],
        }
        loose, tight = self._prob_success_bracket(target_value, terminal_percentiles)
        satisfied = sum(tight) / 2.0
        contradicts_low = loose[0] / 2.0
        contradicts_high = (1.0 + loose[1]) / 2.0
        assert tight[0] < satisfied < tight[1], (
            "the silent probe must be inside the tightest bracket any correct "
            f"derivation can produce, or the silent case proves nothing: {tight}"
        )
        assert 0.0 <= contradicts_low < loose[0], (
            "the low red probe must fall outside the loosest bracket any correct "
            "derivation can produce, or only this derivation fails it: "
            f"loose={loose}"
        )
        assert loose[1] < contradicts_high <= 1.0, (
            "the high red probe must fall outside the loosest bracket any correct "
            "derivation can produce, or only this derivation fails it: "
            f"loose={loose}"
        )

        # Silent: the figure SATISFIES the table, so no correct reading of it can
        # fire.  Without this, a rule that fired on everything would satisfy the
        # red case below and the pair would prove nothing.
        assert rule_ids(
            self._monte_carlo(prob_success=satisfied, **monte_carlo)
        ) == set()
        # Red on both sides: the table CONTRADICTS the figure.
        impossible = self._monte_carlo(prob_success=contradicts_low, **monte_carlo)
        assert_only(impossible, "NUM-026")
        too_high = self._monte_carlo(prob_success=contradicts_high, **monte_carlo)
        assert_only(too_high, "NUM-026")

        # SECONDARY, and deliberately not load-bearing: the finding has to name
        # the figure and the companion it contradicts, so an operator can act on
        # it.  No expected bracket and no expected numeric appear here -- a
        # derived value in this assertion is exactly what has to go.
        message = find_for(impossible, "NUM-026")[0].message
        assert "prob_success" in message
        assert "target_value" in message

        # 2/8 initial_value against the fan's own year-0 row: every simulated
        # path starts there, so the origin row is that value repeated.  The
        # prob_success it carries is the SAME probe case 1/8 proved silent, so
        # this case isolates the origin identity instead of restating a figure
        # that some other derivation of the bracket might also flag.
        origin = self._monte_carlo(
            prob_success=satisfied, **dict(monte_carlo, initial_value=51200.0)
        )
        assert_only(origin, "NUM-026")
        assert "every simulated path starts at initial_value" in (
            find_for(origin, "NUM-026")[0].message
        )

        # 3/8 effective_positions against the Herfindahl index it is 1/HHI of.
        concentration = {
            "data_status": "available",
            "herfindahl_index": 0.0856,
            "effective_positions": 11.68,
            "effective_positions_note": "N_eff is computed on the UNROUNDED index",
        }
        assert rule_ids(
            make_export({"concentration": _section("concentration", dict(concentration))})
        ) == set()
        overstated = dict(concentration, effective_positions=9.8)
        export = make_export({"concentration": _section("concentration", overstated)})
        assert_only(export, "NUM-026")
        assert "N_eff is defined as 1/HHI" in find_for(export, "NUM-026")[0].message

        # 4/8 cvar_95 against the var_95 whose tail it is the mean of.
        annual = self._tail_mean("realized_risk", "cvar_95", "var_95")
        assert rule_ids(annual) == set()
        milder = clone(annual)
        milder["sections"]["realized_risk"]["data"]["cvar_95"] = -0.0051
        assert_only(milder, "NUM-026")
        assert "cannot be the milder of the two" in find_for(milder, "NUM-026")[0].message

        # 5/8 the same identity under risk_contribution's own vocabulary, on the
        # daily figures rather than the annual ones.
        daily = self._tail_mean(
            "risk_contribution",
            "portfolio_cvar_95_daily",
            "portfolio_var_95_daily",
            tail=-0.0341,
            cutoff=-0.027846,
        )
        assert rule_ids(daily) == set()
        shallower = clone(daily)
        shallower["sections"]["risk_contribution"]["data"][
            "portfolio_cvar_95_daily"
        ] = -0.018
        assert_only(shallower, "NUM-026")
        message = find_for(shallower, "NUM-026")[0].message
        assert "portfolio_var_95_daily" in message
        assert "cannot be the milder of the two" in message

        # 6/8 expected_sharpe rebuilt from the three moments beside it.
        #
        # INERT SCAFFOLDING, NOT A MEASUREMENT.
        # ``expected_sharpe_standard_error`` is INVENTED.  It is not the
        # standard error of this Sharpe, was not measured off any return series,
        # and the v5 exporter publishes no such figure -- ENV-020's own docstring
        # records that ``standard_error`` appears zero times in the real 876 KB
        # artifact.  It exists only so ENV-020 (naked point estimates) does not
        # also fire and confuse ``assert_only``; delete it and this document
        # fails ENV-020 instead of NUM-026.  No rule is exercised on its value
        # and it must not be read as real disclosure.
        moments = {
            "data_status": "available",
            "expected_annual_return": 0.1614,
            "expected_annual_volatility": 0.14,
            "risk_free_rate": 0.02,
            "expected_sharpe": 1.01,
            # INVENTED, inert, ENV-020 admission price -- see comment above.
            "expected_sharpe_standard_error": 0.2134,
            "moments_basis": {
                "display_rounding": {"moment_decimals": 4},
                "formulas": "expected_sharpe = (expected_annual_return - "
                            "risk_free_rate) / expected_annual_volatility",
            },
        }
        assert rule_ids(
            make_export({"optimization": _section("optimization", dict(moments))})
        ) == set()
        restated = dict(moments, expected_sharpe=1.7)
        export = make_export({"optimization": _section("optimization", restated)})
        assert_only(export, "NUM-026")
        assert "one of them being restated rather than computed" in (
            find_for(export, "NUM-026")[0].message
        )

        # 7/8 a test verdict against the p-value and threshold the same scan
        # declares.  The p-value key and the threshold key are derived from the
        # declared decision-test name, so the fixture declares the test too.
        scan = {
            "test_agreement": {
                "decision_test": "engle_granger",
                "agreement_count": 5,
                "disagreement_count": 1,
                "counted_pairs": 6,
            },
            "signal_policy": {
                "p_value_threshold_comparison": "strictly_less_than",
                "engle_granger_p_value_threshold": 0.05,
            },
            "pairs": [
                {"ticker_a": "AAA.NS", "ticker_b": "BBB.NS",
                 "is_cointegrated": True, "engle_granger_pvalue": 0.013557}
            ],
        }
        assert rule_ids(self._pairs(**scan)) == set()
        contradicted = self._pairs(**dict(scan, pairs=[
            {"ticker_a": "AAA.NS", "ticker_b": "BBB.NS",
             "is_cointegrated": True, "engle_granger_pvalue": 0.513557}
        ]))
        assert_only(contradicted, "NUM-026")
        assert "is a label, not a result" in (
            find_for(contradicted, "NUM-026")[0].message
        )

        # 8/8 the alert arm its own correlation selects.  A current correlation
        # of 0.1483 is at or below the published 10th percentile, so the honest
        # document is publishing ELEVATED/lower_tail_collapse/True.  The red
        # case is the correlation moving to 0.4621 -- at or above the 90th
        # percentile, the CRITICAL arm -- while those three labels stand still.
        #
        # INERT SCAFFOLDING, NOT A MEASUREMENT.
        # ``current_avg_correlation_standard_error`` is INVENTED.  It is not the
        # standard error of this correlation, was not measured off any window of
        # pair correlations, and the v5 exporter publishes no such figure.  It
        # exists only so ENV-020 (naked point estimates) does not also fire and
        # confuse ``assert_only``; delete it and this document fails ENV-020
        # instead of NUM-026.  No rule is exercised on its value and it must not
        # be read as real disclosure.
        stability = {
            "data_status": "available",
            "current_avg_correlation": 0.1483,
            # INVENTED, inert, ENV-020 admission price -- see comment above.
            "current_avg_correlation_standard_error": 0.0312,
            "historical_threshold_10th": 0.2179,
            "historical_threshold_75th": 0.4129,
            "historical_threshold_90th": 0.459,
            "alert_level": "ELEVATED",
            "alert_direction": "lower_tail_collapse",
            "is_regime_break": True,
        }

        def _stability(**figures: Any) -> dict[str, Any]:
            return make_export(
                {
                    "risk_studio": _section(
                        "risk_studio",
                        {
                            "data_status": "available",
                            "components": {
                                "correlation_stability": {
                                    "data_status": "available",
                                    **dict(stability, **figures),
                                }
                            },
                        },
                    )
                }
            )

        assert rule_ids(_stability()) == set()
        moved = _stability(current_avg_correlation=0.4621)
        assert_only(moved, "NUM-026")
        message = find_for(moved, "NUM-026")[0].message
        assert "at or above" in message
        assert "historical_threshold_90th" in message


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
        assert out.index("ENVELOPE  (21 rules)") < out.index("CROSS-SECTION")
        assert out.index("CROSS-SECTION") < out.index("NUMERIC")
        assert "PER-SECTION VERDICT" in out
        assert "SUMMARY" in out


# --------------------------------------------------------------------------
# Which rule ids this file actually exercises.
#
# DERIVATION DIRECTION, stated once because it is the whole point:
#
#     ca.RULES (the table)  ──>  the ids that MUST be covered
#     this file's own source ──>  the ids that ARE covered
#
# ``EXERCISED_RULE_IDS`` is derived by PARSING THIS FILE and asking, of every
# test function, "which rule ids do you name inside an assertion?".  It is not
# typed out by hand.  A hand-written list is a promise; this is a reading of
# the tests that are actually there, and the two disagree the moment a body
# stops asserting.
#
# The previous hand-maintained 57-id set could not fail for the reason it
# existed: it was a set difference between a list someone wrote down and the
# rule table, so all 57 ids could be listed with zero tests and it stayed
# green.  Stubbing a test body and leaving the id in the list was invisible to
# it.  Deriving the set is what makes the stub visible.
#
# Why the three-tier predicate, and not a plain "does this string appear in the
# file" scan:
#
#   * Only ``test_*`` functions count.  A helper that builds a fixture is not a
#     test; ids inside one are claims nobody checked.
#   * Only string CONSTANTS count, so a mention in a comment cannot claim a
#     rule.  A raw text scan would be satisfied by the word "NUM-025" in a
#     sentence, which is the failure mode a source scan is usually assumed to
#     have and usually has.
#   * Only constants inside an ASSERTING statement count -- a bare ``assert``
#     or a call to ``assert_only`` -- and NOT under a negation.  This is what
#     excludes the real counter-examples in this very file: ``assert "ENV-001"
#     not in out`` (line ~3276) and the ``NOPE-999`` unknown-id case both name a
#     rule id inside an assertion while proving the opposite of coverage.
#     Counting them would let a test be deleted and the id survive on the
#     evidence of the test that denies it.
#   * Docstrings are excluded, so the prose that explains a rule cannot claim
#     it.  ``test_num025_...`` and friends describe the rule in their docstring;
#     a stubbed body with its docstring left behind would otherwise pass.
#
# What is still hand-maintained, and why it cannot be derived: the ids named in
# a test that are NOT rules.  ``NOPE-999`` is a deliberately absent id used to
# prove the CLI rejects an unknown ``--rule``.  It is not a coverage hole, and
# nothing in the source distinguishes "an id I forgot to add to the table" from
# "an id this test asserts is absent" -- so that one distinction is declared
# here, and ``test_every_claimed_id_is_either_a_rule_or_a_declared_stranger``
# holds the declaration to exactly what the tests actually need.
# --------------------------------------------------------------------------

#: The shape every rule id in ``ca.RULES`` must have.  Derived from the table
#: in the assertion below rather than trusted, so a new id cannot quietly fall
#: outside the scan and go uncovered without anyone noticing.
_RULE_ID_SHAPE = re.compile(r"[A-Z]{2,4}-\d{3}")

#: Ids this file names inside an assertion that are deliberately NOT rules.
#: Hand-maintained because the intent cannot be read from the source; asserted
#: to be exactly the set the tests need in
#: ``test_every_claimed_id_is_either_a_rule_or_a_declared_stranger``.
DECLARED_NON_RULE_IDS: frozenset[str] = frozenset({"NOPE-999"})


def _is_asserting_statement(node: ast.stmt) -> bool:
    """True for a statement that can fail the test.

    ``assert_only`` counts: it is this file's own assertion helper and it
    raises, so a test that only calls it is a test.  Anything else -- an
    assignment, a fixture call, a bare expression -- is not.
    """
    if isinstance(node, ast.Assert):
        return True
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "assert_only"
    )


def _sits_under_negation(
    node: ast.AST, parents: dict[ast.AST, ast.AST]
) -> bool:
    """True if ``node`` is an operand of a ``not`` / ``not in`` / ``!=``.

    ``assert "ENV-001" not in out`` names ENV-001 inside an assertion, and it
    is evidence that ENV-001 is NOT exercised there.  Counting it would let a
    test be gutted while its id stayed alive on the strength of the assertion
    that denies it.
    """
    child: ast.AST | None = node
    parent = parents.get(node)
    while parent is not None:
        if isinstance(parent, ast.UnaryOp) and isinstance(parent.op, ast.Not):
            return True
        if isinstance(parent, ast.Compare):
            # `x not in y` / `x is not y` / `x != y` each pair an op with an
            # OPERAND: the first op owns `left`, every later op owns the
            # comparator at the matching index.  Walking the operands
            # independently of the ops is wrong -- `a != b` has one op and two
            # operands, so a zip would silently skip `b` and let
            # `assert ids != ["NUM-001"]` claim NUM-001.
            operands = [parent.left, *parent.comparators]
            negated = any(
                isinstance(op, (ast.NotIn, ast.IsNot, ast.NotEq))
                for op in parent.ops
            )
            if negated and child in ast.walk(ast.Tuple(elts=operands, ctx=ast.Load())):
                return True
        child, parent = parent, parents.get(parent)
    return False


def _claimed_ids_in_source(source: str) -> dict[str, set[str]]:
    """Map rule id -> names of the ``test_*`` functions in ``source`` asserting it.

    Split out from :func:`_asserted_ids_by_test` so the predicate is testable
    against synthetic sources; ``test_the_claim_scanner_tells_a_real_test_from_a_hollow_one``
    pins the cases that matter, and both the guard and that test go through
    this one function.
    """
    tree = ast.parse(source)
    parents = {
        child: node
        for node in ast.walk(tree)
        for child in ast.iter_child_nodes(node)
    }

    # Docstrings explain rules; they do not exercise them.  Collected across
    # the whole tree so a nested helper's docstring is excluded too.
    docstrings: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(body[0])

    claimed: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test"):
            continue
        # A nested def is not a test of its own, so its own asserts are not
        # this test's evidence -- otherwise a test could delegate every
        # assertion to a helper and still look like coverage.
        for stmt in ast.walk(node):
            if stmt in docstrings or not _is_asserting_statement(stmt):
                continue
            owner = parents.get(stmt)
            while owner is not None and owner is not node:
                if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    break
                owner = parents.get(owner)
            else:
                owner = None
            if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for child in ast.walk(stmt):
                if not (
                    isinstance(child, ast.Constant)
                    and isinstance(child.value, str)
                    and _RULE_ID_SHAPE.fullmatch(child.value)
                ):
                    continue
                if _sits_under_negation(child, parents):
                    continue
                claimed.setdefault(child.value, set()).add(node.name)
    return claimed


def _asserted_ids_by_test() -> dict[str, set[str]]:
    """The same reading, taken from THIS file.

    A test that stops asserting on an id simply stops appearing in that id's
    set, which is what makes a stubbed body visible to the guard.
    """
    return _claimed_ids_in_source(Path(__file__).read_text(encoding="utf-8"))


#: rule id -> names of the tests in THIS file that assert on it.  The guard
#: below reads this, not a hand-written list.
EXERCISED_RULE_IDS: set[str] = set(_asserted_ids_by_test())
