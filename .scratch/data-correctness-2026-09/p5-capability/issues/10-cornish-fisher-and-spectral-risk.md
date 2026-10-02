# 10 — Cornish-Fisher modified VaR and spectral risk measures

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: —
Repo: `backend/`
Effort: S | Score: 24

## What

`CONTEXT.md` §9.11 pins analytical VaR to the Gaussian form:

```
VaR_h = − σ_ann × 1.645 × √(h/252)
CVaR_h = − σ_ann × 2.06 × √(h/252)
```

That is a **normal** assumption. The app's own EVT page already proves the returns are fat-tailed —
so the parametric leg is carrying a distributional assumption the same codebase has already
disproven.

Add the shape correction, plus the spectral family.

## Cornish-Fisher

```
q_α = σ · [ z + (γ/6)(z²−1) + (κ/24)·z(z²−3) − (γ²/36)·z(2z²−5) ]
```

where `z` is the standard normal quantile, `γ` skewness, `κ` excess kurtosis.

**This is not an academic exercise — it is a regulatory method.** ESMA PRIIPs Annex 1 prescribes the
Cornish-Fisher expansion as **the retail VaR method** for PRIIPs KID documents. That is about as
strong an endorsement as exists for a retail-facing risk tool.

Also add spectral measures: EVaR (entropic), EDaR, GMD, TG. Riskfolio-Lib and skfolio both carry
the set.

## Why

A Gaussian VaR on fat-tailed Indian small-cap returns **understates tail risk systematically** —
which is the same failure the EVT page was built to address, but only for the non-parametric leg.
The parametric leg is what feeds the forecast-risk page's headline numbers and the risk-budget
limits in issue 06.

Cornish-Fisher is a cheap correction: it uses skewness and kurtosis, both of which the app can
compute, and it costs about ten lines.

## Change

- Implement the CF expansion with skewness and kurtosis from the observed returns.
- Publish **both** the Gaussian and the CF VaR, with the skewness and kurtosis that produced the
  correction. The difference between them is informative: a large gap means the Gaussian
  assumption is doing real damage.
- Add EVaR/EDaR/GMD/TG to the risk-measure set, with units and the risk-aversion parameter where
  one is needed (EVaR needs `λ`).
- Return `None` with a reason when skewness or kurtosis cannot be estimated reliably.

## Proof of done

- [ ] The CF expansion is validated against a **closed-form reference** and against ESMA's worked
      example.
- [ ] For a symmetric mesokurtic distribution, CF VaR reduces to the Gaussian value. A test
      asserts this — it is the control case.
- [ ] CF VaR > Gaussian VaR for right-skewed input. A test constructs such a series and asserts
      the direction.
- [ ] Skewness and kurtosis are published alongside the corrected VaR.
- [ ] Both the Gaussian and CF figures are shown, so the user can see the magnitude of the
      correction.
- [ ] EVaR is `>=` ES `>=` VaR for a loss distribution. A test asserts the ordering.
- [ ] EVaR's risk-aversion parameter `λ` is documented and configurable.
- [ ] Insufficient data for skew/kurtosis returns `None` with a reason.

## Notes

For the corrected CF expansion (the original has known small-sample issues), see Maillard (2018),
*"A User's Guide to the Cornish Fisher Expansion"*.

Do not **replace** the Gaussian VaR — publish both. The Gaussian figure is what most readers
expect, and showing the delta between the two is more informative than either alone. A large delta
on an Indian small-cap book would itself be a finding.

Refs: `../spec.md`, `CONTEXT.md` §9.11, Phase 5 issue 01, Phase 5 issue 06
