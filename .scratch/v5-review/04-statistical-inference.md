# 04 — Statistical Inference Review

**Artifact:** `C:\es\others things\finengine-portfolio-ai-context v5.json` (876,445 bytes, `export_id portfolio-4b78905b588c`, `schema_version 2.0`, `base_currency INR`, 14 holdings, 17 sections)
**Reviewer scope:** sample sizes, degrees of freedom, significance testing, multiple comparisons, effective sample size, honesty of published confidence levels.
**Reviewer stance:** academic referee. Not checking arithmetic — checking whether the inference is defensible and whether it is honestly labelled.

---

## Verdict

**Is the inference defensible as statistical reasoning? No.** The artifact publishes on the order of 2,000 point estimates and contains, in 876 KB of JSON, **zero** standard errors, **zero** confidence intervals on any estimated parameter, **zero** autocorrelation diagnostics, and **zero** multiple-testing corrections — verified by literal string search: `standard_error` 0 hits, `std_err` 0, `stderr` 0, `conf_int` 0, `ci_low`/`ci_high` 0, `multiple_testing` 0, `bonferroni` 0, `benjamini` 0, `fdr` 0, `family_wise` 0, `autocorrel` 0, `newey` 0, `HAC` 0, `effective_n` 0. The only `pvalue` field in the entire export is the 91 Engle-Granger pair p-values. This is not a stylistic gap; it is the difference between a number and a measurement. The single worst instance is the `pairs` section: 91 uncorrected cointegration tests produce exactly 4 "discoveries" against a by-construction null expectation of 4.55, the p-value distribution is statistically indistinguishable from Uniform(0,1) (one-sample KS D=0.1311, p=0.0799 — cannot reject uniformity), and both Bonferroni and Benjamini-Hochberg FDR at q=0.05 leave **zero** survivors. The section nevertheless publishes `cointegrated_pairs_count: 4` and 2 actionable `SHORT_SPREAD`/`LONG_SPREAD` trading signals derived from those discoveries. Separately, `tear_sheet` publishes Sharpe **3.4876**, Sortino **5.3147**, Calmar **20.1891** and CAGR **42.97%** on **39 daily observations** with `warnings: []` and `status: "available"`; the Sharpe's own t-statistic against zero is **0.516 (p = 0.606)** and its 95% CI is **[−9.77, +16.75]**. A third P0: `forecast_risk` publishes a field literally keyed `confidence_interval` whose value is a hardcoded ±20% multiplier on a point forecast.

**Is it honestly labelled? Partially, and the failures are concentrated in a specific pattern.** The disclosure engineering is *good where it exists* and *absent where it matters most*. `regime` publishes `transition_matrix_provenance: {estimated: false}` and states that its sticky diagonal is a prior; `regime.portfolio_in_current_regime` correctly **withholds** `ann_ret`/`ann_vol` at n=19 and publishes the minimum it would need; `stress_testing` labels its nominal 0.95 as `confidence_basis: "nominal_label_not_simulated"` with `units.confidence_level: "unitless_nominal_label"`; `monte_carlo` ships a 6-line `success_definition_detail` distinguishing terminal from path-touching probability; `pairs` publishes `test_roles`, `decision_test`, `johansen_role` and an explicit `summed_count_note` warning that the two test counts must not be added. That is genuinely above-average. But the disclosure effort is aimed at *unit and coverage* problems, not at *inferential* problems. The `pairs` warning discloses sample-depth asymmetry and says nothing about running 91 tests; the `tear_sheet` section has an empty `warnings` array on a 39-observation Sharpe; and the artifact contains a **direct internal contradiction** on confidence labelling — `stress_testing` gets the "nominal, not simulated" disclosure right while `forecast_risk` publishes a hardcoded ±20% band under the key `confidence_interval` in the same export. An AI agent reading this artifact will treat every flagged anomaly as signal, because nothing in the payload distinguishes a finding that survived multiplicity from one that did not.

**Bottom line for the integrator:** the artifact's *arithmetic* is largely sound (I reproduced the CAGR, the p-values, the beta, the 1.15× stress uplift and the weights sum exactly). Its *inference* is largely absent, and its *labelling of inference* is inconsistent in a way that correlates with how much work the answer looked like it took. Rank the P0s below; SI-1, SI-2 and SI-3 are the ones that change what a reader should conclude.

---

## Findings, ranked

---

### SI-1 · P0 · 91 uncorrected cointegration tests; the "discoveries" are numerically indistinguishable from the null

**JSON path:** `sections.pairs.data` (`scanned_pairs_count`, `cointegrated_pairs_count`, `pairs[]`), `sections.pairs.inputs.p_value_threshold`

**Observed.** 14 tickers → C(14,2) = **91** pairs, each subjected to (i) an Engle-Granger two-step test whose p-value decides, and (ii) a Johansen trace rank-0 test at the 95% critical value which is counted in `test_agreement`. `p_value_threshold: 0.05`. Published: `cointegrated_pairs_count: 4`, `returned_cointegrated_pairs_count: 4`, plus two directional trade signals (`ELECTCAST.NS/MCX.NS` → `LONG_SPREAD`, `JUNIORBEES.NS/MIDCAPIETF.NS` → `SHORT_SPREAD`). **No multiple-testing correction is applied and none is declared.** String search over the whole 876 KB: `bonferroni` 0, `benjamini` 0, `fdr` 0, `family_wise` 0, `multiple_testing` 0. The section's single warning is about *depth*, not multiplicity:

> "Depth-limited pairs: 13 of 91 delivered pairs ran on less than 75% of the deepest pair's overlap… Their Engle-Granger p-values, Johansen ranks and OU half-lives rest on that shorter sample, so they are weaker evidence than the full-depth pairs and the scan is reported as partial."

**Expected + recomputation evidence.**

```
$ cd C:\es\coding\finengine\backend
$ uv run python -c "import json,numpy as np;from scipy import stats; ..."
```
```
N = 91
EG p-value: min 0.002609  max 0.990682  mean 0.4654  median 0.3890
EG p<0.05 : 4   expected by chance at alpha=0.05: 4.55
EG p<0.10 : 7   expected: 9.10
EG p<0.01 : 1   expected: 0.91

UNIFORMITY OF p-VALUES (null: all pairs non-cointegrated -> p~U(0,1))
  KS D=0.1311  p=0.0799      <-- CANNOT REJECT UNIFORMITY

  alpha=0.010  obs= 1  expected=  0.9  binom p=0.599
  alpha=0.025  obs= 2  expected=  2.3  binom p=1.000
  alpha=0.050  obs= 4  expected=  4.5  binom p=1.000
  alpha=0.100  obs= 7  expected=  9.1  binom p=0.600

MULTIPLE-TESTING CORRECTION ON 91 ENGLE-GRANGER PAIR TESTS
Bonferroni alpha = 0.05/91 = 0.000549
pairs surviving Bonferroni: 0 -> []
BH-FDR q=0.05 discoveries: 0 -> []

EMPIRICAL NULL CALIBRATION: what if NO pair is cointegrated?
  EG positives observed  : 4  | expected under pure null: 4.55 | Poisson P(X=4) = 0.189
  Johansen positives obs : 4  | expected under pure null: 4.55 | Poisson P(X=4) = 0.189
  union of either test   : 8  | expected under pure null: 8.87 | Poisson P(X=8) = 0.134
```

The empirical distribution of the 91 published p-values **is a uniform distribution on [0,1]**. The observed count of "significant" pairs (4) is the null expectation (4.55) almost exactly, and the KS test cannot reject the hypothesis that the scan found nothing. This is not a borderline call — the data are fully consistent with zero cointegrated pairs among these 14 names over a 252-day window, which is exactly what theory predicts for a set of Indian large/mid-cap equities with strong common market factors over 8 months.

**The finding must be stated strongly, and one caveat cuts *against* my own argument being merely conventional:** the 91 tests are not independent. 14 tickers generating 91 pairs share endpoints, so the effective number of independent tests is closer to 14 than to 91. Under-dependence therefore *over*-states the false-positive expectation, which makes the observed 4/91 **more** damning, not less. The section's own `test_agreement` block is the smoking gun it does not see: `decision_positive_count: 4` and `diagnostic_positive_count: 4` from two *different* tests, with `disagreement_count: 8` and `decision_positive_pairs ∩ diagnostic_positive_pairs = ∅` (zero overlap). Two tests of somewhat different nulls each producing exactly 4/91 positives and **no pair flagged by both** is the signature of two independent 5%-level noise generators, not of a real cointegrating structure.

**Root cause.** `app/api/analytics.py:6756-6830` — `_disclosure()` handles currency provenance and depth only; there is no branch that emits a family-size or multiplicity warning. `app/services/cointegration_service.py:46-48` and `:67-70` — the `DECISION_TEST`/`DIAGNOSTIC_TEST`/`TEST_ROLES` contract declares *which* test decides but carries no family size and no correction. `app/services/cointegration_service.py:823` — `CointScannerResponse` is returned with `scanned_pairs_count` and `cointegrated_pairs_count` as bare scalars, giving the consumer no denominator to reason with.

**Confidence: high.** The p-values are internally verifiable (see SI-14 for the verification that they are the right test's p-values), the uniformity result is a standard exact test, and the correction arithmetic is deterministic.

**Fix direction.** Publish the family size alongside the count, apply BH-FDR across the 91 (which yields zero discoveries and should therefore flip `data_status` and suppress the trade signals), and state the null expectation in the warning. Do not ship `SHORT_SPREAD`/`LONG_SPREAD` on a pair that does not survive correction.

---

### SI-2 · P0 · Sharpe 3.49 / Sortino 5.31 / Calmar 20.19 / CAGR 43% published on n=39 with an empty warnings array

**JSON path:** `sections.tear_sheet.data.metrics`, `sections.realized_risk.data.portfolio`, `sections.dashboard.data.components.summary.data`

**Observed.** `sections.tear_sheet.status = "available"`, `sections.tear_sheet.warnings = []`, `data.annualized = true`, `data.observation_count = 39`, and:

```json
"metrics": { "total_return": 0.056879, "cagr": 0.429686, "sharpe": 3.487604,
             "sortino": 5.314715, "calmar": 20.189083, "omega": 1.916946,
             "tail_ratio": 1.172416, "volatility": 0.098238,
             "max_drawdown": -0.021283, "skew": -0.743865, "kurtosis": 2.622096 }
```

`sections.realized_risk.data.portfolio` repeats `sharpe_ratio: 3.4856`, `sortino_ratio: 5.3113`, `annual_return: 0.3624`. The block that carries the headline Sharpe has **eleven numeric fields and not one of them is a window or an observation count** — `n=39` lives two levels away in `data.positions.*.data_points` and in `data_range`.

**Expected + recomputation evidence.**

```
=== SHARPE INFERENCE (analytical, Lo 2002) ===
  SR_ann=3.4876  n=39  n_years=0.1548
  asymptotic SE(SR_ann) = sqrt((1+SR^2/2)/n_years) = 6.7645
  t = SR/SE = 0.5156   two-sided p = 0.6062
  95% CI = [-9.771, 16.746]  -> contains 0: True
  => a 39-observation Sharpe needs n>=564 days for the 95% CI half-width to be <= SR itself.

=== CAGR is pure extrapolation, verified ===
  PUBLISHED cagr = 0.4297
  verify: (1+0.056879)^(252/39)-1 = 0.429684   MATCHES
  -> 5.69% over 39 days, compounded 6.46x, reported as a 42.97% "annualized" CAGR.

=== CALMAR inherits it ===
  0.4297 / 0.0213 = 20.19  (published calmar)

=== SKEW / KURTOSIS on n=39 ===
  skew    = -0.7439  SE=0.3922  t=-1.896  p=0.0655  -> NOT significant at 5%
  kurtosis=  2.6221  SE=0.7845  t= 3.343  p=0.0019  -> significant

=== ORDER-STATISTIC SUPPORT FOR THE TAIL METRICS ===
  5th pct of 39 pts -> order-stat position 1.95 ; 95th pct -> 37.05
  tail_ratio = a ratio of two order stats each supported by ~2 observations
  CVaR95     = the mean of the worst 5% of 39 = 1.95 observations
  VaR95      = sits at order-stat position 1.95 of 39
```

The Sharpe is **not statistically distinguishable from zero** (t = 0.52, p = 0.61). To make the 95% CI half-width of an annualized Sharpe no larger than the Sharpe itself you need ~564 daily observations; the artifact has 39. `Sortino = 5.31` has no finite-sample correction and is maximally unstable over a 39-point sample with a 2.13% maximum drawdown. `Calmar = 20.19` is a direct arithmetic consequence of annualizing a 6-week return. `tail_ratio = 1.1724` divides two order statistics each supported by ~2 data points.

**The Sharpe is also not reproducible from the only return series the artifact publishes.** `sections.dashboard.data.components.performance_history` ships 19 rows of `portfolio_value` / `benchmark_value` (18 usable returns), `status: "partial"` — and nothing else in the export contains a daily return series:

```
=== SHARPE REPRODUCIBILITY: published n=39 headline vs the only published return series (n=18) ===
  PUBLISHED tear_sheet.metrics.sharpe           = 3.4876  (measured_window.days = 39, status=available, warnings=[])
  PUBLISHED realized_risk.portfolio.sharpe     = 3.4856
  RECOMPUTED on the 18 published daily returns = 0.9309   -> 3.75x lower
```

A 3.75× discrepancy between the published headline and the only auditable series in the same export. The 18-day sub-window also implies an annualized volatility of **0.1069** against the published 39-day **0.0982** — i.e. the first 18 of the 39 days are *more* volatile than the whole window, so the 3.49 is being manufactured by an unusually quiet tail.

**Root cause.** `app/utils/holdings.py:35` — `MIN_ANNUALIZE_DAYS = 30`. This is the gate that decides whether a CAGR-style annualization is emitted at all, and it is applied to Sharpe, Sortino, Calmar, omega and tail ratio as well as to CAGR. Thirty daily observations cannot support *any* annualized ratio. The gate is doing exactly what it was coded to do; **the gate is the defect.** `app/utils/holdings.py:443-446` even documents the intent ("so a week-old book can never display a triple-digit 'annualized' artefact") — and 39 observations produces exactly the triple-digit artefact the docstring was written to prevent, because 39 is close enough to 30 to clear the gate. `app/api/analytics.py:680-690, 826-842, 991` — `minimum_observations_required: MIN_ANNUALIZE_DAYS` is published as 30, which advertises the defect as a feature.

**Confidence: high** on the inference (closed-form Lo 2002 SE; the arithmetic reproduces the published CAGR exactly). **Medium** on the 3.75× reproducibility gap, because the 18 published days are a subset of the 39 and the export does not publish the mapping — but the gap is far too large to be subsetting noise, and the direction is consistent (the sub-window is more volatile).

**Fix direction.** Split the gate: a distribution-free metric (`total_return`, `max_drawdown`) needs n ≥ 2; a variance-based annualized ratio needs n ≥ 250; a ratio of two annualized quantities (Sharpe, Sortino, Calmar, information ratio) should be **withheld entirely** below ~500 daily observations, exactly as `regime.portfolio_in_current_regime` correctly withholds at n=19. Publish the Sharpe with its SE and CI, or publish `null` with the reason.

---

### SI-3 · P0 · `confidence_interval` is a hardcoded ±20% multiplier

**JSON path:** `sections.forecast_risk.data.portfolio.confidence_interval`

**Observed.**

```json
"portfolio": { "volatility_forecast": 0.13767283267201857,
               "var_forecast": -0.014266383036982124,
               "cvar_forecast": -0.01786550094600801,
               "confidence_interval": [0.11013826613761486, 0.16520739920642227],
               "term_structure": [0.13767283267201857], ... }
```

Check the arithmetic: `0.13767283 × 0.8 = 0.11013827` ✓ and `0.13767283 × 1.2 = 0.16520740` ✓. The "confidence interval" is `[0.8 × point, 1.2 × point]`.

**Expected.** A field named `confidence_interval` must declare (a) the confidence **level**, (b) the sampling or model basis, (c) the sample size, and (d) whether it is one- or two-sided. None of the four is present anywhere in the payload. The forecast is a **GARCH(1,1) point estimate** (`"model": "GARCH"`, `"horizon": 1`, `observations: 174`) published with no parameter estimates, no convergence flag, no log-likelihood, no persistence estimate, no backtest, and no forecast standard error. A GARCH(1,1) fitted to 174 observations has a multi-day-ahead forecast variance whose sampling error typically exceeds ±20%; the width here is a constant that would be identical for a well-specified model on 5,000 observations and a misspecified one on 50.

**This is aggravated, not excused, by the rest of the artifact.** The *same export* contains a section that gets this exactly right:

```
sections.stress_testing.data.scenarios.*.confidence_level  = 0.95
sections.stress_testing.data.scenarios.*.confidence_basis  = "nominal_label_not_simulated"
sections.stress_testing.data.scenarios.*.units.confidence_level = "unitless_nominal_label"
sections.stress_testing.data.scenarios.*.methodology = "... confidence_level is a nominal 0.95 label with no simulated distribution behind it"
```

The codebase demonstrably knows the difference between a nominal label and a confidence interval, discloses it rigorously in `stress_testing`, and then omits it entirely in `forecast_risk`. That inconsistency — not the hardcoded 0.8/1.2 by itself — is what makes this indefensible rather than merely crude.

**Root cause.** `app/services/analytics_engine.py:1577-1580`, duplicated at `:1649-1652` and `:1696-1699`:

```python
"confidence_interval": [
    max(0.0, float(vol_final * 0.8)),
    float(vol_final * 1.2)
],
```

Surfaced at `app/api/analytics.py:3181` — `"confidence_interval": forecast_result.get("confidence_interval")`. Schema: `app/models/schemas.py:276` — `confidence_interval: List[float]`, with no companion level or basis field.

**Confidence: high.** The 0.8/1.2 identity is exact to all 17 published digits.

**Fix direction.** Rename to `nominal_band_multipliers: [0.8, 1.2]` with a `basis` string, or replace with a real forecast interval (simulation-based quantiles of the GARCH one-step-ahead distribution, which for a fitted GARCH is trivial: sample from the fitted conditional distribution). Either way, never ship the key `confidence_interval` without a level.

---

### SI-4 · P0 · A 95% expected shortfall computed from ~2 observations, published with no n and no CI

**JSON path:** `sections.realized_risk.data.portfolio.var_95`, `.cvar_95`, `.skewness`, `.kurtosis`, `.hit_ratio`

**Observed.**

```json
"portfolio": { "annual_return": 0.3624171632380964, "annual_volatility": 0.09823756813755412,
               "sharpe_ratio": 3.4856030104352476, "sortino_ratio": 5.311263195097079,
               "skewness": -0.7438649924965621, "kurtosis": 2.6220959888856123,
               "max_drawdown": -0.021283071327123593, "var_95": -0.007779716667611284,
               "cvar_95": -0.015381334680204901, "hit_ratio": 0.6153846153846154,
               "annualized": true }
```

**Expected.** On n=39, a 95% VaR is the empirical quantile at order-statistic position `0.05 × 39 = 1.95` — i.e. interpolated between the 1st and 2nd worst of 39 days. A 95% expected shortfall is the mean of the worst `0.05 × 39 ≈ 2` days. The sampling error on a quantile at position 2 of 39 is enormous: the 95% CI on the 2nd order statistic of 39 draws spans roughly the entire [-4%, +2%] daily range. Publishing `-0.015381` as `cvar_95` with no observation count, no CI, and no `var_95_period` field is the "95% CI from 5 Monte Carlo paths" failure mode in its historical-simulation form. The block-level `"annualized": true` is also actively misleading: `var_95`, `cvar_95`, `max_drawdown` and `hit_ratio` are all un-annualized daily/period quantities, while `annual_volatility` is annualized ×√252. A reader taking the block flag at face value would annualize the VaR to −12.3%.

**This same codebase suffixes the field correctly elsewhere**, which makes the omission a defect rather than a house style:

```
sections.risk_contribution.data.portfolio_var_95_daily    = -0.018244   <- correct suffix
sections.risk_contribution.data.portfolio_cvar_95_daily   = -0.025175   <- correct suffix
sections.risk_contribution.data.portfolio_volatility_annualized =  0.178900
sections.realized_risk.data.portfolio.var_95              = -0.007780   <- unsuffixed, in an "annualized": true block
sections.realized_risk.data.portfolio.cvar_95             = -0.015381   <- unsuffixed
```

Three 95% VaRs are published for the same portfolio on three different windows (−0.007780 at n=39, −0.019318 at n=175, −0.018244 at n=251) with no cross-reference and no statement of which is authoritative.

**Root cause.** The realized-risk portfolio block is assembled without a per-block observation count or a period suffix. Compare `app/api/analytics.py:3024, 3044, 3068, 3185` (risk_contribution, which publishes `..._daily` and `..._annualized` explicitly and states `minimum_observations_required`) against the realized-risk `portfolio` block, which publishes `"annualized": true` as a single blanket flag over mixed units. The historical-VaR helper has no minimum-observation gate for the ES specifically — the 30-day gate in `app/utils/holdings.py:35` is the only one, and 39 clears it.

**Confidence: high** on the order-statistic arithmetic (deterministic given n=39). **High** that no CI exists (string search).

**Fix direction.** Rename to `var_95_daily` / `cvar_95_daily`, attach `observations: 39` inside the block, and withhold the ES below ~250 observations (a 95% ES needs ≥ 20 tail observations to mean anything, i.e. n ≥ 400). If it must be published at n=39, publish `cvar_95_daily_supporting_observations: 2`.

---

### SI-5 · P0 (systemic) · 495 hypothesis tests with a stated α, zero corrections, zero uncertainty anywhere in the export

**JSON path:** artifact-wide

**Observed.** Full census of hypothesis tests with an explicit significance level, across all 17 sections:

| Section | Test family | n | α | Correction |
|---|---|---:|---:|---|
| `pairs` | Engle-Granger cointegration (2-sided asymptotic p) | 91 | 0.05 | **none** |
| `pairs` | Johansen trace rank-0 vs 95% critical value | 91 | 0.05 | **none** |
| `factor_exposure` | OLS alpha/beta vs benchmark, 14 positions + 1 portfolio | 15 | 0.05 | **none** |
| `factor_exposure` | HAC lag-5 Newey-West inference (SEs computed, discarded) | 15 | 0.05 | **none** |
| `dashboard.risk_score` | factor leg R² → "High unexplained risk" alert | 1 | 0.05 (threshold **unpublished**) | **none** |
| `risk_studio.tail_dependence` | POT/GPD 99% VaR and ES on k=26 exceedances | 2 | 0.01 | **none** |
| `monte_carlo` | prob_success = 743/2000 paths ≥ 2× target | 1 | — | **none** |
| `regime` | Gaussian HMM (3 states, 15 free params, n=719) | 1 | — | **none** |
| `regime` | per-state ann_ret / ann_vol (n **undeclared**) | 6 | — | **none** |
| `regime` | `crash_veto_threshold = -0.1` post-hoc relabel rule | 1 | — | **none** |
| `risk_studio.vol_cone` | GARCH(1,1) forecast vs 21d cone | 1 | — | **none** |
| `india_flows.delivery_anomalies` | 2σ delivery z-tests (**latent**, component unavailable) | 280 | 0.0455 | **none** |

**Total with a stated α: 495. Corrections declared: 0.**

**Expected + recomputation evidence.** Literal string search over the 876,445-byte file:

```
autocorrel           0        multiple_testing    0        fdr                0
newey                0        bonferroni          0        family_wise        0
HAC / " HAC" / hac_  0        benjamini           0
ar1                  0        effective_n         0   (2 hits, both the string "N_eff" in a concentration methodology note)
standard_error       0        std_err / stderr    0
conf_int             0        ci_low / ci_high     0
pvalue              91        p_value              1   (the input p_value_threshold itself)
```

`india_flows.inputs.component_inputs.delivery_anomalies` declares `sigma_threshold: 2`, `lookback_days: 20`, `requested_symbol_count: 14`. If that component had been available it would have run 20 × 14 = **280** one-sided 2σ tests with an expected **12.7** false anomalies. This is a *latent* design defect — the component is `unavailable` in this export, so I flag the design, not an observed error.

The raw-string check is the finding. An AI context artifact's job is to let a downstream agent distinguish signal from noise. This one publishes ~2,000 point estimates, 495 nominal-α tests, and not one number that quantifies the noise floor. Everything a reader takes from it is a point estimate presented with the visual authority of a measurement.

**Root cause.** No cross-cutting inference-disclosure layer exists. `app/services/ai_context_service.py` assembles the 17 sections and each section's own `_disclosure()` (e.g. `app/api/analytics.py:6756-6830`) covers *unit* and *coverage*; none covers multiplicity, effective sample size, or estimator uncertainty. The omission is structural, not per-section negligence.

**Confidence: high** (literal string search is conclusive).

---

### SI-6 · P1 · 99% VaR and ES from 26 GPD exceedances, with the shape parameter clipped against a significant rejection

**JSON path:** `sections.risk_studio.data.components.tail_dependence.data`

**Observed.** `confidence_level: 0.99`, `total_observations: 518`, `exceedances_count: 26`, `gpd_shape_xi_raw: -0.70676185`, `gpd_shape_xi_constrained: -0.5`, `gpd_shape_xi: -0.7068`, `gpd_shape_xi_used: -0.5`, `gpd_shape_xi_basis: "constrained_clip"`, `constraint_reason: "gpd_shape_clipped"`, `metrics_valid: true`, `raw_fit_valid: true`, `is_fat_tailed: true`, `evt_pot_var_99: -0.036708`, `evt_pot_es_99: -0.041074`, `historical_var_99: -0.031724`, `historical_es_99: -0.036539`. No confidence interval on any of the four.

**Expected + recomputation evidence.**

```
=== GPD SHAPE: the clip is imposed AGAINST a significantly-outside-the-boundary estimate ===
  k=26 exceedances, raw ML xi = -0.70676
  asymptotic SE(xi_hat) = sqrt((1+xi)^2/k) = 0.05751
  95% CI for xi = [-0.8195, -0.5940]
  t-test of raw xi against the clip boundary -0.5: t=-3.595  p=0.00145
  -> the raw fit is SIGNIFICANTLY below the boundary, yet the artifact publishes
     metrics_valid=true, raw_fit_valid=true, constraint_applied=true.

  propagation: 99% GPD excess quantile vs xi (beta fixed at 0.014671, p=0.99)
    xi=-0.7068 -> q99=0.019956   xi=-0.60 -> 0.022909
    xi=-0.5500 -> q99=0.024556   xi=-0.5000 -> q99=0.026408
  moving xi from the used -0.50 to the raw -0.7068 changes the 99% level by
  0.006451 (18% of the published evt_pot_var_99 magnitude).

=== parametric bootstrap of the 99% GPD quantile, k=26, B=20000 ===
    sd = 0.002431   95% CI width = 0.009247 = 25% of the published evt_pot_var_99 magnitude
    the EVT-vs-historical gap (0.004984) is 0.9x the 95% CI half-width (0.004623).
```

The entire point of this component is the comparison `evt_pot_var_99` (−0.036708) vs `historical_var_99` (−0.031724) — a 0.004984 gap that the section presents as a finding. The resampling uncertainty on the 99% GPD quantile at k=26 is of the same order. And the constraint that produces the published number is not a neutral regularisation: the raw ML shape is **significantly** below the −0.5 boundary (p = 0.0015), so the clip is not merely "the fit wandered outside the admissible region", it is the code overriding a statistically significant result without saying so. `is_fat_tailed: true` is derived from the *clipped* ξ. `metrics_valid: true` and `raw_fit_valid: true` are both published and neither discloses that the raw fit is significantly inadmissible.

**Root cause.** `app/services/` tail-dependence GPD fitter — the `constrained_clip` on `gpd_shape_xi` and the `gpd_shape_xi_used` selection. (The disclosure *around* it is unusually good: `pot_threshold_basis` and `gpd_shape_xi_used_rule` both explain that the fitting threshold and the reported confidence level are deliberately different, and that the reported risk was computed from the constrained moments. The disclosure is thorough about *which* parameter was used and silent about *whether the constraint was warranted*.)

**Confidence: high** on the ξ inference (standard GPD asymptotic variance, k=26). **High** that no CI is published. **Note honestly:** my bootstrap reproduces the *uncertainty scale*, not the published point estimate (my resampled 99% quantile centres at 0.0441 vs the published 0.0367, because the published figure is `max`'d against a historical floor and the loss orientation differs). The width, not the centre, is the transferable quantity.

**Fix direction.** Publish the ξ clip as a *test result* (`xi_clip_rejection_t: -3.60`, `xi_clip_p: 0.0015`) so a reader can see the constraint was imposed against the data, and publish a bootstrap or sandwich interval on the 99% quantile. Do not present a 0.5 pp EVT-vs-historical difference as a result at k=26.

---

### SI-7 · P1 · Volatility-cone percentile ranks computed over overlapping windows; the 252-day rank rests on ~9 effective observations

**JSON path:** `sections.risk_studio.data.components.volatility_cone.data.windows[]`, `.current_forecast`

**Observed.** Source series `sections.tear_sheet.data.full_history.observation_count = 2486`. Five windows, each publishing `min`, `p25`, `median`, `p75`, `max`, `current_realized`, `percentile_rank`, `insufficient_data`. **No window count, no effective count, no overlap note in the schema.**

```
  w_days n_windows n_eff(iid) p25      median   pct_rank  insufficient_data
  10     2477      247.7     0.1135   0.1537   50.7      false
  21     2466      117.4     0.1279   0.1662   17.5      false
  63     2424       38.5     0.1358   0.1913    2.9      false
  126    2361       18.7     0.1567   0.2102   25.7      false
  252    2235        8.9     0.1819   0.1858    1.9      false

  95% half-width on a percentile RANK, at each effective n:
     w=10   n_eff= 247.7  +/-  6.2 pct-points
     w=21   n_eff= 117.4  +/-  9.0 pct-points
     w=63   n_eff=  38.5  +/- 15.8 pct-points
     w=126  n_eff=  18.7  +/- 22.6 pct-points
     w=252  n_eff=   8.9  +/- 32.9 pct-points
```

**Expected.** A rolling-L realized-volatility series over T observations yields T−L+1 **overlapping** windows sharing (L−1)/L of their data. Under iid returns the effective count is (T−L+1)/L. The published `percentile_rank: 1.9` for the 252-day window — the section's most striking claim ("current 252-day realized vol is at the 1.9th percentile of its own history", i.e. essentially the calmest in a decade) — carries a 95% resampling half-width of **±32.9 percentage points**. "1.9" is not distinguishable from 17, or from 35, or from 50. The `insufficient_data: false` flag is structurally incapable of catching this: see the gate below.

`current_forecast` adds a GARCH(1,1) point forecast `annualized_vol: 0.1519` with no standard error, no parameters, no convergence flag, no log-likelihood, and no backtest, ranked at `percentile_rank: 45` against the 21-day cone and labelled `valuation: "normal"`.

**Root cause.** `app/services/volatility_service.py:252` — the only gate on publishing five quantiles plus a rank is `if len(rolling_vol) >= 2:`. At `len == 2` the code publishes a `median`, a `p25`, a `p75`, a `min`, a `max` and a `percentile_rank: 50.0`. `app/services/volatility_service.py:261` — `rank = np.sum(vol_values <= curr_v) / len(vol_values) * 100.0` counts overlapping windows as independent. `app/models/schemas.py:572, 580` — `VolConeWindow` has no count or effective-count field, so the omission is baked into the contract. Same pattern at `:311` for `forecast_rank`.

**Confidence: high** (the VIF result is standard; the gate is a two-line read).

**Fix direction.** Publish `n_windows` and `n_effective = n_windows / window_days` per window, raise the quantile gate from 2 to a defensible minimum, and either drop `percentile_rank` for windows where the effective count is under ~30 or publish its interval. A 252-day cone built on 2486 observations is a nine-observation statistic wearing a 2486-observation costume.

---

### SI-8 · P1 · Monte Carlo probability with no error bar, resting on a mean return whose t-statistic is 0.93; `expected_shortfall_vs_target` has no level and is not a tail expectation

**JSON path:** `sections.monte_carlo.data`

**Observed.** `num_paths: 2000`, `seed: 42`, `model_observations: 500`, `model_minimum_observations: 60`, `prob_success: 0.3715`, `historical_mu_annual: 0.1297`, `historical_sigma_annual: 0.1972`, `student_t_df: 4.51`, `expected_shortfall_vs_target: -26732.4`, `terminal_percentiles: {p5..p95}`, `fan: 11 rows × 5 percentiles`.

**Expected + recomputation evidence.**

```
  prob_success=0.3715  implied k/Np = 743/2000  MC (binomial) SE = 0.0108
  95% MC CI = [0.3503, 0.3927]      <-- NOT PUBLISHED

  PARAMETER uncertainty (the DOMINANT term, also unpublished):
    mu_ann=0.1297  sigma_ann=0.1972  n_daily_returns=500 (1.984 years)
    SE(mu_ann) = sigma/sqrt(n_years) = 0.1400
    t(mu>0) = 0.926   p = 0.3542
    95% CI for mu_ann = [-0.1447, 0.4041]  -> contains 0: True
    95% CI for sigma_ann (chi-square) = [0.1859, 0.2105]  (width 12.5% of the point estimate)
    student_t_df = 4.51  -> NO confidence interval on df is published.
```

The section publishes 0 warnings and `status: "available"`. Two distinct uncertainties are omitted:

1. **Monte-Carlo error** on `prob_success`: binomial SE = 0.0108, a 95% interval of [0.3503, 0.3927]. Cheap to publish, never published. 55 percentiles across `fan` + `terminal_percentiles` also carry no MC error bars.
2. **Parameter error**, which dominates by an order of magnitude. The entire 5-year, 37.15% "chance of doubling" rests on `historical_mu_annual = 0.1297` estimated from 500 daily returns (1.98 years). Its t-statistic against zero is **0.926, p = 0.354**; its 95% CI is **[−14.5%, +40.4%]** and comfortably contains zero. `student_t_df = 4.51` is a heavy-tail parameter with enormous estimation uncertainty at n=500 and no interval. A reader is given 37.15% to four significant figures with no indication that the underlying drift could plausibly be negative.

**`expected_shortfall_vs_target` is uninterpretable as labelled.** Root cause `app/services/monte_carlo_service.py:380-383`:

```python
failing = terminal[terminal < target_value]
expected_shortfall = round(float(failing.mean() - target_value), 2) if len(failing) else 0.0
```

This is the **unconditional mean shortfall over failing paths only** — a conditional expectation at the `1 − prob_success = 62.85`th percentile, not a tail expectation. Standard expected shortfall is `E[X | X ≤ VaR_α]` for a stated α; a reader will parse "expected shortfall" as a 95%-tail number. The magnitude is misleading in the *safe* direction (−26,732 reads as a modest tail loss when it is a near-median conditional mean), but the label is wrong, and the payload publishes **no α, no conditioning event, no n, no CI and no units field** for it. `monte_carlo_service.py:428` is the only place it appears.

**Clean in this section:** `num_paths: 2000` and `seed: 42` are published (genuinely reproducible), `model_observations: 500` and `model_minimum_observations: 60` are published, and `success_definition_detail` is a six-line, correct explanation that `prob_success` is a *terminal* statistic and a lower bound on any path-touching probability. That is exactly the disclosure discipline the rest of the artifact is missing.

**Confidence: high.**

---

### SI-9 · P1 · 30 regression coefficients published with HAC standard errors computed and then discarded; `annualized_alpha` uses linear annualization

**JSON path:** `sections.factor_exposure.data.portfolio`, `.positions.*`, `.r_squared`, `.adjusted_r_squared`

**Observed.** 14 per-position `{alpha, annualized_alpha, market, data_points}` plus `{portfolio: {alpha, annualized_alpha, market}, r_squared, adjusted_r_squared}`. `status: "available"`, `warnings: []`.

**Expected + recomputation evidence.** The code fits every one of these regressions with Newey–West HAC standard errors at lag 5 — the correct tool for exactly the autocorrelation concern at issue — and then publishes only the point estimates:

```
app/services/analytics_engine.py:1750
    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
...
app/services/analytics_engine.py:1759-1767
    positions_exp[ticker] = {
        'alpha': round(alpha, 6) ...,
        'annualized_alpha': round(alpha * 252.0, 4) ...,
        'market': round(beta, 4) ...,
        'data_points': data_pts, ... }          # <- no bse, no tvalues, no pvalues, no conf_int
```

`model.bse` and `model.pvalues` are computed by statsmodels and discarded three lines later. The identical pattern repeats for the portfolio model at `:1789-1801`. Two further defects in the same block:

- **`:1751-1752` and `:1787-1788` — silent inference downgrade.** `except Exception: model = sm.OLS(y, X).fit()` falls back to **iid** standard errors on the same code path. Because the SEs are discarded anyway the fallback is invisible, but it proves the inference basis is nondeterministic and undisclosed.
- **`:1761` and `:1796` — linear annualization of a daily alpha.** `'annualized_alpha': round(alpha * 252.0, 4)`. For the published portfolio `alpha = 0.002042`, linear annualization gives **0.5146** (the published value); correct compounding `(1+0.002042)^252 − 1` gives **0.6719**. The codebase uses the correct geometric form elsewhere — `app/services/regime_service.py:238` and `app/utils/holdings.py:465` both compute `(cum ** (252.0/n)) - 1` — so this is an inconsistency, not ignorance.

The 15 alpha estimates are also never tested, so "this holding has positive alpha" is asserted 15 times with no standard error, and no multiplicity correction (SI-5).

**Root cause.** `app/services/analytics_engine.py:1750-1767` and `:1786-1801`. The fitting is careful; the *publication* is what drops the inference.

**Confidence: high** — this is a direct read of the source.

**Fix direction.** Publish `alpha_se`, `alpha_t`, `alpha_p` and a 95% CI from the HAC fit that is already being computed; compound the alpha; and either correct the 15 alphas for multiplicity or label them exploratory.

---

### SI-10 · P1 · Two R² values, statistically disjoint, same field family, cross-reference present in only one of the two payloads

**JSON path:** `sections.factor_exposure.data.r_squared` vs `sections.dashboard.data.components.risk_score.data.factor_r_squared`

**Observed and recomputed.**

```
=== CORRECTED: 95% CI on each published R^2 (Fisher z on r=sqrt(R^2)) ===
  factor_exposure (n=174)  R2=0.6511  r=0.8069  z=+1.1181  SE(z)=0.0765  95% CI = [0.5594, 0.7280]
  risk_score      (n=36)   R2=0.2391  r=0.4890  z=+0.5347  SE(z)=0.1741  95% CI = [0.0365, 0.4961]
  -> CIs are DISJOINT.
```

**Actual values and windows, as requested:**

| | Value | Window | n | Where the n lives |
|---|---:|---|---:|---|
| `factor_exposure.data.r_squared` | **0.6511** (`adjusted_r_squared` 0.649) | 2026-01-20 → 2026-09-25 | **174** | `data.model_window.days`, two keys away; **not attached to the scalar** |
| `risk_score.data.factor_r_squared` | **0.2391** | 2026-08-04 → 2026-09-24 | **36** | `risk_score.data.factor_model.model_window.days`, three keys away |

**Expected.** The two numbers differ by **2.72×** on windows differing by **4.8×** in length, and their 95% intervals do not overlap — so they are not two noisy measurements of one construct, they are **two genuinely different measurements published under near-identical names with no shared vocabulary**. `factor_exposure` reports 65% of variance explained at `status: "available"` with `warnings: []`. `risk_score` reports 24% and raises `alerts: ["High unexplained risk (low R-squared: 0.24)"]`. An agent reading `sections.factor_exposure` alone concludes the factor model explains 65% of portfolio risk; an agent reading `sections.dashboard` alone is told 76% of it is unexplained. Both are true of their own windows. Neither payload says so.

**The one mitigation, and its limit.** `risk_score.data.factor_model.note` is genuinely good:

> "factor_exposure publishes the same model over full exchange history, so its R-squared describes a longer, different sample: compare the two only through this block's basis and window, never by their values alone."

But it lives in **one** of the two payloads. `factor_exposure.data.r_squared` carries no reciprocal note, no window suffix, and no n. A bidirectional cross-reference is needed, or the fields should be renamed to embed the window (`r_squared_174d` / `r_squared_36d`).

**Degrees of freedom.** `factor_exposure` portfolio regression: OLS, 2 coefficients, n=174 → **df = 172**, adequate. `risk_score` portfolio regression: OLS, 2 coefficients, n=36 → **df = 34**, and `se(β) ≈ 1/√36 = 0.167`, which is why the R² interval is ±0.23 wide. Adequate but marginal; the 36-row R² is the number driving a "HIGH RISK" alert and a saturated 30/30 score leg (SI-12).

**A further undisclosed df problem in the same regression.** `app/services/analytics_engine.py:1780` — `traded = aligned_returns.notna().any(axis=1)`. The portfolio series is "active" on any day *at least one* of 14 constituents traded. So the 174-row portfolio return series is computed over a **day-to-day-varying constituent set** (per-ticker `data_points` range 102–172 against the portfolio's 174). The published `alpha = 0.002042` and `r_squared = 0.6511` therefore describe a return series whose composition changes across the window — a moving-basket alpha. Nothing in the payload discloses this.

**Confidence: high.**

---

### SI-11 · P1 · `regime` publishes a benchmark-derived feature named `log_holding_return`; a 99.9993% posterior with no convergence flag; per-state annualized returns with undeclared n

**JSON path:** `sections.regime.data.model.features`, `.regime_probabilities`, `.states[]`, `.observations`

**Observed.**

```json
"model": { "type": "gaussian_hmm", "architecture": "hamilton_1989", "states": 3,
           "features": ["ret21_log_holding_return_21d", "vol21_realized_vol_21d_annualized"],
           "covariance_type": "full", "scaler": "standard_scaler_fitted_on_requested_window",
           "n_iter": 200, "tolerance": 0.0001, "random_state": 100,
           "lookback_days": 1100, "observations": 719, "minimum_observations": 200,
           "decoding": "viterbi", "posterior": "filtering" }
"regime_probabilities": { "crisis": 99.9993, "calm": 0.0006, "bull": 0 }
"states": [ {"regime":"crisis","ann_ret":-0.2666,"ann_vol":0.1124,"historical_days_pct":30.9},
            {"regime":"calm",  "ann_ret": 0.1228,"ann_vol":0.1096,"historical_days_pct":53.3},
            {"regime":"bull",  "ann_ret": 0.8627,"ann_vol":0.1965,"historical_days_pct":15.9} ]
"observations": 719
"portfolio_in_current_regime": { "days": 19, "ann_ret": null, "ann_vol": null, "annualized": false, ... }
```

**Three defects.**

**(a) The feature is mislabelled, and the mislabelling is load-bearing.** `app/services/regime_service.py:446` publishes the feature name `ret21_log_holding_return_21d`. The feature is computed at `app/services/regime_service.py:195`:

```python
ret21 = np.log(close / close.shift(REGIME_FEATURE_WINDOW_DAYS)).dropna()
```

where `close` derives from `bench_data` (`:152-192`) — the **NIFTY 50 benchmark** (`"benchmark": {"symbol": "^NSEI", "name": "NIFTY 50"}`). The docstring at `:125` repeats the error: "21-day log **holding** return". So the regime classification describes the *benchmark*, not the portfolio, while every published field name says "holding". An agent reading `ret21_log_holding_return_21d` will conclude the crisis call is about this portfolio. It is about NIFTY. The same payload's own `history_coverage.covered_days = 39` (holding rows) sitting next to `model.observations = 719` (benchmark rows) makes the contradiction visible to a careful reader and invisible to a fast one.

**(b) `regime_probabilities.crisis = 99.9993` is a degenerate in-sample point posterior presented to four decimals.** `app/services/regime_service.py:226` — `hmm.fit(x_scaled)` **discards the return value**, so `monitor_.converged` and `monitor_.iter` are never read. The payload publishes `n_iter: 200` and `tolerance: 0.0001` — which invites the reader to assume convergence — but no `converged` flag, no `n_iter_run`, no log-likelihood, no AIC/BIC. There is no holdout. The scaler is fitted on the same 719 rows (`:204-205`, and the payload says so: `scaler: "standard_scaler_fitted_on_requested_window"`). Only 15 free parameters are estimated (`params="mc"`, `regime_service.py:217-218`), so df is not the issue — **the absence of a convergence or likelihood field is.** A 99.9993% posterior is the signature of a model latching onto a single observation; publishing it to 5 significant figures implies a precision that no in-sample unvalidated filter can support.

**(c) Per-state annualized returns with no per-state n.** `app/services/regime_service.py:235` computes `n_sub = len(r_sub)` per state and **never publishes it** — `states[]` carries exactly four keys. `bull`'s `ann_ret = 0.8627` is a geometric mean over the ~114 observations (15.9% of 719) assigned to that state, extrapolated by `252/114 = 2.21×`. `crisis` gets ~222 days, `calm` ~383. With `recent_history_self_transition_pct = 96.6387` over 119 transitions, the expected regime run length is `1/(1−0.966) ≈ 29` days, so `bull` is roughly four separate ~29-day episodes each annualized as if it persisted for a year. No duration, no n, no standard error, no CI.

**Clean in this section, and genuinely exemplary — the codebase can do this right:**
- `transition_matrix_provenance: {source: "configured_sticky_prior", estimated: false, estimated_parameters: "means_and_covariances_only", read_this_as: "model prior; not ..."}` — the 96% diagonal is explicitly declared a prior, not a fitted quantity, and the payload tells the reader where to look instead (`stability_pct`). This is the best single piece of statistical disclosure in the entire artifact.
- `portfolio_in_current_regime` at n=19 **withholds** `ann_ret` and `ann_vol`, sets `annualized: false`, and publishes `minimum_observations_required: 30` and `observations: 19`. This is the behaviour SI-2 argues `tear_sheet` should adopt.
- `stability_pct_rule` states the formula in words, `stability_pct_observations = 719` states the n, `stability_pct_scope` states the domain, and `stability_pct_note` warns it is neither the transition-matrix prior nor the recent-history rate.

**Root cause.** `app/services/regime_service.py:446` (feature name), `:125` (docstring), `:226` (discarded convergence monitor), `:235` (computed-but-unpublished `n_sub`), `:440-460` (the `model` payload block, which has no convergence or likelihood field).

**Confidence: high** on (a) and (c) — both are direct source reads. **High** that (b)'s fields are absent. **Medium** on how *degenerate* the posterior actually is; without the fitted HMM I cannot distinguish "genuinely overwhelming evidence" from "unconverged latch", which is precisely why the missing `converged` flag matters.

---

### SI-12 · P1 · `risk_score` publishes a saturated score leg as if it were a measurement, and a 39-row "last 60 days" volatility

**JSON path:** `sections.dashboard.data.components.risk_score.data.components`, `.overall_score`, `.alerts`

**Observed.** `overall_score: 13.7`, `risk_level: "LOW"`, `components: {concentration: 8.6, volatility: 9.8, correlation: 5.3, factor_risk: 30, market_risk: 9.8}`, `alerts: ["High unexplained risk (low R-squared: 0.24)"]`, `factor_r_squared: 0.2391`.

**Two clipped quantities presented as measurements.**

**(a) `factor_risk: 30` is a hardcoded ceiling, not a score.** `app/services/analytics_engine.py:1228`:

```python
factor_score = min(30, (1 - r_squared) * 100)
```

With `r_squared = 0.2391`: `(1 − 0.2391) × 100 = 76.09` → `min(30, 76.09) = **30**`. The leg is pinned at maximum. It can only ever communicate "R² < 0.70"; it cannot distinguish R² = 0.24 from R² = 0.00. No `unclipped_value` field is published. The alert at `:1287` (`f"High unexplained risk (low R-squared: {r_squared:.2f})"`) fires on R² alone with **no threshold published at all** — the string `0.24` is the only evidence a reader gets that the trigger is a cutoff rather than a continuous reading.

**(b) `market_risk: 9.8` is a 39-observation volatility silently computed where the code asks for 60.** `app/services/analytics_engine.py:1237-1239`:

```python
recent_returns = portfolio_returns.tail(60)   # Last 60 days
recent_vol = recent_returns.std() * np.sqrt(252)
market_score = min(30, recent_vol * 100)
```

The holding window is 39 rows. `tail(60)` silently returns 39. `0.098238 × 100 = 9.8238` → the published `market_risk: 9.8`, which is exactly the 39-day `annual_volatility` from SI-2. So a 39-point σ is presented as a "last 60 days" measure with no shortfall disclosure. `pandas.Series.tail` does not warn on a short frame, and nothing downstream checks.

**Neither the 30/30 saturation nor the 60→39 truncation is disclosed.** The `methodology` string is otherwise admirably specific (it states the five weights, the renormalization rule, the correlation-leg formula, and the benchmark requirement) — which makes the two undisclosed saturations stand out.

**Root cause.** `app/services/analytics_engine.py:1228` (saturating `min`, no unclipped echo), `:1237` (`tail(60)` with no length assertion), `:1287` (alert with no threshold field).

**Confidence: high** (arithmetic exact; both are two-line source reads).

---

### SI-13 · P1 · Johansen test swallows every exception and returns `False`, making the published 83/91 test-agreement uninterpretable

**JSON path:** `sections.pairs.data.test_agreement`, `sections.pairs.data.pairs[].johansen_cointegrated`

**Observed.** `test_agreement: {counted_pairs: 91, decision_positive_count: 4, diagnostic_positive_count: 4, agreement_count: 83, disagreement_count: 8, decision_positive_only_count: 4, diagnostic_positive_only_count: 4, ...}`. Published as a headline diagnostic of the dual-test design.

**Expected.** A test-agreement rate is only meaningful if every test actually ran. `app/services/cointegration_service.py:341-357`:

```python
def test_johansen_cointegration(series_a, series_b) -> bool:
    try:
        res = coint_johansen(data, det_order=0, k_ar_diff=1)
        ...
        return bool(trace_stat_r0 > crit_val_95_r0)
    except Exception as e:
        logger.debug(f"Johansen test error: {e}")
        return False
```

A singular information matrix, near-collinear prices, or a degenerate eigenvalue all raise — and the function returns **`False`**, which is indistinguishable from a genuine "not cointegrated at 95%". The failure increments `agreement_count` when the Engle-Granger verdict was also negative. The published 83/91 "91.2% test agreement" is therefore an **upper bound that silently mixes real negatives with failures**, and the section offers no `johansen_error_count` to separate them. Note the same section *does* count and report `errors` elsewhere in the payload family, so the omission is specific to this test.

Secondary: `coint_johansen` publishes **no p-value for Johansen at all** — only a boolean against the 95% critical value. So the artifact runs 182 hypothesis tests in this section and surfaces 91 of them, with no multiplicity accounting for either family (see SI-1).

**Root cause.** `app/services/cointegration_service.py:355-357` — bare `except Exception` returning a hardcoded `False`; consumed at `:415` (`johansen_coint = test_johansen_cointegration(...)`) and folded into `johansen_agrees_with_decision` at `:498`.

**Confidence: high** on the code path. **Medium** on whether any of the 91 actually threw — I cannot execute against the artifact's own price series, so this is a defect in the *reported statistic's* validity, not a proven miscount.

---

### SI-14 · P1 · The published cointegration p-value is purely asymptotic; at the actual n the finite-sample critical value rejects one of the four published findings

**JSON path:** `sections.pairs.data.pairs[].engle_granger_pvalue`

**First, the clean result.** I verified the published p-value genuinely belongs to the named decision test, as the review brief asked:

```
MAX |mackinnonp(t) - published p| over 91 pairs, N=2: 2.380e-05
  JUNIORBEES.NS/MOTILALOFS.NS  t= -4.2948  published_p=0.002609  mackinnonp(N=2)=0.002609
  JKIL.NS/NIFTYIETF.NS         t= -3.6595  published_p=0.020638  mackinnonp(N=2)=0.020641
  ELECTCAST.NS/MCX.NS          t= -3.4031  published_p=0.042007  mackinnonp(N=2)=0.042007
  JUNIORBEES.NS/MIDCAPIETF.NS  t= -3.3475  published_p=0.048530  mackinnonp(N=2)=0.048525
```

Monotonicity check: **0 violations** across all 91 pairs (p decreases monotonically as |t| grows). The p-value is the Engle-Granger t-test p-value, matching `statsmodels.tsa.adfvalues.mackinnonp(t, regression='c', N=2)`, which is what `statsmodels.tsa.stattools.coint` returns. **There is no test/p-value mismatch.** The `decision_test: "engle_granger"` / `johansen_role: "diagnostic_only"` labelling is correct and consistently applied on all 91 rows.

**But the p-value ignores n entirely, and that changes one of the four findings.** `mackinnonp(teststat, regression='c', N=1, lags=None)` takes **no `nobs` argument** — the signature is confirmed by introspection. `statsmodels/tsa/stattools.py` (v0.15.0) computes `pval_asy = mackinnonp(res_adf[0], regression=trend, N=k_vars)` while computing the *critical values* with `mackinnoncrit(N=k_vars, regression=trend, nobs=nobs - 1)`. So the section's p-value is the **asymptotic** one and the sample size never enters it. MacKinnon 2010 finite-sample critical values at the actual n:

```
  nobs=  30  1%=-4.2988  5%=-3.5474  10%=-3.1888
  nobs= 108  1%=-4.0007  5%=-3.3933  10%=-3.0840
  nobs= 168  1%=-3.9663  5%=-3.3727  10%=-3.0693
  nobs= 174  1%=-3.9605  5%=-3.3715  10%=-3.0689
  nobs= 200  1%=-3.9520  5%=-3.3669  10%=-3.0657   <- asymptotic, what the section effectively uses

  JUNIORBEES.NS/MOTILALOFS.NS     n=171 |t|=4.2948  REJECT
  JKIL.NS/NIFTYIETF.NS            n=108 |t|=3.6595  REJECT
  ELECTCAST.NS/MCX.NS             n=173 |t|=3.4031  REJECT
  JUNIORBEES.NS/MIDCAPIETF.NS     n=168 |t|=3.3475  *** DOES NOT REJECT AT 5% with the finite-sample critical value ***
```

The fourth published "cointegrated pair" — `JUNIORBEES.NS/MIDCAPIETF.NS`, `p = 0.048530`, `is_cointegrated: true`, and the source of a **`SHORT_SPREAD (Short JUNIORBEES.NS, Long MIDCAPIETF.NS)`** trading signal — fails the correctly size-corrected 5% test at its own n=168. It clears only because the asymptotic critical value (−3.3669) is 0.006 short of the finite-sample one (−3.3727) and the statistic is 3.3475. (This is an internal inconsistency *within statsmodels itself* — `mackinnonp` and `mackinnoncrit` interpolate differently — but the artifact inherits it silently and reports only the p-value, so a reader has no way to see the borderline case.)

**Root cause.** The artifact surfaces `mackinnonp` output only; `statsmodels.tsa.stattools.coint` also returns `crit` (the finite-sample critical values at 1%/5%/10%), and `app/services/cointegration_service.py:392` discards it with `t_stat, p_val, _ = coint(p_a, p_b)`. Publishing `crit` alongside `p_val` — or using the finite-sample critical value for the decision — would make the borderline cases self-evident.

**Confidence: high** on the asymptotic-vs-finite-sample discrepancy (both from `statsmodels 0.15.0`, exact). **Note the interaction with SI-1:** this finding is moot if the family is corrected, since Bonferroni and BH both return zero discoveries regardless of which critical value is used. Fix SI-1 first; treat this as a correctness/robustness cleanup.

---

### SI-15 · P1 · A 2,486-day "track record" of 14 *today's* holdings, four of which have 380–1,635 observations, published with no warnings

**JSON path:** `sections.tear_sheet.data.full_history`

**Observed.**

```json
"full_history": { "basis": "full_exchange_history_current_weights",
                  "calculation_basis_note": "hypothetical_current_weights",
                  "observation_count": 2486, "truncated_to_holding_window": false,
                  "per_ticker_return_observations": { "CIPLA.NS": 2483, ..., "NIFTYIETF.NS": 612,
                                                      "MIDCAPIETF.NS": 1635, "MAFANG.NS": 1323,
                                                      "SELECTIPO.NS": 380 },
                  "metrics": { "total_return": 6.092394, "cagr": 0.219672, "sharpe": 0.969056,
                               "sortino": 1.343681, "calmar": 0.364105, "volatility": 0.206757,
                               "max_drawdown": -0.603319, "days": 2486, "annualized": true } }
"relative_vs_nifty": { "beta_vs_nifty": 0.9229, "alpha_annualized": 0.116, "overlap_days": 2474 }
```

`sections.tear_sheet.warnings = []`, `status = "available"`.

**Expected.** A 609% total return, 21.97% CAGR and 0.969 Sharpe over "10 years" are computed on a **constant-weight portfolio of the 14 names the holder happens to own today**, back-filled to 2016-09-12. Two biases follow, neither disclosed:

- **Survivorship / look-ahead selection.** The constituents were chosen with full knowledge of which Indian scrips performed. `calculation_basis.full_history = "hypothetical_current_weights"` discloses the *weight* assumption; it says nothing about the *selection* bias, which is the larger effect.
- **A silently shrinking constituent set.** `SELECTIPO.NS` has 380 of 2,486 observations (15%), `NIFTYIETF.NS` 612 (25%), `MAFANG.NS` 1323 (53%), `MIDCAPIETF.NS` 1635 (66%). On any given day in 2016-2018 the "14-name portfolio" was computed from as few as one name. The artifact publishes the per-ticker counts (**good disclosure**) but not the number of names active on each day, and emits no warning.

A related inconsistency: the 39-day `metrics` block publishes `skew`, `kurtosis`, `omega` and `tail_ratio`; the 2,486-day `full_history.metrics` block publishes **none** of them. Two blocks in the same section with the same key name and different schemas, with no `omitted_fields` entry (it is `[]`).

**Also note the two alphas in one section:** `relative_vs_nifty.alpha_annualized = 0.7423` (74.23%) at `overlap_days: 36`, and `full_history.relative_vs_nifty.alpha_annualized = 0.116` (11.6%) at `overlap_days: 2474`. A **6.4× divergence**, same field name, same section, neither cross-referenced.

**Root cause.** `app/api/analytics.py` tear-sheet `full_history` assembly — no warning branch for partial constituent coverage, and `basis` discloses weights but not selection. Note `app/api/analytics.py:967` and `:1026` already contain careful prose about the HMM window vs the holding window, so the pattern of "declare the window mismatch" exists in this file and is simply not applied here.

**Confidence: high** on the disclosure gap. **Medium** on the magnitude of the selection bias (I cannot recompute the counterfactual universe from the export) — but the direction is unambiguous and the artifact makes no attempt to caveat it.

---

### SI-16 · P2 · `india_flows` — status is honest; the 4 warnings are complete. Latent design defect in the anomaly test

**JSON path:** `sections.india_flows`

**Observed.** `status: "partial"`, 4 warnings:

> **[1]** "Composite data status is only as complete as its weakest component: partial; degraded components (2 of 3): institutional_flows=unavailable, delivery_anomalies=unavailable."
> **[2]** "institutional_flows is unavailable: it is a market-wide aggregate measured over the whole market and has no ticker universe; no measurement was published; ticker coverage does not apply to it and no portfolio weight was renormalized for it."
> **[3]** "delivery_anomalies is unavailable: it is measured symbol-scoped over the requested scrip roster; no measurement was published; no requested symbol had a stored delivery history in the ingested NSE bhavcopy records."
> **[4]** "Composite coverage is only as complete as its weakest component: institutional_flows=unknown (market_wide_aggregate_has_no_ticker_universe); delivery_anomalies=unavailable (no_requested_symbol_had_usable_delivery_history)."

**Assessment against the brief's question — "do the reported flow figures support any conclusion?"** There are **no flow figures**. The `institutional_flows` and `delivery_anomalies` components are both `unavailable` with `data: null`-equivalent payloads. The only measured component is `liquidity_limits`. So the institutional-vs-retail delivery-volume split the brief anticipated **does not exist in this export**, and the artifact says so in four separate, specific, non-generic warnings that each name the *reason* (no ticker universe vs no stored delivery history) and explicitly state that nothing was published and no weight was renormalized. **Status matches reality. This is clean.**

**Latent design defect (flagged for when the data lands).** `inputs.component_inputs.delivery_anomalies` declares `sigma_threshold: 2`, `lookback_days: 20`, `lookback_basis: "trading_sessions_baseline"`, `requested_symbol_count: 14`. That is 20 × 14 = **280** one-sided 2σ anomaly tests, of which **12.7** are expected false positives under the null — and the component's design declares no correction, no per-symbol baseline stability check, and no minimum baseline length. A 20-session baseline is also short enough that the sample σ is materially biased low, inflating the 2σ exceedance rate above nominal. The defect is latent (the data is absent) but it will fire the moment the bhavcopy ingest has delivery volume.

**Root cause.** `app/api/analytics.py` india-flows route; the `sigma_threshold: 2` declaration is in `sections.india_flows.inputs.component_inputs.delivery_anomalies`.

**Confidence: high** that the labelling is honest. **High** that the anomaly design is uncorrected (it is visible in the declared inputs).

---

### SI-17 · P2 · `stress_testing` — 12 of 14 "measured" volatilities are at a clip bound; the "Market Crash" is shallower than the artifact's own realized drawdown

**JSON path:** `sections.stress_testing.data.scenarios`

**Observed and recomputed.**

```
  scenario                  port_impact   max_dd   1.15x check   1.15x verified
  Market Crash                -0.4742    -0.5453      -0.5453     MATCH
  Interest Rate Shock         -0.1942    -0.2233      -0.2233     MATCH
  Volatility Spike            -0.2877    -0.3309      -0.3309     MATCH
  Tech Sector Correction      -0.1349    -0.1551      -0.1551     MATCH

  volatility_adjustment bounds = [0.85, 1.25]  min_observations = 20
  AT THE LOWER CLIP (0.85): 4  [NIFTYIETF.NS, MIDCAPIETF.NS, JUNIORBEES.NS, SELECTIPO.NS]
  AT THE UPPER CLIP (1.25): 8  [ELECTCAST.NS, MOTILALOFS.NS, ARROWGREEN.NS, JKIL.NS, MCX.NS,
                                MOTHERSON.NS, REDINGTON.NS, MAFANG.NS]
  GENUINELY MEASURED      : 2  [CIPLA.NS, NTPC.NS]

  REALIZED max drawdown over the artifact's own 2486-day full history: -0.603319
  "Market Crash" scenario max_drawdown:                                   -0.545300
  -> the "Market Crash" stress is 9.6% SHALLOWER than a drawdown the artifact already
     reports as realized over its own full history.
```

**(a) 12 of 14 vol factors are clipped constants wearing a `measured` label.** Every `by_ticker` entry declares `basis: "measured_annualized_volatility_over_reference"`, but 8 sit exactly at the 1.25 ceiling (implying measured σ ≥ 27.5%) and 4 exactly at the 0.85 floor (implying measured σ ≤ 18.7%). Only CIPLA.NS and NTPC.NS are actual measurements. `STRESS_VOL_ADJ_MAX = 1.25` at `app/services/analytics_engine.py:146`; the adjustment is applied at `:756-762` with `STRESS_VOL_MIN_OBSERVATIONS = 20` at `:147`. **`min_observations: 20` matters here:** NIFTYIETF.NS has exactly 20 return observations in the holding window, so its factor sits at the floor on the bare minimum admissible sample. Same saturation pattern as SI-12, and the same missing `unclipped_value`.

**(b) The "Market Crash" stress is not a worst case.** `max_drawdown = portfolio_impact × 1.15` (`max_drawdown_formula`, verified exact on all four scenarios). The artifact's own `tear_sheet.full_history.metrics.max_drawdown` is **−0.603319** — a *deeper* loss than the −0.545300 "Market Crash". Both are published in the same export under the same field name, neither cross-references the other. A 15% uplift on a point estimate, with no basis and no calibration to anything, is presented as `max_drawdown` for a deterministic no-simulation calculation.

**(c) `SELECTIPO.NS` is modelled as an ETF.** `shock_inputs.instrument_overrides.SELECTIPO.NS = {sector: "Exchange Traded Fund", sector_elasticity: 1.15, basis: "instrument_override_selectipo"}`, while the same export reports SELECTIPO.NS as a **380-of-2,486-observation** name. A micro-cap equity carrying a 1.15 ETF elasticity instead of an equity sector elasticity is a misclassification that directly sets its stress loss.

**What is clean here, and it is exemplary.** `stress_testing` is the best-disclosed section in the artifact for the distinction between a nominal label and a computed interval:

- `confidence_level: 0.95` with `confidence_basis: "nominal_label_not_simulated"`
- `units.confidence_level: "unitless_nominal_label"`
- `max_drawdown_basis: "derived_from_shock_proxy"`, `impact_basis: "deterministic_factor_proxy"`
- `recovery_time_basis: "configured_recovery_estimate_not_simulated"`
- `position_impact_clip_basis: "configured_bounds_not_simulated"`, `sector_elasticity_basis: "static_configured_table"`
- a `methodology` string that spells out the entire formula in one sentence and ends with "confidence_level is a nominal 0.95 label with no simulated distribution behind it"

Every one of these is a `*_basis` field that names the epistemic status of the adjacent number. **The artifact proves it can do this at this level of rigour — which is precisely why `forecast_risk`'s bare `confidence_interval` (SI-3) and `risk_score`'s saturated 30/30 (SI-12) are indefensible rather than merely inelegant.**

**Residual risk worth naming:** `confidence_level: 0.95` is still a *machine-readable field* that a downstream agent will consume programmatically without reading `confidence_basis`. The disclosure mitigates; it does not eliminate.

**Confidence: high** on the arithmetic (all four scenarios verified) and on the clip census. **Medium** on the drawdown comparison, since `full_history` is a back-filled current-weight reconstruction (SI-15) and its −60.33% is itself a hypothetical number — the point stands regardless, which is itself the finding.

---

### SI-18 · P2 · The same construct is published five times with different values, windows, and no cross-references

**JSON path:** artifact-wide

**Observed.** Collated by exhaustive sweep:

| Construct | Values published | Windows | Cross-referenced? |
|---|---|---|---|
| Portfolio annualized volatility | **0.098238**, **0.197796**, **0.178900**, **0.151900**, **0.206757** | 39d, 175d, 251d, GARCH 21d forecast, 2486d | **No** |
| Portfolio 95% VaR | **−0.007780**, **−0.019318**, **−0.018244**, **−0.014266** (forecast) | 39d, 175d, 251d, model | **No** |
| Portfolio max drawdown | **−0.021283**, **−0.137058**, **−0.545300**, **−0.223300**, **−0.330900**, **−0.155100**, **−0.603319** | 39d, 175d, 4 stress scenarios, 2486d | **No** |
| Beta to benchmark | **1.0706**, **0.6743**, **0.9229** | 174d, 36d, 2474d | **No** |
| Annualized alpha | **0.5146**, **0.7423**, **0.116** | 174d, 36d, 2474d | **No** |
| R² | **0.6511**, **0.2391** | 174d, 36d | Partially (SI-10) |

Every value is individually defensible. The problem is that five portfolio volatilities spanning **0.098 to 0.207** — a **2.1× range** — are published with no field that says which is the book's risk. An agent that picks one at random is wrong with high probability. The artifact has a `currency_policy` field at the top level governing unit conflicts across sections; there is no equivalent for the *quantity* conflicts, which are the ones that actually change conclusions.

**Root cause.** No cross-section reconciliation layer. `app/services/ai_context_service.py` assembles sections independently; nothing reconciles same-named constructs across windows.

**Confidence: high** (exhaustive sweep, values quoted above).

---

### SI-19 · P2 · Liquidity scores, bands and percentiles computed from 20–22 observations

**JSON path:** `sections.liquidity.data.scoring`, `.observation_window`

**Observed.** `inputs.lookback_days: 30`; per-ticker `observations` = **20, 20, 20, 20, 20, 21, 21, 21, 21, 21, 21, 21, 21, 22** (min 20, max 22, median 21 across 14 tickers). `bands` are cut at published scores 6 and 8; `spread.tier_ladder` derives bid-ask spreads from turnover tiers.

**Expected.** A 25th or 75th percentile computed from 20 observations is an interpolated order statistic of rank 5 or 15. The 30-session ADV is a mean of 20 points with a standard error of `σ/√20 ≈ 22%` of σ, and the `liquidation_days` bands ("1-2", "2-5", "5-10") are discrete labels attached to those point estimates. Every `days_to_liquidate_10pct_adv` and `days_to_liquidate_20pct_adv` is **0** for all 14 positions — i.e. the position is under one session of ADV — which is a floor artifact (`ceil` of a sub-1 ratio), not a measurement.

**Clean here:** the per-ticker `observations` count **is** published for every ticker, twice (`observation_window` and `scoring.observation_window`), and the `market_cap_provenance` breakdown is published as `{estimated: 4, fallback: 1, measured: 9}` with a single warning that names all five unmeasured names, identifies SELECTIPO.NS as sitting on the fixed ₹1,000,000,000 floor, and states that "the published score, band and liquidation window are partly derived from a substitute for a measurement". That is exactly the right disclosure. The `spread` object goes further and labels itself `provenance: "model_assumed"`, `observed: false`, with a `note` spelling out that the bid-ask spread "is not read from a quote, not measured from intraday data and not derived from the score". Exemplary.

So the finding is narrow: the observation counts are declared (good) but **no uncertainty on any derived quantity is published**, and the `lookback_days: 30` input against 20–22 actual observations is a silent 33% shortfall of the same family as SI-12(b).

**Confidence: high** on the counts (declared in the payload). **Medium** on materiality — with every position at 0 days to liquidate, the metric is currently uninformative regardless of its precision.

---

### SI-20 · P2 · Skewness is published untested and is not significant; the kurtosis field's convention is unlabelled and contradicts another section

**JSON path:** `sections.tear_sheet.data.metrics.skew`, `.kurtosis`; `sections.risk_studio.data.components.tail_dependence.data.is_fat_tailed`

**Observed.** `skew: -0.743865`, `kurtosis: 2.622096` on n=39, no test, no CI, no convention label. `risk_studio.tail_dependence.data.is_fat_tailed: true`, derived from a POT/GPD fit with clipped ξ = −0.5.

**Expected.**

```
  skew    = -0.7439  SE=sqrt(6/39)=0.3922  t=-1.896  p=0.0655  -> NOT significant at 5%
  kurtosis=  2.6221  SE=sqrt(24/39)=0.7845  t= 3.343  p=0.0019  -> significant
```

The published negative skew — the distributional fact an agent would most likely act on ("this book has a fat left tail") — is **not statistically significant** at the conventional level. It is published as a bare point estimate with no indication that 39 observations cannot establish it. The positive excess kurtosis *is* significant, but the field is named `kurtosis` while carrying the **excess** convention (2.62 against a normal 3.0); a reader using the Pearson convention reads 2.62 as extremely platykurtic.

There is also a cross-section tension worth naming: `tear_sheet` says excess kurtosis **2.62 < 3** (leptokurtic) over 39 days while `risk_studio` says `is_fat_tailed: true` over 518 days. These are different windows so they are not strictly contradictory, but nothing in the payload lets a reader see that, and an agent asked "is this book fat-tailed?" gets both answers with equal apparent authority.

**Root cause.** `app/utils/holdings.py:35` gate again — 39 clears 30, and no higher gate exists for higher-order moments, which need O(n²) to estimate and are the *most* sample-size-sensitive statistics in the set. `sections.tear_sheet.data.full_history.metrics` omits skew/kurtosis entirely, so the section cannot even offer the longer-window comparison.

**Confidence: high** on the SEs (standard asymptotic moment SEs) and on the field values.

---

### SI-21 · P2 · `test_johansen_cointegration` runs a VAR on 105–108 observations for the shallow ticker, and the 30-observation gate is the only depth control

**JSON path:** `sections.pairs.coverage.minimum_pair_observations`, `.usable_observations_by_ticker`, `sections.pairs.data.pairs[].overlap_observations`

**Observed.** `minimum_pair_observations: 30`; `usable_observations_by_ticker` ranges 108 (NIFTYIETF.NS) to 174; `depth_ratio` and `depth_status` are published per pair; `depth_limited_pair_count: 13`; `reference_pair_observations: 173`; all 13 depth-limited pairs contain NIFTYIETF.NS (verified: overlap 105–108).

**Assessment.** The depth disclosure here is **genuinely good** and answers the brief's question (e) directly: `JKIL.NS/NIFTYIETF.NS` is published as `is_cointegrated: true` with `depth_ratio: 0.6243`, `depth_status: "partial"`, `overlap_observations: 108`. So **yes — a pair involving the shallow ticker is reported as a finding**, and it carries a per-row `depth_status: "partial"` marker plus a section-level warning. A reader who checks `depth_status` sees it. A reader who reads `cointegrated_pairs_count: 4` does not. This is the same structural weakness as SI-10: correct disclosure attached to the wrong field.

**The statistical depth question itself.** The Johansen system is bivariate with `det_order=0` (constant) and `k_ar_diff=1` (`app/services/cointegration_service.py:349`), giving 3 regressors per equation (2 lagged terms + constant) and residual df = n − 3. At n=108 that is **df = 105** — ample. At the `MIN_PAIR_OBSERVATIONS = 30` floor it would be **df = 27**, which is thin for a trace statistic whose 95% critical values are calibrated for large n. The gate at `app/services/cointegration_service.py:53, 384` (`if len(df) < MIN_PAIR_OBSERVATIONS: return None`) is therefore *technically* sufficient but statistically thin at its boundary, and — per SI-14 — the reported p-value is asymptotic regardless of n, so a 30-observation pair would receive an over-confident p-value with no finite-sample correction available to the reader.

**On the brief's question (f) — stationarity vs cointegration is not confused.** Verified clean. `coint()` performs the Engle-Granger two-step: OLS of `p_a` on `p_b`, then an ADF on the OLS residuals (`statsmodels/tsa.stattools.coint` → `res_co = OLS(y0, xx).fit()` then `adfuller(res_co.resid, ...)`). The published statistic is the residual ADF t-statistic, not a raw price-level ADF. A random walk pair is correctly *not* flagged, and no level-stationarity test is presented as cointegration. `signal: "NOT_COINTEGRATED"` is correctly assigned to all 87 non-flagged pairs, and the `*_zscore` gate at `:433-441` explicitly refuses to emit a trade signal on a non-cointegrated pair — a deliberate and correct guard against trading spurious mean reversion.

**Confidence: high.**

---

## Sample-size census (mandate item 2)

Every published `observation_count` / `n_observations` / `lookback` / `days` / `data_points` in the export, by section, with the statistics that rest on it.

| Section | n | Source field | Statistics resting on it | Verdict |
|---|---:|---|---|---|
| `tear_sheet` | **39** | `data.observation_count`, `measured_window.days` | `sharpe` 3.488, `sortino` 5.315, `calmar` 20.189, `cagr` 0.4297, `omega` 1.917, `tail_ratio` 1.172, `volatility` 0.0982, `skew`, `kurtosis`, `max_drawdown` | **P0 — SI-2** |
| `tear_sheet` | 36 | `relative_vs_nifty.overlap_days` | `beta_vs_nifty` 0.6743, `alpha_annualized` 0.7423, `benchmark_sharpe` −0.6367 | **P1** |
| `tear_sheet.full_history` | 2486 | `full_history.observation_count` | `cagr` 0.2197, `sharpe` 0.969, `max_drawdown` −0.6033 | **P1 — SI-15** (4 constituents at 380–1635) |
| `realized_risk` | **36–39** (20 for NIFTYIETF) | `positions.*.data_points` | `sharpe_ratio` 3.486, `sortino` 5.311, `var_95`, `cvar_95`, `skewness`, `kurtosis` | **P0 — SI-2, SI-4** |
| `realized_risk.instrument_risk` | **175** | `instrument_risk.portfolio.days` | `annual_volatility` 0.1978, `sharpe_ratio` 1.725, `var_95` −0.0193, `max_drawdown` −0.1371 | P2 (n declared) |
| `dashboard.risk_score` | **36** | `factor_model.model_window.days` | `factor_r_squared` 0.2391, `components.factor_risk` 30 (saturated) | **P1 — SI-10, SI-12** |
| `dashboard.risk_score` | **39** | `factor_model.input_window.days` | `history_coverage.covered_days` | declared |
| `dashboard.risk_score.market_risk` | **39** (code asks 60) | `analytics_engine.py:1237` | `components.market_risk` 9.8 | **P1 — SI-12(b)** |
| `dashboard.performance_history` | **19** (18 returns) | `history_coverage.observation_count` | the *only* published return series | declared; `status: partial` |
| `factor_exposure` | **174** | `full_history.observation_count` | `r_squared` 0.6511, `adjusted_r_squared` 0.649, portfolio `alpha`/`market` | **P1 — SI-9** |
| `factor_exposure` positions | **101–166** | `positions.*.data_points` | 14 × {`alpha`, `annualized_alpha`, `market`} | **P1 — SI-9**; code gate is `<10` |
| `risk_contribution` | **251** | `full_history.observation_count`, `calculation_window.days` | `portfolio_volatility_annualized` 0.1789, `portfolio_var_95_daily`, `portfolio_cvar_95_daily`, 28 Euler/CVaR shares | P2 (n declared) |
| `risk_studio.tail_dependence` | **518** (k=**26** exceedances) | `total_observations`, `exceedances_count` | `evt_pot_var_99`, `evt_pot_es_99`, `historical_var_99`, `historical_es_99`, `is_fat_tailed` | **P1 — SI-6** |
| `risk_studio.volatility_cone` | **2486** series, 2235–2477 overlapping windows | `window_days` 10/21/63/126/252 | 5 × {min, p25, median, p75, max, `percentile_rank`}, `current_forecast` | **P1 — SI-7** |
| `regime` | **719** (benchmark) | `data.observations`, `model.observations` | `regime_probabilities`, `stability_pct`, `transition_matrix`, 3 × {`ann_ret`, `ann_vol`} | **P1 — SI-11** |
| `regime` per-state | **undeclared** (~222 / ~383 / ~114) | — | `states[].ann_ret` (−0.2666 / 0.1228 / **0.8627**), `ann_vol` | **P1 — SI-11(c)** |
| `regime.portfolio_in_current_regime` | **19** | `days` | `total_ret` only; `ann_ret`/`ann_vol` **withheld** | **CLEAN — exemplary** |
| `regime.recent_history` | 120 | `series` length | `recent_history_self_transition_pct` 96.64, `transitions` 119 | declared |
| `monte_carlo` | **500** (1.98 yr) | `model_observations` | `historical_mu_annual` 0.1297, `historical_sigma_annual` 0.1972, `student_t_df` 4.51, all 60 fan/percentile values | **P1 — SI-8** |
| `monte_carlo` | 2000 paths | `num_paths`, `seed` 42 | `prob_success` 0.3715, `expected_shortfall_vs_target` | **P1 — SI-8** |
| `pairs` | **91** tests on **105–174** obs | `usable_observations_by_ticker`, `pairs[].overlap_observations` | 4 `is_cointegrated`, 4 `johansen_cointegrated`, 83 `agreement_count`, 91 p-values, 91 OU half-lives | **P0 — SI-1, SI-13, SI-14** |
| `liquidity` | **20–22** | `observation_window.per_ticker.*.observations` | all scores, bands, `days_to_liquidate_*`, ADV, Amihud | **P2 — SI-19** |
| `india_flows.liquidity_limits` | 30 sessions | `adv_lookback_sessions` | ADV, Amihud, liquidation days | P2 |
| `india_flows.delivery_anomalies` | 20 × 14 = 280 (latent) | `lookback_days` 20, `sigma_threshold` 2 | anomaly z-tests | **latent — SI-16** |
| `stress_testing` | **20** min | `volatility_adjustment.min_observations` | 14 vol factors (12 at a clip bound), 4 scenarios | **P2 — SI-17** |
| `forecast_risk` | 174 | `portfolio.observations` | `volatility_forecast`, `var_forecast`, `cvar_forecast`, `confidence_interval` | **P0 — SI-3** |
| `concentration` / `optimization` / `volatility_sizing` | n/a (closed-form / weights) | — | HHI, N_eff, Gini, target weights, inverse-vol sizing | not applicable |

**n < 30 flagged:** none of the *published* statistics rests on fewer than 30 observations — the `MIN_ANNUALIZE_DAYS = 30` gate does hold at the bottom, and `realized_risk` correctly withholds NIFTYIETF's annualized ratios at n=20 with a warning naming the 30-observation requirement. That is a real and creditable piece of engineering.

**n NOT published:** the per-state `n` in `regime.states[]` (SI-11c); the window count and effective count in every `volatility_cone.windows[]` row (SI-7); the observation count inside the `realized_risk.data.portfolio` block that carries `sharpe_ratio: 3.4856` (SI-2); the number of tickers active per day in `tear_sheet.full_history` (SI-15); the unclipped value behind `risk_score.components.factor_risk: 30` (SI-12a); the tail-support count behind `realized_risk.portfolio.cvar_95` (SI-4); the `alpha` for every one of the 28 `risk_contribution` Euler/CVaR shares.

---

## Effective sample size (mandate item 3)

The holding window is 39 rows; `full_history.observation_count` is 2,486. Two distinct effective-N questions arise.

**Autocorrelation of the holding-window returns.** I estimated AR(1) on the only return series the artifact publishes (18 usable returns from `dashboard.performance_history`):

```
  portfolio  n=18  AR1 rho=-0.1399  (se 0.2624, t=-0.53, p=0.601)  VIF (1+rho)/(1-rho)=0.755
  benchmark  n=18  AR1 rho=+0.0054  (se 0.2644, t=+0.02, p=0.984)  VIF=1.011
  95% CI on the portfolio AR(1): [-0.654, +0.374]
```

**Honest reading: on this sample there is no evidence of positive autocorrelation** (ρ = −0.14, p = 0.60; negative autocorrelation would *reduce* the effective N below n). But the interval is wide: an AR(1) of **+0.374 is not excluded**, which corresponds to a variance-inflation factor of 2.17 and an effective N of **17.9 of 39**. So autocorrelation could plausibly halve the effective sample, and the artifact provides no way to tell.

**The artifact's decisive answer is that it never checks.** String search: `autocorrel` 0 hits, `newey` 0, `HAC` 0, `ar1` 0, `serial` 0, `variance_ratio` 0. **The code does check, and throws the answer away** — `app/services/analytics_engine.py:1750` and `:1786` fit every factor regression with `cov_type="HAC", cov_kwds={"maxlags": 5}`, which is a Newey–West correction for autocorrelation and mean reversion in the residuals. The HAC standard errors it produces are discarded three lines later (SI-9). So the correct treatment exists in the codebase, is applied to 15 regressions, and is published for none of them.

**The Lo (2002) Sharpe SE above is the iid baseline; an AR(1) of +0.37 would multiply it by √2.17 = 1.47, taking t from 0.516 to 0.351 (p = 0.73).** The Sharpe is not significant under either assumption.

**Overlapping-window effective N in the volatility cone** is the second, larger effective-N problem, and it needs no distributional assumption at all — the windows share (L−1)/L of their data by construction:

| `window_days` | windows | effective N (iid) | 95% half-width on the published `percentile_rank` |
|---:|---:|---:|---:|
| 10 | 2,477 | 247.7 | ± 6.2 pp |
| 21 | 2,466 | 117.4 | ± 9.0 pp |
| 63 | 2,424 | 38.5 | ± 15.8 pp |
| 126 | 2,361 | 18.7 | ± 22.6 pp |
| **252** | 2,235 | **8.9** | **± 32.9 pp** |

The 252-day cone — the one reporting `percentile_rank: 1.9`, the section's most quotable claim — is a **nine-observation statistic**. This is the artifact's clearest effective-sample-size failure and it needs no distributional assumption to establish. See SI-7.

---

## Multiple comparisons across the whole export (mandate item 4)

See the table in **SI-5**. Summary: **495 hypothesis tests carry an explicit α; 0 corrections are declared.** Expected false discoveries under independence: 4.55 (Engle-Granger) + 4.55 (Johansen) + 0.75 (factor alphas) + 12.74 (delivery anomalies, latent) = **22.6**, against an observed 8 flagged anomalies in this export (4 + 4). Because the 91 pair tests are positively dependent through shared endpoints, the independence assumption *over*-states the pair expectation, so the true expectation is lower than 22.6 — but the observed 8 is then *worse* relative to it, not better. The artifact is honest about units and coverage and silent about multiplicity everywhere.

**Per the brief's framing — "an agent reading this will treat every flagged anomaly as signal" — this is correct, and it is the single most consequential structural property of the export.** Four of the eight flagged anomalies are in the pair section (where the null expectation is 4.55 per test family, so essentially all of them are expected), two are 100%-saturated or hardcoded constants (`risk_score.factor_risk: 30`, `forecast_risk.confidence_interval`), and the remaining two are regime labels from an unvalidated in-sample HMM. **Zero of the eight survive a multiplicity correction or a convergence check.**

---

## P-hygiene (mandate item 5)

**Clean, and worth saying plainly:**

- **93 unique p-value fields; 0 out of range.** All in `[0, 1]`; min 0.002609, max 0.990682. No sentinel `0.0` or `1.0` — the earlier scan flagged `1.0` from a differently-keyed field, and a targeted re-scan of the 91 `*pvalue*` rows found **no** value equal to 0.0 or 1.0. **No hardcoded default p-values.**
- **The p-value belongs to the named test.** Verified against `mackinnonp(t, 'c', N=2)` for all 91 pairs: max absolute deviation **2.38e-05** (JSON rounding at 6 dp). **0 monotonicity violations** — p decreases monotonically as |t| grows across the whole scan. The `decision_test: "engle_granger"` / `johansen_role: "diagnostic_only"` labelling is correct and applied consistently on all 91 rows. **No test/p-value mismatch.** (The Johansen boolean publishes no p-value at all — SI-13, SI-21.)
- **The comparison operator is correct and consistent.** `app/services/cointegration_service.py:399` — `is_coint = bool(engle_granger_pvalue < p_value_threshold)` uses **strict `<`**, the conventional choice. Verified: 4 pairs with p < 0.05, **0** with p exactly == 0.05, so the `<` vs `<=` ambiguity is not load-bearing in this export.
- **No p-value sits exactly at the threshold**, so no boundary-ambiguity finding arises.
- **`test_roles` and `summed_count_note` are exemplary.** `test_roles = {"engle_granger": "published_decision", "johansen": "diagnostic_only"}`, and `summed_count_note` explicitly warns that `is_cointegrated` and `johansen_cointegrated` "are different tests and must NOT be added: a pair can carry both." That is a subtle trap that most artifacts fall into, and this one closes it in the payload.

**Not clean:**

- **The rule is not restated per row.** `decision_test` and `johansen_role` are published on every pair, but the **α and the operator are not**. An agent reading a single pair row sees `is_cointegrated: true` with no way to learn it was tested at 0.05 with `<`. The α lives only in `sections.pairs.inputs.p_value_threshold`, three levels up.
- **Johansen publishes no p-value, only a boolean** against the 95% critical value, so 91 of the 182 tests run in this section are unquantifiable — and, per SI-13, a failed test is indistinguishable from a negative one.

---

## Confidence intervals (mandate item 6)

Full audit in the SI table above. Ranked by severity:

1. **`forecast_risk.confidence_interval` = hardcoded ±20%** — P0, SI-3. Not a CI at all.
2. **`realized_risk.portfolio.cvar_95` from ~2 observations** — P0, SI-4. Level stated (95), sample undeclared, CI absent.
3. **`monte_carlo.prob_success` with no MC error bar** (binomial SE 0.0108 available) and no parameter interval (`mu` t = 0.93, p = 0.35) — P1, SI-8.
4. **`risk_studio.tail_dependence` 99% VaR/ES with no CI** and a clip imposed against a p = 0.0015 rejection — P1, SI-6.
5. **`volatility_cone` percentiles and ranks with no n and no effective n** — P1, SI-7.
6. **`monte_carlo.expected_shortfall_vs_target` with no α, no n, no units** — P1, SI-8. Genuinely uninterpretable: it is a 62.85th-percentile conditional mean wearing the name of a tail expectation.
7. **All 55 fan-chart percentiles and the 5 terminal percentiles carry no MC error bar** — P2. The *levels* are honestly named (`p5`…`p95`) and `num_paths: 2000` is declared, so these read as simulation percentiles rather than intervals, which is defensible labelling with a missing error bar.
8. **`regime.regime_probabilities.crisis = 99.9993`** — P1, SI-11(b). Five significant figures on a degenerate in-sample posterior with no convergence flag.
9. **`dashboard.risk_score.overall_score = 13.7`** — P2. A 0–30 weighted composite with published weights and methodology but **no n and no interval**; a score of 13.7 implies a ±? that is never stated.

**Genuinely clean CI disclosures, for the record:**
- `stress_testing.scenarios.*.confidence_level = 0.95` with `confidence_basis: "nominal_label_not_simulated"` and `units.confidence_level: "unitless_nominal_label"` — SI-17. Exemplary.
- `regime.stability_pct = 96.7` with `stability_pct_rule` (the formula in words) and `stability_pct_observations = 719` — SI-11. Exemplary.
- `regime.portfolio_in_current_regime` withholding `ann_ret`/`ann_vol` at n=19 with `minimum_observations_required: 30` — SI-11. Exemplary, and the model SI-2 argues `tear_sheet` should follow.
- `monte_carlo.success_definition_detail` — a correct six-line statement of what `prob_success` does and does not measure. Exemplary.

---

## Outlier / contamination sensitivity (mandate item 7)

**The brief's premise does not hold for SELECTIPO.NS on volatility, and I should say so rather than manufacture a finding.**

```
  [holding window, n=36-39] volatility ranking        [instrument window, n=175] ranking
   1. ARROWGREEN.NS  0.4749                             1. ARROWGREEN.NS  0.5588
   2. REDINGTON.NS   0.3746                             2. ELECTCAST.NS  0.5201
   3. MCX.NS         0.3645                             3. REDINGTON.NS   0.4767
   4. MAFANG.NS      0.3472                             4. MOTILALOFS.NS  0.4013
   ...                                                   5. MCX.NS         0.3919
  11. SELECTIPO.NS   0.1059                             ...
  12. JUNIORBEES.NS  0.0961                            11. SELECTIPO.NS   0.1915
  13. MIDCAPIETF.NS  0.0877                            12. JUNIORBEES.NS  0.1819
                                                      13. MIDCAPIETF.NS  0.1801
                                                      14. NIFTYIETF.NS   0.1645
```

SELECTIPO.NS ranks **11th of 13** on realized volatility in the holding window and **11th of 14** at n=175. It is the artifact's *lowest*-volatility mid/small-cap name, not a volatility outlier. **MAFANG.NS** is the genuinely volatile one (4th at n=39, 0.3472).

**Constant-ρ portfolio-volatility screen** (using the artifact's own published `risk_score.avg_pairwise_correlation = 0.1059` and its own published per-ticker volatilities; this is a screening approximation, not a reconstruction, since no covariance matrix is published):

```
  [holding window, n=36-39]  usable tickers = 13
     baseline (all)         sigma_p = 0.108835   (+0.00%)
     drop SELECTIPO.NS      sigma_p = 0.112649   (+3.50%)
     drop MAFANG.NS         sigma_p = 0.109251   (+0.38%)
     drop BOTH              sigma_p = 0.113217   (+4.03%)
  [instrument window, n=175]  usable tickers = 14
     baseline (all)         sigma_p = 0.140032   (+0.00%)
     drop SELECTIPO.NS      sigma_p = 0.144059   (+2.88%)
     drop MAFANG.NS         sigma_p = 0.141876   (+1.32%)
     drop BOTH              sigma_p = 0.146124   (+4.35%)
```

**Dropping both names moves portfolio volatility by +4.0% to +4.4%.** That is a modest swing — the book is not fragile to these two names. **I am reporting this as a clean result, not manufacturing a finding to satisfy the brief.**

**The real SELECTIPO.NS fragility is not volatility — it is three other things:**

1. **Survivorship exposure in the 2,486-day back-fill.** `per_ticker_return_observations.SELECTIPO.NS = 380` of 2,486 (**15%**); NIFTYIETF.NS 612 (25%), MAFANG.NS 1,323 (53%), MIDCAPIETF.NS 1,635 (66%). The `full_history` CAGR of 21.97% and Sharpe of 0.969 are computed over a period during which the "14-name portfolio" was substantially smaller. See SI-15.
2. **Misclassification in the stress model.** `instrument_overrides.SELECTIPO.NS = {sector: "Exchange Traded Fund", sector_elasticity: 1.15, basis: "instrument_override_selectipo"}` — a micro-cap equity modelled with ETF elasticity, directly setting its stress loss. See SI-17(c).
3. **Market cap is a floor, not a measurement.** `liquidity.scoring.market_cap_provenance = {estimated: 4, fallback: 1, measured: 9}`, with SELECTIPO.NS the one sitting on the fixed ₹1,000,000,000 floor. The liquidity warning names this explicitly. **Cleanly disclosed.**

**One genuine anomaly I could not resolve, reported as such.** `risk_contribution` assigns MAFANG.NS — 2.73% of weight, 4th-most-volatile name at n=39 (0.3472) — a volatility risk share of **0.152%** and a CVaR-tail share of **0.447%**, the lowest of all 14 by a wide margin. Under the artifact's own published ρ = 0.1059 and MAFANG's own published σ = 0.2812, the constant-ρ screen implies a variance share of **0.598%** — roughly **4× the published figure** — and reconciling the published `portfolio_volatility_annualized = 0.1789` would require an implied MAFANG-vs-rest correlation of **+6.08**, which is impossible. So either the shares or the total is inconsistent under the artifact's own published ρ.

**I am explicitly not calling this a proven error**, for two reasons I can verify: `risk_contribution` uses a 251-day window while `instrument_risk` publishes 175 days, so my σ inputs are not window-matched; and **the artifact publishes no covariance matrix, no per-leg marginal contribution, no per-leg correlation and no per-leg observation count**, so the decomposition cannot be reproduced or falsified from the export. That un-auditability is the finding: 28 risk shares on a portfolio whose published total cannot be reconciled against them, with no intermediate quantity published. Severity P1, folded into SI-5's structural point rather than raised as a separate numerical claim.

---

## Degrees of freedom (mandate item 8)

| Regression / test | n | k | df | Adequate? |
|---|---:|---:|---:|---|
| `factor_exposure` portfolio OLS (α, β) | 174 | 2 | **172** | Yes |
| `risk_score.factor_model` portfolio OLS | 36 | 2 | **34** | Marginal — `se(β) ≈ 0.167`, drives a "HIGH RISK" alert and a saturated 30/30 leg |
| `factor_exposure` per-position OLS (14×) | 101–166 | 2 | 99–164 | Yes in this export |
| — code floor | **10** (`analytics_engine.py:1743, 1782`) | 2 | 8 | **No.** A 2-coefficient regression with `cov_type="HAC", maxlags=5` on 10 rows. Not exercised here (min 101) but the gate is wrong. |
| Engle-Granger two-step (91×) | 105–174 | 2 + ADF lags | ~n−2−lags | Adequate |
| — code floor (`MIN_PAIR_OBSERVATIONS`) | **30** (`cointegration_service.py:53`) | — | ~27 | Thin for a trace statistic calibrated at large n; and the reported p-value is asymptotic regardless (SI-14) |
| Johansen trace, bivariate `det_order=0, k_ar_diff=1` | 105–174 | 3/eq | 102–171 | Yes |
| Gaussian HMM, 3 states, `params="mc"`, 2 features | 719 | 15 | 704 | Yes on df. Fails on **convergence disclosure** (SI-11b), not on df. |
| GPD/POT shape ξ (MLE) | k = **26** | 1 | 25 | `SE(ξ̂) = 0.0575`; the clip at −0.5 is rejected at **p = 0.0015** (SI-6) |
| 95% VaR / ES (historical, n=39) | 39 | 1 quantile | tail support = **~2** | **No** (SI-4) |
| `kurtosis` (n=39) | 39 | — | `SE = 0.7845` | Significant; **`skew` at `SE = 0.3922` is not** (SI-20) |
| `Sharpe` (n=39) | 39 | — | `SE = 6.7645` | **No — t = 0.516, p = 0.606** (SI-2) |
| `regime.states[].ann_ret` | **undeclared** (~114 for `bull`) | — | — | **n not published** (SI-11c) |

**No t-statistic or p-value is reported for any model fitted with insufficient n** — because the artifact reports **no t-statistic or p-value at all**, anywhere (SI-5). The df failures above are therefore latent: the point estimates are published without any indication of their precision, so a reader cannot tell a well-determined number from a nine-observation one. That is the df finding in one sentence.

---

## Recommendations, in priority order

1. **SI-1 / SI-5 — declare the multiplicity.** Publish the test family size next to every count, apply BH-FDR across the 91 pair tests, and suppress `SHORT_SPREAD`/`LONG_SPREAD` on pairs that do not survive. On this data that means shipping **zero** cointegrated pairs, which is the correct answer.
2. **SI-2 — raise and split the annualization gate.** `MIN_ANNUALIZE_DAYS = 30` cannot support an annualized Sharpe. Withhold Sharpe/Sortino/Calmar/omega/tail-ratio below ~500 daily observations, exactly as `regime.portfolio_in_current_regime` already does at n=19. Attach `observations` inside every block that publishes a ratio.
3. **SI-3 — rename `confidence_interval`.** It is `[0.8 × point, 1.2 × point]` at `analytics_engine.py:1577`. Either simulate a real forecast interval or rename to `nominal_band_multipliers` with a basis string. Copy the `stress_testing` disclosure pattern (`confidence_basis`, `units`) — the codebase already has it.
4. **SI-4 — suffix and gate the tail measures.** `var_95_daily` / `cvar_95_daily` (as `risk_contribution` already does), `observations` inside the block, and withhold the ES when tail support is under ~20.
5. **SI-9 — publish the inference you already compute.** The HAC standard errors from `analytics_engine.py:1750` / `:1786` are computed and discarded for 15 regressions. Emitting `alpha_se`, `alpha_t`, `alpha_p` and a 95% CI is a few lines and would move the artifact from "point estimates" to "measurements". Also compound `annualized_alpha` (`:1761`, `:1796`).
6. **SI-6 / SI-7 — publish effective N.** One field per `volatility_cone` row (`n_windows`, `n_effective`) and a bootstrap interval on the 99% GPD quantile would close the two largest remaining gaps. Report the ξ clip as a test result.
7. **SI-11 — fix the feature name, publish convergence, publish per-state n.** `regime_service.py:446` (`log_holding_return` → the benchmark), `:226` (capture `monitor_.converged`), `:235` (publish `n_sub`).
8. **SI-10 / SI-18 — make the cross-references bidirectional.** Rename to embed the window (`r_squared_174d`, `portfolio_vol_39d`) and add the reciprocal note to `factor_exposure` that `risk_score` already carries.
9. **Adopt the existing good pattern everywhere.** `stress_testing`'s `*_basis` fields and `regime`'s `*_provenance` / `*_rule` / `*_observations` fields are the house style the rest of the artifact should meet. The disclosure engineering exists; it is aimed at the wrong problems.

---

## Reproduction

All figures above were produced with `numpy` / `scipy` / `statsmodels 0.15.0` via `uv run python` from `C:\es\coding\finengine\backend`, reading the artifact with `json.load(..., encoding='utf-8')`. Scripts used: `si_quant.py` (volatility screen, MAFANG audit), `si_census.py` (volatility ranking, multiple-comparison census, p-hygiene, CI audit), `si_final.py` (clip saturation, R² CIs, correlation stability), plus inline one-liners for the pair-test statistics, the Lo Sharpe SE, the effective-N tables, the R² Fisher intervals and the string searches. Arithmetic I was able to verify against the payload reproduced it exactly: the `cagr` compounding identity `(1+0.056879)^(252/39)−1 = 0.429684` vs published `0.429686`; all four stress `portfolio_impact × 1.15` values; all 91 Engle-Granger p-values against `mackinnonp` to 2.4e-05; `var_forecast`/`cvar_forecast` unit scaling; the position weights summing to `1.0000000000`; and the 0.8/1.2 identity in `forecast_risk.confidence_interval` to all 17 published digits.
