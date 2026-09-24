# India Microstructure

**Status:** PARTIAL — refresh, section evidence, and direct API capture are complete; source-date/unit validation remains pending.

## Route, fixture, and source identity

- **Route:** `/dashboard/india-flows`
- **Captured:** 2026-09-24 on the isolated testing frontend/backend (`127.0.0.1:3001` / `127.0.0.1:8001`).
- **Frontend build:** `hghBG-hlr8-XxzAq9sTq3`. The working tree was already dirty, so this report does not claim the build is exactly Git HEAD.
- **Fixtures:**
  - **Empty:** 0 portfolio positions.
  - **Seeded:** 5 positions: `RELIANCE.NS`, `HDFCBANK.NS`, `TCS.BO`, `AAPL`, and `MSFT`.
  - **Historical:** the same 5-position synthetic portfolio with purchase dates normalized to `2025-01-01` for analytics history; the captured visible output is the same as the seeded output.
- **Viewports:** desktop `1440×900`; mobile `390×844`.
- Evidence root: `.scratch/backend-deep-audit/browser-e2e/`.

## Coverage and controls

Captured states:

- Desktop empty, seeded, and historical.
- Mobile empty and seeded.
- Mobile historical was not captured.

Visible route controls:

- Shared header: live-data toggle, portfolio PDF export, portfolio refresh, and dark-mode toggle.
- Page-level **Refresh**.
- Read-only sections: FII/DII institutional net flows, delivery-anomaly alerts, and participation-based liquidity/days-to-liquidate.
- No page input, pagination, or destructive control was present.

Observed output:

- Empty and seeded captures both displayed “No institutional flow records available for the last 30 sessions.”
- Both displayed “No >2σ delivery spikes detected in portfolio holdings today,” including the empty-portfolio capture.
- Seeded captures displayed five liquidity rows. The page text/snapshot records `AAPL` as `₹24` and `MSFT` as `₹1,973`, each as `<0.1d` at 10% and 20% ADV and `HIGHLY_LIQUID`.
- The shared header showed `Last updated: Never`. The page separately showed a local “As of” time.

Desktop evidence shows the first part of the liquidity table in the viewport. The mobile seeded viewport ends before the liquidity table. Final internal-scroll sections are present; source-date/unit validation remains pending.

Primary evidence:

- `evidence/screenshots/desktop/{empty,seeded,historical}/dashboard-india-flows.png`
- `evidence/screenshots/mobile/{empty,seeded}/dashboard-india-flows.png`
- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/dashboard-india-flows.txt`
- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/dashboard-india-flows.snapshot.txt`

## API, console, and network evidence

Each of the five captured states issued the same three initial GETs, all with HTTP 200:

1. `GET /api/v1/analytics/india-flows?lookback_days=30`
2. `GET /api/v1/analytics/delivery-anomalies`
3. `GET /api/v1/analytics/liquidity-limits`

| State | API requests | Bad/missing status | Console messages | Page errors |
|---|---:|---:|---:|---:|
| Desktop empty | 3 | 0 | 0 | 0 |
| Desktop seeded | 3 | 0 | 0 | 0 |
| Desktop historical | 3 | 0 | 0 | 0 |
| Mobile empty | 3 | 0 | 0 | 0 |
| Mobile seeded | 3 | 0 | 0 | 0 |

The page uses `Promise.all`, so one failed request would put the whole page into its error state. The captures show the successful path only; no page-level **Refresh** click or controlled provider/database failure was recorded. Network evidence contains request metadata but no direct raw response bodies for these three endpoints.

Evidence:

- `evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/dashboard-india-flows.network.json`
- `evidence/network/console/{desktop,mobile}/{empty,seeded,historical}/dashboard-india-flows.console.json`
- `evidence/network/console/{desktop,mobile}/{empty,seeded,historical}/dashboard-india-flows.errors.json`

## Source and freshness review

- `frontend/src/app/dashboard/india-flows/page.tsx:15-35` fetches all three endpoints and sets `lastUpdated` to the browser's current time after the requests resolve. That timestamp is a fetch-completion time, not a provider/session as-of time.
- The rendered “As of” label therefore does not prove that the newest NSE flow or bhavcopy row belongs to that time (`frontend/src/app/dashboard/india-flows/page.tsx:50-55`).
- `backend/app/api/analytics.py:2624-2643` returns the latest stored FII/DII rows. The service returns row dates, but the captured isolated fixture had no rows.
- `backend/app/api/analytics.py:2646-2686` returns only the filtered anomaly list/count. The empty-portfolio path returns an empty list, and the UI renders that as “no spikes.” The filtered anomaly object also omits the source row date (`backend/app/services/india_data_service.py:320-357`).
- Liquidity uses up to 60 calendar days of price history and the trailing 30 observations for ADV (`backend/app/api/analytics.py:2723-2737`, `backend/app/services/india_data_service.py:367-445`). The service returns `data_status`, portfolio-level metrics, and per-position provenance, but the page displays only a subset and does not show the status or history endpoints.
- The page renders every `position_value` with a rupee sign (`frontend/src/app/dashboard/india-flows/page.tsx:179-203`). The audit already confirmed that portfolio position monetary fields remain native while envelope totals/weights are converted. Consequently, the observed AAPL/MSFT rows are native USD values mislabeled as INR.

## Financial verdicts

| Item | Verdict | Basis |
|---|---|---|
| Empty portfolio: “No >2σ delivery spikes detected in portfolio holdings today” | `DISCREPANCY` | There were no portfolio holdings; an empty result is not evidence of a normal delivery signal. |
| Seeded delivery-anomaly result | `UNVERIFIABLE` | An empty anomaly list can mean normal, insufficient history, unavailable NSE data, or no applicable rows; the page exposes no status/date. |
| FII/DII “no records” message | `UNVERIFIABLE` | It accurately describes the isolated capture but does not establish real-market absence. |
| AAPL/MSFT values shown with `₹` | `DISCREPANCY` | Visible values are native USD position values mislabeled as INR; see `frontend-bugs.md` FE-001 and `backend-bugs.md` BE-001. |
| `<0.1d` / `HIGHLY_LIQUID` verdicts | `UNVERIFIABLE` | No direct raw histories, ADV periods, or `data_status` payload were captured; AAPL also inherits the confirmed bad-quote issue. |

## Findings

### IF-001 — US position values are mislabeled as INR

- **Severity:** P1
- **Owner:** frontend primary; backend contract ambiguity contributes
- **Evidence:** seeded text/snapshot show `AAPL ₹24` and `MSFT ₹1,973`; `frontend/src/app/dashboard/india-flows/page.tsx:197` hard-codes `₹`; `frontend-bugs.md` FE-001 / `backend-bugs.md` BE-001 document the native/base contract.
- **Expected:** render native values with their actual currency or use explicitly converted base-currency position values.

### IF-002 — Empty/unavailable anomaly data is presented as a normal “no spikes” result

- **Severity:** P2
- **Owner:** frontend and backend analytics contract
- **Evidence:** empty capture displays the normal-signal sentence with 0 positions; backend returns an empty list for no tickers and the page ignores count/status.
- **Expected:** show “no holdings,” “insufficient history,” or “provider unavailable” separately from “no anomaly detected.”

### IF-003 — “As of”/“today” wording lacks source-date provenance

- **Severity:** P2
- **Owner:** backend data contract and frontend presentation
- **Evidence:** the page stores `new Date()` after fetch; the delivery response omits the source row date; `data-freshness-bugs.md` lists India dates/units as pending.
- **Expected:** expose and display the latest source session date and provider/fetch metadata.

### IF-004 — Seeded accessibility violations

- **Severity:** P2
- **Owner:** frontend
- **Evidence:**
  - Desktop seeded axe: 2 rule violations / 3 nodes — `color-contrast` (serious, 2 nodes) and `heading-order` (moderate, 1).
  - Mobile seeded axe: 3 rule violations / 3 nodes — `color-contrast` (serious, 1), `heading-order` (moderate, 1), and `scrollable-region-focusable` (serious, 1).
- **Files:** `evidence/network/{desktop,mobile}/seeded/dashboard-india-flows.a11y.json`.

### IF-005 — Mobile header clips the dark-mode control

- **Severity:** P2
- **Owner:** frontend shared header/layout
- **Evidence:** `evidence/screenshots/mobile/seeded/dashboard-india-flows.png` shows the dark-mode control cut off at the right viewport edge.
- **Expected:** all header actions remain visible and keyboard reachable at `390×844`.

## Pending / not tested

- Mobile historical capture.
- Page-level **Refresh** behavior and request replacement.
- Populated FII/DII and delivery-anomaly fixtures, including source-session alignment.
- Provider failure, loading timeout, and database-unavailable states.
- Direct raw endpoint responses and independent replay of ADV, z-scores, and liquidation days.
- Empty-state axe, manual keyboard/focus order, touch-target measurement, and screen-reader testing.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-india-flows-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-india-flows-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-india-flows-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-india-flows-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-india-flows-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-india-flows-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Refresh control | Refresh produced second India-flow, delivery, and liquidity-limit requests. | `../evidence/network/console/desktop/interactions/refresh-controls.txt` |
