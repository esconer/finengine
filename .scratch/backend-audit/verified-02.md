# Verification: 02-api-rest-main.md

Counts: confirmed 49 · refuted 0 · already-fixed 1 · total 50

Line numbers may drift ±3 only in `backend/main.py`, `backend/app/config.py`, `backend/app/api/websocket.py`. All other lines are exact.

## Bugs

P0/security-auth-bind | P0 | already-fixed | config `api_host` default 127.0.0.1 (config.py:17); uvicorn `host="127.0.0.1"` (main.py:175); WS endpoint is `websocket_endpoint(websocket, client_id)` with no `token` param (websocket.py:260) — three cited facts hold; no-auth surface and any Dockerfile `0.0.0.0` residual remain open questions outside the three facts | main.py:175, config.py:17, websocket.py:260 | backend/main.py, backend/app/api/websocket.py | n/a (facts confirmed only)

csv-export-json-encoded | P1 | confirmed | `export_portfolio_csv(...) -> str` returns bare `csv_content` with no `media_type` (portfolio.py:755,796); frontend saves `response.text()` into a `Blob(type:'text/csv')` (dashboard/page.tsx:255-257); tests only substring-assert (test_coverage_portfolio_api.py:444) | portfolio.py:755,796 | backend/app/api/portfolio.py | Test asserts `content-type: text/csv` and a real newline between rows

bulk-auto-normalize-added-only | P1 | confirmed | `total_weight = sum(pos.weight for pos in added_positions)` then divides only those (portfolio.py:413-417); pre-existing holdings untouched so global sum can exceed 1.0 | portfolio.py:413 | backend/app/api/portfolio.py | Seed OLD.NS @0.5, bulk-add two @0.3/0.3 auto_normalize=true, assert total_weight==1.0

bulk-intra-payload-dedup | P1 | confirmed | membership test only against `existing_set` of DB tickers (portfolio.py:345-352); no payload-vs-payload dedupe; `ticker` column is `index=True` only, no unique (database.py:16) | portfolio.py:345, database.py:16 | backend/app/api/portfolio.py, backend/app/models/database.py | POST /bulk_add with same scrip twice → assert only 1 row inserted

ws-broadcast-dict-mutation | P1 | confirmed | `for ... in self.subscriptions.items():` (websocket.py:53) calls `send_personal_message` which can `self.disconnect(client_id)` (L49) mutating the dict mid-iteration | websocket.py:53,49 | backend/app/api/websocket.py | Force a send failure for client A during broadcast to 2 clients; B still receives; no RuntimeError

ws-client-id-overwrite | P1 | confirmed | `active_connections[client_id] = websocket` (L32) overwrites silently; later `disconnect(old_id)` (L36-40) deletes the new registration | websocket.py:32 | backend/app/api/websocket.py | Connect two sockets with same client_id; first is orphaned; disconnect first → second removed from maps

prod-middleware-os-getenv | P1 | confirmed | `if os.getenv("ENVIRONMENT", "development") == "production"` (main.py:79) bypasses pydantic `.env` loading; settings.environment is the pydantic field (config.py:50) | main.py:79 | backend/main.py | Unit test: set ENVIRONMENT=production in .env only, import app, assert TrustedHostMiddleware installed

data-source-hardcoded-yfinance | P1 | confirmed | `source="yfinance"` literal (data.py:337) while `_source_of_df` exists (data_service.py:113) and default primary is `bfinance` (source_preference_service.py:30) | data.py:337 | backend/app/api/data.py | Fetch with bfinance primary; assert response.source == "bfinance"

data-from-cache-probe-after-store | P1 | confirmed | `from_cache = not force_refresh and await _get_cached_data(...)` (data.py:308) runs after `fetch_historical_data` already stored fresh rows, so flag is True on vendor fetch | data.py:308 | backend/app/api/data.py | force_refresh=false first fetch → from_cache should be False; second GET → True

portfolio-currency-500 | P2 | confirmed | any `currency != 'INR'` reaches `convert_amount` → `ValueError` (currency_service.py:197) caught as 500 (portfolio.py:145-147) | portfolio.py:120,147 | backend/app/api/portfolio.py, backend/app/services/currency_service.py | GET /portfolio?currency=EUR → expect 400

rebalance-negative-unknown-weights | P2 | confirmed | only `sum_weights > 0` guard (portfolio.py:880); no per-weight `< 0` check; unknown keys skipped by `if pos.ticker in normalized_weights` (L888); sum≤0 falls back to raw weights | portfolio.py:880,888 | backend/app/api/portfolio.py | POST rebalance with weight -0.2 or unknown ticker → expect 400

bare-ticker-crud-no-canonical | P2 | confirmed | GET/PUT/DELETE look up `PortfolioPosition.ticker == ticker.upper()` (L553,619,710) while add stores `canonical_ticker` (L194) → bare `RELIANCE` stored as `RELIANCE.NS` is unreachable | portfolio.py:553,619,710 | backend/app/api/portfolio.py | DELETE /portfolio/RELIANCE after add("RELIANCE") → expect 200 not 404

add-provenance-hardcoded-yfinance | P2 | confirmed | `primary_source="yfinance", last_validated_source="yfinance"` (portfolio.py:222-223) regardless of actual quote vendor | portfolio.py:222 | backend/app/api/portfolio.py | Add with bfinance primary; assert stored primary_source=="bfinance"

ai-endpoints-valueerror-500 | P2 | confirmed | three AI routes only catch `Exception`→500 (equity_research.py:134,148,167) while siblings map ValueError→404 (L46-47 etc.); service raises ValueError for all failures (ai_dossier_service.py:50,70,86) | equity_research.py:134,148,167 | backend/app/api/equity_research.py, backend/app/services/ai_dossier_service.py | Unknown ticker on /ai-dossier → expect 404 not 500

custom-screen-no-bounds | P2 | confirmed | `CustomScreenRequest` fields are bare `Optional` with no ge/le (schemas.py:559-566); prebuilt route has `ge=5, le=100` (equity_research.py:185); custom path uses `max_stocks or 50` (L225) | schemas.py:559-566 | backend/app/models/schemas.py, backend/app/api/equity_research.py | POST /screens/custom max_stocks=10**9 → expect 422

ws-analytics-weights-uncovered | P2 | confirmed | weights built from all positions (websocket.py:153) but `price_df` only has tickers with timeseries (L185); engine renormalizes full dict (analytics_engine.py:62-64) and maps missing cols to 0 (L827) | websocket.py:153, analytics_engine.py:62-64,827 | backend/app/api/websocket.py, backend/app/services/analytics_engine.py | Add holding with no OHLCV; broadcast vol < same portfolio with data

str-e-leak-500 | P2 | confirmed | catch-alls re-raise `f"...: {str(e)}"` across portfolio.py/data.py/equity_research.py (e.g. portfolio.py:147); app-level handler already returns generic envelope (main.py:103-115) | portfolio.py:147 (+27,603,697,749,802,843,959; data.py; equity_research.py) | backend/app/api/*.py | Force internal exception; assert detail has no path/SQL substring

ws-status-always-connected | P3 | confirmed | `"status": "connected"` literal (websocket.py:321) regardless of `active_connections` | websocket.py:321 | backend/app/api/websocket.py | GET /ws/status with 0 connections → status != "connected"

health-env-hardcoded | P3 | confirmed | `"environment": "development"` literal (main.py:157) | main.py:157 | backend/main.py | Set ENVIRONMENT=production; /health still says development

normalize-method-ignored | P3 | confirmed | `method: str = Query(...)` (portfolio.py:807) never read; body only does proportional (L820-828); frontend passes method (api.ts:187-189) | portfolio.py:807 | backend/app/api/portfolio.py | POST /normalize?method=equal → same as proportional (document or drop)

put-ticker-currency-dead | P3 | confirmed | `currency: str = Query(...)` on PUT (portfolio.py:610) unused in handler body | portfolio.py:610 | backend/app/api/portfolio.py | Remove param or use it

bulk-prevalidation-unreachable | P3 | confirmed | `PortfolioPositionBase` already enforces gt/le via pydantic (schemas.py:14-16, validators 27-43) so handler checks at portfolio.py:296-305 and PUT rechecks L631-651 die at 422 first; only `_TICKER_PATTERN` (L309) is live in bulk | portfolio.py:296-305 | backend/app/api/portfolio.py, backend/app/models/schemas.py | Not directly testable as live path; remove dead branches

bulk-duplicates-not-reported | P3 | confirmed | filtered dupes only logged (portfolio.py:349,492-493); `BulkAddResponse` has no duplicates field (L495-499) | portfolio.py:495 | backend/app/api/portfolio.py | Response includes `duplicates: []` with skipped tickers

add-request-dump-dict | P3 | confirmed | `position.dict()` leftover Pydantic-v1 alias in INFO dump (portfolio.py:165) | portfolio.py:165 | backend/app/api/portfolio.py | Use model_dump(); drop or demote to debug

single-add-no-ticker-pattern | P3 | confirmed | `_TICKER_PATTERN` only used at L309 (bulk) and L517 (bulk helper); `POST /add` relies on network `validate_ticker` only (L170) | portfolio.py:170,309 | backend/app/api/portfolio.py | Same format check as bulk on single add

batch-dead-kwargs | P3 | confirmed | `source_used='yfinance', fetch_status='fresh'` passed into `StockDataResponse` (data.py:414-415) which has neither field (schemas.py:106-115) — Pydantic v2 drops extras | data.py:414-415 | backend/app/api/data.py | Remove dead kwargs

config-get-swallows-errors | P3 | confirmed | `except Exception` returns hardcoded defaults as 200 (data.py:190-199) | data.py:194-199 | backend/app/api/data.py | Break DB read; GET /config still 200 defaults (documented as intentional?) → propagate 5xx

config-put-empty-success | P3 | confirmed | no-param PUT returns `updated: True, settings: {}` (data.py:247-251) | data.py:247 | backend/app/api/data.py | PUT /config with no query → 400 or updated:false

excel-content-disposition-inject | P3 | confirmed | `filename` from raw path param with only .NS/.BO stripped, embedded in quoted header (equity_research.py:106-111) | equity_research.py:111 | backend/app/api/equity_research.py | Ticker containing `"` → header breaks; sanitize/encode filename

ws-equalweight-fallback-clean | P3 | confirmed | equal-weight branch only when MV and stored weights both sum ≤0 (websocket.py:155-160) — report correctly marks this clean | websocket.py:155-160 | backend/app/api/websocket.py | n/a (clean note)

## Improvements

response-construction-dup-x4 | P2 | confirmed | identical 16-field `PortfolioPositionResponse(...)` copy-pasted at portfolio.py:243-260, 472-489, 580-597, 673-690 | portfolio.py:243,472,580,673 | backend/app/api/portfolio.py | Extract `_position_response(position, ...)`

get-ticker-network-write-on-read | P2 | confirmed | `GET /{ticker}` does `fetch_quote` + `db.commit()` unconditionally (portfolio.py:564-569) with no staleness gate | portfolio.py:564-569 | backend/app/api/portfolio.py | Use `_update_portfolio_prices` 15-min rule or read-only

staleness-keyed-on-updated-on | P3 | confirmed | `_update_portfolio_prices` keys on `updated_on` (portfolio.py:1078); weight edits/normalize also bump `updated_on` (L662,829) | portfolio.py:1078 | backend/app/api/portfolio.py | Dedicated `price_updated_on` column

get-data-service-duplicated | P3 | confirmed | same `get_data_service` def in data.py:31 and portfolio.py:39 (and analytics.py:47) | data.py:31, portfolio.py:39 | backend/app/api/*.py | Move to `app/api/deps.py`

data-midfile-import | P3 | confirmed | `from app.models.schemas import (StockTimeseriesResponse)` sits after router def (data.py:46-48) | data.py:46 | backend/app/api/data.py | Hoist into top import block L18-21

screener-singleton-vs-per-request | P3 | confirmed | custom screen uses first-call-wins `get_screener_service()` (equity_research.py:218, screener_service.py:352-359, defaults db_session=None) while prebuilt builds per-request with comment "must not live in module-global" (L196-203) | equity_research.py:218 | backend/app/api/equity_research.py, backend/app/services/screener_service.py | Construct per-request for custom too

format-shadows-builtin | P3 | confirmed | `format: str = Query(...)` (equity_research.py:156) shadows builtin, unvalidated until service Literal | equity_research.py:156 | backend/app/api/equity_research.py | Rename to `output_format`; validate in route

lifespan-no-cleanup | P3 | confirmed | lifespan only logs after yield (main.py:64-65); `close_db_connections` exists (db/database.py:99) but never called (repo grep = definition only); `update_task` not cancelled | main.py:54-65 | backend/main.py | Call close_db_connections + cancel update_task in shutdown

bulk-response-missing-duplicates-field | P3 | confirmed | same root as bulk-duplicates-not-reported (portfolio.py:495-499) | portfolio.py:495 | backend/app/api/portfolio.py | Add `duplicates: List[str]` to BulkAddResponse

config-get-error-style-divergence | P3 | confirmed | GET /config converts failures to 200-defaults (data.py:190-199) while sibling handlers use 4xx/5xx — real divergence | data.py:190 | backend/app/api/data.py | Align once QH-04 lands

## Optimizations

from-cache-double-read | P2 | confirmed | same probe as data-from-cache-probe-after-store (data.py:308) re-reads full window via `_get_cached_data` purely for existence | data.py:308 | backend/app/api/data.py | Plumb hit flag from fetch_historical_data

timeseries-quote-every-get | P2 | confirmed | `fetch_quote(ticker)` on every GET (data.py:312) with no TTL for sector/industry metadata | data.py:312 | backend/app/api/data.py | Cache quote or reuse 15-min portfolio rule

ws-triple-select-no-topic-gate | P2 | confirmed | three `select(PortfolioPosition)` per cycle (websocket.py:103,135,211) + 1y timeseries load + full analytics recompute; topic filter only at broadcast (L54) | websocket.py:103,135,211 | backend/app/api/websocket.py | Fetch once/cycle; skip senders with zero subscribers (QH-05)

custom-screen-no-cache | P2 | confirmed | `run_custom_screen` has no L1/L2 path; singleton has `cache_service=None` so `_get_cached_screen` returns None (screener_service.py:120-121); `run(max_stocks=None)` full scan (L316) | screener_service.py:316,120 | backend/app/services/screener_service.py, backend/app/api/equity_research.py | Two-layer cache keyed on filter hash

currency-convert-in-loop | P3 | confirmed | `await convert_amount` per position inside loop (portfolio.py:120-123) | portfolio.py:120-123 | backend/app/api/portfolio.py | Convert total once after loop

bulk-refresh-n-selects | P3 | confirmed | `for position in added_positions: await db.refresh(position)` (portfolio.py:453-454) | portfolio.py:453 | backend/app/api/portfolio.py | expire_on_commit=False or single IN-query

bulk-validate-sequential-then-gather | P3 | confirmed | `for ... validate_ticker` sequential (portfolio.py:326-328) before concurrent quote gather (L367) | portfolio.py:326 | backend/app/api/portfolio.py | Semaphore+gather for STEP 2 (QH-06)

add-network-validate-before-dup-check | P3 | confirmed | network `validate_ticker` at L170 runs before local dup check at L197-199 — 409 wastes upstream call | portfolio.py:170,197 | backend/app/api/portfolio.py | Reorder: canonical dup-check first

iterrows-rowwise-pydantic | P3 | confirmed | `for _, row in df.iterrows():` building StockDataResponse (data.py:322,404) | data.py:322,404 | backend/app/api/data.py | df.to_dict("records") / itertuples

refresh-endpoint-sequential | P3 | confirmed | `for ticker in tickers: await fetch_historical_data(...)` (data.py:466) | data.py:466 | backend/app/api/data.py | Semaphore(5)+gather like bulk add
