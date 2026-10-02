# 07 — Shareholding pattern producer

Status: needs-info
Type: task
Phase: 4
Blocked by: Phase 1 issue 19
Repo: `backend/`
Severity: **MEDIUM**

## What

Write a producer for `nse_shareholding_patterns` (`models/database.py:265`), which declares
`promoter_pledged_pct` at `:273`.

`promoter_pledged_pct` currently has **neither a reader nor a writer**.

## Why

Shareholding pattern is the quarterly governance record: promoter holding, FII/DII holding, public
float, and pledged shares. It is the input to promoter-pledge delta alerts, which is a real
credit/leverage signal, and to the FII-ownership trend that complements the daily flow data from
issue 03.

## The hard constraint: restatement

**Key every row by `(symbol, as_of, revision_date)`, not `(symbol, as_of)`.**

- NSE's shareholding-pattern page publishes an explicit **REVISION DATE** column.
- **Companies do restate.** A promoter holding revised downward in a later filing is materially
  different information from an error.
- Storing one mutable row per symbol per quarter will silently corrupt the history — which is worse
  than not having it, because the corruption is invisible.

This means a schema change to `nse_shareholding_patterns`, and a migration.

## Source

`nseindia.com/companies-listing/corporate-filings-shareholding-pattern`

Columns include: shares pledged, % of promoter, % of total, shares encumbered — plus the revision
date. A per-company API variant exists at
`nseindia.com/api/corporate-share-holdings-master?index=equities&symbol=X`.

Requires a session cookie. The HTML table path is the fallback and is brittle.

## Change

- Add `revision_date` to the model and to the natural key. Migration required.
- Upsert on `(symbol, as_of, revision_date)`, so a restatement inserts a new row.
- Expose a reader that returns **all** revisions for a `(symbol, as_of)`, plus a convenience view of
  the latest.
- Preserve `as_of` and `revision_date` through to the API so a consumer can tell a restatement from
  an original.
- Wire `promoter_pledged_pct` into a reader for the first time.

## Proof of done

- [ ] A quarter's rows land and the reader returns them.
- [ ] A fixture with **two revision dates for the same `(symbol, as_of)`** stores both rows and
      does not overwrite. **This is the key regression test.**
- [ ] The API returns both revisions and the latest, distinctly.
- [ ] `promoter_pledged_pct` has a reader and returns real values.
- [ ] The migration is reversible.
- [ ] A quarter absent from the feed yields no row, and a consumer can distinguish "not reported"
      from "reported as zero". This connects to Phase 2 issue 11.
- [ ] The test uses a recorded fixture.

## Notes

This pairs with Phase 1 issue 19 (`bfinance.ownership`), which does the fetch and parse. Do not
re-implement the HTML parsing here.

The restatement handling is the whole difficulty. A test that only stores one revision would pass
against an implementation that silently overwrites — so the two-revision fixture is mandatory.

Refs: `../spec.md`, `backend/app/models/database.py:265,273`, `backend/app/services/india_data_service.py:372,445`, Phase 1 issue 19
