# Screener Studio

**Status:** PARTIAL — built-in/custom screen, add flow, and section evidence are complete; duplicate-row conflict and manual a11y remain partial.

## Route, fixture, and source identity

- **Route:** `/dashboard/screener-studio`
- **Captured:** 2026-09-24 on the isolated testing frontend/backend (`127.0.0.1:3001` / `127.0.0.1:8001`).
- **Frontend build:** `hghBG-hlr8-XxzAq9sTq3`; the dirty working tree means this build is not claimed to be exactly Git HEAD.
- **Fixtures:** empty (0 positions), seeded (5 positions), and desktop historical (same 5 positions with normalized purchase dates). Mobile historical was not captured.
- The screener is portfolio-independent: seeded and historical captures completed with the same Coffee Can result; the empty captures began the same default scan; later interaction captures completed the screen workflow.
- **Viewports:** desktop `1440×900`; mobile `390×844`.
- Evidence root: `.scratch/backend-deep-audit/browser-e2e/`.

## Coverage and controls

Captured states:

- Desktop empty, seeded, and historical.
- Mobile empty and seeded.

Visible controls:

- **Custom Screener Builder** toggle.
- Five pre-built strategies: Coffee Can Portfolio, Magic Formula (India), Debt Free Compounders, High Dividend Champions, and Undervalued Growth.
- Custom filters: minimum ROCE, minimum ROE, maximum P/E, minimum market cap, minimum dividend yield, and **Execute Custom Screen**.
- Result search, sortable price/market-cap/P-E/ROCE/ROE/dividend-yield columns, peer-research links, per-row **Portfolio** buttons, and Previous/Next pagination.
- Shared header: live-data toggle, PDF export, portfolio refresh, and dark-mode toggle.

Observed output:

- Seeded desktop/mobile and historical desktop showed the default Coffee Can screen with “25 Stocks Found.” The first page displayed 20 of 25.
- Desktop showed the table and several rows in the viewport. Mobile showed the page header and vertically stacked strategy cards; the result table was below the captured viewport.
- Empty desktop/mobile captures showed strategy metadata and a cold-run scanning state. The coffee-can request had no captured response status by capture end; the strategy buttons were disabled while loading. There was no console or page error.

Primary evidence:

- `evidence/screenshots/desktop/{empty,seeded,historical}/dashboard-screener-studio.png`
- `evidence/screenshots/mobile/{empty,seeded}/dashboard-screener-studio.png`
- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/dashboard-screener-studio.txt`
- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/dashboard-screener-studio.snapshot.txt`

## API, console, and network evidence

Initial requests:

1. `GET /api/v1/screens`
2. `GET /api/v1/screens/coffee_can?max_stocks=50`

| State | `/screens` | Coffee-can run | Bad/missing status | Console | Page errors |
|---|---:|---:|---:|---:|---:|
| Desktop empty | 200 | no status captured | 1 | 0 | 0 |
| Desktop seeded | 200 | 200 | 0 | 0 | 0 |
| Desktop historical | 200 | 200 | 0 | 0 | 0 |
| Mobile empty | 200 | no status captured | 1 | 0 | 0 |
| Mobile seeded | 200 | 200 | 0 | 0 | 0 |

The missing coffee-can status is an in-flight/capture-end condition, not evidence of an HTTP failure. No custom-screen POST, portfolio GET/add POST, or strategy-switch request was captured.

Network evidence contains request metadata but no direct raw screener response body. Evidence:

- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/dashboard-screener-studio.network.json`
- `evidence/network/console/{desktop,mobile}/{empty,seeded,historical}/dashboard-screener-studio.console.json`
- `evidence/network/console/{desktop,mobile}/{empty,seeded,historical}/dashboard-screener-studio.errors.json`

## Source and freshness review

- The page loads strategy metadata and automatically runs the default `coffee_can` strategy (`frontend/src/app/dashboard/screener-studio/page.tsx:70-126`).
- Backend strategy metadata and execution are backed by `bfinance.screens` (`backend/app/services/screener_service.py:65-117`, `182-278`). Results are capped after the full universe is scanned.
- The service has a 5-minute in-process cache and a 24-hour database cache keyed by strategy, universe token, and UTC day (`backend/app/services/screener_service.py:31-42`, `68-69`, `197-227`).
- The response identifies `source: bfinance` but does not include a quote/fundamental as-of timestamp, fiscal statement periods, universe snapshot/version, or per-field source dates (`backend/app/services/screener_service.py:261-268`). The page does not display the response's source field.
- The page requests `max_stocks=50`; its table paginates the returned 25 rows at 20 per page. Search/sorting are client-side.
- **Add to Portfolio** first performs an INR portfolio GET, then POSTs one share using the screen price and a calculated weight (`frontend/src/app/dashboard/screener-studio/page.tsx:163-200`). This mutating path was exercised with a temporary BHARTIARTL.NS row and cleaned up afterward.

## Financial verdicts

| Item | Verdict | Basis |
|---|---|---|
| API/UI count `25 Stocks Found` and 20-row first page | `VERIFIED` (presentation only) | The captured response completed with 200 and the rendered count/pagination agreed. |
| Default strategy identity and description | `VERIFIED` (rendering only) | UI rendered backend-provided Coffee Can metadata; underlying universe/filter execution was not replayed. |
| Displayed price, market cap, P/E, ROCE, ROE, and dividend-yield values | `UNVERIFIABLE` | No direct raw provider payload, field dates, or primary-source reconciliation was captured. |
| Displayed dividend yields such as `305.00%`, `470.00%`, `603.00%`, `627.00%`, and `665.00%` | `UNVERIFIABLE` | The values are directly visible, but this evidence does not establish whether each unit/period is correct; no discrepancy verdict is assigned. |
| Whether every result satisfies the declared ROCE/ROE/market-cap criteria | `UNVERIFIABLE` | Strategy execution was not independently replayed and no raw candidate universe was captured. |
| Source freshness/cache age | `UNVERIFIABLE` | The UI exposes no as-of date and the response contains no provider timestamp. |

## Findings

### SS-001 — Financial screen results lack auditable as-of and field-period provenance

- **Severity:** P2
- **Owner:** backend/provider contract and frontend presentation
- **Evidence:** response source is only `bfinance`; no quote/fundamental date, fiscal period, universe version, or field-level provenance is returned/displayed. The visible yield examples make unit/period provenance especially important.
- **Expected:** return and display data-as-of, statement periods, universe snapshot/version, units, and cache/provider status.

### SS-002 — Seeded accessibility violations

- **Severity:** P2
- **Owner:** frontend/shared sidebar
- **Evidence:**
  - Desktop seeded/historical: `color-contrast` (serious, 1 node) and `heading-order` (moderate, 1).
  - Mobile seeded: `heading-order` (moderate, 1).
- **Files:** `evidence/network/desktop/{seeded,historical}/dashboard-screener-studio.a11y.json`, `evidence/network/mobile/seeded/dashboard-screener-studio.a11y.json`.

### SS-003 — Empty captures end during a cold full-universe run

- **Severity:** P3
- **Owner:** audit/runtime coverage; product owner only if timeout/cancel behavior is proven deficient
- **Evidence:** the coffee-can request had no status in both empty captures while the page displayed its scanning state; subsequent seeded runs completed. No failure or console error was recorded.
- **Expected/next proof:** capture a controlled timeout/failure or allow the cold run to settle before classifying product behavior.

## Pending / not tested

- Mobile historical capture.
- All four remaining built-in strategies.
- Custom-builder open, invalid values, each filter, custom POST, and empty-result behavior.
- Result search, every sortable column, Previous/Next, and peer links.
- Add-to-Portfolio success, duplicate/validation conflict, and persistence/removal.
- Direct raw screen payload, candidate universe, cache provenance, and independent criteria/unit replay.
- Empty-state axe, manual keyboard/focus order, mobile table horizontal-scroll keyboard access, and touch-target measurement.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 12 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-screener-studio-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-screener-studio-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-screener-studio-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-screener-studio-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-screener-studio-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-screener-studio-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Built-in/custom screens | Coffee Can and custom screen POSTs completed. | `../evidence/network/console/desktop/interactions/screener-controls.txt` |
| Add to portfolio | BHARTIARTL.NS was added through the UI and removed after verification. | `../evidence/network/pages/desktop/interactions/screener-add-post-portfolio.json` |
