"""P1 quant-math batch regression tests (remediation-2026-09 issue 11, audit F2-F8).

Each test pins the corrected behavior with an independent hand-check:
Sortino downside-deviation, single-pass EWMA + flat term structure, free-alpha
CVaR, OU oscillatory (None, None), MC float horizons + int bootstrap seed,
one-way backtest turnover + multiplicative cost + mean-based Sharpe, max_sharpe
guard + beta forwarding, vol-cone nulls + flag, active-history factor OLS,
benchmark-threaded/excluded risk factor leg + stateless scoring, and
scale-to-target volatility sizing with cash remainder.
"""

import numpy as np
import pandas as pd
import pytest

from app.services.analytics_engine import AnalyticsEngine
from app.services.cointegration_service import compute_ou_parameters
from app.services.monte_carlo_service import simulate_goal
from app.services.volatility_service import VolatilityService


def _synth_prices(days=252, n_assets=3, seed=42):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=days)
    data = {}
    for i in range(n_assets):
        price = 100.0 * np.exp(np.cumsum(rng.normal(0.0008, 0.012, days)))
        data[f"STK_{i}"] = price
    return pd.DataFrame(data, index=dates)


class TestSortinoDownsideDeviation:
    def test_sortino_uses_full_series_downside_deviation(self):
        engine = AnalyticsEngine()
        r = pd.Series([0.01, -0.02, 0.03, -0.01, 0.005, -0.005,
                       0.02, -0.03, 0.015, 0.008, -0.012, 0.004])
        got = engine._calculate_basic_metrics(r)["sortino_ratio"]
        target = engine.risk_free_rate / 252
        down = np.minimum(0.0, r.to_numpy(dtype=float) - target)
        expected_dd = float(np.sqrt(np.mean(down ** 2)) * np.sqrt(252))
        expected = float((r.mean() * 252 - engine.risk_free_rate) / expected_dd)
        assert got == pytest.approx(expected, rel=1e-9)
        # Hand-check discriminates against the old std-of-negatives formula
        old_dd = float(r[r < 0].std() * np.sqrt(252))
        assert abs(expected_dd - old_dd) > 1e-6


class TestEwmaSinglePass:
    def test_ewma_matches_riskmetrics_recursion_and_flat_term(self):
        engine = AnalyticsEngine()
        r = pd.Series(np.random.default_rng(0).normal(0.0005, 0.012, 200))
        out = engine._ewma_forecast(r, 5)
        rc = np.clip(r.to_numpy(dtype=float), -0.20, 0.20)
        var = float(np.var(rc))
        for x in rc[-60:]:
            var = 0.94 * var + 0.06 * x * x
        expected = float(np.clip(np.sqrt(var * 252), 0.05, 1.20))
        assert out["volatility_forecast"] == pytest.approx(expected, rel=1e-9)
        assert len(out["term_structure"]) == 5
        for v in out["term_structure"]:
            assert v == pytest.approx(expected, rel=1e-12)


class TestCvarFreeAlpha:
    def test_min_cvar_converges_with_positive_loss_var(self):
        from app.services.optimization_service import _min_cvar
        # Strong positive drift: VaR of loss is > 0, which neg=True cut off
        rng = np.random.default_rng(3)
        rets = pd.DataFrame(rng.normal(0.002, 0.008, (300, 3)), columns=list("ABC"))
        w = _min_cvar(rets, beta=0.95)
        assert abs(w.sum() - 1.0) < 1e-6
        assert (w >= -1e-7).all()

    def test_alpha_is_free_variable_in_source(self):
        import inspect
        import app.services.optimization_service as opt
        src = inspect.getsource(opt._min_cvar)
        assert "cp.Variable()" in src
        assert "cp.Variable(neg=True)" not in src


class TestOuOscillatory:
    def test_oscillatory_branch_returns_none_none(self):
        # AR(1) coef -0.5 -> gamma ~= -1.5 in (-2, -1]: sign-flipping overshoot
        rng = np.random.default_rng(11)
        z = np.zeros(500)
        for t in range(1, 500):
            z[t] = -0.5 * z[t - 1] + rng.normal(0, 1)
        gamma, _ = np.polyfit(z[:-1], z[1:] - z[:-1], 1)
        assert -2.0 < gamma <= -1.0
        assert compute_ou_parameters(z) == (None, None)


class TestMcFloatHorizon:
    def _rets(self):
        return pd.Series(np.random.default_rng(5).normal(0.0004, 0.01, 300),
                         index=pd.bdate_range("2024-01-01", periods=300))

    def test_float_horizon_gives_int_steps(self):
        r = self._rets()
        for method in ("gbm", "student_t", "bootstrap"):
            out = simulate_goal(r, 100_000, 150_000, 2.5,
                                method=method, num_paths=100, seed=1)
            # 2.5y * 252 = 630 steps; fan covers the fractional horizon
            assert out["fan"][-1]["year"] == 2.5
            assert 0.0 <= out["prob_success"] <= 1.0

    def test_bootstrap_deterministic_with_int_seed(self):
        r = self._rets()
        kw = dict(initial_value=100_000, target_value=150_000, horizon_years=2,
                  method="bootstrap", num_paths=100, seed=7)
        a = simulate_goal(r, **kw)
        b = simulate_goal(r, **kw)
        assert a["prob_success"] == b["prob_success"]
        assert a["terminal_percentiles"] == b["terminal_percentiles"]


class TestBacktestOneWayTurnover:
    def test_turnover_cost_and_sharpe(self, monkeypatch):
        import app.services.backtest_service as bt
        dates = pd.bdate_range("2024-01-01", periods=200)
        rng = np.random.default_rng(9)
        rets = pd.DataFrame(rng.normal(0.0005, 0.01, (200, 2)),
                            index=dates, columns=["A", "B"])
        monkeypatch.setattr(
            bt, "optimize",
            lambda train_window, strategy="hrp", risk_free_rate=0.02:
                {"weights": {"A": 0.8, "B": 0.2}},
        )
        res = bt.run_walk_forward_backtest(
            rets, strategy="hrp", rebalance_freq_days=50, lookback_days=60,
            transaction_cost_bps=100.0, risk_free_rate=0.02)
        # 50/50 -> 80/20: sum|dW| = 0.6, one-way = 0.3 (old code reported 0.6)
        assert res["rebalance_events"][0]["turnover"] == pytest.approx(0.3)
        assert res["total_turnover"] == pytest.approx(
            sum(e["turnover"] for e in res["rebalance_events"]))
        # OOS rows 60..198 at fixed 80/20; only the first day pays friction,
        # multiplicatively: (1-c)(1+r)-1 with c = 0.3 * 0.01
        base = rets.iloc[60:199].to_numpy() @ np.array([0.8, 0.2])
        exp_daily = base.copy()
        exp_daily[0] = (1.0 - 0.003) * (1.0 + base[0]) - 1.0
        exp_sharpe = (exp_daily.mean() * 252 - 0.02) / (exp_daily.std(ddof=1) * np.sqrt(252))
        assert res["sharpe_ratio"] == pytest.approx(round(float(exp_sharpe), 4), abs=1e-4)


class TestMaxSharpeGuardAndBeta:
    def test_all_negative_excess_still_raises(self):
        from app.services.optimization_service import _max_sharpe
        with pytest.raises(ValueError):
            _max_sharpe(np.array([-0.01, -0.02]), np.eye(2) * 0.04, 0.02)

    def test_raw_sum_guard_fires_on_degenerate_solver_output(self, monkeypatch):
        import app.services.optimization_service as opt
        created = []
        real_var, real_problem = opt.cp.Variable, opt.cp.Problem

        def spy_var(*a, **k):
            v = real_var(*a, **k)
            created.append(v)
            return v

        def fake_problem(obj, constraints):
            p = real_problem(obj, constraints)
            orig_solve = p.solve

            def solve(*a, **k):
                out = orig_solve(*a, **k)
                for v in created:
                    if v.value is not None:
                        v.value = np.zeros_like(np.asarray(v.value, dtype=float))
                return out

            p.solve = solve
            return p

        monkeypatch.setattr(opt.cp, "Variable", spy_var)
        monkeypatch.setattr(opt.cp, "Problem", fake_problem)
        with pytest.raises(ValueError, match="non-positive"):
            opt._max_sharpe(np.array([0.10, 0.08]), np.eye(2) * 0.04, 0.02)

    def test_optimize_forwards_beta(self):
        import app.services.optimization_service as opt
        rng = np.random.default_rng(13)
        rets = pd.DataFrame(rng.normal(0.0005, 0.012, (250, 3)),
                            columns=list("ABC"))
        out = opt.optimize(rets, "min_cvar", beta=0.90)
        assert abs(sum(out["weights"].values()) - 1.0) < 1e-4


class TestVolConeNulls:
    def test_window_beyond_history_is_null_with_flag(self):
        s = pd.Series(np.random.default_rng(2).normal(0, 0.015, 15))
        cone = VolatilityService.calculate_volatility_cone(s, windows=[10, 21])
        w10 = next(w for w in cone["windows"] if w["window_days"] == 10)
        w21 = next(w for w in cone["windows"] if w["window_days"] == 21)
        assert w10["insufficient_data"] is False
        assert w10["median"] is not None
        # 15 obs < 21-day window: single rolling value -> quantile bounds
        # would be fabricated multiples, so nulls + flag (observed kept)
        assert w21["insufficient_data"] is True
        for k in ("min", "p25", "median", "p75", "max", "percentile_rank"):
            assert w21[k] is None
        assert w21["current_realized"] is not None

    def test_tiny_history_is_all_null_with_flag(self):
        s = pd.Series([0.01, -0.02, 0.005])
        cone = VolatilityService.calculate_volatility_cone(s, windows=[10, 21])
        for w in cone["windows"]:
            assert w["insufficient_data"] is True
            for k in ("min", "p25", "median", "p75", "max",
                      "current_realized", "percentile_rank"):
                assert w[k] is None

    def test_single_observation_keeps_only_observed_value(self):
        s = pd.Series(np.random.default_rng(4).normal(0, 0.01, 10))
        cone = VolatilityService.calculate_volatility_cone(s, windows=[10])
        w = cone["windows"][0]
        assert w["insufficient_data"] is True
        assert w["current_realized"] is not None
        for k in ("min", "p25", "median", "p75", "max"):
            assert w[k] is None


class TestFactorActiveHistory:
    @pytest.mark.asyncio
    async def test_zero_filled_prelisting_rows_excluded(self):
        engine = AnalyticsEngine()
        dates = pd.bdate_range("2024-01-01", periods=120)
        rng = np.random.default_rng(6)
        bench_rets = rng.normal(0.0005, 0.01, 120)
        bench_prices = pd.Series(100 * np.cumprod(1 + bench_rets), index=dates)
        idio = rng.normal(0, 0.005, 120)
        a_rets = np.concatenate([np.zeros(60), 1.5 * bench_rets[60:] + idio[60:]])
        a_prices = np.concatenate([np.full(60, 50.0), 50 * np.cumprod(1 + a_rets[60:])])
        prices = pd.DataFrame({"A": a_prices}, index=dates)
        res = await engine.factor_exposure_analysis(prices, benchmark_data=bench_prices)
        pos = res["positions"]["A"]
        # 60 active days (first listing-day jump + 59); zeros excluded
        assert pos["data_points"] == 60
        # Active-only beta ~= 1.5; zero-diluted full-sample beta would be ~0.75
        assert abs(pos["market"] - 1.5) < 0.35


class TestRiskScoringFactorLeg:
    def _frame(self):
        return _synth_prices(days=120, n_assets=3, seed=21)

    @pytest.mark.asyncio
    async def test_no_benchmark_excludes_and_renormalizes(self):
        engine = AnalyticsEngine()
        df = self._frame()
        weights = {"STK_0": 0.4, "STK_1": 0.3, "STK_2": 0.3}
        res = await engine.risk_scoring(df, weights)
        assert res["components"]["factor_risk"] is None
        assert res["excluded_components"] == ["factor_risk"]
        c = res["components"]
        expected = (c["concentration"] * 0.20 + c["volatility"] * 0.25
                    + c["correlation"] * 0.20 + c["market_risk"] * 0.10) / 0.75
        assert res["overall_score"] == pytest.approx(round(expected, 1), abs=0.15)

    @pytest.mark.asyncio
    async def test_benchmark_threaded_into_factor_leg(self):
        engine = AnalyticsEngine()
        df = self._frame()
        weights = {"STK_0": 0.4, "STK_1": 0.3, "STK_2": 0.3}
        port_rets = pd.DataFrame(
            (df.pct_change(fill_method=None).fillna(0.0) * pd.Series(weights)).sum(axis=1))
        bench = pd.Series(
            port_rets.iloc[:, 0].to_numpy() + np.random.default_rng(3).normal(0, 0.002, len(df)),
            index=df.index)
        res = await engine.risk_scoring(df, weights, benchmark_data=bench)
        assert res["excluded_components"] == []
        assert res["components"]["factor_risk"] is not None
        assert res["factor_r_squared"] is not None and res["factor_r_squared"] > 0

    @pytest.mark.asyncio
    async def test_scoring_is_stateless(self):
        engine = AnalyticsEngine()
        df = self._frame()
        weights = {"STK_0": 0.5, "STK_1": 0.5, "STK_2": 0.0}
        r1 = await engine.risk_scoring(df, weights)
        r2 = await engine.risk_scoring(df, weights)
        assert r1["overall_score"] == r2["overall_score"]
        assert r1["change"] == 0 and r2["change"] == 0
        assert not hasattr(engine, "_previous_risk_score")


class TestTargetVolatilityScaling:
    @pytest.mark.asyncio
    async def test_scale_to_target_with_cash_remainder(self):
        engine = AnalyticsEngine()
        df = _synth_prices(days=252, n_assets=3, seed=33)
        weights = {"STK_0": 1 / 3, "STK_1": 1 / 3, "STK_2": 1 / 3}
        res = await engine.volatility_sizing(
            df, weights, model="EWMA", target_volatility=0.10)
        rec, vols = res["recommended_weights"], res["volatilities"]
        scale = res["scale_factor"]
        # Inverse-volatility ratios preserved through scaling
        assert (rec["STK_0"] / rec["STK_1"]) == pytest.approx(
            (1 / vols["STK_0"]) / (1 / vols["STK_1"]), rel=1e-4)
        assert sum(rec.values()) == pytest.approx(scale, abs=1e-4)
        assert res["cash_weight"] == pytest.approx(max(0.0, 1.0 - scale))
        assert scale < 1.0 and res["leveraged"] is False
        assert res["achieved_volatility"] == pytest.approx(0.10, rel=1e-6)
        assert "cash" in res["methodology"] and "scale" in res["methodology"]
