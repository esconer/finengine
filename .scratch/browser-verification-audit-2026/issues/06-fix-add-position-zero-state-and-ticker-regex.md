# 06 — Fix Add Position Zero-State Auto-Weight & Alphanumeric Ticker Validation

Status: closed
Type: bug
Target: rontend/src/components/portfolio/AddPositionModalSimple.tsx

## Problem
1. When adding the first stock to an empty portfolio (positions = 0 / total_value = 0), totalPortfolioValue defaulted to 100000, causing initial weight auto-calculation to show 3.06% instead of 100.00%.
2. Ticker validation regex rejected tickers with digits (e.g. 3MINDIA.NS), hyphens (BAJAJ-AUTO.NS), or long symbols (TATAMOTORS.NS).
3. Currency label was hardcoded to USD even when entering Indian NSE/BSE stocks.

## Fix
1. Initialized totalPortfolioValue to 0 and tracked existingCount. When existingCount === 0 || totalPortfolioValue <= 0, auto-calculated weight is strictly set to 1.0 (100.00%).
2. Expanded ticker validation regex to /^[A-Za-z0-9\-\ &\.]{1,20}$/.
3. Added dynamic currency detection (switches to INR and region: IN on .NS/.BO scrip codes).

## Verification
- bun x tsc --noEmit passed with 0 errors.
- bun x vitest run passed (35/35).
- Git commit 17dc790.
