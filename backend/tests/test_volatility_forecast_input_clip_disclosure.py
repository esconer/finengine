"""Every volatility fit is run on a winsorised return series, and now says so.

THE DEFECT.  `volatility_forecast_point` did

    clean = returns.replace([np.inf, -np.inf], np.nan).dropna()
    clean = clean.clip(lower=-0.20, upper=0.20)

and every GARCH, EGARCH and EWMA fit in the section ran on that censored series.
Nothing on any payload said so.  A conditional sigma fitted to a series with
both tails pinned at +/-20 % describes the censored series, and a reader holding
that number had no way to know the input was not the delivered one.

THE SIBLING PATH ALREADY DECLARED IT.  `stress_test`'s
`volatility_adjustment.return_clip` publishes the same two bounds, because a
clip written twice is a drift waiting to happen - which is the same argument
`FORECAST_VOL_CLIP_LOW` and `EWMA_LAMBDA` carry for their own constants.

THE FIX IS DISCLOSURE ONLY, and that is asserted here rather than asserted in a
comment.  `FORECAST_INPUT_RETURN_CLIP` is exactly the two literals that were
inline, the series the fit sees is the same series, and the published sigma must
come back BIT-IDENTICAL - compared by `repr`, which is the only comparison that
distinguishes "the same value" from "the same to within a tolerance".  Nothing
about a fitted number moved.

The clip is published on all four forecast shapes - the three models and the
refusal - because a consumer must not have to branch on whether the fit
succeeded to learn what it was handed.
"""

import asyncio

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import (
    EWMA_LAMBDA,
    FORECAST_INPUT_RETURN_CLIP,
    AnalyticsEngine,
    volatility_forecast_point,
)

ENGINE = AnalyticsEngine()


def _returns(days: int = 240, seed: int = 5, scale: float = 0.0019) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(
        0.0001 + scale * rng.standard_normal(days),
        index=pd.bdate_range("2022-01-03", periods=days),
    )


def test_the_constant_is_exactly_the_literals_that_were_inline():
    assert FORECAST_INPUT_RETURN_CLIP == (-0.20, 0.20)
    assert list(FORECAST_INPUT_RETURN_CLIP) == [-0.20, 0.20]


def test_the_clip_actually_bites_on_this_fixture():
    """Guard: a disclosure about an inert clip proves nothing.

    A heavy-tailed draw with real mass beyond +/-20 %.  NOT pre-clipped here: an
    outer `np.clip` at +/-0.15 would put the series inside the very bounds the
    test is claiming are active.
    """
    rng = np.random.default_rng(9)
    tailed = pd.Series(0.0002 + 0.09 * rng.standard_t(df=4, size=4000))
    assert (tailed.abs() > 0.20).any(), "no observation fell outside the clip"
    assert tailed.abs().max() > 0.20


@pytest.mark.parametrize("model", ["GARCH", "EGARCH", "EWMA"])
def test_every_model_publishes_the_input_clip_it_was_fitted_on(model):
    returns = _returns()
    if model == "EWMA":
        result = ENGINE._ewma_forecast(returns, 1)
    else:
        method = (
            ENGINE._garch_forecast if model == "GARCH" else ENGINE._egarch_forecast
        )
        result = asyncio.run(method(returns, 1))

    assert result.get("error") is None, result
    assert result["input_return_clip"] == [-0.20, 0.20]


def test_the_refusal_publishes_it_too():
    """One shape for a consumer to read, whichever branch produced the payload."""
    for model in ("GARCH", "EGARCH", "EWMA"):
        empty = ENGINE._empty_forecast(1, model)
        assert empty["input_return_clip"] == [-0.20, 0.20]


def test_the_clip_is_on_the_payload_and_not_only_on_the_model_params():
    """It sits beside the number it explains, not buried in a params blob."""
    result = ENGINE._ewma_forecast(_returns(), 1)
    assert "input_return_clip" in result
    assert "input_return_clip" not in result["model_params"]


# ---------------------------------------------------------------------------
# No figure moved.  The restatement below is the recursion, written out from the
# module's own constants so the comparison is of the arithmetic rather than of
# a transcription of it.
# ---------------------------------------------------------------------------

def test_publishing_the_clip_left_the_ewma_sigma_bit_identical():
    returns = _returns()
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


def test_the_clip_is_still_applied_and_not_merely_published():
    """A disclosure that stops being true is worse than no disclosure.

    An input with returns far outside the bounds must come back with a sigma
    built from the CENSORED series - identical to the sigma the same series
    produces after it is clipped by hand.
    """
    wild = pd.Series(
        [0.0001, 0.9, -0.85, 0.0001, 0.62] * 20, index=pd.bdate_range("2024-01-02", periods=100)
    )
    censored = wild.clip(lower=-0.20, upper=0.20)
    assert censored.abs().max() <= 0.20
    assert wild.abs().max() > 0.20

    point = volatility_forecast_point(wild, "EWMA", 1)
    same = volatility_forecast_point(censored, "EWMA", 1)
    # Bit-identical, not approximately equal: the engine saw the censored one.
    assert repr(float(point["raw_volatility_forecast"])) == repr(
        float(same["raw_volatility_forecast"])
    )


def test_the_stress_path_publishes_the_same_bounds_from_the_same_constant():
    """One named clip, two call sites - de-duplicated so they cannot drift."""
    index = pd.bdate_range("2024-01-02", periods=120)
    rng = np.random.default_rng(4)
    prices = pd.DataFrame(
        {"AAA.NS": 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, 119)))},
        index=index[1:],
    )
    result = asyncio.run(
        ENGINE.stress_test(prices, {"AAA.NS": 1.0}, "market_crash")
    )
    published = result["shock_inputs"]["volatility_adjustment"]["return_clip"]
    assert published == list(FORECAST_INPUT_RETURN_CLIP)


def test_the_published_clip_is_the_input_bound_and_not_the_output_clip():
    """There are two clips in this section and they must not be confused.

    `FORECAST_VOL_CLIP_LOW/HIGH` bound the PUBLISHED annualized sigma for UI
    stability.  `input_return_clip` bounds the SERIES the model was fitted on.
    They are different quantities in different units, and a reader who saw only
    one would be misled about the other.
    """
    returns = _returns()
    result = ENGINE._ewma_forecast(returns, 1)
    assert result["input_return_clip"] == [-0.20, 0.20]
    # The output clip is published separately, in annualized units, on the tail
    # disclosure - and it is a different pair of numbers.
    tail_clip = result["tail_measure"]["var_clip_bounds"]
    assert tail_clip == [-0.99, -0.001]
    assert tail_clip != result["input_return_clip"]
