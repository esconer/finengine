# Frontend Bugs

Status: complete with explicit manual-a11y and provider-freshness limitations.

## FE-001 — USD view mislabels unconverted native-currency row values

- **Severity:** P1
- **Owner:** frontend primary; backend contract ambiguity contributes
- **Route:** `/portfolio/manage`
- **State:** Mixed INR/USD synthetic portfolio, USD selected
- **Observed:** The backend correctly converts the envelope total to `$2,603.86` and provides `position_currencies`, but position monetary fields remain native. The frontend discards that provenance and formats every row with `$`, visually labeling a mixed-native sum of `60,202.21` as dollars.
- **Expected:** Every value governed by the selected base currency must be converted using the returned FX provenance before rendering, or remain explicitly labeled in its native currency.
- **Evidence:**
  - `evidence/screenshots/states/portfolio-manage-usd.png`
  - `evidence/network/pages/desktop/states/portfolio-manage-usd.txt`
  - `evidence/network/pages/desktop/states/portfolio-usd-api.json`
- **Reproduction:**
  1. Seed INR and USD positions.
  2. Open Portfolio Management.
  3. Select USD.
  4. Compare headline total with per-row current values and totals.

## FE-002 — Add Position assigns India region to US ticker

- **Severity:** P1
- **Owner:** frontend
- **Route:** `/dashboard`, Add Position modal
- **Observed:** Adding `AAPL` through the Dashboard UI submitted `region: "IN"`. The resulting row displayed buy price and current value with INR notation and Unknown sector. Source inspection also shows the CSV importer hard-codes `region: 'IN'`; that importer branch is not yet runtime-proven with a US fixture.
- **Expected:** Region/currency should be inferred from or explicitly selected for the ticker and remain consistent through the API and UI.
- **Evidence:**
  - `evidence/network/pages/desktop/states/msft-add-attempt.network.json`
  - `evidence/screenshots/issues/msft-add-attempt-desktop.png`
  - `evidence/network/pages/desktop/states/us-reseed.json`
  - Manage-page row evidence in the same state capture.

## FE-003 — Dashboard uses a noncanonical, currency-mixed diversification heuristic

- **Severity:** P1
- **Owner:** frontend
- **Route:** `/dashboard`
- **Observed:** Dashboard intentionally computes a composite score from native `market_value / totalValue`, `1/HHI`, a 10-effective-holdings scale, and a sector-count multiplier, but presents it as a diversification score. With mixed INR/USD positions this differs from the concentration API's base-currency arithmetic. The dashboard displayed `18.7%`; the API and independent Decimal replay produced HHI `0.5956`, N_eff `1.68`, and diversification `50.5%` for the returned quotes. Because AAPL is itself discrepant, the 50.5% value is not externally validated as true real-market diversification.
- **Expected:** Use the true base-currency concentration result consistently, or explicitly label a separate heuristic. Empty portfolio must be N/A; N≤1 must be 0%.
- **Evidence:**
  - `evidence/network/pages/desktop/states/concentration-api.json`
  - `evidence/calculations/outputs/portfolio-reconciliation.md`
  - `frontend/src/app/dashboard/page.tsx:106-121`
  - `evidence/network/pages/desktop/historical/dashboard.txt`

## FE-004 — Empty portfolio renders diversification as 0.0%

- **Severity:** P2
- **Owner:** frontend
- **Routes:** `/dashboard`, `/dashboard/concentration`
- **Observed:** Empty Dashboard shows `Diversification Score 0.0%`. The Concentration page goes further and reports HHI `0.00`, “Well Diversified,” “Risk Managed,” and a safely below-limit `0.0%` largest position for a portfolio with no holdings.
- **Expected:** Empty/zero-value portfolio should show N/A/unavailable and no safety verdict. A single holding should show 0% diversification; these states must not be conflated.
- **Evidence:**
  - `evidence/screenshots/desktop/empty/dashboard.png`
  - `evidence/network/pages/desktop/empty/dashboard.txt`
  - `evidence/network/pages/desktop/empty/dashboard-concentration.txt`

## FE-005 — Expected unavailable analytics create avoidable console/API errors on empty state

- **Severity:** P2
- **Owner:** frontend, backend error-contract contribution
- **Routes:** Dashboard, Pairs, Tear Sheet, Risk Contribution, Risk Studio
- **Observed:** Empty-state navigation generates 404 API calls and console errors. Risk Studio issues four unavailable calls; Dashboard and Pairs mainly add console noise, while Risk Contribution/Risk Studio expose visible failure states. Tear Sheet also returned/logged 404 in seeded captures, so it is not exclusively an empty-state issue.
- **Expected:** Empty state should avoid requests that cannot succeed or should suppress expected 404 console noise and render a deliberate unavailable state.
- **Evidence:**
  - `evidence/calculations/outputs/browser-baseline-summary.md`
  - Per-page console/network JSON under `evidence/network/console/desktop/empty/` and `evidence/network/pages/desktop/empty/`.

## FE-006 — Accessibility violations across the product

- **Severity:** P2
- **Owner:** frontend
- **Observed:** Axe recorded violations in 65 of 110 captured page/viewport states: 43/44 seeded captures and 22/22 historical desktop captures. The 148 rule-occurrence records represent 11 unique axe rule IDs, not 148 unique defects. Rules include `button-name`, `select-name`, `label`, `nested-interactive`, `scrollable-region-focusable`, color contrast, heading order, and 404 landmark/H1 issues.
- **Evidence:** `evidence/network/{desktop,mobile}/seeded/*.a11y.json`, `evidence/network/desktop/historical/*.a11y.json`, and the baseline summary.
- **Note:** No empty-state axe capture was run. Manual keyboard and screen-reader validation remains pending.

## FE-007 — Optimizer navigation copy says four strategies while five are exposed

- **Severity:** P3
- **Owner:** frontend
- **Route:** Sidebar → Optimizer
- **Observed:** Sidebar description says “across four strategies”; HRP, min-vol, max-Sharpe, min-CVaR, and Black-Litterman are exposed.
- **Evidence:** Browser snapshot plus `frontend/src/components/layout/Sidebar.tsx:136-142` and `frontend/src/app/dashboard/optimize/page.tsx:49-80`.

## FE-008 — Dashboard P&L mixes converted current value with unconverted mixed-native cost basis

- **Severity:** P1
- **Owner:** frontend
- **Route:** `/dashboard`
- **Observed:** With the five-position mixed-currency fixture, Dashboard displayed unrealized P&L `+₹1,90,377.31` / `+320.23%` while current value was approximately `₹2,50,000`.
- **Independent same-snapshot value:** Applying the returned live USD→INR rate to both current value and cost gives cost `₹244,592.7494`, unrealized P&L `₹5,234.5644`, and return approximately `2.14%`. True acquisition-date historical-FX cost/P&L remains `UNVERIFIABLE` without dated FX, but the displayed result is still invalid because it subtracts values in different currencies.
- **Cause:** `totalValue` is converted to INR, but `totalCost` sums raw `quantity × buy_price` across INR and USD without converting USD costs.
- **Evidence:** Browser-observed `evidence/network/pages/desktop/issues/add-malformed-ticker.txt` and `evidence/screenshots/issues/add-malformed-ticker.png`, plus `evidence/calculations/outputs/portfolio-reconciliation.json`.
- **Expected:** Aggregate both current value and cost basis in one declared base currency before subtracting or computing percentages.

## FE-009 — Portfolio Management header shows stale zero/Never after successful import

- **Severity:** P2
- **Owner:** frontend state synchronization
- **Route:** `/portfolio/manage`
- **Observed:** After importing INFY.NS, the table and statistics updated to six positions, but the header still displayed `0 positions` and `Last updated: Never`.
- **Expected:** Header count and last-updated state must derive from the same refreshed portfolio state as the table.
- **Evidence:** `evidence/network/console/desktop/states/import-csv-submit.txt` and `evidence/screenshots/states/desktop-csv-import-complete.png`.
- **Cleanup:** Temporary INFY.NS was deleted from the isolated database; canonical five-position fixture restored.

## FE-010 — Frontend WebSocket client is not mounted by product pages

- **Severity:** P2
- **Owner:** frontend integration
- **Observed:** A browser load of `/dashboard` produced no frontend WebSocket request or console connection event, while the isolated backend accepted a manually opened browser WebSocket and replied `pong`. Source search found `useRealTime`/`WebSocketClient` but no production page caller.
- **Expected:** If live updates are a product promise, mount one lifecycle owner and expose connected/disconnected state; otherwise remove the dead client/heartbeat surface and document polling as the transport.
- **Evidence:** `evidence/network/console/desktop/interactions/browser-websocket.txt`, `evidence/network/console/desktop/interactions/browser-websocket-ping.txt`, `evidence/runtime/websocket-audit.json`, and `frontend/src/hooks/useRealTime.ts` / `frontend/src/lib/websocket.ts`.

## FE-011 — Stress Testing duplicates the Market Crash POST on populated loads

- **Severity:** P2
- **Owner:** frontend request orchestration
- **Observed:** Populated desktop, mobile, and historical captures each show five stress POSTs for four displayed scenarios; two requests have the identical `{"scenario":"Market Crash"}` body. The direct API contract itself accepts one request per scenario.
- **Expected:** Deduplicate in-flight scenario requests and make the displayed count correspond to unique scenario executions.
- **Evidence:** `evidence/network/pages/desktop/seeded/dashboard-stress-testing.network.json` and matching mobile/historical files; source `frontend/src/app/dashboard/stress-testing/page.tsx:437-470,519-531`.

## FE-012 — Shared shell freshness/count state disagrees across routes

- **Severity:** P2
- **Owner:** frontend store synchronization
- **Observed:** Final section captures show some populated pages with `0 positions` and `Last updated: Never` while other pages show five positions and populated values. Portfolio Management also showed `0 positions` / `Never` after a successful six-position import.
- **Expected:** One portfolio snapshot should drive the header, page counts, and freshness label; unavailable state must be explicit.
- **Evidence:** `evidence/calculations/outputs/desktop-visual-review.md`, `evidence/calculations/outputs/mobile-visual-review.md`, and `evidence/network/console/desktop/states/import-csv-submit.txt`.

## FE-013 — Settings source changes hide broad cache invalidation

- **Severity:** P2
- **Owner:** frontend/backend configuration UX
- **Observed:** The source preference can delete cached time series and analytics broadly, but the Save UI only describes saving a preference. The isolated interaction saved yfinance, restored bfinance, then purged cache; the UI gave no invalidation scope warning.
- **Expected:** Show affected caches, expected latency/freshness impact, and confirmation before a broad invalidation.
- **Evidence:** `evidence/network/console/desktop/interactions/settings-source2.txt`, `evidence/network/console/desktop/interactions/settings-cache.txt`, and `pages/dashboard-settings.md`.

## FE-014 — Responsive section review shows unreachable/clipped content on mobile

- **Severity:** P2/P3
- **Owner:** frontend responsive layout
- **Observed:** Representative final mobile sections show fixed-header obstruction on Tear Sheet, Risk Contribution, and Monte Carlo; clipped controls/tables on Pairs, India Flows, and Portfolio Management; and low-contrast action labels in Settings. The screenshots prove visibility defects; horizontal scroll/keyboard reachability was not fully tested.
- **Expected:** Content should not be hidden under the sticky header, and controls/tables should remain readable and operable at 390px.
- **Evidence:** `evidence/calculations/outputs/mobile-visual-review.md` and the cited section PNGs.


- AI Dossier API exists but has no visible production UI caller.
- Backtesting is API-only; no dedicated page was found.
- `GET /portfolio/{ticker}` and portfolio normalization are API-only.
