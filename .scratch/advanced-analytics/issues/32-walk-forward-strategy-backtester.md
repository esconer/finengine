# 32 — Walk-Forward Strategy Backtester

Status: ready-for-agent
Type: feature
Blocked by: 08

## What
Build a walk-forward historical backtesting module:
- Rebalances portfolio on a rolling schedule (monthly, quarterly) using a selected optimization strategy (HRP, Min Vol, Max Sharpe, Equal Weight).
- Computes cumulative returns, turnover cost penalty (slippage + STT/brokerage), max drawdown, and Sharpe ratio vs buy-and-hold benchmark.
- Visualizes equity curves and rolling drawdowns.

## Why
Allows users to backtest whether dynamic rebalancing historically added alpha or reduced risk on their specific basket of stocks.

## Proof of done
- [ ] Backtest executes for 5-year history on 10 stocks in under 5 seconds with detailed transaction turnover logs.
