# 07: Clarify optimizer, simulation, regime, and pairs semantics

**What to build:** Make optimization, Monte Carlo, regime, and pairs outputs independently auditable by exposing their actual samples, units, probability meanings, percentage units, and uneven pair-history limitations.

**Blocked by:** 01: Normalize the AI export contract

**Status:** ready-for-agent

- [ ] Optimizer exports risk-free rate, model window, observation count, latest input date, and execution-normalized weight/delta guidance.
- [ ] Monte Carlo exports currency, model as-of/history evidence, and explicit success semantics (terminal versus path-touch).
- [ ] Regime probability and transition fields declare percentage units and identify the NIFTY benchmark/model basis.
- [ ] Pairs reports per-ticker observation-depth coverage and becomes partial when materially fewer usable observations exist, especially for late-listed assets.
- [ ] Dual-test semantics clearly state that the published decision uses Engle–Granger while Johansen is diagnostic.
- [ ] Regression tests cover terminal-success labeling, regime percentages, and uneven NIFTYIETF overlap.
