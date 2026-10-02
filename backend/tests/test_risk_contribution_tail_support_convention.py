"""`risk_contribution`'s `tail_support` adopts the engine's declared convention.

THE RESIDUAL.  `tail_support` published `effective_n_formula` beside a
hand-rounded `ar1` (6 decimals) and `effective_n` (4 decimals), declaring NEITHER
count.  The same section's `autocorrelation` block - the window-level figure, on
the same object, published beside it - went through the engine's
`autocorrelation_disclosure`, which publishes `ar1_decimals`,
`effective_n_decimals` and a `recomputation_deviation` inside a declared bound.
So one object carried the same formula at a declared precision on one side and an
undeclared one on the other, and a reader checking the formula against the
published digits could not know which rounding they were entitled to.

WHAT THE ENGINE'S CONVENTION EXCLUDES, read from its implementation rather than
guessed: `autocorrelation_disclosure(observations)` takes the OBSERVATIONS and
derives `n` itself, so a caller that supplies its own population cannot call it.
`risk_contribution`'s entire point is a TAIL `n` the section's own
`port_ret <= var_95` mask produced, so this block is outside the function.

WHAT WAS ADOPTED ANYWAY, and why the exclusion does not bite: the convention is
the two declared decimal counts and the reproducibility bound, and
`effective_n_reproducibility_bound(observations, published_ar1)` is a function of
PUBLISHED inputs only.  Both are reusable unchanged.  The route now rounds with
the engine's own constants rather than a literal, so the three blocks that
publish this formula - the window `autocorrelation`, this one, and each
estimate's own `effective_n` - cannot drift apart.

THE LOAD-BEARING DETAIL.  `effective_n` here is CAPPED at the tail count, and
the cap is a step applied AFTER the formula.  Folding it into the reproducibility
record would report a residual that the declared rounding bound does not and
should not cover, and would read as a defect that is really a declared step.  So
the record describes `effective_n_uncapped` - the figure the formula itself
produces - and `effective_n_cap_applied` says whether the cap bound.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.api.analytics import _risk_contribution_tail_uncertainty
from app.services.analytics_engine import (
    AUTOCORRELATION_AR1_DECIMALS,
    AUTOCORRELATION_EFFECTIVE_N_DECIMALS,
    UNCERTAINTY_BOOTSTRAP_RESAMPLES,
    UNCERTAINTY_CONFIDENCE_LEVEL,
    ar1_autocorrelation,
    autocorrelation_disclosure,
    effective_n_reproducibility_bound,
    effective_sample_size,
)

TEST_RESAMPLES = 120

#: The clearance these fixtures are held to, in calendar days.  Three tests in
#: this project have broken on hard-dated fixtures; the frames below are
#: stamped relative to today and `_clearance` asserts each one is recent
#: enough - which means within `RECENT_DAYS` of today - so nothing here
#: depends on a literal date.  This is the bound the guard actually uses.
RECENT_DAYS = 21
WINDOW = 300


def _cleared(frame_end: date, today: date) -> bool:
    """Whether a frame ending `frame_end` is recent enough as of `today`.

    PURE, and it takes both dates, so the rule can be exercised against
    representative days - a weekday, a Saturday, a Sunday, a weekday market
    holiday, a stale frame - without freezing the clock, without a date
    parameter on `_clearance`, and without a new dependency.  The rule is the
    one this module's header claims: the frame's last observation must fall
    within `RECENT_DAYS` of today.

    WHAT THIS REPLACED, because the difference is the whole defect.  The guard
    used to compute its reach against `pd.bdate_range(..., periods=1)[0]` -
    the LAST BUSINESS DAY at or before today - and assert `reach <= 0`.  That
    expression says nothing about this fixture.  It says `today is a business
    day`, so it went red on every Saturday (reach 1), every Sunday (reach 2)
    and every market holiday, putting fourteen tests here red on a Saturday
    with a message blaming a clock that had not moved at all.  `RECENT_DAYS`
    was declared in this module and referenced nowhere; this is what it was
    declared for.
    """
    return (today - frame_end).days <= RECENT_DAYS


def _index(n: int = WINDOW) -> pd.DatetimeIndex:
    """The fixture's index, stamped from the clock rather than written down.

    The single source of the frame's last observation: `_clearance` checks the
    very index its callers will get, not a separately re-derived one.
    """
    return pd.bdate_range(end=datetime.now().date(), periods=n)


def _clearance() -> None:
    """The frame is stamped from the clock; assert it is still recent enough.

    The guard for the module header's warning about hard-dated fixtures: if a
    frame stops being stamped relative to today, this says so HERE, rather than
    letting the assertions further down quietly run against stale data.  Its
    rule is `_cleared`, i.e. `RECENT_DAYS`; its own verdict does not depend on
    what day of the week the suite is run on.
    """
    frame_end = _index()[-1].date()
    today = datetime.now().date()
    assert _cleared(frame_end, today), (
        f"the fixture's last observation ends {(today - frame_end).days} days "
        f"before today, past the {RECENT_DAYS}-day clearance it is stamped "
        f"against, so it no longer models a recent book"
    )


def _series(seed: int = 5, n: int = WINDOW) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0004, 0.011, n), index=_index(n))


def _block(seed: int = 5, n: int = WINDOW):
    """The real builder, on a real series, with the real tail mask."""
    _clearance()
    series = _series(seed=seed, n=n)
    var_95 = float(np.percentile(series.to_numpy(), 5))
    mask = series <= var_95
    published = {
        "portfolio_var_95_daily": var_95,
        "portfolio_cvar_95_daily": float(series[mask].mean()),
    }
    return (
        _risk_contribution_tail_uncertainty(
            series, var_95=var_95, tail_mask=mask, published=published,
            scope="risk_contribution (test)",
        ),
        series,
        mask,
        published,
    )


class TestTailSupportDeclaresItsPrecision:
    def test_it_publishes_the_two_decimal_counts_it_actually_uses(self):
        """The whole defect: the same formula at two precisions, one undeclared."""
        support = _block()[0]["tail_support"]
        assert support["ar1_decimals"] == AUTOCORRELATION_AR1_DECIMALS
        assert support["effective_n_decimals"] == AUTOCORRELATION_EFFECTIVE_N_DECIMALS
        assert support["ar1_basis"], "a declared count with no basis is half a fix"

    def test_the_engine_window_block_declares_the_same_two(self):
        """One convention across the object that publishes both figures.

        The window-level `autocorrelation` block is the engine's own, and it is
        the reference this block has to agree with.  Asserting both against the
        same two constants is what makes "one convention" a fact rather than an
        intention.
        """
        block = _block()[0]
        window = block["autocorrelation"]
        support = block["tail_support"]
        assert window["ar1_decimals"] == support["ar1_decimals"]
        assert window["effective_n_decimals"] == support["effective_n_decimals"]
        assert window["effective_n_formula"] == support["effective_n_formula"]

    def test_each_estimate_entry_declares_it_too(self):
        """Three blocks publish this formula; all three now declare the count."""
        block = _block()[0]
        for field, entry in block["estimates"].items():
            assert entry["effective_n_decimals"] == (
                AUTOCORRELATION_EFFECTIVE_N_DECIMALS
            ), field
            assert entry["effective_n"] is not None, field
            # and the entry's own figure is the TAIL one, as before
            assert entry["support_scope"] == support_scope()

    def test_the_published_digits_are_the_declared_rounding(self):
        """Recomputed here, so the declaration is checked against the numbers.

        Asserted against the RAW inputs rather than against a literal: a
        declaration that says 4 decimals while publishing 6 would otherwise pass
        a test that only compared the two to each other.
        """
        block, series, mask, _published = _block()
        support = block["tail_support"]
        raw = series.to_numpy(dtype=float)[mask.to_numpy()]
        assert support["tail_observations"] == int(raw.size)
        raw_ar1 = ar1_autocorrelation(raw)
        assert raw_ar1 is not None
        assert support["ar1"] == round(
            raw_ar1, AUTOCORRELATION_AR1_DECIMALS
        )
        assert len(str(support["ar1"]).split(".")[-1]) <= (
            AUTOCORRELATION_AR1_DECIMALS
        )
        raw_effective = effective_sample_size(int(raw.size), raw_ar1)
        assert support["effective_n_uncapped"] == round(
            raw_effective, AUTOCORRELATION_EFFECTIVE_N_DECIMALS
        )
        # ...and the CAP is the tail count, applied after the formula
        assert support["effective_n"] == min(
            support["effective_n_uncapped"], float(raw.size)
        )

    def test_the_decimals_are_the_engine_currently_declares(self):
        """The coupling is to the engine, so a change there is visible here.

        The route now ROUNDS with the engine's constants rather than a literal
        6 and 4, which is the point of adopting the convention - and it means a
        change in `analytics_engine.py` moves these digits.  This assertion is
        what makes that a visible event rather than a silent one, and it is
        deliberately stated as a value rather than as an identity.
        """
        assert (AUTOCORRELATION_AR1_DECIMALS, AUTOCORRELATION_EFFECTIVE_N_DECIMALS) == (
            6, 4
        ), (
            "the engine's declared precisions moved. This block rounds with them, "
            "so its published digits moved with them; the recorded measurement "
            "and the tests that pin the digits need re-reading, not just a re-run"
        )


class TestTheReproducibilityRecord:
    def test_it_uses_the_engines_own_key_names(self):
        """Compared against the engine's OUTPUT, so a rename there is caught.

        Not a hand-written list of key names: the engine's block is built here
        and the two key sets are required to match, so this cannot drift from
        the convention it claims to follow.
        """
        reference = autocorrelation_disclosure(
            _series().to_numpy()[:, None]
        )["effective_n_reproducibility"]
        record = _block()[0]["tail_support"]["effective_n_reproducibility"]
        shared = {
            "recomputes_from_published_ar1",
            "recomputation_deviation",
            "recomputation_deviation_bound",
            "bound_basis",
        }
        assert shared <= set(reference), sorted(set(reference))
        assert shared <= set(record), sorted(record)
        assert record["bound_basis"] == reference["bound_basis"], (
            "the bound's basis text is the engine's own and must not be reworded "
            "here, or a reader comparing the two blocks sees two conventions"
        )

    def test_the_bound_is_the_engines_own_function_of_published_inputs(self):
        """Recomputed here from `n` and the PUBLISHED ar1, as a reader would."""
        support = _block()[0]["tail_support"]
        record = support["effective_n_reproducibility"]
        assert record["recomputation_deviation_bound"] == (
            effective_n_reproducibility_bound(
                support["tail_observations"], support["ar1"]
            )
        )

    def test_the_deviation_is_measured_not_asserted(self):
        """Recomputed from the published ar1 and n, exactly as the engine does."""
        support = _block()[0]["tail_support"]
        record = support["effective_n_reproducibility"]
        if record["reason"] is not None:
            pytest.skip("this tail published no ar1, so there is nothing to check")
        recomputed = effective_sample_size(
            support["tail_observations"], support["ar1"]
        )
        deviation = abs(recomputed - support["effective_n_uncapped"])
        assert record["recomputation_deviation"] == pytest.approx(deviation)
        assert record["recomputes_from_published_ar1"] is bool(deviation == 0.0)

    def test_the_deviation_lands_inside_the_declared_bound(self):
        """The property the record exists to state, and it is a real assertion.

        Not a tautology: the bound is derived from `n`, the published `ar1` and
        the two declared decimals, while the deviation depends on how far the
        UNROUNDED ar1 sits from the published one.  A tail where that gap
        exceeded the bound would fail here.
        """
        support = _block()[0]["tail_support"]
        record = support["effective_n_reproducibility"]
        if record["reason"] is not None:
            pytest.skip("this tail published no ar1")
        assert record["recomputation_deviation"] <= (
            record["recomputation_deviation_bound"]
        )
        assert record["within_declared_bound"] is True

    def test_it_describes_the_uncapped_figure_not_the_capped_one(self):
        """The cap is a separate declared step, and folding it in is a defect.

        When the cap binds, the residual between a recomputation and the
        published `effective_n` is the CAP rather than rounding, and a rounding
        bound does not cover it.  Reporting it against the capped figure would
        produce a `within_declared_bound: false` that is true arithmetic and a
        false alarm.
        """
        support = _block()[0]["tail_support"]
        record = support["effective_n_reproducibility"]
        assert record["describes"] == "effective_n_uncapped"
        assert "effective_n_uncapped" in support["effective_n_cap_basis"]
        assert "AFTER the formula" in support["effective_n_cap_basis"]
        # the cap is stated, and it is a boolean or null rather than implied
        assert "effective_n_cap_applied" in support
        expected = (
            None if support["effective_n"] is None
            else bool(
                support["effective_n"] < support["effective_n_uncapped"]
            )
        )
        assert support["effective_n_cap_applied"] is expected, support

    def test_a_too_short_tail_reports_an_absence_rather_than_a_zero(self):
        """Never fabricate: no ar1 means no deviation, and it says so."""
        block = _risk_contribution_tail_uncertainty(
            _series(seed=9, n=40), var_95=0.0,
            tail_mask=pd.Series(np.zeros(40, dtype=bool)),
            published={"portfolio_var_95_daily": 0.0,
                       "portfolio_cvar_95_daily": None},
            scope="risk_contribution (test)",
        )
        record = block["tail_support"]["effective_n_reproducibility"]
        assert record["recomputation_deviation"] is None
        assert record["recomputation_deviation_bound"] is None
        assert record["within_declared_bound"] is None
        assert record["recomputes_from_published_ar1"] is None
        assert record["reason"], "a null deviation with no reason is a silent one"
        # the declared counts are still published - the block knows its precision
        assert block["tail_support"]["effective_n_decimals"] == (
            AUTOCORRELATION_EFFECTIVE_N_DECIMALS
        )

    def test_it_states_the_scope_exclusion_rather_than_leaving_it_implied(self):
        """A reader has to be able to see why the function was not called."""
        support = _block()[0]["tail_support"]
        assert "autocorrelation_disclosure" in support["effective_n_convention"]
        assert "cannot be called" in support["effective_n_convention"]
        assert "TAIL" in support["effective_n_convention"]


class TestNothingTheChangeMoved:
    def test_the_two_published_figures_are_unchanged_by_the_adoption(self):
        """The digits are pinned, because the rounding now reads the engine.

        A literal 6 and 4 replaced by the engine's constants publish the same
        numbers today.  If the engine's declared precisions ever move, these
        assertions fail and the change to the payload is a deliberate, visible
        event rather than a diff nobody reads.
        """
        support = _block()[0]["tail_support"]
        # what the hand-rounded version published: 6 dp on ar1, 4 dp on effective_n
        assert support["ar1"] == round(support["ar1"], 6)
        assert support["effective_n"] == round(support["effective_n"], 4)
        assert support["effective_n_uncapped"] == round(
            support["effective_n_uncapped"], 4
        )
        # and the window-side figure this block points at is untouched
        assert support["window_effective_n"] == _block()[0][
            "autocorrelation"
        ]["effective_n"]

    def test_the_tail_populations_are_unchanged(self):
        """The block still measures the TAIL and still names both populations."""
        block, series, mask, _published = _block()
        support = block["tail_support"]
        assert support["tail_observations"] == int(mask.to_numpy().sum())
        assert support["window_observations"] == int(series.size)
        assert support["scope"] == support_scope()
        for field, entry in block["estimates"].items():
            assert entry["effective_n"] == support["effective_n"], field
            assert entry["effective_n_uncapped"] == (
                support["effective_n_uncapped"]
            ), field
            assert entry["support_observations"] == support["tail_observations"]
            assert entry["effective_n_basis"], field

    def test_the_engine_draw_count_and_level_are_not_hard_coded_here(self):
        """This block does not resample; it must not claim a draw count of its own."""
        block = _block()[0]
        support = block["tail_support"]
        # no draw count is invented on the tail block
        assert not any("bootstrap_resamples" in key for key in support), support
        assert block["confidence_level"] == UNCERTAINTY_CONFIDENCE_LEVEL
        assert block["bootstrap_resamples"] == UNCERTAINTY_BOOTSTRAP_RESAMPLES


def support_scope() -> str:
    from app.api.analytics import RISK_CONTRIBUTION_TAIL_SUPPORT_SCOPE

    return RISK_CONTRIBUTION_TAIL_SUPPORT_SCOPE


# ---------------------------------------------------------------------------
# the clearance guard.  It shipped asserting the wrong thing and turned the
# whole file red every weekend, so its rule is pinned here in BOTH
# directions: what it must accept (weekends, holidays) and what it must still
# reject (a frame that stopped being recent).
# ---------------------------------------------------------------------------
def _pinned(moment: datetime) -> type:
    """A `datetime` stand-in whose `now()` is `moment`, for one `with` only.

    This is the whole clock override in this module: scoped to a single test,
    restored on exit by `mock.patch`, and never installed globally.  The
    alternative - a freezegun-style dependency - is not permitted here, and
    freezing time for the suite would be worse than not testing the guard.
    """
    return type(
        "_Pinned", (datetime,),
        {"now": classmethod(lambda _cls, _tz=None: moment)},
    )


class TestTheClearanceGuard:
    def test_the_rule_it_replaced_was_only_ever_a_business_day_assertion(self):
        """THE RED PROOF: what the old guard actually computed.

        The old body, reproduced verbatim and run over the measured table.  Its
        reach is measured against the last business day at or before today, so
        `reach <= 0` reduces to `weekday < 5` - which is why fourteen tests
        here went red every Saturday and Sunday with a message about a clock
        that had not moved.  The table is asserted in full, so this is a check
        rather than a restatement: a wrong transcription fails it.
        """
        def superseded_reach(day: date) -> int:
            return (day - pd.bdate_range(
                end=pd.Timestamp(day), periods=1
            )[0].date()).days

        measured = {
            date(2026, 10, 1): 0,   # Thursday
            date(2026, 10, 2): 0,   # Friday
            date(2026, 10, 3): 1,   # Saturday - the whole defect
            date(2026, 10, 4): 2,   # Sunday
            date(2026, 10, 5): 0,   # Monday
        }
        for day, reach in measured.items():
            assert superseded_reach(day) == reach, (day, day.strftime("%A"))
            # and the old verdict is EXACTLY the weekday: nothing about the
            # fixture, the window, or RECENT_DAYS enters into it
            assert (reach <= 0) is (day.weekday() < 5), (day, day.strftime("%A"))

        # the fixed rule disagrees on the two weekend rows and agrees elsewhere
        frame_end = date(2026, 10, 2)   # the frame stamped on that Friday
        for day in measured:
            assert _cleared(frame_end, day) is True, (day, day.strftime("%A"))

    def test_the_rule_clears_a_weekend_regardless_of_the_day_it_is_run(self):
        """FIX PROOF: weekday-independence across representative dates.

        One frame, stamped on a Thursday, read on each later day.  The weekend
        rows are the ones the old guard rejected; the point is that they now
        pass for the stated reason - within `RECENT_DAYS` of today - and that
        no row depends on what day of the week the suite happens to run.
        """
        frame_end = pd.bdate_range(
            end=date(2026, 10, 1), periods=1
        )[0].date()
        for day, verdict in (
            (date(2026, 10, 1), True),   # Thursday, the day it was stamped
            (date(2026, 10, 2), True),   # Friday
            (date(2026, 10, 3), True),   # Saturday
            (date(2026, 10, 4), True),   # Sunday
            (date(2026, 10, 5), True),   # Monday
        ):
            assert _cleared(frame_end, day) is verdict, (day, day.strftime("%A"))

    def test_a_genuinely_stale_frame_is_still_rejected(self):
        """STILL FAILS: the fix must not have made the check vacuous.

        The defect inverted - a guard that passes anything - would be the same
        bug the other way round.  So the boundary is asserted from both sides:
        exactly `RECENT_DAYS` old clears, one day more does not.
        """
        frame_end = pd.bdate_range(
            end=date(2026, 10, 1), periods=1
        )[0].date()
        assert _cleared(frame_end, frame_end + timedelta(days=RECENT_DAYS))
        assert not _cleared(
            frame_end, frame_end + timedelta(days=RECENT_DAYS + 1)
        )
        # and a frame from last year is nowhere near the clearance
        assert not _cleared(frame_end, date(2027, 10, 1))

    def test_market_holidays_are_ordinary_weekdays_to_this_index(self):
        """Market holidays explicitly, since the old guard died on them too.

        `pd.bdate_range` skips Saturday and Sunday and knows nothing about
        exchange holidays, so on a weekday the frame is stamped to that very
        day - Christmas, Diwali, a national closure - and the guard reads a
        reach of 0.  Swept across a full year, EVERY day clears, and the worst
        reach any day can produce is 2: a Sunday.  That margin is why a single
        market holiday cannot turn this file red, and why neither can a run that
        straddles one.
        """
        days = pd.date_range("2026-01-01", "2026-12-31", freq="D").date
        worst = 0
        for day in days:
            frame_end = pd.bdate_range(
                end=pd.Timestamp(day), periods=1
            )[0].date()
            assert _cleared(frame_end, day), (day, day.strftime("%A"))
            worst = max(worst, (day - frame_end).days)
        assert worst == 2, worst
        assert worst < RECENT_DAYS

    def test_the_shipped_guard_itself_survives_a_weekend_clock(self):
        """`_clearance` end to end with the clock pinned to each of those days.

        The pure rule is tested above; this proves the guard that actually
        runs in the other fourteen tests reaches the same verdict, so the rule
        and the call site cannot drift apart.
        """
        for moment in (
            datetime(2026, 10, 1, 12, 0),   # Thursday
            datetime(2026, 10, 2, 12, 0),   # Friday
            datetime(2026, 10, 3, 12, 0),   # Saturday
            datetime(2026, 10, 4, 12, 0),   # Sunday
            datetime(2026, 10, 5, 12, 0),   # Monday
            datetime(2026, 12, 25, 12, 0),  # Christmas, a weekday
        ):
            with patch(f"{__name__}.datetime", _pinned(moment)):
                _clearance()

    def test_the_shipped_guard_rejects_a_hard_dated_frame(self):
        """The negative half of the previous test, on the real guard.

        A pinned clock CANNOT stage this: `_index` stamps from the same clock
        it reads, so moving the clock moves both ends and `reach` stays 0.  The
        only way this fixture goes stale is the failure the module header names
        - someone replaces `end=datetime.now().date()` with a literal - so that
        is what is staged here, with `_index` patched to a frame from last year
        and the clock left alone.  The guard must refuse it, loudly, by name.
        """
        stale = pd.bdate_range(
            end=datetime.now().date() - timedelta(days=365), periods=WINDOW
        )
        with patch(f"{__name__}._index", return_value=stale):
            with pytest.raises(AssertionError, match="clearance"):
                _clearance()


# ---------------------------------------------------------------------------
# the section-level route, so this is not a unit test of a helper
# ---------------------------------------------------------------------------
class TestThroughTheRoute:
    @pytest.mark.asyncio
    async def test_a_real_risk_contribution_publishes_the_convention(self):
        """`get_risk_contribution` end to end on a clock-stamped three-leg book."""
        from app.api.analytics import get_risk_contribution
        from app.models.database import PortfolioPosition

        _clearance()
        dates = pd.bdate_range(
            end=pd.Timestamp.now().normalize(), periods=MODEL_OBS + 1
        )
        frames = {}
        for index, ticker in enumerate(("A.NS", "B.NS", "C.NS")):
            rng = np.random.default_rng(20 + index)
            frames[ticker] = pd.DataFrame(
                {"adj_close": pd.Series(
                    100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.011, len(dates)))),
                    index=dates,
                )},
                index=dates,
            )
        positions = [
            PortfolioPosition(
                id=1, ticker=t, weight=1 / 3, quantity=10.0, buy_price=None,
                last_price=100.0, market_value=10000.0, region="IN",
                sector="Tech", industry="Y",
                added_on=pd.Timestamp.now().normalize()
                - pd.Timedelta(days=RECENT_DAYS + 30),
            )
            for t in frames
        ]

        def _rows(rows):
            scalars = MagicMock()
            scalars.all.return_value = list(rows)
            result = MagicMock()
            result.scalars.return_value = scalars
            return result

        db = AsyncMock()
        db.execute = AsyncMock(side_effect=lambda *a, **k: _rows(positions))

        class _Market:
            def __init__(self, f):
                self.frames = f
                self.fetch_historical_data = AsyncMock(side_effect=self._fetch)

            async def _fetch(self, ticker, _start, _end):
                frame = self.frames.get(ticker)
                return pd.DataFrame() if frame is None else frame.copy()

        result = await get_risk_contribution(
            tickers="A.NS,B.NS,C.NS", db=db, data_service=_Market(frames),
        )
        block = result["estimate_uncertainty"]
        support = block["tail_support"]
        assert support["ar1_decimals"] == AUTOCORRELATION_AR1_DECIMALS
        assert support["effective_n_decimals"] == AUTOCORRELATION_EFFECTIVE_N_DECIMALS
        assert support["effective_n_convention"]
        record = support["effective_n_reproducibility"]
        if record["reason"] is None:
            assert record["recomputation_deviation"] <= (
                record["recomputation_deviation_bound"]
            )
        # the block-level autocorrelation figure is still the window one
        assert support["window_effective_n"] == block["autocorrelation"][
            "effective_n"
        ]
        assert support["window_observations"] > support["tail_observations"]


MODEL_OBS = 300
