# Issue 05: Standardize INR Currency & Indian Microstructure Number Formatting

Status: closed
Type: bug
Priority: P2
Blocked by: —

## Description
1. `/dashboard` displays Market Value and Price with hardcoded Dollar signs (`$111,250.00` and `$1112.50`) for Indian NSE equities.
2. The Add Position modal prompts for `Buy Price (USD) *`.
3. `/dashboard/stress-testing` displays confidence level as `0.95%` instead of `95%` because backend returns decimal `0.95`.
4. `/dashboard/india-flows` displays 30D ADV as raw 13-digit numbers with decimals (`₹12,97,67,60,608.79`) instead of standard financial Indian notation (`₹1,297.68 Cr`).
5. Discrete counts (e.g. Number of Positions) render as floats (`2.00`) instead of integers (`2`).

## Proposed Fix
1. Bind currency symbol dynamically to active currency (`₹` / `$`).
2. Format confidence level: `(conf < 1 ? conf * 100 : conf).toFixed(0) + '%'`.
3. Format large Indian values in Crores (`val >= 1e7 ? '₹' + (val / 1e7).toFixed(2) + ' Cr' : ...`).
4. Format discrete counts with `Math.round(val)` or `val.toFixed(0)`.

## Proof of Done
- [ ] Prices and market values show `₹` by default for NSE stocks.
- [ ] Stress test confidence level displays as `95%` or `99%`.
- [ ] 30D ADV on `/dashboard/india-flows` displays cleanly in Crores (`₹1,297.68 Cr`).
- [ ] Position counts display as integers (`2`).
