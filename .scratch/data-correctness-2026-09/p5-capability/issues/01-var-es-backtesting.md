# 01 — VaR and ES backtesting

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: —
Repo: `backend/`
Effort: S | Score: 45 — **best value-per-hour in the entire backlog**
Reference: Basel traffic light, Kupiec POF, Christoffersen independence

## What

The app computes VaR and Expected Shortfall from **three different engines** — Gaussian, Student-t,
and EVT-POT — and validates **none** of them. There is no hit rate, no Kupiec p-value, no traffic
light, and no exceptions timeline.

Add all four.

## Why

A pro-grade terminal's first obligation when it publishes a 99% ES is to tell you **how often it
was wrong**. The app publishes a number with unbounded confidence.

This is the cheapest credibility upgrade available:

- The return series already exists.
- The VaR functions already exist.
- The tests are closed-form.

It is the difference between a metrics app and a risk system. The verdict it produces is worth
more than three more analytics pages:

> *"EVT-POT ES breached 4 times in 250 days; Gaussian VaR breached 11 times (Yellow zone,
> k=3.50) — the fat-tail engine is the one to trust."*

## What to build

### 1. Exceptions timeline

Per-day hit/miss against each engine, with the breach ratio on a miss. This is the most
interpretable output and the most useful for a single user.

### 2. Kupiec POF (unconditional coverage)

`LR_uc = -2 ln( [ (1-α)^(n-x) α^x ] / [ (1-α̂)^(n-x) α̂^x ] )`, asymptotically χ²(1).

### 3. Christoffersen independence

`LR_ind` on the sequence of hits. Then:

### 4. Conditional coverage

`LR_cc = LR_uc + LR_ind ~ χ²(2)`.

### 5. Basel traffic light

250-day, 99% VaR: **green 0–4, yellow 5–9 (k=3.50), red ≥10.**

### 6. ES backtest

The `α`-ES traffic light per Constanzino & Curran. The Bank of Italy publishes all four tests in a
single table; that presentation is a good model.

## The power caveat — read this before designing the UI

A 99% VaR expects **2.5 exceedances in 250 days**. A worked example: 3 exceedances in 120 days
yields a Kupiec p-value of **0.166** — a test that passes almost anything.

So:

- **The traffic light and the raw hit count are honest and useful.** Report both.
- **The p-value is not a verdict at this sample size.** Report it as supporting evidence.
- **Headline the hit count and the worst breach ratio. Do not headline the p-value.**

Never render "Kupiec p = 0.62, model validated". That is a false all-clear, and on a single
portfolio it is the single most misleading thing this feature could produce.

## Change

- A `VaRBacktestService` computing all six outputs.
- A route exposing them, with `model`, `confidence`, `window`, `n_observations`, and
  `min_observations_required` in the response.
- `data_status: "unavailable"` with a reason when the window is too short — the existing
  `min_observations_required` / `annualizable` guard pattern on `forecast-risk` is the precedent.
- A page or a section on the risk-studio canvas.
- The frontend must present the power caveat, not just the verdict.

## Proof of done

- [ ] Kupiec, Christoffersen, and `LR_cc` are validated against **closed-form references**, not
      snapshots. These are analytical tests.
- [ ] The traffic light thresholds are exactly 0–4 / 5–9 / ≥10 and are unit-tested at each boundary.
- [ ] Each of the three engines is backtested independently and the comparison is visible.
- [ ] The exceptions timeline renders per-day hits with the breach ratio.
- [ ] The worst breach ratio is reported alongside the hit count.
- [ ] A window shorter than `min_observations_required` returns `data_status: "unavailable"` with a
      reason, not a p-value.
- [ ] **The frontend states the power caveat.** A test asserts the caveat text is present. This is
      the most important acceptance criterion on this ticket.
- [ ] A known-synthetic series with a deliberately wrong VaR produces the expected breach pattern.
- [ ] This also resolves the VaR duplication noted in Phase 3 — four different VaR constructions
      all reach responses as "VaR". The backtest page makes the differences visible, which is the
      first step to consolidating them.

## Notes

`scipy` is already a dependency. This is ~120 lines plus tests and a page.

The reference implementation to follow is the Bank of Italy's disclosure table, which presents
Kupiec, Christoffersen, conditional coverage, and the ES test together with the traffic light.

Refs: `../spec.md`, Phase 3 §"Duplicated and drifting formulas", `CONTEXT.md` §9.11
