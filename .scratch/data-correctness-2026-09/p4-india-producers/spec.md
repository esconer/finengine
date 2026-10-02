# Phase 4 — India data producers

Status: ready-for-agent
Repo: this project, `backend/`
Tickets: 11
Gate: **issues 01 and 02 first.** They are pre-existing bugs in the read path that make the
producers untestable.

## The problem in one paragraph

finengine has 4 NSE tables, a carefully built `IndiaDataService` with validation, upsert, and read
paths, and 3 live API routes reading them. There is **no HTTP fetcher and no scheduler anywhere in
the codebase.** The tables are structurally guaranteed empty, so `/dashboard/india-flows` renders
against nothing.

This is the good news: the schema work is already done. `india_data_service.py:29-32`'s field
contract **already matches the NSE CM bhavcopy schema exactly.** These tickets are "wire up a
producer", not "design a schema".

## Ticket map

| # | Ticket | Effort | Summary |
|---|---|---|---|
| 01 | Fix the never-emitting delivery-row guard | S | `len(rows) < 3` means the reader can never emit a row |
| 02 | Fix the `nse_bulk_block_deals` column mismatch | S | Model declares `close`; the writer uses `close_price`. Silent insert failure |
| 03 | FII/DII producer | S | `nseindia.com/api/fiidiiTradeReact` |
| 04 | Security-wise delivery % producer | S | A **second** feed — not in the CM bhavcopy |
| 05 | Bhavcopy producer + post-market cron | M | Schedule per Phase 0 issue 03, **not** 18:30 |
| 06 | Bulk/block deal producer | M | Three-tier endpoint fallback |
| 07 | Shareholding pattern producer | M | Keyed `(symbol, as_of, revision_date)` |
| 08 | India VIX series | S | The only implied-vol anchor in India |
| 09 | Trade count and ₹-turnover | S | Same bhavcopy as issue 05 |
| 10 | Derived circuit bands | S | Free once issue 05 lands. **No per-symbol feed exists** |
| 11 | NSE daily volatility / VaR margin / ELM per scrip | S | A real per-holding leverage ceiling |

## Architecture decision: where does the fetch live?

The **fetch and parse** belongs in bfinance (Phase 1 issues 15, 17, 19), because it is reusable
capability and it belongs with the other vendor logic.

The **scheduling, persistence, and alerting** belongs here, because it is app-specific
orchestration.

This split is already established by `CONTEXT.md` §5 and by the way the rest of the data layer
works. Do not re-implement scraping in the app.

## Cadence

| Feed | Availability | Recommended schedule |
|---|---|---|
| CM bhavcopy | EOD, ~23:00–01:00 IST | Post that, **not** 18:30 |
| Security-wise delivery % | Later than the bhavcopy, separate report | After the bhavcopy run |
| FII/DII | Intraday, revised same-day | Once daily after close; mark same-day values provisional |
| AMFI NAV | T+0 after ~21:00 IST | Once daily |
| India VIX | EOD | With the bhavcopy run |

Phase 0 issue 03 determines the exact times. Confirm the host timezone — if it is not IST, the
scheduler must pin the timezone explicitly.

## Anti-bot posture

NSE sits behind Akamai with **per-endpoint** policies, not per-client. A documented probe found
`/api/quote-equity` returning **403 from both datacenter and residential IPs** while
`/api/marketStatus` and `/api/corporate-announcements` returned 200 from the same IPs.

Practical consequences:

- A plain cookie scrape is sufficient for `/api/fiidiiTradeReact` and the bulk-deal endpoints.
- `quote-equity` requires a real browser TLS fingerprint and is **not** reliably obtainable.
- **Any module built on a session-gated endpoint must degrade to the cookie-free static ZIP
  feeds**, which are immune to this entirely.

**Prefer static archives wherever an archive exists.** The bhavcopy family is the strongest
position precisely because it needs no session.

Cookie lifetime is measured in minutes; ~90s is the observed community value. A production client
needs re-seeding, non-JSON-content-type detection (Akamai returns an HTML block page, not a 403
JSON body), referer + realistic-UA pairing, and a last-good cache.

NSE publishes **no rate limit** for `/api/*`. Observed enforcement is Akamai plus intermittent
429s. Safe posture: **one fetch per feed per day, cache aggressively, never burst.**

## Verification

- Each producer has a test using a recorded fixture. No test hits the network.
- A test asserts each producer writes rows and that a reader can read them back — the round trip
  that does not currently exist.
- A test asserts a non-trading day produces no row without raising.
- A test asserts same-day FII/DII values are marked provisional.
- `/dashboard/india-flows` renders real values, and its existing exemplary failure semantics are
  preserved.
