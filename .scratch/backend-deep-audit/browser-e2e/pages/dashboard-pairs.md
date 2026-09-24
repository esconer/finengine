# Cointegration & Pairs Scanner

**Status:** PARTIAL — scan control, section evidence, and direct replay are complete; exact coint contract/mobile focus remain partial.

> Evidence paths are relative to `browser-e2e/`.

## Route and fixture

- **Route:** `/dashboard/pairs`
- **Isolated stack:** frontend `127.0.0.1:3001`; backend `127.0.0.1:8001`, `environment=testing`.
- **Fixture:** `browser-e2e-five-equity-v1`: RELIANCE.NS ×10, HDFCBANK.NS ×20, TCS.BO ×15, AAPL ×5, MSFT ×4. Historical desktop uses normalized `added_on=2025-01-01`; early seeded captures predate normalization.
- **Automatic parameters:** `lookback_days=252`, `p_value_threshold=0.05`.
- **Method stated by UI/source:** Engle-Granger, Johansen rank tests, OLS hedge ratio, Ornstein-Uhlenbeck half-life, and spread z-score.

## Controls and exercised behavior

| Control / behavior | Source evidence | Browser evidence |
|---|---|---|
| Automatic scan on mount | `frontend/src/app/dashboard/pairs/page.tsx:10-31` | One GET in every captured state. |
| Scan Universe / manual refresh | `page.tsx:45-52` | Present; **not clicked**. |
| Pair table | `page.tsx:62-113` | Ten populated rows in seeded/historical desktop; table is horizontally scrollable on mobile. |
| Error/no-results states | `page.tsx:55-71` | Empty and populated error/no-pair states rendered; manual recovery not tested. |

The page has no visible lookback or threshold control; those values are source constants (`page.tsx:7-8`).

## Desktop and mobile evidence

| State | Desktop 1440×900 | Mobile 390×844 | Observed result |
|---|---|---|---|
| Empty | `evidence/screenshots/desktop/empty/dashboard-pairs.png`; `evidence/network/pages/desktop/empty/dashboard-pairs.txt` | `evidence/screenshots/mobile/empty/dashboard-pairs.png`; `evidence/network/pages/mobile/empty/dashboard-pairs.txt` | Visible `No portfolio positions found` plus no-pairs guidance. |
| Seeded | `evidence/screenshots/desktop/seeded/dashboard-pairs.png`; `evidence/network/pages/desktop/seeded/dashboard-pairs.txt` | `evidence/screenshots/mobile/seeded/dashboard-pairs.png`; `evidence/network/pages/mobile/seeded/dashboard-pairs.txt` | Ten pair rows; every signal is `Not cointegrated`. Mobile shows the first columns and requires horizontal scrolling for the rest. |
| Historical desktop | `evidence/screenshots/desktop/historical/dashboard-pairs.png`; `evidence/network/pages/desktop/historical/dashboard-pairs.txt` | **Not captured** | Same ten rows and p-values after purchase-date normalization. |

The mobile header's rightmost theme icon is visibly clipped at the screenshot edge, and the table is horizontally scrollable. Axe also reports that the scrollable region is not keyboard-focusable; final section evidence is present; horizontal reachability remains untested.

## API, console, and network evidence

| Capture | API | Status | Console / page errors |
|---|---|---|---|
| Empty desktop/mobile | `GET /analytics/coint?lookback_days=252&p_value_threshold=0.05` | 404 | 1 console error each: `No portfolio positions found`. |
| Seeded desktop/mobile | Same GET | 200 | 0 console errors; 0 page errors. |
| Historical desktop | Same GET | 200 | 0 console errors; 0 page errors. |

Primary files:

- `evidence/network/pages/desktop/{empty,seeded,historical}/dashboard-pairs.network.json`
- `evidence/network/pages/mobile/{empty,seeded}/dashboard-pairs.network.json`
- `evidence/network/console/desktop/{empty,seeded,historical}/dashboard-pairs.console.json`
- `evidence/network/console/mobile/{empty,seeded}/dashboard-pairs.console.json`

Backend source returns 404 when no portfolio allocation exists (`backend/app/api/analytics.py:2574-2585`) and otherwise scans the complete supplied portfolio universe.

## Calculations and verdicts

### Captured historical result

Ten rows are shown, matching all `C(5,2)=10` unordered pairs among five holdings. The smallest displayed Engle-Granger p-value is `0.0836` (AAPL / RELIANCE.NS), above the configured `0.05` threshold. All ten signals are therefore rendered as `Not cointegrated`.

| Check | Calculation / comparison | Rendered result | Verdict |
|---|---|---|---|
| Pair coverage | `5 choose 2` | 10 rows | `VERIFIED` |
| Threshold classification | Minimum p-value `0.0836 > 0.05` | All ten `Not cointegrated` | `VERIFIED` from displayed values |
| Half-life rendering | All non-null values render with one decimal and `days` | `5.9` through `35.9` days shown | `VERIFIED` for display formatting |
| Signal/z-score rendering | All non-null z-scores render to two decimals plus σ | e.g. `0.11σ`, `-1.85σ` | `VERIFIED` for display formatting |

### Statistical verdict

- Pair enumeration and threshold/signal consistency: `VERIFIED`.
- Raw Engle-Granger tests, Johansen rank, OLS hedge ratios, OU estimates, and z-scores: `UNVERIFIABLE` without raw price histories/direct payload and independent replay.
- The AAPL current-quote defect does not by itself explain the historical scan result, which uses cached price history; provider/cache freshness still requires source checks.

## Accessibility evidence

No empty-state axe capture exists.

- **Seeded desktop:** `color-contrast` serious (1 node), `heading-order` moderate (1).
- **Seeded mobile:** `heading-order` moderate (1), `scrollable-region-focusable` serious (1).
- **Historical desktop:** `color-contrast` serious (1), `heading-order` moderate (1).
- Manual keyboard/focus and screen-reader checks: **not tested**.

Files: `evidence/network/{desktop,mobile}/seeded/dashboard-pairs.a11y.json` and `evidence/network/desktop/historical/dashboard-pairs.a11y.json`.

## Findings

| ID | Severity | Owner | Evidence-based finding |
|---|---|---|---|
| PR-F01 | **P2** | Backend error contract + frontend empty-state handling | Empty portfolio triggers/logs a 404 and then also shows “No cointegrated pairs found,” combining failure and valid zero-result language. Part of FE-005. |
| PR-F02 | **P2** | Frontend | Mobile table's scrollable region is not keyboard-focusable; desktop/mobile also have contrast and heading-order violations. Part of FE-006. |
| PR-F03 | **P3** | Frontend | Global `Last updated: Never` remains after a successful automatic scan. |
| PR-F04 | **P3** | Frontend responsive layout | The mobile header's rightmost theme control is clipped in the captured viewport; final layout/section proof is pending. |
| PR-F05 | **Verification blocker** | Analytics owner + QA | Manual Scan Universe refresh is `EXERCISED`; exact raw statistical tests remain `UNDERDETERMINED`. |

## Pending / not tested

- Manual Scan Universe refresh, loading transition, and error recovery.
- Direct raw response/price-series capture and independent EG/Johansen/OLS/OU replay.
- Lookback/threshold edge cases and insufficient-history behavior, since no controls are exposed.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-pairs-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-pairs-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-pairs-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-pairs-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-pairs-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-pairs-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Scan control | Scan Universe produced a second 200 cointegration request. | `../evidence/network/console/desktop/interactions/refresh-controls.txt` |
