# 07 — `resolve_company_id` must require an exact match

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: 01
Repo: `C:\es\coding\bfinance`
Severity: **CRITICAL**

## What

`src/bfinance/screener/client.py:221-222`
```python
# If no exact match, return first item's ID
```

A fuzzy fallback returns the first item's company ID when no exact match exists. And
`get_chart_timeseries` keys its cache on `comp_id` **only** (`:322`), with no symbol in the key.

## Why

A typo silently resolves to a different company, and because the chart cache key omits the
symbol, the wrong series is also **written into the right company's cache slot**, poisoning it
for the legitimate symbol.

Verified live:
```
resolve_company_id('RELIANC')  -> comp_id=2726   # 2726 == Reliance Industries
```

So `Ticker("RELIANC").history()` returns **RELIANCE's price series**, while
`Ticker("RELIANC").financials` is empty (the profile URL 404s). The same object returns
contradictory data. `Ticker("RELIANC").valuation_history()` also returns Reliance's multiples.

This is the worst failure mode in the library because it is completely silent — the caller gets
real-looking numbers for the wrong company.

## Proof of done

- [ ] `resolve_company_id('RELIANC')` returns `None`, not a fuzzy match.
- [ ] A `Ticker` built on an unresolved symbol returns empty/None for **all** accessors
      consistently — never a mix of real data and empty data.
- [ ] The chart cache key includes the symbol, not just `comp_id`.
- [ ] Two different symbols cannot collide in the chart cache. A test writes a series for symbol A
      and confirms symbol B does not read it.
- [ ] A test asserts the specific regression: `Ticker("RELIANC").history()` does not return
      Reliance Industries' price series.
- [ ] The `Ticker` exposes a clear unresolved state (see issue 11's `currentPrice=None`
      behaviour) so the caller gets a diagnosable error rather than an empty frame.

## Notes

Exact match should be against the `url` field or the symbol, whichever the screener response
carries reliably. Check both and document which is authoritative.

Refs: `../spec.md`, `screener/client.py:221-222,322`, issue 11

## Verification correction (2026-09-28)

**CONFIRMED, with one latent caveat worth recording.**

`screener/client.py:282-313` uses exactly one route - `f"{self.BASE_URL}/company/{clean}/"` after
`normalize_symbol` - and `extract_company_id` requires the `data-company-id` **attribute**. There is
no search endpoint, so it cannot return a different company via best-match ordering. This is a
genuine improvement over the old `?q=` resolver, which was also a robots violation.

Measured, all four failure modes return `None` rather than a wrong id:

```
single company page            -> 500325
attribute absent               -> None   (+ WARNING at client.py:310-312)
id as text, not an attribute   -> None
attribute is the company name  -> None
```

**Caveat: it is a first-match regex over the whole HTML, not scoped to the company block.** HTML
containing two `data-company-id` attributes returned `999999` when the wrong one came first. A real
single-company page has only one, so this is latent rather than live - but "exact" is slightly
stronger than what the code guarantees. A test with a two-attribute fixture would pin it.
