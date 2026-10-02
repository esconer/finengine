# Consolidated Audit — Plan

**Date:** 2026-10-02
**Deliverable:** a triaged, evidence-backed audit written to `.scratch/2026-10-consolidated-audit/`
**Explicitly NOT in scope:** fixing anything. No code, config, dependency or test changes.

---

## 1. What was already done (Phase 1 — complete, do not repeat)

Six read-only agents surveyed disjoint areas. Orchestrator then spot-verified the top claims
against source. **11 of 11 verified verbatim**, including one the orchestrator actively challenged
and was wrong to challenge:

| Claim | Location | Verdict |
|---|---|---|
| `next.config.ts` has **no** `output` key at all | `frontend/next.config.ts` | CONFIRMED (zero matches) |
| Base image `node:18-alpine` | `frontend/Dockerfile:2` | CONFIRMED |
| CI runs `pytest ... tests/` incl. `tests/integration/` | `.github/workflows/ci-cd.yml:54` | CONFIRMED |
| `BASE_EXPORT` hardcodes `C:\Users\Sayanti\...\v27.json` | `backend/tests/test_audit_rule_coverage.py:77` | CONFIRMED |
| `rsplit('///',1)` yields a **relative** sqlite path | `backend/Dockerfile:52` | CONFIRMED — orchestrator disputed, was wrong |
| `np.random.seed(hash(ticker) % 2**32)` | `backend/tests/conftest.py:448` | CONFIRMED |
| No `restoreMocks`/`unstubGlobals` | `frontend/vitest.config.mts:8-14` | CONFIRMED |
| `sharpe_ratio … else 0.0` | `analytics_engine.py:5468` | CONFIRMED |
| `volume = float(df[vol_col].mean())` into tier ladder | `analytics_engine.py:3945`, `:3971` | CONFIRMED |
| `positions: List[PortfolioPositionBase]` — no `max_length` | `schemas.py:374` | CONFIRMED |
| `as_of=datetime.now()` on the no-data branch | `analytics.py:10891`, `:11920` | CONFIRMED |

Findings available to the writers are on disk — **the writers' `Reads` column points at these
files, not at an agent summary.** Phase 1 was 91 items; the inventory is ~91 too.

| Inventory file | Covers | Writer |
|---|---|---|
| `plans/2026-10-audit/inventory-a1-api-services.md` | API-1..10, SVC-1..11, plus the full services cache inventory | A1 |
| `plans/2026-10-audit/inventory-a2fe-a3infra.md` | FE-1..11 (+ settled `/v1/models`, hardened list, bundle), INF-1..22 (+ CI matrix, hermeticity, doc drift) | A2, A3 |
| `plans/2026-10-audit/inventory-a4-prior-art.md` | OE-01..15, CL-01..22, 4 refuted claims, stale list, directory verdicts, 10 coverage gaps | A4 |
| `plans/2026-10-audit/inventory-a5-crosscut.md` | feature backlog + cross-cutting unverified seeds | A5 |

**Tooling facts the writers must know** (established by the orchestrator, both by hit and by control):
- `rg` with a quoted pattern containing `"` **silently matches nothing** on this machine — and
  **`-F` does NOT rescue it** (verified: `rg -F 'foo("'` returns zero on a control file where
  `Select-String` and `rg -F 'foo'` both match). **Use `Select-String`**, or a quote-free pattern.
  Any "no matches" claim needs a control search that DOES match.
- **`rg` is not the only trap — `Get-ChildItem -Recurse` misses dotfiles and hidden dirs.** The infra
  explorer lost `.github/workflows/` and `.githooks/` to this. Use `-Force` / `hidden: true`.
- `rg` respects `.gitignore`. `.scratch` is **not** ignored, but only **384 of 1849** `.md` files
  under it are visible to a default `rg` — `backend-deep-audit` alone is **1523 files / ~1.1 GB**
  (mostly `.next` webpack packs, `node_modules`, `.pack` files). Use `--no-ignore` to see the corpus.
- `.scratch` contains **1853 `.md` files / ~13 MB**, 24 subdirectories, 16 loose files.
- `C:\es\coding\bfinance` is **OFF LIMITS** (a different directory). The `bfinance` PyPI package in
  `backend/.venv` is a legitimate dependency and may be read.
- Runner is `bun`; `node`/`npm`/`npx` are unavailable. Do not run `pytest` (network, ~12 min),
  `next build`, or any server.

---

## 2. Document structure

One directory. `STATUS.md` + `LEDGER.md` are the two things a human reads; everything else is on demand.

```
.scratch/2026-10-consolidated-audit/
  STATUS.md        tombstone: which prior dirs this supersedes, coverage statement, counts
  LEDGER.md        THE file — ranked table rows only
  detail/api.md services.md frontend.md infra-tests.md prior-art.md
  features.md      non-defects, quarantined, EXCLUDED from all defect totals
  rejected.md      inherited claims that did not reproduce — unbounded, load-bearing
  unverified.md    ≤10, each with the exact command that would settle it
  open.json        machine-readable backlog with stable IDs
```

### Ordering inside LEDGER.md
- **§0 Verdict** — one paragraph. Ship-blocking yes/no, open blocker count, unknown count,
  **pre-cap counts for every band**. If the reader reads nothing else they must still be correct.
- **§1 BLOCKER** — cap 10
- **§2 DEFECT** — cap 25
- **§3 RISK** — cap 40
- **§4 NIT** — cap 30
- **§5 POINTERS** — to `features.md` / `rejected.md` / `unverified.md`

### The cap is a disclosure, never a truncation
If 14 items qualify as BLOCKER, `LEDGER.md` §0 states **"14 found, cap 10, 4 deferred to §2 and
listed there"** and all 14 appear somewhere. Silent overflow is forbidden: it converts the document
from merely incomplete into actively reassuring-while-wrong, in the direction the reader most wants
to be told. The pre-cap count also goes in `STATUS.md` and in `open.json`.

### Vocabulary — deliberately small, because parallel agents apply rich vocabularies inconsistently
**Severity:** `BLOCKER` (wrong number reaches the user, money, or availability) · `DEFECT` (real bug,
bounded blast radius, workaround exists) · `RISK` (will bite later, or developer-facing) · `NIT`
**Confidence:** `VERIFIED` (mechanism traced in source) · `DERIVED` (logical, nothing executed) ·
`NEEDS-RUNTIME` (needs a run to settle)

**Severity and confidence are orthogonal and are reported in separate columns.** A `DERIVED`
BLOCKER and a `VERIFIED` RISK are different kinds of statement and must not collapse into one
priority number.

---

## 3. Evidence floor

A row may enter `LEDGER.md` only with all five:
1. A `path:line` that **exists** — mechanically confirmed at write time.
2. The cited construct is **actually there** (quoted or precisely paraphrased).
3. A mechanism in ≤3 steps from construct to wrong outcome. "This looks wrong" is not a mechanism.
4. A stated impact, or the explicit admission "developer-facing, no user-visible effect" (caps at RISK).
5. Where the claim turns on a **type or a runtime value, the actual resolved type/value is named** —
   not the type a reader would assume. This project has already been burned exactly here:
   `float()` on a *Python* complex raises `TypeError`; on a **numpy scalar** it silently truncates.
   The entire Johansen finding turned on that distinction.

Every BLOCKER additionally carries a **reproduction**: a command, a request, or a two-line script.

### Drop vs quarantine
- **Below the floor → dropped.** Not archived, not listed.
- **Quarantine** (`unverified.md`) only under a hard, named exception: needs credentials, needs a
  runtime execution, or two code paths are genuinely ambiguous. **Plus** the full floor above.
  There is no exception for "the agent was fairly sure" and none for a missing `path:line`.
- **Cap 10.** Exceeding 10 means the exploration was too shallow, not that the project is haunted.
- Rationale: quarantine *launders*. An agent that cannot meet the bar dumps the item in
  "unverified" and it survives forever. Silence and dumping are both bad; a queue with an exit and a
  settle-command is neither.

---

## 4. Merge policy for prior art

Three sources, never mixed:
1. **Fresh code findings** (API/SVC/FE/INF) → populate §1–§4. These are re-verified against current
   code, so they carry full evidence regardless of whether an earlier audit also found them.
2. **Inherited claims** (OE-nn) → each gets exactly one verdict: reproduced at `path:line` /
   not-reproducible / partial / cannot-be-settled-by-reading. An inherited claim that **cannot be
   re-verified is NOT promoted to OPEN** — it goes to `unverified.md` or `rejected.md`, never to a
   severity band on the strength of the old document alone.
3. **Confirmed-closed claims** (CL-nn) → `rejected.md` with the current-code proof. **This is a
   deliverable, not a side effect.** Retiring 22 verified-closed findings is what makes this run
   different from audit #27.

**Never edit or delete any prior `.scratch` file.** They are the provenance for every confirmed item.
Retirement is by tombstone in `STATUS.md` only.

---

## 5. Task graph

### Wave A — 5 writers, parallel, disjoint output files

| ID | Writer | Reads (on disk) | Writes | Depends on |
|---|---|---|---|---|
| A1 | services + API | `inventory-a1-api-services.md` | `detail/api.md`, `detail/services.md` | — |
| A2 | frontend | `inventory-a2fe-a3infra.md` (Part 1) | `detail/frontend.md` | — |
| A3 | infra / tests / deps | `inventory-a2fe-a3infra.md` (Part 2) | `detail/infra-tests.md` | — |
| A4 | prior art | `inventory-a4-prior-art.md` | `detail/prior-art.md`, `rejected.md` | — |
| A5 | cross-cutting | `inventory-a5-crosscut.md` + A1–A4 detail files | `features.md`, `unverified.md` | A1–A4 |

Each writer **re-verifies** its own rows against source before emitting them — the writer is not the
explorer that produced the claim, so this is an independent check, not a rubber stamp.

**A4 owns `rejected.md` exclusively.** Any inherited claim A4 cannot settle by reading is **not**
written to `unverified.md`; it goes into a delimited handoff block at the end of
`detail/prior-art.md` headed `<!-- UNVERIFIED-HANDOFF -->`. A5 folds that block into
`unverified.md` against the single ≤10 cap. This resolves the two-writer collision.

**`Verify:` per writer** — every `path:line` the writer emitted resolves; **and a semantic spot-check**:
re-read a sample of at least 5 of that writer's own citations and confirm the cited construct is
actually present at that line. Citation *liveness* is not support — a resolvable citation can still
point at absent code. Also: every id in the writer's namespace (`API-*` / `SVC-*` / `FE-*` / `INF-*` /
`OE-*` / `CL-*`) appears exactly once across all detail files.

### Wave B — 1 assembler (serial; genuine data dependency on all of Wave A)

Reads the five detail files. Applies caps **with disclosure**, ranks by severity then confidence,
emits `LEDGER.md`, `STATUS.md`, `open.json`.

**Dedup is the assembler's job and it is mandatory.** A defect found both fresh (A1–A3) and by prior
art (A4) must occupy **exactly one row**. Precedence: **the fresh finding wins**; the prior-art row
is demoted to a `also found by` provenance field on that row, not a second row. Rationale: the fresh
row is re-verified against current code and the prior-art one may only be inherited.
Wave B "does not re-derive findings" — this is not re-derivation, it is choosing which of two
existing rows represents one defect.

**`Verify:`** row count in `LEDGER.md` == sum of per-band counts in §0 == length of `open.json`, and
**no two ledger rows cite the same `file:function`**.

### Wave C — verification (orchestrator, not delegated)

1. Extract every `path:line` from `LEDGER.md` and confirm each resolves. A dead citation fails the
   whole document.
2. **Semantic spot-check:** independently re-read the top ≤10 BLOCKER citations and confirm the
   construct is present and the mechanism holds. Do not read any writer's summary first.
3. `git status --porcelain` **diffed against the captured baseline** must show no new entries outside
   `.scratch/2026-10-consolidated-audit/`. Baseline (captured before Wave A) has 8 entries, all
   pre-existing: ` M .scratch/project-state/current-state.md`, `?? .scratch/data-correctness-2026-09/`,
   `?? .scratch/v5-review/1{1,2,3}-*.md`, `?? .scratch/verification/`, `?? plans/2026-10-audit/`,
   `?? plans/2026-10-consolidated-audit.md`. **The tree was already dirty; the gate is a diff, not
   a clean-tree assertion.**

---

## 6. Do-not-touch

- **No edits to any source file.** `backend/**`, `frontend/**`, `.github/**`, `docker-compose*`,
  `scripts/**`, `pyproject.toml`, `package.json`, any lockfile.
- **No edits or deletions to any pre-existing `.scratch` file or directory.**
- No commits. No `git stash`/`checkout`/`restore`. No installs. No upgrades. No server.
- No `pytest`, `next build`, `vitest`, or audit CLI runs.
- `C:\es\coding\bfinance` off limits.

## 7. Known limits to disclose in §0

- No finding was reproduced at runtime. Everything is source-verified; nothing is measured.
- The refusal rate of the new Johansen tri-state on the real 14-name book is still unmeasured.
- The paired `/health` + `/v1/models` request flood was **ruled out** as a frontend cause (zero
  occurrences of `v1/models` anywhere under `frontend/src`); the caller is outside the audited
  directories and remains unidentified.
- `context_audit.py` (228 KB) has never been audited as a *collector*, only its rules' logic.
- `.scratch/backend-audit/verified-01..06.md` holds ~205 defects outside any ticket system and was
  not adjudicated this run.