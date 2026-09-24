# Forecast Risk — Page Report

**Status:** PARTIAL — EGARCH/10-day controls, provider failure, section evidence, and direct replay are complete; other horizons/models and manual a11y remain partial.
**Route:** `/dashboard/forecast-risk`  
**Audit date:** 2026-09-24  
**Evidence stack:** isolated production frontend on `127.0.0.1:3001` and testing backend on `127.0.0.1:8001`.

> Evidence paths beginning `../evidence/` are relative to this report. Existing evidence only was used; no new browser/API/network call was made.

## Route and fixture

- **Empty:** zero positions.
- **Seeded:** five synthetic holdings across INR/USD: RELIANCE.NS, HDFCBANK.NS, TCS.BO, AAPL, and MSFT.
- **Historical:** same holdings with normalized `added_on=2025-01-01`; this does not create historical FX data.
- **Default control state:** GARCH, 1-day horizon.
- **Viewports:** desktop `1440×900`; mobile `390×844`.
- App scrolling is internal to `<main>`; no settled top/middle/bottom section set currently exists.

## Coverage

| State | Desktop | Mobile | Notes |
|---|---|---|---|
| Empty | `../evidence/screenshots/desktop/empty/dashboard-forecast-risk.png` | `../evidence/screenshots/mobile/empty/dashboard-forecast-risk.png` | Honest N/A/error state captured |
| Five-position seeded | `../evidence/screenshots/desktop/seeded/dashboard-forecast-risk.png` | `../evidence/screenshots/mobile/seeded/dashboard-forecast-risk.png` | Default GARCH/1-day captured |
| Historical holding-date state | `../evidence/screenshots/desktop/historical/dashboard-forecast-risk.png` | Not captured | Same displayed default outputs as seeded |
| EWMA / EGARCH | EGARCH exercised; EWMA not separately exercised | Same for mobile | Direct API and independent replay captured |
| Horizons 5/10/20/30 and custom range | 10 days exercised; others not | Same for mobile | 10-day request captured |
| Final internal-scroll sections | 13 desktop captures | 13 mobile captures | See **Final internal-scroll evidence** |

Text evidence: `../evidence/network/pages/desktop/{empty,seeded,historical}/dashboard-forecast-risk.txt` and matching mobile files.

## Executive verdict

- Empty state behaves honestly: two HTTP-200 forecast requests return an error payload, the page shows “Forecast Unavailable — No portfolio positions found,” all four cards are N/A, and no synthetic chart/table is rendered.
- Default seeded GARCH/1-day values are internally arithmetically consistent with the current backend formulas, but the underlying econometric estimate and mixed-currency portfolio return construction were not independently replayed.
- The “Confidence Interval” is a deterministic 0.8×–1.2× volatility band, not a stated statistical confidence interval. That terminology is materially misleading.
- The page makes two identical forecast GETs on each captured load; the cause is not proven.
- Axe finds a critical unlabeled range input, three nested-interactive model cards, contrast, and heading-order defects.

## Visible behavior

### Empty

- Model GARCH, horizon 1 day, parameters `p:1, q:1, type:GARCH`.
- Warning: `Forecast Unavailable — No portfolio positions found`.
- 1-day VaR, CVaR, volatility, and confidence interval all N/A.
- Model and horizon controls remain visible.
- Projection area says curves are unavailable rather than inventing a curve.
- No position table is rendered.
- Header nevertheless says `Last updated: Just now` because the page handles a successful HTTP response containing an error payload.

### Seeded/historical default GARCH

- 1-day VaR: `-2.98%`.
- 1-day CVaR: `-3.73%`.
- Volatility forecast: `28.78%`.
- Displayed confidence interval: `23.02% - 34.53%`.
- Per-position volatility/VaR:
  - RELIANCE.NS: 18.30%, -1.90%, Low
  - HDFCBANK.NS: 21.92%, -2.27%, Medium
  - TCS.BO: 26.51%, -2.75%, Medium
  - AAPL: 27.12%, -2.81%, Medium
  - MSFT: 36.28%, -3.76%, High
- Risk labels follow the source thresholds: `<20%` Low, `>20%` and `≤35%` Medium, `>35%` High, with rounding explaining the displayed 35% cases.
- Forward volatility and VaR/CVaR charts, position table, insights, model parameters, and export action are present in page text; lower sections are not fully image-captured.

## Controls and interaction evidence

| Control | Evidence status |
|---|---|
| GARCH / EWMA / EGARCH model cards | Visible; **none exercised beyond default GARCH** |
| Horizon buttons 1/5/10/20/30 | 10-day button exercised; other buttons not exercised |
| Custom horizon range 1–30 | Visible; **not exercised** |
| Hero refresh | Visible; **not exercised** |
| Help/Explainer buttons and modal | Visible; **not exercised** |
| Export CSV | Visible; **not exercised** |
| Position table search/pagination | Visible; **not exercised** |
| Global Live/PDF/refresh/dark-mode/menu | Visible; **not exercised** |

Source: `frontend/src/app/dashboard/forecast-risk/page.tsx:350-496` and `frontend/src/app/dashboard/forecast-risk/page.tsx:601-1113`.

## Financial verdicts

### Default 1-day arithmetic

| Value | Independent check from displayed volatility | Verdict |
|---|---|---|
| 1-day VaR | `28.78% × 1.645 / √252 ≈ 2.98%` | `VERIFIED` as formula/display arithmetic |
| 1-day CVaR | `28.78% × 2.06 / √252 ≈ 3.73%` | `VERIFIED` as formula/display arithmetic |
| Displayed interval | `28.78% × 0.8 = 23.024%`; `× 1.2 = 34.536%` | `VERIFIED` as deterministic arithmetic, **not** as a statistical confidence level |
| Per-position Low/Medium/High labels | Values map to current source thresholds after rounding | `VERIFIED` as label transform |

The current 1-day GARCH backend uses the fitted return-space volatility and multipliers 1.645/2.06 (`backend/app/services/analytics_engine.py:1168-1226`), which matches the captured default values.

### Model/data verdicts

| Value/behavior | Verdict | Qualification |
|---|---|---|
| GARCH fitted volatility estimate | `PARTIAL` | Raw response and replay captured; exact fit metadata remains underdetermined |
| EWMA output | `NOT TESTED` | EWMA control was not separately exercised |
| EGARCH output | `EXERCISED / PARTIAL` | EGARCH + 10-day request and direct replay captured; exact fit metadata remains underdetermined |
| 5/10/20/30-day outputs | `PARTIAL` | 10-day output exercised; 5/20/30-day controls not exercised |
| Per-position forecasts | `PARTIAL` | Captured response replayed; exact per-position fit contract remains underdetermined |
| Mixed-currency portfolio return series | `UNVERIFIABLE` | Current-FX-converted weights are combined with local-currency asset returns; no daily historical FX series |
| AAPL input quote | `DISCREPANCY` | Current quote $4.89 is materially wrong; exact use in each fitted window requires raw provenance |
| Empty-state N/A behavior | `VERIFIED` presentation behavior | No fabricated metrics or curves |

A successful formula match does not validate the forecast estimate or its real-world usefulness.

## API, network, and console

- Empty desktop/mobile: two completed identical `GET /analytics/forecast-risk?model=GARCH&horizon=1` requests, both HTTP 200.
- Seeded desktop/mobile and historical desktop: two completed requests:
  1. default GARCH/1-day without a ticker list;
  2. GARCH/1-day with the five-ticker list.
- All recorded responses are HTTP 200; no console errors or warnings were recorded.
- The duplicate calls are a P3 efficiency/state-hydration issue. React effect dependencies and persisted-store hydration are plausible, but the exact cause is not asserted without a new trace.
- No route-specific `GET /portfolio` appears; ticker state comes from `usePortfolioStore`. Cold direct-navigation behavior was exercised on the isolated route.

Primary evidence:
- `../evidence/network/pages/desktop/empty/dashboard-forecast-risk.network.json`
- `../evidence/network/pages/desktop/seeded/dashboard-forecast-risk.network.json`
- `../evidence/network/console/desktop/seeded/dashboard-forecast-risk.console.json`

## Accessibility and responsive evidence

### Axe

- Seeded desktop: 4 rules — `label` critical (1), `nested-interactive` serious (3), `color-contrast` serious (1), and `heading-order` moderate (1).
- Seeded mobile: the critical label, three nested-interactive nodes, and heading-order violation; color contrast was not reported in that capture.
- Historical desktop repeats all four rules.
- The unlabeled control is the custom horizon `<input type="range">`; its visible text label has no `htmlFor`/programmatic association.
- Each model card is a `div role="button"` containing a real Help button, producing three nested-interactive nodes.
- No empty-state axe run exists.

Evidence: `../evidence/network/desktop/seeded/dashboard-forecast-risk.a11y.json`, `../evidence/network/mobile/seeded/dashboard-forecast-risk.a11y.json`, and `../evidence/network/desktop/historical/dashboard-forecast-risk.a11y.json`.

### Responsive

- Desktop first viewport presents four metric cards and two model/horizon panels.
- Mobile stacks the hero, metric cards, model cards, and horizon controls.
- Manual keyboard operation of the custom `div role="button"` model cards and range input has not been tested.

## Findings

### FR-01 — “Confidence Interval” is a fixed ±20% band, not a statistical confidence interval

- **Severity:** P2
- **Owner:** backend metric contract; frontend labeling/explainer
- **Observed:** Captured interval 23.02%–34.53% is exactly 0.8×–1.2× the 28.78% forecast. Current GARCH, EGARCH, and EWMA source uses the same deterministic band.
- **Expected:** Either calculate and name a defined confidence level with methodology/coverage, or rename it to a deterministic sensitivity/illustrative band.
- **Evidence:** `backend/app/services/analytics_engine.py:1215-1218`, `1287-1290`, and `1334-1337`.

### FR-02 — Model cards contain nested interactive controls

- **Severity:** P2
- **Owner:** frontend
- **Observed:** Three `role="button"` containers each contain a Help `<button>`; keyboard/screen-reader interaction semantics are ambiguous.
- **Expected:** Make the card a real button/control and place Help as a sibling, or use a non-interactive card with a separate explicit selection button.

### FR-03 — Custom horizon range has no accessible label

- **Severity:** P2
- **Owner:** frontend
- **Expected:** Associate the visible label with the input and expose current value/min/max programmatically.

### FR-04 — Duplicate forecast requests occur on every captured load

- **Severity:** P3
- **Owner:** frontend
- **Observed:** Two identical default requests in empty state and two GARCH/1-day calls around store hydration in seeded state.
- **Expected:** De-duplicate until model/horizon/tickers actually change; verify stale-response cancellation.

### FR-05 — Chart horizon/term-structure provenance needs clearer labeling

- **Severity:** P2/P3
- **Owner:** frontend analytics presentation
- **Observed:** The frontend always builds at least a 10-day display curve. With a one-element GARCH term structure it carries the last value forward; VaR/CVaR bands use square-root-of-time scaling from the selected base horizon.
- **Expected:** Clearly distinguish model-returned term structure, flat carry-forward, and illustrative scaling; do not imply all displayed days are independent model forecasts.

### FR-06 — Freshness clock advances on an empty error response

- **Severity:** P3
- **Owner:** frontend
- **Observed:** Empty state says `Last updated: Just now` even though the forecast is unavailable and no positions exist.
- **Expected:** Distinguish request time from successful data time.

## Reproduction summary

1. Use the isolated testing stack and empty portfolio; open `/dashboard/forecast-risk` and verify the HTTP-200 error payload renders N/A without fake curves.
2. Seed the five-position fixture; confirm default GARCH/1-day values and compare the fixed formula arithmetic above.
3. Inspect recorded network files for duplicate requests.
4. Run axe at 1440×900 and 390×844; inspect the range label and nested model-card controls.
5. For full model proof, capture raw responses while separately exercising EWMA, EGARCH, and every horizon.

## Pending / not tested

- Raw GARCH/EWMA/EGARCH responses, fitted diagnostics, and independent replay for 1/5/10/20/30 days.
- Model and horizon control interaction, rapid-change stale-response handling, refresh, help modal, export, search, and pagination.
- Statistical confidence-interval methodology; current evidence supports only a fixed multiplier band.
- Daily historical FX and base-currency construction for the mixed-currency portfolio return series.
- Cold direct route with cleared persisted state.
- Controlled provider/database failures and WebSocket behavior.
- Manual keyboard, focus order, screen-reader, zoom, and touch validation.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-forecast-risk-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-forecast-risk-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-forecast-risk-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-forecast-risk-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-forecast-risk-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-forecast-risk-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Model/horizon controls | EGARCH + 10 days produced a 200 request. | `../evidence/network/console/desktop/interactions/forecast-egarch-10d-final.txt` |
| Provider failure | Forecast API aborted; explicit Network Error rendered. | `../evidence/screenshots/interactions/desktop-forecast-provider-failure.png` |
