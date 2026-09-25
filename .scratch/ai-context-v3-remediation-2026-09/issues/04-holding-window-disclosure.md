# 04: Correct holding-window and per-position disclosure

**What to build:** Make realized analytics distinguish stored holding dates from buy-price-inferred effective starts, and ensure every position's warnings, limited-history flags, observation counts, and annualization gates use that position's own measured history.

**Blocked by:** 01: Normalize the AI export contract

**Closes:** V3-06, portfolio-level gate and Forecast/Summary portion of V3-17

**Evidence:** NIFTYIETF 20 return observations versus 39/176-day warning counts; inferred 2026-05-19 start precedes stored `added_on` 2026-06-08; generic limited-history flags disagree with position rows.

**Work area:** Holding provenance helpers and realized/summary/forecast history metadata. Dashboard composition remains owned by ticket 02.

**bfinance gate:** No bfinance edits. Pre-listing history must stay absent or be labelled inferred/limited; never backfill. If bfinance must change, stop and request explicit approval through a written proposal.

**Blocked by:** 01: Normalize the AI export contract (shared contract only; the holdings-helper/UI wave below can start immediately)

**Status:** claimed

## Comments

### Wave 1 (helpers + holding-window UI) landed

`backend/app/utils/holdings.py` gained additive provenance:
`effective_start_detail`, `analytics_start_claim`, `position_limited_history`,
`annualizable`, `position_history_note`. The intentional buy-price repair
(`min(added_on, inferred)`, 2 % tolerance, never backfilled) is preserved; only
its provenance is now published. `frontend/src/lib/historyFormat.ts` mirrors the
wording, and Realized Risk / Tear Sheet render it.

**Integrator fixes applied on review:**

1. Realized Risk per-ticker bullets printed the ticker twice
   (`• TICKER: TICKER: 20 own return observations…`) because the page prefixed
   the ticker while `perTickerDetail` also leads with it. The page now prefixes
   only when forwarding a backend `message` verbatim.
2. The new `HoldingProvenanceDisclosure` test asserted
   `not.toMatch(/NIFTYIETF\.NS.*held since/)` against the whole detail block's
   concatenated `textContent`, so the *stored* leg's legitimate "held since"
   tripped it. Scoped the assertion to each bullet element.

**Verification:** backend `test_phase2_disclosure.py` — only
`test_realized_risk_case_a_intersection_copy` fails, which is on the documented
pre-existing baseline (`masked_days 25` vs `covered_days 24`, unrelated
intersection bug). Frontend 203/203 green, `tsc` exit 0.

**Outstanding:** the route copy in `get_realized_risk` / `get_analytics_summary`
still says "held since <inferred date>"; that is the next wave once
`backend/app/api/analytics.py` is free.

- [ ] Stored `added_on`, inferred `analytics_start`, and `analytics_start_source ∈ {stored_added_on, buy_price_inferred, unknown}` are separate fields.
- [ ] User-facing warnings say “inferred analytics start” rather than claiming a holding date that was never stored.
- [ ] Per-position limited-history flags and warnings use the position's own return observations, not portfolio/global counts.
- [ ] Portfolio-level annualization gates in Forecast Risk and Summary use the portfolio's own measured return observations, not a position count.
- [ ] Full-history instrument metrics remain available but cannot overwrite or excuse the short holding-window status.
- [ ] Realized Risk, summary, dashboard, and Tear Sheet expose consistent per-position history semantics; dashboard composition itself remains owned by ticket 02.
- [ ] Regression tests cover imported holdings whose buy price predates `added_on` and late-listed ETF histories.
