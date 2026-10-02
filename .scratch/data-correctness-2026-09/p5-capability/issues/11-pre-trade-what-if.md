# 11 — Pre-trade what-if incremental risk check

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: 12
Repo: `backend/`
Effort: M | Score: 28

## What

Answer: *"If I add ₹2L of X, what happens to VaR, ES, HHI, sector weight, tracking error, and days to
liquidate?"*

The app has the risk engine **and** the rebalancer. Nothing joins them. Today every analytics call
reads `PortfolioPosition` rows directly, so scoring a hypothetical book requires threading a
parameter through the whole chain.

## Why

This is the last step from "a terminal that reports" to "a terminal that advises", and it is the
functionality that makes issue 12's rebalancer genuinely decision-grade rather than mechanically
correct.

Professional pre-trade systems (Trading Technologies SPAN/PRISMA, Redline PTR, Opensee) all do
this. The core concept is **Incremental VaR** — the difference in portfolio VaR with and without a
given trade.

One important caveat, straight from the literature: **like VaR, the sum of incremental VaRs does not
sum to the overall VaR.** That is a property of the measure, not a bug. Do not present incremental
contributions as if they were additive.

## Change

- Thread a `hypothetical_positions` (or `scenario`) parameter through the analytics chain, so the
  engine can be evaluated against a book that is not yet in the database.
- **Design this as a general seam, not a one-off.** The same parameter serves issue 12's ledger
  replay, issue 13's tax-aware rebalancing, and issue 16's snapshots. Getting this seam right is
  worth more than any single feature on it.
- A `POST /analytics/what-if` endpoint accepting a proposed trade (or list of trades) and returning
  the full metric delta: VaR, ES, vol, HHI, effective positions, sector weights, tracking error,
  days-to-liquidate, and each risk budget from issue 06.
- Show **deltas**, not just post-trade levels. The user asked "what changes", not "what is".
- Pre-trade limit checks from issue 06 run on the hypothetical book, and a breach is flagged
  **before** the trade, which is the entire point.

## Proof of done

- [ ] The seam is general: a hypothetical book can be evaluated by every analytics endpoint, not
      just the new one. A test evaluates the same book via the parameter and via a temporary
      database state and asserts identical results.
- [ ] Every metric returns `before`, `after`, and `delta`.
- [ ] Incremental VaR's non-additivity is documented in the response, so a consumer does not sum
      the parts.
- [ ] A proposed trade that breaches a limit from issue 06 is flagged, with the breached limit
      named.
- [ ] An infeasible proposed trade (insufficient cash, invalid quantity) returns a clear error,
      not a computed result.
- [ ] A trade of zero quantity returns the current book unchanged, with zero deltas.
- [ ] The response declares units for every metric and states the evaluation basis.

## Notes

The seam is the real deliverable. Every future feature that needs "what if" — the ledger's
point-in-time replay, tax-aware rebalancing, historical what-if grids, stress testing a candidate
book — depends on it. Design it as a first-class input to the analytics layer rather than a
parameter on one endpoint.

Blocked on issue 12, because the ledger gives the seam a natural home: a scenario is just a
hypothetical set of transactions.

Refs: `../spec.md`, Phase 5 issues 06, 12, 13, 16
