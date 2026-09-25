# 04: Correct holding-window and per-position disclosure

**What to build:** Make realized analytics distinguish stored holding dates from buy-price-inferred effective starts, and ensure every position's warnings, limited-history flags, observation counts, and annualization gates use that position's own measured history.

**Blocked by:** 01: Normalize the AI export contract

**Closes:** V3-06, portfolio-level gate and Forecast/Summary portion of V3-17

**Evidence:** NIFTYIETF 20 return observations versus 39/176-day warning counts; inferred 2026-05-19 start precedes stored `added_on` 2026-06-08; generic limited-history flags disagree with position rows.

**Work area:** Holding provenance helpers and realized/summary/forecast history metadata. Dashboard composition remains owned by ticket 02.

**bfinance gate:** No bfinance edits. Pre-listing history must stay absent or be labelled inferred/limited; never backfill. If bfinance must change, stop and request explicit approval through a written proposal.

**Status:** ready-for-agent

- [ ] Stored `added_on`, inferred `analytics_start`, and `analytics_start_source ∈ {stored_added_on, buy_price_inferred, unknown}` are separate fields.
- [ ] User-facing warnings say “inferred analytics start” rather than claiming a holding date that was never stored.
- [ ] Per-position limited-history flags and warnings use the position's own return observations, not portfolio/global counts.
- [ ] Portfolio-level annualization gates in Forecast Risk and Summary use the portfolio's own measured return observations, not a position count.
- [ ] Full-history instrument metrics remain available but cannot overwrite or excuse the short holding-window status.
- [ ] Realized Risk, summary, dashboard, and Tear Sheet expose consistent per-position history semantics; dashboard composition itself remains owned by ticket 02.
- [ ] Regression tests cover imported holdings whose buy price predates `added_on` and late-listed ETF histories.
