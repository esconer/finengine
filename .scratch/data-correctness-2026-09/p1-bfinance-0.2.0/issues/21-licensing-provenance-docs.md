# 21 — Licensing and provenance documentation

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: —
Repo: `C:\es\coding\bfinance`
Effort: S

## What

Publish a per-source provenance and licence table, and reconcile the README's claims with what
the library actually does and is permitted to do.

## Why

Two problems, one legal and one reputational.

### The legal exposure

bfinance is **MIT-licensed** and PyPI-shaped. That licence **cannot grant rights it does not
have.** The library's systemic risk is upstream: it depends 100% on Screener.in (Mittal
Analytics), whose ToS prohibits automated scraping and redistribution.

Issues 15 through 20 add NSE, AMFI, NSE Indices, and RBI dependencies. Adding a second
single-source dependency does not diversify the risk — it adds sources.

Mitigating factors for the specific sources in this spec:

| Source | Position |
|---|---|
| NSE bhavcopy / FO archives | Published as **free-of-charge public dissemination products** |
| AMFI NAV | A **statutorily mandated** disclosure |
| NSE Indices constituent CSVs | Free public dissemination |
| RBI reference rate | Official statistical publication |

The line to hold: **personal and research use is fine. Redistributing derived NSE or AMFI data
inside an SDK that others install is not** — and that is precisely what the NSE Data & Analytics
licensing regime governs.

### The reputational exposure

The README/docstrings currently overstate parity in two directions:

- "1:1 drop-in replacement for yfinance" — issue 14 documents 65 missing `Ticker` members, 102
  missing `info` keys, a different `Screen` concept with no query DSL, and no streaming
- "180+ key metrics dictionary" — actual count is 86
- "live market microstructure" — issue 06 shows a price can be up to 24h stale with no public way
  to refresh it

And the library already has an honesty standard it applies to *missing* data (returning `None`
rather than guessing) which it does **not** apply to *fabricated* data. This ticket extends that
standard to the documentation layer.

## What to publish

### 1. A per-source provenance table

| Source | Used for | Auth | Cadence | Licence / ToS position | Redistributable in an SDK? |
|---|---|---|---|---|---|
| screener.in | profiles, statements, charts, ratios | none | per-request | ToS prohibits automated scraping and redistribution | **No** |
| NSE bhavcopy (CM/FO) | OHLCV, futures, OI | none | EOD ~23:00 IST | free public dissemination | Personal/research only |
| AMFI NAVAll.txt | MF/ETF NAV | none | T+0 ~21:00 IST | statutorily mandated | Personal/research only |
| NSE Indices CSVs | constituents | none | per rebalance | free public dissemination | Personal/research only |
| RBI reference rate | USD/INR | none | daily | official statistics | Yes, with attribution |
| NSE `/api/*` | FII/DII, chains, deals, filings | cookie | intraday | Akamai-fronted, no published rate limit | Personal/research only |

### 2. A capability matrix

Honest statement of what is supported vs yfinance, including the divergences issue 14 cannot
close (no query DSL, no streaming, no analyst estimates, no BSE historical).

### 3. A provenance field on returned data

Consistent with the `provenance` convention the consuming app already uses in
`currency_service.py` and `analytics_engine.py`. Every bfinance return should be able to say
where it came from and whether it is cached.

### 4. Staleness disclosure

Per-function cadence and typical staleness, so a consumer can decide whether the data is fresh
enough for their use.

## Proof of done

- [ ] A `docs/data-sources.md` (or equivalent) contains the provenance table, and it is linked
      from the README.
- [ ] The README's parity and metrics-count claims match reality, or are explicitly qualified
      with a link to the capability matrix.
- [ ] A `provenance` / `source` field is present on every public return type, consistent naming
      across modules.
- [ ] A `stale_after` or equivalent field is present on cacheable returns so a consumer can detect
      staleness without inspecting internals.
- [ ] The data sources that were researched and **rejected** are documented with reasons:
      NSE Level-2 / Post-Trade FTP (licensed), "short interest" (**does not exist as a published
      number in India** — publish client-wise short *sell volume* from the SLBS report instead),
      Prowess/CMIE (institutional pricing), Bloomberg/Refinitiv/FactSet consensus (licensed; free
      India consensus scraped from Moneycontrol/Trendlyne/Tickertape is ToS-prohibited and
      slug-unstable), BSE Web Forms scraping, per-symbol circuit-limit tables (**do not exist as
      a feed** — bands must be derived), RBI DBIE (no public API).
- [ ] A `CONTRIBUTING` or maintainer note records that adding a new upstream source requires a
      licence review, so this is not re-litigated per module.
- [ ] The licence file's scope statement acknowledges that MIT covers the code only, not the
      upstream data rights.

## Notes

This is the lowest-effort, highest-risk-reduction ticket in Phase 1. It costs an afternoon and it
is the difference between a library with a defensible provenance story and one that quietly
redistributes data it has no right to redistribute.

Refs: `../spec.md`, `README.md`, `screener/client.py:62`, `market/ratios.py:79`
