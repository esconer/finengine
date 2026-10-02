# Detail — Prior art (writer A4)

**Scope:** `plans/2026-10-audit/inventory-a4-prior-art.md` — `OE-01..15` only. `CL-01..22`, the
4 refuted claims, the stale list, directory verdicts and coverage gaps are in
[`../rejected.md`](../rejected.md).

**Method.** Every OE item below was re-opened at the cited line by the writer of this file, which is
not the agent that produced the inventory. Nothing here is promoted on the strength of the old
document. Each row carries its own evidence, and one item (`OE-13`) did not survive re-verification
and is recorded as rejected.

**Result:** 15 items opened, **14 held**, **1 rejected**. Pre-cap counts: **2 BLOCKER · 5 DEFECT ·
5 RISK · 2 NIT**.

**Resolutions of values.** Where a claim turns on a type or a magnitude, the resolved value is named
rather than assumed:

| Claim | Resolved value | Source |
|---|---|---|
| `volatility_forecast` units | **fraction**, clipped at `1.20` (= 120 %) | `analytics_engine.py:850` `FORECAST_VOL_CLIP_HIGH = 1.20` |
| `current_spread_zscore` nullable | **`None` when `spread_std <= 1e-8`** | `cointegration_service.py:1470-1472` |
| `p` type on `/dashboard/pairs` | **`any`** | `pairs/page.tsx:39` `useState<any[]>([])` |
| `_in_memory_df_cache` scope | **class attribute**, shared across all `DataService()` instances | `data_service.py:298` |
| `bfinance_synthetic_ohlc` transport | **`pandas.DataFrame.attrs`** — not a column | `bfinance/market/ohlcv.py:165,249` |

---

## OE-01 — Scale-sniffing percent formatter on three dashboard pages
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `frontend/src/app/dashboard/liquidity/page.tsx:390`; `frontend/src/app/dashboard/stress-testing/page.tsx:557,563,572,581`; `frontend/src/app/dashboard/volatility-sizing/page.tsx:814`
- **Asserted by**: `data-correctness-2026-09/p3-honesty-correctness/issues/24-delete-scale-sniffing-formatters.md:15` and `frontend-audit/01-dashboard-pages-a.md:43` — **2 artifacts, independent lineages** (a 2026-10 correctness programme and a frontend audit wave). Ticket 24 is `Status: ready-for-agent`: the fix was never attempted.
- **Symptom**: a fraction with magnitude ≤ 1.0 is multiplied by 100, and a fraction with magnitude > 1.0 is not. So a genuine **250 %** return-space volatility renders **"2.5%"**, and — worse — the stress *severity ladder* built on the same sniff (`stress-testing/page.tsx:581-582`, thresholds `-25 / -15 / -5`) grades that position **"Low"**.
- **Evidence**:
  ```
  frontend/src/app/dashboard/stress-testing/page.tsx
  557:    const pct = Math.abs(value) <= 1.0 && value !== 0 ? value * 100 : value;
  581:    const impactVal = Math.abs(rawImpact) <= 1.0 && rawImpact !== 0 ? rawImpact * 100 : rawImpact;
  582:    const severity = impactVal < -25 ? 'Critical' : impactVal < -15 ? 'High' : impactVal < -5 ? 'Medium' : 'Low';
  863:    const pct = Math.abs(impact) <= 1.0 && impact !== 0 ? impact * 100 : impact;   // vol-sizing
  ```
- **Mechanism**: 1. The formatter infers the unit from magnitude instead of being told it. 2. A value > 1.0 in fraction space passes through unscaled → rendered 100× too small. 3. The severity ladder compares the same wrong value against percent-space thresholds → a −120 % stress impact is graded "Low".
- **Impact**: `volatility`, `current_weight`, `recommended_weight`, `weight_change`, `bid_ask_spread`, `targetVolatility` (23 call sites in `volatility-sizing`), `impact`, `portfolio_impact` (7 call sites in `stress-testing`), `highLiquidityShare`. Weights are always in [0,1] and are unaffected; the exposure is volatility and impact above 100 %.
- **Suggested fix**: delete the sniff. Each call site already knows its unit — pass a formatter per space (`formatFractionAsPercent` vs `formatPercentLiteral`) or normalise server-side as `23-declare-units-block` proposes. One shared helper is required; three copies is the current state.

---

## OE-02 — `/portfolio/manage` renders return-space volatility 100× low and always badges "Low"
- **Class**: bug
- **Severity**: BLOCKER
- **Confidence**: VERIFIED
- **Location**: `frontend/src/app/portfolio/manage/page.tsx:799,818,134,164-168`; producer `backend/app/api/analytics.py:5377`
- **Asserted by**: `data-correctness-2026-09/main-report.md:40` + `.../p3-honesty-correctness/issues/03-portfolio-manage-unit-and-badge-bugs.md:18`; independently `frontend-audit/audit/01-app-router-boundaries.md:125` — **2 independent lineages**. **See "False closures" below: this item is live *behind* a closure marker.**
- **Symptom**: a real 25.4 % volatility renders **"0.25%"** and a real 3.1 % 1-day VaR renders **"0.03%"**. Every row carries a green **"Low"** risk badge regardless of actual risk, because `0.25 < 20` is always true.
- **Evidence**:
  ```
  frontend/src/app/portfolio/manage/page.tsx
  164:    const getRiskLevel = (volatility: number): 'Low' | 'Medium' | 'High' => {
  165:        if (volatility < 20) return 'Low';
  166:        if (volatility < 40) return 'Medium';
  799:                    <span>{position.volatility_forecast.toFixed(2)}%</span>
  818:                {position.var_forecast >= 0 ? '+' : ''}{position.var_forecast.toFixed(2)}%
  ---
  frontend/src/app/dashboard/forecast-risk/page.tsx   (the sibling that is CORRECT, same payload)
  465:            volValue == null ? 'N/A' : volValue > 0.35 ? 'High' : volValue > 0.20 ? 'Medium' : 'Low';
  525:        return `${(value * 100).toFixed(decimals)}%`;
  ```
- **Mechanism**: 1. The backend publishes an **annualised fraction** — proven by the engine's clip bound `FORECAST_VOL_CLIP_HIGH = 1.20` (`analytics_engine.py:850`), which would be nonsensical in percent space. 2. The page appends `%` to the raw fraction. 3. The same fraction is compared to percent-space thresholds, and every fraction-valued volatility is below 20, so the badge is unconditionally "Low".
- **Impact**: `volatility_forecast` and `var_forecast` are wrong by **100×** in the portfolio management table; `risk_level` is a constant. This is the exact number a portfolio owner reads before sizing a position.
- **Suggested fix**: port the `forecast-risk` treatment — `* 100` for display and fraction-space thresholds for the badge — and extract both into one shared module so the two pages cannot drift a third time. The route already publishes `return_space_volatility` beside `volatility_forecast` (`analytics.py:5377-5378`), so the unit is explicit on the wire and the client is the only defect.

### False closure — OE-02 (and the mechanism is worse than "a ticket was marked closed")

The inventory recorded "the ticket is marked `closed` and the defect is live". On re-verification the
**closure record is the defect's camouflage, and its cause is subtler than a stale status line**:

| Artifact | What it asserts | Status line |
|---|---|---|
| `data-correctness-2026-09/.../issues/03-portfolio-manage-unit-and-badge-bugs.md` | the real defect — ×100 and the thresholds, 5 unchecked proof-of-done boxes | `Status: ready-for-agent` — **never claimed done** |
| `frontend-audit/03-tools-pages-c.md:32-34` (03-B1) | a **different, narrower** claim: null `.toFixed()` crashes the page | `03-B1` closed |
| `frontend-audit/03-tools-pages-c.md:92-95` (03-B11) | a **different, narrower** claim: `risk_level: 'Low'` fabricated on error paths | `Status: fixed` |

Both frontend fixes genuinely landed — `portfolio/manage/page.tsx:796` now guards `!= null` and `:134`
now writes `risk_level: vol !== undefined ? getRiskLevel(vol) : undefined`. But **neither touched the
unit scale or the thresholds**, because neither claimed them. A reader who sees two `fixed`
annotations on this page concludes the file was reviewed. It was reviewed for two other bugs.

So: not a stale `closed` marker — a **narrowing closure**. Two real fixes shipped; the 100× error
they sit next to is untouched and the annotations make it look addressed. `verification/2026-09-ticket-state.md`
documents this exact failure mode for `remediation-09` ("the verification quietly narrows the claim to
the route that works"), so it is a known pattern in this repo, not a one-off.

---

## OE-03 — Liquidity turnover uses `mean(volume) × last_close` instead of `mean(volume × close)`
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/analytics_engine.py:3945,3947` feeding the tier ladder at `:3959,3963,3967,3971` and the published field at `:3984`
- **Asserted by**: `data-correctness-2026-09/p3-honesty-correctness/issues/16-liquidity-turnover-formula.md:16`; `v5-review/06-risk-liquidity.md` (7+ lines incl. `:23,:36,:365,:670`); `backend-audit/03-core-services.md:77,79` — **3 independent lineages**. Ticket 16 is `ready-for-agent`.
- **Symptom**: the `avg_turnover` figure and every liquidity tier are derived from an estimator that is not average daily turnover. A liquid mega-cap and an illiquid small-cap can be graded into the wrong band.
- **Evidence**:
  ```
  backend/app/services/analytics_engine.py
  3945:                volume = float(df[vol_col].mean())
  3946:                price = float(df[close_col].iloc[-1]) if close_col and not df.empty else 0.0
  3947:                daily_turnover = volume * price
  3959:                if daily_turnover >= 500000000.0 or mc >= 500000000000.0:
  3963:                elif daily_turnover >= 100000000.0 or mc >= 100000000000.0:
  3967:                elif daily_turnover >= 20000000.0 or mc >= 10000000000.0:
  3972:                    score_raw = max(2.5, min(5.9, 3.0 + (daily_turnover / 2e7) * 2.9))
  ```
- **Mechanism**: 1. `mean(volume)` and `last_close` are independent aggregates multiplied together, which is not `E[V·P]`. 2. The difference is exactly `Cov(volume, close)` over the window, plus the choice of *terminal* price in place of the mean price. 3. The wrong quantity is the sole input to all four tiers, all four `spread` ladders, and the published `avg_turnover`.
- **Impact**: `score`, `category`, `liquidation_days`, `spread`, `avg_turnover` for every position. The magnitude is **not** the "~2×" the old claim used; the real bias is the volume/price covariance over whatever window `price_data` carries, and that is unmeasured.
- **Suggested fix**: compute per-row turnover and then average — `float((df[vol_col] * df[close_col]).mean())` — and state the window the frames were trimmed to, because "average over all loaded history" is itself not a daily turnover figure.

---

## OE-04 — Benchmark is `^NSEI`, a price index, with no published provenance
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED *(for the missing provenance and the price-index fact; the basis asymmetry is a separate, quarantined claim — see handoff)*
- **Location**: `backend/app/services/benchmark_service.py:20` (symbol), `:24` (close-column candidates), `:2` (docstring)
- **Asserted by**: `advanced-analytics/issues/05-benchmark-ingestion-service.md`; `session-log-2025-08-25.md:92,100,138`; and jointly with OE-05 in `data-correctness-2026-09/p3-honesty-correctness/issues/27-real-risk-free-rate-and-tr-benchmark.md` (`Status: needs-info`, blocked on Phase 1 issue 15). **3 lineages, one of which is a ticket that has never been picked up.**
- **Symptom**: nothing on any tear-sheet, regression or regime page tells the reader that beta, alpha, R² and the information ratio are measured against a **price** index while the portfolio leg may be a **total-return** series.
- **Evidence**:
  ```
  backend/app/services/benchmark_service.py
  2:  Benchmark index service - ingests and serves NIFTY 50 (^NSEI) returns.
  20: BENCHMARK_SYMBOL = "^NSEI"  # NIFTY 50
  24: _CLOSE_CANDIDATES = ("adj_close", "close", "Adj Close", "Close")
  ```
  Control on this file: `provenance|basis|total_return` → **0 matches**; `benchmark` → 10 matches.
- **Mechanism**: 1. `^NSEI` is a price index; the module's own docstring calls the output "returns", which is a false statement about its own input. 2. `_CLOSE_CANDIDATES` prefers `adj_close` first — so whether the two legs end up on the *same* basis is decided silently, by whatever the vendor happened to put in the frame. 3. Nothing publishes which column won, so the asymmetry is invisible to the reader.
- **Impact**: `beta_vs_benchmark`, `alpha`, `adjusted_r_squared`, the market-model block and the tear-sheet comparison table. The severity does **not** rest on a measured drag — it rests on the reader being unable to tell what the number is measured against.
- **Suggested fix**: publish the resolved price column and the basis next to the benchmark series (`benchmark_basis`, `benchmark_price_column`, `total_return: true|false`), and either switch to a total-return series or state in the payload why the price index is the chosen basis.

---

## OE-05 — A 2 % risk-free rate is hardcoded twice and never justified for an Indian book
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `backend/app/config.py:53`; second, independent constant at `backend/app/api/analytics.py:555`; disclosure strings at `backend/app/services/analytics_engine.py:5658-5662` and `backend/app/api/analytics.py:634-638`
- **Asserted by**: `data-correctness-2026-09/p3-honesty-correctness/issues/27-real-risk-free-rate-and-tr-benchmark.md:38`; `v5-review/01-quant-math.md:239`; `backend-audit/03-core-services.md:93-95,202,222` + `backend-audit/00-INDEX.md:34` — **3 lineages; one (`backend-audit`) asserts it is fixed.**
- **Symptom**: Sharpe, Sortino, alpha, the excess-return leg of beta and the optimiser's objective all deduct 2 %/yr on a book of Indian equities. The response *discloses* the rate (`"risk_free_rate": self.risk_free_rate`) and explains *how* it is applied — it never says the value is a placeholder inconsistent with the instruments the book is actually made of.
- **Evidence**:
  ```
  backend/app/config.py
  53:    risk_free_rate: float = Field(default=0.02)  # 2% annual risk-free rate
  ---
  backend/app/api/analytics.py
  555: TEAR_SHEET_RISK_FREE_RATE = 0.02
  ---
  backend/app/services/analytics_engine.py
  5658:                "risk_free_rate_basis": (
  5659:                    "the engine's configured annual risk-free rate, used as "
  ```
  Consumers: `analytics_engine.py` 14, `optimization_service.py` 25, `analytics.py` 13, `backtest_service.py` 8.
- **Mechanism**: 1. A round placeholder is the default for a market whose risk-free instrument is not 2 %. 2. Every excess-return figure inherits it. 3. **There are two sources of truth** — fixing `config.py:53` leaves the tear-sheet route at `analytics.py:555`, so the two paths would disagree and nothing would detect it.
- **Impact**: `sharpe_ratio`, `sortino_ratio`, `alpha`, `excess_return`, and the optimiser's risk-aversion scaling. Direction and rough size are arithmetic on a disclosed input; the exact instrument-correct value needs a market data source, so **no magnitude is claimed here**.
- **Suggested fix**: one constant, one owner, resolved from a dated instrument (or from the backend's own `NSEBhavcopy` instrument-free proxy) and published with its `as_of`. Remove the second literal. Add a test asserting the two paths resolve to the same value, so a future divergence is caught rather than assumed away.

---

## OE-06 — CI still authenticates to AWS with long-lived static keys
- **Class**: risk
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `.github/workflows/ci-cd.yml:178-183` (job gated by `:166` `if: github.ref == 'refs/heads/main'`)
- **Asserted by**: `project-state/current-state.md:97-98`; `quality-hardening/issues/QH-13-cicd-pipeline-fixes.md:18`; `verification/2026-09-ticket-state.md:122` — **3 artifacts. These are not 3 independent observations**: QH-13 is the ticket, and `project-state` and the verification ledger were both written from it in the same 2026-09 pass. The corroboration is documentary, not independent.**
- **Symptom**: none today. A main-branch push exchanges two long-lived IAM keys for ECR credentials.
- **Evidence**:
  ```
  .github/workflows/ci-cd.yml
  178:    - name: Configure AWS credentials
  179:      uses: aws-actions/configure-aws-credentials@v4
  180:      with:
  181:        aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
  182:        aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
  183:        aws-region: us-east-1
  ```
  Control over `.github/**` (with `-Force`): `oidc` / `role-to-assume` → **0 matches**. The only hit is `configure-aws-credentials` at `:179`. One workflow file exists in `.github/workflows/`.
- **Mechanism**: 1. QH-13 specified OIDC `role-to-assume` and was closed as done. 2. Only the k8s removal and the frontend job landed; the credential migration did not. 3. `configure-aws-credentials@v4` supports OIDC as a direct alternative and it is not used, so nothing in the repo is choosing keys over a role.
- **Impact**: no active breach. The deploy job is `main`-only and the project is single-user localhost, so this is **credential hygiene**, not an open exposure. Two independent artifacts say otherwise; that disagreement is recorded rather than resolved in the more alarming direction. The correct reading is that the *ticket* overstates the consequence and the *code* matches the ticket's own spec being undone.
- **Suggested fix**: the QH-13 migration, if the account still exists. If it does not, delete the deploy job and the secrets rather than leaving a commented-out path — an unexercised OIDC migration is a second untested code path.

---

## OE-07 — Four NSE India tables have no producer, no fetcher and no caller
- **Class**: feature *(missing producer)*
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/india_data_service.py:149` (`ingest_bhavcopy_records(self, records: List[Dict[str, Any]], ...)`), `:228` (`ingest_institutional_flow`); tables at `backend/app/models/database.py:188,220,242,267`
- **Asserted by**: `project-state/current-state.md:113`; `backend-audit/05-market-data-services.md:46`; `data-correctness-2026-09/p1-bfinance-0.2.0/issues/03-real-ohlcv-from-bhavcopy.md` — **3 lineages**, though the third is a *programme* that intends to build the missing fetcher rather than a separate observation.
- **Symptom**: `/dashboard/india-flows` renders an empty board. There is no code path in the running application that can ever make it non-empty.
- **Evidence**:
  ```
  backend/app/services/india_data_service.py
  149:    async def ingest_bhavcopy_records(self, records: List[Dict[str, Any]], date_dt: datetime) -> int:
  150:        """Validate, deduplicate, and upsert bhavcopy rows; invalid rows are quarantined."""
  ```
  Controls, all with a matching positive: the file contains **0** matches for `requests.get` / `httpx` / `aiohttp` / `def fetch` / `fetch_` / `download`. `backend/app` contains **0** matches for `APScheduler`, `celery`, `BackgroundScheduler`, `add_job`, `cron`. Every call site of `ingest_bhavcopy_records` and `ingest_institutional_flow` in the repository is in `backend/tests/` (`test_agent_b_data_audit.py:445-461`, `test_bugfix_providers_05.py:307-341`, `test_coverage_india_data.py:68-93`) — **zero production callers.**
- **Mechanism**: 1. The ingest functions take an already-materialised list, so someone upstream must fetch the bhavcopy ZIP from NSE — and that code does not exist. 2. No scheduler library is installed, so nothing calls the ingest on a timer either. 3. The four tables are therefore permanently empty; `cache_service.py:502-505` even registers them for stats, so the app reports on tables it can never populate.
- **Impact**: the entire India-specific feature surface — bhavcopy delivery analytics, FII/DII flows, bulk/block deals, shareholding patterns. Note the *magnitude* ("all rows=0") is a database fact and is quarantined, not asserted here.
- **Suggested fix**: decide the feature. Either land the NSE fetcher (the `p1-bfinance-0.2.0` programme already scoped it) or remove the four tables, their stats registration and the `/dashboard/india-flows` route. An empty table registered in a stats map is worse than an absent one: it looks maintained.

---

## OE-08 — The `bfinance_synthetic_ohlc` provenance flag is never read — and is also set too often
- **Class**: maintainability
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: produced at `backend/.venv/Lib/site-packages/bfinance/market/ohlcv.py:165,249`; **never consumed** — 0 matches in `backend/app` and 0 in `backend/tests`. The project's own provenance helper is at `backend/app/services/data_service.py:294-296`
- **Asserted by**: `data-correctness-2026-09/main-report.md:9,89`; `.../spec.md:24,90`; `.../p1-bfinance-0.2.0/spec.md:92`; `.../p1-bfinance-0.2.0/issues/03-real-ohlcv-from-bhavcopy.md:22,40,53` — **4 files, but 2 of the 4 are the same programme** (`spec.md` and its own `p1-` child). Effective independent lineages: **2.**
- **Symptom**: none visible today. The guard that would distinguish synthetic bars from real bars does not exist, so nothing downstream can tell them apart.
- **Evidence**:
  ```
  backend/.venv/Lib/site-packages/bfinance/market/ohlcv.py
  161:            empty = pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], name="Date", tz="Asia/Kolkata"))
  165:            empty.attrs["bfinance_synthetic_ohlc"] = True
  ---
  246:        if resample is not None and not df.empty:
  247:            df = _resample_ohlcv(df, resample)
  249:        df.attrs["bfinance_synthetic_ohlc"] = True
  ```
  Controls: `synthetic` in `backend/app` → **9 matches**, all unrelated (synthetic *multi-day returns*, synthetic *placeholders*). `bfinance_synthetic_ohlc` in `backend/app` → **0**.
- **Severity reduction — the "every page computes on synthetic bars" framing is falsified.** The ledger measured **4 rows of 31,338 (0.013 %)** contamination. I did not reproduce that number (it is a database measurement, quarantined below), but I can confirm the *direction*: the finding is real and the magnitude is negligible. Reported as RISK, not as a defect, for exactly that reason.
- **Two findings the old account missed, both of which argue for the guard rather than against the item:**
  1. **The flag is over-set.** `ohlcv.py:249` assigns it **unconditionally** on every resampled frame — including resampled frames built entirely from real OHLCV. So the flag is not "synthetic" in the sense anyone would assume; it means "went through `_resample_ohlcv`". A guard written against this flag would produce false positives.
  2. **The transport cannot survive the pipeline.** The flag rides in `pandas.DataFrame.attrs`, which is dropped by `concat`, `merge`, arithmetic and `groupby`. The project's own adjacent helper reads a *different* mechanism —
     ```
     backend/app/services/data_service.py
     294:    def _source_of_df(df: Optional[pd.DataFrame]) -> str:
     295:        """Actual vendor that produced a downloaded frame (bfinance marks its output)."""
     296:        return "bfinance" if getattr(df, "_source", "") == "bfinance" else "yfinance"
     ```
     but bfinance sets **no** `_source` attribute anywhere in the package (0 matches), so `_source_of_df` can never return `"bfinance"` — **it is dead code by construction.** The comment on `:295` is false about the dependency it describes.
- **Mechanism**: 1. bfinance marks two frames, one of them indiscriminately. 2. The mark travels in `attrs`, which the project's own frame handling does not preserve. 3. No consumer reads it, so nothing acts on either fact.
- **Impact**: no user-visible figure today. The risk is that a synthetic frame is indistinguishable from a real one, and the only guard that exists is one whose semantics do not mean what a reader would assume.
- **Suggested fix**: report this to the bfinance maintainers first — the over-set at `ohlcv.py:249` is an upstream defect and fixing it here would paper over it. Independently: correct `_source_of_df`'s comment or its contract, since it is currently unreachable code making a claim about a dependency it never sees.

---

## OE-09 — `_empty_concentration` publishes `diversification_score 0.0` — and says so in the source
- **Class**: risk
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/analytics_engine.py:6316-6347` (comment at `:6327-6335`); the sibling that *was* corrected at `:6349-6372`; the sibling cited by the inventory at `:3869`
- **Asserted by**: **4 artifacts, 4 independent lineages — the highest corroboration in the corpus.** `data-correctness-2026-09/p3-honesty-correctness/issues/08-degenerate-concentration-returns.md:21,25`; `bug-sweep-2026/issues/02-fix-concentration-page-invariant-and-metric-fallbacks.md:12`; `ai-context-v3-remediation-2026-09/open-defects.md:212`; `browser-verification-audit-2026/issues/14-concentration-audit.md:25`. Ticket 08 is `ready-for-agent`.
- **Symptom**: with no position data, the concentration endpoint returns `diversification_score: 0.0` and `diversification_ratio: 1.0` — numerically identical to a measured **single-holding** portfolio.
- **Evidence**:
  ```
  backend/app/services/analytics_engine.py
  6324:            "diversification_score": 0.0,
  6325:            "diversification_ratio": 1.0,
  6330:            # three numbers above are NOT: diversification_score 0.0 on an empty
  6331:            # book is indistinguishable from a measured single-holding book, the
  6332:            # same class of defect the liquidity `_empty_liquidity` comment
  6333:            # records (V3-09). Left exactly as they were -- changing them is
  6334:            # outside this disclosure, and a consumer that needs the difference
  6335:            # has `error` and `n_holdings` == 0 to read it from.
  ```
- **Mechanism**: 1. `_empty_concentration` returns zeros, which the project's own `AGENTS.md` invariant also prescribes for `N ≤ 1` — so the value is not *wrong*, it is **ambiguous**. 2. `n_holdings == 0` and `error` are the only disambiguators, and both require the consumer to look. 3. The sibling `_empty_liquidity` was corrected to `None` for exactly this reason (`:6357-6361`), so the codebase has two conventions and this one kept the old.
- **Impact**: the `diversification_score` and `diversification_ratio` fields on an empty book. No measured consequence; the ambiguity is the whole claim.
- **Triage — this is a design decision awaiting an explicit call, not a defect awaiting a patch.** The author knew, wrote down why, cited the precedent that contradicts the choice, and deferred it as outside the scope of that disclosure. Four independent audits subsequently flagged it, which means the deferral is not being honoured in practice. The decision to make is one of three:
  1. **Align with `_empty_liquidity`** — publish `None` for both fields and let `n_holdings == 0` be the answer. Costs the `AGENTS.md` invariant's "single-holding renders 0 %" rule its simplest expression, but the invariant can still hold for the *measured* `N == 1` case.
  2. **Keep the values and fix the consumer** — require every reader of `diversification_score` to branch on `n_holdings` first. This is a contract obligation with no enforcement point.
  3. **Keep as-is and accept it**, recording the ambiguity in the payload as an explicit `diversification_measured: false` flag.
  Option 1 is the one consistent with the file's own precedent. **Do not treat this as a mechanical fix: option 2 versus 3 is a live question and the four corroborating audits do not answer it.**
- **Note on the AGENTS.md invariant**: it mandates 0 % for `N ≤ 1`, which is why option 1 is not free. Any change must amend the invariant in the same change, or the invariant and the payload will disagree.

---

## OE-10 — `/screens/custom` uses the module-global screener singleton its own docstring forbids
- **Class**: bug
- **Severity**: DEFECT
- **Confidence**: VERIFIED
- **Location**: `backend/app/api/equity_research.py:252` inside the route at `:246`; the correct sibling at `:232`; the self-refuting docstring at `:228-229`
- **Asserted by**: `remediation-2026-09/issues/09-screener-l2-prod-wiring.md:9` + `remediation-2026-09/spec.md:31` (**one lineage — a ticket and its own spec**); independently `backend-audit/02-api-rest-main.md:79`, `backend-audit/verified-02.md:81`, `backend-audit/verified-05.md:60`; adjudicated at `verification/2026-09-ticket-state.md:136-140`. Effective independent lineages: **2.**
- **Symptom**: `/screens/custom` runs against a long-lived `ScreenerService` bound to a session and cache from whichever request first constructed it. Custom screens can read another request's transaction state.
- **Evidence**:
  ```
  backend/app/api/equity_research.py
  228:    Per-request service: CacheService holds the request-scoped session, so it
  229:    must not live in the module-global singleton (stale-session reuse).
  232:        service = ScreenerService(db_session=db, cache_service=CacheService(db, ...))
  ---
  246: @router.post("/screens/custom", response_model=ScreenerResponse)
  252:        service = get_screener_service()
  ```
- **Mechanism**: 1. `get_screener_service` (`backend/app/services/screener_service.py:382`) memoises a service holding a `CacheService` bound to one `AsyncSession`. 2. That session is bound to the event loop / request that created it. 3. `/screens/custom` reuses it across requests, so the stale-session defect the sibling was refactored to avoid still exists on this route.
- **Impact**: custom-screen results can reflect another request's uncommitted state. Secondary, same file: `:246` does **not** catch `ValueError`, so an invalid custom screen surfaces as 500 while its sibling at `:237` correctly returns 400.
- **Suggested fix**: construct the service per request exactly as `:232` does, and add the missing `ValueError → 400` arm. The refactor is a two-line copy; the reason it was not done is recorded in `verification/2026-09-ticket-state.md:136-140` — the closure note named the route that works.

---

## OE-11 — WebSocket `background_updates()` cannot exit while a send cycle raises
- **Class**: bug
- **Severity**: RISK
- **Confidence**: VERIFIED
- **Location**: `backend/app/api/websocket.py:270-294`
- **Asserted by**: `resource-optimization/issues/01-memory-leak-cpu-optimization.md:12,22`; `verification/2026-09-ticket-state.md:157`; `data-correctness-2026-09/p2-data-layer/issues/10-websocket-ticker-honesty.md:65,80` — **3 independent lineages.**
- **Symptom**: an idle backend still runs one full three-query cycle plus a 30-second sleep before the loop exits; and if any send raises while no client is connected, the loop never exits at all.
- **Evidence**:
  ```
  backend/app/api/websocket.py
  272:    while True:
  275:            await send_portfolio_update()
  278:            await send_analytics_update()
  281:            await send_market_data_update()
  284:            await asyncio.sleep(30)
  287:            if not manager.active_connections:
  288:                break
  292:        except Exception:
  293:            logger.error("Background update cycle failed")
  294:            await asyncio.sleep(5)  # Wait before retry
  ```
- **Mechanism**: 1. The `break` sits **inside** the `try`, after three awaits and a 30 s sleep, so an idle backend always pays a full cycle. 2. If any of the three sends raises, control jumps to `:292` and the `:287` check is **never reached** — the `while True` continues. 3. With zero connections and a persistently failing send, the loop retries every 5 seconds indefinitely.
- **Impact**: the resource-optimisation ticket's promise of a *bounded* `background_updates()` is not met. The cost is CPU and DB queries on an idle backend, not user-visible wrongness, which is why this is RISK and not DEFECT. The exception-path case is sharper than the original claim's "unreachable until after a full cycle" — it is unreachable **forever** while the send fails.
- **Suggested fix**: hoist the liveness check above the work (`if not manager.active_connections: break` as the first statement of the loop body), and wrap the whole body so the check is evaluated on every path including the exception path. Keep the `CancelledError` re-raise at `:290`.

---

## OE-12 — The L1 in-memory DataFrame cache is a class attribute with no eviction
- **Class**: maintainability
- **Severity**: NIT
- **Confidence**: VERIFIED
- **Location**: `backend/app/services/data_service.py:298` (declaration), `:555` and `:651` (writes), `:626-627` (read-time freshness test), `:254` (the only clear)
- **Asserted by**: `quality-hardening/issues/QH-14-memory-and-cpu-optimization.md:28`; `data-source-preference/spec.md:41,121`; `caching-architecture-sqlite-wal-optimization.md:20,38,88` — **3 independent lineages.**
- **Symptom**: none observable. The cache grows with the number of *distinct ticker spellings* the process has ever seen and never shrinks except on a config-fingerprint change.
- **Evidence**:
  ```
  backend/app/services/data_service.py
  298:    _in_memory_df_cache: Dict[str, Any] = {}
  400:        entry = self._in_memory_df_cache.get(ticker)
  555:        self._in_memory_df_cache[ticker] = (now_ts, base, generation)
  626:            normalized_ticker in self._in_memory_df_cache
  627:            and now_ts - self._in_memory_df_cache[normalized_ticker][0] < self._l1_ttl_seconds(config)
  651:                    self._in_memory_df_cache[normalized_ticker] = (now_ts, full_frame if ... , generation)
  ```
  The only clearing path is `:250-256` `_refresh_runtime_config`, gated on `config.fingerprint` changing.
- **Mechanism**: 1. TTL is evaluated **on read only** (`:626-627`); an entry that has expired is never deleted, only overwritten. 2. There is no write-path eviction. 3. Size is therefore bounded by the distinct key count, not by TTL or by memory.
- **Severity, with the inventory's disagreement carried forward rather than silently resolved**: the original claim said **"OOM"**; that is **overstated and I do not adopt it**. Growth is bounded by the ticker universe — tens of entries for a single-user book, each a DataFrame — which is a few MB. Reported as **NIT**: an undeclared bound, with a real but second-order consequence.
- **Two corrections to the original account, both from reading the code:**
  1. **It is a class attribute, not an instance dict** — so it is shared by every `DataService()` in the process, including every test fixture. That is a cross-test and cross-tenant leak, which is more interesting than the memory bound.
  2. `:555` and `:651` are **two distinct write paths** keyed differently (`ticker` vs `normalized_ticker`), so the same instrument can occupy two entries. The original account treated these as one cache site.
- **Impact**: process memory over a long-lived session; test isolation where fixtures share ticker keys. Developer-facing, no user-visible effect.
- **Suggested fix**: sweep expired entries on the write path (a periodic pass, not a per-read `pop`, to keep the hot path cheap), and decide deliberately whether this should be per-instance. If per-instance is intended, say so in the declaration, because a class-level mutable dict reads as a bug even where it is a design.

---

## OE-13 — REJECTED. The backend CSV export **does** neutralise formula injection.

This item was in the inventory as OPEN. **It does not hold up.** It is recorded here rather than
deleted, because the reason it was believed is itself informative.

- **Claim as inherited**: `backend/app/api/portfolio.py:1809-1815` — "Backend CSV export has no
  formula-injection neutralization; `custom_name` is user-supplied. The frontend half was fixed
  (`escapeCsvCell`); the backend half was not."
- **Why it is refuted**: the helper exists, is complete, and is applied to every user-controlled
  column:
  ```
  backend/app/api/portfolio.py
  851: def _safe_csv_cell(value: Any) -> Any:
  852:     """Prevent spreadsheet formula execution while retaining CSV structure."""
  853:     if isinstance(value, str) and value and value.lstrip() and value.lstrip()[0] in "=+-@":
  854:         return "'" + value
  ---
  1818:        for position in positions:
  1820:                _safe_csv_cell(position.ticker),
  1822:                _safe_csv_cell(position.region),
  1825:                _safe_csv_cell(position.sector),
  1826:                _safe_csv_cell(position.industry),
  1827:                _safe_csv_cell(position.custom_name or ''),
  ```
  `:853` neutralises the full OWASP trigger set (`=`, `+`, `-`, `@`) after stripping leading
  whitespace, which also covers tab- and CR-prefixed bypasses. The three unguarded columns —
  `weight`, `last_price`, `market_value` — are floats, which cannot be formulas; `added_on` /
  `updated_on` are `.isoformat()` dates, which begin with a digit.
- **There is no prior-art provenance for the claim.** `_safe_csv_cell` has **0 matches across the
  entire `.scratch` corpus**, including `backend-deep-audit` — verified with `-Force` and with the
  control term `portfolio.csv`, which returns 15+ hits. So this was not an inherited claim that
  turned out to be fixed; it was an assertion with **no artifact behind it** that the code then
  refuted. It should never have been in the inventory.
- **What almost certainly happened**: the fix shipped in the same change that fixed the CSV
  content-type bug (`backend-audit/02-api-rest-main.md:19`, closed with
  `Response(media_type="text/csv", ...)` — confirmed at `portfolio.py:1838-1841`), and the audit of
  that change recorded the content-type fix but not the injection helper added beside it. The
  frontend half is separately proven live at `frontend/src/lib/utils.ts:92` with 8 pages, `export.ts`,
  `store.ts` and 12 assertions in `frontend/src/test/unit/csv-escape.test.ts`. **Both halves are fixed.**
- **Disposition**: not carried to the ledger. `CL-22` in `../rejected.md` is the correct home for the
  frontend half; the backend half needs no retirement row because it was never a live finding.

---

## OE-14 — `/dashboard/pairs` calls `.toFixed()` on an `Optional[float]` and white-screens
- **Class**: bug
- **Severity**: BLOCKER
- **Confidence**: VERIFIED
- **Location**: `frontend/src/app/dashboard/pairs/page.tsx:145` (throw), `:144` (non-fatal), `:39` (why TypeScript cannot catch it); contract `backend/app/models/schemas.py:495`; producer `backend/app/services/cointegration_service.py:1470-1472,1604`
- **Asserted by**: `data-correctness-2026-09/main-report.md:62` + `.../p3-honesty-correctness/issues/04-pairs-zscore-crash.md:14,15,19,21,37,39,47` — **1 lineage** (a report and its own ticket), ticket `Status: ready-for-agent`, severity **CRITICAL — a white screen**. **Independently re-found by the frontend writer as `FE-5` — see "Cross-agent duplicates" below.**
- **Symptom**: `/dashboard/pairs` renders nothing but a white screen whenever any pair in the scan has a degenerate spread.
- **Evidence**:
  ```
  frontend/src/app/dashboard/pairs/page.tsx
  39:    const [pairs, setPairs] = useState<any[]>([]);
  130:                              {pairs.map((p, idx) => (
  144:    <td className={...${Math.abs(p.current_spread_zscore) > 2 ? ... : ''}}>
  145:        {p.current_spread_zscore.toFixed(2)}σ
  ---
  backend/app/models/schemas.py
  495:    current_spread_zscore: Optional[float] = None
  ---
  backend/app/services/cointegration_service.py
  1471:    if spread_std > 1e-8:
  1472:        current_zscore = round(float((spread[-1] - spread_mean) / spread_std), 4)
  1604:        current_spread_zscore=current_zscore,
  ```
- **Mechanism**: 1. `spread_std <= 1e-8` — a degenerate spread — leaves `current_zscore` as its initialiser `None` (`:1470`), and `:1604` publishes that `None` into a field the schema declares `Optional`. This is a **designed-for** state: `:800` branches on it explicitly with `_is_real(zscore)`. 2. The frontend declares the array as `any[]` (`:39`), so `p.current_spread_zscore.toFixed` compiles. 3. The null reaches render; `Math.abs(null)` is `0` so `:144` survives, and `:145` throws a `TypeError` **during render, inside `.map()`** → React unmounts the tree → white screen. Line `:142` guards the neighbouring `ou_half_life_days` and `:149` guards `signal`; this one field alone is unguarded.
- **Impact**: total loss of the `/dashboard/pairs` page for any scan containing a cointegrated-but-degenerate pair — which is precisely the population the page exists to surface.
- **Suggested fix**: `p.current_spread_zscore == null ? 'N/A' : \`${p.current_spread_zscore.toFixed(2)}σ\``, matching the file's own `:142` pattern and the project's absent-value contract. Then type the row: a local `PairRow` interface mirroring `schemas.py:485-502` removes the `any` that let this ship.

### Cross-agent duplicate — OE-14 == FE-5

`FE-5` (frontend writer, `detail/frontend.md`) and `OE-14` (this file) are the **same defect**:
`Optional[float] current_spread_zscore` rendered through `.toFixed()` on `pairs/page.tsx`.

This is **independent corroboration of a `suspected` item** and should raise its confidence in the
assembler's ranking. The two agents did not share a lineage: `FE-*` comes from the frontend
explorer's own fresh survey of `frontend/src`, while `OE-14` descends from
`data-correctness-2026-09`. Two independent surveys, one defect, and the defect is still live in
current code — the ticket-04 status line (`ready-for-agent`) has not moved in the intervening time.

**Dedup precedence is the fresh finding's** (`FE-5`), per the plan's Wave B rule. `OE-14` should
appear as an `also found by` provenance field on the `FE-5` row, not as a second row. I have
**not** seen `detail/frontend.md`, so I am recording the relationship, not adjudicating it.

**No other duplicates found across the OE set.** OE-04 and OE-05 share a ticket
(`27-real-risk-free-rate-and-tr-benchmark.md`) but are distinct defects in distinct modules; OE-06
and OE-15's QH-13 arm share a ticket but only one is emitted at severity above NIT.

---

## OE-15 — Four quality-hardening tickets closed without their criterion being met
- **Class**: maintainability
- **Severity**: NIT
- **Confidence**: VERIFIED
- **Location**: `frontend/next.config.ts:5`; `backend/pyproject.toml:25,34`; `frontend/src/lib/api.ts:644`; envelope — no location exists (see evidence)
- **Asserted by**: `verification/2026-09-ticket-state.md:150-153` (**one table, one lineage**); `frontend-audit/06-config-tests-crosscutting.md:224,226,236` and `ponytail-audit/audit.md:43` for QH-08 (2 further lineages); `backend-audit/01-api-analytics.md:47` + `backend-audit/02-api-rest-main.md:83` for QH-04. Effective: **3.**
- **Symptom**: none to a user. Four tickets are marked done against criteria that current code does not meet, which makes the ticket ledger unreliable as a work queue.
- **Evidence**:
  ```
  frontend/next.config.ts
  5:  reactCompiler: false, // Disabled for stability          <- QH-08 asked for true
  ---
  frontend/src/lib/api.ts
  640:  async getFinancialStatements(
  644:  ): Promise<any> {                                        <- QH-09 asked for no Promise<any>
  ---
  backend/pyproject.toml
  25:  "alembic",                                               <- QH-10 asked for removal
  34:  "scikit-learn>=1.7.2",                                  <- genuinely used
  ---
  QH-04: no {"status","errors","data"} envelope exists.
  ```
  Controls: literal `"errors":` in `backend/app` → **0 matches**; `errors=` → **37 matches** (pandas
  `errors="coerce"`); `alembic` in `backend/app` → **0 matches** (unused dependency);
  `sklearn` → **1 match**, a real import at `backend/app/services/regime_service.py:236`
  (`from sklearn.preprocessing import StandardScaler`).
- **Mechanism**: 1. Each ticket's acceptance criterion is stated as a property of the tree and the tree still lacks it. 2. The status line was advanced on the basis of work being *done*, not the criterion being *met*. 3. The QH-10 criterion is **unsatisfiable as written** — `scikit-learn` is genuinely imported, so "sync without scikit-learn/alembic" cannot pass without removing a live dependency.
- **Correction to the inventory**: it listed `QH-09` at `:380`. The line has drifted to **`api.ts:644`** — I verified the construct is present there. This is exactly the 1,000–2,000-line anchor drift that coverage gap #1 describes; it is a live instance of it, in a file that is only ~650 lines, which suggests the drift is a citation habit rather than a property of large files.
- **Impact**: none user-facing. None of the four fabricates a number or blocks a boot. Their combined cost is that the next agent reads a green ledger and skips the work.
- **Suggested fix**: re-open QH-04, QH-08, QH-09, QH-13 (the last is `OE-06`); rewrite QH-10's criterion to "remove `alembic`; retain `scikit-learn` and record why", since the current wording cannot be satisfied. For the recurring class: require a ticket's status line to cite the verification, as `verification/2026-09-ticket-state.md` itself does.

---

## Rejected on re-verification

| ID | Inherited claim | Why it failed | Disposition |
|---|---|---|---|
| **OE-13** | Backend CSV export has no formula-injection neutralisation; `custom_name` unsanitised | `_safe_csv_cell` exists at `backend/app/api/portfolio.py:851-855`, covers the full OWASP trigger set, and is applied to `custom_name` at `:1827` and every other string column at `:1820,1822,1825,1826`. The three unguarded columns are floats; the dates are `isoformat()`. | Not carried. Both halves of the CSV fix are live (frontend proven at `frontend/src/lib/utils.ts:92` + 12 test assertions). |

**One item was rejected, and it is the item with the least provenance in the set** — `_safe_csv_cell`
has zero occurrences anywhere in `.scratch`, so the claim had no artifact behind it at all. This is
the concrete cost of the merge policy's rule that an inherited claim is a hypothesis of unknown age:
had it been promoted on the inventory's word, it would have shipped as a defect.

**Partial corrections** (item held, accounting adjusted):

| ID | Inventory said | Current code says |
|---|---|---|
| OE-02 | "the ticket is marked `closed`" | The `data-correctness` ticket is `ready-for-agent`, **not closed**. The closure is `frontend-audit` 03-B1/03-B11, which closed two *narrower* claims. A narrowing closure, not a stale marker — see the section above. |
| OE-07 | "no producer and no scheduler", `rows=0` needs measurement | Stronger than claimed: **zero production callers** of either ingest function, and no scheduler library installed at all. The *table emptiness* is still quarantined. |
| OE-12 | "`_in_memory_df_cache` class dict, no eviction" | Correct, plus two facts missed: TTL is read-time-only so expired entries are never deleted, and `:555`/`:651` are two key-spellings of one cache. |
| OE-15 | QH-09 cited at `api.ts:380` | Line drift; present at `api.ts:644`. QH-10's criterion is **unsatisfiable** — `scikit-learn` is genuinely imported at `regime_service.py:236`. |
| OE-08 | "flag never read" | Correct, plus: the flag is **over-set** unconditionally at `bfinance/market/ohlcv.py:249`, and `data_service.py:296`'s `_source_of_df` is **dead code** because bfinance never sets `_source`. |
| — | inventory: `_safe_csv_cell`-equivalent absent | Corrected by rejection above. |

---

## Cross-agent duplicate register

| Prior-art ID | Fresh ID | Defect | Independence |
|---|---|---|---|
| **OE-14** | **FE-5** | `.toFixed()` on `Optional[float] current_spread_zscore` → white screen, `dashboard/pairs/page.tsx:145` | **Independent.** `FE-5` from the frontend explorer's own survey of `frontend/src`; `OE-14` from `data-correctness-2026-09`. Different lineages, same defect, still live. |

No other OE item duplicates an item in another writer's namespace as far as this file can determine.
`OE-04` + `OE-05` share ticket 27 and `OE-06` shares QH-13 with one arm of `OE-15`, but in both cases
the items are distinct defects in distinct files and both should keep their own rows.

---

<!-- UNVERIFIED-HANDOFF -->
Inherited claim | why unresolvable | the exact command or observation that would settle it
OE-04 — whether the benchmark leg and the portfolio leg are on the **same return basis** (i.e. does the vendor frame for `^NSEI` carry `adj_close` at all, or only `close`?) | `benchmark_service.py:24` tries `"adj_close"` before `"close"`, so the basis is decided silently by vendor output. Whether yfinance/bfinance emits `Adj Close` for an **index** symbol is a fact about a third-party package's behaviour, not about this repo's source. Reading this repo can establish the *rule*, never the *outcome*. Named exception: needs a runtime execution. | `python -c "import yfinance as yf; print(list(yf.Ticker('^NSEI').history(period='5d').columns))"` in `backend/.venv` — if `Adj Close` is absent, the benchmark leg is price-return while the portfolio leg uses `adj_close` and the asymmetry is real; if present, `^NSEI` is being read as total-return and there is no asymmetry at all. Alternatively log the resolved column in `_close_series` and observe one live run.
OE-07 — that the four NSE tables (`nse_bhavcopy`, `nse_institutional_flows`, `nse_bulk_block_deals`, `nse_shareholding_patterns`) are **empty in the live database** | The *code* claim is settled by reading: zero production callers of either ingest function, and no scheduler library in `backend/app`. Whether the tables hold rows **right now** is a database fact, and the only writers are tests. `project-state/current-state.md:113` asserts `all rows=0` from a 2026-09 pass that predates whatever ran since. Named exception: needs a runtime execution. | `sqlite3 backend/data/daisy.db "select 'bhavcopy', count(*) from nse_bhavcopy union all select 'flows', count(*) from nse_institutional_flows union all select 'blocks', count(*) from nse_bulk_block_deals union all select 'holdings', count(*) from nse_shareholding_patterns;"` — if all four return 0 the empty-table claim holds; any non-zero row means data arrived by a route this audit did not find.
OE-08 — the contamination magnitude, cited by the prior ledger as **4 rows of 31,338 (0.013 %)** | The inventory lowered OE-08's severity on the strength of this number, and I did not reproduce it. It is a row count in the project's SQLite database. Everything needed for the *severity* decision is therefore resting on a number neither I nor the inventory can cite a `path:line` for. Named exception: needs a runtime execution. | `sqlite3 backend/data/daisy.db "select count(*) from stock_timeseries;"` for the denominator, then join against the synthetic set the `p1-bfinance-0.2.0` programme identified — `data-correctness-2026-09/p1-bfinance-0.2.0/issues/03-real-ohlcv-from-bhavcopy.md` is the artifact that recorded the 4 rows and should name the SQL it ran.
<!-- /UNVERIFIED-HANDOFF -->

**Handoff note for A5:** three entries. All three meet the five-condition floor (real `path:line`,
named exception, settle-command) and all three are **needs-a-runtime-execution** — none is a
"the agent was fairly sure" case. Fold against the single ≤10 cap. If the cap is tight, OE-08's
magnitude is the one to drop: OE-08's *ledger row* does not depend on it, because it is filed as a
missing guard, not as a contamination count.