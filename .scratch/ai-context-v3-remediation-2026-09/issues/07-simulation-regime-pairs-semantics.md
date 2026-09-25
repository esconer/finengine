# 07: Clarify optimizer, simulation, regime, and pairs semantics

**What to build:** Make optimization, Monte Carlo, regime, and pairs outputs independently auditable by exposing their actual samples, units, probability meanings, percentage units, and uneven pair-history limitations.

**Blocked by:** 01: Normalize the AI export contract; 03: Make volatility sizing safe to interpret and execute; 05: Separate full-history calculations from holding context

**Closes:** V3-11, V3-12, V3-13, V3-14

**Evidence:** Monte Carlo `0.335` is terminal success with no semantics/currency/as-of; regime percentages are 0–100; pairs NIFTYIETF overlap is 106–109 versus 168–174; optimizer omits rf/history evidence.

**Work area:** Optimization history disclosure, Monte Carlo semantics, regime benchmark/percentage/posterior metadata, and pair depth/test semantics. Consume ticket 03’s execution-normalization rule and ticket 05’s history shapes.

**bfinance gate:** No bfinance edits. Missing model or benchmark history must be unavailable/partial; never simulate from fabricated observations. If bfinance must change, stop and request explicit approval through a written proposal.

**Status:** ready-for-agent

- [ ] Optimizer exports the risk-free rate actually used, model window, observation count, latest input date, and consumes ticket 03's single execution-normalization rule.
- [ ] Monte Carlo exports currency, model as-of/history observations, an annualization flag, and `success_definition: terminal_wealth_above_target` (or another explicit path definition).
- [ ] Regime identifies `^NSEI`, states whether the posterior is filtered or smoothed, and marks probability/transition values as percentage units.
- [ ] Pairs declares its universe scope (`holdings_only` or watchlist-inclusive), per-ticker usable observations, effective pair window, and dual-test roles.
- [ ] Materially short overlap makes pairs partial rather than `complete`; Johansen is labelled diagnostic-only.
- [ ] Regression tests cover terminal-success labeling, regime units, execution normalization, and uneven NIFTYIETF overlap.
