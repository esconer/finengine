"""V3-11/V3-13/V3-14 semantics: Monte Carlo success, regime units, pairs depth.

Three audit findings are regression-gated here:

- V3-11  `prob_success` was an unlabelled `0.335` with no statement that it
         is TERMINAL success (share of paths finishing above the target), not
         the probability of touching the target at any point.
- V3-13  regime probabilities / transition rows are percentage points summing
         to 100, the benchmark series was undeclared, and the filtered
         posterior vs the Viterbi-decoded `current_regime` disagreement was
         invisible.
- V3-14  pairs reported `complete` while a young ETF (NIFTYIETF, ~106-109
         usable sessions) sat next to peers with 168-174, and the
         Engle-Granger-decides / Johansen-diagnostic split was unlabelled.

No DB and no network: seeded RNG plus AsyncMock'd benchmark fetches.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.models.schemas import CointPairResult
from app.services.cointegration_service import (
    DECISION_TEST,
    JOHANSEN_ROLE,
    MIN_PAIR_DEPTH_RATIO,
    MIN_PAIR_OBSERVATIONS,
    CointegrationService,
    _db_cache_keys,
    _IN_MEMORY_COINT_CACHE,
    assess_pair_depth,
    analyze_pair_cointegration,
    pair_depth_ratio,
    shallow_tickers,
    summarize_pair_depth,
    usable_observations_by_ticker,
    with_test_role_metadata,
)
from app.services.monte_carlo_service import (
    _calibrate,
    _model_window,
    _simulate_gbm,
    simulate_goal,
)
from app.services.regime_service import (
    MIN_OBSERVATIONS,
    REGIME_STATES,
    _regime_metadata,
    classify,
    detect_regime,
)

REGIME_LABELS = {"crisis", "calm", "bull"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _benchmark_walk(n=300, seed=0):
    """Price frame + matching return series, both long enough to fit."""
    rng = np.random.default_rng(seed)
    rets = pd.Series(
        rng.normal(0.0005, 0.012, n), index=pd.date_range("2023-01-01", periods=n, freq="B")
    )
    close = (1.0 + rets).cumprod() * 100.0
    return close, rets


def _returns_series(seed=7, n=500):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0004, 0.011, n), index=pd.bdate_range("2024-01-01", periods=n))


class _FakeCache:
    """Dict-backed stand-in for CacheService with real (ticker, metric) keying."""

    def __init__(self, store=None):
        self.store = store or {}

    async def get_cached_analytics(self, ticker, metric_name):
        hit = self.store.get((ticker, metric_name))
        if hit is None:
            return None
        return {"value": hit["metric_value"], "model_params": hit["model_params"]}

    async def set_cached_analytics(self, ticker, metric_name, metric_value, calculation_date, model_params=None):
        self.store[(ticker, metric_name)] = {"metric_value": metric_value, "model_params": model_params}


def _legacy_pair_row(a="NIFTYIETF.NS", b="NIFTYBEES.NS"):
    """Exactly the field set a pre-V3-14 build wrote to the DB cache."""
    return {
        "ticker_a": a,
        "ticker_b": b,
        "engle_granger_pvalue": 0.031,
        "engle_granger_tstat": -3.4,
        "is_cointegrated": True,
        "hedge_ratio_beta": 1.02,
        "intercept_alpha": 0.5,
        "ou_half_life_days": 12.0,
        "ou_reversion_speed_theta": 0.06,
        "current_spread_zscore": 0.8,
        "johansen_cointegrated": False,
        "last_price_a": 100.0,
        "last_price_b": 200.0,
        "overlap_observations": 107,
        "signal": "NEUTRAL",
    }


# ===========================================================================
# V3-13 - regime units, benchmark identity, posterior vs Viterbi
# ===========================================================================
class TestRegimeMetadata:
    async def test_detect_regime_declares_percent_units_and_sources(self):
        _, rets = _benchmark_walk(seed=3)
        with patch("app.services.regime_service.BenchmarkService") as cls:
            inst = cls.return_value
            inst.get_benchmark_df = AsyncMock(return_value=None)
            inst.get_returns = AsyncMock(return_value=rets)
            res = await detect_regime(MagicMock(), lookback_days=1100)

        assert res["probability_unit"] == "percent_0_to_100"
        assert res["transition_unit"] == "percent_0_to_100"
        assert res["posterior_type"] == "filtered_final_observation"
        assert res["current_regime_source"] == "viterbi_decoded_path"

    async def test_probabilities_and_transitions_really_are_percent_points(self):
        _, rets = _benchmark_walk(seed=5)
        with patch("app.services.regime_service.BenchmarkService") as cls:
            inst = cls.return_value
            inst.get_benchmark_df = AsyncMock(return_value=None)
            inst.get_returns = AsyncMock(return_value=rets)
            res = await detect_regime(MagicMock(), lookback_days=1100)

        probs = res["regime_probabilities"]
        assert set(probs) == REGIME_LABELS
        assert all(0.0 <= v <= 100.0 for v in probs.values())
        assert sum(probs.values()) == pytest.approx(100.0, abs=0.01)
        for row in res["transition_matrix"].values():
            assert all(0.0 <= v <= 100.0 for v in row.values())
            assert sum(row.values()) == pytest.approx(100.0, abs=0.3)

    async def test_benchmark_block_names_series_and_price_input_used(self):
        close, rets = _benchmark_walk(seed=7)
        # Price-frame path: measured OHLCV input.
        with patch("app.services.regime_service.BenchmarkService") as cls:
            inst = cls.return_value
            inst.get_benchmark_df = AsyncMock(return_value=close.to_frame("close"))
            inst.get_returns = AsyncMock(return_value=rets)
            measured = await detect_regime(MagicMock(), lookback_days=1100)
        # Return-series fallback path: derived input, and it says so.
        with patch("app.services.regime_service.BenchmarkService") as cls:
            inst = cls.return_value
            inst.get_benchmark_df = AsyncMock(return_value=None)
            inst.get_returns = AsyncMock(return_value=rets)
            derived = await detect_regime(MagicMock(), lookback_days=1100)

        for res in (measured, derived):
            assert res["benchmark"]["symbol"] == "^NSEI"
            assert res["benchmark"]["lookback_days_requested"] == 1100
            assert res["benchmark"]["data_status"] == "available"
        assert measured["benchmark"]["price_input"] == "daily_ohlcv_price_frame"
        assert measured["benchmark"]["price_input_provenance"] == "measured"
        assert measured["benchmark"]["price_input_reason"] is None
        assert derived["benchmark"]["price_input"] == "daily_returns_series"
        assert derived["benchmark"]["price_input_provenance"] == "derived"
        assert derived["benchmark"]["price_input_reason"]

    async def test_model_block_matches_the_fit_that_ran(self):
        close, rets = _benchmark_walk(seed=9)
        with patch("app.services.regime_service.BenchmarkService") as cls:
            inst = cls.return_value
            inst.get_benchmark_df = AsyncMock(return_value=close.to_frame("close"))
            inst.get_returns = AsyncMock(return_value=rets)
            res = await detect_regime(MagicMock(), lookback_days=1100)

        model = res["model"]
        assert model["type"] == "gaussian_hmm"
        assert model["states"] == REGIME_STATES == 3
        assert len(model["features"]) == 2
        assert model["scaler"].startswith("standard_scaler")
        assert model["n_iter"] == 200
        assert model["lookback_days"] == 1100
        assert model["minimum_observations"] == MIN_OBSERVATIONS
        assert model["observations"] == res["observations"] >= MIN_OBSERVATIONS
        assert model["training_window_status"] == "available"
        assert model["decoding"] == "viterbi"
        assert model["posterior"] == "filtering"

    async def test_posterior_and_viterbi_disagreement_is_visible(self):
        _, rets = _benchmark_walk(seed=11)
        with patch("app.services.regime_service.BenchmarkService") as cls:
            inst = cls.return_value
            inst.get_benchmark_df = AsyncMock(return_value=None)
            inst.get_returns = AsyncMock(return_value=rets)
            res = await detect_regime(MagicMock(), lookback_days=1100)

        argmax = max(res["regime_probabilities"], key=res["regime_probabilities"].get)
        assert res["posterior_argmax_regime"] == argmax
        assert isinstance(res["current_regime_matches_posterior_argmax"], bool)
        assert res["current_regime_matches_posterior_argmax"] is (
            argmax == res["current_regime"]
        )

    def test_metadata_pure_helper_never_invents_observations(self):
        payload = {
            "current_regime": "calm",
            "regime_probabilities": {"crisis": 5.0, "calm": 90.0, "bull": 5.0},
        }
        meta = _regime_metadata(payload, use_returns=False, lookback_days=500)
        # Absent count stays absent: 0 would be a fabricated measurement.
        assert meta["model"]["observations"] is None
        assert meta["model"]["training_window_status"] == "unavailable"
        assert meta["posterior_argmax_regime"] == "calm"
        assert meta["current_regime_matches_posterior_argmax"] is True
        # Unusable posterior payload must not raise or invent an argmax.
        broken = _regime_metadata(
            {"current_regime": "calm", "regime_probabilities": None},
            use_returns=True,
            lookback_days=500,
        )
        assert broken["posterior_argmax_regime"] is None
        assert broken["current_regime_matches_posterior_argmax"] is False

    def test_metadata_leaves_classify_shape_untouched(self):
        # `classify` is unit-tested for shape only and never sees the lookback,
        # so the metadata must NOT be baked into its payload.
        close, _ = _benchmark_walk(seed=13)
        raw = classify(close)
        assert raw is not None
        for key in (
            "probability_unit",
            "transition_unit",
            "posterior_type",
            "current_regime_source",
            "benchmark",
            "model",
            "units",
        ):
            assert key not in raw
        for key in (
            "as_of",
            "current_regime",
            "stability_pct",
            "label_overrides",
            "regime_probabilities",
            "transition_matrix",
            "realtime_ewma_vol",
            "realtime_parkinson_vol",
            "states",
            "recent_history",
            "observations",
        ):
            assert key in raw

    async def test_detect_regime_keeps_every_existing_key_and_value(self):
        _, rets = _benchmark_walk(seed=15)
        with patch("app.services.regime_service.BenchmarkService") as cls:
            inst = cls.return_value
            inst.get_benchmark_df = AsyncMock(return_value=None)
            inst.get_returns = AsyncMock(return_value=rets)
            res = await detect_regime(MagicMock(), lookback_days=1100)
        raw = classify(rets, is_returns=True)
        # `all_regimes` is deliberately consumed by the portfolio leg.
        raw.pop("all_regimes", None)
        for key, value in raw.items():
            assert key in res
            assert res[key] == value
        assert "generated_at" in res

    def test_units_block_covers_every_percentage_and_annualized_fraction(self):
        close, rets = _benchmark_walk(seed=17)
        payload = classify(close)
        payload.pop("all_regimes", None)
        meta = _regime_metadata(payload, use_returns=False, lookback_days=1100)
        payload.update({k: v for k, v in meta.items() if k != "units"})
        units = meta["units"]

        declared = set()
        for key, value in payload.items():
            if key.endswith("_pct") or key.endswith("_vol") or key in {"ann_ret", "ann_vol"}:
                declared.add(key)
            if key == "states" and isinstance(value, list):
                for row in value:
                    for row_key in row:
                        if row_key.endswith("_pct") or row_key.endswith("_vol") or row_key in {"ann_ret", "ann_vol"}:
                            declared.add(f"states[].{row_key}")

        assert declared, "payload must actually contain percentages/annualized fractions"
        assert declared <= set(units)
        assert units["regime_probabilities"] == "percent_0_to_100"
        assert units["transition_matrix"] == "percent_0_to_100"
        assert units["stability_pct"] == "percent_0_to_100"
        assert units["states[].ann_ret"] == "annualized_fraction_geometric_cagr"
        assert units["states[].ann_vol"] == "annualized_fraction"
        assert units["realtime_ewma_vol"] == "annualized_fraction"
        assert units["realtime_parkinson_vol"] == "annualized_fraction"
        assert units["portfolio_in_current_regime.total_ret"] == "holding_period_fraction"
        assert units["observations"] == "count_trading_days"


# ===========================================================================
# V3-11 - Monte Carlo success semantics
# ===========================================================================
class TestMonteCarloSuccessSemantics:
    def test_labels_terminal_success_and_spells_out_touch_distinction(self):
        out = simulate_goal(
            _returns_series(), initial_value=1_000_000, target_value=1_500_000,
            horizon_years=5, method="gbm", num_paths=400, seed=42,
        )
        assert out["success_definition"] == "terminal_wealth_above_target"
        detail = out["success_definition_detail"]
        assert "TERMINAL" in detail
        assert "any point" in detail
        assert "target_value" in detail
        assert str(out["horizon_years"]) in detail
        assert out["prob_success_units"] == "fraction_of_paths_0_to_1"
        assert out["annualized"] is True
        assert out["annualization_basis"] == "trading_days_per_year_252"
        assert out["annualized_fields"] == ["historical_mu_annual", "historical_sigma_annual"]

    def test_prob_success_is_terminal_not_path_touch(self):
        # Reproduce the exact path matrix: simulate_goal seeds a fresh
        # Generator, runs one chunk (<= chunk cap) and calls _simulate_gbm
        # with it, so a single-chunk GBM run is bit-identical here.
        returns = _returns_series(seed=23, n=400)
        v0, target, horizon, num_paths, seed = 100_000.0, 130_000.0, 2.0, 400, 11
        out = simulate_goal(
            returns, initial_value=v0, target_value=target, horizon_years=horizon,
            method="gbm", num_paths=num_paths, seed=seed,
        )
        assert out["num_paths"] == num_paths  # no clamping happened

        mu, sigma, _ = _calibrate(returns)
        paths = _simulate_gbm(
            mu, sigma, v0, horizon, num_paths, np.random.default_rng(seed)
        )
        terminal = float(np.mean(paths[:, -1] >= target))
        touch = float(np.mean((paths >= target).any(axis=1)))

        assert out["prob_success"] == pytest.approx(terminal, abs=1e-4)
        # The two statistics must genuinely differ, otherwise the label would
        # be decoration rather than a correction.
        assert touch > terminal
        assert out["success_definition"] == "terminal_wealth_above_target"

    def test_model_observations_count_usable_history(self):
        returns = _returns_series(seed=31, n=300)
        out = simulate_goal(
            returns, initial_value=100_000, target_value=150_000,
            horizon_years=3, method="gbm", num_paths=200, seed=1,
        )
        assert out["model_observations"] == 300
        assert out["model_minimum_observations"] == 60
        assert out["model_window_start"] == returns.index[0].strftime("%Y-%m-%d")
        assert out["model_as_of"] == returns.index[-1].strftime("%Y-%m-%d")
        assert out["model_as_of"] > out["model_window_start"]

    def test_model_window_absent_for_non_date_index(self):
        # A RangeIndex would otherwise be read as nanoseconds since the epoch
        # and publish a fabricated 1970 window.
        returns = pd.Series(np.random.default_rng(3).normal(0.0004, 0.01, 300))
        out = simulate_goal(
            returns, initial_value=100_000, target_value=150_000,
            horizon_years=3, method="gbm", num_paths=200, seed=1,
        )
        assert out["model_as_of"] is None
        assert out["model_window_start"] is None
        assert out["model_observations"] == 300
        assert _model_window(returns) == (None, None)

    def test_model_window_skips_trailing_nan_observations(self):
        returns = _returns_series(seed=37, n=300)
        usable = returns.copy()
        usable.iloc[-3:] = np.nan
        out = simulate_goal(
            usable, initial_value=100_000, target_value=150_000,
            horizon_years=3, method="gbm", num_paths=200, seed=1,
        )
        assert out["model_observations"] == 297
        assert out["model_as_of"] == usable.dropna().index[-1].strftime("%Y-%m-%d")

    def test_existing_monte_carlo_keys_unchanged(self):
        out = simulate_goal(
            _returns_series(seed=41), initial_value=100_000, target_value=150_000,
            horizon_years=4, method="gbm", num_paths=300, seed=2,
        )
        for key in (
            "method", "initial_value", "target_value", "horizon_years", "num_paths",
            "prob_success", "terminal_percentiles", "fan", "expected_shortfall_vs_target",
            "historical_mu_annual", "historical_sigma_annual", "disclaimer",
        ):
            assert key in out
        assert 0.0 <= out["prob_success"] <= 1.0


# ===========================================================================
# V3-14 - pairs depth + dual-test roles
# ===========================================================================
class TestPairsDepthHelpers:
    def test_minimum_gate_is_the_one_the_engine_enforces(self):
        idx = pd.bdate_range("2026-01-01", periods=MIN_PAIR_OBSERVATIONS + 5)
        too_short = analyze_pair_cointegration(
            "A.NS", "B.NS",
            pd.Series(100.0 + np.arange(MIN_PAIR_OBSERVATIONS - 1), index=idx[: MIN_PAIR_OBSERVATIONS - 1]),
            pd.Series(200.0 + np.arange(MIN_PAIR_OBSERVATIONS - 1), index=idx[: MIN_PAIR_OBSERVATIONS - 1]),
        )
        assert too_short is None

    def test_depth_ratio_never_invents_a_denominator(self):
        assert pair_depth_ratio(106, 174) == pytest.approx(0.6092, abs=1e-4)
        assert pair_depth_ratio(174, 174) == 1.0
        assert pair_depth_ratio(None, 174) is None
        assert pair_depth_ratio(106, None) is None
        assert pair_depth_ratio(106, 0) is None
        assert pair_depth_ratio(106, -5) is None

    def test_assess_pair_depth_uses_shared_status_vocabulary(self):
        short = assess_pair_depth(106, 174)
        assert short["status"] == "partial"
        assert short["depth_limited"] is True
        assert short["depth_ratio"] < MIN_PAIR_DEPTH_RATIO
        deep = assess_pair_depth(174, 174)
        assert deep["status"] == "available"
        assert deep["depth_limited"] is False
        unknown = assess_pair_depth(None, 174)
        assert unknown["status"] == "unavailable"
        assert unknown["depth_ratio"] is None
        assert unknown["depth_limited"] is None
        # No reference at all: unmeasured, not "everything is fine".
        assert assess_pair_depth(174, None)["status"] == "unavailable"

    def test_summarize_pair_depth_rolls_up_conservatively(self):
        assert summarize_pair_depth([]) == ("available", 0)
        assert summarize_pair_depth([assess_pair_depth(174, 174)]) == ("available", 0)
        assert summarize_pair_depth(
            [assess_pair_depth(174, 174), assess_pair_depth(106, 174)]
        ) == ("partial", 1)
        assert summarize_pair_depth(
            [assess_pair_depth(106, 174), assess_pair_depth(None, 174)]
        ) == ("unavailable", 1)

    def test_usable_observations_by_ticker_is_measured(self):
        idx = pd.bdate_range("2026-01-01", periods=10)
        series = pd.Series(100.0 + np.arange(10), index=idx)
        short = series.iloc[-4:]
        assert usable_observations_by_ticker({"A.NS": series, "NIFTYIETF.NS": short}) == {
            "A.NS": 10,
            "NIFTYIETF.NS": 4,
        }
        assert usable_observations_by_ticker({}) == {}
        assert usable_observations_by_ticker({"A.NS": None}) == {"A.NS": 0}
        assert shallow_tickers({"A.NS": 174, "NIFTYIETF.NS": 107}) == ["NIFTYIETF.NS"]
        assert shallow_tickers({"A.NS": 174, "B.NS": 168}) == []


class TestPairsCacheCompatibility:
    def test_legacy_cache_row_still_loads(self):
        pair = CointPairResult(**_legacy_pair_row())
        assert pair.decision_test is None
        assert pair.johansen_role is None
        assert pair.johansen_agrees_with_decision is None
        assert pair.depth_ratio is None
        assert pair.depth_status is None

    async def test_db_cache_read_backfills_roles_from_legacy_row(self):
        """A row legacy only in its DECLARATIONS is still served and upgraded.

        Legacy is three different things. The role/depth fields are
        declarations, so they can be backfilled from the engine's own
        constants. The hedge regression's standard errors and the per-leg
        stationarity verdicts are MEASUREMENTS and cannot be, so a row missing
        those is a miss and gets recomputed. This test covers the first kind,
        which is the behaviour it was written for.
        """
        row = _legacy_pair_row()
        row.update(
            {
                "hedge_ratio_beta_std_error": 0.05,
                "intercept_alpha_std_error": 1.4,
                "hedge_regression_observations": 107,
                "hedge_regression_std_error_basis": (
                    "ols_standard_error_from_polyfit_covariance_df_n_minus_2"
                ),
                # The gate is a measurement, so a row that answers it is a hit
                # even though every declaration is still absent.
                "stationarity_leg_a": {
                    "ticker": "NIFTYIETF.NS", "observations": 107,
                    "transform": "log_price", "alpha": 0.05,
                    "lag_rule": "adf:max_lags=1,lag_selection=aic",
                    "adf_pvalue": 0.55, "adf_lags": 0, "kpss_pvalue": 0.0001,
                    "kpss_bandwidth": 4, "verdict": "i1", "reason": "fixture",
                },
                "stationarity_leg_b": {
                    "ticker": "NIFTYBEES.NS", "observations": 107,
                    "transform": "log_price", "alpha": 0.05,
                    "lag_rule": "adf:max_lags=1,lag_selection=aic",
                    "adf_pvalue": 0.48, "adf_lags": 0, "kpss_pvalue": 0.0002,
                    "kpss_bandwidth": 4, "verdict": "i1", "reason": "fixture",
                },
                "stationarity_gate": {
                    "verdict": "both_legs_i1", "leg_a_verdict": "i1",
                    "leg_b_verdict": "i1", "reason": "fixture",
                },
            }
        )
        db_ticker, metric = _db_cache_keys("NIFTYIETF.NS", "NIFTYBEES.NS", "2026-09-24")
        cache = _FakeCache({(db_ticker, metric): {"metric_value": 0.031, "model_params": row}})
        svc = CointegrationService(db_session=None, cache_service=cache)
        _IN_MEMORY_COINT_CACHE.clear()
        try:
            got = await svc._get_cached_pair("NIFTYIETF.NS", "NIFTYBEES.NS", "2026-09-24")
        finally:
            _IN_MEMORY_COINT_CACHE.clear()
        assert got is not None
        assert got.engle_granger_pvalue == pytest.approx(0.031)
        assert got.decision_test == DECISION_TEST == "engle_granger"
        assert got.johansen_role == JOHANSEN_ROLE == "diagnostic_only"
        # Derived from two booleans the legacy row already carried.
        assert got.johansen_agrees_with_decision is (got.johansen_cointegrated == got.is_cointegrated)

    async def test_db_cache_misses_a_row_that_predates_the_uncertainty_measurement(self):
        """The other kind of legacy: a row written before the standard errors
        existed. It is a MISS, not a hit, because the slope drives a trade
        instruction and a standard error cannot be invented from a constant.
        Serving it would make the omission indistinguishable from a deliberate
        `not_computed` in the artifact."""
        row = _legacy_pair_row()
        db_ticker, metric = _db_cache_keys("NIFTYIETF.NS", "NIFTYBEES.NS", "2026-09-24")
        cache = _FakeCache({(db_ticker, metric): {"metric_value": 0.031, "model_params": row}})
        svc = CointegrationService(db_session=None, cache_service=cache)
        _IN_MEMORY_COINT_CACHE.clear()
        try:
            got = await svc._get_cached_pair("NIFTYIETF.NS", "NIFTYBEES.NS", "2026-09-24")
        finally:
            _IN_MEMORY_COINT_CACHE.clear()
        assert got is None

    def test_with_test_role_metadata_is_idempotent(self):
        pair = with_test_role_metadata(CointPairResult(**_legacy_pair_row()))
        again = with_test_role_metadata(pair)
        assert pair.decision_test == again.decision_test
        assert pair.johansen_agrees_with_decision == again.johansen_agrees_with_decision
        assert pair.depth_ratio is None  # never invented by the role upgrade


def _uneven_universe(deep=174, young=107, seed=41):
    """Two deep peers plus a young ETF - the NIFTYIETF shape from the audit."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2026-01-01", periods=deep)
    base = pd.Series(100.0 + np.cumsum(rng.normal(0.05, 1.0, deep)), index=index)
    peer = 1.5 * base + 10.0 + pd.Series(rng.normal(0.0, 0.4, deep), index=index)
    etf_index = index[deep - young:]
    etf = pd.Series(
        50.0 + np.cumsum(rng.normal(0.02, 0.3, young)), index=etf_index
    )
    return {
        "INFY.NS": base,
        "TCS.NS": peer,
        "NIFTYIETF.NS": etf,
    }


class TestPairsScanDepthDisclosure:
    async def test_uneven_overlap_makes_the_scan_partial_not_complete(self):
        _IN_MEMORY_COINT_CACHE.clear()
        svc = CointegrationService(db_session=None, cache_service=None)
        res = await svc.scan_pairs(_uneven_universe(), p_value_threshold=0.05, max_half_life=None)
        _IN_MEMORY_COINT_CACHE.clear()

        assert res.minimum_pair_observations == MIN_PAIR_OBSERVATIONS
        assert res.minimum_depth_ratio == MIN_PAIR_DEPTH_RATIO
        assert res.reference_pair_observations == 174
        assert res.depth_status == "partial"
        assert res.depth_limited_pair_count == 2
        assert res.data_status == "partial"
        assert res.shallow_tickers == ["NIFTYIETF.NS"]
        counts = res.usable_observations_by_ticker
        assert counts["INFY.NS"] == 174 and counts["NIFTYIETF.NS"] == 107

        by_pair = {(p.ticker_a, p.ticker_b): p for p in res.pairs}
        deep = by_pair[("INFY.NS", "TCS.NS")]
        assert deep.overlap_observations == 174
        assert deep.depth_ratio == 1.0
        assert deep.depth_status == "available"
        for young in (("INFY.NS", "NIFTYIETF.NS"), ("NIFTYIETF.NS", "TCS.NS")):
            pair = by_pair[young]
            assert pair.overlap_observations == 107
            assert pair.depth_ratio == pytest.approx(107 / 174, abs=1e-4)
            assert pair.depth_status == "partial"
            # The effective pair window is disclosed, not just the count.
            assert pair.overlap_start is not None and pair.overlap_end is not None

    async def test_even_depth_stays_available(self):
        _IN_MEMORY_COINT_CACHE.clear()
        svc = CointegrationService(db_session=None, cache_service=None)
        res = await svc.scan_pairs(_uneven_universe(deep=200, young=200), max_half_life=None)
        _IN_MEMORY_COINT_CACHE.clear()
        assert res.depth_status == "available"
        assert res.depth_limited_pair_count == 0
        assert res.data_status == "available"
        assert res.shallow_tickers == []

    async def test_count_invariants_survive_depth_bookkeeping(self):
        _IN_MEMORY_COINT_CACHE.clear()
        svc = CointegrationService(db_session=None, cache_service=None)
        res = await svc.scan_pairs(_uneven_universe(), max_half_life=None)
        _IN_MEMORY_COINT_CACHE.clear()
        assert res.returned_pairs_count == len(res.pairs)
        assert (
            res.returned_cointegrated_pairs_count + res.returned_non_cointegrated_pairs_count
            == len(res.pairs)
        )
        assert res.cointegrated_pairs_count == sum(1 for p in res.pairs if p.is_cointegrated)

    async def test_dual_test_roles_are_labelled_on_every_pair(self):
        _IN_MEMORY_COINT_CACHE.clear()
        svc = CointegrationService(db_session=None, cache_service=None)
        res = await svc.scan_pairs(_uneven_universe(), max_half_life=None)
        _IN_MEMORY_COINT_CACHE.clear()
        assert res.test_roles == {
            "engle_granger": "published_decision",
            "johansen": "diagnostic_only",
        }
        assert res.pairs
        for pair in res.pairs:
            assert pair.decision_test == "engle_granger"
            assert pair.johansen_role == "diagnostic_only"
            assert pair.johansen_agrees_with_decision == (
                pair.johansen_cointegrated == pair.is_cointegrated
            )

    async def test_universe_scope_stays_route_owned(self):
        _IN_MEMORY_COINT_CACHE.clear()
        svc = CointegrationService(db_session=None, cache_service=None)
        res = await svc.scan_pairs(_uneven_universe(), max_half_life=None)
        _IN_MEMORY_COINT_CACHE.clear()
        # The service cannot know whether the universe was holdings-only or
        # holdings + watchlist; that stays undeclared rather than guessed.
        assert res.universe_scope is None

    async def test_single_ticker_universe_still_publishes_the_gate(self):
        _IN_MEMORY_COINT_CACHE.clear()
        svc = CointegrationService(db_session=None, cache_service=None)
        res = await svc.scan_pairs({"INFY.NS": _uneven_universe()["INFY.NS"]})
        _IN_MEMORY_COINT_CACHE.clear()
        assert res.data_status == "unavailable"
        assert res.depth_status == "unavailable"
        assert res.test_roles["johansen"] == "diagnostic_only"
        assert res.minimum_pair_observations == MIN_PAIR_OBSERVATIONS
        assert res.minimum_depth_ratio == MIN_PAIR_DEPTH_RATIO
        assert res.usable_observations_by_ticker == {"INFY.NS": 174}
        assert res.pairs == []

    async def test_cached_pairs_get_the_same_depth_treatment(self):
        _IN_MEMORY_COINT_CACHE.clear()
        svc = CointegrationService(db_session=None, cache_service=None)
        data = _uneven_universe()
        first = await svc.scan_pairs(data, max_half_life=None)
        second = await svc.scan_pairs(data, max_half_life=None)  # all cache hits
        _IN_MEMORY_COINT_CACHE.clear()
        assert second.depth_status == first.depth_status == "partial"
        assert [p.depth_ratio for p in second.pairs] == [p.depth_ratio for p in first.pairs]
        assert [p.depth_status for p in second.pairs] == [p.depth_status for p in first.pairs]
        for pair in second.pairs:
            assert pair.decision_test == "engle_granger"
