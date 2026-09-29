"""What a count, a band and a mean are measured over - stated, not assumed.

Four defects share one shape: a published number whose POPULATION or
AGGREGATION RULE was never written down, so a reader could not check it against
the values published beside it.

1. `history_coverage.model_observation_count` was a copy of
   `full_history.observation_count` - the rows of the INPUT FRAME - published
   under the name of the model's own sample. The v26 export published 175 where
   the regression used 101, with no scope, and a comment asserting that "the
   counts are the observations the model used". The count is now handed IN by
   the caller that measured it, with the population it describes, and degrades
   to a stated upper bound when it cannot be measured.

2. `liquidation_time_days` is the band of the MEAN published score, while
   `by_position.*.liquidation_days` is a distribution (v26: 1-2 over legs
   distributed {1-2: 10, 2-5: 3, 5-10: 1}). Nothing said which, so the two could
   not be reconciled. The rule is now published; the value is untouched.

3. `volume_stats.avg_volume` is an unweighted mean of per-leg means taken over
   UNEQUAL row counts. The basis and the per-leg counts are now published; the
   value is untouched, because `total_portfolio_volume` on the same block is a
   SUM of the same per-leg means and changing one alone would break the block.

4. `diversification_score` is a 0-100 index published with no scale, no `n` and
   no formula. The engine measures the index and now declares it; this file
   gates that the ROUTE forwards the declaration, and that the published score
   satisfies the published formula from the published inputs.

The property that was violated three times is not that three sections publish
the same number - they do not, and must not: `factor_exposure` fits a benchmark
regression over a SUBSET of its frame, while `risk_contribution` fits a
whole-book covariance over the whole frame. The violated property is that
`model_observation_count` was published with no `model_observation_count_scope`
anywhere, so no reader could tell which population each of the three carried.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import numpy as np
import pandas as pd
import pytest

from app.api import analytics as analytics_mod
from app.api.analytics import (
    MODEL_SAMPLE_COVARIANCE_FRAME_SCOPE,
    MODEL_SAMPLE_FRAME_SCOPE,
    MODEL_SAMPLE_FITTED_SCOPE,
    get_concentration_metrics,
    get_factor_exposure,
    get_liquidity_metrics,
    get_risk_contribution,
)
from app.models.database import PortfolioPosition


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


def _pos(ticker, *, market_value=10000.0, sector="Tech", added_on=None,
         region="IN"):
    return PortfolioPosition(
        id=1, ticker=ticker, weight=None, quantity=1.0, buy_price=None,
        last_price=float(market_value), market_value=float(market_value),
        region=region, sector=sector, industry="Y", added_on=added_on,
    )


def _walk(dates, *, seed=1, drift=0.0, scale=100.0):
    rng = np.random.default_rng(seed)
    return pd.Series(
        scale * np.exp(np.cumsum(rng.normal(drift, 0.01, len(dates)))), index=dates
    )


def _frame(dates, *, seed=1):
    return pd.DataFrame({"adj_close": _walk(dates, seed=seed)}, index=dates)


class _Market:
    """Price frames keyed by ticker, sliced to the requested window."""

    def __init__(self, frames, caps=None):
        self.frames = frames
        self.caps = caps or {}
        self.fetch_historical_data = AsyncMock(side_effect=self._history)
        self.fetch_quote = AsyncMock(side_effect=self._quote)

    async def _history(self, ticker, start, end):
        frame = self.frames.get(ticker)
        if frame is None:
            return pd.DataFrame()
        window = frame.loc[
            (frame.index >= pd.Timestamp(start)) & (frame.index <= pd.Timestamp(end))
        ]
        return window.copy()

    async def _quote(self, ticker):
        return {"market_cap": self.caps.get(ticker)}


def _ohlcv(dates, *, price=100.0, volume=1_000_000.0):
    return pd.DataFrame(
        {"Close": np.full(len(dates), price), "Volume": np.full(len(dates), volume)},
        index=dates,
    )


def _recent_bdays(periods: int) -> pd.DatetimeIndex:
    """Business days ENDING TODAY, sized to sit inside the route's own window.

    Every analytics route derives its requested window from `datetime.now()` -
    the liquidity route asks for `now - 30d .. now` - and the market seam slices
    the delivered frame to that window. A frame hard-dated to a fixed past date
    therefore ages: it delivers fewer rows as the clock advances and eventually
    delivers NONE, at which point the section returns its no-price-data shape and
    the test fails on a calendar, not on the disclosure it is about.

    Anchoring to the clock removes the calendar from the test. `periods` is kept
    at or below 20 because 20 business days is about 28 calendar days, so the
    whole frame lands inside a 30-day request on any weekday.
    """
    return pd.bdate_range(end=pd.Timestamp(datetime.now().date()), periods=periods)


class _RecordingEngine:
    """A REAL engine, with its result kept so identity can be asserted.

    The route only awaits `concentration_analysis`, so anything carrying that
    method is a valid engine to it. This one delegates to a real
    `AnalyticsEngine` and holds the exact dict the route was handed - which is
    what makes `result["scale"] is engine["scale"]` a statement about object
    identity rather than about two equal dicts.
    """

    def __init__(self):
        self.engine = analytics_mod.AnalyticsEngine()
        self.calls = 0
        self.results = []

    async def concentration_analysis(self, weights):
        self.calls += 1
        result = await self.engine.concentration_analysis(weights)
        self.results.append(result)
        return result


# ---------------------------------------------------------------------------
# 1. model_observation_count is the fit's own sample, and says which one
# ---------------------------------------------------------------------------
async def _factor_payload(*, ticker_frames, bench_dates, tickers):
    db = _db([_pos(t, added_on=datetime(2020, 1, 1)) for t in tickers])
    bench = SimpleNamespace(
        get_returns=AsyncMock(return_value=_walk(bench_dates, seed=99, drift=0.0003))
    )
    return await get_factor_exposure(
        tickers=",".join(tickers), lookback_days=365, db=db,
        data_service=_Market(ticker_frames),
        benchmark_service=bench,
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )


@pytest.mark.asyncio
async def test_model_observation_count_is_the_fits_own_sample_not_the_frame():
    """A late-listed leg makes the two populations differ, as on the live book.

    The portfolio series is coverage-gated, so the fit can only run on the dates
    where the WHOLE book is priced. The frame the fit was handed keeps the early
    dates, where one leg was unpriced. The published count must be the first
    population, and must be asserted against the fit's own `observations` rather
    than a literal, so the test states the CAUSE and not an accident of a fixture.
    """
    dates = pd.bdate_range(end=pd.Timestamp("2026-09-22"), periods=253)
    frames = {
        "A.NS": _frame(dates, seed=3),
        "LATE.NS": _frame(dates[-20:], seed=4),
    }

    result = await _factor_payload(
        ticker_frames=frames, bench_dates=dates, tickers=["A.NS", "LATE.NS"]
    )
    coverage = result["history_coverage"]
    frame_rows = coverage["full_history"]["observation_count"]
    fit_rows = result["portfolio"]["observations"]

    assert fit_rows and fit_rows < frame_rows, (
        "the fixture must separate the two populations or the test proves nothing"
    )
    # THE CAUSE: the count is the fit's own sample.
    assert coverage["model_observation_count"] == fit_rows
    assert coverage["model_observation_count_scope"] == MODEL_SAMPLE_FITTED_SCOPE
    assert coverage["model_observation_count_status"] == "fitted"
    assert coverage["model_observation_count_status_reason"] is None
    # The frame count is still published, under its own keys and its own scope.
    # It is NOT withdrawn: it is the frame, and `covered_days` keeps naming it.
    assert coverage["covered_days"] == frame_rows
    assert coverage["full_history"]["observation_count"] == frame_rows
    assert coverage["full_history"]["window"]["days"] == frame_rows
    assert result["model_window"] == coverage["full_history"]["window"]
    assert coverage["benchmark_overlap_observations"] >= fit_rows


@pytest.mark.asyncio
async def test_published_sample_is_the_one_adjusted_r_squared_was_fitted_on():
    """The count and the fit statistic must be the SAME fit, provably.

    `adjusted_r_squared` is statsmodels' `rsquared_adj`, the identity
    `1-(1-R^2)(n-1)/(n-2)`. Solving it for n against the published pair pins the
    sample that produced them. This is how the v26 export was shown to have used
    101 while publishing 175, and it is the check that fails if the count and
    the R-squared ever drift apart again.
    """
    dates = pd.bdate_range(end=pd.Timestamp("2026-09-22"), periods=253)
    result = await _factor_payload(
        ticker_frames={"A.NS": _frame(dates, seed=3), "LATE.NS": _frame(dates[-20:], seed=4)},
        bench_dates=dates, tickers=["A.NS", "LATE.NS"],
    )
    coverage = result["history_coverage"]
    published = coverage["model_observation_count"]
    frame_rows = coverage["full_history"]["observation_count"]
    r_squared = float(result["r_squared"])
    adjusted = float(result["adjusted_r_squared"])

    def predicted(n):
        return 1.0 - (1.0 - r_squared) * (n - 1) / (n - 2)

    # `r_squared`/`adjusted_r_squared` are each rounded to 4 decimals, so the
    # identity can only be checked to that order, not exactly.
    assert abs(predicted(published) - adjusted) < 5e-4, (
        "the published sample is not the one adjusted_r_squared was fitted on"
    )
    # And the frame is NOT that sample: it fails the same identity. This is the
    # difference the old 175-vs-101 contradiction was, as a test rather than a
    # claim.
    assert abs(predicted(frame_rows) - adjusted) > 1e-3, (
        "the fixture no longer separates the fit's sample from the frame"
    )


@pytest.mark.asyncio
async def test_unmeasurable_fit_sample_degrades_to_a_stated_upper_bound():
    """The fallback: a stated ceiling, never a wrong sample.

    The engine publishes `observations: 0` on every not-fitted path. A count that
    cannot be measured must be published as the frame it was handed, with a
    scope and a reason that say it is an upper bound - not as a sample.
    """
    dates = pd.bdate_range(end=pd.Timestamp("2026-09-22"), periods=253)
    frames = {"A.NS": _frame(dates, seed=3), "LATE.NS": _frame(dates[-20:], seed=4)}

    async def _not_fitted(*_args, **_kwargs):
        return {
            "portfolio": {
                "alpha": None, "annualized_alpha": None, "market": None,
                "observations": 0, "error": "insufficient data for factor regression",
            },
            "positions": {},
            "r_squared": None,
            "adjusted_r_squared": None,
            "error": "insufficient data for factor regression",
        }

    with patch.object(
        analytics_mod.AnalyticsEngine,
        "factor_exposure_analysis",
        AsyncMock(side_effect=_not_fitted),
    ):
        result = await _factor_payload(
            ticker_frames=frames, bench_dates=dates, tickers=["A.NS", "LATE.NS"]
        )

    coverage = result["history_coverage"]
    frame_rows = coverage["full_history"]["observation_count"]
    assert coverage["model_observation_count"] == frame_rows
    assert coverage["model_observation_count_scope"] == MODEL_SAMPLE_FRAME_SCOPE
    assert coverage["model_observation_count_status"] == "regression_sample_unavailable"
    reason = coverage["model_observation_count_status_reason"]
    assert isinstance(reason, str) and "upper bound" in reason
    assert coverage["model_observation_count_note"] and "UPPER BOUND" in (
        coverage["model_observation_count_note"]
    )
    # The frame is never withdrawn from the block, so a reader can still see
    # what the ceiling is made of.
    assert coverage["covered_days"] == frame_rows


@pytest.mark.asyncio
async def test_every_section_publishing_a_model_count_declares_its_population():
    """The property that was violated three times: no scope, three sections.

    `factor_exposure` and `risk_contribution` share one builder and publish the
    same KEY for two DIFFERENT populations - a benchmark-regression subset and a
    whole-book covariance frame. Neither is allowed to be the other's, and
    neither may publish the key without saying which it is. (The third
    publication, the `risk_studio` dashboard twin, is a copy of the
    `risk_contribution` section payload - `ai_context_service` guarantees the
    copy, and `test_ai_context_component_reference` gates that guarantee - so
    the two here are the two that can disagree.)
    """
    dates = pd.bdate_range(end=pd.Timestamp("2026-09-22"), periods=253)
    factor = await _factor_payload(
        ticker_frames={"A.NS": _frame(dates, seed=3), "LATE.NS": _frame(dates[-20:], seed=4)},
        bench_dates=dates, tickers=["A.NS", "LATE.NS"],
    )
    rc_db = _db([_pos("A.NS", added_on=datetime(2020, 1, 1))])
    contribution = await get_risk_contribution(
        tickers="A.NS",
        db=rc_db,
        data_service=_Market({"A.NS": _frame(dates, seed=3)}),
    )

    published = {
        "factor_exposure": factor["history_coverage"],
        "risk_contribution": contribution["history_coverage"],
    }
    for name, coverage in published.items():
        assert isinstance(coverage.get("model_observation_count_scope"), str), (
            f"{name} publishes model_observation_count with no scope"
        )
        assert coverage["model_observation_count_scope"], name
        assert coverage["model_observation_count_status"], name

    # Two populations, two scopes, neither borrowed from the other.
    assert (
        published["factor_exposure"]["model_observation_count_scope"]
        == MODEL_SAMPLE_FITTED_SCOPE
    )
    assert (
        published["risk_contribution"]["model_observation_count_scope"]
        == MODEL_SAMPLE_COVARIANCE_FRAME_SCOPE
    )

    # The covariance model IS the frame, so its count is the frame's - and its
    # value is unchanged by any of this.
    rc_coverage = published["risk_contribution"]
    assert rc_coverage["model_observation_count"] == rc_coverage["covered_days"]
    assert rc_coverage["model_observation_count"] == (
        rc_coverage["full_history"]["observation_count"]
    )
    assert "min_periods" in rc_coverage["model_observation_count_note"]
    # ...while the regression's is strictly narrower than its frame.
    assert (
        published["factor_exposure"]["model_observation_count"]
        < published["factor_exposure"]["full_history"]["observation_count"]
    )


# ---------------------------------------------------------------------------
# 2 + 3. the liquidity aggregation rules
# ---------------------------------------------------------------------------
def _band_for(score, bands):
    for band in bands:
        low, high = band.get("min_published_score"), band.get("max_published_score")
        if low is not None and score < float(low):
            continue
        if high is not None and score >= float(high):
            continue
        return band["band"], band["liquidation_days"]
    raise AssertionError(f"no band for {score}")


@pytest.mark.asyncio
async def test_liquidation_window_states_the_aggregation_behind_it():
    """The section value reconciles with the rule, and the rule is not a leg.

    The book is built so the legs SPAN all three bands: a mean-score band, a
    worst-case leg and a median leg that are three different strings. That is
    the only way to prove the published rule is the mean and not either
    alternative - a fixture where they agree would pass by coincidence.
    """
    dates = _recent_bdays(20)
    # Turnover tiers, pinned by the engine's own formulas at a constant close of
    # 100: daily_turnover = volume * 100. Three legs at 2e8/day land in Tier 2
    # (7.8 + 2e8/5e8*1.1 = 8.24 -> 8.2, band 1-2) and one at 1.93e6/day in
    # Tier 4 (3.0 + 1.93e6/2e7*2.9 = 3.28 -> 3.3, band 5-10). The mean of those
    # four published scores is 6.975, which the section rounds to 7.0 and bands
    # as Medium - a band NO leg occupies, and about 1.0 clear of BOTH band
    # edges. The clearance is asserted below: a fixture whose mean sat a hundredth
    # from an edge would fail on any drift in the engine's tiers, and would fail
    # with a message about worst-case reasoning that names the real cause not at
    # all.
    specs = {
        "AAA.NS": 2_000_000.0,
        "BBB.NS": 2_000_000.0,
        "CCC.NS": 2_000_000.0,
        "DDD.NS": 19_300.0,
    }
    frames = {
        ticker: _ohlcv(dates, price=100.0, volume=volume)
        for ticker, volume in specs.items()
    }
    db = _db([_pos(t, market_value=1_000_000.0) for t in specs])

    result = await get_liquidity_metrics(
        db=db, data_service=_Market(frames),
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )

    bands = result["scoring"]["bands"]
    rule = result["liquidation_time_days_aggregation"]
    assert isinstance(rule, str) and rule
    assert "mean" in rule.lower()
    assert "not a worst case" in rule.lower()
    assert "not a median" in rule.lower()

    # The published value IS the band of the mean of the published leg scores.
    leg_scores = [row["score"] for row in result["by_position"].values()]
    mean_score = float(np.mean(leg_scores))
    expected_band, expected_days = _band_for(round(mean_score, 1), bands)
    assert result["liquidation_time_days"] == expected_days
    assert result["overall_band"] == expected_band
    assert result["overall_score"] == round(mean_score, 1)

    # FIXTURE PRECONDITION, asserted before the claim it supports: the mean must
    # sit well inside the band it is expected to land in, or the two assertions
    # below are measuring rounding rather than the aggregation rule.
    edges = [b["min_published_score"] for b in bands if b["min_published_score"] is not None]
    clearance = min(
        [edge - mean_score for edge in edges if edge > mean_score]
        + [mean_score - edge for edge in edges if edge <= mean_score]
    )
    assert clearance >= 0.5, (
        f"fixture drift: the mean score {mean_score} sits {clearance:.3f} from a "
        "band edge, so this test would fail on a tier change rather than on an "
        "aggregation defect"
    )

    # The distribution is published in full, and it is NOT what the section
    # value reports. On this book the section publishes a band NO leg occupies,
    # and it is neither the worst leg nor the median leg: a rule that took any
    # leg-level aggregation could not produce it.
    leg_days = sorted(row["liquidation_days"] for row in result["by_position"].values())
    assert len(set(leg_days)) > 1, "the fixture must span more than one band"
    assert result["liquidation_time_days"] not in set(leg_days)
    assert result["liquidation_time_days"] != max(leg_days)
    assert result["liquidation_time_days"] != leg_days[len(leg_days) // 2]


@pytest.mark.asyncio
async def test_scoring_bands_and_thresholds_are_one_table_not_two():
    dates = _recent_bdays(20)
    db = _db([_pos("AAA.NS", market_value=1_000_000.0)])
    result = await get_liquidity_metrics(
        db=db,
        data_service=_Market({"AAA.NS": _ohlcv(dates)}, caps={"AAA.NS": 2.0e11}),
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )
    scoring = result["scoring"]
    assert scoring["thresholds"] == scoring["bands"]
    assert scoring["thresholds_alias_of"] == "bands"
    assert "SAME mapping" in scoring["thresholds_alias_note"]


@pytest.mark.asyncio
async def test_avg_volume_basis_names_the_unweighted_mean_and_shows_the_inequality():
    """Unequal leg sample sizes, and the two candidate means are far apart.

    `avg_volume` must stay the unweighted mean of the per-leg means - the value
    is not being changed here - while the disclosure has to let a reader see
    that the legs are not interchangeable.
    """
    dates = _recent_bdays(20)
    # One leg covers the whole delivered window, the other only its last 8
    # sessions, so the two legs' sample sizes differ INSIDE the delivered
    # window rather than only before it.
    frames = {
        "AAA.NS": _ohlcv(dates, volume=4_000_000.0),
        "BBB.NS": _ohlcv(dates[-8:], volume=100_000.0),
    }
    db = _db([_pos("AAA.NS", market_value=1_000_000.0), _pos("BBB.NS", market_value=1_000_000.0)])

    result = await get_liquidity_metrics(
        db=db, data_service=_Market(frames),
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )
    stats = result["volume_stats"]
    legs = {t: row["avg_volume"] for t, row in result["by_position"].items()}

    assert "unweighted" in stats["avg_volume_basis"].lower()
    assert "row-weighted" in stats["avg_volume_basis"].lower()

    counts = stats["avg_volume_leg_observations"]
    assert set(counts) == set(legs)
    assert counts == {
        ticker: result["scoring"]["observation_window"]["per_ticker"][ticker]["observations"]
        for ticker in legs
    }
    assert stats["avg_volume_leg_observation_min"] < stats["avg_volume_leg_observation_max"]
    assert stats["avg_volume_leg_observation_total"] == sum(counts.values())

    unweighted = float(np.mean(list(legs.values())))
    weighted = float(np.average(list(legs.values()), weights=list(counts.values())))
    assert unweighted != pytest.approx(weighted, rel=1e-6), (
        "the fixture must make the two candidate means differ"
    )
    # The published figure is the UNWEIGHTED mean, unchanged - and provably not
    # the row-weighted one, which is the number a reader would otherwise assume.
    assert stats["avg_volume"] == pytest.approx(unweighted, rel=1e-12)
    assert stats["avg_volume"] != pytest.approx(weighted, rel=1e-6)
    # The sum on the same block is the sum of the same per-leg means, so its own
    # basis is stated too rather than left to be read as a portfolio volume.
    assert "sum_of_the_same_per_leg_mean_volumes" in (
        stats["total_portfolio_volume_basis"]
    )
    assert stats["total_portfolio_volume"] == pytest.approx(sum(legs.values()), rel=1e-12)


@pytest.mark.asyncio
@pytest.mark.parametrize("clock_offset_days", [0, 37, 400])
async def test_the_aggregation_claim_holds_on_any_calendar_date(
    clock_offset_days, monkeypatch
):
    """The determinism this file owes, as an assertion rather than a claim.

    Every route here takes its window from `datetime.now()`, and the liquidity
    one asks for a flat 30 days. A test that pins a fixture to a fixed past date
    therefore measures the calendar as much as the disclosure: the delivered
    window shortens as the clock advances, and on the day the whole frame falls
    out of the request the section returns its no-price-data shape and the test
    fails for a reason that has nothing to do with aggregation. The offset runs
    here span a different weekday alignment, a month boundary and a year
    boundary, and the same three claims - the section value is the mean's band,
    the band is no leg's band, and the legs disagree with each other - must hold
    in each.
    """
    real_now = datetime.now()

    class _ShiftedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return real_now + timedelta(days=clock_offset_days)

    monkeypatch.setattr(analytics_mod, "datetime", _ShiftedClock)
    sim_today = pd.Timestamp(_ShiftedClock.now().date())
    dates = pd.bdate_range(end=sim_today, periods=20)
    specs = {"AAA.NS": 2_000_000.0, "BBB.NS": 2_000_000.0, "CCC.NS": 2_000_000.0,
             "DDD.NS": 19_300.0}

    result = await get_liquidity_metrics(
        db=_db([_pos(t, market_value=1_000_000.0) for t in specs]),
        data_service=_Market({
            ticker: _ohlcv(dates, price=100.0, volume=volume)
            for ticker, volume in specs.items()
        }),
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )

    bands = result["scoring"]["bands"]
    leg_scores = [row["score"] for row in result["by_position"].values()]
    assert leg_scores, f"no legs were measured on the simulated date {sim_today.date()}"
    mean_score = float(np.mean(leg_scores))
    assert result["liquidation_time_days"] == _band_for(round(mean_score, 1), bands)[1]
    leg_days = [row["liquidation_days"] for row in result["by_position"].values()]
    assert len(set(leg_days)) > 1
    assert result["liquidation_time_days"] not in set(leg_days)
    assert result["liquidation_time_days"] != max(leg_days)
    assert result["liquidation_time_days"] != sorted(leg_days)[len(leg_days) // 2]


# ---------------------------------------------------------------------------
# 4. the diversification scale
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_diversification_score_declares_its_scale_and_satisfies_its_formula():
    db = _db([
        _pos("AAA.NS", market_value=400_000.0),
        _pos("BBB.NS", market_value=300_000.0),
        _pos("CCC.NS", market_value=200_000.0),
        _pos("DDD.NS", market_value=100_000.0),
    ])

    result = await get_concentration_metrics(
        db=db, data_service=Mock(), analytics_engine=analytics_mod.AnalyticsEngine()
    )

    scale = result["scale"]
    assert scale["min"] == 0.0 and scale["max"] == 100.0
    assert "100" in scale["at_max"] and "1 / n_holdings" in scale["at_max"]
    assert "0" in scale["at_min"] and "herfindahl_index == 1" in scale["at_min"]
    assert "n_holdings" in scale["holdings_basis"]
    assert result["n_holdings"] == len(result["by_weight"]) == 4
    assert "herfindahl_index" in result["diversification_score_formula"]
    assert "n_holdings" in result["diversification_score_formula"]
    assert "DIFFERENT statistic" in result["diversification_ratio_formula"]

    # The published score satisfies the published formula, from the published
    # inputs, at the published precision.
    herfindahl = float(result["herfindahl_index"])
    n = int(result["n_holdings"])
    recomputed = ((1.0 - herfindahl) / (1.0 - 1.0 / n)) * 100.0
    assert round(recomputed, 1) == result["diversification_score"]
    # ...and the route's numbers are the engine's, unchanged.
    engine = await analytics_mod.AnalyticsEngine().concentration_analysis(
        result["by_weight"]
    )
    for key in (
        "largest_position", "top_3", "top_5", "top_10", "herfindahl_index",
        "effective_positions", "diversification_score", "diversification_ratio",
        "gini_coefficient",
    ):
        assert result[key] == engine[key], key
    # The scale and the formulas are the engine's own, forwarded rather than
    # restated: one scale, one text. A route-side copy beside the engine's would
    # be two declarations of one rule, which is the defect the liquidity
    # `bands`/`thresholds` alias is about.
    assert result["scale"] == engine["scale"]
    assert result["diversification_score_formula"] == engine["diversification_score_formula"]
    assert result["diversification_ratio_formula"] == engine["diversification_ratio_formula"]
    assert result["n_holdings"] == engine["n_holdings"]


@pytest.mark.asyncio
async def test_the_engine_s_five_disclosures_travel_through_the_route_end_to_end():
    """The gap a stubbed engine leaves open: none of the five keys are covered.

    Every other concentration test here calls the route with a real engine, but
    asserts the values it computes ITSELF - so if the route dropped a forwarded
    key, only this test would notice. It runs a real `concentration_analysis`
    through the route with a recorder standing in for the engine, and checks the
    five keys the engine now publishes arrive as the ENGINE'S OWN OBJECTS, not
    as rebuilt copies: a copy is free to drift from the object the index was
    measured under, which is the one thing a forwarded disclosure must not do.
    """
    recorder = _RecordingEngine()
    result = await get_concentration_metrics(
        db=_db([
            _pos("AAA.NS", market_value=500_000.0), _pos("BBB.NS", market_value=250_000.0),
            _pos("CCC.NS", market_value=150_000.0), _pos("DDD.NS", market_value=100_000.0),
        ]),
        data_service=Mock(), analytics_engine=recorder,
    )

    assert recorder.calls == 1, "the recorder must have seen the real engine run"
    engine = recorder.results[0]
    for key in (
        "n_holdings", "scale", "diversification_score_formula",
        "diversification_ratio_formula", "effective_positions_note",
    ):
        assert key in engine, f"the engine stopped publishing {key}"
        assert key in result, f"{key} did not travel through the route"
    # Identity, not equality: the same object, so there is one declaration.
    assert result["scale"] is engine["scale"]
    assert result["diversification_score_formula"] is engine["diversification_score_formula"]
    assert result["diversification_ratio_formula"] is engine["diversification_ratio_formula"]
    assert result["effective_positions_note"] is engine["effective_positions_note"]
    assert result["n_holdings"] == engine["n_holdings"] == len(result["by_weight"])
    # And the scale that arrived is the one the score is read on.
    assert result["scale"]["min"] == 0.0 and result["scale"]["max"] == 100.0


@pytest.mark.asyncio
async def test_no_book_publishes_the_count_that_disambiguates_its_zero():
    """`diversification_score: 0.0` on an empty book is not a measurement.

    It is indistinguishable from a measured single-holding book, so the count
    that disambiguates it is published beside it: `n_holdings: 0`, the engine's
    own stated way of telling the two apart, next to `zero_metrics` and the
    error. The SCALE is not restated here - this branch never calls the engine,
    and a second copy of that text is what a single implementation avoids.
    """
    result = await get_concentration_metrics(
        db=_db([]), data_service=Mock(),
        analytics_engine=analytics_mod.AnalyticsEngine(),
    )
    assert result["zero_metrics"] is True
    assert result["diversification_score"] == 0.0
    assert result["n_holdings"] == 0
    assert result["error"] == "No portfolio positions found"
    # The route publishes no scale of its own anywhere.
    assert "scale" not in result
    assert not any(
        key.startswith("CONCENTRATION_DIVERSIFICATION") and key != (
            "CONCENTRATION_DIVERSIFICATION_FORWARDED_KEYS"
        )
        for key in dir(analytics_mod)
    ), "a second copy of the engine's scale text is back in the route module"
