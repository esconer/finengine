# 15 — Factor breadth: sector-relative loadings and style factors

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: 07
Repo: `backend/`
Effort: L | Score: 32

## What

Factor exposure is currently a **single-factor CAPM OLS**. The response is literally
`{alpha, market}` plus R². "You are a tech-beta book, R²=0.31" is one number.

Extend to:

1. **Sector-relative betas** — each holding's excess return regressed on `^NSEI` **plus** its
   sector index return.
2. **Style factors** — size, value, momentum, low-vol.

## The critical design constraint: time-series form, NOT Barra

**Do not attempt a cross-sectional Barra model.** Barra estimates factor returns from **daily
cross-sectional regressions across thousands of names**. With 10–20 holdings:

- There is no cross-section. "Country factor" is degenerate — it is 1 for everything.
- Size and value have essentially no cross-sectional variance to estimate against.
- 6 factors on 20 observations is **unidentified**.

A model reporting six factors on twenty holdings with no diagnostics is textbook fake precision,
and it would be a genuine regression in a product whose entire value proposition is analytical
credibility.

**Do** the time-series form: regress each holding's excess return on `^NSEI` + sector index returns
over 2–3 years. Same answer, ~20 lines, defensible.

## Why

One factor explains a small fraction of a typical Indian portfolio's variance. Knowing whether the
residual 70% is sector-driven, style-driven, or genuinely stock-specific is the difference between
"reduce your beta" and "your IT allocation is the problem".

Style factors should be built as **return-based factor-mimicking portfolios** from data the app can
source, or from bfinance's fundamental columns. Kenneth French's Data Library publishes
**Emerging Market** factors (SMB / HML / DMS / CMA / Mom), which are the correct priors for an
Indian book — a US factor set would misprice an Indian portfolio.

## Change

- Multi-factor OLS per holding: `r_i − r_f = α + β_m·r_m + Σ β_s·r_sector + ε`.
- Publish every loading **with** its R², standard error, t-statistic, and observation count. A
  loading without a t-statistic is not a finding.
- Style factors as factor-mimicking portfolios, or from French EM factors.
- Aggregate to portfolio factor exposure, and feed issue 04's specific-risk decomposition properly
  (residual variance becomes specific risk with more than one factor).
- Report the **incremental** R² from each additional factor, so the user can see which factors earn
  their place.
- Refuse to fit when observations are insufficient for the factor count. A 6-factor model on 30
  observations must not produce six loadings.

## Proof of done

- [ ] Each loading is published with R², standard error, t-statistic, and observation count.
- [ ] The model **refuses to fit** when observations < some multiple of the factor count, with a
      reason. A test forces this — it is the anti-fake-precision guard.
- [ ] Incremental R² per factor is reported, so a useless factor is visibly useless.
- [ ] A synthetic series generated from a known multi-factor model recovers the true loadings within
      tolerance. This is the key correctness test.
- [ ] Sector-relative betas match a direct two-factor regression on constructed data.
- [ ] Specific risk from issue 04 is consistent with the multi-factor residual variance.
- [ ] Style factors are documented, including their construction and whether they are French EM or
      locally built. A factor whose construction is not documented is not usable.
- [ ] The response states plainly that this is a **time-series factor model**, not a Barra model.

## Notes

The single most important acceptance criterion is the **refusal to fit** when observations are
insufficient. That one behaviour is what separates this from fake precision, and it is cheap to
implement given the `min_observations_required` pattern the app already uses on `forecast-risk`.

Also: publish the **incremental** R². Six factors that collectively add 0.02 to R² over the market
factor are noise, and the user should be able to see that without doing the arithmetic.

Refs: `../spec.md`, Phase 5 issues 04, 07, `CONTEXT.md` §9.12
