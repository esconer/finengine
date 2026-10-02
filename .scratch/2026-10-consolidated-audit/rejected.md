# Rejected — inherited claims that did not reproduce

**Writer:** A4 (prior art). **Companion:** [`detail/prior-art.md`](detail/prior-art.md) (the `OE-*` rows).

**What this file is.** The retirement deliverable. Twenty-two findings that prior artifacts asserted as
open or in-progress and that are now **proven fixed in current code**, four claims that were asserted
and are **false**, a stale list that must not be re-reported, the directory verdicts, and the ten
coverage gaps. Each retirement row was re-verified by the writer of this file against current code;
none is retired on the strength of a status line.

**Counts:** 22 CL rows · 4 refuted claims · 11 stale/superseded entries · 21 directory verdicts · 10
coverage gaps.

> ### A provenance warning that applies to this whole file
>
> The inventory labelled these rows with IDs — `API-001/002/003/005`, `QUANTCODE-002/003/012`,
> `DATA-006/024`, `FOUND-001/003/005`. **None of those strings occurs anywhere in the `.scratch`
> corpus** (searched with `-Force`, excluding `backend-deep-audit` and verified against a positive
> control). They are the *explorer's own* shorthand, not artifact IDs. Where a CL row below has no
> `.scratch` source I say **"no artifact located"** rather than inheriting the label as if it were a
> citation. Four rows (CL-04, CL-07, CL-08, CL-12) are in that state: the **closure is proven**, but
> the original assertion could not be traced to an artifact. A retirement with no provenance is still
> a retirement — the code is the evidence — but it should not be read as "an audit found this and we
> closed it".

---

## Part 1 — Confirmed closed (CL-01 .. CL-22)

Each row: the finding **as originally asserted**, the `.scratch` artifact that asserted it, and the
**current-code proof it is closed**. Line numbers are as they resolve today; several of the original
citations have drifted by 1–13 lines, noted where it matters.

| ID | Finding as asserted | Asserted by | Current-code proof of closure |
|---|---|---|---|
| **CL-01** | Partial-basket renormalisation — under-covered dates were zero-filled or renormalised, republishing a partial basket under the portfolio's name (v5-review headline **P0**, QM-1) | `v5-review/01-quant-math.md:11,63,433,434`; `v5-review/02-performance-attribution.md:136,158` | `analytics_engine.py:255-293` `aggregate_active_returns` **drops** under-covered dates: `:285` keeps only `coverage["published"]` rows. `:265-271` states it in the source — *"They are not zero-filled … and they are not renormalised, because renormalisation republishes a partial basket under the portfolio's name … Such a day is a different portfolio."* API side publishes `"partial_basket_policy": "refused_not_renormalised"` at `analytics.py:8976` (exact literal verified). |
| **CL-02** | `confidence_interval` was published as σ × [0.8, 1.2] — "the most reusable falsehood" in the codebase | `data-correctness-2026-09/p3-honesty-correctness/spec.md:14`; `.../issues/20-hmm-convergence-check.md:37,38,53`; `.../p5-capability/spec.md:135,153` | `analytics_engine.py:5888-5890` publishes `"confidence_interval": None` with `"confidence_interval_status": "not_computed"` and a reason. Control: `confidence_interval_status` appears at **7** sites (`:5889, 5907, 5963, 5985, 6048, 6058, 6296`), so every producer of the field carries the status with it. |
| **CL-03** | The optimiser published moments that were not its weights' moments (PA-1) | `v5-review/02-performance-attribution.md:17,235,258,337,346,347` | `optimization_service.py:94-99` — *"PA-1: the single funnel"*, one `_weight_vector` that reindexes every solver's output into `returns.columns` order with a universe check. `:891-892` — *"Keyed in scipy-linkage leaf order - deliberately NOT assumed to be the column order."* |
| **CL-04** | A tail-risk memo was insensitive to the weights it was computed for | **no artifact located** (the label `API-003` occurs nowhere in the corpus; no `.scratch` file uses the phrase "weight-insensitive tail memo") | `analytics.py:12366` defines `_normalised_weights_key(weights)` returning a sorted `Tuple[Tuple[str, float], ...]`; `:12521` — `threshold_quantile, _normalised_weights_key(weights),` — the key is now a function of the normalised weights. Closure proven; provenance missing. |
| **CL-05** | EVT clipped its fitted GPD shape, and then `is_fat_tailed: true` contradicted the block that computed it (RL-2) | `v5-review/06-risk-liquidity.md:65`; `v5-review/queue.md:54`; `v5-review/09-consolidated.md:162`; `v5-review/12-undocumented-hunt.md:482` | `tail_risk_service.py:57` — *"the verdict reads `gpd_shape_xi_raw`."* `:173` — `"gpd_shape_xi_fitted_field": "gpd_shape_xi_raw"`. `:177` — `"gpd_shape_xi_was_clipped": shape_clipped`, so the clip is disclosed rather than applied silently. `:387` publishes `gpd_shape_xi_used` beside the raw value. Raw MLE, constrained value, basis and clip flag all four are published. |
| **CL-06** | Backtest accepted a negative `transaction_cost_bps` | `data-correctness-2026-09/main-report.md:80`; `.../p1-bfinance-0.2.0/issues/16-costs-date-keyed-schedule.md:45` | `backtest_service.py:36-42` — `:37-38` `except (TypeError, ValueError)` re-raises as `"transaction_cost_bps and risk_free_rate must be finite numbers"`; `:39-40` `if not math.isfinite(transaction_cost_bps) or transaction_cost_bps < 0.0: raise ValueError("transaction_cost_bps must be finite and >= 0")`. The **resolved** check is on a `float`, so the numpy-scalar truncation trap does not apply here. |
| **CL-07** | Backtest held weights constant across a rebalance chunk | **no artifact located** (`QUANTCODE-002` occurs nowhere; `strat_denominator` has no `.scratch` hit) | `backtest_service.py:156-158` — the comment states the identity, the code implements it: `# w[t+1] = w[t] * (1 + r[t]) / (1 + w[t]·r[t])`, then `:157` `current_weights = current_weights * (1.0 + row) / strat_denominator`. Drift-compounding across a chunk is closed. |
| **CL-08** | The WebSocket handshake had no Origin/Host check | **no artifact located** (`API-002` occurs nowhere; `websocket handshake` has no hit). Nearest substance: `bfinance-handoff.md:123` | `websocket.py:145` defines `_origin_allowed(origin)`; `:253` gates the upgrade on `return _safe_local_host(host) and _origin_allowed(_header_value(websocket, "origin"))`; `:259` applies the same rule on the `request.headers` path. Rejection path at `:264-267` closes with code 1008 **before** `accept()`, so a rejected socket is never registered. |
| **CL-09** | Raw `HTTPError` logging leaked the Alpha Vantage API key in the query URL | `backend-audit/05-market-data-services.md:34`; `backend-audit/verified-05.md:44` | `alpha_vantage_service.py:299-300` — `# Never interpolate HTTPError: requests embeds the query URL/key.` followed by `logger.warning("AV HTTP error on %s: status=%s", function_name, status)`. Both operands are the function name and an int. |
| **CL-10** | Both Compose files injected a **synchronous** SQLite URL into an async engine | `backend-audit/06-foundation.md:22,36`; `backend-audit-2026/BACKEND_REVIEW.md:53` | `docker-compose.yml:13` and `docker-compose.prod.yml:14` both `DATABASE_URL: sqlite+aiosqlite:////app/backend/data/daisy.db`. **Pinned by a test**: `backend/tests/test_agent_d_deployment_contract.py:35` asserts the aiosqlite string is present and `:36` asserts `"DATABASE_URL: sqlite:///" not in text`. A second guard sits in `config.py:24-30` (`database_url_must_be_async_sqlite`). |
| **CL-11** | `deploy.sh` globally pruned Docker resources and volumes | `backend-audit/01-api-analytics.md:25,78`; `backend-audit/06-foundation.md:51,87`; `backend-audit/verified-01.md:19` | `scripts/deploy.sh:8` — *"The script never prunes Docker resources and never removes named volumes."* Control: the only bare `rm` is `:205` `rm -f "$STATE_DIR/${ENVIRONMENT}.previous.env"`, a state file. The three `compose run --rm` flags (`:68, :90, :109`) remove ephemeral **containers**, which is the documented purpose of the flag. |
| **CL-12** | Initial loss was omitted from drawdown | **no artifact located** for the drawdown claim itself. `verification/2026-09-ticket-state.md:110-111` documents the *correction* of a neighbouring claim | `analytics_engine.py:2090-2096` prepends a ones baseline: `baseline = np.ones((1, series.shape[1]))`, `extended = np.vstack([baseline, prices])`, `running_peak = np.maximum.accumulate(extended, axis=0)`, `return (extended / running_peak).min(axis=0) - 1.0`. `:2085-2088` records the superseded heuristic and the harm it caused — *"invented a peak the portfolio never reached: a series whose first cumulative price clears 10 reported -70% drawdown here against quantstats' -9.6%."* |
| **CL-13** | MFI was returned as a fraction rather than on the 0–100 scale — a 51.94-point error | `data-correctness-2026-09/main-report.md:82`; `.../spec.md:79,294` | `indicators_service.py:154-159` documents the upstream behaviour and rescales at the adapter boundary: *"The installed stockstats implementation exposes MFI as a positive/(positive+negative) fraction, while this service's public contract documents the conventional 0–100 oscillator (>80/<20). Convert at the adapter boundary rather than exposing two scales."* `:159` `values = values * 100.0`. |
| **CL-14** | The cointegration cache key omitted the lookback window | `backend-audit/04-quant-services.md:96,140`; `backend-audit/FIX-REPORT.md:38` ("cointegration cache") | `cointegration_service.py:882` — `coverage = history_coverage or ("lookback:unknown" if lookback_days is None else f"lookback:{int(lookback_days)}")`; `:885` — the key literal contains `|lookback:{lookback_days}|coverage:{coverage}`. A second builder repeats it at `:902` / second key at `:906`. Both cache paths key on the window. |
| **CL-15** | Mixed-currency positions were aggregated into one portfolio total | `backend-audit/05-market-data-services.md:20,64` (FX cluster); `frontend-audit/audit/01-app-router-boundaries.md:149` | `portfolio.py:690` defines `_position_currency(position, quote_data=None)`; it is called per position at `:951`, `:1929`. `currency_provenance` is constructed at `:900`, `:1974` and published at `:1096`, `:2106`, `:2121`; the schema field is `portfolio.py:81`. `:573` explains the rule in the payload itself. |
| **CL-16** | The WebSocket promoted a fabricated `sharpe = 0.0` to `"measured"` | `data-correctness-2026-09/p3-honesty-correctness/issues/13-websocket-fabricated-sharpe.md:23,27,60,61`; `.../p3-honesty-correctness/spec.md:49` | `websocket.py:393-396` — `realized_vol = None`, `sharpe = None`, `max_dd = None`, `analytics_status = "unavailable"`, set **before** any data is read. `:428` `sharpe = None if candidate_sharpe is None else float(candidate_sharpe)`; `:453` publishes `"sharpe_ratio": _rounded_or_none(sharpe)`. Absent stays absent. |
| **CL-17** | Persisted cache settings were written but never read — a no-op | `backend-audit/04-quant-services.md:57` (no-op cluster); the frontend half is `frontend-audit/03-tools-pages-c.md:117,119` (03-B15) | `api/data.py:334` `ttl_raw = await get_setting(db, "cache_ttl_minutes")`; `:344` `cache_ttl_minutes=cache_ttl` passes it into the cache service; `:358` the write endpoint validates `ge=1, le=1440`; `:401-403` persists it; `:446-447` echoes it in the response. The setting is read on the path that uses it. |
| **CL-18** | `np.polyfit` emitted a `RankWarning` on degenerate spread variance | `backend-audit-2026/BACKEND_REVIEW.md:45,116,118,175`; `backend-audit-2026/LIBRARY_FIXES.md:92`; `bug-sweep-2026/spec.md:18` | `cointegration_service.py:958-960` — `# Guard against zero or degenerate variance in spread series` / `if float(np.var(z_lag)) < 1e-12:` / `return None, None`. The **resolved** comparison is `float(np.var(...)) < 1e-12` — a Python float against a Python float, so no numpy-scalar coercion question arises. |
| **CL-19** | India-flows ADV was rendered as raw 13-digit rupees | `advanced-analytics/issues/17-india-flows-dashboard.md:8,18`; `advanced-analytics/spec.md:111` | `dashboard/india-flows/page.tsx:376-382` `formatInr` — `:379` `if (val >= 10000000) return \`₹${(val / 10000000).toLocaleString('en-IN', {...})} Cr\``, `:380` the same at `1e5` → `L`, `:378` `if (val === 0) return '₹,10'`, `:377` a `MISSING` sentinel for non-finite. `:383-385` separately explains the `"0d"` liquidation-window edge case. `en-IN` localisation per the `AGENTS.md` invariant. |
| **CL-20** | Missing `busy_timeout` caused `database is locked` under the dashboard's parallel writes | `caching-architecture-sqlite-wal-optimization.md:18,35,44,56,59`; `backend-audit/00-INDEX.md:54` | `db/database.py:115` `dbapi_connection.execute("PRAGMA busy_timeout=30000")`, inside a block that also sets `journal_mode=WAL` (`:106`). `:110-114` records the incident — *"15 dropped stores in one 20s burst on 2026-09-06"* — and `:97-103` records the harder bug: the previous `isinstance(dbapi_connection, sqlite3.Connection)` guard *"never matched, so this whole block silently never ran"*, with a do-not-restore warning. |
| **CL-21** | DELETE-then-INSERT on `AnalyticsCache` was non-atomic | `caching-architecture-sqlite-wal-optimization.md:19,34,64,70,71,72` | `cache_service.py:335-342` — `stmt = sqlite_insert(AnalyticsCache).values(...)` chained into `).on_conflict_do_update(` at `:342`. One statement, no window between delete and insert. The remaining `delete` at `:402-403` is the expiry purge (`AnalyticsCache.expires_at <= now`), not a replacement path. |
| **CL-22** | CSV formula injection in the frontend export | `frontend-audit/04-system-layer.md:59,60`; `frontend-audit/00-INDEX.md:45,52`; `frontend-audit/WAVE3-REVIEW.md:19`; `frontend-audit/FIX-REPORT.md:35` | **Stronger evidence than the inventory had.** `frontend/src/lib/utils.ts:92` exports `escapeCsvCell(value: unknown): string`; it is imported and applied across **8 pages** (`concentration:28,441,443`; `liquidity:18,420,421`; `regime:19,329,338,351`; `risk-contribution:24,330,338,352`; `risk-studio:17,364,369,373,375`; `stress-testing:17,662,664`; `volatility-sizing:17,860-870`) plus `lib/export.ts:12,265,267` and `lib/store.ts:5,495,497`. `frontend/src/test/unit/csv-escape.test.ts:6-27` asserts 12 behaviours including `=cmd\|'/c calc'!A0`, `+1`, `-1`, `@SUM(A1)`, `\r=` and `\t` prefixes. **The backend half is also fixed and is separately proven in `detail/prior-art.md` §OE-13** — the original claim that only the frontend half was fixed is refuted. |

**Line drift note for the reader:** CL-05's citations moved ~4 lines (`383-394` → `:387`; `172-179` → `:173-177`);
CL-01's moved ~1 (`:266-271` → `:265-271`). Every cited line above was opened and confirmed to resolve.

---

## Part 2 — Refuted claims (inherited assertions that are FALSE)

Four claims from `project-state/current-state.md` and `data-correctness-2026-09/main-report.md`.
**Do not carry any of these forward.**

### R1 — "`analytics_cache` table is **confirmed dead**" — REFUTED
Asserted at `project-state/current-state.md:110`: *"A model definition plus a service registration;
never read or written."*

The table is read, written, purged and **reported on**:
- `cache_service.py:288-291` — `select(AnalyticsCache).where(...)` with an expiry filter on read
- `cache_service.py:335-342` — `sqlite_insert(AnalyticsCache).values(...)` then `.on_conflict_do_update(`
- `cache_service.py:402-403` — `delete(AnalyticsCache).where(AnalyticsCache.expires_at <= ...)` expiry purge
- `cache_service.py:424` and `:428` — `select(func.count()).select_from(AnalyticsCache)` hit and expiry statistics
- `api/data.py:425` — `await db.execute(delete(AnalyticsCache))`, purging the cache in the same transaction as a primary-source change

**One correction to the refutation itself:** the inventory cited `api/data.py:500` as registering it in
the stats map. **That line is a route signature** (`) -> StockTimeseriesResponse:`), not a stats
registration. The stats-map registration is at `cache_service.py:500-505`. Recorded so the next reader
does not chase a dead citation.

### R2 — "`price_as_of` is consumed by zero frontend pages" — PARTLY REFUTED
Asserted at `project-state/current-state.md:112`.

**The narrow claim holds.** The bare field `price_as_of` has zero frontend consumers. Every frontend
occurrence is `sizing_price_as_of` (the aligned replacement) or `per_position_price_as_of_at`.

**The implication does not.** The replacement **is** consumed, at four call sites plus a test:
- `frontend/src/types/index.ts:799` and `:843` declare `sizing_price_as_of: string | null`
- `frontend/src/app/dashboard/volatility-sizing/page.tsx:752` binds it
- `volatility-sizing/page.tsx:1516` reads `sizing_data.sizing_basis.price_freshness.sizing_price_as_of`
- `frontend/src/test/pages/SectionProvenance.test.tsx:301,305,308` pins the binding

So the provenance the claim says is unconsumed **is** consumed, four times, under a new name.

### R3 — "`up_capture`/`down_capture` are dead fields" — CONFIRMED TRUE
Asserted at `project-state/current-state.md:111`.

Verified: `backend/app/models/schemas.py:272` `up_capture: Optional[float] = None` and `:273`
`down_capture: Optional[float] = None`. Across the whole of `backend/app` these are the **only two
occurrences** — both declarations, no producer. The claim stands and is carried into coverage gap #3
(they are a frontend/backend contract mismatch: the TypeScript types declare fields the API never sends).

**Correction:** the claim counts them as one item; they are **two declarations** on adjacent lines, not one.

### R4 — "`india_data_service.py:395` `len(rows) < 3` can never emit a row" — REFUTED AS STATED
Asserted at `data-correctness-2026-09/main-report.md:32`.

**The subject of the claim no longer exists at that site.** The guard has moved to `:412`, and it now
sits inside a per-symbol loop:

```
backend/app/services/india_data_service.py
400:        for symbol in symbols:
402:            result = await self.db.execute(
403:                select(NSEBhavcopy)
407:            rows = result.scalars().all()
412:            if len(rows) < 3:
413:                continue
```

`rows` is now the result of a **per-symbol query** (`:402-407`), and `:412` skips only that symbol.
Skipping a symbol with fewer than three delivery observations before computing a delivery-percentage
anomaly is **correct**, not defective. The original claim described a code shape that no longer exists.

---

## Part 3 — Stale / superseded — do not re-report

| Entry | Why it must not be re-reported |
|---|---|
| **All bfinance cross-repo findings** — `High = max(Open,Close)*1.002`, `ticker.py` period inversion, `sector.py` literals, `corporate.py` Vodafone splits, the `trendlyne` robots gate, `to_yfinance()` TTM bugs | The subject is `C:\es\coding\bfinance`, a **different directory, off limits to this run**. No claim about it can be verified from here, so none can enter a ledger. Note the `bfinance` PyPI package in `backend/.venv` **is** a legitimate dependency and was read for `OE-08` — the boundary is the *source tree*, not the name. |
| The `p1-bfinance-0.2.0` spec's own file count | Self-contradicted inside the corpus: `verification` §6.1 claims 2 upstream URLs where reality is 5 hosts. A spec that miscounts its own inputs is not a citable source. (The programme is **live**, not stale — see directory verdicts — and `OE-07` and `OE-08` both descend from it.) |
| `bfinance-v0.1.3-audit-and-release-notes.md`, `bfinance-integration/`, `bfinance-handoff.md` | Superseded by the 0.2.0 programme. Release notes for a version the project has moved past. |
| **`data-correctness` root cause #2** — statement period inversion | The cited fix route no longer exists in that shape: `models/statements.py:88` is not the dead `to_yfinance()` the claim describes. `alpha_vantage_service.py:32,:72` show the module was rewritten around identity. The symptom may have gone; the *argument* cannot be followed. |
| **`ENV-012` "blind to future `as_of`"** | **Sharper than the inventory recorded.** The inventory called this "unverified, not closed". It is stronger than that: `v5-review/00-integrator.md:300-301,339` records that the agent reported ENV-012 as invisible and was **corrected by direct mutation-testing** — *"ENV-012 does fire on this exact condition"*. The surviving critique (`v5-review/05-adversarial.md:34,492`, confidence high) is narrower: ENV-012 tests **only** against the envelope collection window, so it has no notion of *relative* staleness between sections. Cite that narrower form. `context_audit.py:739` is cited by `v5-review/03-data-integrity.md:210` but is now a **section header comment**, not the rule body — the anchor drifted in a 4,980-line file. |
| **`NUM-018`, `XS-009`** rule critiques | Rule-critique backlog items with no ticket, no reproduction and no current-code anchor. (`NUM-014`'s third-bucket relaxation **did** ship in a recent commit — that one is closed, not stale.) |
| `package-upgrades-and-linting-2026.md`; all four session logs; `session-summary-2026-09-02.md` | Point-in-time working notes. `package-upgrades-and-linting-2026.md:71` even records a `memoiz` hit that is a dependency-scan artifact, not a finding. |
| `page_5..page_10_*_audit.md` (6 files) | Superseded by `page-audit-2026-09/` and `browser-verification-audit-2026/`, which re-audited the same pages with more evidence. Re-reporting from them re-reports a second-hand conclusion. |
| `FRONTEND-AUDIT-PROMPT.md`, `INDEPENDENT-AUDIT-PROMPT.md` | **Prompts, not findings.** They contain zero discoveries; they are the instructions that produced the audits that do. A grep for a term like `ADV ` hits `FRONTEND-AUDIT-PROMPT.md:86` — that is the prompt *asking* for ADV coverage, not a finding about it. |
| `frontend-audit/01..06` per-report tallies | `frontend-audit/WAVE3-REVIEW.md` §P2-3 documents that six `06` status annotations **under-claim** fixes and that the `02–06` header tallies mask per-finding reality. **Re-deriving counts from those headers produces wrong numbers** — this is a live trap, not a theoretical one: I used the per-finding status lines (`03-tools-pages-c.md:32-34, 92-95`) rather than the tallies, and that is how the `OE-02` narrowing closure became visible. |

---

## Part 4 — Directory verdicts

`superseded` · `live` · `partly-live` · `unclear / not opened`. Reproduced from the inventory's survey
and annotated with what re-verification added.

### superseded — do not re-audit
| Directory | Basis |
|---|---|
| `backend-audit-2026/` | P0 all fixed; 4 deferred with a stated reason. |
| `deep-history-2026-09/` | Phases 14–17 shipped in `13d89ed`. |
| `p1-financial-correctness-2026-09/` | All six done. |
| `bug-sweep-2026/` | Spot-checked 2 of 6, both closed. |

### live — findings here stand
| Directory | Basis, and what re-verification added |
|---|---|
| `verification/` | The 222-ticket ledger. **It is itself an inherited claim** — the source explorer spot-checked 12 of its assertions and found 2 false, 2 stale-but-real, 8 confirmed (~17 % error). Its `§4.1`–`§4.4` are the **real** status, not its status column. Re-verified this run: `§4.1` QH-13 (**live**, `OE-06`), `§4.2` QH-04 (**live**, `OE-15`), `§4.4` `QH-08`/`QH-09`/`QH-10` (**live**, `OE-15`), `§4.4` `resource-optimization/01` bounded loop (**live**, `OE-11`). **5 of 5 spot-checks held.** |
| `data-correctness-2026-09/` | 5 root causes, 4 still open. **Re-verification added:** its ticket `03` is the *true* claim behind `OE-02`, and the `frontend-audit` closure that sits beside it is narrower than the ticket. Its P3 tickets 03, 04, 08, 16, 24 are all still `ready-for-agent` and all still reproduce (`OE-02`, `OE-14`, `OE-09`, `OE-03`, `OE-01`). |
| `project-state/` | 2 refuted claims (R1, R2 above), 1 confirmed (R3), 1 refuted-as-stated (R4). **Treat §5 "Live tech debt" as four claims of which two need correcting.** |
| `quality-hardening/` | **7 of 14 closed falsely**; `verification` §4.1–§4.4 is the real status, not the ticket files. **Re-verification confirms 3 of those 7 false closures are still false** (QH-04, QH-08/QH-09/QH-10, QH-13) — i.e. the false-closure rate has not improved since the 2026-09 pass. |
| `resource-optimization/` | Live: `issues/01` bounded `background_updates()` is still unbounded → `OE-11`. |

### partly-live — mixed; adjudicate per finding, never per directory
| Directory | Basis |
|---|---|
| `backend-deep-audit/` | 121 findings. Math findings largely closed; contract/deployment mostly closed. **Not read this run** — 1,523 files / ~1.1 GB, mostly `.next` packs and `node_modules`. Two things were confirmed from it by targeted search: `bfinance_synthetic_ohlc` has **0** hits there too (`OE-13`'s rejection was checked against this directory as well), and `context_audit.py:739`'s drift. |
| `v5-review/` | QM-1 closed (`CL-01`), SI/AD/RL mixed. `RL-2` closed (`CL-05`), `PA-1` closed (`CL-03`). |
| `ai-context-v3-remediation-2026-09/` | **All 8 self-declared FIXED, none independently verified.** Its `V3-09` convention is the live counter-example for `OE-09`: `issues/06-concentration-liquidity-stress-semantics.md:7` is where the `_empty_liquidity` half was fixed and `_empty_concentration` was not. Treat all 8 as unverified. |
| `frontend-audit/` | WAVE3 left 7 genuinely open B-findings. **Its per-finding status lines are trustworthy; its header tallies are not** (see Part 3). It is also the artifact that produced the `OE-02` narrowing closure. |
| `backend-audit/` | **~205 defects outside any ticket system**, described by their own authors as *"audit reports, not resolutions"* that *"read like completion reports"*. Not adjudicated this run. **The single largest untracked body of work in the repository** — see coverage gap #10. |
| `browser-verification-audit-2026/` · `page-audit-2026-09/` · `terminal-ux-audit-2026/` | `terminal-ux-audit-2026/` issues 04 and 05 are marked `closed` **but the named defects are live** — the second false-closure cluster after `quality-hardening/`. The other two are ordinary live audits. |
| `remediation-2026-09/` · `ponytail-audit/` | `remediation-09` is a **narrowing closure** (`verification` §4.3) → `OE-10`. `ponytail-audit/` #15 flags five observability services mounting missing directories; never re-checked → gap #7. |

### unclear / not opened — a backlog, not an audit
| Directory | Basis |
|---|---|
| `advanced-analytics/` | 32 feature tickets. A backlog. Several of its tickets turned out to be the **provenance** for live defects (`17-india-flows-dashboard.md` → `CL-19`; `05-benchmark-ingestion-service.md` → `OE-04`; `18-liquidity-limits-days-to-liquidate.md` → `CL-19`'s `liquidation_days`), so it is not worthless — it is simply not an audit and its `verification` §7.4 note (13 status tokens against a documented 5) is the reason. |
| `portfolio-audit-2026/` · `data-source-preference/` · `plugin-architecture/` | Not opened. `data-source-preference/spec.md:41,121` is cited for `OE-12`, so it has substance; `plugin-architecture/` is design, not findings. |

---

## Part 5 — Coverage gaps — nobody has audited these

**These are as valuable as the open list.** A gap is a claim about the *absence* of work, and an
absence cannot be re-verified by reading the artifacts that would contain it — only by surveying the
code itself. Each entry states what is not covered and what a first pass would open.

### 1. `analytics.py` (651 KB) has no owner after line drift
Every citation into it is 1,000–2,000 lines stale. `verification` §7.5 tabulates **six** tickets
whose anchors now point at unrelated code; `§4.5` records `remediation/10` citing `:222-259, 839-862,
1032-1045, 812` against a file that is now much longer — *"The file is now 9,355 lines"* at that
reading, so it has grown further still. The untyped/unbounded compute request bodies were flagged once
in 2026-09 and never re-verified.
**First pass:** rebuild the route→line map mechanically, then re-anchor the six stale tickets.
*New this run:* `OE-15`'s QH-09 arm is an instance of this failure mode in a file only ~650 lines —
which suggests anchor drift is a **citation habit**, not a property of large files, and is therefore
cheaper to fix than the inventory implies.

### 2. `context_audit.py` (228 KB, 4,980 lines, ~47 rules) unaudited as a *collector*
`v5-review/07/08/09` review the **rules' logic**. Nobody has reviewed what the collector **costs**, or
whether its clock ordering is sound.
**First pass:** read the collection loop and the envelope window, not the rule bodies. `ENV-012`
(`v5-review/05-adversarial.md:34`) is the known entry point: it tests only against the collection
window and has no notion of relative staleness between sections.

### 3. No security or threat-model audit exists
No IDOR, authorization, CORS-origin or rate-limit review in ~380 artifacts. Nothing in the corpus asks
"who may call this route". The only adjacent work is `_origin_allowed` (`CL-08`) — a transport-layer
check on one upgrade path.
**First pass:** enumerate mutating routes and their `Depends` chains. R3 (`up_capture`/`down_capture`
declared but never produced) is the contract-mismatch shape this would find more of.

### 4. No supply-chain / dependency-trust audit
The project's **#1 data defect** depends on a third-party PyPI package that nothing in-repo can
influence. The 0.2.0 programme is 22 tickets deep with no verification gate.
**First pass:** `OE-08` already found two concrete instances upstream — `bfinance/market/ohlcv.py:249`
over-sets the synthetic flag, and the package sets no `_source` attribute, which makes
`data_service.py:296` unreachable dead code. There is a real audit here and it has an entry point.

### 5. Concurrency is nearly unreviewed
Two races found: portfolio price refresh (fixed) and MC aggregate memory (**never resolved**). The
SSE/WS broadcast path, `_TAILS_CACHE_GENERATION`, and cache purge during in-flight publication were
named once and never revisited.
**First pass:** `OE-11` is a third instance and was found by reading the loop, not by a concurrency
audit. The `advance_cache_generation` fence (`data_service.py:552, 650`) is the pattern to check
against.

### 6. The 13 newly-migrated Radix modals got no accessibility review
Keyboard trap, focus restore, `aria-*` coverage — none examined.
**First pass:** the Radix migration is recent enough that its own PR would enumerate the 13; start from
`frontend/src/components/`.

### 7. `docker-compose.prod.yml` observability stack never re-checked
`ponytail-audit` #15 flags prometheus / grafana / elasticsearch / logstash / kibana — ~105 lines —
mounting directories that do not exist.
**First pass:** the compose files *were* read this run for `CL-10` (both at `:13`/`:14`); the
observability block is further down and was not examined.

### 8. `lib/export.ts` was split but never re-audited
The chunk boundary, and whether `ChartExporter` still draws placeholder rects.
**First pass:** `lib/export.ts` was confirmed live for `CL-22` (`:12, :265, :267`); the chart path was
not read.

### 9. Number formatting standardized for money but not for counts and percentages
`india-flows` `"0d"` ADV display, and three unreviewed residual `|| 0` display coercions.
**First pass:** `OE-01` is the largest instance of exactly this — three copies of a scale-sniffing
formatter (ticket 24). The `|| 0` class is the same shape and remains unmeasured.

### 10. ~205 defects in `backend-audit/verified-01..06.md` remain outside the ticket system
Described by their own authors as *"audit reports, not resolutions"* that *"read like completion
reports"* — **the single largest untracked body of work**, never de-duplicated against
`backend-deep-audit`'s 121 findings or `v5-review`'s export audit.
**First pass:** de-duplicate by `file:function` before adjudicating anything. Three way-overlapping
bodies of findings is the condition under which a fresh audit re-reports closed work — which is the
failure mode this file exists to prevent.

---

## What was retired, in one line each

**22 closed** (CL-01..22, each proven in current code — 18 traced to an asserting artifact, 4 proven
closed but with **no artifact located**: CL-04, CL-07, CL-08, CL-12) · **4 refuted** (R1 refuted,
R2 partly refuted, R3 confirmed true, R4 refuted as stated) · **11 stale/superseded** · **21
directory verdicts** (4 superseded, 5 live, 9 partly-live, 3 unclear) · **10 coverage gaps**.

**Nothing in this file was retired by editing or deleting a prior `.scratch` artifact.** Every
retirement above is a record here and nowhere else. The prior files remain the provenance for every
confirmed item, exactly as the merge policy requires.