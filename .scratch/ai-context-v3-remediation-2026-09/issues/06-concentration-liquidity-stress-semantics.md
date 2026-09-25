# 06: Correct concentration, liquidity, and stress semantics

**What to build:** Make concentration rounding exact and make liquidity and stress outputs disclose their units, estimated inputs, classification thresholds, and heuristic versus simulated meaning.

**Blocked by:** 01: Normalize the AI export contract

**Closes:** V3-08, V3-09, V3-10

**Evidence:** Industrials displays 0.0984 versus exact 0.0983; SELECTIPO market cap equals the INR 1bn fallback; score 8 carries Medium band; stress drawdown is a fixed 1.15 shock proxy with hardcoded confidence.

**Work area:** Concentration accumulation, liquidity provenance/scoring disclosure, stress scenario labels, corresponding page types, and dedicated tests. Use ticket 01 status/provenance vocabularies.

**bfinance gate:** No bfinance edits. An absent market cap must remain `fallback/unavailable`; never assume one silently. If bfinance must change, stop and request explicit approval through a written proposal.

**Status:** ready-for-agent

- [ ] Sector weights are accumulated at full precision and rounded once; a test asserts the published total is 1.0 within 1e-9 and any residual is explicit.
- [ ] Public `data_status` is not copied from coverage status and uses ticket 01's vocabulary.
- [ ] Liquidity publishes the raw score, rounded score, threshold used, and derives the band from one clearly documented rule.
- [ ] Market-cap provenance is explicit per position (`quote`, `screener_fundamentals`, `price_x_shares_floor`, or `fallback`) with `is_estimate`; the SELECTIPO floor is never silent.
- [ ] Liquidity exports currency, actual data range, observation date, and monetary/turnover units.
- [ ] Stress proxy max drawdown and confidence are renamed or tagged `derived_from_shock_proxy`; methodology never implies an independent simulation.
- [ ] Regression tests cover v3 rounding, SELECTIPO fallback, score boundary, and scenario semantics.
