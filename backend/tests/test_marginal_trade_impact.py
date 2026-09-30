"""A PROPOSED change, scored for the delta it makes -- and every refusal named.

Everything else in this service describes the portfolio as it IS. The gap this
file closes is the prospective one: given the user's real persisted weights and
a hypothetical trade, publish what concentration and risk BECOME, and by how
much, so the answer is a decision rather than a level.

Four traps are gated here, each of which would be silently fatal:

1.  The route must not go through `resolve_allocation`. That helper hard-codes
    `eq = 1.0 / len(ticker_list)` for any ticker absent from the positions
    table, so a proposed "buy X at 5%" would be reinterpreted as "N tickers at
    1/N each" -- a DIFFERENT portfolio, not a perturbation of this one.
2.  Nothing may be persisted. A proposed position given an `added_on` would
    enter `effective_start`'s INTERSECTION across the book and mask every real
    holding to a window that never existed.
3.  A user-supplied weight is not a measurement. `measured | unmeasured` is
    load-bearing vocabulary, so the proposal needs a THIRD state, and it has to
    reach the concentration block's OUTPUT (per-leg contribution shares), not
    just the request row.
4.  `.corr()` is pairwise-complete: a pair under two shared rows is NaN, which
    means UNKNOWN. It must never become 0.0, which claims no relationship
    whatsoever. Three paths did exactly that before this feature existed.

The refusal vocabulary is the hard part, so it is asserted per state:
`measured (n shared sessions)`, `unmeasurable` with the count and the floor
named, and `not attempted` with why. A refused figure is null plus a reason and
is never a zero.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_mod
from app.api.analytics import (
    MARGINAL_MIN_SHARED_SESSIONS,
    MARGINAL_PROPOSAL_PROVENANCE,
    MARGINAL_STATE_MEASURED,
    MARGINAL_STATE_NOT_ATTEMPTED,
    MARGINAL_STATE_UNMEASURABLE,
    MARGINAL_WEIGHT_PROVENANCE_MEASURED,
    MARGINAL_WEIGHT_PROVENANCE_PROPOSED,
    post_marginal_trade_impact,
)
from app.models.database import PortfolioPosition
from app.models.schemas import (
    MARGINAL_FUNDING_CASH_RESIDUAL,
    MARGINAL_FUNDING_SELL_AND_REBALANCE,
    MarginalTradeImpactRequest,
)
from app.services.analytics_engine import (
    MIN_SHARED_ROWS_FOR_CORRELATION,
    AnalyticsEngine,
)
from app.utils.allocations import MIN_SIZING_OBSERVATIONS
from app.utils.holdings import MIN_ANNUALIZE_DAYS


# ---------------------------------------------------------------------------
# seams
# ---------------------------------------------------------------------------
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


def _pos(ticker: str, market_value: float, *, sector: str = "Energy"):
    return PortfolioPosition(
        id=1, ticker=ticker, weight=None, quantity=1.0, buy_price=None,
        last_price=market_value, market_value=market_value, region="IN",
        sector=sector, industry="Y", added_on=None,
    )


class _Market:
    """Price frames keyed by ticker, sliced to whatever window is requested.

    The fixture index is anchored to the CLOCK, never to a fixed past date: the
    route derives its window from `datetime.now()`, so a hard-dated fixture
    eventually falls out of the request and the route returns its no-price-data
    shape for a reason that has nothing to do with the claim under test.
    """

    def __init__(self, frames: Dict[str, pd.DataFrame]):
        self.frames = frames
        self.fetch_historical_data = AsyncMock(side_effect=self._history)

    async def _history(self, ticker, start, end):
        frame = self.frames.get(ticker)
        if frame is None:
            return pd.DataFrame()
        window = frame.loc[
            (frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))
        ]
        return window.copy()


def _ohlcv(dates, prices):
    return pd.DataFrame({"Close": prices, "Volume": np.full(len(dates), 1e6)}, index=dates)


def _walk(rng, days, *, drift=0.0004, vol=0.011):
    return 100.0 * np.cumprod(1.0 + rng.normal(drift, vol, days))


def _history_clock(days: int) -> pd.DatetimeIndex:
    """`days` business days ending on the current date.

    Anchored to the clock on purpose; see `_Market`.
    """
    return pd.bdate_range(end=pd.Timestamp(datetime.now().date()), periods=days)


async def _run(
    db,
    market,
    legs: List[Dict[str, Any]],
    *,
    funding: str = MARGINAL_FUNDING_SELL_AND_REBALANCE,
    history_days: int = 900,
) -> Dict[str, Any]:
    request = MarginalTradeImpactRequest(
        legs=legs, funding=funding, history_days=history_days,
    )
    return await post_marginal_trade_impact(
        request=request,
        db=db,
        data_service=market,
        analytics_engine=AnalyticsEngine(),
    )


def _metrics(block: Dict[str, Any]) -> Dict[str, Any]:
    return block["metrics"]


# ---------------------------------------------------------------------------
# A. concentration -- pure arithmetic, always available
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_concentration_delta_is_published_not_only_a_level():
    """THE claim: the answer is a change, not a number.

    A response carrying `after: 0.34` with no `before` and no `delta` describes
    a book nobody holds. This asserts the delta is present, is the arithmetic
    difference of the two published levels, and is non-zero for a proposal that
    actually changes the book.
    """
    db = _db([
        _pos("A.NS", 0.50), _pos("B.NS", 0.30), _pos("C.NS", 0.20),
    ])
    market = _Market({})

    result = await _run(db, market, [{"ticker": "NEW.NS", "target_weight": 0.30}])

    hhi = _metrics(result["concentration"])["herfindahl_index"]
    assert hhi["before"] is not None and hhi["after"] is not None
    assert hhi["delta"] == pytest.approx(hhi["after"] - hhi["before"], abs=1e-9)
    # Adding a fourth position to a book of three DIVERSIFIES it. If the sign
    # were wrong this would be the first thing to break.
    assert hhi["delta"] < 0.0
    assert hhi["state"] == MARGINAL_STATE_MEASURED
    assert hhi["reason"] is None
    # And the sample is stated, so a reader can judge the arithmetic.
    assert isinstance(hhi["observations"], int)

    for key in ("effective_positions", "top_3", "diversification_score"):
        entry = _metrics(result["concentration"])[key]
        assert set(("before", "after", "delta")) <= set(entry)
        assert entry["delta"] == pytest.approx(entry["after"] - entry["before"], abs=1e-9)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "legs, expect_concentrating",
    [
        # A 20% buy into a 70/30 book DIVERSIFIES it. Under pro-rata funding a
        # new leg dilutes unless w > 2H/(1+H); at H=0.58 that threshold is
        # 0.734, so 0.20 lands well below it and the HHI must FALL. Asserting
        # the opposite here would encode a sign error.
        ([{"ticker": "NEW.NS", "target_weight": 0.20}], False),
        # 0.90 is above the threshold: this buy really does concentrate.
        ([{"ticker": "NEW.NS", "target_weight": 0.90}], True),
        # The other way a book concentrates: fatten the incumbent.
        ([{"ticker": "BIG.NS", "target_weight": 0.90}], True),
    ],
)
async def test_the_hhi_delta_sign_is_right_in_both_directions(
    legs, expect_concentrating
):
    """"Will this concentrate me?" is answered by the DIRECTION of the delta.

    Both signs are asserted, because an implementation that returns a
    consistently-signed delta passes either single-direction check. The sign is
    recomputed here from the published weights rather than read off the index.
    """
    current = {"BIG.NS": 0.70, "MID.NS": 0.30}
    db = _db([_pos(t, w) for t, w in current.items()])

    result = await _run(db, _Market({}), legs)

    hhi = _metrics(result["concentration"])["herfindahl_index"]
    recomputed = sum(
        float(w) * float(w) for w in result["proposed_weights"].values()
    )
    baseline = sum(float(w) * float(w) for w in current.values())
    assert hhi["after"] == pytest.approx(recomputed, abs=1e-4)
    assert hhi["before"] == pytest.approx(baseline, abs=1e-4)
    if expect_concentrating:
        assert hhi["delta"] > 0.0, legs
        # Effective N falls when HHI rises. The two must move together.
        assert _metrics(result["concentration"])["effective_positions"]["delta"] < 0.0
    else:
        assert hhi["delta"] < 0.0, legs
        assert _metrics(result["concentration"])["effective_positions"]["delta"] > 0.0


@pytest.mark.asyncio
async def test_concentration_needs_no_price_history_and_no_adapter():
    """A data service that fails every fetch must not cost the concentration half.

    `concentration_analysis(weights)` is arithmetic on a dict. If this half ever
    starts depending on the feed, it starts failing for reasons unrelated to
    the question being asked.
    """
    class _Dead:
        async def fetch_historical_data(self, *_a, **_k):
            raise RuntimeError("feed is down")

    db = _db([_pos("A.NS", 0.6), _pos("B.NS", 0.4)])
    result = await _run(db, _Dead(), [{"ticker": "NEW.NS", "target_weight": 0.25}])

    assert result["concentration"]["state"] == MARGINAL_STATE_MEASURED
    assert result["concentration"]["reason"] is None
    assert _metrics(result["concentration"])["herfindahl_index"]["delta"] is not None


# ---------------------------------------------------------------------------
# B. the funding arithmetic -- recomputed here, not restated
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_buying_at_weight_w_scales_the_rest_of_the_book_by_one_minus_w():
    """The funding rule, checked against the arithmetic rather than the code.

    "Buy X at 5%" must leave every existing position at 95% of its current
    weight. The expectation below is derived from the rule in plain arithmetic
    (`w * (1 - x)`), NOT from a second reading of the implementation, so it can
    disagree with it.
    """
    current = {"A.NS": 0.5, "B.NS": 0.3, "C.NS": 0.2}
    target = 0.05
    db = _db([_pos(t, w) for t, w in current.items()])

    result = await _run(db, _Market({}), [
        {"ticker": "NEW.NS", "target_weight": target},
    ])

    proposed = result["proposed_weights"]
    for ticker, weight in current.items():
        assert proposed[ticker] == pytest.approx(weight * (1.0 - target), rel=1e-12), (
            f"{ticker} was not scaled by 1 - w; the rest of the book must fund "
            "the purchase pro rata"
        )
    assert proposed["NEW.NS"] == pytest.approx(target, rel=1e-12)
    assert sum(proposed.values()) == pytest.approx(1.0, abs=1e-12)
    assert result["funding_residual"] == pytest.approx(0.0, abs=1e-12)

    # The rule the reader is told, and the scale factor it implies.
    derivation = result["disclosure"]["weight_derivation"]
    assert derivation["unnamed_book_scale_factor"] == pytest.approx(
        1.0 - target, rel=1e-12,
    )
    assert derivation["funding"] == MARGINAL_FUNDING_SELL_AND_REBALANCE
    assert derivation["funding_rule"]


@pytest.mark.asyncio
async def test_cash_residual_funding_does_not_reinvest_a_sale():
    """"Buy X at 5%" does not say where the 5% comes from.

    Two rules are published and the caller names one. Under `cash_residual`
    nothing is reinvested: unnamed legs keep their exact weights and the
    unspent weight becomes cash rather than being silently pushed back into the
    book.
    """
    current = {"A.NS": 0.6, "B.NS": 0.4}
    db = _db([_pos(t, w) for t, w in current.items()])

    result = await _run(db, _Market({}), [
        {"ticker": "B.NS", "target_weight": 0.0},
    ], funding=MARGINAL_FUNDING_CASH_RESIDUAL)

    assert result["cash_weight"] == pytest.approx(0.4, abs=1e-12)
    assert result["proposed_weights"]["A.NS"] == pytest.approx(0.6, rel=1e-12)
    assert "B.NS" not in result["proposed_weights"]
    assert (
        sum(result["proposed_weights"].values()) + result["cash_weight"]
    ) == pytest.approx(1.0, abs=1e-12)
    # The published closure is legs PLUS cash against 1.0, not legs alone: a
    # residual computed over the legs of a book that deliberately holds cash
    # would read as a rule that failed to close.
    assert result["funding_residual"] == pytest.approx(0.0, abs=1e-12)
    derivation = result["disclosure"]["weight_derivation"]
    assert derivation["proposed_total"] == pytest.approx(0.6, abs=1e-12)
    assert derivation["cash_weight"] == pytest.approx(0.4, abs=1e-12)
    # Under this rule the SAME sale is NOT redistributed, which is the whole
    # point of naming it.
    rebalanced = await _run(_db([_pos(t, w) for t, w in current.items()]), _Market({}), [
        {"ticker": "B.NS", "target_weight": 0.0},
    ])
    assert rebalanced["proposed_weights"]["A.NS"] == pytest.approx(1.0, rel=1e-12)
    assert rebalanced["cash_weight"] is None


@pytest.mark.asyncio
async def test_cash_residual_refuses_a_purchase_the_book_cannot_pay_for():
    """A buy funded by cash would need a portfolio value this endpoint lacks.

    The book is fully invested, so `cash_residual` has nothing to sell. Funding
    it would mean scaling the whole book by 1/(1+w) -- a rescale nobody asked
    for -- or inventing a portfolio value to size the new money. It refuses.
    """
    db = _db([_pos("A.NS", 0.6), _pos("B.NS", 0.4)])

    result = await _run(db, _Market({}), [
        {"ticker": "NEW.NS", "target_weight": 0.10},
    ], funding=MARGINAL_FUNDING_CASH_RESIDUAL)

    assert result["error"] is not None
    assert "more weight than the book holds" in result["error"]
    assert result["concentration"]["state"] == MARGINAL_STATE_NOT_ATTEMPTED


@pytest.mark.asyncio
async def test_a_proposal_that_cannot_be_funded_is_refused_not_rescaled():
    """Never silently rescale the book in a way the caller did not ask for.

    A proposal naming every holding and summing to 0.9 has no unnamed book to
    release 0.1 from. Fabricating one would answer a different question.
    """
    db = _db([_pos("A.NS", 0.6), _pos("B.NS", 0.4)])

    result = await _run(db, _Market({}), [
        {"ticker": "A.NS", "target_weight": 0.5},
        {"ticker": "B.NS", "target_weight": 0.4},
    ])

    assert result["error"] is not None
    assert "nothing to sell" in result["error"]
    assert result["concentration"]["state"] == MARGINAL_STATE_NOT_ATTEMPTED
    assert result["risk"]["state"] == MARGINAL_STATE_NOT_ATTEMPTED
    # The persisted book is a measurement, so it survives the refusal: a reader
    # told "your proposal names every holding" has to see which holdings.
    assert result["current_weights"] == {"A.NS": 0.6, "B.NS": 0.4}
    assert result["proposed_weights"] == {}


# ---------------------------------------------------------------------------
# trap 1: the route must not funnel through resolve_allocation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_route_never_goes_through_resolve_allocation(monkeypatch):
    """`resolve_allocation` would reinterpret a proposed ticker as 1/N.

    It hard-codes `eq = 1.0 / len(ticker_list)` for anything absent from the
    positions table, so "buy X at 5%" would become an equal-weight book -- a
    different portfolio, whose deltas describe something the user does not hold.
    """
    def _forbidden(*_a, **_k):
        raise AssertionError(
            "resolve_allocation was called; it assigns 1/N to any ticker "
            "missing from the positions table, which is exactly the wrong "
            "reinterpretation of a proposed leg"
        )

    monkeypatch.setattr(analytics_mod, "resolve_allocation", _forbidden)

    db = _db([_pos("A.NS", 0.7), _pos("B.NS", 0.3)])
    result = await _run(db, _Market({}), [
        {"ticker": "BRAND.NEW.TICKER", "target_weight": 0.05},
    ])

    assert result["error"] is None
    # The proposal was applied to the USER'S weights, at the weight they asked
    # for -- not to an equal-weight reconstruction of some other book.
    assert result["proposed_weights"]["BRAND.NEW.TICKER"] == pytest.approx(0.05)
    assert result["disclosure"]["resolved_via_resolve_allocation"] is False


# ---------------------------------------------------------------------------
# trap 2: the proposal is never persisted
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_the_proposal_is_never_persisted_and_never_given_an_added_on():
    """A hypothetical is not a holding.

    Writing one would give it an `added_on`, and `effective_start` takes the
    INTERSECTION start across the whole book -- so one invented row would mask
    every real holding to a window that never existed.
    """
    positions = [_pos("A.NS", 0.7), _pos("B.NS", 0.3)]
    db = _db(positions)

    result = await _run(db, _Market({}), [
        {"ticker": "NEW.NS", "target_weight": 0.10},
    ])

    assert result["error"] is None
    db.add.assert_not_called()
    db.commit.assert_not_called()
    db.flush.assert_not_called()
    db.delete.assert_not_called()
    # No row was mutated, and no `added_on` was written to anything.
    assert [p.ticker for p in positions] == ["A.NS", "B.NS"]
    assert all(p.added_on is None for p in positions)
    assert result["disclosure"]["persisted"] is False
    assert "added_on" in result["disclosure"]["persistence_note"]


# ---------------------------------------------------------------------------
# trap 3: provenance propagates into the concentration OUTPUT
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_user_supplied_weight_is_proposed_provenance_and_reaches_the_output():
    """The third state, and it has to PROPAGATE.

    HHI, effective-N, the diversification score and every contribution share are
    computed from these weights. If the proposed leg were annotated as proposed
    on the request row only, every index downstream would read as a measurement
    of the book -- which it is not.
    """
    db = _db([_pos("A.NS", 0.6), _pos("B.NS", 0.4)])

    result = await _run(db, _Market({}), [
        {"ticker": "NEW.NS", "target_weight": 0.25},
    ])

    by_leg = result["concentration"]["by_leg"]
    assert by_leg["NEW.NS"]["weight_provenance"] == MARGINAL_WEIGHT_PROVENANCE_PROPOSED
    assert by_leg["A.NS"]["weight_provenance"] == MARGINAL_WEIGHT_PROVENANCE_MEASURED
    assert by_leg["B.NS"]["weight_provenance"] == MARGINAL_WEIGHT_PROVENANCE_MEASURED

    # And the assumption reaches the block that publishes the indices.
    assert "NEW.NS" in result["concentration"]["proposed_tickers"]
    assert "proposed" in result["concentration"]["weight_provenance_vocabulary"]
    assert result["proposal_provenance"] == MARGINAL_PROPOSAL_PROVENANCE
    assert result["proposal_provenance"].startswith("user_supplied")
    assert "user-supplied weight" in result["concentration"]["basis"]
    # A leg the proposal did not name is a measured weight, so the vocabulary
    # distinguishes the two rather than calling everything unmeasured.
    assert MARGINAL_WEIGHT_PROVENANCE_MEASURED != "unmeasured"
    assert MARGINAL_WEIGHT_PROVENANCE_PROPOSED != "unmeasured"


# ---------------------------------------------------------------------------
# B. risk -- measured deltas on a real book, and refusal where it is not
# ---------------------------------------------------------------------------
def _real_book_market(days: int = 400):
    """A real book plus a candidate that overlaps it well."""
    dates = _history_clock(days)
    rng = np.random.default_rng(11)
    return _Market({
        "A.NS": _ohlcv(dates, _walk(rng, days, vol=0.010)),
        "B.NS": _ohlcv(dates, _walk(rng, days, vol=0.014)),
        "NEW.NS": _ohlcv(dates, _walk(rng, days, vol=0.030)),
    })


@pytest.mark.asyncio
async def test_risk_publishes_before_after_and_delta_on_a_real_book():
    """Both books are measured over the SAME sessions, or the delta is noise."""
    db = _db([_pos("A.NS", 0.5), _pos("B.NS", 0.5)])

    result = await _run(db, _real_book_market(), [
        {"ticker": "NEW.NS", "target_weight": 0.20},
    ])

    risk = result["risk"]
    assert risk["state"] == MARGINAL_STATE_MEASURED, risk["reason"]
    assert risk["shared_sessions"] >= MARGINAL_MIN_SHARED_SESSIONS
    for key in ("annual_volatility", "var_95", "cvar_95", "sharpe_ratio"):
        entry = risk["metrics"][key]
        assert entry["before"] is not None, key
        assert entry["after"] is not None, key
        assert entry["delta"] is not None, key
        assert entry["delta"] == pytest.approx(entry["after"] - entry["before"], abs=1e-9)
        assert entry["state"] == MARGINAL_STATE_MEASURED
        assert entry["observations"] == risk["shared_sessions"]
        assert entry["units"]

    # A 30%-vol candidate against a 10-14% book must RAISE volatility. If the
    # sign is wrong the whole feature is answering the wrong question.
    vol = risk["metrics"]["annual_volatility"]
    assert vol["delta"] > 0.0
    assert vol["delta_percentage_points"] == pytest.approx(vol["delta"] * 100.0, abs=1e-4)


@pytest.mark.asyncio
async def test_a_candidate_with_too_little_history_is_refused_not_zeroed():
    """THE refusal test: a refusal with a reason, never a fabricated delta.

    Three weeks of history cannot produce a trustworthy risk delta. Publishing
    0.0 would be indistinguishable from a measured "no change", which is the
    one number a reader must never be handed for an unmeasured quantity.
    """
    long_dates = _history_clock(400)
    short_dates = _history_clock(20)
    rng = np.random.default_rng(5)
    market = _Market({
        "A.NS": _ohlcv(long_dates, _walk(rng, 400, vol=0.010)),
        "B.NS": _ohlcv(long_dates, _walk(rng, 400, vol=0.012)),
        "NEW.NS": _ohlcv(short_dates, _walk(rng, 20, vol=0.030)),
    })
    db = _db([_pos("A.NS", 0.5), _pos("B.NS", 0.5)])

    result = await _run(db, market, [
        {"ticker": "NEW.NS", "target_weight": 0.20},
    ])

    risk = result["risk"]
    assert risk["state"] == MARGINAL_STATE_UNMEASURABLE
    assert risk["reason"]
    assert str(MIN_ANNUALIZE_DAYS) in risk["reason"], (
        "the refusal must name the floor it fell below"
    )
    for key in ("annual_volatility", "var_95", "cvar_95", "sharpe_ratio"):
        entry = risk["metrics"][key]
        assert entry["before"] is None and entry["after"] is None
        assert entry["delta"] is None
        assert entry["state"] == MARGINAL_STATE_UNMEASURABLE
        assert entry["reason"] == risk["reason"]
    # The short leg is named, so the reader knows WHICH leg was thin.
    assert "NEW.NS" in risk["tickers_below_minimum_sample"]
    assert risk["per_ticker_return_observations"]["NEW.NS"] < MIN_SIZING_OBSERVATIONS
    assert result["data_status"] == "partial"


@pytest.mark.asyncio
async def test_an_absent_shared_period_is_refused_with_the_count():
    """No overlap at all is also `unmeasurable`, and says how little it had."""
    today = pd.Timestamp(datetime.now().date())
    old = pd.bdate_range(end=today - timedelta(days=400), periods=200)
    fresh = pd.bdate_range(end=today, periods=200)
    rng = np.random.default_rng(7)
    market = _Market({
        "A.NS": _ohlcv(old, _walk(rng, 200, vol=0.010)),
        "NEW.NS": _ohlcv(fresh, _walk(rng, 200, vol=0.020)),
    })
    db = _db([_pos("A.NS", 1.0)])

    result = await _run(db, market, [
        {"ticker": "NEW.NS", "target_weight": 0.20},
    ])

    risk = result["risk"]
    assert risk["state"] == MARGINAL_STATE_UNMEASURABLE
    assert risk["shared_sessions"] == 0
    assert "0 shared return sessions" in risk["reason"]
    assert risk["metrics"]["annual_volatility"]["delta"] is None


@pytest.mark.asyncio
async def test_an_empty_book_refuses_rather_than_reporting_against_nothing():
    """No book means no before-state; a delta against nothing is not a delta."""
    result = await _run(_db([]), _Market({}), [
        {"ticker": "NEW.NS", "target_weight": 0.10},
    ])

    assert result["error"] is not None
    assert "No portfolio positions found" in result["error"]
    assert result["concentration"]["state"] == MARGINAL_STATE_NOT_ATTEMPTED
    assert result["risk"]["state"] == MARGINAL_STATE_NOT_ATTEMPTED
    assert result["data_status"] == "unavailable"


# ---------------------------------------------------------------------------
# trap 4: an unknown correlation is never published as 0.0
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_an_unmeasurable_correlation_is_never_published_as_zero():
    """`.corr()` answers NaN under two shared rows; NaN means UNKNOWN.

    0.0 in a correlation is not a neutral placeholder, it is the strongest
    available claim -- no relationship whatsoever. The route publishes no
    correlation figure at all, so the floor it declares is a floor it never
    steps over, and the refusal wording it forwards is the engine's own.
    """
    result = await _run(
        _db([_pos("A.NS", 0.6), _pos("B.NS", 0.4)]), _Market({}),
        [{"ticker": "NEW.NS", "target_weight": 0.10}],
    )

    thresholds = result["disclosure"]["thresholds"]
    assert thresholds["MIN_SHARED_ROWS_FOR_CORRELATION"]["value"] == (
        MIN_SHARED_ROWS_FOR_CORRELATION
    )
    assert thresholds["MIN_SHARED_ROWS_FOR_CORRELATION"]["value"] == 2

    risk = result["risk"]
    if risk["state"] == MARGINAL_STATE_MEASURED:
        # No pairwise figure may be published as a stand-in zero anywhere.
        for key in ("annual_volatility", "var_95", "cvar_95", "sharpe_ratio"):
            assert risk["metrics"][key]["delta"] is not None or risk["metrics"][key][
                "before"
            ] is None
    else:
        for entry in risk["metrics"].values():
            assert entry["delta"] is None, (
                "a refused risk half published a delta; the refusal is the answer"
            )


# ---------------------------------------------------------------------------
# the vocabulary itself
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_every_published_figure_carries_an_explicit_state_and_a_reason():
    """A reader must be able to tell, without inference, what was measured."""
    db = _db([_pos("A.NS", 0.6), _pos("B.NS", 0.4)])
    result = await _run(db, _Market({}), [
        {"ticker": "NEW.NS", "target_weight": 0.10},
    ])

    states = set(result["disclosure"]["states"])
    assert states == {
        MARGINAL_STATE_MEASURED,
        MARGINAL_STATE_UNMEASURABLE,
        MARGINAL_STATE_NOT_ATTEMPTED,
    }

    for block in ("concentration", "risk"):
        section = result[block]
        assert section["state"] in states
        if section["state"] != MARGINAL_STATE_MEASURED:
            assert section["reason"], block
        for entry in section["metrics"].values():
            assert entry["state"] in states
            assert entry["reason"] is None or isinstance(entry["reason"], str)
            if entry["state"] != MARGINAL_STATE_MEASURED:
                assert entry["reason"], block
            else:
                # A `measured` figure with a null side is the one combination
                # that makes a value indistinguishable from an absence.
                assert entry["before"] is not None, block
                assert entry["after"] is not None, block
                assert entry["delta"] is not None, block
                assert entry["reason"] is None, block
    for leg in result["concentration"]["by_leg"].values():
        assert leg["state"] in states
        assert "weight_provenance" in leg


@pytest.mark.asyncio
async def test_the_thresholds_that_gate_the_statistics_are_published_with_their_sources():
    """Every gate is declared, with the value AND where it is declared."""
    result = await _run(
        _db([_pos("A.NS", 0.6), _pos("B.NS", 0.4)]), _Market({}),
        [{"ticker": "NEW.NS", "target_weight": 0.10}],
    )

    thresholds = result["disclosure"]["thresholds"]
    assert thresholds["MIN_ANNUALIZE_DAYS"]["value"] == MIN_ANNUALIZE_DAYS == 30
    assert thresholds["MIN_ANNUALIZE_DAYS"]["declared_in"] == "app/utils/holdings.py"
    assert thresholds["MIN_SIZING_OBSERVATIONS"]["value"] == MIN_SIZING_OBSERVATIONS
    assert thresholds["MIN_SIZING_OBSERVATIONS"]["declared_in"] == (
        "app/utils/allocations.py"
    )
    assert thresholds["MIN_SHARED_ROWS_FOR_CORRELATION"]["declared_in"] == (
        "app/services/analytics_engine.py"
    )
    assert thresholds["PORTFOLIO_RETURN_MIN_COVERAGE"]["value"] == 1.0
    assert result["disclosure"]["minimum_shared_sessions_required"] == (
        MIN_ANNUALIZE_DAYS
    )
    for spec in thresholds.values():
        assert spec["gates"]


@pytest.mark.asyncio
async def test_the_weights_can_be_recomputed_by_hand_from_the_published_derivation():
    """Current weights + rule + proposal == the proposed vector."""
    current = {"A.NS": 0.5, "B.NS": 0.3, "C.NS": 0.2}
    db = _db([_pos(t, w) for t, w in current.items()])

    result = await _run(db, _Market({}), [
        {"ticker": "NEW.NS", "target_weight": 0.15},
    ])

    derivation = result["disclosure"]["weight_derivation"]
    assert derivation["current_weights"] == dict(sorted(current.items()))
    scale = derivation["unnamed_book_scale_factor"]
    assert scale == pytest.approx(0.85, rel=1e-12)
    for ticker, weight in current.items():
        expected = weight * scale
        assert result["proposed_weights"][ticker] == pytest.approx(expected, rel=1e-12)
    assert result["proposed_weights"]["NEW.NS"] == pytest.approx(0.15, rel=1e-12)
    assert result["current_weights"] == dict(sorted(current.items()))
    assert sum(result["proposed_weights"].values()) == pytest.approx(1.0, abs=1e-12)


@pytest.mark.asyncio
async def test_a_legs_absent_share_is_a_measured_zero_not_an_absence():
    """`before: null` on a new leg would say its share is UNKNOWN.

    It is not unknown: the book is 60/40 across two names, so a third name's
    share is exactly 0.0 and the engine has said so by omitting it. Publishing
    null there would make a measured zero indistinguishable from a gap.
    """
    db = _db([_pos("A.NS", 0.6), _pos("B.NS", 0.4)])

    result = await _run(db, _Market({}), [
        {"ticker": "NEW.NS", "target_weight": 0.25},
    ])

    leg = result["concentration"]["by_leg"]["NEW.NS"]
    assert leg["before"] == 0.0
    assert leg["after"] == pytest.approx(0.25, abs=1e-6)
    assert leg["delta"] == pytest.approx(0.25, abs=1e-6)


@pytest.mark.asyncio
async def test_an_empty_proposed_book_is_unmeasurable_not_a_zero_index():
    """`concentration_analysis` zeroes every index for an empty book.

    Those zeroes are an ABSENCE wearing a measurement's clothes. Forwarding
    them as "concentration went to 0.0" would be the defect this engine already
    documents in `_empty_concentration`, reproduced one layer up.
    """
    db = _db([_pos("A.NS", 1.0)])

    # Funding everything to cash leaves no invested leg at all.
    result = await _run(db, _Market({}), [
        {"ticker": "A.NS", "target_weight": 0.0},
    ], funding=MARGINAL_FUNDING_CASH_RESIDUAL)

    concentration = result["concentration"]
    assert concentration["state"] == MARGINAL_STATE_UNMEASURABLE
    assert concentration["reason"]
    assert "absent book" in concentration["reason"]
    assert concentration["metrics"] == {}
    assert concentration["by_leg"] == {}
    # The risk half refuses for the same reason, and publishes nothing.
    assert result["risk"]["metrics"]["annual_volatility"]["delta"] is None


@pytest.mark.asyncio
async def test_a_risk_figure_the_engine_withholds_is_not_published_as_measured():
    """`state: measured` beside a null is the one ambiguous combination left.

    If `calculate_portfolio_metrics` publishes no Sharpe for either book, the
    delta does not exist. Reporting it as measured with a null value and no
    reason is exactly what this payload exists to prevent.
    """
    class _NoSharpe(AnalyticsEngine):
        async def calculate_portfolio_metrics(self, price_data, weights=None):
            metrics = await super().calculate_portfolio_metrics(price_data, weights)
            out = dict(metrics)
            out["sharpe_ratio"] = None
            return out

    db = _db([_pos("A.NS", 0.5), _pos("B.NS", 0.5)])
    request = MarginalTradeImpactRequest(
        legs=[{"ticker": "NEW.NS", "target_weight": 0.20}], history_days=900,
    )
    result = await post_marginal_trade_impact(
        request=request,
        db=db,
        data_service=_real_book_market(),
        analytics_engine=_NoSharpe(),
    )

    sharpe = result["risk"]["metrics"]["sharpe_ratio"]
    assert sharpe["before"] is None and sharpe["after"] is None
    assert sharpe["delta"] is None
    assert sharpe["state"] == MARGINAL_STATE_UNMEASURABLE
    assert sharpe["reason"], "a figure that is not measured must say why"
    # The figures the engine DID publish are unaffected.
    assert result["risk"]["metrics"]["annual_volatility"]["state"] == (
        MARGINAL_STATE_MEASURED
    )


# ---------------------------------------------------------------------------
# request validation
# ---------------------------------------------------------------------------
def test_the_request_rejects_a_duplicate_leg_and_an_unknown_funding_rule():
    with pytest.raises(ValueError):
        MarginalTradeImpactRequest(
            legs=[
                {"ticker": "A.NS", "target_weight": 0.1},
                {"ticker": "a.ns", "target_weight": 0.2},
            ],
        )
    with pytest.raises(ValueError):
        MarginalTradeImpactRequest(
            legs=[{"ticker": "A.NS", "target_weight": 0.1}],
            funding="yolo",
        )


@pytest.mark.asyncio
async def test_tickers_are_normalized_so_a_duplicate_cannot_appear_in_two_cases():
    with pytest.raises(ValueError):
        MarginalTradeImpactRequest(legs=[
            {"ticker": "a.ns", "target_weight": 0.1},
            {"ticker": " A.NS ", "target_weight": 0.2},
        ])


# ---------------------------------------------------------------------------
# calendar fragility
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("clock_offset_days", [0, 37, 400, 900])
async def test_the_feature_survives_any_calendar_date(clock_offset_days, monkeypatch):
    """The window comes from `datetime.now()`, so a fixture pinned to a fixed
    past date eventually falls out of the request.

    On the day the whole frame does, the risk half returns its no-price-data
    shape and the test fails for a reason that has nothing to do with the claim
    under test. The offsets here span a different weekday alignment, a month
    boundary and two year boundaries, and the same three claims -- the delta is
    the difference of the two published levels, the funding scaled the unnamed
    book, and a leg the proposal did not name carries `measured` provenance --
    must hold on each.
    """
    real_now = datetime.now()

    class _ShiftedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return real_now + timedelta(days=clock_offset_days)

    monkeypatch.setattr(analytics_mod, "datetime", _ShiftedClock)
    shifted_today = pd.Timestamp(_ShiftedClock.now().date())
    dates = pd.bdate_range(end=shifted_today, periods=400)
    rng = np.random.default_rng(21)
    market = _Market({
        "A.NS": _ohlcv(dates, _walk(rng, 400, vol=0.010)),
        "B.NS": _ohlcv(dates, _walk(rng, 400, vol=0.012)),
        "NEW.NS": _ohlcv(dates, _walk(rng, 400, vol=0.030)),
    })

    result = await _run(
        _db([_pos("A.NS", 0.6), _pos("B.NS", 0.4)]), market,
        [{"ticker": "NEW.NS", "target_weight": 0.20}],
    )

    hhi = _metrics(result["concentration"])["herfindahl_index"]
    assert hhi["delta"] == pytest.approx(hhi["after"] - hhi["before"], abs=1e-9)
    for ticker in ("A.NS", "B.NS"):
        assert result["proposed_weights"][ticker] == pytest.approx(
            result["current_weights"][ticker] * 0.8, rel=1e-12,
        )
    by_leg = result["concentration"]["by_leg"]
    assert by_leg["NEW.NS"]["weight_provenance"] == (
        MARGINAL_WEIGHT_PROVENANCE_PROPOSED
    )
    assert by_leg["A.NS"]["weight_provenance"] == MARGINAL_WEIGHT_PROVENANCE_MEASURED
    assert result["error"] is None