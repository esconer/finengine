# Fix-session prompt (paste into a fresh session)

```
You are fixing bugs in the FinEngine FastAPI backend (working dir: C:\es\coding\finengine).

A full line-by-line audit already exists — READ THESE FIRST, in order:
1. .scratch/backend-audit/00-INDEX.md  (consolidated findings, themes, suggested fix order)
2. .scratch/backend-audit/01-api-analytics.md … 06-foundation.md  (per-area detail, every finding cited as file.py:LINE)

TASK: fix all findings, in this priority: P1 first, then P2, then P3 (skip anything marked RESOLVED or refuted during verification).

CONTEXT FROM THE AUDIT SESSION (already done, do NOT redo):
- The only P0 (auth/0.0.0.0 bind/dead WS token) is RESOLVED: main.py:175 and config.py:17 now bind 127.0.0.1, websocket.py:260 token param removed. App is localhost-only single-user; auth is explicitly out of scope forever unless exposure changes.
- Line numbers in reports may be off by ±3 in main.py, config.py, app/api/websocket.py only (those files were edited after the audit). All other line numbers should match.
- Known cross-cutting theme: fabricated metric fallbacks (placeholder {alpha:0, market:1}, hardcoded optimize metrics, fake EVT numbers) — fix these with ONE shared "value unavailable" convention (null/omitted + flag), not four ad-hoc patches.

HARD RULES:
1. VERIFY BEFORE FIXING. Never fix a finding on the audit's word alone. For each finding: re-read the cited code, confirm the bug still exists and the mechanism is real, and where feasible write a FAILING regression test first (red → fix → green). If a finding is wrong, already fixed, or unreachable, mark it "refuted/already-fixed" in its report with one line of evidence — do not fix it. Mark each finding Status: verified | refuted | fixed as you go (append a Status: line under the finding or maintain a checklist at the top of each report).
2. ROOT-CAUSE FIXES ONLY. Smallest change that fixes the mechanism for every caller — not a guard on the path the ticket names. Follow the repo ladder in AGENTS.md: reuse existing helpers, stdlib first, no new dependencies, no unrequested abstractions.
3. EVERY nontrivial fix gets ONE permanent regression test in backend/tests/ (pytest; name it test_bugfix_<area>_<nn>.py or extend the nearest existing test file). Trivial one-liners may skip tests. Prefer permanent tests over debug scripts (AGENTS.md).
4. VERIFY AFTER EACH AREA: `uv run --group dev ruff check main.py app/` (backend/ workdir) must pass; run the touched test files: `uv run --extra dev pytest tests/<files> -q`. Full-suite coverage gate fails when running subsets — that's expected; only the full suite must meet 80% at the end. Run the full suite once at the very end: `uv run --extra dev pytest -q` and fix any regressions you caused.
5. DO NOT commit, push, or widen ruff rule scope. DO NOT touch frontend/ unless a fix genuinely requires it (CSV export fix may — if so, keep it minimal).
6. Respect AGENTS.md quantitative invariants: true HHI diversification (N≤1 → 0%), inverse-vol risk parity, geometric monthly compounding, zero-state portfolio weight = 100%, en-IN currency formatting, NSE/BSE ticker regex with hyphens, metric-card hygiene (no fabricated metrics).

WORKFLOW — deploy subagents in parallel waves:

WAVE 1 — VERIFIERS (6 parallel, read-only personas, one per report 01–06):
Persona: "Bug Verifier — skeptical, evidence-first, never edits code."
Each reads its report + the cited code + relevant tests, outputs a verified worklist: finding id → confirmed/refuted/already-fixed + one-line evidence + exact current line number + files to touch + suggested regression-test idea. Write results to .scratch/backend-audit/verified-0N.md. Do not fix anything in this wave.

WAVE 2 — FIXERS (parallel by area, start after Wave 1 completes; run independent areas concurrently):
Personas, one subagent each:
- "Surgical Fixer — API layer" (reports 01+02): analytics/portfolio/data/equity_research/websocket/main
- "Surgical Fixer — Core services" (report 03): analytics_engine/data_service/cache_service
- "Surgical Fixer — Quant correctness" (report 04): regime/volatility/tail_risk/optimization/monte_carlo/cointegration/correlation/backtest/indicators/benchmark — must understand the financial math, cite the invariant violated, verify formula fixes against the quant invariant tests
- "Surgical Fixer — Data providers" (report 05): alpha_vantage/india_data/currency/screener/equity_research/company_data/source_preference/ai_dossier — unit-consistency and HTTP/timeout/error-mapping fixes
- "Surgical Fixer — Foundation" (report 06): schemas/db/config/utils/migrations/root scripts — MOST SENSITIVE: the add_portfolio_columns.py fix may need a data-repair migration for already-fabricated rows; back up/inspect before writing repair logic; delete or quarantine the trap root scripts
Rules for fixers: only fix findings in your area marked verified; red-green test first; update your report's findings to Status: fixed with commit-less diff summary; stay inside your file list (if a fix requires touching another area's file, note it as a cross-area handoff instead of editing).
Foundation fixer runs FIRST (it owns schemas/migrations other fixes may depend on); the other four can run in parallel with it.

WAVE 3 — REVIEWER + QA (1 subagent, after Wave 2):
Persona: "Diff Reviewer — adversarial, ponytail lens: rejects over-engineering, verifies each fix matches its finding, checks no fabricated values remain, checks no dead code left behind."
Runs: full `uv run --extra dev pytest -q`, ruff, greps for banned placeholders ({alpha: 0.0, market: 1.0}, hardcoded 0.12/0.22/0.45, fabricated gpd values). Produces .scratch/backend-audit/FIX-REPORT.md: findings fixed/refuted/skipped counts, test results, any remaining issues.

FINAL: update 00-INDEX.md (mark resolved items, link FIX-REPORT.md), then report to me: counts fixed/refuted/skipped, full-suite result, and any finding you deliberately did not fix with the one-line reason.
```
