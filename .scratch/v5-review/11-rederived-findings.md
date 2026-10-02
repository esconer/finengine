# 11 — Re-derived findings against `v19.json`

**Artifact** `C:\Users\Sayanti\AppData\Local\Temp\opencode\v19.json` · 834 973 B ·
`export_id` `portfolio-59ade3fd0d46` · `schema_version` `2.0` ·
`generated_at` `2026-09-27T15:59:55.022185Z` · 17 sections · 14 positions ·
`total_value` **43 608.669902801514 INR** · `base_currency` `INR`.

**Why this file exists.** The review documents quote an artifact four fixes old.
Eight findings were already withdrawn for that reason. This pass re-derives every
*still-open* finding from `v19.json` only, and gives the JSON path and observed
value for every claim. A claim without both is not a claim.

**Method.** Navigated only with Python scripts (a `get()` resolver that tolerates
dotted ticker keys, a recursive path walker, a content-hash deduplicator, and raw
substring counters). Scripts live outside the repo in
`C:\Users\Sayanti\AppData\Local\Temp\opencode\rd*.py`. No file outside this one was
created, edited or deleted in the workspace; no source, test or existing doc was
touched.

**Correction to the brief.** The brief says QM-2's `overlap_days: 36` "is now 20".
Confirmed — but only for the *holding-window* block. A second, live
`alpha_annualized` exists in the *full-history* block at **0.2176**, and it is
refuted by its own uncertainty block. See **NEW-1**, the most important finding here.

---

# Section 1 — Re-derivation of the open findings

## 1.1 RL-7 · `concentration` diversification metrics — **SURVIVES**

### Live values

| path | value |
|---|---|
| `sections.concentration.data.diversification_score` | `98.4` |
| `sections.concentration.data.diversification_ratio` | `0.83` |
| `sections.concentration.data.effective_positions` | `11.61` |
| `sections.concentration.data.herfindahl_index` | `0.0862` |
| `sections.concentration.data.gini_coefficient` | `0.252` |
| `sections.concentration.data.methodology` | `'Concentration analysis using Herfindahl-Hirschman Index (HHI), Effective Positions (N_eff), and Lorenz Gini Coefficient'` |

Second copy at `sections.dashboard.data.components.concentration.data.diversification_score`
= `98.4` and `…diversification_ratio` = `0.83` (identical).

### What reconciles, exactly

Recomputed from the 14 published `by_weight` values
(`sections.concentration.data.by_weight`, which sum to exactly `1.0`):

```
sum(w^2)                = 0.08615799255446031
herfindahl_index        = 0.0862      == round(sum(w^2), 4)          OK
1/sum(w^2)              = 11.606584257031079
effective_positions     = 11.61       == round(1/sum(w^2), 2)        OK
1/0.0862 (published)    = 11.60092807424594                          (rounding-path, benign)
```

So HHI and N_eff are exact and mutually consistent. **RL-7 is not about those two.**

### The scale question — a scale is NOT stated, and two sibling scores DO have one

Term counts over the full 834 973 B:

```
"look-through"        0        "underlying"        0
"look through"        0        "index constituents" 0
"holdings of"         0        "Nifty 50"/"NIFTY50"/"Nifty50"  0
"lookthrough"         0        "tracking error"     0
"0-100"               0        "0 to 100"           0
```

Declared scales that *do* exist elsewhere in the same artifact:

- `sections.liquidity.data.scoring.scale` = `{"min": 2.5, "max": 10.0, "unit": "index_0_to_10"}`
- `sections.dashboard.data.components.risk_score.data.score_audit.scale` = `'risk_points_0_to_30_higher_is_riskier'`
- `findpath("scale")` returns 12 paths; **none is under `sections.concentration`.**

`grep 'scale' sections.concentration.data` → `[]`. So a 0–10 liquidity score and a
0–30 risk score both declare their range, and the 0–100-looking `98.4` declares
nothing.

### The formula question — no formula, and the two fields are mutually inconsistent

Neither `diversification_score` nor `diversification_ratio` has a
`*_basis` / `*_unit` / `*_formula` / `*_scale` sibling
(`[k for k in concentration.data if 'diversif' in k]` → the two names only).
`"diversification_score"` occurs **2×** in the artifact (the section and its
dashboard mirror) and `"Calmar"` **0×** — i.e. the Calmar field has no prose
either, but the score is at least named twice.

`100 × diversification_ratio = 83.0`, not `98.4`. A reader who assumes
`score = 100 × ratio` is wrong by 15.4 points. No field contradicts the
assumption, because no field states either.

Reconstructions tried and **rejected** against `98.4` / `0.83`:

| candidate | value | matches score? | matches ratio? |
|---|---|---|---|
| `(1 − HHI)×100` | 91.384 | no | — |
| `N_eff/n × 100` | 82.904 | no | **≈ 0.8290 → 0.83** |
| `(N_eff−1)/(n−1)×100` | 81.589 | no | — |
| `100 − 100·√HHI` | 70.647 | no | — |
| `(1 − gini)×100` | 74.8 | no | — |
| `1 − gini` | 0.748 | — | no |

`diversification_ratio` is *consistent with* `N_eff/n` (0.8290 → 0.83).
`diversification_score` reconciles with **none** of the nine candidates. Its basis
is **UNDETERMINED from this artifact** — recovering it needs the
`concentration` implementation, not the payload. I did not read the source.

### The look-through question — the ETF sleeve is now identifiable and still undisclosed

Per-position sector comes from `sections.portfolio.data.positions[*].sector`
(a field that exists, so no ticker string was interpreted as a company name).
Exactly **five** positions carry `sector == "Exchange Traded Fund"`:

```
NIFTYIETF.NS     0.024093375378170835
MIDCAPIETF.NS    0.10156007758091541
JUNIORBEES.NS    0.12467314479455312
MAFANG.NS        0.027336307057788604
SELECTIPO.NS     0.04329414391050457
sum             = 0.32095704872193254
```

`sections.concentration.data.by_sector["Exchange Traded Fund"]` = `0.321`
= `round(0.32095705, 4)`. All seven sector buckets reconcile to
`by_weight` at 4 dp (max |Δ| 4.3e-05, exactly the rounding residual, and
`by_sector_rounding_residual` = `0.0` is published alongside
`by_sector_rounding_decimals` = `4`).

**What the score would need to account for, and does not.** Splitting the same
14 published weights into the 5-ETF sleeve and the 9 direct sleeves:

```
ETF sleeve weight            = 0.32095704872193254   (32.10% of the book)
ETF sleeve own sum(w^2)      = 0.029059989708819796
non-ETF sum(w^2)             = 0.057098002845640525
non-ETF HHI                  = 0.057098002845640525
non-ETF N_eff                = 17.513747419562343
```

So the published `herfindahl_index` `0.0862` and `effective_positions` `11.61`
count **five index-tracking sleeves as five independent positions**, and one
third of the book is a single undifferentiated sector bucket. The artifact
publishes **zero** fields named look-through, underlying, index constituents or
holdings of (counts above), and no field states the sleeve weight, the sleeve
count, or any constituent decomposition. The reader can *derive* the sleeve
weight from `by_sector`; the reader cannot learn what is inside it.

### Verdict

**SURVIVES**, marginally narrower than the review stated. The five ETF
instruments are now identifiable from the artifact and their 32.10% weight is
derivable — the review could not do either. Unchanged: no scale, no formula, no
look-through disclosure, and `diversification_score` `98.4` reconciles with no
reconstruction I could build, including the one its own sibling
`diversification_ratio` implies.

---

## 1.2 RL-1 · `liquidity.liquidation_days` — **NARROWER** (two sub-claims, opposite verdicts)

### (a) `observation_window.start/end` still null — **WITHDRAWN**

```
sections.liquidity.data.observation_window.start            = '2026-08-28'   (was null)
sections.liquidity.data.observation_window.end              = '2026-09-25'   (was null)
sections.liquidity.data.observation_window.ticker_count     = 14
sections.liquidity.data.scoring.observation_window.start   = '2026-08-28'
sections.liquidity.data.scoring.observation_window.end     = '2026-09-25'
sections.liquidity.data.latest_observation_date            = '2026-09-25'
sections.liquidity.as_of                                   = '2026-09-25'
sections.liquidity.as_of_semantics                         = 'latest_observation_date'
```

The window is now published three times (section, `data`, `scoring`) and the two
copies are byte-identical objects. `data_range.end` = `'2026-09-27'` (a Sunday,
the requested end) is a *different* field from `observation_window.end`
`'2026-09-25'` (the last trading session); the pair is internally coherent and
should not be read as a contradiction.

### (b) `liquidation_days` is a pure function of the turnover tier — **CONFIRMED, and the mapping is now published**

All 14 positions, from `sections.liquidity.data.by_position.<ticker>`:

| ticker | `liquidation_days` | `spread_tier` | `avg_turnover` (INR/session) | `category` | `market_cap_provenance` |
|---|---|---|---|---|---|
| CIPLA.NS | 1-2 | tier_1 | 1 244 170 024.9165387 | High | measured |
| ELECTCAST.NS | 1-2 | tier_2 | 148 642 559.7196481 | High | measured |
| MOTILALOFS.NS | 1-2 | tier_1 | 758 306 580.5213195 | High | measured |
| ARROWGREEN.NS | 2-5 | tier_3 | 51 186 282.975 | Medium | measured |
| JKIL.NS | 2-5 | tier_3 | 20 173 096.378164675 | Medium | measured |
| NTPC.NS | 1-2 | tier_1 | 2 521 433 992.61591 | High | measured |
| MCX.NS | 1-2 | tier_1 | 6 343 004 799.227004 | High | measured |
| MOTHERSON.NS | 1-2 | tier_1 | 1 861 606 503.0629776 | High | measured |
| REDINGTON.NS | 1-2 | tier_1 | 2 675 066 480.678571 | High | measured |
| NIFTYIETF.NS | 1-2 | tier_2 | 151 185 435.8449402 | High | **estimated** |
| MIDCAPIETF.NS | 2-5 | tier_3 | 25 221 144.36415596 | Medium | **estimated** |
| JUNIORBEES.NS | 1-2 | tier_2 | 233 170 031.66245812 | High | **estimated** |
| MAFANG.NS | 1-2 | tier_2 | 175 008 555.2359423 | High | **estimated** |
| SELECTIPO.NS | **5-10** | tier_4 | 2 902 206.675482614 | Low | **fallback** |

```
distinct liquidation_days over 14 positions: {'1-2': 10, '2-5': 3, '5-10': 1}
tier_1 -> {'1-2'}   tier_2 -> {'1-2'}   tier_3 -> {'2-5'}   tier_4 -> {'5-10'}
pure function of spread_tier: True
```

**Strictly, it is a pure function of the tier, not of the band:** tiers 1 and 2
collapse to the same window. The band table
(`sections.liquidity.data.scoring.thresholds`, byte-identical to
`…scoring.bands`) maps High→1-2, Medium→2-5, Low→5-10, and the observed
band/window pairs are consistent with it.

I re-derived the whole ladder from
`sections.liquidity.data.scoring.spread.tier_ladder` and it holds to the last
published digit on all 14 legs: `round(spread, 4)` matches `spread` 14/14, and
`round(score_raw, 6)` matches `score_raw` 14/14. `recomputed_from_avg_turnover`
publishes `confirmed_count` = 14, `unconfirmed_count` = 0.

### (c) The residual: the portfolio-level roll-up has no stated rule

```
sections.liquidity.data.liquidation_time_days = '1-2'
```

while 3 legs are `'2-5'` and 1 is `'5-10'`. The mode is `'1-2'` (10/14), so the
value is plausibly modal — but **no field states the aggregation rule**.
`findpath("liquidation_time_days")` returns only two paths (the section and its
dashboard mirror); the entire 46-occurrence `"liquidation"` sweep in the
artifact contains exactly one prose sentence about liquidation
(`sections.liquidity.data.warnings`, which is about the five unmeasured market
caps, not about the roll-up). SELECTIPO is 4.33% of the book and its own
`liquidation_days` is `'5-10'` — 5× the portfolio headline.

### (d) NEW, adjacent: the band mean is an unweighted mean over unequal samples

```
mean of the 14 by_position.avg_volume          = 2427219.741747225
sections.liquidity.data.volume_stats.avg_volume = 2427219.741747225   exact match
volume_stats.avg_volume × 14                    = 33981076.38446115
volume_stats.total_portfolio_volume             = 33981076.38446115   exact match
```

`volume_stats.avg_volume` is the **unweighted** mean of 14 per-leg means, and no
field says so (`volume_band_basis` documents only the band percentages). Worse,
the 14 legs are averaged over **unequal** sample sizes, which the artifact now
publishes in `sections.liquidity.data.observation_window.per_ticker`:
`{21: 9 tickers, 20: 4 tickers, 19: 1 ticker}` and **NIFTYIETF.NS is the 19**.
I confirmed the denominators are real by recovering each leg's implied volume
sum as an exact integer: NIFTYIETF `575571.7368421053 × 19 = 10 935 863`
(integer), CIPLA `888883.380952381 × 21 = 18 666 551`, NTPC
`7720250.904761905 × 21 = 162 125 269`. So `avg_volume` is a mean over each
leg's own count, and `tier_ladder.applies_when` thresholds are stated against
"avg_turnover" with no statement that the averaging window differs per leg.

### Verdict

**NARROWER.** (a) withdrawn — the window is published three times. (b) confirmed
and the ladder is now fully published and reproducible. What survives is
(c): the portfolio-level `liquidation_time_days` roll-up rule is unstated, and
(d) a new observation about the unweighted band mean over unequal samples.

---

## 1.3 Conventions

### (a) Calmar — **NARROWER**

`findpath("calmar")` returns **4** paths and there is exactly **one** Calmar
number in the artifact:

| path | value |
|---|---|
| `sections.tear_sheet.data.metrics.calmar` | `null` (`metrics.annualized` = `false`) |
| `sections.tear_sheet.data.estimate_uncertainty.metrics.estimates.calmar.point` | `null` |
| `sections.tear_sheet.data.full_history.metrics.calmar` | **`2.336774`** |
| `sections.tear_sheet.data.full_history.estimate_uncertainty.metrics.estimates.calmar.point` | `2.336774` |

Units actually used, derived not assumed:

```
cagr / |max_drawdown| = 0.300514 / 0.128602 = 2.336775477830827
published calmar                                   = 2.336774
```

The 1.5e-06 gap is double rounding, not a contradiction: over the box
`cagr ∈ [0.3005135, 0.3005145]`, `|mdd| ∈ [0.1286015, 0.1286025]` the ratio spans
`[2.3367625, 2.3367885]`, and `2.336774` sits inside it. **Convention confirmed as
`CAGR ÷ |full-window max drawdown|`** — an *annualised* numerator over a
*multi-year, unannualised* denominator. The `max_drawdown` spans 2016-09-12 →
2026-09-25 per `sections.tear_sheet.data.full_history.window`; it is not scaled
to a year.

**No prose states this.** `"Calmar"` (capitalised) occurs **0×** in 834 973 B.

**Cross-block consistency is UNDETERMINED, not "inconsistent".** The
holding-window block's Calmar is `null`, so the two blocks never exhibit both
conventions side by side and the comparison cannot be run. For scale: had the
holding-window Calmar been published under the same field name with
`annualized: false`, it would have carried `total_return/|mdd|` =
`0.044961/0.007312` = **6.148933**, i.e. **2.63×** the full-history figure. That
is a hypothetical, stated as one — the field is `null` and no such number
exists in the payload.

### (b) Risk-free rate — **WITHDRAWN as unpublished; NARROWER as co-located**

`findpath("risk_free")` → 70 paths, 37 distinct parents. Every value is `0.02`.
It is published at:

- `sections.optimization.data.risk_free_rate` = `0.02` (top level, beside the moments)
- `sections.optimization.data.moments_basis.risk_free_rate` = `0.02`
- `sections.optimization.data.estimate_uncertainty.notes.risk_free_rate` = `0.02`
- `sections.optimization.data.current_portfolio.estimate_uncertainty.notes.risk_free_rate` = `0.02`
- `sections.realized_risk.data.portfolio.estimate_uncertainty.notes.risk_free_rate` = `0.02` + all 14 `…positions.<t>.estimate_uncertainty.notes.risk_free_rate`
- `sections.tear_sheet.data.estimate_uncertainty.metrics.notes.risk_free_rate`, `…full_history.estimate_uncertainty.metrics.notes.risk_free_rate`, `…estimate_uncertainty.relative_vs_nifty.benchmark.notes.risk_free_rate`

**Not co-located with any consuming metric.** Key lists:

```
sections.tear_sheet.data.metrics keys        : [total_return, cagr, sharpe, sortino, calmar,
                                                omega, tail_ratio, volatility, max_drawdown,
                                                skew, kurtosis, annualized]   -> no risk_free_rate
sections.tear_sheet.data.full_history.metrics: [total_return, cagr, sharpe, sortino, calmar,
                                                volatility, max_drawdown, days, annualized] -> none
sections.realized_risk.data.portfolio        : [annual_return, annual_volatility, sharpe_ratio,
                                                sortino_ratio, skewness, kurtosis, max_drawdown,
                                                var_95, cvar_95, hit_ratio,
                                                estimate_uncertainty, annualized] -> none
```

The rate is buried one level under `estimate_uncertainty.notes`, in a *different
object* from the Sharpe it produced. A reader who reads only
`sections.tear_sheet.data.full_history.metrics` cannot see it.

**NEW: the artifact publishes two mutually inconsistent deannualisation
conventions for the same `0.02`.** The two `risk_free_rate_basis` strings are
verbatim-different:

- `sections.realized_risk.data.portfolio.estimate_uncertainty.notes.risk_free_rate_basis`
  = `'the engine's configured annual risk-free rate, used as risk_free_rate / 252 for the Sortino downside target and as the numerator deduction for both ratios'`
  → **simple** `rf/252`
- `sections.tear_sheet.data.full_history.estimate_uncertainty.metrics.notes.risk_free_rate_basis`
  = `'the annualized rf this route passes to quantstats; quantstats deannualises it COMPOUNDED as (1 + rf) ** (1/252) - 1 and the resampling statistics use the same deannualisation'`
  → **compounded** `(1+rf)^(1/252)−1`

```
0.02/252               = 7.936507936507937e-05
(1.02)**(1/252) - 1    = 7.858494198464960e-05
absolute difference    = 7.801373804297617e-07 per session
relative difference    = 0.0099273138177305   (0.99%)
annualised equivalent  = 1.9659e-04
```

The `optimization` family publishes a third, third-order basis: its
`estimate_uncertainty.notes` has keys
`[annualization_factor, estimator, forward_looking, resampling_basis, risk_free_rate]`
— **no `risk_free_rate_basis` at all**, though
`sections.optimization.data.moments_basis.formulas.expected_sharpe` =
`'(expected_annual_return - risk_free_rate) / expected_annual_volatility'` with
`annualization_factor` = `252`.

### (c) Stress `max_drawdown` and the `1.15` convention — **WITHDRAWN**

All four scenarios publish the formula and apply it uniformly:

| path | `portfolio_impact` | `max_drawdown` | `round(pi×1.15, 4)` |
|---|---|---|---|
| `…scenarios.Market Crash` | -0.4742 | -0.5453 | **-0.5453** ✓ |
| `…scenarios.Interest Rate Shock` | -0.1942 | -0.2233 | **-0.2233** ✓ |
| `…scenarios.Volatility Spike` | -0.2877 | -0.3309 | **-0.3309** ✓ |
| `…scenarios.Tech Sector Correction` | -0.1349 | -0.1551 | **-0.1551** ✓ |

Every scenario carries, verbatim:

- `max_drawdown_basis` = `'derived_from_shock_proxy'`
- `max_drawdown_formula` = `'portfolio_impact * 1.15'`
- `methodology` = `"…portfolio_impact = sum of position_impact * weight; max_drawdown = portfolio_impact * 1.15, a fixed uplift on that same proxy, not a simulated peak-to-trough path; re…"`

`"1.15"` occurs 13×, of which 4 are the formula, 4 are the methodology, 4 are
`sections.stress_testing.data.scenarios.*.shock_inputs.instrument_overrides.SELECTIPO.NS.sector_elasticity`
(an unrelated number that happens to be 1.15), and 1 is an unrelated percentile
`{"year":4.5,…}`. `findpath("baseline")` → 0, so there is no un-1.15-ed baseline
drawdown to contradict the four. The convention is disclosed, uniform, and
arithmetically exact to 4 dp on 4/4. **Withdrawn as a defect.**

Residual worth one line, not a finding: the same field name `max_drawdown` is
used here for a *proxy with a 1.15 uplift* and at
`sections.tear_sheet.data.full_history.metrics.max_drawdown` /
`sections.realized_risk.data.portfolio.max_drawdown` for a *measured
peak-to-trough*. Units agree (`fraction_of_portfolio_value` vs
`annualized: true` block), and `max_drawdown_basis` discloses the difference, so
this is a naming hazard rather than a defect.

---

## 1.4 Residuals

| # | residual | verdict | evidence |
|---|---|---|---|
| R1 | `correlation` sub-score floor | **NARROWER** | see below |
| R2 | `components` values plain float or numpy | **UNDETERMINED** | see below |
| R3 | per-state `ann_ret` withholding asymmetry | **UNDETERMINED** | see below |
| R4 | `cross_section_reconciliation` | **SURVIVES, disclosed** | see below |
| R5 | `accounting_basis` scope | **SURVIVES, scoped** | see below |
| R6 | `exceedances_count` vs a 2-parameter GPD | **NARROWER, disclosed** | see below |
| R7 | NIFTYIETF per-leg price gaps | **NARROWER** | see below |

### R1 · the `correlation` sub-score floor — NARROWER

```
sections.dashboard.data.components.risk_score.data.score_audit.components.correlation
  .input_statistic_value  = 0.099375
  .formula                = "min(30, 50 * max(0, avg_pairwise_correlation))"
  .sub_score              = 5.0            (round(50*0.099375, 1) = round(4.96875, 1) = 5.0)
  .cap_binds_when_input_is= ">= 0.60"
  .unpin_condition        = "avg pairwise correlation < 0.60"
sections.dashboard.data.components.risk_score.data.avg_pairwise_correlation = 0.0994
```

The floor is **not reached** in this export (`0.099375 > 0`), and the formula
string now publishes the `max(0, …)` clamp verbatim, so the reachability the
queue described is visible to a reader. What is *not* visible: the score is
published at 1 dp while its input is at 6 dp, and
`published_input_as` = `"avg_pairwise_correlation"` points at the **4 dp** copy
(`0.0994`) rather than at the 6 dp `input_statistic_value` (`0.099375`) actually
used. The sibling components point at themselves
(`"score_audit.components.concentration.input_statistic_value"`), so the pointer
discipline is inconsistent inside one object. Harmless at the current value
(`round(50×0.0994, 1)` is also `5.0`), but it is a recomputability gap.

### R2 · are `components` values plain floats or numpy-derived? — **UNDETERMINED**

```
raw occurrences: 'np.float' 0   'float64' 0   'dtype' 0   'numpy' 0
                 'NaN' 0      'Infinity' 0  '-Infinity' 0
                 'True' 0     'False' 4
leaf types after json.load: {str: 10422, int: 2874, float: 5901, NoneType: 1843, bool: 1522}
```

`json.load` has already coerced every leaf to a Python primitive, so **this
artifact cannot exhibit a numpy type** either way. Settling it requires reading
the serialiser in the producing code, which is out of scope for a read-only
artifact pass and is a live code change (other agents own those files). To
determine: grep the export/serialisation path for a `default=` handler in
`json.dumps` / the pydantic model config, and check whether
`sections.dashboard.data.components.risk_score.data.score_audit.components.*.sub_score`
is produced by `float(...)` or left as a numpy scalar.

### R3 · per-state `ann_ret` below ~30 state-days — **UNDETERMINED**

```
sections.regime.data.states[0] = {regime: crisis, ann_ret: -0.3085, ann_vol: 0.1179,
                                  historical_days_pct: 23.6, observations: 170, annualization_factor: 1.4824}
sections.regime.data.states[1] = {regime: bull,   ann_ret:  0.8627, ann_vol: 0.1965,
                                  historical_days_pct: 15.8, observations: 114, annualization_factor: 2.2105}
sections.regime.data.states[2] = {regime: calm,   ann_ret:  0.0957, ann_vol: 0.1078,
                                  historical_days_pct: 60.6, observations: 436, annualization_factor: 0.578}
```

```
252/170 = 1.482353 -> published 1.4824   OK
252/114 = 2.210526 -> published 2.2105   OK
252/436 = 0.577982 -> published 0.578    OK
```

`sections.regime.data.portfolio_in_current_regime` = `{"days": 18, "ann_ret": null,
"ann_vol": null, "total_ret": 0.0442, "annualized": false, …}` and its
`history_coverage.minimum_observations_required` = **30** — so that block
withholds at 18 < 30 and publishes the threshold.

**The asymmetry cannot manifest here: the smallest state has 114 observations,
3.8× the 30 threshold.** So `v19.json` neither confirms nor refutes the claim
that per-state `ann_ret` lacks the gate; it is a code-level claim and the code
was out of scope. `sections.regime.data.units` declares
`states[].ann_ret` = `"annualized_fraction_geometric_cagr"` and
`states[].observations` = `"count_trading_days"`, so `bull`'s **+86.27%**
annualised figure is derived from 114 trading days and the payload does disclose
its divisor (`annualization_factor` 2.2105) — but publishes no interval and no
warning for it. To determine: read the regime per-state annualisation path in
`analytics_engine.py` (not mine to touch).

### R4 · `cross_section_reconciliation` — present, and honest about not reconciling

```
sections.portfolio.data.snapshot_consistency.cross_section_reconciliation
  .measured_here      = false
  .reason             = "This route values the held universe and returns; it cannot observe the
                         price instant any other section used, so it publishes its own clocks and
                         refuses to assert an alignment it did not measure."
  .rule_for_a_reader  = "Treat two numbers for the same ticker as one fact only when their
                         published price dates match; otherwise the gap is a snapshot gap, not an
                         arithmetic disagreement."
```

Two paths only (section + dashboard mirror). The sibling
`sections.portfolio.data.snapshot_consistency.what_this_invalidates` is a
two-element array whose first element states the 781.659145 s / 13-instant mark
spread and its consequence for every cross-section figure.
`findpath("baseline")` = 0, `what_this_invalidates_at` /
`per_position_price_as_of_at` / `detail_at` in
`snapshot_consistency_measured` **all resolve**. The finding survives as a
*disclosure that is itself the fix*; nothing left to re-derive.

### R5 · `accounting_basis` scope — present, and explicitly bounded

```
sections.portfolio.data.accounting_basis.scope.covers
  = "sections.portfolio only: positions[*] (market_value, total_cost, unrealized_gain_loss and
     their base-currency twins), total_value and sectors."
sections.portfolio.data.accounting_basis.scope.does_not_cover
  = "Every other section's return series, the monte_carlo projection, the tear sheet, tear-down
     risk rows and the optimiser target are computed elsewhere from their own delivered bars and
     declare no basis of their own. This block must not be read as stating theirs: read a number
     from one of those sections and its gross-or-net status is UNKNOWN, not gross."
```

`basis` = `'gross_of_all_transaction_costs_and_tax_unadjusted_prices'`,
`gross_or_net` = `'gross'`, `net_of_costs` = `false`, plus a 7-item
`not_accounted_for` array (dividends, corporate actions, fees, tax, slippage,
turnover, survivorship) each with an `effect` string, and
`reader_consequence` = `'These are GROSS figures… an upper bound on net outcome,
not an estimate of it.'` Two paths only.

**The stated scope is accurate against the payload.** I checked the boundary it
draws: `sections.factor_exposure`, `sections.tear_sheet`,
`sections.monte_carlo` and `sections.optimization` indeed publish no
`gross_or_net` / `net_of_costs` of their own. **Survives as a scoped disclosure;
the scope claim is verified, not merely repeated.**

### R6 · `exceedances_count` against a two-parameter GPD — NARROWER, disclosed

```
sections.risk_studio.data.components.tail_dependence.data
  .exceedances_count = 16      .total_observations = 307
  .threshold_u       = 0.017569
  .gpd_shape_xi_raw  = -0.54850111   .gpd_shape_xi_used = -0.5
  .gpd_shape_xi_basis= 'constrained_clip'   .constraint_reason = 'gpd_shape_clipped'
  .gpd_scale_beta    = 0.014357  (= .gpd_scale_beta_raw = .gpd_scale_beta_constrained)
  .gpd_shape_constrained = true  .metrics_constrained = true
  16/307 = 0.05211726384364821  == published pot_threshold_basis.exceedance_fraction 0.052117
```

`pot_threshold_basis` publishes `threshold_quantile` = 0.95, `reported_level` =
0.99, `level_fields` = `{"fitted": "threshold_u", "reported": "confidence_level"}`
and `suffixed_field_rule` explaining that `_99` names the reported level, not the
POT level. So "the fit uses a 5% exceedance budget and the report is at 99%" is
now explicit, and `gpd_shape_xi_used_rule` states the moments come from the
**clipped** shape.

Residual: a two-parameter GPD (shape + scale) is fitted to **16** points, and
`exceedances_count` 16 is 5.2% of 307 — the classic rule-of-thumb floor, with no
stated minimum and no interval on either parameter. Neither
`sections.risk_studio` nor the block carries a warning about the exceedance
budget. The lookback shortfall is *also* undisclosed here:
`sections.risk_studio.inputs.component_lookbacks.tail_dependence` = **756**
against a 307-row sample (2.46×), with no requested-vs-measured pair in the
block. To determine whether 16 is enough for this fit, one would need the fit's
standard errors, which the artifact does not publish.

### R7 · NIFTYIETF's per-leg price gaps — **NARROWER, and much closer to settled**

The queue recorded "the artifact publishes no per-leg missing dates". It now
publishes per-leg missing **counts** in four windows plus a named refusal
attribution. The consolidated table, all from published fields:

| ticker | `risk_score.history_coverage.tickers.<t>.return_observations` | `liquidity…observation_window.per_ticker.<t>.observations` | `realized_risk…positions.<t>.estimate_uncertainty.observations` | `tear_sheet…full_history.per_ticker_return_observations.<t>` |
|---|---|---|---|---|
| CIPLA.NS | 39 | 21 | 39 | 2484 |
| ELECTCAST.NS | 39 | 21 | 39 | 2484 |
| MOTILALOFS.NS | 37 | 20 | 37 | 2482 |
| ARROWGREEN.NS | 37 | 20 | 37 | 2482 |
| JKIL.NS | 37 | 20 | 37 | 2482 |
| NTPC.NS | 39 | 21 | 39 | 2484 |
| MCX.NS | 39 | 21 | 39 | 2484 |
| MOTHERSON.NS | 39 | 21 | 39 | 2484 |
| REDINGTON.NS | 39 | 21 | 39 | 2482 |
| **NIFTYIETF.NS** | **20** | **19** | **20** | **612** |
| MIDCAPIETF.NS | 37 | 20 | 37 | 1636 |
| JUNIORBEES.NS | 39 | 21 | 39 | 2482 |
| MAFANG.NS | 39 | 21 | 39 | 1326 |
| SELECTIPO.NS | 39 | 21 | 39 | 383 |

NIFTYIETF is the **sole** short leg on the holding window (20 vs 37/39, a 49%
shortfall) and is 4.1× short on full history (612 vs 2482–2484).

The refusal attribution is explicit:

```
sections.dashboard.data.components.performance_history.partial_basket_policy
  = 'refused_not_renormalised'
sections.dashboard.data.components.performance_history.refused_partial_coverage_rows = 17
…performance_history.warnings[0]
  = "…NIFTYIETF.NS (17 session(s) without a price), ARROWGREEN.NS (1 session(s)
     without a price), JKIL.NS (1), MIDCAPIETF.NS (1), MOTILALOFS.NS (1)."
```

This also **settles QM-1 as fixed**: the partial-basket renormalisation is gone
and replaced by refusal, with the count and the offending legs named. (The
review's P0 QM-1 is not in my assigned list, but the parent should know.)

**What is still UNDETERMINED is the cause**, and the artifact provably cannot
settle it: I enumerated every dated record in the payload — 342 of them, in five
containers — and **none carries a per-ticker value**:

```
sections.regime.data.recent_history[-1]                        keys: [date, regime]
sections.risk_studio…correlation_stability.data.series[-1]     keys: [avg_correlation, date,
                                                                      threshold_75th, threshold_90th]
sections.dashboard…performance_history.data[-1]                 keys: [date, portfolio_value,
                                                                      benchmark_value, return, …]
sections.tear_sheet.data.underwater[-1]                         keys: [date, drawdown]
```

No per-leg date list exists, and no dated record is leg-keyed. Vendor gap vs
cache artifact is therefore **UNDETERMINED**; what would settle it is either the
per-leg missing-date list or the delivered-bar index for
`StockTimeseries` per ticker over 2026-08-03 → 2026-09-25.

---

# Section 2 — Regression watch

Every item confirmed **still fixed**, with its JSON path.

| # | item | path | live value | verdict |
|---|---|---|---|---|
| 1 | `alpha_annualized` null | `sections.tear_sheet.data.relative_vs_nifty.alpha_annualized` | `null` | FIXED |
| 1b | …and its band null too | `…relative_vs_nifty.measurement_windows.windows.portfolio_benchmark_overlap` | `minimum_observations_required: 30`, `below_minimum_observations_required: true`, `observations: 20`, `gate_effect: "withheld: fewer overlapping observations than the annualization policy requires…"` | FIXED |
| 2 | `measurement_windows` present, 3 windows | `sections.tear_sheet.data.relative_vs_nifty.measurement_windows` | `distinct_windows: 3`, `windows_fields_rest_on: 2`, `status: "computed"`, `reason: null` | FIXED |
| 2b | `requested_window_benchmark` @ 245, not shared | `…measurement_windows.windows.requested_window_benchmark` | `observations: 245`, `observation_count: 245`, `window {start: 2025-09-29, end: 2026-09-25, days: 245}`, `shares_metrics_sample: false`, `truncated_by_cached_benchmark_depth: false` | FIXED |
| 2c | the 4 benchmark fields are marked off-window | `…measurement_windows.fields` | each `shares_metrics_window: false`, `observations_short_of_metrics_window: 225` | FIXED |
| 3 | `is_fat_tailed` null + withheld reason | `sections.risk_studio.data.components.tail_dependence.data.is_fat_tailed` | `null`; `is_fat_tailed_withheld_reason` non-empty; `fired_signals: ["excess_kurtosis_above_threshold", "evt_var_exceeds_historical_var"]`; `gpd_shape_xi_raw: -0.54850111`; `excess_kurtosis: 1.925106` (> 0.5); `evt_var_exceeds_historical_var: true` | FIXED |
| 4 | vol-cone: all 5 windows withhold, `effective_n` published | `sections.risk_studio.data.components.volatility_cone.data.windows[*].percentile_rank` | `null` ×5; `effective_n` = 29.8 / 13.67 / 3.89 / 1.44 / 0.22; `minimum_effective_n_for_percentile_rank: 30.0`; `n_windows` = 298/287/245/182/56, all = `307 − L + 1` ✓ | FIXED |
| 4b | `current_forecast` withholds too | `…volatility_cone.data.current_forecast.percentile_rank` | `null`, `ranked_against_window_days: 21` | FIXED |
| 5 | correlation two-sided, `historical_threshold_10th` present | `sections.risk_studio.data.components.correlation_stability.data` | `current_avg_correlation: 0.1361`, `historical_threshold_10th: 0.2189`, `…_25th` **absent**, `…_75th: 0.4129`, `…_90th: 0.459`, `historical_median: 0.3408`, `is_regime_break: true`, `alert_level: "ELEVATED"`, `series_observations: 489`, `series_retained: 60`, `series_trimmed_in_summary: true` | FIXED (but see NEW-4) |
| 6 | `score_audit` with both fields | `sections.dashboard.data.components.risk_score.data.score_audit` | present; `duplicate_components` n=1 (`market_risk`↔`volatility`, `relation: "identical"`, `sample_dependent: true`, `clears_when: "…grows past 60 rows…"`); `saturated_components: ["factor_risk"]`; `independent_component_count: 4` | FIXED (but see NEW-2, NEW-3) |
| 7 | `snapshot_consistency_measured` at the envelope | `snapshot_consistency_measured` | `status: "multiple_instants"`, `distinct_price_instants: 13`, `distinct_delivered_bar_dates: 1`, `mark_instant_spread_seconds: 781.659145`, `delivered_bar_spread_calendar_days: null`; all three `*_at` pointers resolve | FIXED |
| 7b | `snapshot_consistency` flag | `snapshot_consistency` | `'best_effort'` | FIXED |
| 8 | `accounting_basis` present | `sections.portfolio.data.accounting_basis` | present, 11 top-level keys, `scope.covers` / `scope.does_not_cover` both non-empty | FIXED |
| 9 | 14 positions | `sections.portfolio.data.positions` | `len` = 14, `sum(weight)` = `1.0` exactly | FIXED |
| 9b | book total | `sections.portfolio.data.total_value` | `43608.669902801514`; `sum(market_value)` = `43608.669902801514` (exact); `sum(market_value_base)` identical | FIXED |
| 9c | `model_observation_count` | `sections.dashboard.data.components.risk_score.data.model_observation_count` | `38`, scope `'active_benchmark_overlap_return_rows'` — matches `factor_model.benchmark_overlap_return_rows: 38` and `factor_model.model_observation_count: 38` | FIXED (queue correction #4 holds) |
| 9d | `risk_contribution` still down | `sections.risk_contribution.status` / `.data` | `'unavailable'` / `null`; `warnings[0]` = `"This section failed and publishes no measurement of it: Internal server error. Nothing in this payload is a measurement of the requested quantity."` | **NOT FIXED** — carried, disclosed |
| 9e | envelope warnings empty | `warnings` | `[]` — while `risk_contribution.status` = `'unavailable'` | see NEW-6 |
| 9f | `overlap_days` | `sections.tear_sheet.data.relative_vs_nifty.overlap_days` | `20` (queue's `36` is stale) | value moved |

**Nothing in the watch list has regressed.** Two items need action rather than
reassurance: **9d** (`risk_contribution` still `unavailable`, now with a truthful
warning) and the full-history `alpha_annualized` **0.2176**, which the queue's
withdrawal did not cover — see NEW-1.

---

# Section 3 — New defects in this session's blocks

Ordered by severity. Every number re-derived by script; nothing asserted.

## NEW-1 · `tear_sheet.full_history` publishes a beta its own estimator refutes, with a sign inversion · **P0**

This is the most consequential thing in the artifact and nobody has reviewed it.

```
sections.tear_sheet.data.full_history.relative_vs_nifty.beta_vs_nifty    =  1.1037
sections.tear_sheet.data.full_history.relative_vs_nifty.alpha_annualized =  0.2176
sections.tear_sheet.data.full_history.relative_vs_nifty.overlap_days     =  307
```

And in the same section, one object deeper:

```
sections.tear_sheet.data.full_history.estimate_uncertainty.relative_vs_nifty
  .estimates.beta_vs_nifty.reason
    = "the resampling estimator's own point value (-0.227490896001) does not reproduce the
       published beta_vs_nifty (1.1037); difference 1.33 exceeds the 0.0001 identity
       tolerance. The band would describe a different statistic, so it is withheld."
  .estimates.alpha_annualized.reason
    = "the resampling estimator's own point value (0.305655329887) does not reproduce the
       published alpha_annualized (0.2176); difference 0.0881 exceeds the 0.0001 identity
       tolerance. The band would describe a different statistic, so it is withheld."
```

`1.1037` is **positive**; the estimator's own value is **−0.2275**. That is a sign
inversion *and* a magnitude error, on the same 307 rows the block names
(`observations: 307`, `effective_n: 273.2965`,
`window {start: 2025-03-11, end: 2026-09-23, days: 307}`).

The uncertainty gate behaved correctly — it refused to attach a band. The defect
is that the **point** is published anyway, unflagged at the field, and the
`measurement_windows` block beside it says the opposite:

```
…full_history.relative_vs_nifty.measurement_windows.status  = "computed"
…measurement_windows.reason                                   = null
…measurement_windows.windows.portfolio_benchmark_overlap.gate_effect
  = "reported: the overlap clears the annualization policy minimum"
…measurement_windows.comparison_note
  = "…`metrics` and this block's holding-window sample are like for like, and nothing else
     here is. In particular a `metrics` ratio and a `benchmark_*` value are measured over
     different periods and their difference is not a skill gap."
```

`"1.1037"` occurs 3× in the artifact and `"0.2176"` 4×; the refutation appears
**only** inside the two `reason` strings. A reader of `relative_vs_nifty` +
`measurement_windows` gets a confident, un-caveated **+1.10 beta / +21.8%
annualised alpha**; a reader of the uncertainty block finds the payload
disowning it.

**A second, independent pair disagrees with both:**

```
sections.factor_exposure.data.portfolio.market           = 1.143
sections.factor_exposure.data.portfolio.annualized_alpha = 0.5431
sections.factor_exposure.data.portfolio.alpha            = 0.002155   (x 252 = 0.54306 ✓)
sections.factor_exposure.data.portfolio.alpha_std_error  = 0.000584   (t = 3.69)
sections.factor_exposure.data.portfolio.market_std_error = 0.060528   (t = 18.9)
sections.factor_exposure.data.portfolio.std_error_basis  = "newey_west_hac_maxlags_5"
sections.factor_exposure.data.portfolio.observations     = 100
```

So the artifact carries **three** beta/alpha pairs on three different samples —
`1.143 / 0.5431` (100 rows, Newey-West SEs, cleanly identified),
`1.1037 / 0.2176` (307 rows, refuted by its own estimator),
`−0.2275 / 0.3057` (the same 307 rows, from the estimator) — and no field
cross-references any of them. The holding-window pair is correctly `null`
(`sections.tear_sheet.data.relative_vs_nifty.beta_vs_nifty` = `null`,
`.alpha_annualized` = `null`).

**Note for the parent's record:** the queue's withdrawal of QM-2 ("`74%
annualised alpha` does not exist; `alpha_annualized` publishes `null`") is
correct **for the holding-window block** and must not be generalised. A
`0.5431` annualised alpha *does* exist at
`sections.factor_exposure.data.portfolio.annualized_alpha`, and a `0.2176` at
`sections.tear_sheet.data.full_history.relative_vs_nifty.alpha_annualized`.

**What is needed:** the identity check that the uncertainty gate already runs
(`point_tolerance` = `1e-4`) must also gate the *point* on the
full-history beta/alpha path, or the point must be withheld with the same reason.
The defect is a code change in the producing module and is **not mine to make** —
recorded, not fixed.

## NEW-2 · `headline_share` normalises by the rounded score; the three shares sum to 1.001571 · **P1**

```
sections.dashboard.data.components.risk_score.data.score_audit
  .overall_score (sibling)                  = 12.8
  .components.*.headline_contribution  sum   = 12.820103
  .components.*.headline_share        sum    = 1.0015699999999998
  .effective_information.headline_basis_score = 12.8
  .effective_information.headline_attribution sum = 12.820103
  .effective_information.responsive_share_of_headline = 0.357545
  .effective_information.pinned_share_of_headline     = 0.585938
  .effective_information.duplicate_share_of_headline  = 0.058088
     -> sum 1.001571
  .effective_information.responsive_weight + pinned_weight + duplicate_weight = 1.0
```

Proven by inverting each share:

```
implied denominator = contribution / share
  concentration 1.724    / 0.134687 = 12.8000475
  volatility    1.858821 / 0.145220 = 12.8000344
  correlation   0.993753 / 0.077637 = 12.7999923
  factor_risk   7.5      / 0.585938 = 12.7999891
  market_risk   0.743529 / 0.058088 = 12.8000448
sum(contributions) / overall_score = 12.820103 / 12.8 = 1.0015705469
sum(published shares)                          = 1.0015699999
```

The shares divide by the **rounded** `overall_score` (12.8) while the
contributions sum to the **unrounded** total (12.820103). Nothing in the payload
states the shares' denominator.

**Careful — one thing that looks like a false claim and is not.**
`effective_information.headline_weight_basis` reads:

> `'effective (renormalized) weights; each leg sits in exactly one of
> headline_bucket responsive/pinned/duplicate/excluded, and the first three sum
> to 1 -- the whole headline'`

"the first three sum to 1" is about the **weights**, and
`responsive_weight + pinned_weight + duplicate_weight` = `1.0` exactly, with
`headline_weight_total` = `1.0`. That sentence is **true**. The word "share"
appears in neither note (`headline_weight_basis` contains `sum` but not `share`;
`headline_attribution_note` contains `sum` and `round` but not `share`).
So the finding is a **disclosure gap on the shares**, not a false statement.
`headline_attribution_note` does explain the contribution-vs-score gap
("…the contributions sum to the unrounded overall_score, which the payload
publishes rounded to 1 decimal…, so their sum can differ from it by up to
0.05") — and says nothing about the shares.

`overall_score_raw` is `null` at
`sections.dashboard.data.components.risk_score.data.overall_score_raw`, so the
unrounded 12.820103 is nowhere published as a field. The sibling
`sections.liquidity.data.overall_score_raw` = `7.971429` *is* published beside
its `overall_score` = `8.0` — so the artifact uses both conventions.

## NEW-3 · `headroom_to_cap` is not `cap − sub_score` on 4 of 5 legs, with no declared precision · **P1**

```
sections.dashboard.data.components.risk_score.data.score_audit.components
  component        sub_score   cap−sub    headroom_to_cap   Δ
  concentration      8.6        21.4         21.38          +0.0200
  volatility         7.4        22.6         22.564715      +0.035285
  correlation        5.0        25.0         25.031236      −0.031236
  factor_risk       30.0         0.0          0.0            0.0
  market_risk        7.4        22.6         22.564715      +0.035285
```

`sub_score` is published at 1 dp; `headroom_to_cap` at 6 dp; they are
1.4–3.5 pp apart on four of five legs. `score_audit` publishes **no** precision
or rounding declaration — `[k for k in score_audit]` =
`[cap, components, duplicate_components, effective_information, excluded_components,
excluded_reasons, independent_components, nominal_weight_total, nominal_weights,
saturated_components, scale, weight_rule]`.

The artifact has exactly **one** `display_rounding` block and it is 200 KB away
in a different section: `sections.optimization.data.moments_basis.display_rounding`
= `{"weights_decimals": 6, "moment_decimals": 4, "note": "A reader recomputing from the
published 6-decimal weights lands within 5e-7 * len(universe)…"}`. So the
convention exists in the codebase and was not carried to `score_audit`.

A reader checking the identity a field name implies gets a wrong answer on 4/5
rows with nothing to tell them which number is the rounded one.

## NEW-4 · `correlation_stability`'s alert prose is the high-correlation branch's text, fired on a low-correlation reading · **P1**

```
sections.risk_studio.data.components.correlation_stability.data
  .current_avg_correlation    = 0.1361
  .historical_median          = 0.3408      (current is 60.1% BELOW median)
  .historical_threshold_10th  = 0.2189      (current is BELOW the 10th percentile)
  .historical_threshold_75th  = 0.4129
  .historical_threshold_90th  = 0.459
  .is_regime_break            = true
  .alert_level                = "ELEVATED"
  .series[-1]                 keys: [avg_correlation, date, threshold_75th, threshold_90th]
```

`message`, verbatim:

> "Average pairwise correlation (0.136) is at or below the 10th percentile (0.219)
> of its own history (median 0.341). Co-movement has collapsed: this is a change of
> correlation regime, not a reassurance. **Positions that diversified historically
> may not diversify against each other in this regime**, so historical risk
> estimates that assumed the median correlation no longer describe this book.
> (tested two-sided against its own history of 489 overlapping 60-day rolling
> windows.)"

The two-sided test is now correctly implemented — the LOW branch fired, and the
opening sentence reports it correctly. But the operative claim is the HIGH
branch's: a low average pairwise correlation among holdings means the holdings
diversify **more** than typical, not less. The measured value is in the *most
diversified decile* of its own sample, and the prose asserts that historical
diversifiers may fail to diversify in this regime.

Two corroborating asymmetries in the same object:

- The per-row `series` schema carries `threshold_90th` and `threshold_75th` —
  the two thresholds **not** breached — and does **not** carry
  `threshold_10th`, the one that was. A reader scanning the series for the
  trigger cannot find it.
- `alert_level: "ELEVATED"` with no direction field, so nothing in the payload
  records that this was a *low*-correlation alert.

The `489` claim is **not** a defect: it is published as
`.series_observations` = `489` with `.series_retained` = `60` and
`.series_trimmed_in_summary` = `true`, and
`sections.risk_studio.omitted_fields` =
`["components.correlation_stability.data.series"]` explains the trim. That part
is exemplary.

## NEW-5 · the vol-cone's `current_forecast` withholding reason names a field it does not have · **P1**

```
sections.risk_studio.data.components.volatility_cone.data.current_forecast keys:
  [annualized_vol, effective_n, effective_n_rule, horizon_days, model,
   minimum_effective_n_for_percentile_rank, n_windows, percentile_rank,
   percentile_rank_95pct_half_width_pct, percentile_rank_half_width_rule,
   percentile_rank_sufficient_data, percentile_rank_withheld_reason,
   ranked_against_window_days, valuation]
  'current_realized' in current_forecast -> False
```

`current_forecast.percentile_rank_withheld_reason` is **byte-identical** to the
21-day window row's reason (verified `==`):

> "withheld: effective_n 13.67 < 30 overlapping-window observations over 21d; the
> worst-case 95% half-width on a rank here is 26.5pp, so the rank carries no usable
> information. **The quantiles in this row still describe the observed
> overlapping-window sample; current_realized is measured.**"

`current_forecast` publishes `model: "GARCH(1,1)"`, `annualized_vol: 0.1323`,
`horizon_days: 21`, `valuation: "normal"` — a **model forecast**, and no
`current_realized` field. The sentence's last clause asserts a measurement that
the object it is attached to does not carry. The 21-day row's
`current_realized` is `0.0725`, so the forecast is
`0.1323 / 0.0725 = 1.8248×` the realised figure — a difference the copied reason
conceals rather than describes.

**Adjacent, same block:** `insufficient_data` is `false` on all five window rows
while `percentile_rank` is `null` and `percentile_rank_sufficient_data` is
`false`. The row-level flag a reader would naturally check is not the flag that
drives the null, and `current_forecast` has no `insufficient_data` field at all.
Both flags are individually correct; nothing states their scopes.

## NEW-6 · published `effective_n` / `ar1` pairs and `percentile_rank_95pct_half_width_pct` are not recomputable from the payload · **P2**

21 distinct autocorrelation blocks. `effective_n = n(1−ar1)/(1+ar1)` holds to
rounding on all 21, but the published pair is not self-reproducing to 1e-4 on
**5 of 21**, because `ar1` is published at 5 dp and `effective_n` at 3–4 dp with
no declared precision, and `effective_n` was computed from the unrounded `ar1`:

| block | n | `ar1` | `effective_n` | recomputed from published `ar1` | abs err |
|---|---|---|---|---|---|
| 92a30c74 | 37 | 0.046339 | 33.7227 | 33.722777 | 7.7e-05 |
| 95ed3604 | 37 | −0.256325 | 62.5059 | 62.505833 | 6.8e-05 |
| 9fc5175a | 245 | −0.059075 | 275.7644 | 275.764142 | 2.6e-04 |
| e26bf43a / 3f670599 | 307 | 0.05808 | 273.2965 | 273.296386 | 1.1e-04 |
| d2e7eb2e / 4ce4a91e | 170 | 0.074968 | 146.2886 | 146.288485 | 1.2e-04 |

Inverting `effective_n` back to an implied `ar1` puts the residual at ≤1.2e-06 —
i.e. the discrepancy is the 5-dp `ar1` display, confirmed.

`effective_n` is also published at **3 dp in 2 blocks** (`48.709`,
`31.443`) and **4 dp in the other 19**, with no rule.

Same defect in the vol-cone, larger and cleanly demonstrable:

```
published rule: percentile_rank_95pct_half_width_pct = 1.96*100*sqrt(0.25 / effective_n)
  L= 10  published 18.0    from published eff_n 18.0    OK
  L= 21  published 26.5    from published eff_n 26.5    OK
  L= 63  published 49.7    from published eff_n 49.7    OK
  L=126  published 81.5    from published eff_n 81.7    MISMATCH (1.0 pp is not it: 0.2 pp)
  L=252  published 207.9   from published eff_n 208.9   MISMATCH (1.0 pp)
```

All five are reproducible from the **unrounded** `n_windows / window_days`
(`1.444444` → 81.54 → 81.5; `0.222222` → 207.89 → 207.9), so the rule is right
and the *published pair* is not.

## NEW-7 · `full_history` advertises a 2 486-row window and annualises on 307 rows — a 9.11× error for a reader who recomputes · **P0**

```
sections.tear_sheet.data.full_history.observation_count = 2486
sections.tear_sheet.data.full_history.window            = {start: 2016-09-12, end: 2026-09-25, days: 2486}
sections.tear_sheet.data.full_history.first_observation  = '2016-09-12'
sections.tear_sheet.data.full_history.last_observation   = '2026-09-25'
sections.tear_sheet.data.full_history.metrics.days      = 307      <-- the annualisation divisor
```

I proved `307` is the divisor by elimination:

```
(1 + 0.377277)**(252/307)  - 1 = 0.3005145033   <- the only candidate in the rounding box
(1 + 0.377277)**(365/307)  - 1 = 0.4631400709
(1 + 0.377277)**(252/2486) - 1 = 0.0329808329
(1 + 0.377277)**(365/2486) - 1 = 0.0481209770
published cagr = 0.300514
ln(1+0.300514)/ln(1+0.377277) = 0.8208457  ->  implied n_days = 307.00045
```

```
reader recomputes cagr from the PUBLISHED window: 0.032981 (3.30%)
published:                                     0.300514 (30.05%)
ratio:                                         9.1118x
```

`metrics.days` = 307 is the **only** counter-signal inside `metrics`; the block's
own `observation_count` and `window.days` say 2486 and the block advertises
`first_observation` 2016-09-12. The 307-row sample *is* named elsewhere —
`…relative_vs_nifty.measurement_windows.windows.holding_window_metrics.window` =
`{start: 2025-03-11, end: 2026-09-23, days: 307}` with
`same_sample_as: "tear_sheet.full_history.metrics"` and
`published_also_at: "tear_sheet.full_history.metrics.days"`, and
`sections.monte_carlo.data.model_window_start` = `"2025-03-11"` with
`model_observations` = `307` — but **no field inside `full_history` states that
its metrics were measured on a 307-row sub-window.** `"2025-03-11"` occurs 4× in
the artifact, always attached to 307, and nothing says why the sample begins
there rather than at `first_observation`.

This is the same class the integrator already recorded once ("three blocks
*mislabelling* their count population"), on a block nobody re-checked, and it is
the second-largest numerical consequence in the export after NEW-1.

Two adjacent items in the same neighbourhood:

- **307 is not derivable from the published per-leg counts.**
  `sections.tear_sheet.data.full_history.per_ticker_return_observations` minimum is
  **383** (`SELECTIPO.NS`), max **2484**. A 14-way intersection of those counts
  cannot be 307. Unexplained shortfall: **76 rows**, no field names it. The same
  307 drives `…tail_dependence.data.total_observations` = 307,
  `…volatility_cone` (all `n_windows` = `307 − L + 1`, verified 5/5),
  `…optimization`? no (`170`), and `sections.monte_carlo.data.model_observations`
  = 307.
- **Three un-disclosed requested-vs-measured shortfalls.**
  `sections.risk_studio.inputs.component_lookbacks` = `{risk_contribution: 365,
  tail_dependence: 756, volatility_cone: 756, correlation_stability: 756}` against
  a 307-row sample (2.46×) and
  `sections.monte_carlo.data.model_minimum_observations` = 60 — no block in
  `risk_studio` publishes a measured-vs-requested pair.

## NEW-8 · `factor_exposure` publishes five different row counts for one regression family · **P1**

```
sections.factor_exposure.data.portfolio.observations                          = 100
sections.factor_exposure.data.model_window                                    = {start: 2026-01-20, end: 2026-09-25, days: 174}
sections.factor_exposure.data.full_history.observation_count                  = 174
sections.factor_exposure.data.history_coverage.model_observation_count         = 174
sections.factor_exposure.data.history_coverage.covered_days                   = 174   (scope "model_return_observations")
sections.factor_exposure.data.history_coverage.benchmark_overlap_observations = 169
sections.factor_exposure.data.r_squared                                       = 0.7147   (no n, no window)
sections.factor_exposure.data.lookback_days / inputs.lookback_days            = 252
```

`portfolio.observations` = **100** contradicts every other count in its own
section by 74 rows (and 69 against the benchmark overlap), with no field naming
the discrepancy. `annualized_alpha` = `0.5431` and `market` = `1.143` are
computed on the 100.

The direction of the compromise is also undisclosed: the risk-score leg reads
`factor_exposure`-style r-squared but from a *different* sample —
`sections.dashboard.data.components.risk_score.data.score_audit.components.factor_risk.input_statistic_value`
= `0.0758` with `input_statistic: "benchmark_regression_r_squared"` and
`input_sample.rows: null` + `rows_reason`, against
`sections.factor_exposure.data.r_squared` = `0.7147`. The risk-score side
disclaims comparability explicitly
(`…risk_score.data.factor_model.note`: "factor_exposure publishes the same model
over full exchange history, so its R-squared describes a longer, different
sample: compare the two only through this block's basis and window, never by
their values alone") — but the *`factor_exposure`* side names no sample for its
`r_squared` and nothing links the two. Two fields with near-identical names
(`benchmark_regression_r_squared`, `factor_r_squared`) carry 0.0758 and 0.7147
and differ by 9.4×.

*(No truncation claim here: `model_window` 2026-01-20 → 2026-09-25 is 249
calendar days = the 252-day request expressed in trading days. That reconciles.)*

## NEW-9 · `full_history.measurement_windows` is the holding-window template with its numbers swapped · **P2**

```
sections.tear_sheet.data.full_history.relative_vs_nifty.measurement_windows
  .windows.holding_window_metrics.basis        = "full_exchange_history_current_weights"
  .windows.holding_window_metrics.description  = "the hypothetical-current-weights portfolio
     return series over the full cache depth, which is the same sample the full_history
     metrics block was measured from"
  .windows.portfolio_benchmark_overlap.relation_to_metrics_window_basis
    = "every holding-window portfolio return observation also has a benchmark return, so a
       field fitted here uses exactly the rows the metrics block was measured from"
  .comparison_note = "…`metrics` and this block's holding-window sample are like for like…"
```

A key named `holding_window_metrics` inside `full_history` describes a 307-row
full-cache-depth window, and two prose fields still say "holding-window". The
holding-window twin at `sections.tear_sheet.data.relative_vs_nifty.measurement_windows`
carries the same sentences with `holding_window` genuinely meaning the holding
window. A reader who greps `holding_window_metrics` gets both.

Also: `distinct_windows` = **3** and `windows_fields_rest_on` = **2** in the
holding-window block (honest — `holding_window_metrics` is a reference window no
`relative_vs_nifty` field rests on) versus **2** and **1** here. Both pairs are
published, so the counts reconcile; the defect is the copied prose, not the
counting.

## NEW-10 · `omega`'s standard error and its interval disagree by 3×, unremarked · **P2**

```
sections.tear_sheet.data.estimate_uncertainty.metrics.estimates.omega
  .point = 3.38539   .standard_error = 60.814153   .conf_int = [1.314768, 21.222506]
  .point_within_conf_int = true    .point_within_conf_int_note = null
sections.tear_sheet.data.estimate_uncertainty.metrics.estimates.tail_ratio
  .point = 1.554919  .standard_error = 17.241108   .conf_int = [0.85946, 10.655782]
```

```
1.96 x se(omega)      = 119.19355
published CI halfwidth =   9.95387
se / CI width          =   3.0548
se / point             =  17.96x
```

For a percentile bootstrap of the *same* statistic, the standard error and the
interval width should agree within a small factor; here they differ by 3× and the
SE is 18× the point. The method string does declare the SE's definition
("the sample standard deviation (ddof=1) of the resampled statistic"), and the
interval is a percentile interval, so the two are *allowed* to diverge on a
heavy-tailed resampling distribution — but
`point_within_conf_int_note` is `null` and no field warns that the SE and the
band describe distributions this far apart. Across all 261 records with both
fields, `omega` and `tail_ratio` are the only two above a 50% divergence
(`sortino_ratio` next at 0.751).

**This one is a disclosure gap, not an error** — the bootstrap of a ratio with a
near-zero denominator genuinely can produce that. Listed because the artifact's
own standard is to publish such notes elsewhere
(`point_within_conf_int_note` on the one out-of-interval record, and
`headline_attribution_note` on the rounding), and here it does not.

## Checked and found NOT defective (recorded so they are not re-cited)

| checked | result |
|---|---|
| point inside its own `conf_int`, all 343 estimate records | 2 exceptions, both on NIFTYIETF `cvar_95`, and **both fully disclosed** with a `point_within_conf_int: false` and an explanatory `point_within_conf_int_note` |
| `point_within_conf_int` flag vs arithmetic, 343 records | **0** disagreements |
| `block_size` vs the published `n ** (1/3)` rule, 21 blocks | 20/21 exact. The 21st is the `not_computed` `market_model` block (`observations: 0`, `block_size: 1`) — an undisclosed floor of 1 at n=0, harmless because `status: "not_computed"` and a `reason` are both present |
| `n_windows` vs the 307-row series, 5 vol-cone windows | all 5 = `307 − L + 1` exactly |
| stress `max_drawdown` = `round(portfolio_impact × 1.15, 4)` | 4/4 exact |
| liquidity tier ladder `spread` and `score_raw` | 14/14 exact at 4 dp and 6 dp respectively |
| `by_sector` vs `by_weight` | all 7 buckets reconcile at 4 dp, `rounding_residual: 0.0` published |
| HHI and N_eff vs `by_weight` | exact to the published precision |
| `annualized_alpha` = `alpha × 252` | 0.002155 × 252 = 0.54306 → 0.5431 ✓ |
| regime `annualization_factor` = `252 / observations` | 3/3 exact |
| envelope `snapshot_consistency_measured` pointers | 3/3 resolve |
| `sum(weight)` = 1.0, `sum(market_value)` = `total_value` | both exact |
| `"Calmar"`, `"look-through"`, `"underlying"`, `"0-100"` prose | **0 occurrences each** — these absences *are* the RL-7 and Calmar findings |
| 9 `status: "not_computed"` records that carry a `point` | **not defects** — each has a `reason` scoping the status to the *interval* ("The point estimate stands; its precision is declared absent rather than approximated") or naming the failed identity check |

---

# Uncertainty — what I could not determine, and what would be needed

1. **`diversification_score` = 98.4's formula.** Nine reconstructions tested, none
   matches. Needs the `concentration` scoring code in `analytics_engine.py`
   (owned by another agent this session — not read, not touched).
2. **Whether `score_audit` `components` values are numpy scalars in the producer.**
   `json.load` erases the distinction; the payload has zero numpy markers. Needs
   the serialisation path (`json.dumps(..., default=)` or the pydantic model
   config), not the artifact.
3. **Whether per-state `ann_ret` has a 30-observation gate.** The smallest live
   state has 114 observations, so the artifact cannot exhibit the asymmetry.
   Needs the regime per-state path in `analytics_engine.py`.
4. **Whether NIFTYIETF's gap is a vendor gap or a cache artefact.** The artifact
   publishes per-leg missing *counts* in four windows plus a 17-session refusal
   attribution naming NIFTYIETF, but I enumerated all 342 dated records in the
   payload and **none carries a per-ticker value**, so no missing date is
   inferable. Needs either a per-leg missing-date list or the delivered-bar index
   per ticker over 2026-08-03 → 2026-09-25.
5. **Whether 16 exceedances is enough for the two-parameter GPD.** No standard
   errors on `gpd_shape_xi` or `gpd_scale_beta` are published, and no minimum is
   stated. Needs the fit's covariance, which the payload does not carry.
6. **What the 307-row sample boundary is.** `2025-03-11` is published four times,
   always with 307, and never explained. It is also *not* the 14-way intersection
   of the published per-leg counts (shortest is 383). Needs the analytics window
   resolution in the engine.
7. **Which beta is right** — `1.143` (factor_exposure, 100 rows, Newey-West),
   `1.1037` (tear_sheet full_history, 307 rows) or `−0.2275` (the same 307 rows,
   from the payload's own estimator). `mu`/cov and the two return series are
   unpublished, so this cannot be settled from the artifact. Needs the
   full_history beta/alpha code path.
8. **What `gamma`-free `p` the 0.95% and 99% levels correspond to** — not needed,
   dropped as scope creep.

No `git stash`, `git checkout` or `git restore` was used. No source, test or
existing doc was read-modified or written other than this file.

---

# Next step for the parent

**NEW-1 is the mission.** The uncertainty gate's own identity check already
proves `tear_sheet.full_history.relative_vs_nifty.beta_vs_nifty` = `1.1037` is
not the regression of the published series — its own resampling estimator returns
**−0.2275**, a sign inversion. Route it as a new P0 against the producer of the
full-history beta/alpha, with the requirement that the `point_tolerance` identity
check gate the **point**, not only the band. Do not let it be closed as
"the band was correctly withheld": the band was withheld *because* the point is
wrong, and the point is still published with `measurement_windows.status =
"computed"` and `gate_effect = "reported: the overlap clears the annualization
policy minimum"` beside it.

Then, in order: **NEW-7** (2486 advertised / 307 annualised, 9.11× recompute
error), **NEW-2** and **NEW-3** (the `score_audit` rounding pair, one
`display_rounding` block away in `optimization`), **NEW-4** (the copied
high-correlation alert prose), **NEW-5** (the copied `current_realized`
sentence), **NEW-8** (five counts, one regression family).

Two corrections to carry forward:

- **RL-7 SURVIVES**; the five ETF instruments and their 32.10% weight are now
  derivable, but scale, formula and look-through disclosure are all still absent
  (`"look-through"`/`"underlying"`/`"index constituents"` = 0 occurrences) while
  two sibling scores declare theirs.
- **Do not generalise QM-2's withdrawal.** `alpha_annualized` is `null` in the
  holding-window block, but `0.2176` is live in `full_history` and `0.5431` is
  live in `factor_exposure.data.portfolio.annualized_alpha`.

Two items that no longer need chasing: the stress `1.15` convention
(**WITHDRAWN** — published as `max_drawdown_formula` and exact on 4/4) and
`liquidity.observation_window.start/end` being null (**WITHDRAWN** — published
three times). And **QM-1 is fixed**: `partial_basket_policy =
"refused_not_renormalised"`, `refused_partial_coverage_rows = 17`, with the
offending legs and session counts named in
`…performance_history.warnings[0]`.
