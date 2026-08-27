# 25 — Interactive Efficient Frontier Curve Chart

Status: ready-for-agent
Type: feature
Blocked by: 08

## What
Enhance `/dashboard/optimize` with an interactive Markowitz Efficient Frontier scatter curve (Recharts / SVG):
- X-axis: Portfolio Volatility (Annualized %)
- Y-axis: Expected Portfolio Return (%)
- Plots 50 frontier portfolios connecting Min Vol to Max Return
- Overlay distinct markers for:
  - Current portfolio allocation
  - Max Sharpe Portfolio
  - Minimum Volatility Portfolio
  - Min CVaR Portfolio
  - Hierarchical Risk Parity (HRP) Portfolio

## Why
Visualizes where the current portfolio sits relative to optimal risk-return boundaries.

## Proof of done
- [ ] Frontier curve renders smoothly for user holdings with hover tooltips displaying portfolio metrics at each point.
