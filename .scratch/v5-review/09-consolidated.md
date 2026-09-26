# v5 export — consolidated review

Six persona reviewers, adversarially cross-checked. Every P0 below was
re-derived by the integrator from the artifact or the source unless marked
*agent-verified*. Agent claims I corrected or downgraded are recorded too —
including one where **my own correction of an agent was itself wrong**.

Artifact: `C:\es\others things\finengine-portfolio-ai-context v5.json`
876 445 B · `portfolio-4b78905b588c` · schema 2.0 · 2026-09-26 · 17 sections ·
14 holdings · book value **INR 43,609**

Reviewer files: `01-quant-math` · `02-performance-attribution` ·
`03-data-integrity` · `04-statistical-inference` · `05-adversarial` ·
`06-risk-liquidity` · integrator verification in `00`, `07`, `08`, `09`.

---

## The one-paragraph answer

**The arithmetic is correct and the interpretation is not defensible.** Agent 01
rebuilt the price frame from the database and reproduced `tear_sheet`'s 11
metrics to |Δ| < 5e-7, `realized_risk`'s portfolio and all 14 per-position
metrics to |Δ| < 1e-12, `risk_contribution`'s 14 Euler RCs to **Δ = 0.000000**,
`monte_carlo` from its seed, and `volatility_sizing`'s 14 EWMA vols to **Δ = 0.0**.
**Not one number is arithmetically fabricated.** Every P0 below is a defect in
*what was measured, what was claimed about it, or what it instructs a reader to
do* — which is a harder class of bug to find and a more dangerous one, because
the numbers are all correct.

Three structural themes, in order of severity:

1. **The 39-observation series is not the portfolio** (QM-1) — and nothing says so.
2. **~2,000 point estimates, zero uncertainty** (SI-5), including a
   "confidence interval" that is a constant (SI-3/QM-3).
3. **The artifact emits an actionable trade instruction derived from noise**
   (SI-1/AD-1).

---

## P0s — reproduced by me

### QM-1 · the headline series is a partial basket, renormalised daily · CONFIRMED

`analytics_engine.py:74-77`:

```python
active      = clean.notna() & (weight_frame > 0.0)
active_wt   = active.mul(weight_frame, axis=1).sum(axis=1)
numerator   = clean.where(active, 0.0).mul(weight_frame, axis=1).sum(axis=1)
portfolio   = numerator / active_wt          # <- renormalises whatever survived
```

On any date where only some tickers have a finite return, the surviving weights
are **renormalised to 1.0** and the day's "portfolio return" is computed from
that partial basket. The docstring is explicit that this is deliberate — it
trades synthetic zeros for renormalisation. The second distortion is worse
because it is invisible.

Agent 01's specific instance: **20 of 39 days are partial baskets, and the final
day is `ELECTCAST.NS` alone**, whose weight `0.033177` is inflated by
`1/0.033177 = 30.1415` — I reproduced that factor exactly. So the last
observation, which sets the terminal value and therefore `total_return`, CAGR,
Sharpe and Sortino, is **one small-cap's return standing in for a 14-stock
portfolio**.

**Disclosure: none.** All 7 occurrences of "renormaliz" in the artifact concern
risk-score weights, regime rounding, and `india_flows`. `partial_basket`,
`basket`, `breadth`, `constituent_count`, `legs_active` — **0 occurrences each**.

### SI-1 / AD-1 · trade instructions derived from noise · CONFIRMED

```
KS test, 91 Engle-Granger p-values vs Uniform(0,1):  D=0.131101  p=0.079886
declared positives 4 · expected by chance 4.55 · Poisson P(X=4)=0.188710
Bonferroni 0.05/91 = 0.00054945  ->  0 survivors
bonferroni 0 | fdr 0 | multiple_testing 0 | false_discovery 0
```

The p-values are statistically indistinguishable from random. Four "discoveries"
where 4.55 are expected by chance; zero survive correction. Yet:

| pair | p | johansen agrees | hedge β | published signal |
|---|---|---|---|---|
| ELECTCAST/MCX | 0.042 | **false** | 0.0086 | `LONG_SPREAD (Long ELECTCAST.NS, Short MCX.NS)` |
| JUNIORBEES/MIDCAPIETF | 0.0485 | **false** | 33.6396 | `SHORT_SPREAD (Short JUNIORBEES.NS, Long MIDCAPIETF.NS)` |

`test_agreement` honestly discloses the 8 disagreements, but the `signal` field
is not gated by them. The ±1.5 z-threshold is hardcoded and appears 0 times in
876 KB, and neither directive publishes its hedge ratio — read 1:1 they
mis-size by ~116× and ~34×.

### SI-3 / QM-3 · `confidence_interval` is `σ × [0.8, 1.2]` · CONFIRMED to the bit

```
midpoint*0.8 == ci[0]  ->  True (exact float equality)
midpoint*1.2 == ci[1]  ->  True
```

Aggravated because the **same export** has `stress_testing` labelling its
nominal 0.95 `nominal_label_not_simulated`. The codebase knows the convention
and violates it one section over — which teaches the reader to trust the field.

### QM-4 · `achieved_volatility` is a tautology · CONFIRMED — and I was wrong

```
rec_vol = target/scale = 0.15/1.295309 = 0.11580248
rec_vol * scale = 0.15  ==  published achieved_volatility   (exactly)
```

**I must retract my own correction.** Agent 05 reported this and I rebutted it:
I computed `target/current = 1.031 ≠ scale_factor 1.295309` and concluded the
algebra was wrong. My error was assuming the scale is built from
`current_volatility` (0.145465). It is built from a **third** volatility,
0.1158. So `achieved_volatility` is indeed `target_volatility` by construction —
a tautology presented as a measurement, and the published `current_volatility`
is not the vol the sizing used. Agent 01 adds that the true sample-covariance
vol of the book is **0.224888**, contradicting `realized_risk`'s 0.1978 by 36%.

### QM-2 · `relative_vs_nifty` is on a 244-day window, unlabelled · CONFIRMED

`benchmark_*` metrics (−0.068626 / 0.132634 / −0.151818 / −0.636734) match a
**244-day** window exactly; the 36-day window gives different values including
−7.02. They sit beside 39-day metrics with no window label
(`analytics.py:5459-5471`).

### PA-1 · optimizer publishes moments that are not its weights' moments · agent-verified

Published `expected_annual_return 0.2602 / vol 0.1772 / sharpe 1.356` on a
170-observation window. Recomputed from the **published weights**:
`0.000860 / 0.051108 / −0.374507` — a **25.93pp** error and a **sign inversion**.
Root cause: HRP rebinds `assets` to scipy-linkage leaf order without reindexing
`mu`/`cov` (`optimization_service.py:302,304-306,320-321`); leaf order equalled
column order in **0/400** trials.

My corroboration: both triples are internally coherent
(`(0.2602−0.02)/0.1772 = 1.35553`; `(0.000860−0.02)/0.051108 = −0.374501`), so the
agent's numbers are the true moments of the published weights, not noise. I
cannot reproduce them — `mu`/`cov` are unpublished, which is itself part of the
defect. A sign inversion is the worst failure mode for a field an agent acts on.

### AD-2 · GARCH VaR/CVaR are hardcoded z-multiples, with a unit contradiction · CONFIRMED

`analytics_engine.py:1567-1568`: both are `return_space_vol × {1.645, 2.06}`.
Published ratio `0.017865501/0.014266383 = 1.25228` = `2.06/1.645` exactly. So
**`cvar ≡ 1.25228 × var`**, a constant — not a quantile of the fitted
distribution, under `model: GARCH`.

Additionally (my finding, unreported by any agent): the same object publishes
`annualized: True` while carrying a **1-day** VaR
(`0.13768/√252 × 1.645 = −0.01427` ✓). Annualising it is wrong by **15.87×**,
and `confidence_interval` is an interval on *volatility* sitting unlabelled
beside a VaR.

### AD-5 · 13 of 14 trades stamped `executable` while the gate says `false` · CONFIRMED

### DI-1 · `portfolio.as_of` is 18.049 ms *after* `generated_at`, on a Saturday · CONFIRMED

`as_of = 2026-09-26T15:33:25.781197Z` vs `generated_at = …25.763148Z`. NSE is
closed Saturday. The warning exists and is honest — the defect is that the
misleading value sits in `as_of` and the correction sits in `warnings`.

### RL-2 · `is_fat_tailed: true` refuted by its own block · CONFIRMED

`gpd_shape_xi_raw −0.7068`, `gpd_shape_xi_used −0.5` (both negative = *bounded*
tail), and `evt_pot_var −0.036708 < historical_var −0.031724`. No
`is_fat_tailed_basis`. Also: the POT fit rests on **26 exceedances** of 518,
unflagged.

---

## My own tool is three-for-three wrong

- `NUM-018` / `XS-009` — demanded fabricated data to go green.
- `ENV-012` — **blind to future and stale `as_of`** (mutation-tested: +5 months
  → green, −10 years → green). Tests membership in the collector's clock window
  instead of ordering against it.
- `ENV-016` (agent 05) — exempts `available` sections from carrying any warning,
  which is the status every P0 above carries.

Agent 05's characterisation is the fair one and I am adopting it over my own
docstring: **not one of the 47 rules asks whether a number is true.** Agent 03
mutation-tested 8 defects through the suite — including relabelling all 14
positions USD at `fx_rate 1` — and all stayed green. **Green means "no known
pattern matched", not "correct."**

---

## Corrections and downgrades I am recording against agents

| Agent claim | Disposition |
|---|---|
| AD-4 "achieved is a tautology" | Agent **right**; **my rebuttal was wrong** — retracted above |
| AD-4 algebra (`scale = target/current`) | Wrong — scale uses a third vol, 0.1158 |
| AD-2 "`cvar = −VaR × 2.06`" | Right substance, wrong ratio — it is `var × 1.25228` |
| RL-11 sizing "no warning, P0" | **Downgraded to P2.** A dedicated `execution` block discloses `execution_eligible: false`, `financing_requirement: 12878.08 INR`, `block_reasons`, and `methodology` — twice. Residual is only that no `warnings` array exists |
| RL-1 "overstated ~10,700×" | Ratio **withdrawn** — band-midpoint vs sub-second is meaningless. Structural point stands, severity P1 not P0 on a INR 43,609 book |
| SI-1 test/p-value mismatch | **Refuted.** Verified against `mackinnonp` for all 91 pairs, max Δ 2.4e-05, 0 monotonicity violations |
| QM-5 (39-day annualisation) | **Not a new defect** — deliberate policy from the prior wave. The new part is disclosure: Sharpe 95% CI [−9.77, +16.75] spans zero, published `available` with no warning |
| SELECTIPO contamination (my own prior) | **Does not hold.** Ranks 11/13 on vol; dropping SELECTIPO+MAFANG moves portfolio vol +4.0% |

---

## Clean — recorded so it is not re-litigated

Reproduced bit-exact by agent 01: `tear_sheet` 11 metrics (|Δ|<5e-7);
`realized_risk` portfolio + 14 positions (|Δ|<1e-12); `risk_contribution` 14
Euler RCs (**Δ=0.000000**); `monte_carlo` from `seed=42`; `volatility_sizing`
14 EWMA vols (**Δ=0.0**); GARCH refit in `arch` (Δ 6e-10). By agent 03: all 7
per-position identities across 14 positions at **Δ 0.00e+00**, `Σweight = 1.0`,
all FX `identity`, `concentration` and `stress_testing` reconciling exactly. By
agent 02: weights bit-identical in 4 places and provably current market value on
a book that drifted up to 5.36pp; regime internally consistent (the bull/HIGH-risk
contradiction I expected **does not exist**); no lookahead bias in the optimizer;
dashboard copy layer 0 diffs on all 9 true copies. By agent 04: no hardcoded
p-values; stationarity not confused with cointegration; `regime` and
`india_flows` disclosure is exemplary; Sortino correctly uses full-sample
downside deviation at a MAR; `realized_risk` **refuses** NIFTYIETF with nulls
rather than defaulting; `MCX.NS` refused as below-minimum-notional; all stress
shocks multiplicative with the post-shock book re-normalising to 1.0000000000;
`sum(trades.amount)` equals `financing_requirement` to the paisa.

---

## If only three things get fixed

1. **QM-1** — stop renormalising partial baskets, or publish per-day constituent
   count. A Sharpe computed from a series whose last day is one stock at 30×
   weight is not a portfolio Sharpe, and no downstream caveat repairs it.
2. **SI-1** — gate `signal` on `johansen_agrees_with_decision`, publish the
   multiplicity correction and the hedge ratio, or stop emitting directives.
3. **SI-3** — delete `confidence_interval` or compute it. A hardcoded ±20% band
   under the name of a confidence interval is the most reusable falsehood in the
   artifact.
