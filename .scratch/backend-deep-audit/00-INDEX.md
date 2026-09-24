# FinEngine backend independent deep audit — master index

**Audit date:** 2026-09-24  
**Context:** personal, single-user, localhost cash-equity portfolio and analytics application.  
**Mode:** documentation-only; no application, test, configuration, database, lockfile, or Git file was changed.  
**Permitted writes:** only `.scratch/backend-deep-audit/`.  
**Prior audit:** opened only after Wave 1; comparison is in [`crosscheck-vs-prior.md`](crosscheck-vs-prior.md).

## 1. Executive result

The current backend has substantial useful capability, but it is not yet a trustworthy decision terminal without a trust/data-quality spine and a coherent add-ticker impact layer. The most important findings are:

1. **Math:** the analytics-engine GARCH/EGARCH horizon conversion is wrong at multi-day horizons; pre-listing backfill distorts portfolio moments; initial-loss drawdown is omitted; EVT fitted-shape clipping and MFI scaling are wrong; the first-position zero-state weight is not forced to 100%.
2. **Contracts:** mixed-currency portfolio totals, a weight-insensitive tail cache, no-op persisted cache settings, provider partial-frame acceptance, response-schema drift, fallback provenance, and source-switch cache bypass can all produce plausible-looking but wrong results.
3. **Operations:** Compose/build/deployment paths are not a working reproducible deployment, and the deployment cleanup can prune the portfolio volume.
4. **Decision workflow:** the backend has most numerical ingredients for a non-mutating “add ticker X” analysis, but no coherent endpoint freezes funding, returns before/after deltas, and reports data quality.
5. **Product gap:** transaction history, complete benchmark-relative performance, field-level freshness/quality, risk decomposition, peer/earnings/event research, and ownership-quality workflows are more decision-moving than adding more model variants.

No P0 was confirmed under the localhost single-user threat model. This does not mean the WebSocket browser boundary is closed; see `code/01-api-layer.md:49-56`.

## 2. Coverage and artifacts

| Area | Report | Coverage | Findings/count basis |
|---|---|---|---:|
| API/entrypoint | [`code/01-api-layer.md`](code/01-api-layer.md) | 7 files, 4,678 lines: all `backend/app/api/*.py` plus `backend/main.py` | 26 |
| Core analytics/data/cache | [`code/02-core-services.md`](code/02-core-services.md) | 12 service-scope files plus direct contracts and 27 test-gap files | 23 |
| Quant/risk services | [`code/03-quant-services.md`](code/03-quant-services.md) | 12 quant-service files, 4,492 lines | 22 |
| Data/research providers | [`code/04-data-providers.md`](code/04-data-providers.md) | 22 service files, 7,924 lines, plus callers/contracts/tests | 27 |
| Foundation/operations | [`code/05-foundation.md`](code/05-foundation.md) | 40 source/operations files plus 10 test-gap files and read-only SQLite metadata | 23 |
| Risk/time-series quant | [`quant/verify-risk-timeseries.md`](quant/verify-risk-timeseries.md) | 19 model families; installed-library inventory; deterministic evidence | 19 families |
| Portfolio/correlation quant | [`quant/verify-portfolio-correlation.md`](quant/verify-portfolio-correlation.md) | 92 comparison cases; installed-library inventory; deterministic evidence | 92 cases |
| Bloomberg-class gap | [`gaps/bloomberg-gap.md`](gaps/bloomberg-gap.md) | 18 capabilities, 10 verified source families, 30 backlog rows | 18 / 30 |
| Stock research + add fit | [`gaps/stock-research-fit.md`](gaps/stock-research-fit.md) | 32 current areas, 25 metrics, 8 verified source families, 12 backlog rows | 25 / 12 |
| Prior comparison | [`crosscheck-vs-prior.md`](crosscheck-vs-prior.md) | Prior reports plus current code re-check | 8 comparison groups |

The five code-report counts are partition-local and include some cross-file findings. They are not a globally deduplicated implementation backlog. The recommendations in §6 are deduplicated by decision risk.

### Evidence artifacts

- [`quant/evidence/verify-risk-timeseries.py`](quant/evidence/verify-risk-timeseries.py)
- [`quant/outputs/verify-risk-timeseries.txt`](quant/outputs/verify-risk-timeseries.txt)
- [`quant/evidence/verify-portfolio-correlation.py`](quant/evidence/verify-portfolio-correlation.py)
- [`quant/outputs/verify-portfolio-correlation.txt`](quant/outputs/verify-portfolio-correlation.txt)

The portfolio runner was corrected during validation: the reference now converts annualized cumulative GARCH variance back to return-space volatility before comparing it with the backend. The regenerated result is `81 MATCHES / 2 DIVERGES / 9 BUG` over 92 cases. The risk runner remains `13 MATCHES / 2 DIVERGES / 4 BUG` over 19 families.

## 3. Severity and category counts

### 3.1 Code-report severity

| Report | P0 | P1 | P2 | P3 | Total |
|---|---:|---:|---:|---:|---:|
| API | 0 | 7 | 17 | 2 | 26 |
| Core | 0 | 4 | 13 | 6 | 23 |
| Quant code | 0 | 5 | 14 | 3 | 22 |
| Data providers | 0 | 9 | 17 | 1 | 27 |
| Foundation | 0 | 8 | 9 | 6 | 23 |
| **Partition total** | **0** | **33** | **70** | **18** | **121** |

### 3.2 Code-report primary categories

The API/core/quant reports use the requested four-category vocabulary. Provider and foundation reports retain their more useful domain-specific categories rather than forcing unlike findings into “bug” or “improvement.”

| Report family | Category counts |
|---|---|
| API | Bug 17; Improvement 4; Optimization 3; Recommended change 2 |
| Core | Bug 17; Improvement 2; Optimization 2; Recommended change 2 |
| Quant code | Bug 17; Improvement 2; Optimization 2; Recommended change 1 |
| Data providers | Fallback/source precedence 7; symbol mapping 2; time/calendar 3; data quality 4; cache/config 2; API/error contract 4; retry/async 2; currency 1; security 1; provenance 1 |
| Foundation | Docker/CI/deployment 7; database/config/startup 5; secrets/logging 3; data integrity/transactions 4; async 1; dependency/build 1; schema/dead code 1; lifecycle 1 |

### 3.3 Product/report counts

| Product output | Count |
|---|---:|
| Bloomberg-equity capability rows | 18 |
| Bloomberg backlog rows | 30 |
| Verified source families in Bloomberg report | 10 |
| Current stock-research/portfolio areas | 32 |
| Add-ticker metrics | 25 |
| Add-ticker metrics computable from existing services | 23 |
| Add-ticker metrics requiring a new benchmark-aware endpoint | 2 |
| Stock-fit backlog rows | 12 |
| Stock-fit ship-first metrics | 23 |
| Verified source families in stock-fit report | 8 |

## 4. Quant/model verdict summary

### 4.1 Installed reference stack

`arch 8.0.0`, SciPy `1.18.1`, statsmodels `0.15.0`, QuantStats `0.0.81`, hmmlearn `0.3.3`, stockstats `0.6.8`, scikit-learn `1.9.1`, CVXPY `1.9.3`, and NumPy/pandas are installed. `TA-Lib`, pandas-ta, VectorBT, Empyrical, Pyfolio, riskfolio-lib, and PyPortfolioOpt are not installed. No package was added. No model received `REPLACE-WITH-LIBRARY`; the existing stack plus independent formulas was sufficient. A future TA-Lib parity suite would be a new dependency, not a current requirement.

### 4.2 Every model-family verdict in one line

| Model family | Verdict | Reference / magnitude |
|---|---|---|
| Realized annual return, volatility, Sharpe, Sortino, hit ratio | **MATCHES** | Independent NumPy/Pandas formulas; zero difference on aligned fixture |
| Historical 95% VaR/CVaR | **MATCHES** | NumPy percentile and conditional tail mean; zero difference |
| Analytics drawdown baseline | **BUG** | Initial loss omitted; first `-10%` fixture gives backend `0.0` vs baseline-aware `-0.10` |
| Skewness and excess kurtosis | **MATCHES** | SciPy/pandas unbiased identities; <=`2.44e-16` relative difference |
| Static normalized EWMA | **DIVERGES** | Unnormalized finite-sample convention differs by `0.02899` / `18.69%`; backend normalized identity matches |
| Recursive EWMA and normal tails | **MATCHES** | Independent recursion/SciPy; tails within declared rounded-constant tolerance |
| Rolling realized volatility and volatility cone | **MATCHES** | Pandas rolling/NumPy quantiles; zero or output-rounding difference |
| AnalyticsEngine GARCH horizon VaR/CVaR | **BUG** | `arch` cumulative h-day variance; five-day VaR `-0.02031` vs correct `-0.00908`, `123.61%` relative magnitude |
| VolatilityService horizon-average GARCH | **MATCHES** | `arch` RMS cumulative forecast; zero difference |
| AnalyticsEngine EGARCH multi-day path | **BUG** | `arch` simulation available but backend returns nulls; h=5 availability `0` vs `1` |
| EVT-POT typical fitted path | **MATCHES** | SciPy GPD and POT moments; <=`4.6e-7` output difference |
| EVT-POT fitted-shape boundary | **BUG** | Clipped shape `-0.5` vs fitted `-2.0130`; VaR/ES materially changed |
| Student-t lower-tail dependence | **MATCHES** | SciPy t-CDF closed form; zero difference |
| Gaussian HMM regime detection and summary | **MATCHES** | Independent features plus hmmlearn; <=`1.76e-4` rounded-diagnostic difference |
| Monte Carlo GBM/Student-t/bootstrap | **MATCHES** | Independent same-seed NumPy/SciPy/arch replays; zero or output-rounding difference |
| Walk-forward backtest return/turnover mechanics | **MATCHES** for tested implementation | Independent schedule/P&L replay; does not include the separate drawdown baseline defect |
| Walk-forward backtest drawdown | **BUG** | Initial peak omitted; five-day-style replay understates by `9.85%` |
| Technical indicators excluding MFI | **MATCHES** except Bollinger outer bands **DIVERGES** | SMA/EMA/RSI/MACD/ATR/VWMA match; Bollinger sample/population sigma differs by about `0.08` price units |
| MFI | **BUG** | Fraction `0.52468` vs canonical 0–100 `52.46785`; `51.94` point / `99%` relative error |
| Benchmark OLS beta/alpha/R² | **MATCHES** | statsmodels OLS/HAC point estimates; <=`2.74e-5` output difference |
| QuantStats tear sheet and relative metrics | **MATCHES** | Installed QuantStats plus independent wrapper identities; <=`3.12e-7` |
| Portfolio return construction with staggered listings | **BUG** | Active-history reference: annual return differs `16.38%`, volatility `8.90%` |
| Geometric monthly compounding | **MATCHES** | `(1+r).groupby([year,month]).prod()-1`; max absolute `4.98e-7` |
| Rolling pairwise correlation | **MATCHES** | Independent pairwise Pearson loop; <=`1e-13` series error |
| Cointegration, hedge ratio, OU, Johansen | **MATCHES** | statsmodels/independent formulas; output-rounded half-life difference `0.00486` days |
| HHI, effective N, Gini, single-holding diversification | **MATCHES** for positive normalized weights | True `sum(w²)`, `1/HHI`, one holding exactly `0%` |
| Concentration with accepted zero-weight row | **DIVERGES** | Active-holdings reference gives `100%` vs backend `93.8%`; `6.2` percentage points |
| Zero-state/empty-book first weight | **BUG** | Client `0.20` returned where invariant requires `1.0`; `80` percentage points |
| Positive-sigma inverse-volatility risk parity | **MATCHES** | `1/sigma` reference; max absolute weight difference `3.02e-7` |
| Zero-volatility inverse-volatility edge | **DIVERGES** | 5% floor regularizes constant asset to `0.68554` vs epsilon reference ~`1.0` |
| HRP | **MATCHES** | Canonical SciPy HRP; zero difference |
| Minimum variance | **MATCHES** | Independent SciPy SLSQP; max absolute `9.07e-8` |
| Maximum Sharpe | **MATCHES** | Independent SciPy tangency; max absolute `1.60e-8` |
| Minimum CVaR | **MATCHES** | Rockafellar–Uryasev LP/SciPy HiGHS; max absolute `1.09e-9` |
| Black-Litterman | **MATCHES** | Transparent posterior/tangency replay; max absolute `3.61e-8` |
| Euler volatility and empirical tail contribution | **MATCHES** | Independent contribution identities; max absolute `4.99e-7` |
| Regime-conditioned portfolio summary | **MATCHES** | Geometric CAGR replay; max absolute `2.01e-5` |
| Tracking error / information ratio | **NOT PRESENT** | No implementation or output fields; do not report a fabricated value |

The two evidence runners overlap on several families. Their raw case totals are therefore evidence counts, not 111 unique model families.

## 5. Priority findings and deduplicated recommendations

The table is recommendations only. No row below is an instruction to modify code in this session. Every row carries the required source/build tag.

### 5.1 Top ten recommendations

| Rank | Priority | Recommendation | Why it matters | Data source/build tag |
|---:|---|---|---|---|
| 1 | P1 | Correct the analytics-engine GARCH/EGARCH horizon semantics and add identical-input numeric regression tests. | Multi-day VaR/CVaR is materially wrong; this is a direct risk-decision error. | **build-from-free-proxy:** installed `arch` + existing backend seam; no new key |
| 2 | P1 | Establish one strict portfolio return/drawdown contract: no synthetic pre-listing prices/zero returns; initial wealth included in drawdown. | Current moments and tail metrics change with listing age; first loss can disappear. | **build-from-free-proxy:** existing OHLCV and deterministic fixtures |
| 3 | P1 | Enforce the empty-book 100% weight invariant and make portfolio currency/base-currency conversion explicit before aggregation. | First-position and mixed-IN/US totals can be immediately wrong. | **build-from-free-proxy:** existing quote/position data; no new source |
| 4 | P1 | Separate model fitting, portfolio transformation, and request orchestration; add weight-aware tail cache keys and bounded request contracts. | A first tails request can block the event loop, and a weight change can return old tail risk. | **build-from-free-proxy:** existing analytics/cache services |
| 5 | P1 | Make provider acceptance fail closed on requested-window coverage, missing fields, schema mismatches, and source provenance; wire persisted cache settings to runtime behavior. | Current data can be partial, stale, mixed-source, or labeled with the wrong provenance while looking successful. | **build-from-free-proxy:** existing bfinance/yfinance/Alpha Vantage; source behavior documented in [`gaps/bloomberg-gap.md`](gaps/bloomberg-gap.md) §2 |
| 6 | P1 | Repair Compose/Docker/deploy as a reproducible local deployment and remove volume-pruning cleanup; define a versioned migration path. | The checked-in deployment path can fail before startup or put the local portfolio at risk. | **build-from-free-proxy:** existing SQLite/app deployment; no new data source |
| 7 | P1 | Add one read-only `POST /analytics/add-ticker-impact` basic response: funding, Δvol/MRC, ΔHHI/N_eff, ΔVaR/CVaR/MDD, candidate correlations, sector/region drift, and %ADV/liquidation days. | Directly answers buy/avoid/weight decisions without mutating the book. | **build-from-free-proxy:** free yfinance/bfinance OHLCV/fundamental proxies [S1][S2] |
| 8 | P1 | Build the immutable transaction/cash-flow ledger before claiming historical TWR/MWR, tax lots, or realistic backtests. | Current performance history backcasts today’s quantities and cannot reconstruct prior decisions. | **build-from-free-proxy:** existing adjusted prices/actions [S1][S2] |
| 9 | P1 | Ship a unified field-level data-quality/freshness contract and portfolio health view. | A numerically correct result on stale, mixed-source, or wrong-unit data is not decision-grade. | **build-from-free-proxy:** existing source/cache metadata; source coverage matrix [S1][S2][S7] |
| 10 | P1 | Complete benchmark-relative performance and ownership/event decision layer: TE/IR, peer comps, earnings calendar, free estimate proxy, news/tone, India ownership quality, corporate actions. | These are more decision-moving than adding another forecast variant. | **free (cited):** [S1], [S2], [S4], [S5], [S7], [S9]; use manual/licensed boundaries exactly as cited |

### 5.2 Full deduplicated backlog

| ID | Priority | Deliverable | Decision value | Data source/build tag | Difficulty |
|---|---|---|---|---|---|
| BL-01 | P1 | Analytics-engine GARCH/EGARCH horizon correction and regression fixture | Correct multi-day risk | **build-from-free-proxy:** installed `arch` | S |
| BL-02 | P1 | Active-history return mask and baseline-aware drawdown | Correct portfolio moments and loss reporting | **build-from-free-proxy:** existing OHLCV | S |
| BL-03 | P1 | Zero-state 100% weight plus base-currency/position-currency contract | Correct first add and mixed-region totals | **build-from-free-proxy:** existing quote/position schema | M |
| BL-04 | P1 | Weight-aware tail memo, bounded request bodies, event-loop offload | Correct and responsive risk endpoints | **build-from-free-proxy:** existing cache/analytics | M |
| BL-05 | P1 | Provider coverage/freshness/field validation and source-aware cache keys | Prevent partial/stale/mixed-source data from passing | **build-from-free-proxy:** [S1][S2][S3] existing cascade | M |
| BL-06 | P1 | Compose/Docker/CI/deploy repair and migration convergence | Make local operations reproducible and protect the book | **build-from-free-proxy:** existing deployment files | M–L |
| BL-07 | P1 | Add-ticker basic endpoint: vol, MRC, HHI/N_eff, VaR/CVaR, MDD, correlation, sector/region, ADV | Directly changes add/avoid/weight decision | **build-from-free-proxy:** [S1][S2] | M |
| BL-08 | P1 | Immutable buy/sell/dividend/fee/cash ledger plus TWR/MWR | Makes performance and attribution auditable | **build-from-free-proxy:** [S1][S2] actions/prices | M–L |
| BL-09 | P1 | Data-quality/freshness/units/source badges and stale-input gates | Makes every decision metric auditable | **build-from-free-proxy:** [S1][S2][S7] | M |
| BL-10 | P1 | Benchmark-relative suite: active return, TE, IR, up/down capture, benchmark policy | Answers value added, not just return | **build-from-free-proxy:** free [S1] index returns; total-return rights unverified | M |
| BL-11 | P1 | Ownership-quality scorecard: FII/DII, promoter pledge, concentration, freshness | Ownership deterioration can change avoid/weight | **build-from-free-proxy:** [S2] plus manual [S4][S5]; no automated NSE collection | M |
| BL-12 | P1 | Earnings/reporting calendar and corporate-action calendar | Avoid event surprises and adjust total-return analysis | **free (cited):** [S1][S2] | S–M |
| BL-13 | P1 | Free estimate/revision proxy with analyst count/as-of and raw snapshots | Shows expectation direction when coverage exists | **free (cited), partial:** [S1]; production consensus **paid-only** later | M |
| BL-14 | P1 | Portfolio news/tone feed with URL de-duplication and uncertainty | Helps investigate a price move; non-gating | **free (cited):** [S9] | M |
| BL-15 | P1 | Complete marginal/component volatility, VaR/ES, sector risk decomposition | Finds the holding creating risk, not only its weight | **build-from-free-proxy:** existing covariance/tail services | M |
| BL-16 | P1 | Sortable peer/relative-valuation table with medians and missingness | Prevents single-company ratio mistakes | **free (cited):** [S1][S2] | M |
| BL-17 | P1 | Execution-realistic backtest: commission, spread/slippage, distributions, benchmark, capacity | Stops friction-free strategy claims | **build-from-free-proxy:** [S1][S2]; richer microstructure is later | M–L |
| BL-18 | P2 | Factor/style basic: value, momentum, quality, low-volatility, contribution | Shows hidden style concentration | **build-from-free-proxy:** [S1][S2]; US factor validation [S10] | M |
| BL-19 | P2 | India Brinson-Fachler basic using manual monthly benchmark weights | Explains sector allocation/selection/interaction | **build-from-free-proxy:** [S6] + existing returns | M |
| BL-20 | P2 | Ordinary correlation heatmap, top pairs, rolling change, sector overlay | Finds hidden co-movement | **build-from-free-proxy:** [S1][S2] | S–M |
| BL-21 | P2 | Saved screen definitions, watchlists, in-app alerts, run history | Makes research repeatable | **build-from-free-proxy:** existing screener/WebSocket | M |
| BL-22 | P2 | Safe custom metric language: allow-listed AST, ratios, windows, ranks | Encodes repeatable theses without arbitrary code | **build-from-free-proxy:** existing fields [S1][S2] | M |
| BL-23 | P2 | India/US macro pulse: GDP, CPI, labor/trade with as-of/missingness | Slow-moving context without fake real-time claims | **free (cited):** [S8] | S–M |
| BL-24 | P2 | Printable HTML decision report; styled PDF later | Produces an auditable meeting pack | **build-from-free-proxy:** existing payloads; renderer later | S/M |
| BL-25 | P2 | Benchmark selection for NIFTY/S&P 500/mixed region plus TE/IR | Required for US/mixed books | **build-from-free-proxy:** [S1] price-index proxies; total-return rights unverified | M |
| BL-26 | P2 | Rolling estimator stability: 63/252/756 return/vol/covariance diagnostics | Prevents one-window reversal from driving a decision | **build-from-free-proxy:** existing returns | M |
| BL-27 | P2 | Normalize sector/industry and listing-region taxonomy; expose UNKNOWN | Required for sector/region concentration gates | **build-from-free-proxy:** [S1][S2] raw labels/suffixes | M |
| BL-28 | P2 | Candidate-aware downside, beta, drawdown-episode, and deterministic stress deltas | Completes risk diagnosis after basic add impact | **build-from-free-proxy:** existing analytics/stress/bootstrap | M |
| BL-29 | P3 | Network communities/centrality and rolling graph changes | Useful at larger universe scale; not first decision gate | **build-from-free-proxy:** existing correlations | M |
| BL-30 | P3 | Versioned formula library, alert delivery, advanced macro revision history | Workflow depth after basic usage proves value | **build-from-free-proxy:** existing screens/WebSocket/data snapshots | M–L |
| BL-31 | P3 | Professional analyst consensus/history, holder-level ownership, licensed news | Better completeness, but cost/rights constrained | **paid-only:** procure only after free proxy is insufficient | L |
| BL-32 | P3 | BSE licensed market data/microstructure | Exchange-authorized depth and redistribution rights | **paid-only:** official [BSE product page] | L |

`[S1]`–`[S10]` and `[BSE product page]` are defined with verified URLs and policy limits in §7.

## 6. Clean areas and explicit non-findings

- `backend/app/api/__init__.py` and the equity-research API file are clean within their inspected contracts; current API findings concentrate in portfolio/data/analytics orchestration.
- Source-preference validation, current quote memo, analytics-cache natural-key upsert, and current HHI/inverse-volatility positive-sigma paths are clean.
- Geometric monthly compounding passes the mandatory invariant with deterministic evidence.
- Installed-library checks show no reason to add a new portfolio library now; riskfolio-lib and PyPortfolioOpt are absent but independent references already validate the implemented models.
- `GARCH`/`EGARCH` model fitting itself is offloaded; the remaining issue is the surrounding horizon transformation and API orchestration.
- Provider source cascades, prebuilt screener cache, and core India liquidity formulas are clean only within the bounded contracts stated in `code/04-data-providers.md`.
- The current SQLite metadata check in `code/05-foundation.md` reports `quick_check=ok`, zero foreign-key violations, and zero duplicate logical keys in the inspected current DB. This is runtime metadata, not a claim that all writes are safe.
- The current yfinance/Alpha/NSE source rights and several numeric policy details are not fully verified; reports explicitly mark those fields `not verified` rather than inferring them.

## 7. Verified free-data source table

All rows below were opened/returned by the Wave 1 web-verification work. “Not verified” is intentional. The full field-level notes are in `gaps/bloomberg-gap.md:36-51` and `gaps/stock-research-fit.md:90-103`.

| ID/source | Capabilities it feeds | Coverage/history/policy verified | Exact verified URL |
|---|---|---|---|
| **S1 yfinance/Yahoo client** | IN/US OHLCV/actions, quotes, fundamentals, statements, calendar, estimates proxy, news, holders, benchmark histories | Symbol-dependent IN/US; history/max symbol age; no numeric public quota; code Apache-2.0, upstream Yahoo personal-use notice; vendor SLA not verified | [API reference](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.html), [project legal notice](https://github.com/ranaroussi/yfinance/blob/main/README.md) |
| **S2 bfinance** | India quotes/history, fundamentals, statements, shareholding, peers, concalls, ratios, screener, AI context | India NSE/BSE; package claims 10+ annual years/12+ quarters; MIT library, upstream exchange rights and numeric quota not verified; upstream SLA not verified | [PyPI bfinance](https://pypi.org/project/bfinance/) |
| **S3 Alpha Vantage** | Daily OHLCV, global quote, optional news/estimates/ownership/fundamentals | Official examples include US and India BSE symbols; daily endpoint claims 25+ years; free key 25/day verified, per-minute not verified; adjusted/full and some fields may be premium; terms apply | [Documentation](https://www.alphavantage.co/documentation/), [API-key policy](https://www.alphavantage.co/support/api-key/) |
| **S4 NSE FII/FPI/DII reports** | India daily institutional cash-market flows | India only; archive depth not verified; no public API/rate; NSE terms prohibit systematic automated collection; provisional/event-driven | [FII/DII report](https://nseindia.com/reports/fii-dii), [archive](https://www.nseindia.com/products/content/equities/equities/eq_fiidii_archives.htm), [terms](https://www.nseindia.com/static/nse-terms-of-use) |
| **S5 NSE shareholding filings** | Promoter/public/institutional ownership, pledge, filing/revision dates | India listed; issuer filing history, fixed depth not verified; no public API/rate; manual personal use unless licensed | [Corporate filings](https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern), [terms](https://www.nseindia.com/static/nse-terms-of-use) |
| **S6 NSE Indices reports/subscription** | India benchmark weights, index history, Brinson basic inputs | India indices; monthly archive; ongoing/historical constituent weights are subscription; portal personal-use/reproduction restrictions verified | [Monthly reports](https://www.niftyindices.com/reports/monthly-reports), [data subscription](https://www.niftyindices.com/offerings/data-subscription), [terms](https://niftyindices.com/terms-of-use) |
| **S7 SEC EDGAR APIs** | US issuer identity, filing history, reported XBRL company facts, dates/periods | US registrants; EDGAR history from 1994 Q3; no key; 10 requests/second fair-access limit; nightly bulk structures; declared User-Agent required | [API docs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), [developer resources](https://www.sec.gov/about/developer-resources) |
| **S8 World Bank Indicators API v2** | India/US GDP, CPI, macro context, selected labor/trade indicators | India/US verified; many series extend beyond 50 years, indicator-dependent; no key; generally CC BY 4.0 with indicator exceptions; numeric rate not verified; `lastupdated` exposed | [API help](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392), [terms](https://www.worldbank.org/ext/en/legal/terms-conditions/datasets) |
| **S9 GDELT DOC 2.0** | Portfolio news, article URLs, source country/language, tone proxy, volume | Global monitoring; India query verified; default three-month window; 15-minute timeline for short spans; free/open project, numeric rate/content license not fully verified | [API announcement](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/), [rate-limit notice](https://blog.gdeltproject.org/ukraine-api-rate-limiting-web-ngrams-3-0/), [data page](https://gdeltproject.org/data.html) |
| **S10 Kenneth French Data Library** | US market, size, value, profitability, investment, momentum factor validation | US only; daily factors from 1926-07-01 verified; no key; numeric rate/content license not verified; monthly reconstruction | [Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_Library.html), [factor description](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_factors.html) |
| **BSE market-data products** | Licensed BSE prices, volume, corporate actions, filings, classification | BSE-listed India; official product page states EOD/history depth; automated data products require subscription; rate/rights depend on purchased license | [Official products](https://www.bseindia.com/market_data_products.html?flag=real), [tariff sheet](https://www.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf) |

**Source-selection rule:** prefer existing bfinance/yfinance/Alpha/NSE paths and no-new-key proxies. Do not treat a package’s MIT license as a grant of upstream exchange-data rights. Do not automate an exchange page whose terms prohibit systematic collection. Preserve source/as-of/missingness even when a field is unavailable.

## 8. Do-not-do list

1. Do not reopen the resolved remote-bind/authentication P0 unless the service is exposed beyond localhost; fix the narrower WebSocket Origin/Host boundary instead.
2. Do not add another risk-model variant before fixing the existing horizon transformation, pre-listing return contract, and drawdown baseline.
3. Do not automate NSE website collection from the free basic plan; use manual personal imports or a licensed feed.
4. Do not present fallback FX, synthesized ADV, zero-filled OHLCV, stale bars, or missing news/estimates as measured values.
5. Do not use a synthetic one-share ad-hoc portfolio as a candidate valuation or liquidity decision.
6. Do not apply US factor benchmarks to Indian holdings or mix regional benchmarks without an explicit policy and common dates/currency.
7. Do not add an opaque AI stock-picker surface before the input provenance, decision ledger, and add-impact gates exist.
8. Do not purchase terminal-grade data before the free source/basic proxy workflow demonstrates a material gap; paid upgrades are `paid-only` and lower priority.
9. Do not reintroduce fixed prior paths as active findings: current source shows the prior cache-key, fallback-fabrication, indicator-warmup, root-script, and service-side async repairs.

## 9. Verification and read-only confirmation

- Wave 1 code auditors reported focused test runs of 178 core tests, 114 quant-code tests, and 59 foundation/provider tests, plus Ruff passes. The full suite was not rerun because the strict read-only contract disallows generated coverage/cache artifacts outside the permitted directory.
- Both deterministic quant runners completed successfully with no network and no backend writes. The corrected portfolio runner passed `uv run --no-sync ruff check --no-cache`.
- Web-source claims are limited to sources actually opened/returned in the Wave 1 gap reports. Where a publisher did not expose a numeric quota, license detail, update SLA, or per-symbol coverage, the reports say `not verified`.
- The only files created or edited during this audit are under `.scratch/backend-deep-audit/`, including the evidence scripts and outputs listed above. No backend, frontend, config, migration, test, database, lockfile, or Git file was modified by this audit.

## 10. Final reading order

1. Start with [`code/01-api-layer.md`](code/01-api-layer.md) and [`code/05-foundation.md`](code/05-foundation.md) for the highest operational/contract risk.
2. Read [`quant/verify-risk-timeseries.md`](quant/verify-risk-timeseries.md) and [`quant/verify-portfolio-correlation.md`](quant/verify-portfolio-correlation.md) before trusting risk outputs.
3. Use [`gaps/stock-research-fit.md`](gaps/stock-research-fit.md) for the basic add-ticker decision workflow.
4. Use [`gaps/bloomberg-gap.md`](gaps/bloomberg-gap.md) for the broader terminal roadmap and source constraints.
5. Use [`crosscheck-vs-prior.md`](crosscheck-vs-prior.md) to understand what the prior remediation pass closed and what independent verification newly found.
