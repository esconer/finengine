# Frontend App Router / Pages / Boundaries Audit

**Audit date:** 2026-09-24  
**Scope:** Current working tree at `C:\es\coding\finengine`  
**Mode:** Independent, read-only line audit. No product, config, test, or git files were changed. This report is based on the current files, not prior audit reports.

## Executive summary

The current App Router shell is structurally valid: the root redirect, nested dashboard layout, root `error`/`global-error`/`not-found`, and the `useSearchParams` Suspense boundary are present. The highest-risk issues are at the client/API boundary rather than in JSX syntax:

1. `/dashboard/volatility-sizing` can send scaled weights to the live rebalance endpoint, whose implementation renormalizes them to 100%; target-volatility cash/leverage semantics are therefore lost before the database mutation.
2. `/portfolio/manage` renders forecast volatility/VaR fractions as if they were percentage points and applies 20/40 thresholds to fraction values, producing materially understated risk labels and values.
3. A fresh direct navigation to `/dashboard/realized-risk` has no portfolio bootstrap; the analytics hook refuses to fetch while the persisted Zustand position list is empty, so the route can render an empty/N/A state instead of the backend portfolio.

There are **25 counted findings**: **16 Bug**, **7 Improvement**, **1 Optimization**, and **1 Revamp-needed**. By severity: **P0: 0, P1: 7, P2: 15, P3: 3**.

The highest-value already-fixed-looking patterns were verified rather than re-reported: TanStack cell renderers use `row.original || row`; the copula page binds `tickers` and indexes `matrix[row][col]`; forecast curves are guarded when base forecasts are null; and the main INR displays use `₹`/Indian notation. Those patterns are detailed in the verification section.

## Counts

| Category | P0 | P1 | P2 | P3 | Total |
|---|---:|---:|---:|---:|---:|
| Bug | 0 | 7 | 9 | 0 | 16 |
| Improvement | 0 | 0 | 4 | 3 | 7 |
| Optimization | 0 | 0 | 1 | 0 | 1 |
| Revamp-needed | 0 | 0 | 1 | 0 | 1 |
| **Total** | **0** | **7** | **15** | **3** | **25** |

## Coverage / file list

### App Router files read in full

- `frontend/src/app/layout.tsx` (35 lines)
- `frontend/src/app/page.tsx` (10)
- `frontend/src/app/error.tsx` (26)
- `frontend/src/app/global-error.tsx` (50)
- `frontend/src/app/not-found.tsx` (20)
- `frontend/src/app/globals.css` (26)
- `frontend/src/app/dashboard/layout.tsx` (27)
- `frontend/src/app/dashboard/page.tsx` (619)
- `frontend/src/app/dashboard/settings/page.tsx` (292)
- `frontend/src/app/dashboard/equity-research/page.tsx` (1,215)
- `frontend/src/app/dashboard/screener-studio/page.tsx` (738)
- `frontend/src/app/dashboard/realized-risk/page.tsx` (554)
- `frontend/src/app/dashboard/forecast-risk/page.tsx` (1,113)
- `frontend/src/app/dashboard/factor-exposure/page.tsx` (893)
- `frontend/src/app/dashboard/stress-testing/page.tsx` (1,066)
- `frontend/src/app/dashboard/concentration/page.tsx` (974)
- `frontend/src/app/dashboard/liquidity/page.tsx` (876)
- `frontend/src/app/dashboard/volatility-sizing/page.tsx` (1,269)
- `frontend/src/app/dashboard/tear-sheet/page.tsx` (995)
- `frontend/src/app/dashboard/risk-contribution/page.tsx` (614)
- `frontend/src/app/dashboard/risk-studio/page.tsx` (706)
- `frontend/src/app/dashboard/optimize/page.tsx` (436)
- `frontend/src/app/dashboard/regime/page.tsx` (763)
- `frontend/src/app/dashboard/monte-carlo/page.tsx` (292)
- `frontend/src/app/dashboard/pairs/page.tsx` (117)
- `frontend/src/app/dashboard/india-flows/page.tsx` (216)
- `frontend/src/app/portfolio/manage/page.tsx` (900)

`frontend/src/app/favicon.ico` is a binary asset; it was included in the inventory but has no line-level audit surface. No `loading.tsx`, nested `error.tsx`, or nested `not-found.tsx` files exist under the app tree. The root files above are the only error/not-found boundaries found.

### Configuration files read in full

- `frontend/next.config.ts` (41 lines)
- `frontend/tsconfig.json` (42)
- `frontend/eslint.config.mjs` (33)
- `frontend/postcss.config.mjs` (7)
- `frontend/package.json` (59)

### Supporting boundary files and backend contracts read

- `frontend/src/lib/api.ts`, `frontend/src/lib/store.ts`, `frontend/src/lib/utils.ts`
- `frontend/src/hooks/useAnalytics.ts`, `frontend/src/hooks/useRealTime.ts`
- `frontend/src/types/index.ts`
- `frontend/src/components/layout/DashboardLayout.tsx`, `Header.tsx`, `Sidebar.tsx`
- Relevant backend routes in `backend/app/api/portfolio.py`, `analytics.py`, `data.py`, and `equity_research.py`
- Relevant response models in `backend/app/models/schemas.py`
- Relevant optimization and India-flow service contracts

### Route inventory and notable audit targets

| Route | Status | Main findings / verified notes |
|---|---|---|
| `/` | Compliant | Server redirect is correct (`frontend/src/app/page.tsx:5-10`). |
| `/dashboard` | Defects | F-06, F-16, F-17, F-24, F-25. |
| `/dashboard/settings` | Defects | F-11, F-15, F-17, F-18. |
| `/dashboard/equity-research` | Defect | F-17, F-22, F-24. Suspense boundary is correct. |
| `/dashboard/screener-studio` | Mostly compliant | TanStack accessors are correct; F-15/F-16/F-17 apply. |
| `/dashboard/realized-risk` | Defect | F-01, F-06, F-12, F-15, F-17. |
| `/dashboard/forecast-risk` | Defects | F-12, F-15, F-17. Null-curve guard is correct. |
| `/dashboard/factor-exposure` | Mostly compliant | F-12, F-15, F-17, F-24. Error+null handling is correct. |
| `/dashboard/stress-testing` | Defects | F-16, F-17, F-18. |
| `/dashboard/concentration` | Defect | F-17, F-19, F-24. HHI/diversification math is grounded. |
| `/dashboard/liquidity` | Defect | F-07, F-17, F-24. |
| `/dashboard/volatility-sizing` | Defects | F-03, F-09, F-10, F-17, F-18. |
| `/dashboard/tear-sheet` | Mostly compliant | F-17, F-24. Monthly compounding is deterministic. |
| `/dashboard/risk-contribution` | Mostly compliant | F-06, F-17. CVaR-null handling is correct. |
| `/dashboard/risk-studio` | Defect | F-06, F-17. Matrix parsing is correct. |
| `/dashboard/optimize` | Defect | F-15, F-17, F-21. |
| `/dashboard/regime` | Mostly compliant | F-15, F-17, F-25. |
| `/dashboard/monte-carlo` | Defects | F-12, F-15, F-17, F-24. |
| `/dashboard/pairs` | Defects | F-04, F-15, F-17, F-20. |
| `/dashboard/india-flows` | Mostly compliant | F-15, F-18. Field names match the backend service. |
| `/portfolio/manage` | Defects | F-02, F-05, F-08, F-15, F-17, F-18. It correctly owns its sibling `DashboardLayout` rather than nesting a second dashboard layout. |

## Confirmed current defects

### F-01 — Direct realized-risk navigation has no portfolio bootstrap

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P1
- **Locations:** `frontend/src/app/dashboard/realized-risk/page.tsx:36-52`; `frontend/src/hooks/useAnalytics.ts:30-32,94-106`; `frontend/src/lib/store.ts:230-239`
- **Impact:** On a fresh browser/direct navigation, the persisted Zustand store can be empty. The realized-risk page consumes `usePortfolioAnalytics()` and `usePerformanceData()` but never calls `fetchPortfolio()`. The analytics hook explicitly skips its seven-request fetch when `positions.length === 0`, so the route can settle into a successful-looking N/A state and show an empty universe even when the backend has holdings.
- **Evidence:** The page only destructures the store and analytics hook (`realized-risk/page.tsx:41-44`); the hook's bootstrap condition is `if (positions.length > 0)` (`useAnalytics.ts:96-101`); the persisted state is the only initial source (`store.ts:230-239`). Other pages such as factor exposure and liquidity explicitly call `fetchPortfolio()` (`factor-exposure/page.tsx:314-317`, `liquidity/page.tsx:318-321`).
- **Recommendation (documentation only):** Define a route/data ownership contract that guarantees a current portfolio snapshot before route analytics render, or move the initial portfolio read into the shared App Router shell. Add a direct-navigation acceptance case for an empty persisted store.

### F-02 — Portfolio forecast values are formatted and classified in the wrong units

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P1
- **Locations:** `frontend/src/app/portfolio/manage/page.tsx:80-124,153-158,725-777`; backend contract `backend/app/services/analytics_engine.py:1083-1101` and `backend/app/api/analytics.py:734-748`
- **Impact:** The backend returns annualized volatility and VaR as fractions (for example, `0.25` and `-0.0205`). The management table renders `0.25%` rather than `25.00%`, and `getRiskLevel()` compares `0.25` with `< 20` and `< 40`, so virtually every normal fraction is labeled `Low`. VaR is understated by 100x and the risk badge is quantitatively wrong.
- **Evidence:** Raw values are copied into position state (`manage/page.tsx:109-124`); the formatter uses `.toFixed(2)}%` without multiplying by 100 (`manage/page.tsx:731-754`); thresholds are 20/40 (`manage/page.tsx:153-158`). The backend contract explicitly documents and returns fractions (`analytics_engine.py:1083-1101`).
- **Recommendation (documentation only):** Choose one canonical unit at the API/UI boundary. If the contract remains fractional, document that all consumers must multiply by 100 for display and use `0.20`/`0.40` thresholds; add a regression fixture with a 25% forecast and a -2% VaR.

### F-03 — Live volatility rebalancing discards target-volatility cash/leverage semantics

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P1
- **Locations:** `frontend/src/app/dashboard/volatility-sizing/page.tsx:301-339,414-445,646-845,1171-1181`; backend `backend/app/services/analytics_engine.py:653-715`; mutation endpoint `backend/app/api/portfolio.py:1097-1147`
- **Impact:** The sizing engine scales inverse-volatility weights to a target and returns a `cash_weight` when scale is below one (or can produce a leveraged sum when scale is above one). The page sends only `recommended_weights` to `/portfolio/rebalance`. That endpoint normalizes every submitted weight to sum to 1, removing both the cash remainder and any intended leverage before updating quantities. A user can click “Confirm Live Rebalance” and receive a materially different allocation from the displayed target-volatility proposal.
- **Evidence:** The page passes `sizingData.recommended_weights` directly to `rebalancePortfolio(..., false)` (`volatility-sizing/page.tsx:429-445`). The backend sizing result includes scaled weights and `cash_weight` (`analytics_engine.py:662-715`). The rebalance route computes `normalized_weights = ... / sum_weights` (`portfolio.py:1097-1098`) and mutates using those normalized values (`portfolio.py:1142-1147`).
- **Recommendation (documentation only):** Specify whether live rebalance supports cash, leverage, or only fully invested long-only weights. Require the UI and mutation contract to carry the same target-weight semantics, and add a dry-run/live parity acceptance test for target volatility above and below current volatility.

### F-04 — Pairs page dereferences an optional spread z-score

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P1
- **Locations:** `frontend/src/app/dashboard/pairs/page.tsx:86-102`; backend schema `backend/app/models/schemas.py:342-358`
- **Impact:** `current_spread_zscore` is explicitly optional in the backend response model. The page calls `.toFixed(2)` without a null guard. A valid response with no computable OU/spread value can throw during render, taking down the entire pairs route rather than showing N/A.
- **Evidence:** Backend field declaration is `Optional[float] = None` (`schemas.py:351-353`); frontend uses `p.current_spread_zscore.toFixed(2)` (`pairs/page.tsx:100-102`). The adjacent half-life field is correctly guarded, demonstrating the missing guard is localized.
- **Recommendation (documentation only):** Treat every optional coint field as nullable in the frontend contract and render N/A/unknown explicitly. Add a fixture with `current_spread_zscore: null` to the route acceptance matrix.

### F-05 — USD toggle is a symbol swap, not a currency conversion

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P1
- **Locations:** `frontend/src/app/portfolio/manage/page.tsx:364-365,391-418,468-541,686-715`; backend `backend/app/api/portfolio.py:266-300,315-325`
- **Impact:** Selecting USD changes the formatter and query parameter, but the backend deliberately preserves each position's native-unit `current_value`/`market_value` while converting only the aggregate envelope. The page formats those native values as USD and mixes them with the converted `summary.total_value`, so totals, P&L, buy prices, current values, and VaR can represent different currencies under one view.
- **Evidence:** The page formats every transformed position with the selected currency (`manage/page.tsx:364-365,686-715`). Backend code explicitly says “Preserve the established per-position native-unit response” and returns the converted aggregate separately (`portfolio.py:266-325`).
- **Recommendation (documentation only):** Remove the USD control until a real conversion contract is exposed, or return converted per-position values plus provenance and make all summary/table fields use the same unit. Add INR/USD round-trip acceptance fixtures.

### F-06 — Failed/partial analytics refreshes can leave stale values looking current

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P1
- **Locations:** `frontend/src/hooks/useAnalytics.ts:68-90`; `frontend/src/app/dashboard/page.tsx:63-65,269-284`; `frontend/src/app/dashboard/risk-studio/page.tsx:210-237,399-404`
- **Impact:** On an all-endpoint failure, the analytics hook records an error but does not clear the previous `data`; the dashboard does not consume the hook's `error` at all and only checks the portfolio-store error. Risk Studio uses `Promise.allSettled`, retains the previous value for every rejected endpoint, and only writes a console warning for partial failure. A risk terminal can therefore continue displaying old metrics after a failed refresh without a visible stale marker.
- **Evidence:** The hook's catch path sets only `error` (`useAnalytics.ts:84-90`), while the dashboard ignores that field (`dashboard/page.tsx:63-65`). Risk Studio only calls `setError` when all requests fail and only `console.warn`s for partial failures (`risk-studio/page.tsx:220-226`), leaving prior state intact.
- **Recommendation (documentation only):** Make endpoint freshness/error state first-class: clear or visibly mark stale panels, show the last successful timestamp, and prevent old values from being presented as current after a failed refresh.

### F-07 — Liquidity error envelopes render backend fallback values as valid scores

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P1
- **Locations:** `frontend/src/app/dashboard/liquidity/page.tsx:268-315,595-674,406-409`; backend `backend/app/api/analytics.py:933-942,978-985`
- **Impact:** The backend returns HTTP-success payloads with `error` plus fallback values such as score `5.0`, risk `Medium`, and liquidation `5-10` when there are no positions or no price data. The page displays the embedded error banner but still renders the metric cards and breakdown because its render gates check the separate network `error` state, not `liquidityData.error`. An unavailable portfolio can look like a measured medium-liquidity portfolio.
- **Evidence:** The page explicitly checks `liquidityData?.error` in the banner (`liquidity/page.tsx:595-609`) but renders cards under `!loading` (`liquidity/page.tsx:620-671`). The backend fallback payloads are visible at `analytics.py:933-942` and `analytics.py:978-985`.
- **Recommendation (documentation only):** Treat an embedded error envelope as unavailable data, not as a successful measurement. Suppress score/risk/timeline values or label them explicitly as unavailable; add empty/no-price fixtures to the page contract.

### F-08 — Portfolio-management requests have currency and forecast race windows

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P2
- **Locations:** `frontend/src/app/portfolio/manage/page.tsx:80-151,160-203,205-208`
- **Impact:** The currency effect starts a new portfolio request without a request sequence/abort guard, so a slower USD response can overwrite a newer INR response. Forecast risk is launched fire-and-forget from each portfolio fetch and has no sequence guard; an older forecast can repopulate risk fields after a newer portfolio/currency response, and its loading flag can be cleared out of order. A prior forecast notice is also not cleared at the start of a successful request.
- **Evidence:** `fetchPortfolio()` is re-run from the currency effect (`manage/page.tsx:200-203`), while `fetchForecastRisk()` has no request ID and is invoked with `void` (`manage/page.tsx:189-191`). Its state transitions are unconditional (`manage/page.tsx:80-151`).
- **Recommendation (documentation only):** Document one request lifecycle per currency/universe and require stale-response invalidation, cancellation, and explicit notice clearing before enabling parallel forecast enrichment.

### F-09 — Volatility-sizing ignores backend error envelopes

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P2
- **Locations:** `frontend/src/app/dashboard/volatility-sizing/page.tsx:247-259,301-349,635-674,1151-1192`; backend `backend/app/api/analytics.py:1097-1136`
- **Impact:** The backend returns `{error: ...}` for no positions, zero market value, or no price data. The local response interface has no `error` field, the fetch catch is the only error path, and successful error-envelope responses are installed as `sizingData`. The page can show an empty/N/A sizing canvas with no explanation, which is indistinguishable from a valid portfolio with no actionable data.
- **Evidence:** `VolatilitySizingData` has no error field (`volatility-sizing/page.tsx:247-259`); `fetchSizingData` unconditionally sets the response (`page.tsx:301-311`). Backend error envelopes are returned at `analytics.py:1097-1136`.
- **Recommendation (documentation only):** Add `error`/availability to the UI contract and make error envelopes a visible state before any metric or rebalance action is enabled.

### F-10 — Volatility-sizing turnover is double the backend's one-way turnover

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P2
- **Locations:** `frontend/src/app/dashboard/volatility-sizing/page.tsx:629-633,735-737,1244-1250`; backend `backend/app/api/portfolio.py:1123-1127,1155-1167`
- **Impact:** The page labels the sum of absolute weight changes as “Turnover Delta.” The backend's rebalance response uses one-way turnover (`Σ|Δw| / 2`). The UI can report twice the executable turnover, misleading users about transaction impact and rebalance size.
- **Evidence:** Frontend `totalWeightChange` sums absolute deltas (`volatility-sizing/page.tsx:629-633`) and displays it without halving (`page.tsx:735-737,1244-1250`). Backend calculates `total_turnover_pct` by dividing the same absolute sum by two (`portfolio.py:1123-1127,1155-1167`).
- **Recommendation (documentation only):** Use the backend's one-way turnover field for the headline and label the local gross allocation delta separately if it is still needed.

### F-11 — Settings can overwrite a persisted vendor before its GET resolves

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P2
- **Locations:** `frontend/src/app/dashboard/settings/page.tsx:36-68,75-97,276-287`
- **Impact:** `savedSource` starts as `null`, making `dirty` true and enabling Save before the persisted source is known. If the config GET fails, the page silently keeps the default `bfinance`; a user can save it and unintentionally change a backend preference that was actually `yfinance`. There is no config-loading or config-error state.
- **Evidence:** Initial state and dirty calculation are at `settings/page.tsx:40-52`; the GET catch is intentionally silent (`settings/page.tsx:55-68`); Save is disabled only by `isSaving || !dirty` (`settings/page.tsx:276-287`).
- **Recommendation (documentation only):** Treat config hydration as a first-class state: disable Save until the GET completes, show a read error, and only allow a save after the user has seen the persisted value.

### F-12 — Parameter-driven analysis results are not invalidated while a new request is pending

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P2
- **Locations:** `frontend/src/app/dashboard/monte-carlo/page.tsx:86-103,114-198,226-289`; comparable forecast flow `frontend/src/app/dashboard/forecast-risk/page.tsx:418-431,469-487,910-1032`
- **Impact:** Changing target, horizon, model, or factor lookback starts a request but leaves the previous result visible while loading. Users can read an old probability/curve as if it belonged to the new inputs. The Monte Carlo button also permits non-finite numeric input because it checks only truthiness and `<= 0`.
- **Evidence:** Monte Carlo sets `running` but does not clear/mark `result` before the request (`monte-carlo/page.tsx:86-103`), then renders the existing result in a dimmed block (`page.tsx:226-289`). Forecast similarly sets `loading` without clearing `forecastData` (`forecast-risk/page.tsx:418-431`) and renders curves from the existing data (`page.tsx:910-1032`).
- **Recommendation (documentation only):** Define a pending/result state machine that binds each result to its input snapshot, invalidates stale results on change, and validates finite positive numeric values before enabling execution.

### F-13 — Route/global error boundaries expose raw exception messages

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P2
- **Locations:** `frontend/src/app/error.tsx:3-17`; `frontend/src/app/global-error.tsx:3-30`
- **Impact:** Raw `error.message` values are rendered directly to users. Depending on the failure source, this can expose upstream/vendor details, internal URLs, SQL/provider text, or implementation information. It also gives users no stable support code even though the boundaries accept `digest`.
- **Evidence:** Both components use `{error?.message || ...}` in visible text (`error.tsx:15-17`, `global-error.tsx:28-30`); `digest` is typed but never displayed.
- **Recommendation (documentation only):** Use a sanitized user-facing message plus a support/reference identifier in production, while retaining the full error in protected telemetry.

### F-14 — API error normalization discards structured FastAPI details

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P2
- **Locations:** `frontend/src/lib/api.ts:57-80,96-111`; structured backend example `backend/app/api/portfolio.py:351-360`
- **Impact:** The backend returns useful structured `detail` objects for invalid tickers, including `message`, `error`, and suggestions. `buildApiErrorMessage()` only handles string/array `detail`; an object detail falls through to `HTTP 400`. Users lose the actionable validation message and the UI cannot show suggestions consistently.
- **Evidence:** The builder ignores object details (`api.ts:62-79`), while the portfolio add route emits a dict detail (`portfolio.py:351-360`).
- **Recommendation (documentation only):** Define and document a recursive FastAPI error-envelope normalizer that extracts safe `message`/`error` fields and preserves structured validation metadata separately.

### F-15 — App Router has no segment-level loading/error boundary for client-fetched routes

- **Status:** Confirmed current defect
- **Category:** Improvement
- **Severity:** P2
- **Locations:** `frontend/src/app/dashboard/layout.tsx:17-27`; representative client routes `frontend/src/app/dashboard/page.tsx:1-3`, `realized-risk/page.tsx:5-10`, `portfolio/manage/page.tsx:1-7`; app inventory has no `loading.tsx` or nested `error.tsx`
- **Impact:** The server-rendered App Router shell streams only a client boundary. Route transitions do not have a segment-level Suspense fallback, and most data failures are handled by ad hoc client state rather than route error boundaries. This creates blank/previous-content transitions, duplicated loading patterns, and inconsistent recovery behavior.
- **Evidence:** The dashboard layout only renders `DashboardLayout` around children (`dashboard/layout.tsx:17-27`); all data pages opt into client rendering (`dashboard/page.tsx:1`, `realized-risk/page.tsx:5`, `portfolio/manage/page.tsx:6`). No loading/error files were present in the app inventory.
- **Recommendation (documentation only):** Establish a route-segment contract: server-fetch initial data where appropriate, add shared `loading.tsx` and nested `error.tsx` policies, and reserve client effects for interaction-driven refreshes.

### F-16 — Initial analytics fan-out is duplicated and stress scenarios run serially

- **Status:** Confirmed current defect
- **Category:** Optimization
- **Severity:** P2
- **Locations:** `frontend/src/hooks/useAnalytics.ts:43-60`; `frontend/src/app/dashboard/page.tsx:63-90`; `frontend/src/app/dashboard/concentration/page.tsx:438-447`; `frontend/src/app/dashboard/liquidity/page.tsx:318-327`; `frontend/src/app/dashboard/stress-testing/page.tsx:437-469`
- **Impact:** The shared analytics hook launches seven analytics requests for every consumer, while the dashboard adds two supplementary requests. Concentration and liquidity fetch once on mount and again when positions hydrate. Stress “Run All” uses a sequential `for` loop even though the page describes the scenarios as concurrent. This multiplies vendor/database work and makes first paint slower, especially on cold caches.
- **Evidence:** Seven requests are issued in one hook (`useAnalytics.ts:43-60`); dashboard adds regime and risk contribution (`dashboard/page.tsx:73-90`); both pages fetch again from a positions effect (`concentration/page.tsx:438-447`, `liquidity/page.tsx:318-327`); stress awaits each scenario before the next (`stress-testing/page.tsx:443-455`).
- **Recommendation (documentation only):** Define route-specific query ownership, deduplicate identical in-flight requests, and choose a bounded concurrency policy for scenario batches with visible partial-progress semantics.

### F-17 — Custom dialogs and button-like cards lack a consistent focus/pressed-state model

- **Status:** Confirmed current defect
- **Category:** Revamp-needed
- **Severity:** P2
- **Locations:** `frontend/src/app/dashboard/factor-exposure/page.tsx:125-159`; `frontend/src/app/dashboard/forecast-risk/page.tsx:186-212,805-850`; `frontend/src/app/portfolio/manage/page.tsx:853-861`; `frontend/src/app/dashboard/stress-testing/page.tsx:843-857`
- **Impact:** The factor modal has no dialog role/label, Escape handling, or backdrop dismissal. Other custom dialogs have a role but no focus trap, initial focus, focus restoration, or background inerting. Scenario/model cards use `role="button"`/`tabIndex` without `aria-pressed` or `aria-selected`, so assistive technology cannot reliably communicate the selected state.
- **Evidence:** Factor's modal wrapper is a plain fixed `div` (`factor-exposure/page.tsx:125-159`); the other examples show the missing focus lifecycle despite `role="dialog"` (`forecast-risk/page.tsx:203-212`, `portfolio/manage/page.tsx:853-861`). Keyboard handlers exist on card divs but no pressed state is exposed (`forecast-risk/page.tsx:805-850`, `stress-testing/page.tsx:843-857`).
- **Recommendation (documentation only):** Standardize on one accessible dialog primitive and document focus entry/trap/restore, Escape/overlay behavior, and selected-state semantics for all custom controls.

### F-18 — Several mobile action rows do not wrap

- **Status:** Confirmed current defect
- **Category:** Improvement
- **Severity:** P2
- **Locations:** `frontend/src/app/portfolio/manage/page.tsx:391-445`; `frontend/src/app/dashboard/stress-testing/page.tsx:703-720`; `frontend/src/app/dashboard/india-flows/page.tsx:44-67`
- **Impact:** The management page places a currency toggle plus three action buttons in one non-wrapping flex row. Stress-testing places two wide action controls in the hero row, and India Flows places title plus refresh in a non-responsive row. At narrow widths these controls can overflow the viewport or force horizontal page scrolling, even though the rest of the app uses responsive grids/tables.
- **Evidence:** The management action container is `flex items-center space-x-4` with no `flex-wrap` (`manage/page.tsx:391-445`); stress uses a fixed action row (`stress-testing/page.tsx:703-720`); India Flows uses `flex justify-between items-center` (`india-flows/page.tsx:44-67`).
- **Recommendation (documentation only):** Specify mobile breakpoints and wrapping/stacking behavior for every page header/action group, then verify at narrow phone widths with long localized labels.

### F-19 — Concentration assessment can label a single holding “Moderate Diversification”

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P2
- **Locations:** `frontend/src/app/dashboard/concentration/page.tsx:480-517,599-601,862-905`
- **Impact:** The diversification score correctly forces 0% for one holding, but the risk-assessment cards independently count statuses. `effective_positions` is hard-coded to status `Good`, and the first card uses “Well Diversified” only when at least three of four metrics are Good; a single holding can therefore display “Moderate Diversification” despite a 0% score and HHI near 1.0.
- **Evidence:** Effective positions always receives `status: 'Good'` (`concentration/page.tsx:510-517`); the assessment text uses the count of Good statuses (`page.tsx:862-873`); the zero-state score guard is separate at `page.tsx:599-601`.
- **Recommendation (documentation only):** Derive the qualitative tier from the same N/HHI/largest/top-three inputs as the score, with an explicit single-holding/high-concentration state and no independent “Good” default.

### F-20 — Pairs page hides scan metadata and mixes rejected/non-cointegrated rows into one table

- **Status:** Confirmed current defect
- **Category:** Improvement
- **Severity:** P2
- **Locations:** `frontend/src/app/dashboard/pairs/page.tsx:62-113`; backend `backend/app/services/cointegration_service.py:511-539`; schema `backend/app/models/schemas.py:361-367`
- **Impact:** The backend intentionally keeps non-cointegrated pairs in `pairs` while filtering only cointegrated pairs by half-life. The page's empty state is based on `pairs.length === 0`, so a non-empty non-cointegrated result is shown under a generic “Ranked ... Pairs” heading without `as_of`, universe size, scanned count, cointegrated count, or the active p-value threshold. Users can mistake a non-cointegrated row for a discovered pair.
- **Evidence:** The service explicitly retains non-cointegrated rows (`cointegration_service.py:518-531`) and returns counts/as-of (`schemas.py:361-367`); the page only checks array emptiness and ignores all metadata (`pairs/page.tsx:62-113`).
- **Recommendation (documentation only):** Render cointegrated and non-cointegrated sections separately, expose scan metadata and thresholds, and make the empty state mean zero cointegrated pairs rather than zero rows.

### F-21 — Black-Litterman is selectable without any view inputs

- **Status:** Confirmed current defect
- **Category:** Improvement
- **Severity:** P2
- **Locations:** `frontend/src/app/dashboard/optimize/page.tsx:49-80,147-192`; backend request contract `backend/app/api/analytics.py:58-80`; backend behavior `backend/app/services/optimization_service.py:229-267`
- **Impact:** The UI advertises “subjective investor conviction,” but the page sends only `{strategy}`. With no `views` or `relative_views`, the backend takes the equilibrium-prior branch and returns a prior-only allocation. The user cannot enter the views that distinguish this strategy from a generic equilibrium optimization.
- **Evidence:** The strategy is exposed in the selector (`optimize/page.tsx:74-80`), while `runOptimization()` sends only `strategy` (`page.tsx:88-93`). The backend request supports view fields (`analytics.py:58-80`), but the service uses `mu_bl = pi` when no views are supplied (`optimization_service.py:249-267`).
- **Recommendation (documentation either:** Document the prior-only fallback prominently or add a designed view-entry flow with validation, units, and a clear distinction between absolute and relative views.

### F-22 — Equity-research query parameter is not synchronized after initial mount

- **Status:** Confirmed current defect
- **Category:** Bug
- **Severity:** P2
- **Locations:** `frontend/src/app/dashboard/equity-research/page.tsx:43-47,126-128,161-166`
- **Impact:** `useSearchParams()` is read only to initialize state. A later client navigation that changes `?ticker=` while this route remains mounted does not update `activeTicker` or trigger `fetchAllData()`. The URL can say one company while the terminal continues showing another, and search submission does not update the URL for shareable/back-button behavior.
- **Evidence:** `initialTicker` is used in `useState` initializers only (`equity-research/page.tsx:44-47`); the data effect depends solely on `[activeTicker]` (`page.tsx:126-128`); `handleSearch` only sets state (`page.tsx:161-166`).
- **Recommendation (documentation only):** Define query-param ownership explicitly: either make the URL the source of truth and sync it on every search/peer selection, or update the URL on every state transition and handle back/forward changes.

### F-23 — Frontend DTO types do not match the performance-history response

- **Status:** Confirmed current defect
- **Category:** Improvement
- **Severity:** P3
- **Locations:** `frontend/src/lib/api.ts:408-415`; `frontend/src/hooks/useAnalytics.ts:116-137`; backend `backend/app/api/analytics.py:1453-1465`
- **Impact:** The API wrapper declares `{date, value, benchmark?}`, but the backend returns `portfolio_value`, `return`, and optional `benchmark_value`. The hook currently works only because `performanceData` is `any[]` and it reads the undeclared `portfolio_value` field. A future type cleanup or alternate API response will silently break charts.
- **Evidence:** The incorrect public return type is at `api.ts:408-415`; the hook's `any[]` and `p.portfolio_value` access are at `useAnalytics.ts:116-137`; the actual backend keys are at `analytics.py:1453-1465`.
- **Recommendation (documentation only):** Define one shared, backend-aligned DTO for the performance series and eliminate the `any` escape hatch before relying on strict TypeScript for chart contracts.

### F-24 — Chart-heavy pages lack equivalent accessible data views and heading structure is duplicated

- **Status:** Confirmed current defect
- **Category:** Improvement
- **Severity:** P3
- **Locations:** `frontend/src/components/layout/DashboardLayout.tsx:87-98`; chart examples `frontend/src/app/dashboard/forecast-risk/page.tsx:929-1023`, `realized-risk/page.tsx:440-485`, `concentration/page.tsx:738-771`, `optimize/page.tsx:331-393`, `equity-research/page.tsx:758-826`
- **Impact:** Recharts visualizations are primarily visual surfaces without keyboard-readable summaries or adjacent data tables. The layout header renders an `h1` for the route title while most pages render another `h1` hero title, creating ambiguous document structure for screen readers and SEO/accessibility tooling.
- **Evidence:** The shared header's title is an `h1` (`DashboardLayout.tsx:87-98`), while the dashboard page hero also uses `h1` (`dashboard/page.tsx:289-295`). The chart blocks shown above contain axes/series but no equivalent textual data summary; the custom Monte Carlo SVG is the exception with a basic `role="img"` label (`monte-carlo/page.tsx:62-74`).
- **Recommendation (documentation only):** Define a chart accessibility standard (summary, latest values, units, data-table/screen-reader alternative) and a heading hierarchy where the layout supplies one page title and page content uses section headings.

### F-25 — “Live data” toggle is cosmetic in the audited route shell

- **Status:** Confirmed current defect
- **Category:** Improvement
- **Severity:** P3
- **Locations:** `frontend/src/app/dashboard/page.tsx:297-305`; toggle state `frontend/src/lib/store.ts:247-285`; available auto-refresh implementation `frontend/src/hooks/useRealTime.ts:11-16,63-85`
- **Impact:** The dashboard labels the state “Live Data Active/Off,” and the header animates a refresh icon, but the app routes do not invoke `useAutoRefresh` or a WebSocket subscription to change fetch behavior. Users can believe data is live when the toggle only changes presentation.
- **Evidence:** The dashboard only reads `liveDataMode` to choose the chip text (`dashboard/page.tsx:297-305`); the store action only flips a boolean (`store.ts:270-272`); the real auto-refresh hook exists separately (`useRealTime.ts:11-16,63-85`) but has no app-route call site.
- **Recommendation (documentation only):** Either wire the toggle to the documented refresh/stream lifecycle and expose connection/freshness state, or rename it to a preference that accurately describes its behavior.

## Already-fixed-looking / verified patterns (not counted as current defects)

These were checked because the project guidance calls them out explicitly. They are current-code compliance observations, not claims based on old reports.

- **TanStack Table accessors:** All audited cell renderers in dashboard summary, concentration, factor exposure, forecast risk, liquidity, realized risk, screener studio, stress testing, and volatility sizing use the required `const data = row.original || row;` pattern. Representative locations: `dashboard/page.tsx:164-220`, `concentration/page.tsx:525-575`, `factor-exposure/page.tsx:400-485`, `forecast-risk/page.tsx:511-573`, `liquidity/page.tsx:421-528`, `realized-risk/page.tsx:143-241`, `screener-studio/page.tsx:223-370`, `stress-testing/page.tsx:586-613`, `volatility-sizing/page.tsx:521-614`.
- **Bivariate matrix parsing:** Risk Studio explicitly binds the nested `tail_dependence_matrix.tickers` and `.matrix` (with legacy top-level fallbacks) at `dashboard/risk-studio/page.tsx:277-285`, then uses row/column indices at `page.tsx:551-565`; it does not iterate `Object.keys()` over the outer response object. The defensive `?? (r === c ? 1.0 : 0.0)` fallback at `page.tsx:555` should be documented as a display fallback, but it is not a current contract mismatch for the complete backend matrix.
- **Forecast null handling:** The forecast curve builder returns an empty guarded state when portfolio volatility/VaR/CVaR are null (`forecast-risk/page.tsx:364-415`) and renders an explicit unavailable panel rather than a synthetic curve (`page.tsx:910-1031`). The ±20% lines are explicitly labeled illustrative (`page.tsx:935-943`).
- **Zero-state portfolio weight:** The screener add-to-portfolio path calculates 1.0 for an empty/zero-value portfolio (`screener-studio/page.tsx:163-183`); no arbitrary `100000` fallback was found in the audited app pages.
- **INR/Indian formatting:** Dashboard values use `₹` plus `en-IN` (`dashboard/page.tsx:198-210,332-341`); India Flows formats rupees with `en-IN` and Cr/L notation (`india-flows/page.tsx:180-184`); equity research uses `₹` and `en-IN` for prices (`equity-research/page.tsx:409-416`). The USD and large-number exceptions are captured separately in F-05 and F-23 rather than treated as compliant everywhere.
- **SearchParams Suspense:** Equity Research correctly wraps `useSearchParams()` in a client Suspense boundary (`equity-research/page.tsx:1202-1215`), satisfying the App Router prerender rule.
- **Root/nested layout shape:** `/` is a server redirect; `/dashboard` has one dashboard layout; `/portfolio/manage` is a sibling route and explicitly supplies its own `DashboardLayout`, so the current file is not a double-dashboard-layout defect. The concern is the client-only data lifecycle (F-01/F-15), not duplicate layout mounting.
- **Deterministic monthly compounding:** The tear sheet compounds already-monthly return values geometrically for year totals (`tear-sheet/page.tsx:357-367`); the backend also compounds daily returns by year/month before returning them (`backend/app/api/analytics.py:1679-1688`).
- **Ticker suffix handling:** The audited app pages pass tickers through to backend validators rather than imposing a narrower frontend regex. NSE/BSE suffix support remains a backend/input-modal contract and no contradictory app-level regex was found in this scope.

## Priority order

1. **F-03:** Stop/clarify the live rebalance contract before exposing a database mutation that cannot represent target-volatility cash/leverage semantics.
2. **F-02:** Establish and enforce fractional-vs-percentage units at the API/UI boundary; the current labels are quantitatively wrong.
3. **F-01:** Guarantee portfolio bootstrap for direct route navigation; otherwise valid backend holdings can be hidden by an empty persisted client store.
4. **F-05, F-04, F-07:** Fix currency truthfulness, optional-field rendering, and embedded-error fallback behavior before expanding the terminal surface.
5. **F-06, F-08, F-09, F-12:** Make stale/failed/in-flight states explicit so risk values are never presented as current by accident.
6. **F-15–F-25:** Address the shared App Router, performance, accessibility, responsiveness, and type-contract debt after correctness blockers are closed.

## Audit limitations

- This was a static/read-only audit. No browser session, live backend response, or production build was used, so runtime network/CORS behavior and visual breakpoints were not independently executed.
- Backend files were consulted only where needed to verify response units, optionality, error envelopes, and mutation semantics. Recommendations above are documentation/acceptance guidance, not code changes.
- The binary favicon has no line-level findings, and findings about shared components are included only where they directly affect the audited App Router pages.
