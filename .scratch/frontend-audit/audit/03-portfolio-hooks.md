# Wave 1 Frontend Audit — Portfolio Components + Hooks

**Audit date:** 2026-09-24  
**Mode:** Independent, read-only static source audit  
**Primary scope:** `frontend/src/components/portfolio/**` and `frontend/src/hooks/**`  
**Result:** **29 findings — 0 P0, 12 P1, 15 P2, 2 P3**

## Executive summary

The audited portfolio UI has several correct local safeguards, especially the first-position 100% weight path, ticker-format acceptance, explicit CSV-import acknowledgment, and fail-closed behavior when the add-position portfolio total cannot be loaded. The highest-risk issues are nevertheless material:

1. CSV import can durably commit rows and then return HTTP 500 when the optional purchase date is absent; the same importer also treats a partial backend success as a complete success.
2. Currency semantics are mixed: the backend deliberately returns per-position money in native units while the envelope total is converted, but add-position, table, and statistics code compare or label those values as if they all used one currency.
3. Analytics have no canonical client cache/bootstrap contract. The realized-risk route does not load the portfolio itself, empty-state transitions retain old analytics, failures are hidden, and every consumer fans out to seven endpoints with no `staleTime` or mutation invalidation.

No P0 issue was found. P1 denotes current correctness, data-integrity, or materially broken-route risk; P2 denotes moderate UX, lifecycle, accessibility, or performance risk; P3 denotes minor polish or latent maintainability risk.

## Top 3 findings

### 1. Bulk import has two independent correctness failures

- `frontend/src/components/portfolio/PortfolioDropzone.tsx:168-186` ignores `added`, `failed`, `duplicates`, and `failures`, then always calls `onSuccess()` and closes.
- `backend/app/models/schemas.py:19,61-88,297-308` allows `added_on` to be absent but declares response `added_on` as a required `datetime`.
- `backend/app/api/portfolio.py:569-571,653-689` commits rows and then constructs the response; a row without `added_on` can fail response validation **after the durable commit**, producing a 500 even though the import changed the portfolio.

**Impact:** Users can see failure for data that was actually imported, then retry into duplicate/partial states; true partial imports are also reported as success.

### 2. Native and target currencies are mixed throughout add/display flows

- `backend/app/api/portfolio.py:242-325` explicitly returns `total_value` in the requested currency while preserving each position's monetary fields in native units.
- `frontend/src/components/portfolio/AddPositionModalSimple.tsx:42-45,82-90` combines that converted aggregate with `quantity * buy_price` from the entered/native currency to estimate weight.
- `frontend/src/components/portfolio/PortfolioTable.tsx:112-115,154-192` and `frontend/src/components/portfolio/PortfolioStats.tsx:43-79,188-212` sum and format native position values as the selected display currency, and the table discards the backend's converted live weight by recomputing from native values.

**Impact:** INR holdings can be displayed as dollars after toggling USD, aggregate cards and row values can disagree, mixed-currency additions can submit materially incorrect stored weights, and displayed financial values can be false by an FX factor.

### 3. Analytics bootstrap/cache/error state is not reliable

- `frontend/src/hooks/useAnalytics.ts:34-106` fetches seven endpoints in local state but never fetches the portfolio. `/dashboard/realized-risk` only reads the store (`frontend/src/app/dashboard/realized-risk/page.tsx:41-44`), so a direct first visit can remain empty.
- `frontend/src/hooks/useAnalytics.ts:96-101` does not clear prior analytics when positions become empty.
- `frontend/src/hooks/useAnalytics.ts:65-82,108-113` exposes only an all-or-nothing error and hides partial failures; dashboard does not consume that error.
- TanStack Query is installed (`frontend/package.json:23`) but there is no `QueryClientProvider`, `useQuery`, query key, `staleTime`, retry policy, or invalidation anywhere in `frontend/src`.

**Impact:** Routes can show stale or empty metrics, endpoint outages look like valid N/A data, and navigation/mounts repeat expensive quant requests without deduplication or portfolio-write invalidation.

## Counts

### By category

| Category | Count |
|---|---:|
| Bug | 19 |
| Improvement | 5 |
| Optimization | 2 |
| Revamp-needed | 3 |
| **Total** | **29** |

### By severity

| Severity | Count |
|---|---:|
| P0 | 0 |
| P1 | 12 |
| P2 | 15 |
| P3 | 2 |
| **Total** | **29** |

### Category × severity

| Category | P0 | P1 | P2 | P3 | Total |
|---|---:|---:|---:|---:|---:|
| Bug | 0 | 10 | 9 | 0 | 19 |
| Improvement | 0 | 0 | 4 | 1 | 5 |
| Optimization | 0 | 0 | 1 | 1 | 2 |
| Revamp-needed | 0 | 2 | 1 | 0 | 3 |
| **Total** | **0** | **12** | **15** | **2** | **29** |

## Detailed findings

### F-01 — Direct realized-risk navigation has no portfolio bootstrap

- **Location:** `frontend/src/hooks/useAnalytics.ts:31,96-106`; `frontend/src/app/dashboard/realized-risk/page.tsx:41-44`; `frontend/src/app/layout.tsx:21-33`
- **Category:** Bug
- **Severity:** P1
- **Evidence:** Both analytics hooks only read `positions` from Zustand. `usePortfolioAnalytics` calls its seven APIs only when `positions.length > 0`; it never calls the store's `fetchPortfolio`. The realized-risk page destructures `positions` but does not fetch it. The root layout renders only `children`; that route does not mount `DashboardLayout`, `Header`, or any other initial portfolio loader.
- **Impact:** Direct navigation to `/dashboard/realized-risk` on a first session can show no portfolio analytics even when holdings exist server-side. A hydrated persisted store can instead show stale holdings until some unrelated action refreshes them.
- **Recommendation:** Make portfolio loading a shared query/bootstrap responsibility. The analytics queries should depend on a canonical portfolio query that fetches once, or the route/layout must explicitly await `fetchPortfolio` before enabling analytics requests.

### F-02 — Empty portfolio transitions retain previously fetched analytics

- **Location:** `frontend/src/hooks/useAnalytics.ts:20-28,96-101,108-113`
- **Category:** Bug
- **Severity:** P1
- **Evidence:** When positions are empty, the effect only calls `setLoading(false)`. It does not reset `data`, clear a previous `error`, or invalidate a completed request's local result. `data` remains the last non-empty portfolio's seven response objects.
- **Impact:** After holdings are removed elsewhere, portfolio-level cards can continue rendering the deleted portfolio's risk, volatility, drawdown, and concentration values beside an empty holdings table.
- **Recommendation:** On an empty canonical portfolio query, synchronously reset every analytics slice to `null`/an explicit empty response and clear errors. Prefer query-key removal/invalidation over a second ad hoc local-state cache.

### F-03 — No TanStack Query cache, stale policy, deduplication, or write invalidation

- **Location:** `frontend/src/hooks/useAnalytics.ts:19-114`; `frontend/src/app/dashboard/page.tsx:63-65,229-267`; `frontend/src/app/dashboard/realized-risk/page.tsx:41-42,114-119`; `frontend/package.json:23`
- **Category:** Revamp-needed
- **Severity:** P1
- **Evidence:** `@tanstack/react-query` is installed, but a source-wide search finds no `QueryClientProvider`, `useQuery`, `useMutation`, `staleTime`, `invalidateQueries`, or query keys. Every analytics consumer starts seven local-state requests. The realized-risk page needs realized risk/performance but still receives the full seven-endpoint bundle. Portfolio writes manually refetch the REST portfolio and rely on incidental key changes to trigger analytics; there is no explicit invalidation.
- **Impact:** Expensive analytics are recomputed on every mount/navigation, simultaneous consumers cannot share results, staleTime/background refresh semantics are undefined, and portfolio mutations can leave summary/risk/performance slices from different generations.
- **Recommendation:** Split queries by endpoint and consumer need, use stable portfolio-derived keys, define endpoint-specific `staleTime`/retry/refetch behavior, and invalidate all portfolio-dependent analytics after add/update/delete/import and relevant WebSocket portfolio updates.

### F-04 — Partial analytics failures are converted to silent N/A data

- **Location:** `frontend/src/hooks/useAnalytics.ts:43-82,108-113`; `frontend/src/app/dashboard/page.tsx:63`; backend null/flag examples at `backend/app/api/analytics.py:398-434,770-801,1158-1199,1228-1284`
- **Category:** Bug
- **Severity:** P1
- **Evidence:** `Promise.allSettled` preserves partial results, but a partial rejection is only written to `console.warn`; the corresponding slice becomes `null` and `error` remains `null`. Dashboard does not destructure the hook's `error`. Backend analytics also return HTTP 200 bodies containing `error` for no data/no price history, which are treated as fulfilled successful data.
- **Impact:** A transport failure, a valid no-data response, and a missing-history limitation all collapse into the same N/A/unknown UI. Operators lose the endpoint-level failure signal and users cannot distinguish a calculated zero from unavailable analytics.
- **Recommendation:** Return per-slice states (`data`, `status`, `error`, `updatedAt`, `isStale`) and surface an accessible partial-failure banner. Validate successful response bodies for backend `error`/null-flag contracts instead of treating HTTP 200 as complete success.

### F-05 — Frontend DTOs materially diverge from current backend schemas

- **Location:** `frontend/src/types/index.ts:2-28,43-49,55-114,165-186`; `frontend/src/lib/api.ts:132-160,337-414`; `backend/app/models/schemas.py:61-106,303-308`; `backend/app/api/analytics.py:602-609,1453-1467`
- **Category:** Revamp-needed
- **Severity:** P1
- **Evidence:**
  - Frontend `PortfolioPosition` requires `region`, `primary_source`, `fallback_source`, and `last_validated_source`; backend `PortfolioPositionResponse` does not return those fields.
  - Frontend `PortfolioSummary` omits backend `currency`, `base_currency`, `currency_provenance`, and `position_currencies`, which are required to interpret monetary fields correctly.
  - `analyticsApi.getRealizedRisk` is typed as top-level metrics plus `by_position`, while the endpoint returns `{ portfolio, positions, instrument_risk, ... }`.
  - `getPerformanceHistory` is typed with `value`, while the endpoint returns `portfolio_value`, `return`, and optional `benchmark_value`.
  - `bulkAddPositions` claims a `success` field that backend `BulkAddResponse` does not define, while omitting backend `submitted`, `skipped`, `duplicates`, and `failures`.
  - `AnalyticsData` and most analytics API fields are `any`, hiding these mismatches from strict TypeScript.
- **Impact:** The compiler cannot protect currency, optionality, or chart bindings; callers reasonably read nonexistent fields or treat native values as converted. Future endpoint changes can silently render incorrect financial data.
- **Recommendation:** Replace handwritten partial DTOs with explicit contracts generated from or directly checked against FastAPI OpenAPI. Make currency metadata and nullable dates first-class, then remove `any` from portfolio/analytics boundaries before migration work is layered on top.

### F-06 — Optional-date CSV rows can commit and then return HTTP 500

- **Location:** `frontend/src/components/portfolio/PortfolioDropzone.tsx:111-112,168-177`; `backend/app/models/schemas.py:11-19,76-94,297-308`; `backend/app/api/portfolio.py:563-580,623-663,665-690`
- **Category:** Bug
- **Severity:** P1
- **Evidence:** The importer documents purchase date as optional and omits `added_on` when no valid date exists. `PortfolioPositionBase.added_on` is optional, so backend creation permits `None`. The durable commit occurs at `portfolio.py:644-645`; afterward response construction passes `position.added_on` into a response schema where `added_on: datetime` is mandatory. That post-commit validation error reaches the outer handler and becomes a generic HTTP 500 even though `committed` is already true.
- **Impact:** A generic CSV without a date can change the portfolio but return 500. The UI reports failure, the user retries, and duplicate handling produces an inconsistent recovery experience.
- **Recommendation:** Make response `added_on` nullable (and frontend nullable), or assign a documented default before commit. Add a post-commit-safe response contract and regression test for a bulk row with no date.

### F-07 — Partial bulk import is always reported as complete success

- **Location:** `frontend/src/components/portfolio/PortfolioDropzone.tsx:155-190`; `backend/app/api/portfolio.py:486-535,548-585,692-704`; `backend/app/models/schemas.py:303-308`
- **Category:** Bug
- **Severity:** P1
- **Evidence:** The backend deliberately supports partial success and returns `added`, `failed`, `duplicates`, `failures`, and `skipped`. The frontend calls raw `apiClient.post`, discards the body, then immediately invokes `onSuccess()` and `onClose()` whenever HTTP 200 is received.
- **Impact:** Quote failures, invalid prices, and duplicate rows are hidden. The user can close the preview believing every detected holding was imported, and the next portfolio refresh reveals a different state.
- **Recommendation:** Use the typed `portfolioApi.bulkAddPositions` method, inspect the envelope, show imported/skipped/failed counts and reasons, and only auto-close on `failed === 0`; otherwise keep a result panel open with a precise retry strategy.

### F-08 — Dropzone state survives close/reopen and invalid file replacement

- **Location:** `frontend/src/components/portfolio/PortfolioDropzone.tsx:44-53,124-145,155-190`
- **Category:** Bug
- **Severity:** P1
- **Evidence:** Closing only returns `null`; the component remains mounted by the manage page and no open/close effect resets `fileName`, `parsedRows`, `parseError`, `ackWeights`, or a pending `FileReader`. Selecting a non-CSV/oversize file returns before clearing a previously parsed file and rows. File-read errors also leave prior rows intact.
- **Impact:** Reopening can present stale data as the current selection, and a later invalid replacement can still leave the old batch importable under the acknowledgment checkbox. This is an accidental-write risk in a destructive/global-normalizing flow.
- **Recommendation:** Reset all file/preview/ack state on open and close, clear it before every new selection, track the active reader/request, and invalidate callbacks from superseded files.

### F-09 — Import normalization hardcodes Indian tickers and INR semantics

- **Location:** `frontend/src/components/portfolio/PortfolioDropzone.tsx:55-63,163-179,282-302`; `backend/app/api/portfolio.py:33-45,83-114,242-325`
- **Category:** Bug
- **Severity:** P1
- **Evidence:** Every unsuffixed ticker is rewritten to `.NS`; an unsuffixed US symbol such as `AAPL` becomes `AAPL.NS`. Every row is sent with `region: 'IN'`, the existing portfolio is always fetched as INR, and every preview/estimated value is rendered with `₹`, including symbols allowed through as `^...` or `=X`.
- **Impact:** The UI claims broker-generic support while silently changing instrument identity and currency. Rows can be rejected, imported into the wrong market convention, or displayed with the wrong monetary unit.
- **Recommendation:** Detect exchange from explicit CSV metadata/exchange columns and ticker suffix; do not guess `.NS` for every bare symbol. Carry per-row currency/region, query the summary in a defined base currency, and convert batch values before weight math.

### F-10 — Add-position weight math mixes converted and native monetary units

- **Location:** `frontend/src/components/portfolio/AddPositionModalSimple.tsx:40-52,61-93,170-171`; `backend/app/api/portfolio.py:242-325`
- **Category:** Bug
- **Severity:** P1
- **Evidence:** `getPortfolio({ currency })` returns a total denominated in the selected target currency. The effect then divides `quantity * buy_price`—entered in the ticker's native/effective currency—by `target total + native position value`. `effectiveCurrency` changes only the label; it does not convert the input. For a USD view with an Indian position, INR is added directly to USD; the inverse occurs for US holdings under INR.
- **Impact:** Estimated and submitted weights can be off by the FX rate and mixed units. The backend stores a non-empty position's submitted weight, so the error can persist even though later GETs recompute a live display weight.
- **Recommendation:** Use backend `position_currencies`/provenance and a single target unit, convert the new native value through the same FX service, or have the server derive added-position weights from native values. Do not perform financial aggregation in the modal across currencies.

### F-11 — Table and statistics relabel native values and replace authoritative converted weights

- **Location:** `frontend/src/components/portfolio/PortfolioTable.tsx:40-42,112-115,154-192`; `frontend/src/components/portfolio/PortfolioStats.tsx:43-79,188-212`; call site `frontend/src/app/portfolio/manage/page.tsx:477-500,564-567,686-715`; backend contract `backend/app/api/portfolio.py:266-325`
- **Category:** Bug
- **Severity:** P1
- **Evidence:** Backend comments and implementation explicitly preserve per-position native-unit `current_value`, `total_cost`, and P&L while converting only the aggregate/weight denominator. The components sum those native values and pass the selected `currency` to `formatCurrency`. `PortfolioTable` also recomputes each row's weight from native current values whenever the native total is positive, ignoring the response's target-currency live weight.
- **Impact:** The manage page can show a correctly converted summary total beside row/stat totals that are not converted, and an INR row can be labelled `$` after selecting USD. Mixed-currency relative weights are also wrong when recomputed from native amounts.
- **Recommendation:** Make the response contract unambiguous: either return all position monetary fields converted to the requested currency, or include converted display fields/provenance per row. Render authoritative `weight`; only recompute as an explicitly labelled native-unit fallback.

### F-12 — Add-position portfolio fetch has no cancellation or generation guard

- **Location:** `frontend/src/components/portfolio/AddPositionModalSimple.tsx:40-59,61-77,79-93`
- **Category:** Bug
- **Severity:** P1
- **Evidence:** Opening or changing currency starts `fetchTotalPortfolioValue`, but there is no `AbortController`, request id, mounted flag, or cleanup. The open effect resets `portfolioLoaded`; an older request can resolve afterward and repopulate `existingCount`, `totalPortfolioValue`, and `portfolioLoaded` from a prior currency/open generation.
- **Impact:** The form can calculate from stale holdings or currency, show a misleading zero-state weight, and submit a weight inconsistent with the portfolio snapshot the user saw. Backend first-position enforcement protects the committed empty-book invariant, but it does not correct every non-empty-book weight.
- **Recommendation:** Abort or generation-guard each fetch, reset loading state on close/currency change, and accept only the latest open/currency generation. Display the fetched snapshot timestamp/currency.

### F-13 — Auto-refresh cleanup can permanently latch its in-flight guard and leak a late timer

- **Location:** `frontend/src/hooks/useRealTime.ts:21-61,63-89`
- **Category:** Bug
- **Severity:** P2
- **Evidence:** `isRefreshingRef` is cleared only by the one-second settle timeout or catch. Effect cleanup clears that timeout but does not reset the ref/state. If `enabled`, `liveDataMode`, or `interval` changes during the settle window, subsequent `performRefresh` calls return immediately. If an awaited fetch completes after unmount/cleanup, it can schedule a fresh timeout after cleanup has already run.
- **Impact:** In a still-mounted hook, refresh can become permanently stuck until remount. An unmounted hook can retain a timer and perform late state/store work.
- **Recommendation:** Use an effect-lifetime cancellation token, clear refs/state in cleanup, and release the in-flight guard in a `finally` path. If a visual settle delay is desired, track and cancel it independently.

### F-14 — WebSocket freshness is stamped by acknowledgements and connection state can become sticky

- **Location:** `frontend/src/hooks/useRealTime.ts:121-155,176-199`; `frontend/src/lib/websocket.ts:216-237,373-389`; `backend/app/api/websocket.py:291-310`; `frontend/src/lib/store.ts:371-379`
- **Category:** Bug
- **Severity:** P2
- **Evidence:** The backend emits `subscription_confirmed` messages. `useRealTimeAnalytics.handleMessage` sets `lastUpdate` for every non-pong message, including those acknowledgements, so freshness can become “fresh” before any portfolio/analytics payload arrives. The enhanced hook also returns `isConnected: isConnected || realTimeData.isConnected`; the store connection setter exists but has no caller, and OR semantics cannot turn a previously true store value false.
- **Impact:** Users and freshness indicators can believe live data is current when only a subscription handshake arrived. A disconnected socket may continue to report connected if any other path ever set the store flag true.
- **Recommendation:** Stamp freshness only when a recognized data payload is applied. Treat the socket's current state as authoritative and synchronize the store on every connect/disconnect transition; do not merge booleans with logical OR.

### F-15 — WebSocket lifecycle/reconnect behavior is incomplete and would multiply sockets if status UI is mounted

- **Location:** `frontend/src/hooks/useRealTime.ts:100-104`; `frontend/src/lib/websocket.ts:98-101,154-188,261-263,279-352,367-411`; dormant call sites `frontend/src/components/ui/NotificationSystem.tsx:128-170`
- **Category:** Bug
- **Severity:** P2
- **Evidence:**
  - Every `useEnhancedRealTimeAnalytics`/`useRealTimeAnalytics` call constructs its own `WebSocketClient`; the two notification components would create separate sockets if both were mounted.
  - Topics are supplied to the client and subscribed on open, then subscribed again by the hook effect. Backend sets deduplicate membership, but duplicate wire messages remain.
  - `disconnect()` detaches handlers before close, so hook-local `isConnected`/`readyState` are not synchronously reset.
  - Reconnect uses exponential delay without jitter, stops after five attempts, and never checks the public `autoReconnect` option.
- **Impact:** Re-enabled live mode can show stale connection state; multiple consumers multiply server work; transient outages can give up permanently; retries from many clients can synchronize.
- **Recommendation:** Use one application-level socket/provider with reference-counted subscriptions. Reset state on deliberate disconnect, retain/cancel reconnect timer handles, honor `autoReconnect`, add bounded jitter, and define a terminal/retry-now state. Subscribe exactly once per topic.

### F-16 — Async submit handlers lack synchronous re-entry guards

- **Location:** `frontend/src/components/portfolio/AddPositionModalSimple.tsx:129-150,361-372`; `frontend/src/components/portfolio/EditPositionModal.tsx:74-109,326-337`; `frontend/src/components/portfolio/PortfolioDropzone.tsx:155-190,330-346`
- **Category:** Bug
- **Severity:** P2
- **Evidence:** Buttons become disabled from React state, but `handleSubmit` does not first test a synchronous ref/lock. Repeated submit events, keyboard submission, or re-entrant callbacks can enter before the disabled render is committed and issue duplicate POST/PUT/import requests.
- **Impact:** Duplicate writes, repeated expensive refreshes, conflicting error/success state, and avoidable server load. Bulk import in particular is globally weight-normalizing.
- **Recommendation:** Set a synchronous `submittingRef` before validation/async work, check it at handler entry, clear it in `finally`, and derive button state from the same submission state. Add repeated-submit regression tests.

### F-17 — Local “today” calculations use UTC and reject the current IST date early in the day

- **Location:** `frontend/src/components/portfolio/AddPositionModalSimple.tsx:23-31,63-65,118-121,294-295,331-332`; `frontend/src/components/portfolio/EditPositionModal.tsx:63-66,291-296`; `frontend/src/components/portfolio/PortfolioDropzone.tsx:17-35`; correct shared utility at `frontend/src/lib/utils.ts:74-83`
- **Category:** Bug
- **Severity:** P2
- **Evidence:** Repeated `new Date().toISOString().split('T')[0]` derives the calendar date in UTC. IST is UTC+05:30, so during the first 5.5 hours of a local day this is yesterday. The repository already documents and implements `toDateOnlyString` specifically to avoid this shift.
- **Impact:** The default purchase date can be yesterday, the date input's `max` can reject today, and otherwise valid imports/edits can be rejected or backdated unexpectedly.
- **Recommendation:** Use `toDateOnlyString(new Date())` everywhere and add a test with an IST early-morning instant.

### F-18 — API error normalization drops structured backend detail and edit errors discard useful messages

- **Location:** `frontend/src/lib/api.ts:44-80,88-112`; `backend/app/api/portfolio.py:347-359`; `frontend/src/components/portfolio/AddPositionModalSimple.tsx:141-148`; `frontend/src/components/portfolio/EditPositionModal.tsx:100-106`; `frontend/src/components/portfolio/PortfolioDropzone.tsx:181-187`
- **Category:** Bug
- **Severity:** P2
- **Evidence:** `buildApiErrorMessage` handles string and array `detail`, but backend invalid-ticker errors use an object `{ error, message, suggestions, ... }`; the frontend then falls back to `HTTP 400`. Add-position surfaces only `error.message`, so users lose the actionable message/suggestions. Edit catches an already-normalized `AppError` but replaces it with a generic sentence.
- **Impact:** Useful validation, conflict, and upstream diagnostics are hidden; users cannot correct invalid ticker input from the message and support loses root cause.
- **Recommendation:** Normalize object `detail.message`/`detail.error` into `AppError`, preserve structured `detail`, and pass its user-safe message to forms. Keep technical detail in logs/telemetry, not raw UI.

### F-19 — Form errors are not programmatically associated with inputs or announced

- **Location:** `frontend/src/components/portfolio/AddPositionModalSimple.tsx:214-233,235-281,284-343,345-350`; `frontend/src/components/portfolio/EditPositionModal.tsx:188-315`; `frontend/src/components/portfolio/PortfolioDropzone.tsx:224-272,308-316`
- **Category:** Improvement
- **Severity:** P2
- **Evidence:** Inputs have labels, but invalid fields lack `aria-invalid` and `aria-describedby`; error paragraphs lack stable IDs and live-region semantics. Submit errors are inserted without `role="alert"`. The dropzone's keyboard-operable target has no visible focus style, and its errors are not announced.
- **Impact:** Screen-reader and keyboard users may not learn why submission stopped or which field needs correction; focus remains at the submit button rather than moving to the first invalid control.
- **Recommendation:** Generate field error IDs, wire `aria-describedby`/`aria-invalid`, use `role="alert"` or a polite live region for async errors, focus the first invalid field on validation failure, and add `focus-visible` styling to the dropzone.

### F-20 — Add/edit dialogs can exceed short mobile viewports; holdings actions are undersized

- **Location:** `frontend/src/components/portfolio/AddPositionModalSimple.tsx:177-199,352-374`; `frontend/src/components/portfolio/EditPositionModal.tsx:126-188,317-339`; base dialog `frontend/src/components/ui/dialog.tsx:63-99`; dense table/actions `frontend/src/components/portfolio/PortfolioTable.tsx:118-134,194-213`; delete callsite `frontend/src/app/portfolio/manage/page.tsx:853-896`
- **Category:** Improvement
- **Severity:** P2
- **Evidence:** The shared dialog locks body scrolling but has no viewport-height cap or internal overflow. Add/edit wrap long forms without `max-h`/`overflow-y-auto`, unlike the dropzone, which explicitly uses `max-h-[90vh]` and an overflow body. The table's icon-only edit/delete controls have approximately 16px hit areas with no padding/min-size. The production delete confirmation is a hand-built modal with dialog ARIA but no focus trap, initial focus, or focus restoration.
- **Impact:** On short/mobile screens, lower form fields/actions can become unreachable while body scrolling is disabled. Dense holdings actions are difficult to tap, and keyboard focus can escape or remain behind the delete confirmation.
- **Recommendation:** Give forms a bounded height and scrollable body/footer layout; enlarge or pad row actions to at least a practical touch target; preserve a deliberate horizontal-scroll strategy with a minimum table width on mobile.

### F-21 — CSV parsing, preview rendering, and backend validation scale poorly and can silently mis-map broker files

- **Location:** `frontend/src/components/portfolio/PortfolioDropzone.tsx:66-121,124-145,218-220,274-307`; `backend/app/api/portfolio.py:495-516,537-548`
- **Category:** Optimization
- **Severity:** P2
- **Evidence:** The parser splits the whole file and each row on raw commas, so quoted commas and multiline quoted fields are not CSV-safe. Header aliases include `stock name` as a ticker and positional fallback silently assigns columns. Invalid rows are skipped without a skipped-row report. A 5 MB file can generate tens of thousands of React rows with no row cap, pagination, or virtualization. Backend bulk ticker validation awaits one vendor validation per ticker sequentially before a concurrent quote phase.
- **Impact:** Valid broker exports can be misparsed or partially imported; users cannot audit skipped records; large files freeze/mobile-scroll poorly; import latency scales poorly with ticker count.
- **Recommendation:** Use the already-installed `papaparse` (or a streaming parser), require/confirm column mapping, report every skipped row/reason, cap rows and preview only a window/page, and parallelize/batch backend validation with an explicit concurrency limit.

### F-22 — Global notification/export jobs retain timers and completed records for the session

- **Location:** `frontend/src/hooks/useRealTime.ts:212-275,330-433`
- **Category:** Bug
- **Severity:** P2
- **Evidence:** Auto-hide notification timers are not registered or cleared. Export completion timers are also untracked. Completed export jobs remain in module-global `globalExportJobs` until an explicit remove call; no active production component mounts the export progress/panel path. Listener registration itself is cleaned correctly.
- **Impact:** Long-lived sessions can accumulate completed jobs and pending timers; updates can run after consumers unmount. Repeated exports increase retained state even when no UI is observing it.
- **Recommendation:** Track timer handles, cap/expire global records, remove completed jobs after a bounded display period, and avoid module-global lifetime beyond the owning provider/session.

### F-23 — Portfolio statistics average percentages and trust every numeric field

- **Location:** `frontend/src/components/portfolio/PortfolioStats.tsx:27-76,161-176,202-213`
- **Category:** Improvement
- **Severity:** P2
- **Evidence:** Reducers add `total_cost`, `current_value`, and percentage fields without finite guards, so one bad value contaminates every aggregate. `avgGainLoss` is a simple mean of position returns, while the component computes `totalGainLossPct` from aggregate cost/value but never renders it. The UI labels the simple mean “Average Return,” which can be mistaken for portfolio return.
- **Impact:** Malformed/stale data can produce `NaN`/misleading cards, and users can see materially different performance depending on holding count rather than capital weight.
- **Recommendation:** Sanitize each numeric input, render the value-weighted portfolio return from aggregate cost/current value, and clearly label any simple mean as “mean holding return” if retained.

### F-24 — Performance history silently fails, misses holding-date invalidation, and cannot be refreshed

- **Location:** `frontend/src/hooks/useAnalytics.ts:116-156`; `frontend/src/app/dashboard/realized-risk/page.tsx:114-119`; backend holding behavior `backend/app/api/analytics.py:1406-1423`
- **Category:** Bug
- **Severity:** P2
- **Evidence:** The dependency key contains ticker and quantity but not `added_on` or `buy_price`, while backend performance history masks pre-holding dates using `added_on` and derives current value from quantity. Errors are logged and converted to an empty array; no error is returned. The hook exposes no refresh function, and realized-risk's refresh button refreshes only `usePortfolioAnalytics`, not performance history.
- **Impact:** Purchase-date edits leave rolling volatility/drawdown stale; failures look like “no history”; the visible refresh action does not refresh part of the page.
- **Recommendation:** Use a portfolio-version/query key containing all response-affecting fields, expose slice error/refresh status, and invalidate/refresh performance together with realized risk after portfolio mutations.

### F-25 — Add-position submit remains enabled while the required portfolio snapshot is loading

- **Location:** `frontend/src/components/portfolio/AddPositionModalSimple.tsx:33-38,54-59,79-93,129-139,361-372`
- **Category:** Improvement
- **Severity:** P2
- **Evidence:** There is no `isFetchingPortfolio` state. Until the request resolves, `portfolioLoaded` is false, weight remains zero, and the submit button is enabled (only submitting/fetch-error disable it). A user can fill the form quickly, submit, and receive a synthetic weight validation error instead of a loading state.
- **Impact:** Confusing validation, avoidable failed submissions, and a race perception even though the modal correctly refuses fabricated weights.
- **Recommendation:** Track fetch pending separately, disable submission while pending, show an accessible progress message, and reserve weight validation errors for actual invalid values after successful calculation.

### F-26 — Multiple portfolio UIs and hook families are dormant/duplicated

- **Location:** dormant components `frontend/src/components/portfolio/PortfolioTable.tsx:31-39`, `EditPositionModal.tsx:22-29`, `CurrencySelector.tsx:25-27`, `PortfolioFilters.tsx:21-28`; dormant hooks `frontend/src/hooks/useRealTime.ts:11-97,338-498,501-579`; active layout `frontend/src/components/layout/DashboardLayout.tsx:108-116`
- **Category:** Revamp-needed
- **Severity:** P2
- **Evidence:** Production imports exist only for `AddPositionModalSimple`, `PortfolioDropzone`, and `PortfolioStats`, plus the analytics/performance/sector and notification hooks. The four other portfolio components are test-only/unreferenced. `useAutoRefresh`, `useExportProgress`, `useDashboardPreferences`, and `useDateRangeSelection` have no production caller; connection/freshness components are also not mounted by `DashboardLayout`. The manage page duplicates table, filters, currency toggle, edit, and delete UI inline.
- **Impact:** Fixes and tests can target dead code while production remains divergent; two table/edit/currency implementations can drift; dormant WebSocket/export code adds maintenance and security surface without user value.
- **Recommendation:** Choose one canonical component/hook path. Wire and test it, or delete the dormant implementation after confirming no planned consumer. Consolidate the manage page onto maintained components before adding behavior.

### F-27 — Analytics hooks subscribe to the entire Zustand portfolio store

- **Location:** `frontend/src/hooks/useAnalytics.ts:31,119,161`; store shape/actions `frontend/src/lib/store.ts:24-60,95-242`
- **Category:** Optimization
- **Severity:** P3
- **Evidence:** `usePortfolioStore()` is called without a selector in all three analytics hooks. They only need `positions`, but re-render on changes to `isLoading`, `error`, `totalValue`, `totalWeight`, and action identity/store updates. The string dependency keys prevent duplicate effects for unrelated changes, but render work is still unnecessary.
- **Impact:** Avoidable renders and derived-array/string work during loading/error transitions, especially with multiple dashboard hooks.
- **Recommendation:** Use `usePortfolioStore(state => state.positions)` and memoize derived keys/selectors where needed.

### F-28 — Auto-calculated weight renders a duplicated percent sign

- **Location:** `frontend/src/components/portfolio/AddPositionModalSimple.tsx:284-300`
- **Category:** Bug
- **Severity:** P2
- **Evidence:** The read-only input value itself includes `%` (`100.00%`), while an absolutely positioned suffix always renders another `%` for every non-empty calculated value.
- **Impact:** The primary add-position feedback displays `100.00%%`, undermining confidence in a financial invariant and making the zero-state result visually incorrect.
- **Recommendation:** Render a numeric fraction in the input and keep the single suffix, or remove the suffix and keep the percent in the value. Add a text assertion for the zero-state display.

### F-29 — Small form, table, and locale polish gaps remain

- **Location:** `frontend/src/components/portfolio/AddPositionModalSimple.tsx:153-168,242-280,311-320`; `frontend/src/components/portfolio/EditPositionModal.tsx:82-101,140-146,273-280,318-337`; `frontend/src/components/portfolio/PortfolioTable.tsx:152,168-186,121-134,195-211`; `frontend/src/components/portfolio/CurrencySelector.tsx:27-48`; `frontend/src/components/portfolio/PortfolioFilters.tsx:43-83`
- **Category:** Improvement
- **Severity:** P3
- **Evidence:** Numeric `parseFloat(...) || 0` inputs make intermediate decimal entry awkward; custom-name inputs do not mirror the backend 100-character limit; an unchanged edit still PUTs an empty object and an existing date cannot be cleared; header/cancel/close/filter buttons generally omit explicit `type="button"`; table P&L direction treats non-finite loss as a loss and quantity uses environment-default locale; table headers lack `scope`; mobile currency buttons expose only `₹`/`$` as their responsive accessible name.
- **Impact:** Minor usability, screen-reader, and maintenance friction rather than primary data loss in current production paths.
- **Recommendation:** Apply a small form/table accessibility pass: string-backed numeric drafts, `maxLength`, no-op submission guard, explicit nullable-date semantics, `type="button"`, finite checks, `scope="col"`, `en-IN` where appropriate, and explicit mobile `aria-label` values.

## Coverage

### First-party files read in full

| File | Lines | Production reachability |
|---|---:|---|
| `frontend/src/components/portfolio/PortfolioTable.tsx` | 222 | No production or test import found |
| `frontend/src/components/portfolio/EditPositionModal.tsx` | 345 | No production caller; component tests only |
| `frontend/src/components/portfolio/AddPositionModalSimple.tsx` | 380 | Active: dashboard and portfolio manage |
| `frontend/src/components/portfolio/CurrencySelector.tsx` | 55 | No production caller |
| `frontend/src/components/portfolio/PortfolioStats.tsx` | 219 | Active: portfolio manage |
| `frontend/src/components/portfolio/PortfolioFilters.tsx` | 122 | No production caller |
| `frontend/src/components/portfolio/PortfolioDropzone.tsx` | 351 | Active: portfolio manage |
| `frontend/src/hooks/useRealTime.ts` | 579 | Notifications active; most other exports dormant |
| `frontend/src/hooks/useAnalytics.ts` | 193 | Active: dashboard and realized-risk |
| **Total** | **2,466** | **9/9 files fully read** |

### Imports and call sites inspected

- Production call sites: `frontend/src/app/portfolio/manage/page.tsx`, `frontend/src/app/dashboard/page.tsx`, `frontend/src/app/dashboard/realized-risk/page.tsx`; root bootstrap: `frontend/src/app/layout.tsx`.
- Supporting consumers: `frontend/src/components/ui/NotificationSystem.tsx`, `ExportPanel.tsx`, `frontend/src/components/layout/Header.tsx`, `DashboardLayout.tsx`, `frontend/src/components/charts/PerformanceChart.tsx`, `SectorAllocationChart.tsx`.
- Shared boundaries: `frontend/src/lib/api.ts`, `store.ts`, `websocket.ts`, `utils.ts`, `frontend/src/components/ui/dialog.tsx`, `frontend/src/types/index.ts`, `frontend/package.json`, `frontend/tsconfig.json`.
- Relevant backend contracts: `backend/app/api/portfolio.py`, `analytics.py`, `websocket.py`, and `backend/app/models/schemas.py`.
- Existing focused tests inspected: `AddPositionModalSimple.test.tsx`, `AddPositionZeroState.test.tsx`, `EditPositionModal.test.tsx`, `PortfolioDropzone.test.tsx`. They cover basic open/close, basic validation, zero-state weight, fetch-failure blocking, and happy-path bulk weights, but not the P1 failure modes above.

### Audit dimensions checked

- Forms: validation, finite/range/date checks, duplicate submission, async close behavior, structured errors.
- Destructive flow: CSV global normalization acknowledgment and current delete confirmation.
- Zero-state weights: frontend and backend enforcement.
- Failed fetch/partial response handling.
- INR/USD/native-unit formatting and ticker market conventions.
- TanStack row access and current table implementations.
- API error normalization.
- React Query/cache/staleTime/invalidation presence or absence.
- Zustand selectors, derived state, persistence, and reset behavior.
- WebSocket reconnect, backoff, heartbeat, subscriptions, and cleanup.
- Stale data, memoization, request races, and fixed/N+1 request behavior.
- Accessibility and mobile density.

## Healthy checks

1. **First-position zero-state invariant is correctly guarded.** `AddPositionModalSimple.tsx:79-93` waits for a successful portfolio fetch and sets `1.0` when no positions exist; the test asserts `100.00%`. `portfolio.py:390-393` independently commits `1.0` for the first/zero-value book, so the durable backend invariant is protected even if a client races.
2. **NSE/BSE ticker formats are supported consistently.** `AddPositionModalSimple.tsx:99-103` allows alphanumeric codes, numbers, hyphens, ampersands, dots, and suffixes; `portfolio.py:33-36` mirrors the same format.
3. **Add-position portfolio-fetch failure is fail-closed.** `AddPositionModalSimple.tsx:40-51,133-135,200-211,363-364` shows retry, disables submit, and does not fabricate a weight after failure.
4. **CSV normalization is explicitly acknowledged before the globally weight-changing import.** `PortfolioDropzone.tsx:308-316,330-333` requires a checkbox and disables import until acknowledged.
5. **Current production deletion has a confirmation step and pending disable.** `frontend/src/app/portfolio/manage/page.tsx:853-896` requires explicit confirmation and disables the destructive button while deletion is pending. Its custom dialog still needs the focus-management improvement recorded in F-20.
6. **TanStack invariant is respected at inspected production analytics tables.** Dashboard renderers use `const data = row.original || row;` at `frontend/src/app/dashboard/page.tsx:165,176,195,207,219`; realized-risk does the same at `frontend/src/app/dashboard/realized-risk/page.tsx:144,166,178,194,207,229,241`. The audited portfolio components do not use TanStack rows.
7. **INR base formatting is correct when a value truly is INR.** `frontend/src/lib/utils.ts:23-45` uses `Intl.NumberFormat('en-IN')` with the INR currency style, and `formatIndianRupees` uses Cr/L notation.
8. **Basic request/listener cleanup exists.** Auto-refresh clears interval/timer handles in its normal cleanup path; WebSocket heartbeat timers, subscriptions, disconnect, notification listeners, and export listeners have explicit cleanup. The findings above concern exceptional ordering/stuck-state cases, not total absence of cleanup.
9. **No client-side per-row portfolio N+1 was found.** The add modal uses one summary fetch, importer uses one summary plus one bulk POST, and analytics use a fixed parallel batch. The concerns are the excessive fixed seven-call fanout, missing cache, and backend bulk validation's sequential per-ticker phase.
10. **Several baseline accessibility/mobile foundations are present.** Both forms have labels and native controls; Radix provides dialog semantics; sortable table headers use buttons and `aria-sort`; the CSV target supports Enter/Space; add form grids collapse on mobile; stats/filter layouts are responsive; the dropzone itself has bounded height and a scrollable body.

## Priority recommendation order

1. Fix post-commit bulk response safety and consume partial-result envelopes.
2. Define and implement one explicit currency contract across API DTOs, add-position math, rows, and aggregate cards.
3. Replace local analytics state with canonical portfolio/analytics queries; add route bootstrap and per-slice failure/stale state.
4. Reset/abort add and import async state; add synchronous submit locks.
5. Consolidate dormant portfolio components/hooks and then complete form/table/mobile accessibility polish.
