# 12 — Contract P1 batch

Status: ready-for-agent | Pri: P1 | Owner: builder-C (backend only)

## Items

1. Issue-10 mock-200 remainder nulls (read that file first): realized-risk
   `:222-259`, stress `:839-862`, risk-score `:1032-1045`, liquidity `:812`.
   Null uncomputables, keep `error` keys, update pinned tests.
2. `ValidateTickerRequest max_length=10` (`schemas.py:165`) → 20 + regex
   `^[A-Z0-9\-\&\.]$` matching `portfolio._TICKER_PATTERN`.
3. DB ticker columns `String(10)` → `String(20)` (`models/database.py:16,44,75,97`;
   SQLite ignores length — safe without migration; note it).
4. Stress-test honors `request.tickers` (mirror `resolve_allocation` pattern
   used by neighboring endpoints) instead of ignoring it.
5. Rebalance: `price<=0` → HTTP 400 (not `or 100.0`); float qty (no `int()`
   truncation). Read the block first (`portfolio.py:890-897` area).
6. `PUT /config`: persist `cache_ttl_minutes` + `enable_cache` in
   `app_settings` (same store as `primary_source`) instead of echoing.
7. FX unknown pair raises instead of returning `1.0`
   (`currency_service.py:195-197`).

## Rules

Regression test per item. Full `pytest --no-cov -q` green + ruff clean.
Do NOT touch: auth/WS, Alembic, Unique/Check constraints, `add` renorm
behavior, HMM/copula/ADF research items, frontend files.
