# Performance Tear-Sheet

**Status:** PARTIAL — section evidence and direct API capture are complete; mobile historical and exact mixed-FX metric replay remain partial.

> Evidence paths are relative to `browser-e2e/`.

## Route and fixture

- **Route:** `/dashboard/tear-sheet`
- **Isolated stack:** frontend `127.0.0.1:3001`; backend `127.0.0.1:8001`, `environment=testing`.
- **Fixture:** `browser-e2e-five-equity-v1`: RELIANCE.NS ×10, HDFCBANK.NS ×20, TCS.BO ×15, AAPL ×5, MSFT ×4.
- **State distinction:** early seeded captures had `added_on=2026-09-24` and returned 404. Historical desktop captures were taken after normalization to `added_on=2025-01-01` and returned 200. Mobile has no post-normalization historical capture.
- **Analytical caveat:** mixed-currency historical portfolio returns cannot be independently reproduced without daily historical FX (`../data-freshness-bugs.md`, DF-003). The AAPL `$4.89` current quote defect also remains an input caveat.

## Controls and exercised behavior

| Control / behavior | Source evidence | Browser evidence |
|---|---|---|
| Fetch tear-sheet on mount | `frontend/src/app/dashboard/tear-sheet/page.tsx:301-323` | One GET in every captured state. |
| Export CSV | `page.tsx:369-421,466-475` | Present on desktop; not exercised. |
| Refresh | `page.tsx:476-483` | Desktop control present; inside `hidden md:flex`, so absent on mobile. Not clicked. |
| Try Again | `page.tsx:491-508` | Visible in empty/seeded error captures; not clicked. |
| Full-history vs holding-window sections | `page.tsx:341-348,524-661` | Historical desktop rendered both and labeled them. |
| Monthly heatmap, underwater curve, holdings, explainers | `page.tsx:819-982` | Historical desktop rendered; no interaction beyond load. |

## Desktop and mobile evidence

| State | Desktop 1440×900 | Mobile 390×844 | Observed result |
|---|---|---|---|
| Empty | `evidence/screenshots/desktop/empty/dashboard-tear-sheet.png`; `evidence/network/pages/desktop/empty/dashboard-tear-sheet.txt` | `evidence/screenshots/mobile/empty/dashboard-tear-sheet.png`; `evidence/network/pages/mobile/empty/dashboard-tear-sheet.txt` | Visible error: `Could not build performance tear-sheet` / `Requested resource not found`. |
| Seeded, pre-normalization | `evidence/screenshots/desktop/seeded/dashboard-tear-sheet.png`; `evidence/network/pages/desktop/seeded/dashboard-tear-sheet.txt` | `evidence/screenshots/mobile/seeded/dashboard-tear-sheet.png`; `evidence/network/pages/mobile/seeded/dashboard-tear-sheet.txt` | Same 404/error state despite five positions because no usable holding history existed on that capture date. |
| Historical desktop | `evidence/screenshots/desktop/historical/dashboard-tear-sheet.png`; `evidence/network/pages/desktop/historical/dashboard-tear-sheet.txt` | **Not captured** | 200 result with full-history instrument characteristics, holding-truthed current book, NIFTY comparison, heatmap, underwater curve, and weights. |

The successful desktop design clearly separates `Full-history · 2589 trading days` from `Current book since 2025-01-01`; this prevents the `1094.11%` full-history metric from being mistaken for the `-1.02%` holding-period result.

## API, console, and network evidence

| Capture | API | Status | Console / page errors |
|---|---|---|---|
| Empty desktop/mobile | `GET /analytics/tear-sheet` | 404 | 1 console error each: `API Error ... status: 404 ... Requested resource not found`. |
| Seeded desktop/mobile | Same GET | 404 | 1 console error each. |
| Historical desktop | Same GET | 200 | 0 console errors; 0 page errors. |

Primary files:

- `evidence/network/pages/desktop/{empty,seeded,historical}/dashboard-tear-sheet.network.json`
- `evidence/network/pages/mobile/{empty,seeded}/dashboard-tear-sheet.network.json`
- `evidence/network/console/desktop/{empty,seeded,historical}/dashboard-tear-sheet.console.json`
- `evidence/network/console/mobile/{empty,seeded}/dashboard-tear-sheet.console.json`

The route inventory correctly notes that the seeded endpoint was 404 pending history/provider classification (`../route-inventory.md`). Source maps no positions or no usable in-window history to a generic 404 (`backend/app/api/analytics.py:1883-1889,2051-2055`).

## Calculations and verdicts

### Captured historical result

- Window: `2025-09-24 → 2026-09-24`; five holdings; NIFTY 50 benchmark.
- Full-history asset characteristics: total return `1094.11%`, CAGR `27.30%`, Sharpe `1.08`, max drawdown `-29.12%`, `2589` trading days.
- Holding-truthed current book: total return `-1.02%`, max drawdown `-29.12%` since `2025-01-01`.
- NIFTY comparison: beta `0.36`, annualized alpha `+19.93%`, portfolio Sharpe `1.08`, NIFTY Sharpe `-0.76`, portfolio vol `23.00%`, NIFTY vol `13.29%`, `2464d` overlap.
- Holding-window advanced suite: Sortino `0.01`, Calmar `-0.03`, Omega `1.02`, tail ratio `0.96`, skew `1.21`, kurtosis `12.52`.

### Display-level checks

| Check | Independent calculation from displayed values | Rendered value | Verdict |
|---|---:|---:|---|
| Full-history CAGR relation | `(1 + 10.9411)^(252/2589) - 1 ≈ 27.30%` | `27.30%` | `VERIFIED` at displayed precision |
| 2025 monthly compounding | `1.005×1.014×0.95×0.989−1 ≈ −4.253%` | `-4.3%` | `VERIFIED` from rounded cells |
| 2026 monthly compounding | `0.925×0.93×0.938×1.096×1.076×0.87×1.224×1.067×0.957−1 ≈ 3.473%` | `+3.5%` | `VERIFIED` from rounded cells |
| Max drawdown consistency | Holding max drawdown and underwater trough both `-29.12%` | Both `-29.12%` | `VERIFIED` |

Backend source uses geometric monthly grouping `(1+r).groupby([year,month]).prod()-1` (`backend/app/api/analytics.py:2015-2025`), matching the required deterministic compounding method.

### Financial verdict

- Monthly/year display arithmetic and the full-history total-return/CAGR relationship are `VERIFIED` at rendered precision.
- Full raw QuantStats metrics, beta/alpha, benchmark alignment, and holding-period returns are `UNVERIFIABLE`: direct raw response/series replay is absent.
- True mixed-currency portfolio performance remains `UNVERIFIABLE` without daily historical FX; the AAPL quote defect is an additional fixture caveat.

## Accessibility evidence

No empty-state axe capture exists.

- **Seeded desktop:** `color-contrast` serious (3 nodes), `heading-order` moderate (1).
- **Seeded mobile:** `color-contrast` serious (2), `heading-order` moderate (1).
- **Historical desktop:** `color-contrast` serious (**17 nodes**), `heading-order` moderate (1).
- Manual keyboard/focus and screen-reader checks: **not tested**.

Files: `evidence/network/{desktop,mobile}/seeded/dashboard-tear-sheet.a11y.json` and `evidence/network/desktop/historical/dashboard-tear-sheet.a11y.json`.

## Findings

| ID | Severity | Owner | Evidence-based finding |
|---|---|---|---|
| TS-F01 | **P2** | Backend error contract + frontend state handling | Empty and early-seeded states return/log a generic 404 for absent or not-yet-usable holding history. A deliberate unavailable/insufficient-history state would distinguish this from a missing resource. This is part of FE-005. |
| TS-F02 | **P2** | Backend analytics/data contract | Mixed-currency historical performance lacks daily FX, so displayed portfolio return, beta, alpha, and risk metrics are not independently reproducible. DF-003. |
| TS-F03 | **P2** | Frontend | Historical desktop axe reports 17 serious contrast nodes plus heading-order; seeded viewports also violate contrast. Part of FE-006. |
| TS-F04 | **P3** | Frontend responsive UI | Page-specific Export/Refresh controls are hidden below `md`; mobile error recovery depends on Try Again. |

The explicit separation of full-history asset characteristics and holding-truthed current-book metrics is a positive control, not a finding.

## Pending / not tested

- Refresh, Try Again, CSV, explainers, and chart/table overflow behavior.
- Direct tear-sheet raw-response and independent QuantStats replay.
- Official benchmark and provider freshness checks.
- Any acquisition-date FX replay.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-tear-sheet-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-tear-sheet-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-tear-sheet-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-tear-sheet-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-tear-sheet-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-tear-sheet-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Direct capture/replay | Captured body reviewed; mobile historical remains absent. | `../evidence/calculations/outputs/independent-core-models.md` |
