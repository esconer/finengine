# 22 — Alpha Vantage as fallback data vendor

Status: closed
Type: task
Blocked by: —

## Progress
- [x] DONE core (2026-08-25): `app/services/alpha_vantage_service.py` with
      **multi-key rotation pool** (user directive): N free keys → N×25 req/day,
      N×5 req/min. Per-key budgets tracked in-process; daily-limit notice retires
      key until midnight, frequency notice applies 60s cooldown, invalid keys are
      dropped. Exhausted pools raise locally WITHOUT network calls.
      DataService fallback wired: `_fetch_from_alpha_vantage` (after 3 yfinance
      retries) + `_fallback_quote` (on quote failure/empty); rows stored with
      `source_used='alphavantage'`, FetchLog `fallback_attempt=True`.
      `.env.example` documents single/multi-key setup.
      Offline verification: rotation order, retire-honored-on-retry, cooldown-
      then-reuse, budget guard (0 network calls when exhausted), no-key no-op,
      symbol bridge .NS→.BSE. One real bug found & fixed during tests:
      local-budget exhaustion raised NotConfiguredError instead of RateLimitError.
- [x] DONE pytest coverage (2026-08-25): `tests/test_alpha_vantage.py` — rotation on daily
      limit, retire-honored-on-retry, frequency cooldown→reuse, local budget guard (zero wasted
      network calls), no-key no-op, symbol bridge. Part of the 88-test green suite.
- [ ] Pending: live test with real key(s) — user to add ALPHA_VANTAGE_API_KEYS to backend/.env;
      then force a yfinance failure and confirm AV rows land in stock_timeseries.

## What
Wire Alpha Vantage behind yfinance as automatic fallback in `DataService`:
- New `app/services/alpha_vantage_service.py` (patterns adapted from
  TauricResearch/TradingAgents `dataflows/alpha_vantage_common.py`, Apache-2.0):
  - `TIME_SERIES_DAILY` OHLCV → our lowercase schema (adj_close := close; TS-DAILY is
    unadjusted — noted in metadata)
  - `GLOBAL_QUOTE` partial quote fill (price/volume/range; no sector/fundamentals)
  - Symbol bridge: `.NS` → `.BSE` (AV has no NSE feed; BSE covers the same companies;
    minority symbol-mismatch risk documented)
  - Free-tier budget guard: 25 req/day + 5 req/min tracked in-process BEFORE spending calls;
    disabled entirely when `ALPHA_VANTAGE_API_KEY` unset
  - Error taxonomy per TradingAgents #991: classify "Information"/"Note" payloads —
    rate-limit phrasing checked BEFORE "api key" phrasing (both mention "API key")
- `DataService.fetch_historical_data`: after 3 yfinance retries exhausted → AV fallback →
  store via `_store_timeseries_data(source_used="alphavantage")` + FetchLog
  `fallback_attempt=True`
- `DataService.fetch_quote`: on yfinance failure/empty → AV partial quote

## Why
Resilience against Yahoo rate-limits/outages; user directive. Free tier sized for a personal
daily-refresh dashboard (cache-first design already in place).

## Proof of done
- [ ] Offline test with mocked AV response: fallback stores rows with
      `source_used='alphavantage'`; schema matches cache expectations.
- [ ] No key configured → zero AV calls attempted, yfinance-only behavior unchanged.
- [ ] Budget guard blocks >25 calls/day locally without network round-trip.
