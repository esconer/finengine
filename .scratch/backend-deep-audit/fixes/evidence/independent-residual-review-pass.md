# Independent residual review — final PASS capture

Date: 2026-09-24
Mode: read-only; isolated in-memory SQLite; no Docker, live provider, or `backend/data/daisy.db` access.

## Final verdict: PASS — 8/8

| # | Finding | Result |
|---|---|---|
| 1 | Production health endpoints | `/health=200`, `/api/v1/health=200`; ordinary routes `307` with `ENVIRONMENT=production` and `follow_redirects=False`. |
| 2 | Mixed-currency rebalance/sizing | `8000 INR + 80 INR = 8080 INR`; stale values ignored; AAPL target `0.505` native shares, TCS target `50.5`; sizing portfolio value `8080`; live FX provenance. |
| 3 | Generation fences | Historical startup/direct-upsert regressions passed; quote purge-during-startup left `_quote_memo` empty. |
| 4 | FX rejection/status | Fallback and unlabelled rates rejected; portfolio, rebalance, volatility, and concentration returned `503: Live FX unavailable`. |
| 5 | One-return EWMA | `recommended_weights={}`; `Insufficient data for volatility sizing`. |
| 6 | MFI/risk disclosure | Invalid-price MFI=`nan`; disjoint history returned model-scoped `excluded_assets={'volatility':['A'],'cvar_tail':['B']}`. |
| 7 | Private backup | Backup permission test passed; destination mode `0600` before copy; `bash -n scripts/deploy.sh` passed. |
| 8 | Finite request money | Create/update `quantity` and `buy_price` `+inf` each raised `ValidationError`. |

## Exact final gates

- Focused residual files: **103 passed**.
- Integrated regression set: **223 passed**.
- A focused quant gate: **166 passed**, 12 existing statsmodels warnings.
- B provider/cache gate: **137 passed**.
- C contract gate: **39 passed**.
- D migration/deployment gate: **19 passed**.
- API endpoints + C contracts: **77 passed**.
- C/API/WebSocket/portfolio gate: **114 passed**, 2 existing SQLAlchemy warnings.
- Foundation/migration/deployment/cache gate: **39 passed**.
- Coordinator oracle: **10 passed, 0 failed**.
- Backup-specific test: **1 passed**.
- `bash -n scripts/deploy.sh`: **PASS**.

Docker/container runtime execution remains intentionally unverified because it was excluded by the read-only verification constraints.

A subsequent user-authorized compatibility follow-up added `GET /v1/models` with the honest OpenAI-shaped empty list response; its focused API suite is **39 passed**, the independent endpoint verifier is **PASS**, and the refreshed integrated set is **224 passed**.
