# 16 — Phase 3 tear-sheet hierarchy inversion

Status: pending | Pri: P1 | Blocked by: 13, 14

## Change

- Headline cards ← `full_history` metrics, captioned "Full-history · N
  trading days"; headline β/α ← already-computed `full_relative`.
- Holding window demoted to a "Current book since <intersection>" section
  (Total Return, MaxDD, monthly heatmap, underwater stay holding-truthed —
  they are book-true).
- Full-history = entire cache depth (Phase 1), not per-endpoint request
  windows — ends the 251-vs-175 confusion; span disclosed in the caption.
- Backend: `get_tear_sheet` builds full-history from the unmasked dict
  (already does — repoint to cache-depth span); frontend consumes same
  `full_history` block, no contract change expected.

## Tests

Backend: headline-source test (intersection-truthed book still returns
full-history headline + holding section). Frontend: headline shows
full-history values with caption; holding section labeled with date.

## Acceptance

Live tear-sheet: no N/A headline cards on the 14-position staggered book;
both spans labeled; monthly/underwater unchanged and labeled book-true.
