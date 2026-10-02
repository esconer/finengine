# Ticket state verification — 2026-09-28

Read-only audit. No ticket `Status:` line was changed and no product code was edited.
Every verdict below was produced by inspecting the working tree, not by trusting a status line.

**Scope:** 222 files under `.scratch/**/issues/*.md` (the `node_modules` tree under
`.scratch/backend-deep-audit/browser-e2e/evidence/runtime/frontend-harness/` is excluded).
Plus `C:\es\coding\bfinance` for the 22 Phase-1 tickets, which target the external repo.

---

## 1. Headline

The tracker's `Status:` lines are not a reliable guide to what is done. Roughly **35
verified corrections** are needed across 222 tickets. Three of them are load-bearing enough
to change what you should do next.

| | Count |
|---|---|
| Tickets whose status is **correct** | ~155 |
| Marked done, **actually done** | ~80 |
| Marked open, **actually done** | **19** |
| Marked done, **only partially done** | **13** |
| Marked done, **not done at all** | **2** |
| Marked open, **genuinely not started** | ~85 |

Three findings outrank the rest:

1. **A locked decision rests on a falsified premise.** `spec.md:15` "Purge and full
   refetch" would delete 31,334 legitimate yfinance rows to remove 4 contaminated ones.
2. **bfinance is pinned to PyPI, so the fix for the project's #1 data defect is not
   installed.** The real-OHLC code exists in `C:\es\coding\bfinance` but the backend reads
   PyPI `0.1.3`, which still fabricates `High = max(Open,Close) * 1.002`.
3. **~205 confirmed backend defects are outside the ticket system entirely**, in
   `backend-audit/verified-01..06.md`, which read like completion reports and are not.

---

## 2. Actively harmful — reverse these before anyone acts

### 2.1 Reverse the locked purge decision

`data-correctness-2026-09/spec.md:15` locks "Purge and full refetch", justified by
`p0-preflight/02`'s claim that `stock_timeseries` is full of synthetic bfinance bars.
Measured against a read-only copy of `daisy.db`:

| Metric | Value |
|---|---|
| Total rows | 31,338 across 15 tickers |
| `source_used = 'yfinance'` | 31,334 (99.987%) |
| `source_used = 'bfinance'` | **4 (0.013%)** |
| Span | 2016-08-10 → 2026-09-25 |

The contamination is real and provable. `SELECTIPO.NS 2026-02-01` reads
`open 42.4, high 42.4848, low 41.83616` — and `42.4 x 1.002 = 42.4848` exactly. That is the
fabricated envelope's fingerprint.

**Action:** replace the purge with a targeted delete of those 4 rows. Do not run
`p2-data-layer/02` as written.

### 2.2 bfinance fixes cannot reach the app without a release

| Location | State |
|---|---|
| `C:\es\coding\bfinance\src\bfinance\market\ohlcv.py:445` | `ohlc: Literal["bhavcopy","synthetic"] = "bhavcopy"` — **fixed** |
| `backend/.venv/.../bfinance/market/ohlcv.py:189-194` | `df["High"] = np.maximum(Open, Close) * 1.002` — **still fabricating** |

`uv.lock:362-364` pins `bfinance==0.1.3` from `pypi.org/simple`. There is no
`[tool.uv.sources]`. `backend/.venv/Lib/site-packages/bfinance-0.1.3.dist-info` is a
non-editable PyPI install. **The local repo is not consumed.**

This is what `p0-preflight/04` asks, and it was answerable in 30 seconds. It was never
recorded. Consequence: all 21 Phase-1 tickets need a **publish-then-bump**, not an edit.
P2 tickets 01, 02, 04, 21 all presuppose the fix is live in the environment.

### 2.3 Un-ticketed: ~205 open backend defects

`backend-audit/verified-01..06.md` are **audit reports, not resolutions.** They confirm
defects as still-present, with a "files to touch" and "regression-test idea" column. They
sit in a file list that reads like completions. Still unfixed today:

- `analytics_engine.py` `_empty_metrics` returns `annual_volatility: 0.20, hit_ratio: 0.5, kurtosis: 3`
- `_empty_stress_test` returns `-0.20 / -0.17 / 30`
- `_empty_risk_score` returns `25.0`
- `volatility_service.py` EWMA empty path `return 0.20`
- `_TAILS_RESPONSE_CACHE` has no eviction

This is the **same fabricated-default family** as P3 tickets 08/09/13/19/21/22, discovered
independently and never ticketed. If you fix that cluster, this is a third inventory of it.

---

## 3. Marked open, actually done — 19 tickets

| Ticket | Evidence |
|---|---|
| `ai-context-v3/02, 03, 04, 05, 07, 08` | landed in `cc0410a`, `6e3268d`, `189fd5e`, `22062ed`, `e88bbe3`, `432e7ca` |
| `ai-context-v3/03` execution gate | `volatility-sizing/page.tsx:760-763, 779-782` fail closed; `data-testid="execution-blocked"` |
| `ai-context-v3/04` holding window | `analytics.py:3900-3902`; **zero** `held since` matches in `analytics.py` |
| `deep-history/14, 15, 16, 17` | `13d89ed` — all four phases shipped |
| `p1-financial/01..06` | all six have completed `### Progress` sections with test counts |
| `remediation/11` | 11/11 items fixed; `test_quant_math_p1_batch.py` has one test class per item |
| `bug-sweep/01, 02, 03, 04` | superseded by later work |
| `advanced-analytics/03` | superseded by `terminal-ux/06` + `browser-verification/16` |
| `browser-verification/07` | superseded; server-canonical HHI now |

**Correction to my own earlier report:** I told you `remediation/11` was "verified
un-started", citing `analytics_engine.py:1454`. That was my error. Lines `:1454` and `:1659`
are **bootstrap restatements** of the engine formula — `sum(x)/N` and `mean(x)` are
algebraically identical, and `:1632-1633` says so. The real fix is at `:3965-3968`. All 11
items are done.

**Also corrected:** I called `ai-context-v3/03, 04` "stale claims" needing a decision. They
are not half-finished; they are complete. Nothing to clear beyond the status line.

---

## 4. Marked done, only partially done — 13 tickets

### 4.1 Security item closed without being done

`quality-hardening/QH-13` labelled long-lived `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
in CI as a defect and specified OIDC `role-to-assume`. The k8s removal and frontend job
landed. **The credential migration did not** — `ci-cd.yml:171-172` still holds the keys the
ticket called out. Closed as fully done.

### 4.2 `quality-hardening/QH-04` — not done

The `{"status", "errors", "data"}` response envelope appears **nowhere** in `backend/app`.
Zero matches for `"errors":` in the entire backend. The codebase has an ad-hoc `data_status`
vocabulary instead (`analytics.py:240-254`). The ticket's own open question — migrate vs
`/api/v2` — was never answered.

### 4.3 Half a fix, and the verification note hides it

`remediation-09`. `/screens/{strategy}` correctly builds a per-request `ScreenerService`.
**`/screens/custom` at `equity_research.py:246-260` still calls the module-global
singleton** — the exact stale-session defect the ticket exists to fix. The ticket's status
note reads `closed (verified: ... on /screens/{strategy})`: the verification quietly
narrows the claim to the route that works. Confirmed independently by two agents.

### 4.4 Closed on code presence, ticket's own proof never written

| Ticket | Claim | Reality |
|---|---|---|
| `QH-07` currency stampede | "10 concurrent calls → single fetch" | lock + double-check present (`currency_service.py:137,181-189`); **zero** matches for the concurrency test in `backend/tests` |
| `QH-03` GARCH rescaling | `rescale=True` | manual `* 100` with `rescale=False` (`analytics_engine.py:4303`); the only test **mocks `arch_model`**, so it cannot prove real-library convergence |
| `QH-05` websocket batching | `ROW_NUMBER() OVER (PARTITION BY ticker)` | a 14-day range fetch shipped instead; test pins query *count*, asserts nothing about memory boundedness |
| `QH-01` conftest leak | `try/finally` around `dependency_overrides` | absent at `conftest.py:226-230`; leak prevented by a different mechanism (isolated `test_db`) |
| `QH-10` deps cleanup | "sync without scikit-learn/alembic" | `alembic` (`pyproject.toml:25`) and `scikit-learn` (`:34`) still declared; criterion cannot pass |
| `QH-08` React Compiler | `reactCompiler: true` | `next.config.ts:5` still `false, // Disabled for stability` |
| `QH-09` type safety | "no `Promise<any>`" | `api.ts:380` still has it; no runtime validation on WebSocket messages |
| `QH-12` frontend tests | Layer 1 = `api.ts` + `websocket.ts` | neither has a test file |
| `advanced-analytics/04` | "grep localhost:8000 → zero hits" | 2 hits: `lib/api.ts:39`, `lib/websocket.ts:56` |
| `advanced-analytics/05` | cache-hit test | no test asserts "second call same day, no yfinance request" |
| `terminal-ux/02` settings page | 4 sections | only #3 and #4 built; no currency default, benchmark, lookback, or target-vol controls |
| `resource-optimization/01` | "bounded `background_updates()`" | `websocket.py:272` still `while True`; the `break` at `:287` sits **after** the heavy calls and `sleep(30)`, so an idle backend still burns a full cycle per 30s |

### 4.5 Stale resolutions that will mislead a re-auditor

- `browser-verification/09` claims the fix was `prices.ffill().bfill()` + `returns.fillna(0.0)`.
  **Neither exists in `analytics.py`.** Current code does the opposite deliberately —
  `aggregate_active_returns` (`analytics_engine.py:255-272`) drops under-covered dates and
  refuses both backfill and zero-fill, with a 20-line docstring explaining why. The symptom
  is fixed; the written explanation of how is wrong.
- `remediation/04` cites `frontend/src/app/regime/page.tsx`; the file moved to
  `frontend/src/app/dashboard/regime/page.tsx`. Cited path no longer exists.
- `remediation/10` cites `analytics.py:222-259, 839-862, 1032-1045, 812`. The file is now
  **9,355 lines**; every one of those anchors is unrelated code. The fix did land.
- `ai-context-v3/09` claims 984 backend / 223 frontend tests; actual ~1618 / ~232.

---

## 5. The quant-math cluster — one bug, six tickets

P3 tickets **08, 09, 13, 19, 21, 22** are a single defect wearing six hats: *a failed
measurement returns a plausible number instead of nothing.*

| Site | Emits | Should be |
|---|---|---|
| `analytics_engine.py:2517` | `diversification_ratio = ... if n_assets > 0 else 1.0` | `None`; sibling `:2516` already guards to `0.0` |
| `websocket.py:417-424` | `if all(v is not None ...)` passes on a fabricated `0.0` → `analytics_status = "measured"` | reject `0.0` from an unmeasured branch |
| `analytics_engine.py:3952-3953` | `sharpe_ratio = 0.0` in the `< 10` obs branch | `None` + reason |
| `regime_service.py:342` | `cagr = 0.0` for an unoccupied HMM state | `None` |
| `cointegration_service.py:890` | `z_val = 0.0` while the headline correctly returns `None` | `None` |
| `analytics_engine.py:4798-4811` | `_empty_concentration` returns all `0.0`/`1.0` | `None` throughout — `_empty_liquidity` at `:4813-4836` is the correct reference |
| `tail_risk_service.py:548` | `"matrix": [[1.0]]` for one asset | `None` / explicit status |

**One pass replacing fabricated defaults with `None` + an explicit `data_status` closes all
six**, plus the ~205 un-ticketed ones in section 2.3. Working them in sequence is
substantial wasted effort. The concrete consumer proof: `websocket.py:413-422` promotes a
fabricated zero to `"measured"`, so a portfolio with too little history is currently
reported to the user as measured.

**P3 is otherwise clean:** 27 of 28 tickets are genuinely un-started. Every cited defect was
confirmed live at its stated location.

---

## 6. Phase-1 bfinance — spec badly stale (22 tickets, external repo)

### 6.1 Spec drift

The spec claims bfinance has *"exactly two upstream URLs"* and *"no NSE, BSE, CDSL/NSDL,
SEBI, RBI, AMFI, or NSE Indices code."* Reality is **5 hosts**:

| Host | Purpose | Ticket |
|---|---|---|
| `www.screener.in` | HTML + ratio API | spec-known |
| `nsearchives.nseindia.com` | CM/FO bhavcopy | 03 |
| `www.nseindia.com` | corporate-actions ex-date feed | 05 |
| `marketlens.nseindia.com` | close+volume, 30Y, zero auth | 22 |
| **`trendlyne.com`** | **third-party, unofficial, robots-gated** | **none — unspecced** |

New since the spec: `src/bfinance/nse/` (bhavcopy, corporate_actions, marketlens) and
`src/bfinance/trendlyne/`. Deleted: `src/bfinance/sector.py` (breaking — `bfinance.Sector`
now raises `ImportError`).

### 6.2 Verdicts

| Verdict | Count | Tickets |
|---|---|---|
| Already fixed upstream | 5 | 01, 03, 07, 13, 20 |
| Genuinely shipped | 1 | 22 marketlens |
| Partial | 7 | 05, 08, 09, 10, 11, 21 |
| Not started | 9 | 02, 04, 12, 14, 15, 16, 17, 18, 19 |

**Ticket 05 badly understates its own scope.** The NSE corporate-actions feed landed on
`history(actions=True)` only. `Ticker.splits` / `.dividends` / `.actions` **bypass it
entirely** and still call the equity-capital-ratio inference (`ticker.py:381-393`). The
Vodafone Idea fabricated-split defect is fully live on the public accessor users call.

### 6.3 Un-ticketed bfinance findings

1. **`trendlyne` ships as a default-reachable third-party source with a robots gate**
   (`98463d9`, `b81ca28`) and appears in **zero** tickets, including the licensing one.
2. `to_yfinance()` **silently drops the `TTM` column** — xfail-pinned at
   `test_stmt_accessor_contract.py:196-218`. Becomes a live stale-period bug the moment
   ticket 04 routes accessors through it.
3. `to_yfinance()` emits **duplicate `Diluted EPS` index labels** — `df.rename` duplicates
   rather than merges, so `yf.loc["Diluted EPS"]` returns a `DataFrame` where a `Series`
   is expected.
4. `sqlite_cache` `with _connect()` never closes. `sqlite3.Connection.__exit__` is
   transaction-only, so ticket 06's stated acceptance criterion is unmet.
5. `screens.py:122-124` catches bare `Exception` per symbol and continues — a screen can
   silently return a short universe. Same bug class as ticket 09's deleted `Sector`, in a
   file nobody audited.

---

## 7. Tracker integrity

### 7.1 38 tickets have ambiguous `Blocked by:` references

The tracker uses three syntaxes in one field: `—` (57), `Phase 1 issue 03` (12), and a bare
`01` (**38 tickets / 41 instances**). A bare number carries no phase.

**40 of 41 instances resolve to more than one phase.** `p1-06 Blocked by: 01` could mean
p1-01 (repair-test-suite, external repo) or p2-01 (synthetic-OHLC guard, in-repo) — both
real, both consequential, opposite repos. Only `p3-24 → 23` is unambiguous, by accident.

Consequence: **39 of the 93 tickets advertising `ready-for-agent` are actually blocked.**

**Fix:** rewrite 41 tokens to `Blocked by: p1-01`. One line each, no tooling.

### 7.2 True frontier: 54

p0 3 · p1 10 · p2 10 · p3 20 · p4 2 · p5 9. Adding `remediation-11, 12` (2) and
`ai-context-v3/06, 08` (2) gives **58 unblocked in finengine** — reconciles with the 54
computed here.

### 7.3 Other graph defects

- **1 dangling edge:** `QH-11` cites `Blocked by: 24`; QH has 14 issues.
- **No cycles.** The graph is a DAG.
- `spec.md` triage table claims 92 `ready-for-agent`; actual 93.
- `p5-capability/spec.md` blocks 4 tickets (`01, 02, 04, 05`) that their own ticket files
  mark free. The spec contradicts its tickets.

### 7.4 Status vocabulary: 13 tokens against a documented 5

`docs/agents/triage-labels.md` defines five roles. Observed: **48 distinct raw strings,
13 distinct tokens.**

| Token | Count | Issue |
|---|---|---|
| `ready-for-agent` | 100 | — |
| `closed` | 58 | used as synonym for `resolved`, split by directory |
| `resolved` | 27 | — |
| `needs-info` | 16 | — |
| `ready-for-human` | 6 | — |
| `pending` | 4 | **undefined anywhere in the tracker** |
| `Verified & Fixed` | 4 | non-vocabulary |
| `claimed` | 2 | overlaps `in-progress` |
| `in-progress` | 1 | overlaps `claimed` |
| `deferred` | 1 | unclear: done-later or wontfix? |
| `resolved-with-caveat` | 1 | no canonical equivalent |
| `Resolved and Verified` | 1 | non-vocabulary |
| malformed mojibake | 1 | status + owner + date crammed into one field |

27 done-family entries carry a free-text suffix **inside** the status value, one of them a
200-character paragraph. `browser-verification-audit-2026` is the worst: 5 ways to say done
in 20 files. **9 of 222 put `Status:` at the end of the document** (all of `ai-context-v3`)
— a front-matter parser reads them as statusless.

Proposed: bare lowercase kebab token, nothing after it. Move date, priority, owner and
verification notes to their own lines. One regex.

### 7.5 Cited line numbers are decorative

Backend drift between ticket authorship and now is **1,000–2,000 lines**.

| Ticket | Cited | Actual |
|---|---|---|
| p3-08 | `:674` | `:2517` |
| p3-09 | `:2523-2536` | `:4798-4811` |
| p3-12 | `:1013` | `:2898` |
| p3-14 | `:1249`, `:2207` | `:4482` |
| p3-28 | `:663` | `:2506` |
| p3-18 | `analytics.py:6075` | `analytics.py:7201` |

Every defect was still findable **by content**, so no verdict was downgraded on this basis
— but the anchors are unusable. Cite the symbol, not the line.

---

## 8. Genuinely ready to work

Unblocked **and** verified un-started. This is the actionable list.

| Group | Count | Notes |
|---|---|---|
| **P3 honesty-correctness** | 20 | Best ROI. Pure quant math, zero external deps, no file contention. Plus the 6-ticket cluster in section 5. |
| P2 data-layer | 10 | `04-per-vendor-normalization-adapter` unblocks 4 more; `03-raise-instead-of-return-none` unblocks 2. `17` needs a schema change, not just a service fix. |
| P5 capability | 9 | `07-nse-sector-index-returns` is "free, no new source needed". `09`, `21` are partly shipped — re-scope before dispatch. |
| P0 preflight | 3 | `04-confirm-bfinance-install-mode` is answerable in 30 seconds and gates the whole Phase-1 program. |
| P4 india-producers | 2 | Both are bug fixes to existing producers. |
| ai-context-v3 | 2 | 06, 08 — but 06 is partial; re-read first. |
| remediation-2026-09 | 2 | **Both already done.** Do not dispatch. |

**Do not dispatch:** `p4-02` diagnoses a bug that does not exist (`NSEBulkBlockDeal` has no
`close` column at all). Six P4 tickets and one P5 ticket are `BLOCKED-ON-BFINANCE` on six
missing upstream modules (`flows`, `ownership`, `macro`, `costs`, `constituents`, `deals`).

---

## 9. Recommended sequence

1. **Reverse the purge decision** (section 2.1). Targeted 4-row delete, not a purge. Costs
   minutes; prevents destruction of 31,334 rows.
2. **Record the bfinance install mode** (section 2.2) and decide whether to publish
   upstream. All 21 Phase-1 tickets and 7 P2/P4/P5 tickets depend on this answer.
3. **Fix the 41 `Blocked by:` tokens** (section 7.1). One line each.
4. **Re-open QH-04, QH-13, QH-01, `remediation-09`** — closed with the fix absent. QH-13 is
   a live credential exposure.
5. **Do the degenerate-zeros pass as one unit** (section 5) — 6 tickets plus ~205 un-ticketed.
6. **Then run P3's 20 in parallel.** Independent, unblocked, no shared files.
7. **Tick or delete the 8 mislabeled `needs-info`** (P2-02, P2-12, P3-27, P4-03..07, P5-12).
   All in-repo. P4-05 alone gates 3 more.
8. **Decide the status vocabulary** (section 7.4) before the next agent runs, or they will
   produce a 14th token.

---

## 10. Confidence and limits

- All verdicts cite a `file:line` and were read from the working tree at commit `799d291`.
- **No tests were executed.** Test *presence* and test *content* were verified; a green run
  was not. `remediation/11` is certified as code-complete, not as a passing run.
- `ai-context-v3/01` and `09` are **unverifiable by construction** — their evidence scripts
  are deliberately out of VCS because they handle live holdings.
- `bfinance` HEAD moved to 2026-09-28 during this audit (a `trendlyne` commit and a screener
  refactor). `screener/client.py:100-121`, cited as the pacing-design source, now points at
  `ScreenerClient.__init__`; the logic moved to `:148-165`.
- The `backend-audit/verified-0X.md` count of ~205 is the reports' own figure, not an
  independent recount.
- `p5-02`'s claim that "sklearn is already a dependency" is **half true** — it is in
  `uv.lock` transitively, not in `backend/pyproject.toml`. `LedoitWolf` needs explicit
  declaration.

---

## 11. Corrections to earlier reports in this session

Recorded because they were stated with confidence and were wrong.

| Claim I made | Correction |
|---|---|
| "remediation-11 verified un-started; Sortino is broken at `:1454`" | All 11 items fixed. `:1454` is a bootstrap restatement, algebraically identical to the fix at `:3965`. My grep was a false positive. |
| "ai-context-v3 03 and 04 are stuck in stale claims" | Both **complete**. No decision needed beyond the status line. |
| "deep-history 14-17 pending, blocked behind 13" | All four shipped in `13d89ed`. |
| "6 tickets in p1-financial are open, human-gated" | All six **done**. |
| "the purge premise is falsified" | Refined: contamination is real but **4 rows**, provably. Correct action is a targeted delete, not a reversal. |
| "P3 has 20 unblocked ready-for-agent" | Correct count. But 6 of those 20 are one bug and should be done as a single pass. |
| "13 needs-info tickets are mislabeled" | 16 total, of which 11 are in-repo. The 5 bfinance ones are correctly parked pending approval to edit the external repo. |
