# Root Redirect — Page Report

**Status:** PARTIAL — route states and final section evidence are complete; browser navigation/cache edge cases and manual a11y remain not tested.
**Route:** `/` → `/dashboard`  
**Audit date:** 2026-09-24  
**Evidence stack:** isolated production frontend on `127.0.0.1:3001` and testing backend on `127.0.0.1:8001`.

> Evidence paths beginning `../evidence/` are relative to this report. No live-stack mutation or new browser/API request was performed for this report.

## Route and fixture

- Current source implements a server-side redirect with `redirect('/dashboard')`: `frontend/src/app/page.tsx:5-9`.
- The synthetic fixture is `browser-e2e-five-equity-v1`: RELIANCE.NS, HDFCBANK.NS, TCS.BO, AAPL, and MSFT. Historical captures use purchase dates normalized to `2025-01-01`; earlier seeded captures show `2026-09-24` and must not be treated as historical-acquisition-cost evidence. Fixture: `../evidence/runtime/synthetic-fixture.json`.
- Empty and five-position states were captured at desktop `1440×900` and mobile `390×844`.
- The existing app scrolls inside `<main>`, not the document. No `final-sections-*-summary.json` or final section screenshot set currently exists.

## Coverage

| State | Desktop | Mobile | Notes |
|---|---|---|---|
| Empty portfolio | `../evidence/screenshots/desktop/empty/root.png` | `../evidence/screenshots/mobile/empty/root.png` | Redirect target rendered |
| Five-position seeded | `../evidence/screenshots/desktop/seeded/root.png` | `../evidence/screenshots/mobile/seeded/root.png` | Baseline capture; some cards still show skeletons |
| Historical holding-date state | `../evidence/screenshots/desktop/historical/root.png` | Not captured | Historical desktop only |
| Final internal-scroll sections | 13 desktop captures | 13 mobile captures | See **Final internal-scroll evidence** |

Page text and network records exist under `../evidence/network/pages/{desktop,mobile}/{empty,seeded,historical}/root.*`.

## Observed behavior

1. The recorded navigation begins at `http://127.0.0.1:3001/` and the same request resolves as the `/dashboard` document with HTTP 200. Root and Dashboard text captures are materially identical.
2. Empty state renders Portfolio Summary with `0 positions`, `₹0.00`, annual volatility `N/A`, and diversification `0.0%`.
3. Seeded state renders `5 positions`, market regime `Crisis`, top risk drivers, and an 18.7% diversification score. The baseline image still contains loading skeletons, so it is not proof of final settled rendering.
4. Historical desktop state adds a performance chart with `+21.41%` total return. The screenshot still contains loading skeletons in upper metric cards; final section/settle recapture is complete.

## Controls and exercised behavior

| Control/behavior | Evidence status |
|---|---|
| `/` → `/dashboard` redirect | **Exercised and verified** in empty, seeded, and historical desktop captures; mobile text/network also show the target |
| Dashboard/sidebar navigation | Reachable after redirect; route-by-route links are separately covered by the other page reports |
| Dashboard actions | Not route-specific to `/`; see `dashboard.md` |
| Browser back/forward, redirect loops, cache behavior, and direct production-origin redirect | **Not tested** |

## API, network, and console

- Empty captures record three backend requests: portfolio (200), regime (200), and risk contribution (404). The 404 produces one console error: `API Error ... /analytics/risk-contribution ... Requested resource not found`.
- Seeded captures record ten completed backend requests, all HTTP 200, and no console errors. Historical desktop has the same ten-request pattern.
- The empty 404 is `FE-005`: an unavailable analytics request should be skipped or represented as an expected unavailable state rather than logged as an application error.
- Recorded request files: `../evidence/network/pages/desktop/empty/root.network.json`, `../evidence/network/pages/desktop/seeded/root.network.json`, and matching mobile/historical files.
- Recorded console files: `../evidence/network/console/desktop/empty/root.console.json` and `../evidence/network/console/mobile/empty/root.console.json`.

## Financial verdicts

`/` has no independent financial calculation. Its redirected Dashboard inherits these verdicts:

| Value/behavior | Verdict | Evidence summary |
|---|---|---|
| Redirect itself | `VERIFIED` (functional, not financial) | `/` resolves to `/dashboard` in all captured states |
| Empty diversification | `DISCREPANCY` | Dashboard shows `0.0%`; empty portfolio should be unavailable/N/A |
| First-position value, cost, P&L, and 100% weight | `VERIFIED` | ₹12,270 value, ₹10,000 cost, +₹2,270 P&L, 100.00% weight |
| Five-position Dashboard P&L | `DISCREPANCY` | +₹190,377.31 / +320.23% mixes converted current value with mixed-native cost |
| Five-position diversification | `DISCREPANCY` | Dashboard 18.7% versus API/independent arithmetic 50.5% for returned quotes |
| AAPL quote | `DISCREPANCY` | $4.89 versus secondary observations near $336.16 |
| Historical total return | `UNVERIFIABLE` | No independent daily historical FX series or model replay |
| Annual volatility, VaR forecasts, and risk-driver percentages | `PARTIAL` | Direct replay completed where exposed; exact mixed-FX historical contracts remain underdetermined |

See `../financial-reconciliation.md` and `../frontend-bugs.md`.

## Accessibility and responsive evidence

- Seeded desktop axe: 3 violation rules — `button-name` (critical, 1 node), `color-contrast` (serious, 2 nodes), and `heading-order` (moderate, 1).
- Seeded mobile axe: `heading-order` (moderate, 1). Axe also had one incomplete color-contrast review item.
- Historical desktop repeats the same three rules, with three color-contrast nodes.
- The unnamed button is the Dashboard hero refresh icon: `frontend/src/app/dashboard/page.tsx:308-315`.
- No empty-state axe run, manual keyboard pass, focus-order review, or screen-reader test exists.

Axe evidence: `../evidence/network/desktop/seeded/root.a11y.json`, `../evidence/network/mobile/seeded/root.a11y.json`, and `../evidence/network/desktop/historical/root.a11y.json`.

## Findings

### RT-01 — Empty redirect target emits an avoidable 404 and console error

- **Severity:** P2
- **Owner:** frontend primary; backend error-contract behavior contributes
- **Observed:** Empty `/` and `/dashboard` call `/analytics/risk-contribution`, receive 404, and log `API Error` even though there is no portfolio.
- **Expected:** Avoid the request for an empty portfolio or render/log an expected unavailable state deliberately.
- **Reproduction:** On the isolated testing stack with an empty portfolio, open `/`; follow the redirect and inspect the recorded console/network evidence.

### RT-02 — Redirect target has critical accessibility and financial-reporting defects

- **Severity:** P1 for financial findings; P2 for accessibility
- **Owner:** frontend for the P&L/diversification/a11y presentation; backend contract contributes to currency provenance
- **Details:** The redirect itself works, but the target shows mixed-currency P&L, a noncanonical diversification score, an unnamed button, contrast failures, and invalid heading order. These are not root-route defects; they are inherited Dashboard defects and are documented in `dashboard.md`.

## Reproduction summary

1. Start only the documented isolated testing stack.
2. Open `/` in an empty-portfolio state at `1440×900`; verify the URL/content become `/dashboard`, then observe the risk-contribution 404 and console error.
3. Seed the documented five-position fixture and reload `/`; verify the same Dashboard content and API pattern as direct `/dashboard`.
4. Compare root captures with the corresponding files in `../evidence/network/pages/.../root.*` and `../evidence/screenshots/.../root.png`.

## Pending / not tested

- Redirect loop, history navigation, prefetch behavior, and cache-hit behavior.
- Production-origin redirect behavior; only the isolated build was navigated.
- Root-specific loading, provider-failure, database-unavailable, and WebSocket states.
- Manual keyboard, focus, zoom, and screen-reader validation.
- Final independent replay of Dashboard performance/risk values.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/root-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/root-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/root-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/root-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/root-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/root-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Database-unavailable rendering | Portfolio API aborted; explicit Network Error rendered. | `../evidence/network/console/desktop/interactions/controlled-db-unavailable.txt` |
