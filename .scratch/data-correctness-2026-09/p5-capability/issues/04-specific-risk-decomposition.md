# 04 — Specific (idiosyncratic) risk decomposition

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: —
Repo: `backend/`
Effort: S | Score: 35

## What

Euler risk contribution decomposes **total** volatility. Barra's primary axis is
**total = common-factor risk + specific risk**. Add the second half.

```python
sigma_specific = sigma_asset * sqrt(1 - r_squared)
```

## Why

The app already computes everything needed: `beta` and `r_squared` are published by
`factor-exposure` (`analytics.py`). The derivation is one line and it is not being done.

Specific risk answers a question total risk cannot: **how much of this position's risk is its own
fault rather than the market's?** A 25% vol name at R²=0.9 is almost entirely market beta. The same
25% vol at R²=0.2 is mostly idiosyncratic — a company-specific problem that diversification will
not fix and that sector rotation will not hedge.

For a concentrated retail book this is often the most actionable risk decomposition available,
because idiosyncratic risk is the risk you can actually reduce by changing what you own.

## Change

- Add `specific_risk` and `specific_risk_share` per position, and aggregate to portfolio level.
- `specific_risk_share = specific_variance / total_variance`.
- **Forecast-vs-realised:** the app can also compare the factor model's predicted return against
  the realised return, which is a standard model-quality diagnostic. Worth including in the same
  block.
- Return `None` with a reason when `r_squared` is unavailable or when the window is too short —
  `sqrt(1 - R²)` on a low-R² estimate from 20 observations is noise.

## Proof of done

- [ ] `specific_risk` is validated against a closed-form reference.
- [ ] Portfolio-level specific variance plus common-factor variance equals total variance, within
      tolerance. **This is the key correctness test** — it is an identity, not a statistic.
- [ ] A high-R² position shows a low specific share; a low-R² position shows a high share. A test
      covers both directions.
- [ ] `r_squared` unavailable or below a sample threshold → `None` with a reason, not a computed
      number. A test forces it.
- [ ] The response declares units and states the window and observation count.
- [ ] The frontend renders the decomposition, with `N/A` states.
- [ ] A sector or aggregate view is available, matching the existing risk-contribution rollup
      pattern.

## Notes

Do **not** describe this as a "Barra model". A single-asset time-series regression against
`^NSEI` is a one-factor decomposition, and calling it Barra would overstate it. The honest framing
is "market (systematic) vs stock-specific (idiosyncratic) risk", which is what the MSCI Barra
Handbook calls the two components, computed here in time-series form.

Issue 15 (factor breadth) extends this to sector-relative and style factors. That is the right place
for anything more ambitious.

Refs: `../spec.md`, `backend/app/api/analytics.py`, Phase 5 issue 15
