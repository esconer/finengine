# Issue 04: Fix Volatility Sizing Page Mock Fallbacks & Hardcoded Position Count

Status: resolved
Type: task

## Description
In `frontend/src/app/dashboard/volatility-sizing/page.tsx`:
1. Position count fell back to `|| 14`.
2. Estimated portfolio vol fell back to `'16.5%'`.

## Resolution
- Used `positions.length` directly without arbitrary fallback numbers.
- Replaced `'16.5%'` fallback with dynamic `sizingData?.current_volatility ? formatPercentage(...) : 'N/A'`.

## Verification
- `bun x tsc --noEmit` and `bun run test:run` passed.
- Metric cards reflect real values and 'N/A' when empty.

## Comments
Resolved and verified on 2026-09-02. Mock numbers eliminated.
