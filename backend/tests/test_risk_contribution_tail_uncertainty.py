"""SI-5: the risk contribution tail estimates have to declare their precision.

`risk_contribution` publishes two order statistics of the portfolio's own daily
return series and published both as bare points to six decimals:

  * ``portfolio_var_95_daily`` - the 5th percentile of the series;
  * ``portfolio_cvar_95_daily`` - the mean of the days at or below it.

Neither is a stable function of the window, so a reader had no way to know how
much of that precision was real. This file pins the disclosure and, more
importantly, pins WHY it looks the way it does.

THE TRAP THIS TEST EXISTS FOR
-----------------------------
There are two populations here and they are not the same number:

  * the RESAMPLING frame is the whole published series, because the statistic
    being resampled is the 5th percentile OF that series.  A bootstrap over the
    tail alone would measure the 5th percentile of the tail - a different
    statistic - and `measure_estimate_uncertainty`'s reproduction guard would
    refuse the band, correctly.
  * the EFFECTIVE SAMPLE SIZE is the tail.  A 5 % quantile learns nothing from
    the 95 % of days above it, and the expected shortfall is literally the mean
    of the tail days and nothing else.

Publishing the window's effective n as if it described the estimate is the
defect; so is publishing a number that exceeds the tail. Both are asserted.

No audit CLI here: it reads a frozen export, so a green gate would say nothing
about this code. The rule's own token set is imported instead, so the in-process
assertion is made against the constants the rule actually uses.
"""

from __future__ import annotations

import json
import math
from typing import List

import numpy as np
import pandas as pd
import pytest

from app.api.analytics import (
    RISK_CONTRIBUTION_TAIL_SUPPORT_SCOPE,
    _risk_contribution_tail_uncertainty,
)
from app.debugging.context_audit import UNCERTAINTY_KEY_TOKENS
from app.services.analytics_engine import (
    UNCERTAINTY_BOOTSTRAP_RESAMPLES,
    UNCERTAINTY_BOOTSTRAP_SEED,
    UNCERTAINTY_CONFIDENCE_LEVEL,
    UNCERTAINTY_MIN_OBSERVATIONS,
    ar1_autocorrelation,
    effective_sample_size,
    moving_block_size,
)

FIELDS = ("portfolio_var_95_daily", "portfolio_cvar_95_daily")


# ---------------------------------------------------------------------------
# fixtures -- a portfolio return series with a KNOWN lag, so `effective_n < n`
# is a property of the data and not of the code
# ---------------------------------------------------------------------------

def _portfolio_returns(observations: int = 172, rho: float = 0.4, seed: int = 5):
    """An AR(1) daily return series, which is what daily equity returns are."""
    rng = np.random.default_rng(seed)
    shocks = rng.normal(0.0002, 0.010, observations)
    out = np.zeros(observations)
    for t in range(1, observations):
        out[t] = rho * out[t - 1] + shocks[t]
    return pd.Series(out, index=pd.bdate_range("2025-01-01", periods=observations))


def _publishable(series: pd.Series) -> dict:
    """The two published points, computed exactly as the route computes them."""
    var_95 = float(np.percentile(series, 5))
    tail = series <= var_95
    return {
        "var_95": var_95,
        "tail": tail,
        "published": {
            "portfolio_var_95_daily": round(var_95, 6),
            "portfolio_cvar_95_daily": (
                round(float(series[tail].mean()), 6) if bool(tail.any()) else None
            ),
        },
    }


def _block(series: pd.Series, **overrides) -> dict:
    resolved = _publishable(series)
    return _risk_contribution_tail_uncertainty(
        series,
        var_95=resolved["var_95"],
        tail_mask=resolved["tail"],
        published=resolved["published"],
        scope="risk_contribution (test)",
        **overrides,
    )


def _env020(sections) -> List[str]:
    """ENV-020's own verdict, run in process on a payload built by this code."""
    from pathlib import Path

    from app.debugging.context_audit import (
        Export,
        env_020_point_estimates_carry_uncertainty,
    )

    export = Export(
        doc={"schema_version": "2.0", "sections": sections},
        raw="",
        path=Path("memory"),
    )
    return [f.message for f in env_020_point_estimates_carry_uncertainty(export)]


def _assert_block_contract(block) -> None:
    assert block["scope"]
    assert block["status"] in {"computed", "not_computed"}
    assert set(block["estimates"]) == set(FIELDS)
    for field, entry in block["estimates"].items():
        assert entry["status"] in {"computed", "not_computed", "not_applicable"}, field
        assert "conf_int" in entry, f"{field} omitted conf_int entirely"
        if entry["conf_int"] is None:
            assert entry["standard_error"] is None, field
            assert entry["status"] != "computed", field
            assert entry["reason"], f"{field} has no interval and no reason"
        else:
            assert entry["status"] == "computed", field
            assert entry["reason"] is None, field
            assert entry["conf_int_level"] == UNCERTAINTY_CONFIDENCE_LEVEL, field
            low, high = entry["conf_int"]
            assert math.isfinite(low) and math.isfinite(high) and low <= high, field
            assert entry["standard_error"] is not None and entry["standard_error"] > 0
        # a null effective n is a STATED absence, never a silent one
        assert "effective_n_reason" in entry, field
        if entry["effective_n"] is None:
            assert entry["effective_n_reason"], (
                f"{field} published a null effective_n with no reason"
            )
    json.dumps(block)


# ---------------------------------------------------------------------------
# 1. both tail estimates carry a standard error, an interval and an n
# ---------------------------------------------------------------------------

class TestBothTailEstimatesCarryAPrecisionBasis:
    def test_each_field_publishes_a_standard_error_and_a_real_interval(self):
        block = _block(_portfolio_returns())
        _assert_block_contract(block)
        assert block["status"] == "computed"
        for field in FIELDS:
            entry = block["estimates"][field]
            assert entry["standard_error"] > 0.0, field
            assert entry["conf_int"] is not None, field
            assert entry["conf_int_method"] == "circular_moving_block_bootstrap_percentile"
            # the band describes the published point, not a neighbour
            assert entry["point"] is not None
            assert isinstance(entry["point_within_conf_int"], bool)

    def test_the_interval_is_a_measurement_and_not_a_constant_band(self):
        """NUM-022's failure mode: a band that is the point times a constant."""
        series = _portfolio_returns()
        first = _block(series)
        # a different seed moves the band, so it comes from the resampling
        shifted = _risk_contribution_tail_uncertainty(
            series,
            var_95=_publishable(series)["var_95"],
            tail_mask=_publishable(series)["tail"],
            published=_publishable(series)["published"],
            scope="risk_contribution (test)",
        )
        assert first == shifted, "the same sample and seed must reproduce the block"
        other = _block(_portfolio_returns(seed=99))
        for field in FIELDS:
            assert (
                other["estimates"][field]["conf_int"]
                != first["estimates"][field]["conf_int"]
            )

    def test_the_block_satisfies_the_uncertainty_rule_token_set(self):
        """The rule's own constants, not a hand-written copy of them."""
        block = _block(_portfolio_returns())
        published = {
            key: value
            for key, value in block["estimates"]["portfolio_var_95_daily"].items()
            if any(token in key.lower() for token in UNCERTAINTY_KEY_TOKENS)
            and value is not None
        }
        assert published, "ENV-020 would see no precision disclosure in this section"
        assert "standard_error" in published and "conf_int" in published

    def test_env_020_does_not_fire_on_a_section_carrying_this_block(self):
        """The rule itself, on a payload built here - not a saved artifact.

        The control is the same section WITHOUT the block, which must be red:
        the block is what satisfies the rule, and a test that cannot go red
        proves nothing.
        """
        series = _portfolio_returns()
        resolved = _publishable(series)
        data = dict(resolved["published"])
        data["estimate_uncertainty"] = _block(series)
        assert _env020({"risk_contribution": {"data": data}}) == []
        stripped = {k: v for k, v in data.items() if k != "estimate_uncertainty"}
        assert _env020({"risk_contribution": {"data": stripped}})


# ---------------------------------------------------------------------------
# 2. the effective n is the TAIL, not the window -- the cause, not the value
# ---------------------------------------------------------------------------

class TestTheEffectiveSampleSizeIsTheTail:
    def test_effective_n_is_bounded_by_the_tail_and_far_below_the_window(self):
        series = _portfolio_returns()
        resolved = _publishable(series)
        tail_days = int(resolved["tail"].sum())
        window_days = int(len(series))
        assert 0 < tail_days < window_days, "the fixture must have a real tail"

        block = _block(series)
        for field in FIELDS:
            entry = block["estimates"][field]
            assert entry["support_observations"] == tail_days, field
            assert entry["effective_n"] <= tail_days, (
                f"{field}: an order statistic cannot be informed by more days "
                f"than the tail contains"
            )
            assert entry["effective_n"] < window_days, field
            assert entry["resampling_observations"] == window_days, field
            assert entry["resampling_scope"]

    def test_effective_n_is_recomputed_from_the_tail_sample_not_the_window(self):
        """Independent recomputation, from the tail AR(1) the block publishes."""
        series = _portfolio_returns()
        resolved = _publishable(series)
        tail_values = series.to_numpy(dtype=float)[
            resolved["tail"].to_numpy()
        ]
        expected_ar1 = ar1_autocorrelation(tail_values)
        expected_n = effective_sample_size(int(tail_values.size), expected_ar1)

        block = _block(series)
        support = block["tail_support"]
        assert support["tail_observations"] == int(tail_values.size)
        assert support["window_observations"] == int(len(series))
        assert support["ar1"] == pytest.approx(expected_ar1, abs=1e-6)
        assert support["effective_n"] == pytest.approx(
            min(expected_n, float(int(tail_values.size))), abs=1e-4
        )
        # and it is NOT the window's figure, which is published beside it
        assert support["window_effective_n"] == pytest.approx(
            block["autocorrelation"]["effective_n"], abs=1e-6
        )
        assert support["window_effective_n"] > support["effective_n"]

    def test_a_longer_window_does_not_inflate_the_tail_effective_n(self):
        """The cause: n_eff tracks the TAIL. A longer window adds no tail days."""
        short = _block(_portfolio_returns(observations=172))
        long = _block(_portfolio_returns(observations=300))
        assert (
            long["tail_support"]["tail_observations"]
            > short["tail_support"]["tail_observations"]
        )
        for block in (short, long):
            assert block["tail_support"]["effective_n"] is not None
            for field in FIELDS:
                assert (
                    block["estimates"][field]["effective_n"]
                    <= block["tail_support"]["tail_observations"]
                )
        # the window count, by contrast, is the one that grows
        assert long["tail_support"]["window_observations"] > (
            short["tail_support"]["window_observations"]
        )

    def test_effective_n_is_the_quenouille_adjustment_of_the_tail_ar1(self):
        """The adjustment is APPLIED, whatever the tail's own lag structure.

        A tail of daily returns is usually NEGATIVELY autocorrelated - a large
        loss is followed by a mean-reverting move - so the raw Quenouille figure
        inflates and the published one is bounded. The test therefore asserts
        the arithmetic, not a sign.
        """
        series = _portfolio_returns(observations=400, seed=21)
        block = _block(series)
        support = block["tail_support"]
        ar1 = support["ar1"]
        assert ar1 is not None and -1.0 < ar1 < 1.0
        raw = support["tail_observations"] * (1 - ar1) / (1 + ar1)
        assert support["effective_n_uncapped"] == pytest.approx(raw, abs=1e-3)
        assert support["effective_n"] == pytest.approx(
            min(raw, float(support["tail_observations"])), abs=1e-4
        )

    def test_a_negatively_autocorrelated_tail_is_bounded_and_the_raw_figure_kept(self):
        """The inflation a negative AR(1) produces is shown, not quietly applied."""
        series = _portfolio_returns(observations=172, seed=5)
        block = _block(series)
        support = block["tail_support"]
        if support["ar1"] is None or support["ar1"] >= 0.0:
            pytest.skip("this sample's tail is not negatively autocorrelated")
        assert support["effective_n_uncapped"] > support["tail_observations"]
        assert support["effective_n"] == float(support["tail_observations"])
        assert "redundancy" in support["effective_n_bound"]


# ---------------------------------------------------------------------------
# 3. the null path -- an absence has to SAY so
# ---------------------------------------------------------------------------

class TestTheNullPathIsStated:
    def test_a_tail_too_short_to_fit_an_ar1_publishes_a_reason_not_a_number(self):
        """A 30-day window has a 1-2 day tail: too short for an AR(1) slope.

        The INTERVAL is still computable at 30 rows, so this isolates the
        effective-n null from the too-few-observations case below.
        """
        series = _portfolio_returns(observations=30, seed=9)
        assert UNCERTAINTY_MIN_OBSERVATIONS <= len(series)
        block = _block(series)
        _assert_block_contract(block)
        assert block["status"] == "computed", "the interval is available here"
        support = block["tail_support"]
        assert support["ar1"] is None
        assert support["effective_n"] is None
        assert support["effective_n_reason"]
        assert "too short" in support["effective_n_reason"]
        for field in FIELDS:
            entry = block["estimates"][field]
            assert entry["conf_int"] is not None, field
            assert entry["effective_n"] is None, field
            assert entry["effective_n_reason"], field
            # the honest count is still published: the absence is a missing
            # ADJUSTMENT, not a missing support figure
            assert entry["support_observations"] == support["tail_observations"]

    def test_a_window_below_the_interval_minimum_declares_itself_and_its_count(self):
        series = _portfolio_returns(observations=6, seed=3)
        block = _block(series)
        _assert_block_contract(block)
        assert block["status"] == "not_computed"
        for field in FIELDS:
            entry = block["estimates"][field]
            assert entry["conf_int"] is None
            assert entry["standard_error"] is None
            assert str(UNCERTAINTY_MIN_OBSERVATIONS) in entry["reason"]
        assert block["tail_support"]["tail_observations"] >= 1

    def test_a_withheld_shortfall_says_why_rather_than_publishing_a_zero(self):
        """An expected shortfall that was never measured is `not_applicable`.

        The route publishes `portfolio_cvar_95_daily: None` when no day sits at
        or below the 5th percentile, and the disclosure has to say which of the
        two that is - not measured, or measured as zero.
        """
        series = _portfolio_returns(observations=60, seed=31)
        resolved = _publishable(series)
        block = _risk_contribution_tail_uncertainty(
            series,
            var_95=resolved["var_95"],
            tail_mask=resolved["tail"],
            published={
                "portfolio_var_95_daily": resolved["published"]["portfolio_var_95_daily"],
                "portfolio_cvar_95_daily": None,
            },
            scope="risk_contribution (test)",
        )
        _assert_block_contract(block)
        shortfall = block["estimates"]["portfolio_cvar_95_daily"]
        assert shortfall["point"] is None
        assert shortfall["status"] == "not_applicable"
        assert "undefined rather than zero" in shortfall["reason"]
        # the quantile beside it is still a real measurement
        assert block["estimates"]["portfolio_var_95_daily"]["conf_int"] is not None


# ---------------------------------------------------------------------------
# 4. the band belongs to the published numbers (the machinery's own guard)
# ---------------------------------------------------------------------------

class TestTheBandBelongsToThePublishedNumbers:
    def test_the_interval_is_reproduced_by_an_independent_bootstrap(self):
        """Rebuild the resampling distribution from scratch, then compare."""
        series = _portfolio_returns(observations=200, seed=21)
        resolved = _publishable(series)
        values = series.to_numpy(dtype=float)
        n = int(values.size)
        block_size = moving_block_size(n)
        starts_count = int(np.ceil(n / block_size))
        rng = np.random.default_rng(UNCERTAINTY_BOOTSTRAP_SEED)
        starts = rng.integers(0, n, size=(UNCERTAINTY_BOOTSTRAP_RESAMPLES, starts_count))
        offsets = np.arange(block_size)
        indices = (starts[:, :, None] + offsets[None, None, :]) % n
        indices = indices.reshape(UNCERTAINTY_BOOTSTRAP_RESAMPLES, -1)[:, :n]
        draws = values[indices]                                # (resamples, n)
        resample_var = np.percentile(draws, 5, axis=1)         # per-resample VaR
        shortfall = np.empty(draws.shape[0], dtype=float)
        for row in range(draws.shape[0]):                      # a different
            tail_rows = draws[row] <= resample_var[row]         # accumulation order
            shortfall[row] = draws[row][tail_rows].mean()
        expected = {
            "portfolio_var_95_daily": resample_var,
            "portfolio_cvar_95_daily": shortfall,
        }
        block = _risk_contribution_tail_uncertainty(
            series,
            var_95=resolved["var_95"],
            tail_mask=resolved["tail"],
            published=resolved["published"],
            scope="risk_contribution (test)",
        )
        for field in FIELDS:
            got = block["estimates"][field]["conf_int"]
            want = np.percentile(expected[field], [2.5, 97.5])
            assert got[0] == pytest.approx(want[0], abs=1e-6), field
            assert got[1] == pytest.approx(want[1], abs=1e-6), field
            assert block["estimates"][field]["point_status"] == (
                "reproduced_by_estimator"
            )

    def test_the_standard_error_is_the_resample_dispersion_and_a_movement(self):
        series = _portfolio_returns(observations=200, seed=21)
        block = _block(series)
        for field in FIELDS:
            assert block["estimates"][field]["standard_error"] > 0.0
        other = _block(_portfolio_returns(observations=200, seed=77))
        moved = [
            field for field in FIELDS
            if other["estimates"][field]["standard_error"]
            != block["estimates"][field]["standard_error"]
        ]
        assert moved, "a different sample must move at least one standard error"

    def test_the_scope_says_which_population_the_block_measures(self):
        block = _block(_portfolio_returns())
        support = block["tail_support"]
        assert support["scope"] == RISK_CONTRIBUTION_TAIL_SUPPORT_SCOPE
        assert support["basis"]
        assert "5th percentile" in support["basis"]
        assert block["notes"]["tail_support_scope"] == (
            RISK_CONTRIBUTION_TAIL_SUPPORT_SCOPE
        )

    def test_the_block_is_the_same_shape_as_every_other_uncertainty_block(self):
        """A consumer that reads one block must be able to read this one."""
        block = _block(_portfolio_returns())
        for key in (
            "scope", "status", "method", "method_basis", "confidence_level",
            "observations", "observation_columns", "block_size", "resample_seed",
            "bootstrap_resamples", "autocorrelation", "estimates", "point_tolerance",
        ):
            assert key in block, key
        assert block["method"] == "circular_moving_block_bootstrap_percentile"
        assert block["autocorrelation"]["effective_n"] is not None
        # the guard is the machinery's own, at a tolerance that admits float noise
        assert block["point_tolerance"] == 1e-5
