# Backend code audit — consolidated index

Status: **complete** (audit + fix session + adversarial Wave-3 review, all findings closed)
Date: 2026-09-22 (audit) / 2026-09-23 (fix session + review + review-fix pass)
Scope: all first-party backend Python (`backend/app/`, `backend/main.py`, `backend/migrations/`, root scripts; `.venv` excluded). Line-by-line review by 6 parallel subagents.
Fix session: see [FIX-REPORT.md](FIX-REPORT.md) — **~138 fixed** / 46 already-fixed / ~61 skipped-refuted backlog / 3 refuted; ruff clean; **full suite 537 passed / 0 failed**; prod `daisy.db` byte-identical across suite runs; scope guard clean (no commits, frontend/pyproject/uv.lock untouched, ruff scope unchanged).

## Coverage

| Report | Area | Files |
|---|---|---|
| [01-api-analytics.md](01-api-analytics.md) | API: analytics routes | `app/api/analytics.py` (2020) |
| [02-api-rest-main.md](02-api-rest-main.md) | API: REST + websocket + entrypoint | `portfolio.py`, `data.py`, `equity_research.py`, `websocket.py`, `main.py` |
| [03-core-services.md](03-core-services.md) | Core services | `analytics_engine.py`, `data_service.py`, `cache_service.py` |
| [04-quant-services.md](04-quant-services.md) | Quant/risk services | regime, volatility, tail_risk, optimization, monte_carlo, cointegration, correlation, backtest, indicators, benchmark |
| [05-market-data-services.md](05-market-data-services.md) | Market-data / provider services | alpha_vantage, india_data, currency, screener, equity_research, company_data, source_preference, ai_dossier |
| [06-foundation.md](06-foundation.md) | Models, config, DB, utils, migrations, root scripts | `schemas.py`, `database.py`×2, `config.py`, `utils/*`, `migrations/*`, root test scripts |

## Totals (severity-tagged findings)

| Severity | Count | Meaning |
|---|---|---|
| P0 | 1 | security / crash / data loss |
| P1 | 33 | real bug, wrong result |
| P2 | 76 | improvement worth doing |
| P3 | 97 | nit / optional |

~120 bug findings total across all areas (incl. untagged P2/P3 bugs).

## Fix session 2026-09-23 (complete: waves 1–3 + review-fix pass)

Annotated statuses across reports 01–04+06 (205 findings): **fixed 120 · already-fixed 33 · skipped 47 · partially 2 · n/a 2 · handoff-only 1**. Report 05 (42 findings, table format): 7 fixed · 13 already fixed · 2 refuted · 15 skipped · 5 verified-clean.

- **Wave 4** (closing report handoffs/review leftovers): 7 fixes — identity-check + mock-detection unification, `RuntimeError`→503 ×10 routes, `analytics_cache` unique-index self-heal in `init_db`, flaky-test tolerance, `risk_free_rate`→Settings, 4-file utcnow sweep; mojibake refuted.
- **Wave 3 adversarial review** initially FAILED (2 P1 + 1 P2 + 1 P3, all new — not report findings): prod-DB mutation via test lifespan → **fixed** (tmp-engine `client` fixture, hash-identical acceptance); false report claim → **corrected**; `validate_ticker` unguarded vendor call → **fixed** (+regression test); 14 utcnow residuals → **fixed**.
- Combined report-finding fixes: **~138 fixed** / 46 already-fixed / ~61 skipped-refuted backlog / 3 refuted (B-02, B-12, mojibake).
- Final gates: ruff clean · **full pytest 537 passed / 0 failed** · banned-placeholder greps clean · scope guard clean (HEAD `13d89ed`, no commits, frontend/pyproject/uv.lock untouched) · `daisy.db` byte-identical across suite runs. Deliberately-skipped reasons + open handoffs: [FIX-REPORT.md](FIX-REPORT.md).

## Top findings per area

### 01 — api/analytics.py
1. ~~**[P1]** `analytics.py:97` — `_q` passes NaN through; Starlette `allow_nan=False` turns one NaN quantstats metric into a tear-sheet 500 (verified by execution).~~ **FIXED 2026-09-23** — `_q` returns None for non-finite; regression test in `test_coverage_analytics_extended.py`.
2. ~~**[P1]** `analytics.py:1655` — single-holding optimize returns fabricated `0.12/0.22/0.45` metrics, violating the metric-hygiene invariant; no test covers the branch.~~ **FIXED 2026-09-23** — placeholder grep clean; single-holding branch computed from real returns.
3. ~~**[P1]** `analytics.py:609` — factor-exposure error paths re-emit the banned `{alpha: 0.0, market: 1.0}` placeholder ("β +1.000 Market-Like" regression).~~ **FIXED 2026-09-23** — API + engine (`analytics_engine.py:1259`) both return `alpha/market: None`; test asserts shape.

### 02 — api REST + main
1. ~~**[P0]** `main.py:175` + `websocket.py:260` — no auth on destructive API, default `0.0.0.0` bind, WS `token` param accepted but never validated.~~ **RESOLVED 2026-09-22** — app is localhost-only single-user (auth YAGNI); bound to `127.0.0.1` (`main.py:175`, `config.py:17`), dead `token` param removed from `websocket.py:260`. Revisit auth only if exposed beyond localhost.
2. ~~**[P1]** `portfolio.py:755,796` — `export/csv` returns `-> str` → FastAPI serves JSON-quoted body (verified empirically); frontend saves broken .csv.~~ **FIXED 2026-09-23** — real CSV bytes; tests assert `text/csv` + attachment + raw newlines.
3. ~~**[P1]** `portfolio.py:413` — `auto_normalize` normalizes only newly-added weights → global weight sum >1 on non-empty portfolios.~~ **FIXED 2026-09-23** — DB-wide sum==1.0 asserted with pre-existing holdings.

### 03 — core services
1. ~~**[P1]** `analytics_engine.py:1170` — missing/failed benchmark leg overwrites valid per-position regressions with banned `{alpha:0, market:1}` placeholder (reachable via `analytics.py:652-663`).~~ **FIXED 2026-09-23** — engine returns `None` (`analytics_engine.py:1259`).
2. ~~**[P1]** `data_service.py:840` — `".BSE" in normalized_ticker` never true for canonical `.NS`/`.BO` tickers → every Alpha Vantage fallback quote gets `is_indian=False`.~~ **FIXED 2026-09-23** — `is_indian=True` asserted for `RELIANCE.NS` AV-fallback path.
3. ~~**[P2]** `analytics_engine.py:982` — `arch_model.fit` runs synchronously inside async GARCH/EGARCH forecasts, blocking the event loop per ticker.~~ **FIXED (already in session)** — `asyncio.to_thread` + sentinel test in `test_bugfix_core_services.py`.

### 04 — quant services
1. ~~**[P1]** `cointegration_service.py:255` — pair cache key omits `p_value_threshold`/`include_spread_series` → stale `is_cointegrated`/`signal`/`spread_series` (DB key at `:36` too).~~ **FIXED 2026-09-23** — both mem and DB keys include the params (`cointegration_service.py:56,71`).
2. ~~**[P1]** `tail_risk_service.py:76-81` — ~30–99-day histories skip GPD fit but return fabricated `gpd_shape_xi=0.15`, `beta=std·0.5`, `hist·1.15` under EVT keys — fabrication class of already-fixed P0-6.~~ **FIXED 2026-09-23** — historical-only path returns `model_fitted=False`, no fabricated xi (`tail_risk_service.py:86-129`).
3. ~~**[P1]** `indicators_service.py:146/209` — warmup buffer conflates calendar/trading days → `close_200_sma` structurally null at default lookback 90; `verified_snapshot` hardcodes `lookback_days=5`, making its parameter dead.~~ **FIXED 2026-09-23** — `look_back_days` honored exactly; test asserts `len(recent_closes) == 10`.

### 05 — market-data services
1. ~~**[P1]** `company_data_service.py:138,145,148` — `market_cap`/`dividend_yield`/`return_on_equity` change units (₹Cr vs ₹, % vs fraction) with the bfinance↔yfinance cascade tier → ~100–10⁴× wrong values when source preference flips.~~ **FIXED/ALREADY-FIXED 2026-09-23** — B-01 `*1e7`, B-03 `*100`, B-11/B-13 unit fixes verified (B-02 dividend flip refuted by contract).
2. ~~**[P1]** `alpha_vantage_service.py:263` — `TIME_SERIES_DAILY` omits `outputsize="full"` → ~100-session compact default silently truncates 10-year fetches, stored/served as success.~~ **FIXED (already in session)** — `outputsize: "full"` at `alpha_vantage_service.py:279`.
3. ~~**[P2]** `equity_research_service.py:121` / `screener_service.py:252` — upstream failures wrapped as `ValueError` → vendor outages reported as 404/400 instead of 503.~~ **FIXED 2026-09-23 (Wave 4)** — services raise `RuntimeError` (B-05/B-06), `api/data.py:118` maps to 503, and all 10 vendor routes in `api/equity_research.py` now map `RuntimeError` → 503; regression test `test_bugfix_equity_research_503.py`.

### 06 — foundation
1. ~~**[P1]** `migrations/add_portfolio_columns.py:51` — migration fabricates `quantity=100.0, buy_price=market_value/100.0` for legacy rows → permanent wrong P&L, no backup.~~ **FIXED 2026-09-23** — `quantity=100.0` clause removed (comment confirms).
2. ~~**[P1]** root scripts are traps: `test_bulk_operations_integrity.py:14` imports nonexistent `create_database_engine` (dead); its cleanup `:271` deletes real holdings; `test_api_integrity.py:44` pollutes live portfolio with no teardown.~~ **FIXED 2026-09-23** — all three trap scripts deleted (`test_bugfix_foundation.py` asserts absence).
3. ~~**[P1]** `db/database.py:43` — `makedirs` runs after `create_all`; sqlite crashes `unable to open database file` when `./data` missing (CWD-dependent URL, `config.py:14`).~~ **FIXED 2026-09-23** — directory creation documented/ordered before `create_all` (`database.py:38`).

## Cross-cutting themes

1. **Fabricated metric fallbacks** (01.2, 01.3, 03.1, 04.2) — placeholder/synthetic values served as real data; violates repo metric-hygiene invariant; needs one shared "unavailable" response convention.
2. **Auth gap** (02.1) — only P0; destructive endpoints + `0.0.0.0` bind + unvalidated WS token.
3. **Cache-key staleness** (04.1) — params missing from cache keys.
4. **Unit instability across provider cascade** (05.1) — same field, different units per tier.
5. **Blocking sync work in async handlers** (03.3, also noted in 01/05) — event-loop stalls.

## Suggested fix order

1. P0 auth/bind issue (02.1)
2. Migration data fabrication (06.1) — already-persisted wrong data may need repair
3. Shared "no value" convention killing fabricated fallbacks (01.2/01.3, 03.1, 04.2)
4. CSV export content-type (02.2) and weight normalization (02.3) — user-visible corruption
5. Unit stabilization in company_data cascade (05.1), AV `outputsize` (05.2), BSE detection (03.2)
6. Cache-key fixes (04.1), indicator warmup (04.3), error-mapping convention (05.3)
7. Async blocking sweeps (03.3 et al.), then P2/P3 backlog per report
