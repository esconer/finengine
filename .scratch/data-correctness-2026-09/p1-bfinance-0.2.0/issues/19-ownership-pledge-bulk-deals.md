# 19 — `bfinance.ownership`: shareholding, pledge, bulk/block deals

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: —
Repo: `C:\es\coding\bfinance`
Effort: M

## What

New module. The three Indian ownership and governance signals with no global analogue.

```python
def shareholding_pattern(symbol: str, *, consolidated: bool = True,
                         years: int = 12) -> pd.DataFrame
def promoter_pledge(symbol: str, *, years: int = 6) -> pd.DataFrame
def pledge_delta(symbol: str) -> PledgeDelta
def fpi_ownership(symbol: str) -> pd.DataFrame
def bulk_block_deals(*, start: str, end: str,
                     symbols: Iterable[str] | None = None) -> pd.DataFrame
def insider_transactions(symbol: str, *, start: str,
                          end: str) -> pd.DataFrame
```

## Why

These are genuinely Indian and genuinely differentiating — this is exactly the "not on free sites"
filter the product's value proposition is built on.

**Promoter pledge** is a real credit and leverage signal. bfinance has only a point-in-time
`Pledged percentage` today (`parser.py:214`, surfaced as `info["promoterPledged"]` at
`quotes.py:260`) — no series, no delta. NSE publishes this from NSDL and CDSL with **column 7
updated daily**, which makes it fresher than the quarterly pattern.

**Bulk/block deal price vs the same-day market close** is an instant realised mark on institutional
intent. The counterparty name, classified as FII / MF / promoter / institution, is the actual
signal — not the price.

**Insider transactions** under PIT Regulation 7(2)/(3) are mandatory disclosures and the
highest-signal Indian event available for free. The consuming app has a route
(`finengine/backend/app/api/data.py:305`) that is yfinance-only and effectively always empty for
Indian names.

**FPI ownership** completes the institutional picture alongside FII daily flows from issue 17.

## The hard constraint: restatement

**All of these must be keyed `(symbol, as_of, revision_date)`, not `(symbol, as_of)`.**

- NSE's shareholding-pattern page publishes an explicit **REVISION DATE** column, and companies
  **do** restate.
- PIT disclosures moved to **XBRL-only filing in 2026** (NSE/CML/2026/11, 04-May-2026), with the
  archive at `.../corporate-filings-insider-trading-archive-data`.
- SAST disclosure of promoter/promoter-group changes is system-driven (NSDL/CDSL → RTAs →
  exchanges) and disseminated at T+2.

Storing a single mutable row per symbol will silently corrupt pledge and shareholding history —
which is worse than not having it, because the corruption is invisible.

## Sources

| Data | Route | Auth |
|---|---|---|
| Pledge (NSDL+CDSL, daily) | `nseindia.com/companies-listing/corporate-filings-pledged-data`; per-company `.../api/corporate-share-holdings-master?index=equities&symbol=X` | cookie for API, HTML table otherwise |
| Quarterly pattern | `nseindia.com/companies-listing/corporate-filings-shareholding-pattern` (columns: *Shares pledged*, *% of Promoter*, *% of total*, *Shares encumbered*, plus REVISION DATE) | cookie |
| Bulk/block deals | `nseindia.com/api/snapshot-capital-market-largedeal` → `/api/historical/bulk-deals?from=&to=` → legacy `/api/block-deal` → CSV archive | cookie, POST for snapshot |
| Insider (PIT 7(2)/(3)) | `nseindia.com/companies-listing/corporate-filings-insider-trading` + archive | cookie |

## Proof of done

- [ ] Every return frame carries `as_of` **and** `revision_date`. A test asserts that a
      restatement produces a second row rather than overwriting the first.
- [ ] `pledge_delta()` returns QoQ and YoY percentage-point change plus a breach flag against a
      configurable threshold. A test covers the increase case, the decrease case, and no-change.
- [ ] `bulk_block_deals()` returns `client_name`, `buy_sell`, `quantity`, `trade_price`, the
      same-day close, and the derived premium/discount. Counterparty classification is present
      and its confidence is labelled — the classification rules are heuristics.
- [ ] The three-tier bulk/block endpoint fallback is implemented and each tier is tested. A test
      asserts the fallback engages when the primary 404s.
- [ ] `insider_transactions()` covers the 2026 XBRL format **and** the archive format. Both
      parsers have fixtures.
- [ ] `fpi_ownership()` returns the FPI bucket broken out by category, with `as_of`.
- [ ] Restatement handling is explicitly tested: a fixture with two revision dates for one
      `(symbol, as_of)` returns both, and the consumer can pick the latest.
- [ ] Every function records its source URL and states the reporting lag in the docstring.
- [ ] Exported from the package root.

## Notes

The HTML-table scraping path is brittle. Prefer the JSON APIs where they exist and treat the HTML
table as a documented fallback, not the primary.

This closes existing ticket `t29`. Update that ticket's status when this lands.

Refs: `../spec.md`, `screener/parser.py:214`, `market/quotes.py:260`, `.scratch/advanced-analytics/` ticket `t29`
