"""Disclosure and freshness: the six defects that shipped a degradation unsaid.

Every gate rule this wave targets is a claim about the SHAPE of the export, so
these tests assert the shape at the same seam the exporter builds it: the real
`_make_section`, the real route functions, the real `PortfolioContextService`
collectors, and the real audit rules fed the payload those produce. Running the
audit CLI against the saved `v8.json` export would prove nothing here - that
artifact is a frozen read of the OLD source - so the rules are exercised
directly against freshly built payloads instead.

Covered:

* ENV-016 - `volatility_sizing`, `tear_sheet`, `risk_contribution`, `regime` and
  `risk_studio` each publish a degradation with an empty `warnings` array. Each
  derived warning is asserted to quote a fact the payload actually carries, and
  a section with no degradation is asserted to gain no warning.
* ENV-019 - 13 of 14 trades stamped `executable` inside a section whose own
  `execution.execution_eligible` is false.
* ENV-021 - `coverage_ratio: 0` asserted beside `covered_count: null`.
* DI-1 - `portfolio.as_of` later than the envelope's own `generated_at`, naming
  a Saturday with NSE shut.
* DI-2 - `concentration` / `stress_testing` / `liquidity` numbers with no date.
* DI-5 - `portfolio.omitted_fields: []` while book-level aggregates are absent.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_mod
from app.api.analytics import (
    BLOCKED_BY_SECTION_GATE_STATUS,
    CONCENTRATION_NO_VALUATION_DATE_WARNING,
    CONCENTRATION_VALUATION_BASIS,
    EXECUTABLE_TRADE_STATUSES,
    TRADE_GATE_RECONCILIATION_RULE,
    _reconcile_trade_status_with_gate,
    get_concentration_metrics,
    get_liquidity_metrics,
    get_volatility_sizing,
    run_stress_test,
)
from app.api.portfolio import (
    PORTFOLIO_AS_OF_SEMANTICS,
    PORTFOLIO_VALUATION_BASIS,
    _holding_date_provenance,
    _latest_delivered_close_date,
    _quote_refresh_instant,
    get_portfolio,
)
from app.debugging import context_audit as ca
from app.models.database import PortfolioPosition, StockTimeseries
from app.models.schemas import StressTestRequest
from app.services import ai_context_service as svc
from app.services.ai_context_service import (
    AS_OF_STALENESS_DAYS,
    COVERAGE_COUNT_KEYS,
    PORTFOLIO_AGGREGATES_NOT_PRODUCED,
    STRESS_AS_OF_BASIS,
    STRESS_AS_OF_SEMANTICS,
    PortfolioContextService,
    _degradation_warnings,
    _drop_unmeasured_coverage_ratios,
)

#: The export clock every freshness assertion in this file measures against.
EXPORT_START = datetime(2026, 9, 26, 18, 7, 11, tzinfo=timezone.utc)
EXPORT_START_TEXT = "2026-09-26T18:07:11.579749Z"


# ---------------------------------------------------------------------------
# audit harness: the rules are the assertion, the payload is the fixture
# ---------------------------------------------------------------------------
def _section(
    key: str,
    data: Any,
    *,
    status: str = "available",
    as_of: str | None = "2026-09-25",
    semantics: str | None = "latest_observation_date",
    warnings: list[str] | None = None,
    error: str | None = None,
    omitted: list[str] | None = None,
) -> dict[str, Any]:
    section: dict[str, Any] = {
        "key": key,
        "title": key.replace("_", " ").title(),
        "route": f"/{key}",
        "status": status,
        "detail": "summary",
        "generated_at": EXPORT_START_TEXT,
        "inputs": {},
        "coverage": None,
        "data": data,
        "omitted_fields": list(omitted or []),
        "as_of": as_of,
        "as_of_semantics": semantics,
        "currency": "INR",
        "warnings": list(warnings or []),
    }
    if error:
        section["error"] = error
    return section


def make_export(sections: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Minimal envelope that passes every rule except the one under test."""
    return {
        "schema_version": ca.EXPECTED_SCHEMA_VERSION,
        "export_id": "portfolio-fresh0000",
        "generated_at": EXPORT_START_TEXT,
        "completed_at": "2026-09-26T18:07:48.880737Z",
        "snapshot_consistency": "best_effort",
        "base_currency": "INR",
        "detail": "summary",
        "scope": list(sections),
        "sections": sections,
        "warnings": [],
    }


def rule_ids(sections: dict[str, dict[str, Any]]) -> set[str]:
    export = make_export(sections)
    return {
        finding.rule_id
        for finding in ca.run_rules(ca.Export(doc=export, raw=json.dumps(export)))[0]
    }


def only(sections: dict[str, dict[str, Any]], rule_id: str) -> str:
    """The message of `rule_id`, asserting it is the ONLY rule that fires."""
    export = make_export(sections)
    findings = ca.run_rules(ca.Export(doc=export, raw=json.dumps(export)))[0]
    assert {finding.rule_id for finding in findings} == {rule_id}, [
        (finding.rule_id, finding.message) for finding in findings
    ]
    return findings[0].message


# ---------------------------------------------------------------------------
# seams
# ---------------------------------------------------------------------------
def _service() -> PortfolioContextService:
    return PortfolioContextService(
        db=Mock(),
        data_service=Mock(),
        analytics_engine=Mock(),
        benchmark_service=Mock(),
        cache_service=Mock(),
    )


def _section_for(key: str, data: Any, **kwargs: Any):
    """Build a section through the real exporter seam."""
    return _service()._make_section(
        key=key, data=data, inputs={}, detail="summary", **kwargs
    )


def _rows(rows):
    scalars = MagicMock()
    scalars.all.return_value = list(rows)
    scalars.first.return_value = rows[0] if rows else None
    result = MagicMock()
    result.scalars.return_value = scalars
    result.scalar_one_or_none.return_value = rows[0] if rows else None
    return result


def _db(rows):
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=lambda *_a, **_k: _rows(rows))
    return db


def _pos(ticker, *, market_value, sector="Tech", region="IN", updated_on=None):
    return PortfolioPosition(
        id=1,
        ticker=ticker,
        weight=None,
        quantity=1.0,
        buy_price=market_value,
        last_price=market_value,
        market_value=market_value,
        region=region,
        sector=sector,
        industry="Y",
        added_on=None,
        updated_on=updated_on,
    )


class _Market:
    """OHLCV frames keyed by ticker, in either DataService delivery shape.

    `column_dates=True` reproduces the shape a fresh vendor fetch delivers:
    `date` as a COLUMN over an integer RangeIndex. That is the shape the
    liquidity route used to project away before reading it.
    """

    def __init__(self, frames, *, column_dates: bool = False, caps=None):
        self.frames = frames
        self.column_dates = column_dates
        self.caps = caps or {}
        self.fetch_historical_data = AsyncMock(side_effect=self._history)
        self.fetch_quote = AsyncMock(side_effect=self._quote)

    async def _history(self, ticker, start, end):
        frame = self.frames.get(ticker)
        if frame is None:
            return pd.DataFrame()
        frame = frame.copy()
        if "date" in frame.columns:
            dated = pd.to_datetime(frame["date"])
            frame = frame.loc[
                (dated >= pd.Timestamp(start)) & (dated <= pd.Timestamp(end))
            ]
        else:
            frame = frame.loc[
                (frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))
            ]
        return frame

    async def _quote(self, ticker):
        return {"market_cap": self.caps.get(ticker)}


def _ohlcv(dates, *, price=100.0, volume=1_000_000.0):
    return pd.DataFrame(
        {"Close": np.full(len(dates), price), "Volume": np.full(len(dates), volume)},
        index=pd.DatetimeIndex(dates),
    )


class _StubFX:
    def get_exchange_rate(self, *_a, **_k):
        return 1.0

    def get_exchange_rate_info(self):
        return {}


@pytest.fixture(autouse=True)
def _stable_export_clock():
    """Every `_make_section` call measures staleness against the export clock;
    pin it so the assertions are about the code, not about when they ran."""
    previous = svc._EXPORT_STARTED_AT[0]
    svc._EXPORT_STARTED_AT[0] = EXPORT_START
    yield
    svc._EXPORT_STARTED_AT[0] = previous


# ===========================================================================
# ENV-016: a section that publishes a degradation has to name it
# ===========================================================================
class TestEnv016DegradationIsNamed:
    def test_volatility_sizing_gate_is_named_in_warnings(self) -> None:
        """The section says `available` while its own execution block refuses the
        target. The warning quotes that refusal and its measured financing."""
        data = {
            "data_status": "available",
            "latest_observation_date": "2026-09-25",
            "execution": {
                "execution_eligible": False,
                "block_reasons": ["financing_required"],
                "block_reason": (
                    "Gross exposure 1.295310 exceeds 1.0; the target borrows "
                    "0.295310 of the portfolio value and is not a normal rebalance"
                ),
                "financing_requirement": 12878.08,
                "financing_requirement_currency": "INR",
            },
            "trades": {"AAA.NS": {"shares_delta": 2, "status": "executable"}},
        }
        section = _section_for("volatility_sizing", data)

        assert section["status"] == "available", "the status is not the lever here"
        assert section["warnings"], "a published gate must be named in warnings"
        warning = section["warnings"][0]
        # Every clause of the warning is a fact the payload carries.
        assert "not a normal rebalance" in warning
        assert "12,878.08" in warning and "INR" in warning
        assert section["data"]["execution"]["block_reasons"] == ["financing_required"]
        assert "ENV-016" not in rule_ids({"volatility_sizing": section})

    def test_gate_free_sizing_gains_no_warning(self) -> None:
        """No gate means no degradation to name; a warning here would invent one."""
        section = _section_for(
            "volatility_sizing",
            {
                "data_status": "available",
                "latest_observation_date": "2026-09-25",
                "execution": {"execution_eligible": True, "block_reasons": []},
            },
        )
        assert section["warnings"] == []

    def test_risk_contribution_failure_is_named(self) -> None:
        """A section that 500'd published `unavailable` plus an error and no
        warning at all."""
        section = _section_for(
            "risk_contribution", None, status="unavailable", error="Internal server error"
        )
        assert section["warnings"]
        assert "Internal server error" in section["warnings"][0]
        assert "no measurement" in section["warnings"][0]
        assert "ENV-016" not in rule_ids({"risk_contribution": section})

    def test_tear_sheet_truncated_window_is_named_with_the_measured_count(self) -> None:
        """19 measured days against a 365-day request, truncated by the endpoint."""
        section = _section_for(
            "tear_sheet",
            {
                "data_status": "partial",
                "latest_observation_date": "2026-09-22",
                "requested_window": {"start": "2025-09-27", "end": "2026-09-26"},
                "measured_window": {
                    "start": "2026-08-25",
                    "end": "2026-09-22",
                    "days": 19,
                    "truncated_to_holding_window": True,
                },
            },
            status="partial",
        )
        assert section["warnings"]
        warning = section["warnings"][0]
        assert "19" in warning and "365" in warning
        assert "truncated_to_holding_window" in warning
        assert "ENV-016" not in rule_ids({"tear_sheet": section})

    def test_regime_truncated_history_is_named(self) -> None:
        section = _section_for(
            "regime",
            {
                "data_status": "partial",
                "as_of": "2026-09-24",
                "history_coverage": {
                    "requested_start": "2023-09-22",
                    "covered_days": 19,
                    "truncated": True,
                    "annualized": False,
                },
            },
            status="partial",
        )
        assert section["warnings"]
        assert "19" in section["warnings"][0]
        assert "truncated" in section["warnings"][0].lower()
        assert "ENV-016" not in rule_ids({"regime": section})

    def test_regime_without_a_window_block_falls_back_to_its_declared_status(self) -> None:
        """No window to quote is not a reason to stay silent: the endpoint's own
        `data_status` is still a fact the payload declares."""
        section = _section_for("regime", {"data_status": "partial"}, status="partial")
        assert section["warnings"]
        assert "data_status" in section["warnings"][0]
        assert "'partial'" in section["warnings"][0]

    def test_risk_studio_names_its_omissions_and_its_dead_component(self) -> None:
        """A 120-point correlation series is trimmed to 60 in a summary export, so
        the section's own ledger is non-empty; and its risk_contribution
        component produced nothing."""
        series = [
            {"date": f"2026-01-{day:02d}", "value": 0.1} for day in range(1, 29)
        ] * 5
        section = _section_for(
            "risk_studio",
            {
                "data_status": "partial",
                "components": {
                    "risk_contribution": {"status": "unavailable", "data": None},
                    "correlation_stability": {
                        "status": "available",
                        "data": {"as_of": "2026-09-25", "series": series},
                    },
                },
            },
            status="partial",
        )
        assert "components.correlation_stability.data.series" in section["omitted_fields"]
        joined = " ".join(section["warnings"])
        assert "components.correlation_stability.data.series" in joined
        assert "risk_contribution" in joined
        assert "ENV-016" not in rule_ids({"risk_studio": section})

    def test_an_available_unmarked_section_gains_no_warning(self) -> None:
        section = _section_for(
            "concentration", {"data_status": "available", "by_weight": {"A.NS": 1.0}}
        )
        assert section["status"] == "available"
        assert section["warnings"] == []

    def test_a_section_that_already_disclosed_is_not_told_twice(self) -> None:
        """Filling the empty list only: an existing disclosure has discharged the
        obligation, and a second generic sentence would be noise."""
        section = _section_for(
            "volatility_sizing",
            {
                "data_status": "available",
                "execution": {
                    "execution_eligible": False,
                    "block_reasons": ["financing_required"],
                },
            },
            warnings=["market caps are floored"],
        )
        assert section["warnings"] == ["market caps are floored"]

    def test_the_helper_is_a_projection_not_an_inventor(self) -> None:
        """An unremarkable payload yields nothing on its own; only an explicit
        degraded status produces the last-resort sentence, and that sentence
        reports the status rather than asserting a shortfall."""
        assert _degradation_warnings(
            {"by_weight": {"A.NS": 1.0}}, status="available", error=None, omitted=[]
        ) == []
        fallback = _degradation_warnings(
            {"by_weight": {"A.NS": 1.0}}, status="partial", error=None, omitted=[]
        )
        assert len(fallback) == 1
        assert "publishes no explanation" in fallback[0]
        assert "invented" not in fallback[0]


# ===========================================================================
# ENV-019: a per-trade status cannot override the section's own gate
# ===========================================================================
class TestEnv019TradeStatusRespectsGate:
    def test_gated_target_restates_every_executable_leg(self) -> None:
        execution = {
            "execution_eligible": False,
            "block_reasons": ["financing_required"],
            "block_reason": "Gross exposure 1.295310 exceeds 1.0",
            "financing_requirement": 12878.08,
            "financing_requirement_currency": "INR",
        }
        trades = {
            "AAA.NS": {"shares_delta": 2, "status": "executable", "reason": None},
            "BBB.NS": {"shares_delta": -1, "status": "executable"},
            "CCC.NS": {"shares_delta": 0, "status": "below_minimum_notional"},
        }
        reconciled, disclosure = _reconcile_trade_status_with_gate(trades, execution)

        for ticker in ("AAA.NS", "BBB.NS"):
            assert reconciled[ticker]["status"] == BLOCKED_BY_SECTION_GATE_STATUS
            assert reconciled[ticker]["status"] not in EXECUTABLE_TRADE_STATUSES
            # The engine's own leg verdict is preserved, not discarded.
            assert reconciled[ticker]["leg_status"] == "executable"
            assert reconciled[ticker]["execution_eligible"] is False
        # A leg that never claimed permission keeps its own status, and still
        # carries the gate.
        assert reconciled["CCC.NS"]["status"] == "below_minimum_notional"
        assert reconciled["CCC.NS"]["execution_eligible"] is False
        assert "leg_status" not in reconciled["CCC.NS"]
        assert disclosure["restated_trade_tickers"] == ["AAA.NS", "BBB.NS"]
        # The rule travels as a TEMPLATE and the counts in the published sentence
        # are this payload's own. A literal count written from one book would
        # state a number the section's own records contradict on any other book.
        assert "{restated_count}" in TRADE_GATE_RECONCILIATION_RULE
        assert "cannot collect 2 order instructions out of 3 legs" in disclosure["rule"]
        assert disclosure["rule"] == TRADE_GATE_RECONCILIATION_RULE.format(
            restated_count=disclosure["restated_trade_count"], total_count=3
        )

    def test_open_gate_leaves_every_status_untouched(self) -> None:
        trades = {"AAA.NS": {"shares_delta": 2, "status": "executable"}}
        reconciled, disclosure = _reconcile_trade_status_with_gate(
            trades, {"execution_eligible": True}
        )
        assert reconciled == trades
        assert disclosure is None

    def test_no_gate_published_leaves_every_status_untouched(self) -> None:
        """An engine that published no rule block has expressed no opinion."""
        trades = {"AAA.NS": {"shares_delta": 2, "status": "executable"}}
        reconciled, disclosure = _reconcile_trade_status_with_gate(trades, None)
        assert reconciled == trades
        assert disclosure is None

    def test_restated_trade_set_passes_env019(self) -> None:
        reconciled, _ = _reconcile_trade_status_with_gate(
            {"AAA.NS": {"shares_delta": 2, "status": "executable"}},
            {"execution_eligible": False, "block_reasons": ["financing_required"]},
        )
        section = _section(
            "volatility_sizing",
            {"execution": {"execution_eligible": False}, "trades": reconciled},
        )
        assert "ENV-019" not in rule_ids({"volatility_sizing": section})

    def test_the_unreconciled_shape_is_what_env019_catches(self) -> None:
        """Control: the defect is real and this exact payload trips the rule, so
        the passing test above is not passing vacuously."""
        section = _section(
            "volatility_sizing",
            {
                "execution": {"execution_eligible": False},
                "trades": {
                    "AAA.NS": {"shares_delta": 2, "status": "executable"},
                    "BBB.NS": {"shares_delta": -1, "status": "executable"},
                },
            },
        )
        assert "2 record(s)" in only({"volatility_sizing": section}, "ENV-019")

    def test_the_gate_warning_quotes_the_route_measured_gate(self) -> None:
        warning = analytics_mod._execution_gate_warning(
            {
                "execution_eligible": False,
                "block_reasons": ["financing_required"],
                "block_reason": "not a normal rebalance",
                "financing_requirement": 12878.08,
                "financing_requirement_currency": "INR",
            }
        )
        assert warning is not None
        assert "not a normal rebalance" in warning
        assert "12,878.08 INR" in warning
        assert analytics_mod._execution_gate_warning({"execution_eligible": True}) is None

    def test_the_executable_vocabulary_matches_the_audit_rule(self) -> None:
        """The restatement is only as complete as the list it reads; if the audit
        rule learns a new executable literal, this one has to learn it too."""
        assert set(EXECUTABLE_TRADE_STATUSES) == set(ca.EXECUTABLE_STATUSES)
        assert BLOCKED_BY_SECTION_GATE_STATUS not in ca.EXECUTABLE_STATUSES

    @pytest.mark.asyncio
    async def test_the_route_publishes_a_gated_trade_set(self) -> None:
        """End to end: a leveraged analytical target makes the shared rule demand
        financing, and the response must not hand back an order set."""
        dates = pd.bdate_range(end=pd.Timestamp("2026-09-18"), periods=300)
        rng = np.random.default_rng(3)
        frame = pd.DataFrame(
            {
                "adj_close": 100.0
                * np.cumprod(1.0 + rng.normal(0.0002, 0.002, len(dates)))
            },
            index=dates,
        )
        market = _Market({"AAA.NS": frame})
        db = _db([_pos("AAA.NS", market_value=10_000.0)])
        result = await get_volatility_sizing(
            model="EWMA",
            # A target far above the book's own volatility forces a scale > 1.
            target_volatility=0.5,
            portfolio_value=None,
            db=db,
            data_service=market,
            analytics_engine=analytics_mod.AnalyticsEngine(),
        )

        assert result["execution"]["execution_eligible"] is False
        assert result["execution"]["financing_required"] is True
        # No record in the list a consumer iterates claims to be placeable.
        assert result["trades"]
        for ticker, trade in result["trades"].items():
            assert trade["status"] not in EXECUTABLE_TRADE_STATUSES, ticker
            assert trade["execution_eligible"] is False, ticker
        disclosure = result["trade_gate_reconciliation"]
        assert disclosure["restated_trade_tickers"]
        assert disclosure["gate_source"] == "execution.execution_eligible"
        # The engine's own leg verdicts are all still readable.
        assert all(
            trade.get("leg_status") == "executable"
            for trade in result["trades"].values()
        )
        # The section-level sentence travels with the response, and the section
        # clears both rules with the payload this route actually produced.
        assert any("not executable" in warning for warning in result["warnings"])
        section = _section(
            "volatility_sizing",
            result,
            warnings=list(result["warnings"]),
        )
        fired = rule_ids({"volatility_sizing": section})
        assert "ENV-019" not in fired
        assert "ENV-016" not in fired


# ===========================================================================
# ENV-021: a ratio asserted over a count that was never taken
# ===========================================================================
class TestEnv021RatioNeedsACount:
    def _delivery_block(self) -> dict[str, Any]:
        return {
            "scope": "symbol_scoped",
            "status": "unavailable",
            "coverage_status": "unavailable",
            "coverage_status_reason": "no_requested_symbol_had_usable_delivery_history",
            "requested_symbols": ["AAA", "BBB"],
            "covered_symbols": None,
            "missing_symbols": ["AAA", "BBB"],
            "requested_count": 2,
            "covered_count": None,
            "coverage_ratio": 0.0,
        }

    def test_hard_zero_beside_a_null_count_is_dropped_with_a_reason(self) -> None:
        block = self._delivery_block()
        _drop_unmeasured_coverage_ratios({"component_coverage": {"delivery": block}})

        assert block["covered_count"] is None
        assert block["coverage_ratio"] is None
        assert block["coverage_ratio_status"] == "unavailable"
        assert "covered_count" in block["coverage_ratio_unavailable_reason"]
        section = _section("india_flows", {"component_coverage": {"delivery": block}})
        assert "ENV-021" not in rule_ids({"india_flows": section})

    def test_the_unreconciled_block_is_what_env021_catches(self) -> None:
        """Control: the same payload before the edit trips the rule."""
        section = _section(
            "india_flows", {"component_coverage": {"delivery": self._delivery_block()}}
        )
        assert "coverage_ratio is a hard 0" in only(
            {"india_flows": section}, "ENV-021"
        )

    def test_a_measured_zero_count_keeps_its_ratio(self) -> None:
        """Zero covered of two requested, MEASURED, is a real measurement and must
        survive: the fix drops ratios over absent counts, not over zeros."""
        block = {
            "requested_count": 2,
            "covered_count": 0,
            "covered_symbols": [],
            "coverage_ratio": 0.0,
        }
        _drop_unmeasured_coverage_ratios({"component_coverage": {"delivery": block}})
        assert block["coverage_ratio"] == 0.0
        assert "coverage_ratio_status" not in block
        section = _section("india_flows", {"component_coverage": {"delivery": block}})
        assert "ENV-021" not in rule_ids({"india_flows": section})

    def test_a_measured_partial_ratio_keeps_its_ratio(self) -> None:
        block = {"requested_count": 4, "covered_count": 3, "coverage_ratio": 0.75}
        _drop_unmeasured_coverage_ratios({"component_coverage": {"delivery": block}})
        assert block["coverage_ratio"] == 0.75

    def test_the_sibling_block_without_a_ratio_is_untouched(self) -> None:
        block = {
            "coverage_status": "unknown",
            "requested_count": None,
            "covered_count": None,
        }
        _drop_unmeasured_coverage_ratios({"component_coverage": {"flows": block}})
        assert block == {
            "coverage_status": "unknown",
            "requested_count": None,
            "covered_count": None,
        }

    def test_the_count_key_list_matches_the_audit_rule(self) -> None:
        assert set(COVERAGE_COUNT_KEYS) == set(ca.COVERAGE_COUNT_KEYS)


# ===========================================================================
# DI-1: portfolio.as_of is an observation date, not a refresh instant
# ===========================================================================
class TestDi1PortfolioAsOf:
    @pytest.mark.asyncio
    async def test_observation_date_comes_from_the_stored_daily_bars(self, test_db) -> None:
        """A real price observation: the newest `StockTimeseries.date` across the
        held universe, read out of the database, never the request clock."""
        test_db.add_all([
            StockTimeseries(
                ticker="AAA.NS", date=datetime(2026, 9, 24), open=1.0, high=1.0,
                low=1.0, close=1.0, adj_close=1.0, volume=10,
                source_used="yfinance", fetch_status="fresh",
            ),
            StockTimeseries(
                ticker="AAA.NS", date=datetime(2026, 9, 25, 15, 30), open=1.0, high=1.0,
                low=1.0, close=1.0, adj_close=1.0, volume=10,
                source_used="yfinance", fetch_status="fresh",
            ),
        ])
        await test_db.commit()
        assert await _latest_delivered_close_date(test_db, ["AAA.NS"]) == "2026-09-25"

    @pytest.mark.asyncio
    async def test_only_the_held_universe_is_asked_about(self, test_db) -> None:
        """A bar for a ticker the book does not hold cannot date the book."""
        test_db.add(StockTimeseries(
            ticker="ZZZ.NS", date=datetime(2026, 9, 25), open=1.0, high=1.0,
            low=1.0, close=1.0, adj_close=1.0, volume=10,
            source_used="yfinance", fetch_status="fresh",
        ))
        await test_db.commit()
        assert await _latest_delivered_close_date(test_db, ["AAA.NS"]) is None

    @pytest.mark.asyncio
    async def test_no_stored_bar_yields_no_date_rather_than_a_fabricated_one(self, test_db) -> None:
        assert await _latest_delivered_close_date(test_db, ["AAA.NS"]) is None
        # With no held universe there is nothing to ask about at all.
        assert await _latest_delivered_close_date(test_db, []) is None

    def test_the_refresh_instant_stays_in_its_own_field(self) -> None:
        positions = [
            _pos("AAA.NS", market_value=1000.0,
                 updated_on=datetime(2026, 9, 26, 18, 7, 31, 164324)),
            _pos("BBB.NS", market_value=500.0,
                 updated_on=datetime(2026, 9, 26, 18, 7, 18, 83006)),
        ]
        assert _quote_refresh_instant(positions) == "2026-09-26T18:07:31.164324Z"
        # The provenance block names BOTH clocks and says which is which.
        provenance = _holding_date_provenance()
        assert "refresh clock, not an observation date" in provenance["valuation_refreshed_at"]
        assert "real observation date" in provenance["as_of"]
        assert PORTFOLIO_VALUATION_BASIS in provenance["valuation_refreshed_at"]

    @pytest.mark.asyncio
    async def test_route_publishes_a_weekday_observation_and_separates_the_refresh(
        self, test_db
    ) -> None:
        """2026-09-26 is a Saturday with NSE shut, so a valuation instant may not
        name it; the newest delivered bar is Friday the 25th."""
        test_db.add_all([
            PortfolioPosition(
                ticker="AAA.NS", weight=0.0, quantity=1.0, buy_price=900.0,
                last_price=1000.0, market_value=1000.0, region="IN", sector="Tech",
                industry="Y", added_on=datetime(2020, 1, 1),
                updated_on=datetime(2026, 9, 26, 18, 7, 31, 164324),
            ),
            PortfolioPosition(
                ticker="BBB.NS", weight=0.0, quantity=1.0, buy_price=400.0,
                last_price=500.0, market_value=500.0, region="IN", sector="Tech",
                industry="Y", added_on=datetime(2020, 1, 1),
                updated_on=datetime(2026, 9, 26, 18, 7, 18, 83006),
            ),
            StockTimeseries(
                ticker="AAA.NS", date=datetime(2026, 9, 25, 15, 30), open=1.0, high=1.0,
                low=1.0, close=1.0, adj_close=1.0, volume=10,
                source_used="yfinance", fetch_status="fresh",
            ),
        ])
        await test_db.commit()

        with patch("app.api.portfolio._update_portfolio_prices", new=AsyncMock()), \
             patch("app.api.portfolio._clear_portfolio_dependent_memos"), \
             patch("app.api.portfolio.get_currency_service", return_value=_StubFX()):
            envelope = await get_portfolio(
                currency="INR", db=test_db, data_service=Mock()
            )

        assert envelope.as_of == "2026-09-25"
        assert envelope.as_of_semantics == PORTFOLIO_AS_OF_SEMANTICS
        assert envelope.valuation_refreshed_at == "2026-09-26T18:07:31.164324Z"
        # A Saturday, and an instant AFTER the export that contains it: both
        # impossible for an observation date.
        assert date.fromisoformat(envelope.as_of).weekday() < 5
        assert date(2026, 9, 26).weekday() == 5
        refreshed = datetime.fromisoformat(
            envelope.valuation_refreshed_at.replace("Z", "+00:00")
        )
        assert refreshed > EXPORT_START
        assert len(envelope.as_of) == len("2026-09-25"), "a date, not an instant"
        # The disclosure the split would otherwise drop: the values are live
        # quotes, the refresh instant is beside the date and not in it.
        assert len(envelope.warnings) == 1
        assert "live quotes refreshed at 2026-09-26T18:07:31.164324Z" in envelope.warnings[0]
        assert "as_of 2026-09-25 is the newest DELIVERED daily close date" in envelope.warnings[0]

    def test_the_exporter_hoists_that_disclosure_into_the_section(self) -> None:
        """`_collect_warnings` is what carries a route's own warnings into the
        section, so the sentence is not lost at the export boundary."""
        section = _section_for(
            "portfolio",
            {
                "as_of": "2026-09-25",
                "as_of_semantics": PORTFOLIO_AS_OF_SEMANTICS,
                "valuation_refreshed_at": "2026-09-26T18:07:31.164324Z",
                "warnings": [
                    "Position values are live quotes refreshed at "
                    "2026-09-26T18:07:31.164324Z during this request, so the quote "
                    "itself carries no observation date; as_of 2026-09-25 is the "
                    "newest DELIVERED daily close date for the held universe and is "
                    "a separate measurement"
                ],
                "total_value": 1500.0,
            },
        )
        assert any("live quotes refreshed at" in w for w in section["warnings"])
        assert section["as_of"] == "2026-09-25"
        assert section["as_of_semantics"] == PORTFOLIO_AS_OF_SEMANTICS
        assert "ENV-016" not in rule_ids({"portfolio": section})

    @pytest.mark.asyncio
    async def test_no_stored_bar_leaves_as_of_null_and_keeps_the_refresh(
        self, test_db
    ) -> None:
        test_db.add(PortfolioPosition(
            ticker="AAA.NS", weight=0.0, quantity=1.0, buy_price=900.0,
            last_price=1000.0, market_value=1000.0, region="IN", sector="Tech",
            industry="Y", added_on=datetime(2020, 1, 1),
            updated_on=datetime(2026, 9, 26, 18, 7, 31, 164324),
        ))
        await test_db.commit()
        with patch("app.api.portfolio._update_portfolio_prices", new=AsyncMock()), \
             patch("app.api.portfolio._clear_portfolio_dependent_memos"), \
             patch("app.api.portfolio.get_currency_service", return_value=_StubFX()):
            envelope = await get_portfolio(
                currency="INR", db=test_db, data_service=Mock()
            )
        assert envelope.as_of is None
        assert envelope.as_of_semantics is None
        assert envelope.valuation_refreshed_at == "2026-09-26T18:07:31.164324Z"

    def test_the_portfolio_section_passes_env012(self) -> None:
        section = _section(
            "portfolio",
            {
                "as_of": "2026-09-25",
                "valuation_refreshed_at": "2026-09-26T18:07:31.164324Z",
                "total_value": 1500.0,
            },
            as_of="2026-09-25",
            semantics=PORTFOLIO_AS_OF_SEMANTICS,
        )
        assert "ENV-012" not in rule_ids({"portfolio": section})

    def test_the_old_shape_is_what_env012_catches(self) -> None:
        """Control: the pre-fix value - a refresh instant written 18ms AFTER the
        export's own generated_at - is what the rule flags."""
        section = _section(
            "portfolio",
            {"as_of": "2026-09-26T18:07:31.164324Z", "total_value": 1500.0},
            as_of="2026-09-26T18:07:31.164324Z",
            semantics="declared_as_of",
        )
        assert "sits inside the collection window" in only(
            {"portfolio": section}, "ENV-012"
        )


# ===========================================================================
# DI-2: a dated number, or a stated absence of a date
# ===========================================================================
class TestDi2FreshnessOnUndatedSections:
    @pytest.mark.asyncio
    async def test_liquidity_measures_its_window_from_a_date_column_frame(self) -> None:
        """A fresh vendor frame carries `date` as a COLUMN. Projecting the
        Close/Volume pair first dropped the only dated evidence, so a 22-bar
        delivery published `latest_observation_date: null` and null per-ticker
        window bounds for all 14 legs."""
        dates = pd.bdate_range("2026-06-01", "2026-09-25")
        market = _Market(
            {"AAA.NS": _ohlcv(dates), "BBB.NS": _ohlcv(dates)},
            column_dates=True,
            caps={"AAA.NS": 5_000e7, "BBB.NS": 9_000e7},
        )
        db = _db([_pos("AAA.NS", market_value=5000.0), _pos("BBB.NS", market_value=9000.0)])
        with patch(
            "app.api.analytics._convert_analytics_positions",
            new=AsyncMock(return_value=({"AAA.NS": 5000.0, "BBB.NS": 9000.0}, {})),
        ):
            result = await get_liquidity_metrics(
                db=db, data_service=market, analytics_engine=analytics_mod.AnalyticsEngine()
            )

        delivered = result["observation_window"]
        assert result["latest_observation_date"] == "2026-09-25"
        assert delivered["end"] == "2026-09-25"
        # The 30-day request is the request; the delivered window is the evidence,
        # and it is now dated rather than null.
        assert delivered["start"] is not None
        assert delivered["start"] < delivered["end"]
        per_ticker = delivered["per_ticker"]["AAA.NS"]
        assert per_ticker["start"] == delivered["start"]
        assert per_ticker["end"] == delivered["end"]
        assert per_ticker["observations"] > 0
        assert result["scoring"]["observation_window"] == delivered

    @pytest.mark.asyncio
    async def test_a_datelabelled_frame_still_works(self) -> None:
        """A cache hit already arrives date-indexed; promoting the column is a
        no-op there and must not disturb the window."""
        dates = pd.bdate_range("2026-06-01", "2026-09-25")
        market = _Market(
            {"AAA.NS": _ohlcv(dates)}, column_dates=False, caps={"AAA.NS": 5_000e7}
        )
        db = _db([_pos("AAA.NS", market_value=5000.0)])
        with patch(
            "app.api.analytics._convert_analytics_positions",
            new=AsyncMock(return_value=({"AAA.NS": 5000.0}, {})),
        ):
            result = await get_liquidity_metrics(
                db=db, data_service=market, analytics_engine=analytics_mod.AnalyticsEngine()
            )
        assert result["latest_observation_date"] == dates[-1].date().isoformat()
        assert result["observation_window"]["per_ticker"]["AAA.NS"]["start"] is not None

    @pytest.mark.asyncio
    async def test_stress_publishes_the_window_its_volatilities_were_measured_over(self) -> None:
        dates = pd.bdate_range("2024-01-01", "2026-09-25")
        rng = np.random.default_rng(7)

        def _frame(ticker):
            close = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.011, len(dates)))
            return pd.DataFrame(
                {
                    "date": dates,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "adj_close": close,
                    "volume": rng.integers(100_000, 1_000_000, len(dates)).astype(float),
                    "ticker": ticker,
                }
            )

        market = _Market({ticker: _frame(ticker) for ticker in ("AAA.NS", "BBB.NS")},
                         column_dates=True)
        db = _db([_pos("AAA.NS", market_value=5000.0), _pos("BBB.NS", market_value=5000.0)])
        with patch(
            "app.api.analytics.resolve_allocation",
            new=AsyncMock(
                return_value=(["AAA.NS", "BBB.NS"], {"AAA.NS": 0.5, "BBB.NS": 0.5})
            ),
        ):
            result = await run_stress_test(
                StressTestRequest(scenario="Market Crash", tickers=None),
                db=db,
                data_service=market,
                analytics_engine=analytics_mod.AnalyticsEngine(),
            )

        assert "error" not in result, result.get("error")
        assert result["latest_observation_date"] == "2026-09-25"
        window = result["measurement_window"]
        # A request bound is never evidence; the delivered bounds are.
        assert window["requested_start"] and window["requested_end"] >= window["latest_observation"]
        assert window["first_observation"] <= window["latest_observation"]
        assert window["return_observations"] > 0
        adjustment = result["volatility_adjustment_window"]
        assert adjustment["annualization_trading_days"] == 252
        assert adjustment["window"] == window
        assert "measured over this window" in adjustment["note"]

    @pytest.mark.asyncio
    async def test_stress_section_dates_itself_by_its_stalest_scenario(self) -> None:
        """A composite is only as fresh as its stalest leg, so a scenario that
        received a newer bar cannot make the section - and its worst loss - look
        fresher than it is."""
        newest = {
            "Market Crash": "2026-09-25",
            "Interest Rate Shock": "2026-09-20",
            "Volatility Spike": "2026-09-25",
            "Tech Sector Correction": "2026-09-22",
        }

        async def _scenario(request, *_a, **_k):
            return {
                "scenario": request.scenario,
                "max_drawdown": -0.5,
                "latest_observation_date": newest[request.scenario],
                "universe_coverage": {"available_tickers": ["AAA.NS", "BBB.NS"]},
            }

        service = _service()
        with patch(
            "app.services.ai_context_service.analytics_api.run_stress_test",
            new=AsyncMock(side_effect=_scenario),
        ):
            collected = await service._collect_stress_testing(
                SimpleNamespace(tickers=["AAA.NS", "BBB.NS"], cached={})
            )

        assert collected.data.get("failures") == {}
        data = collected.data
        assert data["as_of"] == "2026-09-20", "the oldest scenario, not the newest"
        assert data["as_of_semantics"] == STRESS_AS_OF_SEMANTICS
        assert data["scenario_observation_dates"] == dict(sorted(newest.items()))
        assert "min over scenarios" in STRESS_AS_OF_BASIS
        assert data["scenario_observation_date_basis"] == STRESS_AS_OF_BASIS

    @pytest.mark.asyncio
    async def test_stress_section_with_no_measured_date_publishes_none(self) -> None:
        async def _scenario(request, *_a, **_k):
            return {
                "scenario": request.scenario,
                "max_drawdown": -0.5,
                "universe_coverage": {"available_tickers": ["AAA.NS"]},
            }

        service = _service()
        with patch(
            "app.services.ai_context_service.analytics_api.run_stress_test",
            new=AsyncMock(side_effect=_scenario),
        ):
            collected = await service._collect_stress_testing(
                SimpleNamespace(tickers=["AAA.NS"], cached={})
            )
        assert "as_of" not in collected.data

    def test_a_stale_as_of_is_disclosed_with_its_measured_age(self) -> None:
        """The freshness bound: a section that gains an `as_of` more than
        AS_OF_STALENESS_DAYS behind the export must publish the age."""
        section = _section_for(
            "stress_testing",
            {
                "as_of": "2026-01-05",
                "as_of_semantics": STRESS_AS_OF_SEMANTICS,
                "scenarios": {"Market Crash": {"max_drawdown": -0.5}},
            },
        )
        # Measured from the export clock at midnight of the as_of date, which is
        # exactly what the disclosure reports.
        expected_days = (
            EXPORT_START - datetime(2026, 1, 5, tzinfo=timezone.utc)
        ).total_seconds() / 86400.0
        assert expected_days > AS_OF_STALENESS_DAYS
        stale = [w for w in section["warnings"] if "stale" in w.lower()]
        assert stale, section["warnings"]
        assert f"{expected_days:.2f}" in stale[0]
        # And the audit rule accepts the disclosed staleness.
        assert "ENV-012" not in rule_ids({"stress_testing": section})

    def test_an_as_of_inside_the_bound_is_not_called_stale(self) -> None:
        section = _section_for(
            "stress_testing",
            {"as_of": "2026-09-25", "scenarios": {"Market Crash": {"max_drawdown": -0.5}}},
        )
        assert section["warnings"] == []
        assert "ENV-012" not in rule_ids({"stress_testing": section})

    def test_the_staleness_bound_matches_the_audit_rule(self) -> None:
        assert AS_OF_STALENESS_DAYS == ca.AS_OF_STALENESS_DAYS

    @pytest.mark.asyncio
    async def test_concentration_states_the_absent_valuation_date(self) -> None:
        """There is no observation date for a live-quoted cross-section, so the
        honest publish is null plus the reason - not a borrowed price date."""
        db = _db([_pos("AAA.NS", market_value=1000.0), _pos("BBB.NS", market_value=1000.0)])
        with patch(
            "app.api.analytics._convert_analytics_positions",
            new=AsyncMock(return_value=({"AAA.NS": 1000.0, "BBB.NS": 1000.0}, {})),
        ):
            result = await get_concentration_metrics(
                db=db, data_service=Mock(), analytics_engine=analytics_mod.AnalyticsEngine()
            )

        assert result["as_of"] is None
        assert result["as_of_semantics"] is None
        assert result["valuation_date_status"] == "unavailable"
        assert "refresh" in result["valuation_date_unavailable_reason"]
        assert result["valuation_basis"] == CONCENTRATION_VALUATION_BASIS
        assert result["warnings"] == [CONCENTRATION_NO_VALUATION_DATE_WARNING]
        assert "No valuation date" in result["warnings"][0]

    def test_concentration_absent_date_does_not_trip_env013(self) -> None:
        """A null `as_of` is only a defect beside a dated payload; this one dates
        nothing, so the rule stays quiet."""
        section = _section(
            "concentration",
            {
                "as_of": None,
                "valuation_date_status": "unavailable",
                "by_weight": {"AAA.NS": 0.6, "BBB.NS": 0.4},
            },
            semantics=None,
        )
        assert "ENV-013" not in rule_ids({"concentration": section})


# ===========================================================================
# DI-5: the portfolio omission ledger claims nothing was dropped
# ===========================================================================
class TestDi5PortfolioOmissionLedger:
    def _portfolio_payload(self) -> dict[str, Any]:
        return {
            "positions": [
                {
                    "ticker": "AAA.NS",
                    "total_cost": 900.0,
                    "total_cost_base": 900.0,
                    "unrealized_gain_loss": 100.0,
                },
                {
                    "ticker": "BBB.NS",
                    "total_cost": 400.0,
                    "total_cost_base": 400.0,
                    "unrealized_gain_loss": 100.0,
                },
            ],
            "total_value": 1500.0,
            "total_positions": 2,
            "as_of": "2026-09-25",
            "valuation_refreshed_at": "2026-09-26T18:07:31.164324Z",
        }

    def test_absent_book_level_aggregates_are_named(self) -> None:
        section = _section_for("portfolio", self._portfolio_payload())
        for name in ("day_change", "total_pnl", "previous_close", "total_cost"):
            assert name in section["omitted_fields"]
        disclosed = section["data"]["aggregates_not_produced"]
        assert disclosed["fields"] == sorted(PORTFOLIO_AGGREGATES_NOT_PRODUCED)
        assert "not dropped by compaction" in disclosed["reason"]

    def test_a_per_leg_field_does_not_satisfy_a_book_level_aggregate(self) -> None:
        """`total_cost` exists on every position row; the missing number is the
        book's, so the row must not mark the aggregate as produced."""
        section = _section_for("portfolio", self._portfolio_payload())
        assert "total_cost" in section["omitted_fields"]

    def test_an_endpoint_that_publishes_them_clears_the_ledger(self) -> None:
        payload = self._portfolio_payload()
        payload.update(
            {
                "total_cost": 1300.0,
                "total_pnl": 200.0,
                "day_change": -12.0,
                "previous_close": 1512.0,
            }
        )
        section = _section_for("portfolio", payload)
        assert section["omitted_fields"] == []
        assert "aggregates_not_produced" not in section["data"]
