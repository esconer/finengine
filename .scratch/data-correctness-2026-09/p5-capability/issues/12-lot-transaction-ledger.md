# 12 — Lot / transaction ledger and point-in-time book

Status: needs-info
Type: task
Phase: 5
Blocked by: —
Repo: `backend/` + `frontend/`
Effort: **L** | Score: **50 — the highest-scoring item in the entire backlog**
Blocks: 11, 13, 16, and any honest realized-P&L claim

## What

Add a transaction ledger so the portfolio is a book of record rather than a holdings snapshot.

```sql
CREATE TABLE transactions (
    id           INTEGER PRIMARY KEY,
    ticker       TEXT    NOT NULL,
    side         TEXT    NOT NULL CHECK (side IN ('buy','sell')),
    quantity     REAL    NOT NULL CHECK (quantity > 0),
    price        REAL    NOT NULL CHECK (price > 0),
    trade_date   DATE    NOT NULL,
    fees         REAL    NOT NULL DEFAULT 0,
    notes        TEXT,
    created_at   TIMESTAMP NOT NULL
);
CREATE INDEX ix_transactions_ticker_date ON transactions(ticker, trade_date);

CREATE TABLE cash_ledger (
    id           INTEGER PRIMARY KEY,
    entry_date   DATE    NOT NULL,
    amount       REAL    NOT NULL,          -- signed
    kind         TEXT    NOT NULL,          -- 'deposit','withdrawal','dividend','interest','fee'
    reference    TEXT
);
```

Plus lot construction (FIFO or average-cost, chosen and documented) and a derived
`portfolio_state(as_of)` view.

## Why

**Today the app reconstructs history rather than recording it.**

`GET /api/v1/analytics/performance-history` computes `quantity × past_price` masked to the
buy-implied start. So every "realized" P&L figure, tear-sheet number, and attribution output is a
**hypothetical buy-and-hold of today's book**.

Add a second lot of the same ticker, or take a partial exit, and the entire foundation shifts — the
app cannot represent what actually happened.

This blocks, and unblocks:

| Blocked | Why |
|---|---|
| 13 — tax-aware rebalancing | Tax lots **are** the ledger. Without lots you must assume a single FIFO lot, which is wrong, or understate tax, which is dangerous |
| 16 — snapshot history | Cannot answer "what did my risk look like last quarter" without true weight history |
| 11 — pre-trade what-if | A scenario is naturally a hypothetical set of transactions |
| Any honest realized-P&L claim | It is the fix |

## Change

- Schema plus migration.
- A `transactions` CRUD surface.
- **CSV import** via the broker-export shape `bulk_add` already parses (Zerodha / Groww /
  AngelOne). This is the cheapest path to a populated ledger and should be first.
- Lot construction, with the method stated in the response and stored with each lot so a change of
  method does not retroactively rewrite history.
- **Corporate actions must flow into the ledger.** Phase 1 issue 05 delivers real splits, bonuses,
  and dividend ex-dates; Phase 2 issue 16 wires the route. A 1:2 bonus must change quantity; a
  dividend must produce a cash entry. Without this the ledger drifts from reality on every
  corporate action.
- Expose **TWR (time-weighted return)** next to the existing return series, and money-weighted
  return / IRR once cash flows exist.
- A reconciliation view: ledger-derived positions vs the existing `portfolio_positions` table, with
  differences surfaced. This is a diagnostic, not a replacement — the existing table stays as the
  fast path for current state.

## Proof of done

- [ ] A CSV of real broker transactions imports and produces correct lots.
- [ ] Lot construction is validated against a hand-computed FIFO example, including a **partial
      sell** that leaves a residual lot.
- [ ] A split and a dividend each produce the correct ledger effect. A test covers both.
- [ ] TWR is computed correctly across a cash flow. This is the key correctness test — TWR must be
      invariant to the timing of an external contribution, which is the whole point of the measure.
- [ ] IRR is computed and returns `None` with a reason when there is no sign change in the cash
      flow series.
- [ ] The reconciliation view reports zero differences on a freshly imported ledger. A non-zero
      difference is surfaced, not hidden.
- [ ] The import is idempotent — re-importing the same file does not duplicate.
- [ ] Historical analytics now read the ledger where available, and the response states which basis
      was used (ledger vs reconstruction).
- [ ] The AI-context export includes the transaction summary.

## Notes

The reconciliation view matters more than it looks. It is the mechanism that tells the user which
of the numbers they have been looking at were synthetic — and it keeps the existing
`portfolio_positions` table honest while the ledger is being adopted.

The lot method must be **stored, not derived**. If the method changes from FIFO to average-cost, the
tax lots must not silently rewrite. That would be a correctness bug of exactly the kind this whole
spec is about.

On method choice: FIFO is the Indian default for equity taxation and is the simplest to explain.
Average-cost is smoother for TWR. Pick FIFO, store it, and document it.

Refs: `../spec.md`, Phase 1 issue 05, Phase 2 issue 16, `CONTEXT.md` §3
