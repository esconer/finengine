# 21 — Adopt TradingAgents dataflows components

Status: ready-for-agent
Type: task
Blocked by: —

## Progress
- [x] Slice 1 DONE (2026-08-25): `app/services/indicators_service.py` +
      `GET /data/indicators/{ticker}` + `GET /data/verified-snapshot/{ticker}`;
      `stockstats==0.6.8` added. Verified live: RELIANCE.NS indicators (rsi/macd/close_50_sma),
      TCS.NS snapshot, 400 on unknown indicator. Attribution header present.
- [x] Slice 2 DONE (2026-08-25): `GET /data/fundamentals/{ticker}` — curated ~28-field snapshot
      with stub-info guard. NOTE: Yahoo currently rejects `.info` with 401 Invalid-Crumb
      (transient, known yfinance pain) → endpoint correctly returns **503** with clear message;
      retry when Yahoo recovers.
- [x] Slice 3 DONE (2026-08-25): `GET /data/financials/{ticker}?statement=income|balance|cashflow&freq=quarterly|annual`
      — structured JSON (periods + metrics map), look-ahead filter ported. Verified live:
      TCS.NS quarterly income → 6 periods × 48 metrics.
- [x] Slice 4 DONE (2026-08-25): `GET /data/insider/{ticker}` — records list; verified live
      (INFY.NS → 200, count 0 is a normal response).
- New service: `app/services/company_data_service.py` (Apache-2.0 attribution header).


## What
Adapt selected modules from TauricResearch/TradingAgents `tradingagents/dataflows`
(Apache-2.0 — attribution required in source headers; modifications must be noted):

| Source module | What we take | Where it lands |
|---|---|---|
| `stockstats_utils.py` | 13-indicator curated set + bulk computation via `stockstats.wrap`; rate-limit backoff (`yf_retry`); stale-frame rejection (>10 days); same-day cache TTL concept | new `app/services/indicators_service.py`, fed by OUR SQLite cache instead of their CSV files |
| `market_data_validator.py` | "verified snapshot": fixed default indicator set + latest OHLCV row + recent closes as deterministic ground truth | `/api/v1/data/verified-snapshot/{ticker}` |
| `y_finance.py::get_fundamentals` | curated ~28-field fundamentals extraction incl. stub-info guard | extend `GET /api/v1/data/fundamentals/{ticker}` |
| `y_finance.py::get_balance_sheet/get_cashflow/get_income_statement` + `filter_financials_by_date` | quarterly/annual statements as structured JSON | new `/api/v1/data/financials/{ticker}` |
| `y_finance.py::get_insider_transactions` | free insider trades feed | `/api/v1/data/insider/{ticker}` |

NOT adopted (with reasons): crypto/forex/CFD symbol mapping (NSE-only focus),
polymarket/reddit/stocktwits sentiment (Tier E), alpha_vantage suites (API keys; yfinance
already covers), FRED (US macro).

## Why
Free pro-grade data inflows we'd otherwise hand-roll; user directive. Indicator coverage closes
the biggest gap vs any charting site while adding portfolio-context analytics they can't do.

## Proof of done
- [ ] `GET /data/indicators/RELIANCE.NS?lookback_days=30` returns RSI/MACD/etc. series.
- [ ] Verified-snapshot endpoint rejects stale frames (>10d gap) with explicit error.
- [ ] Attribution headers present; `uv add stockstats` in pyproject.
