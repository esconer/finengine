# Goal Probability (Monte Carlo)

**Status:** PARTIAL — all three methods, section evidence, and direct replay are complete; invalid-input and mixed-FX initial-value limitations remain.

> Evidence paths are relative to `browser-e2e/`.

## Route and fixture

- **Route:** `/dashboard/monte-carlo`
- **Isolated stack:** frontend `127.0.0.1:3001`; backend `127.0.0.1:8001`, `environment=testing`.
- **Fixture:** `browser-e2e-five-equity-v1`: RELIANCE.NS ×10, HDFCBANK.NS ×20, TCS.BO ×15, AAPL ×5, MSFT ×4. Historical desktop uses normalized `added_on=2025-01-01`; early seeded captures predate normalization.
- **Default UI inputs:** target `₹200000`, horizon `5` years, Student-t selected, `2000` paths requested.
- **Known caveats:** default initial value is sourced from current position market values; the AAPL quote is wrong, and historical mixed-currency returns lack daily FX.

## Controls and exercised behavior

| Control / behavior | Source evidence | Browser evidence |
|---|---|---|
| Target value input | `frontend/src/app/dashboard/monte-carlo/page.tsx:78-95,135-148` | Default `200000` rendered; not changed. |
| Horizon range, 1–30 years | `page.tsx:149-163` | Default `5 years` rendered; not changed. |
| GBM / Student-t / Bootstrap selector | `page.tsx:38-42,164-184` | All three engines exercised in one browser session. |
| Run simulation | `page.tsx:86-103,187-194` | Clicked for GBM, Student-t, and Bootstrap; each POST returned 200. |
| Probability, terminal percentiles, fan chart, shortfall, disclaimer | `page.tsx:226-288` | Rendered after each of the three runs. |
| Empty guidance | `page.tsx:212-224` | `No simulation yet` rendered in every state. |

## Desktop and mobile evidence

| State | Desktop 1440×900 | Mobile 390×844 | Observed result |
|---|---|---|---|
| Empty | `evidence/screenshots/desktop/empty/dashboard-monte-carlo.png`; `evidence/network/pages/desktop/empty/dashboard-monte-carlo.txt` | `evidence/screenshots/mobile/empty/dashboard-monte-carlo.png`; `evidence/network/pages/mobile/empty/dashboard-monte-carlo.txt` | Input form and `No simulation yet`; no automatic API call. |
| Seeded | `evidence/screenshots/desktop/seeded/dashboard-monte-carlo.png`; `evidence/network/pages/desktop/seeded/dashboard-monte-carlo.txt` | `evidence/screenshots/mobile/seeded/dashboard-monte-carlo.png`; `evidence/network/pages/mobile/seeded/dashboard-monte-carlo.txt` | Same initial state despite five positions. |
| Historical desktop | `evidence/screenshots/desktop/historical/dashboard-monte-carlo.png`; `evidence/network/pages/desktop/historical/dashboard-monte-carlo.txt` | **Not captured** | Same initial state. |

The mobile target input, horizon slider, three engine buttons, and Run button are visible in the viewport capture. Simulation results and post-run overflow were not captured.

## API, console, and network evidence

| Capture | API requests | Status | Console / page errors |
|---|---:|---|---|
| Empty desktop/mobile | 0 | N/A | 0 console errors; 0 page errors. |
| Seeded desktop/mobile | 0 | N/A | 0 console errors; 0 page errors. |
| Historical desktop | 0 | N/A | 0 console errors; 0 page errors. |

No `POST /api/v1/analytics/monte-carlo` exists because the page waits for explicit user action (`frontend/src/app/dashboard/monte-carlo/page.tsx:86-103`).

Primary files:

- `evidence/network/pages/desktop/{empty,seeded,historical}/dashboard-monte-carlo.network.json`
- `evidence/network/pages/mobile/{empty,seeded}/dashboard-monte-carlo.network.json`
- `evidence/network/console/desktop/{empty,seeded,historical}/dashboard-monte-carlo.console.json`
- `evidence/network/console/mobile/{empty,seeded}/dashboard-monte-carlo.console.json`

## Calculations and verdicts

### Browser/model verdict

- Probability of success, terminal percentiles, fan values, expected shortfall, historical μ/σ, Student-t degrees of freedom, and path count were returned for all three runs; exact stochastic-path replay remains `UNDERDETERMINED`.
- The `2000` paths shown while running is a request constant, not evidence that 2000 paths were executed.

### Source-confirmed initial-value defect

The UI says starting value defaults to the current portfolio market value (`frontend/src/app/dashboard/monte-carlo/page.tsx:195-198`). The backend, when no explicit `initial_value` is sent, sums raw `PortfolioPosition.market_value` fields without currency conversion (`backend/app/api/analytics.py:2451-2464`).

For the captured mixed fixture:

- Raw native-value sum used by that source path: `60,202.210009765625` mixed units.
- Independently reconciled INR portfolio total: `249,827.31377746275` INR.

**Verdict:** `DISCREPANCY` by source inspection. With the mixed-currency fixture, a default Student-t/GBM/bootstrap run would use a materially understated and currency-inconsistent starting value. Runtime confirmation is complete for all three methods; the mixed-currency initial-value discrepancy remains.

### Historical-return limitation

The simulation builds a two-year weighted portfolio return series from cached asset returns (`backend/app/api/analytics.py:2466-2488`). It does not receive daily historical FX. Even after fixing initial value, true mixed-currency portfolio return calibration remains `UNVERIFIABLE` under DF-003.

## Accessibility evidence

No empty-state axe capture exists.

- **Seeded desktop:** `color-contrast` serious (3 nodes), `heading-order` moderate (1).
- **Seeded mobile:** `color-contrast` serious (2), `heading-order` moderate (1).
- **Historical desktop:** same 2 rules and node counts as seeded desktop.
- Manual keyboard/focus and screen-reader checks: **not tested**.

Files: `evidence/network/{desktop,mobile}/seeded/dashboard-monte-carlo.a11y.json` and `evidence/network/desktop/historical/dashboard-monte-carlo.a11y.json`.

## Findings

| ID | Severity | Owner | Evidence-based finding |
|---|---|---|---|
| MC-F01 | **P1** | Backend Monte Carlo endpoint | Default `initial_value` sums native position market values across INR and USD positions without FX conversion. The mixed fixture would use `60,202.210009765625` instead of the reconciled `₹249,827.31377746275` base value. Source-confirmed; runtime simulation not yet exercised. |
| MC-F02 | **P2 analytical** | Backend analytics/data contract | Two-year mixed-currency portfolio returns lack daily historical FX, so simulation calibration is not independently reproducible. DF-003. |
| MC-F03 | **P1 input dependency** | Backend quote/data path | Current initial value and weights depend on the confirmed AAPL `$4.89` quote. Existing BE-002/DF-001 dependency. |
| MC-F04 | **P2** | Frontend | Axe evidence includes serious contrast and heading-order violations. Part of FE-006. |
| MC-F05 | **Verification blocker** | Analytics owner + QA | All three method runs are `EXERCISED`; invalid-input paths and exact stochastic reproducibility remain `NOT TESTED`/`UNDERDETERMINED`. |

## Pending / not tested

- All three methods, target/horizon changes, invalid/zero/negative target handling, and run cancellation.
- Runtime confirmation of the source-level mixed-currency initial-value defect.
- Direct raw response/series capture and independent simulation replay.
- Seed/reproducibility and provider/database failure cases.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-monte-carlo-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-monte-carlo-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-monte-carlo-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-monte-carlo-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-monte-carlo-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-monte-carlo-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| All methods | GBM, Student-t, and Bootstrap each produced a 200 POST and rendered result. | `../evidence/network/console/desktop/interactions/monte-carlo-all.txt` |
