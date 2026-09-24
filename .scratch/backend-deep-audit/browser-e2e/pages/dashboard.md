# Portfolio Summary — Page Report

**Status:** PARTIAL — CRUD, currency, section, controlled-failure, and runtime evidence are complete; direct model certification and manual a11y remain partial.
**Route:** `/dashboard`  
**Audit date:** 2026-09-24  
**Evidence stack:** isolated production frontend on `127.0.0.1:3001` and testing backend on `127.0.0.1:8001`.

> Evidence paths beginning `../evidence/` are relative to this report. This report uses existing captures and source only; no new browser, API, or network call was made.

## Route and fixture

- **Empty state:** zero positions and zero portfolio value.
- **Seeded state:** synthetic five-cash-equity portfolio:
  - RELIANCE.NS: 10 @ ₹1,000
  - HDFCBANK.NS: 20 @ ₹500
  - TCS.BO: 15 @ ₹2,500
  - AAPL: 5 @ $150
  - MSFT: 4 @ $300
- **Historical state:** the same fixture with `added_on` normalized to `2025-01-01`. Earlier seeded captures show `2026-09-24`; those early states are not acquisition-date evidence. See `../evidence/runtime/synthetic-fixture.json`.
- **Viewports:** desktop `1440×900`; mobile `390×844`.
- The recorded build came from a dirty working tree and is not claimed to equal Git HEAD. Current source is used only to explain observed behavior.

## Coverage

| State | Desktop | Mobile | Notes |
|---|---|---|---|
| Empty | `../evidence/screenshots/desktop/empty/dashboard.png` | `../evidence/screenshots/mobile/empty/dashboard.png` | Full page text captured; viewport image only |
| Five-position seeded | `../evidence/screenshots/desktop/seeded/dashboard.png` | `../evidence/screenshots/mobile/seeded/dashboard.png` | Baseline image still shows upper-card skeletons |
| Historical holding-date state | `../evidence/screenshots/desktop/historical/dashboard.png` | Not captured | Performance chart present; upper cards still loading in image |
| Final internal-scroll sections | 13 desktop captures | 13 mobile captures | See **Final internal-scroll evidence** |

## Executive verdict

- The route renders and its shared analytics calls mostly complete, but it is **not financially trustworthy for the mixed-currency fixture**.
- Confirmed P1 defects: mixed-currency P&L, currency-mixed diversification, a materially wrong AAPL quote, and US-ticker region inference through Add Position.
- Empty state gives a false `0.0%` diversification value and makes an unavailable risk-contribution request that returns 404 and logs an error.
- Seeded and historical screenshots are not settled end-to-end evidence: upper metric cards remain skeletons, and the app scrolls inside `<main>`.

## Visible behavior by state

### Empty

- Header: `0 positions`, `Last updated: Never`, `Live`, Export PDF, refresh, dark-mode controls.
- Overview: `₹0.00` total value, `+₹0.00` unrealized P&L, annual volatility `N/A`, diversification `0.0%`.
- Risk metrics are `N/A`/Unknown and performance/sector say no data.
- Market regime still renders `Crisis — 97% stability`; this external/model state is not independently validated in this report.
- Text evidence: `../evidence/network/pages/desktop/empty/dashboard.txt` and `../evidence/network/pages/mobile/empty/dashboard.txt`.

### Five-position seeded

- Header and hero show five positions and `Last updated: Just now`.
- Top risk drivers render MSFT 96%, TCS.BO 3%, HDFCBANK.NS 0%.
- Portfolio health renders diversification 18.7%, weight drift 0.0%, and five sectors.
- A separate settled state capture records total value near ₹2.50 lakh, unrealized P&L `+₹1,90,377.31` / `+320.23%`, diversification 18.7%, and the same risk drivers: `../evidence/network/pages/desktop/issues/add-malformed-ticker.txt`.

### Historical

- Portfolio performance renders `Total Return +21.41%` with dates from July through September 2026.
- This is not independently verified: mixed-currency historical portfolio returns require daily historical FX, which was not captured.
- Some section captures still show skeletons; the final section set is present, so an infinite-loading defect is not asserted.
- Text evidence: `../evidence/network/pages/desktop/historical/dashboard.txt`.

## Controls and interaction evidence

| Control | Visible/source evidence | Runtime evidence |
|---|---|---|
| Header Live toggle | Present | **Not exercised** |
| Header Export PDF | Present; disabled when no positions | **Not exercised** |
| Header refresh | Present | **Not exercised** |
| Dark mode / sidebar collapse / mobile menu | Present | **Not exercised** |
| Hero refresh | Present; icon-only | **Not exercised** |
| Regime and Top Risk Drivers links | Present | Navigation not exercised in this route pass |
| Portfolio performance / sector charts | Present | Visual hover, empty/loading, and data provenance not tested |
| Position table search, sort, pagination | Present | **Not exercised** |
| Table Export CSV | Present | **Not exercised** |
| Add Position modal | Present | **Exercised**; validation captures and AAPL submission exist |
| Quick Actions: Add, Risk Analytics, Rebalance, Stress Test | Present | Quick-action navigation not exercised; destination routes have separate reports |

Current control wiring is in `frontend/src/app/dashboard/page.tsx:57-267` and `frontend/src/app/dashboard/page.tsx:286-617`.

## Financial verdicts

| Value/behavior | Verdict | Evidence and qualification |
|---|---|---|
| Empty total value/P&L | `VERIFIED` as zero-state arithmetic | Both render ₹0.00 for an empty book |
| First position: 100% weight | `VERIFIED` | 10 × ₹1,227 = ₹12,270; observed 100.00% |
| First position cost/P&L | `VERIFIED` | ₹10,000 cost; +₹2,270 P&L; +22.70% |
| API INR envelope total | `VERIFIED` | ₹249,827.31377746275; Decimal replay error ≈ `1.8e-11` |
| API USD envelope total | `VERIFIED` | $2,603.8596547198676; reciprocal-FX replay error ≈ `2.5e-13` USD |
| Dashboard five-position P&L | `DISCREPANCY` | Displays +₹190,377.31 / +320.23%; same-current-FX reference is +₹5,234.5644 / ≈2.14%. True historical-FX P&L remains `UNVERIFIABLE`. |
| Dashboard diversification | `DISCREPANCY` | Displays 18.7%; concentration API and independent replay produce HHI 0.5956, N_eff 1.68, score 50.5% for returned quotes |
| Empty diversification | `DISCREPANCY` | Displays 0.0%; empty portfolio should be N/A/unavailable |
| RELIANCE.NS quote | `STALE` | ₹1,227 versus secondary observation near ₹1,238.40 |
| HDFCBANK.NS quote | `VERIFIED` within intraday timing tolerance | ₹730 versus secondary range ₹727.70–₹729.80 |
| TCS.BO quote | `VERIFIED` within intraday timing tolerance | ₹2,089 versus secondary observation ₹2,090.60 |
| MSFT quote | `STALE` / timing-sensitive | $493.19 versus $495.07 observation |
| AAPL quote/value | `DISCREPANCY` | $4.89 and $24.45 versus secondary observations near $336.16; approximately 98.5% low |
| Historical +21.41% return | `UNVERIFIABLE` | No daily historical FX series or independent performance replay |
| Annual volatility, forecast VaR, Sharpe, risk-driver percentages, regime | `PARTIAL` | Direct API replay completed where exposed; exact mixed-FX historical contracts remain underdetermined |

Independent calculations: `../financial-reconciliation.md` and `../evidence/calculations/outputs/portfolio-reconciliation.md`.

## API, network, and console

- **Empty desktop/mobile:** three recorded API calls: portfolio (200), regime (200), risk contribution (404). The 404 is expected to be unavailable for an empty book but still creates one console error.
- **Seeded desktop/mobile and historical desktop:** ten completed API calls, all HTTP 200 in the deduplicated response evidence; no console errors.
- Recorded Dashboard calls include portfolio, regime, risk contribution, summary, realized risk, forecast risk, factor exposure, concentration, risk score, and 90-day performance history.
- The shared hook currently requests seven analytics resources in parallel: `frontend/src/hooks/useAnalytics.ts:34-82`. The exact captured request set is preserved in the network JSON rather than inferred from current source.
- `GET /portfolio` is not a strict read: current backend code refreshes and commits quotes, as documented in `../backend-bugs.md` (`BE-006`).

Primary evidence:
- `../evidence/network/pages/desktop/empty/dashboard.network.json`
- `../evidence/network/pages/desktop/seeded/dashboard.network.json`
- `../evidence/network/pages/desktop/historical/dashboard.network.json`
- `../evidence/network/console/desktop/empty/dashboard.console.json`

## Accessibility and responsive evidence

### Axe

- **Seeded desktop:** 3 rules — `button-name` critical (1), `color-contrast` serious (2), `heading-order` moderate (1).
- **Seeded mobile:** `heading-order` moderate (1); one incomplete color-contrast review item.
- **Historical desktop:** the same 3 rules, with 3 color-contrast nodes.
- The unnamed button is the hero refresh icon at `frontend/src/app/dashboard/page.tsx:308-315`.
- Heading order skips from the page H1 to lower-level section headings; metric/chart components also use `h3` without an intervening `h2`.
- No empty-state axe run exists.

Evidence: `../evidence/network/desktop/seeded/dashboard.a11y.json`, `../evidence/network/mobile/seeded/dashboard.a11y.json`, and `../evidence/network/desktop/historical/dashboard.a11y.json`.

### Desktop/mobile

- Desktop shows a fixed 256px sidebar, header, hero, four-column metric grid, two-column charts, and a wide position table.
- Mobile reflows the hero and metrics to one column. The first viewport remains readable.
- Manual keyboard/focus, zoom, and screen-reader testing are pending.

## Findings

### DASH-01 — Mixed-currency P&L subtracts incompatible monetary units

- **Severity:** P1
- **Owner:** frontend primary; backend native/base contract ambiguity contributes
- **Observed:** Converted current value is compared with a raw sum of INR and USD `quantity × buy_price` costs.
- **Expected:** Convert current value and cost basis into the same declared base currency before subtraction and percentage calculation.
- **Reproduction:** Seed the five-position fixture, open `/dashboard`, and compare the P&L card with the independent same-current-FX reference in `../financial-reconciliation.md`.

### DASH-02 — Diversification score mixes native values with a converted total

- **Severity:** P1
- **Owner:** frontend
- **Observed:** Source computes weights from native `market_value / totalValue`, then applies HHI, a 10-holding scale, and a sector multiplier. The result is labeled “Diversification Score.”
- **Expected:** Use canonical base-currency weights/HHI, or label and document a separate heuristic. Empty must be N/A; N≤1 must be 0%.
- **Source:** `frontend/src/app/dashboard/page.tsx:106-121`.

### DASH-03 — Add Position infers India region for a US ticker in INR mode

- **Severity:** P1
- **Owner:** frontend
- **Observed:** AAPL submission through the Dashboard modal carried `region: "IN"`; the row rendered with INR notation and Unknown sector. The shared component still maps a non-`.NS`/`.BO` ticker to `IN` whenever `currency === 'INR'`.
- **Source:** `frontend/src/components/portfolio/AddPositionModalSimple.tsx:153-171`.
- **Evidence:** `../evidence/network/pages/desktop/states/msft-add-attempt.network.json` and `../evidence/screenshots/issues/msft-add-attempt-desktop.png`.
- **Expected:** Infer or explicitly select region/currency from ticker provenance and keep it consistent through API/rendering.

### DASH-04 — AAPL valuation is materially wrong

- **Severity:** P1
- **Owner:** backend quote-acceptance/data-service path; exact upstream provider not proven
- **Observed:** AAPL is returned at $4.89 with Unknown sector/industry; multiple secondary current observations were near $336–$337.
- **Evidence:** `../evidence/network/pages/desktop/states/us-reseed.json` and `../evidence/calculations/inputs/external-market-crosscheck.md`.

### DASH-05 — Empty state fabricates diversification and logs unavailable analytics

- **Severity:** P2
- **Owner:** frontend primary; backend error-contract contribution
- **Observed:** Empty Dashboard shows 0.0% diversification and requests risk contribution, which returns 404 and logs an API error.
- **Expected:** Show diversification N/A and suppress/handle expected unavailable analytics deliberately.

### DASH-06 — “Live”/“Just now” lacks market-data as-of provenance

- **Severity:** P2
- **Owner:** backend data contract; frontend labeling contributes
- **Observed:** The page shows “Live Data Active” and “Last updated: Just now” while AAPL is materially wrong and other quotes are timing-sensitive. Position rows do not expose provider, delayed/live state, or quote as-of timestamp.
- **Expected:** Distinguish request/UI refresh time from market quote as-of time and expose provider/freshness metadata.
- **Related evidence:** `../data-freshness-bugs.md` (`DF-002`).

### DASH-07 — Accessibility violations and unresolved loading capture

- **Severity:** P2
- **Owner:** frontend
- **Observed:** Critical unnamed button, serious contrast failures, and heading-order violation. Some section captures retain skeleton cards, but final settle evidence is complete, so an infinite-loading defect is not claimed.
- **Expected:** Name the refresh button, repair contrast/heading hierarchy, and recapture after all analytics settle.

## Reproduction summary

1. Use the documented isolated testing stack and synthetic SQLite fixture.
2. For financial P&L/diversification, load the five-position state and compare Dashboard values with `../evidence/calculations/outputs/portfolio-reconciliation.md`.
3. For region inference, open Add Position in INR mode, enter AAPL, and inspect the recorded POST payload.
4. For empty behavior, clear the isolated portfolio, reload `/dashboard`, and inspect the risk-contribution request/console capture.
5. For accessibility, reproduce at the recorded desktop/mobile viewports and run axe; manual keyboard/screen-reader checks remain a separate pending task.

## Pending / not tested

- Direct raw-response capture and independent replay of summary, realized, forecast, factor, risk-score, regime, and performance metrics.
- Acquisition-date historical FX and true mixed-currency performance/TWR/MWR.
- Quote-provider identity, delayed/live status, and exact as-of timestamps.
- Header and hero refresh, Live toggle, PDF/CSV export, chart hover, table search/sort/pagination, and quick-action navigation.
- Controlled provider failure, database unavailable, stale response race, and WebSocket connect/reconnect.
- Manual keyboard, focus order, touch target, zoom, and screen-reader validation.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Database-unavailable rendering | Portfolio API aborted; explicit network error captured. | `../evidence/screenshots/interactions/desktop-dashboard-db-unavailable.png` |
| Currency and mixed-value states | INR/USD views, CRUD reconciliation, and P&L discrepancy captured. | `../evidence/network/pages/desktop/states/portfolio-usd-api.json` |
