# Accuracy of `docs/research/` — fact-check against current code

Source: a read-only explorer verified every verifiable claim in the six 2026-09-27 research reports
against the code on 2026-10-02. Orchestrator spot-checked the load-bearing claims separately.

**The documents are ~5 months stale on coordinates and substantially sound on substance.**

---

## Verdict

**Substance holds; coordinates are void.** Not one of the 12 licensing claims is wrong — all 12 were
fetched from upstream and match, including the two highest-stakes ones. The architecture advice also
holds: backtrader and backtesting.py are genuinely disqualified by licence, HRP should stay hand-rolled,
the "keep" list is still keep-worthy.

What is broken is the inventory's coordinate system. `analytics_engine.py` has grown **4,119 → 6,365
lines (+55%)** and **34 of 44** symbol-index entries now point at the wrong line. Zero symbols were
deleted and zero renamed — **the document is unusable as a lookup table and dangerous as a refactor
checklist.**

The three most valuable corrections:

1. **The corpus's #1-ranked recommendation is already shipped.** The consolidated report says
   *"ADOPT — upgrade now, your pin is four versions / eight months stale"* against a pin of `0.0.81`.
   `backend/pyproject.toml:21` already reads **`"quantstats>=0.0.85"`**. **Verified.**
2. **Three of the five HIGH/MEDIUM violations the docs list as open have since been fixed**, so §5 of
   both the inventory and the consolidated report is now an action list of defects that no longer exist.
3. **A capability the doc lists as "not implemented" is shipped.** `current-codebase-quant-inventory.md:142`
   reads `| ADF / KPSS / Granger causality | - | **not implemented** | 0 |`. But
   `cointegration_service.py:15` is `from arch.unitroot import ADF, KPSS`, with the gate at `:186-192`.

---

## `current-codebase-quant-inventory.md` — capability table

**0 symbols deleted · 0 renamed · 34 of 44 `analytics_engine.py` index entries at wrong lines.**

Row-for-row verification of the symbol index is in the explorer's full output. Line-exact entries
include `portfolio_return_coverage_block:163`, `_active_weight_frame:63`, `aggregate_active_returns:255`,
`LIQUIDITY_SCORE_BANDS:308`, `liquidity_analysis:3905`, `stress_test:4042`, `risk_scoring:4972`,
`_garch_forecast:5839`, `_egarch_forecast:5916`, `GlobalAnalyticsEngine:6765`.

**Present in code but absent from the index (≥50 module-level symbols), all verified reachable** —
including `autocorrelation_disclosure:1136`, `effective_n_reproducibility_bound:1106`,
`market_model_witness:2159`, `volatility_forecast_point:6497`,
`pairwise_average_correlation_statistics:2333`, `regression_r_squared_statistics:2422`,
`CONCENTRATION_DIVERSIFICATION_SCORE_FORMULA:437`, `RISK_SCORE_LEG_SPECS:590`.

**The "47 capabilities" headline is not reproducible from the document's own tables**, which enumerate
~83 rows in §2.1–§2.7 alone. The count is wrong in the opposite direction to under-counting.

**`benchmark_service.py` — precise claim.** It is absent from `current-codebase-quant-inventory.md`
specifically, but it **is** referenced in 10 places across the other four reports
(`data-and-indicator-libraries.md:28,1179,1359`; `institutional-libraries.md:113`;
`performance-and-backtesting-libraries.md:1201,1540`; `portfolio-optimization-libraries.md:331,878,1023,1475`).
So: **missing from the inventory, not from the corpus.** It is also the location of OE-04 (the
`^NSEI` price-vs-total-return index question), so it is a live and relevant service.

## §5 zero-mock violations — status today

| doc severity | issue | status |
|---|---|---|
| HIGH | Fabricated `market_value=10000.0` per ad-hoc position | **FIXED.** Zero repo-wide matches. Control: the same pattern matches `backtest_service.py:70`, proving the search works. |
| MEDIUM | Period sum published as `annual_return`; hard `sharpe=0.0`/`sortino=0.0` | **FIXED.** Now publishes `None` for all three, with a comment naming the old bug — `analytics_engine.py:5458-5461`. |
| MEDIUM | Equal-weight "market portfolio" in Black-Litterman; silent clip+renorm | **PERSISTS.** `w_mkt = np.ones(n) / n` at `optimization_service.py:791`; `np.clip(raw, 0.0, None)` at `:848`. |
| MEDIUM | Transition matrix published is a prior, never fitted | **PERSISTS — the doc's line was exact.** `sticky_trans` at `regime_service.py:307-311`, `params="mc"` at `:317`, `hmm.transmat_ = sticky_trans.copy()` at `:323`. |
| MEDIUM | Hardcoded per-ticker / 7×7 sector stress elasticities | **PERSISTS, expanded.** `STRESS_CO_MOVEMENT_BASIS:388`, `STRESS_UNCLASSIFIED_SECTOR:374`. |
| MEDIUM | "Student-t copula" is not a copula fit | **PERSISTS mathematically, now self-disclosed.** `calculate_bivariate_tail_dependence` at `tail_risk_service.py:441`; the docstring says "an approximation, not a joint copula fit". |
| LOW | Unreachable duplicate `except HTTPException` | **PERSISTS.** `analytics.py:12343` catches all `HTTPException`, making `:12347` unreachable. (Independently found as API-7.) |
| LOW | `/vol-cone` validates `lookback_days` but never passes it | **PERSISTS.** `analytics.py:12330` calls `calculate_volatility_cone(port_ret)` with one argument. |
| LOW | `ddof=0` inconsistency | **FIXED.** Zero `ddof=0` matches repo-wide. |
| LOW | EWMA seed/iterate window mismatch | **PERSISTS.** `_ewma_forecast` at `analytics_engine.py:5996`. |
| LOW | `quantlib` declared, never imported | **PERSISTS — doc correct.** `pyproject.toml:37` + `uv.lock`; control search across `app/` returned 23 hits for other libraries, none for QuantLib. |

## §3 "free capability additions" — already-shipped check

| addition | status |
|---|---|
| **ADF / KPSS stationarity** | **ALREADY IMPLEMENTED.** `cointegration_service.py:15` imports `from arch.unitroot import ADF, KPSS`; `assess_leg_stationarity`, `assess_pair_stationarity`, `stationarity_gate_of`, ADF+KPSS agreement adjudication, and the full `STATIONARITY_*` constant set. The doc's "not implemented, Effort S" is obsolete. |
| Granger causality | still absent — control search, no `grangercausalitytests` |
| GJR-GARCH | still absent — `arch_model` used at `analytics_engine.py:6582`/`:6586`, both `p=1,q=1`, no `o=1` |
| Bonferroni / BH via `multipletests` | still hand-rolled at `cointegration_service.py:427,444` |
| VaR horizon label | still absent — `_calculate_risk_metrics:5491` returns bare `var_95`/`cvar_95` |
| Parkinson via `arch.roll_volatility` | still hand-rolled at `regime_service.py:273` |
| Efficient frontier / risk parity / sector caps / CVaR turnover penalty | still absent |

## File growth — every `file:line` in the corpus should be treated as void

| file | doc LOC | actual | delta |
|---|---|---|---|
| `analytics_engine.py` | 4,119 | **6,365** | +55% |
| `cointegration_service.py` | ~1,330 | ~1,900 | +43% |
| `optimization_service.py` | 838 | **959** | +14% |
| `tail_risk_service.py` | ~500 | ~700 | +40% |
| `api/analytics.py` | 8,398–8,535 | ~12,600 | +50% |
| `monte_carlo_service.py` | 436 | ~450 | all symbols still exact |
| `regime_service.py` | 624 | ~630 | all symbols still exact |
| `correlation_service.py` | 193 | 193 | exact |
| `backtest_service.py` | 237 | ~240 | exact |
| `currency_service.py` | 398 | ~400 | exact |

---

## Licensing — 12 of 12 checked, 0 wrong, 0 unverifiable

Every licence was fetched from upstream on 2026-10-02. This was the highest-risk claim class in the
corpus and it held completely.

| library | claimed | actual | source |
|---|---|---|---|
| quantstats | Apache-2.0 | Apache-2.0 (canonical, no rider) | `raw.githubusercontent.com/ranaroussi/quantstats/main/LICENSE.txt`; PyPI `spdx_id: Apache-2.0` |
| PyPortfolioOpt | MIT | MIT © 2018 Robert Andrew Martin | `raw.githubusercontent.com/robertmartin8/PyPortfolioOpt/master/LICENSE` |
| Riskfolio-Lib | BSD-3-Clause | BSD-3-Clause © **2020-2026** Dany Cajas | `api.github.com/repos/dcajasn/Riskfolio-Lib/license` |
| skfolio | BSD-3-Clause | BSD-3-Clause © 2023-2026 | `api.github.com/repos/skfolio/skfolio/license` |
| FinQuant | MIT | MIT; v0.7.0 released 2023-09-04. Repo is `fmilthaler/FinQuant`, **not** `ranaroussi` | `pypi.org/project/FinQuant/` |
| FinanceToolkit | MIT | MIT © 2025 Jeroen Bouma | `raw.githubusercontent.com/JerBouma/FinanceToolkit/main/LICENSE.txt` |
| FinanceDatabase | MIT | MIT © 2023 Jeroen Bouma | `raw.githubusercontent.com/JerBouma/FinanceDatabase/main/LICENSE` |
| shashankvemuri/Finance | MIT | MIT © 2021 Shashank Vemuri | `api.github.com/repos/shashankvemuri/Finance/license` |
| QuantLib | BSD-3-Clause | BSD-3-Clause, three clauses verbatim, non-endorsement present | `raw.githubusercontent.com/lballabio/QuantLib/master/LICENSE.TXT` |
| gs-quant | Apache-2.0 | Apache-2.0, unmodified | `api.github.com/repos/goldmansachs/gs-quant/license` |
| **backtrader** | GPL-3.0-or-later | `license: "GPLv3+"`, classifier GPLv3+; LICENSE verbatim | `pypi.org/pypi/backtrader/json`; `raw.githubusercontent.com/mementum/backtrader/master/LICENSE` |
| **backtesting.py** | AGPL-3.0 | `license: "AGPL-3.0"`, v0.6.6 | `pypi.org/pypi/backtesting/json` |

**Two corrections of detail, not substance:**
1. **QuantLib third-party attributions are under-quoted.** The doc cites one ("Stephen Joe and Frances
   Kuo"). The current `LICENSE.TXT` lists **three**: Jäckel's *Monte Carlo Methods in Finance*,
   University of Chicago / Argonne National Laboratory, and Joe/Kuo. Both remain in the redistribution
   obligation.
2. **backtrader abandonment confirmed precisely** — last PyPI release `1.9.78.123` uploaded
   `2023-04-19T14:13:18Z`. The doc's date is exactly right.

**Installed-environment claims all hold:** `pyproject.toml`/`uv.lock` contain none of `pypfopt`,
`skfolio`, `riskfolio-lib`, `copulas`, `empyrical`, `financetoolkit`, `financedatabase`, `ruptures`.
`bfinance`, `arch`, `cvxpy`, `hmmlearn`, `stockstats`, `statsmodels`, `sklearn` are all present and
all still imported.

---

## Recommendations already implemented — do NOT action these

1. **quantstats pin upgrade — DONE.** Highest-ROI item in the corpus; already shipped at
   `pyproject.toml:21`. **Retire this ticket.**
2. **ADF/KPSS stationarity — DONE.** See above.
3. **`quantstats_ratio_statistics` "delete this duplication"** — the doc records an internal reversal
   (§4). Live code confirms §4: wired to `api/analytics.py:616`. Any refactor ticket from §2's
   "duplication" column is void.
4. **VaR horizon label** — still open, but the short-sample defect it sat beside is now fixed, so the
   doc's remediation context is stale.

## Recommendations that remain valid

- **backtrader AVOID (GPL-3.0-or-later), backtesting.py AVOID (AGPL-3.0)** — licence blockers are
  permanent. Close permanently.
- **FinQuant AVOID** — MIT is fine; the reasons are maintenance and scope (v0.7.0 from 2023-09-04).
- **QuantLib: decide.** Still a **dead dependency** — declared at `pyproject.toml:37`, locked, imported
  nowhere in `app/`. Either land options pricing or remove the pin.
- **HRP: do not migrate to `HRPOpt`** — the scipy-1.18 `_LINKAGE_METHODS` argument underpinning the
  HRPOpt verdict was **not** re-tested here. Treat as plausible-but-unconfirmed; keep-as-is is the safe
  default either way. `_hrp_weights` is now at `optimization_service.py:626`.
- **Black-Litterman `w_mkt` defect** — correctly diagnosed and still the right fix; the doc's line is
  wrong, the defect is real at `:791`/`:848`.
- **Still genuinely absent:** Granger causality, GJR-GARCH (one `o=1` from `:6586`), efficient frontier,
  risk parity via CCD, sector caps, CVaR transaction-cost penalty, VaR horizon label, and `copulas` to
  replace the mislabelled tail-dependence function.

---

## ORCHESTRATOR CORRECTION — the explorer's ".venv does not exist" is WRONG

The explorer concluded that *"the `.venv` does not exist"* and therefore that **every runtime-
compatibility claim in the corpus is unverifiable**. That is false. It listed `backend/` without
`-Force` and missed the dot-directory — the exact trap named in its own brief.

```
Test-Path .venv                      : True
Get-ChildItem backend -Force -Directory : .pytest_cache .ruff_cache .scratch .venv app data ...
uv run --extra dev python -c "import bfinance; print(bfinance.__file__)"
  -> C:\es\coding\finengine\backend\.venv\Lib\site-packages\bfinance\__init__.py
```

**The `.venv` exists and is populated.** The runtime claims are therefore testable today and their
"unverifiable" status should be withdrawn. The explorer's line count for `analytics_engine.py` was also
overstated (6,772 claimed vs **6,365** actual) — the growth claim itself still holds (+55% from 4,119).

## Could not verify — genuinely, not by tooling failure

- **scipy 1.18.0 removed `scipy.cluster.hierarchy._LINKAGE_METHODS`** — the load-bearing basis for the
  HRPOpt verdict. Needs a runtime check against the installed scipy.
- **quantstats resolved version in `uv.lock`** — not searched specifically.
- **MOSEK licensing claim** (consolidated report line 206) — not checked.
- **backtesting.py commercial dual-licensing** — already marked `UNVERIFIED` in the docs; correctly so.
- **FinanceDatabase data-provenance / redistribution rights** — already marked `UNVERIFIED`; correctly
  so. MIT covers code, not the Bloomberg-derived identifier table.
- **The legal conclusions themselves.** GPL §5(c) and AGPL §13 readings are technically sound as
  written, but this is not legal advice. The docs' own escalate-to-counsel recommendation stands.