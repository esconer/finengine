# 11 — NSE per-scrip volatility, VaR margin, and ELM

Status: ready-for-agent
Type: task
Phase: 4
Blocked by: 05
Repo: `backend/`
Severity: **MEDIUM**

## What

Ingest NSE's daily per-scrip risk parameters.

## Source

Four reports on `nseindia.com/all-reports`, all **CSV with no auth**:

| Report | Contents |
|---|---|
| CM - Daily Volatility | Per-scrip volatility used for the VaR margin |
| CM - VaR Margin Rates (Begin / 4× intra-day / End of day) | The three margin rates through the day |
| CM - Extreme Loss Margin | ELM rate, 3.5% (2% for broad-index ETFs) |
| CM - Margin Trading Disclosure | Client-wise margin |

VaR methodology: **6σ EWMA with λ=0.995**. Margin floors: **Group I min 9%, Group II min 21.5%,
Group III 50% / 75%.**

Also useful, though not the focus: `CM - Short Selling` (SLBS archives) and `CM - Client Funding`.

## Why

**The exchange's own per-scrip risk ceiling is a real, per-holding leverage capacity limit** — and
the app has no concept of one. It tells you how much the exchange will let you lever a specific
position, which is different from and complementary to how risky the position is.

It also gives a **leverage multiplier for the stress page**: a Group III name at 75% margin behaves
completely differently under a market shock than a Group I name at 9%, and the current stress
elasticities in `CONTEXT.md` §9.13 do not know that.

And **the Group classification explains the circuit band assignment** from issue 10 — Group I/II/III
maps onto the 2%/5%/20% bands. So issues 10 and 11 reinforce each other.

## Change

- Ingest the three reports.
- Store the VaR margin rate (end-of-day is the useful one; the intra-day series is for tracking
  margin calls), the ELM rate, and the computed volatility.
- Record the **effective margin requirement**: `max(VaR_margin, ELM, group_floor)`. Brokers charge
  the effective rate, not the raw VaR figure, and the difference can be large.
- Record the group classification.
- Expose as a per-holding leverage capacity, and feed the group into issue 10's band derivation.

## Proof of done

- [ ] A scrip's effective margin requirement is computed and matches the broker-observable value.
      A test uses three known scrips across different groups.
- [ ] The group classification is stored and queryable.
- [ ] The effective rate accounts for the ELM floor, not just the raw VaR rate. A test asserts a
      name where ELM is the binding constraint.
- [ ] The group feeds issue 10's band derivation consistently.
- [ ] A **short selling** metric is published as short *sell volume*, explicitly **not** as "short
      interest" — see the note below.
- [ ] A test asserts a non-trading day produces no row.
- [ ] The test uses a recorded fixture.

## The one thing to get right in the naming

**"Short interest" does not exist as a published number in India.** What exists is client-wise short
*sell volume* from the SLBS report, and F&O participant positions.

Publishing a metric called "short interest" would be a fabrication. Publish short **sell volume**
and label it precisely. This is called out explicitly in the master spec's non-goals because it is
an easy and tempting metric to add.

## Notes

The `CM - Margin Trading Disclosure` report is client-wise and is a paid product in some contexts —
verify the report is freely downloadable before building on it. The three reports above are the
ones confirmed as free public dissemination.

Refs: `../spec.md`, Phase 4 issue 05, Phase 4 issue 10, `CONTEXT.md` §9.13
