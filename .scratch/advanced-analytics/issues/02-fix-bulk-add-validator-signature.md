# 02 — Fix bulk_add validator signature bug

Status: resolved (2026-08-25)
Type: task
Blocked by: —

## Resolution
Dropped the stray `self` param on module-level `_validate_portfolio_position`
(`portfolio.py`). Regression test `test_bulk_add_positions_success` posts two valid positions and
asserts `added == 2, failed == 0`.

## What
`backend/app/api/portfolio.py:475` defines `_validate_portfolio_position(self, position)` as a
module-level function with two params, but line 362 calls it with one arg:
`_validate_portfolio_position(position)`. The TypeError is swallowed by the per-position try/except,
so every position in a bulk add likely lands in `failed_positions`.

Fix: drop the `self` param (it's not in a class). Add a regression test that bulk-adds two valid
positions and asserts `added == 2`.

## Why
Bulk add is a headline feature; it is probably 100% broken right now despite docs claiming otherwise.

## Proof of done
- [ ] POST `/portfolio/bulk_add` with 2 valid tickers returns `added: 2, failed: 0`.
- [ ] New pytest covers the happy path.
