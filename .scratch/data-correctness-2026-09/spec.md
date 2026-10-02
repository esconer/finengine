# Data Completeness & Correctness — Master Spec

Status: ready-for-agent
Date: 2026-09-27
Scope: `C:\es\coding\bfinance` (v0.1.3 → 0.2.0) and this repo (backend + frontend)
Method: 6 parallel read-only research subagents, cross-referenced. Static reads plus targeted
live probes (bfinance pytest against live screener.in + real yfinance 1.7.0, ~10 numeric harnesses).

## Locked decisions

| Decision | Choice |
|---|---|
| Sequencing | Full spec first, then implement phase by phase |
| bfinance release | **0.2.0, breaking.** Keep 1:1 yfinance parity as the contract. Native statement shape removed |
| `stock_timeseries` cache | **Purge and full refetch** (assumes synthetic contamination — see `p0-preflight/issues/02`) |
| bfinance consumers | Unconfirmed — see Open Questions. Determines whether 0.2.0 can be a clean break |

## Verdict

**Not all the data is being obtained.** 130+ findings collapse into 5 root causes.

| # | Root cause | Severity |
|---|---|---|
| RC1 | bfinance **fabricates OHLC** (`Open=prev_close`, `High/Low=±0.2% envelope`) and sets `df.attrs["bfinance_synthetic_ohlc"]=True` — which this app **never reads** | CRITICAL |
| RC2 | bfinance statement column order is **ascending** vs yfinance **descending**; `company_data_service.py:347` calls those methods directly | CRITICAL |
| RC3 | India ingestion layer is 4 tables + a service with **no fetcher and no scheduler** — structurally guaranteed empty | HIGH |
| RC4 | Unit contract undeclared: `market_cap` has 4 spellings in 3 units; the frontend sniffs scale with `Math.abs(v)<=1.0` | HIGH |
| RC5 | Both layers return plausible numbers where there is no measurement — violates `CONTEXT.md` §9.23 | CRITICAL |

**Structural gap, upstream of most of Phase 5:** there is no book of record. No `transactions`
table, no lot ledger, no cash. `performance-history` reconstructs history as
`quantity × past_price`, so every "realized" figure is a hypothetical buy-and-hold of today's
book. Compounded by `config.py:53 risk_free_rate = 0.02` (India is 5–7.5%) and a price-only
`^NSEI` benchmark (~1.2–1.4%/yr understated).

## Phase index

**108 tickets across 6 phase directories.** Each phase is a self-contained feature slice with its
own `spec.md` carrying the detailed tables, formulas, and acceptance criteria.

| Phase | Dir | Tickets | Gate |
|---|---|---|---|
| 0 | `p0-preflight/issues/` | 4 | Answers required before scoping Phase 1 |
| 1 | `p1-bfinance-0.2.0/issues/` | 22 | **01 is a gate** — the suite currently certifies the bugs as correct |
| 2 | `p2-data-layer/issues/` | 21 | 01 + 02 must ship with Phase 1's 03 (real OHLCV) |
| 3 | `p3-honesty-correctness/issues/` | 28 | Breaking API changes — frontend and backend in the same PR |
| 4 | `p4-india-producers/issues/` | 11 | 01 and 02 first; the readers are currently broken |
| 5 | `p5-capability/issues/` | 21 | 12 (lot ledger) blocks 11, 13, 16 |

### Phase 0 — Pre-flight (4)

| # | Ticket | Answers |
|---|---|---|
| 01 | [Verify the NSE CM bhavcopy endpoint](p0-preflight/issues/01-verify-nse-bhavcopy-endpoint.md) | Does the UDiFF URL resolve? Exact header row? Does pre-2024 history work? |
| 02 | [Audit `stock_timeseries` contamination](p0-preflight/issues/02-audit-stock-timeseries-contamination.md) | Row count, date range, per-source breakdown. Sizes the purge |
| 03 | [Confirm bhavcopy publish time](p0-preflight/issues/03-confirm-bhavcopy-publish-time.md) | Is an 18:30 IST cron reading yesterday's file? |
| 04 | [Confirm bfinance install mode](p0-preflight/issues/04-confirm-bfinance-install-mode.md) | PyPI pin or local path? Determines release sequencing |

### Phase 1 — bfinance 0.2.0, breaking (21)

| # | Ticket | Severity |
|---|---|---|
| 01 | [Repair the test suite](p1-bfinance-0.2.0/issues/01-repair-test-suite.md) | **GATE** |
| 02 | [Record pre-flight results](p1-bfinance-0.2.0/issues/02-record-preflight-results.md) | — |
| 03 | [Real OHLCV from the bhavcopy](p1-bfinance-0.2.0/issues/03-real-ohlcv-from-bhavcopy.md) | **CRITICAL** |
| 04 | [Statement shape → yfinance parity](p1-bfinance-0.2.0/issues/04-statement-shape-yfinance-parity.md) | **CRITICAL** |
| 05 | [Real corporate actions](p1-bfinance-0.2.0/issues/05-real-corporate-actions.md) | **CRITICAL** |
| 06 | [Cache overhaul](p1-bfinance-0.2.0/issues/06-cache-overhaul.md) | **CRITICAL** |
| 07 | [`resolve_company_id` exact match](p1-bfinance-0.2.0/issues/07-resolve-company-id-exact-match.md) | **CRITICAL** |
| 08 | [Unit fixes](p1-bfinance-0.2.0/issues/08-unit-fixes.md) | HIGH |
| 09 | [Delete the fabricated data paths](p1-bfinance-0.2.0/issues/09-delete-fabricated-paths.md) | HIGH |
| 10 | [Eliminate the silent no-ops](p1-bfinance-0.2.0/issues/10-eliminate-silent-no-ops.md) | HIGH |
| 11 | [Ragged-row padding](p1-bfinance-0.2.0/issues/11-ragged-row-padding.md) | MED |
| 12 | [Fix the AI dossier markdown](p1-bfinance-0.2.0/issues/12-fix-ai-context-markdown.md) | MED |
| 13 | [Screener error surfacing](p1-bfinance-0.2.0/issues/13-screener-error-surfacing.md) | MED |
| 14 | [yfinance parity surface](p1-bfinance-0.2.0/issues/14-yfinance-parity-surface.md) | MED |
| 15 | [`nse.macro`: India VIX, TRI, RBI rate](p1-bfinance-0.2.0/issues/15-nse-macro-india-vix-tri.md) | S |
| 16 | [`costs`: date-keyed schedule](p1-bfinance-0.2.0/issues/16-costs-date-keyed-schedule.md) | S |
| 17 | [`flows`: FII/DII + AMFI](p1-bfinance-0.2.0/issues/17-flows-fii-dii-amfi.md) | S |
| 18 | [`universe`: index membership](p1-bfinance-0.2.0/issues/18-universe-index-membership.md) | S/M |
| 19 | [`ownership`: pledge, bulk deals](p1-bfinance-0.2.0/issues/19-ownership-pledge-bulk-deals.md) | M |
| 20 | [`derivatives`: real option chain](p1-bfinance-0.2.0/issues/20-derivatives-real-option-chain.md) | M |
| 21 | [Licensing and provenance docs](p1-bfinance-0.2.0/issues/21-licensing-provenance-docs.md) | S |
| 22 | [**`nse.marketlens`: NSE close + volume**](p1-bfinance-0.2.0/issues/22-nse-marketlens-close-volume.md) | **RESOLVED** |

### Phase 2 — finengine data layer (20)

| # | Ticket | Severity |
|---|---|---|
| 01 | [Read `bfinance_synthetic_ohlc` at ingestion](p2-data-layer/issues/01-read-synthetic-ohlc-flag.md) | **CRITICAL** |
| 02 | [Purge `stock_timeseries` and refetch](p2-data-layer/issues/02-purge-and-refetch-cache.md) | **CRITICAL** |
| 03 | [Raise instead of returning `None`](p2-data-layer/issues/03-raise-instead-of-return-none.md) | **CRITICAL** |
| 04 | [Per-vendor normalization adapter](p2-data-layer/issues/04-per-vendor-normalization-adapter.md) | **CRITICAL** |
| 05 | [Add `source` to the cache key](p2-data-layer/issues/05-cache-key-source-dimension.md) | HIGH |
| 06 | [Wire the real L1 TTL](p2-data-layer/issues/06-wire-real-l1-ttl.md) | MED |
| 07 | [Real retry backoff](p2-data-layer/issues/07-retry-backoff.md) | HIGH |
| 08 | [Record cascade fallbacks](p2-data-layer/issues/08-record-cascade-fallbacks.md) | HIGH |
| 09 | [Portfolio refresh must not serve stale as live](p2-data-layer/issues/09-portfolio-stale-price-honesty.md) | **CRITICAL** |
| 10 | [WebSocket ticker honesty](p2-data-layer/issues/10-websocket-ticker-honesty.md) | **CRITICAL** |
| 11 | [Shareholding `NaN` → `None`](p2-data-layer/issues/11-shareholding-nan-to-none.md) | **CRITICAL** |
| 12 | [Resolve the Tier-3 dead branch](p2-data-layer/issues/12-alpha-vantage-tier3-dead.md) | HIGH |
| 13 | [`_db_lock` coverage](p2-data-layer/issues/13-db-lock-coverage.md) | MED |
| 14 | [Timezone parity](p2-data-layer/issues/14-timezone-parity.md) | MED |
| 15 | [`dropna` compresses the time axis](p2-data-layer/issues/15-dropna-compresses-time-axis.md) | MED |
| 16 | [Wire `get_corporate_actions`](p2-data-layer/issues/16-wire-corporate-actions-route.md) | MED |
| 17 | [Screener source and status honesty](p2-data-layer/issues/17-screener-source-status-honesty.md) | HIGH |
| 18 | [Preserve the vendor name on errors](p2-data-layer/issues/18-preserve-vendor-name-on-errors.md) | MED |
| 19 | [Log identifiers and redaction](p2-data-layer/issues/19-log-identifiers-and-redaction.md) | MED |
| 20 | [Remove dead code](p2-data-layer/issues/20-remove-dead-code.md) | LOW |
| 21 | [**Close/volume reconciliation vs NSE**](p2-data-layer/issues/21-close-volume-reconciliation.md) | HIGH |
| 22 | [**Source degradation contract**](p2-data-layer/issues/22-source-degradation-contract.md) | HIGH |

### Phase 3 — Honesty and quantitative correctness (28)

| # | Ticket | Severity |
|---|---|---|
| 01 | [Delete the fabricated `EXPLAINERS`](p3-honesty-correctness/issues/01-delete-fabricated-explainers.md) | HIGH |
| 02 | [`stress-testing` is not a simulation](p3-honesty-correctness/issues/02-stress-testing-not-a-simulation.md) | HIGH |
| 03 | [`portfolio/manage` unit + badge bugs](p3-honesty-correctness/issues/03-portfolio-manage-unit-and-badge-bugs.md) | **CRITICAL** |
| 04 | [`pairs` z-score crash](p3-honesty-correctness/issues/04-pairs-zscore-crash.md) | **CRITICAL** |
| 05 | [Missing transport-error states](p3-honesty-correctness/issues/05-missing-transport-error-states.md) | HIGH |
| 06 | [`liveDataMode` pill honesty](p3-honesty-correctness/issues/06-live-data-pill-honesty.md) | MED |
| 07 | [Small frontend truthfulness](p3-honesty-correctness/issues/07-small-frontend-truthfulness.md) | LOW/MED |
| 08 | [Degenerate concentration returns](p3-honesty-correctness/issues/08-degenerate-concentration-returns.md) | HIGH |
| 09 | [`_empty_concentration` scored](p3-honesty-correctness/issues/09-empty-concentration-fabricated-score.md) | HIGH |
| 10 | [`annual_return` time base](p3-honesty-correctness/issues/10-annual-return-time-base.md) | HIGH |
| 11 | [Black-Litterman wrong Sharpe](p3-honesty-correctness/issues/11-black-litterman-sharpe.md) | HIGH |
| 12 | [Stress vol zero-return days](p3-honesty-correctness/issues/12-stress-vol-zero-return-days.md) | HIGH |
| 13 | [WebSocket fabricated Sharpe](p3-honesty-correctness/issues/13-websocket-fabricated-sharpe.md) | HIGH |
| 14 | [Unify the three EWMAs](p3-honesty-correctness/issues/14-unify-ewma-implementations.md) | MED |
| 15 | [GARCH no √h](p3-honesty-correctness/issues/15-garch-multistep-no-sqrt-h.md) | MED |
| 16 | [Liquidity turnover formula](p3-honesty-correctness/issues/16-liquidity-turnover-formula.md) | MED |
| 17 | [Missing `Close` scored illiquid](p3-honesty-correctness/issues/17-missing-close-column-scored-illiquid.md) | MED |
| 18 | [CVaR signed normalization](p3-honesty-correctness/issues/18-cvar-contribution-signed-normalization.md) | MED |
| 19 | [Unoccupied HMM state](p3-honesty-correctness/issues/19-unoccupied-hmm-state-fabricated-cagr.md) | MED |
| 20 | [HMM convergence check](p3-honesty-correctness/issues/20-hmm-convergence-check.md) | MED |
| 21 | [Cointegration z-score `None`](p3-honesty-correctness/issues/21-cointegration-zscore-none.md) | MED |
| 22 | [Remaining degenerate zeros](p3-honesty-correctness/issues/22-remaining-degenerate-zeros.md) | MED |
| 23 | [Declare a `units` block](p3-honesty-correctness/issues/23-declare-units-block.md) | HIGH — **RC4** |
| 24 | [Delete scale sniffers](p3-honesty-correctness/issues/24-delete-scale-sniffing-formatters.md) | HIGH |
| 25 | [Unify outage status codes](p3-honesty-correctness/issues/25-unify-outage-status-codes.md) | MED |
| 26 | [`performance-history` hides warnings](p3-honesty-correctness/issues/26-performance-history-hides-warnings.md) | HIGH |
| 27 | [Real risk-free rate + TR benchmark](p3-honesty-correctness/issues/27-real-risk-free-rate-and-tr-benchmark.md) | HIGH |
| 28 | [Remove fabricated API defaults](p3-honesty-correctness/issues/28-remove-fabricated-api-defaults.md) | MED |

### Phase 4 — India data producers (11)

| # | Ticket | Effort |
|---|---|---|
| 01 | [Fix the never-emitting delivery guard](p4-india-producers/issues/01-fix-delivery-row-guard.md) | S |
| 02 | [Fix the bulk-deals column mismatch](p4-india-producers/issues/02-fix-bulk-deals-column-mismatch.md) | S |
| 03 | [FII/DII producer](p4-india-producers/issues/03-fii-dii-producer.md) | S |
| 04 | [Delivery % producer](p4-india-producers/issues/04-delivery-percentage-producer.md) | S |
| 05 | [Bhavcopy producer + scheduler](p4-india-producers/issues/05-bhavcopy-producer-and-scheduler.md) | M |
| 06 | [Bulk/block deals producer](p4-india-producers/issues/06-bulk-block-deals-producer.md) | M |
| 07 | [Shareholding pattern producer](p4-india-producers/issues/07-shareholding-pattern-producer.md) | M |
| 08 | [India VIX series](p4-india-producers/issues/08-india-vix-series.md) | S |
| 09 | [Trade count and ₹ turnover](p4-india-producers/issues/09-trade-count-and-turnover.md) | S |
| 10 | [Derived circuit bands](p4-india-producers/issues/10-derived-circuit-bands.md) | S |
| 11 | [NSE volatility / VaR margin / ELM](p4-india-producers/issues/11-nse-volatility-varmargin-elm.md) | S |

### Phase 5 — New capability (21)

| # | Ticket | Score | Effort |
|---|---|---|---|
| 01 | [VaR/ES backtesting](p5-capability/issues/01-var-es-backtesting.md) | 45 | **S** |
| 02 | [Ledoit-Wolf shrinkage](p5-capability/issues/02-ledoit-wolf-shrinkage.md) | 40 | S |
| 03 | [Tracking error / active risk / IR](p5-capability/issues/03-tracking-error-active-risk-ir.md) | 40 | S |
| 04 | [Specific risk decomposition](p5-capability/issues/04-specific-risk-decomposition.md) | 35 | S |
| 05 | [Drawdown-path risk](p5-capability/issues/05-drawdown-path-risk.md) | 35 | S |
| 06 | [Risk policy limits](p5-capability/issues/06-risk-policy-limits.md) | 32 | S |
| 07 | [NSE sector index returns](p5-capability/issues/07-nse-sector-index-returns.md) | 35 | S |
| 08 | [Historical scenario replay](p5-capability/issues/08-historical-scenario-replay.md) | 28 | S/M |
| 09 | [Bootstrap confidence intervals](p5-capability/issues/09-bootstrap-confidence-intervals.md) | 28 | S/M |
| 10 | [Cornish-Fisher + spectral risk](p5-capability/issues/10-cornish-fisher-and-spectral-risk.md) | 24 | S |
| 11 | [Pre-trade what-if](p5-capability/issues/11-pre-trade-what-if.md) | 28 | M |
| 12 | [**Lot / transaction ledger**](p5-capability/issues/12-lot-transaction-ledger.md) | **50** | **L** |
| 13 | [Tax-aware rebalancing](p5-capability/issues/13-tax-aware-rebalancing.md) | 36 | M |
| 14 | [Brinson attribution](p5-capability/issues/14-brinson-attribution.md) | 32 | S/M |
| 15 | [Factor breadth](p5-capability/issues/15-factor-breadth-sector-and-style.md) | 32 | L |
| 16 | [Portfolio snapshots](p5-capability/issues/16-portfolio-snapshots.md) | 28 | M |
| 17 | [Liquidity-adjusted VaR](p5-capability/issues/17-liquidity-adjusted-var.md) | 24 | M |
| 18 | [Point-in-time fundamentals](p5-capability/issues/18-point-in-time-fundamentals.md) | 24 | M |
| 19 | [FX history](p5-capability/issues/19-fx-history.md) | 30 | S |
| 20 | [MCTR and risk budgeting](p5-capability/issues/20-mctr-and-risk-budgeting.md) | 30 | S |
| 21 | [Regime-conditional forecast](p5-capability/issues/21-regime-conditional-forecast.md) | 18 | M |

## Data sources — verified 2026-09-26

Three official NSE routes were probed live. They are **complementary, not interchangeable**, and
knowing which is which prevents the one mistake that would undo RC1.

| Source | Auth | Depth | Gives | Does **not** give |
|---|---|---|---|---|
| CM bhavcopy | none, static ZIP | UDiFF from 2008-07-08 | **real O/H/L/C/V** | — |
| **MarketLens** | **none at all** | **30Y, from 1996** | close + volume, **exact** | **no O/H/L** |
| `/api/*` | session cookie | varies | FII/DII, deals, filings | close — and `quote-equity` **403s from datacenter IPs** |

MarketLens is the only source in this spec with **zero anti-bot exposure**, verified by direct
probe: a bare request with no cookie, no session, and no `Referer` returns `200`.

**The invariant:** a close-only frame must never be coerced into an OHLCV shape. Issue 22 sets
`attrs["bfinance_marketlens_partial_coverage"] = True` so that mistake is detectable rather than silent.
Making it would recreate the exact RC1 bug the bhavcopy work exists to fix.

## Critical path

```
p0-01..04  (pre-flight)
   ↓
p1-01  test-suite repair  ← GATE. The suite asserts isinstance(c, str) on statement
   ↓                       columns, so fixing 04 without this yields "regressions"
p1-03 real OHLCV  ·  p1-04 statement shape  ·  p1-05 corporate actions
p1-22 marketlens  ← no upstream dependency; buildable immediately
   ↓
p2-01 synthetic-frame guard  +  p2-02 purge & refetch   ← MUST ship together with p1-03
p2-21 reconciliation vs NSE                            ← needs p1-22
   ↓
p3 crash fixes (03, 04)  →  honesty (01, 02)  →  quant correctness (08–22)  →  units (23–28)
   ↓
p4-01/02 schema bugs  →  p4-03..07 producers  →  p4-08..11 derived series
   ↓
p5-01 VaR backtest  →  02/03  →  04–08  →  12 lot ledger  →  13 tax-aware rebalance
```

## Triage status

| Label | Count | Meaning |
|---|---|---|
| `ready-for-agent` | 92 | Fully specified, with `file:line` targets and acceptance criteria |
| `needs-info` | 14 | Blocked on an owner decision, not on missing investigation |
| `resolved` | 1 | Phase 1 issue 22, shipped 2026-09-27 |

The 14 `needs-info` tickets are gated on a decision, and the decision is listed against each:

| Open question | Tickets |
|---|---|
| **1** — is bfinance consumed by anything besides this app? (determines whether 0.2.0 can be a clean break) | p1-04, p1-05, p1-10, p1-14 |
| **2** — should `sector.py` be deleted or made live? | p1-09 |
| **3** — how much synthetic data is in SQLite? (bulk purge vs lazy refetch) | p2-02 |
| **4** — are the 4 India tables already in production use? | p4-03, p4-04, p4-05, p4-06, p4-07 |
| **5** — should the lot ledger import from a broker export or take manual entry? | p5-12 |
| Tier-count decision — implement Alpha Vantage for `.NS`/`.BO`, or accept a 2-tier cascade? | p2-12 |
| Risk-free source — configured dated rate, or a live RBI series? | p3-27 |

Each of these tickets states the decision it needs in its own `## What` or `## Change` section, so
an agent picking one up knows exactly what to ask for.

## Non-goals

Full list with rationale in §"Explicit non-goals" of each phase spec. Summary:

- **Data sources:** NSE Level-2 / Post-Trade FTP (licensed), "short interest" (does not exist
  in India), Prowess/CMIE, Bloomberg consensus, BSE Web Forms scraping, per-symbol circuit-limit
  tables (must be derived), RBI DBIE, and extending `sector.py` as-is.
- **Brave Search `search.brave.com/api/rhfetch/stocks`** — probed and rejected, evidence below.
- **Features:** Basel FRTB, Kelly leverage, a full Barra clone, correlation-network centrality,
  analyst estimate revisions, corporate bond/credit, more dashboard pages, multi-entity accounting.
- **Do not regress:** `analyst_price_targets` returning `None` (`ticker.py:351-360`). Free India
  consensus is ToS-prohibited and unreliable.

### Rejected: Brave Search `rhfetch` finance endpoint

Proposed as a second fallback for ETFs, BSE, and global stocks. **Probed 2026-09-26 and rejected.**

```
https://search.brave.com/api/rhfetch/stocks?symbol={SYM}&range={R}&exchange={EX}
```

**429 on every request**, including both examples supplied:

| Probe | Result |
|---|---|
| `AAPL&range=1m&exchange=NASDAQ` | 429 |
| `RELIANCE.BO&range=5y&exchange=BSE` | 429 |
| `NIFTYBEES.NS&range=ytd&exchange=NSE` | 429 |
| All 10 range variants (1d…max, both cases) | 429 |
| NSE / BSE × suffix / no-suffix / mismatch | 429 |
| Global: AAPL, MSFT, GOOGL × NASDAQ, NAS | 429 |
| **`https://search.brave.com/` homepage** | **429** |
| **`https://search.brave.com/search?q=reliance`** | **429** |
| Cookies obtained during priming | **0** |

Retried with full browser headers (`sec-ch-ua`, `sec-fetch-*`, a cookie jar primed from the real
search page) at 3 s spacing. The block page carries
`<meta name="robots" content="noindex,nofollow">` — Brave is refusing the whole **origin** from this
IP, not just the API path.

Three independent reasons not to build on it even if it were reachable:

1. **`rhfetch` is Brave's internal UI endpoint**, not their documented Search API. No docs, no SLA,
   no versioning. It can change without notice and there is no contract behind it.
2. **Brave's ToS prohibits automated scraping.** Unlike the NSE bhavcopy (free public
   dissemination) or AMFI NAV (statutorily mandated), there is no clean licensing position.
3. It is the same class of dependency as screener.in — a single-source scrape with a commercial
   ToS — so it would **add** systemic risk to bfinance rather than diversify it.

A source reachable only from a real browser is not a data source. **MarketLens (Phase 1 issue 22)
covers the same redundancy need with an official, zero-auth source.**

## Verification gates

| Layer | Gate |
|---|---|
| bfinance | Suite must **fail** if the statement-shape fix regresses. `live` marker enforced in CI. Property test: fresh bfinance `Ticker` and fresh yfinance `Ticker` on one symbol produce equal-shaped frames, and `iloc[:,0]` is the newest period in both |
| backend | Extend `tests/test_quantitative_invariants.py` with the Phase 3 quant tickets. `pytest --cov-fail-under=80` and ruff `E9`+`F` stay green |
| frontend | Component tests asserting `N/A` rendering for each `0.0`→`None` change, the `pairs` null guard, `portfolio/manage` ×100, and that no explainer string contains an unbound percentage |
| end-to-end | After the purge: no `stock_timeseries` row has a synthetic-OHLC marker, and a spot-check ticker matches yfinance O/H/L/C within 0.01% |
| contract | Snapshot the `/api/v1` OpenAPI schema before and after Phase 3. Every `0.0`→`None` change is a deliberate breaking contract change |

## Tests that currently encode buggy behaviour

These will need updating when the fixes land:

- `backend/tests/test_source_preference_and_cache.py:37-53` — hand-built frame, no real-vendor test
- any test asserting `0.0` from a degenerate series
- any frontend test snapshotting an explainer panel
- `bfinance/tests/test_parity_statements.py:93` — `assert all(isinstance(c, str) for c in df.columns)`
- `bfinance/tests/test_parity_info.py:42` — constructs a scenario that cannot occur in production
- `bfinance/tests/conftest.py:13` — the `:memory:` cache fixture is a no-op

## Open questions for the owner

1. **Is bfinance consumed by anything other than this app?** Issues 06, 07, 08, 13 are breaking.
   A 0.2.0 is a clean break only if you are the sole consumer.
2. **Should `sector.py` be deleted or made live?** `p1-12` assumes delete-or-source.
   `Industry.top_companies` is already empty for any key outside a 4-entry map.
3. **How much synthetic data is in SQLite?** `p0-02` answers this; the answer changes the Phase 2
   migration from bulk refetch to lazy per-ticker.
4. **Are the 4 India tables already in production use** (manual CSV loads)? `p4-03..07` assume the
   tables are empty and the readers are untested against real rows.
5. **Should the lot ledger import from a real broker export** (Zerodha/Groww/AngelOne) or accept
   manual entry first? `bulk_add` already parses the CSV shape.

## Phase specs

Each phase directory carries the detailed tables, formulas, and acceptance criteria for its
tickets. Read the phase `spec.md` before working its tickets.

- `p0-preflight/spec.md`
- `p1-bfinance-0.2.0/spec.md`
- `p2-data-layer/spec.md`
- `p3-honesty-correctness/spec.md`
- `p4-india-producers/spec.md`
- `p5-capability/spec.md`
