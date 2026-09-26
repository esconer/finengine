# DI — Data Integrity Audit: `finengine-portfolio-ai-context v5.json`

**Artifact** `C:\es\others things\finengine-portfolio-ai-context v5.json` — 876 KB, `export_id portfolio-4b78905b588c`, `schema_version 2.0`, `base_currency INR`, `detail summary`, 17 sections, 14 holdings, `snapshot_consistency "best_effort"`.
**Sections owned** `portfolio` + envelope (`scope`, `environment`, `warnings`, `base_currency`, `currency_policy`, `snapshot_consistency`) + every section's `inputs` / `coverage` / `omitted_fields` / `as_of` / `as_of_semantics` / `currency` / `warnings`.
**Ground truth read** `backend/app/api/portfolio.py`, `backend/app/services/ai_context_service.py`, `backend/app/debugging/context_audit.py`.
**Scripts** `.scratch/v5-review/_p01_arith.py` … `_p20_stress.py`, `_p18_mutate.py`, `_p19_mut2.py` (all `uv run` from `backend/`).

---

## Verdict

**The ledger arithmetic in this export is TRUE — bit-exact, not merely close — but almost none of it is verified by anything, and the freshness layer around it is not.** All fourteen positions reconcile with zero residual: `quantity × last_price = market_value`, `quantity × buy_price = total_cost`, `market_value − total_cost = unrealized_gain_loss`, `unrealized_gain_loss_pct = (MV−cost)/cost×100`, every `weight = market_value / Σ market_value` to `0.0e+00`, `Σ weight = 1.0` exactly, `total_value = Σ market_value` to `0.0e+00`, all seven sector weights summing to exactly `1.0`, all 14 positions `fx_rate = 1` / `identity` / `native_currency = INR` with `*_base` byte-equal to native. There is no wrong-currency P&L, no unstated FX rate, no `.NS` value assumed to be INR without saying so, no fabricated market cap that isn't provenance-tagged, no duplicate position, no NaN, and no `error: null`. That is a genuinely clean run.

The problem is everything *around* the arithmetic. `sections.portfolio.as_of` is the **newest** of its own fourteen price inputs, lands **18.049 ms after the envelope's own `generated_at`**, and names **Saturday 2026-09-26** — a day the NSE was closed — as a market-observation instant. Three sections (`concentration`, `stress_testing`, `liquidity`) publish investable conclusions with `as_of: null`, and `concentration`/`stress_testing` contain **zero dates of any kind**; `stress_testing` publishes a **−54.53 %** portfolio loss off measured volatilities with no window and no date. `pairs` and `volatility_sizing` both publish an `as_of` **newer than their own inputs** (81 of 91 pair rows are older; the sizing price is 3 days older). The same portfolio value is published at two precisions — `43608.66981063843` and `43608.67` — a ₹1.89e-4 gap that is **4.2× the project's own `MONEY_ABS_TOLERANCE`/`MONEY_REL_TOLERANCE` budget** and that no rule compares. And the decisive structural fact: I mutation-tested the repo's own 47-rule audit. It passes this export 47/47. It also passes an export with a per-row weight off by 5 pp, a `total_cost` of 999 against a true 2 083.60, an `unrealized_gain_loss` zeroed, a P&L % of 99 against a true −30.4, a `market_value_base` silently multiplied by 83, a duplicated ticker, all 14 positions relabelled `USD` at `fx_rate 1`, a `total_value` of 99 999 in one field, and an `as_of` fabricated five months into the future. **The accounting is true by luck of a passing run, not by construction.** That is the finding that matters.

### What reconciles exactly — say it plainly

| Check | Result |
|---|---|
| `quantity × last_price` vs `market_value`, all 14 | delta `0.00e+00` (bit-exact) |
| `quantity × buy_price` vs `total_cost`, all 14 | delta `0.00e+00` |
| `market_value − total_cost` vs `unrealized_gain_loss`, all 14 | delta `0.00e+00` |
| `unrealized_gain_loss_pct` vs `(MV−cost)/cost×100` and vs `(price−buy)/buy×100` | delta `0.00e+00` both forms |
| `weight` vs `market_value / Σ market_value`, all 14 | delta `+0.000e+00` |
| `Σ weight` vs `1.0` | `1.0` exactly |
| `total_value` vs `Σ market_value` | delta `0.0` exactly |
| `total_weight` | `1` exactly |
| `sectors` sum | `1.0` exactly, 7 sectors |
| `*_base` vs native, all 14 rows × 7 pairs | `0` mismatches |
| `fx_rate`, `fx_provenance.provenance`, `native_currency`, `value_currency` | all `1` / `identity` / `INR` / `INR` |
| `concentration.herfindahl_index` vs `Σw²` | `0.0862` = `round4(0.08615799271245198)` ✓ |
| `concentration.effective_positions` vs `1/HHI` | `11.61` = `round2(11.60658423)` ✓ |
| `concentration.top_3 / top_5 / top_10 / largest_position` | delta `0.0 / 1.1e-16 / 1.1e-16 / 0.0` |
| `concentration.gini_coefficient` | `0.252` = `round3(0.251659)` ✓ |
| `concentration.by_weight` vs portfolio weights | all 14 identical, sum `1.0`, no extras, no omissions |
| `concentration.by_sector` vs `round4(portfolio.sectors)` | all 7 `OK`, residual `0.000e+00`, `by_sector_rounding_residual = 0` ✓ |
| `dashboard.summary.concentration_score` vs `HHI × 100` | `8.62` = `8.62` exactly |
| `stress_testing` `max_drawdown` vs `portfolio_impact × 1.15`, 4 scenarios | delta ≤ `4.5e-05` (4 dp rounding) |
| `stress_testing` `portfolio_impact` vs `Σ weight × position_impact`, 4 × 14 legs | delta ≤ `1.2e-05` (4 dp rounding) |
| `dashboard.performance_history.return` vs `pv[i]/pv[i−1] − 1` | 17/19 exact to `<1e-12`; 2 drift ≤ `6.6e-07` |
| 17 sections' `coverage.covered_tickers` | byte-identical to `portfolio`'s, 14 each, `missing_tickers` `[]` |
| tickers / ids | 14 unique tickers, ids `1..14` unique, all `.NS`, all `region IN` |
| strict JSON, duplicate keys, NaN/Inf, `error: null`, status vocabulary | clean |
| `generated_at ≤ completed_at` | `18.703 s`, sane |
| `scope` vs `sections` keys | identical set **and order** |
| repo's own 47-rule audit | **47/47 pass** |

There is **no** rounding-coherence defect to report, because the premise doesn't hold: `market_value` is *not* rounded to 2 dp. 8 of 14 legs carry full float64 precision. The published `weight` is therefore consistent with the *exact* `market_value`, not with a rounded one — **drift `0.000e+00`, magnitude zero.** (The rounding problem here runs the other way — see **DI-10**.)

---

## Findings, ranked

### DI-1 · P0 · `sections.portfolio.as_of` (+ `data.as_of`) and all 14 `updated_on`

**Observed** `as_of = "2026-09-26T15:33:25.781197Z"`. Envelope `generated_at = "2026-09-26T15:33:25.763148Z"`. The portfolio `as_of` is **+18.049 ms after** the export's own `generated_at` and **+9.1 ms after** nothing else. It equals **`max()`** of the fourteen `updated_on` values, not `min()`: those span `15:33:06.491757` → `15:33:25.781197`, a **19.289 s** spread, and `as_of` is the newest. **13 of its own 14 price inputs are older than its `as_of`.** And `2026-09-26` is a **Saturday** — NSE/BSE are closed; the only session in the delivered window tail is Friday `2026-09-25`, which is what `realized_risk`, `forecast_risk`, `factor_exposure`, `volatility_sizing`, `tear_sheet`, `risk_contribution`, `monte_carlo` and `pairs` all correctly declare as their `latest_observation_date`.

**Expected** Per the envelope's own documented rule — *"for a composite, the OLDEST component timestamp — a composite section is only as fresh as its stalest leg, so an unrelated newer quote … can never become the section's `as_of`"* (`ai_context_service.py:492-495`) — the portfolio section's `as_of` must be the **oldest** of its components (`2026-09-26T15:33:06.491757Z`) and must not postdate `generated_at`.

**Recomputation evidence**
```
portfolio as_of - export generated_at   = +18.0 ms
portfolio as_of == max(updated_on)      -> True
portfolio as_of == min(updated_on)      -> False
NEWER than 13 of its own 14 price inputs
as_of inside [generated_at, completed_at] -> True   (so it is not outside the bracket, it is *after the start*)
date.fromisoformat('2026-09-26').strftime('%A') -> Saturday
legs stamped BEFORE export generated_at: 12 / 14
legs stamped AFTER  export generated_at:  2 / 14
```

**Root cause** `app/api/portfolio.py:105` — `_quote_as_of` returns `max(values)` ("Use the newest persisted quote timestamp for snapshot provenance", line 95), wired in at `app/api/portfolio.py:514`. It is the *only* section whose `as_of` comes from a bespoke function rather than the shared `_as_of` resolver, so it is the only one that never gets the oldest-leg rule. The `+18 ms` is structural, not a clock glitch: `generated_at` is stamped at `ai_context_service.py:1330` **before** the portfolio fetch at `:1337`, so any quote written during that fetch necessarily outranks it.

**The warning is real but half the story.** `sections.portfolio.warnings[0]` says *"as_of … is a quote/update timestamp written during this export (it falls inside the collection window), so it marks when the value was refreshed, not a historical observation date."* That is accurate about the **semantics**. It does not disclose that (a) `as_of` is the max rather than the min of its own inputs, (b) it names a non-trading day, or (c) it is a **database write** time, not a quote time — only 2 of 14 legs were actually written inside the collection window. **Confidence: high** (arithmetic exact; root cause read at source).

---

### DI-2 · P0 · `sections.concentration` and `sections.stress_testing` — numbers with no date, `status: available`, no warning

**Observed** Both sections: `as_of: null`, `as_of_semantics: null`, `status: "available"`, `warnings: []`, `coverage.status: "complete"`, `omitted_fields: []`. A recursive scan of `data` finds **zero** `YYYY-MM-DD` substrings in either payload and **zero** keys matching `window|observations|start|end|date|as_of` in `concentration`. Yet `concentration` publishes `largest_position`, `top_3/5/10`, `herfindahl_index`, `effective_positions`, `diversification_score`, `diversification_ratio`, `gini_coefficient`, `by_weight` (14), `by_sector` (7). `stress_testing` publishes four portfolio loss scenarios including `max_drawdown: -0.5453` (−54.53 %) for "Market Crash", each derived from `shock_inputs.volatility_adjustment.by_ticker[*].factor` with `basis: "measured_annualized_volatility_over_reference"`, `min_observations: 20`, `annualization_trading_days: 252` — and that adjustment block publishes **no window and no date** at all.

**Expected** Either a valuation date, or a warning stating that none exists. `stress_testing`'s volatility factor is a *measured* statistic; a measurement with no window and no date is not a measurement a consumer can age.

**Recomputation evidence**
```
--- concentration: as_of=None ---   date-like substrings: NONE   window/obs/date keys: []
--- stress_testing: as_of=None ---  date-like substrings: NONE   window keys: ['min_observations'] only
vol_adjustment window/date keys: NONE
concentration.status=available warnings=0  -> AVAILABLE+NO_ASOF, DATA+NO_ASOF
stress_testing.status=available warnings=0 -> AVAILABLE+NO_ASOF, DATA+NO_ASOF
```

**Root cause** `app/services/ai_context_service.py:496-499` — *"Nothing is invented: a payload that declares no freshness stays None rather than falling back to the export's own `generated_at`."* `_as_of` (`:487-523`) therefore returns `None`, and no caller turns a `None` `as_of` on a data-bearing section into a warning. The guardrail is equally blind: `env_013_no_null_as_of_with_dated_payload` (`app/debugging/context_audit.py:761-786`) only fires when the payload contains one of `DATED_OBSERVATION_KEYS` (`:100-114`) — these payloads contain no dates at all, so it cannot fire; `env_014_as_of_requires_semantics` (`:789`) only fires when `as_of` is **non-null**. The combination is a hole: *"data present, zero dates, zero warnings"* passes all 47 rules. **Proven by mutation** — overwriting `concentration.herfindahl_index` with `0.9999` (true `0.0862`) leaves the audit **green**. **Confidence: high.**

---

### DI-3 · P0 · `sections.liquidity` — a liquidation-window verdict with no date

**Observed** `status: "partial"`, `as_of: null`, `as_of_semantics: null`. Publishes `overall_score: 8`, `overall_band: "High"`, `liquidation_time_days: "1-2"`, `risk_level: "Low"`, plus per-leg `avg_volume`, `avg_turnover`, `market_cap`, `spread`, `category`, `liquidation_days`. The section's `latest_observation_date` is **`null`**. `data.observation_window.start` and `.end` are **`null`**; `scoring.observation_window.start` and `.end` are **`null`**; and **all 14** `scoring.observation_window.per_ticker[*].start`/`.end` are `null` — only `observations` is published (20–22 per leg, 290 total). Exactly **one** warning exists and it is about market caps only; nothing warns that the section has no valuation date.

**Expected** The observation window is stated (it is requested as `2026-08-27` → `2026-09-26`, 30 calendar days) and `as_of` is populated from `latest_observation_date`. A `1-2 day` liquidation claim is the single most time-sensitive number in the export.

**Recomputation evidence**
```
liquidity as_of = None   data.latest_observation_date = None
observation_window.start = None   observation_window.end = None
scoring.observation_window.start = None  .end = None
scoring.requested_window = {start: 2026-08-27, end: 2026-09-26}
per_ticker start/end = null for all 14 (observations published: 20-22 each)
  ARROWGREEN 21 CIPLA 21 ELECTCAST 22 JKIL 21 JUNIORBEES 20 MAFANG 20 MCX 21
  MIDCAPIETF 20 MOTHERSON 21 MOTILALOFS 21 NIFTYIETF 20 NTPC 21 REDINGTON 21 SELECTIPO 20
liquidity.warnings -> exactly 1, about market caps only
```

**Root cause** the same `as_of is None` path as **DI-2** (`ai_context_service.py:496-499`), compounded by `DATED_OBSERVATION_KEYS` (`context_audit.py:100-114`) omitting `data_range.start` / `data_range.end`, so `env_013` cannot see the dated window that *is* present at `data.data_range`. **Confidence: high.**

---

### DI-4 · P0 · `sections.pairs` and `sections.volatility_sizing` — `as_of` newer than their own inputs

**Observed**
- `pairs.as_of = "2026-09-25"`, `as_of_semantics = "latest_available_observation"`. The 91 pair rows' `overlap_end` are spread: `2026-09-22` × 12, `2026-09-23` × 24, `2026-09-24` × 45, `2026-09-25` × 10. **81 of 91 rows are older than the section's own `as_of`**; the minimum is 3 days older.
- `volatility_sizing.as_of = "2026-09-25"`, `as_of_semantics = "latest_observation_date"`. Its own `sizing_price_as_of`, `sizing_basis.sizing_price_as_of`, `sizing_basis.price_freshness.sizing_price_as_of` and `trade_reconciliation.sizing_price_as_of` are all **`2026-09-22`**. The section's **priced trade recommendations** are computed off a 2026-09-22 price while the envelope stamps the section 2026-09-25.

**Expected** Under the stated oldest-input rule, `pairs.as_of` should be `2026-09-22` and `volatility_sizing.as_of` should be `2026-09-22`. A section that publishes trade prices must not claim a freshness its own prices do not have.

**Recomputation evidence**
```
pairs overlap_end histogram: {2026-09-22: 12, 2026-09-23: 24, 2026-09-24: 45, 2026-09-25: 10}
  min 2026-09-22  max 2026-09-25  as_of 2026-09-25  rows older than as_of: 81
volatility_sizing as_of=2026-09-25  vs  sizing_price_as_of=2026-09-22  (x4 locations)
```

**Root cause** `app/services/ai_context_service.py:501-523`. The oldest-leg `min()` at `:522` is reached **only** for a payload with a `components` mapping (i.e. the dashboard). Every non-composite section takes rule 1/2 — *"the first declared timestamp the payload declares itself"* — via `_declared_as_of` (`:469-484`), which returns `latest_observation_date` (a max-like, self-declared stamp) and never consults sibling inputs. `volatility_sizing`'s 3-day gap is the material one: it dates a **recommendation** 3 days newer than the price it used. **Proven by mutation** — setting `pairs.as_of = 2026-10-15` and `volatility_sizing.as_of = 2026-10-05` both leave the audit **green**. **Confidence: high.**

---

### DI-5 · P1 · `sections.portfolio.omitted_fields: []` while the section publishes no cost/P&L/day-change aggregate

**Observed** `portfolio.omitted_fields = []`. Raw-byte counts across the whole 876 KB file: `"day_change"` **0**, `"previous_close"` **0**, `"prev_close"` **0**, `"total_pnl"` **0**, `"total_unrealized"` **0**, `"price_source"` **0**. `"total_cost"` appears 28× — exactly `14 positions × (total_cost, total_cost_base)`, never as an aggregate. There is **no portfolio-level `total_cost`, no `total_pnl`, no `total_day_change`, and no day-change percentage anywhere in the export.** So the `total_value` reconciliation has no counterpart: the reader can sum `total_cost` and `unrealized_gain_loss` themselves, but the export never publishes the totals and never says it omitted them.

**Expected** Either publish the aggregates, or list them in `omitted_fields`. As shipped, `omitted_fields: []` reads as "nothing was dropped" — a true statement about *compaction* and a misleading statement about *the ledger*.

**Recomputation evidence**
```
'day_change' 0   'previous_close' 0   'prev_close' 0   'total_pnl' 0   'total_unrealized' 0
'total_cost' 28  == 14 rows x 2 fields, no aggregate
portfolio.omitted_fields == []
```

**Root cause** `app/services/ai_context_service.py:2252-2326` — `_compact_detail` handles only six named sections (`dashboard`, `tear_sheet`, `monte_carlo`, `pairs`, `risk_studio`, `india_flows`) and trims only named list fields. There is **no `portfolio` branch**, so for `portfolio` compaction is a no-op and `omitted_fields` is `[]` by construction. The field is a *compaction* ledger and structurally cannot express "the endpoint never produced this". **Confidence: high** (behavioural gap; mechanism read at source).

---

### DI-6 · P1 · `sections.dashboard.components.summary.portfolio_value` vs `sections.portfolio.data.total_value`

**Observed** `43608.67` (2 dp) in the dashboard summary; `43608.66981063843` (17 significant digits) in the portfolio section. The same quantity, same export, **₹1.8937e-4 apart**. The summary also carries a **second, different live stamp** for the same 14 positions: `summary.last_updated = "2026-09-26T15:33:43.782044+00:00"` — 18.0 s after the portfolio section's `as_of`, and in a *different format* (`+00:00` vs `Z`) — while the summary's own declared component `as_of` is `2026-09-25` (`latest_observation_date`). So the composite publishes three conflicting freshness statements for one portfolio: `2026-09-26T15:33:25.781197Z` (portfolio), `2026-09-26T15:33:43.782044+00:00` (summary `last_updated`), `2026-09-25` (summary component `as_of`).

**Expected** One value, one precision, one stamp — or an explicit statement that the summary value is a rounded presentation of the portfolio value.

**Recomputation evidence**
```
|43608.67 - 43608.66981063843| = 0.000189
MONEY_ABS_TOLERANCE = 1e-6, MONEY_REL_TOLERANCE = 1e-9  (context_audit.py:133-134)
project money budget on 43608.67  = 1e-6 + 43608.67*1e-9 = 4.46e-05
observed divergence 1.8937e-04  =  4.2x the project's own money tolerance
```
**Proven by mutation** — setting `summary.portfolio_value = 50000` (a 15 % divergence from `portfolio.total_value`) leaves the audit **green**.

**Root cause** two independent producers with different rounding: `app/api/portfolio.py:486` (`total_value += converted_value`, unrounded float) versus the dashboard summary's own value path. No cross-section rule reconciles a composite's summary value against the portfolio section — `num_001_portfolio_totals` (`context_audit.py:1458-1500`) reads `data.positions` + `data.total_value` per section and never compares *across* sections. Secondary: `_AS_OF_KEYS` (`ai_context_service.py:457-463`) puts `latest_observation_date` ahead of `last_updated`, so the envelope reports the summary as `2026-09-25` while the summary body carries `2026-09-26T15:33:43Z`. **Confidence: high.**

---

### DI-7 · P1 · `num_001` cannot see the per-position ledger — 7 of 9 ledger mutations pass

**Observed** The entire position-level accounting is unverified by the project's own audit. `num_001_portfolio_totals` (`context_audit.py:1458-1500`) checks exactly two things: `Σ market_value == total_value` (via `_money_close`, `abs_tol 1e-6 / rel_tol 1e-9`) and `Σ weight == 1` (`abs_tol 1e-6`). Nothing else. Nine mutations, each objectively wrong, each re-run through all 47 rules:

| Mutation | Verdict |
|---|---|
| CIPLA `weight` **+5 pp**, NTPC −5 pp (Σ weight still `1.0`) | **NOT CAUGHT** |
| ELECTCAST `total_cost` → `999` (true `q×buy = 2083.60`) | **NOT CAUGHT** |
| MOTHERSON `unrealized_gain_loss` → `0` (true `+2812.68`) | **NOT CAUGHT** |
| JKIL `unrealized_gain_loss_pct` → `99.0` (true `−30.445`) | **NOT CAUGHT** |
| CIPLA `market_value_base` ×= `83`, native left alone | **NOT CAUGHT** |
| all 14 `native_currency` → `"USD"` with `fx_rate = 1` | **NOT CAUGHT** |
| ELECTCAST `ticker` → `"CIPLA.NS"` (duplicate position) | **NOT CAUGHT** |
| `portfolio.sectors.Healthcare` → `0.5` (sum `1.436`) | **NOT CAUGHT** |
| MOTHERSON `market_value` **+10 %** | CAUGHT — `NUM-001` |
| `total_value` → `99999` | CAUGHT — `NUM-001` |
| CIPLA `weight` → `0.5` | CAUGHT — `NUM-001` |
| drop a position row (Σ mv ≠ total) | CAUGHT — `NUM-001` |

**Expected** `q × price`, `q × avg_cost`, `MV − cost`, `pnl/cost`, `(price−avg)/avg`, per-row `weight = mv/Σmv`, and `*_base == native × fx_rate` should all be recomputed by a rule, the way `num_004` already recomputes liquidity bands (*"recomputed, not trusted"*).

**This is not a live defect — it is the reason there is no live defect.** I verified all 14 rows by hand and every identity holds to `0.0e+00`. The finding is that **nothing in the repo would have told anyone if it did not.** The all-14-`USD` mutation is the sharpest illustration: it manufactures exactly the "USD-listed position valued at an INR-converted price with an unstated rate" P0 the brief asks me to hunt, and the audit stays silent. **Root cause** `app/debugging/context_audit.py:1458-1500` — `num_001` is scoped to the two aggregate sums; there is no `num_0xx_position_identity` rule. **Confidence: high** (mutation-tested).

---

### DI-8 · P1 · `env_012` guard is inverted — future and ancient `as_of` both pass

**Observed** `env_012_as_of_outside_collection_window` (`context_audit.py:722-758`) is named for *outside* the window but its guard is `if not (generated <= as_of <= completed): continue` (`:739`) — it `continue`s, i.e. **skips**, on any `as_of` outside the bracket, and only evaluates the *inside* case. So the two cases that matter most are silently discarded: an `as_of` **after `completed_at`** (unambiguous fabricated time travel) and an `as_of` **years stale**.

**Expected** `as_of > completed_at` must be a finding, unconditionally. `as_of` far outside `[generated_at − tolerance, completed_at]` on the stale side must be a finding too.

**Recomputation evidence**
```
M1  portfolio as_of -> 2027-03-01T00:00:00Z   (5 months in the future)  NOT CAUGHT
M2  portfolio as_of -> 2015-01-01T00:00:00Z   (10 years stale)          NOT CAUGHT
```
The real export's `as_of` is only +18.049 ms past `generated_at`, so it *does* land inside `[generated_at, completed_at]` and ENV-012 evaluates it — and correctly suppresses a finding because the refresh is disclosed. The harness is therefore silent on a 5-month fabrication while being *designed* to catch a 18-millisecond one. **Root cause** `app/debugging/context_audit.py:739`. **Confidence: high** (mutation-tested).

---

### DI-9 · P1 · float32 quantization published as 17-digit precision

**Observed** **10 of 14** `last_price` values are exact float32 round-trips (verified with `struct.pack('f', x)`): `CIPLA 1399.699951171875` (= float32 of 1399.70), `ELECTCAST 72.33999633789062`, `JKIL 473.54998779296875`, `MCX 3324.89990234375`, `MIDCAPIETF 23.309999465942383`, `MOTHERSON 165.7100067138672`, `NTPC 326.6000061035156`, `ARROWGREEN 905.7999877929688`, plus `MOTILALOFS 1029`, `REDINGTON 407.25`. This is the yfinance/pandas float32 channel, and it propagates: `market_value 2799.39990234375`, `total_value 43608.66981063843`.

**Expected** Either round to the exchange tick, or publish the source precision. `total_positions: 14` positions, `total_value` with 17 significant digits, and `dashboard.summary.portfolio_value: 43608.67` — the export simultaneously claims 1e-11 and 1e-2 precision on the same ledger.

**Recomputation evidence**
```
legs whose last_price is a float32 round-trip: 10 / 14
CIPLA  last_price 1399.699951171875  (float32 of the 2-dp value 1399.70)
       market_value 2799.39990234375 ; total_value 43608.66981063843
       vs dashboard summary.portfolio_value 43608.67
```
**Root cause** price ingestion (float32 dtype) upstream of `app/api/portfolio.py:438-441`, which multiplies the float32 straight into `native_current` with no tick normalisation. No rule inspects source precision. **Confidence: high** for the float32 identity; **medium** for attributing the dtype to yfinance specifically (the export's `environment.primary_source: "yfinance"` is a preference order, and `environment.source_semantics` says so explicitly — *"primary_source is preference order, not per-observation vendor proof"* — which the export states honestly).

---

### DI-10 · P1 · Unit incoherence inside single blocks — `weight` fraction vs `unrealized_gain_loss_pct` percent, 0-100 scores beside 0-1 fractions

**Observed** In one `positions` row: `weight: 0.06419365494291758` (fraction) beside `unrealized_gain_loss_pct: -2.2043702237991267` (percent) — a 100× trap with no unit key on either. In one `dashboard.components.summary.data` block: `concentration_score: 8.62` and `risk_score: 13.7` (0-100) beside `realized_volatility: 0.0982`, `forecast_volatility: 0.1377`, `max_drawdown: -0.0213` (0-1 fractions) and `sharpe_ratio: 3.486` (unitless) — no `*_units`, `*_scale` or `annualized_basis` key on the scores. `concentration_score` is exactly `HHI × 100` (`8.62`), while `concentration.by_weight` holds fractions summing to `1.0`; `liquidity` is the only section that does this properly (`scoring.scale.unit: "index_0_to_10"`).

**Expected** Every score and ratio either declares its scale or uses a name that carries it.

**Recomputation evidence**
```
CIPLA: weight 0.06419365 (fraction) | unrealized_gain_loss_pct -2.20437 (percent)  -> 100x, unlabelled
summary: concentration_score 8.62 == herfindahl_index 0.0862 * 100   (exact)
         risk_score 13.7, realized_volatility 0.0982, sharpe_ratio 3.486, max_drawdown -0.0213 -> one flat block
liquidity (correct pattern): scoring.scale = {min 2.5, max 10, unit 'index_0_to_10'}
```
**Root cause** no shared unit/scale convention in `_make_section` (`ai_context_service.py:1529-1598`) — it publishes `currency` (`:1548`) but has no analogous `_infer_unit`. **Confidence: high.**

---

### DI-11 · P1 · `SELECTIPO.NS` market cap is the hardcoded ₹1,000,000,000 floor, and a portfolio-level verdict is published from it

**Observed** `liquidity.by_position["SELECTIPO.NS"]` = `market_cap: 1000000000` (exactly 1e9), `market_cap_provenance: "fallback"`, `market_cap_source: "fixed_floor_1e9_inr"`, `is_estimate: true`. **Disclosure here is exemplary** and I want that on the record: `scoring.market_cap_floor` publishes the constant with `provenance: "fallback"` and a note; `estimated_market_cap_count: 5`, `measured_market_cap_count: 9`, `fallback_market_cap_count: 1`, `non_measured_market_caps` (5 tickers), `non_measured_by_provenance: {estimated: 4, fallback: [SELECTIPO.NS]}` are all published at section level; the per-leg `spread` block explicitly warns that `MCX.score_raw = 10` is a *capped* value with `score_ceiling_applied: true`; and the fact appears in **two** warnings (`liquidity.warnings[0]` and `dashboard.warnings[8]`), each naming the floor value, the ticker and the consequence.

**The residual defect is propagation, not concealment.** `SELECTIPO.NS` scores `3.4` → `category: "Low"` → `liquidation_days: "5-10"`, and the section publishes the portfolio verdict `overall_score: 8`, `overall_band: "High"`, `liquidation_time_days: "1-2"`, `risk_level: "Low"` — computed partly from that fabricated cap. A consumer reading only the portfolio-level band gets a "High / 1-2 days / Low risk" answer with no pointer to the floor (the warnings are section-scoped, and the dashboard *withholds* the score entirely while the `liquidity` section publishes it).

**Expected** A portfolio-level verdict resting partly on a fallback cap should carry the provenance forward (e.g. `overall_score_provenance`), or the `liquidity` section should not publish `overall_band`/`risk_level` while `fallback_market_cap_count > 0`.

**Root cause** the floor constant and its provenance live at the *leg* level (`by_position.*.market_cap_provenance`) with no roll-up to the section verdict; the composite roll-up is not provenance-aware. **Confidence: high** on the numbers; **medium** on the recommended shape.

---

### DI-12 · P2 · `risk_studio.omitted_fields` names a field that is present

**Observed** The export's **only** non-empty `omitted_fields` is `["components.correlation_stability.data.series"]` — and the field is present, at 60 entries. The true shape is published alongside: `series_trimmed_in_summary: true`, `series_observations: 489`, `series_retained: 60`.

**Recomputation evidence**
```
resolved path sections.risk_studio.data.components.correlation_stability.data.series
  -> present: True, len = 60   (of 489 observations)
omitted_fields claims OMITTED; the field ships.
```

**Root cause** `app/services/ai_context_service.py:2308-2316` — the comment *names this exact problem* (*"`omitted_fields` says a field was OMITTED, but this one is still present (just shorter). Listing the bare path made a consumer skip a field that exists."*), adds the honest `series_trimmed_in_summary` metadata, and then appends the bare path to `omitted_fields` anyway at `:2316`. Every other section's `omitted_fields: []` is **correct** against the compaction contract (verified: `performance_history` 19 rows ≤ 90; `monthly_returns` 1 ≤ 24; `underwater` 39 ≤ 90; `monte_carlo.fan` 11 ≤ 12; 91 pairs with no `spread_series`; `institutional_flows` unavailable so no `flows`) — so `risk_studio` is the sole offender, and it is offending in a file whose own code flagged the defect. **Confidence: high.**

---

### DI-13 · P2 · Envelope `warnings: []` while 17 section warnings exist

**Observed** Top-level `warnings` is `[]`; the sum across sections is **17** (dashboard 9, india_flows 4, portfolio 1, realized_risk 1, liquidity 1, pairs 1), carrying **15** distinct facts — `dashboard.warnings[6]` is byte-identical to `realized_risk.warnings[0]` (408 chars, `identical: True`) and `dashboard.warnings[7]` to `liquidity.warnings[0]`. Zero duplicates *within* any section, so the in-section `dict.fromkeys` dedupe works; the redundancy is cross-section.

**Expected** A consumer scanning `warnings` at the envelope finds nothing and concludes the export is clean.

**Root cause** `app/services/ai_context_service.py:1494` — the envelope `warnings` list is only ever appended to by the data-source-metadata failure at `:1473`; section warnings never roll up. `dict.fromkeys` at `:1577` dedupes within a section only. This is *by design* and the design is defensible (per-section self-containment), but the field name is wrong for what it holds. **Confidence: high** on mechanism, **medium** on whether it is worth changing.

---

### DI-14 · P2 · 10 of 17 sections publish `currency: null`

**Observed** `currency: null` for `realized_risk`, `forecast_risk`, `factor_exposure`, `concentration`, `stress_testing`, `tear_sheet`, `risk_contribution`, `risk_studio`, `optimization`, `regime`. `currency: "INR"` for `portfolio`, `dashboard`, `liquidity`, `volatility_sizing`, `monte_carlo`, `pairs`, `india_flows`. Meanwhile `currency_policy` promises *"analytics sections retain their endpoint-declared monetary units"* — and 10 of them publish none.

**Expected** Per the documented contract (`_infer_currency`, `ai_context_service.py:563-591`) `null` is *correct* for a weightless section, and `env_015` (`context_audit.py:811-864`) passes because those payloads declare no currency key. But the export gives a consumer **no way to distinguish** "unitless by construction" from "monetary values present, label withheld" — and `concentration` / `stress_testing` / `optimization` are weight-and-magnitude sections where the distinction matters. **Root cause** no `unit: null`-with-reason vocabulary in the envelope schema (`app/models/schemas.py:144`, `:484`). **Confidence: medium** (contract-conformant; the ambiguity is the finding).

---

### DI-15 · P2 · `as_of` timezone is a known-wrong reinterpretation, and only `holding_date_provenance` says so

**Observed** All 14 `updated_on` and the portfolio `as_of` are naive DB write times rendered with a trailing `Z`. NSE runs IST (UTC+5:30), so the rendering mislocates every price instant by up to 5.5 hours. The export **does** disclose this: `holding_date_provenance.quote_timestamp_timezone` reads *"updated_on is a naive datetime column and carries no offset. as_of renders it as UTC (a trailing Z) so the envelope stays ISO-parseable; the UTC designation is an interpretation, not a stored fact."* (`app/api/portfolio.py:116-120`).

**Expected** Honest disclosure is present and unusually good. The residual defect is that `as_of` still carries the `Z` — `env_012`'s timestamp comparison and any consumer's parser will treat it as UTC — and this is the **only** section whose `as_of` is a timestamp rather than a date, so it is the only one exposed. **Root cause** `app/api/portfolio.py:100-102` (`.replace(tzinfo=timezone.utc)`), mitigated-but-not-fixed by `:116-120`. **Confidence: high.**

---

### DI-16 · P2 · The portfolio freshness warning is true for 2 of 14 legs

**Observed** `portfolio.warnings[0]` asserts the value *"was refreshed during this export."* Twelve of fourteen `updated_on` stamps (`15:33:06.491757` – `15:33:10.759465`) **precede** the envelope's `generated_at` (`15:33:25.763148`); only `CIPLA.NS` (`15:33:25.777771`) and `ARROWGREEN.NS` (`15:33:25.781197`) fall inside the collection window. The 14 stamps span **19.289 s**. With `environment.cache_ttl_minutes: 60`, a leg could be up to 60 minutes older than `as_of` implies, and nothing publishes that spread.

**Recomputation evidence**
```
legs stamped BEFORE export generated_at: 12 / 14
legs stamped AFTER  export generated_at:  2 / 14
quote stamp spread = 19.289 s ;  environment.cache_ttl_minutes = 60
```

**Expected** Either name the spread, or say "the newest of 14 quote stamps, which span N seconds". **Root cause** the warning is generated from `as_of` alone — `_run_timestamp_as_of` (`ai_context_service.py:984-1012`) receives only `resolved` and `data`, and has no access to the per-position stamps it is characterising. **Confidence: high.**

---

### DI-17 · P2 · `as_of_semantics: "declared_as_of"` on the one section that most needs a real label

**Observed** `portfolio.as_of_semantics = "declared_as_of"` — the fallback label from `_AS_OF_SEMANTICS["as_of"]` (`ai_context_service.py:930`), i.e. the exporter naming *the mechanism* rather than the meaning. It is also the label on `regime` and `risk_studio`. The dashboard, which has the same problem, gets the informative `oldest_component_observation` (`:849`, applied at `:1459`). Only `india_flows` publishes a genuinely explanatory label (`liquidity_component_only`, plus a 250-char `as_of_note` stating the portfolio quote date is never used).

**Expected** `portfolio.as_of_semantics` should say something like `newest_quote_write_timestamp_non_trading_day` — the export already knows all of this, it just does not say it in the label. **Root cause** `_payload_as_of_semantics` (`:951-965`) prefers a payload-declared label and otherwise falls back to the key name; `portfolio.data` declares no `as_of_semantics`, so it gets the generic one. **Confidence: high.**

---

## What I checked and found clean (so it is not re-litigated)

- **No wrong-currency or unstated-FX P0.** All 14 positions are `.NS` with `native_currency`/`value_currency` both `INR`, `fx_rate` exactly `1`, `fx_provenance: {provenance: "identity", source: "identity", is_fallback: false}`, and all seven `*_base` fields byte-equal to their native counterparts. `currency_provenance` publishes `aggregation: "per_position_conversion"`, `source_currencies: ["INR"]`, `supported_currencies: ["INR","USD"]`, `pairs: {"INR->INR": {rate: 1, provenance: "identity"}}`, `rate_provider: "currency_service"` — and that derivation is **honest**: with a single source currency, identity *is* the conversion, and the export says so rather than implying a live rate. `position_currencies` publishes a per-ticker map, so the INR determination is measured, not assumed. No position claims a market cap or price derived from a hardcoded floor inside the `portfolio` section (the floor is confined to `liquidity`, and is provenance-tagged — **DI-11**).
- **No `is_estimate` / `provenance` flag on any portfolio price, because the portfolio section publishes no price provenance at all.** Position keys are exactly: `id, ticker, weight, quantity, buy_price, last_price, market_value, sector, industry, region, custom_name, added_on, updated_on, total_cost, unrealized_gain_loss, unrealized_gain_loss_pct, current_value, native_currency, value_currency, fx_rate, fx_provenance, market_value_base, buy_price_base, last_price_base, current_value_base, total_cost_base, unrealized_gain_loss_base, unrealized_gain_loss_pct_base`. There is no `price_source`, no `is_estimate`, no `provenance` on a price. The only freshness evidence per leg is `updated_on` — and the export is upfront that it is a naive DB write time (**DI-15**). `environment.source_semantics` (*"primary_source is preference order, not per-observation vendor proof"*, `ai_context_service.py:1476`) is an honest blanket disclaimer covering the missing per-observation vendor proof.
- **`snapshot_consistency: "best_effort"` (hardcoded at `ai_context_service.py:1484`) is honest but under-specified.** Nothing claims simultaneity it does not have: the `portfolio` section is a live quote, the analytics sections are 2026-09-25 price observations, and the dashboard's `component_as_of` map publishes all eleven legs individually. The real incoherence is the **19.289 s** intra-portfolio spread and the dashboard's three conflicting stamps (**DI-1**, **DI-6**) — not a cross-section simultaneity claim. What `best_effort` does *not* say, and should: it is a constant, carries no definition, and no section is annotated with which legs it covers. The envelope never states the actual valuation-date spread (2026-09-21 → 2026-09-26) anywhere.
- **Status/warning coherence.** `dashboard` (`partial`, 9 warnings): status is justified. Enumerated — W1 liquidity_score withheld (`source_section_partial`, and `summary.liquidity_score` is indeed `null`); W2 the withheld 2026-09-22 observation (matches `withheld_portfolio_observations: ["2026-09-22"]` and `series_end_reason`); W3/W4/W5/W6 are four phrasings of one history-coverage fact (all consistent with `history_coverage: {delivered 19/65, coverage_ratio 0.292308, truncated true, stale true, status partial}`); W7 ≡ `realized_risk` W1 byte-identical; W8 ≡ `liquidity` W1 byte-identical; W9 R² 0.24. Three genuinely dashboard-specific (W1, W2, W9). **Verdict: honest, verbose, no contradiction.** `india_flows` (`partial`, 4 warnings): **status matches exactly** — 2 of 3 components unavailable (`institutional_flows`, `delivery_anomalies`), 1 available (`liquidity_limits`); `component_status` agrees; `coverage_status` agrees; the `as_of_note` honestly states `as_of` comes from the liquidity leg's newest price observation and *"the portfolio quote date is never used"*; and `component_as_of` publishes `{institutional_flows: null, delivery_anomalies: null, liquidity_limits: "2026-09-25"}`. Every section's payload-level `data_status` agrees with its section-level `status` in all 17 cases. No section is `unavailable` with data. No section is `partial` with zero warnings.
- **Envelope structure.** `scope` == `sections` keys, same set **and order**. `generated_at (15:33:25.763148Z) ≤ completed_at (15:33:44.465749Z)`, bracket `18.703 s` — sane, and each section's `generated_at` falls monotonically inside it. `export_id portfolio-4b78905b588c` is `f"portfolio-{uuid.uuid4().hex[:12]}"` (`:1481`) — a fresh random id, not a content hash, so it is not evidence of tampering either way. `detail: "summary"` is honoured consistently. No `error` key anywhere, no `not_requested`, no NaN/Infinity, no duplicate object keys, strict-JSON reparse clean.
- **Fabrication sweep.** 14 unique tickers, ids 1–14 unique, `custom_name` == ticker stem for all 14, all `.NS`, all `region: "IN"`, sector↔industry not 1:1 (correct — 10 industries across 7 sectors). All 17 sections' `coverage.covered_tickers` are byte-identical to the portfolio's 14, `missing_tickers: []` in all 17 — no ticker appears in one section and silently vanishes from another. No duplicated entries anywhere. Every `last_price` sits on a valid ₹0.01/₹0.05 tick once float32 noise is removed — nothing is a suspiciously round fabricated value. `SELECTIPO.NS` is genuinely `sector: "Exchange Traded Fund"`, `industry: "ETF"` — correct (Select IPO ETF is a real NSE ETF), *not* a taxonomy error. Added-on dates are all plausible weekdays (2024-11-25 Mon, 2024-12-09 Mon, 2025-02-14 Fri, 2025-03-07 Fri, 2025-03-21 Fri, 2025-04-24 Thu, 2025-05-19 Mon, 2025-07-17 Thu, 2025-08-20 Wed, 2026-06-08 Mon, 2026-08-04 Tue). The only non-ASCII character in the file is `U+2014 EM DASH` ×4 — **not** encoding corruption (I checked; the `�` in console output is a PowerShell rendering artifact).
- **Cross-section numerics I recomputed and confirmed.** `concentration` reconciles to the portfolio weights exactly (all 14, sum 1.0, residual 0.0 on the 4-dp sector round). `stress_testing` reconciles: `max_drawdown == portfolio_impact × 1.15` for all 4 scenarios to ≤4.5e-05, and `portfolio_impact == Σ weight × position_impact` over all 4 scenarios × 14 legs to ≤1.2e-05 (both 4-dp rounding). `dashboard.summary.concentration_score == herfindahl_index × 100` exactly. `performance_history` `return` matches `pv[i]/pv[i−1] − 1` on 17 of 19 rows to `<1e-12` (2 rows drift ≤6.6e-07 — endpoint rounding, immaterial). `pairs`: `n(n−1)/2 == scanned_pairs_count`, status `partial` correctly forced by the shallow leg. `liquidity`: every leg's `category` matches its own published `score` under the declared band rule, and the `MCX` cap is disclosed rather than presented as measured.

---

## Recommended fixes, in order

| # | Fix | File:line |
|---|---|---|
| 1 | Make `_quote_as_of` return `min()` (or publish both `as_of_newest_quote` and `as_of_oldest_quote`), and stop stamping it as a bare `Z` | `app/api/portfolio.py:105` |
| 2 | Stamp `generated_at` *after* the portfolio fetch, or move `_EXPORT_STARTED_AT[0]` to the true collection start | `app/services/ai_context_service.py:1330-1331` |
| 3 | Apply the oldest-input rule to **non-composite** sections too: min over sibling date fields, not just over `components` | `app/services/ai_context_service.py:501-523` |
| 4 | Fix the inverted `env_012` guard so `as_of > completed_at` is a finding, not a `continue` | `app/debugging/context_audit.py:739` |
| 5 | Add a per-position identity rule: `q×price`, `q×avg_cost`, `MV−cost`, `pnl/cost`, per-row `weight`, `*_base == native×fx` | new `num_0xx` beside `context_audit.py:1458` |
| 6 | Emit a warning (and downgrade status) on any data-bearing section with `as_of: null`; extend `DATED_OBSERVATION_KEYS` with `data_range.start/end` | `ai_context_service.py:1568`, `context_audit.py:100-114` |
| 7 | Reconcile `dashboard.components.summary.portfolio_value` against `portfolio.data.total_value` at one shared precision | cross-section rule |
| 8 | Round prices to the exchange tick at ingestion, or publish the source precision | upstream of `app/api/portfolio.py:438` |
| 9 | Replace the bare `omitted_fields` path with the real path + the trim counts, or rename the field | `ai_context_service.py:2316` |
| 10 | Roll `market_cap_provenance` up to the `liquidity` section verdict | `app/api/portfolio.py`-analog in the liquidity service |
| 11 | Give `portfolio.as_of_semantics` a real label, and name the 19.289 s quote spread | `ai_context_service.py:1569` |

---

**Bottom line for the release decision:** the arithmetic is sound and I would ship the numbers. Do not ship the *freshness layer* as-is without DI-1 through DI-4 resolved — a consumer reading `sections.portfolio.as_of` will believe a Saturday 15:33 UTC market observation exists, and DI-5 through DI-8 mean the next export can be arbitrarily wrong and still report 47/47 green.
