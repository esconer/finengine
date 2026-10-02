# Unverified — claims this audit could not settle by reading

**Cap: 10 entries. There are exactly 10.**

An entry earns a place here only under a hard, named exception — **needs credentials**, **needs a
runtime execution**, or **two code paths are genuinely ambiguous** — *plus* the full evidence floor of
plan §3: a `path:line` that resolves, the cited construct actually there, a mechanism, a stated
impact, and the resolved type or value named. There is **no** exception for "the agent was fairly
sure", and none for a missing citation.

**Quarantine launders.** An item that cannot meet the bar gets dumped here and survives forever.
Exceeding 10 means the exploration was too shallow, not that the project is haunted. **§"Dropped" at
the bottom lists everything that failed the bar, so the cap is visibly a decision and not a
convenience.**

**Sources.** A4's `<!-- UNVERIFIED-HANDOFF -->` block in `detail/prior-art.md` (3 entries, carried
verbatim), the cross-cutting seeds in `plans/2026-10-audit/inventory-a5-crosscut.md`, and `FE-2` as
**un-rejected by COR-1**. Ranked by how badly a reader needs to know.

---

## 1. Real-world frequency of the Johansen tri-state refusal, on the real 14-name book

| | |
|---|---|
| **Claim** | `COINT_CONTRACT_VERSION = "johansen-tristate-1"` shipped in a recent commit. The ~3% refusal rate that motivated it came from **synthetic pairs only**. Nobody has measured what it does on the real book. |
| **`path:line`** | `backend/app/services/cointegration_service.py:63` (contract version) · the tri-state is published at `backend/app/api/analytics.py:11207` from `getattr(pair, "johansen_cointegrated", None)` at `:10993` · `backend/app/api/analytics.py:10960-10993` documents the tri-state contract in prose |
| **Why reading cannot settle it** | The refusal is a property of **real price data**, not of code. The static count of refusal branches is verifiable; how often a real 14-name book takes them is a data fact. |
| **Settle-command** | Scan the real book through the published path and count the third bucket: `cd backend; .\.venv\Scripts\python.exe -c "import asyncio,main; ..."` against `AnalyticsEngine.pairs_analysis` for the 14 live tickers, then tabulate `johansen_cointegrated` across every pair. A count of **0** is itself the answer. |
| **Why it matters** | If it is always 0, the tri-state paths stay unexercised by live data — the same shape as the pre-existing `NUM-024` "live guard with nothing to guard today" note. The tri-state would be shipping untested. |

---

## 2. The paired `/health` + `/v1/models` request flood — who is calling

| | |
|---|---|
| **Claim** | Paired `/health` and `/v1/models` request lines are being produced against the backend origin. The frontend is **ruled out** as the caller. |
| **`path:line`** | `backend/main.py:189` — `@app.get("/v1/models")`, an OpenAI-compatible discovery shim returning `{"object": "list", "data": []}` at `:198` · `backend/main.py:180` — `health_check` · `frontend/src/lib/api.ts:927` — `healthApi.check`, **zero callers** |
| **Why reading cannot settle it** | The caller is **outside** `frontend/src/{app,components,lib,hooks}` — the frontend writer's entire scope. Reading the frontend establishes a negative (ruled out), never an identity. |
| **Settle-command** | Trace it at the server: log `request.client.host`, `request.headers.get("user-agent")` and `request.headers.get("x-stainless-*")` on both routes for one hour of real traffic. The `x-stainless-*` family identifies an OpenAI Python/Node SDK immediately. Alternative: `docker logs -f backend 2>&1 \| Select-String 'v1/models'` with uvicorn access logging on. |
| **New this run** | The backend **does** host `/v1/models`, at `main.py:189`, deliberately, as an honest OpenAI-compatible discovery response — with **no `/api` prefix**, unlike every application route. An OpenAI-compatible SDK probing an LLM server would hit exactly this route. That makes the SDK hypothesis the probable caller. It is still a hypothesis: the route's existence is verified, its being called is not. |

---

## 3. `FE-2` — does `GET /analytics/tails` ever emit a ragged `tail_dependence_matrix`?

**`FE-2` was rejected in full by writer A2. COR-1 overturned that rejection.** It is not in
`rejected.md` and it is **not** a ledger row. It is here.

| | |
|---|---|
| **Claim** | `risk-studio/page.tsx:621` computes `copulaMatrix[rowIdx]?.[colIdx] ?? (rowIdx === colIdx ? 1.0 : 0.0)`. A matrix that is non-empty but **ragged** — `matrix.length > 0` yet `matrix[r].length < tickers.length` for some `r` — passes the whole-matrix guard at `:605` and still yields `undefined`, producing a fabricated `0.000` on the emerald "no crash dependence" band and `0.0000` in the CSV. |
| **`path:line`** | `frontend/src/app/dashboard/risk-studio/page.tsx:621` (the per-cell fallback) · `:605` (the **coarse, whole-matrix** guard A2 relied on) · `:328-332` (`copulaMatrix` assigned straight from the API with **no square-completeness check**) · `:377` (the same fallback in the CSV writer) |
| **Why reading cannot settle it** | COR-1's central point: **this is a backend question.** Whether the backend ever emits a short row is a fact about `GET /analytics/tails`, and reading the frontend cannot establish it. That is precisely the plan §3 named exception "two code paths are genuinely ambiguous" — the frontend guards the whole matrix, the backend may hand it a ragged one, and only a run says which happens. |
| **Settle-command** | `GET /analytics/tails?tickers=<14 live tickers>` and assert rectangularity in the client of the request: for each row of `tail_dependence_matrix.matrix`, `len(row) == len(tickers)`. Repeat across several tickers and date windows. **If every matrix is square and dense, `FE-2` closes for good** — which is what A2 concluded by reading, and what COR-1 shows reading alone cannot establish. |
| **Confidence** | `NEEDS-RUNTIME` |

---

## 4. `OE-04` — is the benchmark leg on the same return basis as the portfolio leg?

*A4 handoff entry, carried verbatim.*

| | |
|---|---|
| **Claim** | `benchmark_service.py:20` pins `BENCHMARK_SYMBOL = "^NSEI"` and `:24` tries `"adj_close"` **before** `"close"`, so whether the two legs end up on the same basis is decided **silently, by whatever the vendor put in the frame**. Nothing publishes which column won. |
| **`path:line`** | `backend/app/services/benchmark_service.py:20` (symbol) · `:24` (`_CLOSE_CANDIDATES`) · `:2` (the docstring calls the output "returns", which is a false statement about its own input) |
| **Why reading cannot settle it** | Whether yfinance or bfinance emits `Adj Close` for an **index** symbol is a fact about a third-party package's behaviour, not about this repository. Reading this repo establishes the **rule**, never the **outcome**. Named exception: needs a runtime execution. |
| **Settle-command** | `cd backend; .\.venv\Scripts\python.exe -c "import yfinance as yf; print(list(yf.Ticker('^NSEI').history(period='5d').columns))"` — if `Adj Close` is absent, the benchmark leg is price-return while the portfolio leg uses `adj_close` and the asymmetry is real; if present, `^NSEI` is being read as total-return and **there is no asymmetry at all**. Alternatively log the resolved column in `_close_series` and observe one live run. |

---

## 5. The backend suite's real baseline, and the unattributed 5→26 swing

| | |
|---|---|
| **Claim** | `RELEASE_NOTES.md:181` documents **"249 / 249 Passed (0 failures, 100% green) with 85% total line coverage"**. The documented claim is already refuted — CI cannot pass at all (`INF-3`, `INF-4`), and it is internally inconsistent, claiming 85% against an `--cov-fail-under=80` gate. A prior artifact records a "**5 failed / 2254 passed**" baseline and a later swing to 26 failures whose cause **nobody has identified**. |
| **`path:line`** | `RELEASE_NOTES.md:181` (the claim) · `.github/workflows/ci-cd.yml:54` (`pytest … --cov-fail-under=80`) · `backend/pyproject.toml:83` (`testpaths = ["tests"]`, which is why the localhost smoke test is collected) |
| **Why reading cannot settle it** | It requires running `pytest` — ~12 minutes, network access — which this run is forbidden to do. The refutation of the *documented* claim is proven from the documented side alone; the **corrected figure is inherited, not measured**. |
| **Settle-command** | `cd backend; uv run pytest -p no:cacheprovider tests/ --cov=app --cov-fail-under=80 --cov-report=term -q --deselect tests/integration/test_compose_services.py` — fixes `INF-3` by exclusion and produces the real pass/fail count and the real coverage percentage. **The same single run also settles the actual `--cov-fail-under=80` outcome**, so the three separate "what does the suite actually do" questions are one command, not three. |
| **Note on the swing** | The vendor seam is better guarded than assumed: `test_bugfix_core_services.py:266-302` installs a spy that fails if `bfinance.Ticker` is ever constructed, and nine further files patch `yfinance`/`bfinance` at module level. **So the vendor seam is *not* the cause, and this audit does not attribute the swing to anything.** Candidates this run raised and did not eliminate: a collection-count change, fixture ordering, or `INF-12`'s `hash()`-seeded data producing values that no longer match. |

---

## 6. Does an all-NaN `Volume` column ever actually reach `liquidity_analysis`?

| | |
|---|---|
| **Claim** | `SVC-1`'s mechanism is deterministic and verified: an all-NaN `Volume` column publishes `score = 5.9`, which is 2.9 points *worse* than the inventory reported (COR-8) and lands 0.1 below the `Medium` cut of 6.0. **What is not known is whether that input state ever occurs in production, or how often.** |
| **`path:line`** | `backend/app/services/analytics_engine.py:3945` (`volume = float(df[vol_col].mean())`) · `:3972` (`score_raw = max(2.5, min(5.9, 3.0 + (daily_turnover / 2e7) * 2.9))`) · band table at `:308-312` |
| **Why reading cannot settle it** | The code path is deterministic; **the prevalence is a property of vendor data.** Whether a real `Volume` column is ever entirely unparseable is a live-data fact. The row itself is in the ledger at DEFECT/VERIFIED; only the prevalence is quarantined. |
| **Settle-command** | Fetch a multi-ticker batch and test the resolved input: `cd backend; .\.venv\Scripts\python.exe -c "from app.services.data_service import DataService; ..."` then assert `df[vol_col].mean()` is finite for every ticker in the real book. Any non-finite result confirms the condition is live. |
| **Type note (plan §3.5)** | `volume` and `price` at `:3945-3946` are **Python `float`s**, not numpy scalars — `float()` on an already-Python NaN is a no-op, not a raise. And Python's two-argument `min(5.9, nan)` returns **`5.9`**, because `nan < 5.9` is `False`. Measured on CPython 3.12.9; reproduce with `python -c "nan=float('nan'); print(max(2.5, min(5.9, 3.0 + (nan/2e7)*2.9)))"`. |

---

## 7. `OE-07` — are the four NSE India tables empty in the live database right now?

*A4 handoff entry, carried verbatim.*

| | |
|---|---|
| **Claim** | `nse_bhavcopy`, `nse_institutional_flows`, `nse_bulk_block_deals` and `nse_shareholding_patterns` are empty. |
| **`path:line`** | `backend/app/services/india_data_service.py:149` (`ingest_bhavcopy_records`) · `:228` (`ingest_institutional_flows`) · tables declared at `backend/app/models/database.py:188,220,242,267` |
| **Why reading cannot settle it** | The *code* claim is settled: **zero production callers** of either ingest function, no scheduler library anywhere in `backend/app`, and zero network-client hits in the file. Whether the tables **hold rows right now** is a database fact, and the only writers are tests. `project-state/current-state.md:113` asserts `all rows=0` from a 2026-09 pass that predates whatever ran since. Named exception: needs a runtime execution. |
| **Settle-command** | `sqlite3 backend/data/daisy.db "select 'bhavcopy', count(*) from nse_bhavcopy union all select 'flows', count(*) from nse_institutional_flows union all select 'blocks', count(*) from nse_bulk_block_deals union all select 'holdings', count(*) from nse_shareholding_patterns;"` — four zeros confirm the empty-table claim; any non-zero row means data arrived by a route this audit did not find. |

---

## 8. Has `async_client` ever written to the real `daisy.db`?

| | |
|---|---|
| **Claim** | `async_client` overrides exactly one FastAPI DI dependency and rebinds neither `db_mod.engine`, `db_mod.SessionLocal`, nor the `ws_mod.SessionLocal` alias — so any route, background task or websocket path that opens its own session reaches the **real** database. The sibling `client` fixture rebinds all three and documents this exact hazard at `:235-244`; it was fixed for one fixture and not the other. |
| **`path:line`** | `backend/tests/conftest.py:223` (`async_client`, docstring claims "never daisy.db") · `:250-256` (the `client` fixture's three-way rebind) · `backend/app/api/websocket.py:19` (binds `SessionLocal` at import) |
| **Why reading cannot settle it** | The mechanism is derived; **reachability is not.** This audit does not exhibit a test that reaches a direct-`SessionLocal` path through this fixture, and did not run the suite. Partially mitigated: `ASGITransport` runs **without lifespan**, so the `init_db()` self-heal does not fire on this path — the residual exposure is confined to code reached *inside* a request. |
| **Settle-command** | Point `TEST_DATABASE_URL` at a disposable file, run the suite, and diff the row counts of the real `backend/data/daisy.db` before and after: `sqlite3 backend/data/daisy.db "select count(*) from portfolio_positions;"` … run … `sqlite3 backend/data/daisy.db "select count(*) from portfolio_positions;"`. A changed count is the proof. Or rebind `SessionLocal` for `async_client` and see which tests go red — that is the same question asked in the other direction. |

---

## 9. `OE-08` — the `bfinance_synthetic_ohlc` contamination magnitude

*A4 handoff entry, carried verbatim.*

| | |
|---|---|
| **Claim** | The prior ledger cited **4 rows of 31,338 (0.013%)** as the contamination caused by bfinance's synthetic-OHLCV frames, and **lowered `OE-08`'s severity on the strength of that number.** Neither the prior explorer nor A4 could reproduce it. |
| **`path:line`** | `backend/.venv/Lib/site-packages/bfinance/market/ohlcv.py:165` (flag set on an empty frame) · `:249` (flag set **unconditionally** on every resampled frame) · never consumed: zero matches in `backend/app` and zero in `backend/tests` |
| **Why reading cannot settle it** | It is a row count in the project's SQLite database. **Everything the severity decision rests on is therefore resting on a number neither this audit nor the inventory can cite a `path:line` for.** Named exception: needs a runtime execution. |
| **Settle-command** | `sqlite3 backend/data/daisy.db "select count(*) from stock_timeseries;"` for the denominator, then join against the synthetic set the `p1-bfinance-0.2.0` programme identified — `.scratch/data-correctness-2026-09/p1-bfinance-0.2.0/issues/03-real-ohlcv-from-bhavcopy.md` is the artifact that recorded the 4 rows and should name the SQL it ran. |
| **Note** | The *structural* half is verified and does not depend on this number: the flag rides in `pandas.DataFrame.attrs`, which `concat`, `merge`, arithmetic and `groupby` all drop; it is set unconditionally on resampled real frames; and `data_service.py:296`'s `_source_of_df` is **dead code by construction** because bfinance sets no `_source` attribute anywhere in the package. |

---

## 10. Bundle weight — is the 715.6 KB export chunk really pulled by 0 of 24 prerendered routes?

| | |
|---|---|
| **Claim** | `recharts` is the largest eager frontend dependency (`frontend/package.json:39`, `"recharts": "^3.10.1"`), and a **715.6 KB export chunk** is claimed to be pulled by **0 of 24 prerendered routes**. Neither figure was re-measured this run. |
| **`path:line`** | `frontend/package.json:39` (`recharts` inside `dependencies`) · the chunk is produced from `frontend/src/lib/export.ts` |
| **Why reading cannot settle it** | Route-level chunk attribution is an output of a production build. `next.config.ts` has no `output` key at all, so a build would fail at the Docker layer anyway (`INF-1`) — this is one of the few questions where the `INF-1` blocker has to be cleared before the question can even be asked. |
| **Settle-command** | `cd frontend; bun run build` then read `.next/` — the route-manifest / build-manifest JSON lists each route's chunk set. Compare against `app-build-manifest.json` or the `pages-manifest`/`app-build-manifest` pair. Alternatively `Select-String` the build output for `export` chunk size. |
| **Carried by** | `detail/frontend.md`, "Adjacent observations" — the writer explicitly declined to measure it and passed it forward rather than asserting it. |

---

## Dropped — failed the bar, and why

Listing these is the point of the cap. Each was a real candidate and each failed for a **named**
reason, not for convenience.

| dropped candidate | why it is not quarantine material |
|---|---|
| Does `actions/cache@v3` hard-fail or merely warn on GitHub runners? | **Already carried, not lost.** This is a sub-claim of `INF-15`, which is a ledger row that states in its own Confidence-split paragraph that the *failure mode is not reproduced*. Filing it again here would double-count one fact in two places. |
| What is the actual `--cov-fail-under=80` outcome? | **Subsumed by entry 5.** The same single `pytest` invocation settles both. One command, one entry — not two entries pointing at one command. |
| Do the 18 unexercised envelope rules (`ENV-001..015,017,018,020`) fire at all? | **The settle-command is itself blocked.** Running the harness requires `v27.json`, which is unreachable on any machine but the author's (`INF-4`, a BLOCKER). Quarantining a question that cannot be asked until a blocker is fixed would launder the blocker. Entry 5's command — which must deselect the smoke test anyway — is the same run. |
| Does bfinance's `info` omit ratio keys or supply literal `0.0`, and does `returnOnCapitalEmployed` arrive pre-scaled? | **Half of it was resolved by reading**, and A1 resolved it: `bfinance/market/quotes.py:244` emits `returnOnEquity` as a **decimal** and `:246` emits `returnOnCapitalEmployed` as **raw percent** — exactly what `screener_service.py:317-318` assume. The scaling is correct; `SVC-4` was narrowed accordingly. The residual is a vendor *data* fact with no observation that would settle it short of a live fetch, so it does not meet the floor. |
| How often does `current_price` come back `None` (`SVC-9`)? | **Already disclaimed on the row.** `SVC-9` states in its Impact field that prevalence is unmeasured and depends on bfinance's return behaviour. A second copy of that caveat in a different file is not new information. |
| Does the `SVC-3` / `SVC-5` write collision actually occur? | **Same shape.** Both rows state "not observed" in their Impact field. Settling it needs a concurrency stress run; no decision currently turns on the answer, and the source fact (three call sites, one unguarded) is already a VERIFIED row. |
| `RELEASE_NOTES.md:182`'s "537 tests". | Settleable only by a vitest run, and the run would settle entry 10's build question too. **No decision turns on a doc-trivia count**, and the material half of that row — 50 test files, counted — is already verified. |
| Has any tracked `*.db` or secret been committed (`INF-18`'s security half)? | **Fails the named-exception test.** `git ls-files "*.db"` settles it with no network, no credentials and no runtime. Per the plan's explicit rule, anything settleable by one such command is a `DERIVED` ledger row or a dropped item — **not** quarantine. `INF-18` carries the caveat. |
| Does any test consume `conftest.py::test_env_vars` (`INF-10`)? | Same failure. One `Select-String` settles it. `INF-10` is a DERIVED row and says its own consumer search was not exhaustively completed. |
| Does the test-harness `pytestmark` really never reach a test (`INF-11`)? | **Already settled by reading**, from pytest's own source in `backend/.venv` (`_pytest/python.py:288`, `:1555`, and the control that `conftest` appears zero times in `_pytest/mark/*.py`). `INF-11` is VERIFIED. Nothing is uncertain. |
| Frontend bundle weight for individual routes beyond #10? | Same command as #10. One entry, not four. |
| `scipy 1.18.0` removed `scipy.cluster.hierarchy._LINKAGE_METHODS` — the load-bearing basis for the HRPOpt AVOID verdict | Displaced, not failed. Real, and it needs a runtime check against the installed scipy — but it settles a *third-party library licence/recommendation* question, not a correctness question about this codebase, and no ledger row or decision here turns on it. Surfaced in `detail/research-doc-accuracy.md` §"Could not verify". |
| `quantstats` resolved version in `uv.lock`; MOSEK licensing claim | Neither has a defect or a decision attached that this audit can name. Below the bar on materiality, not on form. |

**Displaced from `detail/research-doc-accuracy.md`** (a documentation-accuracy slice that arrived after
this file was written; see `STATUS.md` §4.5): its five unverifiable items were offered as candidates and
**all five were declined** — three because they are already marked `UNVERIFIED` in the source docs
*correctly so* (`backtesting.py` commercial dual-licensing, FinanceDatabase data-provenance rights), one
because it is a third-party licence question (above), and one because the legal conclusions themselves
are not this audit's to settle. Its slice also contributes one already-covered item: `quantlib` is the
QH-10 half of ledger row `OE-15`.

**Cap: 10 entered, 11 dropped, 0 merged.** Every entry has a `path:line` that resolves, a stated
reason it cannot be settled by reading, and the **exact command** that would settle it. When one of
those commands is run, the entry either becomes a ledger row or is retired to `rejected.md` with the
output as proof — it does not survive another cycle.