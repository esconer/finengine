# FinEngine cash-equity stock research and “add ticker X” fit audit

**Audit date:** 2026-09-24  
**Scope:** cash equities and portfolio analytics only; Indian and US listed equities; documentation/design only.  
**Evidence rule:** every current-state statement below cites production Python by exact line. Proposed formulas and endpoints are explicitly design, not implemented capability.  
**Counts:** **32 current-state areas assessed** (14 stock-research areas, 18 portfolio-analytics areas); **25 proposed add-impact metrics** (23 computable from existing services, 2 missing behind a new benchmark-aware endpoint; 23 ship-first); **8 verified source families**; **12 backlog items** (P1=4, P2=6, P3=2).

## 1. Executive finding

FinEngine already has most of the numerical ingredients for a read-only “what changes if I add X?” analysis, but its analytics route inventory has no endpoint that freezes a funding assumption and returns coherent before/after values together (`backend/app/api/analytics.py:210-2255`). The cleanest design is one non-mutating orchestration endpoint, not another optimization model: reuse existing OHLCV, market-value weights, covariance, tail, concentration, benchmark, and ADV primitives (`backend/app/api/analytics.py:178-207`, `backend/app/api/analytics.py:700-756`, `backend/app/api/analytics.py:1556-1637`), then compute the same metrics twice—current weights and hypothetical post-purchase weights.

The three ship-first decision metrics are:

1. **Marginal annualized volatility and candidate risk contribution**—the candidate can lower volatility through covariance or increase it despite low standalone volatility.
2. **Δ HHI and Δ effective N from true weights**—the immediate concentration and resulting maximum acceptable weight test.
3. **Position % ADV and estimated liquidation days at explicit participation**—the capacity test for both an Indian and US listing.

The existing endpoint that comes closest, `/api/v1/analytics/liquidity-limits`, creates synthetic ₹10,000 positions for ad-hoc tickers and therefore cannot answer a user-supplied buy amount (`backend/app/api/analytics.py:2101-2107`, `backend/app/api/analytics.py:2126-2143`). The optimizer can include a candidate, but it has no common before/after impact ledger and ad-hoc allocation can be equal-weighted (`backend/app/api/analytics.py:78-97`, `backend/app/api/analytics.py:1645-1727`).

---

## 2. Current individual-stock research capability

“Live” below means computed on request from a vendor/cache path. It does **not** mean licensed real-time exchange data: quote memoization is 30 seconds (`backend/app/services/data_service.py:121-123`), full-depth OHLCV L1 is five minutes (`backend/app/services/data_service.py:131-145`), and portfolio positions refresh only when stale by 15 minutes or forced (`backend/app/api/portfolio.py:1084-1117`).

| # | Research area | Current endpoint/service and exact evidence | What is genuinely computed | Assessment and material qualification |
|---:|---|---|---|---|
| R1 | Quote and listing metadata | `GET /api/v1/data/quote/{ticker}` delegates to `DataService.fetch_quote` (`backend/app/api/data.py:370-393`). The vendor cascade returns price, volume, market cap, sector, industry, 52-week range, P/E, dividend yield, currency, exchange, and a generated timestamp (`backend/app/services/data_service.py:471-497`, `backend/app/services/data_service.py:535-570`). | Price/volume fallback and metadata are assembled by FinEngine. | **Service usable; public typed route needs a key-contract repair.** The service emits `52_week_high/low`, while `StockQuoteResponse` requires `week_52_high/low` (`backend/app/services/data_service.py:489-490`, `backend/app/models/schemas.py:139-151`), so the route is not clean without runtime/schema verification. The timestamp is locally generated, not a vendor quote timestamp (`backend/app/services/data_service.py:555-569`). Alpha Vantage fallback deliberately leaves fundamentals absent (`backend/app/services/data_service.py:883-909`). |
| R2 | Historical OHLCV, corporate actions, validation | `GET /api/v1/data/{ticker}` returns OHLCV and source/cache state (`backend/app/api/data.py:271-361`). The service cascades bfinance/yfinance, then Alpha Vantage, and deep-backfills at most ten years into SQLite (`backend/app/services/data_service.py:131-145`, `backend/app/services/data_service.py:320-443`). Batch OHLCV and ticker validation also exist (`backend/app/api/data.py:396-466`, `backend/app/services/data_service.py:610-735`). Corporate actions are adjusted in `adj_close` (`backend/app/services/data_service.py:737-760`). | Returns, prices, volumes, cache provenance, and adjusted-close calculations are real on a successful vendor response. | **Clean core input.** The Alpha Vantage tier writes raw close into `adj_close` because adjusted daily time series are premium (`backend/app/services/alpha_vantage_service.py:270-308`); risk analytics must flag or exclude that source for long-horizon corporate-action analysis. |
| R3 | Curated fundamentals | `GET /api/v1/data/fundamentals/{ticker}` is a bfinance/yfinance cascade with 24-hour yfinance fundamentals memoization (`backend/app/api/data.py:102-122`, `backend/app/services/company_data_service.py:59-70`, `backend/app/services/company_data_service.py:189-256`). The curated field set includes size, valuation, margins, returns, leverage, liquidity ratios, and free cash flow (`backend/app/services/company_data_service.py:74-102`). | Missing fields are omitted; bfinance values are mapped into the common shape and yfinance ROE is normalized to percent (`backend/app/services/company_data_service.py:148-183`, `backend/app/services/company_data_service.py:208-234`). | **Live/computed, weakly auditable.** The API response carries no source URL, vendor, or vendor as-of timestamp. A one-day yfinance cache can serve a stale snapshot without saying so in the response (`backend/app/services/company_data_service.py:189-193`). |
| R4 | Income, balance-sheet, and cash-flow statements | `GET /api/v1/data/financials/{ticker}` supports income/balance/cashflow and annual/quarterly frequency (`backend/app/api/data.py:125-143`). The service tries bfinance then yfinance and returns period-indexed metrics (`backend/app/services/company_data_service.py:258-351`). | Statement rows and periods are transformed into JSON; optional cutoff filtering exists in the service. | **Usable, not point-in-time through the route.** The service supports `curr_date` and removes later periods (`backend/app/services/company_data_service.py:266-277`, `backend/app/services/company_data_service.py:329-334`), but the public route does not accept or pass it (`backend/app/api/data.py:125-137`). |
| R5 | Valuation and forensic ratios | Full profile exposes P/E, book value, dividend yield, ROCE, ROE, D/E, PEG, EPS, promoter holding/pledge, Piotroski, Graham number, EV/EBITDA, interest coverage, CFO/PAT, CAGR, pros/cons, and peers (`backend/app/api/equity_research.py:37-53`, `backend/app/services/equity_research_service.py:48-115`). A separate custom-ratios/history route exists (`backend/app/api/equity_research.py:89-104`, `backend/app/services/equity_research_service.py:212-256`). | FinEngine assembles and labels fields; some Graham upside is calculated (`backend/app/services/equity_research_service.py:51-65`). | **Mostly upstream pass-through, not FinEngine valuation modeling.** No DCF, WACC, peer-percentile valuation, or source/as-of evidence is implemented. Zero-valued `or` fallbacks can hide unavailable Piotroski/EV values (`backend/app/services/equity_research_service.py:225-242`). |
| R6 | Technical indicators and verified snapshot | `GET /api/v1/data/indicators/{ticker}` computes stockstats indicators on cached OHLCV (`backend/app/api/data.py:47-74`). The live catalogue contains SMA/EMA, MACD, RSI, Bollinger, ATR, VWMA, and MFI (`backend/app/services/indicators_service.py:32-53`). The verified snapshot returns the latest OHLCV row, indicators, and closes with no estimates (`backend/app/api/data.py:77-99`, `backend/app/services/indicators_service.py:204-241`). | Indicator series are calculated after schema cleanup, with a 365-day warm-up floor and a 10-calendar-day stale-data refusal (`backend/app/services/indicators_service.py:147-180`, `backend/app/services/indicators_service.py:97-114`). | **Clean/computed.** “Verified” means deterministic against cached vendor OHLCV, not independently reconciled to an exchange. |
| R7 | Institutional/shareholder ownership | `GET /api/v1/company/{ticker}/shareholding` is explicitly an Indian quarterly/annual trend endpoint (`backend/app/api/equity_research.py:56-70`). It transforms bfinance quarterly and annual frames into chart series (`backend/app/services/equity_research_service.py:125-190`). Promoter and pledge fields also appear in the full profile (`backend/app/services/equity_research_service.py:84-106`). | Period values are extracted; the endpoint does not itself calculate ownership change. | **Partial: India only and upstream-dependent.** There is no US institutional-holder endpoint and no source license/as-of vendor field in the response schema (`backend/app/models/schemas.py:517-528`). |
| R8 | Insider transactions | `GET /api/v1/data/insider/{ticker}` returns yfinance insider transactions and treats an empty result as normal (`backend/app/api/data.py:146-154`). The service converts the dataframe to serializable rows (`backend/app/services/company_data_service.py:353-379`). | Records are normalized, not interpreted. | **Partial availability, no verdict logic.** The service has no bfinance fallback and returns no source/as-of metadata; upstream exceptions become a 500 rather than an explicit unavailable result (`backend/app/api/data.py:146-154`). |
| R9 | News and sentiment | The production equity-research routes move from company research directly to prompts/dossiers and then screeners; no news/sentiment route is present (`backend/app/api/equity_research.py:37-193`, `backend/app/api/equity_research.py:197-257`). The generic fundamentals field map has no news or sentiment field (`backend/app/services/company_data_service.py:74-102`). | None. | **Missing.** No FinEngine news corpus, ticker-news join, article timestamp, source, deduplication, or sentiment score exists. |
| R10 | Analyst estimates, recommendations, and target prices | The current company-data service exposes fundamentals, statements, and insiders only (`backend/app/services/company_data_service.py:64-66`, `backend/app/services/company_data_service.py:72-102`, `backend/app/services/company_data_service.py:258-379`). No estimate/recommendation route exists in the data or equity-research route sets (`backend/app/api/data.py:47-154`, `backend/app/api/equity_research.py:37-257`). | None. | **Missing.** Any add-ticker model must not fabricate forward earnings, consensus returns, or target prices. |
| R11 | Concalls, annual reports, and credit ratings | `GET /api/v1/company/{ticker}/concalls` returns bfinance model dumps (`backend/app/api/equity_research.py:73-86`, `backend/app/services/equity_research_service.py:192-210`). Full profile passes through annual reports and credit ratings (`backend/app/services/equity_research_service.py:108-115`). | URL/model normalization only. | **Partial pass-through, India only.** FinEngine does not fetch, archive, parse, date-validate, or summarize the underlying documents itself. |
| R12 | Peer comparison | Full profile serializes `profile.peers` (`backend/app/services/equity_research_service.py:66-69`, `backend/app/services/equity_research_service.py:108-115`). The schema leaves peer rows as dictionaries (`backend/app/models/schemas.py:456-465`, `backend/app/models/schemas.py:478-514`). | Upstream peer list serialization. | **Partial: India only, no FinEngine comparability test.** No US peer builder, peer-set methodology, liquidity adjustment, or relative-rank calculation exists. |
| R13 | AI dossier and prompts | `GET /company/{ticker}/ai-memo-prompt`, `/ai-forensic-prompt`, and `/ai-dossier` call bfinance prompt/context methods (`backend/app/api/equity_research.py:134-193`). The service invokes `to_ai_context`, `to_investment_memo_prompt`, and `to_forensic_audit_prompt` (`backend/app/services/ai_dossier_service.py:32-92`). A concall prompt method exists in the service but has no route (`backend/app/services/ai_dossier_service.py:94-110`). | Deterministic context/prompt generation from bfinance, not an LLM inference performed by FinEngine. | **Partial/context-only.** It does not score the candidate, validate claims, or add portfolio impact. |
| R14 | Institutional stock screeners | Prebuilt and custom screen routes exist (`backend/app/api/equity_research.py:197-257`). The service defines five India screens, scans the full upstream universe, ranks/caps results, and applies a fail-closed D/E ≤ 0.2 post-filter to the debt-free strategy (`backend/app/services/screener_service.py:73-99`, `backend/app/services/screener_service.py:176-254`, `backend/app/services/screener_service.py:256-274`). | Screener execution and FinEngine debt-free correction. | **Usable India universe tool, not an add-impact tool.** It does not compare a candidate to the current portfolio and does not use US fundamental coverage. |

**Research-area count:** 14 assessed; 5 are live/computed without a route-contract blocker, 7 are partial/pass-through or need contract repair, and 2—news/sentiment and estimates/recommendations—are missing.

---

## 3. Current portfolio-impact and analytics capability

| # | Portfolio capability | Exact current implementation | Assessment and limitation relevant to adding X |
|---:|---|---|---|
| P1 | Position valuation, P&L, and live weights | Portfolio GET refreshes stale prices and returns live market-value weights, P&L, current value, and sector shares (`backend/app/api/portfolio.py:45-147`). Position add fetches a quote and stores quantity, price, market value, sector, and industry (`backend/app/api/portfolio.py:158-266`). | **Clean current-state input.** There is no cash holding or funding ledger; the database contains risky positions only (`backend/app/models/database.py:11-30`). The add route hard-codes `primary_source="yfinance"` even when the quote cascade may have used bfinance (`backend/app/api/portfolio.py:212-235`). |
| P2 | Realized return/risk and position risk | `GET /analytics/realized-risk` computes portfolio/position annual return, volatility, Sharpe, Sortino, skew, kurtosis, max drawdown, historical 95% VaR/CVaR, and coverage warnings (`backend/app/api/analytics.py:210-445`). The engine formulas are explicit (`backend/app/services/analytics_engine.py:846-920`). | **Clean current metric, not a delta.** Annualized values are suppressed below 30 covered observations (`backend/app/utils/holdings.py:24-27`, `backend/app/utils/holdings.py:202-213`). |
| P3 | Forecast volatility/VaR/CVaR | `GET /analytics/forecast-risk` supports EWMA, GARCH(1,1), EGARCH and 1–30 day horizon (`backend/app/api/analytics.py:452-590`). Engine forecasts are implemented at `backend/app/services/analytics_engine.py:978-1096`. | **Computed but not decision-grade on failure.** GARCH/EGARCH paths fall back to fixed annual vol defaults 0.22/0.24 when fitting output is unusable and then clip to 0.05–1.20 (`backend/app/services/analytics_engine.py:994-1014`, `backend/app/services/analytics_engine.py:1037-1056`). The proposed add endpoint must return null on fit failure, not those defaults. |
| P4 | Market beta, alpha, R² | `GET /analytics/factor-exposure` uses NIFTY 50 returns and OLS/HAC regressions for positions and the portfolio (`backend/app/api/analytics.py:597-693`, `backend/app/services/analytics_engine.py:1098-1223`). | **Computed, one-factor only.** The benchmark is hard-coded to `^NSEI` and there is no US or mixed-region benchmark (`backend/app/services/benchmark_service.py:19-23`). The response field is called “factor exposure,” but it is a single market regression (`backend/app/api/analytics.py:644-650`). |
| P5 | Concentration | `GET /analytics/concentration` computes largest, top-3/5/10, HHI, effective positions, normalized diversification score/ratio, Gini, and sector shares (`backend/app/api/analytics.py:700-756`). True formulas, including a single-holding score of zero, are in `backend/app/services/analytics_engine.py:216-249`. | **Clean and directly reusable.** It has no hypothetical candidate and no region concentration. |
| P6 | Liquidity score | `GET /analytics/liquidity` fetches 30-day close/volume and market cap, then applies hard-coded turnover/cap tiers (`backend/app/api/analytics.py:763-839`, `backend/app/services/analytics_engine.py:256-383`). | **Partly computed, partly heuristic.** Empirical spread and liquidation labels are formulas over tiers, not observed bid/ask spreads (`backend/app/services/analytics_engine.py:302-336`). Missing market cap is replaced by an implied capitalization (`backend/app/services/analytics_engine.py:293-301`). |
| P7 | Stress scenarios | `POST /analytics/stress-test` supports request tickers and fixed scenarios (`backend/app/api/analytics.py:846-911`). The engine has market and sector shock multipliers and returns weighted impact (`backend/app/services/analytics_engine.py:385-414`, `backend/app/services/analytics_engine.py:410-557`). | **Deterministic sensitivity, not a forecast.** It returns `confidence_level=0.95` despite using hard-coded scenario multipliers and no confidence estimation (`backend/app/services/analytics_engine.py:539-556`). Candidate sectors not in the DB default to “Exchange Traded Fund.” |
| P8 | Inverse-volatility sizing | `GET /analytics/volatility-sizing` computes true inverse-volatility weights, scales to target vol, reports cash/leveraging, and trade deltas (`backend/app/api/analytics.py:914-987`, `backend/app/services/analytics_engine.py:563-697`). | **Computed sizing aid, not a marginal-impact endpoint.** It allocates among existing holdings and does not measure Δ risk from one candidate amount. |
| P9 | Composite risk score | `GET /analytics/risk-score` combines concentration, volatility, correlation, factor R², and recent volatility; the factor leg is excluded and remaining weights renormalized if the benchmark is missing (`backend/app/api/analytics.py:990-1057`, `backend/app/services/analytics_engine.py:703-829`). | **Computed but threshold-based.** `change` is always zero because the score is stateless (`backend/app/services/analytics_engine.py:797-805`). |
| P10 | Performance history, tear sheet, and benchmark comparison | Performance history computes quantity × price and rebased NIFTY comparison (`backend/app/api/analytics.py:1182-1300`). Tear sheet computes return, CAGR, Sharpe, Sortino, Calmar, volatility, drawdown, alpha/beta, monthly compounding, and underwater curve (`backend/app/api/analytics.py:1360-1546`). | **Usable for current holdings.** Ad-hoc non-DB tickers receive synthetic quantity 1 (`backend/app/api/analytics.py:1206-1220`), which is a normalized research path, not a candidate valuation. Benchmark is NIFTY only and price-return based. |
| P11 | Euler risk contribution and tail attribution | `GET /analytics/risk-contribution` computes annual covariance, `RC_i=w_i(Σw)_i/σ`, historical 95% VaR/CVaR, and sector rollups (`backend/app/api/analytics.py:1556-1637`). | **Clean numerical primitive.** MRC is calculated internally but not returned; CVaR attribution is empirical worst-5%-day contribution, not a marginal derivative (`backend/app/api/analytics.py:1591-1610`). |
| P12 | Optimization | `POST /analytics/optimize/run` supports HRP, minimum variance, maximum Sharpe, minimum CVaR, and Black-Litterman (`backend/app/api/analytics.py:1645-1735`). The service uses trailing mean/covariance, long-only constraints, scenario CVaR, and a Black-Litterman prior/views (`backend/app/services/optimization_service.py:39-43`, `backend/app/services/optimization_service.py:146-215`, `backend/app/services/optimization_service.py:286-330`). | **Computed optimizer, not before/after analysis.** A requested non-DB candidate receives zero current weight while existing requested holdings are normalized; this can produce a trade, but no risk/capacity/exposure deltas or funding ledger. |
| P13 | Walk-forward backtest | `POST /analytics/backtest` supports rolling optimization, rebalancing frequency, lookback, costs, and benchmark leg (`backend/app/api/analytics.py:1738-1788`, `backend/app/services/backtest_service.py:18-195`). | **Usable current/hypothetical strategy tool.** Its benchmark is equal weight, not a market index (`backend/app/services/backtest_service.py:62-68`). |
| P14 | Conditional regime statistics | `GET /analytics/regime` fits a three-state NIFTY HMM and computes portfolio behavior inside the current regime (`backend/app/api/analytics.py:1791-1831`, `backend/app/services/regime_service.py:105-296`, `backend/app/services/regime_service.py:299-352`). | **Computed with disclosed history gate.** It needs at least 200 regime observations and remains NIFTY-only (`backend/app/services/regime_service.py:24-35`, `backend/app/services/regime_service.py:133-135`). |
| P15 | Correlation stability and tail dependence | `GET /analytics/correlation-stability` computes rolling pairwise mean correlation and historical percentile alerts (`backend/app/api/analytics.py:1908-1965`, `backend/app/services/correlation_service.py:17-150`). `/tails` computes EVT VaR/ES and a lower-tail copula matrix (`backend/app/api/analytics.py:2200-2254`, `backend/app/services/tail_risk_service.py:24-155`, `backend/app/services/tail_risk_service.py:234-334`). | **Strong reusable primitives.** Correlation-stability returns an average, not the candidate-to-every-holding linear matrix; tail dependence is not a substitute for ordinary correlation. |
| P16 | Cointegration and volatility cone | `/coint` scans pair cointegration/half-life/z-score (`backend/app/api/analytics.py:1968-2028`). `/vol-cone` computes 10/21/63/126/252-day realized-vol quantiles plus GARCH/EWMA overlay (`backend/app/api/analytics.py:2149-2182`, `backend/app/services/volatility_service.py:187-330`). | **Computed diagnostics.** These can enrich X review, but neither yields coherent add/avoid gates by itself. |
| P17 | Monte Carlo goal simulation | `POST /analytics/monte-carlo` calibrates historical mean/vol and supports GBM, Student-t, and stationary bootstrap with deterministic seed support (`backend/app/api/analytics.py:1834-1905`, `backend/app/services/monte_carlo_service.py:48-138`, `backend/app/services/monte_carlo_service.py:163-230`). | **Computed scenario engine.** The default i.i.d. GBM is not appropriate evidence for marginal tail/correlation decisions unless labeled; bootstrap is the better full add-impact MDD path. |
| P18 | Rebalance simulation/orders | `POST /portfolio/rebalance` supports dry-run, current-to-target quantities, buy/sell cash deltas, and turnover (`backend/app/api/portfolio.py:849-976`). | **Clean execution simulation for existing holdings only.** It rejects unknown tickers (`backend/app/api/portfolio.py:882-894`) and cannot represent a new candidate. |

**Portfolio-area count:** 18 assessed; all have some current implementation, but only a subset is clean enough to serve directly as an add-impact primitive.

---

## 4. Existing capabilities that are clean and reusable

| Capability | Reusable evidence | Why it is usable for add-impact basic |
|---|---|---|
| Market-value-derived current weights | Analytics prefers quantity × latest price, then stored weight, then equal weight only as a final fallback (`backend/app/api/analytics.py:178-207`). | Avoids stale stored-weight distortion. |
| OHLCV provenance and cache | Timeseries stores source, fetch status/status, and fetch timestamp (`backend/app/models/database.py:39-64`); the service uses a 10-year backfill and source cascade (`backend/app/services/data_service.py:320-443`). | Supports a common as-of window and explicit source/freshness output. |
| Technical stale guard | Latest OHLCV more than 10 days before the requested end is rejected (`backend/app/services/indicators_service.py:97-114`). | The new endpoint should reuse the principle, not silently use old bars. |
| True HHI/effective N | HHI is `Σw²`, effective N is `1/HHI`, and one holding has diversification score 0 (`backend/app/services/analytics_engine.py:224-249`). | Directly supplies current and post-add concentration. |
| Realized risk formulas | Trailing mean/vol, daily target for Sortino, historical 5th percentile VaR, tail-mean CVaR, and path drawdown are explicit (`backend/app/services/analytics_engine.py:846-920`). | Before/after use the same estimator on the same dates. |
| Euler volatility contribution | Covariance, MRC, normalized contribution, and sector rollup are explicit (`backend/app/api/analytics.py:1591-1634`). | Exact candidate marginal risk contribution is a small conceptual extension. |
| Correlation and tail calculations | Pairwise rolling correlation and Student-t lower-tail matrix are implemented (`backend/app/services/correlation_service.py:52-67`, `backend/app/services/tail_risk_service.py:269-334`). | Candidate pair calculations can reuse the same aligned return frame. |
| Optimizer/objective code | Long-only HRP/min-vol/max-Sharpe/min-CVaR and covariance/mean construction are implemented (`backend/app/services/optimization_service.py:15-21`, `backend/app/services/optimization_service.py:146-194`, `backend/app/services/optimization_service.py:286-330`). | Useful as an optional full weight-search layer after—not instead of—impact metrics. |
| NIFTY benchmark and conditional regime | `BenchmarkService` caches `^NSEI` and returns aligned simple returns (`backend/app/services/benchmark_service.py:19-23`, `backend/app/services/benchmark_service.py:45-96`); regime statistics disclose overlap and annualization (`backend/app/services/regime_service.py:324-352`). | Reusable for India-only strategies, with explicit price-index and coverage caveats. |

---

## 5. Verified external sources

Verification was performed on 2026-09-24 by web search/fetch of the linked first-party documentation, package metadata, exchange pages, or regulator pages. “Not verified” is intentional where the publisher does not publish the requested fact. Package/library marketing claims are labeled as such rather than treated as exchange authorization.

| Source family and verified URL | Exact method/endpoint | Inputs used in this design | India / US coverage | Verified history depth | Rate, cost, license | Verified update frequency / limitation |
|---|---|---|---|---|---|---|
| **yfinance / Yahoo Finance** — [documentation](https://ranaroussi.github.io/yfinance/), [Ticker API](https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.html), [download API](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html), [code license](https://raw.githubusercontent.com/ranaroussi/yfinance/main/LICENSE.txt) | `yf.download(...)`, `Ticker.history`, `.info`, `.news`, `.earnings_estimate`, `.revenue_estimate`, `.growth_estimates`, `.institutional_holders`, `.major_holders`, `.insider_transactions`, `.recommendations`, `.analyst_price_targets`, `.get_valuation_measures`. Yahoo HTTP endpoint itself: **not verified as a supported public API endpoint**. | OHLCV/actions, quote/fundamentals, statements, sector/industry, news, estimates, ownership, technical inputs, `^NSEI`, `^GSPC`, `USDINR=X`. | US symbols are documented; the backend attempts India through Yahoo `.NS`/`.BO`, but exhaustive external yfinance India coverage was not published and was not probe-tested. Individual field coverage is **not guaranteed per ticker**. `USDINR=X` is verified only as current backend usage, not as a separate external source. | `start` defaults to 99 years ago; `period=max` is accepted; intraday intervals are limited to the last 60 days. Actual depth ends at listing age. | No key and no published fixed request quota; throttling is possible. Code is Apache-2.0. yfinance docs explicitly say Yahoo data is personal-use-only and Yahoo is not affiliated with the project. | Daily/interval vendor updates; no update SLA or fixed fundamentals/estimate refresh time was verified. Existing FinEngine caching is 5-minute L1/DB tail rules for OHLCV, not a vendor SLA (`backend/app/services/data_service.py:131-145`, `backend/app/services/data_service.py:1027-1033`). |
| **bfinance 0.1.0 (Bharat Finance)** — [PyPI JSON metadata and README](https://pypi.org/pypi/bfinance/0.1.0/json) | `bf.Ticker`, `.history`, `.financials`, `.quarterly_income_stmt`, `.shareholding`, `.shareholding_yearly`, `.custom_ratios`, `.peers`, `.to_ai_context`, prompt methods. Underlying upstream HTTP endpoints: **not verified**. | Indian fundamentals/statements, ownership, four-level sector taxonomy, peers, concalls, ratios, AI context. | **India only**, NSE/BSE. No US support claimed. | Package maintainer claims 10–13+ annual years, 12–16+ quarters, 12 quarterly and 11 annual ownership periods, and 40+ concalls. Price-history depth is **not verified**. | No key; free package. No public quota was verified. Package code is MIT, but its README says users must obey upstream terms and mission-critical commercial use needs authorized providers. | Maintainer claims chart cache 6 hours and fundamentals cache 24 hours; upstream refresh schedule/SLA is **not verified**. This is package-maintainer evidence, not an NSE/BSE data license. |
| **Alpha Vantage Stock API** — [documentation](https://www.alphavantage.co/documentation/), [support/rate FAQ](https://www.alphavantage.co/support/), [terms](https://www.alphavantage.co/terms_of_service/) | Base query `https://www.alphavantage.co/query`; verified functions used by current code: `TIME_SERIES_DAILY`, `GLOBAL_QUOTE`. Candidate optional: `TIME_SERIES_DAILY_ADJUSTED`, `NEWS_SENTIMENT`, `EARNINGS_ESTIMATES`, `COMPANY_OVERVIEW`, `INSTITUTIONAL_HOLDINGS`. | OHLCV, EOD quote, optional news/sentiment, estimates, fundamentals, ownership. | Global; official examples include US and Indian BSE symbols. Per-symbol field availability is **not guaranteed**. | Daily endpoint claims 25+ years, but free keys receive only the latest 100 points; `outputsize=full` and adjusted daily series are premium. | Free key verified at 25 requests/day; unlimited quota only for verified open-source/educational projects. No current 5/minute official quota was verified. Terms grant personal, non-commercial use unless agreed otherwise. | `GLOBAL_QUOTE` is updated at end of trading day for free users; real-time/15-minute US data is premium. FinEngine currently requests premium `outputsize=full` (`backend/app/services/alpha_vantage_service.py:270-280`) and assumes 25/day plus 5/minute locally (`backend/app/config.py:34-41`); only 25/day was externally verified. |
| **SEC EDGAR APIs** — [API documentation](https://www.sec.gov/edgar/sec-api-documentation), [fair access](https://www.sec.gov/os/accessing-edgar-data), [reuse FAQ](https://www.sec.gov/os/webmaster-faq) | `https://data.sec.gov/submissions/CIK##########.json`; `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json`; `https://data.sec.gov/api/xbrl/companyconcept/CIK##########/us-gaap/{Concept}.json`. | US issuer identity, filings, audited/reported US-GAAP/IFRS facts, filing dates, fiscal periods. | US SEC registrants, including foreign issuers filing 20-F/40-F/6-K; not Indian domestic coverage. | EDGAR indexes verified from 1994 Q3 to present; company-facts depth is filing history, not a fixed year count. | No API key/authentication. Fair-access maximum 10 requests/second. SEC says government-created and public-filing content is free to access/reuse, subject to declared user agent and acceptable automation policy. | Submissions JSON is updated throughout the day as filings disseminate; bulk structures are republished nightly around 03:00 ET. |
| **NSE Corporate Filings—Shareholding Pattern** — [official page](https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern), [NSE terms](https://www.nseindia.com/static/nse-terms-of-use) | Verified page URL; machine JSON/API endpoint and stable query contract: **not verified**. | Verification source for promoter, public, FII/FPI, MF/AIF, public-shareholding, pledge, and filing dates. | NSE-listed Indian equities; BSE not covered by this source. | Depth visible on the page varies by issuer; not a guaranteed per-ticker API history. | Free public viewing. No public API quota verified. NSE content is owned/licensed; terms prohibit systematic automated collection/aggregation absent permission. | Quarterly reporting plus issuer broadcast dates. Use as a verification/fallback source, not an unattended FinEngine scraper. |
| **Yahoo Finance NIFTY 50 historical page** — [verified page](https://finance.yahoo.com/quote/%5ENSEI/history/) | yfinance/yahoo symbol `^NSEI` via `Ticker.history` or `yf.download`; supported Yahoo HTTP route: **not verified**. | India policy/regional benchmark. | India benchmark. | At least the FinEngine ten-year request path; yfinance supports `max`, actual depth is vendor history. | No key; no fixed quota verified. Yahoo data remains personal-use-only under the yfinance documentation. | Daily vendor bars; no SLA. This is a price index, not a verified total-return index. |
| **Yahoo Finance S&P 500 historical page** — [verified page](https://finance.yahoo.com/quote/%5EGSPC/history/) | yfinance/yahoo symbol `^GSPC` via `Ticker.history` or `yf.download`; supported Yahoo HTTP route: **not verified**. | US policy benchmark. | US benchmark. | At least the FinEngine ten-year request path; yfinance supports `max`, actual depth is vendor history. | No key; no fixed quota verified. Yahoo data remains personal-use-only. | Daily vendor bars; no SLA. This is a price index, not a verified total-return index. |
| **BSE Market Data Products** — [official product page](https://www.bseindia.com/market_data_products.html?flag=real), [official tariff sheet](https://www.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf) | Licensed real-time/EOD/historical products and secure APIs; no free public production endpoint verified. | Exchange-authorized Indian prices, volumes, corporate actions, filings, sector classification, and history. | BSE-listed Indian equities. | Official page states EOD daily data since 1990, scanned quotation files back to 1964, tick data since 2003, and corporate data since 2006. | **Paid/subscription required** for automated data products. Public API rate and redistribution rights depend on purchased license. | Real-time and scheduled snapshot/EOD products; exact entitlement depends on subscription. Deprioritized for an add-ticker basic because it adds cost/licensing. |

### 5.1 Existing backend cross-check

- FinEngine’s actual OHLCV/quote order is configurable between bfinance and yfinance, with Alpha Vantage appended last (`backend/app/services/source_preference_service.py:1-30`, `backend/app/services/source_preference_service.py:81-85`).
- The current default is bfinance, not yfinance (`backend/app/services/source_preference_service.py:24-48`).
- Alpha Vantage maps both `.NS` and `.BO` to `.BSE`; the implementation acknowledges that this is not an NSE feed (`backend/app/services/alpha_vantage_service.py:45-55`).
- The backend does **not** have a direct NSE/BSE downloader. `IndiaDataService.ingest_bhavcopy_records` accepts already-fetched records and persists them (`backend/app/services/india_data_service.py:62-114`); the public NSE-backed analytics query stored institutional flows, delivery anomalies, and OHLCV liquidity (`backend/app/api/analytics.py:2030-2143`). The NSE tables therefore are storage/calculation capability, not a verified official live ingestion pipeline.
- bfinance is the existing India-specific fundamental/ownership/research dependency, yfinance is the existing global fallback, and Alpha Vantage is an optional price/quote fallback (`backend/pyproject.toml:11-42`, `backend/app/services/data_service.py:1-24`).

---

## 6. FREE-SOURCE-OR-BUILD decisions for missing inputs

| Input | Annotation | Basic decision | Full-version boundary |
|---|---|---|---|
| Indian/US prices and history | **[FREE/no new key: build on existing yfinance; bfinance-first is already supported for India]** | Use adjusted close, raw close, and volume with source/fetch/as-of fields. | Do not claim exchange licensing; if commercial/redistributive use is required, licensed vendor data must replace this. |
| Indian fundamentals and valuation | **[FREE/no new key: existing bfinance; US fallback yfinance; US primary-verification SEC EDGAR]** | Show reported values with period and provenance; use missing, never zero, for unavailable values. | Normalize statement taxonomies only after source/period parity is known; do not compare bfinance Ind AS labels to US-GAAP labels as if identical. |
| Indian ownership | **[FREE/no new key: existing bfinance; official NSE page verification only]** | Use bfinance period series and label source `bfinance`; show latest period. | Official NSE reconciliation is a manual/low-frequency audit unless licensed/API permission is obtained. |
| US ownership/insiders | **[FREE/no new key: yfinance holder/insider methods]** | Non-gating informational panel; missing is valid. | SEC 13F aggregation is a different, lagged construct; do not substitute it for issuer holder data without a defined mapping. |
| Forward earnings/revenue estimates and analyst targets | **[FREE proxy/non-gating: yfinance `.earnings_estimate`, `.revenue_estimate`, `.growth_estimates`, `.analyst_price_targets`]** | Display only if present, with analyst count and vendor source; never use as a portfolio-risk input by default. | Production-grade licensed consensus and estimate history is **paid-only**; no paid vendor was selected or verified in this task, so it is deprioritized. |
| Sector/industry map | **[FREE/no new key: bfinance four-level India taxonomy; yfinance `sector`/`industry` for US/global]** | One canonical label plus raw source label; do not merge taxonomies silently. | Curated cross-country GICS-like map is a build task; official BSE/NSE classification feeds are licensed/paid. |
| Listing region | **[BUILD from free existing quote exchange plus `.NS`/`.BO` suffix]** | Derive `IN` or `US` from exchange, with `UNKNOWN` when impossible. | Add issuer domicile/business-region only from filed segment data; listing region must not be mislabeled revenue geography. |
| Benchmarks and macro proxy | **[FREE/no new key: yfinance `^NSEI`, `^GSPC`; existing NIFTY service]** | India-only uses NIFTY 50; US-only uses S&P 500; mixed uses a disclosed region-weighted benchmark. | Total-return benchmarks and live macro series need a licensed/verified feed. Current Yahoo symbols are price indices. |
| Risk-free rate | **[USER INPUT; current static backend default 2%, live official IN/US source not verified]** (`backend/app/config.py:31-32`) | Require annual risk-free input; if omitted, label the existing 2% static assumption. Use the same annual rate before/after; it affects the numerator while differing volatility denominators still affect Δ ratios. | Add official central-bank yield sources only after endpoint, history, terms, and update cadence are verified. |
| News/sentiment | **[FREE headline proxy: yfinance `.news`; FREE-with-key: Alpha Vantage `NEWS_SENTIMENT`]** | Omit from the first add-impact endpoint; no fabricated sentiment score. | Add article-level source, publication time, deduplication, ticker relevance, and a versioned scoring method; never let opaque sentiment alone decide a trade. |
| Spread, order-book impact, lot/circuit microstructure | **[FREE basic proxy: yfinance daily volume; FULL is paid/licensed exchange microstructure]** | ADV participation days only; explicitly no spread or market-impact claim. | Licensed bid/ask/order-book/exchange-rule feeds are paid-only and deprioritized. |

---

## 7. Proposed “add ticker X” flow

### 7.1 One read-only decision endpoint

**Proposed endpoint:** `POST /api/v1/analytics/add-ticker-impact`

It must not mutate `portfolio_positions`. A later explicit add remains a separate user action.

**Conceptual request**

```json
{
  "ticker": "EXAMPLE",
  "position": {
    "amount": 100000,
    "currency": "INR",
    "target_weight": null
  },
  "funding": {
    "mode": "external_cash",
    "amount": 100000,
    "trim": []
  },
  "base_currency": "INR",
  "as_of": "2026-09-24",
  "window": {"start": null, "end": "2026-09-24", "minimum_aligned_sessions": 252},
  "risk": {
    "confidence": 0.95,
    "var_horizon_days": 1,
    "risk_free_rate_annual": 0.02,
    "expected_return_model": "trailing_252"
  },
  "benchmark": {"mode": "auto", "symbol": null},
  "liquidity": {"adv_sessions": 30, "participation_rate": 0.10},
  "scenario": null
}
```

Rules:

- `position.amount` and `position.target_weight` are mutually exclusive; when amount is used, `funding.amount` must equal it. Basic accepts amount. Full may derive amount as `target_weight × (current_value + external_cash)` for external funding.
- All amounts are explicit in `base_currency`; local quantity is advisory and uses the current quote. No execution, tax, brokerage, or recommendation is implied.
- Empty portfolio behavior is explicit: `P=0`, external cash `A` implies candidate post-weight `1.0` and all concentration-diversification metrics follow the single-holding rule.
- If X is already held, this is a top-up: current X market value is increased by A and the pre-trade correlation/weight vector excludes the existing X leg for marginal-correlation reporting.

**Conceptual response contract** (`number|null` is an explicit nullable numeric value, not a filled example)

```text
{
  as_of: string,
  base_currency: "INR" | "USD" | ...,
  data_quality: {
    complete: boolean,
    aligned_sessions: integer,
    sources: Array<{ticker, field, provider, source_used, latest_bar, fetched_on}>,
    freshness: Array<{ticker, latest_bar, calendar_age_days, region_lag_sessions, status}>,
    failures: Array<{code, ticker, affected_metrics, message}>
  },
  funding: {
    mode: "external_cash" | "pro_rata" | "targeted",
    current_value: number,
    funding_amount: number,
    post_value: number,
    trims: Array<{ticker, sale_amount}>
  },
  weights: {
    before: Map<ticker, number>,
    after: Map<ticker, number>,
    candidate_before: number,
    candidate_after: number,
    reconciliation_error: number
  },
  research: {
    fundamentals: {status, provider, as_of, period, fields},
    valuation: {status, provider, as_of, ratios},
    ownership: {status, provider, latest_period, series},
    technicals: {status, provider, latest_bar, indicators},
    peers: {status, provider, method, peers},
    news: {status: "available" | "missing" | "not_shipped", articles},
    estimates: {status: "available" | "missing", analyst_count, estimates}
  },
  risk: {
    annualized_volatility: {before, after, delta, unit: "annualized_fraction"},
    candidate_mrc: {after, unit: "annualized_fraction_per_unit_weight"},
    candidate_risk_contribution: {after, unit: "fraction_of_portfolio_volatility"},
    var_95_1d: {before, after, delta, unit: "loss_fraction"},
    cvar_95_1d: {before, after, delta, unit: "loss_fraction"},
    max_drawdown: {before, after, delta, before_trough_date, after_trough_date},
    sharpe: {before, after, delta, model, risk_free_rate},
    sortino: {before, after, delta, model, risk_free_rate},
    downside_semivariance: {before, after, delta},
    beta: {candidate_before, candidate_after, portfolio_before, portfolio_after, delta, benchmark}
  },
  concentration: {
    hhi: {before, after, delta},
    effective_n: {before, after, delta},
    diversification_score: {before, after, delta}
  },
  dependence: {
    candidate_to_holdings: Array<{ticker, pearson_rho, observations}>,
    candidate_to_portfolio: {before, after, delta},
    tail_dependence: {method, lambda_lower, pairs}
  },
  exposures: {
    sector: {before, after, delta, unknown_share},
    region: {before, after, delta, unknown_share},
    sector_hhi: {before, after, delta},
    region_hhi: {before, after, delta}
  },
  benchmark: {
    symbol_or_rule, base_currency, total_return: boolean,
    tracking_error: {before, after, delta},
    information_ratio: {before, after, delta},
    overlap_sessions: integer
  },
  liquidity: {
    adv_sessions, adv_shares, adv_base, position_shares,
    percent_adv_shares, percent_adv_value,
    liquidation_days: {at_5_pct, at_10_pct, at_20_pct},
    portfolio_max_days, participation_assumptions
  },
  tail_and_scenarios: {
    drawdown_contribution: {episode_start, episode_trough, candidate_pp, all_positions_pp},
    stress: Array<{scenario_id, impact_before, impact_after, delta, deterministic: true}>
  },
  decision_gates: Array<{code, status: "pass" | "fail" | "unavailable", value, user_threshold}>
}
```

`decision_gates` should only evaluate user-supplied policies—for example maximum position, minimum diversification, maximum days-to-liquidate, maximum sector exposure. It should not emit a universal buy/avoid verdict.

### 7.2 Funding and weight semantics

Let:

- `P` = current risky portfolio market value in base currency;
- `V_i` = current holding market value;
- `w_i = V_i/P`;
- `A` = purchase amount for X in base currency;
- `u` = hypothetical post-trade risky weights.

**Basic: external cash**

\[
u_i = \frac{V_i}{P+A}, \quad u_X=\frac{A}{P+A}, \quad \sum_i u_i=1
\]

This is the only ship-first mode because it requires no unstated sale. Current app storage has no cash ledger (`backend/app/models/database.py:11-30`), so the response must call external cash hypothetical rather than implying it was persisted.

**Full: pro-rata funding from current holdings**

For `0 ≤ A ≤ P`, sell `A w_i` from each current holding:

\[
u_i = w_i\frac{P-A}{P}, \quad u_X=\frac{A}{P}
\]

**Full: targeted funding**

Let `A_i` be sale amounts from named holdings, with `ΣA_i=A` and `A≤P`:

\[
u_i = \frac{V_i-A_i}{P}, \quad u_X=\frac{A}{P}
\]

Any funding mix that does not reconcile to `A` is a 422. A user-supplied target weight alone is rejected in basic because the funding source would otherwise be circular and unstated.

### 7.3 Return, currency, and covariance convention

1. Use adjusted-close daily simple returns in each listing currency: `r_i,t = P_i,t / P_i,t-1 - 1`.
2. For a local-currency asset converted into base currency, with `FX_t` quoted as base per local unit:

\[
R_{i,t}=(1+r_{i,t})\left(\frac{FX_t}{FX_{t-1}}\right)-1
\]

3. Basic default is the latest 756 calendar days with at least 252 aligned observations. Full may use five years, rolling windows, and covariance shrinkage.
4. Align IN and US calendars using exchange calendars. Forward-fill only over a verified market holiday. If no calendar is available, basic falls back to common observed dates and marks `mixed_calendar_fallback=true`; it must not forward-fill arbitrary missing history.
5. `Σ = 252 × sample_covariance(R)` using `ddof=1`. Before and after use the exact same dates, price source, FX series, and weights. Any missing holding/candidate leg makes the response incomplete rather than renormalized silently.

### 7.4 End-to-end sequence

1. Canonicalize and validate X; reject invalid or already-held duplicates according to current position rules (`backend/app/api/portfolio.py:176-210`).
2. Load current market values and derive market-value weights; never trust stored weight first (`backend/app/api/analytics.py:178-207`).
3. Refresh/validate X and holdings to one as-of; return source, latest bar, fetched time, and stale reason.
4. Resolve base currency and funding; compute the post-weight vector before fetching optional research.
5. Build the common adjusted-return/covariance/FX frame; fail explicit history/calendar/currency gates.
6. Compute current and hypothetical metrics with identical estimator/window/seed.
7. Build a research panel from existing endpoints without making missing news/estimates look like zero.
8. Return deltas, provenance, policy gates, and failures. Do not mutate the portfolio.
9. If the user later commits the add, refresh the quote again and use a separate position mutation; the impact endpoint’s as-of must be shown beside the stored position update time.

---

## 8. Per-metric design matrix

Status meanings:

- **exists (cite):** the requested post-add quantity itself is already exposed correctly.
- **computable from existing services:** all required price/weight/calculation primitives exist, but a coherent add-impact response is not exposed.
- **missing (new endpoint needed):** the current service also lacks a required benchmark or capability contract.

All rows use the single proposed read-only endpoint unless noted.

### 8.1 Risk, return, and concentration

| # | Metric | Classification and evidence | Mathematical design and assumptions | Input/source tag; basic vs full | Ship-first and decision value | Difficulty | Test oracle |
|---:|---|---|---|---|---|---|---|
| 1 | **Δ annualized portfolio volatility** | **Computable:** market-value weights (`backend/app/api/analytics.py:178-207`), common returns (`backend/app/api/analytics.py:1308-1335`), and covariance engine (`backend/app/services/analytics_engine.py:37-87`) exist. No add endpoint. | `σ(u)=√(u'Σu)`; `Δσ=σ(u)-σ(w)`. At fixed post weights, `∂σ/∂u_X=(Σu)_X/(2σ)`; under external funding, because `du_X/dA=P/(P+A)²`, the per-base-currency derivative is `dσ/dA=(Σu)_X/[2σ(P+A)]`. Basic uses external cash, 756 calendar days, minimum 252 aligned sessions, sample covariance. Full adds rolling windows, Ledoit–Wolf/robust covariance, FX attribution, and estimator sensitivity. | **[BUILD + FREE yfinance/bfinance OHLCV]**; existing CurrencyConversionService for FX. | **YES — ship-first.** Directly changes target weight/add/avoid. | S | Given `Σ=diag(0.04,0.09)` and weights `[0.8,0.2]`, `σ=√(.8²·.04+.2²·.09)` exactly; finite-difference `dσ/dA` matches `(Σu)_X/[2σ(P+A)]`. |
| 2 | **Candidate MRC and Euler RC** | **Computable:** current endpoint already forms `MRC=(Σw)` and `RC=w·MRC/σ` (`backend/app/api/analytics.py:1591-1598`) but returns only normalized RC. | At post weights: standard volatility MRC `MRC_x=(Σu)_x/σ_u`; fixed-weight variance marginal `∂σ/∂u_x=(Σu)_x/(2σ_u)`; external-cash per-currency marginal is row 1’s `dσ/dA`; absolute variance contribution `VC_x=u_x(Σu)_x`; percent volatility contribution `RC%_x=u_x·MRC_x/σ_u`; normalize RC% to 100% for display. `Σ RC% = 1` when σ>0. | **[BUILD existing covariance]**; basic exact Euler. Full adds marginal removal risk and risk budgets. | **YES — ship-first.** Shows whether the position is a diversifier or risk concentrator. | S | Two assets: `Σu` is positive semidefinite; sum of unnormalized `u·(Σu)` equals `σ²`; one long holding has `RC%=100%`. |
| 3 | **Δ one-day historical VaR (95%)** | **Computable:** current 5th-percentile daily return/VaR exists (`backend/app/services/analytics_engine.py:887-902`). | Basic: fixed `c=0.95`, horizon `H=1` trading day, at least 252 observations and at least 20 tail observations. Return losses as positive: `VaR=-quantile_5%(R)`, `ΔVaR=VaR_after−VaR_before`. Full normal-parametric horizon `H`: with daily `μ,σ`, `μ_H=Hμ`, `σ_H=√Hσ`, `VaR_H=-(μ_H-z_cσ_H)` and `z_c=Φ^-1(0.95)=1.6448536`; label it separately from historical. | **[BUILD + FREE returns]**; no paid input. | **YES.** Tail-budget breaches can change size or avoid. | S | On 100 fixed ordered returns, exact 5th percentile/tie rule; loss sign is positive and `ΔVaR=0` for identical weights. |
| 4 | **Δ one-day historical CVaR (95%)** | **Computable:** current tail mean exists (`backend/app/services/analytics_engine.py:893-901`); EVT/ES also exists (`backend/app/services/tail_risk_service.py:70-121`). | Same sample/horizon/confidence as VaR: `CVaR=-mean(R≤q_5%)`; `ΔCVaR=CVaR_after−CVaR_before`. Full normal-parametric `CVaR_H=-(μ_H-φ(z_c)σ_H/c)` at `c=.95`, using the row-3 `μ_H,σ_H,z_c`; EVT POT at 99% is a separate labeled full model and must not be blended with historical CVaR. | **[BUILD + FREE returns]**; basic historical. | **YES.** More sensitive than VaR to candidate tail co-movement. | S | With 100 returns, use 94 zeros plus `[-10%,-9%,-8%,-8%,-7%,-6%]`; NumPy’s linear 5th percentile is `-6.1%`, the six tail observations average `-8%`, and loss-positive CVaR is `8%`. |
| 5 | **Δ maximum drawdown** | **Computable:** path MDD exists (`backend/app/services/analytics_engine.py:906-920`) and tear sheet supplies an underwater series (`backend/app/api/analytics.py:1524-1545`). | **Historical-path, not forecast:** fixed post weights, no intra-period rebalance/cost; `V_t=Π(1+R_{p,t})`, `DD_t=V_t/max_{s≤t}V_s−1`, `MDD=min DD_t`; return both MDD magnitude and date. Full: stationary-bootstrap paths with seed and confidence bands using the existing bootstrap primitive (`backend/app/services/monte_carlo_service.py:110-137`). | **[BUILD + FREE returns]**; basic 756-day path. | **YES.** Can change long-horizon add/avoid/size decisions. | M | Return path `[+10%,-20%,+5%]` has max drawdown exactly `-20%`; identical before/after returns have Δ=0. |
| 6 | **Δ HHI** | **Computable:** true `HHI=Σw²` is already implemented (`backend/app/services/analytics_engine.py:224-228`). | `HHI_after=Σu_i²`; `ΔHHI=HHI_after−HHI_before`. Always non-negative, including external cash. Include all nonzero risky positions; cash is zero only in a separate cash-drag view. | **[BUILD existing concentration]**; basic. Full adds sector HHI separately. | **YES — ship-first.** Immediate concentration/weight constraint. | S | `[.5,.3,.2]` gives HHI `.38`; adding an externally funded fourth leg must not exceed `.38` if all old weights fall. |
| 7 | **Δ effective N and diversification score** | **Computable:** `N_eff=1/HHI`, normalized score, and single-holding zero are implemented (`backend/app/services/analytics_engine.py:227-249`). | `N_eff_after=1/HHI_after`; `ΔN=N_after−N_before`; score `100(1−HHI)/(1−1/N)` for `N>1`, otherwise exactly `0`. | **[BUILD existing concentration]**; basic. Full also reports percentage-point score delta. | **YES — ship-first.** Converts concentration into an interpretable effective breadth. | S | `[.5,.3,.2]` gives `N_eff=1/.38`; one holding gives `N_eff=1`, `N_eff/N=1`, diversification score `0`. |
| 8 | **Δ Sharpe** | **Computable:** current trailing mean/vol Sharpe exists (`backend/app/services/analytics_engine.py:846-872`). | Expected-return model is **descriptive trailing**, not a forecast: `μ̂_p=252·mean(R_p)`, `σ̂_p=√252·std_ddof1(R_p)`, `Sharpe=(μ̂_p−r_f)/σ̂_p`. Basic uses 252 aligned sessions and annual `r_f`; full shows 63/252/756 sensitivity and optional user-supplied forward assumptions with source. | **[BUILD + FREE returns]**; static 2% current default only if explicitly labeled; no consensus forecast. | **YES, but with stability flags.** A material/window-consistent change can alter weight. | S | Constant mean `μ_d` and sample std `σ_d` yield `Sharpe=(252μ_d−r_f)/(√252σ_d)`; zero volatility returns null. |
| 9 | **Δ Sortino** | **Computable:** current Sortino uses daily risk-free target and downside deviation of the full return series (`backend/app/services/analytics_engine.py:866-872`). | `DD=√(252·mean(min(0,R_p−r_f/252)²))`; `Sortino=(μ̂_p−r_f)/DD`; same trailing-return model/window as Sharpe. Full reports downside capture and target sensitivity. | **[BUILD + FREE returns]**; no paid input. | **YES.** Can distinguish added downside asymmetry that Sharpe misses. | S | Returns with zero negative excess return yield null/0 according to disclosed policy; known negative vector gives exact annualized downside deviation. |
 
### 8.2 Dependence, exposure, and benchmark

| # | Metric | Classification and evidence | Mathematical design and assumptions | Input/source tag; basic vs full | Ship-first and decision value | Difficulty | Test oracle |
|---:|---|---|---|---|---|---|---|
| 10 | **Candidate correlation to each current holding** | **Computable:** `_build_wide_returns` and pandas returns are available (`backend/app/api/analytics.py:1308-1335`); correlation-stability already computes every unique pair internally (`backend/app/services/correlation_service.py:52-62`). Current response exposes only average correlation. | Basic Pearson `ρ_Xi=corr(R_X,R_i)` over 252 aligned sessions; return `{ticker, rho, observations}`. Also return pre-trade weighted average `Σw_iρ_Xi` and full matrix for X. Full adds 63-day rolling, Fisher-z CI, and missingness. | **[BUILD + FREE yfinance/bfinance returns]**; basic 252 sessions. | **YES.** High average correlation can overturn a diversification argument. | S | `X=[1,2,3]`, holding `[2,4,6]` gives exactly `ρ=1`; a zero-variance leg returns null. |
| 11 | **Candidate correlation to hypothetical portfolio** | **Computable:** both return series can be built from existing services; no current endpoint returns this pair. | `ρ(X,P)=corr(R_X,R_p^after)`. Also return pre-trade `ρ(X,P^before)` and Δ. Linear correlation is not a tail-dependency substitute. | **[BUILD + FREE returns]**; basic. Full adds downside correlation and rolling stability. | **YES.** A high portfolio correlation is a compact add/avoid warning. | S | If X is exactly twice the pre-portfolio daily return, correlation is `+1`; if constant, null. |
| 12 | **Δ sector exposure** | **Computable:** current sector weights come from persisted quote metadata and market-value weights (`backend/app/api/analytics.py:731-755`); candidate sector is already available from quote/bfinance (`backend/app/services/data_service.py:535-569`, `backend/app/services/equity_research_service.py:77-83`). | For group g: `s_g=Σ_{i∈g}u_i`; return before, after, delta, and candidate contribution `u_X` if X belongs to g. Unknown sector is a visible bucket and blocks a “complete” flag when material. | **[BUILD + FREE existing sector labels]**; basic. Full retains raw and canonical taxonomy. | **YES.** Direct concentration-drift and mandate check. | S | Sector weights sum to 1 including `UNKNOWN`; adding Technology adds exactly its post weight to the Technology bucket. |
| 13 | **Δ listing-region exposure** | **Computable in part:** `region` is stored on each position (`backend/app/models/database.py:15-27`) and quote/suffix determine exchange (`backend/app/services/data_service.py:489-495`, `backend/app/services/data_service.py:555-569`). No current analytics consumes region. | Define region as **listing/exchange region**, not revenue geography. `r_k=Σu_i`; return before/after/delta. Derive `IN` for `.NS`/`.BO`, `US` for US securities, otherwise `UNKNOWN`; do not trust a default alone. | **[BUILD from free quote/suffix]**; basic. Full adds issuer domicile/segment geography only with filed-source evidence. | **YES.** A US/IN mix changes FX and benchmark context. | S | Regions partition all post weights to 1; a candidate’s region delta equals its post weight in that region. |
| 14 | **Sector concentration drift** | **Computable:** current sector shares exist (`backend/app/api/analytics.py:731-755`); group HHI is a new grouping over them. | `HHI_sector=Σg s_g²`; return before/after/Δ and `max_g(s_g^after−s_g^before)`. Unknown is included and separately flagged. | **[BUILD + FREE sector labels]**; basic. | **YES.** Detects concentration hidden by ticker-level diversification. | S | Two sectors `[.5,.5]` give sector HHI `.5`; a new third sector must reduce HHI when funded externally. |
| 15 | **Region concentration drift** | **Computable:** region storage and listing inference exist (`backend/app/models/database.py:20-27`, `backend/app/services/data_service.py:489-495`). | `HHI_region=Σk r_k²`; before/after/Δ plus largest absolute bucket drift. | **[BUILD from free listing metadata]**; basic. | **YES.** Relevant to cross-border concentration. | S | `[.6 IN,.4 US]` gives `.52`; post external-cash India addition must lower it. |
| 16 | **Δ tracking error** | **Missing (new benchmark-aware endpoint):** current benchmark service is fixed to NIFTY 50 (`backend/app/services/benchmark_service.py:19-23`, `backend/app/services/benchmark_service.py:72-96`); no TE route/field exists. | `TE=√252·std_ddof1(R_p−R_b)` on 252 aligned sessions; `ΔTE=TE_after−TE_before`. Auto benchmark: NIFTY for ≥80% IN, S&P 500 for ≥80% US, otherwise `R_b=Σr_region R_region_benchmark`. Explicitly label price-index benchmark. | **[BUILD from FREE yfinance `^NSEI`/`^GSPC`]**; basic. Full requires verified total-return/regional benchmarks. | **NO for stock add basic.** Usually mandate/attribution context, not a single-stock gate. | M | Constant active-return spread has TE 0; a fixed vector reproduces sample standard deviation exactly. |
| 17 | **Information ratio and ΔIR** | **Missing (new endpoint needed):** no IR implementation or chosen policy/mixed benchmark exists. Benchmark limitation is the same as row 16. | `active_t=R_p,t−R_b,t`; `IR=252·mean(active)/(√252·std(active))`; null when TE=0. Return before/after/Δ and active-return mean. | **[BUILD from FREE benchmark returns]**; basic after benchmark policy exists. | **NO for stock add basic.** Relevant for strategic allocation, not default single-name add. | S | Double every active return leaves IR unchanged; sign follows mean active return; zero dispersion returns null. |

### 8.3 Liquidity, downside, beta, drawdown, and stress

| # | Metric | Classification and evidence | Mathematical design and assumptions | Input/source tag; basic vs full | Ship-first and decision value | Difficulty | Test oracle |
|---:|---|---|---|---|---|---|---|
| 18 | **30-session ADV** | **Computable:** current liquidity service already averages volume and close × volume (`backend/app/services/analytics_engine.py:278-336`, `backend/app/services/india_data_service.py:285-301`). | Use **raw close** for traded value, not adjusted close: `ADV_shares=mean(volume_{last30})`; `ADV_base=mean(close×volume_{last30})`. Return both, sample count, first/last date, zero-volume count. | **[BUILD + FREE yfinance/bfinance daily volume]**; basic 30 sessions. | **YES — ship-first.** Capacity depends on the actual proposed size, not a generic liquidity score. | S | Volumes `[100,200,300]` have ADV 200; average rupee ADV equals average of each day’s traded value. |
| 19 | **Position as % ADV** | **Computable:** buy amount and latest price are already inputs to the proposed flow; current per-position volume metrics exist (`backend/app/services/analytics_engine.py:328-336`). | `q=A/P_spot`; `%ADV_shares=100q/ADV_shares`; `%ADV_value=100A/ADV_base`. Return both because share and currency ADV diverge after price moves. | **[BUILD + FREE quote/OHLCV]**; basic. | **YES — ship-first.** A direct size-capacity measure. | S | `A=1,000`, price 10, ADV 100 shares ⇒ q=100, `%ADV=100%`; value test is identical at constant price. |
| 20 | **Estimated liquidation days** | **Computable:** exact helper formula exists (`backend/app/services/india_data_service.py:45-52`) and portfolio limits return 10%/20% participation results (`backend/app/services/india_data_service.py:299-327`). The ad-hoc API uses fake notional, so proposed amount semantics are new. | `days=A/(p·ADV_base)`, basic `p=10%`; full returns 5%/10%/20%. For the book, return value-weighted average **and maximum holding days**; maximum is the bottleneck and must not be hidden by averaging. This is a participation estimate, not an execution forecast. | **[BUILD + FREE volume]**; basic 10%, full 5/10/20 plus spread model. | **YES — ship-first.** Can reduce target size or block an illiquid addition. | S | `A=100,000`, `ADV=500,000`, `p=.10` ⇒ 2 days exactly. |
| 21 | **Price/volume freshness** | **Computable:** DB rows carry source/fetch time (`backend/app/models/database.py:43-54`), and technical data has a stale guard (`backend/app/services/indicators_service.py:97-114`). | Return source, fetched time, latest bar date, calendar age, and region-relative bar lag. Basic rejects no bar, zero/non-positive price, zero latest volume, or age >10 days; if same-region peers exist, reject more than three sessions behind the freshest same-region bar. Full uses NSE/NYSE calendars. Generated quote timestamp is not a vendor timestamp. | **[BUILD existing cache/provenance]**; basic. | **YES — ship-first.** A mathematically correct number on stale data is not decision-grade. | S | Friday data on the following normal Monday is fresh; a ten-day-old bar fails even if fetched today. |
| 22 | **Downside-risk delta** | **Computable:** Sortino, skew, historical CVaR, and EVT/ES already exist (`backend/app/services/analytics_engine.py:846-920`, `backend/app/services/tail_risk_service.py:24-155`). | Basic annualized semivariance `252·mean(min(0,R_p−r_f/252)²)`, worst one-day return/loss, and 95% CVaR; return before/after/delta. Full adds expected-shortfall distribution and regime-conditioned downside. | **[BUILD + FREE returns]**; basic. | **YES.** Identifies tail asymmetry that total volatility can hide. | S | A 252-observation vector with one `-10%` and 251 zeros has annualized downside second moment `252×(0.10²/252)=0.01` before target-rate adjustment. |
| 23 | **Candidate beta and Δ portfolio beta** | **Computable:** OLS/HAC market beta and portfolio beta exist (`backend/app/services/analytics_engine.py:1118-1192`). | `β_X=Cov(R_X,R_b)/Var(R_b)` and `β_p=Σu_iβ_i`; basic 252 aligned sessions, minimum 60 and warning below 252. Full uses rolling beta, robust standard errors, and region-specific benchmarks. | **[BUILD + FREE benchmark/returns]**; basic for auto benchmark. | **YES.** A high-beta candidate can change regional risk even with low standalone correlation. | S | If `R_X=2R_b`, beta is 2; if portfolio weights sum 1, portfolio beta equals the weighted betas. |
| 24 | **Drawdown contribution** | **Computable:** MDD path is built and per-day asset returns are available; current CVaR tail attribution is related but not drawdown attribution (`backend/app/api/analytics.py:1591-1610`). | Define basic as contribution over the **pre-trade maximum-drawdown episode**: identify pre-peak/trough dates, then `DD_RC_X=Σ_{t in episode}u_X R_X,t`, where `R_X,t` is the candidate’s base-currency daily return; normalize by pre-peak value to percentage points. Also return all holding contributions, which sum to the portfolio’s arithmetic return over that episode. Full repeats across the three deepest historical episodes and bootstrap MDD contributions. | **[BUILD + FREE returns]**; basic historical event. | **YES.** Identifies which leg caused the actual observed drawdown; label this path-dependent, not universal causal attribution. | M | On a two-day episode, sum of asset arithmetic contributions equals the weighted portfolio return; signs can offset. |
| 25 | **Stress/scenario delta** | **Computable:** current stress weights, sector multipliers, and weighted impact exist (`backend/app/services/analytics_engine.py:410-557`); request tickers can include a candidate, but no post-funding/candidate sector contract is returned. | Basic: evaluate current `w` and post `u` on the same existing scenario; `impact_p=Σu_i shock_i`, `Δimpact=impact_after−impact_before`. Candidate shock is sector multiplier × market shock unless user supplies a candidate shock. Full accepts a versioned user shock vector; no model calls these “forecasts.” | **[BUILD existing scenario service]**; basic deterministic. | **YES.** Sector/rate/crash scenarios can change add/size decisions. | M | Position impacts multiplied by weights sum exactly to portfolio impact; identical weights give Δ=0. |

**Add-impact metric count:** 25.  
**Classification count:** 23 computable from existing services; 2 missing behind the new benchmark-aware endpoint; 0 requested deltas already exist coherently end-to-end.  
**Ship-first count:** 23 of 25. Only TE and IR are non-ship-first defaults for a single-stock decision.

---

## 9. Prioritized backlog

| Priority | Smallest deliverable | Why now | Source annotation |
|---:|---|---|---|
| **P1-1** | Freeze the read-only add-impact request/response schema and funding resolver: external cash basic; pro-rata/targeted full; exactly one of amount/target weight. | Every current metric depends on an unambiguous post-weight vector; this is the root missing contract, not another model. | **[BUILD existing DataService/portfolio model; FREE inputs]** |
| **P1-2** | Return one coherent before/after core: Δvol+MRC, ΔHHI+N_eff, Δ historical VaR/CVaR/MDD, candidate correlations, sector/region exposure and concentration drift. | Reuses proven primitives and contains the highest-value decision deltas. | **[BUILD + FREE yfinance/bfinance OHLCV; existing bfinance sector labels]** |
| **P1-3** | Add amount-aware 30-session ADV, %ADV, 10% participation days, 5/10/20 sensitivity, and explicit freshness/source gates. | Replaces the fake-notional ad-hoc liquidity behavior with a true capacity answer. | **[BUILD + FREE daily volume; paid microstructure explicitly excluded from basic]** |
| **P1-4** | Add one shared return/FX/calendar window plus provenance and deterministic test fixtures; make stale/missing legs fail closed. | Prevents mathematically neat but incomparable IN/US results and makes every later metric reproducible. | **[BUILD existing cache + CurrencyConversionService; FREE]** |
| **P2-1** | Generalize benchmark selection to NIFTY, S&P 500, and disclosed mixed-region benchmark; add TE/IR. | Required for US/mixed portfolios; current NIFTY hard-coding is insufficient. | **[BUILD from FREE yfinance `^NSEI`/`^GSPC`; verified price-index-only]** |
| **P2-2** | Add a sourced research panel: fundamentals, valuation, ownership, technicals, India peers; include US peers built from sector/industry/market-cap fields. | Gives X context without allowing opaque ratios to replace portfolio impact. | **[FREE/no key: bfinance India, yfinance US/global, SEC EDGAR US verification]** |
| **P2-3** | Add non-gating estimates/recommendation disclosure when present, with analyst count/as-of/source. | Can inform basic choice, but coverage and legal stability are weaker than reported fundamentals. | **[FREE proxy: yfinance estimates/targets; production consensus is PAID-only and deprioritized]** |
| **P2-4** | Add rolling-window estimator stability: 63/252/756 return, volatility, Sharpe, Sortino, and covariance shrinkage diagnostics. | A single trailing window can reverse a decision; stability is the smallest honest defense. | **[BUILD + FREE returns; no new key]** |
| **P2-5** | Normalize sector/industry and listing-region taxonomies, retain raw labels, and expose `UNKNOWN` coverage. | Required before sector HHI/region HHI can be gates. | **[BUILD from FREE bfinance/yfinance metadata and ticker suffixes]** |
| **P2-6** | Add candidate-aware downside, beta, drawdown-episode contribution, and deterministic stress deltas; seeded bootstrap only in full. | Completes risk diagnosis after basic deltas work. | **[BUILD existing analytics/regime/stress/tail/bootstrap; FREE returns]** |
| **P3-1** | Add article-level news/sentiment panel with source, publication time, relevance, deduplication, and model/version. | Useful context but not needed to answer portfolio-impact questions and sentiment can be noisy. | **[FREE headline proxy: yfinance `.news`; FREE-with-key: Alpha Vantage `NEWS_SENTIMENT`; non-gating]** |
| **P3-2** | Acquire licensed total-return benchmarks, exchange microstructure/spread data, official classification feeds, and commercial consensus. | Improves production quality/commercial rights but adds cost and integration/licensing work. | **[PAID-only/deprioritized]** |

**Backlog count:** 12 — P1=4, P2=6, P3=2.

---

## 10. Known limitations and data-quality gates

### 10.1 Data/provenance limitations

1. **No exchange-real-time entitlement:** quote values are vendor/cache values and timestamps are locally generated (`backend/app/services/data_service.py:465-469`, `backend/app/services/data_service.py:555-569`). The add endpoint must say “vendor/on-cache,” not “real-time exchange.”
2. **Position provenance is inaccurate on add:** the route hard-codes yfinance even though the configured source may be bfinance (`backend/app/api/portfolio.py:212-235`, `backend/app/services/source_preference_service.py:24-30`). Historical source truth exists in `stock_timeseries.source_used` (`backend/app/models/database.py:43-54`) and must be joined for market metrics.
3. **Alpha adjusted-price contamination:** the free/full mismatch means Alpha’s unadjusted close is stored as `adj_close` (`backend/app/services/alpha_vantage_service.py:270-297`). Add-impact risk must return null if this source is selected outside a corporate-action-safe window.
4. **Equity-research provenance gap:** fundamentals cache for 24 hours and responses do not include vendor/as-of (`backend/app/services/company_data_service.py:189-234`, `backend/app/models/schemas.py:478-542`). Values are usable only as informational snapshots unless enriched with source metadata.
5. **No current news/estimates:** the current route/service inventory has no news, sentiment, estimate, recommendation, or target-price surface (`backend/app/api/data.py:47-154`, `backend/app/api/equity_research.py:37-257`, `backend/app/services/company_data_service.py:64-379`). The new endpoint must expose `missing`/`not_configured`, never `0`, neutral sentiment, or consensus return.
6. **Peers and ownership are India-only upstream payloads:** no US peer/ownership builder exists (`backend/app/services/equity_research_service.py:66-69`, `backend/app/services/equity_research_service.py:125-190`).
7. **Region is user metadata, not validated geography:** schema/database default it independently of ticker exchange (`backend/app/models/schemas.py:11-19`, `backend/app/models/database.py:15-27`). Derive listing region from suffix/quote for decisions and retain user region as an audit field.
8. **NSE tables are not an ingestion feed:** records must be supplied to the bhavcopy ingestion method (`backend/app/services/india_data_service.py:62-114`); no official download adapter is present.
9. **Liquidity fallbacks are unsafe for add sizing:** the ADV service substitutes 10,000/50,000-share ADV and 0.05 Amihud when data is absent (`backend/app/services/india_data_service.py:285-301`). The add endpoint must return unavailable, never these fallbacks.
10. **Forecast defaults are not measurements:** GARCH/EGARCH failures can return 0.22/0.24 annual-vol defaults (`backend/app/services/analytics_engine.py:994-1014`, `backend/app/services/analytics_engine.py:1037-1056`). Exclude forecast VaR from the first ship-first core.
11. **Stress confidence is not statistical:** the stress response’s 0.95 confidence is hard-coded beside fixed shocks (`backend/app/services/analytics_engine.py:539-556`). Rename it in the proposed response to `scenario_id`; do not present a confidence interval.
12. **Benchmark is NIFTY-only and price-return:** benchmark symbol is fixed (`backend/app/services/benchmark_service.py:19-23`) and no total-return series is verified. Mixed/US TE/IR therefore requires a benchmark-policy change.
13. **FX fallback is fixed at 83:** currency conversion can silently return a hard-coded fallback to the caller even though it is not cached (`backend/app/services/currency_service.py:15-18`, `backend/app/services/currency_service.py:55-68`, `backend/app/services/currency_service.py:180-190`). Add-impact must expose fallback state and fail ship-first mixed-currency calculations when live FX is unavailable.
14. **Ad-hoc analytics can imply false weights:** non-DB tickers are equal weighted by `resolve_allocation` (`backend/app/api/analytics.py:78-97`), performance history gives them quantity 1 (`backend/app/api/analytics.py:1206-1220`), and ad-hoc liquidity creates fake positions (`backend/app/api/analytics.py:2101-2107`). The new endpoint must not reuse any of these as candidate valuation semantics.

### 10.2 Mandatory gates before a metric can affect a decision

| Gate | Pass condition | Failure behavior |
|---|---|---|
| Identity/listing | Canonical ticker, positive quote, recognized listing region | 404/422; no analysis. |
| Funding | Positive A; exact source-of-truth; weights sum 1 within tolerance | 422; no before/after math. |
| Currency | Quote currency known; base conversion available and not fallback | Return local-only research; block base-currency risk deltas. |
| Price completeness | All legs have positive adjusted close and raw close; no Alpha unadjusted fallback in risk window | Null affected metrics and list ticker/source failure. |
| Freshness | Latest bar ≤10 calendar days and not >3 sessions behind freshest same-region peer | Block liquidity; stale flag may permit informational display only. |
| History | ≥252 aligned sessions for ship-first annualized/covariance/tail metrics; 60 minimum only as explicitly low-confidence | Return non-annualized facts where meaningful; never annualize a short sample. |
| Calendar/FX | Returns use one documented alignment rule; no arbitrary fill; FX observations present for every asset date | Mixed-calendar fallback flag; block gate decision if more than 10% dates are fallback-only. |
| Covariance | Symmetric, finite, PSD within tolerance; condition-number/count diagnostic | Fall back to diagonal/shrunk covariance in full; null in basic if not repairable. |
| Tail | At least 20 observations at/below the 95% threshold | Return VaR with low-confidence flag; null CVaR if tail mean is not supported. |
| Sector/region | ≥95% post portfolio value classified or user explicitly accepts `UNKNOWN` | Do not pass sector/region concentration gates. |
| Benchmark | Same base currency, same dates, explicit symbol/region-weighted rule | TE/IR null; risk/return deltas remain valid. |
| Liquidity | 30 positive-volume sessions, current price, current ADV base value | Liquidity unavailable; never use fallback ADV. |
| Research provenance | Vendor/method, period/as-of, and missingness reported | Informational item cannot be a decision gate. |
| Reproducibility | Window, source set, weights, estimator, rf, confidence, horizon, participation, and seed returned | Reject mismatch between before and after calculations. |

### 10.3 Explicit non-goals

- No order routing or execution workflow is included.
- No DCF or price target is invented from insufficient assumptions.
- No “sentiment score” without a versioned scoring method and source timestamps.
- No paid vendor is introduced for ship-first metrics.
- No add endpoint writes portfolio state.

---

## 11. Verification limitations

- External verification covered publisher documentation/package metadata and current official pages, not live per-ticker payload completeness. yfinance/bfinance field availability for every IN/US security remains unverified.
- bfinance history, peers, ownership, concall, cache, and upstream-source claims are package-maintainer claims; the underlying NSE/BSE HTTP endpoints and licenses were not independently verified.
- Alpha Vantage’s free 25/day limit was verified; a current 5/minute quota was not. Premium-only `outputsize=full` behavior conflicts with the local free-fallback assumption.
- Yahoo benchmark pages verify symbols and historical availability, not a supported public HTTP API, total-return methodology, or SLA.
- NSE’s public shareholding page was verified for manual reconciliation only; a stable permitted machine endpoint and quota were not verified. BSE automated market data is paid/licensed.
- SEC EDGAR is suitable for US filed fundamentals and identity, not Indian fundamentals or real-time prices.
- No live NSE/BSE/yfinance/Alpha Vantage request was made against production symbols during this documentation-only audit; conclusions about service wiring are static-code conclusions.
