# Frontend Audit â€” 03: Tools Pages C

Wave-2 status: fixed=54 · verified-open=0 · refuted=0 · skipped=7 · total=61

- **ID:** 03-tools-pages-c
- **Date:** 2026-09-23
- **Auditor lens:** UI/UX + system design (read-only; this file is the only edit)
- **File set & actual line counts** (brief's counts were stale; actuals below):

| File | Lines |
|---|---|
| frontend/src/app/dashboard/equity-research/page.tsx | 1116 |
| frontend/src/app/portfolio/manage/page.tsx | 847 |
| frontend/src/app/dashboard/screener-studio/page.tsx | 662 |
| frontend/src/app/dashboard/settings/page.tsx | 409 |
| frontend/src/app/dashboard/monte-carlo/page.tsx | 289 |
| frontend/src/app/dashboard/india-flows/page.tsx | 152 |
| frontend/src/app/dashboard/pairs/page.tsx | 115 |
| frontend/src/app/layout.tsx | 34 |
| frontend/src/app/page.tsx | 10 |
| frontend/src/app/dashboard/layout.tsx | 27 |
| **Total** | **3561** |

Cross-referenced (read-only): `src/test/pages/{EquityResearch,ScreenerStudio,Settings,MonteCarloCopy,FabricatedFallbacks}.test.tsx`, `src/test/components/AddPositionModalSimple.test.tsx`, `src/lib/api.ts`, `src/types/index.ts`, `src/components/portfolio/AddPositionModalSimple.tsx`, backend `app/models/schemas.py`, `app/api/portfolio.py`, `app/api/equity_research.py`, `app/api/data.py`, `app/services/equity_research_service.py`.

Severity counts: **P0 = 1, P1 = 17, P2 = 27, P3 = 16** (61 findings: 34 bugs, 18 improvements, 9 optimizations).

---

## 1. Bugs

### 03-B1 â€” P0 â€” manage: null `.toFixed()` crashes page when forecast returns null vol/VaR
`frontend/src/app/portfolio/manage/page.tsx:110-112` writes `tickerData.volatility_forecast` / `var_forecast` straight through; render guards at `page.tsx:683` and `page.tsx:698` check `!== undefined`, then call `.toFixed(2)` (`page.tsx:686`, `page.tsx:705`). Backend forecast-risk returns **`null`** per-ticker for insufficient history (proven by `FabricatedFallbacks.test.tsx:118-135`, which feeds `volatility_forecast: null`). `null !== undefined` â†’ `null.toFixed(2)` â†’ TypeError â†’ React crash of the whole manage page. **Wrong (crash), not ugly.**
**Fix:** guard with `!= null` (or `typeof === 'number'`) at both cells and at the `risk_level: getRiskLevel(...)` write (`page.tsx:112`); render `N/A` for null (matches the FabricatedFallbacks contract).
**Status: fixed** - null vol/VaR guarded with `!= null` at both cells; null normalized to undefined at write; `risk_level: undefined` on missing/error (never Low); test: FabricatedFallbacks `portfolio manage null forecast`


### 03-B2 â€” P1 â€” screener: "Add to Portfolio" sends `weight: 0`, always rejected by backend 422
`frontend/src/app/dashboard/screener-studio/page.tsx:156-162` posts `weight: 0`. Backend `PortfolioPositionBase.weight` is `Field(..., gt=0, le=1)` (`backend/app/models/schemas.py:14`) â†’ every add fails 422. The catch (`page.tsx:167-169`) then discards the interceptor's human detail and shows a bare `alert('Could not add â€¦')`, so the user never learns why. Also violates the **zero-state invariant** (first position weight must be 100.00%): even if 0 were accepted, an empty portfolio would get weight 0, not 1.0.
**Fix:** compute weight the way `AddPositionModalSimple.tsx:74-86` does (1.0 when portfolio empty, else value/(total+value)), and surface `err.message` instead of `alert`.
**Status: fixed** - weight computed per AddPositionModalSimple (1.0 empty else value/(total+value)); failures surface inline addError with err.message, no alert; test: ScreenerStudio weight-1.00 + inline-error cases


### 03-B3 â€” P1 â€” equity-research: profile error path reads dead `.response`, drops 503 detail
`frontend/src/app/dashboard/equity-research/page.tsx:91`: `profData.reason?.response?.data?.detail || 'Failed to fetch company profile'`. The axios interceptor (`src/lib/api.ts:51-105`) rejects with a plain `new Error(message)` â€” `reason.response` is always undefined, so the backend's vendor-outage detail (mapped to HTTP 503 in `backend/app/api/equity_research.py:49-254`) never reaches the user; fallback is a generic string. This is exactly the 422/503-humanness invariant, misused at page level.
**Fix:** use `profData.reason?.message` (interceptor already humanizes) as primary, generic string as last resort.
**Status: fixed** - `profData.reason?.message` primary (interceptor humanizes), generic string last resort


### 03-B4 â€” P1 â€” equity-research: stale previous-company data shown after a failed/partial ticker switch
`fetchAllData` (`page.tsx:77-117`) never clears `profile`, `shareholding`, `concalls`, `customRatios`, `financials` on ticker change; failures skip `setProfile` (line 88-92) but the catch only sets `error`. Render condition `!loading && profile` (`page.tsx:291`) then shows the **old company's full profile, shareholding table, and concalls** under the new `activeTicker`/search box, alongside an error banner. Wrong data attribution.
**Fix:** `setProfile(null); setShareholding(null); setConcalls([]); setFinancials(null)` at the top of `fetchAllData` (or key the subtree on `activeTicker`).
**Status: fixed** - profile/shareholding/concalls/financials/errors/audio cleared at top of fetchAllData


### 03-B5 â€” P1 â€” equity-research: shareholding tab renders a blank void; shareholding/concall/ratio failures are silent
Rejected shareholding/concall/ratio promises are ignored (`page.tsx:94-102`, no else branch). Tab body condition `activeTab === 'shareholding' && shareholding` (`page.tsx:663`) renders **nothing at all** â€” tabs + empty slate, no message, no retry. Concalls failure degrades to the misleading "No conference call recordings available" empty state (`page.tsx:855-858`) because `concalls` stays `[]`.
**Fix:** per-endpoint error state; render an error/empty card inside each tab regardless of data presence.
**Status: fixed** - shareholdingError/concallError per-endpoint states render error cards in the affected tabs


### 03-B6 â€” P1 â€” equity-research: statements fetch failure â†’ permanent "Loading statement records..."
Statements errors only `console.warn` (`page.tsx:108-110`, `page.tsx:129-131`); the fallback branch (`page.tsx:1025-1028`) displays "Loading statement records..." forever when `financials` stays null. User waits on an error that already resolved.
**Fix:** track a `statementsError` and render an error + retry in that branch.
**Status: fixed** - statements fetched lazily on financials-tab entry with statementsError + Retry button


### 03-B7 â€” P1 â€” equity-research: AI Memo / Forensic buttons are silent no-ops on failure
`handleOpenAiMemo` / `handleOpenAiForensic` (`page.tsx:166-188`) only `console.error` â€” on 503/vendor outage (the exact case backend now maps) the four entry points (top bar `page.tsx:256-270`, dossier tab `page.tsx:1048-1072`) click and do **nothing**: no spinner, no error, no disabled state (double-click also fires duplicate requests).
**Fix:** loading state on the buttons, surface `err.message` in the page error banner or a toast.
**Status: fixed** - AI memo/forensic handlers wired with aiLoading spinner/disabled and err.message surfacing


### 03-B8 â€” P1 â€” screener â†’ equity-research deep link is dead: `?ticker=` ignored
Screener builds `/dashboard/equity-research?ticker=...` (`screener-studio/page.tsx:201-207`, `page.tsx:348-354`) but equity-research has no `useSearchParams`/`searchParams` handling anywhere (state hardcoded `'RELIANCE'`, `equity-research/page.tsx:49-50`; repo-wide grep: zero `useSearchParams`). "Deep Equity Research" opens RELIANCE regardless of clicked stock.
**Fix:** read `searchParams.ticker` in equity-research (Suspense boundary per App Router rules) to initialize `activeTicker`/`tickerInput`.
**Status: fixed** - default export wraps content in Suspense; initial ticker read from `?ticker=` via useSearchParams; test: EquityResearch `reads ?ticker= deep-link`


### 03-B9 â€” P1 â€” equity-research: dividend-yield heuristic mis-scales yields â‰¤1 and contradicts the peer table
`page.tsx:412-414`: `y > 1 ? y : y * 100`. Backend passes raw vendor value with **no normalization** (`backend/app/services/equity_research_service.py:90`); backend tests use realistic percent-form values `0.4`, `0.5`, `1.2` for Indian stocks (`test_equity_research_and_screens.py:67`, `test_api_endimesteps`-equivalent `test_api_endpoints.py:74,142`). 0.4 â†’ renders **40.00%**. Peer table at `page.tsx:650` renders the same raw field as `${peer.dividend_yield.toFixed(2)}%` (â†’ 0.40%) â€” same payload, two different answers on one page.
**Fix:** pick one unit server-side (normalize to percent in backend), delete the client heuristic, use it for peers too.
**Status: fixed** - raw `dividend_yield.toFixed(2)%` with no y>1 heuristic; test: EquityResearch asserts 0.40% never 40.00%


### 03-B10 â€” P1 â€” equity-research: Piotroski `|| 0` fabricates `0/9` (AGENTS invariant)
`page.tsx:430-437`: `(profile.custom_ratios.piotroski_score || 0)` â€” missing score renders a red **0/9** badge as if measured. Invariant: fabricated metrics â†’ `N/A` + flag, never a fake zero.
**Fix:** `score == null ? 'N/A' : `${score}/9`` and neutral styling for N/A.
**Status: fixed** - `piotroski_score == null` renders N/A with neutral style; test: EquityResearch `null Piotroski score renders N/A`


### 03-B11 â€” P1 â€” manage: error/missing forecast paths fabricate `risk_level: 'Low'`
`page.tsx:115-120` (ticker absent from response) and `page.tsx:128-134` (forecast API throws) both write `risk_level: 'Low' as const` while leaving vol/VaR undefined. Table then shows a confident green **"Low"** badge (`page.tsx:718-727`) next to N/A vol â€” fabricated risk classification. Directly contradicts `FabricatedFallbacks.test.tsx:118-136` ("null vol renders N/A risk level, never a fabricated Low").
**Fix:** set `risk_level: undefined` on both paths; show N/A.
**Status: fixed** - `risk_level: vol !== undefined ? getRiskLevel(vol) : undefined`; error path never writes Low


### 03-B12 â€” P1 â€” manage: delete failure = unhandled promise rejection, zero user feedback
Delete confirm button calls `handleDeletePosition` (`page.tsx:835`) which rethrows (`page.tsx:231-234`); `onClick={() => ...}` floats the rejected promise â†’ console-only. Dialog stays open, no message, user assumes worst. 503/409/422 details all lost. (Error-surfacing invariant.)
**Fix:** `.catch(err => setError(err.message))` (or try/catch in the handler) and keep/close dialog deliberately.
**Status: fixed** - delete call in try/catch -> setError(err.message); isDeleting wired; dialog a11y shipped with 03-I18


### 03-B13 â€” P1 â€” manage: inline-edit save swallows 422/503 and never validates input
`saveEditing` catch (`page.tsx:282-284`) only `console.error`s. Inputs allow `0`/empty (`page.tsx:626`, `639`: `parseFloat || 0`) â†’ backend 422 (`quantity/buy_price gt=0`, `schemas.py:15-16`) â†’ silent failure, edit row stays open with no explanation. Invalid `added_on` is **silently discarded** from the payload (`page.tsx:275-278`) instead of shown as a field error.
**Fix:** surface `err.message` next to the row; block save when quantity/price â‰¤ 0; flag dropped date.
**Status: fixed** - qty/price > 0 validation, invalid/future buy date blocked and flagged, err.message surfaced on failure


### 03-B14 â€” P1 â€” manage: currency formatting uses `en-US`, violating the en-IN invariant
`page.tsx:332-339`: `toLocaleString('en-US')` for every â‚¹ amount (buy price, current value, P/L, totals). AGENTS.md requires `en-IN` localization for Indian equities (â‚¹/Cr/L). Indian portfolios render `1,000,000` instead of `10,00,000`.
**Fix:** use shared `formatCurrency` from `src/lib/utils.ts:23-26` (already `en-IN`) or switch locale to `en-IN` + lakh/crore tiers.
**Status: fixed** - local formatCurrency wraps the shared en-IN util (utils.formatCurrency)


### 03-B15 â€” P1 â€” settings: five preference controls are placebo; success banner lies
`currency`, `benchmark`, `lookbackDays`, `riskFreeRate`, `targetVol` (`page.tsx:42-46`) are pure local state â€” never loaded from backend, never sent. Save persists **only** `{ primary_source }` (`page.tsx:84`; backend `PUT /data/config` accepts only `primary_source|cache_ttl_minutes|enable_cache`, `backend/app/api/data.py:194-219`). Yet the banner claims *"Preferences updated and applied across all quantitative terminal views"* (`page.tsx:146`) and the subtitle promises managing *"valuation currencies, default benchmark indices, statistical model lookback parameters"* (`page.tsx:138-140`). Changing currency to USD then Save shows success while nothing happened. Wrong/misleading, plus stale/partial sync (getConfig at `page.tsx:56-68` hydrates only `primary_source`).
**Fix (either):** persist these fields end-to-end, or remove/disable them with an honest label; success copy must enumerate exactly what was saved.
**Status: fixed** - placebo currency/benchmark/lookback/risk-free/target-vol sections removed; header/success/save copy honest; test: Settings `renders only real data-source controls`


### 03-B16 â€” P1 â€” india-flows: all endpoint errors swallowed â†’ fabricated "no anomalies" success (+ empty state during load)
Every request has `.catch(() => ({ data: { â€¦ [] } }))` (`page.tsx:17-19`), so a 503/outage renders the friendly *"No >2Ïƒ delivery spikes detected in portfolio holdings today."* (`page.tsx:62-63`) â€” **error disguised as clean bill of health** (metric-hygiene invariant). Additionally, tables are not gated on `loading` (`page.tsx:8`, only the Refresh button uses it), so the same false empty state flashes on first paint before data arrives. The outer `catch` (`page.tsx:24-27`) is effectively dead (all inner promises pre-caught) â€” no error UI exists at all.
**Fix:** drop per-request `.catch`, add an error banner, gate empty states on `!loading`.
**Status: fixed** - per-request .catch removed; error state + banner; empty states gated on !loading && !error


### 03-B17 â€” P1 â€” india-flows: `flows` state is dead â€” the advertised FII/DII section doesn't exist
`page.tsx:9` declares `flows`, `page.tsx:17` fetches `/analytics/india-flows?lookback_days=30`, `page.tsx:21` stores it â€” **never rendered anywhere**. Page copy promises *"FII/DII institutional net flows"* (`page.tsx:43-44`; Sidebar/DashboardLayout route subtitles repeat it). Feature fetched, paid for, not shown.
**Fix:** render the flows table/chart or delete the claim + fetch.
**Status: fixed** - FII/DII table rendered from date/fii_net_crores/dii_net_crores/total_net_crores


### 03-B18 â€” P1 â€” pairs: error detail discarded â€” reads dead `.response`, falls back to generic string
`page.tsx:20-21`: `err.response?.data?.detail || 'Failed to scan cointegrated pairs'`. Interceptor rejects plain `Error` (no `.response`), so real 422/503 detail in `err.message` is dropped; user always sees the generic string. Same misuse pattern as 03-B3.
**Fix:** `err?.message || 'Failed to scan cointegrated pairs'`.
**Status: fixed** - `err instanceof Error ? err.message : fallback` at fetchPairs


### 03-B19 â€” P2 â€” settings: three "Active" feed badges are hardcoded fabrications
`page.tsx:336-367`: "Market Price Feed / Screener.in Live API / NSE Bhavcopy Microstructure" all permanently show green pulsing **Active** with no API call. Violates live-API-driven metric hygiene; lies when backend/vendor is down (the same outage that produces 503s elsewhere).
**Fix:** drive from a health/config endpoint or remove the status pill.
**Status: fixed** - hardcoded Active feed pills removed; test: Settings asserts no Active text


### 03-B20 â€” P2 â€” settings: save/cache errors replaced by fixed strings, discarding interceptor detail
`page.tsx:88` ("Could not saveâ€¦ Is the backend running?") and `page.tsx:117` ignore `err.message` (which carries humanized 422/503 text). Generic copy is human but unhelpful for validation failures (e.g. invalid `primary_source`).
**Fix:** `setSaveError(err instanceof Error ? err.message : fallback)`.
**Status: fixed** - err.message passthrough on save/cache failures, no 5s auto-dismiss; test: Settings `surfaces backend error text when saving fails`


### 03-B21 â€” P2 â€” manage: `SimplePortfolioPosition` declares camelCase fields that are never populated
Interface `page.tsx:42-47` declares `totalCost`, `unrealizedGainLoss`, `unrealizedGainLossPct`, `currentValue`; the transform at `page.tsx:156-162` writes `total_cost`, `unrealized_gain_loss`, â€¦ (snake). Runtime works only because spread + snake accessors are used (`page.tsx:327-329`, `665`, `675`); the camelCase contract is a lie to TS and blocks safe refactors.
**Fix:** align interface with actual snake_case payload (or transform fully to camelCase and update accessors).
**Status: fixed** - `type SimplePortfolioPosition = PortfolioPosition` (dead camelCase interface removed)


### 03-B22 â€” P2 â€” manage: forecast response `error` / limited-history flags ignored
`fetchForecastRisk` (`page.tsx:102-124`) reads only `data.positions`; backend forecast-risk includes `error` (`types/index.ts:391`, `analytics.py:506` etc.) and `is_limited_history` (`analytics.py:561`). Backend's "Insufficient data for forecast" never surfaces â€” user sees N/A/Low with no explanation (AGENTS: surface `error/is_limited_history/model_fitted`).
**Fix:** if `data.error`, render an amber banner (pattern already exists: `FabricatedFallbacks.test.tsx:84-99`).
**Status: fixed** - forecastNotice state renders data.error / is_limited_history flag in an amber banner; test: FabricatedFallbacks manage case asserts the backend error text


### 03-B23 â€” P2 â€” equity-research: peer-row click doesn't sync the search box
`page.tsx:635` sets `activeTicker` but not `tickerInput` â€” header input still shows the previous symbol while the body loads the peer, so a subsequent form submit reverts to the old ticker (`handleSearch` reads `tickerInput`, `page.tsx:138-143`).
**Fix:** set both, or derive input from `activeTicker`.
**Status: fixed** - peer-row click also setTickerInput so the search box follows activeTicker


### 03-B24 â€” P2 â€” screener: strategies fetch failure leaves a blank selector, no message
`page.tsx:74-84` only `console.error`s; `strategies` stays `[]` â†’ strategy-card grid (`page.tsx:437-467`) renders empty while `runScreen('coffee_can')` still fires. User sees an empty wall with no explanation/retry.
**Fix:** error state + retry on the strategy grid.
**Status: fixed** - strategiesError state + Retry card with err.message; test: ScreenerStudio `strategy load failure renders the backend message with a Retry control`


### 03-B25 â€” P2 â€” monte-carlo: `FanChart` crashes on empty `fan`
`page.tsx:53`: `fan[fan.length - 1].year` â€” no length guard; `page.tsx:56-58` maps unconditionally. Any backend response with `fan: []` (defensive path) throws during render of results.
**Fix:** early-return null when `fan.length === 0` and show a text summary instead.
**Status: fixed** - FanChart returns null on empty fan after its hooks (useMemo) run


### 03-B26 â€” P2 â€” root layout: metadata still "Create Next App"
`frontend/src/app/layout.tsx:15-18` exports `title: "Create Next App"`, `description: "Generated by create next app"`. Dashboard routes override via `dashboard/layout.tsx:9-15`, but `/portfolio/manage` (no metadata export, no `portfolio/layout.tsx` â€” glob confirmed empty) inherits the scaffold defaults for browser tab/SEO.
**Fix:** real product title/description in root layout; add page/`portfolio` metadata for manage.
**Status: fixed** - metadata title Daisy Risk Engine + real description


### 03-B27 â€” P3 â€” manage: dead `EditPositionModal` wiring
`showEditModal`/`selectedPosition` (`page.tsx:61-62`) are only ever reset, never set to `true`/a position (grep: no other assignments) â€” inline edit is the sole path, yet `<EditPositionModal>` is mounted (`page.tsx:806-815`).
**Fix:** delete the dead state + mount, or wire row action to it (one edit path only).
**Status: fixed** - dead EditPositionModal import/state/mount removed


### 03-B28 â€” P3 â€” manage: `% Return` can render `NaN`
`page.tsx:160`: division by `quantity * buy_price`; `page.tsx:675` renders `.toFixed(2)` unguarded. A zero-cost row (legacy data) shows `NaN%`.
**Fix:** guard denominator, render `N/A`.
**Status: fixed** - `Number.isFinite(pct)` guard renders N/A for zero-cost rows


### 03-B29 â€” P3 â€” equity-research: bare `â‚¹` when price/52W fields null
`page.tsx:362`, `365-367`: `â‚¹{profile.current_price?.toLocaleString(...)}` â†’ `â‚¹` with nothing (React drops `undefined`, keeps the literal). Looks broken next to handled N/A metrics.
**Fix:** conditional like other metric cells (`page.tsx:384` pattern).
**Status: fixed** - price/52W null renders N/A instead of bare Rs


### 03-B30 â€” P3 â€” equity-research: clipboard copy claims success without awaiting
`page.tsx:190-194`: `navigator.clipboard.writeText(text)` un-awaited; `setCopiedPrompt(true)` fires even if the promise rejects (insecure context/permissions) â€” "Copied to Clipboard!" can be false.
**Fix:** `await ... .then(...).catch(showError)`.
**Status: fixed** - clipboard write awaited with catch -> setError


### 03-B31 â€” P3 â€” equity-research: `alert()` for Excel export failure
`page.tsx:160` â€” blocking native alert inconsistent with the page's inline error banner (`page.tsx:281-289`).
**Fix:** set the page error state instead.
**Status: fixed** - Excel export catch -> err.message banner, no alert()


### 03-B32 â€” P3 â€” india-flows: z-score always prefixed `+`
`page.tsx:82`: `+{a.z_score}Ïƒ` renders `+-1.50Ïƒ` for negative spikes.
**Fix:** format sign conditionally (or rely on the number's own sign).
**Status: fixed** - z-score sign-aware (`+` prefix only when > 0)


### 03-B33 â€” P3 â€” pairs: `useState` without setters for constants
`page.tsx:11-12`: `const [lookbackDays] = useState(252)` â€” state machinery for constants; effect deps (`page.tsx:27-29`) pretend they can change.
**Fix:** module-level `const LOOKBACK_DAYS = 252`.
**Status: fixed** - lookback/p-value hoisted to module consts


### 03-B34 â€” P3 â€” equity-research + screener: unused imports (dead bundle surface)
equity-research `page.tsx:46` (`formatCurrency, formatPercent, formatIndianRupees`), `page.tsx:9,23,24,26` (`TrendingUp, ArrowUpRight, ArrowDownRight, Pause` â€” no JSX usage); screener `page.tsx:11,17` (`Percent, ChevronRight`), `page.tsx:37` (`formatCurrency, formatPercent`).
**Fix:** delete (also silences lint).
**Status: fixed** - unused imports deleted in equity-research + screener (also resolves 03-O9)


### AGENTS.md invariant violations in this file set (explicit)

| Invariant | Evidence |
|---|---|
| en-IN localization for Indian equities | **03-B14** â€” manage `page.tsx:335` uses `en-US` |
| Zero-state first position weight = 100.00% | **03-B2** â€” screener `page.tsx:160` sends `weight: 0` (bypasses the modal's 1.0 logic) |
| Metric cards strictly live-API-driven, no fabricated values | **03-B10** (Piotroski `||0`), **03-B11** (fabricated `Low`), **03-B19** (hardcoded `Active`), **03-B16** (error â†’ "No anomalies") |
| Fabricated metrics â†’ null + flag (`error`/`is_limited_history`/`model_fitted`) | **03-B11**, **03-B22** (manage ignores `data.error`) |
| 422/503 surfaced as human messages, not raw/lost | **03-B3**, **03-B18**, **03-B12**, **03-B13**, **03-B2**, **03-B20** |
| TanStack cells: `row.original \|\| row` | **Compliant** â€” screener `page.tsx:197,229,249,269,289,309,329,343` all follow the pattern |

---

## 2. Improvements (UI/UX + system design)

### 03-I1 â€” P2 â€” equity-research: 1116-line monolith; extraction candidates
`page.tsx:48-1116` holds search bar, banner, metric ribbon, 5 tab bodies, audio player, AI modal in one component with ~15 `useState`s. Extract: `ResearchHeader` (`206-272`), `ProfileBanner`+`MetricRibbon` (`293-494`), per-tab components (`529-1076`), `AiPromptModal` (`1080-1113`). Improves testability (current test renders everything), re-render isolation, and code navigation.
**Status: skipped** - component-extraction refactor of the 1116-line monolith exceeds surgical-fix scope; file a dedicated refactor ticket


### 03-I2 â€” P2 â€” equity-research: no per-endpoint error taxonomy / retry
Profile has a banner (`281-289`); shareholding/concalls/ratios/statements/AI-prompts each fail differently (silent, fake-empty, stuck-loading, no-op â€” 03-B5/6/7). Design one pattern: `{ source: 'shareholding', status, message }` + per-card Retry. This is the single highest-value structural fix for the multi-step research flow.
**Status: skipped** - full error-taxonomy abstraction deferred; per-endpoint behavior covered minimally by 03-B5/B6/B7


### 03-I3 â€” P2 â€” equity-research: AI modal a11y gaps
`page.tsx:1081-1113`: backdrop has no `onClick` close, no `Escape` handler, close button (`1089-1094`) has no `aria-label` (bare `âœ•`), no focus trap/return, no `role="dialog"`/`aria-modal`. Keyboard users can get trapped behind `max-h-[85vh]` content.
**Status: fixed** - backdrop onClick + stopPropagation, role=dialog, aria-label close, Escape keydown effect


### 03-I4 â€” P2 â€” equity-research: audio player not reset on ticker change
`activeAudioUrl` (`page.tsx:74`) survives `setActiveTicker` â€” MP3 from company A keeps playing while company B's research loads; the floating player (`820-841`) still shows A's URL. Reset in `fetchAllData`.
**Status: fixed** - setActiveAudioUrl(null) in fetchAllData reset


### 03-I5 â€” P3 â€” equity-research: dated AI model copy
`page.tsx:1046` ("Claude 3.7 / ChatGPT o3") and `page.tsx:1101` ("Claude 3.7 Sonnet, DeepSeek R1, or ChatGPT o3") hardcode model names that age badly. Use neutral "your AI assistant" or a maintained constant.
**Status: fixed** - AI copy de-dated to your AI assistant


### 03-I6 â€” P2 â€” manage: no weight column â€” zero-state 100% and weight math invisible
Table (`page.tsx:538-768`) shows qty/price/date/value/P&L but never `position.weight`, even though updates carry weight (`page.tsx:272`) and Avg Weight is summarized (`496-502`). Users can't verify the invariant (first position = 100.00%) or catch renormalization surprises. Add a Weight column (en-IN %, 2 decimals).
**Status: fixed** - Weight column added (sortable header + cell with N/A guard)


### 03-I7 â€” P2 â€” manage/settings: error UX re-invents weak wheels while a Notification system exists
Manage uses a static red box only for load failures (`page.tsx:422-429`); CRUD failures vanish (03-B12/13). Settings auto-dismisses errors after 5s (`page.tsx:89`) â€” a validation message can disappear while being read. `src/components/ui/NotificationSystem.tsx` already models success/error/warning/info toasts; route mutation outcomes through it (manual dismiss, consistent styling).
**Status: skipped** - NotificationSystem lives in components/ (batch E scope); manage/settings failure messages now persist inline instead of auto-dismissing


### 03-I8 â€” P2 â€” settings: no dirty-state / partial-save UX
Save button always enabled (`page.tsx:393-404`); no "unsaved changes" indicator; no diff of what will change; switching primary-source card then navigating away loses it silently. Track `dirty` vs hydrated config, label Save "Save data-source preference" (until 03-B15 is fixed), disable when clean.
**Status: fixed** - dirty tracked vs hydrated config; Save disabled when clean; label Save Data Source Preference; test: Settings save flow


### 03-I9 â€” P2 â€” screener: custom-filter inputs lack validation/affordances
`page.tsx:484-532`: plain `type="number"` with no `min`/`step`, no labels tied via `htmlFor`, negatives/`NaN` accepted (`Number('')` â†’ 0, so clearing "Max P/E" silently screens `max_pe=0` â†’ empty results that look like a data outage). Add `min`, `step`, inline "must be > 0" validation, `id`/`htmlFor` pairs.
**Status: fixed** - min/step/id/htmlFor on all 5 custom inputs + must-be-positive guard before submit


### 03-I10 â€” P3 â€” screener: custom strategy state + mid-flight strategy switches
After a custom run, `activeStrategy='custom'` (`page.tsx:132`) highlights **no** card (`page.tsx:439` never matches) â€” user loses orientation; built-in cards stay clickable during load (`page.tsx:441-443` not disabled), so two `runScreen`s can race (last-writer-wins). Add a "Custom" chip/active state; disable cards while `loading`.
**Status: fixed** - strategy cards disabled while loading; synthetic Custom Screen active chip after custom runs


### 03-I11 â€” P3 â€” screener: pagination footer reads "Showing 1 to 0 of 0"
`page.tsx:631-638` computes `pageIndex*pageSize+1` unconditionally â€” with an empty filtered set the footer contradicts the "No stocks matched" row (`609-614`). Hide footer or show "0 results" when `rows.length === 0`.
**Status: fixed** - pagination footer hidden when the filtered row set is empty


### 03-I12 â€” P2 â€” design-system divergence: equity-research & screener force a dark slate theme inside a light-capable shell
Both root-div `min-h-screen bg-slate-950 text-slate-100` (`equity-research/page.tsx:205`, `screener-studio/page.tsx:407`) while `DashboardLayout` shell is `bg-gray-50 dark:bg-gray-900` with `dark:` variants (`DashboardLayout.tsx:132`) and siblings (settings/manage/monte-carlo/india-flows/pairs) use semantic `dark:` pairs. In light mode these two pages render as unthemed black rectangles under a white sidebar; they also duplicate page chrome (own `h1` at `equity-research:213`, `screener:415`) while sibling pages use the Header/`routeTitles` pattern â€” and `routeTitles` has no entries for these two routes, so their Header title falls back to generic "Dashboard" (`DashboardLayout.tsx:127`). Standardize on theme tokens + Header titles (coordinate: `routeTitles` lives in shared layout â€” note for that auditor).
**Status: skipped** - cross-cutting theme-token migration spans components/ + shared layout routeTitles; coordination note left for the design-system pass


### 03-I13 â€” P3 â€” monte-carlo: honest calibration fields fetched but never shown
Response carries `historical_mu_annual`, `historical_sigma_annual`, `expected_shortfall_vs_target` (`page.tsx:32-33`) â€” all unused. Displaying them (next to `num_paths`/`method` at `page.tsx:256-259`) would strengthen the "honest copy" stance already asserted by `MonteCarloCopy.test.tsx`.
**Status: fixed** - hist. mu/sigma shown next to paths/method (annual fractions x100 -> %)


### 03-I14 â€” P3 â€” monte-carlo: previous results blank on re-run
`page.tsx:226`: `{!running && result && â€¦}` â€” hitting Run hides all results until the new run lands, flashing to empty. Keep last result with a subtle "updating" overlay (stale-while-revalidate).
**Status: fixed** - results stay mounted during re-run with opacity-50 + pointer-events-none overlay


### 03-I15 â€” P2 â€” india-flows: no timestamp, no error UI (pairs has one â€” copy it)
`pairs/page.tsx:53-58` shows an error banner; india-flows has neither banner nor "as of" time. Add `lastUpdated` (pattern: Header's `lastUpdated` in `Header.tsx:101`) â€” microstructure data is time-critical; undated tables invite stale interpretation.
**Status: fixed** - lastUpdated As-of timestamp + AlertCircle error banner + gated empty states (pairs pattern)


### 03-I16 â€” P2 â€” currency formatting: three local formatters, one shared util
Local `formatCr` duplicated verbatim in equity-research (`page.tsx:196-202`) and screener (`page.tsx:175-181`); manage has its own `en-US` formatter (03-B14); shared `formatCurrency`/`formatIndianRupees` (`src/lib/utils.ts:23-70`) already implement â‚¹/Cr/L en-IN and are imported-but-unused in equity-research (`page.tsx:46`). Consolidate on the util to fix en-IN once everywhere.
**Status: skipped** - formatCr is Cr-denominated while shared formatCurrency is rupee-denominated; consolidation needs a formatting-contract decision, not a drive-by swap


### 03-I17 â€” P3 â€” settings: fixed timeout auto-dismiss + `window.confirm` for the destructive action
Success hides at 3s (`page.tsx:86`), error at 5s (`page.tsx:89`), cache message at 5-6s (`page.tsx:115,118`) â€” users mid-read lose the message; failures especially should persist until dismissed. Cache purge correctly uses `window.confirm` (`page.tsx:96-101`, test-backed) â€” fine, but an in-page confirm matching the manage delete dialog style (`manage/page.tsx:818-843`) would be visually consistent.
**Status: fixed** - failure messages persist until next attempt (no timer); success banner copy honest; window.confirm retained (test-backed)


### 03-I18 â€” P3 â€” manage: delete dialog a11y
`page.tsx:818-843`: fixed overlay without `role="dialog"`, `aria-modal`, Escape-to-close, or focus move â€” inconsistent with AddPositionModal's structure. Also no `disabled`/pending state while delete is in flight (`page.tsx:834-839`).
**Status: fixed** - role=dialog, aria-modal, Escape-to-close, in-flight delete disabled (with 03-B12)


---

## 3. Optimizations

### 03-O1 â€” P2 â€” equity-research: statements waterfall + duplicate fetch + race
`fetchAllData` awaits the 4-way `Promise.allSettled` **then** fetches statements sequentially (`page.tsx:81-110`) â€” pure waterfall adding RTT before `setLoading(false)`. The second effect (`page.tsx:123-136`) fetches statements again whenever `activeTab === 'financials'` (re-entering the tab refetches identical data) **and** on ticker change while on that tab fires **both** fetches concurrently with no ordering guarantee â€” last responder wins (can show the old ticker's statements). Also fetches statements on first load even though the tab isn't visible.
**Fix:** fetch statements lazily on tab entry only; include a request-id/abort guard.
**Status: fixed** - statements fetched lazily on tab entry only; waterfall/duplicate fetch removed; stmtSeq guard


### 03-O2 â€” P2 â€” equity-research: no request cancellation on rapid ticker changes
`page.tsx:119-121` effect has no cleanup/AbortController â€” three quick searches â†’ three in-flight `fetchAllData`s interleaving `setProfile/setShareholding/setConcalls` (compounds 03-B4). Peer-click spam (`page.tsx:635`) triggers the same.
**Fix:** `AbortController` per effect run, or ignore stale resolution via a sequence counter.
**Status: fixed** - fetchSeq/stmtSeq monotonic counters drop stale resolutions on rapid ticker switches


### 03-O3 â€” P2 â€” equity-research: `getCustomRatios` fetched but never rendered
`page.tsx:57` state, `page.tsx:85,100-102` fetch+set â€” `customRatios` appears **nowhere** in JSX (all ratio UI reads `profile.custom_ratios`). A full endpoint round-trip per search is dead weight.
**Fix:** delete state + promise from `Promise.allSettled` (or actually use its `ratios_history` â€” see I1).
**Status: fixed** - customRatios state + Promise.allSettled entry removed (endpoint was never rendered)


### 03-O4 â€” P2 â€” manage: forecast risk blocks first paint
`fetchPortfolio` `await`s `fetchForecastRisk` (`page.tsx:174`) before its `finally` clears `isLoading` (`page.tsx:179`) â€” GARCH latency extends the full-page spinner (`page.tsx:341-349`) even though the table needs only portfolio data. Forecast columns already have their own `isLoadingForecast` skeleton cells (`page.tsx:678-717`).
**Fix:** don't await â€” fire-and-forget with the existing per-cell loading state.
**Status: fixed** - `void fetchForecastRisk(...)` fire-and-forget; per-cell skeletons keep first paint on portfolio data only


### 03-O5 â€” P2 â€” manage: full refetch (portfolio + forecast) after every mutation
Add/update/delete/inline-save all call `fetchPortfolio()` (`page.tsx:198,214,227`) â†’ refetch positions **and** re-run forecast for all tickers (`page.tsx:174`). Inline edits are single-row; a save shouldn't refit GARCH universe-wide.
**Fix:** optimistic single-row patch with rollback, or refetch portfolio only and mark forecast stale.
**Status: skipped** - optimistic single-row patch with rollback is a state-management refactor; current full-refetch remains correct


### 03-O6 â€” P2 â€” screener: success-feedback `setTimeout` leaks across unmount
`page.tsx:164-166` schedules a 3s state update never cleared on unmount (timer cleanup exists only for the slow-hint timer, `page.tsx:100-104`). Navigating away within 3s â†’ setState-on-unmounted warning/leak.
**Fix:** track the timeout in a ref and clear in the same unmount effect.
**Status: fixed** - addedTimerRef cleared on unmount


### 03-O7 â€” P2 â€” equity-research: Recharts statically imported by a 1116-line page
`page.tsx:28-37` pulls Recharts into the route's initial bundle although the chart renders only under the shareholding tab (`page.tsx:699-769`). `next/dynamic` for the `AreaChart` subtree (tab already conditionally mounts) cuts first-load JS for the default Overview tab.
**Fix:** `dynamic(() => import(...), { ssr: false })` around the chart block.
**Status: skipped** - next/dynamic around the chart subtree requires extracting it to a new module (no new files this pass); recharts already in optimizePackageImports


### 03-O8 â€” P3 â€” screener: `STRATEGY_ICONS` rebuilt every render
`page.tsx:66-72` creates a fresh object of JSX nodes each render â€” trivial but free to hoist to module scope (keys are static).
**Status: fixed** - STRATEGY_ICONS hoisted to module scope


### 03-O9 â€” P3 â€” unused imports (see 03-B34)
equity-research `page.tsx:46,9,23,24,26`; screener `page.tsx:11,17,37` â€” dead identifiers in parse/transform path; delete for lint cleanliness and marginally smaller module graphs.
**Status: fixed** - see 03-B34 (unused imports deleted)


---

## 4. Recommended changes (prioritized, top 10)

1. **03-B1 (P0)** â€” `manage/page.tsx:683-705,110-112`: guard `volatility_forecast`/`var_forecast` with `!= null` before `.toFixed()` â€” null vol from forecast-risk crashes the page today; render N/A per the FabricatedFallbacks contract.
2. **03-B15 (P1)** â€” `settings/page.tsx:42-46,84,146`: five preference controls are placebo and the success banner claims they saved â€” either persist them end-to-end or remove them and make the success copy name only `primary_source`.
3. **03-B2 (P1)** â€” `screener-studio/page.tsx:156-162`: `weight: 0` fails backend `gt=0` validation on every add (broken feature + zero-state 100% invariant) â€” reuse AddPositionModal's weight math (1.0 if empty portfolio) and show `err.message` instead of `alert`.
4. **03-B11 + 03-B22 (P1)** â€” `manage/page.tsx:112-134,102-124`: stop fabricating `risk_level: 'Low'` on error/missing/null; surface the forecast payload's `error`/`is_limited_history` as a banner (pattern proven in FabricatedFallbacks tests).
5. **03-B3 (P1)** â€” `equity-research/page.tsx:91`: replace dead `reason?.response?.data?.detail` with `reason?.message` so backend 503 vendor-outage strings actually reach the error banner (same fix for **03-B18** `pairs/page.tsx:20-21`).
6. **03-B16 + 03-B17 (P1)** â€” `india-flows/page.tsx:17-23,62-63,9-21`: remove per-request `.catch` that converts outages into "No anomalies", gate empty states on `loading`, and either render the fetched `flows` (FII/DII section promised in copy) or delete the claim.
7. **03-B12 + 03-B13 (P1)** â€” `manage/page.tsx:231-234,260-285,835`: delete/edit failures are swallowed (unhandled rejection / console-only) â€” route both through `err.message` in the page error banner (or NotificationSystem) and block inline saves with qty/price â‰¤ 0.
8. **03-B9 + 03-B10 (P1)** â€” `equity-research/page.tsx:412-414,430-437`: dividend heuristic renders 0.4 as 40.00% (and contradicts peer column at :650); Piotroski `|| 0` fabricates 0/9 â€” normalize units server-side and render null â†’ N/A.
9. **03-B14 (P1)** â€” `manage/page.tsx:335`: `en-US` locale violates the en-IN â‚¹ invariant â€” switch to shared `formatCurrency` (`src/lib/utils.ts:23`) or `en-IN` + lakh/crore tiers (also closes **03-I16** formatter duplication).
10. **03-B4 + 03-B5 (P1)** â€” `equity-research/page.tsx:77-117,663`: clear all data states on ticker change and give the shareholding tab an error/empty card â€” currently a failed switch shows the previous company's data and a null shareholding renders a blank tab with no message (bundle with **03-B6/B7** error-taxonomy work, **03-I2**).

*Runners-up (P1):* **03-B7** AI buttons silent no-op, **03-B8** dead `?ticker=` deep link from screener. *Quick wins (P2/P3):* **03-B26** root metadata, **03-B34/O9** unused imports, **03-B27** dead EditPositionModal, **03-O6** timer leak.

---

*Read-only audit confirmed: only `.scratch/frontend-audit/03-tools-pages-c.md` was written. No product code, tests, configs, or other scratch files were modified; no commits made.*
