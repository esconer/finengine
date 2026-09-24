# FinEngine UX 05 — Text Wireframes

**Status:** Wave-1 architecture proposal; documentation only  
**Fidelity:** Text wireframes for layout, hierarchy, data states, and copy. They are not visual mockups and do not imply new backend capabilities.

## 1. How to read these wireframes

The target terminal uses a small set of visible state labels:

```text
[LIVE]       A live quote/connection is actually known
[CACHED]     Response came from cache; cache/as-of is shown when available
[STALE]      Last good data remains visible, with age and Refresh
[PARTIAL]    Some fields/rows are available; missing scope is named
[UNAVAILABLE] Endpoint/provider returned no usable result
[N/A]        Metric is not available/not computed
[—]          Table/stat value is unavailable
[NOT SHIPPED] Capability is not exposed by the current backend
```

A wireframe may show placeholder values such as `18.42%`, `₹1.25 Cr`, or `2026-09-24 16:30 IST` to demonstrate hierarchy. They are not hardcoded product data. In implementation, values come only from the API and pass the formatting/null contracts in `01-design-system.md`.

The universal page frame is:

```text
[page title]                                      [page controls]
[context] [base currency] [window] [source/as-of] [quality]
[primary result or N/A]
[supporting panel/table]
[methodology/provenance/action footer]
```

## 2. Application shell

### 2.1 Desktop shell

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ FINENGINE   Portfolio Summary                         Base: INR  As of: —  [Refresh] [Export] │
│              [source: not provided]                  [theme] [settings]                     │
├───────────────────────┬──────────────────────────────────────────────────────────────────────┤
│ PORTFOLIO             │                                                                      │
│  ▸ Summary            │  PAGE CONTENT                                                        │
│    Manage positions   │  max-width 1440 · 16/24px gutters                                   │
│                       │                                                                      │
│ RISK                  │                                                                      │
│  Realized risk        │                                                                      │
│  Forecast risk        │                                                                      │
│  Concentration        │                                                                      │
│  Liquidity            │                                                                      │
│  Stress testing       │                                                                      │
│  Volatility sizing    │                                                                      │
│  Risk contribution    │                                                                      │
│  Risk studio          │                                                                      │
│                       │                                                                      │
│ PERFORMANCE           │                                                                      │
│  Tear-sheet           │                                                                      │
│  Optimizer            │                                                                      │
│  Market regime        │                                                                      │
│  Goal probability     │                                                                      │
│                       │                                                                      │
│ MARKET DIAGNOSTICS    │                                                                      │
│  Pairs scanner        │                                                                      │
│  India microstructure │                                                                      │
│                       │                                                                      │
│ RESEARCH              │                                                                      │
│  Equity research      │                                                                      │
│  Screener studio      │                                                                      │
│                       │                                                                      │
│ SYSTEM                │                                                                      │
│  Settings             │                                                                      │
├───────────────────────┴──────────────────────────────────────────────────────────────────────┤
│ [toast/status region: role=status, dismissible, no fake unread badge]                       │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

The sidebar may collapse to 64px. In collapsed mode every icon has a visible tooltip and an accessible name; active state still has `aria-current="page"` and a non-color rule. The header's as-of/source strip is not a permanent “Live Data Active” badge. If no timestamp is supplied, it reads `As of: not provided`.

### 2.2 Mobile shell

```text
┌───────────────────────────────┐
│ ☰  FinEngine          [⋯]     │
│    Summary · INR · as of —   │
├───────────────────────────────┤
│                               │
│       scrollable page         │
│                               │
├───────────────────────────────┤
│ [Portfolio] [Risk] [Research]  │  ← section jump/drawer, not five icon labels
└───────────────────────────────┘

When the drawer opens:
┌───────────────────────────────┐
│ FINENGINE                  [×] │
│ PORTFOLIO                     │
│   Summary                      │
│   Manage positions             │
│ RISK                          │
│   Realized risk                │
│   ...                          │
└───────────────────────────────┘
```

The closed drawer is inert and not keyboard-focusable. The page keeps its title and context when a route changes.

## 3. Portfolio Summary — `/dashboard`

### 3.1 Success state

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ Portfolio Summary                                                   [Refresh] [Export CSV]   │
│ Current book · INR · 14 positions · Source/as-of: not provided by response                  │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ CURRENT VALUE       UNREALIZED P&L     ANNUAL VOL       1D HISTORICAL VaR     EFFECTIVE N    │
│ ₹1.25 Cr            ▲ +₹8.40 L         18.42%           2.10%                  6.8            │
│                     +6.72%             [N/A if absent]  2.74%                  [N/A if absent]│
│                     window: current   window: 252      loss convention: 95%   HHI source: API  │
├───────────────────────────────────────┬──────────────────────────────────────────────────────┤
│ Performance                           │ Allocation                                          │
│ [chart frame]                         │ [bar/donut frame]                                    │
│ Portfolio ─────                       │ IT          31.20%                                   │
│ NIFTY 50 (price index) ──            │ Financials   27.80%                                  │
│                                       │ Unknown       4.10%                                  │
│ Source / benchmark / data span        │ [View concentration →]                              │
├───────────────────────────────────────┴──────────────────────────────────────────────────────┤
│ Holdings (live response, last successful refresh: —)                       [Manage positions] │
│ Ticker       Weight     Value       P&L          Sector       Source/as-of                  │
│ 3MINDIA.NS   18.20%     ₹22.75 L    ▲ +₹1.10 L   Industrials  not provided                     │
│ BAJAJ-AUTO.NS 12.10%    ₹15.12 L    ▼ −₹0.40 L   Auto         not provided                     │
│ ...                                                                                                 │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Data health: [PARTIAL] 2/14 rows have no sector label · [Refresh]                              │
│ Not available in this response: tracking error, information ratio, TWR/MWR, news, estimates.  │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

The last line is a capability note, not a row of fake `0` cards. If the current response has no source/as-of, the UI says so. If the portfolio is empty, the performance and allocation panels are not rendered as zero-valued analytics.

### 3.2 Loading state

```text
Portfolio Summary
[context skeleton] [context skeleton] [Refresh disabled]

┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ loading      │ │ loading      │ │ loading      │ │ loading      │
│ ████████████ │ │ ████████████ │ │ ████████████ │ │ ████████████ │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘

[chart skeleton]                 [allocation skeleton]
[holdings table skeleton]
```

The page title and context shell remain visible. No metric is rendered as zero while the request is pending.

### 3.3 Empty, error, stale, and partial states

```text
EMPTY PORTFOLIO
┌──────────────────────────────────────────────────────────────┐
│ No positions yet.                                             │
│ Add a ticker or import a CSV to start the book.               │
│ The first position is assigned 100.00% weight.                │
│ [Add position] [Import CSV]                                   │
└──────────────────────────────────────────────────────────────┘

ERROR
┌──────────────────────────────────────────────────────────────┐
│ Portfolio data could not be loaded.                           │
│ Provider detail: <actual FastAPI detail when supplied>        │
│ Last good snapshot: 24 Sep 2026, 16:30 IST                    │
│ [Retry] [Keep last snapshot]                                  │
└──────────────────────────────────────────────────────────────┘

STALE / PARTIAL
┌──────────────────────────────────────────────────────────────┐
│ [STALE] Showing the last successful portfolio snapshot.       │
│ As of: 24 Sep 2026, 16:30 IST · 2 fields lack current data.  │
│ [Refresh]                                                     │
└──────────────────────────────────────────────────────────────┘
```

A failed fetch is not treated as an empty portfolio. A partial response is not presented as a complete portfolio.

## 4. Manage Positions — `/portfolio/manage`

### 4.1 Success state

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ Manage Positions                         [Add position] [Import CSV] [Export] [More ▾]     │
│ 14 positions · ₹1.25 Cr · total weight 100.00% · base INR                                    │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ TOTAL VALUE       TOTAL COST        UNREALIZED P&L     WEIGHT CHECK       LAST UPDATE         │
│ ₹1.25 Cr         ₹1.17 Cr          ▲ +₹8.40 L        100.00%            —                  │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Search ticker / sector…       Sort: Weight ▼       [Normalize weights]                      │
│ ┌──────────────────────────────────────────────────────────────────────────────────────────┐ │
│ │ Ticker          Qty   Buy price  Weight  Last price  Value       P&L          Actions     │ │
│ │ 3MINDIA.NS       120   ₹2,140.00  18.20%  ₹2,245.00  ₹26.94 L   ▲ +₹1.10 L  [Edit][…] │ │
│ │ BAJAJ-AUTO.NS     85   ₹12,800.00 12.10%  ₹12,420.00 ₹10.56 L   ▼ −₹0.40 L  [Edit][…] │ │
│ │ ...                                                                                          │ │
│ └──────────────────────────────────────────────────────────────────────────────────────────┘ │
│ 1–14 of 14 positions · horizontal scroll on small screens                                    │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

The weight column is present so the zero-state and normalization behavior are inspectable. Values are live API values, not client-side estimates. Currency/base provenance is shown near the total.

### 4.2 Add position dialog

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Add position                                                   [×]  │
│ Add a listed cash-equity ticker. The quote and weight are refreshed. │
│                                                                      │
│ Ticker *                 [ 3MINDIA.NS                         ]       │
│ Region                   [ India · IN                         ▼ ]     │
│ Quantity *               [ 120                              ]       │
│ Buy price * (₹)          [ 2,140.00                         ]       │
│ Added on                 [ 24/09/2026                        ]       │
│                                                                      │
│ Calculated weight         18.20%                                │
│ Based on successfully loaded current value.                        │
│                                                                      │
│ [Cancel]                                      [Add position]         │
└──────────────────────────────────────────────────────────────────────┘
```

For a genuinely empty, successfully fetched portfolio, the calculation reads `100.00%`. If the portfolio total cannot be loaded, the dialog stays open and says `Could not load portfolio total — retry`; it must not submit `1.0` as if the book were empty.

### 4.3 Import CSV dialog

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Import portfolio CSV                                                     [×] │
│ Accepted: .csv or .txt · maximum 5 MB · no Excel workbook parser              │
│                                                                              │
│ Drop CSV here  or  [Choose file]                                             │
│                                                                              │
│ Preview                                                                       │
│ ┌──────┬────────┬────────┬────────┬────────┬────────┬────────────────────────┐ │
│ │ Row  │Ticker  │Qty     │Buy     │Weight  │Status  │Message                 │ │
│ │ 1    │INFY    │100     │1,450.00│12.40%  │Ready   │                        │ │
│ │ 2    │BAD     │—       │—       │—       │Skipped │Invalid ticker         │ │
│ │ 3    │500112.BO│20     │210.00  │ 8.10%  │Ready   │                        │ │
│ └──────┴────────┴────────┴────────┴────────┴────────┴────────────────────────┘ │
│ 2 ready · 1 skipped · [I understand imported weights will be reconciled]    │
│                                                        [Cancel] [Import 2]   │
└──────────────────────────────────────────────────────────────────────────────┘
```

A wrong type/size, malformed header, partial failure, or duplicate is a named inline error. The dialog does not promise Excel support unless a real parser is shipped.

### 4.4 Rebalance dry run

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Rebalance plan                                                            [×] │
│ [Dry run] No portfolio records will be changed.                                │
│ Current value: ₹1.25 Cr · Target weights must reconcile to the selected set.  │
│                                                                              │
│ Ticker          Current   Target    Δ weight    Shares Δ       Action        │
│ 3MINDIA.NS      18.20%    16.00%    −2.20%      −12            Sell           │
│ INFY            12.40%    15.00%    +2.60%      +18            Buy            │
│ ...                                                                              │
│ Turnover: 8.40% · Buy: ₹32.50 L · Sell: ₹32.50 L                             │
│ [Back]                                           [Confirm rebalance]         │
└──────────────────────────────────────────────────────────────────────────────┘
```

The live mutation is a separate, explicit confirmation. The screen never labels a dry run as executed.

### 4.5 Manage states

```text
LOADING: table skeleton; Add/Import remain disabled until portfolio total is known.
EMPTY:   no positions card; no invented total value or weight.
ERROR:   actual detail, Retry, preserve last good table if available.
STALE:   last good rows + [STALE] as-of banner; new actions ask for refresh.
PARTIAL: row-level N/A for missing price/sector; successful rows remain visible.
```

## 5. Risk workspace — Risk Studio and route-family template

The individual risk routes remain separate URLs, but they share this frame so users can move between evidence, explanation, and action without learning a new visual language.

### 5.1 Risk Studio success state

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ Risk Studio                         Window: 252 sessions   [Refresh] [Export panel data]     │
│ Current portfolio · NIFTY diagnostics · source/as-of: per panel                             │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ [Euler contribution]       [Volatility cone]       [Correlation stability] [Tail risk]      │
│ ┌───────────────────────┐   ┌─────────────────────┐  ┌─────────────────────┐  ┌──────────────┐ │
│ │ 3MINDIA.NS   24.1%    │   │ Min       12.8%    │  │ Regime: [N/A]       │  │ VaR 99: N/A │ │
│ │ INFY         18.7%    │   │ Max       31.4%    │  │ Rolling avg: —      │  │ Method: EVT │ │
│ │ ...                     │   │ Current   18.4%    │  │ [PARTIAL]           │  │ [STALE]     │ │
│ │ Source: /risk-contribution│ │ Source: /vol-cone │  │ Source: /corr...    │  │ Source: —   │ │
│ └───────────────────────┘   └─────────────────────┘  └─────────────────────┘  └──────────────┘ │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Selected diagnostic                                                                        │
│ [signed contribution table]   [methodology]   [n/a fields are not zero]                     │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

The four panels have independent status. A failed correlation request produces an error/empty panel; it does not produce a green “NORMAL” chip. A missing tail map produces “insufficient tail observations,” not a zero contribution. Vol-cone `min`/`max` are labeled as an envelope unless the backend returns true percentiles.

### 5.2 Risk page state variants

```text
LOADING PANEL
┌──────────────────────────────┐
│ Loading contribution data…   │
│ ███████████  ███████████    │
└──────────────────────────────┘

ERROR PANEL
┌──────────────────────────────┐
│ Contribution data unavailable │
│ <backend detail>             │
│ [Retry panel]                │
└──────────────────────────────┘

NO DATA PANEL
┌──────────────────────────────┐
│ No aligned observations in   │
│ the selected window.         │
│ Change window or add history.│
└──────────────────────────────┘

PARTIAL PANEL
┌──────────────────────────────┐
│ 8/10 positions have data.    │
│ INFY: [N/A] · source/as-of —  │
└──────────────────────────────┘
```

### 5.3 Concentration route pattern

```text
Concentration · current portfolio · base INR · as-of —

Largest position       Top 3             HHI              Effective N       Diversification
31.20%                58.40%            0.18             5.56              42.00%
[source: /analytics/concentration]                         formula: Σw²      formula: 1/HHI

[position weight bars]                 [sector bars]
Single holding: 0.00% diversification (explicit rule)
Unknown sector: [UNKNOWN]              +N more: [Show]
```

The single-holding rule is a visible invariant, not an inferred “low risk” result. A null API response leaves all metric values `N/A` and shows the retry/empty state.

## 6. Equity Research — `/dashboard/equity-research`

### 6.1 Research shell and overview

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ Equity Research                                      [Open in portfolio] [Export model]       │
│ Ticker [ 3MINDIA.NS                         ] [Search]   Source/as-of: not provided          │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ 3MINDIA.NS · 3M IndiaForge Ltd.       [PARTIAL] Company data is provider-dependent            │
│ Quote [N/A]       Market cap ₹… Cr       P/E [N/A]       Sector [N/A]                         │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Overview | Shareholding | Con calls | Financials | Ratios | AI context                         │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Company facts / valuation / peer list                                                        │
│                                                                                                │
│ Field                         Value             Source/as-of     Status                          │
│ Current price                 [N/A]             not provided     unavailable                     │
│ Book value                    [N/A]             not provided     unavailable                     │
│ Peer set                      [N/A]             not provided     upstream list unavailable        │
│ Piotroski                     N/A               not provided     not computed                     │
│                                                                                                │
│ [NOT SHIPPED] News/sentiment and analyst estimates are not exposed by the current API.       │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

The “not shipped” note prevents a blank news area from looking like a successful empty feed. The AI context tab is explicitly labeled context/prompt generation, not a recommendation or an autonomous valuation model.

### 6.2 Research tab states

```text
SHAREHOLDING
┌──────────────────────────────────────────────┐
│ Period       Promoter    FII/FPI    DII       │
│ 2026 Q2      [N/A]       [N/A]      [N/A]     │
│ 2026 Q1      62.10%      18.20%     14.30%    │
│                                               │
│ Source: bfinance periods · as-of: not provided │
└──────────────────────────────────────────────┘

CONCALLS — ERROR
┌──────────────────────────────────────────────┐
│ Calls could not be loaded.                    │
│ Provider detail: <actual detail>              │
│ [Retry calls]                                 │
└──────────────────────────────────────────────┘

CONCALLS — EMPTY
┌──────────────────────────────────────────────┐
│ No call links were returned for this company.│
│ This is an empty result, not a vendor outage. │
└──────────────────────────────────────────────┘

TICKER SWITCH — ERROR
┌──────────────────────────────────────────────┐
│ Could not load 3MINDIA.NS.                    │
│ Previous company data has been cleared.       │
│ [Retry 3MINDIA.NS]                            │
└──────────────────────────────────────────────┘
```

A failed ticker switch must never leave the previous company's profile under the new ticker. Partial success is shown per tab, with a retry scoped to the failed endpoint.

## 7. Screener Studio — `/dashboard/screener-studio`

### 7.1 Strategy and result state

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ Screener Studio                                      [Run screen] [Reset filters]              │
│ India-listed cash equities · provider-dependent · max results 50                                │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Built-in strategies                                                                             │
│ [Coffee Can] [Magic Formula] [Debt-Free Compounders] [High Dividend] [Undervalued Growth]       │
│                                                                                                  │
│ Custom screen                                                                                    │
│ Min ROCE [15]  Min ROE [15]  Max P/E [22]  Min market cap [10,000]  Min yield [2.5]             │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Results: 23 stocks · run: 24 Sep 2026 · [STALE if result cache is older than policy]            │
│ ┌────────────┬──────────┬──────────┬────────┬────────┬────────┬──────────────────────────────┐ │
│ │ Ticker     │ Name     │ Price    │ MCap Cr│ P/E    │ ROCE   │ Action                       │ │
│ │ 3MINDIA.NS │ 3M India │ ₹2,245   │ 12,400 │ 28.2   │ 18.4%  │ [Add selected position]     │ │
│ │ ...                                                                                             │ │
│ └──────────────────────────────────────────────────────────────────────────────────────────────┘ │
│ 1–23 of 23 results                                                                               │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

`Add selected position` opens the normal position dialog. It computes a valid weight only after the current portfolio is successfully loaded: `100.00%` for a truly empty book, otherwise a value-share weight. It never sends `weight: 0` and never uses a bare browser alert.

### 7.2 Screener states

```text
LOADING STRATEGIES
[Loading available strategies…] [Run disabled until a strategy is selected]

STRATEGY ERROR
Could not load strategy list. <actual detail> [Retry strategies]

NO RESULTS
No stocks matched these filters. [Clear filters] [Adjust criteria]

RESULT ERROR
The screen did not complete. <actual detail> [Retry screen]

CUSTOM VALIDATION
Max P/E must be greater than 0. The screen was not run.

NOT SHIPPED
Saved screens, watchlists, and alerts are not available in the current backend.
```

The results table uses the shared table contract: sortable headers are keyboard buttons, filtered count is accurate, and a filtered empty result never says “Showing 1 to 0 of 0.”

## 8. Optimizer and rebalance handoff — `/dashboard/optimize`

### 8.1 Strategy state

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ Portfolio Optimizer                         [Run optimization] [Export plan]                    │
│ Existing holdings only · no new-ticker impact analysis                                         │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ [HRP] [Minimum volatility] [Maximum Sharpe] [Minimum CVaR] [Black-Litterman]                    │
│ Model assumptions: long-only · trailing sample · risk-free rate: backend/default                 │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Expected return       Expected volatility       Expected Sharpe       Solver                    │
│ [N/A]                 [N/A]                     [N/A]                 —                         │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Risk/return chart                                                                   │
│     • real optimal point only when both coordinates exist                                      │
│     • no synthetic frontier; no fabricated current point                                        │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Ticker          Current weight     Recommended weight     Δ weight        Action                │
│ ...                                                                                              │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

If expected return or volatility is null, the chart region says:

```text
Optimization coordinates unavailable.
The backend did not return a finite expected return/volatility pair.
[Run again]
```

### 8.2 Handoff to manage positions

```text
[Review dry-run rebalance]  →  /portfolio/manage?focus=rebalance

┌──────────────────────────────────────────────────────────────────────────────┐
│ Dry-run only · no records changed                                            │
│ Target weights: …                                                            │
│ Turnover: …     Buy: …     Sell: …                                          │
│ [Back to optimizer] [Open rebalance dialog]                                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

The target IA does not imply that the optimizer can add a new ticker. That is a documented backend gap, not a hidden form field.

## 9. Market diagnostics and goal probability

### 9.1 Pairs scanner

```text
Pairs Scanner · 252-session window · source/as-of: not provided

[Search pair] [Minimum p-value: 0.05] [Run scan]

Pair                 p-value       Half-life       z-score       Flag
INFY–HDFCBANK.NS     0.018         18.4 days      −1.82         Cointegrated
TCS–INFY             —             —              —             Insufficient data

[selected pair detail] [methodology] [export]
```

Cointegration is a diagnostic, not a recommendation or a valuation. Missing p-values, half-lives, and z-scores remain `—`.

### 9.2 India microstructure

```text
India Microstructure · Stored NSE-derived records · as-of: —

[STALE] This view reads stored records; unattended official NSE ingestion is not verified.

┌ Delivery spikes ┐  ┌ Institutional flows ┐  ┌ ADV limits ┐
│ Ticker  z-score │  │ Date  FII  DII     │  │ Ticker  days at 10% │
│ INFY    +2.4σ   │  │ —     —    —       │  │ INFY     N/A       │
└─────────────────┘  └────────────────────┘  └──────────────────┘
```

An empty result is shown only after the request succeeds. A failed request shows the actual detail and retry, never “No anomalies detected.”

### 9.3 Goal probability

```text
Goal Probability · current portfolio value · base INR

Target value [₹]     Horizon [5] years     Method [Bootstrap ▼]     Seed [42]
[Run simulation]

Probability of reaching target   [N/A until run]     Paths [10,000]       Historical μ/σ [—]
[fan chart with method, seed, and percentile legend]
```

GBM, Student-t, and bootstrap are explicit assumptions. A failed/empty fan is a named no-data state; it is not a flat line at zero.

## 10. Settings — `/dashboard/settings`

```text
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│ Settings                                                                                       │
│ Only controls persisted by the current backend are shown.                                      │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Data source preference                                                                         │
│ Primary source   [bfinance ▼]   Cache TTL [60] minutes   Enable cache [on/off]                  │
│ Unsaved changes: no                                                                           │
│ [Save data-source preference]                                                                 │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Cache management                                                                               │
│ Clear cached market, analytics, and NSE microstructure data. Holdings are preserved.           │
│ [Clear cache…]                                                                                │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│ Not configurable in the current API: currency conversion policy, benchmark selector,           │
│ risk-free rate, target volatility, and analytics lookback.                                     │
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

The target does not show placebo controls or a banner claiming that unsaved local state was applied. If those settings are added later, each needs a backend persistence contract and a visible as-of/source policy.

## 11. Reusable state snippets

### Loading

```text
┌──────────────────────────────────────────────┐
│ Loading <specific region>…                   │
│ ████████████████████████████████████████████ │
│ Preserve shell, title, and prior context.    │
└──────────────────────────────────────────────┘
```

### Error with backend detail

```text
┌──────────────────────────────────────────────────────────────┐
│ ⚠ <specific operation> failed                                 │
│ <FastAPI detail or typed AppError message>                    │
│ Last successful data: <as-of or not available>               │
│ [Retry] [Dismiss]                                             │
└──────────────────────────────────────────────────────────────┘
```

### Empty

```text
┌──────────────────────────────────────────────────────────────┐
│ <No positions / no matched rows / no observations>            │
│ <Why this is empty and what the user can do next>             │
│ [Relevant action]                                              │
└──────────────────────────────────────────────────────────────┘
```

### Stale or partial

```text
┌──────────────────────────────────────────────────────────────┐
│ [STALE] Last good data: 24 Sep 2026, 16:30 IST                 │
│ [PARTIAL] 8/10 aligned sessions · missing: INFY, TCS            │
│ Values below are last good values, not a fresh claim. [Refresh]│
└──────────────────────────────────────────────────────────────┘
```

## 12. Wireframe acceptance checklist

- [ ] Existing route URLs are represented without adding a new unsupported route.
- [ ] Every page has a title, context, source/as-of treatment, and explicit state handling.
- [ ] The shell never uses a fake “Live Data Active” status or unread badge.
- [ ] Empty portfolio and failed portfolio load are different states.
- [ ] First-position weight is visibly `100.00%` only after an actual empty portfolio is confirmed.
- [ ] No chart shows a synthetic frontier, pseudo-confidence interval, zero cone, or fabricated scenario.
- [ ] Matrix panels use `{ tickers, matrix }` correctly.
- [ ] Research tabs distinguish endpoint errors, valid empty results, and unavailable fields.
- [ ] Screener add-to-portfolio uses a valid weight and the standard position dialog.
- [ ] Optimizer and Monte Carlo disclose assumptions and null results.
- [ ] India flows are labeled as stored/limited data, not guaranteed live official ingestion.
- [ ] News, estimates, TE/IR, transaction-derived returns, saved workflows, and futures/options are not shown as available features.
