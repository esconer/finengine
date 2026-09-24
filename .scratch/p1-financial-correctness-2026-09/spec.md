# P1 Financial Correctness Remediation

Status: active

## Goal

Fix the highest-confidence financial and data-contract defects from the browser audit without speculative model redesign. Preserve user changes in the already-dirty working tree and keep changes surgical.

## Scope

- One declared base currency for portfolio cost, current value, P&L, weights, liquidity limits, and Monte Carlo starting value.
- Explicit native/base position value and currency provenance.
- Quote scale/currency sanity checks and ticker region/currency inference.
- Canonical HHI diversification and honest empty/unavailable states.
- Explicit unavailable forecast responses instead of plausible fallback constants.
- Focused regression tests and isolated-stack verification.

## Non-goals

- No broad analytics-engine rewrite.
- No invented historical FX, quote provider identity, or model parameters.
- No changes to live ports 3000/8000 or production data.
- No unrelated UI cleanup.

## Definition of done

- Each issue has a regression test that fails before the fix or documents an existing reproduction.
- Focused backend/frontend gates pass.
- Synthetic isolated fixture reconciles after the patch.
- No new console errors or duplicate mutation requests in the affected workflows.
- Final diff is reviewed against the dirty-tree baseline and no unrelated files are changed.
