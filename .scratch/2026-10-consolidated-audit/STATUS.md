# STATUS — consolidated audit, 2026-10-02

**This run changed nothing.** No source file, config file, test, dependency, lockfile or CI workflow
was edited, and no prior `.scratch` file was edited or deleted. The five deliverables of this run are
`LEDGER.md`, `STATUS.md`, `open.json`, `features.md` and `unverified.md`. The five writers' outputs
(`detail/*.md`, `rejected.md`) and the override layer (`ORCHESTRATOR-CORRECTIONS.md`) are inputs and
are unmodified.

---

## 1. Tombstone — what this run supersedes

`.scratch/` holds **24 prior subdirectories** plus this one. **23 of the 24 received a directory
verdict; 1 (`bfinance-integration/`) appears only in the stale list.** Retirement is by tombstone
here and nowhere else: every prior file remains the provenance for every confirmed item, per plan §4.

| verdict | directories | what it means now |
|---|---|---|
| **superseded — do not re-audit (4)** | `backend-audit-2026/` · `deep-history-2026-09/` · `p1-financial-correctness-2026-09/` · `bug-sweep-2026/` | Their findings are either fixed or deliberately deferred with a stated reason. Re-reporting from them re-reports closed work. |
| **live — findings here stand (5)** | `verification/` · `data-correctness-2026-09/` · `project-state/` · `quality-hardening/` · `resource-optimization/` | This run's `OE-*` rows descend from these. `data-correctness-2026-09` P3 tickets 03, 04, 08, 16 and 24 are all still `ready-for-agent` and all still reproduce. `verification/`'s §4.1–§4.4 is the real status, **not** its status column. |
| **partly-live — adjudicate per finding, never per directory (10)** | `backend-deep-audit/` · `v5-review/` · `ai-context-v3-remediation-2026-09/` · `frontend-audit/` · `backend-audit/` · `browser-verification-audit-2026/` · `page-audit-2026-09/` · `terminal-ux-audit-2026/` · `remediation-2026-09/` · `ponytail-audit/` | Three overlapping bodies of findings. `ai-context-v3-remediation-2026-09/` self-declares 8 fixed and **none** was independently verified — treat all 8 as unverified. `terminal-ux-audit-2026/` issues 04 and 05 are marked `closed` with live defects: a second false-closure cluster after `quality-hardening/`. |
| **unclear / not opened — a backlog, not an audit (4)** | `advanced-analytics/` (32 tickets) · `portfolio-audit-2026/` · `data-source-preference/` · `plugin-architecture/` (6 design docs) | **Not adjudicated this run.** Pointer only, in `features.md`. Several `advanced-analytics` tickets turned out to be the *provenance* for live defects (`05-benchmark-ingestion-service.md` → `OE-04`; `17-india-flows-dashboard.md` → `CL-19`), so they are not worthless — they are simply not an audit. |
| **no verdict (1)** | `bfinance-integration/` | Listed in `rejected.md` Part 3 as superseded by the bfinance 0.2.0 programme; carries no findings of its own. |

**An arithmetic note, because a wrong count is a wrong tombstone.** `rejected.md`'s own footer reads
"21 directory verdicts (4 superseded, 5 live, 9 partly-live, 3 unclear)". Those are **table-row**
counts: its `partly-live` table has 7 rows covering 10 directories, and its `unclear` table has 2 rows
covering 4 directories. Counting **directories** gives 4 + 5 + 10 + 4 = **23**, plus the one
unclassified = 24. Both figures are correct at their own granularity; the directory-level count is the
one that answers "what is still live".

---

## 2. Retirements — the deliverable, not a side effect

| retired | count | proof standard |
|---|---|---|
| **Confirmed closed (`CL-01`..`CL-22`)** | **22** | Each re-verified against current code. **18** are traced to an artifact that asserted them; **4** (`CL-04`, `CL-07`, `CL-08`, `CL-12`) are proven closed but the original assertion **could not be traced to any artifact** — the closure is proven, the provenance is missing, and that distinction is preserved in `rejected.md`. |
| **Refuted inherited claims** | 4 | `R1` refuted, `R2` partly refuted, `R3` confirmed true, `R4` refuted as stated. |
| **Rejected inherited claim** | 1 | `OE-13` (backend CSV formula injection) — the helper exists and covers every user-controlled column. The claim had **no artifact behind it at all**. Confirmed by COR-5. |
| **Inventory sub-claims that failed re-verification** | 12+ | 6 in `detail/api.md`, 7 in `detail/services.md`, 6 in `detail/infra-tests.md`, plus partial corrections in `detail/prior-art.md`. Not silently corrected in place — each writer kept a "Rejected on re-verification" section. |
| **Stale / superseded entries** | 11 | Listed in `rejected.md` Part 3. |
| **Coverage gaps — nobody has audited these** | 10 | `rejected.md` Part 5. These are claims about an *absence*, which cannot be re-verified from the artifacts that would contain it. |

**The 22 retirements are the reason this run is not audit #27.** A future audit that re-reports closed
work is the specific failure mode `open.json` exists to prevent.

---

## 3. Pre-cap counts

Identical to `LEDGER.md` §0 and to `open.json`'s `pre_cap_counts` block.

| band | pre-cap found | cap | shown | deferred |
|---|---|---|---|---|
| BLOCKER | **8** | 10 | 8 | 0 |
| DEFECT | **21** | 25 | 21 | 0 |
| RISK | **30** | 40 | 30 | 0 |
| NIT | **8** | 30 | 8 | 0 |
| **total ledger rows** | **67** | 105 | **67** | **0** |

**No band reached its cap. Nothing was truncated and nothing was deferred.** Plus **10** entries in
`unverified.md` and an unbounded number of `non-defect` rows in `features.md`, which are **excluded
from every band total above**.

One duplicate defect was merged rather than filed twice: `OE-14` (prior art, BLOCKER) into `FE-5`
(fresh, DEFECT). Full dedup disclosure in `LEDGER.md`'s closing section.

---

## 4. What was NOT examined

This is the section that keeps the rest honest. Nothing below was audited by this run.

### 4.1 Nothing was executed
**No finding in this audit was reproduced at runtime.** No `pytest`, no `next build`, no `vitest`, no
audit CLI, no server, no container build, no `docker compose`. Every row is source-verified; every
magnitude, frequency, latency and cost figure is either explicitly disclaimed on its row or
quarantined in `unverified.md`. A clean `tsc --noEmit` is cited in the detail files only as an argument
for *why a claim is not checkable*, never as evidence against a runtime claim.

### 4.2 Directories and files not read
- **`.scratch/backend-deep-audit/`** — 121 findings, **1,523 files / ~1.1 GB**, not read.
- **`.scratch/backend-audit/verified-01..06.md`** — **~205 defects outside any ticket system**, described
  by their own authors as *"audit reports, not resolutions"*. **The single largest untracked body of
  work in the repository.** Not adjudicated.
- **`.scratch/advanced-analytics/`** — 32 feature tickets. Not adjudicated; pointer only.
- **`.scratch/plugin-architecture/`** (6 design docs + README), **`.scratch/portfolio-audit-2026/`**,
  **`.scratch/data-source-preference/spec.md`** — not opened.
- **`C:\es\coding\bfinance`** — off limits; a different directory. No claim about it can be verified
  from here. (The `bfinance` PyPI package inside `backend/.venv` *is* a legitimate dependency and was
  read, for `OE-08`. The boundary is the source tree, not the name.)
- **`backend/app/services/context_audit.py`** — 228 KB, 4,980 lines. `v5-review/07-09` reviewed the
  **rules' logic**; nobody has reviewed what the **collector costs** or whether its clock ordering is
  sound.

### 4.3 The ten coverage gaps — claims about absence
No security or threat-model audit exists in ~380 artifacts. No supply-chain / dependency-trust audit.
Concurrency is nearly unreviewed (two races found, one fixed and one never resolved; the SSE/WS
broadcast path and cache purge during in-flight publication were named once and never revisited). The
13 newly-migrated Radix modals got no accessibility review. `docker-compose.prod.yml`'s ~105-line
observability stack was never re-checked. `lib/export.ts` was split but the chart path was not
re-audited. Number formatting is standardised for money but not for counts and percentages.
`analytics.py` has no owner after line drift.

### 4.4 Specific claims left open
- **The refusal rate of the new Johansen tri-state on the real 14-name book** — unmeasured. The ~3%
  figure came from **synthetic pairs only**. → `unverified.md` #1.
- **The paired `/health` + `/v1/models` request flood caller** — the frontend is **ruled out** (zero
  `v1/models` under `frontend/src`; `healthApi.check` has zero callers; the only HTTP `setInterval` is
  dead). The caller is outside the audited directories. → `unverified.md` #2. *New this run: the
  backend itself hosts `GET /v1/models` at `backend/main.py:189` as an honest OpenAI-compatible
  discovery shim, which makes an SDK probe the most probable caller — still a hypothesis, not a fact.*
- **`RELEASE_NOTES.md:181`'s "249 / 249 Passed … 85% coverage"** — contradicted by a structurally red
  pipeline and by its own 85%-vs-`--cov-fail-under=80` inconsistency, but the corrected figure is
  **inherited, not measured**. → `unverified.md` #5.
- **Three of the eight rows** in the services cache inventory were not re-verified (`AnalyticsCache`,
  `ScreenerService._cache`, `_exchange_rates`). The table's *conclusion* is consistent with everything
  that was checked but is **not endorsed as fully verified**.
- **Six of eight filenames** in the A1 cache-inventory table are wrong (line numbers right) — COR-7.
  Treat any filename in an inventory *table* as unverified.
- **Three declared-but-unused pytest markers** (`integration`, `database`, `slow`) — counted with a
  *working* control set, because the inventory's stated control did not reproduce.
- **Branch-protection settings** are not in the repository, so what *technically* blocks a merge is
  unobservable from here.
- **`INF-18`'s security half**: no tracked secret or `.db` file was found, but the index was **not
  enumerated**. That gap is settleable with one command, so it is a ledger caveat rather than a
  quarantine entry.

### 4.5 A sixth slice arrived after assembly began — six of its findings are deliberately unranked

`detail/research-doc-accuracy.md` (a `docs/research/` fact-check, written 21:35) landed **after** this
ledger was assembled. It is **not** in the five-writer input list, and it is **documentation-accuracy
only**: it assigns **no id namespace, no severity and no confidence**. Ranking it would mean inventing
band assignments, which this run does not do — so its findings are enumerated here instead of being
silently dropped.

**Six live defects it confirms carry no row in `LEDGER.md`:**

| where | what | why it is not ranked |
|---|---|---|
| `backend/app/services/optimization_service.py:791`, `:848` | Black-Litterman uses an equal-weight "market portfolio" (`w_mkt = np.ones(n) / n`) and then silently `np.clip(raw, 0.0, None)`-renormalises | No severity assigned by the writer; inherited doc claim rated MEDIUM by a 2026-09 research report |
| `backend/app/services/regime_service.py:307-311`, `:317`, `:323` | The published HMM transition matrix is a `sticky_trans` prior that was never fitted — the doc's line was exact | as above (MEDIUM) |
| `backend/app/services/analytics_engine.py:374`, `:388` | Hardcoded per-ticker and 7×7 sector stress elasticities | as above (MEDIUM, and the slice notes it is now *expanded*) |
| `backend/app/api/analytics.py:12330` | `/vol-cone` validates `lookback_days` and then calls `calculate_volatility_cone(port_ret)` without passing it | as above (LOW) |
| `backend/app/services/analytics_engine.py:5996` | EWMA seed/iterate window mismatch | as above (LOW) |
| `backend/pyproject.toml:37` | `quantlib` is declared and locked but imported nowhere in `app/` | **already covered** — this is the QH-10 half of ledger row `OE-15`. Listed here only because the slice treats it as open. |

**Two of its findings overlap this ledger and need no new row:** its unreachable
`except HTTPException` finding is already `API-7`, and its `quantlib` finding is already inside `OE-15`.

**What it retires is as valuable as what it finds.** The research corpus's **#1-ranked
recommendation — "upgrade now, your pin is four versions / eight months stale" — is already shipped**
at `backend/pyproject.toml:21` (`"quantstats>=0.0.85"`). ADF/KPSS stationarity is **already
implemented** at `cointegration_service.py:15` despite a capability table reading *not implemented*. Three
of five HIGH/MEDIUM §5 violations are fixed. **12 of 12 licensing claims were re-fetched from upstream
and 0 are wrong**, including the two load-bearing ones (backtrader GPLv3+, backtesting.py AGPL-3.0). And
**34 of 44 symbol-index entries** in `current-codebase-quant-inventory.md` now point at wrong lines —
the documents' substance holds and their *coordinates* are void.

**Action for a next run:** assign ids, severities and confidences to those six and merge them into
`LEDGER.md` §2–§4. Until then, **`LEDGER.md` §1–§4 is not a complete defect census of this repository**,
and `open.json` does not list them.

---

## 5. Provenance and the next run

`open.json` is the artefact that stops a future audit re-reading 26 directories. Every row has a stable
id matching exactly one section in one `detail/*.md` file. A next run should:

1. Read `open.json` and `rejected.md` **before** searching anything.
2. Treat `rejected.md` as load-bearing: 22 findings there are proven closed **in current code**.
3. Open the ten `unverified.md` entries and run their settle-commands. Each one either closes or becomes
   a row — none may be carried forward again without new evidence.
4. Not trust an inventory *table*'s filename (COR-7), a status line (OE-15), a doc-drift citation
   (`RELEASE_NOTES.md` anchors move), or a header tally (`frontend-audit/02-06` tallies mask
   per-finding reality).
5. Read `LEDGER.md` §0 first. If the reader takes nothing else from this audit, §0 must still be
   correct about severity counts, about CI never having been green, and about the anti-fabrication
   culture being real and working.