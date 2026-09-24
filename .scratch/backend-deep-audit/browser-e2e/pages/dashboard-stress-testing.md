# Stress Testing

**Status:** PARTIAL — Run All/custom controls, section evidence, and direct API capture are complete; selector/export/manual a11y remain partial.

> Evidence paths are relative to `browser-e2e/`. No claim below relies on a live service call made during report generation.

## Route and fixture

- **Route:** `/dashboard/stress-testing`
- **Isolated stack:** frontend `127.0.0.1:3001`; backend `127.0.0.1:8001`, `environment=testing`.
- **Fixture:** `browser-e2e-five-equity-v1`: RELIANCE.NS ×10, HDFCBANK.NS ×20, TCS.BO ×15, AAPL ×5, MSFT ×4. Empty and early-seeded captures predate purchase-date normalization; the historical desktop capture uses `added_on=2025-01-01` (`evidence/runtime/synthetic-fixture.json`, `evidence/network/pages/desktop/states/historical-fixture-update.json`).
- **Known input caveat:** the fixture's AAPL current quote is `$4.89`, already classified as a material quote discrepancy. Current portfolio weights, and therefore stress attributions, are conditional on that quote (`../financial-reconciliation.md`, `../backend-bugs.md`).
- **Viewports:** desktop `1440×900`; mobile `390×844`.

## Controls and exercised behavior

| Control / behavior | Source evidence | Browser evidence |
|---|---|---|
| Fetch portfolio on mount | `frontend/src/app/dashboard/stress-testing/page.tsx:415-520` | `GET /api/v1/portfolio?currency=INR` in every captured state. |
| Automatically run all four standard scenarios when positions exist | `frontend/src/app/dashboard/stress-testing/page.tsx:523-531` | Seeded/historical captures show `4 of 4`; network records successful stress-test POSTs. |
| Run All Scenarios | `frontend/src/app/dashboard/stress-testing/page.tsx:703-711` | Present; automatic load path exercised, but a separate manual click was not captured. |
| Market Crash, Interest Rate Shock, Volatility Spike, Tech Sector Correction cards / Run Test / View Positions | `frontend/src/app/dashboard/stress-testing/page.tsx:831-947` | All four results rendered. Manual per-card rerun was not captured. |
| Custom Shock name, shock %, Run Simulation | `frontend/src/app/dashboard/stress-testing/page.tsx:724-777` | Exercised with `AuditShock` at `-17%`. |
| Scenario selector | `frontend/src/app/dashboard/stress-testing/page.tsx:956-997` | Present; **not exercised**. Axe found the select unnamed. |
| CSV export | `frontend/src/app/dashboard/stress-testing/page.tsx:631-652,987-994` | Present; **not exercised**. |
| Metric/scenario help dialogs | `frontend/src/app/dashboard/stress-testing/page.tsx:218-367` | Present; **not exercised**. |

## Desktop and mobile evidence

| State | Desktop 1440×900 | Mobile 390×844 | Observed result |
|---|---|---|---|
| Empty | `evidence/screenshots/desktop/empty/dashboard-stress-testing.png`; `evidence/network/pages/desktop/empty/dashboard-stress-testing.txt` | `evidence/screenshots/mobile/empty/dashboard-stress-testing.png`; `evidence/network/pages/mobile/empty/dashboard-stress-testing.txt` | `0 of 4`; metrics are `N/A`; no false stress result. |
| Seeded | `evidence/screenshots/desktop/seeded/dashboard-stress-testing.png`; `evidence/network/pages/desktop/seeded/dashboard-stress-testing.txt` | `evidence/screenshots/mobile/seeded/dashboard-stress-testing.png`; `evidence/network/pages/mobile/seeded/dashboard-stress-testing.txt` | Four standard scenarios and five position rows rendered; hero controls stack acceptably in the captured viewport. |
| Historical desktop | `evidence/screenshots/desktop/historical/dashboard-stress-testing.png`; `evidence/network/pages/desktop/historical/dashboard-stress-testing.txt` | **Not captured** | Same four-scenario UI and results after purchase-date normalization. |

The mobile header compresses the route title/subtitle into a narrow column, but the captured hero and controls remain visible. No touch-target or full-scroll conclusion is made from this viewport image alone.

## API, console, and network evidence

| Capture | Observed API traffic | Status | Console / page errors |
|---|---|---|---|
| Empty desktop/mobile | 1 API: `GET /portfolio?currency=INR` | 200 | 0 console errors; 0 page errors. |
| Seeded desktop | 7 API records: 1 portfolio GET, **5** stress-test POST records, 1 stress-test OPTIONS preflight | All recorded 200 | 0 console errors; 0 page errors. |
| Seeded mobile | 6 API records: 1 portfolio GET, 5 stress-test POST records | All recorded 200 | 0 console errors; 0 page errors. |
| Historical desktop | 7 API records: same shape as seeded desktop | All recorded 200 | 0 console errors; 0 page errors. |

Primary network files:

- `evidence/network/pages/desktop/seeded/dashboard-stress-testing.network.json`
- `evidence/network/pages/mobile/seeded/dashboard-stress-testing.network.json`
- `evidence/network/pages/desktop/historical/dashboard-stress-testing.network.json`
- `evidence/network/console/desktop/{empty,seeded,historical}/dashboard-stress-testing.console.json`
- `evidence/network/console/mobile/{empty,seeded}/dashboard-stress-testing.console.json`

The page displays four distinct results, while the network captures contain five POST records. The capture does not retain POST bodies, so it is not possible to identify which request repeated or whether it changed a result.

## Calculations and verdicts

### Display-level replay

| Check | Independent calculation from captured values | Rendered value | Verdict |
|---|---:|---:|---|
| Worst standard scenario | `min(-45.9, -19.7, -25.6, -34.7)` | `-45.9%` | `VERIFIED` |
| Best standard scenario | `max(...)` | `-19.7%` | `VERIFIED` |
| Average impact | `(-45.9 -19.7 -25.6 -34.7) / 4 = -31.475%` | `-31.5%` | `VERIFIED` at displayed precision |
| Mean recovery | `(24 + 9 + 5 + 12) / 4 = 12.5 months` | `12.5 months` | `VERIFIED` |
| Market Crash portfolio impact | Current captured weights × displayed rounded position impacts = about `-45.926%` | `-45.9%` | `VERIFIED` at displayed precision |
| Market Crash severity | All displayed impacts are below `-25%` | All five `Critical` | `VERIFIED` from the page's thresholds |

### Financial/model verdict

- The UI summary arithmetic is internally consistent.
- The underlying three-year sector/volatility shock model, unshown `max_drawdown`, and each position-level factor calculation were **not independently replayed**: `UNVERIFIABLE`.
- The rendered outputs inherit the known AAPL/current-weight caveat; they are not externally certified real-market results.

## Accessibility evidence

No empty-state axe capture exists.

- **Seeded desktop:** 4 axe rules — `color-contrast` serious (4 nodes), `heading-order` moderate (1), `nested-interactive` serious (4), `select-name` critical (1).
- **Seeded mobile:** 3 axe rules — `heading-order` moderate (1), `nested-interactive` serious (4), `select-name` critical (1).
- **Historical desktop:** same 4 rules and node counts as seeded desktop.
- Manual keyboard/focus and screen-reader checks: **not tested**.

Files: `evidence/network/{desktop,mobile}/seeded/dashboard-stress-testing.a11y.json` and `evidence/network/desktop/historical/dashboard-stress-testing.a11y.json`.

## Findings

| ID | Severity | Owner | Evidence-based finding |
|---|---|---|---|
| ST-F01 | **P2** | Frontend analytics request orchestration; backend tracing support | Five stress-test POST records were captured for four displayed automatic scenarios. Request bodies are absent, so duplicate identity/cause is unresolved. |
| ST-F02 | **P2** | Frontend | The global header says `Last updated: Never` even after successful scenario results. The page does not update the UI freshness store. |
| ST-F03 | **P2** | Frontend | Seeded desktop/mobile axe captures contain critical `select-name`, serious `nested-interactive`, serious contrast, and heading-order violations. This is part of consolidated FE-006. |
| ST-F04 | **P1 input dependency** | Backend quote/data path | The known `$4.89` AAPL quote changes the current-weight basis used by the stress engine; all financial verdicts remain conditional. This is BE-002/DF-001, not a new quote finding. |

## Pending / not tested

- Manual Run All, per-scenario rerun, scenario selector, Custom Shock, CSV, help dialog, and failure handling.
- Direct raw model-response capture and independent stress-model replay.
- Historical mobile state.
- Controlled provider/database failure.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-stress-testing-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-stress-testing-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-stress-testing-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-stress-testing-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-stress-testing-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-stress-testing-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Preset/custom controls | Run All and AuditShock -17% completed. | `../evidence/network/console/desktop/interactions/stress-controls.txt` |
