## 2026-08-26T15:57:01Z

You are the Project Orchestrator for FinEngine (Daisy Risk Engine) Quantitative & Production Hardening.
Working directory: c:/sukanta/coding/finengine
Agent metadata directory: c:/sukanta/coding/finengine/.agents/orchestrator
Original user request file: c:/sukanta/coding/finengine/.agents/ORIGINAL_REQUEST.md

Please review the full requirements R1 through R5 and acceptance criteria in c:/sukanta/coding/finengine/.agents/ORIGINAL_REQUEST.md:
- R1: Advanced Volatility Term Structure (vol cone GET /api/v1/analytics/vol-cone with 10/21/63/126/252-day quantiles & GARCH/EWMA) & Tail Risk Suite (99% EVT-POT VaR/ES via scipy.stats.genpareto, lower-tail dependence copula matrix).
- R2: Correlation Stability (rolling 60d average pairwise monitor with 90th-percentile regime breaks) & Cointegration Pairs Scanner (GET /api/v1/analytics/coint with Engle-Granger, Johansen, OU mean-reversion half-life, caching).
- R3: India Market Microstructure & ADV Liquidity Limits (daily NSE data ingestion pipeline in app/services/india_data_service.py for bhavcopy delivery %, FII/DII flows, bulk/block deals, promoter shareholding/pledges cached in data/nse/ and SQLite; liquidity sizing days-to-liquidate @ 10%/20% ADV, Amihud illiquidity).
- R4: Frontend Visual Studio, PDF Export & Zero-Mock Purge (UI views for /pairs, /india-flows, vol-cone panel, tail-dependence heatmap; client-side jsPDF portfolio report export; eliminate all mock data/pseudo-random generators/fake MetricCard deltas in backend and frontend).
- R5: Library-First Architecture & Test Suite Hardening (80%+ Coverage gate: pytest --cov=app --cov-fail-under=80 with isolated SQLite fixtures, bun x tsc --noEmit, bun x vitest run).

Decompose into milestones, dispatch specialized subagents, maintain plan.md and progress.md in your directory (.agents/orchestrator/), and verify all tests and acceptance criteria thoroughly. When finished, report completion back to sentinel.
