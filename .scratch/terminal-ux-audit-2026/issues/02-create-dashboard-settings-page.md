# Issue 02: Create Dedicated /dashboard/settings Page Component

Status: ready-for-agent
Type: bug
Priority: P1
Blocked by: —

## Description
The global sidebar links to `/dashboard/settings`, but navigating to it returns an HTTP 404 (file not found).

## Proposed Fix
Create `frontend/src/app/dashboard/settings/page.tsx` offering:
1. **General Preferences**: Default Display Currency (`INR` ₹ / `USD` $), Default Benchmark Index (`^NSEI` NIFTY 50 / `^BSESN` SENSEX), Default Lookback Window (252D / 756D / 5Y).
2. **Quant Risk Model Settings**: Confidence level default (95% / 99%), Target Volatility Sizing (15% default), Risk-free rate (7.0% default for India).
3. **Data Source & Engine Status**: Connectivity indicators for Yahoo Finance, Screener.in, and NSE Bhavcopy Cache.
4. **Cache & Database Maintenance**: "Clear Cache" and "Force Refresh Prices" trigger buttons.

## Proof of Done
- [ ] Clicking "Settings" in the sidebar opens `/dashboard/settings` with 0 console errors.
- [ ] User preferences toggle smoothly and persist cleanly.
