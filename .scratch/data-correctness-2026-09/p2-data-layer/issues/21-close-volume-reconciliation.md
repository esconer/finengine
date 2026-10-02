# 21 — Close and volume reconciliation against NSE

Status: ready-for-agent
Type: task
Phase: 2
Blocked by: Phase 1 issue 22, 08
Repo: `backend/`
Severity: **HIGH — the ingestion-boundary guard for RC1 and RC2**

## What

Cross-check every persisted OHLCV row against NSE's own MarketLens close, and surface
disagreement instead of silently picking a winner.

On each fetch, after a vendor frame is accepted and before it is written:

```
vendor_close  vs  nse_close   ->  close_divergence_pct
vendor_volume vs  nse_volume  ->  volume_divergence_pct
```

Persist both, expose both, and flag when they exceed tolerance.

## Why

The bfinance audit found that bfinance and yfinance **disagree in ways nothing verifies**:

- bfinance `Ratios.roe` is a **percent** (14.5) while its own `info["returnOnEquity"]` is a
  **fraction** (`r.roe/100`) and yfinance is a **fraction**
- bfinance's `history()` Open/High/Low are **fabricated** — measured 0.4–0.6% mean error, and
  structurally incapable of representing an intraday range
- bfinance's statement columns are **ascending** where yfinance is **descending**, so
  `iloc[:, 0]` silently returns a 10-year-old period as current
- `market_cap` exists in **four spellings across three units** with no declaration at the boundary
- bfinance's `Ticker("RELIANCE.BO").info['symbol']` returns **`RELIANCE.NS`**

Every one of those is a **100× or identity-class error that produces a plausible-looking number
with no exception raised.** Nothing in the pipeline would notice any of them.

NSE MarketLens gives a **third, official, exact** opinion on close and volume — verified 8/8 against
yfinance on both fields. That turns a two-way disagreement into a resolvable one:

- vendor close == NSE close → the vendor's close is right
- vendor close != NSE close, yfinance == NSE → **the vendor is wrong on close**
- vendor close != NSE, yfinance != NSE, and they differ from **each other** → one of them is wrong
  and the cascade should say so rather than write a coin flip into `stock_timeseries`

This is the check that would have caught the RC1 and RC2 bugs **at ingestion**, instead of in a
metric card three screens away.

## The asymmetry to respect

MarketLens is authoritative for **close and volume only**. It has no O/H/L, so a close divergence
is a verdict while an O/H/L gap is simply a coverage difference. Do not attempt to reconcile
O/H/L against it — there is nothing to reconcile against. That is Phase 1 issue 03's job.

## Change

- A reconciliation step at the ingestion boundary, after normalization and before persistence.
- Only reconcile when the date is within MarketLens's coverage and the vendor supplied a close for
  that exact date. Do not nearest-match across a date boundary — that would manufacture agreement.
- Tolerance: **0.1%** on close. Both NSE and yfinance agreed to the cent on all 8 tested sessions,
  so anything larger is a real disagreement and not rounding.
- Volume: 2%. Volume is less reliable across vendors (different consolidation, block-trade
  treatment) so it gets a looser band and is advisory rather than blocking.
- Record the outcome in `fetch_logs` and on the response, using the existing `provenance` /
  `data_status` conventions.
- **A divergence must not silently overwrite the vendor value.** Write the vendor row, record the
  NSE row alongside it with its own provenance, and flag. Auto-correcting is tempting and wrong —
  it hides which vendor is broken, and Phase 2 issue 08 exists precisely so an operator can see
  which vendor is failing.

## Proof of done

- [ ] A vendor frame matching NSE produces `close_divergence_pct ≈ 0` and no flag.
- [ ] A deliberately corrupted close (e.g. ×100) is **caught** and flagged. This is the key
      regression test — it simulates the ROCE-class bug.
- [ ] A vendor close differing from NSE while yfinance matches NSE flags **the vendor**, not
      yfinance.
- [ ] Reconciliation does not fire when the vendor has no row for that date, or when the date is
      outside MarketLens coverage. A test asserts no nearest-match agreement.
- [ ] The response and `fetch_logs` both carry the divergence figures and the NSE provenance.
- [ ] The check is a **single extra network call per fetch window**, not per row — fetch the NSE
      window once and join in memory. A test asserts the call count.
- [ ] Reconciliation failure (NSE unreachable) is non-blocking: the fetch still succeeds and
      records `reconciliation_status: "unavailable"`. **Reconciliation must never be able to fail
      a data fetch.**
- [ ] `/dashboard/settings` or a health endpoint reports per-vendor close accuracy, so a vendor
      silently returning stale-but-plausible prices becomes visible.
- [ ] `test_quantitative_invariants.py` gains a case where a fabricated vendor close is rejected.

## Notes

This is the highest-leverage single guard in the data layer, and it is cheap: one extra windowed
request per fetch, cached aggressively, against a source that has no anti-bot and no rate limit
pressure.

It also directly serves the owner's stated goal — redundancy. After this, a bfinance outage is not
just survivable, it is **detectable and quantifiable**, and the remaining vendor becomes
cross-checkable rather than trusted.

Note the ordering constraint: this lands after Phase 2 issue 08 (cascade logging) and Phase 1
issue 22 (the MarketLens client), because a reconciliation result that cannot be recorded is
useless.

Refs: `../spec.md`, Phase 1 issues 03, 08, 22, Phase 2 issues 04, 08
