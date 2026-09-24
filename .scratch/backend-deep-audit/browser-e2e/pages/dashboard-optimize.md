# Portfolio Optimizer

**Status:** PARTIAL — all five strategy runs, section evidence, and direct replay are complete; financial interpretation/manual controls remain partial.

> Evidence paths are relative to `browser-e2e/`.

## Route and fixture

- **Route:** `/dashboard/optimize`
- **Isolated stack:** frontend `127.0.0.1:3001`; backend `127.0.0.1:8001`, `environment=testing`.
- **Fixture:** `browser-e2e-five-equity-v1`: RELIANCE.NS ×10, HDFCBANK.NS ×20, TCS.BO ×15, AAPL ×5, MSFT ×4. Historical desktop uses normalized `added_on=2025-01-01`; early seeded captures predate normalization.
- **Exposed strategies:** HRP, Minimum Variance, Maximum Sharpe, Minimum CVaR, and Black-Litterman.
- **Known caveat:** any future run would consume current weights and one year of cached closes; current weights inherit the AAPL quote defect, and mixed-currency historical return reconstruction lacks daily FX.

## Controls and exercised behavior

| Control / behavior | Source evidence | Browser evidence |
|---|---|---|
| HRP / Min Vol / Max Sharpe / Min CVaR / Black-Litterman selection | `frontend/src/app/dashboard/optimize/page.tsx:49-80,147-177` | All five cards selected and run in one browser session. |
| Run selected strategy | `page.tsx:179-189` | `Run HRP` rendered; all five strategy buttons were clicked. |
| Result metrics, weight table, risk/return point, trade list, disclaimer | `page.tsx:225-431` | Rendered after each strategy run. |
| Empty guidance | `page.tsx:211-223` | `No results yet` rendered in every state. |

## Desktop and mobile evidence

| State | Desktop 1440×900 | Mobile 390×844 | Observed result |
|---|---|---|---|
| Empty | `evidence/screenshots/desktop/empty/dashboard-optimize.png`; `evidence/network/pages/desktop/empty/dashboard-optimize.txt` | `evidence/screenshots/mobile/empty/dashboard-optimize.png`; `evidence/network/pages/mobile/empty/dashboard-optimize.txt` | Five strategy cards and `No results yet`; no automatic API call. |
| Seeded | `evidence/screenshots/desktop/seeded/dashboard-optimize.png`; `evidence/network/pages/desktop/seeded/dashboard-optimize.txt` | `evidence/screenshots/mobile/seeded/dashboard-optimize.png`; `evidence/network/pages/mobile/seeded/dashboard-optimize.txt` | Same initial state despite five positions. |
| Historical desktop | `evidence/screenshots/desktop/historical/dashboard-optimize.png`; `evidence/network/pages/desktop/historical/dashboard-optimize.txt` | **Not captured** | Same initial state; sidebar/header still says “four strategies.” |

Mobile stacks the five strategy cards vertically; the fifth card extends below the captured viewport. Full reachability and scroll behavior have final section evidence.

## API, console, and network evidence

| Capture | API requests | Status | Console / page errors |
|---|---:|---|---|
| Empty desktop/mobile | 0 | N/A | 0 console errors; 0 page errors. |
| Seeded desktop/mobile | 0 | N/A | 0 console errors; 0 page errors. |
| Historical desktop | 0 | N/A | 0 console errors; 0 page errors. |

No `POST /api/v1/analytics/optimize/run` request exists in these captures because the page waits for explicit user action (`frontend/src/app/dashboard/optimize/page.tsx:88-100`).

Primary files:

- `evidence/network/pages/desktop/{empty,seeded,historical}/dashboard-optimize.network.json`
- `evidence/network/pages/mobile/{empty,seeded}/dashboard-optimize.network.json`
- `evidence/network/console/desktop/{empty,seeded,historical}/dashboard-optimize.console.json`
- `evidence/network/console/mobile/{empty,seeded}/dashboard-optimize.console.json`

## Calculations and verdicts

- Expected return, volatility, Sharpe, recommended weights, trade count, solver, risk/return coordinates, and disclaimer were produced for all five strategies; exact solver contract replay remains `UNDERDETERMINED`.
- No optimizer output can be called financially correct or discrepant from the available browser evidence.
- Backend source confirms a one-year common-sample path and five accepted strategies (`backend/app/api/analytics.py:2215-2307`), but that source inspection is not a substitute for running/replaying all five.

## Accessibility evidence

No empty-state axe capture exists.

- **Seeded desktop:** `color-contrast` serious (2 nodes), `heading-order` moderate (1).
- **Seeded mobile:** `color-contrast` serious (1), `heading-order` moderate (1).
- **Historical desktop:** same 2 rules and node counts as seeded desktop.
- Manual keyboard/focus and screen-reader checks: **not tested**.

Files: `evidence/network/{desktop,mobile}/seeded/dashboard-optimize.a11y.json` and `evidence/network/desktop/historical/dashboard-optimize.a11y.json`.

## Findings

| ID | Severity | Owner | Evidence-based finding |
|---|---|---|---|
| OP-F01 | **P3** | Frontend navigation/content | Sidebar/page description says “four strategies,” while the page exposes five including Black-Litterman. Consolidated FE-007. |
| OP-F02 | **P2** | Frontend | Axe evidence includes serious color contrast and moderate heading-order violations. Part of FE-006. |
| OP-F03 | **Verification blocker** | Analytics owner + QA | All five strategy POSTs and rendered results are `EXERCISED`; exact solver/weight contract replay remains `UNDERDETERMINED`. |

## Pending / not tested

- HRP, Min Vol, Max Sharpe, Min CVaR, and Black-Litterman runs.
- Weight sums, expected metrics, solver output, trade deltas, and disclaimer in each result.
- Empty/invalid/insufficient-common-history/error responses.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-optimize-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-optimize-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-optimize-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-optimize-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-optimize-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-optimize-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| All strategies | HRP, Min Vol, Max Sharpe, Min CVaR, and Black-Litterman each produced a 200 POST. | `../evidence/network/console/desktop/interactions/optimize-all.txt` |
