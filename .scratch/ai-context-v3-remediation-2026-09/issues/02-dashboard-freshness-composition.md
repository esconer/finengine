# 02: Make dashboard history fresh and components canonical

**What to build:** Make the dashboard AI component disclose the exact delivered performance window and freshness, reuse available sibling forecast/liquidity results in its summary, and avoid presenting an unmeasured risk-score delta as zero.

**Blocked by:** 01: Normalize the AI export contract; 04: Correct holding-window and per-position disclosure

**Closes:** V3-02, V3-07, dashboard/portfolio/summary portion of V3-17

**Evidence:** `performance_days=90` versus 20 rows ending 2026-09-22 with dashboard `as_of=2026-09-25`; summary forecast/liquidity nulls beside available siblings; `risk_score.change=0`.

**Work area:** Performance-history coverage/freshness, dashboard component composition/as-of map, summary canonical linking, Risk Score delta, and dashboard tests/UI. Do not redefine shared status/coverage helpers owned by ticket 01.

**bfinance gate:** No bfinance edits. Truncated history must be disclosed or marked unavailable; never backfill or paper over a source gap. If bfinance must change, stop and request explicit approval through a written proposal.

**Status:** ready-for-agent

- [ ] Performance history exposes requested and delivered date ranges, observation counts, first/last observation, and truncation/staleness status.
- [ ] A numeric freshness rule marks a series partial when it is materially shorter than requested or its last observation is stale; the rule and threshold are documented.
- [ ] Per-component `as_of`/`as_of_semantics` are exposed; dashboard-level as-of is not inherited from an unrelated portfolio quote when components differ.
- [ ] Summary forecast and liquidity fields link to canonical sibling results or include machine-readable field-level unavailable reasons.
- [ ] Risk-score change is null/omitted and the UI renders unavailable, never an unchanged zero, unless genuinely calculated.
- [ ] Dashboard tests prove canonical component reuse and honest freshness behavior; portfolio/summary sections either receive explicit window evidence or are recorded as verified no-change.
