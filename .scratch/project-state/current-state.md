# Daisy Risk Engine — Current State

Recorded: **2026-09-28** · Commit: `799d291` · Supersedes the 2026-08-27 revision, which
was a month stale and listed all 13 QH tickets as open when they are closed.

> Full ticket-by-ticket verification (222 tickets, evidence-cited) lives in
> `.scratch/verification/2026-09-ticket-state.md`. **Read that first** — it corrects
> ~35 status lines. This file is the orientation map, not the ledger.

---

## 1. What this project is

**Daisy Risk Engine** — a personal, single-user Bloomberg-grade financial risk analytics
platform for an Indian equity portfolio (NSE/BSE focused).

- **Backend** (`backend/`, Python 3.12, uv): FastAPI + SQLite (async SQLAlchemy/aiosqlite) +
  yfinance + **bfinance 0.1.3 from PyPI** + Alpha Vantage fallback + quantstats/arch/scipy/
  cvxpy/hmmlearn/stockstats. Port 8000.
- **Frontend** (`frontend/`, Bun): Next.js 16 App Router + React 19 + TypeScript + Tailwind +
  Recharts + Zustand + TanStack Query/Table. Port 3000, proxies `/api/v1/*`.
- **Principle:** "Not on Free Sites" — only what TradingView, Screener.in, Chartink and
  Yahoo Finance do not provide.

Status: **advanced quant analytics, with a known honesty problem.** The analytics engine is
substantially correct and heavily tested. The failure mode is not bad math — it is
**fabricated defaults emitted where a measurement failed**, plus a **stale data pipeline**.

---

## 2. Three things to know before starting work

### 2.1 A locked decision rests on a falsified premise

`data-correctness-2026-09/spec.md:15` locks "Purge and full refetch" on the belief that
`stock_timeseries` is full of synthetic bfinance bars. Measured against a read-only copy of
`daisy.db`:

> **4 rows of 31,338 are bfinance (0.013%).** The other 31,334 are yfinance and legitimate.

The contamination is real — `SELECTIPO.NS 2026-02-01` has `high 42.4848` where
`open x 1.002 = 42.4848` exactly — but the purge would delete 31,334 good rows to fix 4.
**Do not run `p2-data-layer/02` as written.** Targeted 4-row delete instead.

### 2.2 bfinance is pinned to PyPI, so the #1 data fix is not installed

| Location | State |
|---|---|
| `C:\es\coding\bfinance\src\bfinance\market\ohlcv.py:445` | `ohlc="bhavcopy"` — **fixed** |
| `backend/.venv/.../bfinance/market/ohlcv.py:189-194` | `High = max(Open,Close) * 1.002` — **still fabricating** |

`uv.lock:362-364` pins `bfinance==0.1.3` from PyPI; no `[tool.uv.sources]`; non-editable
install. **The local repo is not consumed by the backend.** All 21 Phase-1 tickets need a
publish-then-bump, not an edit.

### 2.3 The single largest remaining defect is one bug wearing six hats

P3 tickets 08, 09, 13, 19, 21, 22 are all the same pattern: *a failed measurement returns a
plausible number instead of nothing.* A 1-holding portfolio reports `diversification_ratio
1.0` while its sibling score correctly reports `0.0`. `websocket.py:417` promotes a
fabricated `sharpe_ratio = 0.0` to `analytics_status = "measured"`.

**One pass replacing fabricated defaults with `None` + an explicit `data_status` closes all
six** — plus ~205 more recorded in `backend-audit/verified-01..06.md` that were never
ticketed and read like completion reports.

---

## 3. Architecture

```
yfinance (NSE/BSE auto .NS/.BO)          <- 99.987% of cached rows
   → DataService (retry x3, timeout, per-vendor normalisation MISSING)
      → Alpha Vantage fallback (multi-key, .NS→.BSE bridge)
         → bfinance 0.1.3 (PyPI)  <- 4 rows; STILL FABRICATES OHLC, not installed fix
         → SQLite: stock_timeseries (no source dimension in the cache key)
            → Quant services (15):
               AnalyticsEngine, OptimizationService, RegimeService, MonteCarloService,
               BenchmarkService, VolatilityService, TailRiskService, CorrelationService,
               CointegrationService, IndiaDataService, IndicatorsService,
               CompanyDataService, AlphaVantageService, CurrencyService, ScreenerService
              → REST /api/v1/{portfolio,data,analytics} + WebSocket
                 → Next.js dashboard (17 pages)
```

---

## 4. Test & quality status

Last recorded: **1,618 backend test functions**, ~232 frontend tests in 35 files.
**Not re-run during the 2026-09-28 audit** — no green run was verified.

Gate: `--cov-fail-under=80` (`pyproject.toml:84`), enforced in `ci-cd.yml:54`.
Whether it currently passes is unverified.

**Two things in CI you should know:**
- `ci-cd.yml:171-172` uses long-lived `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
  QH-13 specified OIDC `role-to-assume` for this, was marked closed, and it was not done.
- The k8s deploy step was removed (it referenced a nonexistent directory). Correct.

---

## 5. Live tech debt

| Item | State |
|---|---|
| Frontend `any` epidemic | **Fixed.** 0 hits across `frontend/app` + `frontend/lib`. |
| Factor-model placeholders | **Fixed.** No TODO/placeholder markers in `analytics_engine.py`. |
| Fixed FX 83.0 | **Still `FALLBACK_USD_INR`** (`currency_service.py:27`) but documented as a fallback with provenance inspection. Real dated rate is ticket P3-27 (currently `needs-info`). |
| `analytics_cache` table | **Confirmed dead.** A model definition plus a service registration; never read or written. Ticket P2-20. |
| `up_capture` / `down_capture` | **Dead schema fields** (`schemas.py:272-273`) — declared, populated by nothing, so TypeScript type-checks against fields the API never sends. |
| `price_as_of` | **Inert.** Produced by the backend (AD-16), consumed by **zero** frontend pages. |
| 4 NSE tables | `nse_bhavcopy`, `nse_institutional_flows`, `nse_bulk_block_deals`, `nse_shareholding_patterns` — **all `rows=0`**. No scheduler exists. |
| 41 `Blocked by:` refs | Bare numbers with no phase. 38 tickets. See ledger §7.1. |
| Status vocabulary | 13 tokens against a documented 5. See ledger §7.4. |

---

## 6. Where the work is

| Program | Open | Note |
|---|---|---|
| `data-correctness-2026-09` | **86 finengine** | The body of remaining work. 108 tickets, 1 resolved. |
| `backend-audit/verified-01..06.md` | **~205 unticketed** | Audit reports, not resolutions. Read as completions at your peril. |
| `p1-financial-correctness-2026-09` | 0 | All six done. |
| `ai-context-v3-remediation-2026-09` | 1 | 01-05, 07-08, 09 done. 06 partial. |
| `deep-history-2026-09` | 1 | 14-17 shipped in `13d89ed`. 13's evidence is stale. |
| `remediation-2026-09` | 1 | 01-10 done. 11 done (mislabeled). 12 partial (code 7/7, tests 2/7). |
| `advanced-analytics` | 3 | 1 deferred + 2 needs-info, all old. |

**True frontier: 54** of 93 `ready-for-agent` tickets are actually blocked by the bare-number
ambiguity. Unblocked + verified un-started in finengine: **58**.

Best remaining work, in order:
1. Reverse the purge decision (2.1 above) — minutes, prevents data loss.
2. Record the bfinance install mode — gates 28 tickets across two repos.
3. Do the degenerate-zeros pass as one unit — 6 ticketed + ~205 unticketed.
4. Run P3's 20 remaining tickets in parallel — independent, no file contention.

---

## 7. Documentation map

| File | What |
|---|---|
| **`.scratch/verification/2026-09-ticket-state.md`** | **The ticket ledger. Read first.** |
| `CONTEXT.md` | Domain guide: architecture, vocabulary, runbooks, gotchas |
| `AGENTS.md` | Issue tracker, triage labels, domain docs, quantitative invariants |
| `docs/ai-context.md` | AI export contract (schema 2.0) |
| `.scratch/data-correctness-2026-09/spec.md` | The 5-phase correctness program. Triage table undercounts by 1; p5 sub-spec contradicts its own tickets. |
| `.scratch/data-correctness-2026-09/p1-bfinance-0.2.0/spec.md` | bfinance 0.2.0 release. **Its central "two upstream URLs" claim is now false — there are 5, one unspecced.** |
| `RELEASE_NOTES.md` | Shipped-wave changelogs |
| `docs/agents/` | issue-tracker, triage-labels, domain protocols |
| `docs/research/` | Uncommitted, from the in-flight AI-context work |

---

## 8. Conventions & gotchas

1. Tickers uppercased; Indian normalisation appends `.NS` aggressively.
2. Currency default INR end-to-end (API, formatters, store).
3. PowerShell: no heredocs, no `&&`. Write temp script files for multiline Python.
4. `uv add` on unpinned graphs can churn minutes; pin versions surgically.
5. Patch targets must match the importing namespace.
6. Cache schema lowercase OHLCV; yfinance raw Title-case; normalise at boundaries.
7. Never `asyncio.run()` inside pytest tests.
8. Sum-to-1 assertions on rounded payloads need ~1e-4 tolerance.
9. `.info` intermittently 401s ("Invalid Crumb") → map to 503 upstream-outage.
10. `arch.bootstrap`: iterate via `bs.bootstrap(n)`, NOT `for x in bs`.
11. Student-t moments: analytic `scale*sqrt(df/(df-2))`, not sample std.
12. conftest `dependency_overrides` needs `try/finally` — **QH-01 claims this; it is not
    actually there.** The leak is currently prevented by an isolated `test_db` instead.
13. All `uv` commands are pre-approved — run non-interactively.
14. **Cite symbols, not `file:line`,** in ticket resolutions. Backend files have drifted
    1,000–2,000 lines since the tickets were written.
