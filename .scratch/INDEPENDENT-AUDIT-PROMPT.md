# Independent audit + Bloomberg-gap session prompt (paste into a fresh session)

```
You are running an INDEPENDENT, DOCUMENTATION-ONLY deep audit of the FinEngine backend
(working dir: C:\es\coding\finengine). This is a personal, single-user, localhost quant
portfolio app (Indian equities .NS/.BO + US stocks). You produce reports — you change NO code.

READ-ONLY CONTRACT (highest priority):
- Never edit, create, or delete anything outside .scratch/. No backend/, no frontend/, no config, no git operations.
- You MAY write reports, evidence scripts, and numeric comparison outputs ONLY under .scratch/backend-deep-audit/.
- You MAY run read-only commands (uv run python/pytest on existing tests, uv tree, grep). Verification
  scripts you write must live under .scratch/backend-deep-audit/evidence/ and import the backend code —
  they must not modify it.
- No futures or options content anywhere: no options pricing, Greeks, IV, term structure, F&O chains,
  futures/forwards/swaps, margin. This product is cash equities + portfolio analytics only.

INDEPENDENCE RULE: A prior audit exists at .scratch/backend-audit/. Do NOT read it during your main pass —
form your own conclusions first. Only in Wave 3 (cross-check) may you open it, to document where you
agree/disagree/missed things.

OUTPUT DIRECTORY: .scratch/backend-deep-audit/
  00-INDEX.md                 — master index: coverage, counts, priorities, links
  code/01..0N-*.md            — line-by-line code audit per area
  quant/verify-*.md           — one report per mathematical model + evidence/ scripts + outputs
  gaps/bloomberg-gap.md       — feature gap analysis vs a Bloomberg-class EQUITY terminal
  gaps/stock-research-fit.md  — individual-stock research + "effect on my portfolio" analysis design
  crosscheck-vs-prior.md      — Wave 3 comparison with .scratch/backend-audit/
  FIX- backlog lives inside 00-INDEX.md (recommendations only — nobody fixes anything this session)

QUALITY BAR FOR EVERY CLAIM: cite file.py:LINE, or attach reproducible numeric evidence
(script under evidence/ + its output). No speculation, no generic best-practice filler.
If an area is clean, say so explicitly.

FREE-SOURCE-OR-BUILD RULE (applies to every gap, metric, and data need in Tasks C and D):
- If the underlying info is freely available on any reputable site or public API, cite the exact source:
  name, URL, endpoint if applicable, coverage (IN/US, history depth), rate limits/license, and update
  frequency. Only cite sources you actually verified with web search/fetch — never guess URLs.
- If it is paywalled / paid-terminal-only (Bloomberg, Refinitiv, paid screener tiers), say so, then
  recommend BUILDING it — preferably from free proxies (name which free source feeds which field);
  if no free proxy exists, mark "build after paid data deal" and deprioritize.
- Decision bar: if even a BASIC version of the capability materially helps the user decide
  (buy/sell/weight/avoid), include it in the backlog marked "basic" (ship first) vs "full" (later).
  Skip only what neither free nor buildable-with-free-data and doesn't move decisions.
- Every backlog row must carry: Data source: free (cited) | build-from-free-proxy (named) | paid-only.
Cross-check free sources against what the code already fetches (yfinance, Alpha Vantage, NSE/BSE) —
prefer sources that need no new key/ cost.

TASK A — INDEPENDENT LINE-BY-LINE CODE AUDIT (read every first-party file fully;
backend/app/, backend/main.py, backend/migrations/, root scripts; skip .venv, skip tests except
to note coverage gaps). Categories per finding: Bug / Improvement / Optimization / Recommended change;
severity P0 (security/crash/data loss) / P1 (wrong result) / P2 / P3. Cover beyond the obvious:
error-handling consistency, dead code, DB indexes vs query patterns, cache correctness, async blocking
calls, API contract consistency, config/secrets hygiene, Docker/deploy files, logging, test gaps.

TASK B — VERIFY MATHEMATICAL / QUANT MODELS AGAINST ESTABLISHED LIBRARIES
(“don’t reinvent the wheel” made concrete). For EVERY hand-rolled model in the backend — at minimum:
  volatility (EWMA/GARCH/EGARCH — arch package), tail risk (EVT/GPD — scipy.stats.genpareto),
  cointegration (statsmodels), correlation (pandas/numpy vs sklearn), Monte Carlo,
  optimization/HRP/risk parity (compare vs riskfolio-lib / PyPortfolioOpt if installed),
  regime detection (statsmodels/HMM learnings), indicators (TA-Lib / pandas-ta),
  backtest mechanics (vectorbt-style correctness), quantstats tear-sheet usage, HHI/diversification math:
  1. Inventory installed quant libraries FIRST (backend/pyproject.toml, uv.lock, .venv) — scipy,
     statsmodels, pandas, numpy, arch, quantstats etc. — before recommending anything new.
  2. Extract the exact formula implemented (quote the lines).
  3. Write an evidence script under evidence/ that feeds IDENTICAL inputs to your implementation and to
     the reference library; print both outputs + numeric difference + tolerance verdict.
  4. Verdict per model: MATCHES | DIVERGES (show magnitude) | BUG (wrong math) | REPLACE-WITH-LIBRARY
     (name the library; prefer an already-installed one; note if it would add a new dependency —
     recommending is allowed, implementing is not).
  5. Also check compliance with the repo’s stated invariants (AGENTS.md): true HHI (N≤1 → 0%),
     inverse-vol weights, geometric monthly compounding, zero-state weight = 100%, en-IN formatting,
     ticker regex with hyphens, no fabricated metrics.
Separate genuine mathematical errors from style differences — severity only for real wrongness.

TASK C — “TRUE BLOOMBERG ALTERNATIVE” GAP ANALYSIS (cash equities only, NO futures/options).
Assess what a Bloomberg-class equity terminal offers vs what exists today. Apply the
FREE-SOURCE-OR-BUILD RULE to every capability. For each capability, one row with:
what exists (file:line) → gap → free data source (verified citation) or build-from-proxy plan →
basic-vs-full (does basic already improve decisions? then ship basic) → user value → rough
difficulty → ship/skip recommendation, prioritized.
Candidate checklist (verify against code, add domain items you know, exclude derivatives absolutely):
factor/style analysis (value/momentum/quality/size) & exposure; Brinson/attribution & risk decomposition
(marginal contribution to risk, component VaR); peer/relative valuation & comp tables; earnings calendar,
estimates/consensus revisions; news + sentiment with portfolio relevance; ownership (FII/DII — partially
present, check it); correlation networks & heatmaps; saved custom screeners + alerts/watchlists; formula/
custom-metric language; backtests with costs/slippage/dividends; performance vs benchmark (sortino,
tracking error, information ratio); macro dashboard; report/PDF export; data quality/freshness UI.
Output the prioritized backlog into gaps/bloomberg-gap.md (still recommendations only).

TASK D — INDIVIDUAL STOCK RESEARCH + PORTFOLIO-FIT (“does adding this stock help or hurt me”).
1. Document what per-stock research exists today (research/metrics endpoints — cite file:line).
2. Document what portfolio-impact analysis exists (position analytics, conditional portfolio stats, etc.).
3. Design the missing “if I add ticker X” analysis: marginal Δ volatility, Δ VaR/CVaR, Δ max drawdown,
   Δ diversification (HHI / effective N), Δ Sharpe/Sortino (needs expected-return model — say which),
   correlation to existing holdings + new-sector/region exposure, concentration drift, tracking error
   vs benchmark, capacity/liquidity check. For each metric: exists (cite) | computable from existing
   services (name them) | missing (new endpoint needed) + FREE-SOURCE-OR-BUILD annotation: which free
   site/API supplies each missing input (prices, fundamentals, ownership, estimates, sector maps —
   e.g. verify NSE/BSE, Yahoo, Screener-type sites, FRED, Fama-French libraries; cite what you
   verified, skip what you couldn’t), or "build from free proxy: <sources>" if paid-only.
   Mark metrics whose BASIC version already changes the add/avoid decision as ship-first.
   Save to gaps/stock-research-fit.md.

WORKFLOW — deploy subagents in parallel waves with personas:

WAVE 1 (parallel, none may read .scratch/backend-audit/):
- “Line-by-line Code Auditor” ×5, one area each: API layer (api/*.py + main.py) | core services
  (analytics_engine, data_service, cache) | quant services (regime, volatility, tail_risk, optimization,
  monte_carlo, cointegration, correlation, backtest, indicators, benchmark) | data-provider services
  (alpha_vantage, india_data, currency, screener, equity_research, company_data, source_preference,
  ai_dossier) | foundation (models, config, db, utils, migrations, root scripts, Docker/compose).
  → code/0N-*.md
- “Quant Methodologist / Model Verifier” ×2: (i) risk/time-series models (vol, tail, regime, monte carlo,
  backtest, indicators) and (ii) portfolio/correlation models (HRP/optimization, cointegration,
  correlation, HHI, quantstats usage). Inventory installed libs, write evidence scripts, produce
  quant/verify-*.md with MATCHES/DIVERGES/BUG/REPLACE verdicts.
- “Financial Product Analyst (Bloomberg, equities-only)” → gaps/bloomberg-gap.md. Must web-verify every
  free-source citation (fetch/search it) and tag each row: free (cited) | build-from-free-proxy | paid-only.
- “Portfolio Construction Analyst” → gaps/stock-research-fit.md. Same verified-source rule for every
  missing metric’s data inputs; tag ship-first "basic" metrics that change decisions.
Each wave-1 subagent: READ-ONLY on all code; writes ONLY its assigned output paths; returns
path + finding counts + top 3 findings.

WAVE 2 — “Cross-Auditor”: now allowed to read .scratch/backend-audit/, compare against all Wave-1
outputs; write crosscheck-vs-prior.md: agreed / prior-missed-this / we-missed-this / direct
disagreements (investigate each disagreement against the code and rule for one side with evidence).

WAVE 3 — “Chief Editor”: read everything, deduplicate, write 00-INDEX.md with: coverage table,
severity counts, quant-model verdict summary table (model → verdict → library), prioritized
recommendation backlog (P1→P3) merging code fixes + Bloomberg gaps + stock-fit gaps, and a
“do not do” list (derivatives features explicitly excluded; anything refuted).

FINAL REPORT TO ME: counts by category, every quant-model verdict in one line each (model: verdict),
top 10 recommendations (each with its free-source-or-build tag), a free-data source table
(source → capabilities it feeds → verified), cross-check summary (what the prior audit missed /
got wrong), and confirmation that nothing outside .scratch/backend-deep-audit/ was modified.
```
