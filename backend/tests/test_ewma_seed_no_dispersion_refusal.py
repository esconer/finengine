"""The EWMA recursion's seed must MEASURE a dispersion, or the fit is refused.

THE DEFECT.  `volatility_forecast_point`'s EWMA branch seeded the recursion with

    window = r[-min(len(r), 60):]
    var = float(np.var(window, ddof=1)) if len(window) > 1 else 0.0

and both arms of that conditional published a number.

ARM 1 - the `len(window) < 2` arm, which the surrounding comment claimed was
unreachable.  THAT CLAIM IS WRONG, and it is reachable through THREE paths,
which is worth enumerating because the claim is what let a stand-in seed ship:

  * `volatility_forecast_point` is called DIRECTLY, with no length gate above
    it, by `volatility_forecast_statistics` (:6942) - the resampling
    restatement - and by
    `test_forecast_precision_disclosure.py::TestTheEwmaSeedIsComputedOverThe
    WindowItRecursesOver::test_short_and_degenerate_windows_still_produce_a_
    number`, which feeds it `n = 1`.
  * `forecast_volatility` gates on the RAW series length, not the FINITE count
    (see below), so it does not close the path either.

A sample variance is undefined below two observations, so there is no value to
substitute - and 0.0 is worse than useless here, being the strongest possible
claim ("this book does not move") while remaining rankable against the
realized-vol distribution, where any non-negative p25 puts it in the CHEAP
band.  `volatility_service.calculate_ewma_volatility` already withholds on this
exact case, and this module's own seed comment says so - while two lines above
it calls 0.0 "the explicit zero-assumption contract".  Those two comments
disagree, and this file takes the second one: a published number that rests on
an assumed seed is a substituted number.

CONSEQUENCE, RECORDED RATHER THAN DISCOVERED LATER: refusing this arm makes
that pre-existing test red, because it asserts
`volatility_forecast > 0.0` for `n = 1`.  That assertion and this fix are two
answers to one question and cannot both stand.  The parent owns the choice; the
measurement needed to make it is here.

The second reachability path is the one the brief's claim missed.
`forecast_volatility` gates on the RAW series length, not the FINITE count:

    if len(returns) < 30:  # analytics_engine.py, forecast_volatility
        return self._empty_forecast(model=model.upper())

while the seed is computed from the FINITE count, because the core does
`.replace([inf, -inf], nan).dropna()` before slicing.  So 30 rows carrying ONE
finite observation reach the recursion with `len(window) == 1`.  Measured on
the pre-fix engine:

    forecast_volatility(pd.Series([nan]*29 + [0.01]), model="EWMA")
      -> volatility_forecast 0.05        <- the CLIP FLOOR
         raw_volatility_forecast 0.03888
         return_space_volatility 0.002449

A five-percent annualized volatility forecast, off a single observation.

ARM 2 - `len(window) >= 2` on a CONSTANT window.  Measured on 60 returns of
exactly 0.0007:

    np.var(window, ddof=1)  == 1.195417983887072e-38
    raw sigma               == 0.010975661038436956
    np.isfinite(raw)        == True
    published               -> volatility_forecast 0.05   <- THE CLIP FLOOR
                               return_space_volatility 6.914e-4
                               var_forecast -1.137e-3

That seed is float round-off in the subtraction.  `isfinite` passed, so the
non-finite refusal above it never fired, and the clip published the 5 % floor as
a measurement.  The display and the tail were two orders of magnitude apart:
`volatility_forecast` said 5 % annualized while `var_forecast` was computed from
a sigma of 0.010976 - a book displayed at 5 % volatility whose own VaR said
1.1e-3, i.e. about 4.5x smaller.  One of those two numbers was the clip bound
and the other was round-off, and nothing on the payload said which.

THE FIX.  One predicate, no threshold.  `_measures_dispersion(window)` is
`nunique() >= 2`, exactly equivalent to `max != min`, so "the seed measured
nothing" is a structural fact about the data and not a magnitude judgement -
which is what keeps the fix from inventing the tolerance two previous agents
declined to invent.  Both arms raise `_InsufficientForecast`, the refusal this
section already documents for "too little to fit at all", and both enclosing
handlers treat it as an absent measurement:

  * `volatility_forecast_statistics` catches per draw and counts it NaN, which
    matters here specifically: a moving-block resample of a constant series IS
    that constant series, so every one of the 1000 draws is the same refusal
    rather than the same round-off.
  * `_ewma_forecast`'s `except` returns `_empty_forecast`, where
    `volatility_forecast`, `var_forecast`, `cvar_forecast` and `tail_measure`
    are all None.

THE COUPLING THAT HAD TO BE HANDLED.  `_volatility_sizing` falls back to a
sample standard deviation when a model estimate is unusable.  With the seed now
refusing, a constant leg reaches that fallback - where `series.std(ddof=1)` is
the SAME round-off, so `inv_vols` would receive a sigma of ~1.7e-18 and the leg
would take 100 % of the book.  Refusing one leg while letting the other publish
a worse number would have traded this defect for a bigger one, so the same
predicate is applied there.
"""

import asyncio

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import (
    FORECAST_INPUT_RETURN_CLIP,
    FORECAST_VOL_CLIP_LOW,
    AnalyticsEngine,
    _InsufficientForecast,
    _measures_dispersion,
    volatility_forecast_point,
    volatility_forecast_statistics,
)

ENGINE = AnalyticsEngine()


def _constant_returns(value: float = 0.0007, days: int = 60) -> pd.Series:
    return pd.Series(
        np.full(days, value), index=pd.bdate_range("2024-01-02", periods=days)
    )


def _measured_returns(days: int = 240, seed: int = 5) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(
        0.0001 + 0.0019 * rng.standard_normal(days),
        index=pd.bdate_range("2022-01-03", periods=days),
    )


# ---------------------------------------------------------------------------
# The arithmetic the fix rests on.
# ---------------------------------------------------------------------------

def test_the_constant_window_seed_is_round_off_not_a_variance():
    """1.19e-38 is the subtraction's error, not the book's volatility."""
    window = _constant_returns().to_numpy(dtype=float)
    seed = float(np.var(window, ddof=1))
    assert seed == pytest.approx(1.195417983887072e-38, rel=1e-9)
    assert seed != 0.0
    # So `isfinite` never fired, which is why the clip floor got published.
    assert np.isfinite(float(np.sqrt(seed * 252)))


def test_a_single_observation_would_be_scored_at_the_clip_floor():
    """The pre-fix output, so the size of the defect is on the record."""
    # Pre-fix, `len(window) == 1` seeded var = 0.0 and the recursion gave this.
    var = 0.0
    var = 0.94 * var + 0.06 * (0.01 ** 2)
    raw = float(np.sqrt(var * 252))
    assert raw == pytest.approx(0.03888444419044718, rel=1e-9)
    assert float(np.clip(raw, FORECAST_VOL_CLIP_LOW, 1.20)) == FORECAST_VOL_CLIP_LOW


def test_the_len_less_than_two_arm_is_reachable_through_forecast_volatility():
    """The comment's unreachability claim, corrected by measurement.

    `forecast_volatility` gates RAW length at 30 and the core counts FINITE
    values, so 30 rows with one usable observation get through.  This is the
    exact call, and it is why the arm is now handled rather than documented as
    dead.
    """
    mostly_missing = pd.Series(
        [np.nan] * 29 + [0.01], index=pd.bdate_range("2024-01-02", periods=30)
    )
    assert len(mostly_missing) >= 30, "the raw gate must be satisfied"
    finite = mostly_missing.replace([np.inf, -np.inf], np.nan).dropna()
    assert len(finite) == 1, "the fixture must leave exactly one usable row"

    result = asyncio.run(
        ENGINE.forecast_volatility(mostly_missing, model="EWMA", horizon=1)
    )
    assert result["volatility_forecast"] is None
    assert result["var_forecast"] is None
    assert result["cvar_forecast"] is None
    assert result["tail_measure"] is None
    assert result["error"]


def test_the_core_itself_refuses_rather_than_substituting():
    """Directly, with no length gate above it at all - the restatement's path."""
    with pytest.raises(_InsufficientForecast):
        volatility_forecast_point(pd.Series([0.01]), "EWMA", 1)
    with pytest.raises(_InsufficientForecast):
        volatility_forecast_point(_constant_returns(), "EWMA", 1)


# ---------------------------------------------------------------------------
# Arm 2: the constant window, end to end.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("horizon", [1, 5, 21])
def test_a_constant_window_publishes_no_forecast_at_all(horizon):
    """Nothing is published, not the clip floor and not a zero."""
    result = ENGINE._ewma_forecast(_constant_returns(), horizon)
    for field in ("volatility_forecast", "var_forecast", "cvar_forecast",
                  "tail_measure", "term_structure", "model_params"):
        assert result[field] is None, field
    assert result["error"]
    # The model is still named: the reader knows which fit declined.
    assert result["model"] == "EWMA"


def test_the_constant_window_is_the_case_where_display_and_tail_disagreed():
    """Why the refusal, stated as the disagreement the reader would have seen.

    Pre-fix on this window: `volatility_forecast` 0.05 and `var_forecast`
    -1.1374e-3.  The first is the clip floor - the recursion's own sigma was
    0.010976 - and the second was computed from that raw sigma.  The display was
    about 4.4x the volatility the tail was built on.
    """
    window = _constant_returns().to_numpy(dtype=float)
    var = float(np.var(window, ddof=1))
    for x in window:
        var = 0.94 * var + 0.06 * x * x
    raw = float(np.sqrt(var * 252))
    published = float(np.clip(raw, FORECAST_VOL_CLIP_LOW, 1.20))

    assert published == FORECAST_VOL_CLIP_LOW
    assert raw < FORECAST_VOL_CLIP_LOW
    tail_var = -raw / np.sqrt(252.0) * 1.645
    display_var = -FORECAST_VOL_CLIP_LOW / np.sqrt(252.0) * 1.645
    assert tail_var != pytest.approx(display_var, rel=1e-6)
    assert abs(display_var) / abs(tail_var) == pytest.approx(4.5555, rel=1e-4)


def test_the_resampling_restatement_counts_every_draw_as_absent():
    """A moving-block resample of a constant series is that constant series.

    So the restatement cannot produce a band out of this window - not because
    the draws vary wildly but because every one of them is the same refusal.
    """
    statistic = volatility_forecast_statistics("EWMA", 1)
    block = np.column_stack([_constant_returns().to_numpy(dtype=float)])
    out = statistic(block)
    for name in ("volatility_forecast", "return_space_volatility"):
        assert np.isnan(out[name]).all(), name


def test_the_resampling_restatement_still_measures_a_real_window():
    """Guard: the fixture above would also pass on an always-NaN statistic."""
    statistic = volatility_forecast_statistics("EWMA", 1)
    values = _measured_returns().to_numpy(dtype=float)
    block = np.column_stack([values, values * 1.1, values * 0.9])
    out = statistic(block)
    assert np.isfinite(out["volatility_forecast"]).sum() >= 1
    assert out["volatility_forecast"][0] > 0.0


# ---------------------------------------------------------------------------
# What must not move.
# ---------------------------------------------------------------------------

def test_a_genuinely_measured_low_volatility_book_is_untouched():
    """The whole point of the fix: it fires on absence, not on smallness.

    `daily_vol = 0.0019` is a real ~2.8 % annualized book, well under the 5 %
    clip floor, so the clip still bites - and the recursion's own sigma is a
    measurement, so nothing is refused.
    """
    returns = _measured_returns()
    point = volatility_forecast_point(returns, "EWMA", 1)

    assert _measures_dispersion(returns)
    raw = float(point["raw_volatility_forecast"])
    assert raw < FORECAST_VOL_CLIP_LOW, (
        "the fixture must produce a sigma the clip actually moves, or this "
        "test proves nothing"
    )
    assert float(point["volatility_forecast"]) == FORECAST_VOL_CLIP_LOW
    assert point["return_space_volatility"] == pytest.approx(raw * np.sqrt(1 / 252.0))
    assert ENGINE._ewma_forecast(returns, 1)["volatility_forecast"] is not None


def test_a_two_value_window_is_still_fitted():
    """`nunique() >= 2` means `max != min`; it does not mean "big enough"."""
    returns = pd.Series(
        [0.0007, 0.0007 + 1e-18] * 30, index=pd.bdate_range("2024-01-02", periods=60)
    )
    point = volatility_forecast_point(returns, "EWMA", 1)
    assert np.isfinite(float(point["raw_volatility_forecast"]))
    assert ENGINE._ewma_forecast(returns, 1)["volatility_forecast"] is not None


def test_the_input_clip_is_published_on_every_forecast_shape():
    """WM-9, asserted here because it is the same function."""
    returns = _measured_returns()
    expected = list(FORECAST_INPUT_RETURN_CLIP)
    assert expected == [-0.20, 0.20]
    assert ENGINE._ewma_forecast(returns, 1)["input_return_clip"] == expected
    assert asyncio.run(ENGINE._garch_forecast(returns, 1))["input_return_clip"] == expected
    assert asyncio.run(ENGINE._egarch_forecast(returns, 1))["input_return_clip"] == expected
    assert ENGINE._empty_forecast(1, "EWMA")["input_return_clip"] == expected


def test_publishing_the_clip_moved_no_number():
    """WM-9 is disclosure only: the fitted sigma is bit-identical.

    `FORECAST_INPUT_RETURN_CLIP` is (-0.20, 0.20) - the two literals that were
    inline - so the series the fit sees is the same series, and the published
    sigma must be the same float, not merely close.  Compared by `repr`, which
    is the only comparison that distinguishes "same value" from "same to within
    a rounding tolerance", and the recursion is restated from the module's own
    `EWMA_LAMBDA` so the comparison is of the arithmetic rather than of my
    transcription of it.
    """
    from app.services.analytics_engine import EWMA_LAMBDA

    returns = _measured_returns()
    clipped = returns.clip(
        lower=FORECAST_INPUT_RETURN_CLIP[0], upper=FORECAST_INPUT_RETURN_CLIP[1]
    )
    window = clipped.to_numpy(dtype=float)[-60:]
    var = float(np.var(window, ddof=1))
    for x in window:
        var = EWMA_LAMBDA * var + (1.0 - EWMA_LAMBDA) * x * x

    point = volatility_forecast_point(returns, "EWMA", 1)
    assert repr(float(point["raw_volatility_forecast"])) == repr(
        float(np.sqrt(var * 252))
    )


# ---------------------------------------------------------------------------
# The sizing fallback, which is the coupling.
# ---------------------------------------------------------------------------

def test_a_constant_non_zero_return_series_is_not_constructible_from_prices():
    """Why the coupling guard below is defence in depth, stated as a measurement.

    `_volatility_sizing` is handed PRICES, and `pct_change` of a price frame
    built to drift by a constant 0.0007 a day never returns a constant series:
    the cumprod rounds, so the realised returns carry 2-3 distinct values at
    every length tried.  The structural predicate is `nunique() >= 2`, so such a
    series is (correctly) treated as carrying variation.

    The consequence for this wave is a scope statement, not a coverage gap in
    the guard: the fallback branch below is reached on a real price frame only
    through a FLAT one, where the returns are exactly 0.0 and the dispersion is
    exactly zero - a case the downstream `sigma > 0` parity test already
    excluded.  The guard is kept because it is the same structural fact and
    costs nothing, and because the moment a caller supplies a returns series
    directly rather than a price frame, this is the line that stops a 1.7e-18
    sigma from winning an inverse-volatility allocation.
    """
    for length in (5, 10, 15, 20, 22, 25, 40, 89):
        prices = 100.0 * np.exp(np.cumsum(np.full(length, 0.0007)))
        realised = pd.Series(prices).pct_change().dropna()
        assert realised.nunique() > 1, (
            f"n={length} unexpectedly produced a constant return series; if "
            "this ever holds the reachability statement above needs revisiting"
        )
        assert _measures_dispersion(realised) is True


def test_the_sizing_fallback_refuses_a_window_that_measures_no_dispersion():
    """The coupling: the fallback must not be the way round-off gets in.

    The flat leg's returns are exactly 0.0, so BOTH paths are exercised - the
    EWMA seed refuses (no dispersion) and the sample-volatility fallback is the
    only thing left.  Pre-fix that fallback published 0.0, which is finite and
    non-negative and therefore passed the `vol >= 0` filter, putting the leg
    into `volatilities` and into the portfolio-volatility quadratic form with a
    zero marginal.  Post-fix it publishes nothing for that leg at all.
    """
    days = 90
    index = pd.bdate_range("2024-01-02", periods=days)
    prices = pd.DataFrame(
        {
            "FLAT.NS": np.full(days, 100.0),
            "REAL.NS": np.concatenate(
                [
                    [100.0],
                    100.0
                    * np.exp(
                        np.cumsum(
                            np.random.default_rng(1).normal(0.0003, 0.012, days - 1)
                        )
                    ),
                ]
            ),
        },
        index=index,
    )
    flat_returns = prices["FLAT.NS"].pct_change().dropna()
    assert _measures_dispersion(flat_returns) is False, "the fixture must be flat"

    result = asyncio.run(ENGINE.volatility_sizing(prices, {"FLAT.NS": 0.5, "REAL.NS": 0.5}))
    assert "volatilities" in result, "the payload must expose which legs it used"
    volatilities = result["volatilities"]
    if volatilities:
        # The round-off leg is not in it, under any spelling.
        assert "FLAT.NS" not in volatilities, (
            "a window that measures no dispersion published a volatility"
        )
        for value in volatilities.values():
            assert np.isfinite(value) and value > 0.0
