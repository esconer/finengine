# 13 — Tax-aware rebalancing and tax lot accounting (India)

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: 12
Repo: `backend/`
Effort: M | Score: 36

## What

Make `/portfolio/rebalance` tax-aware. Today it emits a mechanically correct but tax-indifferent
trade list.

## The Indian rules that matter

| Rule | Detail |
|---|---|
| **STCG** | Short-term capital gain, holding < 12 months, **20%** |
| **LTCG** | Long-term, holding > 12 months, **12.5%** |
| **LTCG exemption** | First **₹1.25 lakh** of LTCG is exempt per year |
| **§87A rebate** | Resident individual, total income ≤ ₹5 lakh → rebate up to ₹12,500. Under 115BAC(1A) with income ≤ ₹12 lakh → up to ₹60,000. **Special-rate gains are ineligible** |
| **STCL offset** | Short-term capital loss offsets **both** STCG and LTCG |
| **LTCL offset** | Long-term capital loss offsets **only** LTCG |
| **Carry forward** | 8 years |
| **Harvesting** | Buying back a loss position to crystallise a loss against a gain is a legitimate, distinct strategy |
| **Turnover** | STT, stamp duty, GST — Phase 1 issue 16's `bfinance.costs` |

## Why

**For an Indian long-only retail book, tax dominates the rebalancing decision by an order of
magnitude more than tracking error does.**

Consider a position with 8% unrealised gain, held 4 months. Selling it realises STCG at 20% —
roughly 1.6% of the position, before counting the gain. A 0.5% tracking-error improvement, which is
the entire analytical output of issue 03, is smaller than the tax cost of getting the trade wrong.

So the current rebalancer can recommend a trade that is **arithmetically optimal and
financially wrong**, and it has no way to know.

Screener.in, Zerodha, and Groww all show tax *after the fact*. **None of them show you a
risk-aware, tax-aware rebalance.** That is a clean, defensible extension of the "not on free sites"
filter, and it is blocked on exactly one schema change.

## Change

- Compute, for each proposed trade: realised gain, holding period, applicable rate, tax payable,
  loss harvested or offset, and the **after-tax** expected return.
- Report **after-tax** metrics for every rebalance option, not just the raw ones. Two rebalance
  paths can have identical pre-tax risk and very different after-tax outcomes.
- Model the §87A and 115BAC(1A) rebates, and **respect that special-rate gains are ineligible**.
- Add a **harvesting** mode: identify loss positions whose sale would generate an offsettable loss,
  and show that as a distinct, labelled opportunity. It is a real strategy, not a rounding error.
- Weight the objective: a rebalance that improves tracking error by 0.1% but triggers ₹40,000 of
  tax is worse than doing nothing. Make the tax term explicit in the objective, and let the user
  set their own trade-off.
- Consult Phase 1 issue 16's `bfinance.costs` for transaction costs, not a flat bps constant.

## Proof of done

- [ ] Realised gain, holding period, applicable rate, and tax payable are computed per trade and
      validated against hand-worked examples covering all three cases: LTCG within the exemption,
      LTCG exceeding it, and STCG.
- [ ] §87A and 115BAC(1A) rebates are applied, and the **ineligibility of special-rate gains is
      respected**. A test asserts a large LTCG is not reduced by the rebate.
- [ ] STCL offsets both STCG and LTCG; LTCL offsets only LTCG. A test covers each direction.
- [ ] Loss carry-forward expires after 8 years. A test uses a lot from 9 years ago.
- [ ] **After-tax** metrics are reported for every option, and the before/after difference is
      visible.
- [ ] A rebalance that would trigger material tax is visibly flagged, with the tax amount shown.
- [ ] Harvesting opportunities are identified and labelled as such, and are distinguishable from
      ordinary rebalance trades.
- [ ] The user's tax-rate configuration is used, not a hardcoded rate. Indian rates change with each
      Finance Act — a hardcoded 12.5% will be wrong eventually.
- [ ] Transaction costs come from `bfinance.costs`, versioned by date.
- [ ] A user with **no** unrealised gains anywhere sees a clear "no tax consequence" state, not a
      zero-tax-cost rendering that implies a computation happened.

## Notes

Do not compute tax yourself as a tax advisor would. Compute the **tax consequence of a trade** from
the ledger, show it alongside the risk consequence, and let the user decide. That is a
risk-analytical product, not a tax product.

The configuration should be date-versioned for the same reason `bfinance.costs` is: LTCG rates and
exemption limits have changed repeatedly, and a hardcoded constant will silently become wrong.

Refs: `../spec.md`, Phase 5 issues 03, 06, 12, Phase 1 issue 16
