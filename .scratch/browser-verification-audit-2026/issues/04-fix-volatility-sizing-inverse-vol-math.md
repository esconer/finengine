# Issue 04: Fix Inverse-Volatility Risk Parity Allocation Formula

Status: closed
Type: bug
Priority: P2
Blocked by: —

## Problem Description
On Page 8 (/dashboard/volatility-sizing):
The stock with higher volatility (INFY.NS @ 27.23%) is recommended a higher weight (60.82%), while the stock with lower volatility (HDFCBANK.NS @ 15.46%) is recommended a lower weight (39.18%).
This is an inversion of risk parity (w_i proportional to 1 / sigma_i).

## Fix
In volatility sizing calculation:
Compute inverse volatility weight w_i = (1 / sigma_i) / sum(1 / sigma_k).
Ensure INFY.NS is allocated ~36.2% and HDFCBANK.NS is allocated ~63.8%.
Also fix 'Total Positions' metric card formatting from '2.00' to integer '2'.
