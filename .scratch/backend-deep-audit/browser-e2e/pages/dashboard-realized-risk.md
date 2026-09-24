# Realized Risk — Page Report

**Status:** PARTIAL — route states, section evidence, and direct replay are complete; chart/table interaction and manual a11y remain not tested.
**Route:** `/dashboard/realized-risk`  
**Audit date:** 2026-09-24  
**Evidence stack:** isolated production frontend on `127.0.0.1:3001` and testing backend on `127.0.0.1:8001`.

> Evidence paths beginning `../evidence/` are relative to this report. This report uses existing captures only; no new browser/API/network call was made.

## Route and fixture

- **Empty:** zero active positions.
- **Seeded:** five synthetic holdings: RELIANCE.NS, HDFCBANK.NS, TCS.BO, AAPL, and MSFT.
- **Historical:** purchase dates normalized to `2025-01-01`; earlier seeded captures show `2026-09-24` and are not historical-cost evidence.
- **Viewports:** desktop `1440×900`; mobile `390×844`.
- Page purpose: trailing/full-history instrument characteristics plus holding-window performance, rolling volatility, drawdown, and position-level risk.
- The app scrolls inside `<main>`; the final section capture set is present.

## Coverage

| State | Desktop | Mobile | Notes |
|---|---|---|---|
| Empty | `../evidence/screenshots/desktop/empty/dashboard-realized-risk.png` | `../evidence/screenshots/mobile/empty/dashboard-realized-risk.png` | N/A metrics and empty charts captured |
| Five-position seeded | `../evidence/screenshots/desktop/seeded/dashboard-realized-risk.png` | `../evidence/screenshots/mobile/seeded/dashboard-realized-risk.png` | Baseline images still show metric skeletons |
| Historical holding-date state | `../evidence/screenshots/desktop/historical/dashboard-realized-risk.png` | Not captured | Charts populated, cards N/A, table empty |
| Settled top/middle/bottom sections | 13 desktop captures | 13 mobile captures | See **Final internal-scroll evidence** |

Text/network evidence: `../evidence/network/pages/desktop/{empty,seeded,historical}/dashboard-realized-risk.*` and matching mobile empty/seeded files.

## Executive verdict

- Empty state is appropriately unavailable: all risk cards show N/A and charts say no performance history; it makes no analytics request and logs no error.
- In the five-position historical capture, rolling-volatility and drawdown charts populate, but all eight risk cards remain N/A and Position-Level Risk Analysis contains zero rows without a visible error or coverage explanation.
- All completed API responses in the captured network are HTTP 200. The raw body was not retained, so the reason for N/A/empty rows is **not proven**; this is a diagnostic/UX gap, not a declared calculation discrepancy.
- Direct route rendering depends on the persisted portfolio store rather than fetching portfolio state on this page; cold direct navigation and backend/store divergence remain a frontend risk.
- Axe records serious-to-moderate structural issues, including a non-focusable scrollable main region.

## Visible behavior by state

### Empty

- Universe: `0 active positions`.
- Full-history instrument cards: annual return, volatility, Sharpe, Sortino all N/A.
- Holding-period cards: max drawdown, VaR, CVaR, hit ratio all N/A.
- Both charts say “No performance history yet.”
- Position table has zero rows and no results.
- Text: `../evidence/network/pages/desktop/empty/dashboard-realized-risk.txt` and `../evidence/network/pages/mobile/empty/dashboard-realized-risk.txt`.

### Seeded baseline

- Universe: `5 active positions`.
- Desktop/mobile first-viewport images still show skeletons for all metric cards and say no performance history in the baseline text.
- Header says `Last updated: Never` in the seeded captures.
- This may be a capture-settle issue; no infinite-loading defect is claimed before final section recapture.

### Historical desktop

- Universe: `5 active positions`; header says `Last updated: Just now`.
- Rolling 21-Day Volatility chart spans approximately March through September 2026.
- Underwater Drawdown chart spans approximately February through September 2026 and reaches roughly -20% on the displayed axis.
- Despite populated performance charts, annual return, annual volatility, Sharpe, Sortino, max drawdown, VaR, CVaR, and hit ratio are all N/A.
- Position-Level Risk Analysis reports `(0)` and “No results.”
- No coverage warning, backend error text, or “insufficient history” explanation appears in the captured page text.
- Text: `../evidence/network/pages/desktop/historical/dashboard-realized-risk.txt`.

## Controls and interaction evidence

| Control | Evidence status |
|---|---|
| Hero refresh | Present; **not exercised** |
| Coverage-details toggle | Source exists when warnings are present; no warning/toggle was rendered in captures; **not exercised** |
| Export CSV | Present; **not exercised** |
| Position table search | Present; **not exercised** |
| Pagination | Present with 0 or 1 page depending on state; **not exercised** |
| Chart hover/tooltips | **Not tested** |
| Global Live/PDF/refresh/dark-mode/menu | Present; **Not exercised** |
| Model/window selection | No route-specific model control; page uses 252-day performance request |

Source: `frontend/src/app/dashboard/realized-risk/page.tsx:36-125` and `frontend/src/app/dashboard/realized-risk/page.tsx:251-551`.

## Financial verdicts

| Value/behavior | Verdict | Evidence/qualification |
|---|---|---|
| Empty risk metrics shown as N/A | `VERIFIED` presentation behavior | No portfolio and no performance data |
| Empty-state request suppression | `VERIFIED` | No backend analytics request recorded; zero console errors |
| Historical rolling-volatility series | `PARTIAL` | Raw response and independent replay captured; exact aggregation contract remains underdetermined |
| Historical underwater-drawdown series | `PARTIAL` | Raw response and independent replay captured; exact portfolio aggregation remains underdetermined |
| Full-history annual return/volatility/Sharpe/Sortino | `UNVERIFIABLE` | Captured as N/A; raw body and replay unavailable |
| Holding-period max drawdown/VaR/CVaR/hit ratio | `UNVERIFIABLE` | Captured as N/A; raw body and replay unavailable |
| Position-level risk table | `UNVERIFIABLE` | Five positions are active, but zero rows render; no captured body explains why |
| True realized P&L, TWR, and MWR | `UNVERIFIABLE` | No transaction/cash/dividend/fee ledger exists in the audit fixture |
| Mixed-currency portfolio risk/returns | `UNVERIFIABLE` | No daily historical FX series; current-FX weights cannot certify historical base-currency returns |
| AAPL input price used by any historical metric | `DISCREPANCY` risk | Current quote is $4.89, but exact inclusion in each historical metric requires raw response/model provenance |

The absence of a visible reason for N/A is a presentation/diagnostic issue; it is not treated as proof that the backend returned incorrect metrics.

## API, network, and console

- Empty desktop/mobile: zero recorded backend API calls and zero console errors.
- Seeded desktop/mobile: seven completed analytics/performance calls, all HTTP 200 in request/response pairs; zero console errors.
- Historical desktop: eight completed calls, all HTTP 200, including summary, realized risk, forecast risk, factor exposure, concentration, liquidity, risk score, and 252-day performance history.
- The aggregate baseline summary marks one bad/missing-status record for seeded captures, but the paired response evidence shows all completed calls returned 200. This is retained as a settle/capture caveat, not counted as an endpoint failure.
- No `GET /portfolio` appears in the route-specific captures. Current source reads `positions` from the persisted Zustand store and does not fetch the portfolio itself (`frontend/src/app/dashboard/realized-risk/page.tsx:41-44`).
- Current backend source distinguishes full instrument history and holding-window P&L (`backend/app/api/analytics.py:529-767`), but the captured build returned N/A/empty rows. Because the source tree was dirty and the raw body is absent, source equivalence is not assumed.

Primary evidence:
- `../evidence/network/pages/desktop/seeded/dashboard-realized-risk.network.json`
- `../evidence/network/pages/desktop/historical/dashboard-realized-risk.network.json`
- `../evidence/network/console/desktop/seeded/dashboard-realized-risk.console.json`

## Accessibility and responsive evidence

### Axe

- Seeded desktop: `color-contrast` serious (3 nodes), `heading-order` moderate (1), and `scrollable-region-focusable` serious (1).
- Seeded mobile: `heading-order` moderate (1) and `scrollable-region-focusable` serious (1).
- Historical desktop: `color-contrast` serious (1) and `heading-order` moderate (1).
- The scrollable-region violation targets the page's own `<main class="... overflow-y-auto ...">`; keyboard users may not be able to move focus into that scroll container before using page-wheel/arrow navigation.
- No empty-state axe run exists.

Evidence: `../evidence/network/desktop/seeded/dashboard-realized-risk.a11y.json`, `../evidence/network/mobile/seeded/dashboard-realized-risk.a11y.json`, and `../evidence/network/desktop/historical/dashboard-realized-risk.a11y.json`.

### Responsive

- Desktop first viewport shows both chart panels below metric cards.
- Mobile first viewport stacks metric cards one per row; seeded mobile remains in loading skeletons.
- The 390px header is crowded but all four global icon controls are visible in the captured image.
- Complete chart/table scrolling, touch panning, tooltip behavior, and lower-section clipping are pending.

## Findings

### RR-01 — Five-position state renders unexplained N/A metrics and an empty position table

- **Severity:** P2 provisional
- **Owner:** frontend/backend analytics contract; raw-body diagnosis required
- **Observed:** Historical capture has 200 responses, five active positions, populated performance charts, but all risk cards N/A and zero position-risk rows without an error/coverage message.
- **Expected:** Return explicit reason/coverage metadata and render a deliberate unavailable state, or render the available per-position metrics.
- **Reproduction:** Seed the five-position fixture with `added_on=2025-01-01`, open the route, settle all calls, and capture the raw `/analytics/realized-risk` body plus visible page.

### RR-02 — Direct route depends on persisted portfolio state

- **Severity:** P2
- **Owner:** frontend
- **Observed:** The page sends ticker lists from Zustand but does not fetch `/portfolio`; direct route evidence has no portfolio request. Persisted and backend state can diverge.
- **Expected:** Fetch/validate portfolio state on direct entry or use one synchronized authoritative store with a clear loading/error state.
- **Related evidence:** `../route-inventory.md`, confirmed mismatch 7.

### RR-03 — “Realized P&L” lacks transaction-ledger provenance

- **Severity:** P2 analytical limitation
- **Owner:** backend analytics/product definition
- **Observed:** The fixture supports price history and buy cost, not trades, cash flows, fees, dividends, or corporate actions. Those are required for true realized return/TWR/MWR.
- **Expected:** Label price-window metrics precisely or add a transaction/cash-flow ledger before calling them realized portfolio returns.

### RR-04 — Accessibility defects in contrast, heading order, and scroll focus

- **Severity:** P2
- **Owner:** frontend
- **Observed:** Axe rules above across seeded/historical desktop and mobile.
- **Expected:** Fix contrast tokens, preserve heading hierarchy, and make scrollable regions keyboard-focusable with an appropriate label/tabindex treatment.

### RR-05 — Freshness/loading state is not settled in baseline captures

- **Severity:** P3 / evidence gap
- **Owner:** frontend capture/runtime owner
- **Observed:** Seeded images retain skeletons and `Last updated: Never`; historical charts and clock later populate.
- **Limitation:** Final section/settle recapture is complete; the captures preserve the observed loading/unavailable states, so a persistent spinner is not asserted.

## Reproduction summary

1. Use the isolated testing stack only.
2. Empty: open `/dashboard/realized-risk`; verify N/A cards, empty charts/table, no API calls, and no console errors.
3. Seeded: load the five holdings and wait for all analytics; capture network, console, raw realized-risk body, and full internal-scroll page.
4. Historical: normalize `added_on` to `2025-01-01`, reload, and compare performance charts with all N/A risk cards/zero rows.
5. Run axe at both recorded viewports and perform a separate manual keyboard-scroll check.

## Pending / not tested

- Direct raw response capture for realized risk, performance history, and coverage metadata.
- Independent replay of full-history and holding-window metrics, rolling volatility, and drawdown.
- True realized P&L/TWR/MWR with transaction/cash/dividend/fee ledger.
- Daily historical FX for mixed-currency portfolio risk/returns.
- Refresh, coverage-details toggle, export, search, pagination, and chart tooltips.
- Cold direct navigation with cleared persisted Zustand state.
- Controlled provider/database failures, stale response races, and WebSocket states.
- Manual keyboard, focus order, zoom, touch, and screen-reader validation.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-realized-risk-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-realized-risk-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-realized-risk-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-realized-risk-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-realized-risk-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-realized-risk-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Direct replay | Captured API body independently replayed; exact mixed-FX historical aggregation remains underdetermined. | `../evidence/calculations/outputs/independent-core-models.md` |
