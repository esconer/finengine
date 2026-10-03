"""A liquidity leg whose turnover was never measured publishes no score.

THE DEFECT.  `liquidity_analysis` computed

    volume = df['Volume'].mean()
    price  = df['Close'].iloc[-1]
    daily_turnover = volume * price

and then ran the tier ladder on `daily_turnover` with no finiteness check at
all.  Every tier predicate is `daily_turnover >= X`, and `NaN >= X` is False
for every X, so an unusable turnover fell through all four tiers into the
tier-4 branch, where the two-arg builtin `min` does this:

    >>> min(5.9, float('nan'))
    5.9

because `nan < 5.9` is False.  So `max(2.5, min(5.9, nan))` is **5.9** - the
CEILING of the weakest band - published as a measurement.  And because
`LIQUIDITY_BAND_RISK_LEVEL` INVERTS the band, `5.9` -> `("Low", "5-10")` ->
`"High"` risk.  A book with no measurable volume came back as the
weakest-liquidity-looking score carrying the WORST risk level, which is the
strongest possible statement that it is impossible to trade.

Measured on the pre-fix engine, one leg with an all-NaN Volume column:

    score 5.9 | category 'Low' | liquidation_days '5-10'
    overall_score 5.9 | overall_band 'Low' | risk_level 'High'
    volume_stats {'avg_volume': nan, 'total_portfolio_volume': nan, ...}

A clamp cannot be the fix, and the reason is worth pinning in a test because it
looks like the obvious repair:

    >>> float(np.minimum(5.9, float('nan')))
    nan

`np.minimum` propagates, so a clamp there publishes NaN instead of 5.9 - which
is still a number on the wire, and `_liquidity_band` would then either raise
(`nan >= 8.0` is False for every band, so it falls to the "Low" band anyway) or
need its own guard.  The only correct answer is to refuse before the ladder.

The second half of the coupling is the part that is easy to publish and not
notice: `volume_stats['total_volume'] += volume` carried the same NaN into
`total_portfolio_volume`, and the overall average was taken over
`[data['score'] for data in liquidity_scores.values()]`, which raises TypeError
inside a generator the moment any score is None.  Both are handled here, and
the exclusion is PUBLISHED (`scored_positions`, `unscored_positions`,
`unscored_tickers`) because an `overall_score` that is the mean of an
unstated subset of the book is its own kind of substitution.

WM-8 shares the same two lines and is pinned in the second half of this file:
`mean(Volume) * Close[-1]` is a product of means where the turnover convention
is a mean of products.
"""

import asyncio

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import (
    LIQUIDITY_BAND_RISK_LEVEL,
    AnalyticsEngine,
)

ENGINE = AnalyticsEngine()


def _frame(days: int = 40, close: float = 100.0, volume=1_000_000.0):
    index = pd.bdate_range("2024-01-02", periods=days)
    return pd.DataFrame(
        {"Close": np.full(days, close), "Volume": np.full(days, volume)},
        index=index,
    )


def _liquidity(frame, market_caps=None):
    return asyncio.run(ENGINE.liquidity_analysis({"AAA.NS": frame}, market_caps))


# ---------------------------------------------------------------------------
# The structural facts this fix rests on.  Asserted, not assumed: a fix that
# depended on either of these being false would be a fix that stopped working
# the moment Python or numpy changed.
# ---------------------------------------------------------------------------

def test_the_builtin_min_swallows_a_nan_and_numpy_minimum_does_not():
    """Why a clamp is provably the wrong repair, as executable fact."""
    nan = float("nan")
    # The builtin returns the FIRST argument whenever the comparison is False,
    # which is every comparison against NaN.
    assert min(5.9, nan) == 5.9
    assert max(2.5, min(5.9, nan)) == 5.9
    # numpy propagates instead, so the clamp would publish nan.
    assert np.isnan(float(np.minimum(5.9, nan)))
    assert np.isnan(float(np.clip(nan, 2.5, 5.9)))


def test_every_tier_predicate_is_false_for_a_nan_so_nothing_catches_it():
    """The NaN reached the ladder because no tier could refuse it."""
    nan = float("nan")
    for threshold in (500_000_000.0, 100_000_000.0, 20_000_000.0):
        assert not (nan >= threshold)


# ---------------------------------------------------------------------------
# WM-1
# ---------------------------------------------------------------------------

def test_a_leg_with_no_measurable_turnover_publishes_no_score():
    frame = _frame()
    frame["Volume"] = np.nan
    leg = _liquidity(frame)["by_position"]["AAA.NS"]

    assert leg["score"] is None
    assert leg["score_raw"] is None
    # Not "Low": there is no band, because there is no score to band.
    assert leg["category"] is None
    assert leg["liquidation_days"] is None
    # Nor a spread, which is a function of the same turnover.
    assert leg["spread"] is None
    # And the reason travels with the null, naming the quantity that is absent.
    assert leg["score_unavailable_reason"]
    assert "turnover" in leg["score_unavailable_reason"]


def test_the_refusal_does_not_publish_the_weakest_band_as_a_score():
    """The exact shape of the defect: 5.9, band Low, risk High."""
    frame = _frame()
    frame["Volume"] = np.nan
    result = _liquidity(frame)

    leg = result["by_position"]["AAA.NS"]
    assert leg["score"] != 5.9
    # Pre-fix this was `("Low", "5-10")` -> risk "High".  The inverse map is
    # asserted too so a reader can see which pairing the defect turned into.
    assert LIQUIDITY_BAND_RISK_LEVEL["Low"] == "High"
    # And the refusal does not land on that pairing by way of the overall block.
    assert result["overall_band"] is None
    assert result["risk_level"] is None


def test_an_unmeasured_book_publishes_no_overall_band_and_no_risk_level():
    frame = _frame()
    frame["Volume"] = np.nan
    result = _liquidity(frame)

    # `np.mean` over a list containing None is the TypeError this had to avoid,
    # and reading the None as 0.0 would have published a fabricated bottom score.
    assert result["overall_score"] is None
    assert result["overall_score_raw"] is None
    assert result["overall_band"] is None
    assert result["risk_level"] is None
    assert result["liquidation_time_days"] is None
    # Same convention `_empty_liquidity` uses: no position was measured, so the
    # split is all zeros rather than a 100 % worst-case book nobody observed.
    stats = result["volume_stats"]
    assert stats["high_volume_pct"] == 0
    assert stats["medium_volume_pct"] == 0
    assert stats["low_volume_pct"] == 0


def test_an_unmeasured_leg_does_not_poison_the_portfolio_volume_sum():
    """`0 + nan` is nan, and nan is not a measurement of a portfolio volume."""
    frame = _frame()
    frame["Volume"] = np.nan
    result = _liquidity(frame)

    stats = result["volume_stats"]
    assert np.isfinite(stats["total_portfolio_volume"])
    assert stats["total_portfolio_volume"] == 0
    assert np.isfinite(stats["avg_volume"])


def test_an_unmeasured_leg_is_excluded_from_a_mixed_book_average():
    """The None must not become a zero inside the mean of the scored legs.

    Two legs, one measured and one not.  The measured leg's own score is the
    only thing the portfolio average may be the average OF, so the published
    `overall_score` must equal that leg's score and not a blend with a zero.
    """
    index = pd.bdate_range("2024-01-02", periods=40)
    good = pd.DataFrame(
        {"Close": np.full(40, 10.0), "Volume": np.full(40, 1_000_000.0)},
        index=index,
    )
    bad = pd.DataFrame({"Close": np.full(40, 10.0)}, index=index)
    bad["Volume"] = np.nan

    result = asyncio.run(
        ENGINE.liquidity_analysis({"GOOD.NS": good, "BAD.NS": bad})
    )

    measured = result["by_position"]["GOOD.NS"]["score"]
    assert measured is not None
    assert result["by_position"]["BAD.NS"]["score"] is None
    assert result["overall_score"] == measured, (
        "the unscored leg entered the average as a zero"
    )
    # And the split's denominator is the SCORED count, which is what
    # `volume_stats_basis` already claimed.
    assert result["scored_positions"] == 1
    assert result["unscored_positions"] == 1
    assert result["unscored_tickers"] == ["BAD.NS"]
    total = (
        result["volume_stats"]["high_volume_pct"]
        + result["volume_stats"]["medium_volume_pct"]
        + result["volume_stats"]["low_volume_pct"]
    )
    assert total == pytest.approx(100.0)


def test_a_leg_with_no_close_column_has_no_turnover_to_measure():
    """No price series means the product has no terms; no terms, no score."""
    index = pd.bdate_range("2024-01-02", periods=40)
    volume_only = pd.DataFrame({"Volume": np.full(40, 1_000_000.0)}, index=index)

    result = asyncio.run(ENGINE.liquidity_analysis({"AAA.NS": volume_only}))
    leg = result["by_position"]["AAA.NS"]
    assert leg["score"] is None
    assert leg["avg_turnover"] is None
    assert "no close column" in leg["score_unavailable_reason"]


def test_the_unscored_rule_is_published_so_a_consumer_can_see_it():
    """A null with no published rule is indistinguishable from a bug."""
    result = _liquidity(_frame())
    rule = result["score_band_rule"]["unscored_position_rule"]

    assert rule["published_score"] is None
    assert rule["reason_key"] == "score_unavailable_reason"
    # It has to say which aggregates the leg is kept out of, because those are
    # the figures that would otherwise silently change shape.
    joined = " ".join(rule["excluded_from"])
    assert "overall_score" in joined
    assert "volume_stats" in joined
    # The refusal is reasoned, not just asserted.
    assert "np.minimum(5.9, nan)" in rule["why_not_a_floor"]


def test_a_measured_book_is_untouched_by_the_refusal():
    """No measured leg changes: same score, same band, same risk level."""
    result = _liquidity(_frame(close=10.0, volume=1_000_000.0))
    leg = result["by_position"]["AAA.NS"]

    assert leg["score"] is not None
    assert "score_unavailable_reason" not in leg
    assert result["unscored_positions"] == 0
    assert result["scored_positions"] == 1
    assert result["overall_band"] in LIQUIDITY_BAND_RISK_LEVEL


# ---------------------------------------------------------------------------
# WM-8 - the turnover estimator.  This one CHANGES published numbers, so both
# the old and the new value are pinned and the direction is argued, not assumed.
# ---------------------------------------------------------------------------

#: A steadily RISING price with CONSTANT volume.  With no variance in either
#: factor the covariance term is exactly zero, so `mean(vol) * close[-1]` and
#: `mean(vol * close)` differ by the pure price term: the terminal close against
#: the average close.  That is the defect stated on its own, with the
#: covariance removed so nothing else can explain the gap.
_RAMP_DAYS = 120
_RAMP_VOLUME = 400_000.0


def _ramp_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Close": np.linspace(100.0, 300.0, _RAMP_DAYS),
            "Volume": np.full(_RAMP_DAYS, _RAMP_VOLUME),
        },
        index=pd.bdate_range("2024-01-02", periods=_RAMP_DAYS),
    )


def test_the_ramp_fixture_is_the_one_that_actually_crosses_a_tier():
    """Guard: the fixture is worthless unless the two estimators disagree.

    It does, and not marginally: 120 rows climbing 100 -> 300 have a mean close
    of 200 against a last close of 300, a factor of 1.5.  At 400 000 shares a
    day that is 1.2e8 of turnover under the old product of means (tier 2, score
    8.1, band "High") and 8.0e7 under the mean of products (tier 3, score 6.3,
    band "Medium").  A tier, a score and a band all move.
    """
    frame = _ramp_frame()
    old_turnover = float(frame["Volume"].mean()) * float(frame["Close"].iloc[-1])
    new_turnover = float((frame["Volume"] * frame["Close"]).mean())

    assert old_turnover == 120_000_000.0
    assert new_turnover == 80_000_000.0
    # The old form OVERSTATES a book that rallied: the terminal close is the
    # highest price in the window, and it was applied to the average volume.
    assert old_turnover > new_turnover
    assert (old_turnover - new_turnover) / new_turnover == pytest.approx(0.5)


def test_a_turnover_change_this_large_moves_the_published_score_and_band():
    """WM-8, pinned before and after so the change is reviewable.

    Pre-fix, on this exact frame the engine published score 8.1 / "High" /
    liquidation 1-2.  Post-fix it publishes the mean-of-products value.
    """
    result = _liquidity(_ramp_frame())
    leg = result["by_position"]["AAA.NS"]

    assert leg["avg_turnover"] == 80_000_000.0
    assert leg["score_raw"] == pytest.approx(6.32, abs=1e-9)
    assert leg["score"] == 6.3
    assert leg["category"] == "Medium"
    assert leg["liquidation_days"] == "2-5"
    # The spread follows the same number, and it moved too.
    assert leg["spread"] == 0.0018


def test_the_old_estimator_is_a_product_of_means_and_the_new_one_is_not():
    """The formula change itself, asserted on the same frame.

    The old expression dropped `cov(Volume, Close)` outright and substituted a
    TERMINAL price for an average one, so it scored a book off its last close.
    On a frame where volume and price move together - the normal case for a
    book that rallied - the old form understated; where they move oppositely it
    overstated.  Both directions are shown so the fix cannot be read as a
    one-sided re-scale.
    """
    rng = np.random.default_rng(7)
    n = 120
    up = pd.DataFrame(
        {
            "Close": 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.02, n))),
            "Volume": rng.lognormal(15.0, 1.0, n),
        }
    )
    old_up = float(up["Volume"].mean()) * float(up["Close"].iloc[-1])
    new_up = float((up["Volume"] * up["Close"]).mean())
    assert new_up > old_up
    assert (new_up - old_up) / old_up == pytest.approx(0.07871279, abs=1e-6)

    down_rng = np.random.default_rng(11)
    shocks = down_rng.normal(0.0, 0.015, 200)
    down = pd.DataFrame(
        {
            "Close": 100.0 * np.exp(np.cumsum(shocks)),
            # volume spikes on the DOWN days, so the two factors disagree
            "Volume": 3.0e6 * np.exp(-40.0 * shocks),
        }
    )
    old_down = float(down["Volume"].mean()) * float(down["Close"].iloc[-1])
    new_down = float((down["Volume"] * down["Close"]).mean())
    assert new_down < old_down


def test_a_frame_with_no_price_variance_moves_by_exactly_nothing():
    """The honest case: with zero covariance and a flat price, both agree.

    This is why the change is a correction and not a re-scale - the estimator
    only moves when one of the two defects it fixes is present.
    """
    frame = _frame(days=30, close=1.0, volume=1.2e8)
    old_turnover = float(frame["Volume"].mean()) * float(frame["Close"].iloc[-1])
    new_turnover = float((frame["Volume"] * frame["Close"]).mean())
    assert old_turnover == new_turnover

    result = _liquidity(frame, {"AAA.NS": 6.0e11})
    assert result["by_position"]["AAA.NS"]["score_raw"] == pytest.approx(9.024, abs=1e-9)


def test_the_published_avg_volume_is_a_mean_of_volumes_and_is_unchanged():
    """`avg_volume` is a different statistic and did not move.

    Only `avg_turnover` changed.  `avg_volume` is the mean of the volume
    column, which was and remains the right estimator for that quantity.
    """
    frame = _ramp_frame()
    result = _liquidity(frame)
    leg = result["by_position"]["AAA.NS"]
    assert leg["avg_volume"] == _RAMP_VOLUME
