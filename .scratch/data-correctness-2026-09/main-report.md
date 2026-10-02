Verdict: No, you are not getting the data you need
130+ individual findings collapse into 5 root causes. The most important thing I found is not on any bug list — it emerged only from putting two reports side by side.
Root cause #1 — bfinance fabricates its price bars (CRITICAL, cross-repo)
bfinance/src/bfinance/market/ohlcv.py:189-194:
Open = prev_close.shift(1).bfill()
High = max(O, C) * 1.002
Low  = min(O, C) * 0.998
Measured against real yfinance on RELIANCE.NS: 0.56% mean error on Open, 0.41% High, 0.60% Low. These are not approximations — a max/min envelope is mathematically incapable of representing an intraday range. auto_adjust=True is a no-op column drop (Adj Close == Close, and yfinance's real rescale factor was measured at 0.9954).
Critically, bfinance already tells you: it sets df.attrs["bfinance_synthetic_ohlc"] = True on every frame (ohlcv.py:165,249). finengine never reads that flag.
So every quantitative page in your app computes on an invented price path:
Page	What it computes from the synthetic bar
realized-risk	realized vol, Sharpe, Sortino, hit ratio, MDD
forecast-risk	GARCH/EWMA conditional vol, VaR/CVaR
risk-studio	EVT-POT tail fit, Student-t copula, Parkinson vol
volatility-sizing	inverse-vol parity weights
liquidity	mean(volume) × last_close turnover (itself a bug, see #4)
stress-testing	volatility scalar per ticker
pairs	spread z-score, OU half-life
tear-sheet	underwater curves, monthly heatmap
The fix is cheap and cookie-free: nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_...csv.zip is a static zip, no auth, no session. Effort S.
Root cause #2 — bfinance's statement period order is INVERTED vs yfinance, and finengine consumes it directly
Neither subagent could see this alone. A3 found ticker.py:229,241,253 return to_dataframe(orient="columns") and never call the already-existing to_yfinance() converter. A2 found company_data_service.py:347-352 calls exactly those methods.
The consequence:
 	bfinance	yfinance
Column order	ascending (oldest first)	descending (newest first)
Columns	str 'Mar 2015'	DatetimeIndex
Units	₹ Cr	absolute ₹
Row labels	'Sales'	'Total Revenue'
df.iloc[:, 0] or .iloc[:, -1] returns a 10-year-old number as the current period — no exception, no warning. This is live on /dashboard/equity-research (financial statements tab) and the 8-tab Excel export. models/statements.py:88 has the correct converter; it's dead code because the tests call it directly instead of going through Ticker.
Root cause #3 — the India ingestion layer is a schema with no producer
You have 4 tables (nse_bhavcopy, nse_institutional_flows, nse_bulk_block_deals, nse_shareholding_patterns), a careful india_data_service.py with validation + upsert, and 3 live routes reading them. There is no HTTP fetcher and no scheduler anywhere in the codebase. The tables are structurally guaranteed empty.
Good news: india_data_service.py:29-32 field contract already matches the NSE CM bhavcopy schema exactly. t28 is "wire up a producer", not "design a schema". (One bug: len(rows) < 3 at :395 means it can never emit a row.)
Root cause #4 — the unit contract is undeclared, so both layers guess
market_cap has four spellings in three units and no declaration at the quote boundary:
data_service.py:934            fast_info.market_cap        ← unit undeclared
data_service.py:981            info["marketCap"]           ← absolute ₹
equity_research_service.py:87  market_cap / marketCapInCr  ← ₹ Cr
company_data_service.py:186    r.market_cap * 1e7          ← absolute ₹
Its consumer compares against hardcoded rupee thresholds (analytics_engine.py:751,755,759), and a Cr-valued reading drops a mega-cap two tiers with market_cap_provenance: "measured". Same class of bug on the frontend: liquidity:391, stress-testing:537-561, volatility-sizing:809 all use Math.abs(v) <= 1.0 ? v*100 : v — a scale-sniffing heuristic that mis-renders any legit value in (-1,1].
And the flagship: portfolio/manage/page.tsx:786 renders volatility_forecast.toFixed(2)}% with no ×100, so a real 25.4% vol displays as "0.25%". Line 163's getRiskLevel is a stale pre-fraction copy (if (volatility < 20) return 'Low' is always true) — so every position shows a green "Low" risk badge regardless of actual risk.
Root cause #5 — the app returns plausible numbers where it has no measurement
This is systemic across all three layers, and it violates your own stated principle in CONTEXT.md §9.23 ("engines must never render placeholder fallbacks — return N/A + a flag").
Layer	Example	Reads as
bfinance	sector.py:9-54 — Sector.top_companies is 40 lines of hardcoded literals. TCS cmp=3950.0, mcap=1420000 forever	live market data
bfinance	ticker.py:82-86 — unresolved symbol yields info['currentPrice'] = 0.0	a real quote
bfinance	screens.py:115,216 — DivYield_% is ×100 too high, and the >= 0.025 threshold is a no-op that passes every dividend payer	a working quant screen
bfinance	quotes.py:246 — returnOnCapitalEmployed is percent while returnOnEquity/returnOnAssets in the same dict are fractions	100× discontinuity
bfinance	parser.py:203,209 — or-chain turns a genuine 0.00 into None. Result: INFY, HDFCBANK, TCS all report debtToEquity=None	missing data
bfinance	ai/context.py:166 — strips blank lines, so every table in the AI dossier renders as run-on pipes (visible in your own committed exports/TCS_AI_Dossier.md:11-13)	valid markdown
backend	websocket.py:472-489 — publishes change: 0.00, volume: 0, and a weeks-old close stamped datetime.now()	a live ticker
backend	portfolio.py:1675 — quote failure swallowed; serves stale last_price as live, and as_of = max timestamp makes the whole book look fresh	fresh pricing
backend	data_service.py:838 — ProviderInvalidInputError falls through to bare return None → HTTP 404 "No data found" for a ticker that exists	ticker not found
backend	alpha_vantage_service.py:85-88 — Tier-3 is 100% dead for every .NS/.BO ticker. Your "3-tier cascade" is 2-tier	3-tier resilience
backend	cache_service.py:449 — success_rate_24h reads 0.0% on a fully-cached healthy system	broken feed
quant	analytics_engine.py:2532 — _empty_concentration returns HHI=0.0, diversification_ratio=1.0 → concentration_score: 0.0 is scored into overall_score as minimum risk	zero concentration risk
quant	analytics_engine.py:674 — a 1-stock book publishes diversification_score: 0.0 and diversification_ratio: 1.0 simultaneously	100% diversified
quant	analytics_engine.py:1013 — stress vol drops all zero-return days → +11.8% overstated vol → every stress loss inflated	measured vol
quant	volatility_service.py:164-170 — GARCH "multi-step" uses np.mean(variance_path), so horizon=63 is flat at 19.1% instead of ~87%	63-day forecast
quant	analytics_engine.py:737 — turnover = mean(volume) × last_close instead of mean(volume × close) → 2× error moves names across liquidity tiers	avg daily turnover
frontend	tear-sheet/page.tsx:56,72,79,95,109,165 — EXPLAINERS presents invented portfolio-specific numbers as "Quantitative Benchmark": "Current Portfolio: 1.26 vs NIFTY 50: -0.20", "Motherson 13.6%, JuniorBees 12.8%"	live benchmark
frontend	stress-testing/page.tsx:684,598,773 — labels a deterministic factor proxy "Multi-Factor Simulation Engine" / "Run Simulation", while the backend publishes impact_basis: "deterministic_factor_proxy" and a methodology field the page never renders	a Monte Carlo ran
frontend	pairs/page.tsx:100 — p.current_spread_zscore.toFixed(2) is unguarded but the API type is Optional[float] → TypeError, white screen	—
The one structural gap nobody asked about
A6 found it, and it's upstream of most of the backlog:
You have no book of record. No transactions table, no lot ledger, no cash balance. PortfolioPosition is one row per ticker with quantity / buy_price / added_on, and GET /analytics/performance-history reconstructs history as quantity × past_price.
So every "realized" P&L, tear-sheet, and attribution number is a hypothetical buy-and-hold of today's book. Add a second lot or take a partial exit and the whole foundation shifts.
Compounding it, two hardcoded constants are wrong:
- config.py:53 — risk_free_rate = 0.02. Indian 91-day T-bills yield 5–7.5%. This poisons alpha, Sharpe, Sortino, information ratio, the Black-Litterman posterior, and Monte Carlo drift.
- benchmark_service.py:20 — ^NSEI close, not Total Return. niftyindices publishes explicit Total Returns Index columns. Understates by ~dividend yield (~1.2–1.4%/yr), compounding straight into understated active return.
Both are ~150 lines total and both are free to fix correctly.
What belongs in bfinance
You said: keep yfinance-compatible but extend freely. Ordered by unblocking value:
#	Item	Why	Effort
1	bfinance.nse.bhavcopy() + bhavcopy_range() — real OHLCV, dual UDiFF/legacy parser	Fixes root cause #1, every quant page at once. Cookie-free.	S
2	Ticker.get_*_stmt → return to_yfinance()	Root cause #2. Converter already exists and is tested.	S
3	Cache overhaul: validate-before-write, price TTL to minutes, Ticker.refresh(), contextlib.closing for the per-call connection leak	Kills a 24h stale-price window, a 24h poisoned-cache class, a process-lifetime freeze, and explains your flaky CI	S
4	Delete the equity-capital-ratio split heuristic (corporate.py:106-119)	Vodafone Idea has 4 fabricated "splits" despite never having had one. Corrupts actions, history()['Stock Splits'], and every return calc.	S
5	Unit fixes: returnOnCapitalEmployed/100, Screen DivYield ×100 + threshold, or-chain → is not None helper, pass self.exchange through	4 bugs, all mechanical, all 100× class	S
6	resolve_company_id: require exact match, add symbol to chart cache key	A typo currently returns a different company's price history, cached under the right key	S
7	bfinance.costs — date-keyed CostSchedule (STT/stamp/GST/SEBI, Finance-Act-versioned)	Your backtester hardcodes transaction_cost_bps=10.0; real NSE delivery round-trip is ~22–23bps, and stamp duty is buy-only	S
8	bfinance.nse.macro — India VIX, index TRI + valuation, RBI reference rate	India VIX is your only implied-vol anchor. TRI fixes the benchmark bias.	S
9	bfinance.flows — FII/DII + AMFI NAVAll.txt	AMFI has no key, no cookie, no anti-bot. Best effort-to-value in the matrix.	S
10	bfinance.ownership — pledge history + delta, FPI ownership, bulk/block deals	Has to be (symbol, as_of, revision_date)-keyed — NSE restates these	M
11	bfinance.universe — Nifty 50/100/500 constituents + rebalance events	Kills survivorship bias in your backtester. Free static CSVs; change events need snapshot-and-diff.	S/M
12	bfinance.derivatives — real option chain, FO bhavcopy, roll yield	Replaces SHA-256-seeded pseudo-random OI. Only after #1.	M
Do NOT build (A4 researched these): NSE Level-2 / Post-Trade FTP (licensed), "short interest" (doesn't exist in India — publish short sell volume), Prowess/CMIE, Bloomberg consensus (and free India consensus scraped from Moneycontrol is ToS-prohibited — bfinance correctly returns None today; don't regress it), BSE Web Forms scraping, RBI DBIE (no public API), CTT (abolished 01-Jul-2024).
What finengine needs, ranked
#	Fix	Impact
1	Read bfinance_synthetic_ohlc at the data_service.py:924 ingestion boundary; never present synthetic as measured	Honesty guardrail, even before #1 lands
2	Kill the EXPLAINERS fabricated numbers on 7 pages; render stress-testing's methodology + *_basis; retitle "Simulation" → "Shock Proxy"	#1 honesty defect
3	Fix portfolio/manage ×100 bugs + getRiskLevel; guard pairs z-score crash; add error states to volatility-sizing and realized-risk	2 crash-class + 2 silent-blank
4	Wire the 4 empty India tables to real producers (FII/DII JSON, delivery %, bhavcopy) + a post-market cron	t28/t29 stop being deferred
5	fetch_historical_data must raise on ProviderInvalidInputError, not return None	Kills the false 404s
6	Declare a units block per response field; delete every Math.abs(v)<=1.0 sniffer	Root cause #4
7	Fix the 11 degenerate 0.0/1.0 returns; add 'concentration' to risk_scoring.excluded	Root cause #5
8	Real risk-free rate + NIFTY Total Return benchmark + provenance tag	Unblocks all active-return math
9	Record cascade fallbacks in fetch_logs (primary_attempt/fallback_attempt columns already exist and are never set)	You cannot currently tell "yfinance down, bfinance carrying" from "yfinance fine"
10	get_corporate_actions already exists at data_service.py:1158 and is exposed on no route	Unwire it
Features that would genuinely change the product (A6, grounded in real tool research):
- VaR/ES backtesting — Kupiec POF, Christoffersen, Basel traffic light. You run 3 VaR engines and validate none of them. scipy + ~120 lines, zero deps. Highest credibility-per-hour item in the entire backlog.
- Ledoit-Wolf shrinkage on MinVol/MaxSharpe/MinCVaR — with 10–25 names, MVO is harvesting sampling noise. PyPortfolioOpt's documented default.
- Tracking error / active risk / information ratio — the most-asked equity-book question, currently zero occurrences in the codebase.
- Specific (idiosyncratic) risk decomposition — you already compute the β and R²; specific_risk = σ × √(1−R²).
- Drawdown-path risk — CDaR, Ulcer Index, time-under-water, recovery-time distribution. All ~30 lines on a series you already build.
- Risk policy limits — 21 pages of metrics and zero stated policy, so nothing is ever "wrong."
- Lot ledger — L-sized and blocks tax-aware rebalancing, but everything else is downstream of it.
Skip (A6's anti-pattern analysis): Basel FRTB (a personal long-only book has SES=0, DRC=0 — you'd compute max(IMCC)+0+0 and label it "FRTB capital"), Kelly (μ is too noisy to size leverage), a full Barra clone (no cross-section with 20 holdings), analyst revisions (research feature, not risk), correlation-network centrality (a 12-node graph is not a network), more dashboard pages.
One caveat on effort estimates
These are single-agent estimates against a codebase I haven't run. The two I'd verify before committing a sprint:
1. NSE bhavcopy availability — the legacy cmDDMMYYYYbhav.csv.zip path was discontinued 08-Jul-2024 (NSE Circular 62424). You need a dual-schema parser, and EOD data lands ~23:00–01:00 IST, so a 18:30 cron (as t28 specifies) reads yesterday's file. Worth confirming the current UDiFF URL resolves from your IP before scoping.
2. How much synthetic-OHLC contamination is already in your SQLite stock_timeseries — if the cache holds a year of synthetic bars, the fix needs a purge-and-refetch, not just a code change.
