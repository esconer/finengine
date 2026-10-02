# detail/frontend.md — frontend slice (FE-1..11)

**Writer**: A2 · **Source inventory**: `plans/2026-10-audit/inventory-a2fe-a3infra.md` Part 1
**Scope**: `frontend/src/{app,components,lib,hooks}` — plus the backend schema/DB declarations needed
to name the *actual resolved type* where a claim turns on one (plan §3 condition 5).
**Status**: 10 of 11 items emitted. **1 rejected on re-verification** (FE-2). **0 BLOCKERs** — the
inventory's one BLOCKER-candidate (FE-4) did not survive contact with the backend request schema.

**Method note.** Every `path:line` below was opened by me at write time. Searches for
quote-bearing patterns used `Select-String`; enumerations used `Get-ChildItem -Force -Recurse`
(106 `.ts`/`.tsx` files under `frontend/src`, confirmed against an all-extension count of 108).
**A clean `tsc --noEmit` is not cited against any runtime claim here** — several of these fields
are reached through `any`, or through no `.ts` type file at all, and TypeScript structurally
cannot observe their runtime value.

---

## Ledger rows (descending severity, then confidence)

| # | ID | Class | Sev | Conf | Location |
|---|---|---|---|---|---|
| 1 | FE-1 | bug | DEFECT | VERIFIED | `frontend/src/app/portfolio/manage/page.tsx:786` |
| 2 | FE-4 | bug | DEFECT | VERIFIED | `frontend/src/app/dashboard/screener-studio/page.tsx:177` |
| 3 | FE-5 | bug | DEFECT | VERIFIED | `frontend/src/app/dashboard/pairs/page.tsx:145` |
| 4 | FE-6 | bug | DEFECT | VERIFIED | `frontend/src/components/layout/RealtimeStatus.tsx:41` |
| 5 | FE-7 | bug | RISK | VERIFIED | `frontend/src/lib/store.ts:171` |
| 6 | FE-8 | bug | RISK | VERIFIED | `frontend/src/components/layout/Header.tsx:96` |
| 7 | FE-9 | maintainability | RISK | VERIFIED | `frontend/src/hooks/useRealTime.ts:11` |
| 8 | FE-10 | optimisation | RISK | VERIFIED | `frontend/src/components/layout/Header.tsx:74` |
| 9 | FE-3 | risk | RISK | DERIVED | `frontend/src/components/portfolio/PortfolioStats.tsx:83` |
| 10 | FE-11 | optimisation | NIT | DERIVED | `frontend/src/app/dashboard/volatility-sizing/page.tsx:883` |

Bands: BLOCKER 0 · DEFECT 4 · RISK 5 · NIT 1 · rejected 1.

---

### FE-1 — The unrealized-P/L `%` guard on `/portfolio/manage` is unreachable; the `N/A` branch is dead code

- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `frontend/src/app/portfolio/manage/page.tsx:786` (guard), `:45` (helper), `:200` (producer); rendered from `filteredPositions` built at `:379`/`:209`/`:699`; second consumer `frontend/src/components/portfolio/PortfolioStats.tsx:236`
- **Symptom**: a holding the engine could not cost (`baseCost === 0`) renders a green **`+0.00%`** in the unrealized-P/L column instead of `N/A`, and contributes a fabricated `0.00` to the "Average Gain/Loss" statistic card.
- **Evidence**:
```tsx
// manage/page.tsx:45 — the helper's return type is plain `number`; it cannot yield NaN
const monetaryValue = (base: number | null | undefined, native: number | null | undefined): number => {
    if (typeof base === 'number' && Number.isFinite(base)) return base;
    if (typeof native === 'number' && Number.isFinite(native)) return native;
    return 0;                                   // NaN and undefined BOTH land here
};
// :200 — the unmeasurable case is deliberately BUILT as NaN
unrealized_gain_loss_pct_base: monetaryValue(
    pos.unrealized_gain_loss_pct_base,
    baseCost > 0 ? ((baseCurrent - baseCost) / baseCost) * 100 : NaN),
// :786 — guard is therefore always true; the :788 `N/A` span never renders
{Number.isFinite(monetaryValue(position.unrealized_gain_loss_pct_base, position.unrealized_gain_loss_pct))
    ? `${...}${monetaryValue(...).toFixed(2)}%`
    : <span className="text-gray-500">N/A</span>}
```
- **Mechanism**: (1) `:202` passes `NaN` into `monetaryValue` for a zero-cost holding. (2) `:47-48` — `NaN` fails `Number.isFinite`, so the helper returns the literal `0`, and that `0` is written into `unrealized_gain_loss_pct_base` at `:200`. (3) `:786` re-evaluates `Number.isFinite(0)` → `true` → the `+0.00%` branch wins and `:784`'s `>= 0` comparison paints it green.
- **Impact**: the cell renders `+0.00%` in `text-green-600` for a holding the system could not measure. `PortfolioStats.tsx:92` builds `avgGainLoss` from the same helper and `:236` renders it via `formatPercent` — whose own guard at `:106-110` only catches `null`/`undefined`/non-finite, never a pre-fabricated `0`, so that card also shows `+0.00%`.
- **Suggested fix** (shape, not a patch): stop laundering at the producer. Give `unrealized_gain_loss_pct_base` an honest type (`number | null`) and let it stay `null` when `baseCost <= 0`; then `:786`'s existing `Number.isFinite(...) ? … : 'N/A'` becomes live as written. **Preserve the absence — do not** substitute `0`, `?? 0`, or a `.toFixed()` on a NaN. Blast radius: `manage/page.tsx` (`:200`, `:786`) and `PortfolioStats.tsx:65-68` (`gainLossPct`), plus `:92`/`:143`/`:161`/`:236`. Do **not** "fix" this by re-enabling React Compiler or by memoising — `next.config.ts:5` sets `reactCompiler: false` deliberately.

---

### FE-4 — "Add to portfolio" from the screener fabricates `buy_price: 0`, which the backend rejects as an opaque 422

- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `frontend/src/app/dashboard/screener-studio/page.tsx:177` (fabrication), `:269` (the same file treating `price` as optional), `:406` (ungated button); request schema `backend/app/models/schemas.py:17`; route `backend/app/api/portfolio.py:1135-1137`; message builder `frontend/src/lib/api.ts:65-69`
- **Symptom**: clicking *Add to portfolio* on a screener row whose price the backend could not measure fails, and the error banner names a field the user never typed.
- **Evidence**:
```tsx
// screener-studio/page.tsx:177 — absent price -> 0
      const price = stock.price || 0;
      // Mirror AddPositionModalSimple weight math: first position in an empty
      // portfolio is 1.0 (zero-state invariant); otherwise value/(total+value).
      const portfolio = await portfolioApi.getPortfolio({ currency: 'INR' });
      const posList = portfolio.positions || [];
      const totalValue = portfolio.total_value || 0;
      const positionValue = 1 * price;          // 1 * 0 === 0
      const weight =
        posList.length === 0 || totalValue <= 0
          ? 1.0
          : positionValue / (totalValue + positionValue);
```
```py
# backend/app/models/schemas.py:17 — the POST body schema refuses zero
    buy_price: float = Field(..., gt=0, description="Price per share at time of purchase - must be > 0")
# backend/app/api/portfolio.py:1135-1137 — that schema is the body of the route the app calls
@router.post("/add", response_model=PortfolioPositionResponse)
async def add_position(
    position: PortfolioPositionCreate,
```
- **Mechanism**: (1) `:177` `stock.price || 0` maps an absent price to `0`. (2) `:191` posts `buy_price: 0` to `POST /api/v1/portfolio/add`, whose body model is `PortfolioPositionCreate` → `PortfolioPositionBase.buy_price` with `gt=0`. (3) Pydantic rejects it → HTTP 422 → `buildApiErrorMessage` (`api.ts:65-69`) joins the FastAPI `detail` array into the user's error text.
- **Impact**: the error banner reads **`buy_price: Input should be greater than 0`** — naming a field the user never supplied, for a row whose price cell itself renders `₹undefined` (see `data.price?.toLocaleString(...)` at `:269`). No row is persisted.
- **Suggested fix** (shape, not a patch): make absence survive to the decision — bail out before the POST when the row has no finite price, and disable the button at `:406` on that condition rather than letting the request fail. Blast radius: `screener-studio/page.tsx` only (`:177`, `:191`, `:406`, `:269`). **Do not** "fix" this by widening the backend schema to accept `0`; a zero purchase price is not a real position.
- **Why this is DEFECT and not BLOCKER** — this is where the inventory was wrong, in the *other* direction. The inventory called it "a write… the fabricated zero is persisted and surfaces as wrong total cost, wrong unrealized P/L and wrong risk weight on every dashboard." **That is false**: `buy_price` carries `gt=0` (`schemas.py:17`), so the fabricated zero cannot be persisted. Every downstream corruption the inventory predicted is blocked by the request schema. The defect is the opaque error, not silent corruption.

---

### FE-5 — Pairs page calls `.toFixed()` on a field the backend publishes as `Optional[float] = None`; the throw blanks the whole route

- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `frontend/src/app/dashboard/pairs/page.tsx:145` (the reachable throw), `:137`, `:140`, `:39` (`any[]`), `:142` (the guarded neighbour); schema `backend/app/models/schemas.py:495`; boundary `frontend/src/app/error.tsx:16`
- **Symptom**: when the engine has no current spread for a pair, the Pairs Scanner route does not show one unavailable cell — it renders nothing at all and shows the route-level error screen.
- **Evidence**:
```tsx
// pairs/page.tsx:39 — the response is `any[]`; `p` resolves to `any`, so tsc checks nothing
  const [pairs, setPairs] = useState<any[]>([]);
// :142 — the SAME row guards the adjacent field, which is what makes :145 look like an oversight
                    {p.ou_half_life_days ? `${p.ou_half_life_days.toFixed(1)} days` : 'N/A'}
// :144-145 — the unguarded one
<td className={...}>
    {p.current_spread_zscore.toFixed(2)}σ
</td>
```
```py
# backend/app/models/schemas.py:495 — legitimately absent, default None
    current_spread_zscore: Optional[float] = None
```
- **Mechanism**: (1) the backend omits the field it could not measure and serialises `null` (`schemas.py:495`). (2) `pairs` is `useState<any[]>` at `:39`, so `p.current_spread_zscore` resolves to `any`; `.toFixed(2)` on `null` throws `TypeError`. (3) the throw happens during render of the table, above any per-cell guard, so `app/error.tsx` replaces the **entire route**.
- **Impact**: the user sees the route error boundary — heading `Something went wrong`, body **`Cannot read properties of null (reading 'toFixed')`** (`app/error.tsx:16` renders `error?.message` verbatim) — for a pair scan that had one unmeasured field out of the results. The other pairs, which are fine, are gone with it.
- **Why TypeScript cannot catch this**: `current_spread_zscore` appears in **no** `.ts` type file anywhere under `frontend/src` — a full-tree `Select-String` returns exactly 5 hits, all inside `pairs/page.tsx`, all reached through the `any[]` at `:39`. There is no interface in which the field could be declared optional, so there is nothing for the checker to compare against. A clean `tsc --noEmit` is therefore not evidence against this row.
- **Correction to the inventory**: it claimed *three* unguarded fields. Only **one** is reachable — `engle_granger_pvalue` (`schemas.py:488`) and `hedge_ratio_beta` (`schemas.py:491`) are required `float`, not `Optional`. The finding stands on `:145` alone.
- **Suggested fix** (shape, not a patch): model the coint response with a real interface (`current_spread_zscore: number | null`) instead of `any[]`, and render absence with the `—`/`N/A` convention the rest of the app already uses. **Preserve the absence** — do not `?? 0` and do not `.toFixed()` a possibly-null value. Blast radius: `pairs/page.tsx` (`:39`, `:137`, `:140`, `:145`); a real response type would touch the coint envelope at `:40`.

---

### FE-6 — The live-connection chip has only two states, so it asserts "connecting" forever after the user turns Live off

- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `frontend/src/components/layout/RealtimeStatus.tsx:41` (the lie), `:26-32` (the effect), `:15` (whole-store subscribe); gate `frontend/src/lib/websocket.ts:344`; mounted at `frontend/src/components/layout/DashboardLayout.tsx:116`; default `frontend/src/lib/store.ts:343`
- **Symptom**: after the user switches Live updates **off**, the fixed corner chip keeps claiming it is connecting — indefinitely, because nothing will ever connect.
- **Evidence**:
```tsx
// RealtimeStatus.tsx:26-32 — liveDataMode off: bail out, never connect
  useEffect(() => {
    if (!liveDataMode) {
      setConnected(false);
      return;
    }
    void connect().then(() => setConnected(true)).catch(() => setConnected(false));
  }, [connect, liveDataMode]);
// :41 — two states only; there is no third ("off")
      <span>{statusConnected ? 'Live updates connected' : 'Live updates connecting'}</span>
```
```ts
// lib/websocket.ts:342-350 — with liveDataMode off the client is actively disconnected
  // Auto-connect when liveDataMode is enabled
  useEffect(() => {
    if (liveDataMode) {
      connect().catch(() => {});
    } else {
      disconnect();
    }
```
- **Mechanism**: (1) `store.ts:343` sets `liveDataMode: true`, so the socket connects on mount. (2) the user toggles Live off → `websocket.ts:348-350` calls `disconnect()`, and `RealtimeStatus.tsx:27-30` returns early without connecting. (3) `statusConnected = isConnected || connected` is now permanently `false`, and `:41` has no "off" state to render — so the chip asserts an in-progress connection that can never begin.
- **Impact**: the chip renders **`Live updates connecting`** with its amber `Circle` icon (`RealtimeStatus.tsx:40-41`) for as long as Live mode is off, on every dashboard route (`DashboardLayout.tsx:116`).
- **Suggested fix** (shape, not a patch): give the chip the third state it is missing — render an explicit "off"/"disabled" affordance when `liveDataMode` is false, rather than reusing the `connecting` label for "deliberately not connected". Blast radius: `RealtimeStatus.tsx` (`:24`, `:40-41`). Cosmetic only; no data path depends on it.

---

### FE-7 — The portfolio store launders an absent `total_value` into a measured `0`, at two sites, before any consumer can see it was absent

- **Class**: bug
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `frontend/src/lib/store.ts:171` (`fetchPortfolio`), `:204` (`setPortfolioSnapshot`), seeded `:158`; declared type `:69` `totalValue: number`; hardened-but-unreachable consumer `frontend/src/app/dashboard/page.tsx:160-162`, dead `?? 'N/A'` at `:423`
- **Symptom**: when the payload carries no `total_value`, every consumer of the store — including the one that explicitly tried to guard for it — sees a confident measured zero rather than "not measured".
- **Evidence**:
```ts
// lib/store.ts:169-174  (fetchPortfolio)     — NaN || 0 === 0
                        set({
                            positions: data.positions || [],
                            totalValue: data.total_value || 0,
                            totalWeight: data.total_weight || 0,
                            positionCount: data.total_positions ?? data.positions?.length ?? 0,
                            isLoading: false,
                        });
// lib/store.ts:202-205  (setPortfolioSnapshot) — the identical fabrication, second site
                    set({
                        positions: snapshot.positions || [],
                        totalValue: snapshot.total_value || 0,
```
```tsx
// app/dashboard/page.tsx:156-162 — written to catch exactly this, and unreachable because of it
    // The store types totalValue as `number` and seeds it to 0, so a zero here is
    // a MEASURED zero (an empty book really is worth ₹0) and is kept as one. What
    // must not happen is a non-finite total being laundered into 0 by `|| 0`:
    // NaN || 0 is 0, which turns a broken payload into a confident ₹0.00.
    const measuredTotalValue = typeof totalValue === 'number' && Number.isFinite(totalValue)
      ? totalValue
      : null;
```
- **Mechanism**: (1) a payload whose `total_value` is absent or `NaN` reaches `store.ts:171` (or `:204`). (2) `|| 0` converts both cases to `0` — and `0` is indistinguishable from a genuinely empty book, which is also `0` by design (`store.ts:158`). (3) the declared type is `number` (`:69`), so `dashboard/page.tsx:160`'s `Number.isFinite` check is *always* true and `measuredTotalValue` is never `null` — the guard's own comment describes a failure it structurally cannot detect.
- **Impact**: `dashboard/page.tsx:423` renders `{portfolioMetrics.totalValue ?? 'N/A'}`; because `portfolioMetrics.totalValue` can never be `null`, that `?? 'N/A'` is **dead**, and the metric card shows `₹0.00` for a book whose value was never measured. The same laundering at `:171`/`:204` feeds `totalValue` to every whole-store subscriber, including `Header.tsx:75`.
- **Why TypeScript cannot catch this**: `total_value`'s absence is a runtime property of a JSON payload; the store's own field is declared `totalValue: number` (`store.ts:69`) and is seeded to `0`. There is no `null` in the type for the checker to require.
- **Suggested fix** (shape, not a patch): let the store carry `totalValue: number | null` and stop substituting `0` at the boundary; distinguish "measured zero" (empty book) from "not measured" explicitly rather than by value. That single change revives three already-written guards (`dashboard/page.tsx:160`, `:423`; and the `measuredTotalValue === null` branches at `:168-169`) at zero display cost. Blast radius: `store.ts:69`, `:158`, `:171`, `:204`, plus the read sites enumerated above (`dashboard/page.tsx:57,160-184,270-271,423`; `Header.tsx:75`). **Preserve the absence — `?? 0` here is the defect, not the fix.**

---

### FE-8 — Header's PDF export total silently drops every holding with no measured value

- **Class**: bug
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `frontend/src/components/layout/Header.tsx:96` (fabrication), `:111` (payload), `:29`/`:36` (the scrupulous sibling paths), `:99-102` (the stated principle); sink `frontend/src/lib/export.ts:1017`; nullable fields `frontend/src/types/index.ts:30`
- **Symptom**: the exported portfolio-review PDF prints a *Total Portfolio Value* that is lower than the sum of its own holdings table, with no indication that any row was excluded.
- **Evidence**:
```tsx
// Header.tsx:95-98 — the exception
      const totalVal = positions.reduce(
        (sum, p) => sum + (p.market_value_base ?? p.market_value ?? 0),
        0
      );
// :99-102 — the rule the same file states two lines later, and obeys elsewhere
      // Fetched here, not read from the store: the three analytics routes are
      // the only source for the figures the review quotes, and the store
      // carries holdings only. A route that fails leaves its block absent and
      // the document drops that section's sentences.
```
```ts
// lib/export.ts:1017 — where the fabricated total is printed
  write(`Total Portfolio Value: ${money(portfolioData.totalValue)}`, margin, y);
```
- **Mechanism**: (1) `market_value_base` is declared `number | null` (`types/index.ts:30`) and `market_value` likewise, so a holding the engine could not measure yields `null` for both. (2) `?? 0` at `Header.tsx:96` folds that holding into the sum as a real zero. (3) `totalVal` is passed at `:111` and printed verbatim at `export.ts:1017` as the document's headline figure.
- **Impact**: the PDF prints `Total Portfolio Value: ₹<sum of measured holdings only>` while its own holdings table lists rows that carry no measured value — a document that is internally inconsistent and reads as complete. The same file's own stated standard (`:102`: *"a PDF that silently drops its risk section is recoverable, one that invents it is not"*) is violated by this one total.
- **Suggested fix** (shape, not a patch): compute the total over measured holdings and publish the excluded count alongside it (or mark the total as partial) — mirroring what `hooks/useAnalytics.ts:338-340` already does for sectors. **Do not** fix it by removing the `??` without replacing the semantics: absence must stay visible, not become zero. Blast radius: `Header.tsx:95-98`, `:111`; the `PortfolioData` shape at `export.ts:946` if the count field is added.

---

### FE-9 — ~500 lines of unreachable code, including the app's only HTTP interval and its only `/health` request

- **Class**: maintainability
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `frontend/src/hooks/useRealTime.ts:11` (`useAutoRefresh`), `:338`, `:439`, `:501`; `frontend/src/components/ui/NotificationSystem.tsx:94`, `:128`, `:169`, `:217`; `frontend/src/lib/api.ts:927`; `frontend/src/lib/store.ts:474`
- **Symptom**: none user-visible today. The defect is that the codebase's most plausible-looking poller and its only health probe are both unreachable, so the next auditor (or the next developer) will read them as live.
- **Evidence**:
```ts
// hooks/useRealTime.ts:11 — the app's ONLY setInterval that issues HTTP. Zero callers.
export function useAutoRefresh(enabled: boolean = true, interval: number = 300000) {
// :72 — the interval itself
        intervalRef.current = setInterval(performRefresh, interval);
// lib/api.ts:926-929 — the ONLY /health request in the repo. Zero callers.
export const healthApi = {
  check: async () => {
    const response = await apiClient.get('/health');
```
- **Verified zero-caller inventory** (each confirmed by tree-wide `Select-String` under `frontend/src`, where the only hit is the declaration itself):

| Symbol | Declaration | Hits under `frontend/src` |
|---|---|---|
| `useAutoRefresh` | `useRealTime.ts:11` | 1 (decl only) |
| `useExportProgress` | `useRealTime.ts:338` | 1 (decl only) |
| `useDashboardPreferences` | `useRealTime.ts:439` | 1 decl + 1 prose mention at `store.ts:336` |
| `useDateRangeSelection` | `useRealTime.ts:501` | 1 (decl only) |
| `ExportProgressIndicator` | `NotificationSystem.tsx:94` | 1 (decl only) |
| `ConnectionStatus` | `NotificationSystem.tsx:128` | 1 decl + 1 unrelated `connectionStatus` string at `useRealTime.ts:186` |
| `LiveUpdateIndicator` | `NotificationSystem.tsx:169` | 1 (decl only) |
| `RefreshButton` | `NotificationSystem.tsx:217` | 1 (decl only) |
| `healthApi.check` | `api.ts:927` | 1 (decl only) |
| `dataApi.{getStockData,getBatchStockData,validateTicker}` | `api.ts:559,575,586` | 1 each |
| `dataApi.refreshData` | `api.ts:592` | 0 (`dataApi.refreshData` compound: 0) |
| `portfolioApi.{getPosition,normalizeWeights}` | `api.ts:466,496` | 1 each |
| `companyDataApi.{getFundamentals,getInsiderTransactions}` | `api.ts:634,652` | 1 each |
| `equityResearchApi.getAiDossier` | `api.ts:884` | 1 (decl only) |
| `store.useCSVExport` / `convertToCSV` / `downloadCSV` | `store.ts:474,490,504` | 1 / 2 / 2 (internal only) |

- **The tell that matters**: `NotificationSystem.tsx` is *not* a dead file — `DashboardLayout.tsx:12` imports `NotificationContainer` from it. Four of its exports are dead, and two of them (`ConnectionStatus` at `:128`, `LiveUpdateIndicator` at `:169`) call `useEnhancedRealTimeAnalytics()` (`NotificationSystem.tsx:129`, `:170`), which opens its own `WebSocketClient`. Anyone re-mounting either "to fix something" silently doubles the socket count against a backend that already gates websockets (`backend/app/api/websocket.py:520-521`).
- **Impact**: developer-facing, no user-visible effect — which caps this at RISK. Concrete future cost: `useAutoRefresh` is the first thing the next reader greps for when investigating request volume, and it is dead. Deleting it removes the only HTTP `setInterval` in the tree; keeping it preserves a trap.
- **Suggested fix** (shape, not a patch): delete the confirmed-zero-caller exports and the API methods with no callers, or move them behind an explicit `experimental` boundary. Blast radius: 8 exported symbols across 4 files; `store.ts:490`/`:504` are module-private and can go with `useCSVExport`. Do **not** keep `useAutoRefresh` as "the poller" in a comment — that is the specific belief this row exists to remove.

---

### FE-10 — Three components subscribe to an entire Zustand store rather than a slice

- **Class**: optimisation
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `frontend/src/components/layout/Header.tsx:74` (portfolio store), `frontend/src/lib/websocket.ts:283` (UI store, in the `useWebSocket` hook), `frontend/src/components/layout/RealtimeStatus.tsx:15` (UI store); toggle sites `frontend/src/lib/store.ts:366`; mounted at `DashboardLayout.tsx:116`
- **Symptom**: any write to either store re-renders the header, the socket hook, and the connection chip — including writes that touch none of the fields they read.
- **Evidence**:
```tsx
// Header.tsx:74 — whole-store selector; only 4 fields are destructured at :75
  const portfolioState = usePortfolioStore((state) => state);
  const { positions, positionCount, fetchPortfolio, isLoading } = portfolioState;
```
```ts
// lib/websocket.ts:282-285 — the worse of the two: `useWebSocket` is a hook, mounted on every dashboard route
  const uiState = typeof store.useUIStore === 'function'
    ? store.useUIStore((state: any) => state)
    : undefined;
  const liveDataMode = Boolean(uiState?.liveDataMode);
// RealtimeStatus.tsx:14-16 — the same shape, one component deeper
  const uiState = typeof store.useUIStore === 'function'
    ? store.useUIStore((state: any) => state)
    : undefined;
```
- **Cited cost** (call-site count and re-render trigger, both counted, not estimated): **3** whole-store selectors. `useUIStore` writes `lastUpdated` on every successful portfolio fetch (`store.ts:366`, reached from both `fetchPortfolio` at `:176` and `setPortfolioSnapshot` at `:209`) plus `darkMode` (`:341`) and `liveDataMode` (`:362`); `usePortfolioStore` toggles `isLoading` **twice per fetch** (`store.ts:166` and `:174`). Zustand's `set` produces a new top-level state object, so a `(state) => state` selector yields a fresh reference on every one of those writes and fails `Object.is` each time — the subscribers re-render regardless of which field moved.
- **Impact**: re-rendering `Header` (which owns the PDF export path) and `RealtimeStatus` on every `lastUpdated` tick, and re-rendering the hook that owns the WebSocket lifecycle, for a value (`liveDataMode`) that changes only on an explicit user toggle. Developer- and latency-facing; no incorrect output.
- **Suggested fix** (shape, not a patch): select individual fields (`usePortfolioStore((s) => s.positions)` etc.) or a single `useShallow` comparison. Blast radius: 3 call sites; `websocket.ts:283` and `RealtimeStatus.tsx:15` are both inside the `typeof store.useUIStore === 'function'` defensive branch, so the change must preserve that guard's shape.

---

### FE-3 — `PortfolioStats` calls `.toFixed(1)` on an unguarded largest-position weight

- **Class**: risk
- **Severity**: RISK
- **Confidence**: DERIVED
- **Location**: `frontend/src/components/portfolio/PortfolioStats.tsx:83` (computation), `:194` (render); guarded sibling `:179`; empty-array guard `:112`/`:34`; type `frontend/src/types/index.ts:5`; schema `backend/app/models/schemas.py:87`; column `backend/app/models/database.py:32`
- **Symptom**: a holding whose weight is not a finite number turns the whole "Largest Position" card into `NaN%` — `Math.max` propagates a single bad value across every other holding, so one bad row blanks the card rather than one row.
- **Evidence**:
```tsx
// PortfolioStats.tsx:82-83 — unguarded, and Math.max propagates
    // Portfolio concentration (largest position weight)
    const portfolioConcentration = Math.max(...positions.map(pos => pos.weight * 100));
// :193-194 — unguarded render, in a card the file otherwise formats safely
              <p className="text-lg font-semibold text-purple-900 dark:text-purple-100">
                {stats.portfolioConcentration.toFixed(1)}%
              </p>
// :106-110 — the safe formatter this card has and does not use for this value
  const formatPercent = (value: number | null | undefined) => {
    if (value == null || !Number.isFinite(value)) return '—';
```
- **Mechanism**: (1) `pos.weight * 100` evaluates to `NaN` for any non-finite `weight`. (2) `Math.max` with a `NaN` argument returns `NaN` for the whole array, discarding every other holding's weight. (3) `:194` calls `.toFixed(1)` on that `NaN`, and `(NaN).toFixed(1)` is the literal string `"NaN"`.
- **Impact**: the card renders **`NaN%`** under the heading `Largest Position`, with the sub-label `Concentration Risk` still attached.
- **Actual resolved type, and why the inventory's trigger is wrong**: `PortfolioPosition.weight` is declared `weight: number` (`types/index.ts:5`) — **required and non-nullable**. It is `weight: float` (required) in `PortfolioPositionResponse` (`schemas.py:87`) and `Column(Float, nullable=False)` with `CheckConstraint("weight >= 0 AND weight <= 1")` (`database.py:32`, `:52`) in the database. The data reaching `PortfolioStats` is `data.positions.map((pos) => ({ ...pos, ... }))` (`manage/page.tsx:182-206`, rendered at `:629-632`), so `weight` passes through verbatim. **On the audited path there is no absent weight**, and the empty case is already handled by the `positions.length === 0` early return at `:112`/`:34`, so `Math.max` never sees an empty array either. This is why confidence is DERIVED and not VERIFIED: the construct is present verbatim, but firing it requires a payload that violates the declared contract in all three layers.
- **Why TypeScript cannot catch it**: the field's resolved type is a non-optional `number`, so there is no `null`/`undefined` case in the type for the checker to demand a guard on. The `tsc --noEmit` clean baseline is not evidence against this row — the checker has nothing to complain about precisely because the type lies about the runtime.
- **The tell**: the sibling card at `:179` is *not* at risk only because of the `:112` guard, which makes the file read as protected end-to-end. This one value is not.
- **Suggested fix** (shape, not a patch): route `portfolioConcentration` through the `formatPercent` helper already defined at `:106`, or pre-filter the `Math.max` input to finite weights — the same `typeof x === 'number' && Number.isFinite(x)` shape used at `dashboard/page.tsx:160` and `useAnalytics.ts:339`. **Preserve the absence**: render `—` for an unweighted book, never `0%` (a single-holding portfolio must read `0%` only because its weight is *measured* at `1.0`, never as a fallback). Blast radius: `PortfolioStats.tsx:83` and `:194` only.

---

### FE-11 — Volatility-sizing rebuilds its table column model on every render, unlike its sibling page

- **Class**: optimisation
- **Severity**: NIT
- **Confidence**: DERIVED
- **Location**: `frontend/src/app/dashboard/volatility-sizing/page.tsx:883` (unmemoized); contrast `frontend/src/app/dashboard/page.tsx:249` (memoized); sink `frontend/src/components/ui/DataTable.tsx:70`
- **Symptom**: none visible. The column model for the largest table on the largest dashboard page is reconstructed on every render of that page.
- **Evidence**:
```tsx
// volatility-sizing/page.tsx:882-884 — plain array literal, rebuilt per render
  // Position sizing table columns
  const positionColumns: DataTableColumn<PositionSizing>[] = [
    {
// dashboard/page.tsx:248-249 — the equivalent, wrapped
  // DataTable columns with enhanced functionality
  const positionColumns = useMemo<DataTableColumn<PortfolioPosition>[]>(() => [
```
```tsx
// components/ui/DataTable.tsx:67-70 — `columns` goes straight into the table model, unstabilised
  const table = useTable({
    features: dataTableFeatures,
    data,
    columns,
```
- **Cited cost** (call-site count, counted): `DataTable` has **9** consuming dashboard pages — `dashboard`, `concentration`, `factor-exposure`, `forecast-risk`, `liquidity`, `realized-risk`, `screener-studio`, `stress-testing`, `volatility-sizing`. Exactly one of the nine (`dashboard`, `page.tsx:249`) memoises its columns; this one does not. The rebuild happens once per render of a page that already carries model-selection, sort, filter and export state.
- **Impact**: extra work per render on one route; no incorrect output. NIT is the ceiling here because the cost is a call-site count and a render-frequency argument, not a measurement — I did not run the app, so I cannot state a render rate or a byte saving.
- **Suggested fix** (shape, not a patch): wrap the array in `useMemo` exactly as `dashboard/page.tsx:249` does, with the page's state dependencies in the dep list. Blast radius: one declaration in one file. **Explicitly out of scope**: do **not** reach for React Compiler — `next.config.ts:5` sets `reactCompiler: false` deliberately, and the 57 hand-written memo sites across this app are load-bearing under that setting.

---

## Rejected on re-verification

### FE-2 — REJECTED in full: the copula tail-dependence matrix cannot render a fabricated `1.000`/`0.000`

The inventory marked this "suspected (fires when `tickers.length > matrix[r].length` or a cell is null; **backend payload not seen**)". I read the backend. **The claimed condition is unreachable, and the symptom cannot occur.**

The claimed evidence *is* present verbatim — `risk-studio/page.tsx:621` (`copulaMatrix[rowIdx]?.[colIdx] ?? (rowIdx === colIdx ? 1.0 : 0.0)`, feeding the green `bg-emerald-500/10` band at `:627`) and `:377` (the same fallback in the CSV writer). But both fallbacks are dead:

1. **The matrix is always dense and square.** `backend/app/services/tail_risk_service.py:552` allocates `matrix = np.eye(n, dtype=float)`, and `:571-583` fills every off-diagonal cell unconditionally in a full `i < j` double loop (`matrix[i, j] = lambda_l; matrix[j, i] = lambda_l`). `:611` serialises it as `[[round(float(matrix[r, c]), 4) …]]` for all `r, c` in `range(n)`. No row can be short and no cell can be missing.
2. **`??` only fires on `null`/`undefined`**, and `float()`/`round()` on a numpy cell always yields a float — the function has no `None` return path.
3. **The tickers and the matrix come from the same dict.** `backend/app/api/analytics.py:12549` and `:12551` publish `tail_dependence_matrix` and the legacy top-level `tickers` from the *same* `tail_copula_matrix` object, under the comment *"Keep the legacy top-level list aligned with the matrix it describes."* The frontend's two fallback branches (`risk-studio/page.tsx:325-326`, `:330-331`) therefore cannot produce a ticker list and a matrix from different sources.
4. **The empty case is guarded.** `risk-studio/page.tsx:605` gates the whole table on `copulaTickers.length > 0 && copulaMatrix.length > 0`, so a failed `/tails` fetch shows no table rather than an all-zeros one.

A `NaN` cell would also not produce the claimed output: `NaN ?? x` is `NaN` (the `??` operator does not catch `NaN`), and a bare `NaN` literal in the JSON body is rejected by the browser's `JSON.parse` before the table ever renders.

**Verdict: no defect.** The `?? (rowIdx === colIdx ? 1.0 : 0.0)` at `:621`/`:377` is defensive dead code, not a live fabrication. If the ledger wants a row here, the honest one is a maintainability NIT about unreachable fallbacks — and since the plan's evidence floor (§3) is about wrong outcomes and this has none, it is dropped rather than quarantined. **FE-2 emits no ledger row.**

### Sub-claims rejected while their parent row survived

- **FE-6, "socket URL has a doubled segment" — REJECTED.** `frontend/src/lib/websocket.ts:60` builds `` `${protocol}//${urlHost}/api/v1/ws/ws/${this._clientId}` `` and the inventory read the second `ws` as a typo. It is correct: the router is mounted at `prefix="/api/v1/ws"` (`backend/main.py:159-163`) and the route inside it is `@router.websocket("/ws/{client_id}")` (`backend/app/api/websocket.py:515`). Prefix + route = `/api/v1/ws/ws/{client_id}` — exactly what the client builds. The inventory flagged this "suspected (backend route outside the frontend agent's area)" and the caveat was correct: the check had to cross into the backend. No defect; FE-6 is emitted on the chip's missing third state only. (The supporting observation that `test/unit/websocket.test.ts` asserts the client id via `toContain` at `:73`/`:93` and never the path shape does hold — it is a coverage note, not a defect, and is not emitted.)
- **FE-4, "the fabricated zero is persisted" — REJECTED.** See the row above. `buy_price` carries `gt=0` (`backend/app/models/schemas.py:17`) and the route body is `PortfolioPositionCreate` (`backend/app/api/portfolio.py:1135-1137`), so the write is rejected with a 422. Severity dropped from the inventory's implicit BLOCKER to DEFECT.
- **FE-5, "three unguarded fields" — REJECTED as to count.** `engle_granger_pvalue` (`schemas.py:488`) and `hedge_ratio_beta` (`schemas.py:491`) are required `float`. Only `current_spread_zscore` (`schemas.py:495`) is `Optional[float] = None`. The row survives on one field.
- **FE-3, "when a holding lacks a weight" — REJECTED as to trigger.** `weight` is `nullable=False` in the DB (`database.py:32`) with a CHECK constraint (`:52`), required `float` in the response schema (`schemas.py:87`), and required `number` in TypeScript (`types/index.ts:5`). There is no absent weight on the audited path. The row is emitted at reduced severity and confidence as an unguarded-propagation risk, with the trigger explicitly disclaimed above.

---

## Settled: the /v1/models + /health request flood

**Verdict: RULED OUT as a frontend cause. The caller remains unidentified and lives outside the audited directories.** This is settled for `frontend/src/{app,components,lib,hooks}` and is not re-litigated by this slice.

Evidence, all re-checked by me this run:

| Claim | Command / check | Result |
|---|---|---|
| No `v1/models` anywhere under `frontend/src` | `Select-String` (not `rg`) over all 106 `.ts`/`.tsx` files | **0 hits.** Control `v1/analytics` → 1 hit (`test/components/MarginalImpactPanel.test.tsx:6`), so the search is live. |
| `healthApi.check` is never issued | `Select-String -Pattern 'healthApi'` | **1 hit — its own declaration** at `frontend/src/lib/api.ts:927`. Zero callers. |
| The only HTTP `setInterval` is dead | `Select-String -Pattern 'setInterval'` → 3 sites; `-Pattern 'useAutoRefresh'` → 1 hit | `useRealTime.ts:72` is the only interval that issues HTTP, and `useAutoRefresh` (`useRealTime.ts:11`) has **zero callers**. |
| All three live timers are non-HTTP | read of each site | `useRealTime.ts:153` — 30 s freshness clock, pure `Date` arithmetic, cleared at `:154`. `websocket.ts:192` — 30 s WS `ping` frame. `websocket.ts:196` — 60 s heartbeat `setTimeout`. Both WS timers cleared together in `stopHeartbeat` (`:204-213`). |
| Every HTTP path is `/api/v1/*` | `api.ts` read end to end | Consistent; `/health` at `api.ts:929` is the sole exception and is unreachable. |

**The three live timers, all verified with cleanups:** freshness clock `useRealTime.ts:153` → cleanup `:154`; WS ping `websocket.ts:192` and heartbeat timeout `websocket.ts:196` → both cleared by `stopHeartbeat` at `:204-213`. **No live timer in this frontend issues HTTP.**

**Where that leaves it.** If paired `/health` + `/v1/models` lines are still being produced, the caller is **outside** `frontend/src/{app,components,lib,hooks}` — this writer's entire scope, and outside this writer's lane. The most likely shape is an OpenAI-compatible SDK probing an LLM server, consistent with `/v1/models` sitting on the backend origin with no `/api` prefix while every application path carries `/api/v1`. **This writer did not attempt to identify it, and no frontend fix should be proposed on its behalf.** Any further search must start from a directory other than `frontend/src`.

---

## Hardened and correct — do not re-report

Carried forward so the next audit inherits it rather than re-deriving it. **I spot-verified three of these personally and they hold as described** (marked ✓); the remainder is passed forward from the inventory as-is.

- ✓ `frontend/src/lib/utils.ts:120-131` — `formatIndianRupees` opens with `if (value === null || value === undefined || Number.isNaN(value)) return 'N/A';`. The guard is real and is the app's canonical absence formatter.
- ✓ `frontend/src/lib/export.ts:1082` — `weight === null ? '—' : \`${(weight * 100).toFixed(1)}%\``, with the adjacent comment explaining that a sector-less holding is `—`, not "General". Correct absence handling; note this is the *same document* whose headline total FE-8 reports as unprotected.
- ✓ `frontend/src/hooks/useAnalytics.ts:336-340` — filters to `typeof p.market_value === 'number' && Number.isFinite(p.market_value)` before computing sector shares, with the comment *"a holding with no measured market value publishes none — it is dropped from the book, not counted as worthless."* This is the correct pattern FE-8 should adopt.
- `frontend/src/app/dashboard/page.tsx:129-222` — the hardened metric block. **Read this before filing anything against `portfolioMetrics`**: `:156-162` already documents the `NaN || 0` hazard in its own comment, and `:423`'s `?? 'N/A'` is correct-in-intent. Its one genuine defect is upstream (FE-7), not here.
- `frontend/src/app/dashboard/concentration/page.tsx:686-688,716`
- `frontend/src/app/dashboard/volatility-sizing/page.tsx:1057-1074`
- `frontend/src/components/portfolio/MarginalImpactPanel.tsx`
- `frontend/src/app/dashboard/risk-contribution/page.tsx:338,352`
- `frontend/src/app/dashboard/risk-studio/page.tsx:361-369`
- `frontend/src/components/ui/MetricCard.tsx`

**Sweep context for future writers**: the `|| 0` / `?? 0` sweep across `frontend/src` returns 75 hits, of which roughly 55 are comments *documenting already-fixed* fabrications rather than live code. Do not read the raw hit count as a defect count — several of the comments above are the reason those specific bugs are gone. **Note the corollary this run produced: FE-7 shows a guard can be present, correct, and still unreachable because the fabrication happens upstream in the store.**

---

## Adjacent observations (NOT emitted — outside this slice or outside the claimed scope)

Recorded for the assembler, deliberately not turned into rows:

- `frontend/src/lib/store.ts:206` — `positionCount: snapshot.positions.length` sits two lines below `positions: snapshot.positions || []` (`:203`). If `snapshot.positions` is absent, `:203` substitutes `[]` and `:206` then throws on `undefined.length`. Different mechanism from FE-7, not claimed by any inventory item, and touching it would be a drive-by.
- `frontend/src/app/dashboard/risk-studio/page.tsx:621`/`:377` — the unreachable fallbacks are real dead code. Noted under the FE-2 rejection; not emitted separately because there is no wrong outcome to report.
- Bundle weight (`recharts` as largest eager dep; the 715.6 KB export chunk claimed to be pulled by 0 of 24 prerendered routes) was **not** re-measured — that needs a build, which is out of bounds for this writer. Carried as unverified.

## Uncertainty

- **Nothing was executed.** No `next build`, no `vitest`, no browser. Every row is source-verified; none is measured. The `|| 0`/`?? 0` sweep counts and the "9 `DataTable` consumers" count were computed by search, not observed at runtime.
- **FE-3 and FE-11 are DERIVED and would benefit from a runtime run** — FE-3 needs a payload violating three schema layers, FE-11 needs a render-rate measurement. Both are emitted at severity ceilings that assume no measurement.
- **`tsc --noEmit` exit 0 was taken from the inventory baseline, not re-run.** It is cited in this document only as an argument for *why a claim is not checkable*, never as evidence against a runtime claim.
- **Cross-boundary reads I performed** (all read-only, all inside the type-naming requirement of plan §3 condition 5, none modified): `backend/app/models/schemas.py`, `backend/app/models/database.py`, `backend/app/api/portfolio.py`, `backend/app/services/tail_risk_service.py`, `backend/app/api/analytics.py`, `backend/main.py`, `backend/app/api/websocket.py`. Two sibling writers own those files; if any of them reach a different conclusion on `buy_price` validation, **FE-4's severity is the row that moves** — it is the only frontend row whose severity depends on a backend contract.