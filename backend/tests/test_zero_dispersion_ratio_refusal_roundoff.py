"""A ratio over a denominator that measured NOTHING is `None` - round-off included.

THE DEFECT.  `test_zero_dispersion_ratio_refusal.py` fixed the case where a
ratio's denominator is exactly zero: a window whose every return is `0.0` has
`annual_volatility == 0.0`, the `if annual_volatility > 0` guard is False, and
both ratios publish `None` with their own reason.  That repair asked the wrong
question and therefore stopped one step short.

`> 0` is not "did this window measure a dispersion".  On a window whose every
return is the same NON-ZERO number the standard deviation is not 0.0 but the
round-off of the subtraction that produced it:

    >>> pd.Series([0.0007] * 60).std()
    1.0933517201189523e-19

Annualized that is 1.7356e-18, which is `> 0`, so the guard passed.  Measured
on the pre-fix engine through the production path:

    annual_volatility 1.7356420481756663e-18
    sharpe_ratio      9.011074614399442e+16
    sortino_ratio     None
    sharpe estimate entry: status 'computed', conf_int [9.01e16, 9.01e16],
                           reason None

The band is the second half of it.  `_estimate_uncertainty_block` gated on the
observation COUNT only (`values.size >= 10`), so a 60-row window passed, and a
moving-block resample of a constant series IS that same constant series - every
draw reproduced the round-off and the percentile interval came back
DEGENERATE, agreeing with the point it was supposed to be testing.  A reader
saw a Sharpe of 9e16 with a confidence interval that confirmed it.

THE PREDICATE, and why it has no threshold in it.  `nunique() < 2` is exactly
equivalent to `max == min`: it asks whether two observations differ at all.  No
epsilon, no tolerance, no magnitude cut-off is needed to tell "the dispersion
measured nothing" from "the dispersion measured something", so none is
invented - which matters because any threshold here would be a number this
method did not measure, sitting exactly where the engine's own
`num_018_no_hard_zero_sub_scores` audit says a floor is "strictly worse than the
ambiguity this rule was written to catch".  Two previous agents declined to
invent one for this same reason.

The SAME predicate serves three sites, and all three are pinned here:
`_calculate_basic_metrics`'s Sharpe guard, its Sortino guard, and
`_zero_dispersion_reason` - which is what withholds the band.  The third site is
not redundant with the first two: it is a statement about the SAMPLE, so it
holds even if a future change lets a ratio's point through.

WHAT IS DELIBERATELY NOT WITHHELD.  `annual_return`, `annual_volatility` and
`hit_ratio` still publish on this window, including `annual_volatility` =
1.7356e-18.  That IS the measurement of a constant window; withholding it would
be the opposite defect - hiding a number that was measured, and hiding the very
number that lets a reader see why the ratio is absent.
"""

import asyncio

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import AnalyticsEngine, _measures_dispersion

ENGINE = AnalyticsEngine()

#: Long enough that `SHORT_SAMPLE_MIN_OBSERVATIONS` (10) never fires: these
#: tests are about the OTHER withholding path.
DAYS = 60

#: The constant the pre-fix defect is reproduced on, quoted in the reasons so a
#: reader can check the arithmetic the guard used to admit.
CONSTANT_RETURN = 0.0007


def _constant_returns(value: float = CONSTANT_RETURN, days: int = DAYS) -> pd.Series:
    return pd.Series(
        np.full(days, value), index=pd.bdate_range("2024-01-02", periods=days)
    )


def _measured_returns(days: int = 120, seed: int = 20260903) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(
        rng.normal(0.0003, 0.010, days),
        index=pd.bdate_range("2024-01-02", periods=days),
    )


def _block(returns: pd.Series) -> dict:
    """The production pair: the point, then the band measured on that point."""
    published = ENGINE._calculate_basic_metrics(returns)
    return published, ENGINE._estimate_uncertainty_block(
        returns, published, scope="zero_dispersion_roundoff"
    )


# ---------------------------------------------------------------------------
# The predicate, and the arithmetic it replaces.  Asserted as executable fact
# because a test that cannot fail on these numbers proves nothing about them.
# ---------------------------------------------------------------------------

def test_a_constant_series_measures_a_standard_deviation_of_pure_round_off():
    """Not 0.0.  This is the whole reason `> 0` is the wrong guard."""
    returns = _constant_returns()
    std = float(returns.std())
    assert std == pytest.approx(1.0933517201189523e-19, rel=1e-9)
    assert std != 0.0
    assert (std * np.sqrt(252)) > 0.0
    # And the ratio over it is the 9e16 the defect published.
    annual_return = float(returns.mean() * 252)
    sharpe = (annual_return - ENGINE.risk_free_rate) / (std * np.sqrt(252))
    assert sharpe == pytest.approx(9.011074614399442e16, rel=1e-9)


def test_the_predicate_is_exactly_max_equals_min_and_needs_no_tolerance():
    """`nunique() >= 2` IS `max != min`, so no boundary is being invented."""
    constant = _constant_returns()
    assert constant.nunique() == 1
    assert float(constant.max()) == float(constant.min())
    assert _measures_dispersion(constant) is False

    varied = _measured_returns()
    assert varied.nunique() > 1
    assert float(varied.max()) != float(varied.min())
    assert _measures_dispersion(varied) is True

    # Two observations that differ by one float ULP still differ.  The predicate
    # refuses to pretend otherwise, which is the residual judgement recorded on
    # `_NEAR_ZERO_DISPERSION_NOTE`.
    almost = pd.Series([0.0007, 0.0007 + 1e-18] * 30)
    assert almost.nunique() == 2
    assert _measures_dispersion(almost) is True


def test_missing_observations_are_not_a_dispersion_either():
    """A window of nothing measures nothing, and says so rather than dividing."""
    empty = pd.Series([], dtype=float)
    assert _measures_dispersion(empty) is False
    all_nan = pd.Series([np.nan] * 60)
    assert _measures_dispersion(all_nan) is False
    # `dropna()` drops NaN, not -inf, so the -inf has to be handled explicitly.
    # It is here; this asserts the guard is reached rather than skipped.
    with_inf = pd.Series([np.inf, -np.inf, 0.001, 0.002])
    assert _measures_dispersion(with_inf) is True
    assert _measures_dispersion(pd.Series([np.inf, -np.inf, np.nan])) is False


# ---------------------------------------------------------------------------
# Site 1 and 2: the two ratio guards.
# ---------------------------------------------------------------------------

def test_a_constant_window_publishes_no_sharpe_at_any_magnitude():
    published, block = _block(_constant_returns())

    assert published["sharpe_ratio"] is None
    entry = block["estimates"]["sharpe_ratio"]
    assert entry["point"] is None
    assert entry["status"] == "not_computed"
    assert entry["conf_int"] is None
    # The reason has to name the DENOMINATOR, not borrow the short-window one,
    # which would send a reader off to widen history that is already wide enough.
    assert "fewer than" not in entry["reason"]
    assert "annualized volatility" in entry["reason"]
    assert "9.011e16" in entry["reason"], (
        "the reason must record the value this guard used to admit"
    )


def test_a_constant_window_publishes_no_sortino_either():
    """The same predicate on the denominator each ratio actually divides by."""
    published, block = _block(_constant_returns())
    assert published["sortino_ratio"] is None
    entry = block["estimates"]["sortino_ratio"]
    assert entry["point"] is None
    assert entry["status"] == "not_computed"
    assert entry["conf_int"] is None
    assert "downside deviation" in entry["reason"]


def test_the_window_is_long_enough_that_the_short_sample_branch_is_not_the_one_firing():
    """Guard: a test that could be passing on the <10 branch proves nothing."""
    returns = _constant_returns()
    assert len(returns) >= AnalyticsEngine.SHORT_SAMPLE_MIN_OBSERVATIONS
    published, block = _block(returns)
    # The short-window reason withholds THREE fields including annual_return;
    # this one withholds the two ratios only.
    assert published["annual_return"] is not None
    assert block["estimates"]["annual_return"]["reason"] is None
    for field in ("sharpe_ratio", "sortino_ratio"):
        assert "fewer than" not in block["estimates"][field]["reason"]


# ---------------------------------------------------------------------------
# Site 3: the band.  The defect's other half, and the part a reader sees as
# "the engine is confident".
# ---------------------------------------------------------------------------

def test_the_band_is_withheld_on_a_window_that_measures_no_dispersion():
    """`measure_estimate_uncertainty` gates on the COUNT; a count is not enough.

    Sixty observations is comfortably above the ten the resampler needs, so the
    block runs, resamples 1000 times, and would otherwise publish a
    DEGENERATE interval: a moving-block resample of a constant series is that
    same constant series, so every draw reproduced the point exactly.
    """
    _, block = _block(_constant_returns())
    assert block["observations"] >= 10
    for field in ("sharpe_ratio", "sortino_ratio"):
        entry = block["estimates"][field]
        assert entry["status"] == "not_computed"
        assert entry["conf_int"] is None
        assert entry["standard_error"] is None


def test_the_reason_gate_does_not_depend_on_the_point_being_absent():
    """The third site is a statement about the SAMPLE, not about the point.

    `_zero_dispersion_reason` filters on `declared[field] is None`.  With the
    point guard moved to the structural predicate those two conditions happen
    to agree today - but they are different questions, and the band must be
    withheld for the sample's sake.  Handing the filter a window that measures
    no dispersion and a block that nevertheless claims a point is the case
    where the difference shows, and the filter must still refuse the band.
    """
    returns = _constant_returns()
    lie = {"sharpe_ratio": 9.011074614399442e16, "sortino_ratio": None,
           "annual_volatility": 1.7356420481756663e-18}
    reasons = ENGINE._zero_dispersion_reason(lie, returns.to_numpy(dtype=float))
    assert "sharpe_ratio" in reasons
    assert "sortino_ratio" in reasons


def test_a_measured_window_keeps_both_ratios_and_both_bands():
    """The other side of the guard, and the one that proves the test can pass.

    A real dispersion: `nunique` in the hundreds, a Sharpe the sign of which
    depends on the draw, and a resampling band that BRACKETS the point.  Without
    this the tests above would also be satisfied by a block that withheld
    everything unconditionally.
    """
    returns = _measured_returns()
    published, block = _block(returns)

    assert _measures_dispersion(returns)
    for field in ("sharpe_ratio", "sortino_ratio"):
        assert isinstance(published[field], float), field
        entry = block["estimates"][field]
        assert entry["status"] == "computed", field
        assert entry["reason"] is None, field
        assert entry["conf_int"] is not None, field
        assert entry["conf_int"][0] <= entry["point"] <= entry["conf_int"][1], field
        assert entry["conf_int"][0] < entry["conf_int"][1], (
            "a measured window must produce a band with width, or the band is "
            "degenerate and this fixture cannot discriminate"
        )


def test_a_window_with_variation_but_no_downside_still_keeps_its_sharpe_band():
    """The asymmetric case the `_zero_dispersion_reason` FILTER exists for.

    Returns that vary and never undershoot the risk-free target: the Sharpe has
    a real dispersion to divide by, the Sortino denominator is a zero series.
    One leg is absent, the other must keep the band it earned - which is only
    true if the reason is filtered per field rather than applied to both.
    """
    target = ENGINE.risk_free_rate / 252
    rng = np.random.default_rng(5)
    returns = pd.Series(
        target * 4.0 + rng.uniform(0.0, 0.001, DAYS),
        index=pd.bdate_range("2024-01-02", periods=DAYS),
    )
    downside = np.minimum(0.0, returns.to_numpy(dtype=float) - target)
    assert np.unique(downside).size == 1, "the fixture must never undershoot"

    published, block = _block(returns)
    assert published["sharpe_ratio"] is not None
    assert published["sortino_ratio"] is None
    assert block["estimates"]["sharpe_ratio"]["status"] == "computed"
    assert block["estimates"]["sharpe_ratio"]["conf_int"] is not None
    assert block["estimates"]["sortino_ratio"]["status"] == "not_computed"


# ---------------------------------------------------------------------------
# What the refusal must NOT cost.
# ---------------------------------------------------------------------------

def test_the_real_measurements_beside_the_absent_ratio_still_ship():
    """Withholding the ratios must not hide the window's actual readings."""
    published, block = _block(_constant_returns())

    assert published["annual_return"] == pytest.approx(0.1764, abs=1e-9)
    assert published["annual_volatility"] == pytest.approx(
        1.7356420481756663e-18, rel=1e-9
    )
    assert published["hit_ratio"] == 1.0
    for field in ("annual_return", "annual_volatility", "hit_ratio"):
        assert block["estimates"][field]["point"] == published[field], field


def test_end_to_end_the_portfolio_block_refuses_both_ratios_on_a_flat_book():
    """The same refusal through `calculate_portfolio_metrics`, not just the core.

    Built from a price frame whose `pct_change` is a CONSTANT series.  Float
    `pct_change` of a geometric ramp gives 2-3 distinct values, so the constant
    fixture is assembled from prices that divide exactly - which is why this
    case is exercised on the core series above and the route on the fields it
    actually publishes.
    """
    index = pd.bdate_range("2024-01-02", periods=61)
    prices = pd.DataFrame({"AAA.NS": np.full(61, 100.0)}, index=index)
    metrics = asyncio.run(
        ENGINE.calculate_portfolio_metrics(prices, {"AAA.NS": 1.0})
    )
    # Every return is exactly 0.0, so the dispersion is exactly 0.0 and both
    # ratios were already refused before this wave - the end-to-end path must
    # stay refused, not drift.
    assert metrics["sharpe_ratio"] is None
    assert metrics["sortino_ratio"] is None
    assert metrics["annual_volatility"] == 0.0
    estimates = metrics["estimate_uncertainty"]["estimates"]
    assert estimates["sharpe_ratio"]["status"] == "not_computed"
    assert estimates["sortino_ratio"]["status"] == "not_computed"
    assert estimates["annual_volatility"]["status"] == "computed"


def test_the_near_constant_two_value_window_publishes_and_keeps_its_band():
    """The residual judgement, pinned so it stays a decision and not a drift.

    Two distinct values `1e-18` apart DO carry variation, so the structural
    predicate admits them and a very large Sharpe is published - honestly, with
    a correspondingly wide band.  Declining to publish would require a
    threshold, and a threshold here is a number this method did not measure.
    """
    returns = pd.Series(
        [CONSTANT_RETURN, CONSTANT_RETURN + 1e-18] * 30,
        index=pd.bdate_range("2024-01-02", periods=DAYS),
    )
    published, block = _block(returns)

    assert _measures_dispersion(returns) is True
    assert isinstance(published["sharpe_ratio"], float)
    assert published["sharpe_ratio"] > 1e15
    entry = block["estimates"]["sharpe_ratio"]
    assert entry["status"] == "computed"
    assert entry["reason"] is None
