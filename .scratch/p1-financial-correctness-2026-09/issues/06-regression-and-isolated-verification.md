# 06 — Focused regression and isolated-stack verification

Status: ready-for-human
Type: task
Priority: P1
Owner: main thread
Blocked by: 01-currency-contract-and-pnl, 02-quote-sanity-and-region-inference, 03-canonical-diversification-and-liquidity, 04-forecast-fallback-unavailable, 05-frontend-state-and-empty-contracts

## Scope

- Run focused backend pytest and frontend tests for each changed seam.
- Rebuild/restart only the isolated 3001/8001 stack with the synthetic fixture.
- Re-run portfolio/FX reconciliation and affected browser/API workflows.
- Verify no live 3000/8000 mutation, no temporary positions, and no new secrets/artifacts outside the audit tree.
- Record remaining `UNVERIFIABLE` items rather than broadening the patch.

## Verification progress

- Focused backend contract/service tests: 123 passed.
- Full frontend suite: 181 passed; TypeScript: 0 errors.
- Isolated `8001` API + `3001` browser stack verified the five-position synthetic fixture, INR/USD P&L conversion, canonical concentration, empty-state contracts, quote/region rejection, and one-request-per-endpoint behavior.
- Full backend suite in the heavily dirty tree has 10 failures outside the focused remediation seams (including the live compose-service check); they were not changed or treated as part of this patch.
- Final isolated smoke: five canonical positions, INR total `410449.80`, USD total `4277.97`, AAPL native/base `1679.60`/`161149.23`, concentration `77.6%`, liquidity base `410449.80 INR`, quote source `yfinance`, and rendered USD P&L `+$1,728.67`.

## Comments

This ticket is the final gate, not a license to refactor unrelated analytics.
