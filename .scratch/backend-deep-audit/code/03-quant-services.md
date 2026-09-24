# Quant Services Line-by-Line Code Audit

Audit date: 2026-09-24  
Scope: cash-equity and portfolio-analytics quant services only  
Backend changes: none

## 1. Scope and method

I independently read every source line in the 12 first-party quant-service files listed below. I then traced their public contracts through `backend/app/api/analytics.py`, `backend/app/api/data.py`, `backend/app/api/equity_research.py`, `backend/app/models/schemas.py`, `backend/app/config.py`, and the relevant `DataService` price-frame seam. Tests were read only to determine what is and is not covered; test failures were not manufactured as findings.

No prior audit, `.scratch/backend-audit/` content, or unrelated `.scratch` content was inspected. Data-provider implementations assigned elsewhere were excluded. Out-of-scope asset classes and instruments are not analyzed; the realized-volatility file was read in full, but no out-of-scope judgment is reported. Library/model-equivalence and estimator-choice judgments are left to the separate model-verifier work.

Verification performed read-only:

- Focused regression run: **114 passed**, with 12 existing statsmodels complex-cast warnings.
- Configured Ruff gate on all 12 audited files: **passed**.
- No backend type-check command is configured in `backend/pyproject.toml`.
- Deterministic in-memory probes were used only to confirm formulas already visible in source; no evidence files were created.

### Counts

- Unique findings: **22**
- File associations: **26** (`QUANTCODE-001`, `QUANTCODE-011`, and `QUANTCODE-013` each cross service/caller boundaries)
- Audited source: **12 files / 4,492 lines**

| Dimension | Count |
|---|---:|
| P0 | 0 |
| P1 | 5 |
| P2 | 14 |
| P3 | 3 |
| Bug | 17 |
| Improvement | 2 |
| Optimization | 2 |
| Recommended change | 1 |

## 2. Exhaustive in-scope inventory

“Primary findings” assigns each unique ID to one file so the column reconciles to 22. Cross-file IDs are shown separately and are not counted twice.

| File | Lines read | Count | Primary findings | Cross-file findings | Status |
|---|---:|---:|---|---|---|
| `backend/app/services/analytics_engine.py` | 1-1345 (1,345) | 5 | `001`, `006`-`009` | — | Findings |
| `backend/app/services/backtest_service.py` | 1-195 (195) | 5 | `002`, `003`, `004`, `011`, `020` | — | Findings |
| `backend/app/services/benchmark_service.py` | 1-96 (96) | 1 | `014` | — | Findings |
| `backend/app/services/cointegration_service.py` | 1-467 (467) | 1 | `012` | `013` | Findings |
| `backend/app/services/correlation_service.py` | 1-150 (150) | 1 | `013` | — | Findings |
| `backend/app/services/indicators_service.py` | 1-242 (242) | 1 | `022` | — | Findings |
| `backend/app/services/monte_carlo_service.py` | 1-231 (231) | 1 | `005` | `011` | Findings |
| `backend/app/services/optimization_service.py` | 1-330 (330) | 1 | `010` | `011` | Findings |
| `backend/app/services/regime_service.py` | 1-353 (353) | 1 | `015` | — | Findings |
| `backend/app/services/screener_service.py` | 1-364 (364) | 0 | — | — | Clean in audited contracts |
| `backend/app/services/tail_risk_service.py` | 1-389 (389) | 4 | `016`-`019` | `001` | Findings |
| `backend/app/services/volatility_service.py` | 1-330 (330) | 1 | `021` | — | Findings; out-of-scope content excluded |
| **Total** | **4,492** | **22** | **22 unique** | **26 file associations** | — |

Excluded first-party services: market/corporate/fundamental/news/FII-DII/currency/cache/research/dossier/data-provider files. `backend/app/services/__init__.py` is a three-line package docstring, not a quant service.

## 3. Findings

### P0

None.

### P1

#### QUANTCODE-001 — Bug / P1: missing market observations are converted into zero returns

- **Evidence:** `backend/app/services/analytics_engine.py:57-62` performs `ffill().bfill()`, computes returns, replaces infinities with `0.0`, then `fillna(0.0)`. The shared quant caller repeats the same operation at `backend/app/api/analytics.py:1329-1333`; the full tail suite also does `returns_df[matched_cols].fillna(0.0)` at `backend/app/services/tail_risk_service.py:371-377`.
- **Caller/flow:** Realized risk, forecasts, stress, volatility sizing, risk score, optimizer, backtest, Monte Carlo, and tail endpoints consume these frames. A union-indexed asset with a pre-listing or interior missing price therefore contributes a synthetic 0% return instead of being excluded or explicitly marked inactive.
- **Grounded impact:** Return mean, volatility, VaR/ES, hit ratio, drawdown, covariance, and optimization samples all change when missing observations are fabricated. Position-level counts can reflect raw active history while the portfolio contribution simultaneously includes synthetic zero-return days.
- **Minimum recommendation:** Establish one strict aligned-return contract: remove infinities, preserve an explicit active mask, drop dates that do not satisfy the chosen portfolio rule, and report coverage. Do not backfill prices or returns with economic zeroes.
- **Regression-test gap:** Existing factor tests cover one asset with NaN pre-listing history, but no portfolio/factor/backtest test compares a multi-asset missing-data frame with an independently masked expected result.

#### QUANTCODE-002 — Bug / P1: backtest weights are fixed between scheduled rebalances, causing cost-free daily rebalancing

- **Evidence:** `backend/app/services/backtest_service.py:99-114` keeps `current_weights` unchanged for the whole chunk and computes every day as `chunk_vals @ current_weights`; friction is charged only on `idx == 0` at `backend/app/services/backtest_service.py:120-123`. After day `t`, the correct self-financing weights are `w[t+1] = w[t] * (1+r[t]) / (1+w[t]ᵀr[t])`, not `w[t]`.
- **Caller/flow:** Every multi-asset `/backtest` run with `rebalance_freq_days > 1` silently receives target weights again each day without paying the resulting turnover.
- **Grounded impact:** Strategy returns, Sharpe, CAGR, drawdown, turnover, and costs are all wrong whenever assets have different returns between scheduled rebalances. The benchmark has the same fixed-weight daily-rebalance behavior and no friction, compounding the asymmetry.
- **Minimum recommendation:** Apply returns and then drift weights after each test day; rebalance and charge costs only at the declared boundaries. Define the benchmark either as true buy-and-hold or as a separately labelled, costed daily-rebalanced benchmark.
- **Regression-test gap:** `backend/tests/test_quant_math_p1_batch.py:137-144` currently pins fixed weights for the whole chunk, so the suite entrenches the incorrect assumption rather than testing drift.

#### QUANTCODE-003 — Bug / P1: negative transaction costs are accepted and increase reported wealth

- **Evidence:** Validation at `backend/app/services/backtest_service.py:32-51` omits `transaction_cost_bps`. The exact calculation is `cost_factor = bps / 10000` at line 54 and `day_return = (1 - turnover*cost_factor)*(1+r)-1` at lines 120-123. A negative bps value makes the multiplier exceed one. The raw request value is accepted at `backend/app/api/analytics.py:1749-1753`.
- **Caller/flow:** Any caller can submit a negative cost to `/backtest`; the result is labelled CAGR, Sharpe, drawdown, and turnover as if costs were modeled.
- **Grounded impact:** The service can turn a cost into a return uplift on every rebalance day, materially biasing performance rather than merely accepting an unusual model setting.
- **Minimum recommendation:** Require finite `transaction_cost_bps >= 0` (and a documented upper bound if desired); validate `risk_free_rate` is finite as well.
- **Regression-test gap:** Existing turnover tests cover positive costs only and do not assert rejection of negative/non-finite cost inputs.

#### QUANTCODE-004 — Recommended change / P1: “out-of-sample” backtest is conditional on today’s surviving universe

- **Evidence:** `/backtest` resolves only the current portfolio or current request tickers at `backend/app/api/analytics.py:1755-1759`, then fetches only that fixed set for all history at `backend/app/api/analytics.py:1762-1766`. No point-in-time membership or delisted-name history enters `run_walk_forward_backtest`.
- **Caller/flow:** The default route evaluates historical strategy performance using assets that survived and remain in the current book. The train/test split prevents direct time leakage, but it does not remove universe survivorship/selection bias.
- **Grounded impact:** Reported performance is valid only for the fixed current universe; it is not an unbiased estimate of the strategy over the historical investable universe.
- **Minimum recommendation:** Minimum disclosure is to label this a “fixed-current-universe conditional backtest.” A stronger fix requires point-in-time membership and delisted-security data.
- **Regression-test gap:** Tests use a static synthetic column set and contain no historical membership/delisting fixture capable of detecting the bias.

#### QUANTCODE-005 — Bug / P1: Monte Carlo’s element cap still permits multi-gigabyte valid requests

- **Evidence:** `backend/app/services/monte_carlo_service.py:35-38` budgets **50 million elements per live array**, not total simulation memory. At 40 years, lines 187-188 permit 4,960 paths × 10,080 steps. Each float64 path array is about 381.5 MiB; `_simulate_gbm` names `shocks`, `log_increments`, `log_paths`, and `paths` at lines 73-77, and `hstack` creates another output array at line 77. Student-t has similarly large intermediates at lines 99-106.
- **Caller/flow:** `/monte-carlo` accepts horizons through 40 years and path requests through 20,000. A 20,000-path request is validly scaled to 4,960 paths at that horizon, but the remaining workload is still accepted without an aggregate-memory limit.
- **Grounded impact:** A valid request can allocate at least 1.5 GiB across named live arrays before transient allocations, causing severe memory pressure/OOM.
- **Minimum recommendation:** Simulate in bounded chunks or checkpoints, budget aggregate live elements, and reject with a clear error when the requested workload cannot fit.
- **Regression-test gap:** `backend/tests/test_bugfix_quant_services.py:321-343` monkeypatches simulation and checks only `paths*steps`; it does not test aggregate live memory or actual allocation.

### P2

#### QUANTCODE-006 — Bug / P2: risk-score factor leg discards the supplied portfolio weights

- **Evidence:** Actual weights are used for portfolio returns at `backend/app/services/analytics_engine.py:732`, but the benchmark call at line 762 omits `weights`. `factor_exposure_analysis` therefore defaults to equal weights at lines 157-160, and that equal-weight R² becomes the factor-risk score at line 768.
- **Caller/flow:** `/risk-score` and `/summary` can score volatility for the real book but factor risk for a different equal-weight basket.
- **Grounded impact:** Component and overall risk scores change with the active book even though the factor leg did not; the payload mixes two different portfolios.
- **Minimum recommendation:** Pass the same normalized `weights` to `factor_exposure_analysis`, or calculate R² directly from the already-computed `portfolio_returns`.
- **Regression-test gap:** The benchmark test only checks that a factor component is non-null; it does not compare unequal current weights against an explicitly weighted expected R².

#### QUANTCODE-007 — Bug / P2: multi-asset factor regression treats missing constituents as partial exposure

- **Evidence:** `_calculate_portfolio_returns` uses `(returns * weight_vector).sum(axis=1)` at `backend/app/services/analytics_engine.py:837-842`, which skips missing columns. Portfolio factor regression then marks a date active when **any** constituent is present at lines 1166-1177.
- **Caller/flow:** Before an asset lists, or during an isolated data gap, the regression contains one constituent’s weighted return but silently omits the missing constituent’s weight instead of excluding the date or explicitly treating that weight as cash.
- **Grounded impact:** Portfolio alpha, beta, R², and adjusted R² are regressions on a time-varying exposure, not the current constant-weight portfolio. Position betas already filter to their own active history, so the portfolio and position legs also use different alignment rules.
- **Minimum recommendation:** Use one documented rule: require all positive-weight constituents active, drop each date and renormalize available weights, or include an explicit cash leg.
- **Regression-test gap:** The active-history test uses one asset, for which partial exposure and full exposure are identical; no multi-asset pre-listing fixture checks the portfolio leg.

#### QUANTCODE-008 — Bug / P2: unsupported model names are silently computed as another model and then mislabeled

- **Evidence:** `forecast_volatility` routes every unknown model to GARCH at `backend/app/services/analytics_engine.py:116-123`, while `/forecast-risk` echoes the requested string at `backend/app/api/analytics.py:575-589`. In volatility sizing, every non-GARCH/non-EGARCH value is computed as EWMA at `backend/app/services/analytics_engine.py:596-610`, but methodology is prefixed with the unknown input at lines 678-684.
- **Caller/flow:** Any typo or unsupported model name receives a successful numerical response whose displayed model/methodology does not describe the calculation.
- **Grounded impact:** Consumers cannot audit which estimator produced a risk number; cache/UI labels are false even when the numeric result is otherwise valid.
- **Minimum recommendation:** Validate against `{GARCH, EGARCH, EWMA}` and return a 4xx error for unsupported values.
- **Regression-test gap:** No test sends an unknown model through either service or route.

#### QUANTCODE-009 — Bug / P2: a positive custom stress can be returned as positive `max_drawdown`

- **Evidence:** Custom signed shocks are accepted at `backend/app/services/analytics_engine.py:491-499`. Position and portfolio impact retain the sign at lines 539-545, and `max_drawdown = portfolio_impact * 1.15` is returned unchanged at line 546.
- **Caller/flow:** `StressTestRequest.scenario` is an unrestricted string at `backend/app/models/schemas.py:250-253`; a scenario such as `+10%` therefore reaches this branch.
- **Grounded impact:** A gain scenario is emitted with a positive “max drawdown,” violating the metric’s sign and making gain/loss scenarios indistinguishable by field semantics.
- **Minimum recommendation:** Either reject non-negative shocks for drawdown scenarios or return a signed `scenario_impact` plus a separately defined `max_drawdown` that remains non-positive.
- **Regression-test gap:** Stress tests cover only negative scenarios.

#### QUANTCODE-010 — Improvement / P2: Black-Litterman bypasses the service’s solver-error contract

- **Evidence:** `_solve` maps CVXPY `SolverError` to `ValueError` at `backend/app/services/optimization_service.py:46-52`. `_black_litterman` calls `prob.solve` directly at line 274, and `optimize` promises `ValueError` for solver failures at lines 294-297. `/optimize/run` maps `ValueError` to 400 only at `backend/app/api/analytics.py:1729-1732`.
- **Caller/flow:** A Black-Litterman solver failure can escape as `SolverError` and become a 500, while equivalent min-vol/max-sharpe/min-CVaR failures become client errors.
- **Grounded impact:** API status and error contract are inconsistent specifically by strategy.
- **Minimum recommendation:** Call `_solve(prob)` in `_black_litterman`; retain the existing fallback only for mathematically valid min-vol fallback conditions, not solver exceptions.
- **Regression-test gap:** Solver-error mapping is tested for `_min_vol` only.

#### QUANTCODE-011 — Optimization / P2: solver-, backtest-, and Monte Carlo-heavy work runs on the async event loop

- **Evidence:** Synchronous calls occur inside async routes at `backend/app/api/analytics.py:1702` (`optimize`), line 1768 (`run_walk_forward_backtest`), and line 1890 (`simulate_goal`). The services are synchronous and contain CVXPY solves, repeated walk-forward optimizations, bootstrap generation, and large NumPy arrays.
- **Caller/flow:** One request occupies the worker event loop until all CPU work and memory operations finish; no `asyncio.to_thread`, process pool, or bounded quant executor separates them.
- **Grounded impact:** Concurrent health checks, websocket delivery, and unrelated API requests stall for the duration. Monte Carlo is the largest case and compounds `QUANTCODE-005`.
- **Minimum recommendation:** Use a bounded executor/process pool for CPU-heavy simulations and solver work, with request-level cancellation and aggregate workload limits.
- **Regression-test gap:** There is an event-loop responsiveness test for ARCH fitting inside `AnalyticsEngine`, but none for `/optimize/run`, `/backtest`, or `/monte-carlo`.

#### QUANTCODE-012 — Bug / P2: cointegration cache identity omits the requested lookback/history

- **Evidence:** `_db_cache_keys` and `_mem_cache_key` include pair, date, p-value, and spread flag at `backend/app/services/cointegration_service.py:44-72`, but `scan_pairs` has no lookback argument. `/coint` accepts `lookback_days` at `backend/app/api/analytics.py:1968-1974`, fetches different windows at lines 2002-2006, and then calls the same cache identity at lines 2014-2020.
- **Caller/flow:** A 60-day request and a 2,520-day request for the same pair, day, threshold, and spread flag share both L1 and durable cache keys.
- **Grounded impact:** The second request can receive the first request’s statistics and spread series, changing significance, half-life, z-score, and signal without any data change.
- **Minimum recommendation:** Add effective lookback/history bounds or a deterministic data-coverage fingerprint to both cache keys.
- **Regression-test gap:** Cache tests cover p-value and spread flags, not different lookbacks or coverage lengths.

#### QUANTCODE-013 — Optimization / P2: pairwise endpoints have no universe bound; correlation blocks and cointegration scales as unbounded O(N²)

- **Evidence:** `/correlation-stability` accepts an unrestricted comma-separated ticker string at `backend/app/api/analytics.py:1908-1915`, and calls the synchronous service directly at lines 1954-1957. Correlation forms every pair at `backend/app/services/correlation_service.py:52-62`. `/coint` similarly has no ticker-count limit at `backend/app/api/analytics.py:1968-1978`; it materializes every combination at `backend/app/services/cointegration_service.py:404` and runs statsmodels work one pair at a time at lines 408-431.
- **Caller/flow:** Increasing the request’s ticker count directly increases pair count quadratically. Correlation work remains on the event loop; cointegration offloads each pair but still schedules them serially with unbounded total work.
- **Grounded impact:** Large valid requests cause long latency and event-loop stalls, with no deterministic request-size error boundary.
- **Minimum recommendation:** Deduplicate and cap the universe, reject excessive pair counts up front, vectorize where possible, and use a bounded pair executor for cointegration.
- **Regression-test gap:** Tests use two or three assets and contain no large-universe latency/event-loop guard.

#### QUANTCODE-014 — Bug / P2: historical benchmark requests are fetched from the wrong time anchor

- **Evidence:** `get_returns` computes only `end - start` and forwards `max(days, span_days)` at `backend/app/services/benchmark_service.py:79-87`. `ensure_history` then anchors the fetch to `datetime.now()` at lines 51-57 rather than the requested `end`.
- **Caller/flow:** `get_returns` is a public historical-window helper used by tear-sheet (which accepts explicit dates) as well as current-window analytics callers. For a 2020 start/end request, the service asks the data service for a recent window anchored to 2026 and may return no benchmark even when the database contains 2020 rows.
- **Grounded impact:** Historical beta, alpha, relative metrics, and benchmark overlays silently disappear or use the wrong period.
- **Minimum recommendation:** Anchor the fetch start to the requested end: `fetch_days = span_days + age_of(end)`, or make `ensure_history` accept explicit start/end.
- **Regression-test gap:** The existing test checks only that the forwarded day count is at least the span; it does not assert the actual start/end or a historical end date.

#### QUANTCODE-015 — Bug / P2: crash-veto display state can contradict the returned regime probabilities

- **Evidence:** Display states are relabeled at `backend/app/services/regime_service.py:238-243`. `current_regime` uses `display_states[-1]` at line 274, but `regime_probabilities` is built from the untouched raw HMM posterior at lines 248-251.
- **Caller/flow:** When the latest day triggers the crash veto but its raw HMM label is calm/bull, the response says `current_regime = crisis` while the highest displayed probability can remain calm/bull.
- **Grounded impact:** UI and downstream conditional logic receive contradictory current-state and probability fields on exactly the override days the veto is intended to handle.
- **Minimum recommendation:** Either expose raw and display probability sets separately or recompute/renormalize display probabilities consistently with the override contract.
- **Regression-test gap:** Crash tests verify that vetoed history is not bull/calm, but never assert current-regime/probability agreement on a vetoed latest observation.

#### QUANTCODE-016 — Bug / P2: arbitrary tail confidence is returned under hard-coded “99” field names

- **Evidence:** `confidence_level` is configurable and returned at `backend/app/services/tail_risk_service.py:142-143`, but all four values are hard-coded as `evt_pot_var_99`, `evt_pot_es_99`, `historical_var_99`, and `historical_es_99` at lines 144-147. `/tails` accepts any level from 0.90 to 0.999 at `backend/app/api/analytics.py:2200-2206` and passes it at line 2232.
- **Caller/flow:** A 95% request returns 95% calculations named `*_99`; a 99.9% request is likewise mislabelled.
- **Grounded impact:** Consumers can store or display the wrong confidence level even when the numerical calculation used the requested level.
- **Minimum recommendation:** Use confidence-neutral field names (`var_loss`, `es_loss`) or fix the public endpoint to 0.99 only.
- **Regression-test gap:** Tests cover default/0.99 and threshold validation, not non-0.99 field/schema consistency.

#### QUANTCODE-017 — Bug / P2: constant return series are assigned a finite independence value

- **Evidence:** When either standard deviation is zero, `calculate_bivariate_tail_dependence` sets `rho = 0.0` at `backend/app/services/tail_risk_service.py:204-209`, then evaluates the Student-t formula at lines 222-231.
- **Caller/flow:** Flat prices/returns can reach tail analysis through the shared return builder. Correlation is undefined for a zero-variance series, yet the service returns a finite lambda and a matrix/risk category as if dependence were measurable.
- **Grounded impact:** Constant instruments can receive non-zero lower-tail dependence and appear in pair diagnostics solely because undefined correlation was replaced with zero.
- **Minimum recommendation:** Return an explicit undefined/insufficient-variance result and omit or null the off-diagonal matrix entry; do not substitute independence.
- **Regression-test gap:** No constant/zero-variance pair test exists.

#### QUANTCODE-018 — Improvement / P2: EVT output silently mixes fitted and post-clamped parameters/metrics

- **Evidence:** The fitted GPD shape is clipped to `[-0.5, 0.95]` at `backend/app/services/tail_risk_service.py:103-105`, then the extrapolated VaR is floored at `threshold_u` and `0.9 * historical VaR` at lines 117-120. The clipped shape and altered VaR are returned as ordinary fitted metrics at lines 142-150.
- **Caller/flow:** Consumers cannot distinguish raw MLE/GPD extrapolation from guarded values, and `gpd_shape_xi` is not necessarily the fitted shape.
- **Grounded impact:** Stability guards materially change the reported tail estimate and fitted parameter without a quality flag or raw counterpart.
- **Minimum recommendation:** Return raw fit values plus a separate validity flag, or explicitly expose the constrained estimate and reason. Do not replace the formula result with an undisclosed historical-value floor.
- **Regression-test gap:** Tests check VaR ≤ ES and removal of an old cosmetic multiplier, but not raw-versus-clamped diagnostics or the `0.9*historical` floor.

#### QUANTCODE-019 — Bug / P2: tail-response cache omits portfolio weights

- **Evidence:** The 15-minute response cache key at `backend/app/api/analytics.py:2222` contains tickers, dates, confidence, and threshold, but not weights. The cached response’s EVT block is computed from weight-dependent `port_ret` at lines 2226-2239.
- **Caller/flow:** Changing quantities/weights while keeping the ticker set and date window unchanged can serve the prior portfolio’s VaR/ES for up to 15 minutes. The dependence matrix is weight-independent, but the combined payload is not.
- **Grounded impact:** Tail risk can contradict the current portfolio immediately after a rebalance while appearing fresh.
- **Minimum recommendation:** Include a deterministic normalized-weight fingerprint in the key, or cache the dependence matrix separately and recompute the weighted EVT block.
- **Regression-test gap:** Cache tests vary lookback/tickers, not same-ticker/different-weight requests.

### P3

#### QUANTCODE-020 — Bug / P3: short backtests silently change requested windows without returning effective values

- **Evidence:** When history is short, `backend/app/services/backtest_service.py:49-51` silently replaces user `lookback_days` and `rebalance_freq_days`. The response at lines 179-195 does not report either effective value; the route reports only input-frame length at `backend/app/api/analytics.py:1777-1781`.
- **Caller/flow:** Reproduction requires comparing the same input with different requested windows; the result is not self-describing.
- **Grounded impact:** Users cannot reproduce the run or distinguish requested from executed parameters.
- **Minimum recommendation:** Return `lookback_days_used` and `rebalance_freq_days_used`, or reject the request instead of changing it.
- **Regression-test gap:** No test covers the fallback branch or effective-parameter response.

#### QUANTCODE-021 — Bug / P3: one-observation EWMA returns absolute return instead of an undefined/zero sample variance

- **Evidence:** `backend/app/services/volatility_service.py:98-99` special-cases `n == 1` as `abs(r[0]) * annualization_factor`. The multi-observation estimator at lines 101-110 is a weighted variance, for which one observation supplies no sample variance.
- **Caller/flow:** Direct helper use and GARCH’s short-history fallback can turn a single return’s size into a volatility estimate.
- **Grounded impact:** Larger absolute returns produce larger “volatility,” conflating return level with return dispersion.
- **Minimum recommendation:** Return zero only if the chosen zero-assumption is explicit, otherwise reject/flag insufficient observations; do not use `abs(mean)`.
- **Regression-test gap:** `backend/tests/test_coverage_quant_services.py:82-89` asserts that the one-value result is positive, cementing the wrong formula instead of testing an honest insufficiency contract.

#### QUANTCODE-022 — Bug / P3: indicator `lookback_days` is calendar days despite the API promising records

- **Evidence:** `/data/indicators/{ticker}` describes `lookback_days` as “Window of records to return” at `backend/app/api/data.py:47-55`. The service subtracts `pd.Timedelta(days=lookback_days)` at `backend/app/services/indicators_service.py:182-200` and returns every trading row in that calendar interval.
- **Caller/flow:** A 90-record request typically returns only the trading sessions inside 90 calendar days, not 90 records.
- **Grounded impact:** Payload length and any consumer expecting the documented record count vary with weekends/holidays.
- **Minimum recommendation:** Rename the parameter/wording to calendar lookback, or select the last N records after the end date.
- **Regression-test gap:** Tests only assert a lower bound and do not verify exact record-count semantics.

## 4. Bias, alignment, and contract table

| Area | Current contract | Audit conclusion |
|---|---|---|
| Shared portfolio returns | Union-indexed prices are forward/back-filled, then missing returns become zero (`analytics_engine.py:57-62`; `api/analytics.py:1329-1333`) | Incorrect observation contract; see `001`. |
| Adjusted prices/dividends | API price extraction prefers `adj_close` before close (`api/analytics.py:124-127`); DataService persists adjusted data | Return-based analytics receives split/dividend-adjusted prices when the shared route is used. Direct service callers can still pass raw close. |
| Annualization | 252 trading days is used consistently across regime, volatility, optimization, backtest, Monte Carlo, and analytics | No cross-service annualization inconsistency found. Calendar-day indicator lookback is separate and documented in `022`. |
| Backtest time split | Training is `[t-lookback, t)` and test begins at `t` (`backtest_service.py:76-108`) | No direct train/test look-ahead found; weight drift, cost validation, survivorship, and effective-window contracts fail as documented. |
| Backtest costs/dividends | Strategy turnover cost exists; adjusted returns can include distributions; benchmark receives no cost | Cost math is one-way, but negative bps is accepted and fixed weights hide daily turnover (`002`, `003`). |
| Backtest universe | Current DB/request tickers for all history | Fixed-current-universe survivor/selection bias (`004`). |
| Optimization | Long-only, fully invested sample-moment optimizers; no portfolio-return execution simulation | Feasibility/weight invariants look sound. Solver errors are not strategy-consistent (`010`), and quant endpoints block the loop (`011`). |
| Monte Carlo | Historical daily simple returns, 252-day annualization, deterministic seeded paths | Determinism and percentile monotonicity are covered. Long-horizon aggregate memory and requested-path semantics are unsafe (`005`). |
| Tail risk | Loss convention `-return`; 252 is not annualized in EVT output | Confidence naming, constant inputs, constrained-fit disclosure, and weight-aware caching are defective (`016`-`019`). |
| Cointegration | Series align by index before price tests; cache includes p-value/spread flag | Pair alignment is sound. Lookback identity and unbounded pair workload are defective (`012`, `013`). |
| Correlation | Same-day pairwise rolling Pearson correlations, then average | Threshold/flag consistency is covered. Performance and request bounds are defective (`013`). |
| Regime | Trailing 21-day return/volatility features; crash veto changes display only | No direct future feature leakage found. Display state and posterior fields are inconsistent on veto days (`015`). |
| Factor exposure | Position regressions use active history; portfolio regression uses any-active history | Position and portfolio alignment differ (`007`); risk score omits actual weights from factor leg (`006`). |
| Benchmark | Adjusted-close simple returns after window slicing | Current/recent spans work; historical end anchoring is wrong (`014`). Slicing also intentionally omits the first in-window return because its prior close is outside the slice. |
| Technical indicators | Raw OHLCV indicators after numeric coercion/fill | Calendar-vs-record contract differs (`022`). Vendor adjustment/model choices were not judged. |
| Quantitative screener | Current fundamental/ratio snapshot with isolated universe and request-size cache keys | No service-level correctness finding in audited contracts; provider data quality remains outside this audit. |

## 5. Test gaps

The 114 focused tests passing does not cover the following acceptance conditions:

1. **P1 proof set**
   - Drift-correct walk-forward weights and cost only at scheduled boundaries (`002`).
   - Rejection of negative/non-finite backtest costs (`003`).
   - Explicit point-in-time/survivor disclosure or membership fixture (`004`).
   - Aggregate Monte Carlo memory and actual allocation after long-horizon path scaling (`005`).
   - Multi-asset missing-price masking across portfolio metrics and all wide-return consumers (`001`).

2. **P2 proof set**
   - Same-weight risk score, pre-listing multi-asset beta, unknown model labels, and positive stress semantics (`006`-`009`).
   - Event-loop heartbeat tests for optimize/backtest/Monte Carlo (`011`).
   - Coint cache separation by lookback, bounded pairwise universe, and historical benchmark end anchoring (`012`-`014`).
   - Regime override/probability agreement, confidence-neutral tail fields, constant tail inputs, raw-vs-constrained EVT diagnostics, and weight-aware tail cache (`015`-`019`).

3. **P3 proof set**
   - Returned effective backtest windows, one-observation volatility insufficiency, and exact indicator record semantics (`020`-`022`).

Current tests are particularly weak where they assert implementation artifacts rather than financial invariants: fixed inter-rebalance weights and a positive one-observation “volatility” are both currently pinned as expected behavior.

## 6. Explicit clean areas and limitations

### Clean areas confirmed by source/tests

- No P0 issue was found.
- `screener_service.py` is clean within the audited contract: ratio units, full-universe filtering before result cap, BSE ticker mapping, debt enforcement, universe-aware caching, and larger-cap slicing are covered.
- HRP/CVXPY paths enforce long-only, normalized weights; the tested min-vol/tangency/CVaR feasibility identities hold. No library-equivalence judgment is made.
- Concentration uses HHI, `N_eff = 1/HHI`, normalized diversification, and Gini coherently; a single holding renders 0% diversification.
- Walk-forward slices do not directly include the test row in training.
- Current adjusted-price extraction prefers adjusted close, so standard API return analytics include split/dividend adjustments when present.
- Cointegration aligns two indexed price series before tests, uses a one-way cache parameter set, bounds its in-memory TTL, and preserves count/list invariants after half-life filtering.
- The correlation service’s alert and regime-break flag share one threshold comparison; unavailable rolling correlations remain NaN rather than being silently replaced with a valid zero.
- Regime features are trailing; HMM and posterior code is threaded, and timezone-naive portfolio/regime indices are normalized before intersection.
- Tail services reject truly short overlap/history rather than fabricating fitted parameters.
- MC path percentiles are monotonic, seeded runs are deterministic, and the tested bootstrap path is chained correctly.

### Limitations

- This is code/contract auditing, not a model-validation study. GARCH/HMM/EGARCH/EVT/Student-t/Black-Litterman estimator choices and external library-equivalence claims were intentionally not adjudicated.
- No live market/vendor dataset was used to quantify long-run empirical bias; findings are static-contract or deterministic synthetic results.
- Provider retrieval, fundamental correctness, and market microstructure services were excluded.
- Out-of-scope instrument behavior was not judged.
- No backend code was modified, so findings are recommendations only; the focused tests and Ruff gate characterize the current tree, not a remediated tree.
