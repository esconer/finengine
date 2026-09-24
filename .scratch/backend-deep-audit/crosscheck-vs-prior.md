# Wave 2 cross-check — independent deep audit versus prior audit

**Date:** 2026-09-24  
**Scope:** current first-party backend, cash equities and portfolio analytics only.  
**Prior-audit access:** this report is the first point at which `.scratch/backend-audit/` was opened. Wave 1 reports were completed without reading that directory.  
**Changes:** documentation/evidence only; no application, test, configuration, database, lockfile, or Git file was modified.

## Executive comparison

The prior audit and this audit are complementary rather than interchangeable. The prior audit correctly found and drove a large remediation pass. The independent audit confirms most of those repairs against the current tree, then finds residual defects at different seams: contract boundaries, cache identity, event-loop orchestration, data-quality acceptance, deployment layout, and mathematical edge cases that the prior pass did not model numerically.

| Comparison class | Count of comparison groups | Meaning |
|---|---:|---|
| Agreed / prior finding confirmed fixed or clean now | 18 | Current source or current tests support the prior conclusion; no active finding is carried unless a residual seam is named. |
| Prior-missed by this independent audit | 28 | New Wave 1 code, quant, foundation, or product-design groups not present as active findings in the prior reports. |
| We missed as active current defects | 0 active | Prior fixed items were not repeated because the current tree is repaired; they are listed below as verified non-findings rather than suppressed. |
| Disagreements / partial resolutions | 8 | The prior conclusion is directionally right for one path but does not establish the whole contract, or the current source contradicts the prior “closed” claim. |
| Prior items explicitly refuted by prior verification | 2 | Retained for traceability; neither is reintroduced as a current finding. |

These are comparison groups, not raw finding IDs. The code reports contain the authoritative deduplicated counts: API 26, core 23, quant-code 22, data-provider 27, foundation 23. The two quant evidence reports contain 111 model cases after the corrected GARCH reference: 94 `MATCHES`, 4 `DIVERGES`, and 13 `BUG` cases across the two partitions, with family-level verdicts summarized in `quant/verify-*.md`.

## 1. Agreed with the prior audit

### 1.1 Remediation that is visibly present in the current tree

| Group | Prior evidence | Current evidence | Cross-check conclusion |
|---|---|---|---|
| Localhost bind and dead WebSocket token | Prior `02-api-rest-main.md:15`; verification `verified-02.md:9` says `127.0.0.1` and removal of the unused token. | `backend/app/config.py:17-25` and `backend/main.py:173-180` retain the local bind; `backend/app/api/websocket.py:272-278` has no token parameter. | Agree that the former all-interfaces P0 is not a current finding. The separate browser-origin boundary is discussed in §3.1. |
| WebSocket duplicate-ID and mutation safety | Prior `02-api-rest-main.md:25-27`; fix status in `FIX-REPORT.md:36`. | `backend/app/api/websocket.py:30-39` rejects an existing client ID; `:56-61` iterates a snapshot. | Agree: those two prior defects are repaired. |
| CSV response contract | Prior `02-api-rest-main.md:19`; `verified-02.md:11`; fix summary `FIX-REPORT.md:35-36`. | The current API report’s clean inventory does not retain the old JSON-quoted CSV finding; its CSV scope is now limited to formula-safe text at `code/01-api-layer.md:238-245`. | Agree that media-type/body corruption is closed; formula-injection handling is a separate residual issue. |
| Global `auto_normalize` | Prior `02-api-rest-main.md:21`; `verified-02.md:13`; `FIX-REPORT.md:36`. | The current API report has no global-weight-sum finding; its current portfolio write findings are first-weight, duplicate, transaction, and response-contract issues (`code/01-api-layer.md:85-101`, `:184-209`). | Agree that the prior global-normalization defect is no longer active. |
| Source identity and AV quote fallback | Prior `03-core-services.md:15-17`; `verified-03.md:11`; `FIX-REPORT.md:37`. | `backend/app/services/data_service.py:908` uses `_is_indian_ticker(normalized_ticker)`; `backend/app/services/alpha_vantage_service.py:45-55` performs the suffix bridge. | Agree that the prior `.BSE`-suffix classification bug is fixed. The identity-validation limitation is a new residual, not the same bug (§3.4). |
| Empty/unnormalizable frame continuation | Prior `03-core-services.md:183-184`; `verified-03.md:23`; `FIX-REPORT.md:37`. | Current data-provider report does not claim the old `return df` abort; it instead documents the narrower non-empty/partial-frame acceptance at `code/04-data-providers.md:66-72`. | Agree: the old malformed-frame cascade abort is repaired; partial valid frames remain a separate issue. |
| Analytics-cache atomic uniqueness | Prior `03-core-services.md:187`; `FIX-REPORT.md:37`. | Current core report marks the cache upsert/query key clean at `code/02-core-services.md:337` and `code/02-core-services.md:397`; current schema has the natural key. | Agree: the prior delete/insert race is closed. |
| Quote memo | Prior `03-core-services.md:217`; `FIX-REPORT.md:37`. | Current core report confirms the 30-second quote memo and its primary path at `code/02-core-services.md:335-336`; its only quote-cache finding is the fallback bypass at `:309-316`. | Agree: the old “no quote cache” finding is closed; fallback memoization is new. |
| Cointegration parameter cache identity | Prior `04-quant-services.md:140-141`; `verified-04.md:13`; `FIX-REPORT.md:38`. | `backend/app/services/cointegration_service.py:44-72` includes p-value and spread flags in both key builders. | Agree: the exact prior threshold/spread collision is fixed. Lookback identity remains open (§3.7). |
| Cointegration half-life count/list | Prior `04-quant-services.md:141`; `FIX-REPORT.md:38`. | Current quant-code report records no max-half-life count/list defect; its cointegration findings are cache lookback and unbounded pairwise work (`code/03-quant-services.md:157-171`). | Agree: the prior count/list contract is closed. |
| Backtest validation and final day | Prior `04-quant-services.md:142`, `:147-148`; `FIX-REPORT.md:38`. | `backend/app/services/backtest_service.py:32-60` validates strategy/window and appends `len(returns)`; current quant-code report has no final-day omission finding. | Agree: those prior defects are closed. Current mechanics still have different bugs (§3.6). |
| EVT insufficient-exceedance honesty | Prior `04-quant-services.md:143`, `:149-150`; `FIX-REPORT.md:38-39`. | `backend/app/services/tail_risk_service.py:84-93` returns `model_fitted=False` with null GPD parameters; `code/03-quant-services.md:205-211` covers only the remaining fitted-path disclosure issue. | Agree: fabricated `xi=0.15`/`hist*1.15` fallback is gone. Fitted-shape clipping is new (§3.5). |
| Indicator warmup and snapshot length | Prior `04-quant-services.md:144-145`; `FIX-REPORT.md:38`. | `backend/app/services/indicators_service.py:147-153` has a 365-calendar-day floor; `:214-230` passes a real lookback into the snapshot. | Agree: the prior null 200-SMA and dead snapshot parameter findings are closed. MFI scaling is new (§3.5). |
| Monte Carlo element cap existence | Prior `04-quant-services.md:146`; `FIX-REPORT.md:38`. | `backend/app/services/monte_carlo_service.py:35-40` defines the 50-million-element cap and the runner now caps paths. | Agree that a per-array cap exists. It does not establish aggregate live-memory safety (§3.3). |
| Service-side arch fit offload | Prior `04-quant-services.md:154`; `FIX-REPORT.md:38`; prior `03-core-services.md:210`. | `backend/app/services/analytics_engine.py:987-992` and `:1031-1034` call `asyncio.to_thread` for model fitting. | Agree: the fit itself is offloaded. API-level downstream CPU work remains open (§3.2). |
| Root trap scripts and migration fabrication | Prior `06-foundation.md:21-26`; `verified-06.md:7-12`; `FIX-REPORT.md:40`. | The current foundation inventory contains no `test_api_integrity.py`, `test_bulk_operations_integrity.py`, or `_diag_rc.py`; its clean/finding inventory is `code/05-foundation.md:25-83`. | Agree: the prior live-data-polluting scripts and migration quantity fabrication are not current active findings. |
| HHI, effective N, and inverse-volatility invariants | Prior `04-quant-services.md:131`; current quant verifier `quant/verify-portfolio-correlation.md:216-258`. | The independent evidence gives true HHI, `N_eff=1/HHI`, one-holding 0%, and positive-sigma inverse-vol matches. | Agree on the stated positive-weight path. Zero-weight/zero-volatility edges are classified separately, not hidden. |
| Geometric monthly compounding | Prior `AGENTS.md` invariant; current verifier `quant/verify-portfolio-correlation.md:173-179`. | Identical 17-month groupby-product evidence passes. | Agree: the mandatory compounding invariant passes. |
| Current clean research primitives | Prior `05-market-data-services.md:62-68`; current provider report `code/04-data-providers.md:315-325`. | Source-preference validation, AV budget mechanics, prebuilt screener cache, and India math primitives remain clean within their stated contracts. | Agree; this does not imply the surrounding data-quality and provenance contracts are clean. |

### 1.2 Prior items intentionally not carried as active findings

The following prior findings were not repeated in the Wave 1 active-findings tables because the current tree is repaired or the prior item is now clean: NaN metric guard, single-holding optimization placeholders, factor-exposure placeholders, benchmark rebase, concentration sector-weight source, `tickers=portfolio` sentinel, tails-cache eviction, best-effort benchmark, fabricated analytics defaults, summary/risk-score benchmark mismatch, ad-hoc liquidity mode, liquidity column handling, quantity fallback, UTC deprecation sweep, `is_indian`, risk-free configuration, equity-research 503 mapping, dead helper removal, warning-filter scoping, quote-memo existence, and the prior root-script deletions. Their prior citations are `01-api-analytics.md:13-41`, `03-core-services.md:171-218`, `05-market-data-services.md:83-124`, and `FIX-REPORT.md:33-83`; the current independent reports identify the remaining seams rather than reopening repaired behavior.

## 2. Prior audit missed by this independent audit

The following groups were absent as active findings in the prior reports, or were left only as untagged handoffs without a current contract-level test.

### 2.1 New API and portfolio contract groups

1. **Mixed-currency portfolio aggregation.** The route advertises six currencies at `backend/app/api/portfolio.py:45-68`, sums position values at `:92-127`, and stores no position currency in `backend/app/models/database.py:11-30`; the current finding is `code/01-api-layer.md:40-47` (`API-001`). The prior audit only checked the unsupported target-currency request path (`02-api-rest-main.md:37`).
2. **Zero-state first-position weight.** The current add path stores the client weight at `backend/app/api/portfolio.py:198-225` without an empty-book branch; the reproducible 20%-versus-100% result is `quant/outputs/verify-portfolio-correlation.txt:154-155` and `code/01-api-layer.md:85-92` (`API-006`). This is distinct from the prior global-normalization repair.
3. **Browser-origin boundary for WebSockets.** HTTP CORS and production host middleware do not validate the WebSocket handshake: `backend/main.py:79-96`, `backend/app/api/websocket.py:30-31`, `:272-283`. Current finding `code/01-api-layer.md:49-56` (`API-002`).
4. **Weight-insensitive tail memo.** `_TAILS_RESPONSE_CACHE` keys tickers/dates/model parameters but not allocation at `backend/app/api/analytics.py:2215-2243`; current finding `code/01-api-layer.md:58-65` (`API-003`).
5. **Untyped and unbounded compute request bodies.** Optimize, backtest, and Monte Carlo accept raw dictionaries at `backend/app/api/analytics.py:1645-1650`, `:1738-1744`, `:1834-1840`; current finding `code/01-api-layer.md:157-164` (`API-014`).
6. **Formula-capable CSV text.** User/upstream text is written with `csv.writer` without cell neutralization at `backend/app/api/portfolio.py:749-786`; current finding `code/01-api-layer.md:238-245` (`API-023`).
7. **Error/status and post-commit semantics.** Split config commits, post-commit errors described as rollbackable failures, silent duplicate filtering, and raw diagnostic errors are independently cited at `code/01-api-layer.md:184-209` and `:229-236`.

### 2.2 New data/cache groups

8. **Partial vendor acceptance and interval boundaries.** Non-empty frames can be accepted before requested-window coverage is checked at `backend/app/services/data_service.py:799-827` and `:390-420`; end-date behavior is not uniform at `:980-984`. Current findings `code/04-data-providers.md:66-80` (`DATA-001`, `DATA-002`).
9. **Advisory OHLCV validation.** `_store_timeseries_data` logs validation errors and still upserts at `backend/app/services/data_service.py:1066-1110`; current finding `code/04-data-providers.md:82-88` (`DATA-003`).
10. **Persisted cache controls are no-ops.** API settings at `backend/app/api/data.py:157-240` are not consumed by the runtime cache at `backend/app/services/data_service.py:70-76` and `:347-376`; current findings `code/01-api-layer.md:76-83` (`API-005`) and `code/04-data-providers.md:106-112` (`DATA-006`).
11. **Source preference is bypassed by warm cache.** L1/SQLite lookups precede source-order resolution at `backend/app/services/data_service.py:347-379`; current finding `code/04-data-providers.md:114-120` (`DATA-007`).
12. **Quote response field drift.** The service emits `52_week_high/low` at `backend/app/services/data_service.py:482-497`, while the public schema names different fields at `backend/app/models/schemas.py:139-151`; current finding `code/04-data-providers.md:138-144` (`DATA-010`).
13. **Provider outage taxonomy remains inconsistent.** Historical/quote `None` paths map to 404 and statement errors to 400 at `backend/app/api/data.py:302-309` and `:125-143`; current finding `code/04-data-providers.md:146-152` (`DATA-011`).
14. **FX fallback provenance.** The fallback is not cached at `backend/app/services/currency_service.py:55-68`, but the public info payload has no fallback flag at `:126-137`, while portfolio totals consume the returned number at `backend/app/api/portfolio.py:123-127`; current finding `code/04-data-providers.md:210-216` (`DATA-019`).
15. **Missing-history liquidity fabrication.** `backend/app/services/india_data_service.py:274-297` supplies ADV/price/Amihud defaults, and the API reaches it for missing frames at `backend/app/api/analytics.py:2126-2143`; current finding `code/04-data-providers.md:218-224` (`DATA-020`).
16. **Ingestion nulls/conflicts.** NSE ingestion coerces missing values to zero and rolls back a whole batch on conflict at `backend/app/services/india_data_service.py:62-114`; current finding `code/04-data-providers.md:90-96` (`DATA-004`).

### 2.3 New quantitative groups

17. **AnalyticsEngine GARCH/EGARCH horizon transformation.** The current code annualizes cumulative `h`-step variance and then multiplies by `sqrt(h/252)` at `backend/app/services/analytics_engine.py:994-1008` and `:1037-1051`; corrected identical-input evidence is `quant/outputs/verify-risk-timeseries.txt:63-89` and `quant/outputs/verify-portfolio-correlation.txt:174-177`. The prior audit verified the separate `VolatilityService` path, not this analytics-engine tail transformation (`03-core-services.md:127`, `04-quant-services.md:127`).
18. **EVT fitted-parameter clipping.** `backend/app/services/tail_risk_service.py:98-120` clips the fitted shape and uses the clipped value in both moments; boundary evidence is `quant/outputs/verify-risk-timeseries.txt:90-102`. This is separate from the prior repaired insufficient-exceedance fallback.
19. **MFI scale mismatch.** The backend’s own 80/20 description conflicts with the fraction returned by the installed indicator engine; evidence is `quant/outputs/verify-risk-timeseries.txt:147-179` and report `quant/verify-risk-timeseries.md:448-480`.
20. **Portfolio pre-listing backfill and initial-loss drawdown.** `backend/app/services/analytics_engine.py:57-62` backfills and zeroes missing returns; `quant/outputs/verify-portfolio-correlation.txt:109-118` and `:174-186` quantify 16.38% annual-return distortion and omitted initial loss. The prior audit did not run identical-input model evidence.
21. **Backtest inter-rebalance drift and negative costs.** Current code holds `current_weights` across a chunk at `backend/app/services/backtest_service.py:99-123` and accepts a negative `transaction_cost_bps` at `:18-54`; current findings `code/03-quant-services.md:75-89` (`QUANTCODE-002`, `QUANTCODE-003`).
22. **Aggregate Monte Carlo memory.** The 50-million-element cap limits one matrix but allows 4,960 paths × 10,080 steps and multiple live arrays at `backend/app/services/monte_carlo_service.py:35-38`, `:68-107`; current finding `code/03-quant-services.md:99-105` (`QUANTCODE-005`).
23. **Weight-aware concentration, zero-volatility edges, and no TE/IR.** The verifier proves the mandatory HHI path but quantifies the zero-row and zero-volatility edges at `quant/outputs/verify-portfolio-correlation.txt:146-160`; it records zero TE/IR occurrences at `:39-42`. The product-fit design then specifies the missing before/after endpoint in `gaps/stock-research-fit.md:133-379`.

### 2.4 New foundation and product-design groups

24. **Container/deployment layout.** Both Compose files inject a synchronous SQLite URL at `docker-compose.yml:13` and `docker-compose.prod.yml:13`, while the app creates an async engine at `backend/app/db/database.py:20-24`; build contexts, entrypoint, health probes, and missing bind-mounted trees are documented at `code/05-foundation.md:113-247` (`FOUND-001`, `FOUND-002`, `FOUND-015`, `FOUND-017`).
25. **Destructive deployment cleanup and invalid rollback.** `scripts/deploy.sh:173-185` globally prunes volumes and `:242-243` installs it on every exit; rollback at `:188-198` has no prior image identity. Current findings `code/05-foundation.md:129-151` (`FOUND-003` to `FOUND-005`).
26. **Schema convergence and current deployment path.** Startup uses `create_all` plus a narrow self-heal at `backend/app/db/database.py:50-71`, while legacy stock-timeseries/NSE constraints remain a migration concern; current finding `code/05-foundation.md:177-183` (`FOUND-009`) and DB table at `:301-312`.
27. **Full cash-equity terminal gap analysis.** The Bloomberg report independently inventories 18 capabilities and 30 tagged backlog rows at `gaps/bloomberg-gap.md:53-125`; the prior audit had no comparable product-gap layer.
28. **Stock-add decision design.** The stock-fit report inventories 32 current areas, 25 add-impact metrics, and a 12-row backlog at `gaps/stock-research-fit.md:1-18` and `:327-400`; the prior audit had no add-ticker before/after design.

## 3. Disagreements and partial resolutions

### 3.1 Prior P0 security conclusion versus current WebSocket origin boundary

The prior report marked the authentication/bind issue resolved under the localhost single-user posture (`02-api-rest-main.md:15`, `verified-02.md:9`). That conclusion is correct for the former remote-bind/token facts: current `backend/app/config.py:17-25`, `backend/main.py:173-180`, and `backend/app/api/websocket.py:272-278` show the local bind and removed token. It is incomplete for browser security: `backend/main.py:89-96` installs HTTP CORS, but `backend/app/api/websocket.py:30-31` accepts a socket before any Origin/Host check, and `:340-352` exposes a broadcast route. HTTP CORS is not a WebSocket handshake policy. The independent report therefore records no P0 but a current P1 (`code/01-api-layer.md:49-56`). This is a scope/contract disagreement, not a reason to restore the rejected all-interfaces P0.

### 3.2 Prior “arch fit fixed” versus API orchestration still blocking

The prior fix session correctly moved the `arch` fit into a worker thread (`03-core-services.md:210`, `FIX-REPORT.md:38`). The current service still calls heavy synchronous work directly from async routes: `backend/app/api/analytics.py:1702`, `:1768`, `:1890`, `:2173-2175`, and `:2231-2235`. The prior report’s own handoff at `FIX-REPORT.md:77` acknowledged API-layer work, so this is a partial resolution rather than a wholly missed issue. The independent report raises it to a current P1 because a first cache-miss tails request can block the event loop for the documented ~12 seconds (`code/01-api-layer.md:67-74`).

### 3.3 Prior MC cap “fixed” versus aggregate live-memory budget

The prior fix added a 50-million-element cap (`04-quant-services.md:146`, `FIX-REPORT.md:38`). The current code retains that cap at `backend/app/services/monte_carlo_service.py:35-38`, but the accepted 40-year workload can still materialize several arrays of roughly 400 MB each at `:68-107`. The independent verifier’s evidence is `quant/outputs/verify-portfolio-correlation.txt` model/edge output plus `code/03-quant-services.md:99-105`; the correct conclusion is “per-array cap fixed, aggregate memory unresolved,” not either “unbounded” or “fully safe.”

### 3.4 Prior AV bridge “fixed” versus cross-exchange identity

The prior report marked the `.BO` bridge and requested-ticker echo as fixed (`05-market-data-services.md:104-111`, `FIX-REPORT.md:39`). Current `backend/app/services/alpha_vantage_service.py:45-55` does bridge both suffixes, and the current provider report confirms the prior formatting defect is closed. However, the module’s own caveat at `:18-21` says exchange ticker letters can differ, while the implementation applies `.BSE` to every `.NS` request without identity validation. The current report records this new data-identity issue at `code/04-data-providers.md:98-104` (`DATA-005`). The prior “bridge fixed” claim is therefore only about suffix format, not instrument identity.

### 3.5 Prior EVT and indicator “fixed” versus remaining fitted-path bugs

The prior report marked EVT insufficient-exceedance fabrication and indicator warmup/snapshot defects fixed (`04-quant-services.md:143-145`). Current source confirms those exact repairs (`backend/app/services/tail_risk_service.py:84-93`; `backend/app/services/indicators_service.py:147-153`, `:214-230`). The independent verifier finds different defects: clipped fitted GPD shape at `backend/app/services/tail_risk_service.py:98-120` and fraction-scaled MFI in the installed indicator path, with numeric evidence in `quant/outputs/verify-risk-timeseries.txt:90-102` and `:147-179`. These are not reopenings of the prior issues.

### 3.6 Prior backtest “clean except final-day” versus current weight-drift/cost defects

The prior report verified the final-day boundary and input validation (`04-quant-services.md:142`, `:147-148`). Current `backend/app/services/backtest_service.py:56-60` includes the final day and `:32-41` validates inputs, so those repairs stand. The current code still holds the same weights for every day between scheduled rebalances at `:99-123`, which is a distinct strategy-accounting error, and it accepts negative costs at `:18-54`. The prior `verified-04.md:128` claimed the remaining mechanics matched; the independent identical-input replay at `quant/outputs/verify-risk-timeseries.txt:139-146` did not test weight drift, so the prior conclusion was under-scoped rather than mathematically disproved.

### 3.7 Prior coint cache “fixed” versus missing lookback identity

The prior repair added threshold and spread flags to the key (`04-quant-services.md:140-141`; current source `backend/app/services/cointegration_service.py:44-72`). The route supplies a variable lookback window at `backend/app/api/analytics.py:1968-2006`, but the current key builders accept no lookback/history fingerprint. The independent current finding is `code/03-quant-services.md:157-163` (`QUANTCODE-012`). The prior claim remains true for the exact two parameters it tested; it does not cover the route’s third result-affecting dimension.

### 3.8 Prior “no secrets in logs” versus current raw HTTP-error logging

The prior provider report marked the async-offload/no-secrets axis clean (`05-market-data-services.md:60`), and the fix report claimed no full key exposure (`FIX-REPORT.md:49`). Current `backend/app/services/alpha_vantage_service.py:227-241` places the key in the request URL and logs the raw `HTTPError`, while the global handler logs raw exception text at `backend/main.py:104-110`. The independent report records the potential key-bearing log at `code/04-data-providers.md:250-256` (`DATA-024`) and foundation `code/05-foundation.md:169-175` (`FOUND-008`). This is a direct disagreement on the “no secrets in logs” claim; only last-four key logging is clean.

## 4. Items we did not miss as active defects

There are no confirmed current defects in this category that the prior audit found and the independent pass should have repeated. The following prior groups are explicitly checked as current clean/fixed or are outside the current active scope:

- NaN/inf response guard, single-holding optimizer metric calculation, factor-error nulls, benchmark rebase, concentration sector weights, portfolio sentinel, tails-cache eviction, best-effort benchmark, fabricated API defaults, summary benchmark parity, and ad-hoc liquidity mode: prior `01-api-analytics.md:13-41`; current repair status summarized in `FIX-REPORT.md:35`; no contrary current active finding in `code/01-api-layer.md`.
- AV `is_indian`, empty-frame continuation, cache upsert uniqueness, quote memo existence, warning scoping, dead helper removal, risk-free setting, and API route 503 mapping: prior `03-core-services.md:171-218`, `05-market-data-services.md:83-124`, and `FIX-REPORT.md:37-39`; current core/provider/foundation reports mark the corresponding paths clean where in scope.
- Cointegration parameter keys, half-life filtering, backtest final-day/window/unknown-strategy handling, EVT insufficient-exceedance honesty, indicator warmup/snapshot length, and the existence of a Monte Carlo cap: prior `04-quant-services.md:140-160`; current source confirms the exact repaired lines. Residual issues are listed separately in §3.3, §3.5, §3.6, and §3.7.
- Trap-script deletion, migration quantity-fabrication removal, `is_indian` and config/schema repairs: prior `06-foundation.md:21-40`, `verified-06.md:7-15`; current foundation inventory has no active instance.

This is intentionally not a claim that the prior reports were perfect. It means the independent audit did not silently reopen a repaired path as a current finding.

## 5. Prior items explicitly refuted or narrowed

| Prior item | Cross-check result |
|---|---|
| Dividend-yield unit flip (`05-market-data-services.md:110`, `verified-05.md:12`) | Retain the prior refutation. Current code/report does not classify this as a current unit-flip defect. |
| `.BO` as a standalone bridge defect (`05-market-data-services.md:111`, `verified-05.md:32`) | Retain the prior refutation of the narrow formatting claim. The current cross-exchange identity issue in §3.4 is distinct and remains valid. |
| “No secrets in logs” (`05-market-data-services.md:60`, `FIX-REPORT.md:49`) | Narrowed/refuted for raw provider exceptions only; current key-bearing `HTTPError` logging remains a current finding. |
| “All API heavy work is offloaded” (implicit in prior fix status) | Narrowed: model fitting is offloaded, but API-level quant calls remain synchronous; §3.2 applies. |
| “Cache purge resets all process memos” (prior `03-core-services.md:158`) | Narrowed: DataService/screener/currency paths are cleared, but cointegration/company-data memos and in-flight publication remain; `code/02-core-services.md:172-179` and `code/04-data-providers.md:170-176` apply. |

## 6. Cross-check conclusion

The prior audit’s strongest contribution is the remediation inventory: it found the original fabrication, validation, cascade, cache-key, and unsafe-script classes and drove most of them into the current tree. Its weakest area is boundary closure: it verified one implementation path where several paths exist (analytics-engine versus volatility-service GARCH; equity-research routes versus all data routes; quote/FX cache versus response provenance), and it did not independently model the full mathematical output against installed libraries.

The independent audit therefore adds three classes of work rather than repeating the old list:

1. **Residual correctness after fixes:** weight-sensitive tail cache, pre-listing return construction, initial-loss drawdown, backtest weight drift, GARCH/EGARCH horizon conversion, EVT fitted-shape clipping, MFI scale, mixed currency, and deployment layout.
2. **Contract and provenance closure:** provider acceptance predicates, source-switch cache behavior, persisted settings, response schema alignment, fallback disclosure, and WebSocket origin validation.
3. **Decision workflow design:** the cash-equity terminal gap matrix and the non-mutating “add ticker X” impact endpoint, with free-source/build/paid tags and numeric design oracles.

No prior-audit claim is treated as evidence without a current source line or a current reproducible evidence artifact in this report.
