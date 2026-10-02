# 17 — Liquidity-adjusted VaR

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: —
Repo: `backend/`
Effort: M | Score: 24

## What

The app computes ADV, days-to-liquidate at 10%/20% participation, Amihud illiquidity, and a
max-sane-value cap — and **never joins any of them to the risk number.**

L-VaR is VaR over the **liquidation horizon**, incorporating market impact:

> *"the minimum VaR of any static liquidation strategy … depends on the time to liquidation and on
> the confidence level chosen, in addition to market parameters such as the impact coefficient"*
> — Almgren & Chriss, *Optimal Execution of Portfolio Transactions*, J. Risk 3(2), 2000

## Why

**VaR assumes instantaneous liquidation at the current price, which is false for a position that
takes nine days to exit.**

The gap between the two is where the real risk lives for a concentrated book. "This 8% position is
worth 14% of your VaR once you account for the fact that you cannot sell it" is a materially
different statement from "this position is 8% of your portfolio".

The Almgren-Chriss framework also gives a **temporary vs permanent impact decomposition** and an
optimal execution schedule, which is directly actionable for a position you do need to trim.

## The honest difficulty

**Daily bars cannot identify market impact.** Impact is fundamentally an intraday phenomenon, and
the app has daily data.

Three options, in descending order of preference:

1. **Ingest intraday bars** for the positions being analysed. Accurate, but the anti-bot cost is
   high — `/api/quote-equity` returns 403 from datacenter IPs (see the Phase 4 spec).
2. **Calibrate on ADV/turnover** — assume impact scales with participation rate. Weaker, but
   defensible and honest about its assumptions.
3. **Report L-VaR as a range** under several participation assumptions rather than a point estimate.
   Cheapest, and arguably the most honest.

**Recommend option 3 now, option 1 later if it proves valuable.** A point estimate from daily bars
would be exactly the kind of fake precision this spec exists to eliminate.

## Change

- L-VaR at a chosen participation rate and confidence, computed on the liquidation horizon.
- Report the **assumed impact model explicitly**, with its parameters in the response. If the model
  is "participation-scaled", say that.
- Report a **range** across participation assumptions (e.g. 5%, 10%, 20%) rather than a single
  number, unless a calibrated model is available.
- Report the **temporary/permanent impact split** and an indicative execution schedule from
  Almgren-Chriss.
- Report L-VaR **alongside** conventional VaR, not instead of it. They answer different questions:
  VaR is "how much can I lose", L-VaR is "how much can I lose given that I must also trade".

## Proof of done

- [ ] L-VaR is validated against a hand-computed Almgren-Chriss example.
- [ ] L-VaR ≥ conventional VaR for a position with material liquidity constraint. A test asserts
      the ordering, which is a property, not a coincidence.
- [ ] The impact model and its parameters are published in the response.
- [ ] A **range** across participation rates is reported, not a single point estimate, unless a
      calibrated model is in use.
- [ ] The response states that daily bars cannot identify impact, and what that means for the
      estimate's reliability.
- [ ] A position that is fully liquid (near-zero liquidation days) has L-VaR ≈ VaR within
      tolerance. This is the control case.
- [ ] The execution schedule is indicative and labelled as such, not presented as an executable
      instruction.
- [ ] `None` with a reason when ADV is unavailable or the position exceeds the max-sane-value cap.

## Notes

Amihud illiquidity from Phase 4 issue 09 is a natural input to the impact calibration, since it is
computed on real `TtlTrfVal` rather than reconstructed turnover.

Be careful with the framing. The app is an **analytics terminal**, not a trading execution system.
The execution schedule is illustrative. Presenting it as an order-routing recommendation would be
overclaiming.

Refs: `../spec.md`, Phase 4 issue 09, Phase 3 issue 16
