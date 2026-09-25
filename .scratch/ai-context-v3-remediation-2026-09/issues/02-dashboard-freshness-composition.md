# 02: Make dashboard history fresh and components canonical

**What to build:** Make the dashboard AI component disclose the exact delivered performance window and freshness, reuse available sibling forecast/liquidity results in its summary, and avoid presenting an unmeasured risk-score delta as zero.

**Blocked by:** 01: Normalize the AI export contract

**Status:** ready-for-agent

- [ ] Performance history exposes requested and delivered date ranges, observation counts, first/last observation, and truncation/staleness status.
- [ ] A performance series materially shorter or stale relative to its request is partial, with a warning and non-empty as-of semantics.
- [ ] Dashboard as-of is not inherited from an unrelated portfolio quote when a component has a different observation date.
- [ ] Summary forecast and liquidity fields link to canonical sibling results or include machine-readable field-level unavailable reasons.
- [ ] Risk-score change is null/unavailable unless genuinely calculated.
- [ ] Dashboard tests prove canonical component reuse and honest freshness behavior.
