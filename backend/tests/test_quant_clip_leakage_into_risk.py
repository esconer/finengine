"""A display clip must not become a risk measure.

Both defects here are the same mistake in two places: a number that was
clipped or floored for DISPLAY was then reused as if it were the measurement,
so the published figure described a different quantity than its name claims.

  * QM-6  the EWMA branch derived `return_space_volatility` -- and therefore
          VaR and CVaR -- from the **clipped** annualized sigma, while the
          GARCH and EGARCH branches derived theirs from the **raw** one.  A
          2.8 %-volatility book published a VaR computed from the 5 % floor,
          1.73x high, and the two branches disagreed on identical input.
          `volatility_sizing` already made the raw/clipped distinction for
          inverse-volatility parity (:4628); the tail block did not.

  * QM-2  `adjusted_r_squared` was published as `max(0.0, rsquared_adj)`, so
          every fit worse than the sample mean reported exactly `0.0` -- the
          value a perfect fit of nothing would also report.  The negative
          value is the informative one.

Each test states the CAUSE, so a fixture that stops exercising the clip fails
rather than passing silently.
"""

import asyncio

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from app.services import analytics_engine as engine_mod
from app.services.analytics_engine import (
    AnalyticsEngine,
    FORECAST_VOL_CLIP_HIGH,
    FORECAST_VOL_CLIP_LOW,
    TAIL_CLIP_HIGH,
    TAIL_CLIP_LOW,
    TAIL_ES_MULTIPLIER,
    TAIL_Z_MULTIPLIER,
    volatility_forecast_point,
)


def _low_vol_returns(n: int = 240, seed: int = 11) -> pd.Series:
    """A genuinely low-volatility book, well under the 5 % annualized floor.

    `daily_vol=0.0019` gives ~2.8 % annualized, so the recursion's own sigma
    lands below `FORECAST_VOL_CLIP_LOW` and the clip is guaranteed to bite.
    """
    rng = np.random.default_rng(seed)
    return pd.Series(
        0.0001 + 0.0019 * rng.standard_normal(n),
        index=pd.bdate_range("2022-01-03", periods=n),
    )


def _high_vol_returns(n: int = 240, seed: int = 5) -> pd.Series:
    """A ~14 % book: above the floor, so the clip is inert and the raw sigma
    is published unchanged.  This is the guard against over-correcting."""
    rng = np.random.default_rng(seed)
    return pd.Series(
        np.clip(0.0002 + 0.009 * rng.standard_t(df=9, size=n), -0.15, 0.15),
        index=pd.bdate_range("2022-01-03", periods=n),
    )


def _portfolio_and_benchmark(
    n: int, target_r2: float, seed: int = 7
) -> tuple[pd.Series, pd.Series]:
    """A benchmark and a portfolio whose OLS R2 against it is ~`target_r2`."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2024-01-01", periods=n + 1)[1:]
    bench = pd.Series(rng.standard_normal(n), index=index)
    beta = 0.5
    noise_sd = np.sqrt(
        beta**2 * bench.var(ddof=1) / max(target_r2, 1e-12) * (1.0 - target_r2)
    )
    port = pd.Series(
        beta * bench + noise_sd * rng.standard_normal(n), index=index
    )
    return port, bench


# ---------------------------------------------------------------------------
# QM-6 -- the derived risk measure uses the raw sigma on every branch
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("horizon", [1, 5, 21])
def test_the_ewma_core_derives_its_return_space_volatility_from_the_raw_sigma(
    horizon,
):
    """The GARCH/EGARCH convention, applied to the third branch.

    `return_space_volatility` is the ONLY input to VaR/CVaR, so building it
    from the clipped annualized path is what published a floored VaR.
    """
    returns = _low_vol_returns()
    point = volatility_forecast_point(returns, "EWMA", horizon)

    raw = float(point["raw_volatility_forecast"])
    assert raw < FORECAST_VOL_CLIP_LOW, (
        "the fixture must produce a sigma the clip actually moves, or this "
        "test proves nothing"
    )
    expected = raw * np.sqrt(horizon / 252.0)
    assert float(point["return_space_volatility"]) == pytest.approx(expected), (
        "EWMA's return-space sigma is built from the clipped annualized path, "
        "not the raw recursion output"
    )


def test_the_ewma_published_var_is_not_the_five_percent_floor_on_a_low_vol_book():
    """The defect as a reader would meet it.

    Measured on the pre-fix engine: EWMA VaR was -0.00518126, which is exactly
    `-0.05/sqrt(252) * 1.645` -- the 5 % floor's VaR -- while the raw sigma's
    VaR on the same 240 rows was -0.00298908.
    """
    returns = _low_vol_returns()
    result = AnalyticsEngine()._ewma_forecast(returns, 1)
    tail = result["tail_measure"]

    raw_var = (
        -float(result["raw_volatility_forecast"]) / np.sqrt(252.0)
        * TAIL_Z_MULTIPLIER
    )
    floor_var = (
        -FORECAST_VOL_CLIP_LOW / np.sqrt(252.0) * TAIL_Z_MULTIPLIER
    )
    assert result["var_forecast"] == pytest.approx(raw_var), (
        "EWMA VaR is not the raw sigma's VaR"
    )
    assert result["var_forecast"] != pytest.approx(floor_var), (
        "EWMA VaR is still the 5 % floor's VaR on a low-volatility book"
    )
    assert result["cvar_forecast"] == pytest.approx(
        -float(tail["return_space_volatility"]) * TAIL_ES_MULTIPLIER
    )


@pytest.mark.parametrize("horizon", [1, 10])
def test_every_branch_derives_its_tail_by_the_same_rule_on_the_same_input(
    horizon,
):
    """EWMA and GARCH on IDENTICAL rows must agree on the RULE, not the value.

    They are different models, so their sigmas legitimately differ; what must
    not differ is the convention.  Asserted as the two rules the GARCH branch
    already satisfied and the EWMA branch did not.
    """
    returns = _low_vol_returns()
    for model in ("EWMA", "GARCH"):
        point = volatility_forecast_point(returns, model, horizon)
        raw = float(point["raw_volatility_forecast"])
        expected = raw * np.sqrt(horizon / 252.0)
        assert float(point["return_space_volatility"]) == pytest.approx(
            expected
        ), f"{model} breaks the raw-sigma convention"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["EWMA", "GARCH", "EGARCH"])
async def test_each_published_branch_measures_its_tail_from_return_space_volatility(
    model,
):
    """`var == -rsv * Z` for all three, the invariant GARCH always held."""
    returns = _low_vol_returns()
    method = getattr(AnalyticsEngine(), f"_{model.lower()}_forecast")
    result = method(returns, 1)
    if asyncio.iscoroutine(result):
        result = await result
    tail = result["tail_measure"]
    if tail is None:
        pytest.skip(f"{model} could not fit this fixture")
    rsv = float(tail["return_space_volatility"])
    lo, hi = (TAIL_CLIP_LOW, TAIL_CLIP_HIGH)
    assert result["var_forecast"] == pytest.approx(
        float(np.clip(-rsv * TAIL_Z_MULTIPLIER, lo, hi))
    )
    assert result["cvar_forecast"] == pytest.approx(
        float(np.clip(-rsv * TAIL_ES_MULTIPLIER, lo, hi))
    )


@pytest.mark.parametrize("horizon", [1, 5, 21])
def test_the_published_ewma_branch_carries_the_raw_sigma_to_the_tail(horizon):
    """`_ewma_forecast` at h>1, not just the core.

    The old code multiplied the CLIPPED annualized sigma by `sqrt(h/252)`
    inside this method, so the h>1 tail was floored independently of the core
    -- a second site, not a consequence of the first.
    """
    returns = _low_vol_returns()
    result = AnalyticsEngine()._ewma_forecast(returns, horizon)
    tail = result["tail_measure"]
    raw = float(result["raw_volatility_forecast"])
    expected = raw * np.sqrt(horizon / 252.0)

    assert raw < FORECAST_VOL_CLIP_LOW, "the fixture must sit below the floor"
    assert float(tail["return_space_volatility"]) == pytest.approx(expected), (
        "the published EWMA tail is not the raw sigma's return-space sigma"
    )
    assert result["var_forecast"] == pytest.approx(
        float(np.clip(-expected * TAIL_Z_MULTIPLIER, TAIL_CLIP_LOW, TAIL_CLIP_HIGH))
    )
    assert result["cvar_forecast"] == pytest.approx(
        float(np.clip(-expected * TAIL_ES_MULTIPLIER, TAIL_CLIP_LOW, TAIL_CLIP_HIGH))
    )
    # ... while the public field keeps its UI bound at every horizon.
    assert result["volatility_forecast"] == pytest.approx(FORECAST_VOL_CLIP_LOW)


def test_the_public_volatility_forecast_stays_clipped_on_a_low_vol_book():
    """The clip is NOT the defect.  Removing it from the public field would
    move a published figure that was already correct."""
    returns = _low_vol_returns()
    result = AnalyticsEngine()._ewma_forecast(returns, 1)
    assert float(result["volatility_forecast"]) == pytest.approx(
        FORECAST_VOL_CLIP_LOW
    ), "the public clipped field moved; only the derived measure should change"
    assert result["term_structure"] == [FORECAST_VOL_CLIP_LOW]


def test_the_high_vol_book_is_untouched_by_the_fix():
    """A book above the floor publishes raw == clipped, so nothing may move."""
    returns = _high_vol_returns()
    point = volatility_forecast_point(returns, "EWMA", 1)
    assert float(point["raw_volatility_forecast"]) > FORECAST_VOL_CLIP_LOW, (
        "the fixture must sit above the floor or it proves nothing"
    )
    assert float(point["volatility_forecast"]) == pytest.approx(
        float(point["raw_volatility_forecast"])
    )
    assert float(point["return_space_volatility"]) == pytest.approx(
        float(point["raw_volatility_forecast"]) / np.sqrt(252.0)
    )


def test_the_high_cap_still_applies_to_the_public_field_not_to_the_tail():
    """The cap direction: a >120 % sigma publishes the raw VaR, not a capped
    one.  TAIL_CLIP_HIGH bounds the LOSS side, which the raw sigma must reach
    before the cap would start hiding it."""
    rng = np.random.default_rng(3)
    wild = pd.Series(
        0.0 + 0.5 * rng.standard_normal(300),
        index=pd.bdate_range("2022-01-03", periods=300),
    )
    point = volatility_forecast_point(wild, "EWMA", 1)
    raw = float(point["raw_volatility_forecast"])
    assert raw > FORECAST_VOL_CLIP_HIGH, "the fixture must exceed the cap"
    assert float(point["volatility_forecast"]) == pytest.approx(
        FORECAST_VOL_CLIP_HIGH
    ), "the public field must stay capped"
    assert float(point["return_space_volatility"]) == pytest.approx(
        raw / np.sqrt(252.0)
    ), "the derived measure must be the uncapped sigma"


def test_the_ewma_forecast_refuses_a_missing_raw_sigma(monkeypatch):
    """Never fabricate: a core that publishes no usable raw sigma must
    produce the engine's empty contract, not the clipped number back."""
    real = engine_mod.volatility_forecast_point

    def _no_raw(returns, model="EWMA", horizon=1):
        point = dict(real(returns, model, horizon))
        point["raw_volatility_forecast"] = None
        return point

    monkeypatch.setattr(engine_mod, "volatility_forecast_point", _no_raw)
    result = AnalyticsEngine()._ewma_forecast(_low_vol_returns(), 1)
    assert result["tail_measure"] is None, (
        "a missing raw sigma was substituted rather than refused"
    )
    assert result["var_forecast"] is None
    assert result["cvar_forecast"] is None


def test_the_ewma_forecast_refuses_a_non_finite_raw_sigma(monkeypatch):
    """`np.isfinite`, not the builtin: `min(5.9, nan)` is 5.9, so a naive
    clamp would quietly hand back the clipped value."""
    real = engine_mod.volatility_forecast_point

    def _nan_raw(returns, model="EWMA", horizon=1):
        point = dict(real(returns, model, horizon))
        point["raw_volatility_forecast"] = float("nan")
        return point

    monkeypatch.setattr(engine_mod, "volatility_forecast_point", _nan_raw)
    result = AnalyticsEngine()._ewma_forecast(_low_vol_returns(), 1)
    assert result["tail_measure"] is None, (
        "a NaN raw sigma was substituted rather than refused"
    )
    assert result["var_forecast"] is None


def test_the_core_refuses_a_non_finite_sigma_rather_than_clipping_it(
    monkeypatch,
):
    """A non-finite raw sigma must raise, not become the 5 % floor.

    `volatility_sizing` reads `raw_volatility_forecast` for its parity, so a
    non-finite raw that quietly became the floor would publish a fabricated
    allocation beside a real-looking risk measure.  `+inf` is the input that
    actually reaches the guard: the recursion seeds from `np.var`, and the
    builtin `max(0.0, nan)` returns `0.0`, which would quietly turn a NaN into
    a legitimate-looking zero rather than raising.
    """
    monkeypatch.setattr(np, "var", lambda *a, **k: float("inf"))
    with pytest.raises(ValueError, match="non-finite sigma"):
        volatility_forecast_point(_low_vol_returns(), "EWMA", 1)


def test_the_builtin_max_that_seeds_the_recursion_swallows_a_nan():
    """Documents the trap this branch sits next to, so the guard above is not
    read as redundant: `max(0.0, nan)` is `0.0`, not `nan`."""
    assert max(0.0, float("nan")) == 0.0
    assert np.minimum(0.0, float("nan")) != np.minimum(0.0, float("nan"))


# ---------------------------------------------------------------------------
# QM-2 -- a negative adjusted R-squared is published, not clipped to 0.0
# ---------------------------------------------------------------------------

def test_the_engine_reachable_minimum_fit_sample_is_eleven_rows():
    """The floor that sets the negative threshold.

    `_calculate_factor_exposures` is gated by `len(common_dates) > 10`, so 10
    rows never reaches the fit at all and 11 is the smallest sample the engine
    can publish -- which puts the adjusted-R2 sign boundary at 1/(n-1) = 0.10,
    not at 1/(n-1) = 0.111 as a naive "n=10" reading would suggest.
    """
    fitted_samples = {}
    for n in (9, 10, 11, 12):
        port, bench = _portfolio_and_benchmark(n, 0.5)
        out = AnalyticsEngine()._calculate_factor_exposures(
            pd.DataFrame({"AAA": port}), bench, {"AAA": 1.0}
        )
        fitted_samples[n] = out.get("adjusted_r_squared") is not None
    assert fitted_samples == {9: False, 10: False, 11: True, 12: True}, (
        "the fixture no longer separates 'below the gate' from 'above it'"
    )


@pytest.mark.parametrize("target_r2", [0.02, 0.05, 0.09])
def test_a_negative_adjusted_r_squared_is_published_not_clipped_to_zero(
    target_r2,
):
    """The defect: a model explaining 5 % of variance published `0.0`, which is
    also what a fit explaining NONE would publish, and what a reader taking 0
    as the boundary of "no explanatory power" reads as a perfect outcome."""
    port, bench = _portfolio_and_benchmark(11, target_r2)
    out = AnalyticsEngine()._calculate_factor_exposures(
        pd.DataFrame({"AAA": port}), bench, {"AAA": 1.0}
    )
    published = out["adjusted_r_squared"]

    assert out["r_squared"] < 1.0 / 10.0, (
        "the fixture must be a fit whose adjusted R2 is genuinely negative"
    )
    assert published < 0.0, (
        "adjusted R2 was published as 0.0 for a fit worse than the mean"
    )
    assert published != 0.0, "0.0 is indistinguishable from the clip"
    assert published == pytest.approx(
        float(sm.OLS(port, sm.add_constant(bench)).fit().rsquared_adj), abs=5e-5
    )


def test_the_adjusted_r_squared_identity_survives_on_a_negative_fit():
    """The invariant the repo ALREADY asserts, which the clip broke.

    `tests/test_model_sample_and_aggregation_disclosure.py` solves
    `1-(1-R^2)(n-1)/(n-2)` for the published pair.  That identity holds only
    for the unclipped value: at n=11, R^2=0.0276 the true adjusted is -0.0804,
    the clip published 0.0, and the residual was 8.04e-02 against a 5e-4
    tolerance.
    """
    port, bench = _portfolio_and_benchmark(11, 0.05)
    out = AnalyticsEngine()._calculate_factor_exposures(
        pd.DataFrame({"AAA": port}), bench, {"AAA": 1.0}
    )
    n = int(out["portfolio"]["observations"])
    r_squared = float(out["r_squared"])
    adjusted = float(out["adjusted_r_squared"])

    assert adjusted < 0.0, "the fixture must exercise the negative branch"
    predicted = 1.0 - (1.0 - r_squared) * (n - 1) / (n - 2)
    assert abs(predicted - adjusted) < 5e-4, (
        "the published adjusted R2 is not the one this sample was fitted on"
    )


def test_a_positive_adjusted_r_squared_is_unchanged():
    """The guard against over-correcting: a fit that was already right must
    publish exactly what it published before."""
    port, bench = _portfolio_and_benchmark(60, 0.10)
    out = AnalyticsEngine()._calculate_factor_exposures(
        pd.DataFrame({"AAA": port}), bench, {"AAA": 1.0}
    )
    true_adj = float(sm.OLS(port, sm.add_constant(bench)).fit().rsquared_adj)
    assert true_adj > 0.0, "the fixture must sit in the unclipped region"
    assert float(out["adjusted_r_squared"]) == pytest.approx(
        round(true_adj, 4), abs=1e-9
    )
    assert max(0.0, round(true_adj, 4)) == round(true_adj, 4), (
        "the clip would have been inert here, so the fixture proves nothing"
    )


def test_adjusted_r_squared_never_exceeds_raw_r_squared():
    """The pair invariant the audit rule `adjusted_r_squared_exceeds_r_squared`
    checks, on the negative side: a negative is trivially below any R^2."""
    port, bench = _portfolio_and_benchmark(11, 0.05)
    out = AnalyticsEngine()._calculate_factor_exposures(
        pd.DataFrame({"AAA": port}), bench, {"AAA": 1.0}
    )
    assert float(out["adjusted_r_squared"]) <= float(out["r_squared"])


def test_a_fit_below_the_floor_still_publishes_none_not_zero():
    """The not-fitted contract is untouched: absence stays absence, and is
    still distinguishable from the measured 0.0 the clip used to invent."""
    index = pd.bdate_range("2024-01-01", periods=3)
    out = AnalyticsEngine()._calculate_factor_exposures(
        pd.DataFrame({"AAA": pd.Series([0.01, -0.02, 0.03], index=index)}),
        pd.Series([0.01, -0.02, 0.03], index=index),
        {"AAA": 1.0},
    )
    assert out["adjusted_r_squared"] is None
    assert out["r_squared"] is None
    assert out["error"] == "insufficient data for factor regression"