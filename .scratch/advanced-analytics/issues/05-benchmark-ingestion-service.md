# 05 — Benchmark ingestion service (^NSEI cached)

Status: resolved (2026-08-25) - app/services/benchmark_service.py; ^NSEI via shared cache (492 days live-verified); Yahoo-native symbol passthrough added to _normalize_indian_ticker.
Type: task
Blocked by: —

## What
New `app/services/benchmark_service.py`: fetch ^NSEI (NIFTY 50) daily OHLCV via existing
DataService into `stock_timeseries` (ticker `^NSEI`), once per day max. Expose helper
`get_benchmark_returns(start, end)`. Wire it into analytics endpoints where benchmark matters
(beta/R²/factor exposure) instead of the current empty-series fallback
(`analytics_engine.py:153-157`).

## Why
Unlocks beta vs market, R², regime detection, and honest tear-sheet comparisons.

## Proof of done
- [ ] `stock_timeseries` contains ^NSEI rows after one call.
- [ ] Second call same day hits cache (no yfinance request).