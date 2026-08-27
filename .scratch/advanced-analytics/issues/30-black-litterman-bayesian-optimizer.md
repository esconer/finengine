# 30 — Black-Litterman Bayesian Portfolio Optimization

Status: ready-for-agent
Type: feature
Blocked by: 08

## What
Add the Black-Litterman model to `OptimizationService` using `cvxpy` / `scipy`:
- Implied equilibrium excess returns derived from NIFTY 50 / market cap weights ($P = \Pi$).
- Support subjective investor views:
  - Absolute view: "Stock A will return $X\%$".
  - Relative view: "Stock A will outperform Stock B by $Y\%$".
- View confidence weighting matrix ($\Omega$).
- Output posterior blended returns and optimal weights.

## Why
Allows quantitative investors to express conviction views while anchoring to market equilibrium, avoiding extreme corner solutions of pure MVO.

## Proof of done
- [ ] Black-Litterman optimization returns balanced weights reflecting input view tilts.
