# Quantitative coverage — every metric this codebase computes, with its verdict

**Purpose.** The anti-re-litigation artefact. **A row marked `VERIFIED-CORRECT` must never be
audited again by name** — the reference and the probe are already on the record. Rows marked
`WRONG-NUMBER` / `WRONG-CONVENTION` / `FRAGILE` name the finding that owns them.

**How to read a verdict.**
`VERIFIED-CORRECT` — the implemented formula is the standard definition, checked against a
reference (a library's own source in `backend/.venv`, a closed-form identity, or a numeric
probe) *and* the line was opened. · `WRONG-NUMBER` — publishes a value the metric does not
mean. · `WRONG-CONVENTION` — defensible but inconsistent or undisclosed. · `FRAGILE` —
correct today, breaks on a real input.

**Provenance of a verdict.** `VERIFIED` (code + reference read) · `DERIVED` (arithmetic /
definition, no external reference quoted) · `NEEDS-RUNTIME` (cannot be settled without
executing project code).

**Counts (tallied from the table, not asserted).** **162 numbered metric rows** across 17
sections. By verdict: `VERIFIED-CORRECT` **129** · `WRONG-NUMBER` **7** · `WRONG-CONVENTION`
**18** · `FRAGILE` **8**. Distinct findings owned: **28** (`QM-1` … `QM-28`, all ids unique) —
the 7 WRONG-NUMBER **rows** collapse to 5 findings because row 5 (Sharpe) and row 7 (Sortino
guard) are both QM-3, and the 18 WRONG-CONVENTION rows are shared across 12 findings. The
VERIFIED-CORRECT rows expand into the 53 `VC-*` blocks of `detail/quant-models.md`.
Cross-references into `detail/services.md` are marked `≡ SVC-n` and are **the same defect, not
a second one**.

---

## A. `analytics_engine.py` — realized risk (portfolio + per position)

| # | Metric | Field / key | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 1 | Coverage fraction | `active_return_coverage.covered_weight_fraction` | `analytics_engine.py:128-130` | VERIFIED-CORRECT | VERIFIED |
| 2 | Renormalisation uplift | `renormalization_uplift` | `analytics_engine.py:142-144` | VERIFIED-CORRECT | VERIFIED |
| 3 | Annualized arithmetic return | `annual_return` | `analytics_engine.py:5464` | VERIFIED-CORRECT | VERIFIED |
| 4 | Annualized volatility (ddof=1 ×√252) | `annual_volatility` | `analytics_engine.py:5465` | VERIFIED-CORRECT | VERIFIED |
| 5 | **Sharpe ratio** | `sharpe_ratio` | `analytics_engine.py:5468` | **WRONG-NUMBER** | **QM-3** ≡ SVC-2 |
| 6 | Sortino — downside denominator | `sortino_ratio` formula | `analytics_engine.py:5470-5476` | VERIFIED-CORRECT (full-`N` denominator) | VERIFIED |
| 7 | **Sortino ratio — degenerate case** | `sortino_ratio` guard | `analytics_engine.py:5476` | **WRONG-NUMBER** | **QM-3** ≡ SVC-2 |
| 8 | Hit ratio | `hit_ratio` | `analytics_engine.py:5479` | VERIFIED-CORRECT | VERIFIED |
| 9 | **Historical VaR 95 %** | `var_95` | `analytics_engine.py:5498` | **WRONG-CONVENTION** (sign/units undeclared) | **QM-12** |
| 10 | **Historical CVaR / ES 95 %** | `cvar_95` | `analytics_engine.py:5501` | **WRONG-CONVENTION** (same; `≤percentile` mask ≥5 % undeclared) | **QM-12** |
| 11 | Maximum drawdown | `max_drawdown` | `analytics_engine.py:5521-5529` | VERIFIED-CORRECT | VERIFIED |
| 12 | Skewness (Fisher-Pearson, bias-corrected) | `skewness` | `analytics_engine.py:5541` | VERIFIED-CORRECT | VERIFIED |
| 13 | **Kurtosis** | `kurtosis` | `analytics_engine.py:5542` | **WRONG-CONVENTION** (Fisher **excess**, plain name) | **QM-11** |
| 14 | Portfolio return aggregation / coverage gate | `aggregate_active_returns` | `analytics_engine.py:255-293`, `:56` | VERIFIED-CORRECT | VERIFIED |

## B. `analytics_engine.py` — quantstats tear-sheet restatements

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 15 | Sharpe (compounded daily rf) | `sharpe` | `analytics_engine.py:2036-2040` | VERIFIED-CORRECT | VERIFIED |
| 16 | Sortino (full-`N` denominator) | `sortino` | `analytics_engine.py:2042-2047` | VERIFIED-CORRECT | VERIFIED |
| 17 | Omega ratio (rf=0, req=0) | `omega` | `analytics_engine.py:2049-2057` | VERIFIED-CORRECT | VERIFIED |
| 18 | Total return (compounded) | `total_return` | `analytics_engine.py:2059-2062` | VERIFIED-CORRECT | VERIFIED |
| 19 | CAGR (geometric, `abs()` quirk) | `cagr` | `analytics_engine.py:2064-2069` | VERIFIED-CORRECT | VERIFIED |
| 20 | Volatility (ddof=1 ×√252) | `volatility` | `analytics_engine.py:2071-2073` | VERIFIED-CORRECT | VERIFIED |
| 21 | Max drawdown (returns baseline 1.0) | `max_drawdown` | `analytics_engine.py:2075-2096` | VERIFIED-CORRECT | VERIFIED |
| 22 | Calmar | `calmar` | `analytics_engine.py:2098-2100` | VERIFIED-CORRECT | VERIFIED |
| 23 | Tail ratio (q95/q05) | `tail_ratio` | `analytics_engine.py:2102-2109` | VERIFIED-CORRECT | VERIFIED |
| 24 | Daily risk-free de-annualisation | `daily_rf` | `analytics_engine.py:2034` | VERIFIED-CORRECT (compounded, not divided) | VERIFIED |
| 25 | Beta (cov/var, ddof=1) | `beta` | `analytics_engine.py:2135-2151` | VERIFIED-CORRECT | VERIFIED |
| 26 | Annualized Jensen alpha (×252) | `alpha_annualized` | `analytics_engine.py:2148` | VERIFIED-CORRECT | VERIFIED |
| 27 | Independent beta/alpha witness | `market_model_witness` | `analytics_engine.py:2159-2214` | VERIFIED-CORRECT (genuinely independent path) | VERIFIED |
| 28 | Pairwise average correlation (bootstrap restatement) | `avg_pairwise_correlation` | `analytics_engine.py:2333-2419` | VERIFIED-CORRECT (pairwise-complete) | VERIFIED |
| 29 | R² (`Sxy²/(Sxx·Syy)`) | `factor_r_squared` | `analytics_engine.py:2437-2447` | VERIFIED-CORRECT | VERIFIED |
| 30 | "returns look like prices" guard | `quantstats_returns_look_like_prices` | `analytics_engine.py:1999-2012` | VERIFIED-CORRECT | VERIFIED |

## C. `analytics_engine.py` — concentration, liquidity, stress

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 31 | Herfindahl index | `herfindahl_index` | `analytics_engine.py:3861` | VERIFIED-CORRECT | VERIFIED |
| 32 | Effective positions (1/HHI) | `effective_positions` | `analytics_engine.py:3864` | VERIFIED-CORRECT | VERIFIED |
| 33 | Diversification score (normalised HHI) | `diversification_score` | `analytics_engine.py:3868` | VERIFIED-CORRECT | VERIFIED |
| 34 | Diversification ratio (N_eff/n) | `diversification_ratio` | `analytics_engine.py:3869` | VERIFIED-CORRECT | VERIFIED |
| 35 | Gini coefficient | `gini_coefficient` | `analytics_engine.py:3873` | VERIFIED-CORRECT (probe-verified identity) | VERIFIED |
| 36 | Top-N concentration | `top_3`/`top_5`/`top_10`/`largest_position` | `analytics_engine.py:3855-3858` | VERIFIED-CORRECT | VERIFIED |
| 37 | **Concentration refusal payload** | `_empty_concentration` | `analytics_engine.py:6316-6347` | **WRONG-CONVENTION** (`HHI 0.0` impossible for `n≥1`) | **QM-20** |
| 38 | **Liquidity tier score on NaN volume** | `by_position.*.score` | `analytics_engine.py:3945-3973` | **WRONG-CONVENTION** (publishes 5.9) | **QM-16** ≡ SVC-1 |
| 39 | Liquidity band rule | `_liquidity_band` / `LIQUIDITY_SCORE_BANDS` | `analytics_engine.py:2566-2572`, `:308-312` | VERIFIED-CORRECT (bands read the rounded score) | VERIFIED |
| 40 | Market-cap provenance | `_market_cap_provenance` | `analytics_engine.py:2575-2595` | VERIFIED-CORRECT (estimated/fallback disclosed) | VERIFIED |
| 41 | Stress per-ticker impact | `position_impacts` | `analytics_engine.py:4281-4284` | VERIFIED-CORRECT (proxy, fully disclosed) | VERIFIED |
| 42 | **Stress portfolio impact / drawdown** | `portfolio_impact`, `max_drawdown` | `analytics_engine.py:4197`, `:4285-4288` | **WRONG-CONVENTION** (weights un-normalised locally) | **QM-17** |
| 43 | Stress volatility adjustment | `shock_inputs.volatility_adjustment` | `analytics_engine.py:4258-4279` | VERIFIED-CORRECT | VERIFIED |
| 44 | Stress holding co-movement (leave-one-out) | `co_movement_with_rest_of_book` | `analytics_engine.py:3516-3621` | VERIFIED-CORRECT (measured, published, not applied) | VERIFIED |

## D. `analytics_engine.py` — risk score

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 45 | Concentration sub-score | `components.concentration` | `analytics_engine.py:5029` | VERIFIED-CORRECT (`min(30, HHI·100)`) | VERIFIED |
| 46 | Volatility sub-score | `components.volatility` | `analytics_engine.py:5057` | VERIFIED-CORRECT (`min(30, σ·√252·100)`) | VERIFIED |
| 47 | Correlation sub-score | `components.correlation` | `analytics_engine.py:5118-5123` | VERIFIED-CORRECT (`min(30, 50·max(0,ρ̄))`) | VERIFIED |
| 48 | Factor sub-score | `components.factor_risk` | `analytics_engine.py:5162` | VERIFIED-CORRECT (`min(30,(1−R²)·100)`) | VERIFIED |
| 49 | Market-risk sub-score | `components.market_risk` | `analytics_engine.py:5216` | VERIFIED-CORRECT (`min(30, σ_tail60·√252·100)`) | VERIFIED |
| 50 | Composite risk score | `overall_score` | `analytics_engine.py:5241-5250` | VERIFIED-CORRECT (weights renormalise to 1, None legs excluded) | VERIFIED |
| 51 | Average pairwise correlation (published) | `avg_pairwise_correlation` | `analytics_engine.py:5092-5097` | VERIFIED-CORRECT | VERIFIED |
| 52 | Risk-score leg weights | `RISK_SCORE_WEIGHTS` | `analytics_engine.py:566-572` | VERIFIED-CORRECT (sums to 1.00) | VERIFIED |
| 53 | **Concentration leg on an unmeasured HHI** | `components.concentration` | `analytics_engine.py:5027-5030` | **FRAGILE** | **QM-27** |

## E. `analytics_engine.py` — factor exposure

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 54 | Market beta (per ticker) | `positions.*.market` | `analytics_engine.py:6148` | VERIFIED-CORRECT | VERIFIED |
| 55 | Daily alpha (per ticker) | `positions.*.alpha` | `analytics_engine.py:6147` | VERIFIED-CORRECT | VERIFIED |
| 56 | Annualized alpha (×252) | `positions.*.annualized_alpha` | `analytics_engine.py:6161` | VERIFIED-CORRECT | VERIFIED |
| 57 | HAC standard errors (Newey–West, maxlags=5) | `alpha_std_error`, `market_std_error` | `analytics_engine.py:6077-6080`, `:6149-6150` | VERIFIED-CORRECT (basis published) | VERIFIED |
| 58 | R² of the portfolio fit | `r_squared` | `analytics_engine.py:6211` | VERIFIED-CORRECT | VERIFIED |
| 59 | **Adjusted R²** | `adjusted_r_squared` | `analytics_engine.py:6212` | **WRONG-NUMBER** (`max(0, ·)` hides negatives) | **QM-2** |
| 60 | **Factor-exposure failure block** | `positions.*` on exception | `analytics_engine.py:6175-6182` | **FRAGILE** (`data_points: 0` is false) | **QM-28** |

## F. `analytics_engine.py` — volatility forecast & sizing

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 61 | GARCH(1,1) annualized forecast | `volatility_forecast` | `analytics_engine.py:6642-6650` | VERIFIED-CORRECT (mean of horizon variance path) | VERIFIED |
| 62 | EGARCH forecast (analytic h=1 / simulation h>1) | `volatility_forecast` | `analytics_engine.py:6591-6650` | VERIFIED-CORRECT (arch 8 refuses analytic h>1) | VERIFIED |
| 63 | EWMA forecast (RiskMetrics recursion) | `volatility_forecast` | `analytics_engine.py:6530-6569` | VERIFIED-CORRECT (`ddof=1` window seed, λ=0.94) | VERIFIED |
| 64 | Cumulative-horizon annualisation | `_cumulative_forecast_volatility` | `analytics_engine.py:5770-5775` | VERIFIED-CORRECT (`√(Σv·252/t)`) | VERIFIED |
| 65 | **h-day return-space sigma (EWMA branch)** | `return_space_volatility` | `analytics_engine.py:6565` | **WRONG-CONVENTION** (built from the *clipped* sigma) | **QM-6** |
| 66 | h-day return-space sigma (GARCH/EGARCH) | `return_space_volatility` | `analytics_engine.py:6652` | VERIFIED-CORRECT (raw path) | VERIFIED |
| 67 | **Parametric VaR / CVaR forecast** | `var_forecast`, `cvar_forecast` | `analytics_engine.py:5864-5869` | **WRONG-CONVENTION** (correct constants; estimator named only in the nested block) | **QM-13** |
| 68 | Normal z / ES multipliers | `TAIL_Z_MULTIPLIER`, `TAIL_ES_MULTIPLIER` | `analytics_engine.py:834-835` | VERIFIED-CORRECT (1.6449 / 2.0627 measured) | VERIFIED |
| 69 | Volatility term structure | `term_structure` | `analytics_engine.py:5892-5895`, `:6007` | VERIFIED-CORRECT (flat under RiskMetrics, declared) | VERIFIED |
| 70 | **Input return winsorisation** | (undisclosed) | `analytics_engine.py:6528` | **FRAGILE** (±20 % clip before every fit) | **QM-25** |
| 71 | Inverse-volatility risk-parity weights | `recommended_weights` | `analytics_engine.py:4720-4743` | VERIFIED-CORRECT (`w ∝ 1/σ`) | VERIFIED |
| 72 | Scale-to-target | `scale_factor` | `analytics_engine.py:4799` | VERIFIED-CORRECT (`target/σ_p`, identity published) | VERIFIED |
| 73 | Achieved volatility (measurement) | `achieved_volatility` | `analytics_engine.py:4824-4826`, `:4487-4526` | VERIFIED-CORRECT (sample covariance, not the target) | VERIFIED |
| 74 | Current-book volatility (modelled) | `current_volatility` | `analytics_engine.py:4696-4702` | VERIFIED-CORRECT (corr × EWMA marginals) | VERIFIED |
| 75 | Current-book volatility (sample cov) | `current_volatility_sample_covariance` | `analytics_engine.py:4714-4718` | VERIFIED-CORRECT | VERIFIED |
| 76 | Gross exposure / net cash weight | `execution`, `cash_weight` | `analytics_engine.py:4836-4846` | VERIFIED-CORRECT (signed, leverage disclosed) | VERIFIED |

## G. `analytics_engine.py` — uncertainty machinery

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 77 | AR(1) autocorrelation | `ar1` | `analytics_engine.py:1022-1040` | VERIFIED-CORRECT (regressor in the denominator) | VERIFIED |
| 78 | Effective sample size | `effective_n` | `analytics_engine.py:1043-1060` | VERIFIED-CORRECT (`n(1−ρ)/(1+ρ)`) | VERIFIED |
| 79 | Moving-block bootstrap | `conf_int`, `standard_error` | `analytics_engine.py:1197-1237`, `:1428-1876` | VERIFIED-CORRECT (circular MBB, percentile, repro-guarded) | VERIFIED |
| 80 | Optimization-moment normal-theory SE | `normal_theory_standard_error` | `optimization_service.py:264-284` | VERIFIED-CORRECT (`√(252/n)·σ_p`; the factor the comment warns about is kept) | VERIFIED |

## H. `volatility_service.py`

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 81 | Rolling realized volatility | `window_results[].*` | `volatility_service.py:186-188` | VERIFIED-CORRECT (`ddof=1`, `√252`) | VERIFIED |
| 82 | EWMA (RiskMetrics) volatility | `current_forecast` / sizing | `volatility_service.py:233-241` | VERIFIED-CORRECT (no mean subtraction) | VERIFIED |
| 83 | **EWMA on a single observation** | `annualized_vol` | `volatility_service.py:225-230` | **FRAGILE** (returns `0.0`; feeds `valuation:"cheap"`) | **QM-24** |
| 84 | GARCH(1,1) annualized vol (mean path variance) | `annualized_vol` | `volatility_service.py:292-294` | VERIFIED-CORRECT (`100` rescale applied once) | VERIFIED |
| 85 | Vol-cone percentile rank | `percentile_rank` | `volatility_service.py:399-401` | VERIFIED-CORRECT (empirical CDF) | VERIFIED |
| 86 | Vol-cone effective n / Wald half-width | `effective_n` etc. | `volatility_service.py:53-57`, `:131-140` | VERIFIED-CORRECT (`n_windows / L`) | VERIFIED |
| 87 | **Cone EWMA overlay horizon** | `current_forecast.horizon_days` | `volatility_service.py:439-441`, `:487` | **WRONG-CONVENTION** (publishes 21 for a spot estimate) | **QM-14** |
| 88 | Cone positioning verdict | `valuation` | `volatility_service.py:474-482` | VERIFIED-CORRECT (p25/p75 comparison, `"unknown"` branch exists) | VERIFIED |

## I. `tail_risk_service.py`

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 89 | Historical VaR / ES (99 %) | `historical_var_99`, `historical_es_99` | `tail_risk_service.py:244-246` | VERIFIED-CORRECT | VERIFIED |
| 90 | EVT-POT VaR (99 %) | `evt_pot_var_99` | `tail_risk_service.py:259-261` | VERIFIED-CORRECT (incl. the ξ→0 limit) | VERIFIED |
| 91 | **EVT-POT Expected Shortfall** | `evt_pot_es_99` | `tail_risk_service.py:262` | VERIFIED-CORRECT — **probe P1b** | VERIFIED |
| 92 | GPD shape / scale | `gpd_shape_xi_raw`, `gpd_scale_beta_raw` | `tail_risk_service.py:286-303` | VERIFIED-CORRECT (`genpareto.fit(…, floc=0)`; sign convention published) | VERIFIED |
| 93 | Excess kurtosis | `excess_kurtosis` | `tail_risk_service.py:348` | VERIFIED-CORRECT (scipy default `fisher=True`) | VERIFIED |
| 94 | Fat-tail verdict | `is_fat_tailed` | `tail_risk_service.py:103-187` | VERIFIED-CORRECT (withheld, never contradicted by the shape) | VERIFIED |
| 95 | t-copula lower-tail λ_L | `matrix`, `lower_tail_lambda` | `tail_risk_service.py:511-512` | VERIFIED-CORRECT (standard formula; marginal-ν approximation disclosed) | DERIVED |
| 96 | **Linear correlation for λ_L** | `linear_correlation` | `tail_risk_service.py:487-492` | **FRAGILE** (`rho = 0.0` on a constant leg) | **QM-22** |

## J. `regime_service.py`

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 97 | Per-state CAGR | `states[].ann_ret` | `regime_service.py:339-340` | VERIFIED-CORRECT (geometric, own `n` published) | VERIFIED |
| 98 | **Per-state annualized volatility** | `states[].ann_vol` | `regime_service.py:343` | **WRONG-CONVENTION** (mean of overlapping σ, not √mean variance) | **QM-7** |
| 99 | Regime probabilities (filtered posterior) | `regime_probabilities` | `regime_service.py:374-377` | VERIFIED-CORRECT (in-sample nature disclosed) | VERIFIED |
| 100 | Transition matrix | `transition_matrix` | `regime_service.py:380-386` | VERIFIED-CORRECT (configured prior, disclosed as such) | VERIFIED |
| 101 | Regime stability | `stability_pct` | `regime_service.py:371-372` | VERIFIED-CORRECT | VERIFIED |
| 102 | State day share | `historical_days_pct` | `regime_service.py:349` | VERIFIED-CORRECT | VERIFIED |
| 103 | Parkinson volatility | `realtime_parkinson_vol` | `regime_service.py:264-273` | VERIFIED-CORRECT (pool before sqrt, `4ln2`) | VERIFIED |
| 104 | EWMA diagnostic vol | `realtime_ewma_vol` | `regime_service.py:262`, `:288` | VERIFIED-CORRECT | VERIFIED |
| 105 | Crash-veto threshold | `label_overrides.crash_veto_*` | `regime_service.py:90-113`, `:45` | VERIFIED-CORRECT (display guard, declared, model untouched) | VERIFIED |

## K. `monte_carlo_service.py`

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 106 | Calibrated μ / σ | `historical_mu_annual`, `historical_sigma_annual` | `monte_carlo_service.py:76-77` | VERIFIED-CORRECT | VERIFIED |
| 107 | GBM drift & diffusion | (paths) | `monte_carlo_service.py:119-120` | VERIFIED-CORRECT (consistent with an arithmetic μ) | VERIFIED |
| 108 | Student-t moment matching | (paths) | `monte_carlo_service.py:159-164` | VERIFIED-CORRECT (analytic `√(ν/(ν−2))`) | VERIFIED |
| 109 | Probability of success | `prob_success` | `monte_carlo_service.py:379` | VERIFIED-CORRECT (terminal; lower bound disclosed) | VERIFIED |
| 110 | Terminal percentiles / fan | `terminal_percentiles`, `fan` | `monte_carlo_service.py:384`, `:219-237` | VERIFIED-CORRECT (one array, disclosed) | VERIFIED |
| 111 | **Shortfall vs target** | `expected_shortfall_vs_target` | `monte_carlo_service.py:380-383` | **FRAGILE** (`0.0` on an empty conditioning set) | **QM-23** |

## L. `correlation_service.py`

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 112 | Rolling average pairwise correlation | `avg_correlation`, `current_avg_correlation` | `correlation_service.py:61-62` | **WRONG-NUMBER** (shrinking pair denominator) | **QM-15** ≡ SVC-8 |
| 113 | Regime-break alert | `is_regime_break`, `alert_level` | `correlation_service.py:121-178` | VERIFIED-CORRECT *given its series* (two-sided; `(2/(N(N−1)))Σρ` claim is the defect at row 112) | VERIFIED |

## M. `backtest_service.py`

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 114 | CAGR | `cagr`, `benchmark_cagr` | `backtest_service.py:188-189` | **WRONG-CONVENTION** (formula right, gate missing) | **QM-19** ≡ SVC-7 |
| 115 | Sharpe | `sharpe_ratio`, `benchmark_sharpe` | `backtest_service.py:201-202` | VERIFIED-CORRECT (arithmetic annualisation) | VERIFIED |
| 116 | Annualized volatility | `annualized_volatility` | `backtest_service.py:198-199` | VERIFIED-CORRECT | VERIFIED |
| 117 | Max drawdown | `max_drawdown` | `backtest_service.py:204-205` | VERIFIED-CORRECT | VERIFIED |
| 118 | Calmar | `calmar_ratio` | `backtest_service.py:207` | VERIFIED-CORRECT | VERIFIED |
| 119 | Turnover & cost | `total_turnover`, `cost_penalty` | `backtest_service.py:118-120` | VERIFIED-CORRECT (one-way, halved) | VERIFIED |
| 120 | Self-financing weight drift | (simulation) | `backtest_service.py:157-158` | VERIFIED-CORRECT (no look-ahead rebalance) | VERIFIED |

## N. `optimization_service.py`

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 121 | Annualized μ / Σ | `mu`, `cov` | `optimization_service.py:88-89` | VERIFIED-CORRECT (`ddof=1`, ×252) | VERIFIED |
| 122 | Moment triple | `expected_annual_*` | `optimization_service.py:110-155` | VERIFIED-CORRECT (order invariant, one funnel) | VERIFIED |
| 123 | HRP weights | `weights` (hrp) | `optimization_service.py:626-712` | VERIFIED-CORRECT (Lopez de Prado bisection, `α = 1 − σ²_L/(σ²_L+σ²_R)`) | VERIFIED |
| 124 | Minimum-variance weights | `weights` (min_vol) | `optimization_service.py:715-725` | VERIFIED-CORRECT | VERIFIED |
| 125 | Maximum-Sharpe tangency | `weights` (max_sharpe) | `optimization_service.py:728-745` | VERIFIED-CORRECT (homogenisation, `y≥0`, normalised) | VERIFIED |
| 126 | Minimum-CVaR weights | `weights` (min_cvar) | `optimization_service.py:748-763` | VERIFIED-CORRECT (Rockafellar–Uryasev scenario LP) | VERIFIED |
| 127 | **Black-Litterman posterior covariance** | `cov_bl` | `optimization_service.py:829` | **WRONG-NUMBER** | **QM-1** |
| 128 | **Black-Litterman posterior mean / excess** | `mu_bl` → `excess` | `optimization_service.py:793`, `:834` | **WRONG-NUMBER** (rf subtracted twice) | **QM-5** |
| 129 | **cvxpy solve status** | (not published) | `optimization_service.py:521-527` | **FRAGILE** (`optimal_inaccurate` published as optimal) | **QM-21** |
| 130 | Strategy objective disclosure | `objective` | `optimization_service.py:64-71`, `:349-369` | VERIFIED-CORRECT (only `max_sharpe`/`black_litterman` claim Sharpe) | VERIFIED |
| 131 | Black-Litterman prior market portfolio | `w_mkt` | `optimization_service.py:791` | VERIFIED-CORRECT (equal weight, disclosed) | VERIFIED |

## O. `cointegration_service.py`

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 132 | **Engle–Granger p-value / t-stat** | `engle_granger_pvalue`, `engle_granger_tstat`, `is_cointegrated` | `cointegration_service.py:1401-1410` | **WRONG-NUMBER** (collinear ⇒ `p=0.0`, `t=−inf`, invalid JSON) | **QM-4** |
| 133 | Engle–Granger trend / autolag setup | (undisclosed) | `cointegration_service.py:1403` | VERIFIED-CORRECT (`trend="c"`, `autolag="aic"` are the installed defaults) | VERIFIED |
| 134 | **Johansen trace rank test** | `johansen_cointegrated` | `cointegration_service.py:1062-1063` | **WRONG-CONVENTION** (`det_order`, `k_ar_diff` hardcoded, gates a directive) | **QM-8** |
| 135 | Johansen refusal on complex / ≥1 eigenvalues | (returns `None`) | `cointegration_service.py:1065-1108` | VERIFIED-CORRECT (refuses rather than salving the real part) | VERIFIED |
| 136 | **Stationarity gate vs decision transform** | `stationarity_gate` | `cointegration_service.py:1208` vs `:1403` | **WRONG-CONVENTION** (log-price gate, level-price test) | **QM-9** |
| 137 | ADF p-value (log price, `trend="c"`, AIC, `max_lags=1`) | `adf_pvalue` | `cointegration_service.py:1210-1215` | VERIFIED-CORRECT (kwargs match `arch 8.0.0` signature) | VERIFIED |
| 138 | KPSS p-value (NW bandwidth) | `kpss_pvalue` | `cointegration_service.py:1216-1220`, `:1119-1133` | VERIFIED-CORRECT (`⌊4(n/100)^{2/9}⌋`, never 0) | VERIFIED |
| 139 | I(1) / I(0) / undetermined verdict | `verdict` | `cointegration_service.py:1259-1288` | VERIFIED-CORRECT (both tests must agree) | VERIFIED |
| 140 | Hedge ratio & intercept | `hedge_ratio_beta`, `intercept_alpha` | `cointegration_service.py:1426-1428` | VERIFIED-CORRECT (OLS level fit) | VERIFIED |
| 141 | Hedge-regression standard errors | `hedge_ratio_beta_std_error` | `cointegration_service.py:1443-1456` | VERIFIED-CORRECT (`polyfit(cov=True)`, df = n−2) | VERIFIED |
| 142 | Spread & z-score | `current_spread_zscore`, `spread_points` | `cointegration_service.py:1459`, `:1468-1472` | VERIFIED-CORRECT (matches the hedge ratio used downstream) | VERIFIED |
| 143 | OU reversion speed & half-life | `ou_reversion_speed_theta`, `ou_half_life_days` | `cointegration_service.py:962-986` | VERIFIED-CORRECT (`θ=−ln(1+γ)`, `t½=ln2/θ`) | VERIFIED |
| 144 | **Hedge ratio finiteness guard** | `hedge_ratio_beta` | `cointegration_service.py:1426-1431` | **FRAGILE** (no `isfinite` check) | **QM-26** |
| 145 | Bonferroni threshold | `corrected_threshold` | `cointegration_service.py:427-441` | VERIFIED-CORRECT (`α/m`, `None` on an empty family) | VERIFIED |
| 146 | Benjamini–Hochberg threshold | `bh_threshold` | `cointegration_service.py:444-466` | VERIFIED-CORRECT (step-up, `k·q/m` published) | VERIFIED |
| 147 | Pair depth ratio | `depth_ratio` | `cointegration_service.py:287-330` | VERIFIED-CORRECT | VERIFIED |

## P. `indicators_service.py` / `screener_service.py` / `equity_research_service.py`

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 148 | **MFI (0–100)** | `mfi` | `indicators_service.py:154-159` | VERIFIED-CORRECT — **prior finding fixed; do not re-audit** | VERIFIED |
| 149 | RSI / SMA / EMA / MACD / Bollinger / ATR / VWMA | `rsi`, `close_50_sma`, … | `indicators_service.py:119-177` → `stockstats.py` | VERIFIED-CORRECT (Wilder `smma`; `MA ± 2·mov_std`) | VERIFIED |
| 150 | Screener custom-filter units (ROCE %, ROE %) | `run_custom_screen` | `screener_service.py:317-324` | VERIFIED-CORRECT (matches `bfinance` `quotes.py:241-246`) | VERIFIED |
| 151 | Debt-free D/E ceiling | `_enforce_debt_free` | `screener_service.py:280-298` | VERIFIED-CORRECT (fail-closed at 0.2) | VERIFIED |
| 152 | Graham upside % | `graham_upside_pct` | `equity_research_service.py:60`, `:235` | VERIFIED-CORRECT | VERIFIED |

## Q. `benchmark_service.py` / `app/utils/holdings.py` / wire contracts

| # | Metric | Field | Where | Verdict | Ref |
|---|---|---|---|---|---|
| 153 | **Benchmark return series** | `^NSEI` returns | `benchmark_service.py:20`, `:24`, `:142` | **WRONG-CONVENTION** (price index, no TRI, undisclosed) | **QM-10** |
| 154 | **Risk-free rate** | `risk_free_rate` | `config.py:53`, `analytics.py:555` | **WRONG-CONVENTION** (flat 0.02, duplicated) | **QM-18** |
| 155 | Annualization factor | `TRADING_DAYS = 252` everywhere | 6 files listed in QM-18 | VERIFIED-CORRECT (252 throughout; **no 365 anywhere**) | VERIFIED |
| 156 | Annualization gate | `MIN_ANNUALIZE_DAYS = 30` | `app/utils/holdings.py:32-35`, applied at `:356-367` | VERIFIED-CORRECT (policy lives in one place) | VERIFIED |
| 157 | Holding-window masking | `holding_window*` | `app/utils/holdings.py:165-230` | VERIFIED-CORRECT (never guesses, warns and drops) | VERIFIED |
| 158 | Per-position limited history | `position_limited_history` | `app/utils/holdings.py:233-247` | VERIFIED-CORRECT (own leg's count only) | VERIFIED |
| 159 | Regime-conditioned portfolio summary | `portfolio_regime_summary` | `app/utils/holdings.py:450-467` | VERIFIED-CORRECT (CAGR + `ddof=1` σ, gated) | VERIFIED |
| 160 | **Dead wire contracts** | `RealizedRiskMetrics` … `RiskScore` | `schemas.py:259-330` (+ control search) | **WRONG-CONVENTION** (no units declared *and* never applied) | **QM-11**, **QM-12** |
| 161 | `ForecastRiskMetrics.confidence_interval: List[float]` | `confidence_interval` | `schemas.py:283` | **WRONG-CONVENTION** (engine publishes `None`; schema would reject — moot because the model is dead) | **QM-11** header |
| 162 | `CointPairResult.engle_granger_tstat: float` | `engle_granger_tstat` | `schemas.py:489` | **WRONG-CONVENTION** (accepts `−inf` ⇒ invalid JSON) | **QM-4** |

---

## Metrics NOT audited (named, so the gap is on the record)

| Metric / area | Where | Why not |
|---|---|---|
| Liquidity tier thresholds (the 50 Cr / 10 Cr / 2 Cr turnover cuts and the 4 score tiers) | `analytics_engine.py:3958-3973` | Design constants, not a statistic. Checked only that they are monotonic and that the tier ladder is entered with a finite value (QM-16). |
| Stress sector-elasticity table (7 scenarios × 7 sectors) | `analytics_engine.py:4075-4146` | Judgement inputs, fully published in `shock_inputs.sector_elasticity_table` with `basis: "static_configured_table"`. No formula to be wrong. |
| GBM path values, bootstrap path values, fan checkpoints | `monte_carlo_service.py:107-196`, `:219-237` | Simulation draws, not estimates. The *calibration* they rest on is audited at row 106. |
| Liquidation-window and spread constants (`1-2`/`2-5`/`5-10` days; 2–60 bp) | `analytics_engine.py:3961-3973`, `:308-312` | Design policy, published in `LIQUIDITY_SCORE_BAND_RULE`. |
| `ai_context_service.py` (2,779 lines), `data_service.py` (1,764 lines) | — | Outside the declared scope. |
| `cache_service.py`, `currency_service.py`, `ai_dossier_service.py`, `company_data_service.py`, `india_data_service.py`, `ai_context_india.py`, `benchmark_service` fetch plumbing | — | Outside the declared scope. |
