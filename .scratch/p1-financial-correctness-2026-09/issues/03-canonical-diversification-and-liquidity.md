# 03 — Use canonical base-currency diversification and liquidity

Status: ready-for-human
Type: bug
Priority: P1
Owner: main thread
Blocked by: 01-currency-contract-and-pnl

## Problem

Dashboard uses a native-mixed heuristic and displays 18.7% instead of the concentration endpoint's returned-quote arithmetic (~50.5%). Liquidity limits sum native mixed values as if they were one currency.

## Acceptance criteria

- Dashboard uses the canonical HHI/effective-holdings diversification result.
- Empty portfolios render unavailable, not safe/0% diversification; N<=1 remains 0%.
- Liquidity portfolio aggregation uses the same declared base currency and reports it.
- Regression tests cover empty, single-holding, and mixed-currency cases.

## Evidence

- `.scratch/backend-deep-audit/browser-e2e/financial-reconciliation.md`
- `.scratch/backend-deep-audit/browser-e2e/backend-bugs.md`
- `.scratch/backend-deep-audit/browser-e2e/evidence/calculations/outputs/independent-core-models.md`

## Comments

Do not change concentration policy thresholds without an explicit product decision; fix the data basis and canonical arithmetic first.

### Progress

- Dashboard now consumes `concentration.diversification_score` from the analytics response instead of recomputing from native values.
- N≤1 remains 0%; missing canonical data renders N/A.
- Red/green proof: `DashboardPhase4.test.tsx` failed with the old heuristic and passes after the patch; focused related tests and TypeScript pass.
- Liquidity service/API now receives converted position values and FX rates, reports base/native units, and converts traded-value denominators consistently.
- Empty portfolio is N/A on Dashboard; N=1 remains 0%; backend empty analytics responses now carry `zero_metrics` for the UI contract.
- Focused service/API and frontend tests pass; isolated browser reconciliation confirms canonical concentration and base-currency liquidity.
