# FinEngine UX 02 — Current-to-Target Information Architecture

**Status:** Wave-1 architecture proposal; documentation only  
**Scope:** Current frontend routes, current backend capability, and a target IA that preserves existing URLs  
**Product boundary:** Personal, localhost-first, India-first listed cash equities. Futures, options, and other asset classes are explicitly out of scope.

## 1. IA decisions

### 1.1 Preserve routes, change navigation

The first revamp is a hierarchy and presentation migration, not a URL migration. Every current page remains reachable at its current path. The target sidebar groups routes by the decision a user is trying to make:

```text
FinEngine
├─ Portfolio
│  ├─ Summary                         /dashboard
│  └─ Manage positions                /portfolio/manage
├─ Risk
│  ├─ Realized risk                   /dashboard/realized-risk
│  ├─ Forecast risk                   /dashboard/forecast-risk
│  ├─ Concentration                   /dashboard/concentration
│  ├─ Liquidity                       /dashboard/liquidity
│  ├─ Stress testing                  /dashboard/stress-testing
│  ├─ Volatility sizing               /dashboard/volatility-sizing
│  ├─ Risk contribution               /dashboard/risk-contribution
│  └─ Risk studio                     /dashboard/risk-studio
├─ Performance & allocation
│  ├─ Tear-sheet                      /dashboard/tear-sheet
│  ├─ Optimizer                       /dashboard/optimize
│  ├─ Market regime                   /dashboard/regime
│  └─ Goal probability                /dashboard/monte-carlo
├─ Market diagnostics
│  ├─ Pairs scanner                   /dashboard/pairs
│  └─ India microstructure            /dashboard/india-flows
├─ Research
│  ├─ Equity research                 /dashboard/equity-research
│  └─ Screener studio                 /dashboard/screener-studio
└─ System
   └─ Settings                        /dashboard/settings
```

This grouping is metadata in one navigation configuration. It does not add a route, move a page behind a new router, or require a redirect. The existing `navigation` array in `frontend/src/components/layout/Sidebar.tsx` is the natural source to extend with `section`, `title`, and `status` fields; `DashboardLayout` should derive page titles from that same array.

### 1.2 Shared information scent

Every page should answer the same first four questions without forcing the user to read the backend:

1. **What portfolio/context?** Current positions, selected tickers, or the company being researched.
2. **What window and unit?** Date range, horizon, base currency, and model where applicable.
3. **How fresh and from where?** Source, market date/as-of, cache state, and quality flags when the API provides them.
4. **What is actionable or unavailable?** Controls that mutate/calculate, plus a clear distinction between a true empty result and an unavailable capability.

The shell owns the first three where they are global. A page owns its analysis controls and interpretation. A route must not infer a “live” state from the mere presence of a WebSocket client or a cache hit.

## 2. Current route inventory

The following inventory reflects the current `page.tsx` files and sidebar entries. `/` redirects to `/dashboard`; it is not a separate product surface. `/portfolio/manage` is currently outside the dashboard layout and should adopt the same shell in the target.

| Current URL | Current purpose/UI entry | Primary backend surface | Target section | URL action |
|---|---|---|---|---|
| `/` | Redirect to dashboard | None | — | Keep redirect |
| `/dashboard` | Portfolio summary, value, P&L, risk highlights, holdings | `GET /portfolio`, plus selected analytics calls | Portfolio | Keep |
| `/dashboard/equity-research` | Company profile, shareholding, concalls, ratios, prompts/dossier | `/company/{ticker}/full-profile`, `/shareholding`, `/concalls`, `/custom-ratios`, `/export-excel`, AI prompt/dossier routes | Research | Keep |
| `/dashboard/screener-studio` | Five built-in India screens and custom filter; add result to portfolio | `/screens`, `/screens/{strategy}`, `/screens/custom`, then `/portfolio/add` | Research | Keep |
| `/dashboard/realized-risk` | Historical return, volatility, Sharpe/Sortino, drawdown, VaR/CVaR | `GET /analytics/realized-risk` | Risk | Keep |
| `/dashboard/forecast-risk` | EWMA/GARCH/EGARCH volatility and horizon VaR/CVaR | `GET /analytics/forecast-risk` | Risk | Keep |
| `/dashboard/factor-exposure` | OLS alpha/beta/R² against NIFTY; current label says “multi-factor” | `GET /analytics/factor-exposure` | Risk | Keep; clarify label |
| `/dashboard/stress-testing` | Fixed/custom deterministic stress scenarios | `POST /analytics/stress-test` | Risk | Keep; constrain controls to contract |
| `/dashboard/concentration` | Largest positions, HHI, effective N, diversification, sectors | `GET /analytics/concentration` | Risk | Keep |
| `/dashboard/liquidity` | Heuristic score, liquidation estimates, position table | `GET /analytics/liquidity` | Risk | Keep; label methodology |
| `/dashboard/volatility-sizing` | Inverse-volatility target weights and trade deltas | `GET /analytics/volatility-sizing` | Risk | Keep |
| `/dashboard/tear-sheet` | Performance suite and NIFTY comparison | `GET /analytics/tear-sheet` | Performance & allocation | Keep |
| `/dashboard/risk-contribution` | Euler volatility and historical tail contribution | `GET /analytics/risk-contribution` | Risk | Keep |
| `/dashboard/risk-studio` | Composite canvas for Euler, vol cone, correlation stability, tails | `/analytics/risk-contribution`, `/vol-cone`, `/correlation-stability`, `/tails` | Risk | Keep |
| `/dashboard/optimize` | HRP, minimum volatility, maximum Sharpe, minimum CVaR, Black-Litterman | `POST /analytics/optimize/run` | Performance & allocation | Keep |
| `/dashboard/regime` | NIFTY HMM state and conditional portfolio statistics | `GET /analytics/regime` | Performance & allocation | Keep |
| `/dashboard/monte-carlo` | Goal probability using GBM, Student-t, or bootstrap | `POST /analytics/monte-carlo` | Performance & allocation | Keep |
| `/dashboard/pairs` | Cointegration, half-life, and z-score scan | `GET /analytics/coint` | Market diagnostics | Keep |
| `/dashboard/india-flows` | Stored delivery, FII/DII, and liquidity-limit reads | `GET /analytics/india-flows`, `/delivery-anomalies`, `/liquidity-limits` | Market diagnostics | Keep; qualify ingestion |
| `/dashboard/settings` | Primary source, cache TTL, cache enablement, cache clear | `GET/PUT /data/config`, `POST /data/cache/clear` | System | Keep |
| `/portfolio/manage` | Position CRUD, CSV import, normalize, rebalance, CSV export | `/portfolio`, `/add`, `/bulk_add`, position `GET/PUT/DELETE`, `/export/csv`, `/normalize`, `/rebalance` | Portfolio | Keep; adopt shell |

### 2.1 Backend-only capabilities not currently top-level routes

These routes exist or are used by the current risk studio, but should not become new navigation items merely because the endpoint exists:

- `GET /analytics/summary`, `GET /analytics/performance-history`, and `POST /analytics/backtest` support the summary/research workflow but are not separate current pages.
- `GET /analytics/risk-score` has a backend contract but no current top-level page. Do not add a “score” nav item until its threshold semantics and missing-data behavior are explicit.
- `GET /analytics/correlation-stability`, `GET /analytics/vol-cone`, and `GET /analytics/tails` are diagnostic panels consumed by `/dashboard/risk-studio`.
- `GET /data/verified-snapshot`, `GET /data/indicators/{ticker}`, `GET /data/fundamentals/{ticker}`, `GET /data/financials/{ticker}`, and `GET /data/insider/{ticker}` are data/research primitives, not independent top-level destinations yet.

## 3. Target page contract

Every target route uses the same frame:

```text
[Page title]                         [route-specific controls]
[Portfolio/company context] [base currency] [window] [source/as-of] [quality]
[Primary result: live values, N/A, or a named unavailable state]
[Supporting explanation/methodology]
[Action surface: only mutations/calculations the backend supports]
```

The frame has five states:

| State | Screen behavior | Copy/evidence rule |
|---|---|---|
| Loading | Keep shell and page title; skeleton the shape of the result | “Loading current data…” is not a metric |
| Success | Render API values with units, window, and quality | No invented fallback values |
| Empty | Explain why the result is empty and offer the relevant next action | “No positions”, “no rows matched”, or “no observations” are distinct |
| Error | Show backend detail where available, preserve last good data if safe, and offer Retry | Never turn an error into an empty success state |
| Stale/partial | Keep last good result visible, add age/partial banner, mark affected fields | “Stale as of…” and “8/10 aligned” are not hidden in console logs |

A route can show different states per panel. For example, a successful portfolio response can coexist with an unavailable forecast panel. The unavailable panel must not blank or contaminate successful cards.

## 4. Route-by-route target map and capability matrix

The “backend-supported” column describes shipped routes/services, not a claim that every response is decision-grade. The “target treatment” column describes how the UI should present those limitations.

### 4.1 Portfolio

#### `/dashboard` — Portfolio Summary

**User job:** Understand current value, unrealized P&L, allocation, and the most decision-relevant risk snapshot.

**Shipped inputs:**

- `GET /portfolio` returns positions, total value, sectors, and explicit base-currency provenance in the current backend envelope.
- `GET /analytics/realized-risk` supplies historical risk when enough aligned history exists.
- `GET /analytics/risk-contribution` and `/analytics/regime` can provide a compact diagnostic; these should be independently retryable.

**Target layout:**

1. Context strip: current value, base currency, number of positions, as-of/source quality.
2. Metric strip: unrealized P&L, annual volatility, 1-day historical VaR/CVaR, effective N/diversification.
3. Allocation panel with `Unknown` sector handling.
4. Performance panel with an explicit benchmark label.
5. Holdings table linking to `/portfolio/manage`.
6. Data-health panel that names any missing/stale field.

**Do not show:** tracking error, information ratio, TWR/MWR, news/sentiment, analyst targets, or a transaction-derived return. They are not in the current shipped response contract.

#### `/portfolio/manage` — Manage Positions

**User job:** Add, edit, delete, import, normalize, and rebalance current positions.

**Shipped inputs:** Portfolio CRUD, bulk add, CSV export, weight normalization, and dry-run/live rebalance routes are present. Bulk responses include added/failed/skipped/duplicate details in the current backend envelope.

**Target layout:**

- Header actions: `Add position`, `Import CSV`, `Export CSV`, `Normalize weights`, `Rebalance`.
- Summary strip: total value, total cost, unrealized P&L, position count, total weight, base currency.
- Table: ticker, quantity, buy price, last price, weight, current value, unrealized P&L, sector, updated/as-of, row actions.
- Import/dropzone dialog: preview, accepted file type/size, parsed row count, skipped/duplicate/failed rows, and explicit weight acknowledgment.
- Rebalance dialog: target weights, dry-run first, order/turnover/cash deltas, then a separate confirm step for mutation.

**Zero-state:** The empty state says “No positions yet. Add a ticker or import a CSV.” The first position's auto-calculated weight is `100.00%`; no arbitrary `100000` portfolio total or failed-fetch “empty” state is allowed.

**Currency caveat:** The aggregate response can carry a converted base currency and provenance, but per-position native values and any frontend symbol toggle need a real, explicit rate. The UI must not show a converted-looking dollar value when it is only symbol substitution.

### 4.2 Risk

#### `/dashboard/realized-risk` — Realized Risk

**Backend:** `GET /analytics/realized-risk` computes annual return, volatility, Sharpe, Sortino, skew, kurtosis, drawdown, historical VaR/CVaR, hit ratio, and coverage warnings. It can return nulls/flags for insufficient history.

**Target treatment:** Show the actual server window (`data_range`) and coverage. Separate “not computed” from “zero risk.” If history is truncated or missing, keep the metric `N/A` and explain the coverage limitation. This route is not a substitute for a transaction ledger or TWR/MWR.

#### `/dashboard/forecast-risk` — Forecast Risk

**Backend:** `GET /analytics/forecast-risk` exposes EWMA, GARCH, and EGARCH horizons. The response includes nullable values and `model_fitted`/limited-history/error flags in the current contract.

**Target treatment:** A model/horizon toolbar, fit-status banner, horizon curve only when the response supplies it, and a table of values. Do not create a confidence interval locally or plot a synthetic ±20% band. A failed fit is a visible “model unavailable” state, not a default 22% volatility.

#### `/dashboard/factor-exposure`

**Backend:** `GET /analytics/factor-exposure` is a single-market OLS regression against the current NIFTY benchmark, returning alpha, beta, R², and related fields. It is not a value/momentum/quality factor suite.

**Target treatment:** Rename the explanatory copy to “Market beta / alpha” while preserving the URL. Show benchmark, lookback, overlap, and error fields. A payload containing `r_squared: 0` plus an error must be treated as unavailable, not as a live “weak fit.”

#### `/dashboard/stress-testing`

**Backend:** `POST /analytics/stress-test` supports fixed scenario identifiers and returns deterministic weighted impacts. The current public request contract is the reliable boundary; custom shock/duration fields shown by a page must not be presented as applied unless the backend accepts and echoes them.

**Target treatment:** Scenario cards are real buttons with keyboard support. Show scenario definition, selected positions, impact, recovery field when present, and methodology. A recovery value of `0` is not a substitute for null. `confidence_level` is shown as a model field only if its semantics are documented; it is not a generic statistical confidence claim.

#### `/dashboard/concentration`

**Backend:** `GET /analytics/concentration` provides largest/top-N weights, true HHI, effective positions, diversification, Gini, and sector shares. The positive normalized-weight path is reusable.

**Target treatment:** HHI and `N_eff` are the source of truth. For one holding, diversification is exactly `0%`; an empty book is a separate empty state. Show a sortable position table, sector bars with `+N more`, and an explanatory formula. Do not show a fabricated HHI during loading/error.

#### `/dashboard/liquidity`

**Backend:** `GET /analytics/liquidity` provides a heuristic score, liquidation-time labels, volume statistics, and position-level results. Some values are formula/tier outputs, not observed bid/ask spread or order-book impact.

**Target treatment:** Label the score “heuristic” and show its methodology. Missing market cap, spread, or volume is `N/A`; do not substitute an implied market cap or tier spread. Position results should show the input window and source/as-of when available.

#### `/dashboard/volatility-sizing`

**Backend:** `GET /analytics/volatility-sizing` computes inverse-volatility weights (`w_i ∝ 1/σ_i`), target volatility, and trade deltas for the existing portfolio.

**Target treatment:** Show the exact formula, model, target, current/target weight table, and dry-run rebalance link. Do not infer a risk-parity result for a missing/zero-volatility input. A total weight change above 1.0 is a valid aggregate turnover value and must not be misformatted as a small percentage.

#### `/dashboard/risk-contribution`

**Backend:** `GET /analytics/risk-contribution` returns normalized Euler volatility contribution and empirical tail-loss shares, plus sector rollups. Marginal risk is computed internally but is not currently returned as a complete public field.

**Target treatment:** Keep signed tail-versus-volatility differences. A missing `cvar_tail` map is “insufficient tail observations,” not a zero contribution. Link to the source window and portfolio composition.

#### `/dashboard/risk-studio`

**Backend panels:** `/analytics/risk-contribution`, `/analytics/vol-cone`, `/analytics/correlation-stability`, and `/analytics/tails` are shipped diagnostic surfaces. The current backend/model audit found contract and model-quality caveats around tail outputs, volatility-cone labels, and source/history coverage.

**Target treatment:** A four-panel diagnostic canvas with independent panel states. Use the actual backend keys, true min/max labels unless true percentiles are returned, and `N/A` for unknown fat-tail status. Never show a zero cone or “NORMAL” all-clear when a panel failed. A red/amber panel is a warning about evidence quality, not an automatic trade instruction.

### 4.3 Performance and allocation

#### `/dashboard/tear-sheet`

**Backend:** `GET /analytics/tear-sheet` returns performance metrics, monthly returns, underwater curve, and a NIFTY-relative comparison. The benchmark service is effectively NIFTY-only, and the history is not a complete transaction/cash ledger.

**Target treatment:** Label the benchmark exactly (“NIFTY 50 price-index comparison” where appropriate), show the actual data span, and separate current-holdings history from investable historical performance. Do not add TE/IR, up/down capture, or TWR/MWR cards until the backend exposes them with overlap/source flags.

#### `/dashboard/optimize`

**Backend:** `POST /analytics/optimize/run` supports five strategies: HRP, minimum volatility, maximum Sharpe, minimum CVaR, and Black-Litterman. It works over the requested/current holding universe and is not a complete “add a new ticker” impact endpoint.

**Target treatment:** Strategy selector, assumptions, real optimal coordinate, actual current-portfolio coordinate only when computed from current data, weight/trade table, and dry-run rebalance. If expected return or volatility is null, show an empty chart with a reason. No synthetic Markowitz frontier or “current” point derived by multiplying the optimum.

#### `/dashboard/regime`

**Backend:** `GET /analytics/regime` fits a three-state NIFTY HMM and returns conditional portfolio statistics, with an observation/coverage gate.

**Target treatment:** Render backend-provided state keys, including `state_N` when the fit is not the expected three-state labeling. Show current regime, stability, probability bars, and portfolio behavior in that regime. Do not fill missing `bull/calm/crisis` keys with zero.

#### `/dashboard/monte-carlo`

**Backend:** `POST /analytics/monte-carlo` supports GBM, Student-t, and stationary bootstrap, with target value, horizon, path count, and seed/disclaimer fields.

**Target treatment:** Inputs, method, seed, path count, target, probability, fan percentiles, and calibration fields. A default i.i.d. GBM is a scenario assumption, not a guaranteed forecast. An empty fan is a named unavailable state, not a crash or a flat zero chart.

### 4.4 Market diagnostics

#### `/dashboard/pairs`

**Backend:** `GET /analytics/coint` returns pair, p-value, half-life, z-score, and cointegration flag.

**Target treatment:** Filterable pair table, selected-pair detail, and methodology/window. This is a statistical pair screen, not a valuation or execution recommendation. Preserve pair symbols and show N/A for absent statistics.

#### `/dashboard/india-flows`

**Backend:** `GET /analytics/india-flows`, `/delivery-anomalies`, and `/liquidity-limits` read stored NSE microstructure/flow records and calculate delivery/liquidity diagnostics.

**Target treatment:** Separate sections for delivery spikes, institutional flows, and ADV/liquidation limits, each with its own as-of/error/empty state. Label data as “stored NSE-derived records” rather than a verified live official feed. The backend has storage and calculation scaffolding, but no verified automated NSE ingestion path; no page may imply unattended real-time exchange data.

### 4.5 Research

#### `/dashboard/equity-research`

**Backend:** Full profile, shareholding, concalls, custom ratios, financial-model XLSX, AI memo/forensic prompts, and dossier routes are shipped. Research coverage is provider- and market-dependent; the shareholding route is India-specific, and peers are an upstream list rather than a full cross-sectional valuation engine.

**Target treatment:**

- Ticker input with deep-link support (`?ticker=`) and a visible active company.
- Overview: quote/profile, valuation, company facts, and source/as-of.
- Shareholding: period-indexed trends, missing periods visible.
- Calls: links and dates; a vendor outage is an error, not “no calls.”
- Financials: statement/frequency/period controls and explicit missingness.
- Ratios: render the fields actually returned; no fabricated Piotroski/Graham values.
- AI context: label prompt/dossier generation as context, not an autonomous recommendation or verified analysis.

News/sentiment and analyst estimates are not current backend routes. They can appear only in a “not shipped” coverage note, never as empty news or zero estimates.

#### `/dashboard/screener-studio`

**Backend:** `/screens` lists five built-in strategies; `/screens/{strategy}` runs one; `/screens/custom` accepts five basic filters (ROCE, ROE, P/E, market cap, dividend yield). Results are India-focused and provider-dependent.

**Target treatment:** Strategy cards with descriptions, custom filter form, run controls, result count, table columns, and an `Add selected position` action that opens the normal position flow. A result's computed weight must be `1.0` for an actually empty portfolio or value-share against a successfully loaded portfolio. Do not send zero weight. Saved screens, watchlists, run history, and alerts are not shipped and must not be implied by the UI.

### 4.6 System

#### `/dashboard/settings`

**Backend:** `GET/PUT /data/config` persists `primary_source` (`bfinance` or `yfinance`), cache TTL, and cache enablement. `POST /data/cache/clear` clears market/analytics/NSE cache tables while preserving portfolio holdings.

**Target treatment:** Show only those real settings, with a dirty state and exact save copy. A cache clear requires confirmation and reports which caches were cleared and that holdings were preserved. Do not show currency, benchmark, risk-free rate, target volatility, or lookback controls as saved preferences unless an end-to-end backend contract exists.

## 5. Backend capability and gap ledger

### 5.1 Shipped capability families

| Family | Current shipped capability | UI consequence |
|---|---|---|
| Portfolio | Current-position CRUD, bulk add/import, normalize, rebalance/dry-run, CSV export | Make `/portfolio/manage` the operational home; do not imply a cash ledger |
| Market data | OHLCV/adjusted close, quote, fundamentals, statements, insider, technical indicators, source preference, cache controls | Show source/cache/as-of when returned; validate tickers and date windows |
| Research | Company profile, India shareholding, concalls, ratios, peers, AI prompt/dossier, XLSX | Treat as research context with provider limitations |
| Screeners | Five fixed strategies, five-field custom screen, result cache | No saved screens/watchlists/alerts in Wave-1 target |
| Realized risk | Return, volatility, Sharpe/Sortino, skew/kurtosis, drawdown, historical VaR/CVaR, hit ratio | Null/coverage states are first-class |
| Forecast risk | EWMA/GARCH/EGARCH and horizons | Do not invent model defaults or confidence bands |
| Factor exposure | Single-market OLS alpha/beta/R² against NIFTY | Rename away from “multi-factor” claims |
| Stress | Deterministic fixed scenarios and weighted impacts | Do not claim a forecast or unsupported custom inputs |
| Concentration | True HHI, effective N, diversification, Gini, sector shares | Use formulas directly |
| Liquidity | Heuristic score, volume/liquidation calculations | Label as heuristic; no observed spread claim |
| Volatility sizing | True inverse-volatility weights and trade deltas | Use true 1/σ allocation |
| Performance | History, tear sheet, monthly compounding, NIFTY comparison | No TWR/MWR/TE/IR claims |
| Risk decomposition | Euler volatility and empirical tail attribution | Show missing tail observations honestly |
| Optimization | Five long-only strategies for current/request universe | No new-ticker impact claim |
| Regime | NIFTY HMM and conditional portfolio statistics | NIFTY-only and coverage-gated |
| Monte Carlo | GBM/Student-t/bootstrap goal simulation | Show assumptions and seed |
| Diagnostics | Correlation stability, vol cone, cointegration, tails | Independent panel states; not universally decision-grade |
| India primitives | Stored flows, delivery, bhavcopy/microstructure schemas, ADV calculations | Stored/limited ingestion, not guaranteed live feed |
| Streaming | Portfolio/analytics/market-data broadcasts every 30 seconds | Connection state is not proof that every field is fresh |

### 5.2 Explicit gaps and deferred UI promises

The target IA must not create cards, navigation entries, or success copy for these capabilities until the backend contract exists:

| Gap | Current state | Target decision |
|---|---|---|
| Add-ticker impact | No shipped read-only endpoint that freezes funding and returns coherent before/after risk, concentration, correlation, and liquidity deltas | Keep as a documented design proposal; do not add a fake “Add impact” route |
| Transaction/cash ledger | Current persistence has positions, not immutable buy/sell/dividend/fee/cash events | Do not claim TWR, MWR, tax lots, or historically reconstructed trades |
| Complete benchmark suite | Current tear sheet is NIFTY-oriented; no tracking error/information ratio or selectable benchmark policy | Do not render TE/IR or generic “outperformance” |
| Field-level quality/freshness | Timeseries and some responses have source/status/fetch metadata, but no unified per-field contract | Use per-response badges now; defer a portfolio-wide quality center |
| News/sentiment | No production FinEngine news corpus or route | Omit or label not shipped; no empty “sentiment neutral” |
| Analyst estimates/targets | No estimates/recommendations route in current data/equity-research APIs | Omit; no target price or consensus count |
| Saved screens/watchlists/alerts | No persisted screen, watchlist, alert, or run-history model | Keep screener as run-only |
| Ownership-quality workflow | Shareholding primitives exist, but no complete quality score, pledge trend, or freshness/reconciliation service | Show raw periods only; defer score |
| Corporate-action calendar | Actions may be used in adjusted data, but no portfolio event calendar route | Do not show event calendar/alerts |
| Unified decision report | Existing CSV/XLSX exports are not a unified auditable portfolio report | Keep existing exports; defer report promise |
| NSE automated ingestion | Storage/calculation scaffolding is not a verified live official ingestion path | Say “stored records” and show as-of; do not call live |
| Mixed-region benchmark policy | Current benchmark service is effectively NIFTY-only | Keep benchmark label; no US/mixed benchmark claim |
| Futures/options | No supported product surface in this scope | Excluded from navigation, copy, and wireframes |

## 6. Target navigation behavior

- The first viewport shows the current section, not a marketing hero. On desktop, section labels are visible; on collapsed/mobile navigation, use grouped disclosure and accessible names.
- A route's page title comes from one metadata object. The current drift where three live routes fall back to “Dashboard” is resolved by using the same object for sidebar and header.
- A “Portfolio context” control can return to `/portfolio/manage`; it does not create a second portfolio model.
- Cross-links between risk pages preserve the current selected portfolio/window when possible, but the selected window must be serialized in the URL or shared state with an explicit reset. Do not silently show a selected date that was not sent to the API.
- Research routes may deep-link to a ticker using `?ticker=`. A deep link must initialize both visible input and loaded company, and a failed switch must clear the prior company’s data.
- The settings page is a footer/system destination, not a place for decorative toggles.

## 7. Information-state acceptance criteria

A route is IA-complete only when:

- [ ] Every current URL remains reachable and the root redirect still works.
- [ ] The target section and page title are derived from one navigation config.
- [ ] Portfolio base currency, window, source/as-of, and quality are visible or explicitly marked unavailable.
- [ ] Loading, empty, error, stale, and partial states do not masquerade as one another.
- [ ] A null metric is not shown as zero, a safe score, a low-risk badge, or a blank cell.
- [ ] All actions map to a current backend mutation/calculation route.
- [ ] The route copy does not claim news, estimates, TE/IR, transaction history, saved workflows, or live NSE ingestion unless those capabilities are shipped and verified.
- [ ] The page preserves the current route when moving between overview, diagnostics, and portfolio management.
