# 16 — Portfolio snapshot and as-of versioning

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: 12
Repo: `backend/`
Effort: M (→ S if snapshotting current weights only) | Score: 28

## What

Persist a point-in-time snapshot of the book's risk profile, so risk can be tracked over time.

```sql
CREATE TABLE portfolio_snapshots (
    id           INTEGER PRIMARY KEY,
    as_of        TIMESTAMP NOT NULL,
    trigger      TEXT NOT NULL,        -- 'scheduled','manual','post-trade','breach'
    total_value  REAL,
    n_positions  INTEGER,
    snapshot     JSON NOT NULL         -- the full risk payload
);
```

## Why

`analytics_cache` is a **per-ticker scalar cache**, not a book. So today the app cannot answer:

- "What did my risk look like last quarter?"
- "When did I first breach 25% VaR?"
- "Has my tracking error been widening?"
- "How long has my current drawdown lasted?"

Risk is a **time series**, and the app treats it as a point reading. That is the gap issue 06's
breach history runs into, and it is what makes issue 05's time-under-water metric
contextless — you cannot know if 40 days underwater is unusual without history.

## Change

- Scheduled snapshots plus manual ones.
- Triggered snapshots on a breach (from issue 06) and after a rebalance.
- Store the full risk payload, so historical queries do not need to be recomputed against data that
  has since changed.
- A `GET /analytics/risk-history` endpoint.
- **Chart the risk trend** on `/dashboard`: VaR, HHI, effective positions, and drawdown over time.
  This is the deliverable — the table is plumbing.
- The ledger (issue 12) gives true weight history. Without it, snapshots capture only *current*
  weights as observed on the snapshot date, which is honest but limited. Do it anyway — it is still
  a time series, and it is the S-effort version of this ticket.

## Proof of done

- [ ] A snapshot is written on schedule, on demand, on breach, and post-rebalance. A test triggers
      each.
- [ ] `GET /analytics/risk-history` returns the series, and a test asserts an inserted fixture
      series comes back correctly.
- [ ] Snapshots are immutable once written. A test asserts no update path exists.
- [ ] A breach-triggered snapshot records which limit was breached, so the history is
      self-describing.
- [ ] The dashboard renders the risk trend chart with a real time axis.
- [ ] The response states the snapshot cadence and the fields captured, so a consumer knows what
      the series does and does not contain.
- [ ] Snapshots of a book that later changed are unaffected — the stored payload is the payload,
      not a live reference. A test changes the DB and asserts history is unchanged.
- [ ] Storage growth is bounded. A retention policy exists and is documented.

## Notes

**Single-user means "audit trail", not "workflow engine".** GIPS traceability, eFront, and
Confluence reconciliation all exist because many people act on a shared record. You are the only
actor.

So build this as **a time series you can chart**, not a versioned store with approvals, an audit
log UI, and a review workflow. That would be a platform, and it is not what you need.

The honest framing: this exists so you can compare your own risk over time and see a breach when it
happened, not to satisfy a regulator.

Refs: `../spec.md`, Phase 5 issues 05, 06, 12
