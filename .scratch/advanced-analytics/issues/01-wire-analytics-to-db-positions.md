# 01 — Wire analytics endpoints to DB positions

Status: resolved (2026-08-25)
Type: task
Blocked by: —

## Resolution
All nine analytics endpoints default to `_load_portfolio_allocation(db)` (market-value weights,
fallbacks to weight column then equal). Explicit `tickers=` still overrides; empty portfolio returns
clean error payloads. Bonus fixes surfaced by the new test suite:
- `analytics.py` liquidity now maps lowercase `volume` and emits engine-shaped Close/Volume frames.
- Price series passed to the engine are date-indexed via `_price_series()` — fresh-fetch rows were
  integer-indexed, crashing stress-test scenario windows (`int64 vs str`).

## Proof of done
- [x] `pytest tests/test_api_endpoints.py -k Analytics` → 11/11 (real engine math, isolated test DB,
      seeded positions; concentration asserts exact 21000/39000 largest-weight).
- [x] Full backend suite green (88 passed).


## What
All nine endpoints in `backend/app/api/analytics.py` currently fall back to a hardcoded demo
portfolio (`AAPL,MSFT,GOOGL,AMZN` @ 25% each — lines 66, 160, 246, 312, 354, 410, 457, 501, 546).
Add a `_load_portfolio_allocation(db)` helper that reads `PortfolioPosition` rows and returns
`{ticker: weight}` (use stored `weight`; if total weight ≤ 0, derive from `market_value`).
Explicit `tickers=` query params keep working (equal weights); only the *default* changes to
the user's actual holdings. Empty portfolio → existing "no data" payloads with a clear message.

## Why
The product's core promise is analytics on YOUR holdings; today six pages show numbers that
belong to a fake portfolio. Spec §F1 / Phase P0.

## Proof of done
- [ ] With ≥1 position in DB, `/analytics/concentration`, `/risk-score`, `/summary`,
      `/stress-test`, `/volatility-sizing`, `/liquidity` all reflect those tickers.
- [ ] Explicit `tickers=INFY.NS,TCS.NS` still overrides.
- [ ] Empty DB returns clean error payload, not demo tickers.
- [ ] `pytest tests/test_api_endpoints.py --no-cov -k analytics` passes (update any test that
      asserted demo defaults — behavior change is intentional).

Refs: `.scratch/advanced-analytics/spec.md`
