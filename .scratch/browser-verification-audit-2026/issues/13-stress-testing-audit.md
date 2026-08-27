# Issue 13: Stress Testing (/dashboard/stress-testing) Audit & Educational Explainer Engine

**Status**: Resolved and Verified
**Date**: 2026-08-28
**Page**: /dashboard/stress-testing

## 1. Problem Statement & Audit Findings
1. **Numbers Meaning & Interpretation**:
   - Worst-Case Scenario (-41.9% Market Crash): Accurate representation of a 2008-style liquidity crash (-35% NIFTY shock) scaled by portfolio beta and high-volatility constituents.
   - Best-Case Scenario (-17.3% Interest Rate Shock): Accurate representation of a 300bp monetary tightening shock (-15% base shock).
   - Average Impact (-27.9% across 4 scenarios): Accurate arithmetic mean loss.
   - Identical Constituent Impact Artifact (-18.0% across multiple stocks): Caused by zero-padding across a 3-year historical frame compressing sample standard deviation down to baseline market volatility (16%). Fixed by filtering active non-zero returns to obtain authentic constituent volatilities.
2. **Missing Scenario Context in Position Table**:
   - Table previously overwrote position impacts with whichever scenario was run last, without displaying which scenario was active.
   - Fixed by adding an interactive Active Scenario Switcher in the table actions, highlighting the currently selected scenario.
3. **Missing Explainer System**:
   - Added interactive ? help buttons to all metric cards, scenario cards, custom shock builder, position impact columns, severity levels, and recovery insights.
4. **Usability Enhancements**:
   - Added Run All Scenarios 1-click execution button.
   - Consolidated double header into a clean single-header DataTable with CSV Export and scenario dropdown.

## 2. Verification
- Backend pytest: 249 passed, 0 failures in 56.97s
- Frontend vitest: 60 passed, 0 failures in 6.77s
- Frontend build: 22/22 static pages generated in 3.2s
- Live API & Web Daemons: 200 OK
