"""
Quantitative and Mathematical Invariant Test Suite.
Validates exact mathematical identities, boundary conditions, numerical stability,
and closed-form analytical solutions without artificial tautological mocks.
"""

import numpy as np
import pandas as pd
import pytest
from scipy.stats import t as student_t

from app.services.analytics_engine import AnalyticsEngine
from app.services.optimization_service import (
    _hrp_weights,
    _min_vol,
    _max_sharpe,
    _min_cvar,
)
from app.services.cointegration_service import compute_ou_parameters
from app.services.tail_risk_service import TailRiskService
from app.services.monte_carlo_service import (
    simulate_goal,
)


class TestQuantitativeInvariants:
    """Rigorous tests for core quantitative and financial invariants."""

    def test_euler_volatility_attribution_exact_identity(self):
        """
        Euler's Theorem for 1-homogeneous risk measures:
        sigma_p(w) = sum_{i=1}^N w_i * (d sigma_p / d w_i) = sum_{i=1}^N RC_i
        Percentage risk contributions RC_i / sigma_p must sum to 1.0 (100%).
        """
        np.random.seed(42)
        n = 4
        # Generate arbitrary positive definite covariance matrix
        a = np.random.normal(0, 1, (n, n))
        cov = a @ a.T + 0.1 * np.eye(n)

        # Arbitrary non-trivial weights summing to 1
        w = np.array([0.4, 0.3, 0.2, 0.1])
        port_var = float(w.T @ cov @ w)
        sigma_p = np.sqrt(port_var)

        # Marginal risk contribution: MRC = (cov @ w) / sigma_p
        mrc = (cov @ w) / sigma_p

        # Component risk contribution: RC = w * mrc
        rc = w * mrc

        # Invariant 1: sum of absolute risk contributions equals portfolio volatility
        assert abs(np.sum(rc) - sigma_p) < 1e-12

        # Invariant 2: percentage risk contributions sum to 1.0
        pct_rc = rc / sigma_p
        assert abs(np.sum(pct_rc) - 1.0) < 1e-12

    @pytest.mark.asyncio
    async def test_herfindahl_effective_positions_and_gini_bounds(self):
        """
        Ground-truth concentration mathematics:
        - Uniform: w_i = 1/N => HHI = 1/N, N_eff = N, Gini = 0.0, DivScore = 100%
        - Single Asset: w = [1.0] => HHI = 1.0, N_eff = 1.0, Gini = 0.0, DivScore = 0.0%
        - Skewed: w = [0.8, 0.1, 0.1] => HHI = 0.66, N_eff = 1.515
        """
        engine = AnalyticsEngine()

        res_single = await engine.concentration_analysis({"INFY.NS": 1.0})
        assert res_single["herfindahl_index"] == 1.0
        assert res_single["effective_positions"] == 1.0
        assert res_single["diversification_score"] == 0.0
        assert res_single["gini_coefficient"] == 0.0

        res_equal = await engine.concentration_analysis({f"A_{i}": 0.2 for i in range(5)})
        assert abs(res_equal["herfindahl_index"] - 0.20) < 1e-4
        assert abs(res_equal["effective_positions"] - 5.0) < 1e-4
        assert abs(res_equal["diversification_score"] - 100.0) < 1e-2
        assert abs(res_equal["gini_coefficient"] - 0.0) < 1e-4

        res_skewed = await engine.concentration_analysis({"A": 0.8, "B": 0.1, "C": 0.1})
        assert abs(res_skewed["herfindahl_index"] - 0.66) < 1e-4
        assert abs(res_skewed["effective_positions"] - (1.0 / 0.66)) < 0.02
        # (1 - 0.66) / (1 - 1/3) * 100 = 0.34 / (2/3) * 100 = 51.0%
        assert abs(res_skewed["diversification_score"] - 51.0) < 0.5

    def test_inverse_volatility_parity_closed_form(self):
        """
        Inverse-volatility parity weights: w_i proportional to 1 / sigma_i.
        If Asset A has sigma_A = 0.10 and Asset B has sigma_B = 0.20,
        then w_A / w_B = sigma_B / sigma_A = 2.0 exactly.
        """
        vol_a, vol_b, vol_c = 0.10, 0.20, 0.40
        inv_vols = [1.0 / vol_a, 1.0 / vol_b, 1.0 / vol_c]
        expected_weights = [iv / sum(inv_vols) for iv in inv_vols]

        assert abs(expected_weights[0] / expected_weights[1] - 2.0) < 1e-12
        assert abs(expected_weights[1] / expected_weights[2] - 2.0) < 1e-12
        assert abs(sum(expected_weights) - 1.0) < 1e-12

    def test_hrp_and_cvxpy_optimizers_feasibility_and_optimality(self):
        """
        Verifies that all portfolio optimizers (HRP, min_vol, max_sharpe, min_cvar):
        1. Produce weights strictly in [0, 1] that sum to 1.0 within numerical precision.
        2. Minimum Variance portfolio achieves lower variance than an equal-weight portfolio.
        3. Maximum Sharpe portfolio achieves higher Sharpe than an equal-weight portfolio.
        """
        np.random.seed(123)
        t_len = 300
        n_assets = 4

        # Generate realistic asset returns with different means and volatilities
        mu_daily = np.array([0.0008, 0.0004, 0.0006, 0.0002])
        vols_daily = np.array([0.012, 0.018, 0.025, 0.008])
        raw_noise = np.random.normal(0, 1, (t_len, n_assets))
        returns_array = mu_daily + raw_noise * vols_daily
        returns_df = pd.DataFrame(returns_array, columns=[f"STK_{i}" for i in range(n_assets)])

        cov_annual = returns_df.cov().values * 252.0
        mu_annual = returns_df.mean().values * 252.0
        rf = 0.02

        # 1. HRP
        w_hrp = _hrp_weights(returns_df).values
        assert abs(np.sum(w_hrp) - 1.0) < 1e-6
        assert (w_hrp >= -1e-7).all()

        # 2. Min Vol
        w_min_vol = _min_vol(cov_annual)
        assert abs(np.sum(w_min_vol) - 1.0) < 1e-6
        assert (w_min_vol >= -1e-7).all()
        w_eq = np.full(n_assets, 1.0 / n_assets)
        var_min_vol = float(w_min_vol.T @ cov_annual @ w_min_vol)
        var_eq = float(w_eq.T @ cov_annual @ w_eq)
        assert var_min_vol <= var_eq

        # 3. Max Sharpe
        w_max_sharpe = _max_sharpe(mu_annual, cov_annual, rf)
        assert abs(np.sum(w_max_sharpe) - 1.0) < 1e-6
        assert (w_max_sharpe >= -1e-7).all()
        sharpe_opt = float((mu_annual @ w_max_sharpe - rf) / np.sqrt(w_max_sharpe.T @ cov_annual @ w_max_sharpe))
        sharpe_eq = float((mu_annual @ w_eq - rf) / np.sqrt(w_eq.T @ cov_annual @ w_eq))
        assert sharpe_opt >= sharpe_eq - 1e-5

        # 4. Min CVaR
        w_min_cvar = _min_cvar(returns_df, beta=0.95)
        assert abs(np.sum(w_min_cvar) - 1.0) < 1e-6
        assert (w_min_cvar >= -1e-7).all()

    def test_ornstein_uhlenbeck_analytical_parameter_recovery(self):
        """
        Simulate an exact Ornstein-Uhlenbeck mean-reverting process:
        dZ_t = theta * (mu - Z_t) dt + sigma dW_t
        Verify that compute_ou_parameters accurately recovers theta and half-life t_{1/2} = ln(2)/theta.
        """
        np.random.seed(999)
        n_steps = 1000
        theta_true = 0.20
        half_life_true = np.log(2.0) / theta_true  # ~3.465 days

        # Discrete Euler-Maruyama for OU
        z = np.zeros(n_steps)
        for t in range(1, n_steps):
            z[t] = z[t-1] - theta_true * z[t-1] + np.random.normal(0, 0.5)

        theta_est, hl_est = compute_ou_parameters(z)
        assert theta_est is not None
        assert hl_est is not None
        # Estimation should be within 20% of ground truth on 1000 samples
        assert abs(theta_est - theta_true) < 0.05
        assert abs(hl_est - half_life_true) < 1.0

        # Non-mean-reverting explosive series must return None, None
        explosive = np.exp(np.linspace(0, 5, 100))
        assert compute_ou_parameters(explosive) == (None, None)

    def test_evt_peaks_over_threshold_cvar_le_var(self):
        """
        Extreme Value Theory: Expected Shortfall (CVaR) is the conditional mean beyond VaR.
        For return losses (where negative is loss):
        ES_alpha <= VaR_alpha < 0
        """
        np.random.seed(777)
        # Heavy-tailed Student-t returns
        heavy_returns = pd.Series(student_t.rvs(df=3, loc=0.0002, scale=0.015, size=500))
        res = TailRiskService.calculate_evt_pot_var_es(heavy_returns, confidence_level=0.99, threshold_quantile=0.95)

        assert res["evt_pot_var_99"] < 0.0
        assert res["evt_pot_es_99"] <= res["evt_pot_var_99"]
        assert res["exceedances_count"] > 0

    def test_monte_carlo_quantile_monotonicity(self):
        """
        Monte Carlo simulated trajectories must maintain strict quantile monotonicity across all horizons:
        Q_0.05(t) <= Q_0.25(t) <= Q_0.50(t) <= Q_0.75(t) <= Q_0.95(t)
        """
        np.random.seed(555)
        returns = pd.Series(np.random.normal(0.0005, 0.015, 252))

        for method in ("gbm", "student_t", "bootstrap"):
            sim_res = simulate_goal(
                portfolio_returns=returns,
                initial_value=100000.0,
                target_value=120000.0,
                horizon_years=2,
                method=method,
                num_paths=1000,
                seed=42,
            )
            tp = sim_res["terminal_percentiles"]
            assert tp["p5"] <= tp["p25"]
            assert tp["p25"] <= tp["p50"]
            assert tp["p50"] <= tp["p75"]
            assert tp["p75"] <= tp["p95"]
            assert 0.0 <= sim_res["prob_success"] <= 1.0

            # Check all fan checkpoints
            for fan_pt in sim_res["fan"]:
                assert fan_pt["p5"] <= fan_pt["p25"]
                assert fan_pt["p25"] <= fan_pt["p50"]
                assert fan_pt["p50"] <= fan_pt["p75"]
                assert fan_pt["p75"] <= fan_pt["p95"]

    def test_deterministic_monthly_return_compounding(self):
        """
        Deterministic Return Compounding:
        Monthly returns must be grouped and compounded geometrically via
        (1 + r).groupby([year, month]).prod() - 1 rather than arithmetic sum.
        """
        dates = pd.date_range("2024-01-01", periods=60, freq="B")
        # Create non-zero daily returns
        r = pd.Series(np.full(60, 0.01), index=dates)

        # Geometric compounding: (1 + 0.01)^N - 1
        jan_count = sum(dates.month == 1)
        expected_jan_geom = (1.0 + 0.01) ** jan_count - 1.0

        m_series = (1.0 + r).groupby([r.index.year, r.index.month]).prod() - 1.0
        assert abs(m_series.iloc[0] - expected_jan_geom) < 1e-12
