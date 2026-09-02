# Issue 06: Quantitative Mathematical Test Suite & Pytest Loop Scope Configuration

**Status**: resolved · **Owner**: agent · **Date**: 2026-09-02  
**Component**: backend/tests/test_quantitative_invariants.py, backend/pyproject.toml, backend/app/services/analytics_engine.py

---

## 1. Problem Description
- Backend tests had areas relying on superficial mocks rather than analytical and mathematical proofs.
- Pytest emitted PytestDeprecationWarning: The configuration option asyncio_default_fixture_loop_scope is unset.
- Degenerate/infinite prices (np.inf) passed into calculate_portfolio_metrics emitted RuntimeWarning: invalid value encountered in subtract in pandas nanops.

---

## 2. Root Cause
1. Pytest-asyncio 0.24.0 requires explicit declaration of asyncio_default_fixture_loop_scope = 'function' in pyproject.toml.
2. Prices containing np.inf or -np.inf produced NaN differences in _calculate_position_metrics and pct_change standard deviation calculations.
3. Lack of a dedicated mathematical invariant test suite proving Euler homogeneous risk decomposition, Herfindahl concentration bounds, inverse-volatility parity ratios, optimizer optimality, Ornstein-Uhlenbeck parameter recovery, EVT Expected Shortfall bounds, and Monte Carlo multi-path quantile monotonicity.

---

## 3. Implementation
1. Added backend/tests/test_quantitative_invariants.py:
   - test_euler_volatility_attribution_exact_identity: Proves sum(RC_i) = sigma_p and sum(%RC_i) = 1.0.
   - test_herfindahl_effective_positions_and_gini_bounds: Proves N <= 1 -> DivScore = 0.0%, equal-weight -> DivScore = 100.0%, skewed -> DivScore = 51.0%.
   - test_inverse_volatility_parity_closed_form: Proves w_A / w_B = sigma_B / sigma_A = 2.0 exactly.
   - test_hrp_and_cvxpy_optimizers_feasibility_and_optimality: Proves HRP, Min Vol, Max Sharpe, Min CVaR produce valid weights in [0, 1] summing to 1.0; verifies Min Vol variance <= equal-weight variance and Max Sharpe >= equal-weight Sharpe.
   - test_ornstein_uhlenbeck_analytical_parameter_recovery: Proves recovery of speed theta and t_{1/2} = ln(2)/theta on simulated OU trajectories; verifies explosive series return (None, None).
   - test_evt_peaks_over_threshold_cvar_le_var: Proves CVaR_0.99 <= VaR_0.99 < 0.
   - test_monte_carlo_quantile_monotonicity: Proves Q_0.05 <= Q_0.25 <= Q_0.50 <= Q_0.75 <= Q_0.95 across GBM, Student-t, and Stationary Bootstrap engines.
   - test_deterministic_monthly_return_compounding: Proves (1+r).groupby([year, month]).prod() - 1 produces exact analytical compounding.
2. Updated pyproject.toml:
   - Added asyncio_default_fixture_loop_scope = 'function' under [tool.pytest.ini_options].
3. Sanitized Infinite Prices in analytics_engine.py:
   - Replaced [np.inf, -np.inf] with np.nan before forward/backward filling and return calculations.

---

## 4. Verification
- uv run python -m pytest tests/test_quantitative_invariants.py: 8 passed in 2.55s.
- Full pytest suite uv run python -m pytest: 287 passed, 0 failed, 0 warnings, 82.52% coverage.
