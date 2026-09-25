# 03: Make volatility sizing safe to interpret and execute

**What to build:** Deliver volatility-sizing targets whose weights, financing requirements, trade amounts, integer share instructions, price basis, freshness, and history window form one executable and auditable contract.

**Blocked by:** 01: Normalize the AI export contract

**Status:** ready-for-agent

- [ ] Executable recommended weights obey the same normalization accepted by the rebalance workflow.
- [ ] A leveraged analytical target explicitly reports gross exposure, financing requirement, and execution eligibility instead of reporting zero cash for 129% risky weights.
- [ ] Trade amount and integer share delta reconcile using an exported sizing price and price as-of date.
- [ ] Share rounding follows one documented rule and cannot silently turn material trades into zero shares.
- [ ] Volatility sizing exports its actual history window, observation count, latest observation, currency, and minimum-sample status.
- [ ] Backend and frontend regression tests prevent applying an unsupported leveraged target as a normal rebalance.
