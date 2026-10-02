# 17 — A missing `Close` column is scored as maximally illiquid

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: 16
Repo: `backend/`
Severity: **MEDIUM**

## What

`analytics_engine.py:730-738`

There is an `if not vol_col: continue` guard for a missing volume column. There is **no
`if not close_col` guard**.

## Why

With `close_col` absent, `price` silently becomes `0.0`, so:
```
daily_turnover = 0.0
→ tier 4
→ score_raw = max(2.5, min(5.9, 3.0)) = 3.0
→ band "Low"
→ liquidation_days "5-10"
→ risk_level "High"
```

A **missing price column** is reported as a **measured** 3.0/10 liquidity score with a "High" risk
level and a fabricated "estimated" ₹1bn market cap.

The resolver at `:731` accepts four spellings of the close column. A fifth vendor shape silently
becomes a 3.0 with no signal that anything was wrong.

## Change

Add the symmetric guard:
```python
if not vol_col or not close_col:
    continue        # or mark the leg unmeasured
```

Better: mark the leg **unmeasured** rather than dropping it silently, so the coverage block can
report that a position was excluded for missing data. A silently-`continue`d position is
indistinguishable from one that was never in the portfolio.

## Proof of done

- [ ] A frame with `Volume` but no recognised `Close` column is excluded or marked unmeasured —
      never scored as 3.0.
- [ ] A test with a missing close column asserts no liquidity score is produced for that position.
- [ ] The coverage block reports the exclusion with a reason, so the user learns a position was
      dropped for missing data.
- [ ] A frame with a missing volume column behaves the same way. The two paths are symmetric.
- [ ] The four-spelling resolver is documented, and a test covers each accepted spelling. A fifth
      vendor shape produces a clear "unrecognised shape" error rather than a silent 3.0.
- [ ] Add to `test_quantitative_invariants.py`.

## Notes

This and issue 16 are the same code block. Fix them together, and extract the column resolution
plus the pairing into one helper so a new vendor shape fails loudly at the seam rather than
producing a plausible liquidity score.

Refs: `../spec.md`, `backend/app/services/analytics_engine.py:730-738,731,751-765`
