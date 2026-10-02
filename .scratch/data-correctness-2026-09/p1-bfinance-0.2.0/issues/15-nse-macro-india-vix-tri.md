# 15 — `bfinance.nse.macro`: India VIX, index TRI, RBI reference rate

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: 03
Repo: `C:\es\coding\bfinance`
Effort: S

## What

New module. Three key-free Indian macro/valuation series that bfinance does not currently have.

```python
def india_vix(start: str | None = None, end: str | None = None) -> pd.DataFrame
def index_valuation(index: str = "NIFTY 50", *,
                    metric: Literal["pe", "pb", "div_yield"] = "pe") -> pd.DataFrame
def index_total_return(index: str = "NIFTY 50", *, net: bool = False) -> pd.DataFrame
def usd_inr_reference_rate(start: str | None = None,
                           end: str | None = None) -> pd.Series
```

## Why

**India VIX** is the only implied-volatility measure in India. The consuming app's entire
volatility apparatus — vol cones, forecast-risk, volatility-sizing, regime — is currently pure
realized volatility with no risk-neutral cross-check. India VIX gives a variance-risk-premium read
and a forward 1-month expected move to sanity-check forecast VaR.

**Index total return** fixes a live correctness bug. The app benchmarks against `^NSEI` **close**
(`finengine/backend/app/services/benchmark_service.py:20`), a price index. niftyindices.com
publishes explicit `Total Returns Index` and `Net Total Return Index` columns, exactly so this is
avoidable. The price index understates the benchmark by roughly the dividend yield
(~1.2–1.4%/yr), which compounds directly into understated active return and a wrong information
ratio on every tear sheet.

**Index P/E and P/B percentiles** give a valuation-regime input, so stress scenarios can be
driven by an observed valuation state rather than a hand-set shock.

**RBI reference rate** is the authoritative USD/INR fixing. The app currently uses a yfinance spot
quote with a hardcoded `83.0` fallback (`currency_service.py:27,362`), and applies that single
**live** rate to the entire portfolio return history — fabricating returns on any non-INR leg
(`region` defaults to `"US"`, so the path is live).

## Sources

All key-free, no session, no anti-bot:

| Series | Route |
|---|---|
| India VIX | `nseindia.com/reports-indices-historical-vix` CSV, or `/api/indicesHistory?indexType=INDIA VIX` |
| Index OHLC + P/E + P/B + div yield + **TRI** | `niftyindices.com/reports/historical-data` |
| All-index daily closes (~140 indices, archive to ~2018-09) | `archives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv` |
| RBI daily reference rate | `rbi.org.in/Scripts/Statistics.aspx` |

## Proof of done

- [ ] `india_vix()` returns a dated close series covering at least 5 years.
- [ ] `index_total_return("NIFTY 50")` returns both the price index and the TRI, and the ratio
      between them is consistent with the cumulative dividend yield (roughly 1.01–1.015 per year).
- [ ] `index_valuation("NIFTY 50", metric="pe")` returns a history with percentile ranking
      computed against its own history.
- [ ] `usd_inr_reference_rate()` returns a business-day series, not a forward-filled calendar.
- [ ] Every function is exported from the package root.
- [ ] A test confirms the TRI series returns a **higher** cumulative return than the price index
      over a multi-year window. If it does not, the mapping is wrong.
- [ ] Each function records its source URL and retrieval cadence in its docstring, and exposes a
      `provenance` field consistent with the honesty standard bfinance already applies elsewhere.

## Notes

The 10-year G-Sec curve and RBI policy repo are deliberately **out of scope** here. The G-sec
curve lives in RBI Handbook of Statistics HTML tables (effort M, low frequency value) and RBI DBIE
has no public API. The reference rate is the one RBI series worth the trouble.

Refs: `../spec.md`, Phase 3 issue 14, Phase 3 issue 19, Phase 4 issue 08
