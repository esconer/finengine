# Volatility Sizing

**Status:** PARTIAL — dry-run simulation, section evidence, and direct replay are complete; GARCH/EGARCH/target controls and live execution remain untested.

> Evidence paths are relative to `browser-e2e/`.

## Route and fixture

- **Route:** `/dashboard/volatility-sizing`
- **Isolated stack:** frontend `127.0.0.1:3001`; backend `127.0.0.1:8001`, `environment=testing`.
- **Fixture:** `browser-e2e-five-equity-v1`: RELIANCE.NS ×10, HDFCBANK.NS ×20, TCS.BO ×15, AAPL ×5, MSFT ×4. Historical desktop uses `added_on=2025-01-01`; earlier seeded captures predate normalization.
- **Known caveat:** current weights use quote-derived portfolio values, including the confirmed AAPL `$4.89` discrepancy. Recommended weights and trade sizing are therefore conditional on that input.
- **Viewports:** desktop `1440×900`; mobile `390×844`.

## Controls and exercised behavior

| Control / behavior | Source evidence | Browser evidence |
|---|---|---|
| Fetch portfolio, then sizing analytics | `frontend/src/app/dashboard/volatility-sizing/page.tsx:293-381` | Portfolio GET followed by `GET /analytics/volatility-sizing?model=EWMA&target_volatility=0.15` in all states. |
| EWMA / GARCH / EGARCH model cards | `page.tsx:261-265,951-997` | EWMA baseline and dry-run exercised; GARCH/EGARCH cards not separately exercised. |
| Target-volatility range and 10%/15%/20% presets | `page.tsx:1000-1044` | Defaults rendered; **not changed**. |
| Page-specific Refresh | `page.tsx:391-393,879-887` | Desktop present; hidden on mobile by `hidden md:flex`; not clicked. |
| Export CSV | `page.tsx:484-509` | Present; not exercised. |
| Execute Rebalance modal | `page.tsx:395-450,646-851` | Opened in dry-run mode; live mode not opened. |
| Dry-run simulation / live database commit | `page.tsx:414-449,815-845` | Dry-run exercised; live database commit deliberately not exercised. |
| Explainer dialogs | `page.tsx:135-229` | Present; not opened. |

## Desktop and mobile evidence

| State | Desktop 1440×900 | Mobile 390×844 | Observed result |
|---|---|---|---|
| Empty | `evidence/screenshots/desktop/empty/dashboard-volatility-sizing.png`; `evidence/network/pages/desktop/empty/dashboard-volatility-sizing.txt` | `evidence/screenshots/mobile/empty/dashboard-volatility-sizing.png`; `evidence/network/pages/mobile/empty/dashboard-volatility-sizing.txt` | `Est. Portfolio Vol: N/A`; no fabricated recommendations. |
| Seeded | `evidence/screenshots/desktop/seeded/dashboard-volatility-sizing.png`; `evidence/network/pages/desktop/seeded/dashboard-volatility-sizing.txt` | `evidence/screenshots/mobile/seeded/dashboard-volatility-sizing.png`; `evidence/network/pages/mobile/seeded/dashboard-volatility-sizing.txt` | EWMA, target 15%, current estimated vol 23%, five sizing rows. |
| Historical desktop | `evidence/screenshots/desktop/historical/dashboard-volatility-sizing.png`; `evidence/network/pages/desktop/historical/dashboard-volatility-sizing.txt` | **Not captured** | Same default EWMA result after purchase-date normalization. |

The mobile hero remains readable, but the page-specific refresh action is absent below `md`. No touch-target conclusion is drawn from the viewport screenshot alone.

## API, console, and network evidence

| Capture | Observed API traffic | Status | Console / page errors |
|---|---|---|---|
| Empty desktop/mobile | `GET /portfolio?currency=INR`; `GET /analytics/volatility-sizing?model=EWMA&target_volatility=0.15` | Both 200 in both viewports | 0 console errors; 0 page errors. |
| Seeded desktop/mobile | Same two GETs | Both 200 in both viewports | 0 console errors; 0 page errors. |
| Historical desktop | Same two GETs | Both 200 | 0 console errors; 0 page errors. |

Primary files:

- `evidence/network/pages/desktop/{empty,seeded,historical}/dashboard-volatility-sizing.network.json`
- `evidence/network/pages/mobile/{empty,seeded}/dashboard-volatility-sizing.network.json`
- `evidence/network/console/desktop/{empty,seeded,historical}/dashboard-volatility-sizing.console.json`
- `evidence/network/console/mobile/{empty,seeded}/dashboard-volatility-sizing.console.json`

## Calculations and verdicts

### Inverse-volatility replay

Using only the displayed rounded volatilities, normalized `1 / σ` weights are approximately:

| Ticker | Displayed σ | Normalized inverse-vol weight | × disclosed scale `1.2136` | Displayed recommendation |
|---|---:|---:|---:|---:|
| MSFT | 29.6% | 15.52% | 18.83% | 18.8% |
| TCS.BO | 27.8% | 16.52% | 20.05% | 20.1% |
| HDFCBANK.NS | 19.3% | 23.80% | 28.88% | 28.9% |
| RELIANCE.NS | 19.2% | 23.92% | 29.03% | 29.0% |
| AAPL | 22.7% | 20.24% | 24.56% | 24.6% |

- The page's true inverse-volatility invariant is **VERIFIED at displayed precision**.
- Current weights sum to `99.9%` after one-decimal rounding; recommended weights sum to `121.4%`.
- Backend source explicitly sets `cash_weight=max(0,1-scale)`, so scale `1.2136` yields `cash=0` and `leveraged=true` (`backend/app/services/analytics_engine.py:758-827`).
- The page methodology says `leverage required; not full ERC`. The gross allocation is therefore internally explained, but it is not a self-financing 100%-capital recommendation.
- Target/achieved volatility `15.0%` is enforced by multiplying the recommended portfolio by `target / rec_vol`; only the displayed result is evidenced, not a raw covariance replay.

### Share/currency calculation finding

The endpoint converts current weights and portfolio value to INR (`backend/app/api/analytics.py:1283-1379`), but trade sizing computes:

- INR amount = `weight_delta × portfolio_value`
- shares = INR amount ÷ the asset's native `current_price`

at `backend/app/services/analytics_engine.py:788-806`, with no ticker FX conversion. For USD AAPL/MSFT, dry-run share counts are therefore expected to be overstated by the INR/USD rate. This is **source-confirmed but runtime-not-exercised** because the dry-run was not opened/run.

### Financial verdict

- Inverse-volatility relative sizing: `VERIFIED` at display precision.
- Gross leverage/cash treatment: `VERIFIED` from source plus displayed methodology.
- Raw EWMA estimates, target-volatility scaling, and GARCH/EGARCH alternatives: `UNVERIFIABLE` without raw series/model response.
- Dry-run USD share deltas and live rebalance safety: dry-run runtime captured; source-level currency defect and untested live-commit path remain documented.

## Accessibility evidence

No empty-state axe capture exists.

- **Seeded desktop:** `color-contrast` serious (1), `heading-order` moderate (1), `label` critical (1), `nested-interactive` serious (6).
- **Seeded mobile:** `heading-order` moderate (1), `label` critical (1), `nested-interactive` serious (6).
- **Historical desktop:** same 4 rules and node counts as seeded desktop.
- Manual keyboard/focus and screen-reader checks: **not tested**.

Files: `evidence/network/{desktop,mobile}/seeded/dashboard-volatility-sizing.a11y.json` and `evidence/network/desktop/historical/dashboard-volatility-sizing.a11y.json`.

## Findings

| ID | Severity | Owner | Evidence-based finding |
|---|---|---|---|
| VS-F01 | **P1** | Backend analytics sizing service | INR trade capital is divided by native-currency prices to produce share deltas without per-ticker FX conversion. USD dry-run share counts are expected to be wrong by the USD/INR factor; dry-run runtime evidence is captured, while the live path remains untested. |
| VS-F02 | **P2** | Backend sizing contract + frontend safety UX | The displayed recommendation is a `121.4%` gross allocation with zero cash and leverage required. It is disclosed in the bottom methodology, but the primary recommendation table does not show a financing/borrowing requirement. Live execution was not tested. |
| VS-F03 | **P3** | Frontend responsive UI | Page-specific Refresh is hidden below `md`; no in-page refresh is available at 390px. |
| VS-F04 | **P2** | Frontend | Global `Last updated: Never` remains after successful sizing output. |
| VS-F05 | **P2** | Frontend | Axe evidence includes a critical label violation, serious nested controls/contrast, and heading-order issue. Part of FE-006. |
| VS-F06 | **P1 input dependency** | Backend quote/data path | Current weights inherit the known AAPL quote discrepancy. Existing BE-002/DF-001 dependency. |

## Pending / not tested

- GARCH, EGARCH, range input, and all presets.
- CSV export, explainer dialog, and page-specific refresh.
- Dry-run simulation, response review, cancellation, and live rebalance (intentionally not run).
- Raw model response/series capture and independent replay.

## Final internal-scroll evidence

Capture policy: one short-lived Chrome-for-Testing instance per page; guaranteed 5–20 second wait; explicit internal `main`-container scrolling through top, intermediate, and bottom positions.

### Desktop

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/desktop/sections-final/dashboard-volatility-sizing-section-01.png`
- Middle: `../evidence/screenshots/desktop/sections-final/dashboard-volatility-sizing-section-07.png`
- Bottom: `../evidence/screenshots/desktop/sections-final/dashboard-volatility-sizing-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

### Mobile

- 13 section captures; 13 unique images.
- Top: `../evidence/screenshots/mobile/sections-final/dashboard-volatility-sizing-section-01.png`
- Middle: `../evidence/screenshots/mobile/sections-final/dashboard-volatility-sizing-section-07.png`
- Bottom: `../evidence/screenshots/mobile/sections-final/dashboard-volatility-sizing-section-13.png`
- Manifest: `../evidence/runtime/section-capture-manifest.json`

## Browser interaction evidence

| Workflow | Result | Evidence |
|---|---|---|
| Dry-run simulation | Simulation POST returned 200; UI displayed 0 Database Changes; five positions remained. | `../evidence/network/console/desktop/interactions/vol-sizing-simulation.txt` |
| Direct replay | Inverse-volatility and endpoint-consistency checks completed. | `../evidence/calculations/outputs/independent-core-models.md` |
