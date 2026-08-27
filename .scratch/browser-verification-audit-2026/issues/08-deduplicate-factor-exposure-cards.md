# 08 — Deduplicate Factor Exposure Metric Cards & Purge Mock Deltas

Status: closed
Type: bug
Target: rontend/src/app/dashboard/factor-exposure/page.tsx

## Problem
1. Factor Exposure page rendered duplicate rows of R-Squared and Adjusted R^2 metric cards.
2. The second row contained hardcoded placeholder deltas (change={0.02}, change={0.01}).

## Fix
1. Consolidated into a single clean row of 4 key factor metrics (Market Beta, Jensen Alpha, R-Squared, Model Fit Quality).
2. Eliminated duplicate cards and placeholder mock deltas.

## Verification
- bun x tsc --noEmit passed with 0 errors.
- Factor exposure view renders clean deduplicated card grid.
- Git commit 0bc4a76.
