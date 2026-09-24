# Audit Environment

**Status:** complete with explicit limitations  
**Captured:** 2026-09-24–25 UTC  
**Repository:** `C:\es\coding\finengine`

## Protected live stack

| Service | Address | Process | Audit use |
|---|---|---|---|
| Existing frontend | port 3000 | `next start` | Discovery only; not navigated for mutation testing |
| Existing backend | `127.0.0.1:8000` | `uvicorn main:app --reload` | Health/OpenAPI/build discovery only |

The existing backend was not proven to use an isolated database. A read-only portfolio probe returned 14 positions, so it is treated as protected/live. No CRUD, settings, cache purge, explicit refresh, analytics POST, or WebSocket broadcast was sent to port 8000. One later `GET /api/v1/portfolio` safety comparison was attempted and timed out; because the current GET implementation refreshes quotes and commits, the final integrity report must conservatively disclose that this read-only-by-intent request could have changed the live cache/position values.

## Isolated audit stack

| Service | Address | Process/database |
|---|---|---|
| Audit backend | `127.0.0.1:8001` | Python 3.12 / Uvicorn; `environment=testing`; absolute disposable SQLite path under `evidence/runtime/` |
| Audit frontend | `127.0.0.1:3001` | Next.js 16.3.6 production build from output-only frontend harness; API origin `http://127.0.0.1:8001/api/v1` |

Isolation proof:

- Audit backend health returned HTTP 200 with `environment=testing`.
- Audit portfolio initially returned zero positions and zero value.
- The live frontend `.next` directory was not overwritten.
- The audit frontend build ID is `hghBG-hlr8-XxzAq9sTq3`.
- Synthetic positions were visible only through port 8001.

## Source/build identity

- Git HEAD: `e430e1e25e55bd53dbebe2a35b0af64dffda2eaa`.
- Branch: `master`, three commits ahead of `origin/master` at discovery.
- Working tree was already heavily dirty: 435 porcelain entries at baseline.
- Baseline status fingerprint: `E18BD3CEE798A4C6933DAB67F300F2AD5DBDD357B6D9D3F261978B3EE32DBB49`.
- Baseline diff fingerprint: `4F65216DB6D1FDF325AAE9AD8EDD3876EB0EE15706F37E91555E368FCFB238CE`.
- Existing frontend build ID: `GBC2suDDMSV5hpsFxVBf9`.
- The report must not claim that either build is exactly HEAD because the tree is dirty.

## Browser

- Automation CLI: `agent-browser 0.38.1`.
- Browser: Chrome for Testing `152.0.7977.54`.
- Named session: `finengine-browser-e2e`.
- Allowed browser origins: `127.0.0.1` and `localhost` only.
- Desktop viewport: `1440×900`, DPR 1.
- Mobile viewport: `390×844`, DPR 1.

## Protected database baseline

Read-only shared-handle SHA-256 values captured without opening SQLite:

| File | SHA-256 |
|---|---|
| `backend/data/daisy.db` | `41CC3DAD505E5BD4CEB70AC94FC23E144B7B7C450714233391D8537EAAE3B4E5` |
| `backend/data/daisy.db-wal` | `28111EB61F96E0D3D2AA122F319B586EA4C4334F80FB64CB78089E1394214B22` |
| `backend/data/daisy.db-shm` | `318BC973F5AEAC98653B8A8625FE49E9B5569903569EDD9D58EB4CDFA4F0CB0F` |

These values must be recomputed at audit end. Any difference must be reported as an integrity/environment issue unless audit actions are independently proven not to have touched the file.

## Final isolated-state checks

- Final isolated portfolio probe returned HTTP 200 with exactly five canonical tickers: `RELIANCE.NS`, `HDFCBANK.NS`, `TCS.BO`, `AAPL`, `MSFT`.
- Temporary `INFY.NS` and `BHARTIARTL.NS` rows were removed after import/add tests.
- The primary data-source preference was restored to `bfinance` after the yfinance interaction.
- Cache purge returned HTTP 200; the subsequent portfolio refresh returned HTTP 200 and preserved the five-position fixture.
- Browser interaction policy remained one short-lived Chrome-for-Testing instance per batch. Agent-browser Chrome processes were closed at the end; no audit browser process remains.
- Final state artifact: `evidence/runtime/final-isolated-state.json`.
- Final integrity artifact: `evidence/runtime/final-integrity.json` / `evidence/calculations/outputs/final-integrity.md`.
- Main `backend/data/daisy.db` hash still matches the baseline. The live `-wal` and `-shm` hashes differ from the baseline; because the existing backend is protected and the earlier timed-out GET may have refreshed/committed, this is disclosed as an environment/integrity discrepancy rather than attributed to the isolated audit.
- Git status/diff fingerprints also differ from the pre-audit baseline while the porcelain count remains 435; the repository was already heavily dirty and no source/config/test/Git edit was intentionally made. The mismatch is preserved in the final-integrity artifact.

## Secret handling

- Secret environment values were not read or printed.
- The isolated frontend harness did not copy `.env.local`.
- The isolated backend ran from the audit runtime directory and did not load the repository `.env` as its working-directory file.
- Alpha Vantage availability is recorded only as configured/unconfigured; no key value is present in evidence.
