# 08: Make India composite coverage honest and complete

**What to build:** Represent the heterogeneous institutional-flow, delivery-anomaly, and portfolio-liquidity components with one coherent composite contract without implying ticker coverage or weight renormalization for market-wide flow data.

**Blocked by:** 01: Normalize the AI export contract

**Status:** ready-for-agent

- [ ] Composite coverage promotes usable nested liquidity coverage and separately records unavailable flow/delivery universes.
- [ ] Market-wide FII/DII and delivery data do not claim a portfolio-weight basis.
- [ ] Composite as-of semantics explain that only the liquidity component has a current observation.
- [ ] Inputs include each component's lookback, threshold, symbol universe, and scope.
- [ ] Missing FII/DII legs and unavailable delivery data remain explicit null/unavailable states.
- [ ] Backend and frontend tests preserve honest partial rendering without fabricated zero/no-anomaly claims.
