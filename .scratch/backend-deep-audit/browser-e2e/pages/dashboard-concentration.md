# Concentration — Page Report

**Status:** PARTIAL — section evidence and independent concentration replay are complete; refresh/export/manual a11y remain partial.
**Route:** `/dashboard/concentration`  
**Audit date:** 2026-09-24  
**Evidence stack:** isolated production frontend on `127.0.0.1:3001` and testing backend on `127.0.0.1:8001`.

> Evidence paths beginning `../evidence/` are relative to this report. Existing evidence only was used; no new browser/API/network call was made.

## Route and fixture

- **Empty:** zero positions.
- **Seeded:** five synthetic cash equities across INR/USD: RELIANCE.NS, HDFCBANK.NS, TCS.BO, AAPL, and MSFT.
- **Historical:** same fixture with `added_on=2025-01-01`.
- Concentration uses current base-currency market-value weights, not purchase-date weights.
- **Viewports:** desktop `1440×900`; mobile `390×844`.
- App scrolling is internal; the final section set is present.

## Coverage

| State | Desktop | Mobile | Notes |
|---|---|---|---|
| Empty | `../evidence/screenshots/desktop/empty/dashboard-concentration.png` | `../evidence/screenshots/mobile/empty/dashboard-concentration.png` | False safety verdicts captured |
| Five-position seeded | `../evidence/screenshots/desktop/seeded/dashboard-concentration.png` | `../evidence/screenshots/mobile/seeded/dashboard-concentration.png` | Metrics/table/charts captured |
| Historical holding-date state | `../evidence/screenshots/desktop/historical/dashboard-concentration.png` | Not captured | Same concentration output as seeded |
| Refresh / CSV / help / search | **Not tested** | **Not tested** | Controls visible only |
| Final internal-scroll sections | 13 desktop captures | 13 mobile captures | See **Final internal-scroll evidence** |

Text/raw evidence: `../evidence/network/pages/desktop/{empty,seeded,historical}/dashboard-concentration.txt` and `../evidence/network/pages/desktop/states/concentration-api.json`.

## Executive verdict

- For the five returned quote weights, the concentration endpoint is arithmetically correct: HHI, N_eff, normalized diversification, top-N weights, and Gini reconcile under independent Decimal replay.
- The result is only conditionally correct for FinEngine's returned quotes. AAPL's quote is materially wrong, and current values lack provider/as-of provenance.
- Empty state is financially misleading: the API returns zeros plus an error, but the page ignores the error and declares “Well Diversified,” “Risk Managed,” and a safely controlled 0% largest position.
- Seeded narrative is internally contradictory: HHI 0.60, 75.8% largest position, and 94.1% top-three are paired with “good diversification” and “all position weights within standard risk limits,” while the same page says High Concentration Risk.
- Seeded loads issue three identical concentration requests; axe reports contrast and heading-order defects.

## Visible behavior

### Empty

- Effective Positions: `0.0 of 0`; Diversification Score: `0%`.
- Largest Position, Top 3, HHI, and Effective Positions all render `0.0%` / `0.00`.
- Lorenz chart draws an empty 0%→100% equal-weight line.
- Risk assessment says:
  - “Well Diversified”
  - “All position weights within standard risk limits”
  - “Risk Managed”
- Insights say the largest holding is safely below 15%.
- This is the confirmed false safety state `FE-004`.
- Text: `../evidence/network/pages/desktop/empty/dashboard-concentration.txt` and `../evidence/network/pages/mobile/empty/dashboard-concentration.txt`.

### Seeded/historical

- Effective Positions: `1.7 of 5`.
- Diversification Score: `50.5%`.
- Largest Position: `75.8%` (MSFT).
- Top 3 Holdings: `94.1%`.
- HHI: `0.60` (raw API 0.5956).
- Effective Positions: `1.68`.
- Sector bars:
  - Technology 75.8%
  - Information Technology 12.5%
  - Financial Services 5.8%
  - Energy 4.9%
  - AAPL's 0.9% remains under Unknown and is filtered from the visible sector panel.
- Position rows:
  - MSFT 75.8%, cumulative 75.8%, High
  - TCS.BO 12.5%, cumulative 88.3%, Medium
  - HDFCBANK.NS 5.8%, cumulative 94.1%, Low
  - RELIANCE.NS 4.9%, cumulative 99.1%, Low
  - AAPL 0.9%, cumulative 100.0%, Low, Unknown sector
- Risk assessment says “Moderate Diversification,” but its paragraph says “Portfolio shows good diversification.” The Monitor card says all weights are within limits, while the same page reports High Concentration Risk.
- Full text: `../evidence/network/pages/desktop/seeded/dashboard-concentration.txt` and `../evidence/network/pages/desktop/historical/dashboard-concentration.txt`.

## Controls and interaction evidence

| Control | Evidence status |
|---|---|
| Refresh | Visible; **not exercised** |
| CSV Export | Visible; **not exercised** |
| Metric/table help modals | Multiple visible; **not exercised** |
| Position table search/pagination | Visible; **not exercised** |
| Global Live/PDF/refresh/dark-mode/menu | Visible; **not exercised** |

Source: `frontend/src/app/dashboard/concentration/page.tsx:347-450` and `frontend/src/app/dashboard/concentration/page.tsx:603-971`.

## Financial verdicts

### Seeded returned-quote arithmetic

| Value | Independent result | Observed/API | Verdict |
|---|---:|---:|---|
| Largest position | 75.762916% | 75.762916% | `VERIFIED` |
| Top 3 | 94.149617% | 94.149617% | `VERIFIED` |
| HHI | 0.5956494140543129 | 0.5956 | `VERIFIED` |
| Effective positions `1/HHI` | 1.6788398954 | 1.68 | `VERIFIED` |
| N-normalized diversification | 50.543823% | 50.5 | `VERIFIED` |
| Gini | 0.6291164895 | 0.629 | `VERIFIED` |
| Weight sum | 1.0 | 1.0 | `VERIFIED` |
| Sector weights sum | 1.0 | 1.0 | `VERIFIED` |

Source formula: `HHI = Σw²`, `N_eff = 1/HHI`, and diversification `(1-HHI)/(1-1/N)` in `backend/app/services/analytics_engine.py:241-309`.

### Qualifications and UI verdicts

| Value/behavior | Verdict | Qualification |
|---|---|---|
| Seeded concentration metrics | `VERIFIED` for FinEngine's returned current quotes | Not externally certified because AAPL quote is wrong and other prices are timing-sensitive |
| True real-market concentration | `UNVERIFIABLE` | No official exchange/issuer numeric certification and no provider/as-of metadata |
| AAPL contribution | `DISCREPANCY` input | AAPL is 0.94% weight only because its $4.89 quote is materially wrong |
| Empty HHI/largest/top-N values | `DISCREPANCY` presentation | API carries `error: No portfolio positions found`; page should show N/A, not zero/safe |
| Empty “Well Diversified/Risk Managed” | `DISCREPANCY` | False safety verdict for no holdings |
| Seeded “good diversification/all within limits” copy | `DISCREPANCY` | Contradicts HHI 0.60, 75.8% largest, 94.1% top-three, and High Concentration Risk |
| “Moderate Diversification” heading | `NOT TESTED` as policy | No documented threshold policy establishes this label |
| Sector classification | `UNVERIFIABLE` | AAPL is Unknown; provider/industry classifications were not independently certified |

## API, network, and console

- Empty desktop/mobile: one portfolio GET (200) and one concentration GET (200). The concentration response contains an error field but is rendered as a normal zero payload.
- Seeded desktop/mobile and historical desktop: one portfolio GET plus three identical completed `GET /analytics/concentration` calls, all HTTP 200.
- Current source explains the duplication pattern: mount calls `fetchPortfolio()` and `fetchConcentrationData()`, then a positions-state effect calls concentration again (`frontend/src/app/dashboard/concentration/page.tsx:438-447`).
- No console errors or warnings were recorded.
- Raw concentration payload: `../evidence/network/pages/desktop/states/concentration-api.json`.
- Primary network files: `../evidence/network/pages/desktop/empty/dashboard-concentration.network.json` and `../evidence/network/pages/desktop/seeded/dashboard-concentration.network.json`.

## Accessibility and responsive evidence

### Axe

- Seeded desktop: `color-contrast` serious (1) and `heading-order` moderate (1).
- Seeded mobile: `heading-order` moderate (1).
- Historical desktop repeats both desktop rules.
- No empty-state axe run exists.

Evidence: `../evidence/network/desktop/seeded/dashboard-concentration.a11y.json`, `../evidence/network/mobile/seeded/dashboard-concentration.a11y.json`, and `../evidence/network/desktop/historical/dashboard-concentration.a11y.json`.

### Responsive

- Desktop first viewport shows four metric cards and side-by-side Lorenz/sector panels.
- Mobile stacks cards/panels; the 390px header clips the far-right dark-mode icon in the captured image.
- Manual touch scrolling, tooltips, and focus order are pending.

## Findings

### CONC-01 — Empty portfolio produces false safety verdicts

- **Severity:** P2
- **Owner:** frontend primary; backend empty payload contributes
- **Observed:** Zero-valued metrics are displayed as 0%, followed by Well Diversified, Risk Managed, and “safely below” language.
- **Expected:** Treat the endpoint error/empty state as N/A and suppress safety/limit conclusions.
- **Evidence:** `../evidence/network/pages/desktop/empty/dashboard-concentration.txt`.

### CONC-02 — Seeded risk narrative contradicts the numbers

- **Severity:** P2
- **Owner:** frontend
- **Observed:** HHI 0.60, largest 75.8%, top-three 94.1%, MSFT High, and High Concentration Risk coexist with “good diversification” and “all position weights within standard risk limits.”
- **Source:** `frontend/src/app/dashboard/concentration/page.tsx:852-907`.
- **Expected:** Generate all assessment copy from the same threshold outcomes and avoid unconditional “good”/“within limits” text.

### CONC-03 — Concentration depends on a materially wrong AAPL quote

- **Severity:** P1 inherited data risk
- **Owner:** backend quote-acceptance/data-service path
- **Observed:** API arithmetic is correct, but AAPL's 0.94% weight is derived from $4.89 rather than a credible current quote.
- **Expected:** Validate quote scale/currency/provider before persistence and expose as-of provenance.

### CONC-04 — Three identical concentration calls per seeded load

- **Severity:** P3
- **Owner:** frontend
- **Expected:** Coalesce mount/store-hydration fetches and use the request sequence guard already present to prevent redundant work.

### CONC-05 — Contrast and heading hierarchy defects

- **Severity:** P2
- **Owner:** frontend
- **Expected:** Repair the active-sidebar description contrast and use a valid heading hierarchy.

### CONC-06 — Mobile header control clipping

- **Severity:** P2/P3
- **Owner:** frontend
- **Observed:** At 390px, the far-right dark-mode control is partially clipped in the Concentration capture.
- **Limitation:** Reachability and final scrolled layout are not tested.

## Reproduction summary

1. Use the isolated testing stack and empty portfolio; open `/dashboard/concentration` and verify zero metrics plus false safe verdicts.
2. Seed the five-position fixture; compare the page with `../evidence/network/pages/desktop/states/concentration-api.json` and `../evidence/calculations/outputs/portfolio-reconciliation.md`.
3. Inspect network evidence for three identical concentration calls.
4. Compare the risk-assessment cards with the largest/top-three/HHI values and row risk labels.
5. Run axe at 1440×900 and 390×844 and inspect the 390px header.

## Pending / not tested

- Refresh, CSV export, help modals, search, pagination, and chart tooltips.
- Single-holding route-specific concentration capture beyond the shared 0% diversification invariant.
- External/provider validation of prices, sectors, quote timestamps, and classification policy.
- Model replay is complete for returned weights; final real-market revalidation after quote correction is still required.
- Controlled provider/database failures, stale response races, and WebSocket behavior.
- Manual keyboard, focus, screen-reader, zoom, touch, and horizontal-overflow validation.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-concentration-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-concentration-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-concentration-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-concentration-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-concentration-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-concentration-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Direct replay | HHI/effective-holdings/Gini arithmetic matched API for returned quotes; Dashboard heuristic remains discrepant. | `../evidence/calculations/outputs/independent-core-models.md` |
