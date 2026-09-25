# 03: Make volatility sizing safe to interpret and execute

**What to build:** Deliver volatility-sizing targets whose weights, financing requirements, trade amounts, integer share instructions, price basis, freshness, and history window form one executable and auditable contract.

**Blocked by:** 01: Normalize the AI export contract

**Closes:** V3-03, V3-04, execution-normalization portion of V3-12

**Evidence:** recommended weights sum to 1.290041; net trades buy INR 12,648.30; eight share deltas are zero despite large amounts; no sizing price/as-of.

**Work area:** Volatility-sizing engine contract, the shared execution-normalization rule consumed by rebalance/optimizer, sizing price/date evidence, volatility-sizing UI, and dedicated tests.

**bfinance gate:** No bfinance edits. Missing sizing data must be `unavailable` or explicitly `fallback`; never assume a price or market cap. If bfinance must change, stop and request explicit approval through a written proposal.

**Blocked by:** 01: Normalize the AI export contract (shared contract only; the engine/rebalance helper wave below can start immediately)

**Status:** claimed

## Comments

### Wave 1 (engine + shared rule) landed

`backend/app/utils/allocations.py` is the single normalization rule
(`WEIGHT_NORMALIZATION_RULE = "divide_all_legs_by_gross_exposure"`) with
`fully_funded` / `financed_gross_exposure_exceeds_100_percent` /
`unlevered_long_only_plus_cash` / `empty_target` modes.
`analytics_engine.volatility_sizing` now returns `execution`, `exposure`,
`sizing_basis`, `sizing_history` and half-up trade instructions with
`rounding_residual`; the fabricated `100.0` price fallback is gone.
`rebalance_portfolio` consumes the same rule and now **rejects** gross > 1 with
HTTP 400 instead of silently normalizing a 129 % target down to 100 %.

**Regression risk this created (must be closed before this ticket is done):**
`frontend/src/app/dashboard/volatility-sizing/page.tsx` called
`rebalancePortfolio(recommended_weights)` unconditionally, so a leveraged book
would now surface a raw 400. Route integration and the UI execution gate are
dispatched as the current wave.

**Verification:** 39 new tests (15 engine + 24 normalization), 294-test focused
regression set green, full backend suite 737 passed / 7 failed (the 6 documented
pre-existing failures plus `tests/integration/test_compose_services.py::test_published_backend_and_frontend`,
which needs a live localhost service and touches nothing changed here).

- [ ] Executable recommended weights obey one documented normalization rule shared with the rebalance workflow.
- [ ] A leveraged analytical target reports `gross_exposure`, `financing_requirement`, `execution_eligible`, and the reason it is not a normal rebalance; it never reports zero cash for 129% risky weights.
- [ ] Trade amount and integer share delta reconcile using one exported `sizing_price` and `sizing_price_as_of`; a regression fixture proves the reconciliation.
- [ ] Share rounding follows a documented rule; material sub-lot trades are reported as below minimum/notional rather than silently becoming zero shares.
- [ ] The old `full_universe` blanket weight claim is removed from this section.
- [ ] Volatility sizing exports its actual history window, observation count, latest observation, currency, and minimum-sample status.
- [ ] Backend and frontend regression tests prevent applying an unsupported leveraged target as a normal rebalance.
