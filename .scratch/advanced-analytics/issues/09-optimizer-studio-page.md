# 09 — Optimizer studio page

Status: ready-for-agent
Type: task
Blocked by: 08

## What
Route `/optimizer`: model picker, constraint form (per-asset min/max, sector caps), run button,
efficient frontier line chart, current↔optimal diff table with trade list (shares to buy/sell
using last_price × quantity). "Apply suggestions" is OUT of scope for now (display only).

## Why
Turns rebalancing from guesswork into evidence. Spec §F4 / Phase P2.

## Proof of done
- [ ] Run on real portfolio produces frontier + trade list in <15s.
- [ ] Constraints are respected in returned weights (spot-check).
