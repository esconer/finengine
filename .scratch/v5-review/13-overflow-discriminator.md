# 13 — Overflow discriminator: a structural test for the EGARCH simulation divergence

**Mission:** find a *structural* discriminator separating the EGARCH
`horizon > 1` simulation divergence from a genuinely extreme volatility
forecast, because a magnitude threshold has already been measured and shown to
be arbitrary. Two implementers declined to pick one; correctly.

**Verdict: NO STRUCTURAL DISCRIMINATOR EXISTS.** Established by measurement on
5,185 real EGARCH(1,1) fits, not by argument. Every derivation-based predicate
fails in both directions, and the only quantities that separate the two sets
in-sample are magnitudes whose separation does not survive a hold-out split.

**Reachability is higher than the deferral assumed.** On the real 14-position
book, `model=EGARCH&horizon=3` at the real leg length produces **0 divergent
point estimates in 15 legs + 1 index**, but **156 of 2,993 published
restatements (5.2%) land exactly on the clip bound, on 15 of 15 legs**, and four
of those legs carry restatements whose true raw value is between 1e6 and 1e54.

All scratch scripts live outside the repo, in
`C:\Users\Sayanti\AppData\Local\Temp\opencode\` (`od06`…`od15`).

---

## 1. What was measured, and on what

| population | n | what it is |
|---|---|---|
| P1 | 1,000 | the finding's own circular moving-block resample set for EGARCH h=3, reproduced from `UNCERTAINTY_BOOTSTRAP_RESAMPLES/SEED` and the test's `_returns(60, seed=3, rho=0.35)` |
| P2 | 3,000 | prefixes of the same draws at 20/25/31/35/41/50 observations (the degenerate regime) |
| P3 | 630 | **the real 14-position book** + `^NSEI`, taken from a copy of `backend/data/daisy.db` `stock_timeseries` (15 tickers, 2,487 rows each): the 175-observation window the route sees, the full history, and 40 moving-block resamples per leg |
| P4 | 480 | synthetic GARCH(1,1) returns at 1.0–4.5 % daily vol, β ∈ {0.90, 0.97, 0.99} — the "genuinely extreme but real" false-positive population |
| P5 | 75 | **real** book returns truncated to 20/22/25/30/40 observations — the "≈22 return rows per leg" scenario the mission hypothesised |

Every fit was measured exactly as `volatility_forecast_point` builds it:
`arch_model(x*100, vol="EGARCH", p=1, q=1, dist="normal", rescale=False)`,
`method="simulation"`, `simulations=2000`, `rng=dist(seed=100).simulate([])`,
h=3 (and h=21 for the horizon-growth test). Total 5,185 fits, 303 s.

**The finding's continuum reproduces.** Raw annualized values over P1:
`785 < 0.5, 79 in [0.5,1.2), 33 in [1.2,2), 39 in [2,10), 32 in [10,1e3),
5 in [1e3,1e9), 9 above 1e9` — against the recorded `785 / 34 / 39 / 31 / 16`.
The two differ only by 18 draws, which the recorded figures attribute to the
18 draws the engine already refuses as non-finite (measured: exactly 18).

**One mechanism fact that reframes the whole question.** `arch` 8.0.0
`volatility.py:2841` returns `VarianceForecast(paths.mean(1), paths, shocks)`:
**`fc.variance.values` is already the ensemble mean**, shape `(1, horizon)`.
`ARCHModelForecastResult` publishes only `mean / residual_variance /
simulations / variance`; the 2,000 individual draws exist solely on
`vfcast.forecast_paths`, which `mean.py:1038-1054` consumes and discards. So
`AnalyticsEngine._forecast_variance_path` is handed the mean, and the gate at
`analytics_engine.py:6182` (`not np.isfinite(variance_path).all()`) tests the
**mean**, never a draw. The ensemble is available and never inspected.

---

## 2. The discriminator scan

For every candidate, the question asked is the strongest possible form of "is
this a discriminator":

> Is there **any** threshold on this quantity at which the divergent set and
> the real set do not overlap?

Non-separability is cut-independent: the "best cut" row is the minimum
misclassification count achievable by *any* threshold on that quantity. If it is
> 0, the quantity separates; otherwise it cannot, ever, at any cut.

Scored set: 5,040 real fits (raw < 1e3) vs 61 divergent fits (raw ≥ 1e3).
The 84 fits the engine already refuses (non-finite mean) are excluded — the
gate exists and works.

```
candidate                          separable?   min errors  best cut   overlap band
abs_beta                           no                 61      1          real [0,1]  ∩ div [8.8e-17,1]
one_minus_beta                     no                 61      1          real [0,1]  ∩ div [0,1]
alpha                              no                 60      9.038      real [-9.36,9.038] ∩ div [-8.31,9.31]
gamma                              no                 31      7.473      real [-349,7.47] ∩ div [-564,176]
|gamma|                            no                  7      7.473      real [0.0013,349] ∩ div [0.33,564]
omega                              no                 59      -85.8      real [-85.8,1.34e4] ∩ div [-3223,1799]
|omega|                            no                 43      4.23       ...
sigma_d2 (derived)                 no                  8      55.9       real [2.1e-6,1.22e5] ∩ div [31.6,3.18e5]
lognormal_correction_log (derived) no                 54      3.73e15    real [1.1e-4,3.7e15] ∩ div [36.2,2.9e17]
unconditional_lnvar (derived)      no                 58      6.76e15    real [-6.7e15,6.8e15] ∩ div [-1.2e15,2.6e16]
mean_reversion_horizon (derived)   no                 60      9.0e15     real [1,9.0e15] ∩ div [1,4.5e15]
implied_ln_E_sigma2 (derived)      no                 54      6.76e15    ...
lnvar_gap (derived)                no                 38      26.7       real [-741.8,26.7] ∩ div [-89.6,219.5]
|lnvar_gap| (derived)              no                 61      3.6e-5     ...
ln_gap_over_implied (derived)      no                 60      22927      ...
insample_lnvar_range               no                 59      28.07      real [0.018,28.07] ∩ div [4.71,28.29]
insample_lnvar_slope_per_step      no                 61      0.294      ...
insample_lnvar_last                no                 52      14.05      real [-14.5,14.1] ∩ div [-13.7,19.7]
sim_nonfinite                      no                 61      0          real [0,0] ∩ div [0,0]
sim_frac_nonfinite                 no                 61      0          ...
sim_mean_over_median               no                  4      3.09e5     real [0.98,2.8e7] ∩ div [1.01,3.1e219]
sim_max_over_mean                  no                 21      839.8      ...
sim_median_last                    no                 28      9.75e6     ...
sim_q99_last                       no                  3      2.25e8     real [0,2.25e8] ∩ div [4.9e7,7.4e191]
sim_q999_last                      ABOVE                0      5.20e8     real ≤5.20e8 < div 9.74e9
sim_frac_over_1e15                no                  7      0          real [0,0] ∩ div [0,1]
horizon_growth (h21/h3)            no                 57      0.378      real [0.38,1.1e161] ∩ div [0.38,3.0e92]
convergence_flag                   no                 61      9          real [0,9] ∩ div [0,9]
loglikelihood                      no                 61      -6.13      ...
loglikelihood / obs                no                 60      -3         ...
std / max_abs / resid_std / resid_max_abs / n   no    61      --         ...
sim_max_finite                     ABOVE                0      2.31e10    real ≤2.31e10 < div 1.35e11
raw_volatility_forecast            ABOVE                0      711.6      real ≤711.6 < div 1003
return_space_volatility            ABOVE                0      77.6       real ≤77.6 < div 109.4
```

**30 of 30 absolute-value and signed forms are non-separable.** The four
in-sample separators are all *magnitudes of the published number or of its
largest draw*.

### And those four do not survive a hold-out

Split the 61 divergent fits in half at random 400 times; take the only
zero-false-positive cut available on half A (the minimum of A); score on half B
plus all 5,040 real fits.

```
candidate          full-sample gap      out-of-sample errors (median / p90 / max)   P(0 errors)
sim_max_finite           5.84x            1 / 3 / 10                                 0.497
sim_q999_last           18.7x             0 / 3 / 7                                  0.515
raw_vol                  1.41x            0 / 3 / 8                                  0.505
return_space_vol         1.41x            1 / 3 / 7                                  0.480
```

A coin flip. **The full-sample "gap" is an artefact of fitting one cut to 61
samples** — including for `raw_volatility_forecast` itself, whose full-sample gap
is only 1.41x. Two-sided forms fail harder still: choosing the cut on half of
`|gamma|` gives a median of **3,955** errors on the other half
(P(0 errors) = 0.000).

This is the mission's own premise, now measured rather than assumed: **there is
no gap, and the apparent gap is not a gap.**

### The derivation-based predicates, scored

Four predicates whose threshold comes from a derivation rather than a choice:

| # | predicate | derivation of the threshold | FP / real | FN / divergent |
|---|---|---|---|---|
| P1 | `abs(beta) >= 1` | the exact covariance-stationarity boundary of the EGARCH(1,1) log-variance recursion `l_t = ω + β l_{t-1} + α(\|z\|−√(2/π)) + γz` | **164 / 5040 (3.3 %)** | **60 / 61 (98.4 %)** |
| P2 | any non-finite member of the 2,000-path ensemble | none needed — it is the check the engine already performs, one level earlier | 0 / 5040 (0 %) | 61 / 61 (100 %) |
| P3 | `σ_d²/2 > ln(DBL_MAX)`, `σ_d² ≡ α²(1−2/π) + γ²` | `ln(DBL_MAX) = 709.7827` is the exact point `np.exp` saturates in IEEE-754 double | 2 / 5040 (0.04 %) | 31 / 61 (50.8 %) |
| P4 | `ω/(1−β) + σ_d²/(2(1−β²)) > ln(DBL_MAX)` — the model-implied `ln E[σ²]` | as above; `σ²` is lognormal(ω/(1−β), σ_d²/(1−β²)) | 300 / 5040 (6.0 %) | 13 / 61 (21.3 %) |
| — | *baseline* `raw > ln(DBL_MAX)` (a magnitude) | — | 1 / 5040 | 0 / 61 |

P4 is the best principled candidate and it is the one the mission's framing
implies. It still **wrongly refuses 6.0 % of genuine forecasts and misses
21.3 % of the divergences.** On the finding's own 1,000-draw publication set:
FP = 41/968, FN = 7/14.

**The exact predicate P1 is the worst of the four.** Measured reason: the
divergent fits' median `|β|` is **0.798** and one has `|β| = 8.8e-17`; the
pinned draw has `β = 0.99999999996`, and the draw the engine *already* refuses
(draw 27) has `β = 0.915 < 1`. **The explosion is not persistence — it is the
leverage term γ.** Of the 61 divergent fits, 41 have a `convergence_flag != 0`
(67.2 %) against 28.1 % of everything else, so `arch` *does* expose a signal and
the engine ignores it — but a `flag != 0` gate refuses 1,414 of 5,040 real fits
and still misses 20 of 61.

The five largest divergences P4 misses, showing why:

```
raw=6.15e+83  |b|=0.751  a=+0.221  g=+13.02   sigma_d2=169.6   implied_lnE_inf=186.9
raw=1.03e+19  |b|=0.893  a=-0.174  g=+29.89   sigma_d2=893.4   implied_lnE_inf=-625.7
raw=2.55e+14  |b|=0.507  a=+1.293  g=+25.63   sigma_d2=657.4   implied_lnE_inf=441.6
raw=3.87e+09  |b|=0.797  a=+5.665  g=-15.93   sigma_d2=265.4   implied_lnE_inf=454.7
raw=4.82e+07  |b|=0.751  a=-0.167  g=+12.46   sigma_d2=155.3   implied_lnE_inf=-12750
```

All five have `|β| < 0.9`, a *finite* model-implied `E[σ²]`, and a `γ` inside the
range spanned by ordinary real fits (`γ` reaches −349 among the 5,040 real
fits). They diverge because the **fitted level** is already absurd, not because
the fitted parameters are outside a stationarity region.

---

## 3. Why: the divergence is the model's own continuum, and it is two-sided

For a stationary EGARCH(1,1) with normal innovations, `σ²` is
`lognormal(ω/(1−β), σ_d²/(1−β²))`. `|β| < 1` is sufficient for that
distribution to exist — and its mean `exp(μ + σ_d²/(2(1−β²)))` is then a
**finite real number for every finite `μ`, `σ_d²`, and `1−β² > 0`.** There is no
`β < 1` and no parameter set that makes the model assert a nonexistent forecast;
`β → 1⁻` makes it assert an arbitrarily large one, continuously. The continuum
the mission documented is not an artefact of the engine's clip. **It is the
model class.**

Measured corroboration — the same degenerate-fit family produces a *collapse*
as well as an explosion, and nothing catches that either:

```
raw <= 1e-12 :  848 / 5101 finite-raw fits (16.6 %)
raw <= 1e-9  :  884 / 5101 (17.3 %)
raw >= 1e3   :   61 / 5101 ( 1.2 %)
```

`EGARCH_VOL_CLIP_LOW = 0.0`, so a fit that collapses publishes
`volatility_forecast = 2.0e-27`. Measured on the real book: **NTPC.NS at
h=3 EGARCH publishes `volatility_forecast = 1.9998e-27` while the same series
under GARCH publishes 0.1435.** `lnvar_gap` (the departure of the median
forecast's log-variance from the last observed level) separates
{normal, collapse} from most of {explode} — collapse max `−24.91`, normal max
`16.26`, explode `[−89.62, 219.5]` — but the explode set has members in the
collapse band, so the two-sided `|lnvar_gap|` still has 61 minimum errors.

---

## 4. Reachability, measured on the real book

Real legs from `stock_timeseries`: 14 book tickers + `^NSEI`, 2,487 price rows
each. The artifact's published `return_observations` are 103–175 (mean 166.9);
the portfolio leg has 101.

**Point estimates, at the length the route actually uses (175 returns):**

```
P3_real_win175   n= 15   ordinary 15   extreme 0   divergent 0   refused 0   max raw 0.4798
P3_real_full     n= 15   ordinary 15   extreme 0   divergent 0   refused 0   max raw 0.5106
```

Every leg lands between 0.13 and 0.48 annualized, against a clip bound of 1.20.
`GET /forecast-risk?model=EGARCH&horizon=3` on this book publishes **no
divergent headline figure**. The deferral's premise holds for the headline.

**But the precision band is contaminated, on every leg.** Measured through the
engine's own `volatility_forecast_point`, on the engine's own circular
moving-block rule with 200 draws per leg, h=3, EGARCH:

```
leg             n   point    p50     p95     max   raw p95    raw max   on clip  refused
CIPLA.NS      175   0.1630  0.2048  0.8962  1.2000    0.8962   1.872e+13     9        2
ELECTCAST.NS  175   0.4295  0.5074  1.1179  1.2000    1.125       7.19       10        1
MOTILALOFS.NS 175   0.3726  0.3833  0.9700  1.2000     0.970       4.891       9        0
ARROWGREEN.NS 175   0.4798  0.5004  1.2000  1.2000     1.230        127.4      11        0
JKIL.NS       175   0.3304  0.2930  0.4785  1.2000     0.4785       20.37       3        0
NTPC.NS       175   0.0000  0.1958  1.2000  1.2000     1.885        140.2      17        0
MCX.NS        175   0.3781  0.3903  0.5210  1.2000     0.521       6.042       2        1
MOTHERSON.NS  175   0.2916  0.3632  1.2000  1.2000     4.359    6.296e+54      29        1
REDINGTON.NS  175   0.4068  0.4552  1.2000  1.2000     2.185    1.255e+16      16        0
NIFTYIETF.NS  175   0.1338  0.1312  0.2058  1.2000     0.2058       23.6       4        1
MIDCAPIETF.NS 175   0.1765  0.1693  0.2795  1.2000     0.2795       14.03       7        0
JUNIORBEES.NS 175   0.1861  0.1749  0.7322  1.2000     0.7322       36.95       9        0
MAFANG.NS     175   0.2744  0.2766  0.4424  1.2000     0.4424    3.744e+10       9        0
SELECTIPO.NS  175   0.2226  0.1916  1.2000  1.2000     4.270    2.087e+06      16        1
^NSEI         175   0.1280  0.1438  0.4581  1.2000     0.4581       121.9       5        0

TOTAL 2993 usable restatements: 156 (5.2 %) publish exactly 1.20; 7 (0.23 %) refused
```

- **15 of 15 legs** have at least one restatement that publishes exactly the
  clip bound.
- **5 of 15 legs** have a published 95th percentile sitting exactly on 1.20
  (ARROWGREEN, NTPC, MOTHERSON, REDINGTON, SELECTIPO) — the band's upper end is
  the bound, so the band carries no information about where the estimator is.
- **4 legs** carry restatements whose true raw value is 1e6–1e54, i.e. exactly
  the defect, entering the artifact as 1.20.
- Only **7 / 3000 = 0.23 %** are refused as non-finite.

**Short legs, the hypothesised scenario.** Real returns truncated to 20–40
observations, all 15 tickers × 5 lengths = 75 fits: 53 ordinary, 21 extreme
(raw 1.2–1e3, 28 %), **1 divergent (1.3 %, ELECTCAST.NS at 30 obs, raw
8.6e22)**, 0 non-finite. By length: 20 → 0/15, 22 → 0/15, 25 → 0/15,
**30 → 1/15**, 40 → 0/15. So a 22-observation leg does **not** hit it; 30 does
once in fifteen.

Rule of three on the 0/15 as-is result: 95 % upper bound 3/15 = 20 % per leg
request. The tighter statement is the direct one: the largest raw on the real
window is **0.4798** against a bound of **1.20**, a factor of 2.5 of headroom
on every leg.

---

## 5. The honest alternative: stop hiding it

The mission's fallback — *"publish the raw value beside the clipped one and
refuse the clip entirely"* — is the right answer, with three measured
qualifications.

**In favour.**

1. The route already drops `raw_volatility_forecast` entirely. `analytics.py`
   forwards `volatility_forecast` and `var_forecast` per leg (5759–5766) and
   `volatility_forecast` + `tail_measure.return_space_volatility` for the
   portfolio (4745–4748). **`raw_volatility_forecast` is never published**, so a
   reader has no way to tell a clipped 1.20 from a real one on a leg, and no
   way to see that a 1.20 is sitting on a bound. The `precision` block's
   `derivation_precondition` machinery (5160–5194) already exists to publish
   exactly this kind of "the clip is active here" fact — it is wired to
   `volatility_forecast` and would work unchanged on a raw field.
2. Refusing the clip is the only option that cannot be wrong. It moves no draw
   by an invented amount, because it moves them by their own value.
3. It costs the artifact nothing: the export runs GARCH/analytic at h=1
   (measured: `model_params.forecast_method == "analytic"`, and the analytic
   recursion never exponentiates a simulated path), so no default-export number
   moves.

**Against, and the size of it.** A magnitude gate would move 14 of 118
clip-active P1 draws (11.9 %), 2 of 33 on real-book resamples (6.1 %), 1 of 22
on short real legs (4.5 %), and 3 of 433 on the genuinely-extreme synthetic
population (0.7 %). **Refusing the clip moves all of them**, including the 104
P1 draws, 31 real-book draws and 430 synthetic draws that are *genuine*
extreme-but-real forecasts. That is the trade: a gate mis-states ~12 % of
clip-active draws by an invented amount; removing the clip states 100 % of them
correctly and asks the reader to see that 34,200 % annualized volatility is
absurd. On a payload whose stated purpose is machine-readability, the second is
worse for a consumer and better for a reader.

**Recommended shape — detect nothing, disclose everything:**

- Keep the clip. It is doing what it was written to do, and 88–99 % of the
  draws it binds are real extreme forecasts.
- **Publish `raw_volatility_forecast` on every leg and on the portfolio**, and
  publish `volatility_forecast_at_clip_bound: true/false` beside it, mirroring
  the existing `derivation_precondition_met` pattern. That is the whole fix for
  the disclosure defect: the headline still reads 1.20, but the block now says
  the raw is 2.2e34 and that the bound is active.
- **Publish the number of restatements that landed on the clip bound** on the
  precision block, with the count. 5.2 % measured. A band whose 95th percentile
  is the bound should say so in a number, not leave the reader to notice.
- Add **one** new key, `volatility_forecast_clipped` (bool), or reuse the
  existing `annualized_volatility_at_clip_bound` wording from 5190–5194 for
  consistency. No key is needed for the divergence case specifically — that is
  the point.

**One change that is not a magnitude gate and should be made anyway:** the
collapse side. `EGARCH_VOL_CLIP_LOW = 0.0` lets a fit publish
`volatility_forecast = 1.9998e-27` (measured, NTPC.NS, EGARCH h=3, same series
under GARCH = 0.1435). 884 of 5,101 finite-raw fits (17.3 %) publish a raw ≤ 1e-9
and none of them is caught. That is a *different* number from the one this
mission is about, and it is larger in count.

---

## 6. Where the fix belongs

**Engine, not route — but only the gate, not a discriminator.**
`volatility_forecast_point` is the single source of truth for the point and is
re-run by `volatility_forecast_statistics` (`analytics_engine.py:6259–6297`), so
any check added there automatically applies to both the headline and the band.
That is the property the resampling restatement was built to have and the
reason the two cannot drift.

The one engine change with a derivation and no free constant: **apply the
finiteness gate to arch's own ensemble rather than to its mean.** P2 above
scores FP 0 / 5040 and FN 61 / 61 — it cannot misclassify a real fit, and it
catches 100 % of the already-refused set *earlier and more honestly* (the
reason becomes "a member of the forecast distribution is not representable"
rather than "the mean is not finite"). It does **not** fix the finding, and it
must not be presented as doing so. It requires wrapping
`EGARCH._simulation_forecast` to reach `forecast_paths`, which arch does not
expose.

**Route, for the disclosure.** `raw_volatility_forecast` is dropped at
`analytics.py:5759–5766` and `4745–4748`; that is where the raw has to be
forwarded. The `precision` block already has the vocabulary
(`derivation_precondition`, `derivation_precondition_met`,
`derivation_precondition_evidence`) and the 5190–5194 text already says
"annualized_volatility_at_clip_bound is …" — the block was written for a field
the route does not publish.

---

## 7. What I could not determine

- **Whether the 4 in-sample separators would separate on a different book.** The
  hold-out says their full-sample separation is not real *on this population*;
  that is not the same as proving they could never work on a larger, cleaner
  divergence set. A population with 1,000+ divergent fits rather than 61 would
  settle it. I could not construct one: generating divergent fits requires
  moving-block resampling or short degenerate prefixes, both of which also
  generate the real extreme fits, which is the finding itself.
- **Whether a discriminator exists that is not a function of the fitted
  parameters and not a magnitude** — e.g. one computed from the *in-sample
  residual* recursion's own properties (autocorrelation of `|resid|`, the
  number of distinct values, a Kolmogorov–Smirnov against the fitted innovation
  law). I did not test residual-distribution shape. It is the only family of
  structural signal in the list that I left unmeasured, and it is the one place
  a genuine answer would have to live.
- **Whether the `gamma` term's *sign consistency* with the leverage pattern
  matters** (EGARCH's usual `γ < 0` constraint). Not tested.
- **`β_bse` is absent from every fit** — `fitted.bse` did not populate, so the
  "is the near-unit root identified by n observations" test could not be run.
  The half-life-over-n ratio is reported as a quantity but carries no standard
  error, so it could not be scored.
