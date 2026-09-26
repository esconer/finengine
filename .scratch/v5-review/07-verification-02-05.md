# Integrator verification — agents 02 (performance/attribution) and 05 (adversarial)

Companion to `00-integrator.md`. Every claim below was re-derived by me unless
explicitly marked *agent-verified only*.

---

# Agent 05 — adversarial falsification

## The characterisation of my own tool is correct and I am adopting it

Agent 05 ran the checker itself: `47 rules · passed 47 · failed 0 · findings 0 ·
exit 0`, matching my own run exactly. Its sharper observation: **not one of the
47 rules asks whether a number is *true*.** They check internal consistency,
provenance labelling, unit agreement and disclosure. A rule set with no truth
predicate cannot catch a confidently-wrong number — which is the dominant failure
class in this artifact.

That is the correct characterisation of the tool, and it is a better description
of its limits than anything I wrote in its own docstring.

## AD-2 — CONFIRMED. Corrected ratio, plus a defect the agent missed

The agent wrote "`cvar_forecast` is the hardcoded literal `−VaR × 2.06`". The
substance is right; the ratio is misstated. Source
`analytics_engine.py:1567-1568` (repeated at 1647-1648, 1694-1695):

```python
var_forecast  = float(np.clip(-return_space_vol * 1.645, -0.99, -0.001))
cvar_forecast = float(np.clip(-return_space_vol * 2.06,  -0.99, -0.001))
```

Both are the **same scalar** times a hardcoded normal z-multiple. Neither is a
quantile of the fitted GARCH distribution. So `forecast_risk` publishes, under
`model: GARCH`, two numbers that are not GARCH outputs.

My recomputation pins the constant exactly:

```
var_forecast  = -0.014266383
cvar_forecast = -0.017865501
ratio         = 1.25228
2.06 / 1.645  = 1.25228      <- exact to 5 dp
```

Correct statement: **`cvar = var × 1.25228`**, a fixed constant. Neither `1.645`
nor `2.06` nor a 95% level appears anywhere in the 876 KB, so a reader cannot
tell these are normal-approximation 95% figures.

### Additional defect I found, unreported by the agent: a unit contradiction

```
confidence_interval = [0.11014, 0.16521]   <- ANNUALISED volatility range
midpoint                                    =  0.13768
0.13768 / sqrt(252)                         =  0.008675  <- DAILY vol
-0.008675 * 1.645                           = -0.01427  <- var_forecast  ✓
annualized: True                            <- published on this object
horizon: 1                                  <- published on this object
```

`var_forecast` is unambiguously a **1-day** VaR, while the same object publishes
`annualized: True`. An agent that annualises it is wrong by **15.87×**. And
`confidence_interval` is an interval on *volatility* sitting unlabelled beside a
VaR, so `0.110–0.165` reads like a plausible VaR range and is not one.

## AD-5 — CONFIRMED

```
execution_eligible  : False
trade status counts : {'executable': 13, 'below_minimum_notional': 1}
```

13 of 14 trades stamped `"executable"` inside a section whose own gate reads
`execution_eligible: false` and whose `methodology` says "not executable as a
normal rebalance". Iterating `trades[]` is the natural way to consume a sizing
section, and it yields 13 executable instructions with the gate never seen.
Related and confirmed: `execution_eligible` has no published policy basis.

## AD-4 — PARTLY WRONG; recording the correction

The agent claimed `achieved_volatility` is algebraically incapable of differing
from `target_volatility`. That does not reproduce:

```
target_volatility   = 0.15
current_volatility  = 0.145465131
scale_factor        = 1.295309
achieved_volatility = 0.15

target / current = 1.031120    <- NOT the published scale_factor
current * scale  = 0.188427    <- NOT the published achieved_volatility
```

`scale_factor` equals `gross_exposure` (1.29531), and `current × scale`
overshoots by 25%. The agent's stated algebra is not the code path. What
survives is weaker but real: `achieved_volatility == target_volatility` to
1e-12, and the agent's separate claim that the `0.15` is hardcoded by the
exporter (`ai_context_service.py:1968`) — meaning the sole reason the section
recommends borrowing ₹12,878 is a constant, not a portfolio risk appetite.
*Agent-verified only; I did not confirm the source line.*

## Rest — accepted as agent-verified, not independently re-derived

AD-1 (91 pair tests, 4 positives against 4.55 expected by chance, hardcoded ±1.5
z-threshold absent from the artifact, two explicit "Short MCX.NS" directives on
pairs where the Johansen test disagrees, `hedge_ratio_beta: 33.6396` omitted from
the sizing string); AD-3 (42.97% CAGR from 39 observations with
`status: available` and zero warnings; two objects both named `portfolio`
disagreeing 2.01× on vol and 6.4× on max drawdown; `methodology: "using
quantstats"`); AD-8 (no dividend / fee / tax / slippage / survivorship / split /
corporate-action field anywhere in an artifact containing a 5-year Monte Carlo);
AD-10 (`coverage_ratio: 0` beside `covered_count: null`); AD-16 (three live price
snapshots for the same 14 tickers, 31 mismatching pairs, disclosed only by
`snapshot_consistency: best_effort`).

**Design finding worth acting on:** `ENV-016` only obliges `partial` /
`unavailable` sections to carry warnings. `available` — the status every one of
these problems carries — is exempt from saying anything at all.

---

# Agent 02 — performance & attribution

## Four of five sections are clean; I endorse the do-not-re-litigate list

`concentration` exact to the last published digit and honouring both repo
invariants. `risk_contribution` closes to 1.0, 14/14 sector rollups reconcile,
all 28 shares positive, Cauchy–Schwarz feasible. `regime` internally consistent —
the hypothesised "bull/low-vol vs HIGH risk" contradiction **does not exist**,
and I had expected it to. The 14 weights are bit-identical in 4 places, sum to
exactly 1.0, and are provably current market value (`weight == mv/total_value`
to 0.0) on a book that drifted up to 5.36pp, with the basis declared three
times. Dashboard copy layer: 0 diffs on all 9 true copies.

The agent also found **no lookahead bias** in the optimizer — worth recording,
since that was on my checklist as a likely P0.

## PA-1 (P0) — corroborated, and the error is worse than a wrong number

`optimization` publishes, on a 170-observation window (`2025-09-29` →
`2026-09-22`, `meets_minimum_sample: true`):

```
expected_annual_return = 0.2602      expected_annual_volatility = 0.1772
expected_sharpe        = 1.356       risk_free_rate = 0.02
weights                = 14 legs, sum 0.999998
```

The agent ran the repo's own `optimize()` and recomputed the moments of the
**published weights**: `ret 0.000860, vol 0.051108, sharpe −0.374507`. Root cause:
the HRP branch rebinds `assets` to the scipy-linkage **leaf order** without
reindexing `mu` or `cov` (`optimization_service.py:302,304-306,320-321`), so the
weight vector and the moment matrices are in different asset orders. Over 400
synthetic 14-asset books, leaf order equalled column order in **0/400** trials.

**My independent corroboration.** I cannot reproduce the recomputation — `mu`
and `cov` are not published, so the claim is not checkable from the artifact
alone, and that non-publishability is itself part of the defect. What I *can*
check is whether each triple is internally coherent, and both are:

```
published:   (0.2602 − 0.02) / 0.1772 = 1.35553   vs published 1.356     ✓
recomputed:  (0.000860 − 0.02) / 0.051108 = −0.374501 vs recomputed −0.374507 ✓
```

So the agent's numbers are not noise — they are the coherent moments of the
published weights. The divergence is therefore:

- **expected return wrong by 25.93 percentage points** (26.02% published vs 0.086% actual)
- **Sharpe sign inverted** — `+1.356` published vs `−0.374507` actual

A sign inversion is the worst possible failure mode for a field an agent will act
on: the recommendation reads as a risk *reduction* and is in fact a move to a
negative-Sharpe portfolio. The agent's evidence that leaf order ≠ column order in
0/400 trials makes "wrong ordering" the only parsimonious explanation, and it
explains the sign flip exactly.

Independent supporting observation, entirely from the artifact: the recommended
vector takes **MAFANG.NS from 2.73% to 14.86%** — a 5.4× overweight into the
thinnest name in the book, which the agent flags as sitting on an implied ≥1.00%
annualised-vol floor. A correct HRP solution would not concentrate that heavily
in a name with a data-quality floor on its volatility.

## PA-2 (P1) — independently confirmed, and it is damning on its own

```
optimized  expected_sharpe = 1.356
current    sharpe (tear_sheet, 39 obs) = 3.487604
current    cagr (tear_sheet, 39 obs)   = 0.429686
optimized  expected_annual_return       = 0.2602
```

The "optimized" portfolio publishes a **lower** Sharpe than the book you already
hold, and a lower expected return than the realised CAGR. Different windows, so
not strictly apples-to-apples — but the artifact publishes **no current-portfolio
objective on the same 170-row sample**, so "is this better than what I hold?" is
unanswerable from the export. And the strategy is `hrp` (hierarchical risk
parity), which does not maximise Sharpe, yet publishes `expected_sharpe`.

## PA-3 (P1) — accepted; a naming collision, not a maths error

`factor_exposure.model_observation_count = 174` is provably not the regression
sample: `1−(1−0.6511)(n−1)/(n−2)` reproduces the published
`adj_r_squared = 0.6490` only for n ∈ [165,172] (n=174 gives 0.6491). The true
count (167) sits three keys away in the same block, and the sibling `risk_score`
publishes the same field name with the correct unit. So the field is
mis-named/mis-valued, and two sections use one name for two different units —
the exact class of defect this whole exercise exists to eliminate.

## PA-4 (P1) — accepted; two irreconcilable Sharpes

`summary.sharpe_ratio = 3.4856` vs `tear_sheet.metrics.sharpe = 3.4876`, same
39-obs window, same `annualized` flag, volatility agreeing to 1e-7. Unreconcilable
from the artifact because `tear_sheet.metrics` publishes **no risk-free rate**, so
a reader cannot tell whether the two differ by a risk-free assumption or by a bug.
