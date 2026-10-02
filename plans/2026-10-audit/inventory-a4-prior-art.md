# Inventory slice A4 — Prior art in `.scratch/`

Source: a read-only explorer enumerated **24 subdirectories + 16 loose `.md` files (1853 files,
~13 MB)**. **Only 19 of ~380 files were actually read.** Every per-ticket status reaches the reader
through `verification/2026-09-ticket-state.md`, which is itself an inherited claim — the explorer
spot-checked **12 of its assertions and found 2 false, 2 stale-but-real, 8 confirmed** (~17% error
rate). **That file is a work-list, not a source of truth.**

Tooling: `rg -F` does **not** fix the quote trap; use `Select-String` or a quote-free pattern.
Default `rg` sees only **384 of 1849** `.md` files under `.scratch` — use `--no-ignore`. Never edit
or delete any prior `.scratch` file; they are the provenance for every confirmed item.

---

## OPEN — verified against current code by the explorer. The spine of the new audit.

| ID | Finding | Loc | Corroboration | Sev / Conf |
|---|---|---|---|---|
| **OE-01** | Scale-sniffing percent formatter still on 3 dashboard pages: `Math.abs(value) <= 1.0 && value !== 0 ? value*100 : value` | `dashboard/liquidity/page.tsx:390`; `stress-testing/page.tsx:557,563,572,581`; `volatility-sizing/page.tsx:814` | 3 files | HIGH / confirmed |
| **OE-02** | `/portfolio/manage` renders return-space vol as a percent (`volatility_forecast.toFixed(2)}%` with no ×100) and always badges "Low" (`getRiskLevel(vol)` fed the raw fraction) | `portfolio/manage/page.tsx:799, 134, 164-168`; producer maps the field to `return_space_volatility` at `analytics.py:5077` | 2 files | HIGH / confirmed — **the ticket is marked `closed` and the defect is live. A false closure.** |
| **OE-03** | Liquidity turnover is `mean(volume) × last_close`; correct form is `mean(volume × close)`. Feeds the 4 liquidity tiers at `:3959,3963,3967` | `analytics_engine.py:3945-3947` | 2 files | MEDIUM / confirmed defect, needs-measurement magnitude ("~2×" is **not** measured — the real bias is the volume/price correlation over the window) |
| **OE-04** | Benchmark is `^NSEI`, a **price** index, with no provenance published | `benchmark_service.py:20` | 3 files | MEDIUM / confirmed (control: 0 matches for `provenance|basis|total_return_index`; 10 for `benchmark`) |
| **OE-05** | `risk_free_rate: float = Field(default=0.02)` on an Indian book. `analytics_engine.py:5657-5662` publishes `risk_free_rate_basis` explaining *how* the rate is used, never that 2% is inconsistent with Indian T-bills | `backend/app/config.py:53`; consumed at `analytics_engine.py:3630,5468,5473,5476`, `analytics.py:132,166`, `backtest_service.py:25`, `optimization_service.py:770,858` | 3 files, **one asserting it is closed** | HIGH / confirmed |
| **OE-06** | CI still uses long-lived AWS credentials; QH-13 closed without the migration. No `oidc`/`role-to-use` anywhere | `.github/workflows/ci-cd.yml:181-182` | 2 files, **same lineage** (both descend from the 2026-09-28 session — corroboration is **not** independent) | HIGH in principle / confirmed code — but the workflow only runs on push/PR and the project is single-user localhost, so this is hygiene not an active breach |
| **OE-07** | Four NSE India tables have **no producer and no scheduler**. `ingest_bhavcopy_records` consumes an already-fetched list; no fetcher exists (control: 0 matches for `requests.get\|httpx\|aiohttp\|def fetch`) | `india_data_service.py:149` | 3 files | HIGH / confirmed architecture; `rows=0` needs-measurement |
| **OE-08** | The `bfinance_synthetic_ohlc` provenance flag is **never read** — 0 matches in `backend/app` (control: `synthetic` → 9 matches, all unrelated) | absent | 3 files | **HIGH but sharply reduced** — the ledger measured real contamination at **4 rows of 31,338 (0.013%)**. The "every page computes on synthetic bars" framing is **falsified**; the missing guard is not. |
| **OE-09** | `_empty_concentration` publishes `diversification_score 0.0` / `diversification_ratio 1.0` — **and a source comment explains why it was left** | `analytics_engine.py:6316-6347`, sibling `:3869` | **4 files — highest corroboration in the corpus** | HIGH / confirmed — but it is an **informed documented decision**, so triage as a design decision, not a blind fix |
| **OE-10** | `/screens/custom` still uses the module-global screener singleton, while its sibling at `:232` builds a per-request instance. The ticket's status line quietly narrows its own claim to the route that works | `api/equity_research.py:246-253` | 1 file | MEDIUM-HIGH / confirmed |
| **OE-11** | WebSocket `background_updates()` is not bounded: `while True:` → 3 heavy calls → `sleep(30)` → *then* the `if not active_connections: break` | `api/websocket.py:270-294` | 2 files | MEDIUM / confirmed — the spec promised bounded; the break is unreachable until after a full cycle |
| **OE-12** | L1 in-memory DataFrame cache is unbounded (`_in_memory_df_cache` class dict, no eviction on any write path) | `data_service.py:298, 555, 651` | 2 files | **LOW-MEDIUM — explorer's severity *disagrees* with the claim.** Growth is bounded by the ticker universe (tens of entries), so "OOM" is overstated for a single-user book. Still an undeclared bound. |
| **OE-13** | Backend CSV export has **no formula-injection neutralization**; `custom_name` is user-supplied. The frontend half was fixed (`escapeCsvCell`); the backend half was not | `api/portfolio.py:1809-1815` | 2 files | MEDIUM / confirmed |
| **OE-14** | `/dashboard/pairs` calls `.toFixed()` on `Optional[float]` `current_spread_zscore` → white screen | `dashboard/pairs/page.tsx:144-145`; contract `schemas.py:495` | 1 file — **independently re-found by the frontend explorer as FE-5** | MEDIUM / suspected. **Note:** the field appears in **no `.ts` type file** (control: `*.ts` → 0, `*.tsx` → 2), so TypeScript structurally cannot catch it. |
| **OE-15** | Four QH tickets closed without the fix: QH-08 (`reactCompiler: false` at `next.config.ts:5`), QH-10 (`"alembic"` still at `pyproject.toml:25`; the scikit-learn half is a genuine miss-only), QH-09 (`api.ts:644` `): Promise<any> {` — cited as `:380`, line drift), QH-04 (no `{"status","errors","data"}` envelope exists; 15 matches are all pandas `errors="coerce"`) | see loc | 1 file | LOW individually — none fabricates a number or blocks a boot. QH-13 (OE-06) is the only one with real consequence. |

## CLOSED — each asserted OPEN or in-progress by ≥1 prior artifact, now proven fixed in current code

**This list is the retirement deliverable. It is what makes this run different from audit #27.**

| ID | Finding | Current-code proof |
|---|---|---|
| CL-01 | Partial-basket renormalisation (v5-review headline P0, QM-1) | `analytics_engine.py:255-293` — `aggregate_active_returns` now **drops** under-covered dates; `:266-271` "not zero-filled … and not renormalised, because renormalisation republishes a partial basket under the portfolio's name"; publishes `renorm: "not_applied"` + `partial_basket_days`; API side `analytics.py:8976 "partial_basket_policy": "refused_not_renormalised"` |
| CL-02 | `confidence_interval` = σ × [0.8, 1.2] ("the most reusable falsehood") | `analytics_engine.py:5888-5890` → `"confidence_interval": None, "confidence_interval_status": "not_computed"`; same at `:5962, :6047, :6295` |
| CL-03 | Optimizer published moments that were not its weights' moments (PA-1) | `optimization_service.py:96` "the single funnel"; `:891` "Keyed in scipy-linkage leaf order - deliberately NOT assumed to be" |
| CL-04 | Weight-insensitive tail memo (API-003) | `analytics.py:12518-12522` — `cache_key` now includes `_normalised_weights_key(weights)` |
| CL-05 | EVT fitted-shape clipping; `is_fat_tailed: true` refuted by its own block (RL-2) | `tail_risk_service.py:383-394` publishes raw MLE + `gpd_shape_xi_used/basis/raw/constrained`; `:172-179` publishes `gpd_shape_xi_was_clipped`; the verdict reads the **raw** fit (`:72-75`) |
| CL-06 | Backtest accepts negative `transaction_cost_bps` (QUANTCODE-003) | `backtest_service.py:39-40` raises unless finite **and** ≥ 0 |
| CL-07 | Backtest holds weights across a rebalance chunk (QUANTCODE-002) | `backtest_service.py:157` `current_weights * (1.0 + row) / strat_denominator` |
| CL-08 | WebSocket handshake has no Origin/Host check (API-002) | `websocket.py:145` `_origin_allowed`, `:253` guard, `:601` raises 403 |
| CL-09 | Raw `HTTPError` logging leaks the AV key in the URL (DATA-024, FOUND-008) | `alpha_vantage_service.py:299-300` — "Never interpolate HTTPError: requests embeds the query URL/key" |
| CL-10 | Both Compose files inject a **sync** SQLite URL into an async engine (FOUND-001) | `docker-compose.yml:13` and `.prod.yml:14` both `sqlite+aiosqlite:////app/...`; **pinned by a test**: `test_agent_d_deployment_contract.py:35-36` |
| CL-11 | `deploy.sh` globally prunes volumes (FOUND-003..005) | `scripts/deploy.sh:8` "The script never prunes Docker resources and never removes named volumes"; only remaining `rm` is `:205` on a state file |
| CL-12 | Initial loss omitted from drawdown | `analytics_engine.py:2090-2096` prepends a ones baseline; `:2085-2089` records the superseded heuristic that "invented a peak the portfolio never reached" |
| CL-13 | MFI returned as a fraction, not 0–100 (51.94-point error) | `indicators_service.py:154-159` — documents the installed stockstats behaviour and scales `values * 100.0` |
| CL-14 | Cointegration cache key omits the lookback window (QUANTCODE-012) | `cointegration_service.py:882-888` key includes `lookback:{lookback_days}|coverage:{coverage}`; second builder `:902-906` |
| CL-15 | Mixed-currency portfolio aggregation (API-001) | `portfolio.py:690` `_position_currency()`; `currency_provenance` published at `:573, :652`; contract `:548-555` |
| CL-16 | WebSocket promotes a fabricated `sharpe = 0.0` to `"measured"` | `websocket.py:394` `sharpe = None`, `:396` `analytics_status = "unavailable"`, `:455` publishes it |
| CL-17 | Persisted cache settings are no-ops (API-005, DATA-006) | `api/data.py:334-337` reads `cache_ttl_minutes`; `:344` passes it into the cache service |
| CL-18 | `np.polyfit` RankWarning on degenerate spread variance | `cointegration_service.py:958-960` `if float(np.var(z_lag)) < 1e-12: return None, None` |
| CL-19 | India-flows ADV rendered as raw 13-digit rupees | `dashboard/india-flows/page.tsx:379-381` Cr/L formatting; `:226-228` `₹ Cr` headers |
| CL-20 | Missing `busy_timeout` → `database is locked` | `db/database.py:115` `PRAGMA busy_timeout=30000`; `:100-101` records that the block had "silently never ran" |
| CL-21 | Non-atomic DELETE-then-INSERT on `AnalyticsCache` | `cache_service.py:335-342` `.on_conflict_do_update(`; the remaining `delete` at `:402` is expiry purge |
| CL-22 | Dead frontend CSV formula injection (frontend half only) | frontend `escapeCsvCell` per `frontend-audit/WAVE3-REVIEW.md` §P0-2 — **the backend half remains open as OE-13** |

## REFUTED — inherited claims that are FALSE. Do not carry forward.

- **"`analytics_cache` table is confirmed dead"** (`project-state/current-state.md:110`) — **refuted.**
  `cache_service.py:288-291` selects it with an expiry filter, `:335-342` upserts, `:402-403` purges,
  `:424-436` reports hit/expiry stats; `api/data.py:425` purges on demand; `:500` registers it in the stats map.
- **"`price_as_of` is consumed by zero frontend pages"** (`:112`) — **partly refuted.** The bare field is
  unused, but its aligned replacement is consumed: `frontend/src/types/index.ts:799, 843` and
  `volatility-sizing/page.tsx:752, 1516` bind `sizing_price_as_of`, pinned by `SectionProvenance.test.tsx:301-308`.
- **"`up_capture`/`down_capture` dead fields"** (`:111`) — **confirmed true.** Exactly 1 match in
  `backend/app`: the declaration at `schemas.py:272`. No producer.
- **"`india_data_service.py:395` `len(rows) < 3` can never emit a row"** (`main-report.md:32`) —
  **refuted as stated.** The guard moved to `:412` and now sits inside a per-symbol anomaly loop over
  a query result, where skipping a symbol with <3 rows is correct. The original claim's subject no
  longer exists at that site.

## STALE / SUPERSEDED — do not re-report
- **All bfinance cross-repo findings** (`High = max(Open,Close)*1.002`, `ticker.py` period inversion,
  `sector.py` literals, `corporate.py` Vodafone splits, `trendlyne` robots gate, `to_yfinance()` TTM bugs).
  Subject is `C:\es\coding\bfinance` — **off limits**. The `p1-bfinance-0.2.0` spec is additionally
  self-contradicted by `verification` §6.1 (claims 2 upstream URLs; reality is 5 hosts).
- `bfinance-v0.1.3-audit-and-release-notes.md`, `bfinance-integration/`, `bfinance-handoff.md` — 0.2.0 program supersedes.
- **`data-correctness` root cause #2 (statement period inversion)** — the cited fix route
  (`models/statements.py:88` dead `to_yfinance()`) no longer exists in that shape; `alpha_vantage_service.py:32,:72`
  show the module was rewritten around identity.
- **`ENV-012`, `ENV-016`, `XS-009`, `NUM-018` rule critiques** — `ENV-012`'s "blind to future `as_of`"
  is **unverified**, not closed. (`NUM-014`'s third-bucket relaxation shipped in a recent commit.)
- `package-upgrades-and-linting-2026.md`, all four session logs, `session-summary-2026-09-02.md`.
- `page_5..page_10_*_audit.md` (6 files) — absorbed by `page-audit-2026-09/` + `browser-verification-audit-2026/`.
- `FRONTEND-AUDIT-PROMPT.md`, `INDEPENDENT-AUDIT-PROMPT.md` — prompts, no findings.
- `frontend-audit/01..06` per-report tallies — §P2-3 already documents that six `06` status annotations
  under-claim fixes and the `02–06` header tallies mask per-finding reality. **Re-deriving from those
  headers will produce wrong numbers.**

## DIRECTORY VERDICTS
**superseded** `backend-audit-2026/` (P0 all fixed, 4 deferred with reason) · `deep-history-2026-09/`
(phases 14–17 shipped in `13d89ed`) · `p1-financial-correctness-2026-09/` (all six done) ·
`bug-sweep-2026/` (spot-checked 2/6, both closed) · `bfinance-integration/`
**live** `verification/` (the 222-ticket ledger — but an inherited claim) · `data-correctness-2026-09/`
(5 root causes, 4 still open) · `project-state/` (2 refuted claims) · `quality-hardening/` (**7 of 14
closed falsely**; §4.2/§4.4 of the ledger is the real status) · `resource-optimization/`
**partly-live** `backend-deep-audit/` (121 findings; math findings largely closed, contract/deployment
mostly closed) · `v5-review/` (QM-1 closed, SI/AD/RL mixed) · `ai-context-v3-remediation-2026-09/`
(all 8 self-declared FIXED, **none independently verified**) · `frontend-audit/` (WAVE3 left 7 genuinely
open B-findings) · `backend-audit/` (**~205 defects outside any ticket system**; the explorer could
not adjudicate them this run) · `browser-verification-audit-2026/` · `page-audit-2026-09/` ·
`terminal-ux-audit-2026/` (issues 04 and 05 marked `closed` but the named defects are live) ·
`remediation-2026-09/` · `ponytail-audit/`
**unclear / not opened** `advanced-analytics/` (32 feature tickets, a backlog not an audit) ·
`portfolio-audit-2026/` · `data-source-preference/` · `plugin-architecture/` (design, not findings)

## GAPS IN PRIOR WORK — nobody has audited these. As valuable as the OPEN list.

1. **`analytics.py` (651 KB) has no owner after line drift.** Every citation to it is 1,000–2,000
   lines stale; `verification` §7.5 tabulates six tickets whose anchors are unrelated code. The
   untyped/unbounded compute request bodies (API-014) were flagged once in 2026-09, never re-verified.
2. **`context_audit.py` (228 KB, ~47 rules) unaudited as a *collector*.** `v5-review/07/08/09` review the
   rules' logic; nobody has reviewed what the collector costs or whether its clock ordering is sound.
3. **No security or threat-model audit exists.** No IDOR, authorization, CORS-origin or rate-limit
   review anywhere in 380 artifacts.
4. **No supply-chain / dependency-trust audit.** The project's #1 data defect depends on a third-party
   PyPI package nothing in-repo can influence; the 0.2.0 program is 22 tickets deep with no verification gate.
5. **Concurrency is nearly unreviewed.** Two races found (portfolio price refresh — fixed; MC aggregate
   memory — never resolved). The SSE/WS broadcast path, `_TAILS_CACHE_GENERATION`, and cache purge
   during in-flight publication were named once and never revisited.
6. **The 13 newly-migrated Radix modals got no accessibility review** — keyboard trap, focus restore,
   `aria-*` coverage.
7. **`docker-compose.prod.yml` observability stack never re-checked** — `ponytail-audit` #15 flags
   prometheus/grafana/elasticsearch/logstash/kibana (105 lines) mounting missing directories.
8. **`lib/export.ts` was split but never re-audited** — the chunk boundary and whether `ChartExporter`
   still draws placeholder rects.
9. **Number formatting standardized for money but not counts/percentages** — `india-flows` "0d" ADV
   display and 3 unreviewed residual `|| 0` display coercions.
10. **~205 defects in `backend-audit/verified-01..06.md` remain outside the ticket system** and are
    described by their own authors as "audit reports, not resolutions" that "read like completion
    reports" — the single largest untracked body of work, never de-duplicated against
    `backend-deep-audit`'s 121 findings or `v5-review`'s export audit.