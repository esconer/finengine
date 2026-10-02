# 16 — Liquidity turnover uses the wrong formula

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `backend/`
Severity: **MEDIUM**

## What

`analytics_engine.py:737-739`
```python
volume = float(df[vol_col].mean())
price  = float(df[close_col].iloc[-1]) if close_col and not df.empty else 0.0
daily_turnover = volume * price
```

## Why

A **mean over the whole history** multiplied by the **most recent** price. Neither factor matches
the other.

A stock that fell 50% over the window reports roughly **2×** its true average daily turnover. One
that doubled reports roughly **0.5×**.

This is not a cosmetic field. `daily_turnover` is a **primary key input** to the tier ladder at
`:751-765`, so a 2× error can move a name across the 2 Cr / 10 Cr / 50 Cr boundaries — changing
its liquidity band, its `liquidation_days`, and its `risk_level`.

## Change

```python
daily_turnover = float((df[vol_col] * df[close_col]).mean())
```

Then fix the adjacent `close_col` guard as issue 17 describes, and pull both into one place so
the volume/price pairing cannot be separated again.

## Proof of done

- [ ] A series with a 50% price decline over the window reports turnover computed from the
      **paired** series, matching a hand-computed reference. A test asserts the exact value.
- [ ] A flat-price series is unaffected — the current and corrected formulas agree when price is
      constant. This confirms the fix is targeted.
- [ ] A name near a tier boundary is classified the same way by the corrected formula as by a
      direct computation from the raw data. Spot-check two real names.
- [ ] Add to `test_quantitative_invariants.py`.
- [ ] The liquidity page numbers will change. Flag it in the release notes.

## Notes

Two adjacent defects in the same block, both worth fixing here:

- `high_volume_pct` / `medium_volume_pct` / `low_volume_pct` (`:805,819-825`) are
  `count / total_positions` — **position-count** shares, not volume shares. The
  `LIQUIDITY_SCORE_BAND_RULE["volume_stats_basis"]` entry at `:346` states this correctly, so the
  *rule* is right and the *key names* are wrong. Either rename the keys to `high_volume_position_pct`
  or compute actual volume shares.
- `max_sane_value_inr` is a hardcoded threshold used to cap position value. Check whether it
  should scale with portfolio value rather than being an absolute constant.

Refs: `../spec.md`, `backend/app/services/analytics_engine.py:346,730-765,805,819-825`
