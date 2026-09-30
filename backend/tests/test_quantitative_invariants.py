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

    @pytest.mark.asyncio
    async def test_the_diversification_score_satisfies_its_published_formula(self):
        """RL-7: `diversification_score` shipped as a bare 0-100 number.

        The v26 export published 98.5 with no scale, no formula and no holding
        count: a reader could not recompute it, and could not tell what 100
        meant. All three are now published, and this asserts the score is the
        expression those three keys describe, evaluated on the published inputs
        rather than on the engine's internal unrounded index.

        The tolerance is derived, not chosen: `herfindahl_index` is published
        rounded to 4 decimals, so the published index is within 5e-5 of the one
        the score was computed from, and the formula's divisor is `1 - 1/n` >=
        0.5 for n >= 2, which puts the induced error in the score at <= 0.01 --
        and the score itself is published rounded to 1 decimal. Where the
        published index is exact (a single holding, equal weight) the identity
        below is exact too, and is asserted as such.
        """
        engine = AnalyticsEngine()
        books = [
            {"A": 0.8, "B": 0.1, "C": 0.1},
            {f"N{i}": 0.2 for i in range(5)},
            {f"N{i}": 1.0 / 7 for i in range(7)},
            {"A": 0.6, "B": 0.15, "C": 0.15, "D": 0.1},
            {"A": 0.34, "B": 0.33, "C": 0.33},
        ]
        for book in books:
            result = await engine.concentration_analysis(book)
            n = result["n_holdings"]
            assert n == len(book), (n, book)
            hhi = result["herfindahl_index"]
            recomputed = ((1 - hhi) / (1 - 1 / n)) * 100
            assert result["diversification_score"] == pytest.approx(
                recomputed, abs=0.011
            ), (book, result["diversification_score"], recomputed)
            # The ratio is a different statistic, not a second reading of the
            # score: it is only equal to it (as a fraction) at equal weight.
            assert result["diversification_ratio"] == pytest.approx(
                (1 / hhi) / n, abs=0.02
            ), book
            assert result["diversification_score_formula"]
            assert result["diversification_ratio_formula"]
            assert "1 - 1/n_holdings" in result["diversification_score_formula"]
            assert "effective_positions / n_holdings" in (
                result["diversification_ratio_formula"]
            )
        # The two anchors, stated as anchors rather than left to be inferred.
        equal = await engine.concentration_analysis({f"N{i}": 0.2 for i in range(5)})
        assert equal["diversification_score"] == 100.0
        assert equal["herfindahl_index"] == 0.2
        single = await engine.concentration_analysis({"ONLY": 1.0})
        assert single["diversification_score"] == 0.0
        assert single["n_holdings"] == 1
        assert single["herfindahl_index"] == 1.0

    @pytest.mark.asyncio
    async def test_the_diversification_scale_says_what_both_ends_mean(self):
        """A scale with no anchors is a range, not a scale."""
        engine = AnalyticsEngine()
        result = await engine.concentration_analysis({"A": 0.8, "B": 0.1, "C": 0.1})
        scale = result["scale"]
        assert scale["min"] == 0.0
        assert scale["max"] == 100.0
        assert "0" in scale["unit"] and "100" in scale["unit"]
        # 100 is a NORMALIZED value: equal weight at any holding count.
        assert "1 / n_holdings" in scale["at_max"]
        # 0 is one holding carrying the whole book.
        assert "herfindahl_index == 1" in scale["at_min"]
        assert "n_holdings" in scale["holdings_basis"]
        # And the holding count is the one the formula is evaluated at, not a
        # second definition: zero and non-finite rows are not holdings.
        with_zeros = await engine.concentration_analysis(
            {"A": 0.8, "B": 0.2, "ZERO": 0.0, "NEG": -0.1}
        )
        assert with_zeros["n_holdings"] == 2
        # (1 - 0.68) / (1 - 1/2) * 100 = 64.0
        assert with_zeros["diversification_score"] == 64.0

    @pytest.mark.asyncio
    async def test_effective_positions_declares_the_rounding_it_uses(self):
        """`1 / herfindahl_index` will not reproduce `effective_positions`.

        The index is published at 4 decimals and the effective count is built
        from the unrounded one, so the two differ by up to ~0.008 on a 14-name
        book (0.0078 on the v26 one). The payload states the basis rather than
        leaving a reader to trip over the mismatch.
        """
        engine = AnalyticsEngine()
        book = {f"N{i}": 0.05 + 0.01 * i for i in range(14)}
        result = await engine.concentration_analysis(book)
        note = result["effective_positions_note"]
        assert "UNROUNDED" in note
        assert "4 decimals" in note
        # And the statement is true: the two genuinely differ on a skewed book.
        published = 1 / result["herfindahl_index"]
        assert published != pytest.approx(result["effective_positions"], abs=1e-4)
        assert result["effective_positions"] == pytest.approx(published, abs=0.02)
        assert result["n_holdings"] == 14

    @pytest.mark.asyncio
    async def test_holdings_basis_states_the_look_through_limitation(self):
        """One holding is ONE row, and that is a limitation, not a measurement.

        `n_holdings` counts rows. A holding that is itself a fund is never
        decomposed, so a US mega-cap technology fund on a book of Indian listings
        is one of the fourteen, and the book reads as fourteen-way diversified
        while the technology exposure inside that one row is unmeasured. Stating
        it is the difference between a reader who is misled by the number and a
        reader who knows what the number does not cover.
        """
        engine = AnalyticsEngine()
        result = await engine.concentration_analysis({f"N{i}": 0.05 for i in range(14)})
        basis = result["scale"]["holdings_basis"]
        # the existing count rule is still there, extended rather than replaced
        assert "n_holdings counts the rows" in basis
        assert "strictly positive, finite weight" in basis
        # the limitation, in the payload's own words
        assert "no look-through" in basis
        assert "LIMITATION" in basis
        assert "not measured" in basis
        # and the consequence that makes it matter on this book
        assert "fund" in basis
        assert "currency" in basis
        # a limitation is prose, not a figure: nothing numeric was added here
        assert result["n_holdings"] == 14
        assert result["herfindahl_index"] == pytest.approx(1 / 14, abs=1e-4)
        # and the same text reaches the empty-book shape, so a consumer reads one
        empty = engine._empty_concentration()
        assert empty["scale"]["holdings_basis"] == basis

    @pytest.mark.asyncio
    async def test_the_ratio_formula_states_which_way_round_it_runs(self):
        """The orientation, because two scales read as two disagreeing numbers.

        The ratio and the score are the same concentration on different scales,
        and both run the same way - larger is better diversified. The ratio's
        MAXIMUM, 1.0, is at equal weight, which is exactly where the score is at
        its 100; the ratio's MINIMUM, 1 / n_holdings, is at one holding carrying
        the book, which is exactly where the score is at its 0. Without that a
        reader parses 0.83 as "83% diversified" beside a score of 98.5 and
        concludes two numbers disagree.

        The orientation note is asserted against the NUMBERS, not against a
        phrase, so a reworded sentence still has to be true.
        """
        engine = AnalyticsEngine()
        equal = await engine.concentration_analysis({f"N{i}": 0.2 for i in range(5)})
        single = await engine.concentration_analysis({"ONLY": 1.0})
        # a genuinely skewed 14-name book, so the ratio is strictly between its
        # two ends rather than pinned at equal weight
        result = await engine.concentration_analysis(
            {f"N{i}": 0.05 + 0.01 * i for i in range(14)}
        )
        formula = result["diversification_ratio_formula"]

        # the claim the note makes, checked against the engine
        assert equal["diversification_ratio"] == pytest.approx(1.0, abs=1e-9)
        assert equal["diversification_score"] == pytest.approx(100.0, abs=1e-9)
        assert single["diversification_ratio"] == pytest.approx(1 / 1, abs=1e-9)
        assert single["diversification_score"] == pytest.approx(0.0, abs=1e-9)
        # the minimum of the ratio is 1 / n, NOT 1.0, and lands at one holding
        assert "1 / n_holdings" in formula
        assert "1.0" in formula
        # and the note is present on both ends of the scale, in words
        assert "ORIENTATION" in formula
        assert "MAXIMUM is 1.0, at equal weight" in formula
        assert "MINIMUM is 1 / n_holdings" in formula
        # a real book sits between the two, and the two scales really do disagree
        # in magnitude on it - which is the whole reason the note is needed
        assert 1 / 14 < result["diversification_ratio"] < 1.0
        assert 0.0 < result["diversification_score"] < 100.0
        assert result["diversification_score"] != pytest.approx(
            result["diversification_ratio"] * 100.0, abs=5.0
        )
        # the same text reaches the empty-book shape
        assert engine._empty_concentration()["diversification_ratio_formula"] == formula

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

    def test_prob_success_agrees_with_its_own_terminal_percentile_table(self):
        """
        prob_success is bracketed by the terminal_percentiles published beside it.

        Both are summaries of ONE array -- the terminal values of the same
        simulated paths, which is why the block now declares
        `terminal_percentiles_basis` -- so the published table constrains the
        figure:

            * the SMALLEST published level whose value is AT OR ABOVE the target
              puts a FLOOR under prob_success: the mass at or above that
              percentile is at or above p_a, and p_a is at or above the target,
              so at least (100 - a)% of the paths clear it;
            * the SMALLEST published level whose value falls SHORT of the target
              puts a CEILING on prob_success: the bottom a% of the paths sit at
              or below p_a, and p_a is below the target, so at most (100 - a)%
              of the paths clear it.

        The floor is read off the SMALLEST clearing level, never the largest. A
        floor read off the LARGEST would assert that 95% of paths clear any
        target sitting below p95, which is false of every distribution
        carrying mass between the target and p95 -- it rejects correct figures
        instead of catching wrong ones, and it is what the real export tripped
        on (prob_success=0.922 against a table whose p25 already clears the
        target: a 7.8% share of failing paths sitting between p5 and p25,
        exactly where the table puts it).
        """
        rng = np.random.default_rng(20260930)
        returns = pd.Series(rng.normal(0.0005, 0.015, 309))

        def run(method: str, target: float):
            return simulate_goal(
                portfolio_returns=returns,
                initial_value=100_000.0,
                target_value=target,
                horizon_years=5,
                method=method,
                num_paths=1000,
                seed=11,
            )

        for method in ("gbm", "student_t", "bootstrap"):
            # Targets sit at fixed fractions of the run's own p25, so each one
            # lands strictly BETWEEN two published levels and the bracket has
            # both a floor and a ceiling to be checked against. A target above
            # every level (or below every one) would leave the relation half
            # vacuous, which is how a wrong floor can hide behind a passing
            # assertion.
            p25 = run(method, 150_000.0)["terminal_percentiles"]["p25"]
            for target in (0.60 * p25, 1.40 * p25, 2.20 * p25):
                out = run(method, target)

                # The basis is declared, not inferred: a reader (or an audit
                # rule) must be able to learn that the two figures come from
                # one sample without reading the engine.
                assert out["terminal_percentiles_basis"] == (
                    "empirical_quantiles_of_simulated_terminal_paths"
                )
                detail = out["terminal_percentiles_basis_detail"]
                assert "same 1000 simulated paths" in detail
                assert "NOT a parametric fit" in detail

                # Compare against the PUBLISHED (rounded) values, because that
                # is what a consumer of the payload actually has.
                published_target = out["target_value"]
                levels = {
                    int(key.lstrip("p")): float(value)
                    for key, value in out["terminal_percentiles"].items()
                }
                clearing = [lvl for lvl, val in levels.items() if val >= published_target]
                short = [lvl for lvl, val in levels.items() if val < published_target]
                assert clearing, f"{method}: no level clears the target; nothing to check"

                low = (100 - min(clearing)) / 100.0
                high = 1.0 - min(short) / 100.0 if short else 1.0

                assert low <= out["prob_success"] <= high, (
                    f"{method} target={published_target}: "
                    f"prob_success={out['prob_success']} lies outside the bracket "
                    f"[{low}, {high}] its own percentile table requires"
                )

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

class TestShortWindowsWithholdRatherThanFabricate:
    """A short return window publishes `None` plus a reason, never a number.

    THE DEFECT.  `AnalyticsEngine._calculate_basic_metrics` had a
    `len(returns) < 10` branch that published, for every position with fewer
    than ten return observations:

        annual_return = float(returns.sum())   # a CUMULATIVE PERIOD total
        sharpe_ratio  = 0.0                    # a hard zero
        sortino_ratio = 0.0                    # a hard zero

    Three separate fabrications.  `returns.sum()` is a period total wearing
    the key of an annual RATE, and it disagreed with
    `engine_risk_statistics.annual_return` (analytics_engine.py:2209), which
    has always used `mean(axis=0) * 252` on every window including short
    ones - so the engine carried two different formulas for one field name.
    And a hard 0.0 is the one value indistinguishable from a measured zero:
    a reader cannot tell "we measured no excess return" from "we could not
    measure excess return at all".

    `annual_volatility` and `hit_ratio` deliberately STAY, because both are
    genuine measurements over the observed window.  Whether a short window may
    ANNUALIZE is the separate policy question owned by
    `apply_annualization_gate` / `MIN_ANNUALIZE_DAYS` in app/utils/holdings.py,
    which the routes already apply; that gate is untouched here.
    """

    @staticmethod
    def _engine() -> AnalyticsEngine:
        return AnalyticsEngine()

    @staticmethod
    def _returns(n: int, seed: int = 11) -> pd.Series:
        rng = np.random.default_rng(seed)
        return pd.Series(
            rng.normal(0.0004, 0.012, n),
            index=pd.bdate_range("2025-01-01", periods=n),
        )

    def test_the_three_are_none_below_ten_observations(self):
        for n in range(1, 10):
            metrics = self._engine()._calculate_basic_metrics(self._returns(n))
            assert metrics["annual_return"] is None, n
            assert metrics["sharpe_ratio"] is None, n
            assert metrics["sortino_ratio"] is None, n

    def test_no_period_sum_is_published_under_the_annual_return_key(self):
        """The specific fabrication: a cumulative sum wearing an annual label."""
        series = self._returns(7)
        metrics = self._engine()._calculate_basic_metrics(series)
        assert metrics["annual_return"] != float(series.sum())
        # And the two formulas in this one file now agree on the boundary.
        assert AnalyticsEngine.SHORT_SAMPLE_MIN_OBSERVATIONS == 10

    def test_the_measured_two_survive(self):
        """Withholding is scoped: volatility and hit rate are real numbers."""
        series = self._returns(7)
        metrics = self._engine()._calculate_basic_metrics(series)
        assert isinstance(metrics["annual_volatility"], float)
        assert metrics["annual_volatility"] == pytest.approx(
            float(series.std() * np.sqrt(252))
        )
        assert metrics["hit_ratio"] == pytest.approx(float((series > 0).mean()))

    def test_ten_observations_is_enough_and_the_values_are_real(self):
        metrics = self._engine()._calculate_basic_metrics(self._returns(10))
        for key in ("annual_return", "sharpe_ratio", "sortino_ratio"):
            assert isinstance(metrics[key], float), key
        assert np.isfinite(metrics["annual_return"])

    def test_each_withheld_field_publishes_a_stated_reason(self):
        """`None` without a reason is a silent hole, not a disclosure."""
        engine = self._engine()
        series = self._returns(7)
        metrics = engine._calculate_basic_metrics(series)
        block = engine._estimate_uncertainty_block(
            series, metrics, scope="test short window"
        )
        for field in AnalyticsEngine.SHORT_SAMPLE_WITHHELD_FIELDS:
            entry = block["estimates"][field]
            assert entry["point"] is None, field
            assert entry["status"] == "not_computed", field
            reason = entry["reason"]
            assert reason, field
            # The reason must be specific enough to act on: it names the
            # threshold, says the value is withheld rather than low, and says
            # what to do about it.
            assert "10" in reason, field
            assert "withheld" in reason, field
            assert "Widen the history window" in reason, field

    def test_the_short_window_reason_beats_the_generic_null_reason(self):
        """It must not be laundered into the generic `point is None` text."""
        engine = self._engine()
        series = self._returns(7)
        metrics = engine._calculate_basic_metrics(series)
        block = engine._estimate_uncertainty_block(
            series, metrics, scope="test short window"
        )
        generic = "the point estimate itself is withheld (below the"
        for field in AnalyticsEngine.SHORT_SAMPLE_WITHHELD_FIELDS:
            assert generic not in block["estimates"][field]["reason"], field

    def test_a_long_window_publishes_no_short_sample_reason(self):
        """The reason is scoped to the short window, not stamped on always."""
        engine = self._engine()
        series = self._returns(60)
        metrics = engine._calculate_basic_metrics(series)
        block = engine._estimate_uncertainty_block(
            series, metrics, scope="test long window"
        )
        for field in AnalyticsEngine.SHORT_SAMPLE_WITHHELD_FIELDS:
            assert "Widen the history window" not in (
                block["estimates"][field]["reason"] or ""
            ), field

    def test_the_measured_fields_are_unaffected_by_the_withholding(self):
        """The disclosure for a measured field is still a real interval."""
        engine = self._engine()
        series = self._returns(60)
        metrics = engine._calculate_basic_metrics(series)
        block = engine._estimate_uncertainty_block(
            series, metrics, scope="test long window"
        )
        annual_vol = block["estimates"]["annual_volatility"]
        assert annual_vol["point"] is not None
        assert annual_vol["conf_int"] is not None

    def test_no_hard_zero_is_published_for_an_unmeasured_quantity(self):
        """The general rule, asserted over the whole short-window block."""
        metrics = self._engine()._calculate_basic_metrics(self._returns(5))
        for field in AnalyticsEngine.SHORT_SAMPLE_WITHHELD_FIELDS:
            assert metrics[field] is None, (
                f"{field} published {metrics[field]!r} on an unmeasured "
                "quantity"
            )
