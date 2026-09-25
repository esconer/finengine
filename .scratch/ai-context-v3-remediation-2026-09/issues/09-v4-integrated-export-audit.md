# 09: Generate and audit the integrated v4 export

**What to build:** Produce a fresh AI-context export after all remediation tickets and prove that all 17 sections are arithmetically, semantically, and operationally safe for portfolio decision support and AI consumers.

**Blocked by:** 01: Normalize the AI export contract; 02: Make dashboard history fresh and components canonical; 03: Make volatility sizing safe to interpret and execute; 04: Correct holding-window and per-position disclosure; 05: Separate full-history calculations from holding context; 06: Correct concentration, liquidity, and stress semantics; 07: Clarify optimizer, simulation, regime, and pairs semantics; 08: Make India composite coverage honest and complete

**Closes:** Final verification of V3-01 through V3-17

**Evidence:** v3 artifact SHA-256 and the 17-row evidence ledger in the feature audit file.

**Work area:** Integrated verification, committed v4 evidence, and any cross-ticket reconciliation only after individual tickets land.

**bfinance gate:** No bfinance edits. Record bfinance git status and confirm no dependency/source/preference changes leak into the fix.

**Status:** ready-for-agent

- [ ] Focused backend, frontend, type/build, and lint checks pass.
- [ ] Full backend results are recorded against the 674/6 baseline; any regression is listed by test ID.
- [ ] Fresh v4 JSON and Markdown evidence are committed under the feature's `evidence/` directory, with a 17-row per-section verdict table and a v3→v4 field-level delta.
- [ ] Sections with no remediation change (portfolio, summary, forecast, risk studio, tear sheet where applicable) have an explicit verified-no-change record.
- [ ] Two exports of the same book are byte-identical except allow-listed run metadata; ordering and cache identity are proven stable.
- [ ] Every section has valid status, coverage, timestamps, currency units, inputs, warnings, and calculation basis.
- [ ] Portfolio arithmetic, contribution sums, optimizer weights/trades, simulation quantiles, pair counts, matrix alignment, and dashboard duplication are independently recomputed.
- [ ] No requested ticker, measured date, assumed unit, fallback score, or calculation universe is silently omitted or fabricated.
- [ ] No bfinance change leaked into the repository, dependency lock, or source preference.
