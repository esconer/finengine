# Data Freshness and Provider Findings

Status: active.

## DF-001 — AAPL quote is not merely stale; it is materially wrong

- Severity: P1
- FinEngine: $4.89, Unknown sector/industry.
- Multiple secondary 2026-09-24 observations: approximately $336.16; official numeric exchange/issuer pages were unavailable.
- Difference: approximately 98.5%.
- Verdict: `DISCREPANCY`.
- Evidence: `evidence/calculations/inputs/external-market-crosscheck.md` and `us-reseed.json`.

## DF-002 — Market quote as-of provenance is insufficient

- Severity: P2
- Position rows expose a current value but not a provider market timestamp, quote source, or delayed/live flag.
- Fetch time cannot be treated as quote as-of time.
- Consequence: stale provider values can be persisted and displayed as current.

## DF-003 — Mixed-currency historical metrics lack daily historical FX

- Severity: P2 / analytical limitation
- Current portfolio can convert current values with one live FX snapshot, but historical INR/USD portfolio returns cannot be independently reproduced without daily historical FX.
- Verdict for mixed-currency historical performance: `UNVERIFIABLE` unless daily FX is returned/captured.

## DF-004 — Representative current-price freshness

| Ticker | Verdict | Note |
|---|---|---|
| RELIANCE.NS | `STALE` / `DISCREPANCY` | App ₹1,227 vs current secondary observation ~₹1,238.40 |
| HDFCBANK.NS | `VERIFIED` with timing caveat | App ₹730 vs intraday ₹727.70–₹729.80 |
| TCS.BO | `VERIFIED` with timing caveat | App ₹2,089 vs intraday ₹2,090.60 |
| MSFT | `STALE` / timing-sensitive | App $493.19 vs current observation $495.07 |
| AAPL | `DISCREPANCY` | App $4.89 vs ~$336.16 |

Official exchange pages did not expose numeric fields to the fetcher, so the current spot checks are secondary-source observations and not official certification.

## DF-005 — Broad cache invalidation is not surfaced as a freshness event

- Severity: P2
- Saving a different primary source can invalidate time series and analytics broadly, while the UI presents the action as a simple preference save.
- The isolated cache-purge interaction returned 200 and preserved the five-position portfolio, but did not provide a market-data as-of timestamp or a before/after accuracy guarantee.
- Verdict: `UNVERIFIABLE` for post-purge market accuracy until fresh provider responses are timestamped and compared.
- Evidence: `evidence/network/console/desktop/interactions/settings-source2.txt`, `evidence/network/console/desktop/interactions/settings-cache.txt`, and `pages/dashboard-settings.md`.

## DF-006 — Current quote timestamps are not part of the position contract

- Severity: P2
- Fetch time is not a quote as-of time. The captured quote/history mismatch for AAPL cannot be resolved to an exact provider timestamp or delayed/live state.
- Verdict: `UNVERIFIABLE` for provider freshness and exact quote provenance; the AAPL value itself remains `DISCREPANCY` against the independent observation.
- Evidence: `evidence/network/api-final/quote_AAPL.200.json`, `evidence/network/api-final/history_AAPL.200.json`, and `data-freshness-bugs.md` DF-001/DF-002.

## Pending

- India data dates/units and source freshness.
- Fundamentals statement periods and filing/publication timestamps.
- FII/DII, delivery, deals, and shareholding session alignment.
- Provider-specific field coverage.
