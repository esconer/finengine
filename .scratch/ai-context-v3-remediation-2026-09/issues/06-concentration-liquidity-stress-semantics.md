# 06: Correct concentration, liquidity, and stress semantics

**What to build:** Make concentration rounding exact and make liquidity and stress outputs disclose their units, estimated inputs, classification thresholds, and heuristic versus simulated meaning.

**Blocked by:** 01: Normalize the AI export contract

**Status:** ready-for-agent

- [ ] Sector weights are accumulated at full precision and rounded once, so displayed sector weights reconcile to 100% without invented redistribution.
- [ ] Liquidity score and risk band derive from the same rounded score or disclose the raw-score threshold explicitly.
- [ ] Imputed market-cap floors and other estimated liquidity inputs are marked measured/fallback/estimated per position.
- [ ] Liquidity exports currency, actual data range, observation date, and scoring methodology.
- [ ] Stress scenarios describe deterministic impact proxies accurately; proxy max drawdown and confidence are not labelled as independently simulated statistics.
- [ ] Regression tests cover the v3 rounding, SELECTIPO fallback, score boundary, and scenario semantics.
