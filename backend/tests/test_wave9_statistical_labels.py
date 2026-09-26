"""Wave 9 (SI-11 / SI-7 / AD-9): three claims whose labels misstate the computation.

Each test here pins the CAUSE of the defect, not just the value that replaced
it, so it fails if the cause returns even under a different number:

- SI-11(a) `classify` receives only benchmark data, so a feature published as
  `log_holding_return` claims to describe a book the function cannot see.
- SI-11(b) `hmm.fit()`'s return value was discarded, so no convergence state
  was published at all; and hmmlearn's own `converged` is true when the
  ITERATION CAP is hit, so the bare flag is not evidence of convergence.
- SI-11(c) the per-state `n_sub` was computed and dropped, so `ann_ret` was a
  geometric mean over an unpublished n extrapolated by 252/n.
- SI-7 `percentile_rank` was gated on `len(rolling_vol) >= 2`, but the rolling
  windows OVERLAP: a 252-day cone on 2486 returns is 2235 windows and ~8.9
  independent observations, so a rank published off it carries a ~33pp
  half-width.
- AD-9 the correlation break test was upper-tail only, so a collapse in
  co-movement reached the "within normal historical bounds" message.

No DB, no network, no audit CLI: seeded RNG and faked estimators only.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.services.correlation_service import analyze_correlation_stability
from app.services.regime_service import (
    HMM_N_ITER,
    HMM_TOL,
    MIN_OBSERVATIONS,
    _regime_metadata,
    classify,
    detect_regime,
)
from app.services.volatility_service import (
    MIN_EFFECTIVE_OBSERVATIONS_FOR_PERCENTILE,
    VolatilityService,
    _percentile_rank_basis,
)

REGIME_LABELS = {"crisis", "calm", "bull"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _benchmark_frame(n=719, seed=3):
    """Price frame of the shape `classify` is given: a benchmark, nothing else."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-01", periods=n, freq="B")
    close = (1.0 + rng.normal(0.0005, 0.011, n)).cumprod() * 100.0
    return pd.DataFrame(
        {"close": close, "high": close * 1.005, "low": close * 0.995}, index=dates
    )


async def _detect_regime(frame):
    with patch("app.services.regime_service.BenchmarkService") as cls:
        inst = cls.return_value
        inst.get_benchmark_df = AsyncMock(return_value=frame)
        inst.get_returns = AsyncMock(return_value=None)
        return await detect_regime(MagicMock(), lookback_days=1100)


def _daily_returns(n=2486, seed=11):
    rng = np.random.default_rng(seed)
    return pd.Series(
        rng.normal(0.0004, 0.011, n), index=pd.bdate_range("2016-09-12", periods=n)
    )


# ===========================================================================
# SI-11(a) - a benchmark feature published as a holding feature
# ===========================================================================
class TestRegimeFeatureProvenance:
    def test_classify_cannot_see_holdings_so_no_feature_may_say_holding(self):
        """Pin the cause: `classify` takes benchmark data and nothing else.

        If a holdings input is ever threaded in, this test fails and the
        "holding" name becomes defensible. Until then the name must not claim
        the book.
        """
        import inspect

        params = set(inspect.signature(classify).parameters)
        assert "bench_data" in params
        assert not (params & {"holdings", "positions", "portfolio", "portfolio_returns"})

    async def test_published_feature_is_named_for_the_benchmark(self):
        res = await _detect_regime(_benchmark_frame())
        features = res["model"]["features"]
        assert features == [
            "ret21_log_benchmark_return_21d",
            "vol21_realized_vol_21d_annualized",
        ]
        # The defect was a name asserting a source the payload contradicts.
        assert not any("holding" in name for name in features)

    async def test_model_block_declares_the_feature_source(self):
        res = await _detect_regime(_benchmark_frame())
        model = res["model"]
        assert model["feature_source"] == "benchmark_series_not_portfolio_holdings"
        assert "not the book" in model["feature_source_detail"]
        # The declaration must agree with the sibling benchmark block.
        assert res["benchmark"]["symbol"] == "^NSEI"


# ===========================================================================
# SI-11(b) - the discarded convergence monitor
# ===========================================================================
class _Monitor:
    """hmmlearn 0.3.3's ConvergenceMonitor surface, built by hand."""

    def __init__(self, history, iter_, n_iter, tol):
        self.history = list(history)
        self.iter = iter_
        self.n_iter = n_iter
        self.tol = tol

    @property
    def converged(self):
        # Verbatim 0.3.3 semantics: the CAP counts as converged.
        return self.iter == self.n_iter or (
            len(self.history) >= 2
            and self.history[-1] - self.history[-2] < self.tol
        )


class _FakeHMM:
    def __init__(self, *args, monitor=None, **kwargs):
        self.startprob_ = np.array([0.33, 0.34, 0.33])
        self.transmat_ = np.array(
            [[0.96, 0.03, 0.01], [0.02, 0.96, 0.02], [0.01, 0.03, 0.96]]
        )
        self._monitor = monitor

    @property
    def monitor_(self):
        if self._monitor is _MISSING:
            raise AttributeError("monitor_")
        return self._monitor

    def fit(self, x):
        return self

    def predict(self, x):
        return np.array([i % 3 for i in range(len(x))])

    def predict_proba(self, x):
        return np.tile(np.array([0.6, 0.3996, 0.0004]), (len(x), 1))


_MISSING = object()


class _FakeScaler:
    def fit_transform(self, x):
        return np.asarray(x, dtype=float)


def _classify_with_monitor(monitor):
    hmm_cls = lambda *a, **kw: _FakeHMM(*a, monitor=monitor, **kw)  # noqa: E731
    with (
        patch("sklearn.preprocessing.StandardScaler", _FakeScaler),
        patch("hmmlearn.hmm.GaussianHMM", hmm_cls),
    ):
        return classify(_benchmark_frame())


class TestRegimeConvergenceDisclosure:
    async def test_real_fit_publishes_its_convergence_state(self):
        res = await _detect_regime(_benchmark_frame())
        conv = res["model_convergence"]
        assert conv["available"] is True
        assert isinstance(conv["converged"], bool)
        assert isinstance(conv["iterations_run"], int) and conv["iterations_run"] >= 1
        assert conv["iteration_cap"] == HMM_N_ITER
        assert conv["tolerance"] == HMM_TOL
        assert conv["converged_within_tolerance"] is True
        assert conv["hit_iteration_cap"] is False
        assert conv["final_log_likelihood"] is not None
        assert conv["log_likelihood_observations"] == conv["iterations_run"]
        assert "in_sample" in conv["evaluation_basis"]
        assert "no holdout" in conv["posterior_basis"]

    def test_converged_because_the_cap_was_hit_is_not_reported_as_converged(self):
        """Pin the cause: hmmlearn's `converged` is true at the cap too.

        A fit that exhausted its 200 iterations with a last improvement far
        above tolerance MUST NOT read as a converged fit, and the payload must
        make the distinction rather than republish the flag alone.
        """
        history = [-1000.0 + i for i in range(HMM_N_ITER)]  # still improving hard
        monitor = _Monitor(history, iter_=HMM_N_ITER, n_iter=HMM_N_ITER, tol=HMM_TOL)
        conv = _classify_with_monitor(monitor)["model_convergence"]

        assert conv["converged"] is True  # hmmlearn says so (iter == n_iter)
        assert conv["hit_iteration_cap"] is True
        assert conv["converged_within_tolerance"] is False
        assert conv["final_log_likelihood_delta"] == pytest.approx(1.0)
        assert "iteration cap" in conv["convergence_rule"]

    def test_non_monotone_likelihood_is_published_not_swallowed(self):
        # The last step is tiny (tolerance met) but an earlier step went
        # backwards, which hmmlearn only warns about in `report()`.
        history = [-1000.0, -900.0, -950.0, -950.00001]
        monitor = _Monitor(history, iter_=4, n_iter=HMM_N_ITER, tol=HMM_TOL)
        conv = _classify_with_monitor(monitor)["model_convergence"]
        assert conv["log_likelihood_monotonic"] is False
        assert conv["converged_within_tolerance"] is True  # the delta, not the shape
        assert conv["converged"] is True
        assert conv["final_log_likelihood"] == pytest.approx(-950.00001)

    def test_absent_monitor_publishes_why_it_cannot_be_used(self):
        conv = _classify_with_monitor(_MISSING)["model_convergence"]
        assert conv["available"] is False
        assert conv["converged"] is None
        assert "monitor_" in conv["reason"]
        assert conv["evaluation_basis"] == "unknown"

    def test_convergence_counts_carry_units(self):
        frame = _benchmark_frame()
        payload = classify(frame)
        payload.pop("all_regimes", None)
        meta = _regime_metadata(payload, use_returns=False, lookback_days=1100)
        units = meta["units"]
        assert units["model_convergence.iterations_run"] == "count_em_iterations"
        assert units["model_convergence.iteration_cap"] == "count_em_iterations"
        assert units["model_convergence.final_log_likelihood"] == "log_likelihood_nats"
        assert units["model_convergence.tolerance"] == "log_likelihood_nats_per_iteration"
        assert "no holdout" in payload["model_convergence"]["posterior_basis"]


# ===========================================================================
# SI-11(c) - the per-state n that was computed and dropped
# ===========================================================================
class TestRegimeStateSampleSize:
    async def test_each_state_publishes_the_n_behind_its_annualized_return(self):
        res = await _detect_regime(_benchmark_frame())
        states = res["states"]
        assert {s["regime"] for s in states} == REGIME_LABELS
        for row in states:
            assert isinstance(row["observations"], int) and row["observations"] > 0
            # ann_ret is a geometric mean over `observations` days
            # extrapolated to 252, so the factor is what turns it into a
            # per-year figure and must be published with it.
            assert row["annualization_factor"] == pytest.approx(
                252.0 / row["observations"], abs=5e-4
            )

    async def test_state_counts_partition_the_classification_sample(self):
        res = await _detect_regime(_benchmark_frame())
        total = res["observations"]
        assert total >= MIN_OBSERVATIONS
        assert sum(s["observations"] for s in res["states"]) == total
        for row in res["states"]:
            # days_pct was already published; `observations` is its denominator.
            assert row["historical_days_pct"] == pytest.approx(
                100.0 * row["observations"] / total, abs=0.05
            )

    def test_state_observations_carry_units(self):
        payload = classify(_benchmark_frame())
        payload.pop("all_regimes", None)
        units = _regime_metadata(payload, use_returns=False, lookback_days=1100)["units"]
        assert units["states[].observations"] == "count_trading_days"
        assert units["states[].annualization_factor"] == (
            "ratio_trading_days_per_year_over_state_observations"
        )


# ===========================================================================
# SI-7 - the vol-cone verdict on overlapping windows
# ===========================================================================
class TestVolConeEffectiveN:
    def test_effective_count_is_windows_over_window_length(self):
        assert _percentile_rank_basis(2235, 252)["effective_n"] == pytest.approx(
            8.87, abs=0.01
        )
        assert _percentile_rank_basis(2477, 10)["effective_n"] == pytest.approx(
            247.7, abs=0.01
        )
        assert _percentile_rank_basis(0, 10)["effective_n"] is None
        assert _percentile_rank_basis(10, 0)["effective_n"] is None

    def test_published_half_width_reproduces_the_effective_n_arithmetic(self):
        basis = _percentile_rank_basis(2235, 252)
        # 1.96 * 100 * sqrt(0.25 / 8.87) = 32.9pp on the 252d cone.
        assert basis["percentile_rank_95pct_half_width_pct"] == pytest.approx(32.9, abs=0.1)
        assert basis["minimum_effective_n_for_percentile_rank"] == 30.0
        assert "overlapping" in basis["effective_n_rule"]

    def test_long_window_cone_withholds_the_rank_it_cannot_support(self):
        """The audited book: 2486 returns, 252-day window, ~8.9 effective n."""
        cone = VolatilityService.calculate_volatility_cone(_daily_returns(), windows=[252])
        row = cone["windows"][0]
        assert row["window_days"] == 252
        assert row["n_windows"] == 2486 - 252 + 1 == 2235
        assert row["effective_n"] == pytest.approx(8.87, abs=0.01)
        assert row["effective_n"] < MIN_EFFECTIVE_OBSERVATIONS_FOR_PERCENTILE
        # The verdict is withheld, not replaced by another number...
        assert row["percentile_rank"] is None
        # ...and the reason plus the precision that is missing are published.
        assert row["percentile_rank_sufficient_data"] is False
        assert "withheld" in row["percentile_rank_withheld_reason"]
        assert "8.87" in row["percentile_rank_withheld_reason"]
        assert row["percentile_rank_95pct_half_width_pct"] == pytest.approx(32.9, abs=0.1)
        # The measured level and the description of the sample survive.
        assert row["current_realized"] is not None
        assert row["median"] is not None

    def test_short_window_cone_still_publishes_its_rank_with_its_precision(self):
        """Do not over-refuse: at 247.7 effective observations the rank is fine."""
        cone = VolatilityService.calculate_volatility_cone(_daily_returns(), windows=[10])
        row = cone["windows"][0]
        assert row["effective_n"] == pytest.approx(247.7, abs=0.01)
        assert row["percentile_rank_sufficient_data"] is True
        assert row["percentile_rank_withheld_reason"] is None
        assert 0.0 <= row["percentile_rank"] <= 100.0
        assert row["percentile_rank_95pct_half_width_pct"] == pytest.approx(6.2, abs=0.1)

    def test_gate_boundary_is_the_effective_count_not_the_raw_one(self):
        """2235 raw windows is 'plenty'; 8.87 independent observations is not."""
        thin = _percentile_rank_basis(2235, 252)
        dense = _percentile_rank_basis(2235, 21)
        assert thin["n_windows"] == dense["n_windows"] == 2235
        assert thin["percentile_rank_sufficient_data"] is False
        assert dense["percentile_rank_sufficient_data"] is True

    def test_forecast_rank_inherits_the_same_gate_and_basis(self):
        """`current_forecast.percentile_rank` ranks against the same series."""
        cone = VolatilityService.calculate_volatility_cone(
            _daily_returns(), windows=[252]  # benchmark window forced to 252d
        )
        fc = cone["current_forecast"]
        assert fc["ranked_against_window_days"] == 252
        assert fc["n_windows"] == 2235
        assert fc["effective_n"] == pytest.approx(8.87, abs=0.01)
        assert fc["percentile_rank"] is None
        assert fc["percentile_rank_sufficient_data"] is False
        # The GARCH level and its valuation are unchanged: only the rank is gated.
        assert fc["annualized_vol"] > 0
        assert fc["valuation"] in {"cheap", "normal", "rich"}


# ===========================================================================
# AD-9 - the one-sided correlation regime test
# ===========================================================================
def _fake_rolling_series(monkeypatch, values):
    idx = pd.bdate_range("2024-01-01", periods=len(values))
    series = pd.Series(values, index=idx)
    monkeypatch.setattr(
        "app.services.correlation_service.compute_rolling_avg_correlation",
        lambda *a, **k: series,
    )


def _stub_returns(n_tickers=3, periods=120):
    idx = pd.bdate_range("2024-01-01", periods=periods)
    return pd.DataFrame(
        {f"A{i}": np.full(periods, 0.01) for i in range(n_tickers)}, index=idx
    )


class TestCorrelationTwoSidedRegimeTest:
    def test_a_collapse_in_correlation_is_not_reported_as_normal(self, monkeypatch):
        """The audited case: 0.140 current against a 0.341 median.

        Historically ~0.50, now 0.14. Under an upper-tail-only test this reached
        the ELSE branch and its "within normal historical bounds" message.
        """
        _fake_rolling_series(monkeypatch, [0.50] * 99 + [0.1404])
        res = analyze_correlation_stability(_stub_returns(), window_days=60)

        assert res.current_avg_correlation == pytest.approx(0.1404)
        assert res.historical_median == pytest.approx(0.50)
        assert res.is_regime_break is True
        assert res.alert_level != "NORMAL"
        assert res.alert_level == "ELEVATED"
        # The message a downstream model quotes must not assert normality.
        assert "normal historical bounds" not in res.message
        assert "10th" in res.message and "0.140" in res.message
        assert "may not diversify" in res.message

    def test_flag_and_alert_come_from_the_same_two_comparisons(self, monkeypatch):
        """Both tails must be driven by one comparison each.

        A flat series makes current == p90 == p10 exactly; the flag and the
        alert must agree, and the upper tail must keep winning the tie so the
        existing CRITICAL semantics are unchanged.
        """
        _fake_rolling_series(monkeypatch, [0.90] * 120)
        res = analyze_correlation_stability(_stub_returns(), window_days=30)
        assert res.is_regime_break is True
        assert res.alert_level == "CRITICAL"
        assert res.is_regime_break is (res.alert_level == "CRITICAL")

    def test_upper_tail_behaviour_is_unchanged(self, monkeypatch):
        _fake_rolling_series(monkeypatch, [0.30] * 99 + [0.55])
        critical = analyze_correlation_stability(_stub_returns(), window_days=60)
        assert critical.is_regime_break is True
        assert critical.alert_level == "CRITICAL"
        assert "Diversification breakdown detected." in critical.message

        _fake_rolling_series(monkeypatch, list(np.linspace(0.10, 0.60, 100)) + [0.53])
        elevated = analyze_correlation_stability(_stub_returns(), window_days=60)
        assert elevated.is_regime_break is False
        assert elevated.alert_level == "ELEVATED"
        assert "75th percentile" in elevated.message
        assert "10th" not in elevated.message  # upper branch, unchanged wording

    def test_normal_branch_states_the_band_it_actually_tested(self, monkeypatch):
        """`NORMAL` is only a bounded claim, so the bounds must be in it."""
        values = list(np.linspace(0.20, 0.50, 100)) + [0.34]
        _fake_rolling_series(monkeypatch, values)
        res = analyze_correlation_stability(_stub_returns(), window_days=60)

        assert res.is_regime_break is False
        assert res.alert_level == "NORMAL"
        assert "10th-90th percentile band" in res.message
        # The distribution being ranked is overlapping windows; say so, with n.
        assert f"{len(values)} overlapping 60-day rolling windows" in res.message
        assert "in-sample rank, not a significance test" in res.message
