# 17 — Phase 4 dashboard instrument vol + diversification decimals

Status: pending | Pri: P2 | Blocked by: 13, 14

## Change

- `get_analytics_summary`: add `instrument_volatility` (+ days) computed on
  the unmasked window (same instrument-risk logic as realized-risk);
  card always shows it captioned "full-history asset vol".
- Diversification: verify rounding source of "100%", render 1 decimal.

## Tests

Summary test: staggered book → `instrument_volatility` populated while
holding `realized_volatility` stays gated; frontend test for caption.

## Acceptance

Dashboard Ann Vol card never N/A-gates on intersection length; score shows
e.g. 98.4%, not 100%.
