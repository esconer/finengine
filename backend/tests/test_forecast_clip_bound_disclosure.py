"""A 95% band whose upper end IS the clip bound has to say so in a number.

THE DEFECT.  `volatility_forecast_point` publishes a CLIPPED annualized
volatility - `np.clip(raw, clip_low, FORECAST_VOL_CLIP_HIGH)` - and the route
forwarded only the clipped side.  A reader looking at a published interval whose
far end reads 1.20 could not tell a data-driven 97.5th percentile from the clip
bound itself, and could not tell how far a clipped point had moved.

WHAT ALREADY EXISTED AND IS NOT REBUILT HERE.  Every leg's
`precision.derived_values['positions.<T>.var_forecast']` already carries
`derivation_precondition`, `derivation_precondition_met` and
`derivation_precondition_evidence`, whose evidence string reads
`"annualized_volatility_at_clip_bound is False: the published leg volatility is
... against bounds [0.05, 1.2]"`.  That is a BOOLEAN about the POINT.  What was
missing is any statement about the BAND, and the MAGNITUDE the clip removed.

WHY THERE IS NO THRESHOLD, restated rather than re-derived, because the absence
is the finding: on 5,185 real EGARCH(1,1) fits thirty candidate discriminators
were scored and 30 of 30 are non-separable (`.scratch/v5-review/
13-overflow-discriminator.md` §2).  The best principled predicate wrongly refuses
6.0 % of genuine forecasts while missing 21.3 % of divergences, and the four
quantities that separate in-sample hold out at a coin flip.  For any beta < 1 the
EGARCH conditional variance is lognormal with finite expectation, so no parameter
set makes the model assert a nonexistent forecast and beta -> 1 asserts an
arbitrarily large one continuously.  `TestNoThresholdIsPublished` pins that the
fix is disclosure and not detection.

WHAT IS ASSERTED HERE, AND WHY A COUNT ALONE IS NOT ENOUGH.  The headline case
this file exists for is a band that lands ON the bound.  A test that only checked
the count would pass on a payload that counted correctly and still left a reader
unable to tell a clipped band from an unclipped one, so
`TestABandOnTheBoundIsDistinguishableInThePayload` asserts the payload's own
flag, not just the number behind it.  `TestAnUnmeasuredCountIsNullNotZero`
asserts the other half: a leg whose restatements were never taken must not be
able to say 0.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_api
from app.api.analytics import (
    _clip_restatement_record,
    _forecast_volatility_clip_block,
    get_forecast_risk,
)
from app.services.analytics_engine import (
    FORECAST_VOL_CLIP_HIGH,
    FORECAST_VOL_CLIP_LOW,
    UNCERTAINTY_MIN_OBSERVATIONS,
    AnalyticsEngine,
)

#: A short draw count, so the suite is not dominated by optimiser runs.  The COUNT
#: is not what this file is about; the disclosure is.  The block publishes
#: whichever count it was given, so a reduced count is visible rather than silent.
TEST_RESAMPLES = 60

TICKERS = ("AAA.NS", "BBB.NS", "CCC.NS")
OBSERVATIONS = 60

#: The key set `positions.<ticker>` carried BEFORE this disclosure existed.  The
#: fix adds keys under `precision` and under each leg block's `notes`; it must not
#: add, remove or rename anything on the published leg.
PRE_EXISTING_LEG_KEYS = {
    "volatility_forecast", "var_forecast", "is_limited_history",
    "history_warning", "data_points", "return_observations",
}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _prices(*, seed: int = 3, tickers=TICKERS, observations: int = OBSERVATIONS):
    """A book of geometric walks, dated to END ON THE CLOCK.

    The route derives its own window from `datetime.now()`, so a hard-dated
    fixture here would be a second, unrelated source of calendar truth.  The
    prices are stamped relative to today and the assertions below check the
    clearance as a precondition, which is what keeps this file from breaking the
    way three hard-dated fixtures in this project already have.
    """
    end = pd.Timestamp(datetime.now().date())
    dates = pd.bdate_range(end=end, periods=observations)
    rng = np.random.default_rng(seed)
    out = {}
    for index, _ticker in enumerate(tickers):
        walk = np.cumsum(rng.normal(0.0003, 0.010, observations))
        out[_ticker] = pd.Series(100.0 * np.exp(walk), index=dates)
    return out


def _clearance(observations: int = OBSERVATIONS) -> None:
    """How far back the fixture reaches, asserted as a precondition on the clock.

    This file's only calendar-derived assertion is that the fixture is recent
    enough for the route's history gate, and a fixture that stops being recent
    enough should say so HERE instead of failing somewhere further down.  Three
    tests in this project have broken on hard-dated fixtures; this is the shape
    that does not.
    """
    reach = (datetime.now() - datetime.combine(
        _prices(observations=observations)[TICKERS[0]].index[-1].date(),
        datetime.min.time(),
    ))
    assert reach <= timedelta(days=30), (
        f"the price fixture ends {reach.days} days before today, so it no "
        f"longer clears a history gate that assumes a recent book"
    )


async def _payload(*, engine: Any = None, tickers=TICKERS) -> dict:
    """`get_forecast_risk` called the way the route is called, on a real engine."""
    _clearance()
    series = _prices(tickers=tickers)

    async def allocation(_tickers, _db):
        return list(tickers), {t: 1.0 / len(tickers) for t in tickers}

    engine = engine or AnalyticsEngine()
    with patch("app.api.analytics.resolve_allocation", side_effect=allocation), \
         patch("app.api.analytics._fetch_price_series_dict",
               new=AsyncMock(return_value=series)):
        return await get_forecast_risk(
            model="GARCH", horizon=1, tickers=",".join(tickers),
            start=series[tickers[0]].index[0].date(),
            end=series[tickers[0]].index[-1].date(),
            db=Mock(), data_service=Mock(), analytics_engine=engine,
        )


@pytest.fixture
def fast_resamples(monkeypatch):
    monkeypatch.setattr(
        analytics_api, "FORECAST_PORTFOLIO_REFIT_RESAMPLES", TEST_RESAMPLES
    )


def _clip(data: dict) -> dict:
    node = data["precision"]["volatility_clip"]
    assert node is not None, "this section published no volatility_clip node"
    return node


# ---------------------------------------------------------------------------
# 1. the count, and the denominator it is a fraction of
# ---------------------------------------------------------------------------
class TestTheCountCarriesItsDenominator:
    @pytest.mark.asyncio
    async def test_the_block_publishes_a_count_and_the_population_it_is_of(
        self, fast_resamples
    ):
        """The count alone is unreadable: 3 of what?

        The denominator has to name its population, because "restatements" means
        two different things on this section - the draws requested, and the draws
        that came back finite.  They differ whenever a refit fails, and the failed
        ones are counted rather than dropped, so the two populations are not the
        same set.
        """
        data = await _payload()
        portfolio = _clip(data)["restatements"]["portfolio"]

        assert portfolio["status"] == "measured", portfolio
        assert isinstance(portfolio["at_clip_bound"], int), portfolio
        assert isinstance(portfolio["usable_restatements"], int), portfolio
        assert 0 <= portfolio["at_clip_bound"] <= portfolio["usable_restatements"]
        # and the denominator is the population the band itself was read off
        assert portfolio["usable_restatements"] == TEST_RESAMPLES, portfolio
        rule = _clip(data)["denominator_rule"]
        assert "USABLE RESTATEMENT" in rule
        assert "finite" in rule
        assert "usable_restatements" in rule

    @pytest.mark.asyncio
    async def test_a_zero_count_carries_its_share_and_no_reason(
        self, fast_resamples
    ):
        """0 is a real answer and must not read as an absence.

        On this fixture nothing is clipped, so `at_clip_bound` is 0,
        `share_of_usable_restatements` is 0.0 rather than null, and `reason` is
        null because nothing needs explaining.
        """
        portfolio = _clip(await _payload())["restatements"]["portfolio"]
        assert portfolio["at_clip_bound"] == 0, portfolio
        assert portfolio["share_of_usable_restatements"] == 0.0, portfolio
        assert portfolio["reason"] is None, portfolio
        assert portfolio["largest_removed_by_clip"] == 0.0, portfolio

    def test_the_share_is_the_count_over_the_named_denominator(self):
        """Recomputed here, so the ratio cannot be a second opinion."""
        record = _clip_restatement_record(
            status="measured", at_clip_bound=7, usable_restatements=200,
            largest_removed_by_clip=1.25,
        )
        assert record["share_of_usable_restatements"] == pytest.approx(0.035)
        # ...and a null denominator yields a null share, never a 0.0
        assert _clip_restatement_record(
            status="not_measured",
        )["share_of_usable_restatements"] is None

    @pytest.mark.asyncio
    async def test_each_leg_is_counted_on_its_own_population_not_a_pooled_one(
        self, fast_resamples
    ):
        """A single pooled total would be a different number and a worse one.

        Each leg is re-fitted on its OWN return series at its own draw count, so
        the legs' restatements are separate populations and are never added
        together here.  The scope key says so, and the two measured lists are the
        legs themselves rather than a count of legs.
        """
        data = await _payload()
        restatements = _clip(data)["restatements"]
        assert set(restatements["positions"]) == set(TICKERS), restatements
        assert "independently" in restatements["denominator_scope"]
        # this book's legs are all fitted, so every one of them is unmeasured
        assert restatements["legs_with_a_measured_count"] == []
        assert restatements["legs_whose_count_is_unmeasured"] == sorted(TICKERS)
        assert restatements["measured_leg_count"] == 0
        assert restatements["unmeasured_leg_count"] == len(TICKERS)


# ---------------------------------------------------------------------------
# 2. the case the whole disclosure exists for: a band that lands ON the bound
# ---------------------------------------------------------------------------
class TestABandOnTheBoundIsDistinguishableInThePayload:
    """A test that only counted correctly would not catch this.

    The defect is not a wrong number; it is an indistinguishable one.  So these
    assert the FLAG the payload carries, and that the flag is derived from the
    published interval rather than asserted beside it.
    """

    @staticmethod
    def _clipped_engine(at_bound: int):
        """The engine's own restatement, with `at_bound` of its draws clipped.

        A double around the real factory rather than a stand-in for it, because
        the block also runs a REPRODUCTION GUARD: it re-derives the point on the
        original sample and withholds the band if that does not match the
        published one.  A fabricated estimator that returned a made-up point
        would trip the guard, and the test would then be measuring the guard
        rather than the clip disclosure.

        So the guard's own call passes through untouched - the real point, so the
        real band survives - and only the draw set is altered: the last
        `at_bound` restatements publish the bound itself with a pre-clip value of
        1e12 behind them.  That is exactly the state 156 of 2,993 real
        restatements were in, and it costs no optimiser run to reproduce.

        The block is `(n, draws, k)` with the TIME axis first, so the draw count
        is axis 1 - the same fact the production observer has to get right.
        """
        import app.services.analytics_engine as engine_module

        original = engine_module.volatility_forecast_statistics

        def factory(model, horizon, fields=("volatility_forecast",)):
            wanted = tuple(dict.fromkeys((*fields, "raw_volatility_forecast")))
            inner = original(model, horizon, fields=wanted)

            def statistic(block):
                out = {k: np.array(v, dtype=float) for k, v in inner(block).items()}
                count = int(np.asarray(block).shape[1])
                # `at_bound` is guarded explicitly rather than left to
                # `out[-at_bound:]`, because `-0 == 0` would make the negative
                # slice the WHOLE array and the control case would clip
                # everything.
                if count > 1 and at_bound > 0:
                    raw = out.get("raw_volatility_forecast")
                    if raw is None:
                        raw = out["volatility_forecast"].copy()
                        out["raw_volatility_forecast"] = raw
                    out["volatility_forecast"][-at_bound:] = FORECAST_VOL_CLIP_HIGH
                    raw[-at_bound:] = 1e12
                return out
            return statistic
        return factory

    @pytest.mark.asyncio
    async def test_a_band_whose_far_end_is_the_bound_says_so(
        self, fast_resamples, monkeypatch
    ):
        monkeypatch.setattr(
            analytics_api, "volatility_forecast_statistics",
            self._clipped_engine(at_bound=3),
        )
        data = await _payload()
        portfolio = _clip(data)["restatements"]["portfolio"]

        assert portfolio["status"] == "measured", portfolio
        assert portfolio["at_clip_bound"] == 3, portfolio
        assert portfolio["usable_restatements"] == TEST_RESAMPLES, portfolio
        # the BAND statement, which the per-point evidence string cannot make
        assert portfolio["published_interval"][-1] == pytest.approx(
            FORECAST_VOL_CLIP_HIGH
        )
        assert portfolio["published_interval_at_clip_bound"] is True, portfolio
        # ...and the MAGNITUDE, so the three clipped draws are not three
        # indistinguishable 1.20s
        assert portfolio["largest_removed_by_clip"] == pytest.approx(1e12 - 1.20)

    @pytest.mark.asyncio
    async def test_a_band_whose_far_end_is_a_quantile_says_the_other_thing(
        self, fast_resamples, monkeypatch
    ):
        """The negative control, and the reason the first test means anything.

        Identical code, identical book, zero clipped draws: the same three keys
        now read 0, the far end is the data's own quantile, and the flag is
        False.  A payload that published the same words in both cases would pass
        a count-only test and tell a reader nothing.
        """
        monkeypatch.setattr(
            analytics_api, "volatility_forecast_statistics",
            self._clipped_engine(at_bound=0),
        )
        data = await _payload()
        portfolio = _clip(data)["restatements"]["portfolio"]

        assert portfolio["at_clip_bound"] == 0, portfolio
        assert portfolio["published_interval"][-1] < FORECAST_VOL_CLIP_HIGH, (
            f"the control is supposed to be an unclipped band, got "
            f"{portfolio['published_interval']}"
        )
        assert portfolio["published_interval_at_clip_bound"] is False, portfolio
        assert portfolio["largest_removed_by_clip"] == 0.0, portfolio

    def test_the_flag_is_derived_from_the_interval_not_asserted(self):
        """The record cannot claim a flag its own interval contradicts."""
        on = _clip_restatement_record(
            status="measured", at_clip_bound=4, usable_restatements=100,
            conf_int=[0.11, 0.44],
        )
        assert on["published_interval_at_clip_bound"] is False
        assert on["published_interval"] == [0.11, 0.44]
        touching = _clip_restatement_record(
            status="measured", at_clip_bound=4, usable_restatements=100,
            conf_int=[0.11, FORECAST_VOL_CLIP_HIGH],
        )
        assert touching["published_interval_at_clip_bound"] is True
        # a record with no interval states no verdict rather than defaulting False
        assert _clip_restatement_record(
            status="not_measured",
        )["published_interval_at_clip_bound"] is None


# ---------------------------------------------------------------------------
# 3. an unmeasured count is null, never 0
# ---------------------------------------------------------------------------
class TestAnUnmeasuredCountIsNullNotZero:
    @pytest.mark.asyncio
    async def test_a_fitted_leg_says_the_count_was_never_taken(
        self, fast_resamples
    ):
        """The fourteen legs of the real book, all of them.

        0 here would assert that the clip bound was tested on this leg and never
        bound it, which is the one claim this payload does not make: the
        re-fit estimator was declined for cost, so nothing was tested.
        """
        data = await _payload()
        restatements = _clip(data)["restatements"]
        for ticker in TICKERS:
            record = restatements["positions"][ticker]
            assert record["status"] == "not_measured", (ticker, record)
            assert record["at_clip_bound"] is None, (ticker, record)
            assert record["usable_restatements"] is None, (ticker, record)
            assert record["largest_removed_by_clip"] is None, (ticker, record)
            assert record["share_of_usable_restatements"] is None, (ticker, record)
            assert "not measured" in record["reason"], (ticker, record)

    @pytest.mark.asyncio
    async def test_a_limited_leg_counts_zero_because_no_clip_applies_to_it(
        self, monkeypatch
    ):
        """The other 0, and it is a different 0.

        A leg below the history gate has its forecast computed as its own sample
        standard deviation with no clip at all, so the restatements WERE taken and
        the bound was never in play.  That is `measured` with 0, not
        `not_measured` with null - and the reason says which.

        25 price rows is the window that reaches the limited branch and still
        clears the uncertainty module's own 20-observation floor, which is what
        makes the restatements exist at all on this leg.
        """
        series = _prices(tickers=("AAA.NS",), observations=25)

        async def allocation(_tickers, _db):
            return ["AAA.NS"], {"AAA.NS": 1.0}

        with patch("app.api.analytics.resolve_allocation", side_effect=allocation), \
             patch("app.api.analytics._fetch_price_series_dict",
                   new=AsyncMock(return_value=series)), \
             patch.object(analytics_api, "FORECAST_PORTFOLIO_REFIT_RESAMPLES",
                          TEST_RESAMPLES):
            limited = await get_forecast_risk(
                model="GARCH", horizon=1, tickers="AAA.NS",
                start=series["AAA.NS"].index[0].date(),
                end=series["AAA.NS"].index[-1].date(),
                db=Mock(), data_service=Mock(),
                analytics_engine=AnalyticsEngine(),
            )
        assert limited["positions"]["AAA.NS"]["is_limited_history"] is True
        block = limited["precision"]["estimated_statistics"]["positions"]["AAA.NS"]
        assert block["observations"] >= UNCERTAINTY_MIN_OBSERVATIONS, block
        record = _clip(limited)["restatements"]["positions"]["AAA.NS"]
        assert record["status"] == "measured", record
        assert record["at_clip_bound"] == 0, record
        assert 0 < record["usable_restatements"] <= block["bootstrap_resamples"], (
            record, block["bootstrap_resamples"]
        )
        assert record["largest_removed_by_clip"] == 0.0, record
        assert "clip bounds are not applied" in record["reason"], record

    @pytest.mark.asyncio
    async def test_a_leg_too_short_to_resample_is_not_a_measured_zero(self):
        """The fourth case, which is neither of the three above.

        The two gates on a leg are not the same gate: `position_limited_history`
        fires below 30 return observations, `UNCERTAINTY_MIN_OBSERVATIONS` is 20.
        A 20-price-row leg is therefore limited-history AND unresamplable, and
        its record must not be `measured` with a null denominator - that is a
        count of zero out of an unknown population, which asserts the restate-
        ments were counted when they were not.
        """
        series = _prices(tickers=("AAA.NS",), observations=20)

        async def allocation(_tickers, _db):
            return ["AAA.NS"], {"AAA.NS": 1.0}

        with patch("app.api.analytics.resolve_allocation", side_effect=allocation), \
             patch("app.api.analytics._fetch_price_series_dict",
                   new=AsyncMock(return_value=series)):
            data = await get_forecast_risk(
                model="GARCH", horizon=1, tickers="AAA.NS",
                start=series["AAA.NS"].index[0].date(),
                end=series["AAA.NS"].index[-1].date(),
                db=Mock(), data_service=Mock(),
                analytics_engine=AnalyticsEngine(),
            )
        leg = data["positions"]["AAA.NS"]
        assert leg["is_limited_history"] is True, leg
        block = data["precision"]["estimated_statistics"]["positions"]["AAA.NS"]
        assert block["observations"] < UNCERTAINTY_MIN_OBSERVATIONS, block
        record = _clip(data)["restatements"]["positions"]["AAA.NS"]
        assert record["status"] == "not_measured", record
        assert record["at_clip_bound"] is None, record
        assert record["usable_restatements"] is None, record
        assert record["largest_removed_by_clip"] is None, record
        assert "UNCERTAINTY_MIN_OBSERVATIONS" in record["reason"], record
        # the leg's own point is still published - this is an absence of a COUNT
        assert leg["volatility_forecast"] is not None, leg

    @pytest.mark.asyncio
    async def test_the_declined_leg_still_gets_a_free_and_true_count_of_zero(
        self, fast_resamples
    ):
        """Nothing on the leg was withheld because of the clip.

        The leg's own clip-bound count being an absence must not leak into the
        leg's real disclosure: the observation count, AR(1) and effective sample
        size are still measured and still published.
        """
        data = await _payload()
        block = data["precision"]["estimated_statistics"]["positions"][TICKERS[0]]
        assert block["estimator_withheld"], block
        assert block["observations"] > 0
        assert block["autocorrelation"]["effective_n"] is not None
        # and the reason the count is absent points at the cost decision
        record = _clip(data)["restatements"]["positions"][TICKERS[0]]
        assert "precision.measurements_withheld" in record["reason"]


# ---------------------------------------------------------------------------
# 4. the MAGNITUDE the clip removed, on the point as well as the band
# ---------------------------------------------------------------------------
class TestTheMagnitudeIsPublished:
    def test_a_clipped_point_is_distinguishable_from_a_genuine_one(self):
        """Two published 1.20s, and the payload has to tell them apart.

        The boolean already exists - `annualized_volatility_at_clip_bound` in
        each leg's `derivation_precondition_evidence`.  What a boolean cannot do
        is tell a fit that forecast 120 % from one that produced 1e12 and was
        collapsed onto the bound, so the raw and the distance are published.
        """
        node = _forecast_volatility_clip_block(
            model="EGARCH",
            forecast_result={
                "volatility_forecast": FORECAST_VOL_CLIP_HIGH,
                "raw_volatility_forecast": 1e12,
            },
            positions={
                "CLIPPED.NS": {
                    "volatility_forecast": FORECAST_VOL_CLIP_HIGH,
                    "is_limited_history": False,
                },
                "GENUINE.NS": {
                    "volatility_forecast": FORECAST_VOL_CLIP_HIGH,
                    "is_limited_history": False,
                },
            },
            estimated={"positions": {}},
            raw_volatility={"CLIPPED.NS": 1e12, "GENUINE.NS": 1.20},
        )
        clipped = node["point"]["positions"]["CLIPPED.NS"]
        genuine = node["point"]["positions"]["GENUINE.NS"]
        # identical published values, and the payload separates them
        assert clipped["published"] == genuine["published"]
        assert clipped["at_clip_bound"] is True
        assert clipped["clip_removed"] == pytest.approx(1e12 - 1.20)
        assert genuine["at_clip_bound"] is True
        assert genuine["clip_removed"] == 0.0
        assert clipped["raw_volatility_forecast"] != (
            genuine["raw_volatility_forecast"]
        )
        # and the legs that are on a bound are NAMED, not left for a scan
        assert node["point"]["at_clip_bound_positions"] == [
            "CLIPPED.NS", "GENUINE.NS",
        ]
        assert node["point"]["at_clip_bound_portfolio"] is True

    @pytest.mark.asyncio
    async def test_a_fitted_leg_publishes_its_pre_clip_value(self, fast_resamples):
        """The number the route used to drop entirely, now published.

        Checked against the ENGINE's own value, not restated: the route forwards
        `volatility_forecast` and `var_forecast` per leg and used to forward
        neither the raw nor the distance, so a leg reading exactly the bound was
        indistinguishable from a leg that genuinely forecast 120 %.
        """
        data = await _payload()
        for ticker in TICKERS:
            record = _clip(data)["point"]["positions"][ticker]
            assert record["at_clip_bound"] is False, (ticker, record)
            assert record["clip_removed"] == 0.0, (ticker, record)
            raw = record["raw_volatility_forecast"]
            assert isinstance(raw, float) and np.isfinite(raw), (ticker, record)
            assert raw == pytest.approx(
                data["positions"][ticker]["volatility_forecast"]
            ), (ticker, record)
        portfolio = _clip(data)["point"]["portfolio"]
        assert portfolio["clip_removed"] == 0.0, portfolio
        assert portfolio["raw_volatility_forecast"] == pytest.approx(
            data["portfolio"]["volatility_forecast"]
        )

    @pytest.mark.asyncio
    async def test_a_limited_leg_publishes_no_raw_rather_than_a_made_up_one(self):
        """A leg with no fitted model behind it has no pre-clip value.

        Publishing its own published value as the "raw" would be a fabricated
        input: it would make `clip_removed` a subtraction of a number from itself
        and imply a clip that was never applied.
        """
        series = _prices(tickers=("AAA.NS",), observations=25)

        async def allocation(_tickers, _db):
            return ["AAA.NS"], {"AAA.NS": 1.0}

        with patch("app.api.analytics.resolve_allocation", side_effect=allocation), \
             patch("app.api.analytics._fetch_price_series_dict",
                   new=AsyncMock(return_value=series)), \
             patch.object(analytics_api, "FORECAST_PORTFOLIO_REFIT_RESAMPLES",
                          TEST_RESAMPLES):
            data = await get_forecast_risk(
                model="GARCH", horizon=1, tickers="AAA.NS",
                start=series["AAA.NS"].index[0].date(),
                end=series["AAA.NS"].index[-1].date(),
                db=Mock(), data_service=Mock(),
                analytics_engine=AnalyticsEngine(),
            )
        record = _clip(data)["point"]["positions"]["AAA.NS"]
        assert record["raw_volatility_forecast"] is None, record
        assert record["clip_removed"] is None, record
        assert "no raw" in record["raw_volatility_forecast_basis"], record
        assert "without the fitted models' clip bounds" in (
            record["raw_volatility_forecast_basis"]
        ), record

    def test_an_absent_point_never_becomes_a_zero_clip(self):
        node = _forecast_volatility_clip_block(
            model="GARCH",
            forecast_result={"volatility_forecast": None,
                             "raw_volatility_forecast": None},
            positions={}, estimated={}, raw_volatility={},
        )
        assert node["point"]["portfolio"]["at_clip_bound"] is None
        assert node["point"]["portfolio"]["clip_removed"] is None
        assert node["point"]["at_clip_bound_positions"] == []


# ---------------------------------------------------------------------------
# 5. the shape of the fix: disclose, do not detect
# ---------------------------------------------------------------------------
class TestNoThresholdIsPublished:
    @pytest.mark.asyncio
    async def test_the_block_states_why_it_refuses_to_classify_a_large_forecast(
        self, fast_resamples
    ):
        """The measured reason, so the absence is a decision and not an oversight.

        Thirty candidate discriminators on 5,185 real EGARCH(1,1) fits, none of
        them separable, and the four in-sample separators hold out at a coin flip.
        A reader who wants to know why a huge draw is not refused finds that here
        rather than inferring that nobody thought about it.
        """
        node = _clip(await _payload())
        text = node["no_divergence_threshold"]
        assert "5,185" in text or "5185" in text, text
        assert "30 of 30" in text
        assert "6.0 %" in text or "6.0%" in text
        assert "coin flip" in text

    @pytest.mark.asyncio
    async def test_the_bounds_are_published_and_named_where_they_live(
        self, fast_resamples
    ):
        """The reader needs the actual constant, not the fact that one exists."""
        node = _clip(await _payload())
        assert node["bounds"]["high"] == FORECAST_VOL_CLIP_HIGH
        assert node["bounds"]["low"] == FORECAST_VOL_CLIP_LOW
        assert node["bounds"]["model"] == "GARCH"
        assert "analytics_engine.py" in node["declared_at"]
        assert "volatility_forecast_point" in node["declared_at"]

    def test_the_low_bound_follows_the_model_because_only_it_differs(self):
        """EGARCH's low bound is 0.0 and everyone else's is 0.05.

        Publishing one number for both would state a bound that was not the one in
        force on an EGARCH request, which is the class of error this whole node
        exists to remove.
        """
        def bounds(model):
            return _forecast_volatility_clip_block(
                model=model, forecast_result={}, positions={}, estimated={},
                raw_volatility={},
            )["bounds"]

        assert bounds("EGARCH")["low"] == 0.0
        assert bounds("GARCH")["low"] == FORECAST_VOL_CLIP_LOW
        assert bounds("EWMA")["low"] == FORECAST_VOL_CLIP_LOW
        # the HIGH bound is the same for all three, and that is the one this
        # finding is about
        assert {bounds(m)["high"] for m in ("EGARCH", "GARCH", "EWMA")} == {
            FORECAST_VOL_CLIP_HIGH
        }

    @pytest.mark.asyncio
    async def test_the_point_level_boolean_is_still_where_it_was(self):
        """The new node ADDS to the existing prose; it does not replace it.

        A fix that moved the per-leg `annualized_volatility_at_clip_bound` into a
        new key would break the pointer and evidence checks that already cover
        it, and would leave a reader who only reads the derivation entry with
        less than they had.
        """
        data = await _payload()
        for ticker in TICKERS:
            entry = data["precision"]["derived_values"][
                f"positions.{ticker}.var_forecast"
            ]
            assert "annualized_volatility_at_clip_bound" in (
                entry["derivation_precondition_evidence"]
            )
        assert "raw_volatility_forecast" in _clip(data)["point"]["point_basis"]


# ---------------------------------------------------------------------------
# 6. no published value moved
# ---------------------------------------------------------------------------
class TestNoPublishedValueMoved:
    @pytest.mark.asyncio
    async def test_the_new_keys_are_new_and_the_leg_is_untouched(
        self, fast_resamples
    ):
        """The disclosure is additive at the section level and nothing else.

        `positions.<ticker>` is the surface other consumers and the frontend
        read, so its key set is pinned: the clip magnitude lives under
        `precision`, not on the leg.
        """
        data = await _payload()
        for ticker in TICKERS:
            assert set(data["positions"][ticker]) == PRE_EXISTING_LEG_KEYS, ticker
        assert "volatility_clip" in data["precision"]
        # the leg's OWN uncertainty block gained the tally under notes, which is
        # the caller's namespace on it, and lost nothing
        block = data["precision"]["estimated_statistics"]["positions"][TICKERS[0]]
        assert "clip_bound_restatements" in block["notes"]
        assert block["estimates"]["volatility_forecast"]["point"] == (
            data["positions"][TICKERS[0]]["volatility_forecast"]
        )

    @pytest.mark.asyncio
    async def test_the_route_publishes_the_engine_value_untouched(
        self, fast_resamples
    ):
        """The published forecast is the engine's, and the raw is the engine's.

        Checked against a direct engine call rather than against a stored
        fixture, so it cannot rot: if the route started forwarding a
        re-derived or rounded number, this fails.
        """
        series = _prices()
        engine = AnalyticsEngine()
        data = await _payload(engine=engine)
        # The PORTFOLIO leg is an aggregate the route builds from the
        # allocation, so the per-leg check below is the one that can be made
        # against the engine directly.  The portfolio's own numbers are still
        # pinned: they are the engine's, forwarded verbatim.
        for ticker in TICKERS:
            rets = series[ticker].pct_change(fill_method=None).dropna()
            direct = await engine.forecast_volatility(rets, "GARCH", 1)
            assert data["positions"][ticker]["volatility_forecast"] == (
                direct["volatility_forecast"]
            )
            record = _clip(data)["point"]["positions"][ticker]
            assert record["raw_volatility_forecast"] == direct[
                "raw_volatility_forecast"
            ]
        portfolio = _clip(data)["point"]["portfolio"]
        assert portfolio["published"] == data["portfolio"]["volatility_forecast"]
        assert portfolio["raw_volatility_forecast"] == pytest.approx(
            portfolio["published"]
        )

    def test_the_observer_returns_the_engine_dict_unchanged(self):
        """The wrapper observes; it does not transform.

        If it altered the draws it would silently become a second implementation
        of the band, which is the drift this whole disclosure rests on not
        existing.  Compared against the engine's OWN factory called with the same
        `fields`, so a difference here is the wrapper's and not the field set's.
        """
        import app.services.analytics_engine as engine_module

        series = _prices()["AAA.NS"].pct_change(fill_method=None).dropna()
        fields = (
            "volatility_forecast", "return_space_volatility",
            "raw_volatility_forecast",
        )
        plain = engine_module.volatility_forecast_statistics("GARCH", 1, fields=fields)
        observed, tally = analytics_api._observed_volatility_statistics("GARCH", 1)
        block = np.stack([series.values] * TEST_RESAMPLES, axis=1)[:, :, None]
        seen = observed(block)
        direct = plain(block)
        assert sorted(seen) == sorted(direct) == sorted(fields)
        for key in direct:
            np.testing.assert_array_equal(seen[key], direct[key])
        assert tally["restatements"] == TEST_RESAMPLES
        assert tally["usable_restatements"] == TEST_RESAMPLES
        assert tally["at_clip_bound"] == 0
        assert tally["largest_removed_by_clip"] == 0.0

    def test_the_observer_reads_the_DRAW_axis_and_not_the_observation_axis(self):
        """The block is `(n, draws, k)`; reading axis 0 would count observations.

        On this fixture the two differ, which is the point: an observer that read
        the wrong axis would publish a denominator of 59 for a band read off 60
        draws, and on the real book's 175-observation legs it would publish 175
        for 1,000.  Both look plausible and neither is the population the band was
        measured on.
        """
        series = _prices()["AAA.NS"].pct_change(fill_method=None).dropna()
        observed, tally = analytics_api._observed_volatility_statistics("GARCH", 1)
        block = np.stack([series.values] * TEST_RESAMPLES, axis=1)[:, :, None]
        assert block.shape[0] != block.shape[1], (
            "the fixture must have n != draws, or this test cannot fail"
        )
        observed(block)
        assert tally["restatements"] == block.shape[1]
        assert tally["restatements"] != block.shape[0]

    def test_the_observer_ignores_the_reproduction_guards_own_call(self):
        """`measure_estimate_uncertainty` calls the statistic twice.

        The second call is the guard's single-draw re-derivation of the point,
        not a draw set, and counting it would put a population of one into a
        denominator that means restatements.
        """
        series = _prices()["AAA.NS"].pct_change(fill_method=None).dropna()
        observed, tally = analytics_api._observed_volatility_statistics("GARCH", 1)
        block = np.stack([series.values] * TEST_RESAMPLES, axis=1)[:, :, None]
        observed(block)
        assert tally["restatements"] == TEST_RESAMPLES
        guard_call = series.values[:, None, None]
        assert guard_call.shape[1] == 1
        observed(guard_call)
        assert tally["restatements"] == TEST_RESAMPLES, (
            "the single-draw reproduction call overwrote the draw count"
        )
