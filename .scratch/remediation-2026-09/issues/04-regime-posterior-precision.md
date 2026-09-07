# 04 — Regime posterior precision

Status: closed (2026-09-07, verified: 4dp emitted, precision tests green)

## Problem (verified 2026-09-07)

`regime_service.py:238-241` rounds posteriors to 1dp server-side, so a genuine
`0.04%` becomes `0.0%` — display-layer information destroyed at the source.
No argmax clipping exists (saturation itself is honest model output);
`regime/page.tsx:513,517,521` renders raw values. A `0.4%` posterior already
displays correctly; true `0.0/100.0` saturation stays as-is (honest).

## Fix

- Emit full precision (`round(..., 4)`) from the service; frontend keeps 1dp
  formatting (verify by reading `regime/page.tsx`, no frontend edits — B territory).
- Add/extend a regime test asserting a small posterior (e.g. 0.0004) survives
  the service unrounded-to-zero.
