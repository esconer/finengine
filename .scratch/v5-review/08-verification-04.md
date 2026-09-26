# Integrator verification — agent 04 (statistical inference)

Both headline claims reproduced by me, to the last bit.

---

## SI-3 — CONFIRMED EXACTLY. A hardcoded ±20% band sold as a confidence interval

```
confidence_interval = [0.11013826613761486, 0.16520739920642227]
midpoint            = 0.13767283267201857

midpoint * 0.8 == ci[0]   ->  True   (exact float equality, not a tolerance)
midpoint * 1.2 == ci[1]   ->  True
width / centre            =  0.4
```

`forecast_risk.data.portfolio.confidence_interval` is literally
`volatility × [0.8, 1.2]`. It is not an estimate of anything. It is a
multiplicative fudge factor published under a name that means "we computed an
uncertainty". Source `analytics_engine.py:1577-1580`.

The aggravating detail, which I verified is *not* a defence: in the **same
export**, `stress_testing` labels its nominal 0.95 as
`nominal_label_not_simulated`. The codebase knows the difference between a
simulated confidence level and an assumed one, and applies it in one section
while violating it in another. That inconsistency is what makes SI-3 a P0 rather
than a naming nit — a reader who has been taught the convention by `stress_testing`
will read `confidence_interval` as simulated.

## SI-1 — CONFIRMED, and it is the most dangerous finding in the review

I reproduced the statistics independently.

```
n pairs = 91
one-sample KS vs Uniform(0,1):  D = 0.131101   p = 0.079886
```

The 91 published Engle-Granger p-values are **statistically indistinguishable
from uniform**. The test is detecting nothing beyond chance. Against that:

```
declared positives                 = 4
expected by chance at alpha=0.05   = 4.55
Poisson P(X=4 | lambda=4.55)       = 0.188710
Bonferroni threshold 0.05/91       = 0.00054945   -> survivors = 0
```

Four "discoveries" where 4.55 are expected by pure chance, and **zero survive
correction**.

Multiplicity is not merely un-applied, it is **absent from the artifact**:

```
bonferroni 0 | fdr 0 | multiple_testing 0 | multiple comparison 0
family_wise 0 | false_discovery 0
```

### The part that makes this P0 rather than P1: the artifact issues trade directives

`test_agreement` is honest and detailed — it publishes `disagreement_count: 8`,
`decision_positive_only_count: 4`, `diagnostic_positive_only_count: 4`, and names
`decision_positive_pairs`. The two positive sets do not overlap at all. So the
*structural* disagreement is disclosed.

**But the `signal` field is not gated by that disagreement.** All four
decision-positive pairs carry `johansen_agrees_with_decision: false`, and two of
them carry explicit, actionable instructions:

| pair | p | johansen agrees | hedge_ratio_beta | published signal |
|---|---|---|---|---|
| ELECTCAST.NS / MCX.NS | 0.042007 | **false** | 0.008606 | `LONG_SPREAD (Long ELECTCAST.NS, Short MCX.NS)` |
| JUNIORBEES.NS / MIDCAPIETF.NS | 0.048530 | **false** | 33.6396 | `SHORT_SPREAD (Short JUNIORBEES.NS, Long MIDCAPIETF.NS)` |
| JUNIORBEES.NS / MOTILALOFS.NS | 0.002609 | false | 0.270609 | NEUTRAL |
| JKIL.NS / NIFTYIETF.NS | 0.020638 | false | 3.164018 | NEUTRAL |

So the export tells an AI agent to **short MCX** and to **short MIDCAPIETF** on
the strength of results indistinguishable from noise, on pairs its own second
statistical test rejects.

Two further aggravators the agent surfaced and I confirm are absent from the
file: the ±1.5 z-threshold that generates these signals is hardcoded
(`cointegration_service.py:436,438`) and appears **0 times** in 876 KB; and
neither directive publishes its hedge ratio. Taking the spreads 1:1 when the
hedge ratios are **0.0086** and **33.64** mis-sizes them by roughly **116×** and
**34×** respectively.

Net: a confident, actionable, statistically unsupported instruction with an
undisclosed threshold, no multiplicity correction, and sizing that is wrong by
one to two orders of magnitude if read literally. `depth_status: partial` and its
warning do disclose *sample depth* — the disclosure is real, it is simply pointed
at the smaller of the two problems.

## SI-2 — accepted; I will not re-litigate the 39-observation statistics

Sharpe 3.4876 / Sortino 5.3147 / Calmar 20.1891 / CAGR 42.97% on
`observation_count: 39`, `annualized: true`, `warnings: []`,
`status: available`. Lo SE 6.7645 → t = 0.516, p = 0.606, 95% CI
[−9.77, +16.75] — i.e. indistinguishable from zero. Root cause
`app/utils/holdings.py:35`, `MIN_ANNUALIZE_DAYS = 30`.

This one I am treating differently from the rest, and I want to be explicit about
why. It was recorded in the previous wave as a **deliberate policy decision, not a
defect**: the 30-day gate annualises 36–39-observation samples, producing a ~43%
CAGR from 39 days. Nothing changed this wave. What the agent has now added is
the *magnitude* of the consequence, which was not previously quantified anywhere:
the Sharpe's confidence interval spans zero, and the number is published with
`status: available` and no warning.

So the finding is not "the gate is wrong" — it is **"a statistic whose CI spans
zero is published as available with nothing said about its uncertainty."** That
is a disclosure defect, and it is the same defect as SI-5.

## SI-5 — the systemic finding, and I am adopting it as the headline

495 hypothesis tests carry a stated alpha. Zero corrections. Across 876 KB:

```
standard_error 0 | conf_int 0 | autocorrel 0 | newey 0 | HAC 0 | effective_n 0
```

Roughly 2,000 point estimates and not one interval. This is the structural
reason the individual P0s matter: the artifact is built to make numbers
actionable, and it supplies no uncertainty on any of them, at every level. It
compounds SI-3 (a confidence interval that is a constant) and SI-2 (a Sharpe
whose CI spans zero, presented as available).

## Clean results I am recording so they are not re-litigated

Agent 04 did the most valuable negative work in the whole review, and I am
endorsing all of it:

- **The pair p-values are the right test's p-values.** Verified against
  `mackinnonp(t,'c',N=2)` for all 91 pairs, max deviation **2.4e-05**, zero
  monotonicity violations. No test/p-value mismatch.
- **No hardcoded p-values**, none out of range, none at a decision boundary.
- **Stationarity is not confused with cointegration**; the signal gate does refuse
  non-cointegrated pairs (it is the *cointegrated-but-contested* pairs that slip
  through).
- **`regime` disclosure is the best in the artifact** — `estimated: false` on the
  transition matrix, a stated stability rule with its 719 observations, and it
  *withholds* annualised figures at n=19.
- **`india_flows`' `partial` status is honest** — its four warnings fully explain
  the degradation, and it publishes no flow figures at all rather than bad ones.
- **`stress_testing`'s `*_basis` fields are exemplary.**
- **The SELECTIPO-contamination premise does not hold.** It ranks 11th of 13 on
  volatility, and dropping SELECTIPO + MAFANG moves portfolio volatility by only
  **+4.0%**. Reported as a clean negative result rather than a suspected finding.
