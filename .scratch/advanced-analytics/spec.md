# Spec: Advanced Analytics — the "not on free sites" tier

Status: draft · Owner: sukanta · Created: 2026-08-25
Depends on: `.scratch/project-state/current-state.md` (truth-pass items in its §8)

---

## 0. Goal

Turn Daisy Risk Engine from "portfolio tracker with demo analytics" into a **Bloomberg-grade
decision terminal** for an Indian equity portfolio. Every feature must answer a concrete
question about money: *what to hold, what to trim, when to de-risk, how bad can it get,
how much can I actually own, what is smart money doing.*

**Non-goals:** real-time tick data, order execution, algo trading, multi-user SaaS, and
— critically — **anything a free site already shows well.**

## 1. The filter test (your rule, formalized)

| Free sites already do this (Yahoo / TradingView / Screener.in / Chartink) | → We DON'T build it |
|---|---|
| Price charts, candlesticks, SMA/EMA/RSI/MACD/Bollinger | ❌ |
| Basic fundamentals ratios (P/E, ROE), screener filters | ❌ |
| News feeds, dividend history, simple return trackers | ❌ |
| Simple pie-chart allocation, basic beta/vol numbers | ❌ |

| Free sites DON'T do this | → We build it |
|---|---|
| Portfolio-level factor/risk decomposition of YOUR actual holdings | ✅ |
| Optimization under constraints (CVaR, HRP, Black-Litterman, risk parity) | ✅ |
| Regime detection + regime-conditional portfolio behavior | ✅ |
| Monte Carlo goal probabilities with fat tails | ✅ |
| EVT tail risk, copula tail-dependence ("which pairs crash together") | ✅ |
| Cointegration/pairs screening within your own universe | ✅ |
| Liquidity-constrained position sizing (days-to-liquidate) | ✅ |
| India microstructure: delivery %, FII/DII flows, bulk deals, shareholding deltas | ✅ |

## 2. Resource map — never rebuild the wheel

### Already in `backend/pyproject.toml`, currently UNUSED (free wins)
| Library | Gives us | Where it plugs in |
|---|---|---|
| **riskfolio-lib** | 20+ portfolio optimization models (HRP, CVaR-opt, max-diversification, risk parity/budgeting, Black-Litterman, hierarchical clustering, worst-case OPT) | Optimization Studio — almost zero new code for the math |
| **PyPortfolioOpt** | classic MVO, efficient frontier, LSC | fallback/complement to riskfolio |
| **quantstats** | full pro tear-sheet: omega, tail ratio, capture ratios, Calmar/Sterling/Burke, monthly heatmap, underwater plots | replace hand-rolled metrics in `analytics_engine.py` |
| **QuantLib** | fixed income / derivatives math if ever needed | shelf for now |

### New dependencies (small, deliberate)
| Library | Gives us | Notes |
|---|---|---|
| `hmmlearn` | Gaussian HMM market-regime detection | stable, sklearn-family |
| `pandas-ta-openbb` | 130+ indicators if/when wanted | **NOT** plain `pandas-ta` — original is abandoned & numpy-2-broken; this fork is maintained (verified Aug 2026) |
| `nsepythonserver` (or direct NSE archive endpoints) | bhavcopy, delivery %, FII/DII, bulk deals, derivatives reports | India edge; needs browser-like headers + caching |
| `statsmodels` (have it) | Engle-Granger/Johansen cointegration, Markov-switching models | already installed |
| Optional later: `vectorbt` (backtesting overlays), `financepy` (options Greeks/IV surface), `transformers`+FinBERT (news sentiment) | — | Tier E only |

### Reference architectures (study, don't embed)
- **OpenBB** (AGPL) — how they structure providers/routers/extensions. AGPL means don't copy code into your app unless you accept AGPL for the whole thing; borrow patterns instead. Its MCP/data-provider design is worth reading.
- **Microsoft qlib** — factor-evaluation workflow ideas if you ever go ML.

---

## 3. Features → decisions (the contract each feature must satisfy)

| # | Feature | Question it answers | Decision it informs |
|---|---|---|---|
| F1 | Holdings-truth plumbing (benchmark ^NSEI cached, all analytics read DB positions) | "Is any of this real?" | prerequisite for everything |
| F2 | Pro tear-sheet (quantstats): omega, tail ratio, up/down capture, monthly heatmap, underwater | "Is my portfolio healthy vs NIFTY?" | hold course vs investigate |
| F3 | Risk contribution (Euler decomposition: % of portfolio vol/CVaR per position & sector) | "Where does my risk actually come from?" | which positions to trim |
| F4 | **Optimization Studio** (riskfolio-lib): pick model (HRP/CVaR/BL/risk-parity/max-div), constraints (min/max weight, sector caps), efficient frontier, current→optimal trade list | "What SHOULD I hold?" | rebalancing with evidence |
| F5 | Regime engine (HMM on NIFTY returns+vol): current regime label, portfolio's historical behavior IN that regime, banner alerts | "Is the tape hostile right now?" | de-risk vs stay invested |
| F6 | Monte Carlo goal engine (block-bootstrap + Student-t, 10k paths): P(portfolio > target in 12m), drawdown distribution | "Can I hit my number? How bad is bad?" | savings rate / exposure changes |
| F7 | Tail suite: EVT-POT VaR + copula tail-dependence matrix | "What's my true worst case, and which holdings die together?" | hedging / concentration cuts |
| F8 | Correlation stability monitor (rolling corr regime-break alerts) | "Is diversification working TODAY?" | reduce gross exposure when corrs spike |
| F9 | Volatility cone & term structure (realized 10–252d vs GARCH forecast band) | "Is current vol cheap or rich?" | option hedges / timing entries |
| F10 | Cointegration scanner (holdings + watchlist): EG & Johansen tests, half-life | "Any relative-value pairs here?" | pair trades within universe |
| F11 | Liquidity limits: days-to-liquidate @ 10/20% ADV participation, Amihud illiquidity score | "How much of X can I actually own?" | position size caps |
| F12 | India flows dashboard: delivery % anomalies, FII/DII daily flows, bulk/block deals, quarterly shareholding deltas (promoter pledge!) | "What is smart money doing in MY names?" | conviction check / early exits |
| F13 | One-click PDF portfolio review (front-end jsPDF already installed) | "Summarize all of the above" | actual review ritual |

## 4. Backend shape (new modules, same patterns)

```
app/services/
  benchmark_service.py      # ^NSEI / NIFTYBEES.NS once-daily fetch → stock_timeseries
  optimization_service.py   # wraps riskfolio-lib; constraints DTO in, weights+frontier out
  regime_service.py         # hmmlearn fit on cached index returns; regime labels + persistence
  simulation_service.py     # block-bootstrap Monte Carlo; EVT fits (scipy genpareto)
  india_data_service.py     # NSE archives: bhavcopy/delivery%, FII/DII, bulk deals, shareholding
app/api/
  optimize.py    # POST /api/v1/optimize/run, GET /api/v1/optimize/frontier
  advanced.py    # /tear-sheet /risk-contribution /regime /monte-carlo /tails /vol-cone /coint /liquidity-limits
  india.py       # /flows/fii-dii /flows/delivery /deals/bulk /shareholding-delta
```
- Heavy jobs run as FastAPI BackgroundTasks; results land in the **currently-unused `analytics_cache`**
  table keyed `(portfolio_fingerprint, feature, params_hash)` with TTL — invalidates on portfolio change.
- Reuse existing DataService cache for all price input; no second source of prices.
- Keep single-user, no-auth posture.

## 5. Frontend shape (reuse components; new routes)

| Route | Content | Reuses |
|---|---|---|
| `/dashboard` upgrade | regime banner strip (F5) replaces fake "Live Data Active"; real change-deltas | MetricCard |
| `/analytics/tear-sheet` | quantstats tables + monthly heatmap + underwater chart (F2) | DataTable, charts |
| `/analytics/risk-studio` | risk contribution sunburst/bar + tail-dependence heatmap + vol cone (F3,7,8,9) | Recharts |
| `/optimizer` | model picker, constraint form, frontier line, current↔optimal diff table w/ trade list (F4) | forms + DataTable |
| `/analytics/monte-carlo` | fan chart + goal-probability slider (F6) | PerformanceChart pattern |
| `/pairs` | cointegration matrix + half-life table (F10) | DataTable |
| `/india-flows` | FII/DII bars, delivery-% anomalies, bulk-deal feed (F12) | new, simple |

Delete on sight: mock websocket broadcasts, fake MetricCard deltas, mock `usePerformanceData`.

## 6. Phasing (tracer bullets — every phase ends usable)

| Phase | Scope | Est. sessions | Exit proof |
|---|---|---|---|
| **P0 Truth pass** | current-state.md §8: wire analytics to DB positions, fix bulk_add validator, rebalance→normalize, consolidate HTTP client | 1 | every existing page reflects real holdings |
| **P1 Foundation** | benchmark ingestion + quantstats tear-sheet + Euler risk contribution (F1,F2,F3) | 2 | tear-sheet page renders for real portfolio vs NIFTY |
| **P2 Optimizer** | riskfolio integration + constraints + frontier + trade list (F4) | 2 | "rebalance" button opens evidence-backed suggestion |
| **P3 Uncertainty** | HMM regime + Monte Carlo goals + vol cone (F5,6,9) | 2-3 | regime banner live; P(goal) slider works |
| **P4 Tail & pairs** | EVT VaR, copula matrix, corr monitor, cointegration scan (F7,8,10) | 2 | tail-dependence heatmap + pairs candidates render |
| **P5 India edge** | NSE ingestion pipeline + flows dashboard (F12) + liquidity limits (F11) | 3 | FII/DII + delivery% update daily from cached bhavcopy |
| **P6 Polish** | PDF review report (F13), delete all remaining mocks, WS worker done-or-hidden | 1 | zero `_empty_*` canned payloads reachable in normal use |

## 7. Risks & mitigations

- **riskfolio/cvxpy on Windows**: solvers ship wheels (Clarabel/ECOS); pin versions, smoke-test import in P2 kickoff before building UI.
- **NSE blocks non-browser clients** aggressively; endpoints change. Mitigate: dedicated session w/ realistic headers, daily batch fetch (not on-request), raw-file cache under `data/nse/`, tolerate failures loudly-but-gracefully.
- **HMM instability on short series**: fit on NIFTY (^NSEI has decades of history), not individual names; fix random_state; fall back to simple 200d-vol regime classifier if HMM flips too often.
- **Copulas/EVT overkill risk**: implement AFTER Monte Carlo works; both share the returns-prep plumbing.
- **Scope creep into ML alpha**: explicitly deferred; plumbing first, predictions never before P6.

## 8. Acceptance for the whole spec

A stranger looking at any page can tell (a) it's computed from the user's actual holdings,
(b) what action the screen suggests, and (c) nothing shown also appears verbatim on Yahoo Finance.
