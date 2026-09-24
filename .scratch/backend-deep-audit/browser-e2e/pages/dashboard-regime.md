# Market Regime

**Status:** PARTIAL — refresh, section evidence, and direct replay are complete; export/manual a11y remain untested.

> Evidence paths are relative to `browser-e2e/`.

## Route and fixture

- **Route:** `/dashboard/regime`
- **Isolated stack:** frontend `127.0.0.1:3001`; backend `127.0.0.1:8001`, `environment=testing`.
- **Fixture:** `browser-e2e-five-equity-v1` as recorded in `evidence/runtime/synthetic-fixture.json`; positions are RELIANCE.NS ×10, HDFCBANK.NS ×20, TCS.BO ×15, AAPL ×5, and MSFT ×4. Historical desktop uses normalized `added_on=2025-01-01`; early seeded captures predate normalization.
- **Model:** three-state Gaussian HMM over NIFTY 50 (`Calm`, `Bull Rally`, `Crisis`) with a conditional portfolio-return leg.
- **Known caveat:** the benchmark regime can be evaluated with an empty portfolio, but the conditional portfolio return remains subject to missing daily historical FX and the AAPL quote/current-weight defect.

## Controls and exercised behavior

| Control / behavior | Source evidence | Browser evidence |
|---|---|---|
| Fetch regime on mount | `frontend/src/app/dashboard/regime/page.tsx:257-279` | One `GET /analytics/regime` in every state. |
| Refresh | `page.tsx:381-399` | Present on desktop/mobile; not clicked. |
| Export CSV | `page.tsx:303-343,381-390` | Present; not exercised. |
| Try Again | `page.tsx:403-420` | Not present because all baseline requests succeeded. |
| Metric/section explainers | `page.tsx:112-189` | Present; not opened. |

## Desktop and mobile evidence

| State | Desktop 1440×900 | Mobile 390×844 | Observed result |
|---|---|---|---|
| Empty | `evidence/screenshots/desktop/empty/dashboard-regime.png`; `evidence/network/pages/desktop/empty/dashboard-regime.txt` | `evidence/screenshots/mobile/empty/dashboard-regime.png`; `evidence/network/pages/mobile/empty/dashboard-regime.txt` | HMM market section rendered with `720` observations; portfolio section correctly says to add holdings. |
| Seeded | `evidence/screenshots/desktop/seeded/dashboard-regime.png`; `evidence/network/pages/desktop/seeded/dashboard-regime.txt` | `evidence/screenshots/mobile/seeded/dashboard-regime.png`; `evidence/network/pages/mobile/seeded/dashboard-regime.txt` | Crisis regime, probabilities, state table, timeline, and portfolio-in-regime section rendered. |
| Historical desktop | `evidence/screenshots/desktop/historical/dashboard-regime.png`; `evidence/network/pages/desktop/historical/dashboard-regime.txt` | **Not captured** | `721` observations; portfolio history section uses `449` actual holding days since `2023-09-27` and `170` regime-overlap days. |

Mobile hero controls remain visible. The timeline/table below the viewport is not proven keyboard-reachable or fully visible by the screenshot alone.

## API, console, and network evidence

| Capture | API | Status | Console / page errors |
|---|---|---|---|
| Empty desktop/mobile | `GET /analytics/regime` | 200 | 0 console errors; 0 page errors. |
| Seeded desktop/mobile | Same GET | 200 | 0 console errors; 0 page errors. |
| Historical desktop | Same GET | 200 | 0 console errors; 0 page errors. |

Primary files:

- `evidence/network/pages/desktop/{empty,seeded,historical}/dashboard-regime.network.json`
- `evidence/network/pages/mobile/{empty,seeded}/dashboard-regime.network.json`
- `evidence/network/console/desktop/{empty,seeded,historical}/dashboard-regime.console.json`
- `evidence/network/console/mobile/{empty,seeded}/dashboard-regime.console.json`

The endpoint deliberately keeps the NIFTY leg available when the portfolio leg cannot be built (`backend/app/api/analytics.py:2380-2422`).

## Calculations and verdicts

### Captured historical result

- As of `2026-09-24`; `721` trading days analyzed.
- Current regime `Crisis`; stability `96.7%`; regime benchmark volatility `11.2%`; historical share `31%`.
- Posterior: Bull Rally `0%`, Calm `0.0003%`, Crisis `99.9997%`.
- State table: Bull `86.3%` return / `19.7%` vol / `16%` share; Calm `12.8%` / `11.0%` / `53%`; Crisis `-28.7%` / `11.2%` / `31%`.
- Parkinson vol `8.8%`; fast EWMA vol `12.6%`.
- Portfolio inside Crisis: `170` overlap days, annualized return `-46.6%`, annualized volatility `22.2%`.

### Display-level checks

| Check | Calculation / comparison | Rendered result | Verdict |
|---|---|---|---|
| Posterior sum | `0 + 0.0003 + 99.9997` | `100%` | `VERIFIED` |
| Historical state-share sum | `16 + 53 + 31` | `100%` | `VERIFIED` |
| Current-state consistency | Largest posterior is Crisis `99.9997%` | Current regime `Crisis` | `VERIFIED` |
| Empty portfolio handling | No portfolio metrics fabricated | “Add holdings…” message | `VERIFIED` |

Backend source fits a three-state HMM through `detect_regime` and builds the portfolio leg with holding-aware returns (`backend/app/api/analytics.py:2380-2415`). This confirms intended method, not the raw fit.

### Financial verdict

- Probability/share sums and current-state consistency: `VERIFIED` at display precision.
- HMM transition/emission parameters, Viterbi path, annualized state returns, stability, Parkinson/EWMA values, and conditional portfolio return: `UNVERIFIABLE` without raw NIFTY/portfolio series and direct replay.
- Portfolio-in-regime return is additionally limited by missing daily historical FX; AAPL/current-weight input remains conditional on BE-002.

## Accessibility evidence

No empty-state axe capture exists.

- **Seeded desktop:** `color-contrast` serious (1 node), `heading-order` moderate (1).
- **Seeded mobile:** `heading-order` moderate (1), `scrollable-region-focusable` serious (1).
- **Historical desktop:** `color-contrast` serious (1), `heading-order` moderate (1).
- Manual keyboard/focus and screen-reader checks: **not tested**.

Files: `evidence/network/{desktop,mobile}/seeded/dashboard-regime.a11y.json` and `evidence/network/desktop/historical/dashboard-regime.a11y.json`.

## Findings

| ID | Severity | Owner | Evidence-based finding |
|---|---|---|---|
| RG-F01 | **P2 analytical** | Backend analytics/data contract | Mixed-currency portfolio-in-regime return cannot be independently reproduced without daily historical FX. DF-003. |
| RG-F02 | **P1 input dependency** | Backend quote/data path | Conditional portfolio weights inherit the confirmed AAPL quote defect. Existing BE-002/DF-001 dependency. |
| RG-F03 | **P2** | Frontend | Axe evidence includes contrast, heading order, and a mobile non-focusable scrollable region. Part of FE-006. |
| RG-F04 | **Verification blocker** | Analytics owner + QA | HMM and conditional portfolio calculations were not replayed from raw series. Coverage gap, not a claimed numerical defect. |

The empty portfolio's market-regime result with a clear unavailable portfolio leg is a positive control.

## Pending / not tested

- Refresh, Export CSV, explainers, and any loading/error transition.
- Direct raw response/series capture and independent HMM/Viterbi/volatility replay.
- Model relabeling/crash-guard and short-overlap branches.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-regime-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-regime-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-regime-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-regime-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-regime-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-regime-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Refresh control | Refresh produced a second 200 regime request. | `../evidence/network/console/desktop/interactions/regime-refresh-final.txt` |
