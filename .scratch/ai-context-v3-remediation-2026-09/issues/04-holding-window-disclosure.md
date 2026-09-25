# 04: Correct holding-window and per-position disclosure

**What to build:** Make realized analytics distinguish stored holding dates from buy-price-inferred effective starts, and ensure every position's warnings, limited-history flags, observation counts, and annualization gates use that position's own measured history.

**Blocked by:** 01: Normalize the AI export contract

**Status:** ready-for-agent

- [ ] Stored added-on dates and inferred analytics starts have separate, explicit provenance labels.
- [ ] User-facing warnings say “inferred analytics start” rather than claiming a holding date that was never stored.
- [ ] Per-position limited-history flags and warnings use the position's own return observations, not portfolio/global counts.
- [ ] Full-history instrument metrics remain available but cannot overwrite or excuse the short holding-window status.
- [ ] Realized Risk, summary, dashboard, and Tear Sheet expose consistent per-position history semantics.
- [ ] Regression tests cover imported holdings whose buy price predates `added_on` and late-listed ETF histories.
