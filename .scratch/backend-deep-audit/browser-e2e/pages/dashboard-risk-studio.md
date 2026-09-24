# Risk Studio

**Status:** PARTIAL — section evidence and empty/error contract are captured; partial failure/manual controls remain untested.

> Evidence paths are relative to `browser-e2e/`.

## Route and fixture

- **Route:** `/dashboard/risk-studio`
- **Isolated stack:** frontend `127.0.0.1:3001`; backend `127.0.0.1:8001`, `environment=testing`.
- **Fixture:** `browser-e2e-five-equity-v1`: RELIANCE.NS ×10, HDFCBANK.NS ×20, TCS.BO ×15, AAPL ×5, MSFT ×4. Historical desktop uses normalized `added_on=2025-01-01`; early seeded captures predate normalization.
- **Capabilities:** risk contribution, EVT-POT tail risk, Student-t lower-tail copula matrix, volatility cones, and rolling correlation stability.
- **Known caveat:** current weights inherit the AAPL `$4.89` quote defect; mixed-currency historical return/covariance replay lacks daily FX.

## Controls and exercised behavior

| Control / behavior | Source evidence | Browser evidence |
|---|---|---|
| Parallel-load four analytics GETs | `frontend/src/app/dashboard/risk-studio/page.tsx:199-242` | Four XHRs captured in every state. |
| Refresh Studio | `page.tsx:244-247,378-394` | Present on desktop/mobile; not clicked. |
| Export CSV | `page.tsx:308-344,378-386` | Present; not exercised. |
| Metric explainers | `page.tsx:120-197` | Present; not opened. |
| Partial/all endpoint failure handling | `page.tsx:210-237,399-404` | Empty all-failure state rendered; partial failure was not tested. |

The UI intentionally uses `/analytics/tail-dependence`; `/analytics/tails` is a real but unused alias (`../route-inventory.md`).

## Desktop and mobile evidence

| State | Desktop 1440×900 | Mobile 390×844 | Observed result |
|---|---|---|---|
| Empty | `evidence/screenshots/desktop/empty/dashboard-risk-studio.png`; `evidence/network/pages/desktop/empty/dashboard-risk-studio.txt` | `evidence/screenshots/mobile/empty/dashboard-risk-studio.png`; `evidence/network/pages/mobile/empty/dashboard-risk-studio.txt` | All four endpoints 404; visible `Failed to load Risk Studio analytics`; metrics shown as em dash/N/A. |
| Seeded | `evidence/screenshots/desktop/seeded/dashboard-risk-studio.png`; `evidence/network/pages/desktop/seeded/dashboard-risk-studio.txt` | `evidence/screenshots/mobile/seeded/dashboard-risk-studio.png`; `evidence/network/pages/mobile/seeded/dashboard-risk-studio.txt` | Four headline metrics, Euler bars, 5×5 copula matrix, volatility cone, and correlation card rendered. |
| Historical desktop | `evidence/screenshots/desktop/historical/dashboard-risk-studio.png`; `evidence/network/pages/desktop/historical/dashboard-risk-studio.txt` | **Not captured** | Same 200 result after purchase-date normalization. |

The mobile hero keeps Export CSV and Refresh Studio visible. Lower scrollable matrix/chart keyboard behavior is not proven by the viewport image.

## API, console, and network evidence

| Capture | API traffic | Status | Console / page errors |
|---|---|---|---|
| Empty desktop/mobile | `GET /analytics/risk-contribution`, `/tail-dependence`, `/vol-cone`, `/correlation-stability` | All four 404 | 4 console errors per viewport; 0 uncaught page errors. |
| Seeded desktop/mobile | Same four GETs | All four 200 | 0 console errors; 0 page errors. |
| Historical desktop | Same four GETs | All four 200 | 0 console errors; 0 page errors. |

Primary files:

- `evidence/network/pages/desktop/{empty,seeded,historical}/dashboard-risk-studio.network.json`
- `evidence/network/pages/mobile/{empty,seeded}/dashboard-risk-studio.network.json`
- `evidence/network/console/desktop/{empty,seeded,historical}/dashboard-risk-studio.console.json`
- `evidence/network/console/mobile/{empty,seeded}/dashboard-risk-studio.console.json`

## Calculations and verdicts

### Captured historical result

- Portfolio annualized volatility: `25.47%`.
- 99% EVT-POT one-day VaR: `-3.41%`; 99% expected shortfall: `-4.80%`.
- Correlation regime: `NORMAL`; current 60-day average `0.105`; historical 90th percentile `0.269`.
- EVT shape `ξ=0.2893`, scale `β=0.0062`, `Fat Tailed: Yes`.
- Copula lower-tail matrix diagonal is `1.000`; visible off-diagonal values range from `0.073` to `0.231`.
- Sector rollup matches Risk Contribution: Technology `96.0%`, Information Technology `3.0%`, Financial Services `0.5%`, Energy `0.5%`, Unknown `0.1%`.

### Display-level checks

| Check | Calculation / comparison | Rendered result | Verdict |
|---|---|---|---|
| Risk-page consistency | Risk Studio portfolio volatility equals Risk Contribution page | `25.47%` on both | `VERIFIED` across pages |
| EVT ordering | ES `-4.80%` is more negative than VaR `-3.41%` | Both rendered | `VERIFIED` as expected tail ordering |
| Correlation regime | `0.105 < 0.269` | `NORMAL` / `Diversified Regime` | `VERIFIED` from displayed comparison |
| Copula structure | Matrix is symmetric; diagonal `1.000`; values are finite | 5×5 rendered matrix | `VERIFIED` structurally |
| Copula alert threshold | Largest visible off-diagonal `0.231 < 0.25` explainer threshold | No red high-dependence cell | `VERIFIED` from displayed values |

Backend source fits EVT-POT and pairwise Student-t copulas from the same return frame (`backend/app/api/analytics.py:2820-2877`) and uses a separate 60-day correlation service. The source confirms the intended methods, not the raw numerical outputs.

### Financial verdict

- Cross-page consistency and matrix/range/order checks: `VERIFIED` at display precision.
- Raw covariance, EVT fit, copula fit, volatility-cone quantiles, and correlation threshold: `UNVERIFIABLE` without raw series/direct responses and independent replay.
- Current-weight and mixed-currency inputs remain conditional on BE-002/DF-001 and DF-003.

## Accessibility evidence

No empty-state axe capture exists.

- **Seeded desktop:** `color-contrast` serious (1 node), `heading-order` moderate (1).
- **Seeded mobile:** `heading-order` moderate (1), `scrollable-region-focusable` serious (1).
- **Historical desktop:** `color-contrast` serious (1), `heading-order` moderate (1).
- Manual keyboard/focus and screen-reader checks: **not tested**.

Files: `evidence/network/{desktop,mobile}/seeded/dashboard-risk-studio.a11y.json` and `evidence/network/desktop/historical/dashboard-risk-studio.a11y.json`.

## Findings

| ID | Severity | Owner | Evidence-based finding |
|---|---|---|---|
| RS-F01 | **P2** | Backend empty-state contracts + frontend orchestration | Empty portfolio fires four analytics requests, receives four 404s, and logs four API errors. Expected unavailability should be gated or represented deliberately. Part of FE-005. |
| RS-F02 | **P2** | Frontend | Global `Last updated: Never` remains after four successful analytics responses. |
| RS-F03 | **P1 input dependency** | Backend quote/data path | Current Euler weights inherit the AAPL quote defect. Existing BE-002/DF-001 dependency. |
| RS-F04 | **P2 analytical** | Backend analytics/data contract | Mixed-currency tail/correlation/covariance results lack daily historical FX for independent replay. DF-003. |
| RS-F05 | **P2** | Frontend | Axe evidence includes contrast, heading order, and a mobile non-focusable scrollable region. Part of FE-006. |

## Pending / not tested

- Refresh Studio, CSV, explainers, and partial-endpoint failure.
- Direct raw responses/series and independent EVT/copula/cone/correlation replay.
- Model exclusion/insufficient-history branches.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-risk-studio-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-risk-studio-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-risk-studio-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-risk-studio-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-risk-studio-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-risk-studio-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Empty/error contract | Unavailable calls and visible error states captured. | `../evidence/network/pages/desktop/empty/dashboard-risk-studio.txt` |
