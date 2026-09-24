# Risk Contribution

**Status:** PARTIAL — section evidence and direct replay are complete; empty/error contract and manual controls remain partial.

> Evidence paths are relative to `browser-e2e/`.

## Route and fixture

- **Route:** `/dashboard/risk-contribution`
- **Isolated stack:** frontend `127.0.0.1:3001`; backend `127.0.0.1:8001`, `environment=testing`.
- **Fixture:** `browser-e2e-five-equity-v1`: RELIANCE.NS ×10, HDFCBANK.NS ×20, TCS.BO ×15, AAPL ×5, MSFT ×4. Historical desktop uses normalized `added_on=2025-01-01`; early seeded captures predate normalization.
- **Model window in captured result:** `2025-09-24 → 2026-09-24`; current weights and one-year portfolio return/covariance data drive the result.
- **Known caveat:** the known AAPL `$4.89` quote changes current weights. Daily historical FX is also absent, so true mixed-currency portfolio return/covariance cannot be independently reproduced.

## Controls and exercised behavior

| Control / behavior | Source evidence | Browser evidence |
|---|---|---|
| Fetch risk contribution on mount | `frontend/src/app/dashboard/risk-contribution/page.tsx:248-271` | One GET in every captured state. |
| Refresh | `page.tsx:377-394` | Desktop present; inside `hidden md:flex`, absent on mobile. Not clicked. |
| Export CSV | `page.tsx:295-340,377-386` | Present; not exercised. |
| Volatility Share / Tail Loss Share sector toggle | `page.tsx:521-555` | Both options rendered; not toggled. |
| Try Again | `page.tsx:402-419` | Visible in empty capture; not clicked. |
| Metric explainers | `page.tsx:114-191` | Present; not opened. |

## Desktop and mobile evidence

| State | Desktop 1440×900 | Mobile 390×844 | Observed result |
|---|---|---|---|
| Empty | `evidence/screenshots/desktop/empty/dashboard-risk-contribution.png`; `evidence/network/pages/desktop/empty/dashboard-risk-contribution.txt` | `evidence/screenshots/mobile/empty/dashboard-risk-contribution.png`; `evidence/network/pages/mobile/empty/dashboard-risk-contribution.txt` | Visible `Could not decompose portfolio risk` / `Requested resource not found`. |
| Seeded | `evidence/screenshots/desktop/seeded/dashboard-risk-contribution.png`; `evidence/network/pages/desktop/seeded/dashboard-risk-contribution.txt` | `evidence/screenshots/mobile/seeded/dashboard-risk-contribution.png`; `evidence/network/pages/mobile/seeded/dashboard-risk-contribution.txt` | Portfolio volatility, VaR, CVaR, top driver, position bars, sector rollup, and diagnostic rendered. |
| Historical desktop | `evidence/screenshots/desktop/historical/dashboard-risk-contribution.png`; `evidence/network/pages/desktop/historical/dashboard-risk-contribution.txt` | **Not captured** | Same 200 result after purchase-date normalization. |

The captured mobile hero and metric stack remain visible. Sector and lower-page behavior cannot be judged from the viewport screenshot alone.

## API, console, and network evidence

| Capture | API | Status | Console / page errors |
|---|---|---|---|
| Empty desktop/mobile | `GET /analytics/risk-contribution` | 404 | 1 console error each: `API Error ... status: 404 ... Requested resource not found`. |
| Seeded desktop/mobile | Same GET | 200 | 0 console errors; 0 page errors. |
| Historical desktop | Same GET | 200 | 0 console errors; 0 page errors. |

Primary files:

- `evidence/network/pages/desktop/{empty,seeded,historical}/dashboard-risk-contribution.network.json`
- `evidence/network/pages/mobile/{empty,seeded}/dashboard-risk-contribution.network.json`
- `evidence/network/console/desktop/{empty,seeded,historical}/dashboard-risk-contribution.console.json`
- `evidence/network/console/mobile/{empty,seeded}/dashboard-risk-contribution.console.json`

## Calculations and verdicts

### Captured historical result

- Portfolio annualized volatility: `25.47%`.
- Daily VaR 95%: `-2.29%`; daily CVaR 95%: `-3.17%`.
- Top risk driver: MSFT `96.0%` of volatility risk.
- Volatility shares: MSFT `96.0%`, TCS.BO `3.0%`, HDFCBANK.NS `0.5%`, RELIANCE.NS `0.5%`, AAPL `0.1%`.
- Tail shares: MSFT `88.8%`, TCS.BO `9.3%`, RELIANCE.NS `1.0%`, HDFCBANK.NS `0.7%`, AAPL `0.2%`.
- Diagnostic: TCS.BO tail share exceeds volatility share by `+6.3` percentage points.

### Display-level checks

| Check | Calculation | Rendered value | Verdict |
|---|---:|---:|---|
| Volatility-share total | `96.0+3.0+0.5+0.5+0.1` | `100.1%` | `VERIFIED` as one-decimal rounding |
| Tail-share total | `88.8+9.3+1.0+0.7+0.2` | `100.0%` | `VERIFIED` |
| CVaR tail ordering | CVaR `-3.17%` is more negative than VaR `-2.29%` | Both rendered | `VERIFIED` as expected empirical-tail ordering |
| TCS divergence | `9.3%−3.0%` | `+6.3%` | `VERIFIED` |

Backend source implements Euler contribution `w_i(Σw)_i/σ_p`, normalizes to 100%, derives VaR as the empirical fifth percentile, and CVaR as the mean return on `R <= VaR` (`backend/app/api/analytics.py:2060-2207`). This confirms the method, not the raw numerical result.

### Financial verdict

- Displayed share sums, divergence, and tail ordering: `VERIFIED`.
- Raw covariance matrix, fitted VaR/CVaR, sector mapping, and Euler outputs: `UNVERIFIABLE` without raw returns/weights and independent replay.
- Current weights are conditional on the AAPL quote defect; true mixed-currency daily portfolio risk is additionally limited by missing historical FX.

## Accessibility evidence

No empty-state axe capture exists.

- **Seeded desktop:** `color-contrast` serious (1 node), `heading-order` moderate (1).
- **Seeded mobile:** `heading-order` moderate (1).
- **Historical desktop:** `color-contrast` serious (1), `heading-order` moderate (1).
- Manual keyboard/focus and screen-reader checks: **not tested**.

Files: `evidence/network/{desktop,mobile}/seeded/dashboard-risk-contribution.a11y.json` and `evidence/network/desktop/historical/dashboard-risk-contribution.a11y.json`.

## Findings

| ID | Severity | Owner | Evidence-based finding |
|---|---|---|---|
| RC-F01 | **P2** | Backend error contract + frontend empty-state handling | Empty portfolio calls the analytics endpoint and receives/logs a generic 404. Expected unavailability is presented as a failed resource. Part of FE-005. |
| RC-F02 | **P1 input dependency** | Backend quote/data path | Current risk weights inherit the confirmed AAPL `$4.89` quote. Existing BE-002/DF-001 dependency. |
| RC-F03 | **P2 analytical** | Backend analytics/data contract | Mixed-currency return/covariance reconstruction lacks daily historical FX; model correctness remains unverified. DF-003. |
| RC-F04 | **P2** | Frontend | Axe evidence includes serious contrast and heading-order violations. Part of FE-006. |
| RC-F05 | **P3** | Frontend responsive UI | Page-specific Refresh is hidden below `md`; not available in the mobile hero. |

## Pending / not tested

- Refresh, Try Again, sector toggle, CSV, and explainers.
- Direct raw response/series capture and independent Euler/VaR/CVaR replay.
- Excluded-asset and partial-history cases.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 10 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-risk-contribution-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-risk-contribution-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-risk-contribution-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-risk-contribution-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-risk-contribution-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-risk-contribution-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Direct replay | Tail and volatility attribution checks completed; exact tail definition remains underdetermined. | `../evidence/calculations/outputs/independent-core-models.md` |
