"""`expected_shortfall_vs_target` publishes a 0.0 that reads as a measurement.

Expected shortfall is the mean shortfall *of the paths that fell short*. When
every simulated path clears the target the conditioning set is EMPTY, its mean
is undefined, and the service published `0.0` - a number indistinguishable,
on its own, from "the average path missed by nothing". It happens to be
self-explaining only while `round(prob_success, 4) != 1.0`: past ~20,000 paths
a few misses round `prob_success` to 1.0 while the sentinel is still 0.0.

The fix is not to restructure the statistic. It is to publish the size of the
set the mean was taken over, so the sentinel can only be read as a sentinel.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.services.monte_carlo_service import simulate_goal


def _returns_series(seed: int = 5, n: int = 500) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.Series(rng.normal(0.0004, 0.011, n), index=idx)


def test_an_empty_conditioning_set_ships_its_own_size():
    """Every path clears the target: there is no shortfall distribution."""
    out = simulate_goal(
        _returns_series(),
        initial_value=1_000_000,
        target_value=1_001,
        horizon_years=3,
        method="gbm",
        num_paths=400,
        seed=9,
    )

    assert out["prob_success"] == 1.0  # nothing failed, by construction
    assert out["expected_shortfall_vs_target"] == 0.0  # the sentinel
    # ...and the sentinel is legible, because the set it summarises is published.
    assert out["expected_shortfall_paths_failing"] == 0


def test_the_published_count_is_the_conditioning_set_not_a_guess():
    out = simulate_goal(
        _returns_series(),
        initial_value=1_000_000,
        target_value=1_500_000,
        horizon_years=5,
        method="gbm",
        num_paths=400,
        seed=42,
    )

    failing = out["expected_shortfall_paths_failing"]
    assert isinstance(failing, int)
    assert 0 < failing <= out["num_paths"]
    # It has to reconcile with the other two published figures, so it cannot be
    # a restatement of one of them: successes + failures == num_paths.
    assert round(out["prob_success"] * out["num_paths"]) + failing == out["num_paths"]
    assert out["expected_shortfall_vs_target"] < 0  # failing paths miss by value


def test_a_total_miss_reports_every_path_as_failing():
    out = simulate_goal(
        _returns_series(),
        initial_value=1_000,
        target_value=1_000_000_000,
        horizon_years=2,
        method="gbm",
        num_paths=400,
        seed=9,
    )

    assert out["prob_success"] == 0.0
    assert out["expected_shortfall_paths_failing"] == out["num_paths"]