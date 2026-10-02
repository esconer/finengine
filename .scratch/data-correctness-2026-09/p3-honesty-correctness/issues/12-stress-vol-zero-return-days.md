# 12 — Stress-test volatility drops all zero-return days

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `backend/`
Severity: **HIGH**

## What

`analytics_engine.py:1013`
```python
non_zero = s[s != 0.0].clip(lower=-0.20, upper=0.20)
...
ticker_vol = non_zero.std() * sqrt(252)      # :1015
```

That `ticker_vol` feeds `vol_adj` (`:1016-1019`), which multiplies **every** `ticker_impact`
(`:1031`).

The published basis string at `:1020-1023` is
`vol_basis: "measured_annualized_volatility_over_reference"`.

## Why

Filtering on the **outcome variable** before computing dispersion is a statistical error. Genuine
flat sessions — no trade, a circuit-limit lock, a stale price in a thin scrip — are exactly the
low-dispersion days that must be retained to measure dispersion honestly.

Measured (200 days, 40 of them exactly `0.0`):
```
true annualised vol (all 200 days)     = 0.189639
code vol (zero days dropped, 160 days) = 0.212039   -> +11.81%
resulting vol_adj: 0.9638 (code) vs 0.8620 (truth)
```

So a systematically overstated vol inflates the headline "Market Crash −35%" and
"Volatility Spike −22%" losses.

The trigger is not exotic: **any Indian small or mid-cap with frequent zero-return sessions** —
which is precisely the population this engine targets.

## The internal contradiction

`analytics_engine.py:2334-2336`, in the same file, says the opposite and says why:

> *"dropna, not `!= 0.0`: keeps genuine 0% return days"*

Two rules, opposite meanings, 320 lines apart. The factor-regression one is right.

## Change

```python
clean = s.clip(lower=-0.20, upper=0.20)      # winsorize only
ticker_vol = clean.std() * sqrt(252)
```

Apply the identical rule used at `:2334-2336`, and extract it to one shared helper so the two sites
cannot drift again.

Also fix the adjacent defect while in this code: `:1032` has
`min(-0.02, ticker_impact)` — a floor that **enlarges** small losses. A custom "−1%" scenario
publishes **−2.00%** per position. It is disclosed as `position_impact_clip`, but the direction of
the effect is a floor on *severity*, not a sanity clamp. A floor makes sense only if it prevents
catastrophic values, and −2% is not catastrophic.

## Proof of done

- [ ] A series containing zero-return days produces the same volatility as the full-series
      computation. A test with 40 zeros in 200 days asserts equality.
- [ ] The `vol_adj` for that series matches the corrected value (0.8620 in the measured case).
- [ ] A custom "−1%" scenario publishes −1%, not −2.00%.
- [ ] The winsorization helper is shared with `:2334-2336`. Grep confirms one implementation.
- [ ] `vol_basis` still describes what was computed accurately.
- [ ] Add to `test_quantitative_invariants.py`.
- [ ] Re-check the stress-test outputs after this lands — several numbers on that page will change,
      and the page's historical screenshots or documented values will be stale.

## Notes

This fix will visibly change the stress-testing page's numbers. That is the point — but flag it in
the release notes, because "the stress numbers changed" without explanation invites a regression
report.

Refs: `../spec.md`, `backend/app/services/analytics_engine.py:1013,1015-1019,1020-1023,1031,1032,2334-2336`
