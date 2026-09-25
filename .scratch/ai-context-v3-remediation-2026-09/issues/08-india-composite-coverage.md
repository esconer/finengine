# 08: Make India composite coverage honest and complete

**What to build:** Represent the heterogeneous institutional-flow, delivery-anomaly, and portfolio-liquidity components with one coherent composite contract without implying ticker coverage or weight renormalization for market-wide flow data.

**Blocked by:** 01: Normalize the AI export contract

**Closes:** V3-15

**Evidence:** composite coverage is `unknown` and claims weight renormalization while nested liquidity coverage is 14/14; FII/DII and delivery components are unavailable; inputs omit component windows/scope.

**Work area:** India composite coverage/as-of/input aggregation, India component statuses, and India page rendering. Consume ticket 01 coverage/provenance vocabularies.

**bfinance gate:** No bfinance edits. bfinance shareholding data is not a substitute for daily FII/DII cash flows; missing flows remain unavailable. If bfinance must change, stop and request explicit approval through a written proposal.

**Status:** ready-for-agent

- [ ] Composite coverage promotes usable nested liquidity coverage and separately records unavailable flow/delivery universes.
- [ ] Market-wide FII/DII declares `scope: market_wide` and no portfolio weight basis; delivery declares the requested symbol universe explicitly.
- [ ] Composite as-of semantics explain that only the liquidity component has a current observation and expose per-component as-of dates.
- [ ] Inputs include each component's lookback, threshold, symbol universe, and scope, including the fact that liquidity is portfolio-wide.
- [ ] Missing FII/DII legs and unavailable delivery data remain explicit null/unavailable states.
- [ ] Backend and frontend tests preserve honest partial rendering without fabricated zero/no-anomaly claims.
