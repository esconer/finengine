"""Estimator-uncertainty regressions (SI-5).

SI-5 was the last structural red rule in the v5 review: the export published on
the order of two thousand point estimates and, across 876 KB of JSON, carried
no standard error, no interval and no effective-sample-size figure anywhere. A
point estimate published with the visual authority of a measurement IS the
defect.

The fix is deliberately narrow. Every estimate now carries ONE of two things:

  * a real interval, with its method, its level and the n it rests on, or
  * ``not_computed`` / ``not_applicable`` with the reason.

An interval invented to satisfy the rule is worse than the absence, because it
converts a known gap into a false precision. So the tests here are weighted
towards the two ways that failure could hide:

  * an interval that does not belong to the published statistic (the
    reproduction guard in ``measure_estimate_uncertainty``), and
  * a ``null`` interval that is a silently ABSENT key rather than a stated
    absence.

Nothing here runs the audit CLI: it reads a frozen export, so a green gate
would say nothing about the code. The rule's own token set is imported instead,
so the in-process assertion is made against the constants the rule actually
uses.
"""

import json
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import quantstats as qs

from app.api.analytics import (
    _pairs_estimate_uncertainty,
    _tear_sheet_relative_uncertainty,
    _tear_sheet_uncertainty,
    TEAR_SHEET_RISK_FREE_RATE,
)
from app.debugging.context_audit import (
    ESTIMATE_KEY_TOKENS,
    UNCERTAINTY_KEY_TOKENS,
)
from app.services.analytics_engine import (
    UNCERTAINTY_BOOTSTRAP_RESAMPLES,
    UNCERTAINTY_BOOTSTRAP_SEED,
    UNCERTAINTY_CONFIDENCE_LEVEL,
    UNCERTAINTY_MIN_OBSERVATIONS,
    AnalyticsEngine,
    ar1_autocorrelation,
    autocorrelation_disclosure,
    effective_sample_size,
    engine_risk_statistics,
    market_model_statistics,
    measure_estimate_uncertainty,
    moving_block_indices,
    moving_block_size,
    quantstats_ratio_statistics,
    quantstats_returns_look_like_prices,
)
from app.services.optimization_service import (
    MOMENT_KEYS,
    TRADING_DAYS,
    _as_matrices,
    _hrp_weights,
    _weight_vector,
    no_estimate_uncertainty,
    optimizer_no_sample_reason,
    optimize,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def _returns(n: int = 170, k: int = 6, seed: int = 7) -> pd.DataFrame:
    """A wide daily-return frame with a real market factor and a small drift."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-02", periods=n)
    common = rng.normal(0.0002, 0.008, (n, 1))
    idio = rng.normal(0.0, 0.009, (n, k))
    return pd.DataFrame(common + idio, index=idx, columns=[f"S{i}" for i in range(k)])


def _series(n: int = 174, seed: int = 5, mu: float = 0.0004) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.Series(
        np.clip(mu + 0.010 * rng.standard_t(5, n), -0.2, 0.3), index=idx
    )


def _positive_autocorrelated(n: int = 400, rho: float = 0.5, seed: int = 2) -> np.ndarray:
    """An AR(1) with a known lag, so `effective_n < n` is not a coincidence."""
    rng = np.random.default_rng(seed)
    shocks = rng.normal(0.0, 0.01, n)
    out = np.zeros(n)
    for t in range(1, n):
        out[t] = rho * out[t - 1] + shocks[t]
    return out


# ---------------------------------------------------------------------------
# the contract every block must satisfy
# ---------------------------------------------------------------------------

def _walk_blocks(payload):
    """Every mapping that looks like an uncertainty block, with its path."""
    found = []
    if isinstance(payload, dict):
        if "estimates" in payload and "scope" in payload:
            found.append(payload)
        for value in payload.values():
            found.extend(_walk_blocks(value))
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            found.extend(_walk_blocks(item))
    return found


def _assert_block_contract(block) -> None:
    """Every field: a real interval, or a status with a reason. Never silence."""
    assert block["scope"], "a block must say what it covers"
    assert block["status"] in {"computed", "not_computed"}
    assert isinstance(block["estimates"], dict)
    for field, entry in block["estimates"].items():
        assert entry["status"] in {"computed", "not_computed", "not_applicable"}, field
        # criterion: a null interval is a PRESENT key, never an absent one.
        assert "conf_int" in entry, f"{field} omitted conf_int entirely"
        if entry["conf_int"] is None:
            assert entry["standard_error"] is None, field
            assert entry["status"] != "computed", field
            assert entry["reason"], f"{field} has no interval and no reason"
            assert entry["conf_int_level"] is None, field
            assert entry["point_within_conf_int"] is None, field
        else:
            assert entry["status"] == "computed", field
            assert entry["reason"] is None, field
            # every interval states method, level and the n it rests on
            assert entry["conf_int_method"], field
            assert entry["conf_int_level"] == UNCERTAINTY_CONFIDENCE_LEVEL, field
            assert entry["observations"] and entry["observations"] > 0, field
            low, high = entry["conf_int"]
            assert math.isfinite(low) and math.isfinite(high) and low <= high, field
            assert entry["standard_error"] is not None
            assert entry["standard_error"] > 0.0, field
            assert isinstance(entry["point_within_conf_int"], bool), field
            if not entry["point_within_conf_int"]:
                # stated, not smoothed over
                assert "non-smooth functional" in entry["point_within_conf_int_note"]
    json.dumps(block)  # no NaN / Infinity ever reaches a serialized payload


# ---------------------------------------------------------------------------
# criterion 1a -- a real interval is correct against an INDEPENDENT
#                  recomputation of the same estimator
# ---------------------------------------------------------------------------

def _independent_moment_interval(
    values: np.ndarray, weights: np.ndarray, rf: float, block_size: int,
    resamples: int, seed: int, field: str = "expected_annual_return",
) -> list:
    """Rebuild the optimizer's mu/cov bootstrap from scratch.

    Deliberately a different implementation of the same estimator: the draws are
    built time-axis-last and the moments are accumulated row-major, so a match
    with the production block is evidence about the ESTIMATOR, not about two
    copies of one expression.
    """
    n, k = values.shape
    starts_count = int(np.ceil(n / block_size))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(resamples, starts_count))
    offsets = np.arange(block_size)
    indices = (starts[:, :, None] + offsets[None, None, :]) % n
    indices = indices.reshape(resamples, starts_count * block_size)[:, :n]
    draws = values[indices]                                  # (resamples, n, k)
    mu_draws = draws.sum(axis=1) / n * TRADING_DAYS          # (resamples, k)
    centred = draws - draws.mean(axis=1, keepdims=True)
    cov_draws = np.einsum("rni,rnj->rij", centred, centred) / (n - 1) * TRADING_DAYS
    expected = mu_draws @ weights
    variance = np.einsum("rij,i,j->r", cov_draws, weights, weights)
    volatility = np.sqrt(variance)
    statistic = {
        "expected_annual_return": expected,
        "expected_annual_volatility": volatility,
        "expected_sharpe": (expected - rf) / volatility,
    }[field]
    low, high = np.percentile(statistic, [2.5, 97.5])
    return [float(low), float(high)]


def test_optimizer_return_interval_is_reproduced_by_an_independent_bootstrap():
    """The published 95 % band on `expected_annual_return`, re-derived to 1e-6."""
    frame = _returns()
    result = optimize(frame, "hrp", current_weights={c: 1 / 6 for c in frame.columns})
    block = result["estimate_uncertainty"]
    entry = block["estimates"]["expected_annual_return"]

    assert entry["status"] == "computed"
    assert entry["conf_int_level"] == 0.95
    assert entry["conf_int_method"] == "circular_moving_block_bootstrap_percentile"
    assert entry["observations"] == len(frame) == 170

    # The published 6-decimal weights must themselves reproduce the moment the
    # record publishes, to the display step the record claims.
    mu, _cov, assets = _as_matrices(frame)
    published_w = np.array([result["weights"][a] for a in assets], dtype=float)
    assert float(mu @ published_w) == pytest.approx(
        result["expected_annual_return"], abs=5e-5
    )

    # The exact solved vector, so the comparison below is about the estimator
    # and not about the 6-decimal display rounding.
    exact_w = _weight_vector(_hrp_weights(frame), assets)
    for field in ("expected_annual_return", "expected_annual_volatility"):
        rebuilt = _independent_moment_interval(
            frame.to_numpy(dtype=float), exact_w, 0.02,
            block["block_size"], block["bootstrap_resamples"], block["resample_seed"],
            field=field,
        )
        assert block["estimates"][field]["conf_int"] == pytest.approx(
            rebuilt, abs=1e-6
        ), field
    # and it is a band around the published number, not a decoration
    assert entry["conf_int"][0] < entry["point"] < entry["conf_int"][1]


def test_optimizer_return_carries_a_second_independent_standard_error():
    """Closed form beside the bootstrap, so one method never stands in for both.

    Normal theory for the ANNUALIZED sample mean:
    ``SE(252 * r_bar) = 252 * sigma_daily / sqrt(n) = sigma_p * sqrt(252 / n)``.
    The annualization does not cancel - `expected_annual_volatility` is already
    scaled by sqrt(252) - so the standard error carries sqrt(252) back out.
    That identity is exact and checkable by hand; the bootstrap is approximate.
    Both are published so they can be compared instead of one standing in for
    the other.
    """
    frame = _returns(seed=13)
    result = optimize(frame, "hrp")
    entry = result["estimate_uncertainty"]["estimates"]["expected_annual_return"]

    observations = result["moments_basis"]["return_observations"]
    # The identity is checked against the PUBLISHED 4-decimal volatility, so the
    # tolerance is one display step of that input (5e-5 * sqrt(252/n)), not 1e-6.
    # The exact 1e-6 reproduction is the bootstrap-band test above, whose inputs
    # are unrounded.
    expected = result["expected_annual_volatility"] * math.sqrt(TRADING_DAYS / observations)
    assert entry["normal_theory_standard_error"] == pytest.approx(expected, abs=1e-4)
    assert "sqrt(252 / n)" in entry["normal_theory_basis"]
    ratio = entry["normal_theory_standard_error"] / entry["standard_error"]
    assert 0.5 < ratio < 2.0, ratio


def test_optimizer_volatility_and_sharpe_carry_intervals_too():
    frame = _returns(seed=21)
    result = optimize(frame, "hrp")
    _assert_block_contract(result["estimate_uncertainty"])
    for field in MOMENT_KEYS:
        entry = result["estimate_uncertainty"]["estimates"][field]
        assert entry["status"] == "computed", field
        assert entry["point"] == pytest.approx(result[field], abs=0.0)
        assert entry["conf_int"] is not None
        assert entry["conf_int"][0] <= entry["conf_int"][1]
    # Sharpe is a ratio of two estimates, so its band is wider than either.
    block = result["estimate_uncertainty"]["estimates"]
    assert (
        block["expected_sharpe"]["conf_int"][1] - block["expected_sharpe"]["conf_int"][0]
        > block["expected_annual_volatility"]["conf_int"][1]
        - block["expected_annual_volatility"]["conf_int"][0]
    )


def test_current_portfolio_shares_the_recommendation_sample_and_bands():
    """The incumbent is scored on the same draws, so the delta is comparable."""
    frame = _returns(seed=31)
    current = {c: 1 / 6 for c in frame.columns}
    result = optimize(frame, "hrp", current_weights=current)
    recommended = result["estimate_uncertainty"]
    incumbent = result["current_portfolio"]["estimate_uncertainty"]

    assert incumbent["status"] == "computed"
    assert incumbent["observations"] == recommended["observations"]
    assert incumbent["resample_seed"] == recommended["resample_seed"]
    assert incumbent["block_size"] == recommended["block_size"]
    assert incumbent["estimates"]["expected_sharpe"]["conf_int"] is not None
    _assert_block_contract(incumbent)


def test_tear_sheet_ratio_restatements_reproduce_quantstats_exactly():
    """The band belongs to the published statistic or it is not published.

    `measure_estimate_uncertainty` refuses to attach a band whose own point value
    does not reproduce the published one, so the restatements have to be exact
    or the block degrades for the wrong reason.
    """
    series = _series()
    suite = quantstats_ratio_statistics(TEAR_SHEET_RISK_FREE_RATE)
    block_input = series.to_numpy().reshape(-1, 1, 1)
    expected = {
        "sharpe": qs.stats.sharpe(series, rf=0.02),
        "sortino": qs.stats.sortino(series, rf=0.02),
        "calmar": qs.stats.calmar(series),
        "omega": qs.stats.omega(series),
        "tail_ratio": qs.stats.tail_ratio(series),
        "total_return": qs.stats.comp(series),
        "cagr": qs.stats.cagr(series),
        "volatility": qs.stats.volatility(series),
        "max_drawdown": qs.stats.max_drawdown(series),
    }
    for name, published in expected.items():
        got = float(np.asarray(suite[name](block_input)).ravel()[0])
        assert got == pytest.approx(float(published), abs=1e-12), name


def test_engine_risk_restatements_reproduce_the_engine_exactly():
    engine = AnalyticsEngine()
    series = _series(n=120, seed=9)
    metrics = {}
    metrics.update(engine._calculate_basic_metrics(series))
    metrics.update(engine._calculate_risk_metrics(series))
    metrics.update(engine._calculate_drawdown_metrics(series))
    suite = engine_risk_statistics(engine.risk_free_rate)
    block_input = series.to_numpy().reshape(-1, 1, 1)
    for name, fn in suite.items():
        got = float(np.asarray(fn(block_input)).ravel()[0])
        assert got == pytest.approx(float(metrics[name]), abs=1e-12), name


def test_market_model_restatement_reproduces_beta_and_alpha_exactly():
    portfolio, benchmark = _series(n=174, seed=3), _series(n=174, seed=4, mu=0.0003)
    beta = float(portfolio.cov(benchmark) / benchmark.var())
    alpha = float((portfolio.mean() - beta * benchmark.mean()) * 252)
    suite = market_model_statistics(252)
    frame = np.column_stack([portfolio.to_numpy(), benchmark.to_numpy()]).reshape(-1, 1, 2)
    assert float(np.asarray(suite["beta"](frame)).ravel()[0]) == pytest.approx(beta, abs=1e-12)
    assert float(np.asarray(suite["alpha_annualized"](frame)).ravel()[0]) == pytest.approx(
        alpha, abs=1e-12
    )


def test_tear_sheet_publishes_a_real_interval_for_every_headline_ratio():
    series = _series()
    published = {
        "sharpe": round(float(qs.stats.sharpe(series, rf=0.02)), 6),
        "sortino": round(float(qs.stats.sortino(series, rf=0.02)), 6),
        "calmar": round(float(qs.stats.calmar(series)), 6),
        "omega": round(float(qs.stats.omega(series)), 6),
    }
    block = _tear_sheet_uncertainty(series, published, scope="unit test")
    _assert_block_contract(block)
    for field, value in published.items():
        entry = block["estimates"][field]
        assert entry["status"] == "computed", field
        assert entry["point"] == value
        assert entry["observations"] == len(series)
    # the smooth ratios: the point sits inside its own band
    for field in ("sharpe", "sortino", "omega"):
        entry = block["estimates"][field]
        assert entry["point_within_conf_int"] is True, field
        assert entry["conf_int"][0] <= published[field] <= entry["conf_int"][1], field
    # Calmar divides by a MAX DRAWDOWN, a non-smooth path functional, so the
    # resampling distribution of the ratio is shifted and coverage is not
    # guaranteed. The block publishes that fact rather than hiding it - which
    # is the whole difference between a real interval and a reassuring one.
    calmar = block["estimates"]["calmar"]
    assert calmar["conf_int"] is not None
    if not calmar["point_within_conf_int"]:
        assert "non-smooth functional" in calmar["point_within_conf_int_note"]


def test_tear_sheet_market_model_block_covers_beta_and_alpha():
    portfolio, benchmark = _series(n=200, seed=3), _series(n=200, seed=4, mu=0.0003)
    beta = float(portfolio.cov(benchmark) / benchmark.var())
    block = _tear_sheet_relative_uncertainty(
        portfolio, benchmark,
        {
            "beta_vs_nifty": round(beta, 4),
            "alpha_annualized": round(
                float((portfolio.mean() - beta * benchmark.mean()) * 252), 4
            ),
        },
        scope="unit test",
    )
    _assert_block_contract(block)
    assert block["estimates"]["beta_vs_nifty"]["conf_int"][0] <= round(beta, 4)
    assert block["estimates"]["beta_vs_nifty"]["conf_int"][1] >= round(beta, 4)
    assert block["observations"] == 200
    assert block["observation_columns"] == 2


# ---------------------------------------------------------------------------
# criterion 1b -- every estimate has a real interval OR a stated absence
# ---------------------------------------------------------------------------

def test_realized_risk_block_satisfies_the_contract_portfolio_and_positions():
    import asyncio

    idx = pd.bdate_range("2023-01-02", periods=240)
    rng = np.random.default_rng(4)
    prices = pd.DataFrame(
        100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.010, (240, 3)), axis=0)),
        index=idx, columns=["A", "B", "C"],
    )
    metrics = asyncio.run(
        AnalyticsEngine().calculate_portfolio_metrics(prices, {"A": 0.4, "B": 0.4, "C": 0.2})
    )
    portfolio_block = metrics["estimate_uncertainty"]
    _assert_block_contract(portfolio_block)
    assert portfolio_block["status"] == "computed"
    assert portfolio_block["observations"] == metrics["observations"]
    for field in ("sharpe_ratio", "sortino_ratio", "var_95", "cvar_95"):
        entry = portfolio_block["estimates"][field]
        assert entry["status"] == "computed", field
        assert entry["conf_int"][0] <= entry["point"] <= entry["conf_int"][1], field

    for ticker, position in metrics["positions"].items():
        block = position["estimate_uncertainty"]
        _assert_block_contract(block)
        # the leg's OWN sample, never the portfolio's
        assert block["observations"] == position["data_points"], ticker
        assert "own" in block["scope"], ticker


def test_realized_risk_declares_the_two_shape_statistics_absent():
    import asyncio

    idx = pd.bdate_range("2023-01-02", periods=200)
    rng = np.random.default_rng(6)
    prices = pd.DataFrame(
        100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.011, (200, 2)), axis=0)),
        index=idx, columns=["A", "B"],
    )
    metrics = asyncio.run(
        AnalyticsEngine().calculate_portfolio_metrics(prices, {"A": 0.6, "B": 0.4})
    )
    estimates = metrics["estimate_uncertainty"]["estimates"]
    for field in ("skewness", "kurtosis"):
        entry = estimates[field]
        assert entry["status"] == "not_computed"
        assert entry["conf_int"] is None
        assert entry["point"] is not None          # the estimate itself still ships
        assert "bias-corrected" in entry["reason"]


def test_pairs_declares_every_family_once_with_a_status_and_a_reason():
    rows = [
        SimpleNamespace(overlap_observations=252),
        SimpleNamespace(overlap_observations=140),
        SimpleNamespace(overlap_observations=None),
    ]
    block = _pairs_estimate_uncertainty(rows, comparisons=91, p_value_threshold=0.05)
    _assert_block_contract(block)
    assert block["row_count"] == 3
    assert block["comparisons_made"] == 91
    assert block["delivered_row_observations"]["min"] == 140
    assert block["delivered_row_observations"]["max"] == 252
    for field in (
        "hedge_ratio_beta", "intercept_alpha", "ou_reversion_speed_theta",
        "ou_half_life_days", "current_spread_zscore",
    ):
        assert block["estimates"][field]["status"] == "not_computed"
        assert block["estimates"][field]["reason"]
    # a per-block basis, not 91 duplicated rows of one
    assert "once for the group" in block["scope"]


def test_pairs_marks_a_threshold_as_not_applicable_not_unmeasured():
    """`family_alpha` is chosen before any test runs, so it has no interval.

    Publishing `not_computed` for it would be wrong in a different way: nothing
    failed to be measured. The distinction matters to a consumer deciding
    whether a gap is a bug in this code or a property of the statistic.
    """
    block = _pairs_estimate_uncertainty([], comparisons=91, p_value_threshold=0.05)
    for field in ("family_alpha", "is_cointegrated", "johansen_cointegrated"):
        entry = block["estimates"][field]
        assert entry["status"] == "not_applicable", field
        assert entry["reason"]
        assert entry["estimator"] is None, field
    assert "threshold" in block["estimates"]["family_alpha"]["reason"]
    assert "hypothesis" in block["estimates"]["is_cointegrated"]["reason"].lower()
    assert "verdict" in block["estimates"]["is_cointegrated"]["reason"].lower()


def test_optimizer_degraded_record_declares_the_absence_for_all_three():
    reason = optimizer_no_sample_reason("the common return frame holds 12 rows")
    block = no_estimate_uncertainty(reason)
    _assert_block_contract(block)
    assert block["status"] == "not_computed"
    assert set(block["estimates"]) == set(MOMENT_KEYS)
    for entry in block["estimates"].values():
        assert entry["point"] is None
        assert entry["conf_int"] is None
        assert "12 rows" in entry["reason"]


def test_every_uncertainty_block_in_each_section_satisfies_the_contract():
    """One pass over the four sections' blocks, all four contracts at once."""
    import asyncio

    frame = _returns(seed=41)
    optimization = optimize(frame, "hrp", current_weights={c: 1 / 6 for c in frame.columns})
    series = _series()
    published = {
        "sharpe": round(float(qs.stats.sharpe(series, rf=0.02)), 6),
        "omega": round(float(qs.stats.omega(series)), 6),
        "skew": round(float(qs.stats.skew(series)), 6),
    }
    tear_sheet = {
        "estimate_uncertainty": {
            "metrics": _tear_sheet_uncertainty(
                series, published, scope="unit test",
                not_computed={"skew": "no vectorised bias-corrected shape estimator"},
            ),
        }
    }
    pairs = {
        "estimate_uncertainty": _pairs_estimate_uncertainty(
            [SimpleNamespace(overlap_observations=252)], 91, 0.05
        )
    }
    idx = pd.bdate_range("2023-01-02", periods=200)
    rng = np.random.default_rng(8)
    prices = pd.DataFrame(
        100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.010, (200, 3)), axis=0)),
        index=idx, columns=["A", "B", "C"],
    )
    realized = asyncio.run(
        AnalyticsEngine().calculate_portfolio_metrics(prices, {"A": 0.4, "B": 0.4, "C": 0.2})
    )

    sections = {
        "tear_sheet": tear_sheet,
        "realized_risk": {
            "portfolio": {"estimate_uncertainty": realized["estimate_uncertainty"]},
        },
        "optimization": optimization,
        "pairs": pairs,
    }
    for name, section in sections.items():
        blocks = _walk_blocks(section)
        assert blocks, f"{name} published no uncertainty block at all"
        for block in blocks:
            _assert_block_contract(block)
        json.dumps(section)


# ---------------------------------------------------------------------------
# criterion 1c -- the ENV-020 escape is present in the section's OWN subtree
# ---------------------------------------------------------------------------

def _uncertainty_tokens_present(node) -> set:
    """Keys the uncertainty rule would accept as a precision disclosure."""
    found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if any(token in key.lower() for token in UNCERTAINTY_KEY_TOKENS):
                if value is not None and not (
                    isinstance(value, (list, tuple)) and not value
                ):
                    found.add(key)
            found |= _uncertainty_tokens_present(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            found |= _uncertainty_tokens_present(item)
    return found


def test_each_measured_section_publishes_a_key_the_uncertainty_rule_recognises():
    """Assert the rule's own token set, in process, on freshly built payloads.

    The audit CLI reads a FROZEN export, so a green run over it would say
    nothing about this code. These assertions use the rule's constants against
    payloads the current code just built, which is the only version of the claim
    that is testable here.

    `pairs` is deliberately NOT in this list: see the next test.
    """
    import asyncio

    frame = _returns(seed=51)
    optimization = optimize(frame, "hrp")
    series = _series()
    tear_sheet = {
        "estimate_uncertainty": {
            "metrics": _tear_sheet_uncertainty(
                series,
                {"sharpe": round(float(qs.stats.sharpe(series, rf=0.02)), 6)},
                scope="unit test",
            )
        }
    }
    idx = pd.bdate_range("2023-01-02", periods=200)
    rng = np.random.default_rng(9)
    prices = pd.DataFrame(
        100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.010, (200, 3)), axis=0)),
        index=idx, columns=["A", "B", "C"],
    )
    realized = asyncio.run(
        AnalyticsEngine().calculate_portfolio_metrics(prices, {"A": 0.4, "B": 0.4, "C": 0.2})
    )
    sections = {
        "realized_risk": {
            "portfolio": {"estimate_uncertainty": realized["estimate_uncertainty"]}
        },
        "tear_sheet": tear_sheet,
        "optimization": optimization,
    }

    for name, section in sections.items():
        found = _uncertainty_tokens_present(section)
        assert found, f"{name} exposes no key the uncertainty rule recognises"
        # and at least one of them is a genuine interval or effective count
        assert any(
            token in key.lower()
            for key in found
            for token in ("conf_int", "effective_n", "standard_error")
        ), f"{name} only exposes a non-interval token: {sorted(found)}"

    # sanity: the token sets still classify the fields they are meant to
    assert "sharpe" in ESTIMATE_KEY_TOKENS
    assert "expected_sharpe" in ESTIMATE_KEY_TOKENS
    assert "conf_int" in UNCERTAINTY_KEY_TOKENS
    assert "effective_n" in UNCERTAINTY_KEY_TOKENS
    assert "autocorrel" in UNCERTAINTY_KEY_TOKENS


def test_pairs_is_a_declared_absence_and_the_rule_rightly_refuses_it():
    """The residual gap, pinned as a test so it cannot be forgotten.

    The pairs section publishes a per-block `not_computed` basis, so the rule's
    escape set stays empty and ENV-020 will keep flagging it. That is the
    correct outcome: the section says it has no precision figure, and a rule
    that accepted a stated absence would go green on a payload that had
    measured nothing.

    The honest fix is a per-row OLS standard error on `CointPairResult`, which
    lives in `app/models/schemas.py` - outside the file set this wave was given.
    Manufacturing 91 intervals to make the check pass would convert a known gap
    into a false precision, which is the one outcome that is worse than the
    finding.
    """
    block = {
        "estimate_uncertainty": _pairs_estimate_uncertainty(
            [SimpleNamespace(overlap_observations=252)], 91, 0.05
        )
    }
    assert _uncertainty_tokens_present(block) == set()
    assert "keep flagging it" in block["estimate_uncertainty"]["residual_gap"]
    # the per-row nulls are still PUBLISHED, which is what a consumer needs
    for entry in block["estimate_uncertainty"]["estimates"].values():
        assert "conf_int" in entry and entry["conf_int"] is None


# ---------------------------------------------------------------------------
# effective sample size -- the reason the whole wave exists
# ---------------------------------------------------------------------------

def test_autocorrelation_is_estimated_and_effective_n_is_published():
    values = _positive_autocorrelated(n=400, rho=0.5)
    disclosed = autocorrelation_disclosure(values)
    assert disclosed["status"] == "computed"
    assert disclosed["observations"] == 400
    assert disclosed["ar1"] == pytest.approx(0.5, abs=0.12)
    # the whole point: with positive autocorrelation the naive n is NOT the
    # number of independent observations the mean rests on
    assert disclosed["effective_n"] < disclosed["observations"] / 1.5
    assert disclosed["effective_n"] == pytest.approx(
        400 * (1 - disclosed["ar1"]) / (1 + disclosed["ar1"]), abs=1e-3
    )
    json.dumps(disclosed)


def test_effective_sample_size_is_an_absence_rather_than_a_default():
    # a flat series has no AR(1) slope to fit, and the answer is not 0.0
    flat = np.zeros(60)
    assert ar1_autocorrelation(flat) is None
    assert effective_sample_size(60, None) is None
    flat_block = autocorrelation_disclosure(flat)
    assert flat_block["status"] == "not_computed"
    assert flat_block["effective_n"] is None
    assert flat_block["reason"]
    # a rho of exactly +-1 is a non-stationary series, not a small window
    assert effective_sample_size(100, 1.0) is None
    assert effective_sample_size(100, -1.0) is None
    assert effective_sample_size(0, 0.1) is None


def test_effective_n_travels_with_every_published_interval():
    frame = _returns(seed=61)
    block = optimize(frame, "hrp")["estimate_uncertainty"]
    for entry in block["estimates"].values():
        assert entry["effective_n"] is not None
        assert entry["effective_n"] == pytest.approx(
            block["autocorrelation"]["effective_n"], abs=1e-6
        )


# ---------------------------------------------------------------------------
# the guards: a band is withheld rather than invented
# ---------------------------------------------------------------------------

def test_a_statistic_that_does_not_reproduce_the_published_point_is_withheld():
    """The exact failure mode a fabricated interval would hide.

    If the resampling estimator measures a different quantity from the one the
    payload published, its band is not a wider honest answer - it is a
    fabricated precision. So the band is refused and the discrepancy is named.
    """
    series = _series()
    published = {
        # a Sharpe the series does not have, to two decimal places
        "sharpe": round(float(qs.stats.sharpe(series, rf=0.02)), 6) + 0.25,
        "omega": round(float(qs.stats.omega(series)), 6),
    }
    block = _tear_sheet_uncertainty(series, published, scope="unit test")
    entry = block["estimates"]["sharpe"]
    assert entry["status"] == "not_computed"
    assert entry["conf_int"] is None
    assert entry["standard_error"] is None
    assert "does not reproduce the published" in entry["reason"]
    assert "0.25" in entry["reason"]
    # the block itself degrades, and the field that DOES reproduce still ships
    assert block["status"] == "computed"
    assert block["estimates"]["omega"]["status"] == "computed"


def test_a_short_window_declares_no_interval_and_names_the_count():
    series = _series(n=8)
    published = {"sharpe": round(float(qs.stats.sharpe(series, rf=0.02)), 6)}
    block = _tear_sheet_uncertainty(series, published, scope="unit test")
    entry = block["estimates"]["sharpe"]
    assert entry["status"] == "not_computed"
    assert entry["conf_int"] is None
    assert str(UNCERTAINTY_MIN_OBSERVATIONS) in entry["reason"]
    assert "8 measured observation" in entry["reason"]
    assert block["status"] == "not_computed"
    assert block["reason"]


def test_an_empty_window_is_an_absence_not_a_crash():
    block = measure_estimate_uncertainty(
        np.zeros(0), engine_risk_statistics(0.02),
        {"sharpe_ratio": 1.5}, scope="unit test",
    )
    _assert_block_contract(block)
    assert block["observations"] == 0
    assert block["estimates"]["sharpe_ratio"]["reason"]


def test_a_withheld_point_estimate_says_so_instead_of_borrowing_a_band():
    series = _series()
    published = {
        # the annualization gate nulls this one on a short window
        "sharpe": None,
        "omega": round(float(qs.stats.omega(series)), 6),
    }
    block = _tear_sheet_uncertainty(series, published, scope="unit test")
    entry = block["estimates"]["sharpe"]
    assert entry["status"] == "not_computed"
    assert entry["point"] is None
    assert entry["conf_int"] is None
    assert "withheld" in entry["reason"]


def test_a_price_shaped_window_is_refused_rather_than_reinterpreted():
    """quantstats would difference this series; a band would describe the wrong number."""
    prices_like = np.array([1.0, 1.2, 1.4, 2.0, 1.1])
    assert quantstats_returns_look_like_prices(prices_like) is True
    assert quantstats_returns_look_like_prices(_series().to_numpy()) is False
    block = _tear_sheet_uncertainty(
        prices_like, {"sharpe": 0.0, "omega": 1.0}, scope="unit test"
    )
    _assert_block_contract(block)
    assert block["observations"] == 0
    for entry in block["estimates"].values():
        assert "PRICE series" in entry["reason"]


def test_a_statistic_mapped_to_the_wrong_field_is_reported_as_missing():
    """A name/estimator mismatch is a gap, not a silently absent key."""
    block = measure_estimate_uncertainty(
        _series().to_numpy(),
        engine_risk_statistics(0.02),
        {"sharpe_ratio": 1.0, "information_ratio": 0.4},
        scope="unit test",
    )
    entry = block["estimates"]["information_ratio"]
    assert entry["status"] == "not_computed"
    assert "no resampling estimator is registered" in entry["reason"]


def test_non_finite_observations_are_dropped_and_counted():
    values = _series(n=60).to_numpy().copy()
    values[3] = np.nan
    values[7] = np.inf
    block = measure_estimate_uncertainty(
        values, engine_risk_statistics(0.02),
        {"sharpe_ratio": 1.0}, scope="unit test",
    )
    assert block["observations"] == 58
    assert block["dropped_non_finite_observations"] == 2


# ---------------------------------------------------------------------------
# the resampling contract itself
# ---------------------------------------------------------------------------

def test_moving_block_indices_are_circular_contiguous_and_reproducible():
    n, length, draws, seed = 50, 4, 7, 99
    indices = moving_block_indices(n, length, draws, seed)
    assert indices.shape == (draws, n)
    assert indices.min() >= 0 and indices.max() < n
    assert (indices[:, :length] == (indices[:, :1] + np.arange(length)) % n).all()
    # circular: every observation is reachable, and none is dropped by truncation
    assert np.array_equal(indices, moving_block_indices(n, length, draws, seed))


def test_moving_block_size_is_the_published_n_one_third_rule():
    assert moving_block_size(39) == 3      # 39 ** (1/3) = 3.39
    assert moving_block_size(174) == 6     # 174 ** (1/3) = 5.58
    assert moving_block_size(2486) == 14   # 2486 ** (1/3) = 13.54
    assert moving_block_size(1) == 1
    assert moving_block_size(0) == 1


def _engine_block(seed: int = 3, extra_seed: int = 0):
    """A realized-risk-shaped block whose published point actually reproduces."""
    series = _series(n=174, seed=seed)
    engine = AnalyticsEngine()
    published = dict(engine._calculate_basic_metrics(series))
    published.update(engine._calculate_risk_metrics(series))
    return series, published, extra_seed


def test_block_publishes_the_design_that_produced_its_numbers():
    series, published, _ = _engine_block()
    block = measure_estimate_uncertainty(
        series.to_numpy(), engine_risk_statistics(0.02),
        {"sharpe_ratio": published["sharpe_ratio"]}, scope="unit test",
    )
    assert block["bootstrap_resamples"] == UNCERTAINTY_BOOTSTRAP_RESAMPLES
    assert block["resample_seed"] == UNCERTAINTY_BOOTSTRAP_SEED
    assert block["confidence_level"] == UNCERTAINTY_CONFIDENCE_LEVEL
    assert block["block_size"] == moving_block_size(block["observations"])
    assert "Politis" in block["block_size_basis"]
    assert "Politis & Romano" in block["method_basis"]
    assert "reproduces the published point value" in block["point_tolerance_basis"]
    entry = block["estimates"]["sharpe_ratio"]
    assert entry["status"] == "computed"
    assert str(block["observations"]) in entry["conf_int_basis"]
    assert str(block["block_size"]) in entry["conf_int_basis"]
    assert str(block["bootstrap_resamples"]) in entry["conf_int_basis"]


def test_a_different_seed_moves_the_band_so_it_is_a_measurement_not_a_constant():
    series, published, _ = _engine_block()
    first = measure_estimate_uncertainty(
        series.to_numpy(), engine_risk_statistics(0.02),
        {"sharpe_ratio": published["sharpe_ratio"]}, scope="t",
        seed=UNCERTAINTY_BOOTSTRAP_SEED,
    )["estimates"]["sharpe_ratio"]["conf_int"]
    second = measure_estimate_uncertainty(
        series.to_numpy(), engine_risk_statistics(0.02),
        {"sharpe_ratio": published["sharpe_ratio"]}, scope="t",
        seed=UNCERTAINTY_BOOTSTRAP_SEED + 1,
    )["estimates"]["sharpe_ratio"]["conf_int"]
    assert first is not None and second is not None
    assert first != second
    # overlapping, not identical: two draws of the SAME estimator
    assert first[0] < second[1] and second[0] < first[1]


# ---------------------------------------------------------------------------
# route wiring -- a block that never reaches the payload publishes nothing
# ---------------------------------------------------------------------------

def _recent_business_days(periods: int) -> pd.DatetimeIndex:
    """Anchored to now, so a holding stamped today always has rows in the frame."""
    return pd.date_range(end=pd.Timestamp.now().normalize(), periods=periods, freq="B")


def _ohlcv(dates: pd.DatetimeIndex, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0004, 0.010, len(dates))))
    return pd.DataFrame(
        {
            "date": dates,
            "adj_close": closes,
            "volume": np.full(len(dates), 1000.0),
        }
    )


async def test_tear_sheet_route_publishes_the_blocks_in_the_payload(
    test_db,
):
    """The block has to be INSIDE the section, or ENV-020 sees nothing.

    Asserting the helper in isolation proves the arithmetic; only the route
    proves the disclosure survives to a consumer.
    """
    from unittest.mock import AsyncMock, Mock

    from app.api.analytics import get_tear_sheet
    from app.models.database import PortfolioPosition

    dates = _recent_business_days(300)
    test_db.add(
        PortfolioPosition(
            ticker="UNC1.NS", weight=1.0, quantity=10, buy_price=100.0,
            last_price=110.0, market_value=1100.0,
            added_on=dates[0].to_pydatetime(),
        )
    )
    await test_db.commit()
    try:
        mock_ds = Mock()
        mock_ds.fetch_historical_data = AsyncMock(return_value=_ohlcv(dates, 11))
        mock_ds.get_coverage = AsyncMock(return_value={})
        bench = pd.Series(
            np.random.default_rng(4).normal(0.0003, 0.010, len(dates)), index=dates
        )
        mock_bench = Mock()
        mock_bench.get_returns = AsyncMock(return_value=bench)
        result = await get_tear_sheet(
            tickers="UNC1.NS", start="2024-01-01", end=dates[-1].strftime("%Y-%m-%d"),
            db=test_db, data_service=mock_ds, benchmark=mock_bench,
        )
    finally:
        await test_db.execute(PortfolioPosition.__table__.delete())
        await test_db.commit()

    metrics_block = result["estimate_uncertainty"]["metrics"]
    _assert_block_contract(metrics_block)
    assert metrics_block["status"] == "computed"
    assert metrics_block["estimates"]["sharpe"]["conf_int"] is not None
    assert (
        metrics_block["estimates"]["sharpe"]["observations"]
        == result["measured_window"]["observation_count"]
    )
    # the full-depth sibling is a DIFFERENT sample and says so
    full = result["full_history"]["estimate_uncertainty"]["metrics"]
    _assert_block_contract(full)
    assert "full_history" in full["scope"]
    relative = result["estimate_uncertainty"]["relative_vs_nifty"]
    _assert_block_contract(relative["market_model"])
    _assert_block_contract(relative["benchmark"])
    assert relative["market_model"]["estimates"]["beta_vs_nifty"]["conf_int"] is not None
    assert (
        relative["market_model"]["observations"] == result["relative_vs_nifty"]["overlap_days"]
    )
    assert _uncertainty_tokens_present(result)
    json.dumps(result["estimate_uncertainty"])


async def test_optimizer_route_single_holding_publishes_a_block(test_db):
    """The one-leg path builds its own block; it must not crash or go silent."""
    from unittest.mock import AsyncMock, Mock

    from app.api.analytics import OptimizeRequest, run_optimization
    from app.models.database import PortfolioPosition

    dates = _recent_business_days(200)
    test_db.add(
        PortfolioPosition(
            ticker="UNCS.NS", weight=1.0, quantity=10, buy_price=100.0,
            last_price=110.0, market_value=1100.0,
            added_on=dates[0].to_pydatetime(),
        )
    )
    await test_db.commit()
    try:
        mock_ds = Mock()
        mock_ds.fetch_historical_data = AsyncMock(return_value=_ohlcv(dates, 13))
        result = await run_optimization(
            body=OptimizeRequest(strategy="hrp", tickers=["UNCS.NS"]),
            db=test_db, data_service=mock_ds,
        )
    finally:
        await test_db.execute(PortfolioPosition.__table__.delete())
        await test_db.commit()

    block = result["estimate_uncertainty"]
    _assert_block_contract(block)
    assert block["status"] == "computed"
    assert block["estimates"]["expected_sharpe"]["conf_int"] is not None
    assert "normal_theory_standard_error" in block["estimates"]["expected_annual_return"]

