# 12 — Resolve the Alpha Vantage Tier-3 dead branch

Status: needs-info
Type: task
Phase: 2
Blocked by: 08
Repo: `backend/`
Severity: **HIGH**

## What

`alpha_vantage_service.py:34` and `:72-91`:
```python
AV_SYMBOL_MAP: Dict[str, str] = {}          # :34

if raw.endswith((".NS", ".BO", ".BSE")):   # :85
    return None                             # :88
```

`canonical_ticker` only ever produces `.NS` / `.BO` / bare-Yahoo-native symbols
(`data_service.py:199-224`), and this product is India-only.

So `fetch_daily_ohlcv` (`:339`) and `fetch_global_quote` (`:392`) **always** raise
`AlphaVantageIdentityError` for an Indian ticker, **without ever issuing an HTTP request**.

## Why

The documented 3-tier cascade in the API docstring (`data.py:366-368`) and in
`source_preference_service.py:8-10` is **2-tier in practice**. If bfinance *and* yfinance both
fail, there is no third chance.

This is compounded by two things:

1. **The 25 req/day budget is configured** (`config.py:61-62`) for a tier that can never spend it.
2. **Every failure row is mislabeled `source_used="alphavantage"`** (issue 08), so the logs
   actively reinforce the false belief that Tier-3 runs.

To be clear about what is *not* a bug: this fails **loudly**, not silently.
`AlphaVantageIdentityError` is a `ProviderUnavailableError` → `:809-810` → `:833-834` raises →
503. The defect is the false documentation, the wasted budget, and the misleading logs.

## Decision needed

**Option A — implement the mapping.** Alpha Vantage does not cover NSE/BSE equities under their
native tickers. A `.NS` symbol would need to map to a supported symbol, and Alpha Vantage's
equity coverage is US-focused. **This option is probably not viable**, and that should be confirmed
before choosing it.

**Option B — remove Tier-3.** Delete the Alpha Vantage service, its budget config, its docs, and
its UI references. The cascade honestly becomes 2-tier. A 2-tier cascade that works is better than
a 3-tier cascade where the third tier is fiction.

**Option C — repurpose Tier-3 for a symbol set that actually works.** e.g. it could serve
`USDINR=X`-style FX or a global index if a genuine gap appears. Only worth doing if a real gap
exists today.

**Recommendation: Option B**, unless Phase 0 research surfaces a genuine NSE mapping.

## Proof of done

- [ ] A decision is recorded in this ticket's `## Comments` with the reasoning.
- [ ] The documented cascade in `data.py:366-368` and `source_preference_service.py:8-10` matches
      the implementation.
- [ ] The 25 req/day budget config is removed, or justified.
- [ ] The settings page no longer implies three tiers.
- [ ] `fetch_logs` never records a vendor that was not attempted (depends on issue 08).
- [ ] A test asserts the cascade depth and the vendor order for a `.NS` ticker matches the
      documentation.
- [ ] The `/api/v1/data/config` response describes the actual cascade.

## Notes

If Option B is chosen, this becomes a **breaking API documentation change**. Note it in the
release notes — several tickets and the CONTEXT.md architecture diagram describe a 3-tier cascade.

Refs: `../spec.md`, `app/services/alpha_vantage_service.py:34,72-91,339,392,809-810,833-834`, `app/api/data.py:366-368`, `app/services/source_preference_service.py:8-10`, `app/config.py:61-62`, `CONTEXT.md` §2
