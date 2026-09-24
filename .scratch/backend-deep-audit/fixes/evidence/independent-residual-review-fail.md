# Independent residual review — FAIL capture

Date: 2026-09-24
Mode: read-only; isolated in-memory/temp SQLite; no Docker, live provider, or `backend/data/daisy.db` access.

## Findings

- **Health — FAIL:** actual production ASGI probe with `follow_redirects=False` returned `307` for `/health` and `/api/v1/health`; ordinary routes also returned `307`. The subclassed `dispatch` method is bypassed by the installed Starlette ASGI `__call__` path.
- **Quote generation — FAIL:** historical OHLCV startup/direct-upsert fences passed (`3 passed`), but a quote-purge race left `_quote_memo` populated because `fetch_quote()` captured generation after startup awaits.
- **Mixed currency — PASS:** `100 USD + 80 INR = 8080 INR`; rebalance targets `0.505` AAPL shares and `50.5` TCS shares; sizing received `8080`; live `USD->INR` provenance.
- **FX status — PASS:** marked fallback and unlabelled numeric rates rejected; portfolio, rebalance, volatility-sizing, and concentration returned `503: Live FX unavailable`.
- **EWMA — PASS:** one-return portfolio sizing returned `recommended_weights={}` and `Insufficient data for volatility sizing`.
- **MFI/risk — PASS with caveat:** invalid-price MFI returned `nan`; sparse/underdetermined tests passed, but a disjoint-history probe exposed ambiguous global `excluded_assets` disclosure.
- **Backup — PASS:** private-mode harness passed; destination was `0600` before content write; `bash -n scripts/deploy.sh` passed.
- **Finite request values — PASS:** create/update quantity and buy-price `+inf` each raised `ValidationError`.

Focused verifier command result: `27 passed, 64 deselected in 18.20s`.
Overall verdict: **FAIL**. Follow-up fixes are required before closure.
