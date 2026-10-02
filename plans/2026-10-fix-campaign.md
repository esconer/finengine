# Fix campaign — 2026-10-03

Continues the audit (`plans/2026-10-consolidated-audit.md`). 67 ledger findings + 28 quantitative
findings. **Wave 1 is dispatched**; wave 2 is gated on two recon agents triaging the unread rows.

Suite baseline: **2365 passed / 1 deselected / 0 failed / 87.60% coverage**. Must stay green.
Everything commits locally. Nothing is pushed.

---

## The finding that reframed the last round

`test_audit_rule_coverage.py:77` hardcodes `C:\Users\Sayanti\AppData\Local\Temp\opencode\v27.json`
and `:1057` calls `pytest.fail` when it is absent. The file exists **on this machine**, so the suite
went green locally — and `ci-cd.yml:73` runs `pytest tests/`, so on `ubuntu-latest` **the backend job
is still red.**

**A green suite on the developer's machine is not a green CI.** That is now the first task, not a
footnote. Any future claim of "CI is green" must be qualified by whether it was verified *off* this
machine, and the honest answer until Wave 1 lands is **no**.

---

## Wave 1 — dispatched (4 agents, disjoint files)

| ID | Owner | Files | Defects |
|---|---|---|---|
| W1-A | `test_audit_rule_coverage.py` + new fixture | INF-4 — machine-bound gate |
| W1-B | `analytics_engine.py` | SVC-2/QM-3 hard `0.0` Sharpe+Sortino · stress elasticities · EWMA seed |
| W1-C | `analytics.py` | API-2 tear-sheet blocks the event loop · API-3 fabricated `as_of` · `:7185` dead default · `/vol-cone` dropped `lookback_days` |
| W1-D | 6 frontend files | FE-1 dead `N/A` · FE-3 `NaN%` · FE-4 fabricated `buy_price` · FE-7/FE-5 store laundering · COR-3 `store.ts:206` · OE-01 scale-sniffing formatter |

**Why grouped by file, not by severity:** two agents editing one file collide silently. Every pair
above is on a disjoint set.

**Escalation deferred, deliberately:** `is_cointegrated: bool` → `Optional[bool]` spans
`schemas.py` + `cointegration_service.py` + `analytics.py`. W1-C owns `analytics.py`, so this cannot
run concurrently. It is wave 2. It is also the same shape as the `johansen_cointegrated` fix already
shipped, so the pattern is established.

---

## Wave 2 — gated on recon, grouped by file

Candidates already verified, ordered by severity. **Final membership depends on the two triage
agents**; this is the shape, not the commitment.

**`analytics_engine.py`** (after W1-B) — remaining WRONG-CONVENTION and FRAGILE rows from QM-7..28.

**`analytics.py`** (after W1-C) — API-1 uncapped `bulk_add` fan-out · API-4 no pagination ·
API-5 sequential liquidity fetch · `is_cointegrated` Optional ripple.

**`schemas.py` + `cointegration_service.py` + `analytics.py`** — the refusal-representability change.
**This is one atomic change across three files and cannot be split**: making the field Optional
without updating every consumer republishes `None` as `False` in places that never expected it.

**`data_service.py` + `india_data_service.py`** — SVC-3 unlocked writes · SVC-5 no lock at all.
Fix shape is a **session-scoped** lock, not two per-instance locks: two independent locks would not
exclude each other, and `asyncio.Lock` is not re-entrant, so a naive wrap at `:704`/`:771` **deadlocks**.

**`regime_service.py`** — published transition matrix is a prior, never fitted (`:307-323`).
Worth checking against the librarian's trap 2.3 on `select_coint_rank` before touching.

**`vitest.config.mts`** — INF-7 `restoreMocks`/`unstubGlobals` absent while `setup.ts` mutates
globals at module scope. **Known to surface real failures** — four test files hand-roll `mockReset()`
as a workaround, so removing the workaround may red the suite. That is the point, not noise.

**`pyproject.toml`** — INF-16 `--frozen` → `--locked` · INF-17 dev-only deps in runtime deps ·
`quantlib` declared and never imported. **Careful:** there are two dependency tables; a bad edit
breaks every install.

**`backend/tests/conftest.py`** — INF-10 `test_env_vars` cannot work · INF-11 inert `pytestmark` and
an autouse `cleanup_test_data` that cleans nothing · INF-12 `hash()`-seeded fixture producing
different data every process.

**Frontend residual** — FE-6 live chip has two states · FE-8 PDF total drops unvalued legs ·
FE-10 `Header` subscribes to the whole store · FE-11 unmemoized columns.

---

## Explicitly NOT in this campaign

- **`docs/research/` corrections.** The corpus is substantively sound; 34 line references are stale.
  Fixing a research document is not a code fix and was not asked for.
- **Dark-mode unification, chart palette, `Card`/`PageHeader` extraction, the 10 duplicated explainer
  components, react-query adopt-or-remove.** Deferred by decision in an earlier session.
- **React Compiler.** `next.config.ts:5` deliberately off; 57 memo sites load-bearing.
- **The ~30 remaining library traps.** Ranked in
  `.scratch/2026-10-consolidated-audit/library-traps-assessed.md`. The `genpareto` sign convention
  is the one that can *invert* a risk classification rather than perturb a magnitude.
- **The `/v1/models` + `/health` flood.** Ruled out as frontend; the caller has never been
  identified and needs a network trace no agent is permitted to take.

---

## Verification protocol — per task

1. **Red before green, by execution.** Structural proof where runtime is impossible, labelled as
   structural. **No invented timings, no invented pass rates.**
2. **No published figure may change** for a correct input. Where a figure *should* change, say so
   and show why.
3. **Never substitute a plausible value.** No `|| 0`, no `fillna(0)`, no widened `except`, no silent
   `.real`. A refusal must remain expressible.
4. **Full suite green at the end, on a settled tree.** Concurrent agents make interleaved counts
   meaningless — that cost ~30 minutes and produced four different "baselines" last round.
5. **Read the diff before committing.** A worker's report is a claim; my own read is the evidence.

## The trap that has cost the most this session

Every one of these has produced a wrong claim at least once:

- `rg` with a quoted `"` **silently matches nothing** — and **`-F` does not fix it**. Use `Select-String`.
- `Get-ChildItem -Recurse` misses dotfiles/hidden dirs without `-Force`. One agent concluded
  `.venv` did not exist because of this.
- **Python's builtin `min(5.9, nan)` returns `5.9`; `np.minimum(5.9, nan)` returns `nan`.**
- `float(np.complex128(...))` silently truncates; `float(python_complex)` raises `TypeError`.
- **A green suite on the developer's machine is not a green CI.**