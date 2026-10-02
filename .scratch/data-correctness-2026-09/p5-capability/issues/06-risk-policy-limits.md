# 06 — Risk policy limits layer

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: —
Repo: `backend/` + `frontend/`
Effort: S | Score: 32

## What

Let the user declare risk limits and see pass/fail against them, with a breach history.

This is a **product change**, not a model.

The app has 21 pages of metrics and **zero stated policy**. Nothing is ever "wrong". Every number is
just a number, and the user has to know which ones matter to them and what threshold to hold them
to.

## Why

SimCorp, Opensee, CME Globex, and Redline all do this. The difference is between a dashboard and a
**control system**, and it is free to build — every underlying metric already exists.

Suggested limits, all of which the app can already compute:

| Limit | Example |
|---|---|
| Max single-name weight | 15% |
| Max sector weight | 30% |
| Max 1-day VaR | 2.5% |
| Max 1-day ES | 3.5% |
| Max HHI | 0.20 |
| Max effective positions | 10 |
| Max days-to-liquidate | 5 |
| Max portfolio beta | 1.2 |
| Max drawdown | 20% |
| Max single-position risk contribution | 30% |

## Change

- A persisted limit set (user-configurable; this is single-user, so no RBAC).
- An evaluation that runs the limit checks and returns pass/fail/breach per limit.
- A **breach history** — when each limit was first and last breached. This requires snapshots
  (issue 16), so initially: current status plus a log of evaluations.
- A visible, unmissable breach state on `/dashboard`. A limit breach should be the one thing on the
  main page that cannot be missed.
- Settings UI for the limits.

## Proof of done

- [ ] Each limit type is evaluated and returns pass / breach / `unavailable`.
- [ ] A limit whose underlying metric is `None` (unmeasurable) returns `unavailable` with a
      reason — **never `pass`**. An unmeasurable metric must not silently satisfy a limit.
- [ ] A breach is visible on `/dashboard` without navigating.
- [ ] Breach history records the first and last breach date per limit.
- [ ] Limits are persisted and survive a restart.
- [ ] The evaluation is deterministic and unit-tested per limit type.
- [ ] A limit set with no limits configured is a valid state, and says so.

## Notes

This is the highest ratio of user value to implementation cost in Phase 5. It adds no mathematics,
it needs no new data, and it converts 21 pages of metrics into something that can actually drive a
decision.

The `unavailable` case is the important design detail. If VaR cannot be computed for a 3-stock
book, "max 1-day VaR ≤ 2.5%" must read as *unknown*, not as *passed*. Getting that wrong would make
the limits actively misleading for exactly the portfolios most likely to need them.

Refs: `../spec.md`, Phase 5 issues 01, 16
