# 05 — ADVERSARIAL VERIFICATION of `finengine-portfolio-ai-context v5.json`

**Artifact** `C:\es\others things\finengine-portfolio-ai-context v5.json` · 876,445 bytes · `export_id portfolio-4b78905b588c` · `schema_version 2.0` · 17 sections · 14 holdings · `detail=summary`
**Generated** 2026-09-26T15:33:25Z → completed 15:33:44Z (19 s wall clock)
**Reviewer stance** falsification-first. Every finding below was reproduced by recomputation against the artifact, then traced to a `file:line`.

---

## VERDICT (read this first)

**No. An AI agent must not be allowed to act on this artifact, and the 47/47 green audit is actively misleading about that.** The audit tool is a *schema and arithmetic-consistency* checker, and this export is exceptionally good at both — it has clearly been hardened against exactly the class of defect the checker tests, and I could not break a single one of its 47 rules. But every one of the numbers I could not break turns out to be guarded by a disclosure convention that is **decorative rather than load-bearing**. Strip the prose and the file contains: a `cvar_forecast` that is the hardcoded literal `VaR × 2.06` (`analytics_engine.py:1568`) with the 95% level and the `sqrt(252)` never published anywhere in the section; an `achieved_volatility: 0.15` that is **algebraically incapable of differing from its own input** because `scale = target/rec_vol` and `achieved = rec_vol × scale` (`analytics_engine.py:1034,1053`); a 42.97% CAGR, Sharpe 3.49, Sortino 5.31 and Calmar 20.19 computed from **39 daily observations** and published `status: available` with an empty `warnings` array; two explicit long/short **trade instructions** emitted on pairs where the section's own diagnostic test disagrees, drawn from 91 tests at α=0.05 with no multiple-testing correction (4 hits — the null expectation is 4.55); 13 of 14 trade rows stamped `status: "executable"` inside a section whose own gate reads `execution_eligible: false`; a `crisis` regime at 99.9993% posterior while the portfolio's conditional return *in that regime* is **+1.72%**; and a 59% collapse in average pairwise correlation (0.1404 vs median 0.3408) labelled `alert_level: "NORMAL"` with the message "within normal historical bounds". The words `dividend`, `fee`, `tax`, `slippage`, `survivorship` and `corporate action` appear **zero times each** in an 876 KB file containing a five-year Monte Carlo projection and the entire return-statistics stack. Three different price snapshots coexist for the same 14 tickers, reconciled only by the four-word envelope string `snapshot_consistency: "best_effort"` over an empty envelope `warnings: []`. This is a well-formatted envelope around decisions that were never computed and goals that were invented. A model reading it will not be confused by a malformed field; it will be confidently, fluently, and wrongly persuaded — which is strictly worse.

---

## (a) THE CHECKER'S VERBATIM VERDICT

```
export       : C:\es\others things\finengine-portfolio-ai-context v5.json
envelope     : schema_version='2.0' export_id='portfolio-4b78905b588c' sections=17
rules        : 47 selected of 47

ENVELOPE  (18 rules)
  ENV-001      pass  schema_version equals '2.0'
  ENV-002      pass  generated_at <= completed_at
  ENV-003      pass  scope equals the sections keys, as a set AND in order
  ENV-004      pass  every section.status is in {available, partial, unavailable}
  ENV-005      pass  the literal 'not_requested' never appears; an unrequested section is absent
  ENV-006      pass  no error: null (or empty) at ANY depth; a successful section omits the key
  ENV-007      pass  every data_status at any depth is in {available, partial, unavailable}, never a coverage word
  ENV-008      pass  every coverage.status is in {complete, partial, unavailable, unknown}
  ENV-009      pass  coverage.weight_basis appears only with non-empty missing_tickers and is always 'active_weights_renormalized_to_100_percent'
  ENV-010      pass  covered_tickers disjointly partitions requested_tickers, in request order
  ENV-011      pass  available_tickers is a subset of requested_tickers unless raw_available_tickers documents the extras
  ENV-012      pass  a section as_of does not sit inside the envelope collection window unless a refresh timestamp is disclosed
  ENV-013      pass  a section does not report as_of: null while its payload carries dated observations
  ENV-014      pass  every non-null as_of carries a non-empty as_of_semantics
  ENV-015      pass  a section whose payload declares a monetary unit also declares section.currency
  ENV-016      pass  every partial/unavailable section has a non-empty warnings array
  ENV-017      pass  no NaN/Infinity anywhere and the bytes re-parse as strict JSON
  ENV-018      pass  no duplicate object keys in the source bytes

CROSS-SECTION  (9 rules)
  XS-001       pass  every section publishing the holding window agrees on intersection_start, covered_days and covered_days_scope
  XS-002       pass  catches D-01: a published covered_days carries a non-empty covered_days_scope
  XS-003       pass  every effective_start has provenance and an inferred start publishes the stored_added_on it displaced
  XS-004       pass  an effective_start never contradicts the stored added_on without declaring a buy-price inference
  XS-005       pass  catches D-02: per-ticker masked_days/return_observations are reconcilable or the block declares per_ticker_count_units
  XS-006       pass  every full_history block declares a scope, an observation count and a window
  XS-007       pass  regime conditional coverage equals the conditional sample, not the holding pool or the model window
  XS-008       pass  a composite does not read 'complete' coverage while a component is unavailable unless the coverage block names the components it describes
  XS-009       pass  catches D-06: every published factor fit statistic declares its window and observation count, and disagreeing sections distinguish their windows

NUMERIC  (20 rules)
  NUM-001      pass  sum(market_value) == total_value and sum(weight) == 1
  NUM-002      pass  sector weights: the published total equals the sum of the published values, the residual equals 1 - total, and nothing is renormalized to 1.0
  NUM-003      pass  risk contributions declare a unit and publish a residual summing to ~1
  NUM-004      pass  every liquidity category matches its own published score under the declared band rule (recomputed, not trusted)
  NUM-005      pass  an unavailable liquidity result reports a null score, not a plausible mid value
  NUM-006      pass  catches D-03: non-measured market caps are counted and disclosed at section level
  NUM-007      pass  max_drawdown == portfolio_impact * 1.15 for every stress scenario
  NUM-008      pass  every priced sizing trade: amount == shares_delta * sizing_price + rounding_residual
  NUM-009      pass  a zero-share trade carries an explicit status and preserves its notional
  NUM-010      pass  the reconciliation max tolerance is really the max over the same population as the residual
  NUM-011      pass  optimizer weight_delta closes against its own published legs on every record
  NUM-012      pass  optimizer publishes a gross-exposure residual and derives financing_required from the unrounded figure
  NUM-013      pass  Monte Carlo quantiles are non-decreasing across percentiles and success_definition is present
  NUM-014      pass  pairs: n*(n-1)/2 == scanned_pairs_count, a shallow leg forces partial, EG/Johansen agreement counts are published
  NUM-015      pass  regime probabilities and transition rows sum to ~100 with a published residual; stability_pct declares its rule
  NUM-016      pass  the tail-dependence matrix is square, symmetric and unit-diagonal
  NUM-017      pass  EVT declares which gpd_shape_xi produced the metrics
  NUM-018      pass  catches D-04: no risk sub-score is a hard 0 while excluded_components is empty
  NUM-019      pass  catches D-05: no performance row's benchmark_value equals its own portfolio_value unless flagged, no return on the first row, every row carries a benchmark
  NUM-020      pass  a short or stale performance window is reported as partial and the dashboard section reflects it

PER-SECTION VERDICT
  section                status        findings  rules
  portfolio              available     0         pass
  dashboard              partial       0         pass
  realized_risk          partial       0         pass
  forecast_risk          available     0         pass
  factor_exposure        available     0         pass
  concentration          available     0         pass
  liquidity              partial       0         pass
  stress_testing         available     0         pass
  volatility_sizing      available     0         pass
  tear_sheet             available     0         pass
  risk_contribution      available     0         pass
  risk_studio            available     0         pass
  optimization           available     0         pass
  regime                 available     0         pass
  monte_carlo            available     0         pass
  pairs                  partial       0         pass
  india_flows            partial       0         pass

SUMMARY
  rules run   : 47
  passed      : 47  ['ENV-001', ... 'NUM-020']
  failed      : 0  []
  findings    : 0
exit=0
```

`uv run python -m app.debugging.context_audit rules` → `COUNTS: envelope=18  cross-section=9  numeric=20  total=47`.

**Read the verdict correctly:** `exit=0`, `failed: 0`, `findings: 0`. The tool's own note says the `catches D-0x` rules guard defects recorded in `.scratch/ai-context-v3-remediation-2026-09/open-defects.md` and "are expected to be GREEN". **That is the tell: the rule set was written to prove a specific list of six previously-found defects is fixed. It was not written to find new ones.** Six of 47 rules are regression guards on named historical defects. The other 41 check structural invariants that a well-formed export satisfies by construction. Not one rule asks whether a number is *true*.

---

## (b) TABLE OF EVERY SUSPICIOUS LITERAL

Every row was found by walking all leaf scalars. "Verdict" is my recomputation.

| # | Literal | JSON path (short) | Sections | What it is | Verdict |
|---|---|---|---|---|---|
| 1 | `1000000000` | `liquidity.data.by_position.SELECTIPO.NS.market_cap`; `liquidity.data.scoring.market_cap_floor.value` (+2 in dashboard) | liquidity, dashboard | Hardcoded INR 1bn market-cap floor | **Real, and correctly disclosed** — `provenance: "fallback"`, `is_estimate: true`, named in the section warning. This is the *good* pattern; see AD-26 for where it is broken. |
| 2 | `0.15` | `volatility_sizing.data.target_volatility`, `achieved_volatility`; `inputs.target_volatility` | volatility_sizing | Target-volatility constant | **Fabricated input** — hardcoded by the export service, not a request. AD-4 |
| 3 | `0.15` (×3) | `stress_testing…instrument_overrides.SELECTIPO.NS.sector_elasticity` | stress_testing (all 4 scenarios) | Same per-ticker elasticity in all 4 scenarios | Undeclared per-ticker constant that never varies with the scenario. `basis: "instrument_override_selectipo"` — a name, not a derivation. AD-15 |
| 4 | `0.85` / `1.25` (12 of 14 legs × 4 scenarios) | `stress_testing…shock_inputs.volatility_adjustment.by_ticker.*.factor` | stress_testing | Volatility-adjustment clip bounds | **12/14 legs are exactly at the bound.** Only CIPLA (1.0058) and NTPC (0.9849) are interior. Published `status: available`, `warnings: []`. AD-15 |
| 5 | `0.22` | `stress_testing…volatility_adjustment.reference_annualized_volatility` | stress_testing | Hardcoded reference vol | Declared in `methodology`. Acceptable. |
| 6 | `252` (23×) | `…annualization_trading_days`, `…days`, `…lookback_days` | 9 sections | Trading-day annualizer | **Declared in stress_testing / monte_carlo / pairs. NOT declared in `forecast_risk`, `realized_risk`, `tear_sheet`, `risk_contribution` — the four sections that actually publish annualized ratios.** AD-2, AD-3 |
| 7 | `1.645` | — | **nowhere** | VaR z-multiplier (95% one-tailed) | **Zero occurrences in 876 KB.** Hidden constant. AD-2 |
| 8 | `2.06` | — | **nowhere** | CVaR multiplier (`analytics_engine.py:1568`) | **Zero occurrences as a constant** (the 3 textual hits are coincidental t-stats `−2.0668`/`−2.0652` and `ou_half_life_days: 22.06`). Hidden constant. AD-2 |
| 9 | `0` (×14) | `india_flows…liquidity_limits.data.positions[*].days_to_liquidate_20pct_adv` | india_flows | Days to liquidate 20% of ADV | True value ≈ 2.4e-7 days; `round(x,2)` → 0. **No precision or floor field.** AD-11 |
| 10 | `0` (×13) + `0.01` (×1) | `…days_to_liquidate_10pct_adv` | india_flows | ditto at 10% | Whole metric is saturated into `{0, 0.01}`. AD-11 |
| 11 | `0` (×2) | `…portfolio_weighted_days_to_liquidate_10pct`, `_20pct` | india_flows | Portfolio-level liquidation time | Portfolio "can be fully liquidated in 0 days". AD-11 |
| 12 | `0` | `india_flows.data.component_coverage.delivery_anomalies.coverage_ratio` | india_flows | Coverage ratio | **`covered_count: null` and `covered_symbols: null` sit beside it.** 0 asserts a measured zero for an unmeasured quantity. AD-10 |
| 13 | `"HIGHLY_LIQUID"` (×14), `false` (×14) | `…positions[*].liquidity_tier`, `.is_oversized_vs_adv` | india_flows | Per-position classification | **Constant across the whole book — carries zero information, no basis field.** AD-11 |
| 14 | `0.05 × ADV` (×14) | `…positions[*].max_sane_position_value` | india_flows | "Max sane" position size | **Undeclared 5% participation rate**, contradicting the same block's `adv_participation_rates: [0.1, 0.2]`. AD-12 |
| 15 | `0` (×2) | `regime.data.label_overrides.crash_veto_days` | regime, dashboard | Crash-veto window length | A 0-day veto can never fire, yet the "crisis" label is published as if it participated. AD-23 |
| 16 | `0` (×18) | `tear_sheet.data.underwater[*].drawdown` | tear_sheet | Drawdown at each date | Legitimate (monotone-to-high). **Not a defect** — recorded so it is not re-flagged. |
| 17 | `0` (×42) | `interior_price_gaps`, `portfolio_alignment_dropped_rows` | dashboard, realized_risk | Gap / dropped-row counts | Legitimate measured counts. Not defects. |
| 18 | `0` | `optimization.data.weight_normalization.net_cash_weight` | optimization | Net cash | Consistent with `fully_funded`. Not a defect. |
| 19 | `0` | `regime.data.transition_matrix_row_residual_max_abs` | regime, dashboard | Max row residual | Rows sum to 100 after rounding. Not a defect. |
| 20 | `0.15` | `stress_testing…volatility_adjustment.bounds` | stress_testing | — | see #2/#4 |
| 21 | `0.15` | `realized_risk`/`tear_sheet` implied risk-free | — | Risk-free rate | `optimization` publishes `risk_free_rate: 0.02` (a settings default, `analytics_engine.py:199`); `tear_sheet` publishes **no** rf at all. Two implied, one declared. AD-17 |
| 22 | `0.01` | `liquidity.data.scoring.scale.min` | liquidity, dashboard, monte_carlo | Scale floor | Legitimate, declared. |
| 23 | `0.05` | `pairs.data.p_value_threshold` | pairs | Significance level | Declared — but see AD-1: no multiple-testing correction. |
| 24 | `0.75` | `pairs.data.minimum_depth_ratio` | pairs | Depth floor | Declared + warned. Good. |
| 25 | `98.4` | `concentration.data.diversification_score` | concentration, dashboard | Diversification index | **Reconciled** = `(1−HHI)/(1−1/14)×100` = 98.403. But **no scale, no formula, no basis field in the export.** AD-13 |
| 26 | `0.83` | `concentration.data.diversification_ratio` | concentration, dashboard | `N_eff / N` | Reconciled = 11.6066/14 = 0.829. No basis field. AD-13 |
| 27 | `0.0862` / `11.61` / `0.252` | `concentration.data.herfindahl_index` / `.effective_positions` / `.gini_coefficient` | concentration, dashboard | HHI, N_eff, Gini | **All three reconcile exactly** to recomputation from the published weights. Genuine. |
| 28 | `0.3168` | `factor_exposure…SELECTIPO.NS.annualized_alpha` **and** `pairs.data.pairs[6].current_spread_zscore` | factor_exposure, pairs | Coincidental 4dp collision across unrelated computations | **Not a copy-paste bug** — genuine coincidence at 4dp. Recorded so a future collision-detector does not waste a cycle. AD-28 |
| 29 | `0.6153846153846154` | `realized_risk.data.portfolio.hit_ratio` | realized_risk | Hit ratio, 16 sig digits | **Denominator undeclared** — 24/39 and 8/13 both yield it exactly. AD-21 |
| 30 | `99.9993` | `regime.data.regime_probabilities.crisis` | regime, dashboard | Posterior | Consistent with the HMM output. But the portfolio is **+1.72%** in that regime. AD-14 |
| 31 | `0.1404` vs `0.3408` | `risk_studio…correlation_stability.current_avg_correlation` vs `.historical_median` | risk_studio | Average pairwise correlation | **59% collapse below median, classified `alert_level: "NORMAL"`.** AD-9 |
| 32 | `793` and `11` | `monte_carlo.data.chunk_size_paths`, `.checkpoint_count` | monte_carlo | Memory chunk vs fan checkpoints | **Orthogonal quantities published beside `num_paths: 2000`.** `793 × 11 = 8723 ≠ 2000` invites a reader to multiply them. Not an arithmetic impossibility, but an unlabelled dimension mismatch. AD-22 |
| 33 | `-26732.4` | `monte_carlo.data.expected_shortfall_vs_target` | monte_carlo | Mean shortfall of failing paths | **Unconditional mean, not a tail ES.** No unit, no level, no definition. Same word means a 95/99% CVaR elsewhere. AD-7 |
| 34 | `0.3715` | `monte_carlo.data.prob_success` | monte_carlo | Goal probability | Computed against a **fabricated `2 × portfolio_value` goal**, disclosed only in `inputs`. AD-6 |
| 35 | `1.15` | `stress_testing…max_drawdown_formula` | stress_testing (×4) | `max_dd = impact × 1.15` | Hardcoded uplift. Declared in `methodology` and as a formula string. Acceptable — and the checker's NUM-007 pins it. |

---

## (c) FINDINGS

### AD-1 · **P0** · `sections.pairs.data.pairs[*].signal`
**Observed** Two of 91 pairs carry explicit trade instructions:
- `"LONG_SPREAD (Long ELECTCAST.NS, Short MCX.NS)"` — `engle_granger_pvalue: 0.042007`, `current_spread_zscore: -1.6827`, **`johansen_agrees_with_decision: false`**, `hedge_ratio_beta: 0.008606`, `overlap_observations: 173`
- `"SHORT_SPREAD (Short JUNIORBEES.NS, Long MIDCAPIETF.NS)"` — `p: 0.04853`, `z: 1.5388`, **`johansen_agrees_with_decision: false`**, `hedge_ratio_beta: 33.6396`, `overlap_observations: 168`

**Why it cannot be trusted**
1. **Every trade signal in the file is one the diagnostic test rejects.** `test_agreement.decision_positive_count: 4`, `diagnostic_positive_count: 4`, `agreement_count: 83`, `disagreement_count: 8`, `decision_positive_only_count: 4`. The 83 "agreements" are 87 trivial negatives. All 4 positives are EG-yes/Johansen-no.
2. **4 positives out of 91 tests at α=0.05 is the null expectation.** 91 × 0.05 = **4.55 expected false positives**; 4 observed. Two of the four p-values are 0.0420 and 0.0485 — barely inside the threshold. There is **no multiple-hypothesis correction of any kind**: `bonferroni`=0, `fdr`=0, `family_wise`=0, `p_value_adjust`=0, `multiple test`=0, `false positive`=0 occurrences. `scanned_pairs_count: 91` is published, so a careful reader *could* compute it; nothing names it. This is the textbook multiple-comparisons trap, presented as a finding.
3. **The z-score entry threshold is absent from the artifact.** `cointegration_service.py:436,438` hardcodes `>= 1.5` / `<= -1.5`. In 876 KB: `signal_rule`=0, `signal_basis`=0, `entry`=0, `z-score`=0, `reversion_threshold`=0, `deviation`=0, `2.0 sigma`=0. `zscore` appears 91× — once per pair, as the *result* key only. A reader cannot know what triggered the signal, or that the sign convention is inverted relative to intuition.
4. **The instruction omits the size ratio that makes it a trade.** `hedge_ratio_beta: 33.6396` means ~33.6 shares of MIDCAPIETF per 1 share of JUNIORBEES. An agent sizing the string 1:1 is wrong by 33×. `hedge_ratio_beta` is present in the record but not in the directive, and the string is what a model will act on.
5. **The prices behind the signal disagree with the portfolio's own marks.** ELECTCAST is `72.56` here (obs 2026-09-24) vs `72.33999633789062` in `portfolio` (2026-09-26). 31 (ticker, price) combinations across the section mismatch the portfolio. The only warning is about depth.
6. **No borrow, cost, or constraint disclosure whatsoever.** `borrow`=0, `margin`=0, `short sale`=0 occurrences. The portfolio is 100% long; the artifact instructs two shorts.
7. `spread_series: null` on all 91 pairs (`detail=summary`), so the z-score is unverifiable at any level.

**Root cause** `backend/app/services/cointegration_service.py:436`, `:438` (hardcoded ±1.5, no rule exported); `:433-441` (signal emitted with no test-agreement gate)
**Confidence** High — all arithmetic recomputed; all absence counts verified against the raw file bytes.

---

### AD-2 · **P0** · `sections.forecast_risk.data.portfolio.cvar_forecast`, `.var_forecast`
**Observed** `volatility_forecast: 0.13767283267201857`, `var_forecast: -0.014266383036982124`, `cvar_forecast: -0.01786550094600801`, `model: "GARCH"`, `model_params.forecast_method: "analytic"`, `status: available`, `warnings: []`.

**Why it cannot be trusted**
Recomputation: `|var_forecast| / (σ/√252) = 1.645000` **exactly**, for the portfolio and for every one of the 14 positions. `|cvar| / (σ/√252) = 2.0600`.

- `analytics_engine.py:1567` — `var_forecast = -return_space_vol * 1.645` (a literal)
- `analytics_engine.py:1568` — `cvar_forecast = -return_space_vol * 2.06` (a literal)
- Repeated at `:1647`/`:1648` (EGARCH) and `:1694`/`:1695` (fallback)

**`cvar_forecast` is a hardcoded constant multiple of `var_forecast`.** It is not an expected shortfall; it is `VaR × 1.2523`. No GARCH or EVT integration is performed. It happens to approximate the *Gaussian* ES₉₅ ratio (φ(1.645)/0.05 = 2.0628), but 2.06/1.645 = 1.25228 ≠ 2.0628/1.645 = 1.25398, so it is a rounded stand-in for a quantity that was never derived. The section is labelled `model: "GARCH"`, so a reader attributes a distributional result to a GARCH fit that produced only the conditional variance path.

**Neither constant is published.** In 876 KB: `1.645` = **0 occurrences**. `var_confidence`=0, `var_level`=0, `cvar_basis`=0, `var_basis`=0, `confidence_level_basis`=0, `annualization_trading_days` **absent from this section entirely**. Compare: `stress_testing`, `monte_carlo` and `pairs` all publish their annualizer. `realized_risk`, `tear_sheet`, `risk_contribution` and `forecast_risk` — the four sections carrying the annualized ratios a reader will quote — publish none. So the reader cannot know `var_forecast` is 95% one-tailed, and cannot know it is a 1-day figure requiring a √252 to annualize.

Compounding: `analytics_engine.py:1540` clips daily returns to ±20% **before** the GARCH fit. `forecast_risk` publishes `data_points: 173` / `return_observations: 171` as if they were raw observations. `clip` appears in the export only under `stress_testing` and `risk_studio` — **never for `forecast_risk`**. Tail observations are silently removed from the sample and the count is not reduced.

**Root cause** `backend/app/services/analytics_engine.py:1567`, `:1568` (and `:1647`,`:1648`,`:1694`,`:1695`); `:1540` (undisclosed clip)
**Confidence** High — ratios recomputed to 6 decimals on 15 values; root cause read directly.

---

### AD-3 · **P0** · `sections.tear_sheet.data.metrics`, `sections.realized_risk.data.portfolio`
**Observed** `tear_sheet.data.measured_window: {start: 2026-08-04, end: 2026-09-25, days: 39, observation_count: 39}`, `annualized: true`, and:

| metric | value |
|---|---|
| `cagr` | **0.429686** |
| `sharpe` | **3.487604** |
| `sortino` | **5.314715** |
| `calmar` | **20.189083** |
| `omega` | 1.916946 |
| `tail_ratio` | 1.172416 |
| `volatility` | 0.098238 |
| `max_drawdown` | −0.021283 |

Section `status: available`, `warnings: []`, `data_status: available`.

**Why it cannot be trusted**
`CAGR = (1+0.056879)^(252/39) − 1 = 0.429684` — verified. **A 5.69% total return over 39 trading days is extrapolated by a factor of 6.46 into a 42.97% compound annual growth rate.** `calmar = 0.429686/0.021283 = 20.19` — verified. `minimum_observations_required: 30`, so 39 clears the gate by 30%.

A 39-sample standard deviation annualised by √252 is a 6.5× extrapolation; the 95% CI half-width on a 39-sample σ is ±22%. The reported `max_drawdown` of −2.13% over 39 days coexists with per-position drawdowns of −12% to −29% over the same holding period. **`sharpe: 3.49` and `sortino: 5.31` are not risk-adjusted performance figures; they are artefacts of annualising a short, low-dispersion slice.** The section publishes `observation_count: 39` and `truncated_to_holding_window: true`, so a careful reader *can* find the n — but the *value* carries no adjacency to it, `status` is `available`, and the section's `warnings` array is **empty**. `NUM-020` catches a stale *performance* window in `dashboard`; it does not catch this.

**Worse: `realized_risk` publishes two contradictory objects both named "portfolio".**

| | `data.portfolio` (39 rows) | `data.instrument_risk.portfolio` (175 days) |
|---|---|---|
| `annual_return` | 0.362417 | 0.361201 |
| `annual_volatility` | **0.098238** | **0.197796** |
| `sharpe_ratio` | **3.485603** | **1.725018** |
| `sortino_ratio` | 5.311263 | 2.632833 |
| `max_drawdown` | **−0.021283** | **−0.137058** |
| `var_95` | −0.007780 | −0.019318 |

Volatility differs **2.01×**, max drawdown **6.4×**, Sharpe **2.02×**. A 39-sample σ has a 95% CI of roughly ±22%, so a 2× gap is ~9σ — this is not noise, it is two different quantities. **Nothing in the section says which one is the portfolio.** `methodology` is the string `"Real-time calculations using quantstats and statistical models"` — a *library name*, not a method: no window, no formula, no annualizer, no risk-free rate, and no mention that two portfolio profiles exist. `tear_sheet.sharpe: 3.487604` and `realized_risk.sharpe_ratio: 3.485603` are the same statistic on slightly different alignments and appear side by side with a 0.002 gap and no reconciliation note.

**Root cause** `backend/app/services/analytics_engine.py:1346-1372` (annualisation of a 39-row frame; `realized_risk.methodology` is a library reference); the two-object `portfolio` / `instrument_risk.portfolio` split is constructed in `backend/app/api/analytics.py`
**Confidence** High — CAGR, calmar and both Sharpe identities recomputed exactly.

---

### AD-4 · **P0** · `sections.volatility_sizing.data.achieved_volatility`
**Observed** `target_volatility: 0.15`, `achieved_volatility: 0.15` — **byte-identical**. `current_volatility: 0.145465131056991`, `scale_factor: 1.295309`. `inputs.target_volatility: 0.15`. `achieved_volatility_basis` = 0 occurrences; `achieved_basis` = 0 occurrences.

**Why it cannot be true** — it is a **tautology, and the value is mathematically incapable of differing from the target.**

```python
# backend/app/services/analytics_engine.py
1034:  scale = float(target_volatility / rec_vol_ann)
1053:  achieved_vol = float(rec_vol_ann * scale)
1103:  "achieved_volatility": round(achieved_vol, 6),
```

`rec_vol_ann × (target/rec_vol_ann) ≡ target` for any finite positive `rec_vol_ann`. **`achieved_volatility` is a restatement of the function's own input, rounded to 6 decimals, published under a name that asserts an empirical result.** Note the naive sanity check fails: `current_volatility × scale_factor = 0.18842 ≠ 0.15`, because the scale is computed from `rec_vol_ann` (the *recommended* book), not `current_volatility` — a second quantity the export never publishes under that name. A downstream model reading "achieved 15% volatility" will conclude the risk-parity construction landed on target. It did not "land" anywhere; it was told where to go.

**The `0.15` is itself fabricated by the export service, and it is the sole cause of the leverage recommendation.**

```python
# backend/app/services/ai_context_service.py
1968:      target_volatility=0.15,
1976:      inputs={"model": "EWMA", "target_volatility": 0.15, "tickers": context.tickers},
```

The export hardcodes `0.15` and then publishes it inside `inputs` as though it were a request parameter. Because `current_volatility` is 0.1455 < 0.15, the scale factor becomes 1.295, gross exposure 1.295, `cash_weight: -0.295309`, `financing_requirement: 12878.08` INR. **The artifact recommends borrowing money because of a hardcoded literal in the exporter.** `analytics_engine.py:1953` also hardcodes `target_volatility: 0.15` inside the *empty/fallback* result, so a failed computation and this one are indistinguishable from the field alone.

**Root cause** `backend/app/services/analytics_engine.py:1034`, `:1053`, `:1103`, `:1953`; `backend/app/services/ai_context_service.py:1968`, `:1976`
**Confidence** High — read the source; the identity is algebraic.

---

### AD-5 · **P0** · `sections.volatility_sizing.data.trades[*].status`
**Observed** 13 of 14 trade records carry `status: "executable"`; the 14th (`MCX.NS`) carries `status: "below_minimum_notional"`. Simultaneously:
- `execution.execution_eligible: false`
- `execution.block_reasons: ["financing_required"]`
- `execution.block_reason: "Gross exposure 1.295310 exceeds 1.0; the target borrows 0.295310 of the portfolio value and is not a normal rebalance"`
- `exposure.execution_eligible: false`
- `methodology: "... financing required 12878.08 INR; **not executable as a normal rebalance**; ..."`
- `leveraged: true`, `net_cash_weight: -0.29531`

**Why it cannot be trusted** The artifact tells the reader, at the section level and in a prose string, that this is not executable — and then labels 13 individual instructions `"executable"` with concrete `shares_delta` and `amount` values. **The record-level field is the one a model reads per-item.** A 13/14 affirmative rate is not a caveat, it is an instruction set. `execution_eligible` appears with values `true` (`optimization`) and `false` (this section) and carries **no `execution_eligible_basis`, no `execution_eligible_rule`, no policy of any kind** (0 occurrences each) — it is a bare boolean asserting permission with no stated criteria: not tested against liquidity, cost, slippage, borrow, margin, or any limit. There is no borrow rate, no borrow availability, no margin requirement anywhere in the 876 KB (`borrow`=0, `margin`=0).

Two further aggravators: `rounding_tolerance` is half a share, so `CIPLA.NS` books a **17.8% single-leg overshoot** (`rounding_residual: -418.99` on a `2349.21` notional) — disclosed, but at 6-decimal prices; and `sizing_price_as_of: 2026-09-22` is 3 days behind the section `as_of` (disclosed via `sizing_basis.price_freshness`, the best disclosure in the file).

**Root cause** per-trade `status` is set independently of the section execution gate — `backend/app/services/analytics_engine.py` (instruction builder, ~`:1055-1096` region) versus `normalization_block`; no rule reconciles them
**Confidence** High — every field quoted verbatim from the artifact.

---

### AD-6 · **P1** · `sections.monte_carlo.data.prob_success`
**Observed** `prob_success: 0.3715`, `target_value: 87217.34`, `initial_value: 43608.67`, `success_definition: "terminal_wealth_above_target"` + a 5-sentence `success_definition_detail`. `status: available`, `warnings: []`.

**Why it cannot be trusted** The goal is **invented**.
```python
# backend/app/services/ai_context_service.py
2133:  if options.monte_carlo_target_value is not None:
2134:      target = float(options.monte_carlo_target_value); target_policy = "explicit"
2137:  else:
2138:      target = float(context.total_value or 0.0) * 2.0
2138:      target_policy = "2x_current_portfolio_value"
```
Verified: `inputs.target_value: 87217.33962127686 = 2 × 43608.66981063843`. **The user never stated a goal; the exporter doubled the book value and reported a 37.15% probability of reaching it.** `target_policy` is recorded in `inputs` only — it appears **nowhere in `data` and nowhere in `warnings`**. A reader who opens `sections.monte_carlo.data` sees `prob_success: 0.3715` next to a `target_value` and will report "37% chance of hitting the goal". There is no goal.

The disclosure that *is* present (`success_definition_detail`) is genuinely good — it correctly warns the figure is terminal, not path-touching. That quality makes the missing goal disclosure worse, not better: a model is primed to be careful about one definitional subtlety and is not told the target itself is fabricated.

**Root cause** `backend/app/services/ai_context_service.py:2137-2138`, `:2150`, `:2175` (policy recorded in `inputs` only, never promoted into `data` or `warnings`)
**Confidence** High — verified 2× identity; source read.

---

### AD-7 · **P1** · `sections.monte_carlo.data.expected_shortfall_vs_target`
**Observed** `-26732.4`. `expected_shortfall_vs_target_definition`=0, `es_definition`=0, and no `units` entry.

**Why it cannot be trusted**
```python
# backend/app/services/monte_carlo_service.py
381:  expected_shortfall = round(float(failing.mean() - target_value), 2) if len(failing) else 0.0
```
It is the **unconditional mean shortfall across all failing paths** — not a conditional tail expectation at any confidence level. It is not `p5 − target` (−49,843.19) and not `p50 − target` (−11,937.77).

**The same artifact uses "expected shortfall" to mean two unrelated things.** `realized_risk.portfolio.cvar_95: -0.0154`, `risk_contribution…portfolio_cvar_95_daily: -0.025175` and `risk_studio…evt_pot_es: -0.041074` are conditional tail means at stated 95%/99% levels. `monte_carlo.expected_shortfall_vs_target` is an average over ~63% of paths. **One word, two definitions, no namespace, no unit, no level.** A model will read "expected shortfall −26,732" beside "CVaR₉₅ −0.0154" and conflate a rupee amount with a 1.5% daily tail measure.

**Root cause** `backend/app/services/monte_carlo_service.py:381`, `:428` (published with no definition field, unlike the `success_definition` pair two keys away)
**Confidence** High — source read; identity checked against both published percentiles.

---

### AD-8 · **P1** · artifact-wide — undeclared return basis
**Observed** Occurrence counts in the raw 876,445 bytes:

| term | count |
|---|---|
| `dividend` | **0** |
| `fee` | **0** |
| `tax` | **0** |
| `slippage` | **0** |
| `survivorship` | **0** |
| `corporate action` | **0** |
| `split` | **0** |
| `bonus` | **0** |
| `net_of` | **0** |
| `auto_adjust` | **0** |
| `adj_close` | **0** |
| `rebalanc` | 3 |
| `total_return` | 31 |
| `price_basis` | 91 (all `adjusted_close_when_available`, in `pairs` only) |

**Why it cannot be trusted** Every return statistic in the file and the entire five-year projection rest on an **undeclared** basis:
- **No dividend adjustment declared.** Indian large/mid caps yield 1–3% p.a.; a 5-year projection with zero dividends understates the median path materially — plausibly by a double-digit percentage of terminal wealth, against a `p5` of ₹37,374 and `p50` of ₹75,280.
- **No fee, tax, brokerage, STT, GST, stamp-duty or slippage basis.** `monte_carlo` recommends 14 round-trip trades and `volatility_sizing` recommends 14 more; nothing says the projections are gross.
- **No survivorship disclosure.** The universe is the 14 names currently held. Delisted / merged / failed names are absent by construction, so every long-horizon return distribution is optimistically biased, and `full_history` compounds it over 2,486 days.
- **No corporate-action disclosure.** Splits and bonuses are undeclared. `MOTILALOFS` (buy 644.73 → 1029) and `ARROWGREEN` (578.34 → 905.80) are large moves; an unadjusted split corrupts the return series silently. `price_basis: "adjusted_close_when_available"` appears **only** in `pairs` — `portfolio`, `realized_risk`, `tear_sheet`, `volatility_sizing`, `monte_carlo` and `regime` never state their price basis at all.

`monte_carlo.disclaimer` is `"Probabilities are model estimates from historical data; not investment advice."` — a compliance fig leaf, not a model-limitation disclosure. It names none of the eight items above.

**Root cause** the export has no return-basis block; `price_basis` is emitted by the pairs collector only. Cross-cutting: `backend/app/services/ai_context_service.py` section collectors.
**Confidence** High — literal substring counts against the source bytes.

---

### AD-9 · **P1** · `sections.risk_studio.data.components.correlation_stability`
**Observed** `current_avg_correlation: 0.1404`, `historical_median: 0.3408`, `historical_threshold_75th: 0.4129`, `historical_threshold_90th: 0.459`, `is_regime_break: false`, `alert_level: "NORMAL"`, `message: "Average pairwise correlation (0.140) is within normal historical bounds (median 0.341)."`

**Why it cannot be true** Average pairwise correlation has **collapsed 59% below its own historical median** — to 41% of it, far beneath the 25th percentile. The section calls this normal.

```python
# backend/app/services/correlation_service.py
100:  is_regime_break = bool(current_avg_corr >= threshold_90th)
108:  elif current_avg_corr >= threshold_75th:   alert_level = "ELEVATED"
115:  else:                                      alert_level = "NORMAL"
118:      f"(median {historical_median:.3f})."
```
The test is **one-sided (upper only)**. There is no lower bound, so the "ELSE" branch — and its reassuring message string — is reached by any collapse whatsoever. A correlation of 0.14 against a median of 0.34 is a structural regime change in the risk model; it is exactly the condition a "correlation stability" monitor exists to catch. **`alert_level: "NORMAL"` and a message string asserting normality are a status lie**, and the message is the specific thing a downstream model will quote.

**Root cause** `backend/app/services/correlation_service.py:100`, `:108`, `:115`, `:118` (one-sided test; message asserts two-sided normality)
**Confidence** High — source read; the two published values are 0.1404 and 0.3408.

---

### AD-10 · **P1** · `sections.india_flows.data.component_coverage.delivery_anomalies.coverage_ratio`
**Observed** `coverage_ratio: 0`, beside `covered_count: null`, `covered_symbols: null`, `missing_symbols: [all 14]`, `coverage_status: "unavailable"`, `coverage_status_reason: "no_requested_symbol_had_usable_delivery_history"`.

**Why it cannot be false** This is the **hard-zero-where-not-computed** signature. `covered_count` is `null` — coverage was **never measured**, because no NSE bhavcopy delivery history was ingested. A numeric `coverage_ratio: 0` asserts "zero of fourteen symbols covered" as a *measured fact*. It is not; it is the arithmetic default `null/14`. Any consumer keying on the numeric field — which is the natural thing to do, and the only machine-readable field in the block — receives a fabricated measurement. The correct values are `null` or `unknown`.

`ENV-007` (data_status enum) and `ENV-008` (coverage.status enum) both pass, because `coverage_status: "unavailable"` is correct. **The rules validate the enum field and ignore the numeric field sitting beside it.** `coverage_status_reason` and the section warning both say the right thing in prose — so the artifact contains a correct sentence and a wrong number about the same fact, and the number is the one that gets consumed.

**Root cause** `backend/app/api/analytics.py` (india_flows component-coverage builder) — `coverage_ratio` is computed rather than nulled when `covered_count is None`
**Confidence** High — all three fields quoted from the artifact; ENV-007/008 re-read and confirmed to key on the enum strings only.

---

### AD-11 · **P1** · `sections.india_flows.data.components.liquidity_limits.data`
**Observed**
- `positions[*].days_to_liquidate_10pct_adv`: `0` ×13, `0.01` ×1
- `positions[*].days_to_liquidate_20pct_adv`: `0` ×14
- `portfolio_weighted_days_to_liquidate_10pct: 0`, `portfolio_weighted_days_to_liquidate_20pct: 0`
- `positions[*].liquidity_tier`: `"HIGHLY_LIQUID"` ×14
- `positions[*].is_oversized_vs_adv`: `false` ×14
- No `units` block. No `*_precision`. No `*_floor`.

**Why it cannot be true**
```python
# backend/app/services/india_data_service.py
568:  "days_to_liquidate_10pct_adv": round(days_10, 2),
569:  "days_to_liquidate_20pct_adv": round(days_20, 2),
584:  "portfolio_weighted_days_to_liquidate_10pct": round(weighted_days_10 or 0.0, 2),
```
The true values are ~2.4e-7 days. `round(2.4e-7, 2) = 0`. **The whole book reports `0` days to liquidate 20% of ADV, and the portfolio reports `0` days.** A hard zero here is not "instantly liquid" — it is a sub-microsecond quantity rendered by a 2-decimal rounding into a value indistinguishable from zero. The reader cannot distinguish "0 days" from "0.0000002 days" from "not computed". Compare the codebase's own standard elsewhere: `liquidity.volume_band_rounding_decimals: 1` and `concentration.by_sector_rounding_decimals: 4` and `optimization.trades_required_basis.weight_decimals: 4` are all published. **The disclosure convention exists and is simply not applied here.**

`liquidity_tier: "HIGHLY_LIQUID"` and `is_oversized_vs_adv: false` are **constants across all 14 positions** — a per-position classification carrying zero information, with `liquidity_tier_basis`=0 occurrences. Four of the fourteen are SME/illiquid scrips (SELECTIPO, MAFANG, ELECTCAST, JKIL — `adv_30d_shares` 49,881 for ARROWGREEN against 2,446,204 portfolio-average). Publishing a uniform "HIGHLY_LIQUID" over that roster is a false all-clear.

The block also publishes **no `units`** — no `monetary_unit`, no `volume_unit`, no day-basis (trading vs calendar) — while `adv_lookback_sessions: 30` and `adv_participation_rates: [0.1, 0.2]` are present. `liquidity` publishes all three units.

**Root cause** `backend/app/services/india_data_service.py:568`, `:569`, `:584`, `:585` (2-dp rounding with no precision publication); `:571` (tier with no basis)
**Confidence** High — recomputed CIPLA: `2799.4 × 0.10 / 1,145,554,340.56 = 2.44e-7` days; source read.

---

### AD-12 · **P1** · `sections.india_flows…positions[*].max_sane_position_value`
**Observed** `max_sane_position_value: 57277717.03` for CIPLA, in a block that declares `adv_lookback_sessions: 30` and `adv_participation_rates: [0.1, 0.2]`. `max_sane_position_value_basis`=0, `max_sane_basis`=0, `sane_position_basis`=0 occurrences.

**Why it cannot be true** Verified for all 14: `max_sane_position_value == 0.05 × adv_30d_rupees` exactly (CIPLA 57,277,717.03 = 0.05 × 1,145,554,340.56).
```python
# backend/app/services/india_data_service.py
556:  max_position = round(adv_rupees * 0.05, 2)
557:  oversized = bool(position_value > max_position)
```
**A third, undeclared 5% participation rate sits in a block that publishes its other two (10%, 20%) and labels them `adv_participation_rates`.** Nothing names the 5%, and it is the one that drives `is_oversized_vs_adv` — the field that makes the all-clear in AD-11. The field name `max_sane_position_value` is a **judgemental assertion** ("sane"), carries no basis, no unit beyond ambient inference, and reads as a data-derived ceiling. It is a hardcoded literal.

**Root cause** `backend/app/services/india_data_service.py:556`
**Confidence** High — exact identity verified on all 14 legs.

---

### AD-13 · **P1** · `sections.concentration.data.diversification_score`
**Observed** `diversification_score: 98.4`, `diversification_ratio: 0.83`, `effective_positions: 11.61`, `herfindahl_index: 0.0862`, `gini_coefficient: 0.252`, `top_3: 0.363`, `by_sector["Exchange Traded Fund"]: 0.321`, `methodology: "Concentration analysis using Herfindahl-Hirschman Index (HHI), Effective Positions (N_eff), and Lorenz Gini Coefficient"`, `status: available`, `warnings: []`.

**Why it cannot be true** Both values are arithmetically derivable and I confirmed them:
- `diversification_score = ((1 − 0.086158) / (1 − 1/14)) × 100 = 98.403` → `98.4` ✓
- `diversification_ratio = 11.6066 / 14 = 0.829` → `0.83` ✓
- HHI, N_eff, Gini, `top_3`, `top_5`, `top_10`, `largest_position` all reconcile exactly ✓

**The defect is disclosure, not arithmetic.** `concentration.data` publishes **no `scale` block, no `formula`, no `*_basis`**. The normalisation denominator `(1 − 1/N)` — the entire meaning of the number — appears nowhere in the export. Contrast `liquidity`, which publishes a complete `scoring` block: `scale {min: 2.5, max: 10, unit: "index_0_to_10"}`, `score_precision`, `raw_score_field`, `published_score_field`, `bands`, `thresholds`, `score_basis`. **The same codebase holds both standards and applies the good one only to liquidity.**

`98.4` has no unit. A model will read "diversification score 98.4" as 98.4% or 98.4/100 and conclude the book is well diversified — while the same object publishes `top_3: 0.363`, a `32.1%` weight in a single generic "Exchange Traded Fund" bucket spanning 4 of 14 names, and `effective_positions: 11.61` of 14 (i.e. 83% — a materially worse number than 98.4). The HHI-normalisation is a nonlinear rescale that inflates relative to the effective-position ratio. **`98.4` is an unexplained high-precision number presented as a judgement, adjacent to evidence that contradicts the judgement.** `as_of: null` as well, so the reader cannot even date the weights.

**Root cause** `backend/app/services/analytics_engine.py:421` (formula), `:435-436` (published with no basis); `backend/app/api/analytics.py:3549-3550` (pass-through with no `scoring` block, unlike the liquidity equivalent at `:1950-1988`)
**Confidence** High — formula confirmed; absence of a scale block confirmed against the artifact.

---

### AD-14 · **P1** · `sections.regime.data`
**Observed** `current_regime: "crisis"`, `regime_probabilities: {crisis: 99.9993, calm: 0.0006, bull: 0}`, `stability_pct: 96.7`, `status: available`, section `warnings: []`.
- `states[0] = {regime: "crisis", ann_ret: -0.2666, ann_vol: 0.1124, historical_days_pct: 30.9}`
- `states[1] = {regime: "calm",  ann_ret:  0.1228, ann_vol: 0.1096, historical_days_pct: 53.3}`
- `states[2] = {regime: "bull",   ann_ret:  0.8627, ann_vol: 0.1965, historical_days_pct: 15.9}`
- `portfolio_in_current_regime: {days: 19, ann_ret: null, ann_vol: null, total_ret: 0.0172, annualized: false, minimum_observations_required: 30, truncated: true}`
- `label_overrides: {crash_veto_days: 0, crash_veto_threshold: -0.1}`

**Why it cannot be trusted**
1. **The portfolio is +1.72% while in the "crisis" regime.** `portfolio_in_current_regime.total_ret: 0.0172` over the 19 days classified into the current regime. A model reading `current_regime: "crisis"` at 99.9993% will infer distress; the portfolio's own conditional experience of that regime is a gain.
2. **The label ordering inverts the volatility ordering.** `crisis` carries `ann_vol: 0.1124`; `bull` carries `ann_vol: 0.1965`. **The "crisis" state is 43% less volatile than the "bull" state**, and within 2.5% of "calm" (0.1096). A model that reads `crisis` as a volatility state concludes the book is in a *low*-volatility stress regime. This is the same class of defect the repo's own `AGENTS.md` forbids for diversification ("Never invert generic risk scores as a proxy for diversification") — here the inversion is in the regime label itself.
3. **`crash_veto_days: 0` is a no-op.** A zero-day veto window can never fire, so the `-0.1` threshold beside it is inert. Yet `label_overrides` publishes both as if the veto participated in labelling. The "crisis" label came from the HMM alone.
4. The section is **honest** about the sample: `annualized: false`, `ann_ret: null`, `ann_vol: null` correctly withheld below the 30-observation minimum; `holding_context_note` states the holding window "never shortens, lengthens or annualizes this model window"; `stability_pct_rule` is explicit. The disclosure quality is high. **Which is what makes the three findings above survive: nothing warns, and the section's confidence signals all read positive.**

**Root cause** `backend/app/services/regime_service.py` / `analytics_engine.py` — the HMM state labelling and the portfolio-conditional block are computed independently and no cross-check ties the label to the conditional outcome; `label_overrides.crash_veto_days` is a caller-supplied 0
**Confidence** High for the values (all quoted); Medium on the labelling root cause (source path not isolated to one line).

---

### AD-15 · **P1** · `sections.stress_testing.data.scenarios.*.shock_inputs.volatility_adjustment`
**Observed** All four scenarios publish an identical `by_ticker` factor map. Distinct values: `[0.85, 0.9849, 1.0058, 1.25]`. **12 of 14 legs sit exactly on a clip bound** (0.85 or 1.25); only CIPLA (1.0058) and NTPC (0.9849) are interior. `bounds: [0.85, 1.25]`. `max_drawdown_formula: "portfolio_impact * 1.15"`. `confidence_level: 0.95` with `confidence_basis: "nominal_label_not_simulated"`. Section `status: available`, `warnings: []`.

**Why it cannot be trusted**
- **86% of the volatility adjustment is saturated.** The block declares `basis: "measured_annualized_volatility_over_reference"` on every leg — an explicit claim that the number is measured — while 12 of 14 are the clip endpoint. The claim is false for the majority of the book. The clipping is described only inside the `methodology` prose string, **six levels below the value**, and never as a count. Compare `liquidity`, which publishes `estimated_market_cap_count: 5`, `measured_market_cap_count`, `fallback_market_cap_count` and a section warning naming every affected ticker. That standard is not applied here.
- **`SELECTIPO.NS` carries `sector_elasticity: 1.15` in all four scenarios** while the table's own ETF elasticity varies (1.0 / 1.0 / 1.05 / 0.6). A per-ticker elasticity that never responds to the scenario is a constant, named `instrument_override_selectipo` — a label, not a derivation. The coincidence of `1.15` here and `1.15` in `max_drawdown_formula` is a smell worth a second look.
- **`confidence_level: 0.95` is published on every scenario** with `confidence_basis: "nominal_label_not_simulated"`. Correctly disclosed — and still a high-precision risk figure on four scenarios whose `max_drawdown` is a deterministic proxy times 1.15.
- **`as_of: null`, and the block publishes no `data_range`, no window, and no per-ticker observation count.** `min_observations: 20` is a *threshold*, not the count. So twelve saturated factors rest on an unstated sample over an unstated window on an unstated date. **The checker has no rule for a measured statistic with no window** — `XS-006` covers `full_history` blocks only, and `ENV-013` fires only on *dated* observations, of which there are none here.

**Root cause** `backend/app/services/analytics_engine.py:763` (factor), `:803-808` (block, incl. the hardcoded `252`), `:824` (methodology string) — the saturation count is never surfaced
**Confidence** High — recomputed the 12/14 bound count and the `-0.35 × 1.0 × 0.85 = -0.2975` / `-0.35 × 1.3 × 0.85 = -0.38675` position impacts to confirm the arithmetic is as described; the defect is the undisclosed saturation.

---

### AD-16 · **P1** · cross-section — three live price snapshots, one four-word disclosure
**Observed**

| source | as_of | CIPLA | MCX | SELECTIPO | ARROWGREEN |
|---|---|---|---|---|---|
| `portfolio.data.positions[*].last_price` | 2026-09-26 (`updated_on`) | 1399.699951171875 | 3324.89990234375 | 47.2 | 905.7999877929688 |
| `volatility_sizing…sizing_price` | 2026-09-22 | 1384.0999755859375 | 3262.60009765625 | 48.84000015258789 | 913.0499877929688 |
| `pairs.data.pairs[*].last_price_a/b` | 09-22 / 09-23 / 09-24 / 09-25 | 1383, 1399, — | 3374, 3427.7 | 48.2, 48.84 | 875.25, 900, 913.05 |

**31 (ticker, price) combinations in `pairs` disagree with the portfolio's own mark for the same ticker.** Every one of the 14 names appears at 2–4 different prices across the section. Modal gaps: ARROWGREEN 905.80 vs 875.25 (**3.5%**), SELECTIPO 47.20 vs 48.84 (**3.5%**), MCX 3324.90 vs 3427.70 (**3.1%**), MOTILALOFS 1029 vs 1007 (**2.1%**).

**Why it cannot be trusted** The envelope's entire disclosure is `"snapshot_consistency": "best_effort"` plus an **empty envelope `warnings: []`**. There is no drift list, no per-ticker price-consistency block, no `price_as_of` reconciliation. The two *good* disclosures are both local and easy to miss: `volatility_sizing.sizing_basis.price_freshness` names its own 3-day lag, and `sizing_basis.position_last_price_comparison` publishes all 14 relative gaps (`max_abs_relative_gap: 0.034746`, `SELECTIPO.NS`). **`pairs` has no equivalent** — and `pairs` is the section carrying the trade instructions of AD-1, computed on the stalest and most fragmented price set in the file.

Also note `sections.*.as_of` values are a spread: `2026-09-21` (dashboard), `09-22` (optimization), `09-24` (regime), `09-25` (8 sections), `09-26` (portfolio), `null` (concentration, liquidity, stress_testing). `ENV-012` passes because 09-21…09-25 all sit *outside* the collection window; the rule has no notion of *relative* staleness between sections.

**Root cause** `backend/app/services/ai_context_service.py:1484` (`"snapshot_consistency": "best_effort"` hardcoded, unconditional); no cross-section price reconciliation in the collector or in `backend/app/debugging/context_audit.py`
**Confidence** High — all 31 mismatches enumerated; `ENV-012` re-read and confirmed to test only against the envelope window.

---

### AD-17 · **P1** · `sections.optimization`
**Observed** `as_of: 2026-09-22` (3 days behind the modal `2026-09-25`), `latest_observation_date: 2026-09-22`, `history_window: {requested_start: 2025-09-26, requested_end: 2026-09-26, first_observation: 2025-09-29, latest_observation: 2026-09-22, return_observations: 170}`, `status: available`, `warnings: []`. `expected_annual_return: 0.2602`, `expected_annual_volatility: 0.1772`, `expected_sharpe: 1.356`, `risk_free_rate: 0.02`, `solver: "hierarchical-bisection"`.

**Why it cannot be trusted**
- **A 26.02% expected annual return and a 1.356 Sharpe for 14 Indian small/mid caps, on a 170-observation window, with no `expected_return_basis`, no window reference on the value, and no `risk_free_rate_basis`.** `expected_sharpe` reconciles (`(0.2602 − 0.02)/0.1772 = 1.3555`) so it is at least internally consistent — but `risk_free_rate: 0.02` is a bare number read from settings: `analytics_engine.py:199` — `self.risk_free_rate = settings.risk_free_rate  # Settings default: 2% annual`. **A hardcoded economic constant published as an input with no provenance.** This is the *only* section in the file that publishes a risk-free rate, so a reader cannot tell the other sections used a different one — and `tear_sisk`'s Sharpe implies a materially different figure (see AD-3).
- **A 4-day-stale window with `status: available` and zero warnings.** The block publishes `requested_end: 2026-09-26` and `latest_observation: 2026-09-22` side by side, so the gap is visible — but `dashboard` proves the codebase knows how to warn about exactly this ("Last delivered observation is 2026-09-21, 5 calendar days before the requested end 2026-09-26; the series is stale."). `NUM-020` only covers the dashboard *performance* series. Nothing covers a stale optimizer window.
- The section's disclosure is otherwise **exemplary** — `trades_required_basis` with `weight_delta_rule`, both published totals, both rounding residuals, and an explicit `totals_note` explaining that the 4-dp residual and the unrounded `submitted_gross_exposure_measured` are *different roundings of the same vector* rather than one standing in for the other. That is the standard the rest of the file should meet.

**Root cause** `backend/app/services/analytics_engine.py:199` (risk-free default); staleness-to-status wiring in `backend/app/services/ai_context_service.py::_collect_optimization`
**Confidence** High — Sharpe identity verified; `analytics_engine.py:199` read; `dashboard` staleness warning quoted for contrast.

---

### AD-18 · **P1** · artifact-wide — seven "portfolio volatilities", no reconciliation
**Observed**

| value | source | window / estimator |
|---|---|---|
| `0.084` | `regime.realtime_parkinson_vol` | 21d Parkinson, realtime |
| `0.098238` | `tear_sheet.metrics.volatility` | 39 holding-window rows |
| `0.0982` | `realized_risk.portfolio.annual_volatility` | 39 holding-window rows |
| `0.1005` | `regime.realtime_ewma_vol` | EWMA, realtime |
| `0.145465131056991` | `volatility_sizing.current_volatility` | EWMA, 174 obs |
| `0.1789` | `risk_studio…risk_contribution.portfolio_volatility_annualized` | 251 days |
| `0.197796` | `realized_risk.instrument_risk.portfolio.annual_volatility` | 175 days |
| (`0.22`) | `stress_testing…reference_annualized_volatility` | a hardcoded constant, not a measurement |

**Why it cannot be true as a decision input** A 2.35× spread. `XS-001` reconciles the *holding-window* fields (`intersection_start`, `covered_days`) across sections — and those do agree. **No rule reconciles the statistics computed from them.** `risk_contribution` uses 251 days while `realized_risk` and `tear_sheet` use 39; `volatility_sizing` uses an EWMA; `regime` publishes two more. Only some name their window. A model asked "what is this portfolio's volatility?" has eight defensible answers and no basis for choosing. The `instrument_risk` block (0.1978) is the most representative and the least prominent.

**Root cause** no cross-section statistic reconciliation in `backend/app/debugging/context_audit.py`; `XS-001` is scoped to holding-window metadata only
**Confidence** High — all eight values quoted; `XS-001` re-read.

---

### AD-19 · **P1** · `sections.risk_studio.data.components.tail_dependence`
**Observed** `confidence_level: 0.99`, `evt_pot_var: -0.036708`, `evt_pot_es: -0.041074`, `historical_var: -0.031724`, `historical_es: -0.036539`, plus **`evt_pot_var_99: -0.036708`, `evt_pot_es_99: -0.041074`, `historical_var_99: -0.031724`, `historical_es_99: -0.036539` — byte-identical duplicates**. `exceedances_count: 26`, `total_observations: 518`, `exceedance_fraction: 0.050193`, `threshold_quantile: 0.95`, `threshold_u: 0.020464`. `gpd_shape_xi: -0.7068` (raw MLE) / `gpd_shape_xi_raw: -0.70676185` / `gpd_shape_xi_used: -0.5` / `gpd_shape_xi_constrained: -0.5` / `constraint_applied: true` / `constraint_reason: "gpd_shape_clipped"` / `gpd_shape_xi_raw_field: "gpd_shape_xi_raw"` / **`gpd_shape_xi_raw_equals_published_headline: true`**.

**Why it cannot be trusted**
1. **A 99% tail measure from 26 exceedances.** `26 × 0.050193 = 0.99999` ✓ internally consistent. But a 99th-percentile GPD moment estimated from 26 points has no published standard error, no bootstrap interval, no fit-quality statistic. `total_observations: 518` over **what window?** The component publishes **no `as_of`, no `data_range`, no window at all** — unlike `risk_contribution` (`calculation_window: 251 days`) and `volatility_cone` (`as_of`). So the EVT tail-risk numbers are undatable and unreproducible.
2. **The headline parameter is the rejected one.** `gpd_shape_xi: -0.7068` is the raw MLE. The metrics were computed from `gpd_shape_xi_used: -0.5` (clipped). A consumer keying on the natural field name gets a parameter that **did not produce the reported risk**. The disclosure is thorough (`gpd_shape_xi_used_rule` explains it in full) — but `gpd_shape_xi_raw_equals_published_headline: true` asserts, affirmatively, that the headline *is* the raw value, and stops there. A skimming model reads the boolean and moves on.
3. **Four headline tail numbers are duplicated under `_99` suffixes.** `suffixed_field_rule` and `suffixed_field_rule`-adjacent prose disclose this correctly. But the result is 8 numbers where 4 are unique, presented as though `_99` were a second, corroborating measure at a different level. **A model will read `evt_pot_var` and `evt_pot_var_99` as independent confirmations.** That is a naming trap, not a bug, and it is the kind of trap an AI context artifact must not contain.

**Root cause** `backend/app/services/evt_service.py` (or equivalent) — no window/`as_of` on the component; `gpd_shape_xi` / `gpd_shape_xi_used` naming; `_99` alias emission
**Confidence** High for the values and the naming; Medium on the exact service file (not isolated to a line).

---

### AD-20 · **P1** · `sections.forecast_risk` — undisclosed ±20% return clip
Covered in AD-2 as the compounding factor; recorded separately because it is a distinct class of defect (silent data modification) from the hardcoded multipliers.

**Observed** `positions.CIPLA.NS.data_points: 173`, `return_observations: 171`; 14 positions reporting 102–172 observations. `clip` appears in the export only under `stress_testing` and `risk_studio`.

**Why it cannot be true** `analytics_engine.py:1540` — `clean_returns = clean_returns.clip(lower=-0.20, upper=0.20)` — executes **before** the GARCH fit and **before** `data_points` / `return_observations` are counted and published. The published counts are therefore *post-clip* and are labelled as if they were the raw observation counts. For a thin SME name (`SELECTIPO` buy 49.13 → 47.20, `MAFANG`, `ELECTCAST` −30.6% unrealised) daily moves beyond ±20% are plausible, and removing them **truncates exactly the tail the model is supposed to forecast** — biasing both `volatility_forecast` and `var_forecast` low, with no disclosure and no reduced count.

**Root cause** `backend/app/services/analytics_engine.py:1540`
**Confidence** High — source read; `clip` absence in the `forecast_risk` sub-tree confirmed by substring scan.

---

### AD-21 · **P2** · `sections.realized_risk.data.portfolio.hit_ratio`
**Observed** `hit_ratio: 0.6153846153846154` — 16 significant digits. No `hit_ratio_basis`, no denominator.

**Why it cannot be false** It reconciles two ways: `24/39` (= 0.6153846153846154) and `8/13` (= 0.6153846153846154). **The denominator is undeclared and genuinely ambiguous** — 39 aligns with `history_coverage.covered_days: 39`, but 13 suggests a monthly or regime-bucketed count. A 16-digit figure with an unknown `n` invites a downstream model to treat it as a precise measurement. Either publish the denominator or round the value.

**Root cause** `backend/app/services/analytics_engine.py` (`hit_ratio` computation, ~`:1370` region)
**Confidence** High — both denominators verified to yield the published float exactly.

---

### AD-22 · **P2** · `sections.monte_carlo.data` — orthogonal integers published adjacently
**Observed** `num_paths: 2000`, `chunk_size_paths: 793`, `checkpoint_count: 11`, `memory_budget_elements: 50000000`. `793 × 11 = 8723`.

**Why it cannot be false** To be precise: this is **not** an arithmetic impossibility. `chunk_paths` is a memory-budget-derived chunk size and `checkpoint_count` is the number of half-year fan checkpoints — **orthogonal quantities**.
```python
# backend/app/services/monte_carlo_service.py
199:  def _checkpoint_steps(steps, checkpoints_per_year=2)   # 11 half-year columns
208:  def _chunk_path_count(num_paths, steps) -> int          # 793 from MAX_AGGREGATE_ELEMENTS
216:      return max(1, min(int(num_paths), path_cap, chunk_cap))
```
The defect is that three integers whose names invite multiplication sit in one object with **no field stating they are unrelated**. A model asked "how many paths were simulated?" may compute 8723, or divide, or report `chunk_size_paths: 793` as the path count. `NUM-013` checks quantile monotonicity and the presence of `success_definition`; nothing checks that dimensional metadata is labelled.

**Root cause** `backend/app/services/monte_carlo_service.py:432-434`
**Confidence** High — source read; orthogonality confirmed.

---

### AD-23 · **P2** · `sections.regime.data.label_overrides.crash_veto_days: 0`
**Observed** `{"crash_veto_days": 0, "crash_veto_threshold: -0.1"}` (exact: `crash_veto_threshold` is `-0.1`). `units.crash_veto_days: "count_trading_days"`, `units.crash_veto_threshold: "fraction_log_return_21d"`.

**Why it cannot be false** A **zero-length window can never fire**. The `-0.1` threshold beside it is inert, yet the block publishes both as configuration that shaped the label — and the label published is `crisis`. A reader infers a crash-veto override was evaluated and produced the label. It was not. An exact zero in a *configuration* field that disables the mechanism it accompanies.

**Root cause** the regime collector's `label_overrides` builder
**Confidence** High.

---

### AD-24 · **P2** · intra-section ordering inconsistency (determinism probe)
**Observed** The same 14-name set appears in three different orders:

| list | order |
|---|---|
| `portfolio.inputs.tickers`, `portfolio.positions`, `liquidity.by_position`, `volatility_sizing.current_weights`, `optimization.weights`, `tear_sheet.holdings`, `stress_testing…position_impacts` | insertion / `id` order (CIPLA, ELECTCAST, MOTILALOFS, …) |
| `liquidity.scoring.measured_positions`, `liquidity.observation_window.per_ticker` | alphabetical (ARROWGREEN, CIPLA, ELECTCAST, …) |
| `concentration.by_weight` | weight-descending (MOTHERSON, JUNIORBEES, MIDCAPIETF, …) |

**Why it matters** The ordering is at least **deterministic** — I found no `set` iteration and no unstable ordering, and every sort is a stable Python sort over a deterministic input, so two clean exports should agree. `concentration.by_weight` being weight-descending is deliberate. The defect is narrower: **inside the single `liquidity` section, the same 14 names are listed in two different orders** (`by_position` insertion, `observation_window.per_ticker` and `scoring.measured_positions` alphabetical). A diff-based reviewer comparing two `liquidity` blocks positionally will produce false positives, and the inconsistency is a symptom of `sorted(...)` being applied ad hoc at some call sites and not others. No rule covers intra-section list ordering.

**Root cause** `backend/app/api/analytics.py` — `_liquidity_scoring_block` uses `sorted(positions)` (`analytics.py:1975`) while `by_position` preserves upstream order
**Confidence** High — all 13 lists enumerated and compared.

---

### AD-25 · **P2** · undeclared precision drift on republished portfolio values
**Observed**

| value | full precision (portfolio) | reduced precision elsewhere | declared? |
|---|---|---|---|
| CIPLA weight | `0.06419365494291758` | `0.0642` (`optimization`, `india_flows`, `concentration.by_sector`) | `optimization` yes (`weight_decimals: 4`); **`india_flows` no** |
| CIPLA market value | `2799.39990234375` | `2799.4` (`india_flows`) | **no** |
| total value | `43608.66981063843` | `43608.67` (`monte_carlo`, `india_flows`) | `monte_carlo` yes (`round(...,2)`); `volatility_sizing` yes (`portfolio_value_decimals` + `portfolio_value_exact`); **`india_flows` no** |

**Why it matters** The codebase has a strong, consistent convention for publishing rounding precision — `concentration.by_sector_rounding_decimals: 4`, `liquidity.volume_band_rounding_decimals: 1`, `optimization.trades_required_basis.weight_decimals: 4`, `volatility_sizing.portfolio_value_decimals` **plus** `portfolio_value_exact: 43608.66981063843` **plus** `portfolio_value_rounding_residual: -0.00018936157`. That convention (both roundings published, plus the residual) is exactly right. **`india_flows` applies the same rounding and publishes none of it** — no `*_decimals`, no `*_exact`, no residual. Same defect class as AD-11. Not a wrong number; an unreconcilable one.

**Root cause** `backend/app/services/india_data_service.py` rounding sites; `backend/app/api/analytics.py` india_flows block
**Confidence** High.

---

### AD-26 · **P2** · sector taxonomy: 28.7% of the book in one catch-all bucket
**Observed** `portfolio.data.sectors` has 7 buckets, one of which is `"Exchange Traded Fund": 0.32095704728683505`, covering 4 of 14 names: NIFTYIETF (2.4%), MIDCAPIETF (**10.2%**), JUNIORBEES (12.5%), MAFANG (2.7%). `stress_testing` re-derives the same classification via `instrument_overrides` with `MIDCAPIETF.NS.sector: "Exchange Traded Fund"`, `basis: "instrument_override_midcap_etf"`, `SELECTIPO.NS.sector: "Exchange Traded Fund"`, `MAFANG.NS.sector: "Exchange Traded Fund"`.

**Why it matters** A single mid-cap ETF (MIDCAPIETF, the 3rd-largest position at 10.2%) is classified into a generic ETF bucket rather than a sector. That bucket then drives **both** `concentration.by_sector` (so `32.1%` is a taxonomy artefact, not a sector exposure) **and** the `stress_testing` sector-elasticity table — where the "Tech Sector Correction" scenario gives MIDCAPIETF the generic ETF elasticity `0.6` (impact −0.0918) while `Technology` is `1.8`. A mid-cap ETF is being modelled as a broad, low-beta index product in a tech drawdown. Four genuinely distinct exposures (a Nifty ETF, a mid-cap ETF, a junior/mid-cap ETF and a small-cap "MFANG"-style name) are collapsed into one label, and the collapse is load-bearing for both the concentration report and the stress numbers. No field discloses the taxonomy, its source, or that a single bucket spans 4 heterogeneous instruments.

**Root cause** the sector classifier's ETF fallback; `backend/app/api/analytics.py` stress `instrument_overrides` table
**Confidence** High for the values; Medium on whether the taxonomy is a deliberate documented choice (no `*_taxonomy` or `*_classification_basis` field exists to check against).

---

### AD-27 · **P2** · `0.3168` — coincidental cross-section value collision (recorded, **not** a bug)
**Observed** `factor_exposure.data.positions.SELECTIPO.NS.annualized_alpha: 0.3168` **and** `pairs.data.pairs[6].current_spread_zscore: 0.3168`, from two wholly independent computations, both rounded to 4 dp.

**Verdict** **Coincidence, not contamination.** A 4-dp collision between two independently-computed statistics in different domains is expected at this file size (1,985 distinct float leaves). Recorded so that a future cross-section value-collision detector does not spend a cycle here. `confidence` High.

*(Related, and a genuine defect: `strategy: "hrp"` in `optimization` and `methodology` in `volatility_sizing` both say **inverse-volatility** risk parity — "EWMA inverse-volatility risk parity" — while publishing `w ∝ 1/σ` and **no Euler risk-contribution decomposition**, which `volatility_sizing.methodology` states explicitly: `"not full ERC: no Euler RC_i decomposition"`. Correctly disclosed. But `optimization.strategy: "hrp"` labels the same estimator `hrp`, and `optimization` publishes **no** equivalent disclaimer, so a reader of `optimization` alone will believe it received true Hierarchical Risk Parity with Euler risk contributions. P1-adjacent; folded in here for completeness.)*

---

## (d) GAPS IN THE CHECKER — defects it does NOT catch

The tool is a **schema + arithmetic-consistency** checker. It is good at that. It has **no rule that asks whether a number is true, derived, or safe to act on.** Twelve concrete gaps, each with the rule that should exist:

| # | Gap it misses | Which findings | Proposed rule condition (plain terms) |
|---|---|---|---|
| **G1** | An annualized or standardized statistic publishes no sample size at the value. | AD-3 | **"Any leaf whose key matches `annual\|cagr\|sharpe\|sortino\|calmar\|omega\|hit_ratio` must have, in its own parent object or within two levels above it, an `observation_count`/`return_observations`/`covered_days`/`days` field, AND the section's `status` must not be `available` when that count is below a declared `minimum_observations_required` for the annualization factor used (√252 ⇒ ≥ 60 trading days, not 30)."** |
| **G2** | A derived "achieved" quantity is a tautology of its own input, published as a measurement. | AD-4 | **"Any leaf matching `achieved_*` must not be arithmetically equal (to published precision) to a sibling leaf that was supplied as an input, unless the object publishes an `*_basis` naming it as a restatement. Recompute; do not trust."** |
| **G3** | A per-record `status` contradicts the section-level gate. | AD-5 | **"If a section publishes an execution/decision gate (`execution_eligible`, `financing_required`, `blocked`, `*_veto*`) then no record inside it may carry a permissive `status`/`action`/`signal` value unless the record names the gate it satisfies."** |
| **G4** | A numeric coverage ratio of `0` sits beside a `null` count. | AD-10 | **"A numeric `coverage_ratio`/`*_ratio` of exactly 0 is forbidden in the same object as a `null` `covered_count`/`covered_symbols`. Zero is a *measured* value; an unmeasured value must be `null`."** |
| **G5** | A published score/index declares no scale and no formula. | AD-13, AD-19 | **"Every leaf matching `score\|index\|rating\|level` that is not a probability or a count must be in an object carrying both a `scale` (with min/max/unit) and a `formula` or `*_basis`. Where a sibling section publishes such a block for an analogous field, absence is a finding."** |
| **G6** | A hardcoded parameter drives a recommendation and appears in `inputs` as if it were a request. | AD-4, AD-6, AD-17 | **"Any value appearing in both `inputs` and a field that changed the result must carry a `*_provenance` in `{user_supplied, endpoint_default, exporter_hardcoded}`. A value under `inputs` that is not `user_supplied` must be restated in `warnings` when it materially changed the output (e.g. produced leverage, or a target value)."** |
| **G7** | Cross-section snapshot drift in the *values* (not just the holding-window metadata). | AD-16, AD-18 | **"For every (ticker, quantity) pair, collect all published `last_price`/`sizing_price`/`close` values across sections. If two disagree by more than a declared tolerance, emit a finding naming both paths and both observation dates — regardless of whether either section disclosed its own lag locally."** |
| **G8** | A value sits exactly on a documented clip bound / floor, presented as a measurement. | AD-11, AD-15 | **"If a block publishes `bounds`/`clip`/`floor`, count the records sitting on a bound and require that count to be published, and require `status` to drop below `available` when the count exceeds a declared share of the population. A block claiming `basis: 'measured_*'` on a record that is exactly at a clip bound is a finding."** |
| **G9** | A directive-shaped string (`signal`/`action`/`recommendation`) publishes no rule, threshold, or size ratio. | AD-1 | **"Any string matching `LONG\|SHORT\|BUY\|SELL\|HOLD\|action\|recommendation\|signal` that names specific tickers must be accompanied by the threshold that produced it, the test-agreement status of that test, the number of comparisons run, and the sizing ratio. Absent any of the four ⇒ finding."** |
| **G10** | A break/alert test is one-sided while the message asserts two-sided normality. | AD-9 | **"If a component publishes `is_regime_break`/`alert_level` plus a human-readable `message` asserting normality, the test must be two-sided: the object must also publish a lower bound, or the message must not assert normality."** |
| **G11** | A hard zero in a continuous quantity is indistinguishable from "not computed". | AD-10, AD-11, AD-23 | **"A leaf whose key implies a continuous non-negative measurement (not a count, not a price, not an id) and whose value is exactly `0` must either publish a `*_precision`/`*_floor` declaring the resolution, or be `null`. An exact `0` in a `*_basis: 'measured_*'` object is a finding."** |
| **G12** | A forward projection declares no return basis. | AD-8 | **"Any section publishing a horizon > 0 projection (`monte_carlo`, `volatility_sizing`, `optimization`) must publish a `return_basis` block naming: dividend treatment, fee/tax/slippage treatment (gross or net), rebalancing assumption, and survivorship treatment. Absence of the block is a finding, independent of the values."** |

**Bonus gaps the tool also misses, for the record:** intra-section list ordering (AD-24); undeclared republish precision where a sibling section *does* declare it (AD-25); a value duplicated under an alias suffix that reads as a second measure (AD-19); two objects both named `portfolio` carrying contradictory statistics (AD-3); a `methodology` field naming a library rather than a method (AD-3); and any rule at all requiring a *warning* — `ENV-016` fires only on `partial`/`unavailable` sections, so **every one of the 12 sections I found `available` with a disclosure problem sailed through because `available` sections are exempt from having to say anything.**

---

## (e) WHAT THE ARTIFACT GETS RIGHT (stated for fairness, and because it is what made the defects hard to see)

This export is genuinely better than most. The following are all real, verified, and should not be regressed:

- **The INR 1bn market-cap floor is fully disclosed** — `provenance: "fallback"`, `is_estimate: true`, a per-leg `market_cap_provenance`, section-level counts, *and* a warning that names every affected ticker and states the consequence ("the published score, band and liquidation window are partly derived from a substitute for a measurement"). That is the disclosure standard the rest of the file fails to meet.
- **FX provenance is per-position and honest** — `provenance: "identity"`, `is_fallback: false`, `aggregation: "per_position_conversion"`, a `pairs` map, a `rate_provider`. The `INR→INR: 1` identity rate is *proved*, not assumed.
- **The `updated_on` timezone is disclaimed rather than asserted** — "a naive datetime column … the UTC designation is an interpretation, not a stored fact."
- **`success_definition_detail` (monte_carlo)** is a model-quality disclosure most professional artifacts would pay for: it correctly distinguishes terminal from path-touching probability and states which direction the bias runs.
- **`trade_reconciliation` (volatility_sizing)** publishes the rounding *rule*, the quantum, the notional floor, the scope of every aggregate, the max residual **and its ticker**, the min/max tolerance, and a note that "a single maximum does not certify a single maximum." Exemplary.
- **`stability_pct_rule`, `gpd_shape_xi_used_rule`, `suffixed_field_rule`, `totals_note`, `counts_identity`, `provenance_rule`, `holding_context_note`, `position_impact_clip_basis`, `max_drawdown_formula`** — the codebase has genuinely learned the lesson that every derived number needs its derivation published.
- Buy-price-inferred holding starts are published **with the stored import date they displaced** (`stored_added_on: 2026-06-08` beside `buy_price_inferred: 2026-06-01`).
- `concentration`'s HHI / N_eff / Gini / top-N all reconcile to my independent recomputation. No fabrication there.

**The pattern of the failure is consistent and diagnosable:** the disclosure discipline is applied *per-collector*, and it is strong where someone has previously been burned (market caps, FX, rounding, cointegration depth) and absent where nobody has yet. The result is a file that is simultaneously exemplary and untrustworthy, and — this is the dangerous part — **a green audit that certifies the exemplary parts without noticing the rest.**

---

## (f) RECOMMENDED PRIORITY

1. **Gate the artifact.** Do not feed this to an acting agent until AD-1, AD-4 and AD-5 are fixed — those three produce *directives* ("short MCX", "achieved 15% vol", 13 × `"executable"`) rather than observations.
2. **Surface the invented goal** (AD-6): promote `target_policy` from `inputs` into `data` and into `warnings`. One line, and the single most misleading number in the file becomes honest.
3. **Publish `1.645`, `2.06` and `252`** in `forecast_risk` — or better, replace the `2.06` literal with the computed Gaussian ES multiplier and add a `cvar_basis`. The file already has the vocabulary (`*_basis`, `*_formula`, `*_rule`); `forecast_risk` simply never got the treatment.
4. **Rename `achieved_volatility`** to `target_volatility_restated`, or compute it honestly. Do not publish a tautology under a name that asserts an empirical result.
5. **Adopt G1, G2, G3, G4, G5, G9 and G11 as rules.** They are cheap, and each one alone would have caught a P0.
6. **Extend `ENV-016`**: require a *disclosure* warning from `available` sections whose own contents reveal a clamp, an estimate, a floor, or a partial universe. Today only `partial`/`unavailable` sections are obliged to speak, which is precisely backwards — `available` is where the surprises live.

---

*Report generated 2026-09-26. All findings independently recomputed from the artifact bytes; all root causes read from source. Checker verdict in §(a) is verbatim tool output, not a summary.*
