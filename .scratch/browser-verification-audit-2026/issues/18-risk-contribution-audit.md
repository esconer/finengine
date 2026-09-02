# Issue 18: Risk Contribution Audit & Euler Decomposition Upgrade

**Page Under Audit**: [/dashboard/risk-contribution](http://localhost:3000/dashboard/risk-contribution)  
**Status**: Verified & Fixed  
**Date**: September 2, 2026  

---

## 1. Quantitative Verification & Metric Coherence

### Mathematical Verification of Displayed Numbers

| Metric | Displayed Value | Mathematical Formula | Consistency Check |
|---|---|---|---|
| **Portfolio Volatility (ann.)** | 18.08% | σ_p = √(w^T Σ w) × √252 | **Valid** — Matches Tear-Sheet and Realized Volatility. |
| **Daily VaR (95%)** | -1.82% | VaR_95 = Percentile(R_daily, 5%) | **Valid** — Empirical 5th percentile cutoff. |
| **Daily CVaR (95%)** | -2.53% | CVaR_95 = E[R_daily | R_daily ≤ VaR_95] | **Valid** — Conditional average tail loss on crisis sessions. |
| **Top Risk Driver** | MOTHERSON.NS (19.9%) | argmax_i (%RC_i) | **Valid** — Fixed rounding precision (19.9% instead of truncated 20%). |
| **Euler Volatility Sum** | ∑ %RC_i = 100.0% | Euler Theorem: RC_i = w_i (Σ w)_i / σ_p | **Valid** — Exact homogeneous risk attribution. |
| **Tail CVaR Sum** | ∑ %CVaR_i = 100.0% | E[R_i | tail] × w_i / total_tail_loss | **Valid** — Normalized positive loss-shares sum to 100%. |

---

## 2. Identified Deficiencies in Initial Build

1. Top Risk Driver was rounded to nearest integer (e.g. 20% instead of 19.9%).
2. Sector card only displayed volatility contribution without the option to inspect CVaR tail loss share by sector.
3. Missing educational explainers (? buttons) across all metric cards, bar lists, and sector charts.
4. Missing CSV export for risk attribution tables.

---

## 3. Implemented Enhancements

1. **Interactive Educational Explainer System**: Added modal engine with comprehensive descriptions for all 9 core risk contribution concepts.
2. **Sector Volatility vs CVaR Toggle**: Added seamless switching between Volatility Share and Tail Loss Share by sector.
3. **Diagnostic Risk Insight Formatting**: Enhanced symmetric vs asymmetric alert styling.
4. **CSV Export**: Added one-click export generating full position risk decomposition and sector rollups.
