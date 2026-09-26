"""Meaning-of-the-number regressions for the quant analytics engine.

Each test here exists because a published figure was arithmetically correct
while describing the wrong quantity.  The arithmetic is deliberately left
alone in every case; what is asserted is that the number is the quantity its
name says it is, or that it is absent with a reason.

  * QM-1  a date on which only one constituent traded must never be published
          as a portfolio return under the portfolio's name.
  * SI-3  `confidence_interval` must be a real interval or null -- never a
          fixed +/-20 % band around the point forecast.
  * QM-4  `achieved_volatility` must be a measurement, not the target
          restated.
  * AD-2  the tail fields must declare their level, units and basis.
  * SI-9  a computed HAC covariance must be published, or the fit must say it
          is uncorrected.
"""

import json
import math

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm

from app.services.analytics_engine import (
    AnalyticsEngine,
    PORTFOLIO_RETURN_MIN_COVERAGE,
    TAIL_CONFIDENCE_LEVEL,
    TAIL_ES_MULTIPLIER,
    TAIL_Z_MULTIPLIER,
    active_return_coverage,
    aggregate_active_returns,
    portfolio_return_coverage_block,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _returns_with_sparse_tail(n_days: int = 90, seed: int = 7) -> pd.DataFrame:
    """Three legs trading every day, then a four-day tail in which only one
    leg still has a bar -- the shape that produced a one-stock terminal
    observation standing in for the whole book."""
    idx = pd.bdate_range("2024-01-02", periods=n_days)
    rng = np.random.default_rng(seed)
    frame = pd.DataFrame(
        {
            "AAA": rng.normal(0.0004, 0.008, n_days),
            "BBB": rng.normal(0.0002, 0.011, n_days),
            "CCC": rng.normal(-0.0001, 0.014, n_days),
        },
        index=idx,
    )
    frame.iloc[-4:, 1:] = np.nan       # last 4 days: one constituent of three
    return frame


def _returns_with_no_coverage(n_days: int = 30) -> pd.DataFrame:
    """A frame where no date is a full basket, and the last date has no
    covered weight at all (the old contract omitted those outright)."""
    idx = pd.bdate_range("2024-01-02", periods=n_days)
    frame = pd.DataFrame(
        {
            "AAA": np.full(n_days, 0.001),
            "BBB": np.full(n_days, np.nan),
        },
        index=idx,
    )
    frame.iloc[-1, :] = np.nan
    return frame


def _weights() -> dict:
    return {"AAA": 0.5, "BBB": 0.3, "CCC": 0.2}


def _price_frame(n_days: int = 200, seed: int = 11) -> pd.DataFrame:
    idx = pd.bdate_range("2023-01-02", periods=n_days)
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.010, (n_days, 3)), axis=0)),
        index=idx,
        columns=["A", "B", "C"],
    )


def _price_from_returns(returns: pd.DataFrame) -> pd.DataFrame:
    """Invert a return frame into prices; a NaN return becomes a NaN price."""
    prices = (1.0 + returns).cumprod() * 100.0
    prices.iloc[0] = 100.0
    return prices


def _long_returns(n: int = 240, seed: int = 5) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(
        np.clip(0.0002 + 0.009 * rng.standard_t(df=9, size=n), -0.15, 0.15),
        index=pd.bdate_range("2022-01-03", periods=n),
    )


# ---------------------------------------------------------------------------
# QM-1 -- a partial basket is not the portfolio
# ---------------------------------------------------------------------------

def test_single_constituent_day_never_becomes_a_portfolio_return():
    """The published series must not end on a one-leg day, nor contain it."""
    frame = _returns_with_sparse_tail()
    weights = _weights()
    published = aggregate_active_returns(frame, weights)

    last_date = frame.index[-1]
    coverage = active_return_coverage(frame, weights)
    assert bool(coverage["published"].iloc[-1]) is False
    assert int(coverage["constituent_count"].iloc[-1]) == 1
    assert last_date not in published.index
    # the lone constituent's own returns are nowhere in the series
    for value in frame["AAA"].iloc[-4:]:
        assert not np.isclose(published.to_numpy(), float(value)).any()


def test_partial_day_is_dropped_not_zero_filled():
    """A short day is absent. It is never converted into a 0.0 % day."""
    frame = _returns_with_sparse_tail()
    published = aggregate_active_returns(frame, _weights())
    coverage = active_return_coverage(frame, _weights())

    for date, row in coverage.iterrows():
        if not row["published"]:
            assert date not in published.index
    assert int((~coverage["published"]).sum()) == 4
    assert len(published) == len(frame) - 4


def test_published_day_uses_full_book_weights_without_renormalisation():
    """On a fully covered date the day's return is the whole-book weighted sum.

    If a caller widened the gate the weights must still not be renormalised
    silently -- `min_coverage=0` is the only way to get the old behaviour, and
    it has to be asked for.
    """
    frame = _returns_with_sparse_tail()
    weights = _weights()
    published = aggregate_active_returns(frame, weights)

    full = active_return_coverage(frame, weights)
    full = full[full["published"]]
    assert np.allclose(full["covered_weight_fraction"].to_numpy(), 1.0)
    assert full["renormalization_uplift"].max() == pytest.approx(1.0)

    vector = pd.Series(weights)
    expected = frame.loc[published.index].fillna(0.0).mul(vector, axis=1).sum(axis=1)
    assert published.to_numpy() == pytest.approx(expected.to_numpy())


def test_min_coverage_zero_reproduces_the_renormalised_series():
    """The gate is the whole difference, and it is a parameter.

    Proves the contract was changed deliberately and reversibly rather than by
    accident, and gives a caller who genuinely wants a partial basket a
    declared way to ask for one.
    """
    frame = _returns_with_sparse_tail()
    weights = _weights()
    gated = aggregate_active_returns(frame, weights)
    opened = aggregate_active_returns(frame, weights, 0.0)

    assert len(opened) > len(gated)
    assert gated.index.isin(opened.index).all()
    assert gated.to_numpy() == pytest.approx(
        opened.loc[gated.index].to_numpy()
    )


def test_coverage_block_publishes_constituent_count_and_weight_fraction():
    """The dropped dates must be visible, with the size of the distortion."""
    frame = _returns_with_sparse_tail()
    weights = _weights()
    block = portfolio_return_coverage_block(frame, weights)

    assert block["min_covered_weight_fraction"] == PORTFOLIO_RETURN_MIN_COVERAGE
    assert block["total_dates"] == len(frame)
    assert block["published_dates"] + block["dropped_dates"] == len(frame)
    assert block["min_published_constituent_count"] == 3
    assert block["max_published_renormalization_uplift"] == pytest.approx(1.0)
    # named for a reader (or an audit rule) that greps for the defect
    assert block["renorm"] == "not_applied"
    assert block["partial_basket_days"] == block["dropped_dates"]
    # the final day carries 1 of 3 legs: the old rule inflated it 2x
    assert block["dates"][-1]["published"] is False
    assert block["dates"][-1]["constituent_count"] == 1
    assert block["dates"][-1]["covered_weight_fraction"] == pytest.approx(0.5)
    assert block["max_dropped_renormalization_uplift"] == pytest.approx(2.0)
    assert block["max_dropped_covered_weight_fraction"] == pytest.approx(0.5)
    assert len(block["dates"]) == len(frame)
    # every published value is JSON-safe: no Infinity, ever
    json.dumps(block)


def test_date_with_no_covered_weight_reports_no_uplift():
    """`Infinity` is not valid JSON, and a 0-coverage date has no uplift to
    report -- the old rule omitted it outright, so nothing was distorted."""
    frame = _returns_with_no_coverage()
    block = portfolio_return_coverage_block(frame, {"AAA": 0.5, "BBB": 0.5})
    assert block["published_dates"] == 0
    assert block["dropped_dates"] == len(frame)
    # the 0-coverage date is excluded from the uplift, the 0.5 ones are not
    assert block["max_dropped_renormalization_uplift"] == pytest.approx(2.0)
    assert block["min_published_constituent_count"] is None
    assert block["dates"][-1]["constituent_count"] == 0
    assert block["dates"][-1]["covered_weight_fraction"] == 0.0
    json.dumps(block)  # no Infinity reaches a serialized payload


def test_frame_with_nothing_measurable_reports_no_uplift_at_all():
    frame = _returns_with_no_coverage()
    frame.iloc[:, :] = np.nan
    block = portfolio_return_coverage_block(frame, {"AAA": 0.5, "BBB": 0.5})
    assert block["published_dates"] == 0
    assert block["max_dropped_renormalization_uplift"] is None
    assert block["min_published_constituent_count"] is None
    json.dumps(block)


def test_coverage_block_reports_when_there_is_nothing_to_measure():
    empty = pd.DataFrame(columns=["A", "B"])
    block = portfolio_return_coverage_block(empty, {"A": 1.0, "B": 1.0})
    assert block["total_dates"] == 0
    assert block["published_dates"] == 0
    assert block["dates"] == []
    assert block["error"]


@pytest.mark.asyncio
async def test_portfolio_metrics_publish_the_coverage_block():
    prices = _price_frame()
    result = await AnalyticsEngine().calculate_portfolio_metrics(
        prices, {"A": 0.4, "B": 0.4, "C": 0.2}
    )
    block = result["portfolio_return_coverage"]
    assert block["published_dates"] == result["observations"]
    assert block["dropped_dates"] == 0
    assert block["min_published_constituent_count"] == 3


def _price_with_never_listed_leg(n_days: int = 40) -> pd.DataFrame:
    """A book where one leg has a single price point, so it never returns."""
    idx = pd.bdate_range("2024-01-02", periods=n_days)
    listed = 100.0 * np.exp(np.cumsum(np.full(n_days, 0.001)))
    unlisted = np.full(n_days, np.nan)
    unlisted[0] = 100.0
    return pd.DataFrame({"AAA": listed, "BBB": unlisted}, index=idx)


@pytest.mark.asyncio
async def test_portfolio_metrics_refuse_when_no_day_covers_the_book():
    """Every date short of the whole book -> no series, not a thin one."""
    result = await AnalyticsEngine().calculate_portfolio_metrics(
        _price_with_never_listed_leg(), {"AAA": 0.5, "BBB": 0.5}
    )
    assert "portfolio_return_coverage" not in result  # empty-metrics shape
    assert result.get("error") == "Insufficient data for calculations"


# ---------------------------------------------------------------------------
# SI-3 -- a confidence interval is either real or absent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_garch_confidence_interval_is_absent_not_a_fixed_band():
    returns = _long_returns()
    engine = AnalyticsEngine()
    result = await engine._garch_forecast(returns, 1)

    assert result["confidence_interval"] is None
    assert result["confidence_interval_status"] == "not_computed"
    assert "not computed" in result["confidence_interval_reason"].lower()
    # the exact defect: sigma * [0.8, 1.2]
    sigma = result["volatility_forecast"]
    assert [sigma * 0.8, sigma * 1.2] != result["confidence_interval"]


def test_ewma_confidence_interval_is_absent_not_a_fixed_band():
    result = AnalyticsEngine()._ewma_forecast(_long_returns(), 1)
    assert result["confidence_interval"] is None
    assert result["confidence_interval_status"] == "not_computed"
    sigma = result["volatility_forecast"]
    assert [sigma * 0.8, sigma * 1.2] != result["confidence_interval"]


@pytest.mark.asyncio
async def test_egarch_confidence_interval_is_absent_not_a_fixed_band():
    result = await AnalyticsEngine()._egarch_forecast(_long_returns(), 1)
    assert result["confidence_interval"] is None
    assert result["confidence_interval_status"] == "not_computed"


def test_empty_forecast_states_why_it_has_no_interval():
    result = AnalyticsEngine()._empty_forecast(1, "GARCH", error="nope")
    assert result["confidence_interval"] is None
    assert result["confidence_interval_reason"]
    assert result["tail_measure"] is None


# ---------------------------------------------------------------------------
# AD-2 -- the tail fields must declare level, units and basis
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_garch_tail_declares_level_units_and_basis():
    result = await AnalyticsEngine()._garch_forecast(_long_returns(), 1)
    tail = result["tail_measure"]

    assert tail["var_confidence_level"] == TAIL_CONFIDENCE_LEVEL
    assert tail["var_horizon_days"] == 1
    assert tail["var_units"] == "1_day_cumulative_return_decimal"
    assert tail["var_sign_convention"] == "negative_is_loss"
    assert tail["volatility_forecast_units"] == "annualized"
    assert "must NOT be annualized" in tail["annualization_note"]
    # the multipliers are the ones actually used
    assert result["var_forecast"] == pytest.approx(
        -tail["return_space_volatility"] * TAIL_Z_MULTIPLIER
    )
    assert result["cvar_forecast"] == pytest.approx(
        -tail["return_space_volatility"] * TAIL_ES_MULTIPLIER
    )
    assert tail["var_clip_bounds"] == [-0.99, -0.001]


def test_cvar_to_var_ratio_is_published_as_an_identity():
    """`cvar == 1.25228 * var` is a property of the normal distribution.

    Undeclared it read as two independent measurements.  Declared as an
    identity it is a true statement about the estimator.
    """
    result = AnalyticsEngine()._ewma_forecast(_long_returns(), 1)
    tail = result["tail_measure"]
    assert tail["cvar_to_var_ratio"] == pytest.approx(
        TAIL_ES_MULTIPLIER / TAIL_Z_MULTIPLIER
    )
    assert tail["cvar_to_var_ratio_fixed_by_construction"] is True
    assert result["cvar_forecast"] / result["var_forecast"] == pytest.approx(
        tail["cvar_to_var_ratio"]
    )


def test_ewma_tail_says_the_normal_is_assumed_not_fitted():
    tail = AnalyticsEngine()._ewma_forecast(_long_returns(), 1)["tail_measure"]
    assert tail["var_distribution"] == "normal_assumed_no_parametric_fit"
    assert "assumption" in tail["var_distribution_note"]


@pytest.mark.asyncio
async def test_tail_declaration_reaches_model_params():
    """`model_params` is the only block the forecast route forwards verbatim."""
    result = await AnalyticsEngine()._garch_forecast(_long_returns(), 1)
    mirrored = result["model_params"]["tail_measure"]
    assert mirrored is result["tail_measure"]
    assert mirrored["var_confidence_level"] == TAIL_CONFIDENCE_LEVEL
    assert result["model_params"]["confidence_interval_status"] == "not_computed"
    assert result["model_params"]["innovation_distribution"] == "normal"


@pytest.mark.asyncio
async def test_egarch_tail_keeps_its_own_zero_clip_bound():
    result = await AnalyticsEngine()._egarch_forecast(_long_returns(), 1)
    assert result["tail_measure"]["var_clip_bounds"] == [-0.99, 0.0]
    assert result["tail_measure"]["var_horizon_days"] == 1


# ---------------------------------------------------------------------------
# QM-4 -- achieved_volatility is a measurement, not the target restated
# ---------------------------------------------------------------------------

def _independent_sample_cov_vol(returns: pd.DataFrame, weights: dict) -> float:
    vector = np.array([weights[t] for t in returns.columns], dtype=float)
    covariance = returns.cov().to_numpy(dtype=float)
    return float(np.sqrt(vector @ covariance @ vector) * math.sqrt(252.0))


@pytest.mark.asyncio
async def test_achieved_volatility_is_not_a_restatement_of_the_target():
    """`scale = target / sizing_volatility`, so `sizing_vol * scale == target`
    identically. Publishing that product as an achievement publishes the
    target's own arithmetic back to the reader."""
    prices = _price_frame()
    target = 0.11
    result = await AnalyticsEngine().volatility_sizing(
        prices, {"A": 0.4, "B": 0.35, "C": 0.25},
        model="EWMA", target_volatility=target,
    )

    assert result["achieved_volatility"] is not None
    assert result["achieved_volatility"] != pytest.approx(target, rel=1e-3)
    # the identity it replaced is still published, openly
    assert result["imposed_target_volatility"] == pytest.approx(target, rel=1e-6)
    assert "by_construction" in result["imposed_target_volatility_basis"]


@pytest.mark.asyncio
async def test_achieved_volatility_matches_an_independent_recomputation():
    prices = _price_frame()
    result = await AnalyticsEngine().volatility_sizing(
        prices, {"A": 0.4, "B": 0.35, "C": 0.25},
        model="EWMA", target_volatility=0.11,
    )
    returns = prices.pct_change(fill_method=None).iloc[1:]
    scaled = {
        ticker: float(value)
        for ticker, value in result["recommended_weights"].items()
    }
    expected = _independent_sample_cov_vol(returns, scaled)
    assert result["achieved_volatility"] == pytest.approx(expected, rel=1e-5)
    assert result["achieved_volatility_basis"] == (
        "sample_covariance_of_measured_returns"
    )
    assert result["achieved_volatility_reason"] is None


@pytest.mark.asyncio
async def test_sizing_volatility_is_published_and_drives_the_scale():
    prices = _price_frame()
    result = await AnalyticsEngine().volatility_sizing(
        prices, {"A": 0.4, "B": 0.35, "C": 0.25},
        model="EWMA", target_volatility=0.11,
    )
    assert result["sizing_volatility"] is not None
    assert result["sizing_volatility"] > 0.0
    assert result["scale_factor"] == pytest.approx(
        0.11 / result["sizing_volatility"], rel=1e-4
    )
    assert result["sizing_volatility_basis"] in (
        "correlation_x_ewma_volatility", "single_leg_ewma_volatility"
    )


@pytest.mark.asyncio
async def test_the_three_volatilities_each_carry_their_convention():
    """One book, three numbers. Each must name the convention that made it."""
    prices = _price_frame()
    result = await AnalyticsEngine().volatility_sizing(
        prices, {"A": 0.4, "B": 0.35, "C": 0.25},
        model="EWMA", target_volatility=0.11,
    )
    assert result["current_volatility_basis"] == "correlation_x_ewma_volatility"
    assert result["achieved_volatility_basis"] == "sample_covariance_of_measured_returns"
    assert result["sizing_volatility_basis"]
    assert result["current_volatility_sample_covariance"] is not None
    assert result["current_volatility_sample_covariance_reason"] is None
    # the two current-book figures are different quantities and say so
    assert result["current_volatility"] != pytest.approx(
        result["current_volatility_sample_covariance"], rel=1e-3
    )


@pytest.mark.asyncio
async def test_sizing_never_publishes_an_achieved_volatility_it_did_not_measure():
    prices = _price_frame()
    result = await AnalyticsEngine().volatility_sizing(
        prices, {"A": 0.4, "B": 0.35, "C": 0.25},
        model="EWMA", target_volatility=0.11,
    )
    for key in ("achieved_volatility", "sizing_volatility",
                "imposed_target_volatility",
                "recommended_volatility_sample_covariance"):
        value = result[key]
        assert value is None or (isinstance(value, float) and value >= 0.0)


@pytest.mark.asyncio
async def test_risk_score_nulls_an_unmeasurable_volatility_leg():
    """`min(30, nan * 100)` is 30 in Python.

    A book with a never-listed leg has no full-basket day, so the portfolio
    volatility is UNMEASURED. Scoring that as a maximum would fabricate the
    worst possible risk reading out of no data, so the leg is null + excluded
    and the remaining legs renormalise.
    """
    result = await AnalyticsEngine().risk_scoring(
        _price_with_never_listed_leg(), {"AAA": 0.5, "BBB": 0.5}
    )
    assert result["components"]["volatility"] is None
    assert "volatility" in result["excluded_components"]
    # the score is built only from legs that were measured
    assert result["overall_score"] is not None
    assert 0.0 <= result["overall_score"] <= 100.0
    # and the stateless / no-prior-score contract is untouched
    assert result["change"] is None
    assert result["change_status"] == "unavailable"
    assert result["change_reason"] == "no_persisted_prior_score"


@pytest.mark.asyncio
async def test_risk_score_is_still_stateless_under_the_coverage_gate():
    prices = _price_frame()
    engine = AnalyticsEngine()
    first = await engine.risk_scoring(prices, {"A": 0.4, "B": 0.35, "C": 0.25})
    second = await engine.risk_scoring(prices, {"A": 0.4, "B": 0.35, "C": 0.25})
    assert first["overall_score"] == second["overall_score"]
    assert not hasattr(engine, "_previous_risk_score")


@pytest.mark.asyncio
async def test_unavailable_sizing_publishes_no_achieved_volatility():
    result = await AnalyticsEngine().volatility_sizing(
        pd.DataFrame(), {"A": 1.0}
    )
    assert result["achieved_volatility"] is None
    assert result["achieved_volatility_reason"]
    assert result["sizing_volatility"] is None


def test_sample_covariance_helper_reports_why_it_cannot_measure():
    engine = AnalyticsEngine()
    value, reason = engine._sample_covariance_volatility(
        pd.DataFrame(), ["A"], [1.0]
    )
    assert value is None and reason

    frame = pd.DataFrame({"A": [0.01, 0.02, 0.03]}, index=pd.bdate_range("2024-01-01", periods=3))
    value, reason = engine._sample_covariance_volatility(frame, ["ZZZ"], [1.0])
    assert value is None and reason

    value, reason = engine._sample_covariance_volatility(frame, ["A"], [0.0])
    assert value is None and reason


# ---------------------------------------------------------------------------
# SI-9 -- a computed HAC covariance must be published
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_factor_exposure_publishes_robust_standard_errors():
    idx = pd.bdate_range("2024-01-02", periods=120)
    rng = np.random.default_rng(3)
    benchmark = pd.Series(rng.normal(0.0004, 0.008, 120), index=idx)
    prices = pd.DataFrame(
        100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.010, (120, 2)), axis=0)),
        index=idx,
        columns=["A", "B"],
    )
    result = await AnalyticsEngine().factor_exposure_analysis(
        prices, benchmark_data=benchmark, weights={"A": 0.5, "B": 0.5}
    )

    position = result["positions"]["A"]
    assert position["std_error_robust"] is True
    assert "hac" in position["std_error_basis"].lower()
    assert position["alpha_std_error"] is not None
    assert position["market_std_error"] is not None

    # the published SE is the one the fit actually used (6 dp published)
    returns = prices.pct_change(fill_method=None).iloc[1:]
    common = returns.index.intersection(benchmark.index)
    fit = sm.OLS(
        returns["A"].loc[common],
        sm.add_constant(benchmark.loc[common]),
    ).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    assert position["alpha_std_error"] == pytest.approx(float(fit.bse.iloc[0]), abs=1e-6)
    assert position["market_std_error"] == pytest.approx(float(fit.bse.iloc[1]), abs=1e-6)
    # and it is NOT the uncorrected OLS error it used to be computed and dropped
    plain = sm.OLS(
        returns["A"].loc[common],
        sm.add_constant(benchmark.loc[common]),
    ).fit()
    assert position["market_std_error"] != pytest.approx(
        float(plain.bse.iloc[1]), abs=1e-9
    )

    portfolio = result["portfolio"]
    assert portfolio["std_error_robust"] is True
    assert portfolio["market_std_error"] > 0.0
    assert portfolio["observations"] > 10


def test_uncorrected_standard_errors_are_never_labelled_robust(monkeypatch):
    """A failed HAC fit must degrade to a LABEL, never to a silent OLS SE."""
    import app.services.analytics_engine as module

    class _OLS:
        def __init__(self, *args, **kwargs):
            self.bse = pd.Series([0.1, 0.2])

        def fit(self, *args, **kwargs):
            if kwargs.get("cov_type") == "HAC":
                raise ValueError("HAC unavailable")
            return self

    monkeypatch.setattr(module.sm, "OLS", _OLS)
    model, basis, robust = AnalyticsEngine._ols_with_published_se(
        pd.Series([1.0, 2.0]), pd.DataFrame({"c": [1.0, 1.0]})
    )
    assert robust is False
    assert basis == "ols_uncorrected_hac_unavailable"
    assert "uncorrected" in basis


def test_finite_param_never_invents_a_zero_standard_error():
    engine = AnalyticsEngine()
    assert engine._finite_param(pd.Series([0.5, np.nan]), 0) == 0.5
    assert engine._finite_param(pd.Series([0.5, np.nan]), 1) is None
    assert engine._finite_param(pd.Series([0.5, np.inf]), 1) is None
    assert engine._finite_param(pd.Series([]), 0) is None


@pytest.mark.asyncio
async def test_factor_exposure_regression_runs_on_published_portfolio_dates():
    """The portfolio beta's date mask must match the published series.

    Previously the mask was "any constituent traded", which is wider than a
    coverage-gated series -- a `.loc` against it can miss labels outright.
    """
    idx = pd.bdate_range("2024-01-02", periods=150)
    rng = np.random.default_rng(19)
    benchmark = pd.Series(rng.normal(0.0003, 0.008, 150), index=idx)
    base = 100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.009, 150), axis=0))
    prices = pd.DataFrame({"A": base, "B": base * 1.001}, index=idx)
    # B has no bar in the last 30 days -> those dates are not full-basket days
    prices.iloc[-30:, 1] = np.nan

    result = await AnalyticsEngine().factor_exposure_analysis(
        prices, benchmark_data=benchmark, weights={"A": 0.5, "B": 0.5}
    )
    assert "error" not in result
    returns = prices.pct_change(fill_method=None).iloc[1:]
    coverage = active_return_coverage(returns, {"A": 0.5, "B": 0.5})
    usable = coverage[coverage["published"]].index.intersection(benchmark.index)
    assert len(usable) > 10
    assert result["portfolio"]["observations"] == int(len(usable))
