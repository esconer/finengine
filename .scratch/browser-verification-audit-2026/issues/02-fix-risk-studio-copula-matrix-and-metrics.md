# Issue 02: Fix Risk Studio Copula Matrix & Top Metric Cards

Status: closed
Type: bug
Priority: P1
Blocked by: —

## Problem Description
On Page 11 (/dashboard/risk-studio):
1. Top metric cards show dashes '—' for Portfolio Volatility, 99% EVT-POT VaR, and 99% Expected Shortfall.
2. Student-t Copula Dependence Matrix renders backend dictionary keys (tickers, matrix, high_tail_risk_pairs) as column headers and row labels instead of ticker symbols (INFY.NS, HDFCBANK.NS).

## Fix
In frontend/src/app/dashboard/risk-studio/page.tsx:
1. Fix tailRisk/copula response unnesting: const matrixData = tails?.dependence_matrix?.matrix || tails?.matrix; const tickers = tails?.dependence_matrix?.tickers || tails?.tickers || positions.map(p => p.ticker);
2. Fix metric cards data binding to read from riskContribution and tails properly.
