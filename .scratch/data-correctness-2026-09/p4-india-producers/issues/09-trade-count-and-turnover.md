# 09 — Trade count and ₹ turnover

Status: ready-for-agent
Type: task
Phase: 4
Blocked by: 05
Repo: `backend/`
Severity: **MEDIUM**

## What

Surface `TtlNbOfTxsExctd` and `TtlTrfVal` from the CM bhavcopy, which issue 05 already stores.

`india_data_service.py:29-32` already declares these fields in the contract, so **no schema change
is needed** — this is surfacing and using them.

## Why

**`TtlTrfVal` is a more robust ₹ turnover than `Close × Volume`.** The app currently computes
turnover as `mean(volume) × last_close` (Phase 3 issue 16), which is a reconstruction. The bhavcopy
carries the **actual** traded value. Using the real figure removes the approximation entirely and
makes Phase 3 issue 16's fix a temporary bridge rather than the final answer.

**`TtlNbOfTxsExctd` enables a turnover-per-trade ratio**, which is a materially better liquidity
measure than raw volume. A stock with the same rupee turnover but 10× the trade count is far more
liquid — many small, quickly-reversing trades clear easily, while a few large ones do not.

It also enables **Amahud illiquidity** properly, which the app currently cannot compute correctly
from reconstructed data.

## Change

- Expose both fields through the bhavcopy reader.
- Add a **turnover-per-trade** metric: `TtlTrfVal / TtlNbOfTxsExctd`.
- Prefer the bhavcopy's `TtlTrfVal` over the reconstructed `Close × Volume` for any date where both
  exist. Keep the reconstruction as a fallback and label which was used.
- Add Amahud illiquidity as a liquidity metric: `|return| / TtlTrfVal`. It is a well-established
  measure and pairs naturally with the existing Amihud-style logic.

## Proof of done

- [ ] Both fields are readable from the table for stored dates.
- [ ] Where a bhavcopy row exists, turnover comes from `TtlTrfVal`. A test asserts the app uses the
      real figure, not `Close × Volume`.
- [ ] Where no bhavcopy row exists, the reconstruction is used and **labelled as such** in the
      response's provenance.
- [ ] Turnover-per-trade is computed and exposed. A test asserts a hand-computed value.
- [ ] Amahud illiquidity is exposed with a documented formula and units.
- [ ] A `trade_count` of zero yields `None` for turnover-per-trade, not a division error or `0.0`.
- [ ] The test uses a recorded fixture.

## Notes

This makes Phase 3 issue 16's turnover fix less load-bearing. Do them together — issue 16 is still
correct and still needed for the fallback path, but the bhavcopy figure should become the primary.

Refs: `../spec.md`, `backend/app/services/india_data_service.py:29-32,397`, Phase 3 issue 16, Phase 4 issue 05
