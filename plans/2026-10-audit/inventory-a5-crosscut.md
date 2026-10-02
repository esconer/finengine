# Inventory slice A5 — cross-cutting inputs

Source: Phase 1 explorers, read-only. A5 runs **after** A1–A4 and also reads their `detail/*.md`.

## The feature backlog — non-defects, quarantined in `features.md`, EXCLUDED from all defect totals

`.scratch/advanced-analytics/` holds **32 feature tickets** (a backlog, not an audit — the prior-art
explorer did not adjudicate it). `.scratch/plugin-architecture/` holds 6 design docs + a README.
`.scratch/data-source-preference/` holds one unopened `spec.md`.

A5's job is **not** to re-adjudicate those. It is to produce a `features.md` that:
- lists feature/class items **raised by the A1–A4 finding sets** (e.g. INF-9 "assert shape and
  content" and INF-14 "live-export audit gate" are features-as-much-as-defects), and
- carries a pointer to the 32-ticket backlog **without reproducing or endorsing it**, and
- states plainly that `advanced-analytics/` was **not adjudicated this run**.

**Feature rows must never appear in `LEDGER.md` or count toward any band total.** The user asked for
features alongside bugs; the honest way to deliver that without inflating a risk ledger is a separate,
clearly-labelled file. Label every row `non-defect`.

## Cross-cutting unverified seeds — candidates for `unverified.md`

Quarantine is capped at **10** and requires a named exception: needs credentials, needs a runtime
execution, or two code paths are genuinely ambiguous. **Plus** the full evidence floor in §3 —
including a `path:line` that exists. There is no exception for "the agent was fairly sure".

Ranked by how badly the user needs to know:

1. **Real-world frequency of the Johansen refusal** (`COINT_CONTRACT_VERSION = "johansen-tristate-1"`
   shipped in a recent commit). ~3% refusal rate came from **synthetic pairs only**; nobody has
   measured it on the real 14-name book. **If it is always 0, the tri-state paths stay untested by
   live data** — the same shape as the pre-existing NUM-024 "live guard with nothing to guard today"
   note. Needs a scan run. → `needs-runtime`.
2. **Identity of the paired `/health` + `/v1/models` request flood caller.** The frontend is
   **ruled out** (zero `v1/models` occurrences under `frontend/src`, control matched; `/health` exists
   as `healthApi.check` with **zero callers**; the only HTTP `setInterval` is dead). So the caller is
   outside the audited frontend directories — likely an OpenAI-compatible SDK probing an LLM server,
   given `/v1/models` sits on the backend origin with no `/api` prefix. Needs a network trace.
   → `needs-runtime`.
3. **Whether `actions/cache@v3` hard-fails or merely warns** on GitHub-hosted runners
   (`ci-cd.yml:36-37`). Read the pinned version; the retirement is documented, the failure mode is not
   observed. → `needs-runtime`.
4. **Actual `--cov-fail-under=80` outcome.** Three different numbers are claimed across three docs
   (80 / 85 / 62%). Nobody has run it. → `needs-runtime`.
5. **Whether an all-NaN `Volume` column actually reaches `liquidity_analysis`** (SVC-1). The code
   path is deterministic; the prevalence needs a live multi-ticker fetch. → `needs-runtime`.
6. **Whether bfinance's `info` omits ratio keys or supplies literal `0.0`, and whether
   `returnOnCapitalEmployed` arrives pre-scaled** (SVC-4). The explorer could not read the dependency's
   `info` schema. Note `:317` reads ROCE raw while `:318` scales ROE `* 100` — if ROCE arrives already
   in percent, the scale concern evaporates and only the absent-to-zero concern remains. → ambiguity.
7. **The `rows=0` measurement for the four NSE India tables** (OE-07). The architectural claim
   (no fetcher, no scheduler) is confirmed; the emptiness was not measured. Needs DB access.
   → `needs-runtime`.
8. **Whether `async_client` tests have ever written to the real `daisy.db`** (INF-8). Mechanism
   confirmed; reachability unproven. → `needs-runtime`.
9. **Extent of `bfinance_synthetic_ohlc` contamination beyond the ledger's 4-rows-of-31,338**
   (OE-08). The missing guard is confirmed; the ledger's 0.013% measurement was not reproduced.
   → `needs-runtime`.
10. **Whether the 18 unexercised envelope rules (`ENV-001..015,017,018,020`) can fire at all**
    (INF-13). Static count is confirmed; actual fire counts need the harness run, which needs
    `v27.json` — currently unreachable on any other machine (INF-4). → `needs-runtime`.

**Drop, do not quarantine:** anything A1–A4 marked `needs-measurement` but that *does* have a
`path:line` and a named settle-measurement **within reach of a single command that needs no network
and no credentials**. Those are ledger rows with `DERIVED` confidence, not quarantine entries. The
quarantine is for what genuinely cannot be settled by reading.

## Cross-cutting themes the assembler needs for §0

- **The project's own defect class is "uncomputed statistic published as computed."** It now has at
  least 14 live instances across the layer boundary: SVC-1, SVC-2, SVC-4, SVC-6, SVC-9, SVC-10,
  API-3, API-10, FE-1, FE-2, FE-3, FE-4, FE-7, OE-01, OE-02, OE-09. **That is the single most
  concentrated risk in the codebase** and §0 should say so in one sentence with the count.
- **The delivery pipeline has never been green** (INF-1/2/3/4/5). Three independent fatal defects.
  This is arguably the top-line finding: there is no automated evidence any artefact was ever built.
- **Anti-fabrication culture is real and working** — ~20 sites deliberately preserve a missing value,
  several with large comment blocks explaining why a `fillna(0.0)` was removed; 22 prior findings
  verified closed; 692 lines of dead code deleted. §0 should record this, or the document reads as
  uniformly negative and misleads about the codebase's actual state.
- **Two recurring author-side hazards:** (a) a `max_length`/cap is applied everywhere *except* the one
  list that reaches a vendor (API-1); (b) a fabrication guard is applied to the short-sample branch
  but not the equivalent degenerate-value branch (SVC-2 mirrors the `<10` fix without the
  zero-variance fix).