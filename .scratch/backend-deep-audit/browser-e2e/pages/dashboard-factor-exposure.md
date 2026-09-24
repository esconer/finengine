# Factor Exposure — Page Report

**Status:** PARTIAL — 504-day control, section evidence, and direct replay are complete; 126/756-day controls and manual a11y remain partial.
**Route:** `/dashboard/factor-exposure`  
**Audit date:** 2026-09-24  
**Evidence stack:** isolated production frontend on `127.0.0.1:3001` and testing backend on `127.0.0.1:8001`.

> Evidence paths beginning `../evidence/` are relative to this report. Existing evidence only was used; no new browser/API/network call was made.

## Route and fixture

- **Empty:** zero positions.
- **Seeded:** five synthetic holdings: RELIANCE.NS, HDFCBANK.NS, TCS.BO, AAPL, and MSFT.
- **Historical:** same holdings with `added_on=2025-01-01`.
- **Default control state:** 252-day lookback; page presents a single-factor CAPM regression against NIFTY 50.
- **Viewports:** desktop `1440×900`; mobile `390×844`.
- App scrolling is internal; the final section set is present.

## Coverage

| State/control | Desktop | Mobile | Status |
|---|---|---|---|
| Empty | `../evidence/screenshots/desktop/empty/dashboard-factor-exposure.png` | `../evidence/screenshots/mobile/empty/dashboard-factor-exposure.png` | N/A metrics/table captured |
| Five-position default | `../evidence/screenshots/desktop/seeded/dashboard-factor-exposure.png` | `../evidence/screenshots/mobile/seeded/dashboard-factor-exposure.png` | 252-day view captured |
| Historical holding-date state | `../evidence/screenshots/desktop/historical/dashboard-factor-exposure.png` | Not captured | Same displayed default values |
| 126 / 504 / 756-day lookbacks | 504 exercised; 126/756 not | Same for mobile | 504-day request captured |
| Refresh, CSV, help modal, search | **Not tested** | **Not tested** | Controls visible only |
| Final internal-scroll sections | 13 desktop captures | 13 mobile captures | See **Final internal-scroll evidence** |

Text evidence: `../evidence/network/pages/desktop/{empty,seeded,historical}/dashboard-factor-exposure.txt` and matching mobile files.

## Executive verdict

- Empty state is appropriately unavailable: the page fetches portfolio state, does not fire an empty regression, shows N/A metrics, and has no console error.
- Default seeded output is internally coherent as a display transformation: R² 0.042 implies 20.5% correlation and 4.2%/95.8% systematic/specific shares; annualized alpha values are source-consistent after accounting for rounded daily display.
- The actual OLS regressions, benchmark alignment, alpha/beta estimates, and mixed-currency portfolio construction were not independently replayed.
- The lookback selector is labeled in trading days/years but backend subtracts calendar days. This is a confirmed model-input definition mismatch.
- Portfolio alpha of -5.36% annualized is labeled “Neutral Alpha” and described as “no meaningful active edge” because the frontend compares a rounded daily value to ±0.05%. That interpretation is not documented and is internally difficult to reconcile with the displayed annualized loss.
- Axe finds a critical unnamed lookback select, color-contrast failures, and heading-order defects.

## Visible behavior

### Empty

- Header shows zero positions; lookback remains 252 days.
- Market Beta, Alpha, R², model fit, loading bars, and variance decomposition all show N/A.
- Position table has zero rows and no results.
- Insights say Beta/Alpha unavailable due to insufficient regression history.
- No error banner or console error appears.
- Text: `../evidence/network/pages/desktop/empty/dashboard-factor-exposure.txt` and `../evidence/network/pages/mobile/empty/dashboard-factor-exposure.txt`.

### Seeded/historical default

- Period shown: `2026-01-15 to 2026-09-24`.
- R²: `0.042`; model fit: `Weak`.
- Portfolio Market Beta: `+0.388`.
- Portfolio Jensen's Alpha: `-5.36%` annualized; factor-loading card shows daily `-0.0002` and `-5.4% p.a.`.
- Market correlation: `20.5%`; systematic share `4.2%`; idiosyncratic share `95.8%`.
- Position table:

| Ticker | Beta | Daily alpha | Annualized alpha | Label |
|---|---:|---:|---:|---|
| RELIANCE.NS | +0.818 | -0.031% / d | -7.86% | Market-Like |
| HDFCBANK.NS | +1.284 | -0.047% / d | -11.82% | High Beta |
| TCS.BO | +0.785 | -0.217% / d | -54.58% | Defensive |
| AAPL | +0.164 | +0.126% / d | +31.82% | Defensive |
| MSFT | +0.174 | +0.024% / d | +6.09% | Defensive |

- Header says `Last updated: Never` despite the successful page render.
- Source: `frontend/src/app/dashboard/factor-exposure/page.tsx:274-337` and `frontend/src/app/dashboard/factor-exposure/page.tsx:513-529`.

## Controls and interaction evidence

| Control | Evidence status |
|---|---|
| Lookback select: 126/252/504/756 | 504-day option exercised; 126/756 not exercised |
| Hero refresh | Visible; **not exercised** |
| CSV export | Visible; **not exercised** |
| Help/explainer modal | Multiple visible; **not exercised** |
| Position table search/pagination | Visible; **not exercised** |
| Global Live/PDF/refresh/dark-mode/menu | Visible; **not exercised** |

## Financial verdicts

| Value/behavior | Verdict | Evidence/qualification |
|---|---|---|
| Empty metrics shown as N/A | `VERIFIED` presentation behavior | Regression is skipped for empty positions |
| R² → correlation transform | `VERIFIED` as display arithmetic | `√0.042 ≈ 0.2049`, displayed 20.5% |
| R² → systematic/specific shares | `VERIFIED` as display arithmetic | 0.042 → 4.2%; `1-0.042` → 95.8% |
| Annualized-alpha multipliers | `PARTIAL` | Source/display behavior captured; direct replay found field-level discrepancies and rounded-input sensitivity |
| Risk labels from beta thresholds | `VERIFIED` as display transform | >1.2 High, <0.8 Defensive, otherwise Market-Like |
| Portfolio beta 0.388 | `DISCREPANCY` | Independent replay captured aligned histories; market/beta fields differ under the documented convention |
| Portfolio alpha -5.36% | `DISCREPANCY` | Independent replay captured; annualized-alpha field differs under the replay convention |
| Position betas/alphas | `PARTIAL` | Replay completed; several market/alpha/data-point fields differ or depend on alignment |
| R²/model-fit interpretation | `PARTIAL` | Replay completed; exact benchmark/alignment contract remains underdetermined |
| “Neutral Alpha/no meaningful edge” interpretation | `DISCREPANCY` in presentation semantics | -5.36% annualized is paired with a neutral/no-edge conclusion based on an undocumented daily threshold |
| Mixed-currency portfolio factor exposure | `UNVERIFIABLE` | No daily historical FX; current-FX weights are combined with local return series |
| AAPL input history/quote provenance | `UNVERIFIABLE` / current quote `DISCREPANCY` | Exact source series is not captured; current quote is $4.89 |

These verdicts distinguish arithmetic/display consistency from model correctness.

## API, network, and console

- Empty desktop/mobile: one `GET /portfolio?currency=INR`, HTTP 200; no factor request; no console errors.
- Seeded desktop/mobile and historical desktop: one portfolio GET plus two identical completed factor requests:
  `GET /analytics/factor-exposure?tickers=RELIANCE.NS,HDFCBANK.NS,TCS.BO,AAPL,MSFT&lookback_days=252`.
- All completed responses are HTTP 200; no console errors or warnings.
- Duplicate regression calls are a P3 state/efficiency issue; exact cause is not asserted without a new trace.
- Current backend computes `start = now - timedelta(days=lookback_days)` at `backend/app/api/analytics.py:937-940`, then fetches the NIFTY 50 benchmark and runs OLS/HAC regression at `970-1004`.

Primary evidence:
- `../evidence/network/pages/desktop/empty/dashboard-factor-exposure.network.json`
- `../evidence/network/pages/desktop/seeded/dashboard-factor-exposure.network.json`
- `../evidence/network/console/desktop/seeded/dashboard-factor-exposure.console.json`

## Accessibility and responsive evidence

### Axe

- Seeded desktop: `select-name` critical (1), `color-contrast` serious (3), and `heading-order` moderate (1).
- Seeded mobile: `select-name` critical (1) and `heading-order` moderate (1).
- Historical desktop repeats all three desktop rules.
- The lookback `<select>` has no associated `<label>` or accessible name.
- No empty-state axe run exists.

Evidence: `../evidence/network/desktop/seeded/dashboard-factor-exposure.a11y.json`, `../evidence/network/mobile/seeded/dashboard-factor-exposure.a11y.json`, and `../evidence/network/desktop/historical/dashboard-factor-exposure.a11y.json`.

### Responsive

- Desktop shows four metric cards, two analysis panels, and a wide table.
- Mobile stacks the hero and metric cards; lower loading bars/table are captured; detailed review remains pending.
- The header title/control crowding is visible but all global controls remain in the 390px capture.
- Manual keyboard/select interaction and lower-page touch behavior are not tested.

## Findings

### FE-PAGE-01 — Lookback values are calendar days but labeled as trading-day horizons

- **Severity:** P2
- **Owner:** backend calculation contract; frontend labels/explainers
- **Observed:** The page defines 126/252/504/756 as 6 months/1/2/3 years and describes trading-day windows. Backend subtracts the same number of calendar days.
- **Evidence:** Captured 252 setting spans 2026-01-15 to 2026-09-24; source uses `timedelta(days=lookback_days)` at `backend/app/api/analytics.py:937-940`.
- **Impact:** The actual sample is materially shorter than the stated 252 trading days, especially for 126/756-day presets.
- **Expected:** Use trading-day windows or rename options in calendar days with accurate year/month labels.

### FE-PAGE-02 — Annualized -5.36% alpha is called neutral/no-edge

- **Severity:** P2
- **Owner:** frontend analytics interpretation/product
- **Observed:** `getFactorInterpretation` treats daily alpha between -0.0005 and +0.0005 as neutral. The page simultaneously displays -5.36% annualized and says the portfolio approximately matched CAPM with no meaningful active edge.
- **Source:** `frontend/src/app/dashboard/factor-exposure/page.tsx:358-370` and `831-864`.
- **Expected:** Use a documented, statistically defensible threshold on an adequately precise estimate and make the displayed units/verdict consistent.

### FE-PAGE-03 — Lookback select has no accessible name

- **Severity:** P2
- **Owner:** frontend
- **Expected:** Add a visible associated label or explicit `aria-label` including the current horizon.

### FE-PAGE-04 — Contrast and heading hierarchy violations

- **Severity:** P2
- **Owner:** frontend
- **Observed:** Sidebar description, correlation/beta text, and section heading order fail axe in seeded/historical desktop; heading order also fails mobile.

### FE-PAGE-05 — Duplicate factor requests

- **Severity:** P3
- **Owner:** frontend
- **Observed:** Two identical 252-day regression GETs after portfolio state settles.
- **Expected:** Avoid duplicate work while preserving stale-response protection when positions/lookback truly change.

### FE-PAGE-06 — “Multi-factor” navigation label overstates a single benchmark factor

- **Severity:** P3
- **Owner:** product/frontend
- **Observed:** Sidebar says “Multi-factor risk analysis,” while page and backend implement one market benchmark plus alpha.
- **Expected:** Call it single-factor/CAPM exposure or add the promised factor model.

### FE-PAGE-07 — Freshness clock remains Never

- **Severity:** P3
- **Owner:** frontend
- **Observed:** Successful page data renders while header says `Last updated: Never`; this page does not call `updateLastUpdated` in current source.
- **Expected:** Stamp successful model-data receipt without presenting it as quote as-of time.

## Reproduction summary

1. Use the isolated testing stack and empty portfolio; verify no factor request and N/A output.
2. Seed the five holdings and open the default 252-day view; compare R²-derived displays and annualized alpha source behavior.
3. Inspect network evidence for duplicate identical requests.
4. Change the select to 126, 504, and 756 and capture the actual data range/row counts to quantify the calendar/trading-day mismatch.
5. Run axe at 1440×900 and 390×844; inspect the select name and heading/contrast failures.

## Pending / not tested

- Raw factor response, benchmark series, aligned returns, HAC/OLS diagnostics, and independent replay.
- Every lookback control and resulting sample size.
- Refresh, CSV export, help modal, search, and pagination.
- Statistical significance/confidence of alpha/beta and the neutral-alpha policy.
- Daily historical FX and base-currency portfolio return construction.
- Provider/benchmark failure, database-unavailable, stale response, and WebSocket states.
- Manual keyboard, focus, screen-reader, zoom, and touch validation.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-factor-exposure-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-factor-exposure-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-factor-exposure-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-factor-exposure-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-factor-exposure-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-factor-exposure-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Lookback control | 252d → 504d produced a new 200 request and updated copy. | `../evidence/network/console/desktop/interactions/factor-lookback-504.txt` |
