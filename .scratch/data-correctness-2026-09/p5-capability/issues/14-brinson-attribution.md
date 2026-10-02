# 14 — Brinson-Hood-Beebower attribution

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: 07, Phase 3 issue 27
Repo: `backend/`
Effort: S/M | Score: 32

## What

The tear sheet compares to NIFTY but never says **why** the difference exists. Add standard
attribution.

| Component | Brinson-Hood-Beebower (1986) | Brinson-Fachler (1985) |
|---|---|---|
| Allocation | `Σ(w_p − w_b)(R_b,i − R_b) | Σ(w_p − w_b)(R_b,i − R_b) |
| Selection | `Σw_b,i(R_p,i − R_b,i) | Σw_b,i(R_b,i − R_b)(R_p,i − R_b,i)` |
| Interaction | `Σ(w_p − w_b)(R_p,i − R_b,i)` | `Σ(w_p − w_b)(R_p,i − R_b,i)` |

Both sum to active return. Report both, side by side.

## Why

**"Why did I underperform?"** is the question every benchmarked investor asks, and the app can
answer it at the sector level and nothing finer.

Brinson attribution is *the* standard answer, and it is a closed-form decomposition of a number the
app already computes. It is unusually interpretable: allocation says "you were in the wrong
sectors", selection says "you picked worse stocks within sectors", interaction says "your overweight
and your picks compounded".

Needs, from the blocked-on issues:

- **Issue 07** — sector returns, to attribute at the sector level.
- **Phase 3 issue 27** — the **Total Return** benchmark. Brinson against a price index would
  attribute the benchmark's dividend gap to the user's sectors, which is nonsense.
- **Phase 1 issue 18** — constituent weights, for the benchmark side of the decomposition.

## Change

- Sector-level Brinson-Hood-Beebower and Brinson-Fachler, summing to active return.
- Multi-period linking if the user selects a long window. Single-period decomposition does **not**
  compound correctly across periods — the linking convention must be stated. Basel-Leerink and
  Ortec both publish multi-period linking rules; NeoXam describes the return-linking conventions
  used in practice.
- A position-level drill-down from each sector, so allocation and selection can be traced to
  specific holdings.
- Reuse the existing sector rollup pattern from the risk-contribution page so the presentation is
  consistent.

## Proof of done

- [ ] Allocation + Selection + Interaction sums to active return, within tolerance. **This is the
      key correctness test** — it is an identity, not a statistic.
- [ ] BHB and BF are both reported and both sum correctly. A test asserts the difference between
      them appears only in the selection term.
- [ ] An **equal-weight portfolio identical to the benchmark** produces near-zero active return and
      near-zero attribution in every component. This is the control case.
- [ ] The benchmark is Total Return, and the response states the index vintage.
- [ ] A single-period window is attributed correctly. A multi-period window uses a **stated**
      linking convention and a test validates it against a hand-worked example.
- [ ] Sector with insufficient data is excluded with a reason, and the excluded weight is
      disclosed so the components still reconcile to active return over the covered universe.
- [ ] The frontend renders the decomposition with the existing sector rollup pattern, plus
      `N/A` states.

## Notes

The **reconciliation test** is the one that matters. An attribution that does not sum to the
active return it is explaining is worse than none, because it appears to account for the
difference while quietly losing some of it. Assert the identity on every response.

For the multi-period case, prefer to **state the linking convention explicitly** rather than
silently applying one. NeoXam's note that "linked multi-period level, consistent with the return-
linking conventions used in PBOR" is the right standard to cite.

Refs: `../spec.md`, Phase 5 issues 03, 07, Phase 3 issue 27, Phase 1 issue 18
