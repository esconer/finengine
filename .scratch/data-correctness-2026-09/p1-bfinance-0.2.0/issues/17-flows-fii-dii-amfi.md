# 17 — `bfinance.flows`: FII/DII activity and AMFI domestic fund flows

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: —
Repo: `C:\es\coding\bfinance`
Effort: S

## What

New module. The two legs of Indian institutional flow.

```python
def fii_dii_activity(*, start: str | None = None,
                     end: str | None = None) -> pd.DataFrame
def mf_nav_all(*, on: date | str | None = None) -> pd.DataFrame
def mf_equity_flows(*, months: int = 24) -> pd.DataFrame
def etf_aum_and_flows(*, months: int = 24) -> pd.DataFrame
```

## Why

The consuming app has an `/dashboard/india-flows` page, an `nse_institutional_flows` table, a
reader in `india_data_service.py:302`, a route at `analytics.py:7283`, and an AI-context composite
component — and **no producer anywhere**. The page renders against a structurally guaranteed empty
table.

**FII** comes from NSE. **DII** does not come from NSE at all — the DII leg requires AMFI, which is
why only the FII side was ever conceivable.

**AMFI is the single best effort-to-value source in the entire gap matrix.** `NAVAll.txt` is:

- ~16,000 schemes, ~3MB, one GET per business day
- `;`-delimited, T+0 after ~21:00 IST
- **no key, no cookie, no anti-bot**

It is also a statutorily mandated disclosure, which is a materially better licensing position than
scraping a commercial site. Second-leg MF/ETF AUM gives index-fund and ETF AUM → passive flow
pressure per stock, which nothing else in the app can currently produce.

## Sources

| Series | Route | Auth |
|---|---|---|
| FII/DII daily net | `nseindia.com/api/fiidiiTradeReact` (JSON: `category`, `date`, `buyValue`, `sellValue`, `netValue`) | cookie, no key; intraday, revised same-day |
| All-scheme NAV | `portal.amfiindia.com/spages/NAVAll.txt` and `NAVOpen.txt` | **none** |
| MF AUM | `amfiindia.com/research-information` (AAUM, category- and age-wise, folio) + fund-wise AUM RSS | none |

## Proof of done

- [ ] `fii_dii_activity()` returns both categories with `buyValue`, `sellValue`, `netValue`, and
      `date`, covering at least 1 year.
- [ ] Values are flagged `provisional` for the current trading day. Same-day revisions are the
      norm, not an exception.
- [ ] `mf_nav_all()` parses all ~16,000 schemes, strips the AMC and section header lines, and
      returns a frame with scheme name, code, NAV, and date.
- [ ] A test asserts the parsed scheme count is within 5% of the file's actual record count. This
      is the check that catches a silent partial parse.
- [ ] `mf_equity_flows()` returns AUM deltas by category. Note that **NAV ≠ AUM** — the module
      must not present NAV growth as flow, and the docstring says so.
- [ ] `etf_aum_and_flows()` returns ETF/index-fund AUM and net flows separately from the equity
      active fund.
- [ ] Every function records its source URL, its cadence, and its `as_of` timestamp.
- [ ] A cookie-refresh strategy exists for the NSE endpoint, including non-JSON content-type
      detection (Akamai returns an HTML block page, not a 403 JSON body) and a last-good cache.
- [ ] Exported from the package root.

## Notes

Safe operating posture for NSE endpoints: **one fetch per feed per day, cache aggressively, never
burst.** NSE publishes no rate limit for `/api/*`; observed enforcement is Akamai plus intermittent
429s. bfinance's existing global pacing design (`screener/client.py:100-121`) is the right template.

Refs: `../spec.md`, Phase 4 issues 03 and 05
