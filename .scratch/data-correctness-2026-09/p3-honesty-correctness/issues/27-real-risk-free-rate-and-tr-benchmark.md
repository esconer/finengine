# 27 — Real risk-free rate and Total-Return benchmark

Status: needs-info
Type: task
Phase: 3
Blocked by: Phase 1 issue 15
Repo: `backend/`
Severity: **HIGH — two wrong constants contaminating every relative metric**

## What

Two hardcoded values are wrong:

```python
# config.py:53
risk_free_rate = 0.02          # India is 5–7.5%
```

```python
# benchmark_service.py:20
^NSEI close, price-only         # understates by ~1.2–1.4%/yr
```

## Why

### The risk-free rate

Indian 91-day T-bills have yielded **5–7.5%**. At 2%, the excess return on every asset is inflated
by 3–5 percentage points annually. This poisons:

- alpha and annualised alpha
- Sharpe and Sortino
- the information ratio
- the Black-Litterman posterior (both the risk-free anchor and every view)
- Monte Carlo drift
- factor R² and the regression intercept

A Sharpe computed against a 2% risk-free rate when the true rate is 6% is not a slightly wrong
number; it changes the sign of a manager's evaluation in many cases.

### The benchmark

`^NSEI` close is a **price** index. niftyindices.com publishes explicit `Total Returns Index` and
`Net Total Return Index` columns, exactly so this is avoidable.

The price index understates the benchmark by roughly the dividend yield, ~1.2–1.4%/yr, and that
gap **compounds**. Over a multi-year tear sheet the cumulative understatement is substantial, and
it flows directly into understated active return and a wrong information ratio.

So a portfolio that matched NIFTY's total return looks like it underperformed, and vice versa.

## Change

### Risk-free rate

- Source it from a real Indian curve. Phase 1 issue 15 provides
  `usd_inr_reference_rate`; the G-Sec curve is deliberately out of scope there, so use one of:
  - a configured, dated T-bill/G-Sec rate with an `effective_from` (like `bfinance.costs`)
  - RBI reference data via an existing wrapper (`jugaad-data` already exposes "RBI Current Rates")
- **Never a bare constant.** If no rate is available, the dependent metrics should be `None` with
  a reason, not computed against a guess.
- Publish the rate and its effective date in the response, so a user can see what the numbers are
  measured against.

### Benchmark

- Use the NIFTY 50 **Total Return** index, with net total return available as an option.
- Keep the price index available for users who want the price comparison, clearly labelled.
- Publish which index vintage was used, per the `provenance` convention already in the codebase.

## Proof of done

- [ ] No hardcoded risk-free rate remains in `config.py`. Grep confirms.
- [ ] Every response that depends on the risk-free rate publishes the rate and its effective date.
- [ ] With no rate available, Sharpe/alpha/Sortino return `None` with a reason rather than
      computing against a default.
- [ ] The benchmark series is the Total Return index. A test asserts the TRI's cumulative return
      **exceeds** the price index's over a multi-year window.
- [ ] The tear sheet's relative performance changes and the change is explicable as the dividend
      gap. Spot-check one real portfolio and verify the delta is roughly the cumulative yield.
- [ ] The response states the index used and whether it is price, TR, or NTR.
- [ ] A `provenance` field is present, consistent with the existing convention in
      `currency_service.py` and `analytics_engine.py`.
- [ ] `/dashboard/regime` and the regime service, which fit on `^NSEI`, state whether they use
      price or TR.

## Notes

Do this **before** any Phase 5 feature. Every relative-performance feature — information ratio,
Brinson attribution, factor breadth, tax-aware rebalancing — inherits these errors, and fixing
them later means re-validating everything built on top.

Refs: `../spec.md`, `backend/app/config.py:53`, `backend/app/services/benchmark_service.py:20,24,50`, Phase 1 issue 15, Phase 5 issues 03, 14, 15
