# 18 — `bfinance.universe`: index membership, weights, and rebalance events

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: —
Repo: `C:\es\coding\bfinance`
Effort: S (constituents) / M (change events)

## What

New module. Point-in-time index universes, so factor work and backtesting are
survivorship-bias-free.

```python
def index_universe(index: str = "NIFTY 50") -> pd.DataFrame
def index_weights(index: str = "NIFTY 50") -> pd.DataFrame
def universe_history(index: str, *, start: str, end: str) -> pd.DataFrame
def index_rebalance_events(index: str, *, start: str,
                           end: str) -> pd.DataFrame
def free_float_market_cap(symbols: Iterable[str]) -> pd.DataFrame
```

## Why

**Survivorship bias is the quiet killer of any backtest that benchmarks against a present-day
index series.** The consuming app's `benchmark_service.py:20` fetches `^NSEI` as a single
point-in-time price series. Combined with a screener that only sees *current* listings, any
historical screen or backtest implicitly assumes every constituent survived — which is false, and
biases results upward.

bfinance currently has only a free-text breadcrumb scrape for index membership
(`screener/parser.py:144-173`, matching names containing "bse/nifty/sensex"). No universe, no
weights, no history.

Constituent CSVs are **static and free — no key, no cookie, no session**. Rebalance events are the
harder half: NSE Indices publishes **no official change log**, so they must be **derived by
snapshotting and diffing**. That requires a persistent store, which means the fetch belongs in
bfinance and the scheduling belongs in finengine (Phase 4).

Rebalance cadence is semi-annual with cut-offs at 31-Jan / 31-Jul and 4 weeks' notice.

Index universe weights also unblock Phase 5 issue 14 (Brinson attribution), which needs
constituent sector weights as a first-class dataset.

## Sources

| Data | Route | Auth | Note |
|---|---|---|---|
| Constituents | `niftyindices.com/IndexConstituent/ind_nifty50list.csv` (+ `ind_nifty*list.csv`) | **none** | name, symbol, industry, series, ISIN. **No weights** |
| Weights | `nseindia.com/api/equity-stockIndices?index=NIFTY%20IT` | cookie | Only in factsheet PDFs otherwise |
| Free float | Derived from the constituents + market caps | — | — |

## Proof of done

- [ ] `index_universe("NIFTY 50")` returns exactly 50 rows with the expected columns, and the
      symbol set matches a known recent reconstitution.
- [ ] At least NIFTY 50, NIFTY 100, NIFTY 500, and the 13 NSE sectoral indices resolve.
- [ ] `index_weights()` either returns real weights **and labels them `estimated`/session-derived**,
      or raises a typed error. It must not return fabricated weights. Weights are the one field
      with no free source.
- [ ] `universe_history()` returns membership **as of** a date, built from accumulated snapshots.
- [ ] `index_rebalance_events()` returns add/remove/weight-change rows derived by diffing, with
      the derivation method stated in the docstring. A test asserts a known reconstitution date
      produces the expected adds and removes.
- [ ] A snapshot-cache is exposed so a caller can schedule the diff. The function does not manage
      its own persistence silently.
- [ ] `free_float_market_cap()` returns investable weight alongside raw market cap, and documents
      the free-float factor source.
- [ ] Every function records the source URL and the snapshot timestamp.

## Notes

The diff-based change-event derivation is the part that will rot. NSE can change the CSV format,
and a silent format change would make the diff report a mass reconstitution. Add a sanity guard:
a diff producing more than ~15% membership change in one period should raise rather than emit.

Refs: `../spec.md`, Phase 4 issue 10, Phase 5 issues 14 and 15
