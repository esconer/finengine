"""Quote provenance and historical FX: make the ABSENCE visible.

Two things this file pins, both of which were previously silent:

(a) `PortfolioPositionResponse` carried `last_price` and `updated_on` and
    nothing else. `updated_on` is a quote WRITE clock, so a consumer with one
    timestamp had no way to avoid reading it as the time the market priced the
    row. The AD-16 `price_as_of` vocabulary already existed on the envelope; the
    position contract now speaks it rather than coining a parallel one, and
    states the per-position absence as a permanently-null slot with a permanent
    semantics string.

(b) `currency_service` caches ONE spot rate per pair under a 30-minute TTL and
    has no dated series, so any historical window silently reused today's rate.
    A dated FX series is a capability, not a defect, so this does NOT fake one.
    It makes the absence a published fact: a mixed-currency book now reports
    that no dated rate exists and never supplies the snapshot rate in its place.

Every assertion runs against the real schemas/service/route helpers, not the
frozen export artifact.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from app.api.portfolio import (
    PORTFOLIO_PRICE_AS_OF_SEMANTICS,
    _fx_history_disclosure,
    _holding_date_provenance,
    get_portfolio,
)
from app.models.database import PortfolioPosition, StockTimeseries
from app.models.schemas import (
    POSITION_LAST_PRICE_AS_OF_SEMANTICS,
    PortfolioPositionResponse,
)
from app.services.currency_service import (
    HISTORICAL_FX_AVAILABLE,
    CurrencyConversionService,
    coerce_live_fx_rate,
)

_next_id = iter(range(1, 10_000))


class _StubFX:
    """Stub matching the shape `_convert_money` and the disclosures require."""

    def get_exchange_rate(self, *_a, **_k):
        return 1.0

    def get_exchange_rate_info(self):
        return {}


# ===========================================================================
# (a) the position contract states the absence of quote provenance
# ===========================================================================
class TestPositionQuoteProvenanceIsPublished:
    def _position(self, **over: Any) -> PortfolioPositionResponse:
        base = dict(
            id=1, ticker="AAA.NS", weight=0.5, quantity=1.0, buy_price=100.0,
            last_price=120.0, market_value=120.0, sector="Tech", industry="Y",
            custom_name=None,
            added_on=datetime(2020, 1, 1), updated_on=datetime(2026, 9, 26, 18, 7, 31),
            total_cost=100.0, unrealized_gain_loss=20.0,
            unrealized_gain_loss_pct=20.0, current_value=120.0,
        )
        base.update(over)
        return PortfolioPositionResponse(**base)

    def test_the_fields_are_declared_so_fastapi_cannot_drop_them(self) -> None:
        """Declared on the BASE schema, not just set at runtime.

        An undeclared key survives `model_dump()` in-process and vanishes on
        the HTTP wire - the schemas.py:485 lesson. The disclosure has to be on
        the response model to reach a client at all.
        """
        fields = PortfolioPositionResponse.model_fields
        assert "last_price_as_of" in fields
        assert "last_price_as_of_semantics" in fields
        assert "quote_provenance" in fields

    def test_the_as_of_slot_is_empty_and_says_why(self) -> None:
        """No provider market timestamp exists, so null - and never a fetch time."""
        pos = self._position()
        assert pos.last_price_as_of is None
        # The semantics is UNCONDITIONAL, which is the deliberate inversion of
        # the price_as_of pair: here the value never appears, so the reason must.
        assert pos.last_price_as_of_semantics == POSITION_LAST_PRICE_AS_OF_SEMANTICS
        assert "never_populated" in POSITION_LAST_PRICE_AS_OF_SEMANTICS

    def test_a_populated_as_of_cannot_be_produced_by_the_schema(self) -> None:
        """The null is not a default that a caller could quietly fill with fetch time."""
        pos = self._position(last_price_as_of=None)
        assert pos.last_price_as_of is None

    def test_each_unavailable_fact_is_named_with_its_reason(self) -> None:
        """Quote source and delayed/live are absent, not merely undocumented."""
        prov = self._position().quote_provenance
        for key in ("provider_market_timestamp", "quote_source", "delayed_or_live"):
            assert prov[key] is None, f"{key} must be an explicit null"
            assert prov[f"{key}_why"], f"{key} must carry its reason"
        assert prov["delayed_or_live_why"] != prov["quote_source_why"]

    def test_it_says_a_fetch_time_is_not_a_quote_time(self) -> None:
        prov = self._position().quote_provenance
        assert prov["fetch_time_is_not_a_quote_as_of_time"]
        assert "WRITTEN" in prov["fetch_time_is_not_a_quote_as_of_time"]

    def test_the_two_as_of_slots_are_distinguished(self) -> None:
        """`price_as_of` dates the BAR; `last_price_as_of` would date the QUOTE.

        Publishing one date beside a live price invites reading it as the price's
        age. The block has to separate the two clocks by name.
        """
        clocks = self._position().quote_provenance["clocks_that_do_exist"]
        assert "NOT" in clocks["price_as_of"] and "live quote" in clocks["price_as_of"]
        assert clocks["last_price_as_of"] is not None

    def test_the_envelope_provenance_distinguishes_the_two_clocks(self) -> None:
        prov = _holding_date_provenance()
        assert "last_price_as_of" in prov
        entry = prov["last_price_as_of"]
        assert POSITION_LAST_PRICE_AS_OF_SEMANTICS in entry
        assert "price_as_of" in entry and "different clocks" in entry

    def test_every_route_that_returns_a_position_inherits_it(self) -> None:
        """The base schema carries it, so /add cannot be the silent route."""
        assert "last_price_as_of" in PortfolioPositionResponse.model_fields
        # And the envelope that extends it does not shadow it away.
        from app.api.portfolio import PortfolioPositionEnvelope
        assert "last_price_as_of" in PortfolioPositionEnvelope.model_fields

    def test_the_real_route_publishes_it_per_position(self) -> None:
        pos = self._position()
        assert pos.quote_provenance["provider_market_timestamp"] is None


# ===========================================================================
# (b) a mixed-currency historical window states the rate is unavailable
# ===========================================================================
class TestHistoricalFxIsNotFaked:
    def test_the_service_declares_the_capability_gap(self) -> None:
        assert HISTORICAL_FX_AVAILABLE is False

    def test_the_status_never_carries_a_rate(self) -> None:
        """No `rate` key at all - a null could still be misread as a value."""
        svc = CurrencyConversionService()
        status = svc.get_historical_rate_status("USD", "INR", as_of=datetime(2024, 3, 1))
        assert "rate" not in status
        assert status["available"] is False
        assert status["dated"] is False
        assert status["requested_pair"] == "USD_INR"
        assert status["requested_as_of"] == "2024-03-01T00:00:00"

    def test_it_refuses_the_snapshot_rate_as_a_substitute(self) -> None:
        svc = CurrencyConversionService()
        status = svc.get_historical_rate_status("USD", "INR")
        assert status["substitute_available"] is False
        assert "not a substitute" in status["substitute_reason"]

    def test_identity_is_the_one_pair_with_a_dated_answer(self) -> None:
        svc = CurrencyConversionService()
        status = svc.get_historical_rate_status("INR", "INR")
        assert status["available"] is True and status["dated"] is True

    def test_an_unconfigured_pair_still_raises(self) -> None:
        """The :329-330 refusal is untouched by this disclosure."""
        svc = CurrencyConversionService()
        try:
            svc.get_historical_rate_status("GBP", "JPY")
        except ValueError:
            pass
        else:
            raise AssertionError("unconfigured pair must raise ValueError")

    def test_the_mixed_currency_disclosure_crosses_a_boundary(self) -> None:
        block = _fx_history_disclosure(
            {"AAA.NS": "USD", "BBB.NS": "INR"}, "INR", _StubFX()
        )
        assert block["crossed_a_currency_boundary"] is True
        assert block["non_base_currencies"] == ["USD"]
        assert block["historical_rate_available"] is False
        assert block["capability_gap"]

    def test_the_disclosure_supplies_no_rate_of_its_own(self) -> None:
        """No numeric rate anywhere in the block, for any branch."""
        block = _fx_history_disclosure(
            {"AAA.NS": "USD", "BBB.NS": "INR"}, "INR", _StubFX()
        )

        def _assert_no_rates(node: Any) -> None:
            if isinstance(node, dict):
                assert "rate" not in node, "the disclosure must never carry a rate"
                for key, value in node.items():
                    assert key != "rates", "a present-day map is still not historical"
                    _assert_no_rates(value)
            elif isinstance(node, list):
                for item in node:
                    _assert_no_rates(item)

        _assert_no_rates(block)

    def test_it_states_what_the_spot_rate_is_and_is_not(self) -> None:
        block = _fx_history_disclosure({"AAA.NS": "USD"}, "INR", _StubFX())
        assert "PRESENT-DAY" in block["fx_rate_basis"]
        assert any("fx_rate" in w for w in block["what_this_invalidates"])
        assert "dated historical FX" in block["capability_gap"]

    def test_a_single_currency_book_does_not_claim_a_crossing(self) -> None:
        block = _fx_history_disclosure({"AAA.NS": "INR", "BBB.NS": "INR"}, "INR", _StubFX())
        assert block["crossed_a_currency_boundary"] is False
        assert block["non_base_currencies"] == []
        # Still states the gap: the capability is absent regardless of the book.
        assert block["historical_rate_available"] is False

    def test_a_failing_status_does_not_take_the_envelope_down(self) -> None:
        class _RaisingFX:
            def get_historical_rate_status(self, *_a, **_k):
                raise RuntimeError("boom")

        block = _fx_history_disclosure({"AAA.NS": "USD"}, "INR", _RaisingFX())
        assert block["per_position_currency"]["USD"]["available"] is False
        assert block["per_position_currency"]["USD"]["reason"] == "RuntimeError"


# ===========================================================================
# the fail-closed FX path must not have been weakened
# ===========================================================================
class TestFailClosedFxIsPreserved:
    def test_coerce_live_fx_rate_still_refuses_the_fallback_constant(self) -> None:
        from app.services.currency_service import FALLBACK_USD_INR

        fallback = CurrencyConversionService()
        fallback._last_rate_metadata = {"provenance": "fallback", "source": "fallback_constant"}
        try:
            coerce_live_fx_rate(
                {"rate": FALLBACK_USD_INR, "provenance": "fallback",
                 "source": "fallback_constant", "is_fallback": True}
            )
        except Exception as exc:
            assert type(exc).__name__ == "CurrencyUnavailableError"
        else:
            raise AssertionError("the fallback rate must never be admitted as live")

    def test_coerce_live_fx_rate_still_refuses_a_bare_number(self) -> None:
        try:
            coerce_live_fx_rate(83.0)
        except Exception as exc:
            assert type(exc).__name__ == "CurrencyUnavailableError"
        else:
            raise AssertionError("an unlabelled rate must fail closed")

    def test_coerce_live_fx_rate_still_accepts_a_live_quote(self) -> None:
        rate, meta = coerce_live_fx_rate(
            {"rate": 83.25, "provenance": "live", "source": "yfinance"}
        )
        assert rate == 83.25
        assert meta["provenance"] == "live"


# ===========================================================================
# end-to-end: the wire payload for a mixed-currency book
# ===========================================================================
def _pos(ticker: str, currency: str, last_price: float) -> PortfolioPosition:
    return PortfolioPosition(
        id=next(_next_id), ticker=ticker, weight=0.0, quantity=1.0,
        buy_price=last_price, last_price=last_price, market_value=last_price,
        region="IN", sector="Tech", industry="Y",
        added_on=datetime(2020, 1, 1),
        updated_on=datetime(2026, 9, 26, 18, 7, 31),
    )


async def _envelope(test_db, positions, bars=()):
    for position in positions:
        test_db.add(position)
    for ticker, when in bars:
        # The column is a DateTime; the existing provenance test passes the ISO
        # string because its model differs. Pass the object this schema wants.
        test_db.add(StockTimeseries(
            ticker=ticker, date=datetime.fromisoformat(when), open=1.0, high=1.0,
            low=1.0, close=1.0,
            adj_close=1.0, volume=10, source_used="yfinance", fetch_status="fresh",
        ))
    await test_db.commit()

    class _MixedFX:
        def get_exchange_rate(self, *_a, **_k):
            from app.services.currency_service import FXRate
            return FXRate(83.25, provenance="live", source="yfinance")

        def get_exchange_rate_info(self):
            return {"last_updated": None, "is_fallback": False}

        def get_historical_rate_status(self, from_currency, to_currency, *, as_of=None):
            return CurrencyConversionService().get_historical_rate_status(
                from_currency, to_currency, as_of=as_of
            )

    with patch("app.api.portfolio._update_portfolio_prices", new=AsyncMock()), \
         patch("app.api.portfolio._clear_portfolio_dependent_memos"), \
         patch("app.api.portfolio.get_currency_service", return_value=_MixedFX()):
        return await get_portfolio(currency="INR", db=test_db, data_service=Mock())


class TestMixedCurrencyEnvelopeOnTheWire:
    async def test_the_envelope_states_no_dated_rate_exists(self, test_db) -> None:
        # AAPL has no .NS/.BO suffix, so `_position_currency` resolves it to USD
        # and BBB.NS to INR: the book really does cross a currency boundary.
        envelope = await _envelope(
            test_db,
            [_pos("AAPL", "USD", 100.0), _pos("BBB.NS", "INR", 50.0)],
            bars=[("AAPL", "2026-09-25"), ("BBB.NS", "2026-09-25")],
        )
        fx_history = envelope.currency_provenance["fx_history"]

        # The capability gap is stated, not papered over.
        assert fx_history["historical_rate_available"] is False
        assert fx_history["currency_service_historical_fx_available"] is False
        assert fx_history["crossed_a_currency_boundary"] is True
        assert fx_history["non_base_currencies"] == ["USD"]
        assert fx_history["per_position_currency"]["USD"]["dated"] is False

        # The block supplies no rate to stand in for the missing one.
        assert "rate" not in fx_history
        assert "rates" not in fx_history

    async def test_the_present_day_rate_is_labelled_as_such(self, test_db) -> None:
        """`rates` still serves today's quote - but never as a historical one."""
        envelope = await _envelope(
            test_db,
            [_pos("AAPL", "USD", 100.0), _pos("BBB.NS", "INR", 50.0)],
            bars=[("AAPL", "2026-09-25"), ("BBB.NS", "2026-09-25")],
        )
        fx_history = envelope.currency_provenance["fx_history"]
        assert "PRESENT-DAY" in fx_history["fx_rate_basis"]
        assert any("fx_rate" in w for w in fx_history["what_this_invalidates"])

    async def test_the_same_envelope_keeps_both_as_of_clocks_separate(self, test_db) -> None:
        """Bar date on the position; quote as-of permanently null."""
        envelope = await _envelope(
            test_db,
            [_pos("AAPL", "USD", 100.0), _pos("BBB.NS", "INR", 50.0)],
            bars=[("AAPL", "2026-09-25"), ("BBB.NS", "2026-09-25")],
        )
        for pos in envelope.positions:
            assert pos.price_as_of == "2026-09-25"
            assert pos.price_as_of_semantics == PORTFOLIO_PRICE_AS_OF_SEMANTICS
            # The live quote is still undated next to that bar date.
            assert pos.last_price_as_of is None
            assert pos.last_price_as_of_semantics == POSITION_LAST_PRICE_AS_OF_SEMANTICS
            assert pos.quote_provenance["quote_source"] is None

    async def test_an_empty_book_still_publishes_the_disclosure(self, test_db) -> None:
        """The key is present even with nothing converted, so it reads as a fact."""
        envelope = await _envelope(test_db, [])
        fx_history = envelope.currency_provenance["fx_history"]
        assert fx_history["crossed_a_currency_boundary"] is False
        assert fx_history["historical_rate_available"] is False
        assert envelope.positions == []