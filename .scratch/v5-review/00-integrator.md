# Integrator's own pass on the v5 export

Reviewed independently of the six persona agents, using only the artifact and
the source. Kept separate so it is not confused with their findings.

Artifact: `C:\es\others things\finengine-portfolio-ai-context v5.json`
876 445 bytes · `export_id portfolio-4b78905b588c` · `schema_version 2.0`
`generated_at 2026-09-26T15:33:25Z` · `completed_at …:44Z` · `base_currency INR`
`detail=summary` · `snapshot_consistency: best_effort` · 17 sections · 14 holdings

## Checker verdict (run by me, not reported to me)

```
uv run python -m app.debugging.context_audit check --export <v5>
rules run 47 | passed 47 | failed 0 | findings 0 | exit=0
```

47/47 green. Necessary, nowhere near sufficient — see MY-1 below, which the
checker does not catch.

---

## MY-1 (P0, honesty) — `performance_history` states a cause its own artifact disproves

**Path:** `sections.dashboard.data.components.performance_history`
**Severity:** P0 — a delivered-history gap is attributed to data unavailability
when the same file contains the missing data. An AI agent reading this will
conclude the portfolio genuinely has no history before 2026-08-25 and will not
look for it.

**Observed:**

```
history_coverage.requested_start  = 2026-06-28
history_coverage.delivered_start  = 2026-08-25
observation_count                = 19 of 65 expected (29%)
warning: "Delivered history starts 2026-08-25, 58 calendar days after the
          requested 2026-06-28; the requested start was not delivered."
```

**The artifact disproves the stated cause.** For the *same 14 tickers*, the same
file publishes:

```
realized_risk.history_coverage.full_history_start = 2026-01-19  (175 days)
factor_exposure.history_coverage.model_observation_count = 174
tear_sheet.full_history.first_observation = 2016-09-12  (2486 observations)
```

So 2026-01-19 → 2026-08-25 is ~135 sessions of price history that demonstrably
exists in this very artifact, for these very tickers, and that
`performance_history` did not deliver.

**The request was WIDER than the ones that succeeded.** `get_performance_history`
computes `start = today − days` = 90 days back (`analytics.py:4922-4923`), a
*wider* window than `realized_risk`'s 2026-01-17 request — and it delivered
*less*. A wider request returning a narrower series is the inverse of a data
availability constraint, which is what the warning asserts.

**Not the holding mask either.** `get_performance_history` does apply
`holding_window()` with each position's own `added_on` and `buy_price`
(`analytics.py:4967-4982`), so the start is mask-derived in principle. But the
stored `added_on` values are:

```
oldest 2024-11-25 … MCX/NIFTYIETF/MAFANG 2026-06-08 … REDINGTON.NS 2026-08-04
```

The **latest** `added_on` is **2026-08-04**. No position has an `added_on` near
2026-08-25, so the mask cannot produce a 2026-08-25 start. Every other
section's mask-derived start is 2026-08-03 (`buy_price_inferred`).

**So there are two holding-window starts for one portfolio, 16 sessions apart:**

| section | start | source |
|---|---|---|
| `tear_sheet`, `realized_risk`, `regime`, `risk_contribution`, `factor_exposure` | 2026-08-03 | `buy_price_inferred` |
| `performance_history` | 2026-08-25 | undeclared |

Both are labelled `covered_days_scope: holding_window_aligned_return_rows`, so
the existing unit label actively conceals that they are different windows.

**Root cause:** not yet localised. `_fetch_price_series_dict`
(`analytics.py:542-569`) passes `start`/`end` straight to
`data_service.fetch_historical_data` with no cap, so the narrowing is inside the
data service or its cache path — a different code path from the one the other
sections use, since they demonstrably retrieve 2026-01-19. Needs one more hop.

**Consequence:** the user-facing performance chart shows 19 of 39 available
sessions — it silently omits 16 sessions of the holding window, and omits ~135
sessions of history that the artifact itself contains.

**Checker gap (mine):** `XS-001`/`XS-002` reconcile starts only among sections
that publish an `intersection_start`. `performance_history` publishes
`history_coverage.delivered_start` instead, a key the cross-section rules never
read, so it is excluded from the comparison set and the contradiction is
invisible. Proposed rule: *every section declaring a delivered/measured window
start for the same portfolio must declare the same start, or state why not.*
This is a gap in my tool, not in the product, and the product defect above is
real either way.

---

## MY-2 (verified clean) — checks I ran that found nothing

Recording these so nobody re-runs them.

- **No time travel.** Latest date anywhere in the 876 KB file is `2026-09-26`,
  equal to `generated_at`. Zero dates after generation.
- **Weights.** `tear_sheet.holdings` — 14 values, sum `1.0` to 1e-12, all > 0.
  HHI 0.08616, effective N 11.61, top-3 cumulative 0.3630, largest
  MOTHERSON.NS 0.1368. Recomputes cleanly.
- **`tear_sheet` CAGR arithmetic.** `total_return 0.056879`,
  `n 39`, `(1+tr)^(252/39)−1 = 0.429684` vs published `0.429686` — matches
  (the 2e-6 gap is the published 6dp rounding of `total_return`).
  The arithmetic is right. The *policy* of annualising 39 observations is a
  separate question, delegated to the quant and statistical reviewers.
- **`tear_sheet` max drawdown.** Reconstructed from the 39-point
  `underwater` series: `−0.021283`, published `−0.021283` — exact match.
- **Sharpe: my first hypothesis was wrong, and I am recording that so it is not
  re-raised as a false positive.** `sharpe 3.487604` does **not** equal
  `cagr / volatility` (that is 4.3739). It is not a defect: Sharpe correctly
  uses the *arithmetic* mean of daily returns annualised, not the geometric
  CAGR, and for a 5.69% 39-day sample the geometric annualised (42.97%)
  exceeding the arithmetic (≈34%) is the expected ordering. Do not report this
  as a mismatch without recomputing the daily series.
- **`performance_history` row arithmetic.** All 18 delivered `return` values
  reproduce `value[t]/value[t−1]−1` to 1e-6. 0 mismatches.
- **D-05 fix confirmed in the wild.** Row 0 carries `return: null` +
  `warm_up: true` and `benchmark_value == portfolio_value` (the rebasing
  anchor, correct by construction). The trailing 2026-09-22 session is
  withheld, counted in a warning, and named via `series_end_reason` on the last
  delivered row. Portfolio +0.674% vs benchmark −3.782% over the 19 delivered
  sessions; excess +4.46%. No fabrication.

---

# Verification pass on agent 06 (risk & liquidity)

I re-derived agent 06's headline claims rather than accepting them. One was
over-called, one is understated, and I corrected a ratio in the first that was
methodologically meaningless.

## RL-1 — CONFIRMED, but the overstatement ratio must be dropped

`liquidation_days` is a pure function of the turnover tier. Across 14 positions
there are only **three** distinct values, each perfectly correlated with the
score band and with nothing else:

```
CIPLA 1-2 High | ELECTCAST 1-2 High | MOTILALOFS 1-2 High | NTPC 1-2 High
MCX 1-2 High | MOTHERSON 1-2 High | REDINGTON 1-2 High | NIFTYIETF 1-2 High
JUNIORBEES 1-2 High | MAFANG 1-2 High
ARROWGREEN 2-5 Medium | MIDCAPIETF 2-5 Medium
SELECTIPO 5-10 Low
```

CIPLA and MOTHERSON differ ~2.1x in size and both publish `1-2`. SELECTIPO
publishes `5-10` where `quantity 40 / avg_volume 55,821 = 0.0007` days = **60.6
seconds** at 100% participation. Confirmed: the field never touches position
size or ADV.

**Correction to the agent's framing.** It reported "overstated ~10,700x in days"
and named MCX as worst at ~3,786,984x. Those ratios compare a *band midpoint*
against a *recomputation*, which is not a meaningful ratio — the midpoint is
arbitrary and the denominators are sub-second. I withdraw the ratio as evidence.
The finding stands on the structural point: a field named `liquidation_days`
that is a turnover-tier label, not a duration.

**Severity is lower than P0 on this book, and the agent was right to say so.**
The whole portfolio is ~INR 43,609 (MOTHERSON's entire position is INR 5,966),
so every leg is a rounding error against its own ADV — max 0.07% of one session
for SELECTIPO, 0 breaches. Nothing is illiquid *in practice here*. The correct
severity is **P1: a field that is inert on this book and would be catastrophically
wrong on a book where a position genuinely exceeded ADV**, which is the only case
where anyone reads it.

**Extra finding the agent missed.** `liquidity.observation_window.per_ticker.*`
publishes `start: null` and `end: null` for all 14 tickers, with only
`observations: 20-22`. So `avg_volume` and `avg_turnover` — the inputs to the
entire liquidity score — are averaged over an **undeclared period**. You cannot
tell whether that is 20 sessions or 20 months. That is a disclosure defect my
own ENV rules did not catch.

## RL-2 — CONFIRMED and STRONGER than reported

The agent guessed the `is_fat_tailed` basis was `evt_pot_var > historical_var`.
It is not:

```
gpd_shape_xi_raw  = -0.70676185      <- negative
gpd_shape_xi_used = -0.5             <- negative (constrained_clip)
evt_pot_var       = -0.036708
historical_var    = -0.031724        -> evt < hist, i.e. FALSE
is_fat_tailed     = true
```

So `is_fat_tailed: true` is contradicted by **both** signals in the same block:
the GPD shape is negative (a *bounded/light* tail — the opposite of fat), **and**
the EVT VaR is smaller than the historical VaR. There is no `is_fat_tailed_basis`
field. This is a P0: a fat-tail assertion that the artifact's own numbers
refute, sitting directly beside the numbers that refute it.

Also worth carrying: the POT fit has `exceedances_count: 26` on
`total_observations: 518` at `threshold_u: 0.0205`. 26 exceedances for a
two-parameter GPD is at the thin edge of usable, and is not flagged.

## RL-11 — OVER-CALLED. I am downgrading this one.

The agent reported `volatility_sizing` as "publishes `status: available`,
`warnings: []`, while `recommended_weights` sum to 1.295310 and executing needs
INR 12,878 of borrowing." I checked. There is a dedicated `execution` block and
it is thorough:

```
weights_normalized   : false
gross_exposure       : 1.29531
net_cash_weight      : -0.29531
financing_required   : true
financing_requirement: 12878.08 INR
execution_eligible   : false
block_reasons        : ["financing_required"]
block_reason         : "Gross exposure 1.295310 exceeds 1.0; the target borrows
                        0.295310 of the portfolio value and is not a normal
                        rebalance"
leveraged            : true
cash_weight          : -0.295309
methodology          : "...financing required 12878.08 INR; not executable as a
                        normal rebalance; not full ERC: no Euler RC_i decomposition"
```

Every element of the agent's claim is disclosed, twice, in two separate places.
It missed this block. This is **not a P0** and I am recording the downgrade so it
does not reach you as one.

**The residual, defensible finding is much narrower (P2, discoverability):** the
section's `data_status` is `available` and it publishes **no `warnings` array at
all**. A consumer that reads only the status axis — which is exactly the
contract this artifact spent the last two waves establishing — sees a clean,
`available`, `execution_eligible`-bearing recommendation. The blocking
information is real but sits one level down in a nested key that must be found
deliberately. The fix is to surface `financing_required` as a section warning,
not to change any number.

## RL-3 — accepted as reported, not independently re-derived

35% of the risk score structurally pinned: `market_risk` byte-identical to
`volatility` (both 9.8) because `tail(60)` over 38 returns is the entire series,
and `factor_risk` saturated at the 0-30 maximum for any R² ≤ 0.70 on a 36-row
fit. High-signal and consistent with what I saw in the tear sheet, but I am
flagging it as *agent-verified only* so the distinction from my own checks stays
visible.

---

# Verification pass on agent 03 (data integrity & accounting)

## The headline is right, and it is the right way round

Agent 03 checked 7 identities across all 14 positions and got delta `0.00e+00` on
every one, plus `Σweight = 1.0`, `total_value = Σ market_value`, sectors summing
to 1.0, all 14 `*_base` byte-equal to native at `fx_rate 1`, and
`concentration` / `stress_testing` reconciling exactly. **No wrong currency, no
unstated FX, no duplicate position, no NaN.** The arithmetic is true.

The agent's actual thesis is the sharper one, and I endorse it: the accounting is
true *by luck of a passing run, not by construction*. The freshness layer wrapped
around it is not.

## DI-1 — CONFIRMED, and the disclosure does not rescue it

```
generated_at    = 2026-09-26T15:33:25.763148Z
portfolio.as_of = 2026-09-26T15:33:25.781197Z     <- 18.049 ms LATER
as_of_semantics = "declared_as_of"
2026-09-26 is a Saturday. NSE is closed.
```

A valuation instant **18 ms after the snapshot that contains it** is not
possible — you cannot observe a value after the moment you recorded it.

**Partial correction to the agent.** It reported this as ENV-012-invisible. It is
not: ENV-012 *does* fire on this exact condition, and the reason the 47-rule suite
is green is that the portfolio publishes a warning containing the word "refresh",
which trips the rule's disclosure escape hatch:

> "as_of … is a quote/update timestamp written during this export (it falls
> inside the collection window), so it marks when the value was refreshed, not a
> historical observation date"

That is honest disclosure and I am crediting it. **The P0 is not the missing
warning — it is that `as_of` itself is the misleading field.** A consumer reads
`as_of: 2026-09-26T15:33:25Z` and concludes the book was valued Saturday at
21:03 IST, on a day with no market, at a time no exchange quotes. The correction
lives in `warnings`; the false claim lives in `as_of`. `as_of_semantics:
"declared_as_of"` does not say "this is the collector's clock, ignore it as a
market date" — it says nothing useful.

The right fix is for a refresh-timestamp section to publish `as_of` as the last
real *observation* date (2026-09-25, Friday) and move the refresh instant to a
separate field, not to qualify a misleading value from a warning.

## DI-2 / DI-3 — CONFIRMED

```
liquidity       as_of = None
concentration   as_of = None
stress_testing  as_of = None
```

Three sections publish numbers with **no valuation date at all** and, per the
agent, zero dates anywhere in their payloads. `liquidity` publishes
`overall_band "High"`, `liquidation_time_days "1-2"` and `risk_level "Low"` with
`as_of: null` **and** `observation_window.start/end = null` for all 14 legs.
`stress_testing` publishes a −54.53% loss off measured volatilities with no
window anywhere. That is the same class as the 2024 finding where a score was
published with no sample behind it.

## DI-8 — CONFIRMED, and it is a defect in MY tool. I am recording it against myself.

I mutation-tested ENV-012 directly (`context_audit.py:722-760`):

```
as_of 5 months in the FUTURE (2027-03-01)   -> green
as_of 10 years STALE (2016-01-01)           -> green
as_of inside collection window, undisclosed -> FAIL  (correct)
```

The rule reads:

```python
if not (generated <= as_of <= completed):
    continue          # <- everything OUTSIDE the window is skipped
```

So it tests **membership in the collector's own clock window** rather than
**ordering against it**. It catches exactly one narrow band and is blind in both
directions that matter. A section claiming an `as_of` in the future — the single
most egregious honesty failure available to this artifact — passes all 47 rules.

The design is also fragile in a way the fourth probe exposed: the window is
defined by `generated_at`/`completed_at`, so moving `generated_at` earlier makes
every ordinary `as_of` suddenly "inside the collection window" and the rule starts
firing on correct data. A control that moves when the input moves is not a guard.

A correct ENV-012 needs three separate arms, because these are three different
claims:

| condition | meaning | should |
|---|---|---|
| `as_of > completed_at` | observation from the future | **hard fail** |
| `generated_at − as_of` > threshold | stale | **fail with age published** |
| `generated_at ≤ as_of ≤ completed_at` | refresh timestamp | warn unless disclosed |

This is the second time in this review that a rule I wrote was the problem
(the first was `NUM-018`/`XS-009` demanding fabricated data). I am keeping that
pattern visible rather than quietly fixing it, because the rate is the signal:
**my checker is more confident than it is correct, and green means "no known
pattern matched", not "correct."** DI-7 makes the same point from the other side
— 8 of its mutations, including relabelling all 14 positions USD at `fx_rate 1`,
stay green, because `num_001` reconciles block-level aggregates and never looks
at the per-position ledger.
