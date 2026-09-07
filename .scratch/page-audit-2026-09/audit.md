# Full-Page Visual & Contract Audit — 2026-09-06

**Method**: ZCode in-app browser (dedicated tab, 1440×900) — every route loaded,
screenshot captured to `screenshots/`, page text scanned for `NaN / undefined /
Infinity / Error / Failed / N/A`, values cross-checked against `daisy.db` and
backend endpoints. Root causes verified in code. 14 holdings, all added
2026-08-27, cache ≈174 trading days/ticker (2025-12-29 → 2026-09-06).

**Portfolio context**: ₹43,272 market value, +14.16% unrealized, 14 positions.

---

## Verdicts by page (20 routes)

| # | Page | State | Key findings |
|---|---|---|---|
| 1 | `/dashboard` | ⚠️ P1 | Annual Volatility card **N/A** (annualization gate); regime "Crisis, 96% stability" pairing looks alarming but is model output; header "Last updated" inconsistent across pages (see P2-1). `01-dashboard.png` |
| 2 | `/dashboard/equity-research` | ✅ clean | Reliance profile fully rendered (₹17.89 L Cr mcap, P/E 23.9x, Piotroski 6/9, Graham ₹911). 1 stray N/A. `02-equity-research.png` |
| 3 | `/dashboard/screener-studio` | ⚠️ P1 | Infinite "Scanning Indian equity universe…" spinner on cold cache — `GET /screens/coffee_can` took >60s cold (Screener.in per-stock enrichment, TATAMOTORS fallback lookups in log), 0.2s warm. No progress feedback, no timeout message. `03-`, `03b-` pngs |
| 4 | `/dashboard/realized-risk` | ❌ P0 → **FIXED (DSP-10)** | Before: Annual Return/Volatility/Sharpe/Sortino all **N/A**; 14 near-identical warning bullets; holding window (6 days) truncated everything. After: full-history block renders 28.06% / 19.79% / 1.32 / 1.88 on 174 days; holding P&L in own section; precision notice. `04-`, `04b-`, `21-`, `21b-` pngs |
| 5 | `/dashboard/forecast-risk` | ✅ clean | GARCH 1-Day VaR -0.77%, CVaR -0.96%, vol 7.41%. Model/horizon selectors work. `05-forecast-risk.png` |
| 6 | `/dashboard/factor-exposure` | ❌ P0 → **FIXED (DSP-10)** | Before: **β exactly +1.000 for all 14 positions, R² 0.000** — engine's `_empty_factor_exposure()` placeholder `{alpha:0, market:1}` rendered as "Market-Like" because the holding-masked window (~6 obs) degenerated the regression vs the full-year benchmark. After: portfolio β 1.093, R² 0.669, per-position betas 0.54–1.86 on 168–169 obs. `06-factor-exposure.png` |
| 7 | `/dashboard/stress-testing` | ✅ clean | 4 scenarios evaluated; worst -47.1%, per-position impacts populated (CIPLA -19.7%). `07-stress-testing.png` |
| 8 | `/dashboard/concentration` | ✅ clean | HHI 0.09, effective positions 11.6/14, diversification 98.4% — true HHI math intact. `08-concentration.png` |
| 9 | `/dashboard/liquidity` | ⚠️ P2 | First load rendered header only ("Overall Score: 0.0/10" + blank body — contradictory); second load fully populated (7.9/10, Medium, per-position levels). Slow first render, no skeleton. `09-`, `09b-` pngs |
| 10 | `/dashboard/volatility-sizing` | ⚠️ P1 | Est. Portfolio Vol **15.3%** (EWMA) vs Forecast page **7.41%** (GARCH) vs realized full-history **19.79%** — three pages, three vol figures, no reconciliation note. `10-volatility-sizing.png` |
| 11 | `/dashboard/tear-sheet` | ❌ P1 | **8 N/A fields**: CAGR, Sharpe, Beta, Alpha, Portfolio Sharpe, Sortino, Calmar dead — same annualization gate on 6-day holding window vs NIFTY. Only Total Return 0.70%, Omega 1.79, Tail 1.01 render. Needs the DSP-10 full-history treatment (follow-up). `11-tear-sheet.png` |
| 12 | `/dashboard/risk-contribution` | ⚠️ P1 | Portfolio Volatility (ann.) **N/A** while Daily VaR renders; SELECTIPO/ARROWGREEN/MIDCAPIETF show **-0.1%** Euler contributions (degenerate vol estimates in the 6-day window). `12-risk-contribution.png` |
| 13 | `/dashboard/risk-studio` | ⚠️ P1 | "Compiling institutional risk canvas…" ≥12s: `/analytics/tails` (EVT+Copula) takes **12.3s per request** uncached and the studio blocks on all four endpoints behind one spinner. `13-`, `13b-` pngs |
| 14 | `/dashboard/optimize` | ✅ clean | Clean empty state; 4 strategies; "Run HRP" ready. `14-optimize.png` |
| 15 | `/dashboard/regime` | ⚠️ P2 | Posterior degenerate: Calm 0% / Bull 0% / **Crisis 100%** — HMM posterior saturated (no soft probabilities); worth checking posteriors aren't clipped. `15-regime.png` |
| 16 | `/dashboard/monte-carlo` | ✅ clean | Clean empty state; copy says "calibrated on two years of cached closes" but cache holds ~8.5 months (copy drift). `16-monte-carlo.png` |
| 17 | `/dashboard/pairs` | ❌ P1 | Rows with **p-value 0.99** (JUNK cointegration) still render **SHORT_SPREAD trade signals** and OU half-life N/A — signals must be suppressed above a p-value threshold. `17-pairs.png` |
| 18 | `/dashboard/india-flows` | ⚠️ P2 | All "Days @ 10% ADV" render "**0d**" — mathematically right (₹2.7K positions vs ₹127Cr ADV) but useless display; show "<0.1d" or fractional. `18-india-flows.png` |
| 19 | `/portfolio/manage` | ✅ clean | ₹43,272 / +14.16%, best MOTHERSON +83.49%, worst JKIL -28.42%, 9/5 winners — math cross-checked vs DB. `19-portfolio-manage.png` |
| 20 | `/dashboard/settings` | ✅ clean | Source selector reflects persisted value (yfinance) with fallback chain; purge button ready. `20-settings.png` |

## Root causes verified in code

1. **Holding-window mask feeds analytics that need asset history**
   (`holding_window` in `app/utils/holdings.py` applied in `get_realized_risk`
   and `get_factor_exposure`). Correct for realized P&L; wrong for
   instrument risk characteristics and regression vs benchmark.
2. **Degenerate fallback renders as real data** —
   `AnalyticsEngine._empty_factor_exposure()` returns `{alpha: 0.0, market: 1.0}`;
   `apply_annualization_gate` nulls keys but the UI shows raw "N/A" with no
   explanation at card level.
3. **Backend slowness without feedback** — `/analytics/tails` 12.3s,
   cold screener >60s; frontends show infinite spinners.
4. **Signal rendering without statistical qualification** — pairs page.

## Fixes applied this session (DSP-10)

- `get_realized_risk`: new **`instrument_risk`** block (portfolio + 14
  positions on full 174-day history, per-position `total_return`,
  `apply_annualization_gate` vs each ticker's own days);
  `history_coverage.full_history_days/full_history_start` added; warning text
  is now a precision statement.
- `get_factor_exposure`: regression runs on **full history** (holding window
  disclosed via coverage only). Betas are real per-position values now.
- `get_realized_risk` except-clause now `logger.exception` (tracebacks in log).
- Frontend `realized-risk/page.tsx`: two-window layout — "Instrument Risk —
  Full Exchange History" cards + "Holding-Period Realized P&L" section +
  reworked position table (Total Return (Full History), annualized-flag-aware
  Sharpe gate).

**Verification**: backend 371/371 pytest, ruff clean; frontend tsc clean,
66/66 vitest; live endpoints verified (instrument portfolio Sharpe 1.32,
factor β 1.093/R² 0.669); browser screenshots `21-`/`21b-`.

## Follow-up implementation record (2026-09-07)

All three zcode workstreams closed. Backend 372/372 pytest, ruff clean;
frontend tsc clean, 66/66 vitest.

- [x] P1 Tear-sheet full-history split — backend `full_history.{metrics,
  relative_vs_nifty}` in `get_tear_sheet` + frontend "Instrument Risk —
  Full Exchange History" section (`tear-sheet/page.tsx`)
- [x] P1 Risk-contribution full-history covariance — `get_risk_contribution`
  builds on unmasked window; holding truncation disclosed via coverage only
- [x] P1 `/analytics/tails` 15-min TTL (`_TAILS_RESPONSE_CACHE`, 900s;
  decorator placement fixed — cache consts had been inserted between the
  stacked `@router.get` lines, a SyntaxError that broke backend import)
- [x] P1 Pairs gating — `analyze_pair_cointegration` emits
  `NOT_COINTEGRATED` when p >= threshold (no SHORT/LONG_SPREAD on junk
  pairs); pairs page renders "Not cointegrated"; regression test
  `test_non_cointegrated_pair_signal_gated`
- [x] P2 Screener cold-cache feedback — 8s escalating hint ("first run …
  up to a minute… cached and instant")
- [x] P2 Vol reconciliation — Forecast + Sizing captions name model,
  horizon/window and cross-reference each other + Realized Risk
- [x] P2 India-flows `<0.1d` display

Still open (out of zcode scope): Regime saturated posterior, header
"Last updated" unification, liquidity first-render skeleton, dashboard
vol N/A gate, monte-carlo copy drift.

## Remediation record (2026-09-07, `.scratch/remediation-2026-09/`)

All five items above closed, plus a code-scan honesty batch and the
`added_on` contract. Backend 383/383 pytest, ruff clean; frontend tsc
clean, 81/81 vitest.

- `added_on` purchase date: was output-only on both sides (backend ignored
  it, frontend couldn't send it). Now accepted on add/bulk/update
  (validated ≤ today), date pickers in both modals, CSV date-column import,
  4 pytest + 3 vitest.
- Fabricated constants: forecast/summary error branches + `liquidity_score
  7.8` + per-ticker `0.25` → nulls; frontend `1.083/0.679/18.08/0.382/0.158/
  0.139/1.0-beta/0.20-vol` fallbacks → N/A-aware + forecast error banner.
  Residuals (engine-internal 0.22/vol-clamps, liquidity/stress/risk-score
  error-branch constants) documented in issue 08.
- Screener L2 DB cache (24h) + per-request prod wiring (singleton can't hold
  request sessions); regime posteriors at 4dp precision.
- B8 dead `PortfolioCharts.tsx` deleted; liquidity skeleton; dashboard store
  timestamp; monte-carlo honest copy.

## Recommended follow-ups (not yet implemented)

| Pri | Item |
|---|---|
| P1 | Tear-sheet: apply the same full-history instrument-risk split (8 N/A fields today) |
| P1 | Risk-contribution: use full-history covariance (3 ETFs at -0.1% RC, portfolio vol N/A) |
| P1 | Cache `/analytics/tails` (TTL ≈ 15 min) — 12.3s per request blocks Risk Studio |
| P1 | Pairs: suppress SHORT_SPREAD signals when EG p-value > 0.05; show "not cointegrated" |
| P2 | Screener: progress feedback + server-side persistent screen cache (cold run >60s) |
| P2 | Vol figure reconciliation note across Forecast (7.41%) / Sizing (15.3%) / Realized (19.79%) — different models/windows, label them |
| P2 | Regime: investigate saturated posterior (100/0/0) |
| P2 | India-flows: render "<0.1d" instead of "0d" |
| P2 | Header "Last updated" inconsistent per page (Never vs Just now) — unify on store value |
