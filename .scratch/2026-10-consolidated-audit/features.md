# Features and class items — non-defects, quarantined

**Every row in this file is labelled `non-defect` and is EXCLUDED from every band total in
`LEDGER.md` §0 and from `open.json`.** Nothing here is a bug. This file exists so that a feature
request, a capability gap and a defect can be told apart without inflating a risk ledger — and so that
"should we build this?" has an answer that is not a severity band.

**Sources.** `plans/2026-10-audit/inventory-a5-crosscut.md` (the feature backlog and the cross-cutting
theme) plus the feature-shaped items the five writers raised in their own "Reviewed, not emitted as
findings", "Notes for the assembler", "Adjacent observations" and coverage-gap sections. Nothing here
was re-derived from source; it is carried forward with its provenance intact.

---

## 0. The pointer that must not be mistaken for a verdict

> ### `.scratch/advanced-analytics/` (32 tickets) was **NOT adjudicated this run.**
>
> The prior-art writer opened it, recorded that it is a **backlog rather than an audit** (its
> `verification` §7.4 note tabulates 13 status tokens against a documented 5), and declined to rule on
> it. **This run repeats that decision rather than quietly reversing it.** No ticket in that directory
> was opened, re-scored, endorsed or condemned. The 32 tickets are neither counted, ranked, nor
> criticised here.
>
> They are **not worthless**, and the reason is precise: several of them turned out to be the
> *provenance* for defects that **are** live in current code — `05-benchmark-ingestion-service.md` →
> `OE-04`, `17-india-flows-dashboard.md` → `CL-19` and the `liquidation_days` band. A backlog can be
> the best record of why a system is shaped the way it is without being an audit of it.
>
> `.scratch/plugin-architecture/` (6 design docs + a README) and `.scratch/data-source-preference/spec.md`
> were likewise **not opened this run**.

---

## 1. Feature rows

| id | item | class | why it is a non-defect | source |
|---|---|---|---|---|
| `F-01` | `.scratch/advanced-analytics/` — 32 feature tickets | **non-defect** | A backlog. Not adjudicated this run; pointer only. See §0 above. | inventory-a5 §"feature backlog"; `rejected.md` Part 4 |
| `F-02` | `.scratch/plugin-architecture/` — 6 design docs + README | **non-defect** | Design intent, not findings. Not opened this run. | inventory-a5; `rejected.md` Part 4 |
| `F-03` | `.scratch/data-source-preference/spec.md` | **non-defect** | Not opened, but cited for substance by `OE-12`'s provenance. | `rejected.md` Part 4, Part 5 |
| `F-04` | Assert **shape and content**, not `is not None` | **non-defect** (capability gap) | The `INF-9` fix is not a patch; it is a new assertion style the suite has never used — key presence, sign, magnitude, and identity relations (`effective_positions ≈ 1/Herfindahl`, `cvar_95 ≤ var_95`). | `detail/infra-tests.md` INF-9 |
| `F-05` | A CI job (or marked test) that runs the audit harness against an export produced by the **running application** | **non-defect** (capability gap) | `INF-14` is a RISK row about a missing check; the check itself is new capability. It must assert *shape*, not emptiness — a live export is non-deterministic and would be red on day one. | `detail/infra-tests.md` INF-14 |
| `F-06` | One **session-scoped** lock primitive shared by `DataService` and `IndiaDataService` | **non-defect** (shared remediation) | Neither `SVC-3` nor `SVC-5` can be fixed alone: `asyncio.Lock` is not re-entrant and a per-instance lock does not exclude across the two services. This is a primitive that does not exist yet, so it is a build item, not a bug. | `detail/services.md` SVC-3, SVC-5, "Notes for the assembler" |
| `F-07` | Vendorised, **scrubbed** `v27.json` under `backend/tests/fixtures/`, resolved relative to `__file__` | **non-defect** (capability gap) | The `INF-4` fix requires a fixture that must be sanitised before committing: `.gitignore:81-85` states generated exports contain live holdings, quantities, cost basis and P&L. Building the fixture is a task; sanitising it is a constraint, not a defect. | `detail/infra-tests.md` INF-4, "Hermeticity" step 4 |
| `F-08` | Hermeticity mechanism: autouse socket guard + autouse vendor fixtures defaulting to raise + `vcrpy` cassettes + vendorised export + suite-wide class-level cache reset | **non-defect** (capability backlog) | A five-step build, not a bug list. The repository has **already written the right pattern once** (`test_bugfix_core_services.py:266-302`, a `bfinance.Ticker` spy that fails loudly), so steps 2–3 generalise an existing good pattern. **Ordering is the useful part**: the cache reset (step 5) must land before any parallelism is introduced, because `pytest-xdist` is installed and never invoked. | `detail/infra-tests.md` "Hermeticity", recommended mechanism |
| `F-09` | `AnalyticsCache` is generic, so a *future* metric whose writer omits a contract check would re-serve a stale row indefinitely | **non-defect** (design property) | A design property of a working system, not a defect. **No such writer exists today** — the cointegration path is the only heavy user and it does supply a contract version at `cointegration_service.py:886` and `:910`. Deliberately given **no `SVC-*` id** by the writer so it could not contaminate the finding namespace. | `detail/services.md` "Reviewed, not emitted as findings" |
| `F-10` | Require a ticket's status line to **cite its verification** | **non-defect** (process capability) | `OE-15` and `verification/2026-09-ticket-state.md` both show the same failure mode: a status line advanced on work *done* rather than criterion *met*. Four tickets are closed against criteria current code does not meet, and `QH-10`'s criterion is **unsatisfiable as written**. | `detail/prior-art.md` OE-15 |
| `F-11` | `as_of_semantics` on `CorrelationStabilityResponse`, using the closed vocabulary `CointScannerResponse` already defines | **non-defect** (capability gap) | The *mislabel* is `API-3`'s defect; the *missing field* is new capability. `CointScannerResponse` already publishes the vocabulary, so this is extending a working contract, not inventing one. | `detail/api.md` API-3 |
| `F-12` | Publish the resolved benchmark price column and basis (`benchmark_basis`, `benchmark_price_column`, `total_return`) | **non-defect** (capability gap) | `OE-04`'s defect is that the basis is **decided silently**. Making it visible is a schema addition. Note the honest half: reading this repository can establish the *rule* and never the *outcome*, because the outcome is a third-party vendor's behaviour — see `unverified.md` #4. | `detail/prior-art.md` OE-04 |
| `F-13` | A third state on the live-connection chip ("off"/"disabled") | **non-defect** (capability gap) | `FE-6`'s defect is the chip lying about a connection it will never make; the fix is a **missing UI state**, not a wrong computation. | `detail/frontend.md` FE-6 |
| `F-14` | An explicit `experimental` boundary for the confirmed-zero-caller exports | **non-defect** (capability gap) | `FE-9`'s defect is that dead code **reads as live**. Deleting is one answer; a labelled boundary is the other, and the choice is a policy decision rather than a bug fix. Two of the dead exports open their own `WebSocketClient`, so the risk of re-mounting one is concrete. | `detail/frontend.md` FE-9 |
| `F-15` | A per-run record of **which** `as_of` semantics produced a figure, end to end | **non-defect** (capability gap) | The generalisation behind `API-3`, `SVC-1`, `SVC-9` and `SVC-10`: every one of those defects is a missing reason-token on a payload that already has somewhere to put one. | cross-cutting; `detail/services.md`, `detail/api.md` |

---

## 2. Ledger rows that are really pending decisions (context, **not** re-counted)

These **are** in `LEDGER.md` and **are** counted in their bands. They are listed here because the
honest description of each is "a decision someone has not made yet", not "a bug someone has not
fixed". They are **not** excluded from the totals and nothing is double-counted.

| ledger row | band | the pending decision |
|---|---|---|
| `OE-09` | RISK | `_empty_concentration` publishes `diversification_score: 0.0`, and the source **comment says so and cites the contradicting precedent**. Three options, and the writer is explicit that options 2 and 3 are a live question: (1) align with `_empty_liquidity` and publish `None`; (2) keep the values and oblige every consumer to branch on `n_holdings`; (3) keep as-is and publish `diversification_measured: false`. Four independent audits have flagged it, which means the original deferral is not being honoured in practice. Any change must amend the `AGENTS.md` invariant in the same commit. |
| `OE-07` | RISK | Four NSE India tables have no producer, no fetcher and no caller. The decision is a **product** one: land the NSE fetcher (the `p1-bfinance-0.2.0` programme has scoped it) or remove the four tables, their stats registration and the `/dashboard/india-flows` route. An empty table registered in a stats map is worse than an absent one, because it looks maintained. |
| `INF-19` | RISK | `production-images` declares `environment: production` and a live URL for a job that pushes images and stops. Either wire `deploy.sh` into a job or remove the `environment:`/`url:` block so it stops implying a rollout. A **semantic** change to what the pipeline claims to do — do not delete `deploy.sh`; its refusal of mutable tags at `:51-52` is the reference implementation. |
| `INF-20` | RISK | Adding `error::RuntimeWarning` is deliberately **staged**, because it will turn the suite red wherever a `RuntimeWarning` is currently tolerated. That redness is the intended discovery and must land as its own commit with the failures triaged — not folded into another change. |

---

## 3. What is explicitly **not** in this file

- **Anything from `LEDGER.md` §1–§4.** Those are defects and they are counted there.
- **Any inherited claim that failed re-verification.** Those are in `rejected.md`, with the reason.
- **Any claim that could not be settled by reading.** Those are in `unverified.md`, capped at 10, each
  with a settle-command. **Quarantine is not a feature bin.** An item lands in `unverified.md` because
  it needs credentials, a runtime execution, or two genuinely ambiguous code paths — not because it is
  more comfortable here.
- **Any magnitude.** "About 20 sites deliberately preserve a missing value" is the one count quoted in
  this file, and it is quoted from the cross-cutting inventory, not measured by this run.

---

## 4. Mechanical check

Every row in §1 carries the literal label **`non-defect`** in its `class` cell. **None of them appears
anywhere in `LEDGER.md` or in `open.json`.** §2 is explicitly marked as *not* excluded from the band
totals and *not* re-counted; it exists so that "this is a decision, not a bug" is visible without
double-counting it.

| check | result |
|---|---|
| rows in §1 labelled `non-defect` | 15 / 15 |
| §1 rows present in `LEDGER.md` | 0 |
| §1 rows present in `open.json` | 0 |
| §1 rows counted in any band total | 0 |