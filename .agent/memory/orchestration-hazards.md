# Orchestration hazards — finengine fix campaign (2026-10)

Durable process lessons. These are about *how work gets done here*, not about the code.

## A red proof swaps the real file into place. Concurrent readers see fiction.

To prove a test fails on pre-fix code, an agent must put the pre-fix bytes at the real path,
run, then restore. Every honest red proof does this. The window is real and observable.

Seen live: `backend/app/api/analytics.py` measured **667,271 B** (byte-identical to `HEAD`,
`.get("r_squared", 0.0)` back at `:7184`) while another agent was mid-proof, then
**672,094 B** with the fixes present. Tests that pin the fix failed during the window and passed
after. Four "failures" were a proof in progress.

**Rule: never accept a red/green result from a source file whose size or mtime is moving.**
Capture the size before and after a peer agent's window, or re-run any surprising failure once the
tree is settled before believing it. Two agents independently concluded "pre-existing failure"
from a window that was actually someone's proof.

**Corollary:** do not let N agents run the same module's tests concurrently *while* another is
editing that module. Disjoint files are not sufficient — a red proof is not disjoint.

## Machines constraints under many concurrent agents

- **`OPENBLAS_NUM_THREADS=1` on every `uv` / `pytest` call.** With several agents live, free RAM
  drops below 1 GB and OpenBLAS/uvicorn fail to spawn: *"Memory allocation still failed after 10
  retries"*, *"The paging file is too small"*. This silently converts runs into collection
  failures and gets misread as a test defect.
- **A full backend suite run by several agents at once produces meaningless interleaved baselines.**
  One agent's run "showed" 22 pre-existing failures that were another agent's in-flight edits.
  Subagents test only their own files; the root agent runs the full suite once.
- The pass count **drifts upward during a campaign** as agents add test files — 2,365 became 2,497.
  A fixed expected count is a wrong assertion during active work.

## Verified-good verification techniques (worth demanding again)

These agents produced evidence that a reviewer can actually check. Reuse the shapes:

- **Structural, not timing.** For "is this off the event loop", park the call on a `threading.Event`
  and assert a *concurrent* request completes. Binary, cannot pass by being fast, cannot fail on a
  slow machine. Every timing-threshold test I asked for earlier was a tuning risk.
- **Differential attribution.** Re-run a failing set against a pristine copy, then
  `Compare-Object` the sorted FAILED lists. Identity proves "not mine"; anything else names a culprit.
- **Golden with a key-set assertion.** `payload == golden` *plus* `set(payload) == set(golden)` —
  so a silently added or dropped key fails too, not just a changed value.
- **A rejection gets a regression guard.** When an agent disproves a finding, pin the *absence*:
  `test_no_lookback_field_was_added_to_the_cone_payload`. Otherwise the next agent "fixes" it again.
- **Reproduce the old value inside the test** so the claim stays falsifiable rather than merely absent.
- **Agents should discard their own weak tests and say so.** One threw away a loop-iteration counter
  because it passed on both old and new code, and documented why in the module docstring.

## The recurring author-side question, again

Three distinct real defects in this repo were guards of exactly this shape — present, reading as
correct, and **unable to observe the value they tested**:

- `test_risk_contribution_tail_support_convention.py:_clearance` asserts `reach <= 0` against
  `pd.bdate_range`, i.e. it asserts *today is a business day*, while its docstring says it asserts
  the window is *recent enough*. `RECENT_DAYS = 21` is declared and used elsewhere and never
  referenced here. Fails every Saturday, Sunday and market holiday.
- `analytics_engine.py` Sharpe/Sortino had a guard for the short-window branch but not the
  degenerate-value branch.
- `volatility_service.py` ranked a fabricated `0.0` against a percentile distribution.

**Ask "can this guard observe the value it tests?" — not "is there a guard?"**