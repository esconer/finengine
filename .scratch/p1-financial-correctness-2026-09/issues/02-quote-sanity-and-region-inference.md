# 02 — Reject impossible quotes and infer ticker region/currency

Status: ready-for-human
Type: bug
Priority: P1
Owner: main thread
Blocked by: —

## Problem

AAPL was accepted at `$4.89` with unknown sector/industry. Add Position submitted a US ticker with `region: IN`; CSV import also hard-codes India region.

## Acceptance criteria

- Quote acceptance rejects or quarantines implausible symbol/scale/currency values with a clear error.
- Region/currency is inferred from ticker/explicit user input and is preserved through the response.
- Valid Indian and US symbols continue to work.
- Regression tests cover AAPL-scale mismatch, `.NS`/`.BO`, plain US symbols, and explicit region handling.

## Evidence

- `.scratch/backend-deep-audit/browser-e2e/backend-bugs.md`
- `.scratch/backend-deep-audit/browser-e2e/data-freshness-bugs.md`
- `.scratch/backend-deep-audit/browser-e2e/evidence/network/api-final/quote_AAPL.200.json`

## Comments

Do not invent a provider or use a live quote as a test oracle. Use deterministic scale/currency invariants and captured evidence.

### Progress

- Ticker identity now overrides stale region metadata; bare known Indian scrips infer `IN`, plain US symbols infer `US`, and contradictory explicit regions fail closed.
- bfinance is restricted to Indian listings; provider ticker/currency metadata is checked before normalization.
- CSV no longer hard-codes every row to India, and Add Position no longer assigns a bare US ticker `IN` merely because the display currency is INR.
- Deterministic regression tests cover region conflicts, bare Indian inference, AAPL/bfinance routing, and identity/currency contradictions.
