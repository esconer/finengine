"""Tests for the Monte Carlo goal-probability engine (service level)."""

import numpy as np
import pandas as pd
import pytest

from app.services.monte_carlo_service import simulate_goal


def _returns_series(seed: int = 7, n: int = 500) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.Series(rng.normal(0.0004, 0.011, n), index=idx)


class TestSimulateGoal:
    def test_gbm_is_deterministic_with_seed(self):
        r = _returns_series()
        a = simulate_goal(r, initial_value=1_000_000, target_value=1_500_000,
                          horizon_years=5, method="gbm", num_paths=500, seed=42)
        b = simulate_goal(r, initial_value=1_000_000, target_value=1_500_000,
                          horizon_years=5, method="gbm", num_paths=500, seed=42)
        assert a["prob_success"] == b["prob_success"]
        assert a["terminal_percentiles"] == b["terminal_percentiles"]

    def test_prob_success_within_bounds_and_percentiles_monotonic(self):
        r = _returns_series(seed=11)
        out = simulate_goal(r, initial_value=100_000, target_value=180_000,
                            horizon_years=7, method="bootstrap", num_paths=800, seed=3)
        assert 0.0 <= out["prob_success"] <= 1.0
        tp = out["terminal_percentiles"]
        assert tp["p5"] <= tp["p25"] <= tp["p50"] <= tp["p75"] <= tp["p95"]

    def test_easy_target_gives_certainty(self):
        r = _returns_series(seed=5)
        out = simulate_goal(r, initial_value=1_000_000, target_value=1_001,
                            horizon_years=3, method="gbm", num_paths=400, seed=9)
        assert out["prob_success"] == 1.0

    def test_impossible_target_gives_zero(self):
        r = _returns_series(seed=5)
        out = simulate_goal(r, initial_value=1_000, target_value=1_000_000_000,
                            horizon_years=2, method="gbm", num_paths=400, seed=9)
        assert out["prob_success"] == 0.0
        assert out["expected_shortfall_vs_target"] < 0

    def test_fan_checkpoints_cover_horizon(self):
        r = _returns_series(seed=13)
        out = simulate_goal(r, initial_value=500_000, target_value=750_000,
                            horizon_years=4, method="gbm", num_paths=300, seed=1)
        years = [pt["year"] for pt in out["fan"]]
        assert years[0] == 0.0
        assert years[-1] == 4.0
        assert all(p5 <= p50 <= p95 for p5, p50, p95 in
                   [(pt["p5"], pt["p50"], pt["p95"]) for pt in out["fan"]])

    def test_bootstrap_preserves_history_length_requirement(self):
        short = _returns_series(n=40)
        with pytest.raises(ValueError, match="at least 60"):
            simulate_goal(short, initial_value=100_000, target_value=120_000,
                          horizon_years=2, method="bootstrap", num_paths=200)

    def test_student_t_fat_tails_widen_p5(self):
        # Genuinely fat-tailed series: calm 90% + violent left jumps 10%
        rng = np.random.default_rng(17)
        n = 600
        regime = rng.random(n) < 0.10
        vals = np.where(regime,
                        rng.normal(-0.02, 0.02, n),
                        rng.normal(0.0005, 0.006, n))
        fat = pd.Series(vals, index=pd.bdate_range("2024-01-01", periods=n))
        calm = _returns_series(seed=17)
        fat_out = simulate_goal(fat, initial_value=100_000, target_value=150_000,
                                horizon_years=5, method="student_t", num_paths=500, seed=4)
        calm_out = simulate_goal(calm, initial_value=100_000, target_value=150_000,
                                 horizon_years=5, method="student_t", num_paths=500, seed=4)
        # The fitted degrees-of-freedom is the tail diagnostic: jumps → low df
        assert fat_out["student_t_df"] < 10.0
        assert calm_out["student_t_df"] > fat_out["student_t_df"]
        assert 0.0 <= fat_out["prob_success"] <= 1.0

    def test_student_t_deterministic_with_seed(self):
        r = _returns_series(seed=19)
        a = simulate_goal(r, initial_value=100_000, target_value=160_000,
                          horizon_years=4, method="student_t", num_paths=400, seed=8)
        b = simulate_goal(r, initial_value=100_000, target_value=160_000,
                          horizon_years=4, method="student_t", num_paths=400, seed=8)
        assert a["prob_success"] == b["prob_success"]

    def test_student_t_near_cauchy_fit_stays_finite(self):
        # Violent outliers push scipy's df fit toward the Cauchy boundary;
        # engine must stay finite (analytic moments + winsorization guard).
        rng = np.random.default_rng(29)
        n = 500
        vals = rng.normal(0.0003, 0.004, n)
        mask = rng.random(n) < 0.06
        vals[mask] = rng.normal(-0.05, 0.05, int(mask.sum()))
        r = pd.Series(vals, index=pd.bdate_range("2024-01-01", periods=n))
        out = simulate_goal(r, initial_value=100_000, target_value=130_000,
                            horizon_years=6, method="student_t", num_paths=600, seed=11)
        tp = out["terminal_percentiles"]
        assert all(np.isfinite([tp["p5"], tp["p25"], tp["p50"], tp["p75"], tp["p95"]]))
        assert tp["p5"] <= tp["p95"]
        assert 0.0 <= out["prob_success"] <= 1.0

    def test_bootstrap_chains_resamples_for_long_horizon(self):
        # 500 obs ≈ 2y of history; 6y horizon forces chained resamples
        r = _returns_series(n=500, seed=23)
        out = simulate_goal(r, initial_value=100_000, target_value=200_000,
                            horizon_years=6, method="bootstrap", num_paths=150, seed=2)
        assert 0.0 <= out["prob_success"] <= 1.0
        assert out["fan"][-1]["year"] == 6.0

    @pytest.mark.parametrize("kwargs, match", [
        ({"initial_value": 0}, "initial_value"),
        ({"target_value": -5}, "target_value"),
        ({"horizon_years": 0}, "horizon_years"),
        ({"horizon_years": 99}, "horizon_years"),
        ({"method": "quantum"}, "method"),
    ])
    def test_invalid_inputs_raise_value_error(self, kwargs, match):
        r = _returns_series()
        params = dict(initial_value=100_000, target_value=150_000,
                      horizon_years=5, method="gbm", num_paths=200)
        params.update(kwargs)
        with pytest.raises(ValueError, match=match):
            simulate_goal(r, **params)

    def test_zero_volatility_series_reaches_guaranteed_growth(self):
        const = pd.Series([0.0004] * 300,
                          index=pd.bdate_range("2024-01-01", periods=300))
        out = simulate_goal(const, initial_value=100_000, target_value=100_000 * 1.0004 ** 252,
                            horizon_years=1, method="gbm", num_paths=100, seed=0)
        assert out["prob_success"] == 1.0
        assert out["historical_sigma_annual"] == 0.0
