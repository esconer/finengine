# 08 — India VIX series

Status: ready-for-agent
Type: task
Phase: 4
Blocked by: Phase 1 issue 15
Repo: `backend/`
Severity: **HIGH**

## What

Ingest and store India VIX as a first-class series alongside the `^NSEI` benchmark.

The benchmark service (`benchmark_service.py:20`) currently holds **price only**. India VIX is
absent from the entire app.

## Why

**India VIX is the only implied-volatility measure in India.** The app's whole volatility apparatus
— vol cones, forecast-risk, volatility-sizing, regime — is currently **pure realized volatility
with no risk-neutral cross-check.**

It gives three things nothing else can:

1. **A realized-vs-implied comparison.** When VIX sits far above the app's GARCH forecast of
   realized vol, that is the variance risk premium, and it is a genuine signal that the
   realized-only model is underestimating tail risk.
2. **A forward 1-month expected move** to sanity-check forecast VaR. If the app says 21-day VaR is
   2% and VIX implies a 1-sigma 21-day move of 4%, the model is too confident.
3. **A vol-regime input** for the regime engine, which currently fits on realised vol alone.

It is also **key-free** — `nseindia.com/reports-indices-historical-vix` CSV, or
`/api/indicesHistory?indexType=INDIA VIX`. `jugaad-data` has a direct `INDIAVIX` history fetcher.

## Change

Phase 1 issue 15 provides `bfinance.nse.macro.india_vix()`. This ticket is storage, scheduling, and
surfacing.

- Store as a benchmark-adjacent series with `as_of` provenance.
- Schedule EOD with the bhavcopy run (issue 05).
- Surface it: the Vol Cone should show implied alongside realised; forecast-risk should carry it
  as a cross-check; the regime page can use it as an additional feature.
- **Be explicit about what VIX is.** It is a 30-day constant-maturity implied volatility derived
  from NIFTY option prices. It is *not* a forecast of the app's own horizon and *not* directly
  comparable to a single-name realised vol. State that wherever it is displayed, or it will be
  read as a like-for-like comparison.

## Proof of done

- [ ] A history of at least 3 years lands and is readable.
- [ ] The Vol Cone page shows implied alongside realised, with the comparison's limitations stated.
- [ ] Forecast-risk carries India VIX as a cross-check field, with a note that it is a 30-day
      index-level measure and not directly comparable to a single-name figure.
- [ ] A test asserts the stored series' date coverage and that values are in a plausible range
      (typically 10–80).
- [ ] `as_of` is server-published and the freshness caption uses it.
- [ ] The test uses a recorded fixture.

## Notes

**Do not** build the full options Greeks / IV surface (ticket `t31`) as part of this. A6's
research concluded: ship India VIX, drop the surface. A cash-equity book does not need greeks, and
one free daily series delivers most of the value at none of the cost.

Phase 1 issue 19 (`bfinance.derivatives`) is the eventual home of the full chain, if it is ever
wanted. That is a separate, larger decision.

Refs: `../spec.md`, `backend/app/services/benchmark_service.py:20`, Phase 1 issue 15, `.scratch/advanced-analytics/` ticket `t31`
