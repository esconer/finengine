# 03: Make volatility sizing safe to interpret and execute

**What to build:** Deliver volatility-sizing targets whose weights, financing requirements, trade amounts, integer share instructions, price basis, freshness, and history window form one executable and auditable contract.

**Blocked by:** 01: Normalize the AI export contract

**Closes:** V3-03, V3-04, execution-normalization portion of V3-12

**Evidence:** recommended weights sum to 1.290041; net trades buy INR 12,648.30; eight share deltas are zero despite large amounts; no sizing price/as-of.

**Work area:** Volatility-sizing engine contract, the shared execution-normalization rule consumed by rebalance/optimizer, sizing price/date evidence, volatility-sizing UI, and dedicated tests.

**bfinance gate:** No bfinance edits. Missing sizing data must be `unavailable` or explicitly `fallback`; never assume a price or market cap. If bfinance must change, stop and request explicit approval through a written proposal.

**Status:** ready-for-agent

- [ ] Executable recommended weights obey one documented normalization rule shared with the rebalance workflow.
- [ ] A leveraged analytical target reports `gross_exposure`, `financing_requirement`, `execution_eligible`, and the reason it is not a normal rebalance; it never reports zero cash for 129% risky weights.
- [ ] Trade amount and integer share delta reconcile using one exported `sizing_price` and `sizing_price_as_of`; a regression fixture proves the reconciliation.
- [ ] Share rounding follows a documented rule; material sub-lot trades are reported as below minimum/notional rather than silently becoming zero shares.
- [ ] The old `full_universe` blanket weight claim is removed from this section.
- [ ] Volatility sizing exports its actual history window, observation count, latest observation, currency, and minimum-sample status.
- [ ] Backend and frontend regression tests prevent applying an unsupported leveraged target as a normal rebalance.
