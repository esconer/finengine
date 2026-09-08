# 15 — Phase 2 truthful disclosure

Status: pending | Pri: P1 | Blocked by: 13

## Change

- `holdings.py::holding_coverage`: `truncated = intersection_start >
  requested_start`; add `intersection_start` (newest) + per-ticker
  `{effective_start, raw_days, masked_days}` (raw from pre-mask dict).
- Warning copy, three cases per ticker: (a) intersection truncation —
  "realized P&L covers Nd since <intersection>; <ticker> held since <own>,
  instrument risk uses full <M>d"; (b) genuine short feed (raw < 30d) —
  keep exchange-feeds copy; (c) wiped — existing copy.
- Frontend (realized-risk): collapse 14 bullets → one summary banner +
  expandable per-ticker detail; show `{intersection · raw span}`.

## Tests

Coverage unit tests (staggered buys → truncated=True + intersection);
endpoint test asserting case-(a) copy on a staggered book and case-(b)
copy on a 10-day-feed ticker; frontend banner test.

## Acceptance

Live book shows case-(a) copy with the true intersection date; NIFTYIETF
(if genuinely short feed) shows case-(b).
