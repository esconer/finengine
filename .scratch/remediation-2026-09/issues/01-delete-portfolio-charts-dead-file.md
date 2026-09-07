# 01 — Delete `PortfolioCharts.tsx` dead file

Status: closed (2026-09-07, verified: file deleted, tsc+vitest green)

## Problem (verified 2026-09-07)

Bug-sweep B8 (delete dead `frontend/src/components/portfolio/PortfolioCharts.tsx`,
237 lines, formerly hardcoded 11-month mock performance data) was never executed:
file still exists. Mock array is already gone (`customPerformanceData || [...]`
at :95-97) and grep shows zero imports (only self + `.scratch/` docs reference it).

## Fix

1. Re-verify zero imports: `grep -rn "PortfolioCharts" frontend/src`.
2. Delete the file.
3. `bunx tsc --noEmit` + `bun run test:run` green.
