"""AD-16 and AD-8: what the portfolio's marks are, and what they are not.

AD-16 - the export published `snapshot_consistency: "best_effort"` beside an
empty `warnings: []` while its own sections valued the same 14 tickers from
different price instants (a reviewer counted 31 mismatching (ticker, price)
pairs, up to 3.5% apart). One adjective cannot say how many instants, how far
apart, or which leg is stale. These tests assert the measurement replaces it:
a counted block, a per-position `price_as_of` that agrees with `as_of`, and a
named statement of what the spread invalidates.

AD-8 - across 784 KB of artifact, `dividend`, `fee`, `tax`, `slippage`,
`survivorship`, `corporate action` and `split` each appeared ZERO times. The
artifact carried per-position P&L, a book total and a day change and never said
whether any of it was gross. These tests assert the basis block names every
category and states which are and are not accounted for.

Every assertion runs against the real route / real helpers, not the frozen
`v13.json` export - that file is a read of the OLD source, so asserting against
it would prove nothing about the fix. The audit rules are exercised directly
against the freshly built payload instead, which is the same seam
`test_ai_context_freshness_disclosure.py` uses.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.api.portfolio import (
    PORTFOLIO_ACCOUNTING_BASIS,
    PORTFOLIO_AS_OF_SEMANTICS,
    PORTFOLIO_BAR_CLOCK,
    PORTFOLIO_MARK_CLOCK,
    PORTFOLIO_PRICE_AS_OF_SEMANTICS,
    _bar_clock_block,
    _delivered_close_dates,
    _holding_date_provenance,
    _latest_delivered_close_date,
    _mark_clock_block,
    _portfolio_accounting_basis,
    _price_instant_warnings,
    _price_snapshot_consistency,
    get_portfolio,
)
from app.debugging import context_audit as ca
from app.models.database import PortfolioPosition, StockTimeseries

EXPORT_START_TEXT = "2026-09-26T18:07:11.579749Z"


# ---------------------------------------------------------------------------
# seams
# ---------------------------------------------------------------------------
class _StubFX:
    def get_exchange_rate(self, *_a, **_k):
        return 1.0

    def get_exchange_rate_info(self):
        return {}


def _section(
    key: str,
    data: Any,
    *,
    status: str = "available",
    as_of: str | None = "2026-09-25",
    semantics: str | None = "latest_observation_date",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "title": key.replace("_", " ").title(),
        "route": f"/{key}",
        "status": status,
        "detail": "summary",
        "generated_at": EXPORT_START_TEXT,
        "inputs": {},
        "coverage": None,
        "data": data,
        "omitted_fields": [],
        "as_of": as_of,
        "as_of_semantics": semantics,
        "currency": "INR",
        "warnings": list(warnings or []),
    }


def rule_ids(sections: dict[str, dict[str, Any]]) -> set[str]:
    export = {
        "schema_version": ca.EXPECTED_SCHEMA_VERSION,
        "export_id": "portfolio-provenance0",
        "generated_at": EXPORT_START_TEXT,
        "completed_at": "2026-09-26T18:07:48.880737Z",
        # The envelope-level field the collector still hardcodes. Asserted as the
        # pre-fix state, not as something this wave changed.
        "snapshot_consistency": "best_effort",
        "base_currency": "INR",
        "detail": "summary",
        "scope": list(sections),
        "sections": sections,
        "warnings": [],
    }
    return {
        finding.rule_id
        for finding in ca.run_rules(ca.Export(doc=export, raw=json.dumps(export)))[0]
    }


_next_id = iter(range(1, 10_000))


def _pos(ticker: str, *, last_price: float, buy_price: float | None = None,
         updated_on: datetime | None = None) -> PortfolioPosition:
    return PortfolioPosition(
        id=next(_next_id),
        ticker=ticker,
        weight=0.0,
        quantity=1.0,
        buy_price=buy_price if buy_price is not None else last_price,
        last_price=last_price,
        market_value=last_price,
        region="IN",
        sector="Tech",
        industry="Y",
        added_on=datetime(2020, 1, 1),
        updated_on=updated_on or datetime(2026, 9, 26, 18, 7, 31, 164324),
    )


async def _envelope(test_db, positions, bars=()):
    for position in positions:
        test_db.add(position)
    for ticker, when in bars:
        test_db.add(StockTimeseries(
            ticker=ticker, date=when, open=1.0, high=1.0, low=1.0, close=1.0,
            adj_close=1.0, volume=10, source_used="yfinance", fetch_status="fresh",
        ))
    await test_db.commit()
    with patch("app.api.portfolio._update_portfolio_prices", new=AsyncMock()), \
         patch("app.api.portfolio._clear_portfolio_dependent_memos"), \
         patch("app.api.portfolio.get_currency_service", return_value=_StubFX()):
        return await get_portfolio(currency="INR", db=test_db, data_service=Mock())


# ===========================================================================
# AD-16: measure the price spread instead of asserting it did not happen
# ===========================================================================
class TestAd16SnapshotConsistencyIsMeasured:
    def test_the_envelope_publishes_a_count_and_a_spread_not_an_adjective(self) -> None:
        """The direct replacement of `"best_effort"`: a counted, bounded block."""
        positions = [
            _pos("AAA.NS", last_price=100.0, updated_on=datetime(2026, 9, 26, 18, 7, 31)),
            _pos("BBB.NS", last_price=50.0, updated_on=datetime(2026, 9, 26, 18, 7, 29)),
            _pos("CCC.NS", last_price=25.0, updated_on=datetime(2026, 9, 26, 18, 7, 28)),
        ]
        block = _price_snapshot_consistency(
            positions, {"AAA.NS": "2026-09-25", "BBB.NS": "2026-09-22"}
        )

        # A count of distinct instants, not a word.
        assert block["status"] == "multiple_instants"
        assert block["distinct_price_instants"] == 3
        assert block["distinct_delivered_bar_dates"] == 2
        # And the spread between them, measured on each clock in its own unit.
        assert block["mark_instant_spread_seconds"] == 3.0
        assert block["delivered_bar_spread_calendar_days"] == 3
        assert block["price_clocks"][PORTFOLIO_BAR_CLOCK]["oldest"] == "2026-09-22"
        assert block["price_clocks"][PORTFOLIO_BAR_CLOCK]["newest"] == "2026-09-25"
        # Which leg is stale is named, so the spread is attributable.
        assert block["price_clocks"][PORTFOLIO_BAR_CLOCK]["positions_at_each_instant"] == {
            "2026-09-22": ["BBB.NS"],
            "2026-09-25": ["AAA.NS"],
        }
        # And what it invalidates is stated rather than left to be inferred.
        joined = " ".join(block["what_this_invalidates"])
        assert "not a single simultaneous snapshot" in joined
        assert "WRONG date" in joined, "as_of misdates the stale leg and must say so"
        assert "does NOT reconcile another section" in joined

    def test_a_snapshot_that_really_does_line_up_says_so(self) -> None:
        """A single mark instant and a single bar date is the honest `single_instant`
        case, and it must not be diluted by always-on alarm language."""
        positions = [
            _pos("AAA.NS", last_price=100.0, updated_on=datetime(2026, 9, 26, 18, 7, 31)),
            _pos("BBB.NS", last_price=50.0, updated_on=datetime(2026, 9, 26, 18, 7, 31)),
        ]
        block = _price_snapshot_consistency(
            positions, {"AAA.NS": "2026-09-25", "BBB.NS": "2026-09-25"}
        )
        assert block["status"] == "single_instant"
        assert block["distinct_price_instants"] == 1
        assert block["distinct_delivered_bar_dates"] == 1
        assert block["mark_instant_spread_seconds"] is None
        assert block["delivered_bar_spread_calendar_days"] is None
        assert _price_instant_warnings(block) == []
        # The cross-section caveat is unconditional: no route can measure it.
        assert block["cross_section_reconciliation"]["measured_here"] is False

    def test_an_empty_book_is_unmeasured_rather_than_consistent(self) -> None:
        block = _price_snapshot_consistency([], {})
        assert block["status"] == "unmeasured"
        assert block["distinct_price_instants"] == 0
        assert block["distinct_delivered_bar_dates"] == 0
        assert block["per_position_price_as_of"] == {}

    def test_a_position_with_no_delivered_bar_is_partial_and_named(self) -> None:
        """Absence of a date is a fact; it must not be smoothed into the count."""
        block = _price_snapshot_consistency(
            [_pos("AAA.NS", last_price=1.0)], {"AAA.NS": "2026-09-25", "BBB.NS": None}
        )
        assert block["status"] == "partial"
        assert block["price_clocks"][PORTFOLIO_BAR_CLOCK][
            "positions_without_a_delivered_bar"
        ] == ["BBB.NS"]
        assert any("no delivered daily bar" in item for item in block["what_this_invalidates"])

    def test_the_helper_does_not_claim_a_measurement_it_did_not_make(self) -> None:
        """`cross_section_reconciliation.measured_here` is False with a reason, so a
        downstream reader is told the limit rather than left to assume coverage."""
        block = _price_snapshot_consistency(
            [_pos("AAA.NS", last_price=1.0)], {"AAA.NS": "2026-09-25"}
        )
        reconciliation = block["cross_section_reconciliation"]
        assert reconciliation["measured_here"] is False
        assert "cannot observe" in reconciliation["reason"]
        assert reconciliation["rule_for_a_reader"]

    def test_the_mark_clock_is_measured_per_leg_not_taken_from_the_max(self) -> None:
        """The two legs were written 2s apart. `max()` would have published one
        instant and hidden that; the per-ticker map cannot."""
        block = _mark_clock_block([
            _pos("AAA.NS", last_price=1.0, updated_on=datetime(2026, 9, 26, 18, 7, 31)),
            _pos("BBB.NS", last_price=1.0, updated_on=datetime(2026, 9, 26, 18, 7, 29)),
        ])
        assert block["distinct_instants"] == 2
        assert block["spread"] == 2.0
        assert block["spread_unit"] == "seconds"
        assert block["per_ticker"] == {
            "AAA.NS": "2026-09-26T18:07:31Z",
            "BBB.NS": "2026-09-26T18:07:29Z",
        }

    def test_the_bar_clock_reports_a_missing_measurement_as_null_not_a_neighbour(self) -> None:
        block = _bar_clock_block({"AAA.NS": "2026-09-25", "BBB.NS": None})
        assert block["per_ticker"] == {"AAA.NS": "2026-09-25", "BBB.NS": None}
        assert block["positions_without_a_delivered_bar"] == ["BBB.NS"]

    def test_the_spread_warning_names_the_stale_legs(self) -> None:
        block = _price_snapshot_consistency(
            [_pos("AAA.NS", last_price=1.0), _pos("BBB.NS", last_price=1.0)],
            {"AAA.NS": "2026-09-25", "BBB.NS": "2026-09-22"},
        )
        warnings = _price_instant_warnings(block)
        assert len(warnings) == 1
        warning = warnings[0]
        assert "2 distinct delivered" in warning
        assert "3 calendar days" in warning
        # It names the newest leg's date as the one `as_of` will carry, so the
        # reader is told which value the single date is wrong for.
        assert "as_of 2026-09-25 dates only the newest leg" in warning

    def test_the_old_adjective_carries_none_of_this(self) -> None:
        """Control: the pre-fix value names no count, no spread and no leg."""
        for token in ("2", "3", "spread", "AAA.NS", "BBB.NS"):
            assert token not in "best_effort"


class TestAd16PerPositionPriceAsOf:
    @pytest.mark.asyncio
    async def test_the_route_dates_each_mark_to_its_own_ticker(self, test_db) -> None:
        """The per-position field the mission calls the most useful single
        addition: it makes the disagreement local instead of a global adjective."""
        envelope = await _envelope(
            test_db,
            [
                _pos("AAA.NS", last_price=1000.0),
                _pos("BBB.NS", last_price=500.0),
            ],
            bars=[
                ("AAA.NS", datetime(2026, 9, 25, 15, 30)),
                ("AAA.NS", datetime(2026, 9, 24, 15, 30)),
                ("BBB.NS", datetime(2026, 9, 22, 15, 30)),
            ],
        )
        by_ticker = {p.ticker: p for p in envelope.positions}
        assert by_ticker["AAA.NS"].price_as_of == "2026-09-25"
        assert by_ticker["BBB.NS"].price_as_of == "2026-09-22"
        for position in envelope.positions:
            assert position.price_as_of_semantics == PORTFOLIO_PRICE_AS_OF_SEMANTICS
            # It sits beside the price it dates, on the same row.
            assert position.last_price is not None
            # And it never exceeds the book-wide `as_of`, which is that max.
            assert position.price_as_of <= envelope.as_of
        assert envelope.as_of == "2026-09-25"
        assert envelope.as_of_semantics == PORTFOLIO_AS_OF_SEMANTICS

    @pytest.mark.asyncio
    async def test_a_leg_with_no_bar_publishes_null_rather_than_the_book_date(
        self, test_db
    ) -> None:
        """The exact AD-16 hazard: `as_of` is 09-25 because AAA has a bar, and BBB
        has none at all. Copying the book date onto BBB would fabricate a
        measurement for a ticker that never delivered one."""
        envelope = await _envelope(
            test_db,
            [_pos("AAA.NS", last_price=1000.0), _pos("BBB.NS", last_price=500.0)],
            bars=[("AAA.NS", datetime(2026, 9, 25, 15, 30))],
        )
        by_ticker = {p.ticker: p for p in envelope.positions}
        assert envelope.as_of == "2026-09-25"
        assert by_ticker["AAA.NS"].price_as_of == "2026-09-25"
        assert by_ticker["BBB.NS"].price_as_of is None
        assert by_ticker["BBB.NS"].price_as_of_semantics is None
        assert envelope.snapshot_consistency["status"] == "partial"
        assert envelope.snapshot_consistency["price_clocks"][PORTFOLIO_BAR_CLOCK][
            "positions_without_a_delivered_bar"
        ] == ["BBB.NS"]

    @pytest.mark.asyncio
    async def test_a_stale_leg_is_dated_here_and_warned_about_even_though_as_of_is_new(
        self, test_db
    ) -> None:
        """BBB is three sessions behind the book date. Before the fix, the section
        published `as_of: 2026-09-25` and said nothing about BBB."""
        envelope = await _envelope(
            test_db,
            [_pos("AAA.NS", last_price=1000.0), _pos("BBB.NS", last_price=500.0)],
            bars=[
                ("AAA.NS", datetime(2026, 9, 25, 15, 30)),
                ("BBB.NS", datetime(2026, 9, 22, 15, 30)),
            ],
        )
        assert envelope.as_of == "2026-09-25", "the newest leg still dates the book"
        assert {p.ticker: p.price_as_of for p in envelope.positions} == {
            "AAA.NS": "2026-09-25",
            "BBB.NS": "2026-09-22",
        }
        assert envelope.snapshot_consistency["status"] == "multiple_instants"
        assert envelope.snapshot_consistency["distinct_delivered_bar_dates"] == 2
        assert envelope.snapshot_consistency["delivered_bar_spread_calendar_days"] == 3
        spread_warnings = [w for w in envelope.warnings if "distinct delivered" in w]
        assert len(spread_warnings) == 1
        assert "3 calendar days" in spread_warnings[0]
        # The wave-2 two-clock sentence is still present and unchanged in meaning.
        assert any("live quotes refreshed at" in w for w in envelope.warnings)

    @pytest.mark.asyncio
    async def test_the_provenance_block_names_the_per_position_field(self, test_db) -> None:
        """`holding_date_provenance` is where a reader looks for "what is this
        date", so the new field has to be described there too."""
        envelope = await _envelope(
            test_db, [_pos("AAA.NS", last_price=1000.0)],
            bars=[("AAA.NS", datetime(2026, 9, 25, 15, 30))],
        )
        assert envelope.holding_date_provenance == _holding_date_provenance()
        described = envelope.holding_date_provenance["price_as_of"]
        assert PORTFOLIO_PRICE_AS_OF_SEMANTICS in described
        assert "null means NO bar has been delivered" in described

    @pytest.mark.asyncio
    async def test_the_grouped_query_reads_every_ticker_and_ignores_the_rest(
        self, test_db
    ) -> None:
        test_db.add(StockTimeseries(
            ticker="ZZZ.NS", date=datetime(2026, 9, 26), open=1.0, high=1.0, low=1.0,
            close=1.0, adj_close=1.0, volume=10, source_used="yfinance",
            fetch_status="fresh",
        ))
        await test_db.commit()
        await test_db.execute(
            __import__("sqlalchemy").delete(PortfolioPosition)
        )
        await test_db.commit()
        test_db.add_all([
            StockTimeseries(
                ticker="AAA.NS", date=datetime(2026, 9, 25), open=1.0, high=1.0, low=1.0,
                close=1.0, adj_close=1.0, volume=10, source_used="yfinance",
                fetch_status="fresh",
            ),
            StockTimeseries(
                ticker="BBB.NS", date=datetime(2026, 9, 22), open=1.0, high=1.0, low=1.0,
                close=1.0, adj_close=1.0, volume=10, source_used="yfinance",
                fetch_status="fresh",
            ),
        ])
        await test_db.commit()

        dates = await _delivered_close_dates(test_db, ["AAA.NS", "BBB.NS", "CCC.NS"])
        assert dates == {"AAA.NS": "2026-09-25", "BBB.NS": "2026-09-22"}
        assert "ZZZ.NS" not in dates, "a bar the book does not hold cannot date it"
        assert "CCC.NS" not in dates, "a held ticker with no bar yields nothing"
        # The book-wide roll-up is now derived from that same map, so the two
        # published dates cannot disagree.
        assert await _latest_delivered_close_date(test_db, ["AAA.NS", "BBB.NS"]) == "2026-09-25"

    def test_an_empty_universe_asks_nothing(self) -> None:
        block = _bar_clock_block({})
        assert block["distinct_instants"] == 0
        assert block["oldest"] is None and block["newest"] is None
        assert block["positions_at_each_instant"] == {}

    def test_the_published_as_of_is_never_a_weekend_the_quote_claimed(self) -> None:
        """Wave-2 property preserved: the bar clock is a session date, the mark
        clock is an instant, and they stay in separate fields."""
        assert date(2026, 9, 26).weekday() == 5, "2026-09-26 is a Saturday"
        assert PORTFOLIO_MARK_CLOCK != PORTFOLIO_BAR_CLOCK
        assert "write clock" in _mark_clock_block([])["measures"]
        assert "session date" in _bar_clock_block({})["measures"]


# ===========================================================================
# AD-8: the artifact accounts for nothing
# ===========================================================================
class TestAd8CostAndPriceBasisIsDeclared:
    #: Exactly the seven terms the reviewer counted zero times in 784 KB, plus the
    #: three the review listed alongside them.
    REVIEW_TERMS = (
        "dividend", "fee", "tax", "slippage", "survivorship",
        "corporate action", "split", "bonus", "net_of",
    )

    def test_every_category_in_the_review_is_named(self) -> None:
        basis = _portfolio_accounting_basis()
        # Substring search over the serialised block: the review's own method, so
        # the same probe that returned 0 must now return a hit.
        blob = json.dumps(basis).lower()
        for term in self.REVIEW_TERMS:
            assert term in blob, f"{term!r} is still absent from the basis block"

    def test_the_measure_is_each_category_and_its_direction(self) -> None:
        basis = _portfolio_accounting_basis()
        items = {entry["item"]: entry for entry in basis["not_accounted_for"]}
        assert basis["gross_or_net"] == "gross"
        assert basis["net_of_costs"] is False
        assert basis["basis"] == PORTFOLIO_ACCOUNTING_BASIS
        assert len(items) == 7
        for entry in items.values():
            assert entry["accounted_for"] is False
            assert entry["effect"], "a bare 'not accounted for' is not a disclosure"
        # The seven the review named, each findable by content not by position.
        for needle in (
            "dividends", "corporate actions", "fees", "tax", "slippage",
            "turnover", "survivorship",
        ):
            assert any(needle in item for item in items), needle

    def test_the_price_basis_says_price_only_not_total_return(self) -> None:
        basis = _portfolio_accounting_basis()
        mark = basis["value_mark"]
        assert mark["field"] == "positions[].last_price"
        assert mark["adjusted"] is False
        assert "adj_close" in mark["note"]
        assert "not a total-return series" in mark["note"]

    def test_the_arithmetic_itself_is_stated(self) -> None:
        basis = _portfolio_accounting_basis()
        arithmetic = basis["arithmetic"]
        assert "quantity * last_price" in arithmetic["market_value"]
        assert "NOT produced" in arithmetic["realised_pnl"]
        assert "not FIFO" in arithmetic["total_cost"]
        assert arithmetic["unrealized_gain_loss"].count("SAME fx rate") == 1

    def test_what_is_actually_accounted_for_is_also_named(self) -> None:
        """The block must not read as "nothing is accounted for"; FX identity and
        the zero-quantity rule genuinely are."""
        basis = _portfolio_accounting_basis()
        joined = " ".join(basis["accounted_for"])
        assert "fx_conversion" in joined and "identity" in joined
        assert "quantity" in joined

    def test_the_scope_refuses_to_cover_the_other_sections(self) -> None:
        """The honest limit: this block describes the portfolio's own arithmetic.
        Claiming it covers monte_carlo / the tear sheet would be fabrication, so it
        states their basis is UNKNOWN instead."""
        basis = _portfolio_accounting_basis()
        assert "sections.portfolio only" in basis["scope"]["covers"]
        does_not_cover = basis["scope"]["does_not_cover"]
        assert "UNKNOWN, not gross" in does_not_cover
        for section in ("monte_carlo", "tear sheet", "optimiser"):
            assert section in does_not_cover

    def test_it_says_gross_in_plain_words_for_the_reader(self) -> None:
        basis = _portfolio_accounting_basis()
        assert "GROSS figures" in basis["reader_consequence"]
        assert "upper bound" in basis["reader_consequence"]
        # Nothing is actually deducted, so the numbers are untouched.
        assert "deduct" not in basis["arithmetic"]["market_value"].lower()

    @pytest.mark.asyncio
    async def test_the_route_publishes_it_once_on_the_envelope(self, test_db) -> None:
        envelope = await _envelope(
            test_db, [_pos("AAA.NS", last_price=1000.0, buy_price=900.0)],
            bars=[("AAA.NS", datetime(2026, 9, 25, 15, 30))],
        )
        assert envelope.accounting_basis == _portfolio_accounting_basis()
        blob = json.dumps(envelope.accounting_basis).lower()
        for term in self.REVIEW_TERMS:
            assert term in blob

    @pytest.mark.asyncio
    async def test_an_empty_book_still_declares_the_basis(self, test_db) -> None:
        """Disclosure is unconditional: a reader with no holdings still learns the
        contract, and the snapshot block says `unmeasured` rather than nothing."""
        envelope = await _envelope(test_db, [])
        assert envelope.positions == []
        assert envelope.as_of is None
        assert envelope.snapshot_consistency["status"] == "unmeasured"
        assert envelope.accounting_basis["gross_or_net"] == "gross"

    @pytest.mark.asyncio
    async def test_the_declaration_did_not_move_a_single_number(self, test_db) -> None:
        """Reviewer 03 verified all 7 position identities at delta 0.00e+00. The
        disclosure is additive: every identity must still hold exactly."""
        envelope = await _envelope(
            test_db,
            [
                _pos("AAA.NS", last_price=1000.0, buy_price=900.0),
                _pos("BBB.NS", last_price=500.0, buy_price=400.0),
            ],
            bars=[
                ("AAA.NS", datetime(2026, 9, 25, 15, 30)),
                ("BBB.NS", datetime(2026, 9, 22, 15, 30)),
            ],
        )
        total = 0.0
        for position in envelope.positions:
            assert position.market_value == pytest.approx(
                position.quantity * position.last_price
            )
            assert position.total_cost == pytest.approx(
                position.quantity * position.buy_price
            )
            assert position.unrealized_gain_loss == pytest.approx(
                position.market_value - position.total_cost
            )
            assert position.market_value_base == pytest.approx(position.market_value)
            assert position.total_cost_base == pytest.approx(position.total_cost)
            assert position.unrealized_gain_loss_base == pytest.approx(
                position.unrealized_gain_loss
            )
            assert position.current_value_base == position.market_value_base
            assert position.fx_rate == 1.0
            assert position.fx_provenance["provenance"] == "identity"
            total += position.market_value_base
        assert envelope.total_value == pytest.approx(total)
        assert sum(p.weight for p in envelope.positions) == pytest.approx(1.0)
        assert sum(envelope.sectors.values()) == pytest.approx(1.0)


# ===========================================================================
# the disclosed payload must not trip a gate rule
# ===========================================================================
class TestDisclosedPayloadPassesTheGate:
    def test_the_measured_block_and_basis_clear_every_rule(self, test_db) -> None:
        payload = {
            "positions": [
                {
                    "ticker": "AAA.NS",
                    "last_price": 1000.0,
                    "price_as_of": "2026-09-25",
                    "price_as_of_semantics": PORTFOLIO_PRICE_AS_OF_SEMANTICS,
                    "market_value_base": 1000.0,
                    "total_cost_base": 900.0,
                    "unrealized_gain_loss": 100.0,
                    "fx_rate": 1.0,
                    "fx_provenance": {"provenance": "identity"},
                },
                {
                    "ticker": "BBB.NS",
                    "last_price": 500.0,
                    "price_as_of": "2026-09-22",
                    "price_as_of_semantics": PORTFOLIO_PRICE_AS_OF_SEMANTICS,
                    "market_value_base": 500.0,
                    "total_cost_base": 400.0,
                    "unrealized_gain_loss": 100.0,
                    "fx_rate": 1.0,
                    "fx_provenance": {"provenance": "identity"},
                },
            ],
            "total_value": 1500.0,
            "total_positions": 2,
            "total_weight": 1.0,
            "sectors": {"Tech": 1.0},
            "as_of": "2026-09-25",
            "as_of_semantics": PORTFOLIO_AS_OF_SEMANTICS,
            "valuation_refreshed_at": "2026-09-26T18:07:31.164324Z",
            "snapshot_consistency": _price_snapshot_consistency(
                [
                    _pos("AAA.NS", last_price=1000.0),
                    _pos("BBB.NS", last_price=500.0),
                ],
                {"AAA.NS": "2026-09-25", "BBB.NS": "2026-09-22"},
            ),
            "accounting_basis": _portfolio_accounting_basis(),
            "holding_date_provenance": _holding_date_provenance(),
        }
        section = _section(
            "portfolio",
            payload,
            warnings=_price_instant_warnings(payload["snapshot_consistency"]),
        )
        assert rule_ids({"portfolio": section}) == set(), (
            "a disclosure that trips the gate is not a disclosure"
        )

    def test_a_undated_leg_is_not_read_as_a_fabricated_date(self) -> None:
        """ENV-012 keys on the section `as_of`, so a null per-position date must not
        be mistaken for one that sits inside the collection window."""
        payload = {
            "positions": [
                {"ticker": "AAA.NS", "last_price": 1000.0, "price_as_of": "2026-09-25",
                 "market_value_base": 1000.0},
                {"ticker": "BBB.NS", "last_price": None, "price_as_of": None,
                 "market_value_base": 0.0},
            ],
            "total_value": 1000.0,
            "total_positions": 2,
            "as_of": "2026-09-25",
            "as_of_semantics": PORTFOLIO_AS_OF_SEMANTICS,
            "snapshot_consistency": _price_snapshot_consistency(
                [_pos("AAA.NS", last_price=1000.0)], {"AAA.NS": "2026-09-25"}
            ),
        }
        assert "ENV-012" not in rule_ids(
            {"portfolio": _section("portfolio", payload, semantics=PORTFOLIO_AS_OF_SEMANTICS)}
        )


def test_the_two_clock_provenance_still_names_both_clocks() -> None:
    """Wave-2 DI-1 property, restated here so this file fails if a later edit
    collapses the two clocks into one field."""
    provenance = _holding_date_provenance()
    assert "real observation date" in provenance["as_of"]
    assert "refresh clock, not an observation date" in provenance["valuation_refreshed_at"]
    assert PORTFOLIO_AS_OF_SEMANTICS in provenance["as_of"]
