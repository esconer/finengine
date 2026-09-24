# Liquidity Analysis

**Status:** PARTIAL — section evidence, refresh fan-out, and measured-liquidity replay are complete; heuristic exact contract and manual controls remain partial.

> Evidence paths are relative to `browser-e2e/`.

## Route and fixture

- **Route:** `/dashboard/liquidity`
- **Isolated stack:** frontend `127.0.0.1:3001`; backend `127.0.0.1:8001`, `environment=testing`.
- **Fixture:** `browser-e2e-five-equity-v1`: RELIANCE.NS ×10, HDFCBANK.NS ×20, TCS.BO ×15, AAPL ×5, MSFT ×4. Historical desktop uses normalized `added_on=2025-01-01`; early seeded captures predate that normalization.
- **Data caveat:** the page consumes 30-day price/volume history plus quote market-cap fields. The known AAPL `$4.89` quote defect can contaminate quote-derived market-cap/current inputs; the upstream provider/as-of field is not exposed in this page.
- **Viewports:** desktop `1440×900`; mobile `390×844`.

## Controls and exercised behavior

| Control / behavior | Source evidence | Browser evidence |
|---|---|---|
| Fetch portfolio and liquidity on mount; refetch liquidity when positions change | `frontend/src/app/dashboard/liquidity/page.tsx:275-327` | Portfolio GET plus multiple liquidity GETs captured. |
| Page-specific Refresh | `frontend/src/app/dashboard/liquidity/page.tsx:329-331,579-587` | Present on desktop. It is inside `hidden md:flex`, so the page-specific action is absent at 390px. Manual click not tested. |
| Try Again on payload error | `frontend/src/app/dashboard/liquidity/page.tsx:595-609` | Present in empty capture; not clicked. |
| Metric/column explainers | `frontend/src/app/dashboard/liquidity/page.tsx:37-135,217-230` | Present; not opened. |
| Position search | `frontend/src/app/dashboard/liquidity/page.tsx:815-821` | Rendered through `DataTable`; not exercised. |
| Export CSV | `frontend/src/app/dashboard/liquidity/page.tsx:383-404,806-812` | Present; not exercised. |

## Desktop and mobile evidence

| State | Desktop 1440×900 | Mobile 390×844 | Observed result |
|---|---|---|---|
| Empty | `evidence/screenshots/desktop/empty/dashboard-liquidity.png`; `evidence/network/pages/desktop/empty/dashboard-liquidity.txt` | `evidence/screenshots/mobile/empty/dashboard-liquidity.png`; `evidence/network/pages/mobile/empty/dashboard-liquidity.txt` | API returned a payload with an `error`, but UI simultaneously showed `5.0/10`, `Medium`, `5-10 days`, `HIGH RISK`, and “zero severe liquidity traps detected.” |
| Seeded | `evidence/screenshots/desktop/seeded/dashboard-liquidity.png`; `evidence/network/pages/desktop/seeded/dashboard-liquidity.txt` | `evidence/screenshots/mobile/seeded/dashboard-liquidity.png`; `evidence/network/pages/mobile/seeded/dashboard-liquidity.txt` | `9.8/10`, `Low`, `1-2 days`, five high-liquidity positions. |
| Historical desktop | `evidence/screenshots/desktop/historical/dashboard-liquidity.png`; `evidence/network/pages/desktop/historical/dashboard-liquidity.txt` | **Not captured** | Same seeded values and table after purchase-date normalization. |

The mobile hero omits the page-specific refresh control, as confirmed by source and screenshot. The shared top-bar refresh remains visible, but it was not tested as a substitute for this control.

## API, console, and network evidence

| Capture | Observed API traffic | Status | Console / page errors |
|---|---|---|---|
| Empty desktop/mobile | 1 portfolio GET + 1 `GET /analytics/liquidity` | Both 200 | 0 console errors; 0 page errors. The UI error came from the 200 payload. |
| Seeded desktop | 1 portfolio GET + **3** `GET /analytics/liquidity` records | Portfolio 200; all three liquidity records lacked captured status | 0 console errors; 0 page errors. |
| Seeded mobile | 1 portfolio GET + 3 liquidity GETs | All four 200 | 0 console errors; 0 page errors. |
| Historical desktop | 1 portfolio GET + 3 liquidity GETs | All four 200 | 0 console errors; 0 page errors. |

Primary files:

- `evidence/network/pages/desktop/seeded/dashboard-liquidity.network.json`
- `evidence/network/pages/mobile/seeded/dashboard-liquidity.network.json`
- `evidence/network/pages/desktop/historical/dashboard-liquidity.network.json`
- `evidence/network/console/{desktop,mobile}/{empty,seeded}/dashboard-liquidity.console.json`
- `evidence/network/console/desktop/historical/dashboard-liquidity.console.json`

The source invokes liquidity once on mount and again when `positions` changes (`page.tsx:318-327`). That explains duplicate work in principle, but the exact reason for three captured liquidity requests remains **not fully isolated**, although duplicate fan-out is reproducible.

## Calculations and verdicts

### Display/backend consistency

| Check | Calculation / source | Rendered result | Verdict |
|---|---|---|---|
| Overall score | Backend uses a simple arithmetic mean of constituent scores; displayed scores `10,10,10,10,9.1` average to `9.82` | `9.8/10` | `VERIFIED` at one-decimal precision |
| Risk mapping | Backend maps score `>=8` to Low and `1-2` days | `Low`, `1-2 days` | `VERIFIED` |
| Distribution | 5 high + 0 medium + 0 low | `5 (100.0%)`, `0 (0.0%)`, `0 (0.0%)` | `VERIFIED` |

### Methodology discrepancy

- The page explainer says the overall score aggregates constituent scores **weighted by trading volume, daily turnover, and market capitalization** (`frontend/src/app/dashboard/liquidity/page.tsx:38-45`).
- The backend actually computes `np.mean([...constituent scores])` at `backend/app/services/analytics_engine.py:400-403`; volume and market cap affect each tier score, not the final cross-position weighting.
- **Verdict:** `DISCREPANCY` in methodology copy/contract.

### Empty-state discrepancy

- Backend empty payload is explicitly `overall_score=5.0`, `liquidation_time_days="5-10"`, `risk_level="Medium"`, plus `error="No portfolio positions found"` (`backend/app/api/analytics.py:1091-1101`).
- The hero repeats Medium, while the assessment card classifies any score below 6 as `HIGH RISK`, and the execution card says all holdings are healthy even though there are zero holdings.
- **Verdict:** `DISCREPANCY`; empty portfolio should be unavailable, not a scored portfolio.

### Financial/model verdict

Raw volume windows, market-cap payloads, spreads, and liquidation calculations were not independently replayed: `UNVERIFIABLE`. AAPL quote-derived market-cap input is additionally conditional on BE-002.

## Accessibility evidence

No empty-state axe capture exists.

- **Seeded desktop:** `aria-prohibited-attr` serious (1 node), `color-contrast` serious (1).
- **Seeded mobile:** `heading-order` moderate (1), `nested-interactive` serious (7).
- **Historical desktop:** `color-contrast` serious (1), `heading-order` moderate (1), `nested-interactive` serious (7).
- Manual keyboard/focus and screen-reader checks: **not tested**.

Files: `evidence/network/{desktop,mobile}/seeded/dashboard-liquidity.a11y.json` and `evidence/network/desktop/historical/dashboard-liquidity.a11y.json`.

## Findings

| ID | Severity | Owner | Evidence-based finding |
|---|---|---|---|
| LQ-F01 | **P2** | Backend API contract + frontend empty-state handling | Empty portfolio returns scored/risk data together with an error; UI presents contradictory Medium/High/healthy verdicts instead of N/A. |
| LQ-F02 | **P2** | Frontend copy; backend methodology contract owner | UI claims volume/turnover/market-cap-weighted overall aggregation, while backend uses an unweighted mean of constituent scores. |
| LQ-F03 | **P2** | Frontend request orchestration | Three liquidity GETs were captured in each populated baseline, with three status-missing records in seeded desktop. Mount + positions-effect calls are a confirmed duplication path. |
| LQ-F04 | **P3** | Frontend responsive UI | Page-specific Refresh is hidden below the `md` breakpoint; mobile has no in-page refresh control. |
| LQ-F05 | **P2** | Frontend | Axe evidence includes prohibited ARIA, nested interactive controls, contrast, and heading-order violations. Part of FE-006. |
| LQ-F06 | **P1 input dependency** | Backend quote/data path | AAPL `$4.89` can contaminate market-cap-derived liquidity evidence. Existing BE-002/DF-001 dependency. |

## Pending / not tested

- Manual refresh, Try Again, search, CSV, explainer dialogs, and partial-provider failure.
- Exact duplicate-request timing/identity and whether it changes provider/cache load.
- Independent replay from raw 30-day OHLCV and market-cap payloads.
- Historical mobile state.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-liquidity-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-liquidity-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-liquidity-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-liquidity-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-liquidity-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-liquidity-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Refresh/fan-out | Duplicate initial GETs and explicit refresh behavior captured. | `../evidence/network/pages/desktop/seeded/dashboard-liquidity.network.json` |
| Direct replay | Measured-liquidity basis checked; exact heuristic contract remains underdetermined. | `../evidence/calculations/outputs/independent-core-models.md` |
