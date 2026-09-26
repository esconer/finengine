# 02 — Portfolio Performance & Attribution Review

**Artifact:** `C:\es\others things\finengine-portfolio-ai-context v5.json` (876 KB, `export_id portfolio-4b78905b588c`, `schema_version 2.0`, `base_currency INR`, 14 holdings)
**Sections owned:** `concentration`, `risk_contribution`, `factor_exposure`, `optimization`, `regime`, `dashboard` component subtree
**Ground truth:** `backend/app/api/analytics.py`, `backend/app/services/analytics_engine.py`, `backend/app/services/optimization_service.py`, `backend/app/services/regime_service.py`, `backend/app/utils/{holdings,allocations}.py`, `backend/app/services/ai_context_service.py`

---

## Verdict

Four of my five sections are arithmetically sound and unusually well disclosed. `concentration` is exactly right to the last published digit (HHI, N_eff, top-1/3/5/10, Gini, and a diversification score that is a genuine concentration index — `(1−HHI)/(1−1/N)·100 = 98.41 → 98.4` — **not** `100 − risk_score`, which would have been 91.38). `risk_contribution` closes to 1.0 within its own declared rounding, every one of its 14 sector rollups reconciles exactly against the leg shares, all 28 shares are positive, and the shares are Cauchy–Schwarz feasible (implied per-asset vol bounds 1.00 %–28.20 %, all plausible) — so there is no hidden negative variance contribution. `regime` is internally consistent and I found **no** bull/low-vol-vs-HIGH-risk contradiction; its transition matrix is honestly labelled a configured prior rather than a fitted matrix, and its 0.24-vs-0.65 R² divergence from `factor_exposure` is fully disclosed in prose. The 14 published weights are bit-identical in all four places they appear, sum to exactly 1.0, and are provably current market-value weights (`weight == market_value/total_value` to 0.0) on a book that has drifted up to 5.36 pp from cost basis, with that basis declared three times. **But `optimization` is broken in a way that moves money**: the HRP branch of the optimizer computes `expected_annual_return`, `expected_annual_volatility` and `expected_sharpe` against a **mis-permuted weight vector**, because `_hrp_weights` returns its Series in scipy-linkage leaf order and `optimize()` rebinds `assets` to that order but never reindexes `mu` or `cov`. I proved it by running the repo's own code: the published Sharpe comes out at **+0.698 when the actual Sharpe of the published weights is −0.375** — opposite sign. So three of the four numbers an AI would quote from the optimizer section are not the moments of the optimizer's own recommendation. Everything else in this review is P1/P2 disclosure and hygiene.

---

## Findings by severity

### PA-1 · **P0** · `sections.optimization.data.expected_annual_return` / `.expected_annual_volatility` / `.expected_sharpe`

**Observed**
```
optimization.data.strategy                    = "hrp"
optimization.data.solver                      = "hierarchical-bisection"
optimization.data.expected_annual_return      = 0.2602
optimization.data.expected_annual_volatility  = 0.1772
optimization.data.expected_sharpe             = 1.356
optimization.data.weights                     = {CIPLA.NS: 0.128433, ..., MAFANG.NS: 0.148616, ...}
```

**Expected** — `expected_annual_return = μ'w`, `expected_annual_volatility = sqrt(w'Σw)`, `expected_sharpe = (ret−rf)/vol`, all evaluated with **`w` in `returns.columns` order** (the same order `μ` and `Σ` are built in), and keyed to the published ticker names.

The HRP branch violates this. `_hrp_weights` ends with
```python
labels = corr.index[ordered].tolist()      # scipy linkage LEAF order
...
weights = pd.Series(1.0, index=labels)
return weights / weights.sum()             # index == leaf order
```
and `optimize()` does
```python
mu, cov, assets = _as_matrices(returns)   # mu/cov in returns.columns order
if strategy == "hrp":
    weights_series = _hrp_weights(returns)
    assets = list(weights_series.index)   # rebinds `assets` ONLY
    w_vec = weights_series.values          # leaf order
...
exp_ret = float(mu @ w_vec)                                  # MISALIGNED
exp_vol = float(np.sqrt(max(0.0, w_vec @ cov @ w_vec)))       # MISALIGNED
```

**Recomputation evidence** — I ran the repo's actual `optimize()` on a seeded 14-asset / 400-obs frame:
```
returns.columns order : ['A00','A01',...,'A13']
hrp leaf order        : ['A03','A10','A11','A08','A07','A09','A02','A05','A06','A13','A01','A12','A00','A04']
orders identical?     : False

published expected_annual_return     = 0.0899
recomputed from published weights    = 0.000860   (mu . w, column order)     error +0.0890
published expected_annual_volatility = 0.1001
recomputed from published weights    = 0.051108                             error +0.0490
published expected_sharpe            = 0.6981
recomputed sharpe from weights       = -0.374507   <-- OPPOSITE SIGN
```
Magnitude across 400 realistic synthetic 14-asset / 170-obs books (annualized vol 10–42 %, mean −10 %…+60 %):
```
leaf order == column order in 0/400 trials
expected_annual_return error:    MAE 0.1667   p90 |err| 0.3442   max |err| 0.8374
expected_annual_volatility err: MAE 0.0837   p90 |err| 0.1372   max |err| 0.2410
```
Volatility survives roughly (it is second-order in `w`); the **expected return does not** — it is a first-order dot product of two differently-ordered vectors.

**Root cause** — `backend/app/services/optimization_service.py:302` (`mu, cov, assets = _as_matrices(returns)` fixes the column order) + `:304-306` (only `assets` is rebound to leaf order) + `:320-321` (`mu @ w_vec`, `w_vec @ cov @ w_vec`). Test gap: `backend/tests/test_p01_hrp.py:38` does `raw.loc[w.index]` before comparing — the test author *knew* the order differs and reindexed; the production path did not.

**Impact on this export** — `expected_annual_return = 0.2602`, `expected_annual_volatility = 0.1772`, `expected_sharpe = 1.356` are **not** the moments of `optimization.data.weights`. Any consumer that recomputes them from the published weights gets a different answer. (The weights themselves are correct: sum 0.999998, min leg 0.022209, all non-negative — items (a) and (b) of the brief both PASS.)

**Confidence** — High. Reproduced by executing `app.services.optimization_service.optimize` unchanged.

---

### PA-2 · **P1** · `sections.optimization.data` (whole section) — no current-portfolio baseline

**Observed** — The section publishes `expected_annual_return`, `expected_annual_volatility`, `expected_sharpe` and `current_weights`, but **no** `current_expected_return` / `current_expected_volatility` / `current_sharpe` on the same 170-row sample. The only other Sharpe numbers in the artifact are on different samples: `tear_sheet.metrics.sharpe = 3.4876` (39 obs), `tear_sheet.full_history.metrics.sharpe = 0.969056` (2486 obs).

**Expected** — A mean-variance/HRP recommendation is only actionable if the incumbent book is scored on the *same* μ and Σ. The brief's P0 check (d) — "the reported Sharpe must be ≥ the current Sharpe unless constraints bind" — is **unanswerable from this artifact**.

Compounding it: `strategy = "hrp"` is a risk-based (inverse-cluster-variance) allocator that never maximizes Sharpe, yet `expected_sharpe` is emitted under the same field name used for `max_sharpe`, with no field saying "Sharpe was not the objective".

**Root cause** — `backend/app/services/optimization_service.py:323-330` emits identical ex-post diagnostics for every strategy; `backend/app/api/analytics.py:5962-5998` assembles the payload without a current-weight companion.

**Confidence** — High on the gap, High on the HRP-does-not-maximize-Sharpe point.

---

### PA-3 · **P1** · `sections.factor_exposure.data.history_coverage.model_observation_count` (= 174)

**Observed**
```
factor_exposure.r_squared                        = 0.6511
factor_exposure.adjusted_r_squared               = 0.649
factor_exposure.history_coverage.model_observation_count = 174
factor_exposure.history_coverage.benchmark_overlap_observations = 167   <-- same block
factor_exposure.model_window.days                = 174
factor_exposure.full_history.observation_count   = 174
```

**Expected** — `model_observation_count` should be the number of observations the OLS actually consumed. The engine fits on `returns.index ∩ benchmark.index` (`analytics_engine.py:1729-1732`, then `:1780-1781` narrows further to "any constituent traded"). That is the 167, not the 174 price-frame return rows.

**Recomputation evidence** — with one regressor, `adjR² = 1 − (1−R²)(n−1)/(n−2)`. Solving against the published pair:
```
 n=165..172  ->  round4 = 0.6490   MATCH published 0.6490
 n=173       ->  round4 = 0.6491
 n=174       ->  0.649072 -> 0.6491   <-- published count, INCONSISTENT with the R2 pair it ships with
 n=160..164  ->  0.6489
```
The consistent set is `[165…172]`. **174 is not in it; 167 is.** So `model_observation_count = 174` is provably not the regression sample, and it sits 7 rows above the true count published three keys away in the same object.

Aggravating: the sibling `dashboard.components.risk_score.data` publishes the **same field name** with `model_observation_count_scope = "active_benchmark_overlap_return_rows"` and the correct value (36). Two different units, one field name, and the `factor_exposure` instance is the wrong one.

**Root cause** — `backend/app/api/analytics.py:3349-3362` builds the evidence block from `model_returns = price_data.pct_change().iloc[1:]` (price-frame rows) rather than from the benchmark-overlap mask the regression actually uses. Compare the correct pattern at `backend/app/api/analytics.py:4537-4546`, which explicitly sets `model_observation_count_scope`.

**Confidence** — High. The df arithmetic is decisive given 4-dp `r_squared` and 4-dp `adjusted_r_squared`.

---

### PA-4 · **P1** · `dashboard.components.summary.data.sharpe_ratio` vs `sections.tear_sheet.data.metrics.sharpe`

**Observed**
```
dashboard.summary.sharpe_ratio          = 3.4856030104352476
tear_sheet.metrics.sharpe               = 3.487604          (delta 2.001e-3, 0.057 %)
dashboard.summary.realized_volatility   = 0.09823756813755412
tear_sheet.metrics.volatility           = 0.098238          (delta 4.319e-7 — rounding only)
both: observation_count = 39, annualized = true, window 2026-08-04..2026-09-25
implied Sharpe numerator (ann_ret − rf):  summary 0.342417163   tear_sheet 0.342615242
```

**Expected** — One portfolio, one window, one observation count, one `annualized` flag ⇒ one Sharpe. The volatility agrees to 1e-7 but the Sharpe's **numerator** differs by 1.98e-4, i.e. the two routes build the same daily return *variance* from a slightly different daily return *series* (the tear_sheet path is the quantstats suite over adj-close; the summary path is `analytics_engine.calculate_portfolio_metrics` over `aggregate_active_returns`).

**Root cause** — two independent estimators with no shared contract. `backend/app/services/ai_context_service.py:1206` (`_SUMMARY_CANONICAL_SOURCES`) links only `forecast_volatility` and `liquidity_score` from siblings; `sharpe_ratio` and `realized_volatility` are never cross-checked. Aggravating: `tear_sheet.data.metrics` publishes **no risk-free rate**, so a reader cannot reconcile 3.4876 against 3.4856 at all — the `risk_free_rate` used by the summary path comes from `analytics_engine.py:199` (`settings.risk_free_rate`, default 2 %) and is not published on the summary either.

**Confidence** — High on the numbers; Medium on the exact mechanism (no rf is published on the tear_sheet side to confirm which leg moved).

---

### PA-5 · **P2** · `sections.optimization.coverage` vs `.data.history_window`

**Observed** — `coverage.complete = true`, `coverage.coverage_ratio = 1.0`, `coverage.covered_tickers` = all 14, `calculation_universe` = all 14, `data_unavailable_tickers = []`. But `history_window.return_observations = 170` over a window whose neighbours measure 251 rows (`risk_contribution.full_history.observation_count = 251` over the same start date 2025-09-29). `history_window.per_ticker_return_observations` reports **all 14 legs at exactly 170**, so the reader cannot see which leg caused the 32 % loss of the sample.

**Expected** — Either the pre-dropna per-ticker counts, or a published `rows_dropped_incomplete_case`, so the reader can judge a 170-row covariance estimate for a 14-asset book that had ~235 available rows. `minimum_observations_required = 30` and `meets_minimum_sample = true` are published, and 170 > 14 is fine for rank, so this is disclosure, not a math error.

**Root cause** — `backend/app/api/analytics.py:5929` (`returns_df = returns_df.dropna(how="any")`) followed by `_history_window(start, end, returns_df)` at `:5949`/`:5959`, which can only report the post-dropna counts. `NIFTYIETF.NS` has 177 return rows over the year (`risk_contribution.data.full_history.per_ticker_return_observations.NIFTYIETF.NS = 177`) versus 247–249 for the rest — that single late-listed leg sets the effective sample for the whole optimizer.

**Confidence** — High.

---

### PA-6 · **P2** · undisclosed aggregation rule behind every portfolio-level return in the artifact

**Observed** — the measured portfolio return series is **not** a fixed-weight return of the published book. `aggregate_active_returns` renormalises the surviving weights on every partial day:
```python
active_weight = active.mul(weight_frame, axis=1).sum(axis=1)
numerator     = clean.where(active, 0.0).mul(weight_frame, axis=1).sum(axis=1)
portfolio     = numerator.loc[active_weight > 0.0] / active_weight.loc[active_weight > 0.0]
```
Materiality in this export: `NIFTYIETF.NS` has 177 of 251 return rows in the `risk_contribution` window (**29 % of rows**) and 102 of 174 in the `factor_exposure` window (**41 %**). On those days the "portfolio" is a 13-leg book with redistributed weights.

This feeds `factor_exposure.portfolio.{alpha, market}` and `r_squared` (`analytics_engine.py:1775-1786`), `risk_contribution.portfolio_var_95_daily` / `portfolio_cvar_95_daily` (`analytics.py:5252` → `:5724-5824`), and the `tear_sheet` metric suite. The artifact never states the rule — scanning every string in the 876 KB for `aggregate_active` / `active positive` / `renormalis* of weights` / `composition` yields **zero** relevant hits (the 7 `renormal` hits are the risk-score weighting, the regime `historical_days_pct`, and the india_flows coverage notes).

**Expected** — A field such as `portfolio_return_aggregation: "active_weight_renormalized_per_day"` beside `basis` / `calculation_basis`. Without it, `factor_exposure.portfolio.market = 1.0706` reads as "the beta of the published 14-leg book" when it is the beta of a book whose composition changes day to day.

**Root cause** — `backend/app/services/analytics_engine.py:73-77`; consumers at `analytics_engine.py:1775-1786` and `backend/app/api/analytics.py:5252`.

**Confidence** — High on the mechanism, High that it is undisclosed.

---

### PA-7 · **P2** · `sections.risk_contribution` — covariance never published, PSD unverifiable, no eigenvalue repair

**Observed** — The section publishes 28 risk shares, `portfolio_volatility_annualized = 0.1789`, `portfolio_var_95_daily = -0.018244`, `portfolio_cvar_95_daily = -0.025175`, but **no covariance matrix and no correlation matrix anywhere in the artifact**. `risk_studio` publishes only `current_avg_correlation = 0.1404` and a *tail-dependence* matrix (`tail_dependence.data.tail_dependence_matrix`), which is a different object.

**Expected** — Either publish Σ, or state that it is withheld. The code has no PSD guarantee:
```python
cov = returns_df[vol_assets].cov(min_periods=2) * 252     # pandas pairwise-complete -> not PSD in general
sigma_p = float(np.sqrt(max(0.0, vol_w @ cov_values @ vol_w)))   # negative variance silently -> 0
```
`max(0.0, ·)` converts a negative quadratic form into `sigma_p = 0`, which then falls into `vol_rc = {}` while `excluded_assets.volatility` stays `[]` and `model_used_tickers.volatility` still lists all 14 legs — an internally inconsistent empty state. There is no eigenvalue flooring or nearest-PSD repair.

**I could not falsify the published numbers.** Evidence they are sound:
- `positions.volatility` sums to 0.999998, `positions.cvar_tail` to 0.999999 — inside their own declared `rounding_decimals: 6`.
- All 28 shares strictly positive; all 14 sector rollups reconcile **exactly** against the leg shares under the sector map implied by `concentration.by_sector` (diff = 0.00e+00 for all 14, both models).
- `portfolio_var_95_daily (-0.018244) < portfolio_cvar_95_daily (-0.025175)`, and CVaR/σ_daily = 0.025175 / 0.011271 = **2.233** — a plausible fat-tail ratio.
- Cauchy–Schwarz feasibility `σ_i ≥ σ_p · share_i / w_i` holds for all 14 legs with implied bounds **[1.00 %, 28.20 %]** annualized (MOTILALOFS ≥ 28.20 %, REDINGTON ≥ 26.58 %, MOTHERSON ≥ 25.87 %, MAFANG ≥ 1.00 %) — no impossible vol, hence no negative variance contribution.
- The published unit is **component** (`w_i(Σw)_i/σ²`), not marginal, and `contribution_basis.unit = "fraction_of_portfolio_risk"` plus the `normalization` string state this correctly.

**Root cause** — `backend/app/api/analytics.py:5693` (pairwise `cov`), `:5707` (`cov` rebuild), `:5711` (`sqrt(max(0.0, …))` mask with no PSD guard).

**Confidence** — High that this is a verifiability/robustness gap; no evidence of a wrong published number.

---

### PA-8 · **P2** · stale route docstring for the Euler normalisation

**Observed** — `backend/app/api/analytics.py:5577` documents
```
volatility model : RC_i = w_i * (Sigma w)_i / sigma_p   (exact, analytic)
```
but the code publishes `w_i (Σw)_i / σ²`: `contrib = vol_w * mrc / sigma_p` (`:5715`) is then divided by `contrib.sum()` (`:5717`), and `Σ_i w_i(Σw)_i = σ²`, so `contrib.sum() = σ_p` and the published value is the `/σ²` form.

**Expected** — The two forms differ by a factor of σ_p. Demonstrated on a 2-leg book:
```
raw Euler RC (return units) = [0.10392305 0.10392305]  sum = 0.207846  == sigma
normalised to 1 (what the artifact publishes) = [0.5 0.5]
```
The `/σ` form sums to **σ**, not to 1.

**The published payload is correct** — `contribution_basis.unit` and `.normalization` describe the `/σ²` share and the sums verify. Only the docstring is wrong. Fix the comment or the code; as written a reader of the docstring would expect a sum of 0.1789 and find 1.0.

**Root cause** — `backend/app/api/analytics.py:5577` (docstring) vs `:5715-5717` (code).

**Confidence** — High.

---

### PA-9 · **P2** · `sections.regime` — no scope on the two realtime vol fields

**Observed** — `regime.realtime_ewma_vol = 0.1005`, `regime.realtime_parkinson_vol = 0.084`, and `units` declares them only as `"annualized_fraction"`. They are in fact computed from the **benchmark** OHLCV (`regime_service.py:165`, `:176` operate on `bench_data` / `ret_1d` derived from the benchmark close), i.e. ^NSEI — not the portfolio.

**Expected** — `"scope": "benchmark_^NSEI"` in the `units` block, as the block already does for 20 other fields. Without it, a reader comparing 0.1005 against `tear_sheet.metrics.volatility = 0.098238` (39-day, portfolio) or `summary.instrument_volatility = 0.197796` (175-day, portfolio) or `risk_contribution.portfolio_volatility_annualized = 0.1789` (251-day, portfolio) has four candidate "portfolio vols" plus these two unscoped ones, and no way to tell which instrument each describes. The adjacent `regime.benchmark` block (`symbol: "^NSEI"`) makes it inferable, hence P2 not P1.

**Root cause** — `backend/app/services/regime_service.py:298-299` (emits the values) and `:465-473` (`_regime_metadata` unit table, no scope entry).

**Confidence** — High.

---

### PA-10 · **P2** · `dashboard.components.risk_score` — "LOW" level next to a 30/30 leg and a HIGH-risk alert

**Observed**
```
components = {concentration: 8.6, volatility: 9.8, correlation: 5.3, factor_risk: 30, market_risk: 9.8}
alerts     = ["High unexplained risk (low R-squared: 0.24)"]
overall_score = 13.7      risk_level = "LOW"
```
The weighted mean is arithmetically faithful to the published formula:
```
0.20*8.6 + 0.25*9.8 + 0.20*5.3 + 0.25*30 + 0.10*9.8 = 13.71  -> 13.7  ✓
correlation leg: min(30, 50*max(0, 0.1059)) = 5.295 -> 5.3    ✓
volatility leg:  100 * 0.0982376 = 9.82      -> 9.8          ✓
concentration:  HHI 0.0862 * 100 = 8.62     -> 8.6          ✓
```
So this is **not** a math error. It is a presentation contradiction: the factor leg is pegged at the 30/30 maximum and the section's own alert says "High unexplained risk", yet the published level reads "LOW" — because four of five legs cluster at 5–10 and the overall is effectively the volatility leg. The `methodology` string does declare the weights and the 0–30 scale, so a careful reader can reconstruct it. Flagged because a single-word risk verdict is what a dashboard consumer actually reads.

**Root cause** — presentation, in `analytics_engine.risk_scoring` (banding of the weighted mean), surfaced at `dashboard.components.risk_score.data.risk_level`.

**Confidence** — High on the arithmetic; this is a UX finding, not a correctness one.

---

### PA-11 · **P2** · `concentration` zero-state publishes `diversification_ratio = 1.0` for an empty book

**Observed (code path, not exercised by this export — 14 holdings present)** — both zero-state returns set the ratio to fully-diversified:
```python
# backend/app/api/analytics.py:3489-3490   (no positions)
"diversification_score": 0.0,
"diversification_ratio": 1.0,
# backend/app/services/analytics_engine.py:1893-1894  (_empty_concentration)
"diversification_score": 0.0,
"diversification_ratio": 1.0,
```
and for N = 1, `analytics_engine.py:422` computes `diversification_ratio = N_eff/N = 1/1 = 1.0` — again "perfectly diversified" for a single holding.

**Expected** — The repo invariant (`AGENTS.md`, Quantitative & Terminal UI Invariants) pins only `diversification_score` to `0` for N ≤ 1, and `analytics_engine.py:421` does honour it (`if n_assets > 1 else 0.0`) — verified. But the companion `diversification_ratio` renders 1.0 = "maximally diversified" in the same zero/single states. Extend the invariant to cover it.

**Root cause** — `backend/app/api/analytics.py:3490`; `backend/app/services/analytics_engine.py:1894` and `:422`.

**Confidence** — High (code read). Not a finding against this export.

---

## Cross-section agreement (brief item 8)

Every window is declared; **no section measures a window silently**, so there is no P0 here. But the artifact contains **seven distinct measurement windows** for the same book:

| section / leg | start | end | n | unit / basis |
|---|---|---|---|---|
| `tear_sheet` realized | 2026-08-04 | 2026-09-25 | 39 | `holding_window_aligned_return_rows` |
| `tear_sheet` full_history | 2016-09-12 | 2026-09-25 | 2486 | `full_exchange_history_current_weights` |
| `risk_contribution` full_history | 2025-09-29 | 2026-09-25 | 251 | `full_exchange_history_current_weights` |
| `factor_exposure` model | 2026-01-20 | 2026-09-25 | 174 | `model_return_observations` (true regression n = 167, see PA-3) |
| `optimization` history_window | 2025-09-29 | 2026-09-22 | 170 | complete-case return rows |
| `regime` model | 2023-09-22 | 2026-09-24 | 719 | benchmark HMM, 1100-day lookback |
| `regime` portfolio_in_current_regime | (pool 2026-08-03) | 2026-09-26 | 19 | `conditional_regime_return_days` |
| `dashboard.risk_score` factor leg | 2026-08-04 | 2026-09-24 | 36 | `active_benchmark_overlap_return_rows` |
| `dashboard.summary` instrument_risk | 2026-01-19 | 2026-09-25 | 175 | `full_exchange_history_current_weights` |

`as_of` values: `tear_sheet` / `risk_contribution` / `factor_exposure` / `realized_risk` / `forecast_risk` / `volatility_sizing` / `monte_carlo` = 2026-09-25 · `regime` = 2026-09-24 · `optimization` = **2026-09-22** · `concentration` / `liquidity` / `stress_testing` = `null`.

Notable but disclosed: `optimization` is **3 calendar days staler** than the rest of the book, yet its `trades_required` are diffed against `current_weights` measured at 2026-09-26 — the trade list therefore mixes a 2026-09-22 risk model with 2026-09-26 market values. That is visible only via `as_of` + `history_window.latest_observation`; nothing states it. P2.

**No lookahead bias found in `optimization`.** `end = datetime.now()` = 2026-09-26, `start` = −365 d; the sample's last observation is 2026-09-22 = the section's own `as_of`, i.e. nothing after `as_of` enters the fit.

---

## Sections that are clean — do not re-litigate

**`concentration` — CLEAN, exact to the last published digit.**
```
N = 14
HHI   published 0.0862     recomputed sum(w^2) = 0.0861579927  -> 4dp 0.0862  OK
N_eff published 11.61      recomputed 1/HHI     = 11.6065842    -> 2dp 11.61   OK
top_1 0.1367975741430184  diff +0.000e+00
top_3 0.36303079660472    diff +0.000e+00
top_5 0.522359202714934   diff +0.000e+00
top_10 0.8720992878026941 diff +0.000e+00
gini  published 0.252      recomputed 0.251659                 -> 3dp 0.252   OK
by_sector sum = 1.0 exactly; by_sector_rounding_residual = 0
```
The repo's two concentration invariants both hold:
- **Diversification comes from a true concentration index, not an inverted risk score.** `diversification_score = ((1−HHI)/(1−1/N))·100 = 98.4138 → 98.4` ✓. The forbidden `100 − HHI·100 = 91.3842` and `100 − HHI·100·N = −20.62` are both off by 7.0 and 119.0 respectively — **not** what was published.
- **N ≤ 1 renders 0 % diversification.** `backend/app/services/analytics_engine.py:421` — `if n_assets > 1 else 0.0`. Verified: N=1 → HHI=1.0, the `(1−HHI)/(1−1/N)` form is `0/0`, and the guard returns `0.0` instead of dividing by zero.
- `diversification_ratio = N_eff/N = 0.829 → 0.83` ✓ (not `1−Gini = 0.748`, not `1−HHI = 0.914`).
- `top_10` has a `len < 10 → 1.0` fallback (`analytics_engine.py:411`); not exercised at N=14.

**Weights — CLEAN.** `tear_sheet.data.holdings`, `concentration.data.by_weight`, `dashboard.components.concentration.data.by_weight` and `portfolio.data.positions[*].weight` are **bit-identical dicts** (`==` → `True`, zero diffs). `optimization.current_weights` is the exact 4-dp round of each (zero mismatches; published total 1.0001, residual −0.0001 declared). Sum of `tear_sheet.holdings` = **exactly 1.0** (`sum − 1 = 0.0`), all 14 > 0 (min 0.024093, max 0.136798). And they are provably **current market-value** weights, not entry weights: `max |weight − market_value/total_value| = 0.0`. The book **has** drifted from cost basis — MOTHERSON 0.083179 → 0.136798 (**+5.36 pp**), JKIL 0.10777 → 0.065154 (−4.26 pp), ARROWGREEN +2.21 pp — and the basis is declared in three places (`concentration.sector_weight_basis = "market_value_weights_normalized_to_100_percent"`, `tear_sheet.calculation_basis = {"realized": "holding_truthed_current_composition", "full_history": "hypothetical_current_weights"}`, `full_history.basis = "full_exchange_history_current_weights"`). Nothing misleading here.

**`dashboard` component subtree — CLEAN on copy fidelity.** A recursive deep-compare of all 11 components against their source sections returns **0 diffs** for the 9 that are supposed to be copies: `portfolio`, `realized_risk`, `forecast_risk`, `factor_exposure`, `concentration`, `liquidity`, `regime`, `risk_contribution` (and `summary`'s own `history_coverage` fields that mirror siblings). `component_as_of` matches each component's own `as_of` for all 9 that declare one (`concentration` and `liquidity` are `null` in both places). `summary` and `performance_history` are different endpoints rather than copies — of the 10 values `summary` re-publishes from siblings, 9 match and 1 does not (PA-4).

**`regime` — CLEAN, and the hypothesised contradiction is NOT present.** I looked specifically for a "bull/low-vol regime beside a HIGH risk / 30-30 score" and it is not there. `current_regime = "crisis"` at a 99.9993 % filtered posterior — and the label is assigned by **sorting states on `ann_ret`** (`regime_service.py:48-62`), so "crisis" is a low-*return* state, not a high-vol one. `states[0].ann_vol = 0.1124` is mid-pack; the fitted vol ordering is calm 0.1096 < crisis 0.1124 < bull 0.1965, so a crisis label carries no high-vol implication. Verified internally: `regime_probabilities` total 99.9999 with residual published; all three transition rows sum to exactly 100; `stability_pct = 96.7` is consistent with `recent_history_self_transition_pct = 96.6387` over 119 transitions (4 changes); `current_regime_matches_posterior_argmax = true`; `label_overrides.crash_veto_days = 0` with `crash_veto_threshold = -0.1` declared in `fraction_log_return_21d` units and honestly reported as not firing. The transition matrix is explicitly labelled `transition_matrix_provenance.source = "configured_sticky_prior"`, `estimated: false`, `read_this_as: "model prior; not a fitted transition matrix"` — genuinely honest. The conditional portfolio block correctly **refuses** to annualize at `days = 19 < minimum_observations_required = 30` (`ann_ret`/`ann_vol` = `null`). The `risk_score` R² of 0.2391 vs `factor_exposure` R² of 0.6511 is **not** a contradiction: it is explained in prose at `analytics.py:4252-4261` and carried in the payload as `risk_score.data.factor_model.note` — *"factor_exposure publishes the same model over full exchange history… compare the two only through this block's basis and window, never by their values alone"* — with `model_window` and `model_observation_count` published alongside. Only the vol-scope omission (PA-9) stands.

**`factor_exposure` — mostly clean.** The benchmark series is a genuine **return** series, not a price level divided by 1000: the engine's guard is `if (benchmark_data.abs() > 1.0).any(): pct_change()` (`analytics_engine.py:351-352`, mirrored at `analytics.py:3376-3377`), and ^NSEI daily returns can never exceed 1.0, so the branch is a no-op here. Betas span 0.4514 (NTPC) to 1.8565 (MOTILALOFS) with MAFANG at −0.0837 — a price/1000 or level-as-return bug would have produced absurd magnitudes, and none appear. `annualized_alpha` is a hard-coded ×252 (verified: per-position ratios 250.0–253.125, all 252 within the 6-dp alpha rounding), and the portfolio `Σw_i·α_i = 0.001944` vs published `0.002042` (Δ 9.8e-5) is explained by per-asset vs portfolio sample masks. SEs/t-stats use `cov_type="HAC", maxlags=5` with a non-HAC fallback — defensible, though **no t-stat, SE, or residual variance is published at all**, so the brief's dof check is unanswerable from the artifact (P2, folded into PA-3's family). `data_range` (`2026-01-17…2026-09-26`) is the *requested* range, identical to `full_history.requested_window`, while the measured range is `model_window` (`2026-01-20…2026-09-25`) — a field name that reads as the measured range but is not (`analytics.py:3452`). P2.

---

## Ranked summary

| # | ID | Sev | Area | One-liner |
|---|---|---|---|---|
| 1 | PA-1 | **P0** | `optimization` | `expected_annual_return` / `_volatility` / `_sharpe` computed against a mis-permuted weight vector (HRP leaf order). Published Sharpe +0.698 vs actual −0.375 in the repro. |
| 2 | PA-2 | P1 | `optimization` | No current-portfolio objective value on the same sample → "is the optimizer better than what I hold?" is unanswerable; and `hrp` never maximizes Sharpe yet publishes `expected_sharpe`. |
| 3 | PA-3 | P1 | `factor_exposure` | `model_observation_count = 174` is provably not the regression sample (R²/adj-R² pair admits only n ∈ [165,172]; true n = 167, published 3 keys away). Same field name as `risk_score`'s, different unit. |
| 4 | PA-4 | P1 | `dashboard.summary` vs `tear_sheet` | Two Sharpes for the same 39-obs window (3.4856 vs 3.4876), unreconcilable because `tear_sheet.metrics` publishes no risk-free rate. |
| 5 | PA-5 | P2 | `optimization` | `coverage.complete = true` / `ratio 1.0` while the complete-case dropna cut 251 → 170 rows; per-ticker counts all 170 hide which leg caused it. |
| 6 | PA-6 | P2 | all portfolio-return sections | `aggregate_active_returns` renormalises weights on partial days (up to 41 % of rows); rule is nowhere disclosed. |
| 7 | PA-7 | P2 | `risk_contribution` | Σ never published → PSD unverifiable; `sqrt(max(0.0, w'Σw))` masks a negative variance; no eigenvalue repair. Published numbers themselves are sound. |
| 8 | PA-8 | P2 | `risk_contribution` | Route docstring documents `/sigma_p` where the code publishes `/sigma_p²`; the two differ by σ. |
| 9 | PA-9 | P2 | `regime` | `realtime_ewma_vol` / `realtime_parkinson_vol` are benchmark vols with no `scope` in `units`; five other "portfolio vol" numbers compete for the same reading. |
| 10 | PA-10 | P2 | `dashboard.risk_score` | `risk_level: "LOW"` next to a 30/30 `factor_risk` and a "High unexplained risk" alert. Arithmetically faithful; rhetorically wrong. |
| 11 | PA-11 | P2 | `concentration` | Zero-state and N=1 paths publish `diversification_ratio = 1.0` ("maximally diversified"). Not exercised here. |

**Sections with nothing wrong:** `concentration` (exact to the last digit, both repo invariants honoured), the weight vector (bit-identical in 4 places, provably current market-value on a drifted book, basis declared 3×), `risk_contribution`'s published arithmetic (closes to 1.0, all sector rollups reconcile exactly, CS-feasible, no negative contributions), and `regime` (no contradiction; the 0.24-vs-0.65 R² divergence is fully disclosed in prose). The `dashboard` copy layer is byte-clean for all 9 true copies.
