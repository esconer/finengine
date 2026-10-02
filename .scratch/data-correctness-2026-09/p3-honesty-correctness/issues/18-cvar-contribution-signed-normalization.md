# 18 — CVaR risk-contribution shares do not sum to 1

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `backend/`
Severity: **MEDIUM**

## What

`analytics.py:6075-6077` normalises CVaR contributions by `sum(abs(c))`. The sibling volatility
model at `:6040-6042` normalises by the **signed** `contrib.sum()`.

The contract block at `:850-856` and the contract comment at `:880-885` state:
> *"dimensionless SHARES of total portfolio risk, normalized to 1 … publish as 0.999998 …
> `rounding_residual`"*

## Why

If any asset has a **positive** mean tail-day contribution — an asset that rallies on the
portfolio's worst days, which is what a genuine hedge does — then `Σ|c| > |Σc|`, so the shares sum
to **less than 1** by a real amount.

The structural shortfall is then published as `rounding_residual`, which frames a genuine hedge
offset as 6-decimal float noise.

The sector rollup at `:6083-6089` inherits the same non-unit total, so sector shares are also
wrong by the same factor.

## Trigger

Any book containing a genuine diversifying asset — a gold ETF, a short-vol leg, a low-beta
holding. Routine, not exotic.

## Change

- Normalise by the **signed** total, matching the volatility leg at `:6041`.
- Report the hedge offset as its own named field, not folded into `rounding_residual`. Something
  like `hedge_offset_pct` with an explanation, or a separate `gross_contribution` alongside
  `net_contribution`.
- Document the distinction in the contract block. Gross and net risk attribution answer different
  questions, and conflating them is the underlying error.

## Proof of done

- [ ] For a book with a genuine hedge, the CVaR shares sum to 1 (within float tolerance) and the
      hedge offset appears in its own field. A test constructs such a book.
- [ ] For a book with no hedge, behaviour matches the current output. A test confirms no
      regression on the simple case.
- [ ] `rounding_residual` reflects only float noise, and is absent when it is exactly zero.
- [ ] The sector rollup sums to 1 for the same inputs.
- [ ] The contract block at `:850-856` and `:880-885` documents gross vs net attribution.
- [ ] The frontend renders the new field. A component test asserts the hedge case displays.
- [ ] Add to `test_quantitative_invariants.py`.

## Notes

This is the risk-contribution page, which is one of the app's strongest analytical contributions.
Getting the normalisation wrong there is more damaging than the raw number being slightly off,
because a reader uses the shares to make allocation decisions.

Refs: `../spec.md`, `backend/app/api/analytics.py:850-856,880-885,6040-6042,6075-6077,6083-6089`
