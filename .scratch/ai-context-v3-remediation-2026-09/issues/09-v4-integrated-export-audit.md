# 09: Generate and audit the integrated v4 export

**What to build:** Produce a fresh AI-context export after all remediation tickets and prove that all 17 sections are arithmetically, semantically, and operationally safe for portfolio decision support and AI consumers.

**Blocked by:** 02: Make dashboard history fresh and components canonical; 03: Make volatility sizing safe to interpret and execute; 04: Correct holding-window and per-position disclosure; 05: Separate full-history calculations from holding context; 06: Correct concentration, liquidity, and stress semantics; 07: Clarify optimizer, simulation, regime, and pairs semantics; 08: Make India composite coverage honest and complete

**Status:** ready-for-agent

- [ ] Focused backend, frontend, type/build, and lint checks pass.
- [ ] Full backend results are recorded with unrelated pre-existing failures separated from regressions.
- [ ] A new v4 JSON export is generated without modifying bfinance.
- [ ] Every section has valid status, coverage, timestamps, currency units, inputs, warnings, and calculation basis.
- [ ] Portfolio arithmetic, contribution sums, optimizer weights/trades, simulation quantiles, pair counts, matrix alignment, and dashboard duplication are independently recomputed.
- [ ] No requested ticker, measured date, assumed unit, fallback score, or calculation universe is silently omitted or fabricated.
