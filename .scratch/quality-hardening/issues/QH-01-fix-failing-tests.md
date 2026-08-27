# QH-01 — Fix 2 failing tests (conftest leak + rounding tolerance)

Status: closed
Type: task
Blocked by: —

## What

Two tests in `tests/test_advanced_analytics.py` fail:

**`test_no_positions_404`**: Receives `200` instead of `404`. Root cause: the `async_client`
fixture in `conftest.py` does `app.dependency_overrides.pop()` in teardown, but without a
`try...finally` block. If a preceding test's teardown throws, the override leaks and the
"empty portfolio" test finds stale positions from a prior test.

**`test_contributions_sum_to_one_and_ranking`**: Asserts `abs(sum(vol_rc.values()) - 1.0) < 1e-6`.
The API rounds contributions to 6dp, so `sum([0.322057, 0.209285, 0.031044, 0.437613]) = 0.999999`
and `abs(0.999999 - 1.0) = 1.0e-6` which is NOT `< 1e-6`. Off-by-one in tolerance.

## Fix

1. `conftest.py`: Wrap `dependency_overrides` assignment and pop in `try...finally`.
2. `test_advanced_analytics.py`: Widen sum-to-1 tolerance from `1e-6` to `1e-4`.

## Why

These failures block CI. Root causes are test infrastructure bugs, not product bugs.

## Proof of done
- [ ] `uv run pytest tests/test_advanced_analytics.py --no-cov` → all pass
- [ ] Full suite green (148/148)
