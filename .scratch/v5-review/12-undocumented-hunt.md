# 12 — Undocumented-defect hunt against `v26.json`

**Artifact** `C:\Users\Sayanti\AppData\Local\Temp\opencode\v26.json` · 987 515 B ·
`export_id` `portfolio-faa83a4589f1` · `schema_version` `2.0` ·
`generated_at` `2026-09-29T17:45:55.163516Z` · 17 sections · 14 positions ·
`total_value` **42 624.499923706055 INR** · `base_currency` `INR`.

**Method.** Every number below is the output of a Python script written outside
the repo (`C:\Users\Sayanti\AppData\Local\Temp\opencode\h01..h29*.py`, run under
`uv run --no-project --python 3.12`). No source, test or existing doc was
read-modified or written other than this file. No `git stash` / `checkout` /
`restore`.

**Order of work.** (1) mechanical resolution of every pointer class; (2)
recomputation of load-bearing figures from their own published inputs;
(3) exhaustive extraction of every numeric literal from every prose string and
matching it against every published number; (4) regression watch on the v19
findings; (5) the sections nobody had reviewed (`volatility_sizing`,
`risk_contribution`).

---

## 1 · Pointer resolution — the mechanical sweep the brief asked for

**Result: 0 dangling pointers. 209 pointer strings, all resolve. The payload is
clean on this class.**

| pointer class | count | resolves |
|---|---|---|
| `data_ref` (dashboard de-dup) | 8 | 8/8 to a real section |
| `precision_disclosure_at` | 5 | 5/5 |
| `published_value_at` | 5 | 5/5 |
| `published_also_at` | 2 | 2/2 |
| `snapshot_consistency_measured.*_at` | 3 | 3/3 |
| `window_ref` | 8 | 8/8, all present in the sibling `measurement_windows.windows` |
| `inherits_precision_at_path` (list form) | 17 | 17/17 |
| `inherits_precision_at` (dotted form) | 22 | 8/22 — see §1.1 |
| `published_at` (root-anchored, `<component>` expanded) | 60 | 60/60 |

### 1.1 the dotted twin of `inherits_precision_at_path` fails on 14/14 position legs — **disclosed, not a defect**

```
at_path = ["precision","estimated_statistics","positions","CIPLA.NS","estimates","volatility_forecast"]
   -> resolves, point 0.19598052754718792
at      = "precision.estimated_statistics.positions.CIPLA.NS.estimates.volatility_forecast"
   -> a '.'-splitting walker lands on precision.estimated_statistics.positions.CIPLA -> KeyError
```

This is **not** a finding. `inherits_precision_at_basis`, verbatim, on every one
of the 14 legs:

> "inherits_precision_at_path is the AUTHORITATIVE pointer: a list of keys walked
> from the root of this payload. The dotted inherits_precision_at beside it is the
> same pointer written for reading and is NOT resolvable by splitting on '.',
> because the position keys it traverses are ticker symbols such as CIPLA.NS and
> contain dots of their own"

Correct, and the list form is the one that resolves. Recorded so the next pass
does not re-report it.

### 1.2 `data_ref` — resolves, and the identity it claims HOLDS

`components.{portfolio,realized_risk,forecast_risk,factor_exposure,concentration,liquidity,regime,risk_contribution}`
carry `data_ref: "sections.<name>"`, `data_ref_status: "referenced"`,
`data_inline: false`, and **no `data` key** — the payload really is de-duplicated.
The other three (`summary`, `performance_history`, `risk_score`) carry
`data_inline: true`, have no `data_ref` (there is no such section to point at),
and their `data` has **0** byte-identical copies elsewhere in the document.

`component_reference_policy` claims nine fields "are copies of the referenced
section's, so the two paths cannot disagree". Tested, 8 components × 9 fields:

```
fields checked = 72   disagreements = 0   policy-fields-absent = 8
```

72/72 identical. **The strongest claim in the document verifies.** The one gap:
`error` is named in the policy and **0 keys named `error` exist anywhere in the
987 515 B** — a vacuous mention. P3.

---

## 2 · New defects, ranked

### P1-1 · the `concentration` leg inherits its precision from the *declared-constants* block — the wrong class, and the prose asserts it

```
sections.dashboard.data.components.risk_score.data.score_audit.precision.derived_values.concentration
  .input_statistic             = 'herfindahl_index'
  .input_statistic_provenance  = 'measured'
  .inherits_precision_at       = 'score_audit.precision.declared_constants'
  .standard_error_reason       = "...Its precision is entirely INHERITED from that
                                  input's own disclosure, published at
                                  score_audit.precision.declared_constants."
```

The node named resolves, and it is the wrong node. `precision.declared_constants`
publishes `table: "app/services/analytics_engine.py: RISK_SCORE_WEIGHTS"`,
`nominal_weights {concentration 0.2, volatility 0.25, correlation 0.2,
factor_risk 0.25, market_risk 0.1}` and `standard_error: null`. The string
`herfindahl_index` does **not** occur in it (checked mechanically).

The payload's own taxonomy, three keys above, in the same object:

```
precision.classes.declared_constant     = "chosen by design; carries no standard error
                                           and no interval, because it was never estimated"
precision.classes.estimated_statistics  = "measured from data on this section's own sample"
```

So the concentration sub-score — `min(30, herfindahl_index * 100)`, a function of
a statistic the payload proves was measured (`sum(w^2) = 0.0855551049728946` over
the 14 published weights, which rounds to the published `0.0856` exactly) —
declares that it inherits from the block of things that "were never estimated".
`input_statistic_provenance: "measured"` and the pointer are in the same object.

The four siblings are consistent with each other and inconsistent with this one:

| leg | input | provenance | pointer resolves to |
|---|---|---|---|
| `concentration` | `herfindahl_index` | measured | **`declared_constants`** |
| `volatility` | `portfolio_return_annualized_volatility` | measured | `null` + honest reason |
| `correlation` | `avg_pairwise_correlation` | measured | `estimated_statistics.…avg_pairwise_correlation` |
| `factor_risk` | `benchmark_regression_r_squared` | measured | `estimated_statistics.factor_r_squared` |
| `market_risk` | `recent_portfolio_return_annualized_volatility` | measured | `null` + honest reason |

`volatility`'s reason is the model to copy: *"published at no precision disclosure
for this input is published in this section … the sub-score's precision is
therefore declared unstated rather than asserted."* `concentration` should say
the same. `precision.estimated_statistics` has only two keys
(`avg_pairwise_correlation`, `factor_r_squared`) — there is no HHI disclosure
anywhere, and the payload should say so.

**Not a wrong number. A disclosure pointer into the wrong class, repeated in
prose.** P1.

### P1-2 · a template-splice artifact in a published prose string, on 14/14 position legs

`sections.forecast_risk.data.precision.derived_values["positions.<T>.var_forecast"].inherits_precision_reason`

Sentence [2], verbatim:

> "The portfolio leg's sigma IS measured on this same payload, at
> `precision.estimated_statistics.portfolio.estimates.`<b>the fitted leg's
> return-space sigma is its own published annualized volatility times
> sqrt(h / 252), which is an identity of the cumulative-variance path - exact
> unless the published annualized clip bounds are active on this leg, and
> derivation_residual says which case this is**"

A path terminated by a period, immediately followed by a fragment of
`derivation_precondition` with its subject and predicate stripped. The sentence
is ungrammatical and the path it appears to name
(`precision.estimated_statistics.portfolio.estimates.`) resolves to nothing.
Present on all 14 legs (14 distinct strings, one per ticker, same defect).

### P1-3 · the same string says "there is no figure at the far end of it", and there is

Same string, sentence [1]:

> "The pointer is kept because the inheritance is real and the node it names is on
> this payload, but **there is no figure at the far end of it and none is
> claimed**; the target does publish the part of its precision that is free, its
> observation count, AR(1) and effective_n."

The far end, `precision.estimated_statistics.positions.CIPLA.NS.estimates.volatility_forecast`,
publishes:

```
point        = 0.19598052754718792
observations = 173
effective_n  = 155.0866
point_status = 'unverified'      status = 'not_computed'
reason       = "not measured: this leg's re-fit estimator was declared too expensive
                to run, so it was never evaluated rather than having run and failed."
```

What is absent is the **standard error and the interval** — which the sentence
does not say, and which its own `reason` states precisely. The `point` is
published by the *primary* fit, not the declined re-fit. So the disclosure
overstates the absence and mis-describes it. P1.

### P1-4 · `correlation_stability` now publishes a direction field that contradicts the message beside it

```
sections.risk_studio.data.components.correlation_stability.data
  .current_avg_correlation   = 0.1483
  .historical_threshold_10th = 0.2179      (current is below it)
  .historical_median         = 0.3404
  .alert_direction           = 'lower_tail_collapse'      <-- NEW
  .alert_level               = 'ELEVATED'
  .message                   = "Average pairwise correlation (0.148) is at or below
     the 10th percentile (0.218) of its own history (median 0.340). Co-movement has
     collapsed: this is a change of correlation regime, not a reassurance. Positions
     that diversified historically may not diversify against each other in this
     regime, so historical risk estimates that assumed the median correlation no
     longer describe this book. (tested two-sided against its own history of 490
     overlapping 60-day rolling windows.)"
```

v19's **NEW-4 is half-fixed**. The missing direction field now exists and says
`lower_tail_collapse`. The operative sentence is still the **high**-correlation
branch: a measured average pairwise correlation in the most-diversified decile of
its own history is being used to argue that diversification may fail. The field
that records the direction and the prose that draws the conclusion now sit in the
same object and disagree. Also still true: the per-row `series` schema carries
`threshold_90th` and `threshold_75th` and **not** `threshold_10th`, the one that
was breached.

### P2-1 · the cost accounting in `measurements_withheld` does not add up to itself

```
sections.forecast_risk.data.precision.measurements_withheld.why_not_measured
  "...3800 refits in total, 68.6 s of pure optimiser time and 74.2 s of route wall
   time, of which the portfolio leg's 1001 refits were 17.3 s and the fourteen legs'
   2800 were the remaining 51.3 s."
```

```
1001 + 2800 = 3801     claimed total = 3800     DELTA = 1
17.3 + 51.3 = 68.6     claimed optimiser total = 68.6 s      OK
14 x declined_draws_per_leg(200) = 2800                        OK
bootstrap_resamples (portfolio) = 1000  -> 1000 + 2800 = 3800  OK
```

The parts do not sum to the stated total, and the sibling string
`precision.resample_count_rule` in the same block uses **1000** where this one
uses **1001** ("the portfolio leg is resampled at the module's standard 1000
circular moving-block draws"). Two strings in one object, two totals for one
measurement. `resample_count_rule`'s other claim verifies: all 14 position blocks
publish `bootstrap_resamples: 0`, as it says they will.

### P2-2 · `effective_n` fails its own published formula on 25 of 49 blocks (v19: 5 of 21)

Swept every `{ar1, effective_n, observations}` triple in the document against the
formula the block itself publishes (`"n * (1 - ar1) / (1 + ar1)"`), tolerance =
half of the last published digit of `effective_n`:

```
autocorrelation blocks found: 49
blocks exceeding their own published precision: 25
worst: sections.forecast_risk...positions.MOTILALOFS.NS.autocorrelation
       n=173  ar1=-0.090892  effective_n=207.5926  |recomp-eff| = 2.449e-04
```

Root cause is the `ar1` display: it is published at 5–6 dp and `effective_n` was
computed from the unrounded value, so the published pair is not
self-reproducing. `effective_n` is published at **4 dp in 45 blocks, 3 dp in 3,
2 dp in 1**, with no rule anywhere.

Correctly done, for the record: `notes.effective_n_exceeds_observations` is
present on **exactly** the 9 legs whose `effective_n > observations` and on no
other, and explains the `> n` case correctly. All 49 blocks publish
`effective_n_basis` except the 9 note objects (which are the same facts
restated).

### P2-3 · `headroom_to_cap` is not `cap − sub_score` on 4 of 5 legs

```
sections.dashboard...risk_score.data.score_audit.components
  leg              sub_score   cap−sub_score   headroom_to_cap     delta
  concentration      8.6            21.4            21.440000     +0.040000
  volatility         7.6            22.4            22.384647     −0.015353
  correlation        6.2            23.8            23.793859     −0.006141
  factor_risk       30.0             0.0             0.000000      0.000000
  market_risk        7.6            22.4            22.384647     −0.015353
```

`headroom_to_cap` is `cap −` the **unrounded** sub-score; `sub_score` is published
at 1 dp. `score_audit` has **no** `display_rounding` block (the artifact's only
one is `sections.optimization.data.moments_basis.display_rounding`, a different
section). Unchanged from v19's NEW-3.

### P2-4 · `headline_share` sums to 1.001419 and no field says why — **and the brief's framing of this is a mis-read**

```
score_audit.effective_information
  responsive_share_of_headline = 0.370768
  pinned_share_of_headline     = 0.572519
  duplicate_share_of_headline  = 0.058132
  sum                          = 1.001419
  responsive_weight + pinned_weight + duplicate_weight = 0.65 + 0.25 + 0.10 = 1.0
  headline_weight_total        = 1.0
  sum(headline_contribution)   = 13.118601
  overall_score (risk_score.data) = 13.1
  overall_score_raw            = None
  implied denominator per leg  = 13.100002 / 13.100013 / 13.100032 / 13.100002 / 13.100100
```

`headline_share_reason` is `null` on all 5 legs, `share_undefined_reason` is
`null`, and there is no `share_rounding_rule` in `score_audit`. The shares divide
by the **rounded** 13.1 while the contributions sum to the **unrounded**
13.118601.

**The prose is not wrong.** `headline_weight_basis` reads "each leg sits in exactly
one of headline_bucket responsive/pinned/duplicate/excluded, and the first three
sum to 1 -- the whole headline". "The first three" is the three **weights**, and
they sum to `1.0` exactly, with `headline_weight_total: 1.0` published beside it.
`1.001419` is the three **shares** — a different quantity. The finding is a
disclosure gap on the shares' denominator (v19's NEW-2), not a false statement.
Bucket arithmetic is otherwise exact: every leg is in exactly one bucket, the
bucket lists match, `measured_leg_count` 5, `independent_leg_count` 4,
`independent_weight` 0.9 = 1 − `duplicate_weight`.

### P2-5 · `risk_contribution` names its tail model two different things in five containers

```
sections.risk_contribution.data
  .positions                                -> ['volatility', 'cvar_tail']
  .excluded_assets                          -> ['volatility', 'cvar_tail']
  .contribution_basis.per_model             -> ['volatility', 'cvar_tail']
  .sector_rollup                            -> ['volatility', 'cvar']          <--
  .contribution_basis.sector_rollup_per_model-> ['volatility', 'cvar']          <--
```

`cvar_tail` three times, `cvar` twice, for one model, in one object. A consumer
keying on `cvar_tail` misses `sector_rollup`; a consumer keying on `cvar` misses
`positions`. The block is otherwise **exemplary** — see §3.

### P2-6 · `below_minimum_notional: true` cannot be verified from the published `notional_floor`

```
sections.volatility_sizing.data.trades.MCX.NS
  .shares_delta            = 0
  .amount                  = -1038.76
  .sizing_price            = 3324.89990234375
  .below_minimum_notional  = true
  .status                  = 'below_minimum_notional'
  .reason                  = "notional 1038.76 is below one whole share at 3324.8999,
                              so the instruction rounds to zero shares"
trade_reconciliation.notional_floor = 42.624499923706054
```

```
|amount| / notional_floor        = 24.37x
recommended_weight * PV / floor = 51.46x
rounded notional (0 sh * price) = 0        -> below the floor: True
```

The flag is true only under the "rounded notional" reading, i.e. against **one
whole share = 3324.90**, not against the published `notional_floor` of 42.62. A
reader who verifies the flag from `notional_floor` — the only number published
for it — gets the wrong answer on 1 of 14 legs. The correct rule exists only as
free text inside one leg's `reason`; there is no `notional_floor_rule`. MCX is
also the only leg missing `leg_status`.

### P2-7 · `published_input_as` points at the wrong copy on 2 of 5 legs

```
correlation .published_input_as = 'avg_pairwise_correlation'   -> 0.1241  (4 dp)
           .input_statistic_value = 0.124123 (6 dp, the value the sub-score used)
factor_risk .published_input_as = 'factor_r_squared'            (input_statistic is
           'benchmark_regression_r_squared')                     'benchmark_regression_r_squared')
concentration / volatility / market_risk -> point at their own input_statistic_value   OK
```

Harmless at the current values; a recomputability gap, and the pointer discipline
is inconsistent inside one object. v19's R1 residual, unchanged.

### P2-8 · `tail_ratio`'s standard error and its interval describe distributions 4.84x apart

```
sections.tear_sheet.data.estimate_uncertainty.metrics.estimates.tail_ratio
  .point = 1.35862   .standard_error = 30.692291
  .conf_int = [0.843381, 7.18955]   (full width 6.3462)
  .point_within_conf_int = true    .point_within_conf_int_note = null
  se / point   = 22.6x        se / CI full width = 4.84
```

Across all **151** records carrying both a `standard_error` and a `conf_int`:
median `se/full-width` 0.26, and **`tail_ratio` is the only record above 2.0**
(next is 0.36). `omega` has *improved* to 0.29. So v19's NEW-10 survives, now
isolated on one statistic, with no note. (v19 reported `omega` at 3.05x by the
`se / full-width` normalisation; by that measure it is 0.29 today.)

### P3 · the rest

| # | finding | evidence |
|---|---|---|
| P3-1 | `precision_inheritance_factor` on 14 position legs is `0.10362525968336314` = `var_z_multiplier x sqrt(1/252)`, but its basis says "**the constant** this formula multiplies its input by". It is the product of the declared constant and an unclassified day-count literal. `declared_constants.constants` has 4 entries (`var_confidence_level`, `var_horizon_days`, `var_z_multiplier`, `cvar_es_multiplier`) — no day count; `coverage.classified_keys` (123 entries) has none either. The arithmetic purpose is right (`SE x factor` is the SE of the derived value). | `1.645*sqrt(1/252) == 0.10362525968336314` → True |
| P3-2 | `component_reference_policy` names `error` among the nine copied fields. 0 keys named `error` exist in the document. | mechanical count = 0 |
| P3-3 | `trade_gate_reconciliation.rule` says "**every** leg's executable status is restated"; `restated_trade_count` = 13 of 14 (MCX is not restated). The same sentence's last clause correctly says "cannot collect 13 order instructions", so the payload is aware. | `restated_trade_count: 13`, `priced_trades: 14` |
| P3-4 | `precision.headline_attribution.standard_error_reason` says the attribution is "published at full precision because the payload is expected to be **exactly** recomputable from its inputs". It is not: recomputing from the published 6-dp `input_statistic_value` gives Δ = 1.2e-05 (`volatility`), 5e-06 (`market_risk`), 2e-06 (`correlation`). | 1.903850 vs published 1.903838 |
| P3-5 | `min_rounding_tolerance` = 11.655 (MIDCAPIETF.NS) is published **without** a ticker, while `max_rounding_tolerance` and `max_abs_rounding_residual` both name theirs. There is no `min_rounding_tolerance_ticker` key. | key absent |
| P3-6 | `volatility_sizing.data.exposure` publishes one quantity twice under two names at two roundings: `gross_exposure` 1.219707 / `net_cash_weight` −0.219707, and `scale_factor` 1.219708 / `cash_weight` −0.219708. `1 − net_cash_weight == gross_exposure` exactly; `1 − cash_weight == scale_factor` exactly. | both identities exact |
| P3-7 | `data_ref_status` exists only on referenced components; the three `data_inline: true` components have no status field of their own beyond `status`. Consistent with the policy, noted so it is not re-litigated. | — |

### One brief item that does not exist

`_EGARCH_SIMULATED_NO_BAND` — and `EGARCH`, `egarch`, `E-GARCH`, `SIMULATED`,
`_NO_BAND`, `no_band`, `band_withheld_reason` — are **0 occurrences** in the
987 515 B. Whatever was rewritten, the token is not in this artifact. Reported as
UNDETERMINED whether the rewrite landed in this export or lives only in the
producer.

---

## 3 · Reconciliation — what ties

| identity | result |
|---|---|
| `sum(weight)` over 14 positions | `1.0` exact |
| `sum(market_value)` vs `total_value` | 42 624.499923706055, exact |
| `sum(w^2)` vs `concentration.herfindahl_index` | 0.0855551049728946 → 0.0856 exact |
| `1/sum(w^2)` vs `effective_positions` | 11.688373 → **11.69** exact |
| `N_eff/n` vs `diversification_ratio` | 0.834446 → **0.83** exact |
| `forecast_risk` `var_forecast` = `clip(-sigma*z, -0.99, -0.001)` | 0.0 error, and `derivation_residual` 0.0 |
| `forecast_risk` `cvar_forecast` = `clip(-sigma*2.06, …)` | 0.0 error, `derivation_residual` 0.0 |
| `cvar_to_var_ratio` = `2.06/1.645` **and** = `cvar_forecast/var_forecast` | 1.2522796352583587 both ways, 0.0 |
| 14 position `var_forecast` vs their own published `formula` (incl. `sqrt(1/252)`) | 14/14 exact, `derivation_residual` ≤ 1.4e-17 |
| 14 position `volatility_forecast` vs `estimates.point` (band-provenance, `point_tolerance` 1e-6) | 14/14, \|d\| = **0.0** |
| `score_audit` 5 sub-scores from `input_statistic_value` | 5/5 to 1 dp, 0 error |
| `score_audit` contributions = unrounded sub-score × weight | 3/5 to 1.2e-05 (rounding path), 2/5 exact |
| `score_audit` bucket lists vs per-leg `headline_bucket` | exact |
| `headline_attribution` vs per-leg `headline_contribution` | byte-identical |
| `full_history` `(1+total_return)**(252/metrics_observation_count) − 1` vs `cagr` | 0.2922165 vs **0.292217**, \|d\| 4.8e-07 |
| `observation_count − metrics_observation_count` vs `partial_coverage_days` | 2488 − 309 = 2179 = **2179** |
| `volatility_sizing` `sum(recommended_weights)` vs `gross_exposure` | 1.219707 exact |
| `sizing_volatility × scale_factor` vs `target_volatility` | 0.14999969 vs 0.15, \|d\| 3.1e-07 |
| `sum(trades.amount)` vs `execution.financing_requirement` | 9364.9 = **9364.9** exact |
| `trade_reconciliation` 3 aggregates recomputed from the 14 delivered trades | all 3 match exactly, and the argmax tickers match |
| every trade's `\|rounding_residual\| ≤ rounding_tolerance` | 14/14 |
| `risk_contribution` per-leg shares → `sector_rollup` (both models) | 14/14 legs, 7/7 sectors, \|d\| = **0.0** |
| `risk_contribution` model totals vs `contribution_basis.per_model` | 1.0 / 0.999999, residuals 0.0 / 1e-06 |
| vol-cone `percentile_rank_95pct_half_width_pct` = `1.96*100*sqrt(0.25/eff_n)` | 5/5 within 0.05 of the published 1 dp |
| `1.96*se` vs published `conf_int` half-width, 151 records | median ratio 0.98, max 1.20, **0 above 1.5** |
| `gpd_shape_xi_raw` quoted in `is_fat_tailed_withheld_reason` | −0.54336838, exact match |
| `volatility_sizing.methodology` 7 quoted numbers | 7/7 tie to their published fields |
| `component_reference_policy` 9-field copy identity | 72/72 identical |

### `risk_contribution` — newly available, and the cleanest block in the artifact

```
status 'available', warnings [], 17 keys, 2 models x 14 legs
positions.volatility  sum = 1.0        sector_rollup.volatility sum = 1.0
positions.cvar_tail   sum = 0.999999   sector_rollup.cvar       sum = 0.999999
sector reconciliation: 14/14 legs, 7/7 sectors, |d| = 0.0 for BOTH models
rounding_decimals 6, rounding_residual published per model and per rollup
calculation_window {2025-09-29, 2026-09-29, 172 days}, window {…, …}
portfolio_volatility_annualized 0.1781, portfolio_var_95_daily −0.018295,
portfolio_cvar_95_daily −0.027846
```

The v19 queue's "the most visible defect in the artifact" is fully closed, and
closed well. Only the `cvar_tail`/`cvar` naming (P2-5) is wrong.

---

## 4 · Regression watch vs v19 — nothing has regressed

| v19 item | v26 path | observed | verdict |
|---|---|---|---|
| `risk_contribution` 500s | `sections.risk_contribution.status` | `'available'`, 17 keys, `warnings: []`, arithmetic exact | **FIXED** |
| `forecast_risk` available + measured SE | `…data.precision.estimated_statistics.portfolio.estimates.return_space_volatility` | `point 0.006031124275927622`, `se 0.003051`, `conf_int [0.008239, 0.02012]`, `effective_n 108.4506`, `point_status reproduced_by_estimator` | **FIXED** |
| `alpha_annualized` null | `tear_sheet.data.relative_vs_nifty.alpha_annualized` | `null` (holding window) | FIXED |
| `is_fat_tailed` null + reason | `risk_studio…tail_dependence.data` | `null`; reason names `gpd_shape_xi_raw = -0.54336838` and both other fired signals | FIXED |
| vol-cone withholding + `effective_n` | `risk_studio…volatility_cone.data.windows[*]` | `percentile_rank` `[14.7, null, null, null, null]`; `effective_n` `[30.0, 13.76, 3.92, 1.46, 0.23]`; `min_eff_n` 30.0; first row published **exactly at** the gate | FIXED (boundary) |
| `snapshot_consistency_measured` | envelope | `multiple_instants`, 14 price instants, 6.823141 s spread; 3/3 `*_at` pointers resolve | FIXED |
| `accounting_basis` | `portfolio.data.accounting_basis` | 9 keys, `scope.covers` + `does_not_cover` both present | FIXED |
| `partial_coverage_days` in `full_history` | `tear_sheet.data.full_history` | `2179`; `2488 − 309 = 2179` | **FIXED** |
| tear-sheet beta `point_status: verified_against_independent_witness` | `tear_sheet.data.full_history.relative_vs_nifty` | `beta_vs_nifty 1.0931`, `alpha_annualized 0.2236`, both `verified_against_independent_witness`, `status computed`. **v19's P0 (NEW-1, sign inversion vs −0.2275) is GONE.** | **FIXED** |
| 14 positions | `portfolio.data.positions` | 14, `sum(weight) = 1.0` | FIXED |
| `score_audit` `floor` + `duplicate_components` | `risk_score.data.score_audit` | `floor 0.0`, `floor_clamped_components []`, `duplicate_components` n=1 (`market_risk`↔`volatility`, `identical`, `sample_dependent: true`, `clears_when` published) | FIXED |
| de-dup pointers resolving | `dashboard.data.components.*.data_ref` | 8/8 resolve, 0 `data` keys on referenced components, 72/72 copy identities hold | FIXED |

**Also fixed since v19, verified by arithmetic:**

- **NEW-7** (2488 advertised / 309 annualised, 9.11x) — **FIXED**.
  `metrics_observation_count: 309` + `metrics_window {2025-03-11, 2026-09-25, 309}`
  + `metrics_observation_count_basis`, which literally hands the reader the
  formula: *"(1 + total_return) \*\* (252 / metrics_observation_count) - 1
  reproduces `metrics.cagr` and the same expression on observation_count does
  not."* Verified: reproduces 0.2922165 vs published 0.292217.
- **NEW-5** (`current_forecast`'s copied `current_realized` sentence) — **FIXED**.
  Reason rewritten; no `current_realized` key on the object; new text correctly
  separates the model forecast from realised vol.
- **NEW-6** (vol-cone half-widths) — **FIXED**. All 5 now tie from the published
  `effective_n` to 1 dp.
- **QM-1 / XM-1** (partial-basket renormalisation) — still fixed.
- **NEW-10's `omega`** — improved from 3.05 to 0.29 on the same normalisation.

**Still open from v19, unchanged:** RL-7 (below), RL-1(c) `liquidation_time_days`
roll-up rule, RL-2 banding and Calmar convention, NEW-2 (→ P2-4), NEW-3 (→ P2-3),
NEW-4 (→ P1-4, half-fixed), NEW-8, NEW-9, NEW-10 (→ P2-8, now on `tail_ratio`).

**RL-7 re-checked, still open.** `concentration` publishes `diversification_score`
`98.5` with no `*_basis` / `*_unit` / `*_formula` / `*_scale` sibling (only the
two names `diversification_score`, `diversification_ratio` match `diversif`), and
no `"0-100"` / `"Calmar"`-style scale string anywhere in the block, while
`liquidity.data.scoring.scale` and `risk_score…score_audit.scale` both declare
theirs. Candidates recomputed against 98.5, none matches:

```
(1-HHI)*100 = 91.44      N_eff/n*100 = 83.4446     (N_eff-1)/(n-1)*100 = 82.1711
100-100*sqrt(HHI) = 70.7425     100*(1-gini) = 75.3     100*(1-gini/2) = 87.65
100*(1-sqrt(gini)) = 50.3009
```

UNDETERMINED — recovering it needs the `concentration` implementation in
`analytics_engine.py`, which two other agents own this session and I did not
read. `diversification_ratio` **does** reconcile: `N_eff/n = 0.834446 → 0.83`.

**`concentration.as_of = null`** is *not* a finding: it is explained in
`concentration.warnings[0]` — *"No valuation date: concentration is a
cross-section of live-quoted market-value weights, and a quote publishes the
instant it was refreshed rather than an observation date."* Correctly withheld.

---

## 5 · Prose sweep — coverage

Every leaf whose key matches
`(_reason|_basis|_rule|_note|_policy|_limitation|_convention|_semantics|_provenance|message|methodology)`
was collected: **1 678 prose strings**. Every numeric literal in them was
extracted (**1 518 literals**) and matched against **47 941** decimal
representations of all **7 718** numeric leaves in the document.

```
matched 1441   unmatched 77 (4 distinct literals)
```

All four vetted:

| literal | verdict |
|---|---|
| `-0.54336838` in `is_fat_tailed_withheld_reason` and `is_fat_tailed_basis.withheld_reason` | **false positive** — my matcher does not index negatives. `gpd_shape_xi_raw == -0.54336838` exactly. |
| `2800` in `precision.resample_count_rule` | **true** — `14 x 200 = 2800`. Consistent with `measurements_withheld`. |
| `0.219708` in `volatility_sizing.methodology` | **false positive** — `cash_weight == -0.219708` exactly. |
| `3800` in `measurements_withheld.why_not_measured` | **matched, but wrong** — see P2-1. |

So the prose sweep is **exhaustive and found one real numeric error**, which the
naive matcher could not see because "3800" matches a plausible reading. The
prose defects that *are* real (P1-2, P1-3, P1-4, P2-1, P3-3, P3-4) are all
found by reading the string against its siblings, not by literal matching.

---

## 6 · Uncertainty

1. **`diversification_score` = 98.5's formula.** Eight reconstructions, none
   matches. Needs the `concentration` code in `analytics_engine.py` (owned by
   two other agents this session; not read).
2. **Whether `precision_inheritance_factor`'s wording is a bug or a
   simplification.** The arithmetic is right for its stated purpose. Needs the
   producing code to know whether `sqrt(1/252)` is meant to be a declared
   constant. UNDETERMINED.
3. **`_EGARCH_SIMULATED_NO_BAND`.** Not in this artifact under any spelling.
   Cannot tell whether the rewrite landed in a different export or only in the
   producer.
4. **Whether the 14 `point_status: "unverified"` labels are a mislabel.** All 14
   reproduce their published point to \|d\| = 0.0 against a `point_tolerance` of
   1e-6, yet they read `unverified` while the portfolio leg reads
   `reproduced_by_estimator` for the same passing test. The portfolio leg also
   has `witness_status: "not_supplied"`, so `unverified` may be intended as the
   *witness* verdict — but the field is named `point_status` and one sibling uses
   it for the reproduction verdict. Needs the producing code to settle the
   vocabulary. UNDETERMINED — flagged, not asserted.
5. **Whether the concentration HHI pointer (P1-1) is a code bug or a
   hand-written string.** Either way the payload is self-contradictory; the fix
   is a producer change.
6. **NIFTYIETF's per-leg price gap** — still UNDETERMINED, unchanged from v19:
   no dated record in the payload is leg-keyed.
7. **Per-state `ann_ret` 30-observation gate** — still UNDETERMINED; the smallest
   live state is far above the threshold.

---

## 7 · Next step for the parent

1. **P1-1 first.** The `concentration` leg's `inherits_precision_at` must be
   `null` with `volatility`'s wording, or point at a real HHI disclosure. It is
   the only leg in the object that claims an inheritance that does not exist, and
   `standard_error_reason` repeats the wrong path in prose. One-line fix plus one
   string.
2. **P1-2 and P1-3 together** — one template bug producing both. The splice of
   `derivation_precondition` into `inherits_precision_reason` is on 14/14 legs;
   the "no figure at the far end" sentence should say "no **standard error or
   interval** at the far end", because the `point` is there.
3. **P1-4** — the `correlation_stability` message still argues the
   high-correlation branch next to a field that now says `lower_tail_collapse`.
   v19 flagged this; only the direction field landed.
4. Then P2-1 (one word: 3800 or 3801), P2-5 (rename `cvar` → `cvar_tail`, or
   vice versa), P2-6 (publish a `notional_floor_rule`).

**Corrections to carry forward, on the record:**

- **v19's P0 NEW-1 is FIXED.** Do not re-open the tear-sheet beta. It is
  `1.0931` with `point_status: verified_against_independent_witness` and a
  computed interval. The sign inversion is gone.
- **v19's P0 NEW-7 is FIXED.** `metrics_observation_count: 309` is published
  beside `observation_count: 2488` with the formula that uses it.
- **NEW-4 is only half-fixed** — do not close it on the strength of
  `alert_direction`.
- **The brief's reading of `headline_weight_basis` is a mis-attribution.** The
  "first three sum to 1" sentence is about the **weights** (0.65 + 0.25 + 0.10 =
  1.0) and is **true**. `1.001419` is the **shares**. Do not file this as a false
  prose claim; file it as an undisclosed denominator.
- **`_EGARCH_SIMULATED_NO_BAND` is not in `v26.json`.** Do not send an agent
  looking for it in this artifact.
- **The pointer class is clean.** 209 pointer strings, 0 dangling. The dotted
  `inherits_precision_at` failures on 14 legs are disclosed and intentional.
  Do not re-report them.
- **`component_reference_policy` verifies.** 72/72 copy identities hold. It is
  the best-checked claim in the document; cite it as the pattern to copy.
