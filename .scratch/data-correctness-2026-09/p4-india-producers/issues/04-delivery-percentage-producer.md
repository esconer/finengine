# 04 — Security-wise delivery % producer

Status: needs-info
Type: task
Phase: 4
Blocked by: 01
Repo: `backend/`
Severity: **HIGH**

## What

Write a producer for the `deliv_qty` / `deliv_per` columns on `nse_bhavcopy`
(`models/database.py:203-204`), consumed by `india_data_service.py:397`.

## Why

Delivery percentage is **the single best Indian accumulation/absorption signal**. A high delivery
ratio on an up day means real money changed hands rather than intraday churn. It is the
distinguishing metric of Indian market microstructure, and it has no global analogue.

It is also a **much better liquidity denominator than raw volume**: ADV in shares counts trades
that may never change beneficial ownership, while delivery-weighted volume counts the ones that
did. Several of the app's liquidity calculations would improve by using it.

## Source — and a correction to the t28 spec

NSE's "CM - Security-wise Delivery Positions" report, from
`nseindia.com/all-reports`. The legacy path was
`.../products/content/sec_bhavdata_full_DDMMYYYY.csv`.

**Delivery % is NOT in the CM bhavcopy.** It must be fetched from a **second feed** and joined.
Ticket `t28`'s spec implies one file covers delivery %, FII/DII, and bhavcopy — it does not. This
ticket corrects that.

| Property | Value |
|---|---|
| Auth | **None** for the CSV report |
| Cadence | EOD, after the bhavcopy |
| Join key | Symbol + trade date |

For a per-symbol live figure, `nseindia.com/api/quote-equity?symbol=X&section=trade_info` returns
`securityWiseDP.{quantityTraded, deliveryQuantity, deliveryToTradedQuantity}` — but that endpoint
is behind the stricter Akamai policy and returns 403 from datacenter IPs. Prefer the CSV.

## Change

- Fetch the daily report.
- Join against the bhavcopy by `(symbol, date)`.
- Store both `deliv_qty` and `deliv_per`. `deliv_per` should be computed from the two, not trusted
  from the feed, so the two can be cross-checked.
- Handle symbols present in one feed but not the other. A missing delivery figure is `None`, not
  `0.0` — see Phase 3 issue 11 for why.
- The z-score and signal in `analytics.py:7318` are computed downstream and should use the corrected
  data.

## Proof of done

- [ ] Rows land with `deliv_qty` and `deliv_per` populated, and the reader at `:397` returns them.
- [ ] `deliv_per` matches `deliv_qty / quantityTraded` within rounding. A test asserts the
      internal consistency, which also validates the join.
- [ ] A symbol present in the bhavcopy but absent from the delivery feed yields `None`, not `0.0`.
- [ ] A symbol present in the delivery feed but absent from the bhavcopy is handled without
      raising.
- [ ] The z-score and signal at `analytics.py:7318` are computed from the corrected data, and a
      known high-delivery day produces a high signal.
- [ ] `/dashboard/india-flows` renders real delivery percentages.
- [ ] Update ticket `t28`'s spec to record that delivery % is a second feed.
- [ ] The test uses a recorded fixture.

## Notes

Issue 01 must land first — the current `len(rows) < 3` guard means the reader can never return a
row, so a correct producer would appear to do nothing.

Refs: `../spec.md`, `backend/app/models/database.py:203-204`, `backend/app/services/india_data_service.py:395,397`, `backend/app/api/analytics.py:7318`, `.scratch/advanced-analytics/` ticket `t28`
