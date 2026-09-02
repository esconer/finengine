# Issue 02: Fix Concentration Page Invariant Violation & Purge Metric Card Fallbacks

Status: resolved
Type: task

## Description
1. In `frontend/src/app/dashboard/concentration/page.tsx`:
   - `divScore` fallback `98.3` violated AGENTS.md invariant ($N \le 1 \implies 0\%$).
2. Hardcoded mock fallbacks in MetricCards (`13.9%`, `37.7%`, `0.09`, `11.47`, `11.5`) violated metric card hygiene.

## Resolution
- Enforced `const divScore = positions.length <= 1 ? 0.0 : (concentrationData?.diversification_score ?? ...)`.
- Replaced all fake mock fallback strings with `'N/A'` or live computed values from positions.

## Verification
- Empty or 1-position portfolio shows 0.0% diversification score.
- MetricCards reflect live API values or clean 'N/A' without hardcoded mock numbers.
- `bun x tsc --noEmit` and `bun run test:run` passed.

## Comments
Resolved and verified on 2026-09-02. Quantitative bounds and metric card hygiene enforced.
