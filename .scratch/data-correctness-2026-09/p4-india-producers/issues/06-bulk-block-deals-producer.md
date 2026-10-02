# 06 — Bulk/block deal producer

Status: needs-info
Type: task
Phase: 4
Blocked by: 02
Repo: `backend/`
Severity: **MEDIUM**

## What

Write a producer for `nse_bulk_block_deals` (`models/database.py:240-264`), which already declares
`client_name`, `buy_sell`, `quantity`, `trade_price`, and the mismatched `close` column from
issue 02.

## Why

**Bulk-deal price versus the same-day market close is an instant realised mark on institutional
intent.** A block traded at a 4% discount to close is a different signal from one at parity.

But the **counterparty name is the actual signal.** Classifying the client as FII / MF / promoter
/ institution / foreign portfolio turns a price anomaly into an answer to "who is selling?". That
classification is a heuristic and must be labelled as one.

The table has no producer, so none of this is available.

## Source — a three-tier fallback

| Tier | Route | Method |
|---|---|---|
| 1 | `nseindia.com/api/snapshot-capital-market-largedeal` | POST, today's deals |
| 2 | `nseindia.com/api/historical/bulk-deals?from=&to=` | GET, historical |
| 3 | Legacy `nseindia.com/api/block-deal` | GET |
| 4 | CSV archive on the report page | file |

Report page: `nseindia.com/report-detail/display-bulk-and-block-deals`.

The endpoint is **undocumented**, so all four tiers must be maintained. A change in tier 1 should
degrade to tier 2 rather than losing the feed.

## Change

- Implement the fallback chain. Log which tier served the data.
- Join `close` from the bhavcopy (issue 05) for the same `(symbol, date)`.
- Compute `premium_discount_pct` = `(trade_price - close) / close`.
- Classify the counterparty, with a `classification_confidence` field. Heuristics should be
  conservative and their basis documented.
- Handle the `buy_sell` direction correctly relative to the classification — a promoter buying in
  a block is a very different signal from an FII buying.

## Proof of done

- [ ] Rows land with every field populated, including `close` from the bhavcopy join. A test
      asserts a fixture deal round-trips fully.
- [ ] A tier-1 failure falls through to tier 2 and the response records which tier served it. A
      test forces the failure.
- [ ] `premium_discount_pct` matches a hand-computed value.
- [ ] The counterparty classification is present, labelled with its confidence, and its rules are
      documented. A test asserts an unclassifiable name yields `None` with low confidence, **not**
      a guess.
- [ ] A deal on a date with no bhavcopy row yields `close = None` and therefore
      `premium_discount_pct = None` — not `0.0`.
- [ ] Issue 02's mapping test covers this table.
- [ ] The test uses a recorded fixture.

## Notes

Issue 02 must land first, or the `close` column will be silently null and the premium/discount —
the whole point of the feed — will be unavailable.

The `close`/`close_price` naming should be resolved in issue 02 in a way that does not collide
with `trade_price`. A block trade has a price; the market has a close; conflating them is how this
bug happened.

Refs: `../spec.md`, `backend/app/models/database.py:240-264,248`, `backend/app/services/india_data_service.py:445`, Phase 1 issue 19
