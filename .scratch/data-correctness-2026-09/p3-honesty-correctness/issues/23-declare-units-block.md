# 23 — Declare a `units` block on every response field

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: —
Repo: `backend/`
Severity: **HIGH — root cause RC4**

## What

`market_cap` exists in **four spellings across three units** with no declaration at the quote
boundary:

```
bfinance:  data_service.py:934            _read(fast, "market_cap") or _read(info, "marketCap")   ← unit undeclared
yfinance:  data_service.py:981            market_cap or info.get("marketCap")                     ← absolute ₹
bfinance:  equity_research_service.py:87  r.market_cap or info.get("marketCapInCr")                ← ₹ Cr
bfinance:  company_data_service.py:186    r.market_cap * 1e7                                        ← absolute ₹
```

`_normalize_quote_payload` sanitises `market_cap` for **finiteness only**
(`data_service.py:867-869`) and declares **no unit** — unlike `get_fundamentals`, which converts
explicitly at `:183-186`.

## Why

The consumer is unit-sensitive. `analytics_engine.liquidity_analysis` compares `market_cap` against
**hardcoded absolute-rupee thresholds**:

```
analytics_engine.py:751   mc >= 500000000000.0    # ₹50,000 Cr
analytics_engine.py:755   mc >= 100000000000.0    # ₹10,000 Cr
analytics_engine.py:759   mc >=  10000000000.0    # ₹1,000 Cr
```

and its docstring says *"market cap in INR"* (`:714`).

So a **Cr-valued** reading on the bfinance `fast_info` path would drop a mega-cap by **two full
tiers**, and publish `market_cap_provenance: "measured"` (`:778`).

**User-visible symptom:** a mega-cap holding renders as "Tier 4 Smallcap" liquidity, with a
measured-looking provenance tag.

The same pattern repeats across the codebase:

| Quantity | Convention conflict |
|---|---|
| `Ratios.roe` / `info["returnOnEquity"]` | bfinance's `Ratios.roe` is **percent** (14.5); bfinance's own `info["returnOnEquity"]` is a **fraction** (`r.roe/100`); yfinance is a **fraction** |
| `returnOnCapitalEmployed` | **percent** in bfinance, fraction in yfinance — fixed in Phase 1 issue 08, but the app must know which it is receiving |
| `dividendYield` | percent in both (verified) — consistent, but only by coincidence |
| `trailingPE` | ratio; the `or` fallback at `:187-190` maps a genuine `0.0` to the alternate key |

## Change

- Every response field that crosses the vendor boundary carries a **declared unit**. The codebase
  already does this in some places — `stress-testing` publishes a `units` object, and
  `analytics_engine` publishes `market_cap_provenance`. Extend that convention rather than
  inventing a second one.
- Normalise at the boundary: `data_service.py` should return **one canonical unit per field**, and
  the `units` block states it. Internal functions may use whatever is convenient as long as the
  boundary is unambiguous.
- Add a units registry so the declaration is not hand-maintained per endpoint and can be tested.
- Fix the `or` fallback at `:187-190` to an `is not None` test.
- `equity_research_service.py:94` has a latent version of the same bug: `"roe": r.roe if r.roe is
  not None else info.get("returnOnEquity")` — `r.roe` is percent, `info["returnOnEquity"]` is a
  fraction. It is currently unreachable because bfinance's `info` is derived from the same `r.roe`,
  but the next bfinance version that populates `returnOnEquity` independently re-arms it. Fix it
  now while the units work is open.

## Proof of done

- [ ] Every response containing a numeric field also contains a `units` block naming each field's
      unit. A test iterates the response schemas and fails on any missing declaration.
- [ ] `market_cap` has exactly one unit at the API boundary. A test asserts it against a known
      value.
- [ ] The liquidity tier for a known mega-cap is correct. A test uses a real large-cap and asserts
      the tier.
- [ ] `market_cap_provenance` is honest — it does not say `"measured"` for a value whose unit was
      inferred.
- [ ] `roe`, `roce`, and `returnOnEquity` are each declared, and the RO* keys in one response are
      mutually consistent.
- [ ] `equity_research_service.py:94`'s latent percent/fraction bug is fixed.
- [ ] The `or` fallback at `:187-190` uses `is not None`.
- [ ] The units registry is the single declaration point; grep finds no per-endpoint hand-written
      unit strings.

## Notes

This is the systemic fix for RC4. Issue 24 removes the frontend's guesswork that compensated for
it. Together they replace "guess the scale" with "read the declaration".

Refs: `../spec.md`, `backend/app/services/data_service.py:183-190,867-869,914-916,934,940,981,987`, `backend/app/services/equity_research_service.py:87,94`, `backend/app/services/company_data_service.py:183-186,193,196,262-266`, `backend/app/services/analytics_engine.py:714,751,755,759,778`
