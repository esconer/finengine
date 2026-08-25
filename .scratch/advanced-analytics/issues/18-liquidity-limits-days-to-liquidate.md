# 18 — Liquidity limits (days-to-liquidate)

Status: ready-for-agent
Type: task
Blocked by: 01

## What
Replace heuristic liquidity scoring (`analytics_engine.py:229-321`) with participation-based
math: days-to-liquidate = position_value / (k × ADV), k ∈ {10%, 20%}; Amihud illiquidity
|return|/rupee-volume as a cross-sectional score. Endpoint returns per-position limits;
surface "max sane position size" in portfolio manage page tooltips.

## Why
"How much of X can I actually own?" — prevents illiquid smallcap over-sizing.
Spec §F11 / Phase P5.

## Proof of done
- [ ] A ₹5L position in a ₹1Cr ADV stock shows ~25d @10% participation (sanity math checks).
