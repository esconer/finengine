# FinEngine UX 06 — Phased Revamp Plan

**Status:** Wave-1 implementation plan; documentation only  
**Scope:** Frontend revamp for the current cash-equity product  
**Constraint:** Use the installed stack; add no dependency unless a later implementation proves it unavoidable and documents why

## 1. Outcome and sequencing principle

The revamp should make the existing product **more trustworthy before it makes it more decorative**. The first deliverable is a coherent shell, semantic visual vocabulary, honest data states, and a usable portfolio workflow. Existing route URLs remain stable. Backend gaps are disclosed in the UI rather than filled with client-side fiction.

The order is deliberate:

1. Establish shared contracts, tokens, and state semantics.
2. Make navigation and the portfolio operations coherent.
3. Standardize analytics tables/charts without changing route meaning.
4. Make research and market tools consistent with the same rules.
5. Harden accessibility, performance, and regression coverage.

A phase may ship with unavailable panels when the backend is unavailable or a capability is absent. It must not ship with invented values to make the layout look complete.

### Effort scale

- **S:** narrow, local change with a clear contract and limited files.
- **M:** cross-file but bounded migration; several call sites and regression tests.
- **L:** broad route/component migration with data-contract and visual regression risk.

## 2. Non-negotiable implementation rules

1. Preserve `/dashboard`, `/portfolio/manage`, and every current route listed in `02-page-maps.md`; add navigation metadata before adding routes.
2. `null` → `N/A`/`—`, never `0`, a safe score, or a risk verdict. Keep the backend's `error`, `model_fitted`, and `is_limited_history` flags visible.
3. Use one source of truth for navigation metadata, one format module, one chart palette, and one typed error surface.
4. Use `row.original || row` in every TanStack cell renderer. Read matrix responses as `{ tickers, matrix }` and index `matrix[i][j]`.
5. Keep INR formatting en-IN with ₹/Cr/L. Do not implement a symbol-only currency toggle.
6. Show only charts and metrics supported by the response. No synthetic frontier, pseudo-confidence interval, zero-filled cone, fake active feed, or fabricated scenario.
7. Treat current NSE tables as stored records, not a verified live official ingestion path.
8. Do not add a candidate/add-ticker impact route, news, estimates, TE/IR, transaction-derived performance, saved screens, or watchlists until the backend contracts are shipped.

## 3. Component migration map

The map is an implementation inventory, not permission to delete working behavior. Confirm callers and run regression tests before removing a component or export.

### 3.1 Keep

| Component/capability | Decision | Why it stays |
|---|---|---|
| Next.js App Router and route files | Keep | Existing URLs, layouts, and route-level code splitting are sufficient |
| React 19 | Keep | Current runtime and installed capability |
| Tailwind CSS 4 | Keep | Can express the restrained token system without a new styling dependency |
| Geist Sans / Geist Mono | Keep | Already configured; the problem is the global Arial override, not the fonts |
| Lucide React | Keep | Existing icon set covers navigation and controls |
| Recharts | Keep | Existing chart engine; standardize its inputs and tokens rather than replacing it |
| Radix Dialog | Keep and standardize | Existing primitive supplies focus trap, Escape, and dialog semantics |
| TanStack Table | Keep and standardize | Existing dense-table foundation; fix accessors, sorting, and null states |
| Zustand | Keep for client/UI state | Appropriate for sidebar/theme/local interaction; not a server-data cache |
| Axios typed client | Keep | Existing API boundary; improve error/status contract rather than adding a second client |
| `@tanstack/react-query` | Keep available; adopt selectively | It is already installed and can eventually own server reads/cancellation/invalidation, but it is not a prerequisite for the visual shell |
| `LoadingState`, `NotificationSystem`, `ExportPanel` | Keep and harden | Existing primitives already cover useful behavior; replace their ad-hoc call sites |
| Existing CSV/Excel/PDF libraries | Keep | Current exports satisfy the first revamp; no new renderer is needed |

### 3.2 Replace

| Current surface | Replace with | Reason |
|---|---|---|
| Two global variables and Arial body styling in `app/globals.css` | Semantic CSS variable layer mapped through Tailwind `@theme` | One theme contract for surface/text/border/accent/status/data tokens |
| Repeated `bg-white dark:bg-gray-800 rounded-lg shadow-md` shells | Shared `Card`/`Panel` and `cardCN` shell | Prevents light/dark and spacing drift |
| Page-local hex palettes | `chart-theme.ts` semantic series tokens | One color-blind-safe palette and stable series identity |
| `MetricCard` with ambiguous string/prefix/delta behavior | `MetricCard` v2 with `value: number|string|null`, `unit`, `asOf`, `quality`, and finite signed delta | Stops NaN, placeholder deltas, US-dollar defaults, and unsafe sign prefixes |
| `RiskMetricsDisplay` default data | Null-preserving metric display and `PanelState` | Missing risk must not become 0% VaR or “Low Risk” |
| `DataTable`/page-specific tables | Shared `DataTable` contract with explicit `row.original || row`, accessible sorting, and state rows | Makes dense quant tables consistent and keyboard-safe |
| `PortfolioTable` copy-pasted formatting/actions | Shared table primitives plus portfolio-specific columns | Keeps ticker/weight/money semantics in one place |
| Local `formatCurrency`, `formatPercentage`, and `toLocaleString` copies | `lib/format.ts` with explicit unit functions | Fixes en-IN and fraction-vs-percent ambiguity once |
| Hand-rolled modal implementations in portfolio/research pages | Existing Radix `ui/dialog.tsx` wrappers | Focus management and keyboard behavior should not be reimplemented per page |
| Page-local `HelpExplainerModal`/`HelpBtn` variants | Shared `ExplainerDialog` plus page content map | Removes a11y and copy drift across risk routes |
| Inline Recharts JSX and bespoke axis/tooltip styles | `ChartFrame`, shared axes/legend/tooltip, and focused chart modules | Makes null/empty/loading behavior consistent without replacing Recharts |
| Raw `fetch` calls and origin-specific export paths | Typed functions in `lib/api.ts` with one response/error contract | Prevents proxy/origin drift and preserves FastAPI detail |
| Page-local `loading/error/empty` branches | `PanelState`/`ErrorState`/`EmptyState` patterns | Prevents “error rendered as clean empty” and silent console-only failures |
| Settings controls that only change local state | Real backend settings only, or explicit read-only notes | A success banner must describe what was actually persisted |
| Synthetic chart points and hardcoded “live” indicators | Honest empty/unavailable states | A plausible chart is worse than no chart when the data is not present |

### 3.3 Delete after caller audit

| Candidate | Deletion condition | Reason |
|---|---|---|
| `useDashboardPreferences` duplicate store | Confirm zero production callers and migrate any real UI state to `UIStore` | Two sources of truth for theme/currency already exist |
| `useCSVExport`/`convertToCSV` | Confirm zero production callers after all exports route through the shared writer | Dead and historically unsafe duplicate path |
| Phantom `CurrencyContextType`/exchange-rate declarations | If no real conversion implementation is introduced | A type that promises FX without a source creates misleading UI |
| Decorative export settings and selected-format state | Confirm export code does not consume them | Controls that do not affect output are placebo UI |
| Hardcoded feed “Active” badges and fake notification badge | Replace with real connection/notification state or remove | Placeholder status violates metric hygiene |
| Dead `select.tsx` or duplicate primitive | Confirm zero importers and no planned Radix Select use | An unused a11y layer is maintenance debt |
| Synthetic scenario seed data, pseudo-frontier helpers, pseudo-CI helpers | Confirm no legitimate calculation consumes them | Prevents future accidental display of fabricated analytics |
| Static explainer examples phrased as this portfolio's facts | Move to explicitly labeled “Example” content | Hardcoded numbers can be mistaken for live data |
| Dead page-local CSV builders | Replace every caller with the shared writer first | Hand-built rows corrupt commas/newlines and bypass formula guards |

## 4. Phased migration table

| Phase | Goal | Files / areas | User impact | Effort | Dependencies / gaps | Risk |
|---|---|---|---|---|---|---|
| **0 — Trust spine** | Establish semantic tokens, null/error/freshness contracts, formatters, and regression fixtures before visual migration. | `frontend/src/app/globals.css`; `frontend/src/lib/utils.ts`; new `frontend/src/lib/format.ts`; `frontend/src/lib/api.ts`; `frontend/src/types/index.ts`; new `frontend/src/components/ui/PanelState.tsx`; new `frontend/src/components/ui/StatusBadge.tsx`; new `frontend/src/components/charts/chart-theme.ts`; unit tests. | Numbers stop changing meaning between pages; missing values become honest; both themes have one surface language. | **M** | Backend null/flag fields are already partly present, but unified field-level freshness/source coverage is not shipped. Do not block the UI on a new quality endpoint; expose only response metadata now. | **Medium:** broad token/format changes can create visual diffs and expose old call-site assumptions. Mitigate with aliases, route-by-route migration, and invariant tests. |
| **1 — Shell and IA** | Make grouped navigation, route titles, responsive drawer, global context, and settings honest. | `components/layout/Sidebar.tsx`; `DashboardLayout.tsx`; `Header.tsx`; `app/dashboard/layout.tsx`; `app/layout.tsx`; new `app/portfolio/layout.tsx` if needed; shared navigation config; sidebar/layout tests. | Users can find Portfolio, Risk, Performance, Diagnostics, Research, and System without losing existing URLs; `/portfolio/manage` gets the same shell. | **M** | No new backend dependency. Requires one route inventory and a mobile focus/inert pattern. | **Medium:** changing a shared layout can affect every route; preserve route metadata and run full type/test gates after each route slice. |
| **2 — Portfolio operations** | Make CRUD/import/rebalance coherent, accessible, and auditable. | `app/portfolio/manage/page.tsx`; `AddPositionModalSimple.tsx`; `EditPositionModal.tsx`; `PortfolioDropzone.tsx`; `PortfolioTable.tsx`; `PortfolioStats.tsx`; `PortfolioFilters.tsx`; `lib/store.ts`; `lib/api.ts`; `NotificationSystem.tsx`; CSV/export tests. | Empty, loading, failed, and stale books are distinct; first position is visibly 100.00%; import failures and dry-run trades are explicit. | **M** | Backend has current-position CRUD, bulk CSV, normalize, and rebalance, but no cash/transaction ledger. Mixed-currency per-position display still needs explicit provenance. | **High:** these are money mutations. Keep writes behind confirmations, preserve backend error detail, and never auto-submit after a failed portfolio fetch. |
| **3 — Analytics presentation** | Standardize metric cards, risk panels, tables, charts, and method labels across all current analytics routes. | `MetricCard.tsx`; `DataTable.tsx`; `RiskMetricsDisplay.tsx`; `PerformanceChart.tsx`; `SectorAllocationChart.tsx`; shared `ChartFrame`/`PanelState`/`ExplainerDialog`; `app/dashboard/{realized-risk,forecast-risk,factor-exposure,stress-testing,concentration,liquidity,volatility-sizing,tear-sheet,risk-contribution,risk-studio,optimize,regime,monte-carlo}/page.tsx`; chart/table tests. | Dense routes become comparable; missing metrics and failed panels are visible; no pseudo-confidence/frontier/zero-cone claims. | **L** | Backend has the route families, but model-quality findings (GARCH/EGARCH horizon, return construction, drawdown baseline, tail cache, source provenance) mean copy must remain qualified. Benchmark is NIFTY-only. | **High:** broad page migration can accidentally “fix” a label while preserving a wrong model. Add contract tests and compare payloads before/after; do not call outputs decision-grade. |
| **4 — Research and market tools** | Apply the same frame to company research, screener, pairs, India microstructure, Monte Carlo, and Settings. | `app/dashboard/{equity-research,screener-studio,pairs,india-flows,monte-carlo,settings}/page.tsx`; research API wrappers; per-endpoint state components; screener add-to-position flow; settings tests. | Research failures are scoped to a tab, screener results lead to a valid add flow, and market data limitations are visible. | **L** | News/sentiment and analyst estimates are absent; saved screens/watchlists/alerts are absent; NSE data is stored/calculation scaffolding; AI routes generate context/prompts, not verified recommendations. | **Medium/High:** many provider-specific null shapes and partial failures. Keep per-endpoint retries and provider/as-of labels; never fill missing data. |
| **5 — Hardening and quality** | Finish responsive behavior, accessibility, performance boundaries, exports, and regression coverage without expanding scope. | Shared UI/chart modules; `lib/export.ts`; `lib/websocket.ts`; `hooks/useRealTime.ts`; tests under `frontend/src/test/`; `next.config.ts`; browser checklist; optional React Query migration seam. | Dense pages remain usable on small screens; stale data and connection status are explicit; keyboard and screen-reader users can complete core workflows. | **M** | WebSocket lifecycle and server-read caching still have structural debt; no new package is required. Paid/real-time data claims remain out of scope. | **Medium:** performance work can introduce stale-data or race regressions. Keep stale-while-revalidate behavior visible and sequence/cancel requests before optimizing. |

## 5. Phase details and exit criteria

### Phase 0 — Trust spine

**Implementation slice:**

1. Add semantic CSS variables and map them to Tailwind. Keep temporary aliases for old utility names so migration can be incremental.
2. Remove the global Arial override and use Geist tokens.
3. Add explicit format functions for INR, currency, percent fraction, percent points, quantity, and timestamps.
4. Add a typed `AppError`/status presentation and a shared `PanelState` vocabulary.
5. Add regression fixtures for null VaR, null forecast, limited history, failed screener result, zero-state weight, en-IN currency, and color-pair tokens.
6. Add chart series tokens and a shared matrix parser test.

**Exit criteria:**

- A null response cannot render as a numeric zero through the new shared components.
- Light/dark values and up/down contrast checks pass.
- No new dependency is added.
- All current routes still compile against the existing API wrappers.

### Phase 1 — Shell and IA

**Implementation slice:**

1. Turn `Sidebar.navigation` into the single route metadata source, adding section, title, subtitle, and availability status.
2. Derive `DashboardLayout` titles from that source; add `/portfolio/manage` to the same shell without moving the URL.
3. Replace the current header's fake/unknown status claims with a context strip that can show `not provided`.
4. Make the mobile drawer inert/hidden when closed and restore focus on close.
5. Add a route smoke test for every URL in the inventory.

**Exit criteria:**

- All routes have correct titles and active navigation state.
- The shell works at mobile, tablet, and desktop widths.
- No user identity, unread count, or “live” status is implied without a real source.

### Phase 2 — Portfolio operations

**Implementation slice:**

1. Move Add/Edit/Import to the shared Radix dialog and shared field/error patterns.
2. Keep the actual empty-book distinction: only a successfully fetched empty portfolio enables `100.00%` auto-weight.
3. Make CSV import preview, accepted file rules, partial failures, and weight acknowledgment explicit.
4. Make the manage table's weight, currency, null, sorting, and row action contracts shared.
5. Make rebalance dry-run the default; require a separate confirmation for live mutation.
6. Route all mutation outcomes through visible inline/toast feedback.

**Exit criteria:**

- Keyboard-only user can add/edit/import/delete through labelled dialogs.
- Failed portfolio fetch blocks auto-weight and submission.
- CSV export does not save an error body as a `.csv` file.
- No mutation is described as successful before the backend confirms it.

### Phase 3 — Analytics presentation

**Implementation slice:**

1. Migrate metric cards and risk displays first, then the shared table and chart frame.
2. Convert each page's bespoke loading/error/empty branches to a panel state, preserving independent panel errors.
3. Add methodology captions to model-dependent metrics and benchmark labels to comparisons.
4. Remove any local synthetic geometry or heuristic unit detection.
5. Validate matrix and table renderers with the repository invariants.

**Exit criteria:**

- Realized/forecast/stress/concentration/liquidity/sizing/tear-sheet/risk/optimizer/regime routes all render the same state language.
- No `NaN`, `0.00%` VaR, zero cone, `NORMAL` all-clear, `+-3.2%`, or synthetic frontier appears on a failed/unavailable response.
- Min/max, VaR/CVaR, HHI/N_eff, inverse-volatility, and monthly-compounding copy matches the backend formulas.

### Phase 4 — Research and market tools

**Implementation slice:**

1. Split the research page into header, tabs, endpoint state, and data panels without changing the route.
2. Initialize deep-linked tickers correctly and clear prior-company data on a failed switch.
3. Show per-tab errors/empty states; stop console-only failures.
4. Make screener add-to-position use the standard valid-weight flow.
5. Label India data as stored/limited and add as-of/error state.
6. Remove all placebo settings and hardcoded feed statuses.

**Exit criteria:**

- A failed research tab does not display another tab's stale data.
- A valid empty response is distinguishable from provider failure.
- Screener results can be handed to the position flow without `weight: 0`.
- Unsupported news/estimates/saved workflows are labeled or omitted.

### Phase 5 — Hardening and quality

**Implementation slice:**

1. Run responsive/manual checks for every route at narrow and wide widths.
2. Check focus order, dialog return focus, table sorting, chart text alternatives, and live-region announcements.
3. Consolidate CSV/PDF export formatting and page-break behavior without adding a renderer.
4. Add request sequence/cancellation or installed React Query boundaries where races remain; keep WebSocket state honest.
5. Add permanent unit/component tests for the revamp invariants and document any remaining backend handoffs.

**Exit criteria:**

- `bunx tsc --noEmit` passes.
- `bun run test:run` passes, including new regression tests.
- `bun run lint` has no new errors; baseline warning cleanup is tracked separately if still open.
- No hardcoded palette or missing-value fabrication is introduced.
- Manual browser walkthrough covers loading, error, empty, stale, partial, and success for all route families.

## 6. Backend gaps that constrain the revamp

These are dependencies for truthful UI language, not reasons to block a purely visual phase.

| Gap | Frontend response before backend closure |
|---|---|
| No unified field-level freshness/quality contract | Show source/as-of only when present; use per-panel `UNAVAILABLE`/`PARTIAL` states |
| No transaction/cash ledger | Do not promise TWR/MWR, tax lots, or historical trade reconstruction |
| No TE/IR or selectable benchmark suite | Keep NIFTY comparison labeled; omit missing cards |
| No add-ticker-impact endpoint | Do not add candidate-impact navigation or a fake before/after form |
| No news/sentiment or estimates route | Omit or label `NOT SHIPPED`; never render neutral/zero values |
| No saved screens/watchlists/alerts | Keep screener run-only; do not imply persistence |
| Limited India ingestion path | Say “stored records” and show the response as-of; no “live NSE” claim |
| Tail/model/source caveats | Keep methodology and confidence labels narrow; do not translate a warning into a buy/sell verdict |
| Mixed-currency aggregation provenance | Show base currency and rate provenance; avoid symbol-only conversion |

The frontend can ship a clean shell and honest unavailable states while these gaps remain. It cannot make them disappear through copy.

## 7. Explicitly skipped items and reasons

| Skipped item | Reason |
|---|---|
| Futures, options, derivatives, crypto, or other asset-class navigation | Out of product scope and not supported by the current backend |
| New design-system package | Tailwind 4, Radix, Lucide, and existing primitives are sufficient |
| New charting library | Recharts is installed and existing chart contracts can be standardized |
| New table library | TanStack Table is already installed and used |
| New state/data-fetch package | React Query is already installed; no new package is needed. Migrate selectively if it reduces races |
| Generic AI stock picker/recommendation surface | Backend AI routes provide prompts/context, not validated decision output |
| News/sentiment feed | No current backend route or auditable corpus |
| Analyst estimates/target prices | No current backend route; provider coverage is partial/unverified |
| Tracking error/information ratio | Not present in the current backend contract |
| Immutable transaction ledger, TWR/MWR, tax lots | Foundational backend work is not shipped; a UI would imply false history |
| Saved screens, watchlists, alerts, run history | No persisted product models/routes |
| Full NSE ownership-quality score and automated collection | Storage/calculation scaffolding exists, but source rights and live ingestion are not verified |
| Corporate-action calendar and event alerts | Actions are used in calculations but no portfolio calendar route is shipped |
| Unified PDF decision report | Existing exports are sufficient for Wave-1; HTML/print or renderer work is a later scope |
| URL renames and a new router | Existing URLs are usable; preserving them lowers migration risk |
| Auth, multi-user, team workspaces, billing | Product is personal/localhost; backend has no user/tenant model |
| Gradients, glassmorphism, 3D charts, animated marketing hero | Conflicts with the restrained, flat data-terminal direction |
| Silent “best effort” model outputs | Contradicts the trust spine; unavailable is preferable to fabricated precision |

## 8. Verification and handoff checklist

### Design and content

- [ ] All hardcoded page colors map to semantic tokens; chart series use the documented palette.
- [ ] Light/dark surfaces and the up/down pair pass the contrast checks in `01-design-system.md`.
- [ ] Every page title, section label, and tooltip uses one navigation/config source.
- [ ] Copy distinguishes `N/A`, `—`, `UNAVAILABLE`, `STALE`, `PARTIAL`, and `NOT SHIPPED`.

### Data correctness

- [ ] No presentation path converts null/NaN to zero or a safe risk score.
- [ ] INR uses en-IN and explicit base-currency provenance.
- [ ] Percent fraction and percent-point formatters are named and tested.
- [ ] HHI/N_eff and diversification are calculated from true weights; `N ≤ 1` is exactly 0% diversification.
- [ ] Volatility sizing displays true inverse-volatility weights.
- [ ] Monthly return copy/visualization is consistent with geometric compounding.
- [ ] TanStack cells use `row.original || row`.
- [ ] Matrix responses use `tickers` and `matrix[i][j]`.
- [ ] No chart uses a locally invented confidence band, frontier, scenario, or current point.

### Workflow and accessibility

- [ ] All current routes and `/` redirect work.
- [ ] Add/edit/import/delete dialogs have labels, focus traps, Escape, and return focus.
- [ ] Sortable table headers are keyboard buttons with `aria-sort`.
- [ ] Mobile drawer is inert/hidden when closed; active route has a non-color cue.
- [ ] Loading, error, empty, stale, and partial states are manually exercised.
- [ ] Export and mutation actions show terminal success/failure and preserve backend detail.

### Dependency rule

- [ ] No new package is introduced by this revamp.
- [ ] Existing Next/React/Tailwind/Recharts/TanStack/Radix/Lucide/Zustand/Axios capabilities are reused.
- [ ] If a future phase claims a new dependency is unavoidable, it includes a separate decision record explaining why the installed capability cannot satisfy the requirement.

## 9. Recommended first implementation slice

If only one slice is started, choose **Phase 0 + the shell portion of Phase 1**. It has the highest leverage: it fixes the language of numbers and missing data, gives every route a coherent frame, and prevents the later page migrations from multiplying the current color, error, and formatting drift. Portfolio mutation work should follow only after that trust spine is in place.
