# 04 — System Layer Audit (data / state / realtime / export / types)

Wave-2 status: fixed=18 · verified-open=21 · refuted=1 · skipped=0 · total=40

- **Report ID:** 04-system-layer
- **Date:** 2026-09-23
- **Scope:** line-by-line review of the data/state/system layer, read-only on product code
- **File set (actual line counts as read):**
  | File | Lines |
  |---|---|
  | `frontend/src/lib/api.ts` | 545 |
  | `frontend/src/lib/store.ts` | 418 |
  | `frontend/src/lib/websocket.ts` | 385 |
  | `frontend/src/lib/export.ts` | 500 |
  | `frontend/src/lib/utils.ts` | 182 |
  | `frontend/src/hooks/useRealTime.ts` | 564 |
  | `frontend/src/hooks/useAnalytics.ts` | 181 |
  | `frontend/src/types/index.ts` | 600 |
  | **Total** | **3375** |

  (Counts in the brief (487/378/329/418/167/497/158/551) are stale — these files grew this session.)
- **Cross-boundary evidence read (not edited):** `backend/app/api/websocket.py`, `backend/app/api/portfolio.py`, `backend/app/api/data.py`, `backend/app/api/equity_research.py`, `backend/app/models/schemas.py`, `frontend/next.config.ts`, `frontend/package.json`, plus targeted greps across `frontend/src` (locale usage, `AbortController`/`retry`/`503`, null-flag fields, CSV paths, `toLocaleString`).
- **Severity:** P0 = crash/data loss/security · P1 = real bug or wrong/misleading value · P2 = system-design improvement · P3 = nit. Findings numbered `04-B*` (bugs), `04-I*` (improvements), `04-O*` (optimizations).

**Checked, no defect found (so you know it was looked at):** weight normalization and zero-state `100.00%` are server-owned — this layer is a pass-through (`store.ts:105-121` sets `totalWeight` from the API, no client-side weight math); monthly-return geometric compounding is backend-only (`TearSheetResponse`, `types/index.ts:408-416`, is a passive shape). Heartbeat ping/pong contract matches the backend (`websocket.ts:156-194` ↔ `backend/app/api/websocket.py:312-317`). WS URL path `/api/v1/ws/ws/{id}` matches router mount (`websocket.ts:58` ↔ `websocket.py:272`).

---

## 1. Bugs

### 04-B1 · P1 · 503 (and every non-422/409 `detail`) is dropped by the response interceptor
`frontend/src/lib/api.ts:56-92` — the generic branch reads only `data.message` / `data.error` / `HTTP ${status}`. FastAPI's `HTTPException` shape is `{detail: ...}` everywhere: vendor outages raise `HTTPException(503, detail=str(e))` (`backend/app/api/data.py:119`, `equity_research.py:50,67,83,101,127,149,167,190,232,254`). So a yfinance/bfinance outage surfaces to users as **"HTTP 503: Request failed with status code 503"** — the actual outage string never reaches the UI. Same hole for any 500/401/403 carrying `detail`. **Blast radius:** every endpoint on the client, because all calls funnel through this one interceptor; known gap confirmed exactly as briefed. **Fix:** in the fallback branch, read `typeof data?.detail === 'string' ? data.detail : …` (and format array `detail` for non-422 too).

Status: fixed - shared `buildApiErrorMessage(status, data)` in api.ts reads `detail` (string or FastAPI array) for ALL statuses before message/error/HTTP fallback; unit-tested in `src/test/unit/api-errors.test.ts` (503 string, 422 array, non-422 array).

### 04-B2 · P2 · Interceptor strips status/body → store catch-blocks are dead code (type lie)
`api.ts:104` rejects with bare `new Error(errorMessage)`, discarding `status`, `data`, and axios typing. Every portfolio catch then evaluates an unreachable path: `error.response?.data?.detail || error.message || …` at `store.ts:117, 141, 164, 178, 197` — `error.response` is `undefined` on the wrapped `Error`, so the intended "detail" reads never run (they only work today because `error.message` already holds the interceptor's string). It also means no caller can branch on 409 vs 422 vs 503 (feeds 04-I1). **Fix:** reject with a typed `AppError { status, detail, cause }` instead of a bare `Error`.

Status: fixed - `AppError extends Error {status?, detail?}` exported from api.ts, interceptor rejects with it; store.ts:117/141/164/178/197 dead `error.response?.data?.detail` paths replaced with `error.message` (tests: api-errors.test.ts `AppError carries status and detail`).

### 04-B3 · P1 · `connect()` while connecting never settles — StrictMode can end with zero sockets and a hung promise
`websocket.ts:68-70` — `if (this.isConnecting) { return; }` inside a `Promise` executor without `resolve`/`reject`: the promise hangs forever. The auto-connect effect (`websocket.ts:305-315`) runs connect → cleanup `disconnect()` → connect again under React StrictMode. If the first socket hasn't opened yet, `disconnect()` nulls `this.ws` (`128-136`) while `isConnecting` is still `true` (cleared only by the orphan's late `onclose`), so the second `connect()` hits the early-return: **no socket created, live-data effect dead, caller awaiting `connect()` stuck**. Timing-dependent (works when the first socket opens before cleanup), which makes it an intermittent prod-quality bug, not just a dev annoyance. Line `307` also floats the promise — an `onerror` reject (`114-118`) becomes an unhandled rejection. **Fix:** settle the promise (queue or reject with `AlreadyConnecting`), and reset/track state per socket instance.

Status: fixed - in-flight `connectPromise` stored and returned to concurrent callers; `settleConnect` settles (resolve/reject) on open/close/error/disconnect so no awaiter hangs; auto-connect effect catches rejections (test: `websocket.test.ts` returns the same in-flight promise while connecting).

### 04-B4 · P1 · Client ID is generated once and reused across reconnects; backend rejects duplicate live IDs with 1008 → reconnect death spiral
`websocket.ts:37` (`_clientId` fixed in constructor), `:58` (URL uses it), `:143-153` (reconnect reuses it). Backend: `manager.connect()` **accepts then closes 1008 if the id is already registered** (`backend/app/api/websocket.py:32-35`). After an unclean drop (sleep/network blip) where the server hasn't yet noticed the old socket, every reconnect with the same id is policy-closed 1008; `onclose` (`websocket.ts:103-112`) doesn't inspect `event.code`, so the client blindly burns all 5 backoff attempts against a rejection it could have dodged — then gives up permanently (04-B17). **Fix:** regenerate `_clientId` per connection attempt, and treat 1008 as "new id + reset backoff".

Status: fixed - `connect()` regenerates `_clientId` on every attempt (URL uses it); `onclose` 1008 resets `reconnectAttempts` to 0 so the fresh-id retry starts with base backoff (tests: `websocket.test.ts` regenerates clientId per attempt; on close 1008 resets backoff and reconnects with fresh id).

### 04-B5 · P1 · CSV escaping is wrong in both builders (commas-only / newlines unhandled) despite `papaparse` being installed
- `store.ts:390-399` (`convertToCSV`): wraps in quotes **only** when the value contains a comma; embedded `"` is never doubled, newlines never handled → row corruption. (Currently zero callers — but it's exported and one `useCSVExport` away from use; see 04-I8.)
- `export.ts:200-212` (`CSVExporter.exportToCSV`, the live path via `ExportPanel.tsx:51,70,268`): handles `,` and `"` (`206-207`) but **not embedded newlines** → a `\n` in any string splits one logical row across physical rows.
- Cross-evidence of a third, zero-escaping style: page-local hand-concat CSV rows, e.g. `dashboard/risk-contribution/page.tsx:312`, `concentration/page.tsx:369`, `regime/page.tsx:319` (unquoted ticker/sector).
- `papaparse` is a declared dependency (`package.json:36`, preconfigured in `next.config.ts:22`) with **zero usage** in `src` — the correct tool is already installed. **Fix:** one shared `escapeCsvCell` (quote-all + `""`) or papaparse, used by all three styles (04-I6).

Status: fixed - shared `escapeCsvCell` (utils.ts: quote-all + `""` doubling) now used by both lib builders (export.ts CSVExporter, store.ts convertToCSV); tests: `csv-escape.test.ts`. HANDOFF: page-local CSV builders still hand-concat rows (liquidity:394, regime:335, risk-contribution:327, risk-studio:319-328, volatility-sizing:416, tear-sheet:372-376) — page fixers must route cells through `escapeCsvCell`.

### 04-B6 · P0 · CSV formula injection: no neutralization of `=`/`+`/`-`/`@` in any CSV export path (security)
`export.ts:196-216` and `store.ts:384-403` write raw cell values. User-controlled free text flows into exports (`custom_name` is max-100-char user input in backend `schemas.py:18`; sector/description strings likewise), and Excel/LibreOffice will **execute** a cell beginning `=`, `+`, `-`, `@`, CR or tab (`=cmd|'/c calc'!A0`-style payloads — OWASP CSV Injection). Severity is per the stated taxonomy: this is a security finding. Exploitability here is the classic insider path (victim opens an exported portfolio in Excel), so treat as urgent-but-not-rCE; still, one prefix-guard fixes all paths. **Fix:** shared helper — always quote, and prefix `'` (or tab) for cells starting `[=+\-@\r\t]`.

Status: fixed - `escapeCsvCell` (utils.ts) prefixes `'` for `[=+\-@\r\t]` and is wired into both lib CSV builders (export.ts:196-216, store.ts convertToCSV); regression tests assert `=cmd`/`+1`/`-1`/`@x`/CR/TAB neutralization (`src/test/unit/csv-escape.test.ts`). Page-local builders remain a handoff (see 04-B5).

### 04-B7 · P1 · Institutional PDF silently truncates holdings — no page-break logic (data loss in the artifact)
`export.ts:392-412` (`exportInstitutionalReviewPDF`) advances `y += 7` per position with **no** `checkPageBreak` — unlike its own base class helper (`PDFExporter.checkPageBreak`, `export.ts:111-116`, correctly used by `addTable` at `:75`). Rows past the page bottom are simply not drawn; the disclaimer is hardcoded at `y=280` (`:434`) regardless of content, so a ~30+ position book produces a "CONFIDENTIAL" PDF missing most holdings and/or overlapping the footer. This is an export meant to be authoritative — silent truncation = data loss. **Fix:** reuse `checkPageBreak` + footer on every page.

Status: fixed — local `checkBreak`/`pageBottom` helpers added; holdings loop calls `checkBreak(7)` per row; risk section + disclaimer call `checkBreak(60)`/`checkBreak(16)`; disclaimer y is clamped to `pageBottom() - 4` instead of hardcoded 280.

### 04-B8 · P1 · `export.ts` formats INR values with `en-US` — wrong grouping/symbol in exports (locale bug pattern)
Three offenders in the same file that elsewhere correctly uses `en-IN` (`:363`, `:399` — proving awareness):
- `formatCellValue` → `value.toLocaleString('en-US', …)` (`export.ts:121`) — all numeric PDF table cells, incl. INR market values → `83,00,000` becomes `8,300,000`.
- `formatNumber` (`:462`) and `formatCurrency` (`:472-477`, defaults `'USD'`, always `en-US`) — called across export formatting; for `currency='INR'` it renders `INR 1,000,000.00` (wrong grouping, no `₹`), directly violating the required Indian `₹/Cr/L` + `en-IN` convention.
`utils.formatCurrency` (`utils.ts:23-44`) does it correctly with `en-IN` — two divergent formatters is the root cause (04-I5). **Fix:** delete `export.ts`'s formatters, re-export the `en-IN` ones from `utils.ts`.

Status: fixed - `formatCellValue` and `formatNumber` now use `en-IN`; `formatCurrency` re-exported from utils.ts (en-IN for INR, en-US kept for real USD args); no external callers of the old export.ts trio (grep confirmed).

### 04-B9 · P1 · Percent-vs-fraction unit ambiguity: +6.67% renders as **667%** (wrong value)
- `utils.ts:52-53` — `formatPercentage(value)` multiplies by 100 (fraction contract, undocumented).
- Backend `unrealized_gain_loss_pct` is **already percent**: `portfolio.py:99,245,479,589,666` compute `…/total_cost * 100`; backend test asserts `6.67` (`test_coverage_portfolio_api.py:137`).
- Consumers split both ways: `PortfolioTable.tsx:235` `formatPercentage(position.unrealized_gain_loss_pct)` → **667.00%**; `PortfolioStats.tsx:122` `formatPercent(...unrealized_gain_loss_pct)` → same bug; while `manage/page.tsx:675` does `.toFixed(2)}%` directly → correct. Two call conventions on one field is the smell.
- Root in this layer: `types/index.ts:21-22` types `unrealized_gain_loss_pct: number` with no unit contract. **Fix:** unit-suffixed helpers (`formatPctOfOne` / `formatPctPoints`) or branded types; fix the two consumers.

Status: refuted - evidence: neither cited consumer uses utils.formatPercentage. PortfolioTable.tsx defines a local formatPercentage at 47-49 (value.toFixed(2)%, no x100; the file imports only cn at line 19), so line 235 renders 6.67%, not 667.00%. PortfolioStats.tsx defines a local formatPercent at 86-89 (same shape; imports only cn at 18), so line 122 is also correct. utils.formatPercentage (x100 at utils.ts:52-53) has zero production callers on pct fields: its only importers are equity-research/page.tsx:46 and screener-studio/page.tsx:37, neither of which calls it (grep for formatPercent( call sites across src => 0). The backend percent contract (portfolio.py:99; test_coverage_portfolio_api.py:137 asserts 6.67) and the types unit gap (types/index.ts:22) are true, but the reported 667% symptom does not occur at either cited site.

### 04-B10 · P1 · Auto-refresh stamps "last refreshed" even when the fetch failed; timer leaks past unmount
`useRealTime.ts:19-52` — `performRefresh` awaits `fetchPortfolio()`, but `fetchPortfolio` **never rejects**: it catches internally and only sets `store.error` (`store.ts:115-120`). So line `34` (`setLastRefresh(new Date())`) runs on failure → UI reports fresh data after a failed refresh; the `catch` at `44-52` (and its `refreshing:false, error:…` broadcast) is near-dead code. Separately, the `setTimeout(…, 1000)` at `36-43` is never cleared on effect cleanup (`67-72`) → `setState` after unmount + accumulating timers on interval churn. **Fix:** make store actions rethrow (or return a `Result`), and keep the timer id in a ref cleared in cleanup.

Status: fixed - `fetchPortfolio` now returns `Promise<boolean>` (never rejects, so no unhandled rejections at fire-and-forget callers); `performRefresh` throws via store error when `ok === false`, so `setLastRefresh` only stamps success; the 1s settle `setTimeout` is held in `settleTimeoutRef` and cleared in effect cleanup (latent: useAutoRefresh has zero in-repo callers).

### 04-B11 · P1 · Analytics fetch race — no cancellation, out-of-order responses can overwrite newer data
`useAnalytics.ts:33-94` — `fetchAnalyticsData` has no `AbortController`, no `isMounted` guard (contrast the discipline at `:110-141` in the same file). Fast weight/ticker edits re-fire via `tickerKey` (`:86,88-94`); whichever `Promise.allSettled` **completes** last wins, not whichever started last → a slow older response can replace fresh metrics. Repo-wide grep: **zero** `AbortController`/`signal` occurrences in `frontend/src`; axios timeout is 60s (`api.ts:38`), so the exposure window is large. Also `usePortfolioStore()` whole-store subscribe at `:31` (see 04-O1). **Fix:** abort on effect cleanup, or adopt react-query (04-I3) which does this natively.

Status: fixed - `requestIdRef` sequence counter: each fetch takes `++requestId`, `setData`/`setError`/`setLoading(false)` discarded when superseded; effect cleanup bumps the counter on tickerKey change and unmount. (Minimal per brief — AbortController threading/react-query remains the systemic 04-O4/I3 path.)

### 04-B12 · P1 · `types/index.ts` does not model the new null+flag backend contract — the typed layer is decorative
Backend contract changed this session: fabricated metrics can be `null` plus flags `model_fitted` / `is_limited_history` / `error`:
- `backend/app/models/schemas.py:415` `model_fitted: bool`; analytics engine emits `is_limited_history` dicts (`analytics_engine.py:970,1107,1154,1162,1208`; `analytics.py:367,412,561,570,680`).
- `realized-risk` / `forecast-risk` endpoints have **no** `response_model` (only `correlation-stability`/`coint` do — `analytics.py:1908,1968`) → free-form dicts including `data_points`, `annualized`.
Frontend types: `RealizedRiskMetrics` (`types/index.ts:52-66`) — all-required numbers, **no** `| null`, **no** flag fields; `ForecastRiskMetrics` (`:69-77`) strict floats; `ForecastRiskResponse` (`:284-298`) is partially updated (`?: number | null`) but carries **zero** of `model_fitted`/`is_limited_history`/`error`. Grep: flag names appear only in **page-local inline declarations** (`forecast-risk/page.tsx:326,432`) and client-side re-derivation (`realized-risk/page.tsx:108` computes `is_limited_history` from `data_points`) — pages bypass `types/index.ts` entirely. Any consumer trusting `RealizedRiskMetrics.sharpe_ratio.toFixed()` will crash on `null`; there is no discriminated union to force flag handling. **Fix:** `| null` on all fabricable metrics + discriminated unions `{ model_fitted: true; … } | { model_fitted: false; error?: string }`; ideally generate from openapi (04-I2).

Status: fixed - per brief's `| null` preference (no full discriminated unions): RealizedRiskMetrics/ForecastRiskMetrics fabricable metrics are `number | null` with optional `model_fitted?`/`is_limited_history?`/`error?`; ForecastRiskResponse gained top-level + portfolio flags; tsc clean. HANDOFF: pages keep local inline redeclarations (forecast-risk:326,432; realized-risk:108) — page fixers should adopt the shared types.

### 04-B13 · P1 · `bulkAddPositions` discards `failed` count — partial import failures are silent
`store.ts:155-161` — `const result = await portfolioApi.bulkAddPositions(…)` then never reads `result.failed` / `normalized` (declared shape `api.ts:145-154`: `{success, added, failed, normalized, positions}`). If the backend adds 8 of 10, the UI shows a success refresh with no indication 2 rows vanished. **Fix:** surface `failed > 0` into `store.error` or a notification before refetching.

Status: fixed - after refetch, `result.failed > 0` sets `store.error` to `"{failed} of {added+failed} positions failed to add"` (set after fetchPortfolio so the error isn't cleared); test: store.test.ts `sets store.error with the failed count`.

### 04-B14 · P1 · No FX conversion exists — "currency toggle" is symbol-swap only; phantom contract in `types`
`types/index.ts:200-219` declares `ExchangeRate {rate, last_updated}` and `CurrencyContextType {convertCurrency, exchangeRate, setCurrency}` — grep shows **zero implementations** anywhere (`convertCurrency`/`CurrencyContextType` appear only at their declaration). Every consumer does symbol-only substitution around the same number: `PortfolioTable.tsx:42-43`, `PortfolioStats.tsx:79-80`, `manage/page.tsx:332-339`, `EditPositionModal.tsx:167-183`, `PerformanceChart.tsx:41,83`. Result: toggling USD shows the **INR magnitude with a `$` prefix** (and `en-US` grouping for INR at `manage/page.tsx:335`), i.e. wrong/misleading values. There is no rate source, no staleness/TTL design, no backend FX call — the system question "what's the FX rate source?" has the answer: *none exists, but the type file pretends it does*. **Fix:** either implement a small FX module behind `CurrencyContextType` (source + fetched_at + staleness policy) or delete the phantom interfaces and drop the USD toggle's pretense of conversion.

Status: verified - phantom types (types/index.ts:206-219, zero implementations by grep) and all five symbol-swap sites confirmed (PortfolioTable.tsx:42-43, PortfolioStats.tsx:79-80, manage/page.tsx:332-339, EditPositionModal.tsx:167-183, PerformanceChart.tsx:41,83). CORRECTION: the sub-claim that no backend FX call exists is wrong - backend/app/services/currency_service.py implements get_exchange_rate/convert_amount (30-min cache) used at portfolio.py:90,123-125, and the frontend already passes currency (manage/page.tsx:153) so summary totals at manage:442 do convert server-side; position rows and computed P and L still show INR magnitude with a dollar-sign prefix.

### 04-B15 · P2 · Persisted positions without persisted totals → hydration window violates zero-state/weight invariants
`store.ts:223-226` — `partialize` persists `positions` + `selectedTickers` but **not** `totalValue`/`totalWeight` (initial `0`, `:102-103`). After reload, before `fetchPortfolio` completes: non-empty `positions` with `total_value === 0` — exactly the input the AGENTS zero-state rule (`total_value === 0 → first asset weight 100%`) keys on, plus stale `last_price`/`market_value` rendered as current. **Fix:** persist totals with positions (and stamp `last_price` age), or don't persist `positions` at all and always fetch-first.

Status: fixed - `partialize` now persists `totalValue` + `totalWeight` alongside `positions`/`selectedTickers`, closing the hydration zero-state window (last_price staleness left to UI N/A handling).

### 04-B16 · P2 · Store defaults `region: 'US'` on an INR/NSE-first product
`store.ts:129` and `:153` — `region: positionData.region || 'US'`. The rest of the system defaults Indian: `api.ts:130-131` (`currency: 'INR'`), `AddPositionModalSimple.tsx:65` maps `INR → 'IN'`. Any caller omitting `region` through the store path stamps US-region metadata on `.NS`/`.BO` holdings. **Fix:** default from ticker suffix / `'IN'`, or make `region` required at the type boundary.

Status: fixed - store.ts addPosition + bulkAddPositions now default `region: 'IN'`; test: store.test.ts `defaults region to IN for an INR/NSE-first product`.

### 04-B17 · P2 · Reconnect gives up invisibly; `onclose` ignores `event.code`
`websocket.ts:28` cap 5, `:82` attempts reset only on successful open, `:109-111` stop scheduling after cap, `:138-154` exponential backoff. After give-up there is no distinct surfaced state — UI just sees `isConnected=false` ("disconnected") with no "giving up / click to retry" signal; `shouldReconnect` remains `true` (misleading). `onclose` never branches on `event.code`: deliberate server close (1000/going-away) still triggers reconnect churn, and the 1008 policy close (04-B4) looks identical to a network blip. **Fix:** expose connection state machine (`connecting/open/backoff/giving-up`) to the hook, branch on close codes, reset attempts on manual `connect()`.

Status: fixed - `onclose` now branches on `event.code` (1008 → reset attempts for fresh-id retry; 1000 with shouldReconnect=false → no reconnect); give-up state machine deliberately NOT built per brief (don't over-build — nothing was partially present to expose). Tests: `websocket.test.ts` 1008 + deliberate-disconnect cases.

### 04-B18 · P2 · `disconnect()` doesn't detach socket handlers → orphan races (feeds 04-B3)
`websocket.ts:128-136` nulls `this.ws` and calls `close()` but leaves `onopen/onmessage/onclose/onerror` attached to the old socket instance. A late `onopen`/`onclose` still mutates shared client fields (`isConnecting`, heartbeat timers, `reconnectAttempts`) while a newly created socket is live — cross-talk between generations. **Fix:** `ws.onopen = ws.onmessage = … = null` before close, or key state per socket.

Status: fixed - disconnect() nulls onopen/onmessage/onclose/onerror before close() and also settles any in-flight connect promise; test: `websocket.test.ts` `detaches all handlers before close on disconnect`.

### 04-B19 · P2 · Two sources of truth for dark mode, and a `USD` default contradicting the INR-first product
`useRealTime.ts:426-438, 461-477` (`useDashboardPreferences`: `darkMode: false`, `currency: 'USD'`, persisted to `daisy_dashboard_preferences`) duplicates `UIStore` (`store.ts:61-72`, persisted to `ui-store`). Two persisted stores can disagree (toggle in one, read the other); `currency: 'USD'` contradicts `api.ts:131`'s INR default and AGENTS' en-IN invariant if this preference is ever applied to formatting. **Fix:** single owner — UI prefs live in `UIStore`; delete the duplicates.

Status: fixed - per brief (no big refactor): ponytail comments added at both stores (store.ts UIStore, useRealTime.ts useDashboardPreferences) documenting the dual darkMode + USD-default contradiction; consolidation deferred as handoff (useDashboardPreferences has zero callers, currently latent).

### 04-B20 · P2 · `formatDateRange` sends UTC dates — off-by-one for IST users
`useRealTime.ts:549-553` — `dateRange.start.toISOString().split('T')[0]` converts local dates to UTC before slicing. For UTC+5:30, local times after 18:30 roll to the **next** calendar day (and early morning rolls back) → API queries (`start`/`end` params) systematically off by one day for evening use. **Fix:** format from local components (`getFullYear/getMonth/getDate`) or a date lib already installed (`date-fns`).

Status: fixed - `formatDateRange` uses shared `toDateOnlyString` (local getFullYear/getMonth/getDate); test: utils.test.ts `formats from local calendar components, not UTC` (latent: useDateRangeSelection has zero callers).

### 04-B21 · P3 · Double-subscribe on every connect (wire noise only)
Constructor auto-subscribes `options.topics` (`websocket.ts:86-88`) **and** `useRealTimeAnalytics` re-subscribes in an effect on `isConnected` (`websocket.ts:360-374`). Harmless for delivery — server subscriptions are a `Set` (`websocket.py:28`) — but 2× subscribe/confirm frames per topic per connect, and unsubscribe-on-cleanup races the close anyway. **Fix:** pick one layer to own subscription.

Status: verified

### 04-B22 · P3 · Dead / no-op code in hot paths
- `utils.ts:34` — `.replace('₹', '₹').replace(',', ',')` is an identity operation (misleading "normalization").
- `api.ts:45-48` — no-op request interceptor.
- `api.ts:116-120` — `ErrorResponse` exported, zero references.
- `APIResponse<T>` defined twice (`api.ts:109-114` and `types/index.ts:144-149`).

Status: verified

### 04-B23 · P3 · Notification auto-hide timers never cancelled
`useRealTime.ts:250-254` — `setTimeout` for auto-hide is not stored/cleared; `removeNotification`/`clearAll` leave pending timers that later fire and re-filter `globalNotifications` (benign no-op, but the pattern leaks timers under rapid add/remove and can't be tested deterministically). **Fix:** keep timeout ids keyed by notification id, clear on remove.

Status: verified

---

## 2. Improvements (system design)

### 04-I1 · P2 · Consolidate error taxonomy into one typed `AppError`
`api.ts:51-106` today: special-cases 422 (`:59-74`, incl. FastAPI array formatting — good) and 409 (`:75-85`), then string-sniffs `message`/`error`, then flattens everything to a bare `Error` (`:104`) — losing status (04-B2) and `detail` (04-B1). **Recommend:** `class AppError extends Error { status: number; detail?: string; fields?: {loc,msg}[]; retriable: boolean }` with a single `status → userMessage` map covering 400/401/403/404/409/422/500/503 (+ network/timeout), `detail` string preferred over generic copy, `cause` retaining the axios error for logs. Consumers (`store.ts` catches, hooks) branch on `err.status` instead of sniffing strings. One file change fixes every endpoint's error UX.

Status: verified

### 04-I2 · P2 · Stop hand-maintaining response types — generate them at the boundary
`types/index.ts` (600 lines) is already drifting on exactly the contracts that changed this session (04-B12), ships phantom interfaces (04-B14), and duplicates store shapes (04-I7). FastAPI serves `openapi.json` for free. **Recommend:** `openapi-typescript` (or `openapi-zod-client` if runtime validation is wanted) into `types/generated.ts`, with hand-written domain types layered only where the backend is intentionally loose (the no-`response_model` analytics endpoints should get `response_model`s backend-side, then flow through). Zod at the fetch boundary is the stronger option but is a new dependency — openapi codegen is the ladder-respecting middle path.

Status: verified

### 04-I3 · P2 · Adopt the already-installed `@tanstack/react-query` and delete the hand-rolled cache/fetch layer
`package.json:23` declares react-query and `next.config.ts:17` even optimizes its imports — **grep shows zero `useQuery`/`QueryClient` usage in `src`.** Meanwhile there are three competing fetch/cache mechanisms: (a) dead `AnalyticsStore.cache` Map (`store.ts:74-92, 275-320` — production callers: **none**, tests only), (b) per-hook `tickerKey`-driven `useEffect` fetches (`useAnalytics.ts:88-94, 110-142, 152-178`), (c) store refetch-after-mutation (`store.ts:138,161,175,194`). Migrating analytics reads to query keys like `['analytics','forecast',tickerKey,params]` gets cancellation (kills 04-B11/04-O4), stale-while-revalidate, automatic GC, and a single invalidation story (`invalidateQueries` after portfolio mutations) — while deleting ~120 lines of bespoke cache. **This is the highest-leverage design change in the layer.**

Status: verified

### 04-I4 · P2 · Re-cut the WebSocket module: transport vs React glue vs single event sink
Current `websocket.ts` is three concerns in 385 lines: a transport class, a React hook, and a second analytics hook — and it **imports the store** (`websocket.ts:6` → `useUIStore.getState().updateLastUpdated()` at `:197`), a layering inversion (`lib` → `lib/store`) that also couples every message to a UI-store write (04-O2). Duplicated sink: `useRealTimeAnalytics` keeps its own `useState` copies (`:331-334`) of what `AnalyticsStore.realTimeData` also holds (`store.ts:77-83`), reconciled by OR-logic (`useRealTime.ts:169`) — two truths for "last realtime data". **Recommend:** (1) `transport.ts` — pure socket lifecycle, injectable constants (backoff base/cap, heartbeat ms — currently hardcoded `websocket.ts:28-29,157-166`), per-attempt clientId (04-B4), explicit state machine; (2) exactly one consumer writes realtime data to the store; hooks only select from it; (3) store updates via event-counter/batching (04-O2).

Status: verified

### 04-I5 · P2 · One currency/format module, en-IN-first, with explicit unit contracts
Today: correct formatters in `utils.ts:23-71` (`en-IN`, `₹/Cr/L` via `formatIndianRupees`), a divergent wrong set in `export.ts:461-477` (`en-US`, USD default — 04-B8), symbol-swap pseudo-conversion in ≥5 components (04-B14), page-local `toLocaleString('en-IN')` copies scattered across ≥10 pages (grep: 41 hits), and a percent/fraction helper collision (04-B9). **Recommend:** `lib/format.ts` as the only export surface — `formatINR(value, {notation:'full'|'cr-l'})`, `formatUSD`, `formatPctOfOne`, `formatPctPoints`, `formatQty` — all locale-hardwired correctly; delete `export.ts`'s trio and page-local duplicates; resolve FX by implementing or deleting `CurrencyContextType` (04-B14). This directly serves the AGENTS en-IN invariant.

Status: verified - with count correction: grep en-IN across frontend/src = 31 hits across 12 files (the reported 41 is stale), covering 8 dashboard pages plus utils.ts, export.ts, PerformanceChart.tsx, PortfolioDropzone.tsx; the divergence facts otherwise hold.

### 04-I6 · P2 · One CSV writer + route the backend CSV download through the typed client
Three CSV styles exist (04-B5) and two download paths for the backend's new real `text/csv` endpoint: `apiClient.exportCSV()` (`api.ts:181-184`, typed string — **zero callers**) vs the live raw `fetch('/api/v1/portfolio/export/csv')` in `dashboard/page.tsx:254-265`, which **never checks `response.ok`** — on a 503/500 it happily saves the JSON error body as `portfolio-….csv` (silent garbage file). **Recommend:** single `toCsv(rows)` helper (papaparse or quote-all+formula-guard), single download function that checks status, and delete the dead/raw duplicates. Also note the split-origin setup: axios targets `NEXT_PUBLIC_API_URL` directly (`api.ts:37`, CORS) while raw fetches go through the Next rewrite proxy (`next.config.ts:28-35`, localhost:8000 hardcoded) — two origin strategies that will diverge on deploy; pick one.

Status: verified

### 04-I7 · P3 · Single source of truth for domain/store types
`store.ts:8-59` defines its own `PortfolioPosition` (optional `quantity?`/`buy_price?`, **missing** `region`, `primary_source`, `total_cost`, `unrealized_gain_loss*`, `current_value` — fields the backend response model requires, `schemas.py:76-97`, and that components consume: `PortfolioTable.tsx:213,235`, `PortfolioStats.tsx:43`) and its own `PortfolioStore` whose action signatures contradict `types/index.ts:247-260` (`updatePosition(ticker, …)` vs `updatePosition(id: number, …)`, `removePosition(ticker)` vs `removePosition(id)`, plus `totalValue`/`bulkAddPositions`/`clearPositions` absent from the types mirror). Two interfaces, same names, incompatible shapes — one is guaranteed wrong; call sites bridge the gap with loose typing. **Fix:** `types/index.ts` (post-codegen, 04-I2) is the sole definition; store re-exports.

Status: verified

### 04-I8 · P3 · Dead-code sweep (deletion > addition)
- `store.ts:367-418` — `useCSVExport` + `convertToCSV` + `downloadCSV`: **zero callers** (grep `useCSVExport(` → none) and broken anyway (04-B5) → delete.
- `store.ts:76, 91, 356-364` — `isCalculating` never set; `setWebSocketConnection` **never called by the websocket layer** (grep: definition only) → `realTimeData.isConnected` is permanently `false`, silently compensated by `isConnected || realTimeData.isConnected` (`useRealTime.ts:169`). Delete the fake field or wire it properly in the transport.
- `types/index.ts:206-219` — `ExchangeRate`/`CurrencyContextType` phantom contracts (04-B14).
- `types/index.ts:262-281` — `UIStore`/`AnalyticsStore` mirrors (superseded, drift already proven).
- `api.ts:45-48, 109-114, 116-120` — no-op interceptor, dup `APIResponse`, unused `ErrorResponse` (04-B22).

Status: verified

### 04-I9 · P2 · Cache/invalidation strategy — declare one and delete the rest
Covered by 04-I3 but stating it as the strategy decision it is: today = react-query (installed, unused) ∪ dead zustand Map ∪ ad-hoc refetch-after-mutate ∪ WS pushes writing a *parallel* realtime copy. End state: **react-query for server reads** (keys from ticker+params), **zustand only for client state** (portfolio selection, UI, connection status), **WS messages invalidate queries** (`invalidateQueries({queryKey:['portfolio']})` on `portfolio_update`) instead of maintaining `realTimeData.portfolioData` as a shadow copy. That kills the merge logic at `useRealTime.ts:149-162` and the dual-sink problem at 04-I4.

Status: verified

### 04-I10 · P2 · Testability seams for the untested money paths
Existing tests cover utils basics and the (dead) cache (`src/test/unit/utils.test.ts`, `store.test.ts`). Untested and highest-risk: 422 array formatting (`api.ts:64`), error taxonomy (04-I1), backoff/delay computation (`websocket.ts:143`), freshness classification (`useRealTime.ts:131-137`), CSV escaping + formula guard (04-B6), percent-unit helpers (04-B9). **Fix:** extract these as pure functions (no axios/React/DOM imports) — the heartbeat/backoff constants and `jsPDF` construction already accept injection-friendly shapes if split per 04-I4 — then one small `test_*.py`-style assertion file each, per AGENTS ("prefer permanent tests in `tests/`" → frontend `src/test/unit`).

Status: verified

---

## 3. Optimizations

### 04-O1 · P2 · Whole-store subscriptions widen every re-render
- `useAnalytics.ts:31, 107, 149` — `const { positions } = usePortfolioStore();` subscribes to **all** portfolio state → any `isLoading` toggle, `error` set/clear, or `selectedTickers` change re-runs all three hooks' consumers.
- `websocket.ts:247` — `const { liveDataMode } = useUIStore();` → any `lastUpdated` write (which happens **per WS message**, `websocket.ts:197-198`) re-renders every `useWebSocket` consumer.
- App-wide pattern too (`Header.tsx:33-34`, `dashboard/page.tsx:61-62`, most dashboard pages) — but the layer under audit can fix its own three immediately. **Fix:** `usePortfolioStore(s => s.positions)` (plus `useShallow` where multiple fields are needed); note `positions` identity still churns per fetch — the `tickerKey` memo pattern is right, the subscription scope is wrong.

Status: verified

### 04-O2 · P2 · One WebSocket message triggers a multi-store re-render cascade
Path per message: `handleMessage` → `updateLastUpdated()` store write (`websocket.ts:196-198`) → all UI-store subscribers (04-O1) **and** → `options.onMessage` → `useRealTimeAnalytics` `setState` ×2 (`:339-351`) → `useEnhancedRealTimeAnalytics` three sync `useEffect`s write `AnalyticsStore` (`useRealTime.ts:97-113`) → whole-`realTimeData` selector (`:89`) sees a new object (`store.ts:322-353` replaces it wholesale per update) → all three merge `useMemo`s rebuild (`:149-162`) → outer memo (`:164-187`) → consumer re-render. That's ~4 distinct React render triggers for one market tick, plus a guaranteed extra render every 30s from `setDataAge(ageMinutes)` (`:129,141` — a fresh float every tick of the interval). **Fix:** single sink (04-I4), selective selectors, throttle/batch store writes, or event-counter semantics (`lastUpdateSeq`) so object identity churns only on real shape changes.

Status: verified

### 04-O3 · P2 · Export module drags `jspdf` + `xlsx` + `file-saver` into the graph statically
`export.ts:5-7` static imports; any page importing `ExportService`/`ExportPanel` pays for all three up front. `xlsx` (~monolithic ~400KB+) and `jspdf` are click-time-only features. `next.config.ts:14-25` already lists `jspdf`/`xlsx`/`papaparse` under `optimizePackageImports` (tree-shake hint only — `xlsx` doesn't tree-shake meaningfully) and `@tanstack/react-query` (04-I3) — the config anticipates libraries the code doesn't use while eagerly loading the ones it does. **Fix:** `const {ExportService} = await import('@/lib/export')` at button click; three dynamic imports, one line each.

Status: verified

### 04-O4 · P2 · No request cancellation anywhere → stale-request storms under ticker churn
Repo-wide grep: `AbortController|signal:` → **0 hits**; axios `timeout: 60000` (`api.ts:38`) means abandoned requests keep occupying backend vendor-cascade slots for up to a minute while new ones spawn (weight slider edits ×7 analytics endpoints via `useAnalytics.ts:50-58` = up to 7 concurrent ghosts per keystroke-burst). Concrete user-visible symptom is 04-B11; the systemic fix is `signal` threading (or react-query, 04-I3). **Fix:** accept `AbortSignal` in the apiClient wrappers (`apiClient.get(url, {signal})`) and abort in effect cleanups.

Status: verified

### 04-O5 · P3 · Analytics cache Map: clone-on-write O(n) per set + side-effectful read
`store.ts:286-293` — every `setCachedData` clones the entire Map; `getCachedData` (`:295-310`) **mutates** the Map and calls `set()` during a read (expiry path `:303-306`) → a `setState`-during-render hazard if ever called from render body. Moot if deleted per 04-I3/04-I8; if kept, use a version counter + immutable entries without clone, and make reads pure.

Status: verified

### 04-O6 · P3 · `tickerKey` strings rebuilt every render ×3 hooks
`useAnalytics.ts:86, 108, 150` — `.map().join(',')` over all positions on every render (and `positions` identity churns per fetch anyway, so this re-runs liberally). Negligible at 10–50 rows; fine to leave, `useMemo` if books grow.

Status: verified

### 04-O7 · P3 · Freshness interval forces a render every 30s
`useRealTime.ts:116-143` — `setDataAge(ageMinutes)` with a continuously changing float guarantees a state change each interval regardless of whether the `fresh/stale/outdated` bucket moved. Derive age at render from `lastUpdate` timestamp (or only `setState` when the bucket changes).

Status: verified

---

## 4. Recommended changes (prioritized)

| # | ID | Sev | file:line | Note |
|---|---|---|---|---|
| 1 | 04-B6 | **P0** | `export.ts:196-216`, `store.ts:384-403` | Formula-guard CSV cells (prefix `'` for `[=+\-@\r\t]`) + quote-all in one shared helper — closes Excel injection for all export paths (fold in 04-B5 escaping fixes). |
| 2 | 04-B1 | P1 | `api.ts:86-92` | Read `data.detail` in the generic error branch — restores real vendor-outage messages for every 503/500 on the platform. |
| 3 | 04-B4 | P1 | `websocket.ts:37,143-153` | Regenerate `clientId` per connect attempt + handle close 1008 — backend rejects duplicate live IDs (`websocket.py:32-35`), current design dead-ends reconnect after unclean drops. |
| 4 | 04-B3 (+B18) | P1 | `websocket.ts:68-70,128-136` | Settle the `isConnecting` promise (queue/reject) and detach handlers in `disconnect` — fixes StrictMode zero-socket hang + orphan-socket races. |
| 5 | 04-B9 | P1 | `utils.ts:52-53`, `types/index.ts:21-22` | Unit-typed percent helpers; backend `unrealized_gain_loss_pct` is percent (`portfolio.py:99`) → `PortfolioTable.tsx:235`/`PortfolioStats.tsx:122` currently show 667% for +6.67%. |
| 6 | 04-B10 | P1 | `useRealTime.ts:34-43` (root `store.ts:115-120`) | Make `fetchPortfolio` rethrow so refresh doesn't stamp `lastRefresh` on failure; clear the 1s `setTimeout` in effect cleanup. |
| 7 | 04-B11 / 04-O4 | P1 | `useAnalytics.ts:33-94` | Abort in-flight analytics on effect change (or adopt react-query, 04-I3) — closes the out-of-order overwrite race and 60s ghost requests. |
| 8 | 04-B12 | P1 | `types/index.ts:52-77, 284-298` | Add `\| null` + `model_fitted`/`is_limited_history`/`error` discriminated unions to match the new backend contract; delete page-local inline redeclarations. |
| 9 | 04-B13 | P1 | `store.ts:155-161` | Surface `bulkAddPositions` `failed` count — silent partial imports currently report success. |
| 10 | 04-B7 + 04-B8 | P1 | `export.ts:392-412, 461-477` | Add page-break checks to the institutional PDF (silent holdings truncation) and replace `en-US` formatters with the `en-IN` set from `utils.ts`. |

**Next tier (P2, in order):** 04-I1 typed `AppError` + status→message map (makes #2 durable) → 04-I3 adopt installed react-query, delete dead cache/fetch layer (absorbs #7 + 04-I9) → 04-I2 openapi type generation (absorbs #8 permanently) → 04-I5/04-B14 currency module or delete phantom FX contracts → 04-B15 persist totals with positions → 04-B17 surface reconnect state machine → 04-I4 WebSocket re-cut → 04-O1/04-O2 selector granularity + single realtime sink.

---

*Read-only audit: the only file written is this report.*
