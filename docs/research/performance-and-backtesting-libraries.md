# Performance & Backtesting Libraries — Adoption Assessment

**Date:** 2026-09-27
**Scope:** `quantstats`, `skfolio`, `backtrader`, `backtesting.py` for FinEngine (FastAPI 3.12 + Next.js, NSE/BSE, yfinance).
**Method:** GitHub API (repos/releases/commits/search), PyPI JSON API, `LICENSE` files, **Context7** (`/ranaroussi/quantstats`, `/skfolio/skfolio`, `/mementum/backtrader`, `/kernc/backtesting.py`), plus **empirical install-and-run tests** in throwaway venvs on the exact target stack (Python 3.12.9, pandas 3.0.6, numpy 2.5.3, cvxpy 1.9.3, clarabel 0.11.1, scikit-learn 1.9.1).

> **All claims marked VERIFIED were executed on this machine.** Claims marked UNVERIFIED need manual check. Licensing facts come from the GitHub `LICENSE`/tag pages, which are authoritative over Context7.

## Executive summary

| Library | Verdict | Blocker |
|---|---|---|
| **quantstats** 0.0.81 (installed) | **ADOPT** (upgrade + expand) | None. Pin is 4 versions stale and has verified pandas-3 bugs. |
| **skfolio** 1.4.1 | **ADOPT_PARTIAL** | New dep: `plotly>=6.0.0` (~40 MB). Everything else already installed. |
| **backtrader** 1.9.78.123 | **AVOID** | **GPL-3.0-or-later** — forces GPL on the whole backend. Plus abandoned since 2023-04-19. |
| **backtesting.py** 0.6.6 | **AVOID** | **AGPL-3.0 §13** — network copyleft triggers on a FastAPI backend. Plus single-instrument only. |

**The two backtesters are both disqualified by license before architecture even enters the discussion.**

---

## quantstats

Already-installed, actively maintained, Apache-2.0, and being used for **18% of its stat surface** while FinEngine hand-rolls 9 of the functions it already calls. The highest-ROI action in this report is not a new library — it is upgrading the pin and widening the existing one.

### Verdict

**ADOPT** — upgrade the pin from `0.0.81` to `0.0.85` and expand usage from 14 metrics to the full 81-row set. Apache-2.0 with zero new dependencies (every runtime dep is already in FinEngine's lockfile), Python 3.12 + pandas 3.0 verified working, and the current pin carries **verified** pandas-3 and numerical-correctness bugs that 0.0.85 fixes. FinEngine's own 199-line walk-forward backtester already outperforms both backtesters under evaluation for portfolio rebalancing.

### License

- **License:** Apache License 2.0
- **SPDX:** `Apache-2.0`
- **Declared (PEP 639):** `license = "Apache-2.0"` in [`pyproject.toml`](https://github.com/ranaroussi/quantstats/blob/main/pyproject.toml); wheel metadata reports `License-Expression: Apache-2.0`; classifier `License :: OSI Approved :: Apache Software License`
- **Text:** [`LICENSE.txt`](https://github.com/ranaroussi/quantstats/blob/main/LICENSE.txt) — VERIFIED present, 11,358 bytes, contains §§1–9

**Clause quote** — §4 Redistribution (VERIFIED verbatim in `LICENSE.txt`):

> "4. Redistribution. You may reproduce and distribute copies of the Work or Derivative Works thereof in any medium, with or without modifications, and in Source or Object form, provided that You meet the following conditions: (a) You must give any other recipients of the Work or Derivative Works a copy of this License; and (b) You must cause any modified files to carry prominent notices stating that You changed the files; and (c) You must retain, in the Source form of any Derivative Works that You distribute, all copyright, patent, trademark, and attribution notices from the Source form of the Work…"

**Commercial impact:** None. Apache-2.0 is a permissive license with **no copyleft and no network clause**. Linking it into a proprietary FastAPI backend imposes **zero** source-disclosure obligation. There is no AGPL-style "modified version running on a network server" trigger.

**Linking vs vendoring:**
- **Linking (recommended):** `import quantstats as qs`. Obligations are: ship the Apache-2.0 license text in third-party notices, and preserve the copyright/attribution header if you vendor any source. FinEngine does not vendor, so nothing to mark as modified.
- **Vendoring:** permitted under §4(b) but you must then mark your modified files and carry §4(c) attribution forward — pure downside for zero benefit here.

### Maintenance

**ACTIVE — very active.**

| Fact | Value | Source |
|---|---|---|
| Latest release | **v0.0.85**, published 2026-09-26T20:10:00Z | [releases](https://github.com/ranaroussi/quantstats/releases) |
| Last commit | 2026-09-26T20:08:06Z — *"fix: de-annualize the risk-free rate in rar() (#552)"* | [commits](https://github.com/ranaroussi/quantstats/commits/main) |
| Releases in last 24h | **4** (v0.0.82, v0.0.83, v0.0.84, v0.0.85 all on 2026-09-26) | [tags](https://github.com/ranaroussi/quantstats/tags) |
| Open issues | 5–9 | [issues](https://github.com/ranaroussi/quantstats/issues) |
| Stars / forks | 7,659 / 1,238 | GitHub API |
| Archived | No | GitHub API |

**⚠️ FinEngine's pin is 4 versions stale.** `backend/uv.lock:3049-3064` pins `quantstats==0.0.81`, uploaded **2026-01-13** — eight months and four releases behind.

The four new releases are not cosmetic. From the release bodies:

- **v0.0.82** — "Fixed `aggregate_returns()` raising `AttributeError: 'DatetimeIndex' object has no attribute 'week'` **on pandas >= 2.0** (#533). `aggregate_returns()` now uses `isocalendar().week` for the `"week"`, `"eow"` and `"W"` periods." Also fixed `max_drawdown()`/`to_drawdown_series()` depending on the *price level* of the input (#541), and `_prepare_prices()` zero-filling gaps into a spurious −100% drawdown (#545).
- **v0.0.83** — "Fixed `rolling_sharpe()` and `rolling_sortino()` de-annualizing the risk-free rate over the rolling window instead of the year (#549) … they subtracted **exactly twice** the correct risk-free rate." Plus "**Missing observations are no longer treated as 0.0 returns** (#546) … which understated volatility, softened drawdowns and inflated every ratio built on them."
- **v0.0.84** — reverted a bad `kelly_criterion` change; "If you installed 0.0.83 and use a benchmark, upgrading is recommended."
- **v0.0.85** — "**`rar()` charged the annual risk-free rate once per period** (#552) … at a daily frequency a 5% annual rate was subtracted from *every single day*. The series was wiped out and the Risk-Adjusted Return pinned to **−100%**… Every `rf`-taking function in `stats` has now been swept for it… and there is a regression test asserting that no rf-aware metric collapses to −100% under a 5% annual rate."

Note the v0.0.83 gap-handling change is **behavioural for FinEngine**: `_prepare_returns()` no longer fills missing observations with 0.0. That is *more* correct (the v0.0.81 behaviour "asserted the strategy was flat on days it had no data for"), but it means any published metric can legitimately move on upgrade. FinEngine's `_build_wide_returns`/active-history filtering must be the thing that decides coverage, not quantstats' implicit zero-fill.

**Open issue directly relevant to FinEngine** — [#556](https://github.com/ranaroussi/quantstats/issues/556), opened 2026-09-27: *"Discrepancies exist in the calculation results for certain metrics between `qs.stats.xx` and `qs.reports.metrics`."* FinEngine calls `qs.stats.*` directly, so this does not currently affect it — but it is a live reason not to build a second metrics path on `qs.reports.metrics` without a tolerance test.

### Compatibility

| Axis | Status | Evidence |
|---|---|---|
| **Python 3.12** | ✅ VERIFIED | Installed & ran on 3.12.9. `requires-python = ">=3.10"`; classifiers 3.10–3.13 |
| **pandas 3.0.6** | ⚠️ WORKS, but the pin has a **verified crash** | FinEngine's own env, 3.0.6. `0.0.85` requires `pandas>=2.0.0` (no upper bound) |
| **numpy 2.5.3** | ✅ VERIFIED | Ran on 2.5.3. Requires `numpy>=1.24.0` |
| **scipy 1.18.1** | ✅ VERIFIED | Requires `scipy>=1.11.0` |
| **async FastAPI fit** | ⚠️ **sync-only, currently called on the event loop** | See below |

**VERIFIED pandas-3.0 failure on the pinned 0.0.81:**

```
qs.utils.aggregate_returns(r, "weekly")  ->  AttributeError: 'DatetimeIndex' object has no attribute 'week'
qs.utils.aggregate_returns(r, "W")      ->  AttributeError: 'DatetimeIndex' object has no attribute 'week'
```

This is precisely bug #533, fixed in **0.0.82**. FinEngine does not call `aggregate_returns` today, so nothing is broken right now — but it means the pin is a live landmine for the monthly/period roll-up work already on the roadmap, and it independently proves the pin is stale.

**VERIFIED additional 0.0.81 defects** (all fixed by 0.0.85, none currently hit by FinEngine's call sites):

```
qs.stats.rar(r, rf=0.05)              ->  -1.0        # pinned to -100%, bug #552
qs.stats.ghpr(r, bench)               ->  ValueError: The truth value of a Series is ambiguous
qs.stats.rolling_sharpe(r, 252, rf=0) ->  TypeError: got multiple values for argument 'rf'
                                          # 2nd positional arg is `rf`, NOT `rolling_period`
```

**Async / GIL notes.** quantstats is **entirely synchronous** and CPU-bound. Today `backend/app/api/analytics.py` calls ~21 `qs.stats.*` functions directly inside `async def get_tear_sheet` (L6096–6250) — this blocks the event loop. FinEngine's own audit already recorded this at `.scratch/backend-deep-audit/code/01-api-layer.md:70`:

> "The async tear-sheet route calls synchronous quantstats metrics repeatedly at `backend/app/api/analytics.py:1422-1456`…"

`qs.reports.html()` is worse: it renders ~10 matplotlib figures **and writes a file to disk**, all under the GIL, and takes seconds. Wrapping any of this needs `anyio.to_thread.run_sync` (already the pattern FinEngine uses for `arch`/`statsmodels` per `.scratch/backend-audit-2026/BACKEND_REVIEW.md:189`). matplotlib must be forced to `Agg` before the first import (`matplotlib.use("Agg")`) or it will try to open a GUI.

### Dependency footprint

**Direct deps of quantstats 0.0.85** ([pyproject.toml](https://github.com/ranaroussi/quantstats/blob/main/pyproject.toml)):

| Dep | Constraint | FinEngine installed | Verdict |
|---|---|---|---|
| `pandas` | `>=2.0.0` | 3.0.6 | ✅ |
| `numpy` | `>=1.24.0` | 2.5.3 | ✅ |
| `scipy` | `>=1.11.0` | 1.18.1 | ✅ |
| `matplotlib` | `>=3.7.0` | 3.11.2 | ✅ |
| `seaborn` | `>=0.13.0` | 0.13.2 | ✅ |
| `tabulate` | `>=0.9.0` | 0.10.0 | ✅ |
| `yfinance` | `>=0.2.40` | 1.7.0 | ✅ |
| `python-dateutil` | `>=2.8.0` | (transitive) | ✅ |
| `plotly` | `>=5.0.0` (optional `[plotly]`) | **not installed** | opt-in only |

**Conflict risk: ZERO.** Every runtime dependency is already installed and already satisfies the constraint. Upgrading `quantstats` cannot move pandas, numpy, scipy, matplotlib, seaborn, tabulate, or yfinance. This is the single lowest-risk change available in this report.

Optional extras (dev) are `pytest`, `pytest-cov`, `pyright`, `ruff` — none needed in FinEngine's `[project.optional-dependencies] dev` table.

### API surface

All snippets below were **executed against the installed 0.0.81 inside FinEngine's venv** unless marked otherwise.

**Signatures VERIFIED via `inspect.signature`:**

```python
qs.stats.comp(returns)                                                   # VERIFIED
qs.stats.cagr(returns, rf=0.0, compounded=True, periods=252)
qs.stats.sharpe(returns, rf=0.0, periods=252, annualize=True, smart=False)
qs.stats.sortino(returns, rf=0.0, periods=252, annualize=True, smart=False)
qs.stats.calmar(returns, prepare_returns=True, periods=252)
qs.stats.omega(returns, rf=0.0, required_return=0.0, periods=252)
qs.stats.tail_ratio(returns, rf=0.0, periods=252)
qs.stats.volatility(returns, rf=0.0, periods=252, annualize=True)
qs.stats.max_drawdown(prices)                                            # note: arg is `prices`
qs.stats.to_drawdown_series(returns)                                     # -> pd.Series
qs.stats.skew(returns, prepare_returns=True)
qs.stats.kurtosis(returns, prepare_returns=True)
qs.stats.value_at_risk(returns, sigma=1, confidence=0.95, prepare_returns=True)
qs.stats.conditional_value_at_risk(returns, sigma=1, confidence=0.95)
qs.stats.expected_shortfall(returns, sigma=1, confidence=0.95)
qs.stats.cvar(returns, sigma=1, confidence=0.95)          # NOT `cutoff=` — that kwarg is rejected
qs.stats.monthly_returns(returns, eoy=True, compounded=True)
qs.stats.drawdown_details(drawdown)                      # takes a drawdown SERIES, not returns
qs.stats.distribution(returns, compounded=True) -> dict   # returns a dict, not a DataFrame
qs.stats.recovery_factor(returns)                        # total return / max drawdown
qs.stats.ulcer_index(returns) / ulcer_performance_index(returns, rf)
qs.stats.serenity_index(returns, rf)
qs.stats.probabilistic_ratio(series, rf=0.0, base='sharpe', periods=252)
qs.stats.probabilistic_sharpe_ratio / probabilistic_sortino_ratio
qs.stats.greeks(returns, benchmark) -> dict              # {'alpha','beta'}
qs.stats.r_squared / r2(returns, benchmark)
qs.stats.information_ratio(returns, benchmark) / treynor_ratio(returns, benchmark)
qs.stats.rolling_sharpe(returns, rf=0.0, rolling_period=126, annualize=True, periods_per_year=252)
qs.stats.rolling_sortino(returns, rf=0, rolling_period=126, annualize=True, periods_per_year=252)
qs.stats.rolling_volatility(returns, rf=0.0, rolling_period=126, annualize=True)
qs.stats.implied_volatility(returns, periods=252, annualize=True)
qs.stats.kelly_criterion / risk_of_ruin / ghpr(returns, aggregate=None, compounded=True)
qs.stats.rar(returns, rf=0.0)                             # BROKEN pre-0.0.85

qs.utils.download_returns(ticker, period='max', proxy=None)
qs.utils.to_prices(returns, base=1.0) / to_returns(prices) / to_log_returns / to_excess_returns / rebase
qs.utils.aggregate_returns(returns, period=None, compounded=True)   # 'W'/'week' broken pre-0.0.82
qs.utils.make_portfolio(returns, start_balance=100000.0, mode='comp', round_to=None)
qs.utils.exponential_stdev(returns, window=63)

qs.reports.metrics(returns, benchmark=None, rf=0.0, display=True, mode='basic',
                   sep=False, compounded=True, periods_per_year=252, prepare_returns=True,
                   match_dates=True, **kwargs)
qs.reports.html(returns, benchmark=None, rf=0.0, grayscale=False, title='Strategy Tearsheet',
                output=None, compounded=True, periods_per_year=252, figfmt='svg',
                match_dates=True, **kwargs)
qs.reports.full(returns, ..., template='full.html', **kwargs)
qs.plots.snapshot(returns, title=..., figsize=(10,8), mode='comp', log_scale=False, savefig=..., show=True)
qs.plots.monthly_heatmap(returns, benchmark=None, active=False, eoy=True, compounded=True, savefig=...)
qs.plots.drawdowns_periods(returns, periods=5, savefig=...)
qs.plots.rolling_beta(returns, benchmark, window=252)   # in plots, NOT stats
```

**Copyable, VERIFIED-running programmatic usage** (this is the adoption path — `display=False` returns a DataFrame instead of printing):

```python
import matplotlib
matplotlib.use("Agg")          # must precede the first quantstats import
import io, contextlib
import numpy as np, pandas as pd, quantstats as qs

rng  = np.random.default_rng(7)
dates = pd.bdate_range("2021-01-01", periods=900)
r      = pd.Series(rng.normal(0.0004, 0.011, 900), index=dates)
bench  = pd.Series(rng.normal(0.0003, 0.010, 900), index=dates, name="NIFTY")

# 1. The 81-metric table, programmatically (VERIFIED: DataFrame shape (81, 2))
buf = io.StringIO()
with contextlib.redirect_stdout(buf):        # suppresses the ASCII table
    df = qs.reports.metrics(r, benchmark=bench, rf=0.02, mode="full", display=False)
assert df.shape == (81, 2)

# 2. Full HTML tearsheet to a file (VERIFIED: wrote 844,363 bytes)
qs.reports.html(r, benchmark=bench, rf=0.02, title="FinEngine vs NIFTY",
                output="/tmp/finengine-tearsheet.html", open_browser=False)
```

⚠️ **Windows gotcha (VERIFIED, and easy to misread as a library bug):** calling `qs.reports.metrics(..., display=True)` on a `cp1252` console raises
`UnicodeEncodeError: 'charmap' codec can't encode character '\ufe6a'` — the table contains `√` glyphs in the `Sortino/√2` / `Smart Sortino/√2` rows. This is a **console encoding** failure in `tabulate`'s print, not a quantstats defect. Use `display=False`, or set `PYTHONIOENCODING=utf-8`. Do not "fix" it by suppressing exceptions around `metrics()`.

**Note on the brief's guess — VERIFIED FALSE:** `qs.stats.turnover` **does not exist**, in 0.0.81 or in main/0.0.85. I enumerated every public name in both (`dir(qs.stats)`): 84 names in 0.0.81, and the main-branch `stats.py` `def` list has no `turnover`. Likewise there is no `qs.stats.rolling_beta` (it lives in `qs.plots`). FinEngine's turnover is hand-rolled at `backtest_service.py:118` and `api/portfolio.py:2107` and there is nothing in quantstats to replace it with.

### Overlap with FinEngine

`qs.*` in `backend/app/` is confined to **two production files** (55 grep hits, of which 41 are in one route handler).

| FinEngine file / function | quantstats replacement | Effort | Risk |
|---|---|---|---|
| `api/analytics.py:6300-6311` hand-rolled monthly compounding `(1+r).groupby([year,month]).prod()-1` | `qs.stats.monthly_returns(port_ret, eoy=True)` | **S** | Low — output is a pivot DataFrame; needs a reshape to FinEngine's `{year: {month: val}}` shape. Guarded by `try/except` today. |
| `api/analytics.py:6263-6267` hand-rolled `beta = p.cov(b)/b.var()`, `alpha = (p.mean() - beta*b.mean())*252` | `qs.stats.greeks(port_ret, bench_window)` | **M** | **Medium** — `greeks` annualizes with its own `periods`; the `MIN_ANNUALIZE_DAYS` intersection gate at L6254-6256 must be preserved. Losing that gate is the exact lookahead class FinEngine's audits flag. |
| `api/analytics.py:14 metrics` at L6096-6106 + L6141-6147 + L6247-6250 | keep as-is (deliberate) | — | **None** — `_q` per-metric degradation is a design FinEngine's SI-5 uncertainty block depends on. **DO NOT replace with `qs.reports.metrics`**, which fails all-or-nothing and whose `stats` vs `reports` agreement is open issue #556. |
| `api/analytics.py:498-510` `_q()` guard | keep | — | None — this is FinEngine's own correctness layer, not quantstats'. |
| `analytics_engine.py:1053-1152` `quantstats_ratio_statistics()` — 9 numpy restatements | **keep; this is required, not redundant** | — | **High if removed** — `measure_estimate_uncertainty` refuses to publish a band unless its own point value reproduces the published one. quantstats' `stats` functions are scalar-only and cannot be vectorised over `(n, draws, k)` blocks. |
| `analytics_engine.py:1037-1050` `quantstats_returns_look_like_prices()` | keep | — | None — replicates `quantstats.utils._prepare_returns`'s `min >= 0 and max > 1` gate so the band is never attached to a differently-defined statistic. |
| `api/analytics.py:6315` `to_drawdown_series` → last 250 pts | keep | — | None. But **0.0.82 changes the baseline** (#541, #545) — re-baseline the regression test. |
| `tests/test_uncertainty_disclosure.py:296-355,512-514,595,720-737,763` | keep | — | These assert the numpy restatements reproduce `qs.stats.*`. **They become the upgrade tripwire** — see migration order. |
| `api/analytics.py:3455` `methodology: "Real-time calculations using quantstats and statistical models"` | rewrite string | **S** | Low but should be done — the string names a library, not a method, and `.scratch/v5-review/05-adversarial.md:227` already flagged it. |
| `api/analytics.py:6408` `methodology: "quantstats metric suite over cached OHLCV adj-close returns"` | keep + add version | **S** | Low. Add `quantstats==0.0.85` so a published number is traceable to a formula set. |
| `frontend/src/lib/export.ts:319 exportInstitutionalReviewPDF` (jsPDF tearsheet) | `qs.reports.html` as a **server-side** alternative | **L** | **High** — see below. Do not replace. |
| `backtest_service.py:19 run_walk_forward_backtest` (own CAGR/Sharpe/MDD/Calmar at L188-207) | `qs.reports.metrics(returns, display=False)` on the simulated curve | **S** | Low and high value — one call yields 81 metrics on a *known* return series, removing ~20 lines of hand-rolled math. |
| `backtest_service.py:118` one-way turnover `0.5*sum|dw|` | **nothing in quantstats** | — | Keep. There is no `qs.stats.turnover`. |

### Implementation guide

**1. `backend/pyproject.toml` — the only dependency-line change required.** Line 21 currently reads:

```toml
    "quantstats",
```

Change to a floor + a ceiling that forces the review, not a silent bump:

```toml
    "quantstats>=0.0.85",   # 0.0.81 has a verified pandas-3 crash in aggregate_returns (bug #533)
```

Do **not** add an upper bound. quantstats is pre-1.0 and the release cadence is high; a ceiling will guarantee future breakage.

Then resync per `AGENTS.md` (both tool tables):

```
uv sync --extra dev --group dev
```

**2. Files to touch (no source changes required for the upgrade itself).**

| File | Change | Required? |
|---|---|---|
| `backend/pyproject.toml` | L21 → `"quantstats>=0.0.85"` | **Yes** |
| `backend/app/api/analytics.py` | L6024 — hoist `import quantstats as qs` to module scope. Currently function-local; every other import is at L5-38. Recorded as skipped in `.scratch/backend-audit/01-api-analytics.md:51` and `verified-01.md:37`. | Recommended |
| `backend/app/api/analytics.py` | L3455, L6408 — methodology strings | Recommended |
| `backend/app/api/analytics.py` | L6096-6250 — wrap the `qs.stats.*` block in `anyio.to_thread.run_sync` | Recommended (perf) |
| `backend/app/api/analytics.py` | L6300-6311 — delegate to `qs.stats.monthly_returns` | Optional |
| `backend/app/services/backtest_service.py` | L188-207 — delegate to `qs.reports.metrics(display=False)` | Optional |
| `backend/tests/test_uncertainty_disclosure.py` | **re-baseline against 0.0.85** | **Yes** |
| `frontend/src/lib/export.ts` | none | No |

**3. Migration order (strict).**

1. **Bump the floor, resync, run `pytest` untouched.** Expect `test_uncertainty_disclosure.py::test_tear_sheet_ratio_restatements_reproduce_quantstats_exactly` to be the first thing that tells you whether the vectorised restatements still match. Per the 0.0.82 notes, `max_drawdown`'s baseline changed (#541) and per 0.0.83 the gap handling changed (#546) — the `max_drawdown` restatement in `analytics_engine.py:1113-1127` hard-codes the old `prices[0] > 1000 → 1e5` baseline heuristic, so **that one will need rewriting to mirror the new `from returns vs from price series` decision**, not the magnitude guess.
2. Hoist the import out of the handler. Zero behaviour change (`sys.modules` makes per-request import cheap; this is hygiene, not perf).
3. Rewrite the `methodology` strings.
4. **Only then** add new metric adoption (`monthly_returns`, `greeks`, backtest-suite `reports.metrics`), each with its own regression test.
5. Last: the `to_thread` wrap.

**4. Keep vs replace.**

- **KEEP:** `_q()`, `quantstats_ratio_statistics()`, `quantstats_returns_look_like_prices()`, the per-metric degradation model, the `MIN_ANNUALIZE_DAYS` gate, `to_drawdown_series`. These are FinEngine's correctness and disclosure layer sitting *on top of* quantstats. The 0.0.81→0.0.85 upgrade makes the restatements more important, not less.
- **REPLACE:** the hand-rolled monthly groupby (L6303) and the hand-rolled beta/alpha (L6263-6267) — after their own regression tests.
- **REJECT:** swapping the 14-metric `_q` block for `qs.reports.metrics`. It is all-or-nothing where FinEngine is per-metric, and it is the subject of open issue #556.

**5. Rewritten code example** — adopting 67 unused metrics without losing per-metric degradation:

```python
# backend/app/api/analytics.py  (additive; existing 14 keys untouched)
_QUANTSTATS_ROWS = (
    ("Cumulative Return", "total_return_pct"),
    ("Prob. Sharpe Ratio", "prob_sharpe"),
    ("Smart Sharpe", "smart_sharpe"),
    ("Ulcer Performance Index", "upi"),
    ("Ulcer Index", "ulcer_index"),
    ("Serenity Index", "serenity_index"),
    ("Recovery Factor", "recovery_factor"),
    ("Expected Shortfall (cVaR)", "cvar_95"),
    ("Daily Value-at-Risk", "var_95"),
    ("R^2", "r_squared_vs_bench"),
    ("Information Ratio", "information_ratio"),
    ("Treynor Ratio", "treynor_ratio"),
    ("Gain/Pain Ratio", "gain_pain_ratio"),
    ("Payoff Ratio", "payoff_ratio"),
    ("Profit Factor", "profit_factor"),
    ("Longest DD Days", "longest_drawdown_days"),
    ("MTD", "mtd"), ("3M", "r3m"), ("6M", "r6m"), ("YTD", "ytd"),
    ("1Y", "r1y"), ("3Y (ann.)", "r3y_ann"), ("5Y (ann.)", "r5y_ann"),
    ("All-time (ann.)", "rall_ann"),
    ("Best Day", "best_day"), ("Worst Day", "worst_day"),
    ("Best Month", "best_month"), ("Worst Month", "worst_month"),
    ("Best Year", "best_year"), ("Worst Year", "worst_year"),
    ("Win Days", "win_days_pct"), ("Win Month", "win_month_pct"),
    ("Win Quarter", "win_quarter_pct"), ("Win Year", "win_year_pct"),
)

def _quantstats_tearsheet_table(port_ret, bench_window):
    """The rows FinEngine does not already publish, as a dict of float|None.

    `display=False` makes quantstats RETURN the table instead of printing it.
    `redirect_stdout` is belt-and-braces: the table carries U+FE6A glyphs in the
    `Sortino/sqrt(2)` rows, and printing to a cp1252 console raises UnicodeEncodeError.
    """
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        table = qs.reports.metrics(
            port_ret, benchmark=bench_window, rf=TEAR_SHEET_RISK_FREE_RATE,
            mode="full", display=False,
        )
    out: dict[str, float | None] = {}
    for label, field in _QUANTSTATS_ROWS:
        if label not in table.index:
            out[field] = None
            continue
        out[field] = _q(lambda v=v: v, table.loc[label].iloc[0])   # reuses the existing guard
    return out
```

`_q` is reused deliberately — it already returns `None` for non-finite values, which is what keeps a degenerate window from becoming a 500 (the P1 already fixed in `.scratch/backend-audit/00-INDEX.md:42`).

### Risk & caveats

1. **The upgrade is a behaviour change, not a no-op.** 0.0.83 stopped zero-filling missing observations. Any metric FinEngine publishes on a series with gaps can legitimately move. The upside is real (the old behaviour understated volatility and inflated ratios) but it must be communicated, not shipped silently.
2. **`max_drawdown`'s baseline heuristic changed in 0.0.82** — the exact code FinEngine reimplemented at `analytics_engine.py:1113-1127`. This is the highest-probability point of failure in the migration.
3. **quantstats is pre-1.0 and cut 4 releases in one day.** 0.0.82→0.0.83→0.0.84 is a change, a fix, and a revert in 12 hours. Pinning a floor and not a ceiling is the right posture, but re-run the tear-sheet regression suite on every bump.
4. **Open issue #556** — `qs.stats.*` and `qs.reports.metrics` disagree on some metrics. FinEngine uses `stats.*`, so no current impact, but do not build a second metrics path on `reports.metrics` without a tolerance test.
5. **`qs.reports.html` is not a replacement for `export.ts`.** It writes a file to disk, renders ~10 matplotlib figures, and returns HTML — it cannot produce a client-side PDF. It is a viable *server-side HTML* export alongside the existing jsPDF path, and that is all. It is also seconds of GIL-holding work per call and must be `to_thread`ed with `matplotlib.use("Agg")` set.
6. **The 9 hand-written numpy restatements in `analytics_engine.py` are load-bearing.** They look like duplication and are the opposite: they exist so the bootstrap can verify it is resampling the *same* statistic it published. Deleting them to "just use quantstats" would remove the uncertainty-disclosure guarantee.
7. **`_SHAPE_STATISTIC_REASON` remains true after upgrade.** `skew`/`kurtosis` are still pandas bias-corrected shape statistics with no vectorised restatement, so they will still publish a point estimate with a declared-absent interval.
8. **Windows console encoding.** `display=True` will raise `UnicodeEncodeError` on cp1252. Use `display=False`.

---

## skfolio

### Verdict

**ADOPT_PARTIAL** — a genuinely modern, BSD-3-Clause, pandas-3.0-targeted portfolio-optimization library whose one hard dep FinEngine lacks (`plotly`) is a 40 MB plotting library, not a solver. Its `HierarchicalRiskParity` and `RiskBudgeting` are the natural cross-checks on FinEngine's hand-rolled `_hrp_weights`, and its `WalkForward`/`CombinatorialPurgedCV` are the principled replacement for `backtest_service.py`'s bespoke walk-forward. Adopt behind the existing `optimize()` facade, one strategy at a time, with a weight-parity test before switching any production path.

### License

- **License:** BSD 3-Clause ("New" or "Revised")
- **SPDX:** `BSD-3-Clause` (GitHub API license detection); classifier `License :: OSI Approved :: BSD License`; site footer reads "© Copyright 2026, skfolio developers (BSD License)"
- **Copyright:** `(c) 2023-2026 The skfolio developers. All rights reserved.`

**Clause quote** — conditions (VERIFIED verbatim from the PyPI `license` field):

> "Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
> * Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
> * Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
> * Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived from this software without specific prior written permission."

**Commercial impact:** None. No copyleft, no network clause, no source-disclosure trigger. Linking into a proprietary FastAPI backend is fine.

**Linking vs vendoring:** Linking (recommended) — ship the BSD-3-Clause text in third-party notices. Vendoring would require per-file modification marks under clause 1 and buys nothing.

### Maintenance

**ACTIVE — releases roughly daily.**

| Fact | Value | Source |
|---|---|---|
| Latest release | **v1.4.1**, published 2026-09-26T22:34:18Z | [releases](https://github.com/skfolio/skfolio/releases) |
| Previous | v1.4.0 (2026-09-26T10:51Z), v1.3.4 (2026-09-25T15:37Z) | [tags](https://github.com/skfolio/skfolio/tags) |
| Last commit | 2026-09-26T22:34:03Z — *"fix(measures): count the starting wealth as the first drawdown peak (#375)"* | [commits](https://github.com/skfolio/skfolio/commits/main) |
| Open issues | 18 open (GitHub search) / 42 total (repo counter) | [issues](https://github.com/skfolio/skfolio/issues) |
| Open issue profile | Dominated by *feature requests* (Online Portfolio Selection, RegimeSplit, Schur online) not bugs | search results |
| Stars / forks | 2,437 / 262 | GitHub API |
| Archived | No | GitHub API |

**Open correctness issue worth watching** — [#331](https://github.com/skfolio/skfolio/issues/331), opened 2026-09-18: *"[BUG] IC t-statistic assumes independent observations; overlapping windows make it ~3x too large."* Directly relevant to FinEngine's overlapping-window factor work. Does not affect optimization weights.

**API churn is real:** v1.4.0 and v1.4.1 landed on the same day as this research, and Context7's own docs returned `get_measures` under `skfolio.measures` while the installed 1.4.1 has it in **`skfolio.metrics`** (`get_measures` is a private `_measures` in 1.4.1 — VERIFIED: `ImportError`). See the API-surface gotchas below. Vendor against a pinned version, not `latest`.

### Compatibility

| Axis | Status | Evidence |
|---|---|---|
| **Python 3.12** | ✅ VERIFIED | Installed & ran on 3.12.9. `requires-python >=3.10`; classifiers 3.10–**3.14** |
| **pandas 3.0.6** | ✅ VERIFIED + **first-class** | Resolved and ran on 3.0.6. [PR #216 "[ENH] Ensure compatibility with pandas >= 3.0"](https://github.com/skfolio/skfolio/pull/216) **closed 2026-08-23** |
| **numpy 2.5.3** | ✅ VERIFIED | Ran on 2.5.3. `numpy>=1.24.0` |
| **scipy 1.18.1** | ✅ VERIFIED | `scipy>=1.15.2` |
| **cvxpy 1.9.3** | ✅ VERIFIED no conflict | See below — `cvxpy-base 1.9.3` resolves to the *matching* version |
| **scikit-learn 1.9.1** | ✅ VERIFIED | `scikit-learn>=1.6.0` |
| **clarabel 0.11.1** | ✅ VERIFIED | `clarabel>=0.10.0`; this is skfolio's **default solver** and FinEngine already uses Clarabel |
| **async FastAPI fit** | ⚠️ **sync-only, CPU-bound cvxpy** | See below |

**`cvxpy-base` conflict risk: NONE (VERIFIED by resolution).** skfolio requires `cvxpy-base>=1.5.0`, which FinEngine's current lockfile does not have (FinEngine has `cvxpy 1.9.3`, whose own `requires_dist` does *not* list `cvxpy-base` — it bundles the base). On a real resolution against `cvxpy==1.9.3`, uv installed **`cvxpy-base 1.9.3`** — exactly matching, no dual-installation, no class-identity split. This was the single most likely conflict and it does not occur.

**New dependency: `plotly>=6.0.0`.** Resolved to **plotly 7.1.0**, which is **not currently installed** in FinEngine. It is a hard dep (not optional). ~40 MB. Used only by `Portfolio.plot_*()`. It cannot be skipped.

**Async / GIL.** skfolio is **synchronous and CPU-bound**. Convex fits are Clarabel/native (releases the GIL in the solver loop, but the surrounding numpy/cvxpy modelling is Python-level and holds it). VERIFIED timings on a 1200×5 daily frame, py3.12 + pandas 3.0.6:

```
MeanRisk(Variance) fit+predict :  133.1 ms
HierarchicalRiskParity   fit+predict:  15.6 ms
```

Those are per-fit numbers FinEngine's walk-forward would multiply by `n_rebalances`. `WalkForward` + `cross_val_predict(..., n_jobs=N)` uses **sklearn `joblib` process/thread parallelism**, not asyncio — that is the right tool for 100s of small fits inside a request, and it needs no event-loop cooperation. But it will also spawn processes, so it must be called from `to_thread` (or accepted as a deliberate CPU-blocking boundary). FinEngine already records this class of problem for its own solvers at `.scratch/backend-audit-2026/BACKEND_REVIEW.md:189` ("`async def` GARCH blocks loop").

### Dependency footprint

**Direct deps of skfolio 1.4.1:**

| Dep | Constraint | FinEngine installed | Verdict |
|---|---|---|---|
| `numpy` | `>=1.24.0` | 2.5.3 | ✅ |
| `scipy` | `>=1.15.2` | 1.18.1 | ✅ |
| `pandas` | `>=2.1.0` | 3.0.6 | ✅ |
| `cvxpy-base` | `>=1.5.0` | *(resolves to 1.9.3)* | ✅ verified match |
| `clarabel` | `>=0.10.0` | 0.11.1 | ✅ default solver |
| `scikit-learn` | `>=1.6.0` | 1.9.1 | ✅ |
| `plotly` | `>=6.0.0` | **7.1.0 (NEW)** | ⚠️ +40 MB, no upper pin |

**Conflict risk: LOW.** No version conflict. Two caveats:
1. `plotly` is a genuinely new transitive addition to the lockfile — review its own dependency tree (`narwhals`, `packaging`) before merging.
2. Cardinality/threshold constraints need a **mixed-integer** solver (SCIP/GUROBI/MOSEK) which FinEngine does not have. `MeanRisk(cardinality=...)` will not work as-shipped. Documented in skfolio's install guide.

**Additional solver note (Context7 + install docs):** "While the Clarabel solver is included by default, users requiring cardinality and threshold constraints must install additional mixed-integer solvers such as SCIP, GUROBI, or MOSEK." FinEngine's Clarabel 0.11.1 covers everything FinEngine's `optimization_service` does today.

### API surface

Signatures below are **VERIFIED via `inspect.signature` against the installed 1.4.1**, and every optimizer shown was **executed successfully** on pandas 3.0.6.

**⚠️ Module-path gotchas (all VERIFIED — the obvious paths are wrong):**

| You would guess | Actually correct in 1.4.1 |
|---|---|
| `from skfolio import MeanRisk` | `from skfolio.optimization import MeanRisk` |
| `from skfolio.covariance import LedoitWolf` | `from skfolio.moments import LedoitWolf` |
| `from skfolio.risk_measure import RiskMeasure` | `from skfolio import RiskMeasure` (or `skfolio.measures`) |
| `model.predict()` | `model.predict(X)` — **X is required in 1.4.1** |
| `model.portfolio_` | `model.weights_` for weights; `model.predict(X)` for a `Portfolio` |
| `portfolio.weights.items()` | `dict(zip(portfolio.assets, portfolio.weights))` — `weights` is an `ndarray` |
| `from skfolio.measures import get_measures` | `from skfolio.measures import _measures` (private in 1.4.1) |
| `WalkForward(n_splits=5)` | `WalkForward(test_size=..., train_size=..., freq=...)` |

**VERIFIED signature — `MeanRisk.__init__`** (abridged to the parts FinEngine's `STRATEGIES` map onto):

```python
MeanRisk(
    objective_function: ObjectiveFunction = MINIMIZE_RISK,
    risk_measure: RiskMeasure = Variance,
    risk_aversion: float = 1.0,
    prior_estimator: BasePrior | None = None,
    min_weights: MultiInput | None = 0.0,        # FinEngine: long-only -> 0.0
    max_weights: MultiInput | None = 1.0,
    budget: float | None = 1.0,                  # fully invested
    l1_coef: float = 0.0, l2_coef: float = 0.0,
    transaction_costs: MultiInput = 0.0,         # FinEngine: bps -> decimal here
    management_fees: MultiInput = 0.0,
    previous_weights: MultiInput | None = None,  # turnover-aware
    linear_constraints: LinearConstraints | None = None,
    risk_free_rate: float = 0.0,                 # FinEngine: 0.02
    cvar_beta: float = 0.95, cdar_beta: float = 0.95,
    max_cvar: Target | None = None,              # <- ObjectiveFunction.MAXIMIZE_UTILITY / min-CVaR
    solver: str = "CLARABEL",                    # <- FinEngine already uses Clarabel
    fallback: Fallback | None = None,
    raise_on_failure: bool = True,
)
```

**VERIFIED-running end-to-end example:**

```python
import numpy as np, pandas as pd
from skfolio import RiskMeasure
from skfolio.optimization import (
    MeanRisk, HierarchicalRiskParity, InverseVolatility,
    RiskBudgeting, MaximumDiversification,
)
from skfolio.model_selection import WalkForward, cross_val_predict

# X: pd.DataFrame of DAILY RETURNS, DatetimeIndex, one column per NSE ticker
X = pd.DataFrame(...)

# --- single optimizers -------------------------------------------------------
# 1. Minimum CVaR at 95%  (cross-check for optimization_service "min_cvar")
m = MeanRisk(risk_measure=RiskMeasure.CVAR, cvar_beta=0.95,
             min_weights=0.0, max_weights=1.0, budget=1.0,
             solver="CLARABEL").fit(X)
p = m.predict(X)
print(dict(zip(p.assets, p.weights)))          # <- p.weights is ndarray
print(float(p.cvar), float(p.annualized_sharpe_ratio))

# 2. HRP  (cross-check for optimization_service "hrp" / _hrp_weights)
p_hrp = HierarchicalRiskParity().fit(X).predict(X)

# 3. Risk budgeting (NEW capability, no FinEngine equivalent)
p_rb  = RiskBudgeting(risk_measure=RiskMeasure.VARIANCE).fit(X).predict(X)

# 4. Euler risk contribution (NEW - FinEngine computes this by hand)
p_hrp.contribution(measure=RiskMeasure.SEMI_DEVIATION)

# --- walk-forward out-of-sample  (the real prize) ---------------------------
cv = WalkForward(train_size=pd.DateOffset(years=2), test_size=pd.DateOffset(months=1),
                 freq="ME", purged_size=5, embargo_size=5)
mpp = cross_val_predict(MeanRisk(risk_measure=RiskMeasure.CVAR),
                        X, cv=cv, n_jobs=-1)
print(mpp.sharpe_ratio, mpp.max_drawdown, mpp.turnover)
```

**VERIFIED signatures (inspect):**

```python
WalkForward(test_size, train_size, freq=None, freq_offset=None,
            previous=False, expand_train=False, reduce_test=False,
            purged_size=0)
CombinatorialPurgedCV(n_folds=10, n_test_folds=8, purged_size=0, embargo_size=0)
cross_val_predict(estimator, X, y=None, cv=None, n_jobs=None, method="predict",
                  verbose=0, params=None, pre_dispatch="2*n_jobs",
                  column_indices=None, portfolio_params=None,
                  entry_rebalancing_params=None)  -> MultiPeriodPortfolio | Population
```

**VERIFIED `Portfolio` attributes that FinEngine hand-rolls:**

```
turnover, contribution(), composition, weights_dict, ending_weights_dict,
cvar, evar, edar, cdar, value_at_risk, max_drawdown, average_drawdown,
ulcer_index, semi_variance, semi_deviation, effective_number_assets, diversification,
sharpe_ratio, sortino_ratio, calmar_ratio, omega-ish via cvar_ratio,
kurtosis, skew, mean_absolute_deviation, gini_mean_difference, worst_realization,
sric, measures_df, fitness_measures, summary(), get_measure(), rolling_measure(),
contribution(measure=...), plot_cumulative_returns(), plot_contribution(), ...
```

### Overlap with FinEngine

| FinEngine file / function | skfolio replacement | Effort | Risk |
|---|---|---|---|
| `optimization_service.py:53 STRATEGIES = ("hrp","min_vol","max_sharpe","min_cvar","black_litterman")` | keep as the public contract; add a skfolio backend behind it | **S** | Low — this is the correct seam. `optimize(train_window, strategy=..., risk_free_rate=...)` is already the only entry point `backtest_service.py:104` uses. |
| `optimization_service.py:549 _hrp_weights(returns)` (Lopez de Prado recursive bisection, hand-rolled) | `HierarchicalRiskParity().fit(X).predict(X)` | **M** | **Medium** — weights will not be bit-identical (skfolio defaults to `Distance.ABS_CORR` vs FinEngine's linkage choice). Use as a **cross-check**, not a silent swap. |
| `optimization_service.py:619 _min_vol(cov)` (cvxpy) | `MeanRisk(risk_measure=RiskMeasure.VARIANCE)` | **S** | Low — same formulation, Clarabel both sides. Good parity test. |
| `optimization_service.py` `max_sharpe` (tangency homogenization) | `MeanRisk(objective_function=ObjectiveFunction.MAXIMIZE_RATIO)` | **S** | Low–Medium — FinEngine's homogenization trick vs skfolio's ratio form; expect small numeric drift. |
| `optimization_service.py` `min_cvar` (Rockafellar-Uryasev scenario LP) | `MeanRisk(risk_measure=RiskMeasure.CVAR, cvar_beta=0.95)` | **S** | Low — both are Rockafellar-Uryasev. Strongest parity candidate. |
| `optimization_service.py` `black_litterman` | `skfolio.prior.BlackLitterman` | **M** | Medium — different view/prior conventions. |
| — (no equivalent) | `RiskBudgeting(risk_measure=CVAR)`, `HierarchicalEqualRiskContribution`, `NestedClustersOptimization`, `MaximumDiversification`, `InverseVolatility`, `SchurComplementary` | — | **Pure gain** |
| — (no equivalent) | `Portfolio.contribution(measure=...)` — **Euler risk contribution** | **M** | Medium — `.scratch/advanced-analytics/issues` lists Euler risk contribution as pending roadmap; skfolio ships it. |
| — (no equivalent) | `CombinatorialPurgedCV` — CPCV with purge/embargo | **M** | Medium — closes the lookahead gap FinEngine's own audits flag. |
| — (no equivalent) | `DenoiseCovariance`, `DetoneCovariance`, `GerberCovariance`, `ShrunkMu`, `LedoitWolf`, `OAS`, `EWCovariance` | **S** | Low. FinEngine uses `LedoitWolf` in one place only. |
| `analytics_engine.py` concentration / diversification (HHI, N_eff) | `Portfolio.effective_number_assets`, `Portfolio.diversification` | **S** | Low — but FinEngine's `AGENTS.md` invariant mandates HHI/N_eff math; treat skfolio as the cross-check. |
| `backtest_service.py:19-237 run_walk_forward_backtest` (bespoke walk-forward, L75 rebalance_indices, L92-162 loop) | `WalkForward` + `cross_val_predict` | **L** | **High if replaced blindly.** FinEngine's version has deliberate, documented Indian-market choices skfolio does not model: one-way turnover `0.5*Σ|dw|` (L115-118), self-financing weight drift `w[t+1]=w[t](1+r)/(1+w·r)` (L156-158), equal-weight buy-and-hold benchmark (L88-89, L228), explicit `STRATEGIES` routing, and per-window optimizer-failure fallback (L111-113). **Do not delete.** Use `WalkForward` for fold/embargo discipline and keep the inner accounting. |
| `tail_risk_service.py` CVaR | `skfolio.measures.cvar` / `ExtraRiskMeasure.ENTROPIC_RISK_MEASURE` | **S** | Low–Medium. FinEngine has copula/EVT tail machinery skfolio lacks. |
| — (no equivalent) | `DistributionallyRobustCVaR`, `BootstrapMuUncertaintySet`, `EntropyPooling`, `OpinionPooling`, `VineCopula`, `SyntheticData` | — | Pure gain, later |

### Implementation guide

**1. `backend/pyproject.toml` — add one line** inside `dependencies = [...]`, after the `cvxpy` line (L36):

```toml
    "skfolio>=1.4,<2",   # BSD-3-Clause; pins plotly>=6 as a hard dep. Pinned range on
                         # purpose: the 1.4.x API moved (metrics vs measures) and
                         # releases land daily.
```

A hard `<2` bound **is** warranted here (unlike quantstats) because skfolio is post-1.0 and does make breaking API moves within a minor series.

Then `uv sync --extra dev --group dev` per `AGENTS.md`.

**2. Files to touch.**

| File | Change | Phase |
|---|---|---|
| `backend/pyproject.toml` | add `"skfolio>=1.4,<2"` | 1 |
| `backend/app/services/optimization_service.py` | add a `_skfolio_backend(strategy, train_window, risk_free_rate)` next to `_solve` (L519) | 2 |
| `backend/app/services/optimization_service.py` | keep `STRATEGIES` (L53) and `optimize()` signature unchanged — **this is the seam** | — |
| `backend/tests/` | new `test_optimization_parity_skfolio.py` — assert max abs weight delta vs the cvxpy path | 2 |
| `backend/app/services/backtest_service.py` | **do not touch** | — |

**3. Migration order.**

1. **Install + pin, run the full suite unchanged.** Nothing imports skfolio yet, so the suite must be unchanged-green. This proves the install is non-disruptive.
2. **Write the parity test first, against the hand-rolled code.** For each of the four overlapping strategies, assert `max |w_skfolio − w_finexchange| < tol` on a seeded frame. Expect `min_cvar` and `min_vol` to pass tightly; expect `hrp` to need a documented tolerance.
3. **Add a shadow path.** `optimize()` gains an optional `backend: str = "cvxpy"` parameter, defaulting to today's implementation. Nothing changes for callers. `backtest_service.py:104` is untouched.
4. **Add a regression endpoint / test that runs both and publishes the delta.** This is the artifact that makes the swap auditable later.
5. **Only after the delta has been stable for a release**, flip `backend="skfolio"` for `min_cvar` (best parity, highest value). Leave `hrp` on the hand-rolled path — it encodes a specific Lopez de Prado variant skfolio does not reproduce.
6. Separately and later: pilot `CombinatorialPurgedCV` inside `backtest_service` for fold/embargo discipline, keeping the existing inner accounting.

**4. Keep vs replace.**

- **KEEP:** `STRATEGIES`, `optimize()`, `run_walk_forward_backtest`'s turnover/drift/benchmark accounting, all of `tail_risk_service` and the copula/EVT work.
- **SHADOW FIRST, maybe adopt:** `min_vol`, `max_sharpe`, `min_cvar`, `hrp`.
- **ADOPT DIRECTLY (new capability, nothing to displace):** Euler risk contribution via `Portfolio.contribution()`, `LedoitWolf`/`OAS`/`DenoiseCovariance`, `CombinatorialPurgedCV`, `RiskBudgeting`.
- **REJECT for now:** cardinality/threshold constraints (no MIP solver), `SyntheticData`/`OpinionPooling` (no use case yet).

**5. Rewritten code example** — skfolio as a shadow backend behind FinEngine's existing seam:

```python
# backend/app/services/optimization_service.py

#: Strategy -> (skfolio RiskMeasure, skfolio estimator factory). Only the four
#: strategies FinEngine already implements are mapped; `hrp` is deliberately
#: excluded because skfolio's distance default is not FinEngine's linkage choice.
_SKFOLIO_RISK_MEASURES = {
    "min_vol": RiskMeasure.VARIANCE,
    "max_sharpe": None,          # -> ObjectiveFunction.MAXIMIZE_RATIO
    "min_cvar": RiskMeasure.CVAR,
}


def _skfolio_backend(
    train_window: pd.DataFrame,
    strategy: str,
    risk_free_rate: float,
    *,
    previous_weights: Optional[pd.Series] = None,
) -> Optional[Dict[str, Any]]:
    """skfolio's answer to the same question `optimize()` answers, or None.

    Returns None for any strategy without a faithful skfolio equivalent, so the
    caller silently keeps its own implementation rather than degrading to a
    different estimator.
    """
    if strategy not in _SKFOLIO_RISK_MEASURES:
        return None
    if train_window.empty or train_window.shape[1] < 2 or len(train_window) < 30:
        return None

    try:
        kwargs = dict(
            min_weights=0.0, max_weights=1.0, budget=1.0,   # long-only, fully invested
            risk_free_rate=float(risk_free_rate),
            solver="CLARABEL",                                # same solver as _solve()
        )
        if strategy == "max_sharpe":
            model = MeanRisk(
                objective_function=ObjectiveFunction.MAXIMIZE_RATIO, **kwargs)
        else:
            model = MeanRisk(
                risk_measure=_SKFOLIO_RISK_MEASURES[strategy],
                cvar_beta=0.95, **kwargs)
        if previous_weights is not None:
            model = MeanRisk(risk_measure=_SKFOLIO_RISK_MEASURES[strategy],
                             previous_weights=previous_weights.reindex(
                                 train_window.columns).fillna(0.0), **kwargs)

        model.fit(train_window)
        portfolio = model.predict(train_window)
        weights = {a: float(w) for a, w in zip(portfolio.assets, portfolio.weights)}
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("skfolio backend unavailable for %s: %s", strategy, exc)
        return None

    missing = [a for a in train_window.columns if a not in weights]
    if missing:
        return None
    return {
        "weights": {a: weights[a] for a in train_window.columns},
        "estimator": "skfolio",
        "cvar_95": float(portfolio.cvar) if hasattr(portfolio, "cvar") else None,
    }
```

Call it from the existing `optimize()` fan-out, or — cleanest — from `backtest_service.py:104` as an opt-in so `optimization_service` itself stays untouched:

```python
# backend/app/services/backtest_service.py (line ~104, inside the existing try)
opt_res = optimize(train_window, strategy=strategy, risk_free_rate=risk_free_rate)
if use_skfolio_backend:                    # new kwarg, default False
    shadow = _skfolio_backend(train_window, strategy, risk_free_rate,
                              previous_weights=pd.Series(current_weights, index=assets))
    if shadow is not None:
        rebalance_events[-1]["shadow_weights"] = {
            a: round(w, 6) for a, w in shadow["weights"].items()
        }
        rebalance_events[-1]["max_weight_delta"] = round(float(
            0.5 * np.abs(np.array(list(shadow["weights"].values())) - new_weights).sum()
        ), 6)
```

That delta is the deliverable. It is the evidence that lets step 5 happen later on judgement rather than faith.

### Risk & caveats

1. **`plotly>=6.0.0` is a new ~40 MB hard dep** for a plotting feature FinEngine does not use (it has its own Next.js charts). This is the entire cost of adoption. It cannot be made optional.
2. **The 1.4.x API is in motion.** Releases landed on 2026-09-25, -26 (×2) alone. `get_measures` moved from `skfolio.measures` to `skfolio.metrics`; `predict()` began requiring `X`; `weights` is an `ndarray` not a Series. **Pin `>=1.4,<2` and re-run parity tests on every bump.** Do not write `from skfolio import MeanRisk` — it does not work.
3. **`hrp` will not match.** FinEngine's `_hrp_weights` (L549) is a specific Lopez de Prado recursive-bisection variant; skfolio's `HierarchicalRiskParity` uses a distance estimator with a different default. Treat as a cross-check, never a silent swap.
4. **Sync, CPU-bound, and `cross_val_predict` spawns joblib workers.** Not asyncio-friendly. Must be `to_thread`ed; `n_jobs=-1` inside an async request is a deliberate CPU-bound section.
5. **No mixed-integer solver.** `cardinality=`, `threshold_long=`, `threshold_short=` need SCIP/GUROBI/MOSEK. Not available. Do not expose them in the API.
6. **Silent-failure contract.** skfolio's default `raise_on_failure=True` will raise on degenerate input. FinEngine's `optimize()` has a per-window fallback contract (`backtest_service.py:111-113`); the wrapper must catch and return `None`, never let an exception escape into a backtest loop.
7. **Lookahead discipline is on you.** `WalkForward(purged_size=, embargo_size=)` defaults to `purged_size=0`. FinEngine's own audits flag lookahead as a cross-cutting bug class (`.scratch/backend-audit-2026/LIBRARY_FIXES.md:76`). Set `purged_size` and `embargo_size` explicitly, or the default silently reintroduces the problem the whole codebase is trying to avoid.
8. **Open issue #331** — IC t-statistic wrong for overlapping windows. Affects factor/attribution work, not weights.

---

## backtrader

### Verdict

**AVOID** — GPL-3.0-or-later is a hard legal blocker: importing it into FinEngine's proprietary FastAPI backend triggers §5(c) and obliges you to release the entire backend source under GPLv3. It is also **abandoned** — zero commits on `master` since 2023-04-19, zero open issues, 63 untriaged open PRs, issue creation disabled. It *does* still work on Python 3.12 + pandas 3.0.6 (VERIFIED), so the blocker is purely legal and strategic, not technical.

### License

- **License:** GNU General Public License v3 **or later**
- **SPDX:** `GPL-3.0` (GitHub API). Note the *package* declares `GPL-3.0-or-later`; the SPDX id for the detected license is the bare `GPL-3.0`.
- **Declared:** `license='GPLv3+'` in [`setup.py`](https://github.com/mementum/backtrader/blob/master/setup.py); PyPI `License: GPLv3+`; classifier `License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)`
- **Text:** [`LICENSE`](https://github.com/mementum/backtrader/blob/master/LICENSE) = GPLv3 verbatim, VERIFIED (header "GNU GENERAL PUBLIC LICENSE / Version 3, 29 June 2007")
- **Per-file headers:** VERIFIED. Every source file carries the GPL notice, e.g. `backtrader/brokers/__init__.py`:
  > "# Copyright (C) 2015-2023 Daniel Rodriguez / # This program is free software: you can redistribute it and/or modify / it under the terms of the GNU General Public License as published by / the Free Software Foundation, either version 3 of the License, or / (at your option) any later version."

**⚠️ VERIFIED: backtrader is GPLv3+, not permissive. Commonly assumed otherwise — do not.**

**Clause quote** — §5 Conveying Modified Source Versions (GPLv3):

> "c) You must license the entire work, as a whole, under this License to anyone who comes into possession of a copy. This License will therefore apply, along with any applicable section 7 additional terms, to the whole of the work, and all its parts, regardless of how they are packaged. This License gives no permission to license the work in any other way…"

### Commercial impact — **THIS IS THE BLOCKER**

**A proprietary/commercial app like FinEngine cannot use backtrader as a dependency without consequence.** Three points, in order of severity:

1. **§5(c) — the whole work becomes GPLv3.** Python `import backtrader` is a direct function-call-level dependency, not "mere aggregation." There is no JVM-style classpath or `scripts/`-directory carve-out for CPython: the FSF's own position and ordinary practice treat a Python `import` as making the importing work a *combined work* under the GPL. §5(c) then requires licensing **the entire work as a whole** under GPLv3. That means FinEngine's `backend/` — including `analytics_engine.py` (3,867 lines), all services, and the Next.js `frontend/` that talks to it — would have to be released under GPLv3.

2. **Derivative-work and source-disclosure risk extends past the backend.** Once the combined work must be GPLv3, conveying it (hosting it for users, distributing a container, handing it to a client) requires the **complete Corresponding Source** of the whole work, including your own original code. There is no "only the vendored part" limit.

3. **No proprietary path exists without a commercial licence.** The correct options are (a) rewrite the engine (which is what FinEngine has already done, at 199 lines), (b) buy a commercial licence from the author, or (c) use a permissive alternative. There is no "link but don't redistribute" reading of GPLv3 that survives §5(c).

**Linking vs vendoring:** there is no safe option. Linking triggers §5(c). Vendoring triggers §5(b)+(c) immediately and is strictly worse. **The only compliant use is keeping it in a separate process with no linkage** — at which point you have gained nothing over the 199-line vectorized rebalancer FinEngine already has.

> I am not a lawyer and this is not legal advice. The above is a technical reading of the licence text. **Get counsel before any commercial deployment decision.**

### Maintenance

**ABANDONED — VERIFIED with dates.**

| Fact | Value | Source |
|---|---|---|
| Last commit on `master` | **2023-04-19** — *"Version 1.9.78.123"* (`b853d7c`) | [commits/master](https://github.com/mementum/backtrader/commits/master/) |
| PyPI release | 1.9.78.123, uploaded **2023-04-19T14:13:18Z** | [PyPI](https://pypi.org/project/backtrader/) |
| Repo `pushed_at` | 2024-08-19T17:47:36Z — ⚠️ a **non-master branch** push, not a code commit | GitHub API |
| Last commit by the actual maintainer before the 2023 docs sweep | **2021-07-17** (`e2674b1`, merged PR #453) | commits page |
| **Open issues** | **0** — and **"Issue creation is restricted in this repository"** | [issues](https://github.com/mementum/backtrader/issues) |
| **Open PRs** | **63**, none triaged | issues page nav |
| Archived flag | No (but functionally abandoned) | GitHub API |
| Stars / forks | 23,331 / 5,294 | GitHub API |

**The 63-open-PRs / 0-open-issues / issue-creation-restricted combination is the signature of abandonment, not moderation.** The 2023 activity was a single copyright-year update and README restoration by the then-owner; the last substantive code change is from 2020. The widely-held belief that backtrader is dormant is **confirmed with dates**: three and a half years without a commit on the default branch.

**Migration/community status:** the community has moved to forks (`backtrader2`, `bt`, `backtrader_plotting`, and the `backtesting.py` family). Each fork carries its own licence posture, and none of them is upstream backtrader.

### Compatibility

| Axis | Status | Evidence |
|---|---|---|
| **Python 3.12** | ✅ **VERIFIED WORKS** | Imported and ran two full backtests on 3.12.9 |
| **pandas 3.0.6** | ✅ **VERIFIED WORKS** | Both a single-instrument and a 3-asset rebalancing run completed on 3.0.6 |
| **numpy 2.5.3** | ✅ VERIFIED | 2.5.3 in both runs |
| **Declared support** | ❌ **Stale by 5 releases** | `setup.py` classifiers stop at **Python 3.7**; `requires_python` is **empty**; README says *"compatible with Python 3.2 and later"*; plotting needs `matplotlib>=1.4.1` |
| **Hard deps** | ✅ **Zero** | `install_requires` is commented out; only `extras_require={'plotting': ['matplotlib']}` |
| **async FastAPI fit** | ⚠️ **sync-only, event-loop blocking** | See below |

**VERIFIED on Python 3.12.9 + pandas 3.0.6 + numpy 2.5.3** (installed in a throwaway venv; this is an honest, tested result and it contradicts the "it's broken on modern pandas" assumption):

```
backtrader 1.9.78.123 imports cleanly
  -> SyntaxWarning: invalid escape sequence '\*' (cerebro.py:670, :712) — cosmetic

Single-instrument SMA strategy, 500 bars   -> OK, final broker value 1,000,010.26
3-asset order_target_percent rebalance,
  300 bars, 14 rebalances, 3 open positions -> OK, final broker value 1,339,366.81
```

So backtrader is **dormant but not broken** for the common paths. The blocker is legal and strategic, not technical. Anyone claiming "it doesn't work on modern Python" is wrong; anyone concluding "so we should use it" has not read the licence.

**Two real API traps (VERIFIED, cost me a cycle each):**

- **`self.getdata(...)` does not exist.** My first multi-asset attempt died with:
  `AttributeError: 'Lines_LineSeries_LineIterator_DataAccessor_StrategyBase_Strategy_Rebal' object has no attribute 'getdata'`
  Correct access is `self.datas[i]` or `self.getdatabyname(name)`.
- **`_riskfreerate` is not a valid analyzer kwarg.** `SharpeRatio.__init__() got an unexpected keyword argument '_riskfreerate'`. VERIFIED real params:
  `{'timeframe': 8, 'compression': 1, 'riskfreerate': 0.01, 'factor': None, 'convertrate': True, 'annualize': False, 'stddev_sample': False, 'daysfactor': None, 'legacyannual': False, 'fund': None}` — note `riskfreerate`, no leading underscore, and `annualize` defaults to **False**.
  ⚠️ **Context7's `/mementum/backtrader/_autodocs/analyzer.md` documents `strat.analyzers[0].get_analysis()` and `_riskfreerate` — both are wrong for backtrader 1.9.78.123.** The `_autodocs/` tree appears to be generated content, not upstream documentation. Use it with suspicion; the real source is authoritative.

**VERIFIED analyzer weakness.** On a 250-bar daily series:

```
SharpeRatio (riskfreerate=0.02)  ->  OrderedDict({'sharperatio': None})     # None, silently
Calmar       (period=36, monthly) ->  12 monthly values, ALL NaN
DrawDown                         ->  max drawdown 11.51% over 77 bars
TradeAnalyzer                   ->  {'total': ...}
```

`SharpeRatio` returning `None` and `Calmar` returning all-`NaN` without raising is a **silent-degradation hazard**: an institutional risk platform cannot accept an analyzer that yields `None` where FinEngine's own tear-sheet returns a 6-decimal figure with a bootstrap interval. FinEngine would have to re-derive Sharpe and Calmar itself — at which point backtrader contributes only the order-matching engine.

**Async / GIL.** Fully synchronous, single-threaded, pure-Python bar loop. `Cerebro.run()` iterates every bar of every feed in Python — with 3 feeds × 300 bars that is 900 Python-level iterations before any order logic. It blocks the event loop completely. FinEngine's own audit already flags this pattern (`.scratch/backend-deep-audit/code/01-api-layer.md:70`).

### Dependency footprint

**Direct deps: NONE.** VERIFIED from `setup.py` — `install_requires` is entirely commented out with the note `# install_requires=['six'],`. The only extra is `extras_require={'plotting': ['matplotlib']}`.

**Conflict risk: ZERO** — and this is backtrader's one genuine engineering advantage. With no declared dependencies, `uv` cannot be forced to move pandas, numpy, or anything else. **VERIFIED**: `uv pip install backtrader` into a venv that already had `pandas==3.0.6 numpy==2.5.3` added **zero** packages.

That also means backtrader ships its own stale compatibility shims rather than benefiting from the ecosystem's — hence the 2020 `collections.Iterable → collections.abc.Iterable` fix and the 2021 `matplotlib 3.7` locator fix being the last substantive commits. It is running on a hand-maintained island.

### API surface

All snippets below are **VERIFIED by execution** on Python 3.12.9 + pandas 3.0.6, except the analyzer block where I note what is real vs. what Context7 got wrong.

**Single instrument:**

```python
import warnings, numpy as np, pandas as pd
warnings.filterwarnings("ignore")                 # backtrader emits SyntaxWarnings at import
import backtrader as bt

dates = pd.bdate_range("2020-01-01", periods=500)
px    = 100 * np.cumprod(1 + np.random.normal(0.0005, 0.012, 500))
df = pd.DataFrame({"open": px, "high": px*1.01, "low": px*0.99,
                   "close": px, "volume": 1e6}, index=dates)

class SMAcross(bt.Strategy):
    params = (("fast", 20),)
    def __init__(self):
        self.sma = bt.indicators.SMA(period=self.p.fast)
    def next(self):
        if not self.position and self.data.close[0] > self.sma[0]:
            self.buy()
        elif self.position and self.data.close[0] < self.sma[0]:
            self.close()

c = bt.Cerebro(stdstats=False)                    # stdstats=False silences the console report
c.adddata(bt.feeds.PandasData(dataname=df))
c.addstrategy(SMAcross)
c.broker.setcash(1_000_000)
c.run()                                           # VERIFIED: 1,000,010.26
```

**Multi-asset rebalancing** (VERIFIED — this is the shape FinEngine would actually want):

```python
class MonthlyRebal(bt.Strategy):
    def next(self):
        if len(self) % 21 == 0:                  # ~monthly, bar-count based
            for d in self.datas:                  # NOTE: self.datas[i], NOT self.getdata(i)
                self.order_target_percent(data=d, target=1.0 / len(self.datas))

c = bt.Cerebro(stdstats=False)
for ticker, frame in feeds.items():                # NSE tickers are just column labels here
    c.adddata(bt.feeds.PandasData(dataname=frame), name=ticker)
c.addstrategy(MonthlyRebal)
c.broker.setcash(1_000_000)
strat = c.run()[0]
strat.positions                                  # VERIFIED: 3 positions after 14 rebalances
```

**Analyzers — corrected, VERIFIED against 1.9.78.123:**

```python
c.addanalyzer(bt.analyzers.SharpeRatio,    _name="sharpe", riskfreerate=0.02)   # no underscore!
c.addanalyzer(bt.analyzers.DrawDown,      _name="dd")
c.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
c.addanalyzer(bt.analyzers.Calmar,        _name="calmar")
s = c.run()[0]
s.analyzers.sharpe.get_analysis()       # -> {'sharperatio': ...}  (named access VERIFIED)
s.analyzers.getbyname("sharpe").get_analysis()   # also works
s.analyzers[0]                          # positional access also works (VERIFIED)
```

⚠️ `bt.analyzers.SharpeRatio` default `annualize=False` and `riskfreerate=0.01` — both must be set explicitly. And per the weakness above, both `SharpeRatio` and `Calmar` can return `None`/`NaN` on short series without raising.

**Real analyzer set** (VERIFIED from `backtrader/analyzers/__init__.py`): `annualreturn, drawdown, timereturn, sharpe, tradeanalyzer, sqn, leverage, positions, transactions, pyfolio, returns, vwr, logreturnsrolling, calmar, periodstats`.

### Overlap with FinEngine

| FinEngine file / function | backtrader replacement | Effort | Risk |
|---|---|---|---|
| `backtest_service.py:19 run_walk_forward_backtest` — 199 lines, vectorized, walk-forward, self-financing weight drift, one-way turnover, equal-weight buy-and-hold benchmark, `STRATEGIES` routing, per-window failure fallback | `Cerebro` + `MonthlyRebal` + `order_target_percent` | **L** | **High, and pointless.** The replacement is *slower*, *less transparent*, *unable to use FinEngine's cvxpy `optimize()`* (which is the whole point of the walk-forward), and *legally unusable*. Net loss on every axis except broker realism. |
| `backtest_service.py:118` one-way turnover | none | — | backtrader has no portfolio-turnover metric. |
| `backtest_service.py:104 optimize(train_window, strategy=...)` | **no equivalent** | — | backtrader cannot call a Python portfolio optimizer. This alone disqualifies it for FinEngine. |
| `backtest_service.py:228-233` benchmark CAGR/vol/Sharpe/MDD | `bt.analyzers.SharpeRatio` / `Calmar` | **M** | **High** — VERIFIED to return `None` / all-`NaN` on a 250-bar series. Would silently replace FinEngine's 4-decimal figures with nulls. |
| `backtest_service.py:209-217 equity_curve / drawdowns` | `strat.analyzers.drawdown`, broker value | **M** | Medium — requires post-hoc reconstruction from trade records. |
| `backtest_service.py:22 rebalance_freq_days=21` | bar-count `len(self) % 21` | **S** | Low mechanically, but trades calendar-day semantics for bar-count semantics. |
| `backtest_service.py:24 transaction_cost_bps` | `setcommission(commission=...)` + `set_slippage_perc` | **M** | Medium — Indian STT/stamp/SEBI/GST are asymmetric per-leg and leg-dependent; neither FinEngine nor backtrader models them. `.scratch/backend-audit-2026/LIBRARY_FIXES.md:76` already flags this as a required custom `costs.py`. |
| `analytics_engine.py` / `monte_carlo_service.py` | **no overlap** | — | backtrader has no risk-measurement library. |
| — | `bt.analyzers.PyFolio` → `pyfolio.create_full_tear_sheet()` | — | Dead end: `pyfolio` is unmaintained and pulls matplotlib at runtime. Quantstats already covers this better. |
| — | `bt.sizers.PercentSize` / `FixedSize` | — | Marginal; FinEngine sizes in weights directly. |
| — | `bt.feeds.GenericCSVData`, live-trading broker stubs (`IbBroker`, `OandaV20`) | — | Out of scope. FinEngine is analytics-only, no live trading. |

**Net overlap: 0 files worth replacing.** The one FinEngine service in this library's wheelhouse is the one backtrader is worst at replacing.

### Implementation guide

**1. `backend/pyproject.toml` line: NONE. Do not add it.**

There is no implementation guide, because there is no implementation. This is the correct and complete guidance for backtrader.

If someone insists on an *evaluation* install, it must be isolated — never on the backend's dependency graph:

```
uv tool run --from backtrader==1.9.78.123 python -c "import backtrader; print(backtrader.__version__)"
```

or a throwaway venv, as done here (`C:\Users\Sayanti\AppData\Local\Temp\opencode\libcheck\v1`). Never `uv add backtrader` to `backend/`.

**2. Files to touch: none.** Do not touch `backtest_service.py`, `optimization_service.py`, or `pyproject.toml`.

**3. If you need backtrader-shaped capability legally:** the pieces worth *reimplementing* (not importing) are `order_target_percent` semantics and the `DrawDown` analyzer's peak logic. FinEngine's `backtest_service.py:173-183` already does the drawdown correctly and **better** — it explicitly prepends the initial wealth of 1.0 as the first peak (L175) with the comment *"The first out-of-sample loss must be able to create a drawdown immediately."* That is exactly the baseline class of bug backtrader's `DrawDown` and quantstats 0.0.81's `max_drawdown` each got wrong.

**4. Keep vs replace:** keep everything. Replace nothing.

**5. Rewritten code example:** not applicable. The valuable output of this review is the list of things backtrader *cannot* do, which is now recorded in `backtest_service.py`'s favour.

### Risk & caveats

1. **GPL-3.0-or-later §5(c) is disqualifying.** See the Commercial impact section above. This alone is sufficient reason to reject.
2. **Abandoned since 2023-04-19.** Zero open issues, 63 open PRs, issue creation disabled. No security or pandas-3.0 fixes will ever arrive. Any pandas breakage found in future is permanent unless you fork it — and forking a GPL project does not escape the copyleft.
3. **README is wrong about modern Python.** Claims 3.2+; classifiers stop at 3.7; `requires_python` is empty. It happens to work on 3.12 + pandas 3.0.6 (VERIFIED) purely by accident of minimal dependency surface — that is luck, not support.
4. **Analyzers silently return `None`/`NaN`.** VERIFIED on 250 bars. Unacceptable for an institutional platform that publishes precision intervals.
5. **Cannot call FinEngine's optimizer.** `STRATEGIES` routing is the core of the walk-forward, and `Cerebro` has no hook for it.
6. **Context7's backtrader `_autodocs/` tree is unreliable.** It documents `strat.analyzers[0].get_analysis()` and `_riskfreerate=`; both are wrong for 1.9.78.123. Treat any `_autodocs/` content with suspicion.
7. **Forks are not a workaround.** `backtrader2` / `bt` etc. carry their own licences and none is upstream backtrader. Verify each fork's own `LICENSE` independently; several are MIT relicences, but they inherit no upstream maintenance and each needs its own assessment.

---

## backtesting.py

### Verdict

**AVOID** — the licence is **AGPL-3.0**, not the GPL or Apache that the name and popularity suggest, and **AGPL §13 is a network-copyleft clause that triggers on exactly what FinEngine is: a modified version of a network-server program**. It is independently disqualified for FinEngine's use case by its own first-party documentation, which states it *"does not support multi-asset portfolio rebalancing."* Technically it is the better-maintained and more pandas-3-ready of the two backtesters, which makes it the more dangerous one.

### License

- **License:** GNU Affero General Public License v3
- **SPDX:** `AGPL-3.0`; PyPI `License: AGPL-3.0`; classifier `License :: OSI Approved :: GNU Affero General Public License v3 or later (AGPLv3+)`
- **Text:** [`LICENSE.md`](https://github.com/kernc/backtesting.py/blob/master/LICENSE.md) = AGPLv3 verbatim, VERIFIED (header "GNU AFFERO GENERAL PUBLIC LICENSE / Version 3, 19 November 2007")
- **Docs state it plainly** — [kernc.github.io/backtesting.py](https://kernc.github.io/backtesting.py/doc/backtesting/):
  > "This software is licensed under the terms of AGPL 3.0, meaning you can use it for any reasonable purpose and remain in complete ownership of all the excellent trading strategies you produce, but you are also encouraged to make sure any upgrades to Backtesting.py itself find their way back to the community."

**⚠️ VERIFIED: backtesting.py is AGPL-3.0.** The name "backtesting" suggests permissiveness and the README's "retain complete ownership of all the excellent trading strategies you produce" reads like a permissive licence. It is not. The first line of the licence file is "GNU AFFERO GENERAL PUBLIC LICENSE".

**Clause quote — §13 Remote Network Interaction (AGPLv3), VERIFIED verbatim:**

> "Notwithstanding any other provision of this License, if you modify the Program, your modified version must prominently offer all users interacting with it remotely through a computer network (if your version supports such interaction) an opportunity to receive the Corresponding Source of your version by providing access to the Corresponding Source from a network server at no charge, through some standard or customary means of facilitating copying of software. This Corresponding Source shall include the Corresponding Source for any work covered by version 3 of the GNU General Public License that is incorporated pursuant to any other provision of this License."

And from the Preamble:

> "The GNU Affero General Public License is designed specifically to ensure that, in such cases, the modified source code becomes available to the community. It requires the operator of a network server to provide the source code of the modified version running there to the users of that server. Therefore, public use of a modified version, on a publicly accessible server, gives the public access to the source code."

### Commercial impact — **THIS IS THE BLOCKER, AND IT IS WORSE THAN GPL**

**The AGPL is materially more dangerous than the GPL for a web service, and FinEngine sits exactly on the trigger.**

| | GPL-3.0 (backtrader) | **AGPL-3.0 (backtesting.py)** |
|---|---|---|
| Source disclosure when **distributing** | yes | yes |
| Source disclosure when **running as a network service** | **no** | **YES — §13** |
| FinEngine's shape (FastAPI backend, users connect over HTTP) | distribution-only trigger | **§13 trigger fires on first use** |

**The practical consequence for FinEngine:** FinEngine is a FastAPI application. Users interact with it remotely over a network. That is the literal, named subject of AGPL §13. Importing `backtesting` into `backend/app/services/` creates a modified version of a network-server program, and §13 then requires that FinEngine **prominently offer every remote user access to the Corresponding Source of the entire combined work** — i.e. `analytics_engine.py`, all services, the models, and arguably the frontend that drives it.

Three things make this worse than it first looks:

1. **There is no "internal use only" escape.** GPL has a well-known internal-use carve-out (§13 GPL / the "mere aggregation" and non-conveyance arguments). **AGPL was written specifically to close it.** The "and the corresponding source need not include …" and "if your software can interact with users remotely through a computer network, you should also make sure that it provides a way for users to get its source" language exists to defeat exactly the argument FinEngine would want to make.
2. **The trigger is use, not release.** FinEngine is described as personal/single-user today, which is a genuine consideration — but it is also described as an *institutional* platform. The moment it is offered to any third party over a network, §13 attaches. A licence decision that must be revisited at the first institutional customer is not a licence decision, it is a liability.
3. **§13's "prominently offer" is an affirmative UI obligation**, not a passive source-drop. FinEngine would owe users a visible, working source-acquisition path for the combined work.

**Linking vs vendoring:** §13 is identical for both. Vendoring is strictly worse. There is **no compliant way to use backtesting.py inside FinEngine's proprietary server** short of a commercial licence from the author (the author does sell one — the licence is deliberately dual-licensed in practice, though that is an arrangement to negotiate, not a PyPI feature; **UNVERIFIED in detail — needs manual check with the author**) or keeping it in a fully separate, non-linked process with no source obligation, which defeats the purpose.

> Not legal advice. This is a technical reading of the licence text. **Get counsel.** The asymmetry matters: an incorrect "it's just AGPL, fine" is a far more expensive error here than it would be for GPL, because §13 attaches on use.

### Maintenance

**ACTIVE, moderate cadence.** Not abandoned — but not the hyperactive cadence of quantstats/skfolio either.

| Fact | Value | Source |
|---|---|---|
| Latest release | **0.6.6**, uploaded **2026-07-22T14:39:23Z** | [PyPI](https://pypi.org/project/backtesting/) |
| Last commit | **2026-08-05T12:39:16Z** — *"BUG: Size shared memory by materialized array, not lazy Index.nbytes"* | [commits](https://github.com/kernc/backtesting.py/commits/master) |
| Last release → last commit gap | ~2 weeks (post-release fix) | — |
| **Release cadence** | **~7 weeks since 0.6.6** (prior tags 0.6.2–0.6.5) | [tags](https://github.com/kernc/backtesting.py/tags) |
| Open issues | 86 total; 43 open-and-pre-2026 | [issues](https://github.com/kernc/backtesting.py/issues) |
| Issues created 2026 YTD | 11 | search |
| Merged PRs 2026 | Several (e.g. #1354 FutureWarning fix, #1360 silent-cancellation fix, #1370 unreachable-price fix, #1444 `MultiBacktest.run` fix) | [PRs](https://github.com/kernc/backtesting.py/pulls) |
| Stars / forks | 9,000 / 1,540 | GitHub API |
| Archived | No | GitHub API |
| Python classifiers | `Programming Language :: Python :: 3 :: Only` (no per-minor breakdown) | PyPI |

**Healthy but slower.** The 2026 merged-PR list shows a maintainer actively fixing real correctness bugs (silent order cancellation, unreachable order prices, a pandas `FutureWarning`). That is a *maintained* project, materially unlike backtrader.

**Two live correctness issues, both directly relevant to FinEngine's risk posture:**

- **[#1411](https://github.com/kernc/backtesting.py/issues/1411)** (open, 2026-09-25, 7 comments): *"Call `Strategy.next()` on the first valid bar instead of one bar later (plus various bug fixes)"*. This is a **bar-alignment semantics change** — the first bar of a strategy is currently skipped. For a risk platform that must reconcile its backtest against a spot-check, that is a meaningful class of ambiguity.
- **[#1410](https://github.com/kernc/backtesting.py/pull/1410)** (open PR, 2026-09-23): *"BUG: Fix `Backtest()` with a non-datetime index on pandas 3"*. **Still open — so 0.6.6 does not officially support a non-datetime index under pandas 3.0.** (My own test happened to pass; that is luck, not a fix. See Compatibility.)
- **[#1339](https://github.com/kernc/backtesting.py/issues/1339)**: *"backtesting library skips bars where any indicator has NA values (or don't place orders)"* — open since 2025-12-24. Silent bar-skipping is a data-integrity hazard for a risk engine.
- **[#1333](https://github.com/kernc/backtesting.py/issues/1333)**: *"Optimize method fails w/o any error info"* — the parameter sweep fails silently. FinEngine's `.scratch/v5-review/05-adversarial.md` treats silent-failure pathways as a first-class defect class.

### Compatibility

| Axis | Status | Evidence |
|---|---|---|
| **Python 3.12** | ✅ **VERIFIED WORKS** | `requires_python >=3.9`; ran on 3.12.9 |
| **pandas 3.0.6** | ⚠️ **Works, but 0.0.6 predates the pandas-3 fixes** | VERIFIED run on 3.0.6; open PR #1410 targets pandas-3 non-datetime-index |
| **numpy 2.5.3** | ✅ VERIFIED | `numpy>=1.17.0`; ran on 2.5.3 |
| **Hard deps** | ⚠️ **`bokeh>=3.0.0` is new** | FinEngine has no bokeh |
| **async FastAPI fit** | ⚠️ **sync-only, pure-Python bar loop** | See below |

**VERIFIED on Python 3.12.9 + pandas 3.0.6 + numpy 2.5.3:**

```
backtesting 0.6.6
400-bar SMA-crossover, cash=1,000,000, commission=0.001
  -> Return [%]              0.1306
  -> Sharpe Ratio           0.5131
  -> Max. Drawdown [%]     -0.1398
  -> # Trades               14
```

So it imports and runs on FinEngine's exact stack. **But note the caveat:** a second run with a plain `RangeIndex` also succeeded, **even though PR #1410 ("Fix `Backtest()` with a non-datetime index on pandas 3") is still open.** The 0.6.6 release therefore predates any pandas-3 hardening. Do not treat my passing test as support — treat it as an unpatched edge case that happens to work.

**Dependency conflict — the one real risk:**

| Dep | Constraint | FinEngine installed | Verdict |
|---|---|---|---|
| `numpy` | `>=1.17.0` | 2.5.3 | ✅ |
| `pandas` | `!=0.25.0,>=0.25.0` | 3.0.6 | ✅ (unpinned upper — permissive) |
| `bokeh` | `!=3.0.*,!=3.2.*,>=3.0.0` | **not installed** | ⚠️ **NEW** |

`bokeh` is a **hard** dependency for `Backtest.plot()`. It is not in an extra. FinEngine would gain bokeh plus its tree (`contourpy`, `tornado`, `xyzservices`, `jinja2`, `Pillow`, `packaging`) — a substantial addition for a plotting feature FinEngine does not want (it has Next.js charts). The excluded versions (`!=3.0.*,!=3.2.*`) are an author workaround for bokeh API breaks, which is a mild maintenance smell.

**Async / GIL.** Fully synchronous. `Backtest.run()` is a Python `for` loop over bars calling `broker.next()` and `strategy.next()` — there is no compiled fast path and no numba. The latest commit (2026-08-05) is about sizing shared memory for the optimizer, which is a hint that the optimizer is multiprocessing-based rather than vectorized. Blocks the event loop completely.

### API surface

**⚠️ THE ARCHITECTURAL BLOCKER — VERIFIED single-instrument only.**

```python
# VERIFIED via inspect.signature on the installed 0.6.6:
Backtest.__init__(self, data: pd.DataFrame, strategy: Type[Strategy], *,
                  cash: float = 10000, spread: float = .0,
                  commission: Union[float, Tuple[float, float]] = .0,
                  margin: float = 1., trade_on_close=False, hedging=False,
                  exclusive_orders=False, finalize_trades=False)
```

`data` is **one** `pd.DataFrame`. There is no `data0/data1/...` list, no `datas`, no portfolio accounting across instruments.

**And the project says so itself.** Context7, from backtesting.py's own [Quick Start User Guide](https://github.com/kernc/backtesting.py/blob/master/doc/examples/Quick%20Start%20User%20Guide.ipynb):

> "Backtesting.py is a lightweight Python framework (Python 3.6+, Pandas, NumPy, Bokeh) designed for backtesting trading strategies. It features a simple API and is **optimized for individual tradeable assets, focusing on position entry/exit signals, technical indicator values, and interactive trade visualization. It does not support multi-asset portfolio rebalancing or arbitrage strategies.**"

That sentence is dispositive. FinEngine's need — *"validate allocation and rebalancing strategies over Indian equity data"* — is precisely the excluded case.

**VERIFIED-running end-to-end:**

```python
import warnings, numpy as np, pandas as pd
warnings.filterwarnings("ignore")
from backtesting import Backtest, Strategy

np.random.seed(0)
dates  = pd.bdate_range("2022-01-03", periods=400)
close  = 100 * np.cumprod(1 + np.random.normal(0.0006, 0.013, 400))
high, low = close * 1.012, close * 0.988
data = pd.DataFrame({"Open": (high+low)/2, "High": high, "Low": low,
                     "Close": close, "Volume": np.random.randint(1e5, 5e5, 400).astype(float)},
                    index=dates)

class SMAcross(Strategy):
    def init(self):
        self.sma = self.I(lambda x: pd.Series(x).rolling(20).mean(), self.data.Close)
    def next(self):
        if not self.position and self.data.Close > self.sma:
            self.buy(size=100)
        elif self.position and self.data.Close < self.sma:
            self.position.close()

bt = Backtest(data, SMAcross, cash=1_000_000, commission=0.001)
stats = bt.run()
# VERIFIED: Return 0.1306, Sharpe 0.5131, MaxDD -0.1398, 14 trades
stats["_equity_curve"], stats["_trades"], stats["_strategy"]   # VERIFIED keys
```

**Parameter sweep (VERIFIED from docs; note the silent-failure issue #1333):**

```python
stats, heatmap = bt.optimize(
    n1=range(10, 110, 10), n2=range(20, 210, 20),
    constraint=lambda p: p.n2 < p.n1,
    maximize="Equity Final [$]",
    max_tries=200, random_state=0, return_heatmap=True,
)
```

`optimize` is a randomized grid search over a **single instrument**, bounded by `max_tries`. For FinEngine, running "100s of small backtests" would mean 100s of *independent single-instrument* runs — which answers "does this RSI rule make money on RELIANCE" and not "is this HRP rebalancing schedule better than monthly". **The question is not being asked of the right tool.**

**Multi-timeframe is the closest thing to multi-asset**, and it is not it (Context7, from the project's own tutorial):

```python
from backtesting.lib import resample_apply
self.weekly_rsi = resample_apply("W-FRI", RSI, self.data.Close, self.w_rsi)
```

That is a *coarser timeframe of the same instrument*.

**Data shape requirement (Context7, from the project's own docs):** must include `'Open'`, `'High'`, `'Low'`, `'Close'`; `'Volume'` optional. *"A datetime index is recommended, but a range index is also acceptable"* — subject to open PR #1410 under pandas 3.

### Overlap with FinEngine

| FinEngine file / function | backtesting.py replacement | Effort | Risk |
|---|---|---|---|
| `backtest_service.py:19 run_walk_forward_backtest` — multi-asset (`for offset,row_name in enumerate(chunk_index)`, L135-162) | **none — impossible** | — | **N/A. `Backtest` takes one DataFrame.** Disqualified by architecture. |
| `backtest_service.py:104 optimize(train_window, strategy=...)` | **none** | — | backtesting.py cannot invoke a cvxpy optimizer. |
| `backtest_service.py:75 rebalance_indices` schedule | per-bar `len(self) % 21` on one instrument | **N/A** | Different quantity. |
| `backtest_service.py:118` one-way turnover | `Portfolio.turnover` equivalent | — | **Does not exist.** Single-instrument position entry/exit is not portfolio turnover. |
| `backtest_service.py:209-217 equity_curve / drawdowns` | `stats["_equity_curve"]` | **S** | Low in isolation. But it is single-instrument. |
| `backtest_service.py:188-207` CAGR/Sharpe/MDD/Calmar | `stats["Sharpe Ratio"]`, `["Calmar Ratio"]`, `["Max. Drawdown [%]"]` | **S** | Low mechanically. **However** issue #1255 (*"Error printing stats starting at Sortino Ratio"*, open since 2025-03-25) shows the stats table is not fully robust. |
| `backtest_service.py:24 transaction_cost_bps=10.0` | `commission=0.001`, or `spread=` | **M** | Medium — `commission` is symmetric; Indian STT/stamp/SEBI/GST are asymmetric per-leg. Same gap backtrader has. |
| `screener_service.py` single-ticker signal scanning | `Backtest` per ticker | **M** | Medium — a screener is the *one* place single-instrument signal backtesting fits. **This is backtesting.py's only plausible FinEngine use.** Still blocked by AGPL. |
| — (no equivalent) | `optimize()` parameter sweep, `MultiBacktest`/`Pool` | — | Pure gain *for signal strategies only* |
| `frontend` interactive trade chart | `bt.plot()` (Bokeh) | — | **Reject.** FinEngine has its own Next.js charts. This is the sole reason `bokeh` would be added. |

**Net overlap: 0 portfolio-level files.** The only candidate use is per-ticker signal screening, which AGPL forbids.

### Implementation guide

**1. `backend/pyproject.toml` line: NONE. Do not add it.**

```toml
    # NOT THIS — AGPL-3.0 §13 attaches on network use:
    # "backtesting>=0.6.6",
```

**2. Files to touch: none.**

**3. If a commercial AGPL licence is ever negotiated:** the isolated-evaluation pattern is mandatory. Never `uv add`:

```
uv tool run --from backtesting==0.6.6 python -c "from backtesting import Backtest; print('ok')"
```

**4. Keep vs replace:** keep everything. Replace nothing.

**5. Rewritten code example:** not applicable.

### Risk & caveats

1. **AGPL-3.0 §13 is disqualifying and attaches on *use*, not distribution.** FinEngine is a network server. See the comparison table above — the AGPL is strictly more dangerous here than the GPL.
2. **Single-instrument only, by the project's own documentation.** No amount of engineering turns it into a portfolio rebalancer. Disqualified independently of the licence.
3. **Cannot call FinEngine's optimizer.** `STRATEGIES` routing has no hook.
4. **`bokeh` becomes a hard dependency** (~10 transitive packages) purely for `Backtest.plot()`, which FinEngine would not use.
5. **0.6.6 predates the pandas-3 fixes.** Open PR #1410. My RangeIndex test passed, but that is an unpatched path, not support.
6. **Silent-failure pathways.** Issue #1333 (`optimize()` fails with no error info), #1339 (bars with NA indicators silently skipped), #1360 (absolute-size orders silently cancelled for insufficient margin — merged 2026-07-22, so that one is fixed). Two remain. FinEngine's own audits treat silent failure as a first-class defect class; `.scratch/v5-review/05-adversarial.md` documents a live instance of a published-number-without-a-methodology problem.
7. **Bar-alignment semantics unsettled.** Issue #1411 (open, 7 comments) proposes changing when `next()` is first called. Until it settles, a backtest here is hard to reconcile against a spot-check.
8. **AGPL is dual-licensed in practice** — the author sells commercial licences. **UNVERIFIED in detail — needs manual check with the author.** That is a procurement conversation, not a PyPI install.

---

## FinEngine's current quantstats usage audit

**Verdict: heavily under-used, and the pin is stale.**

### Which files use it

| File | Kind | Depth |
|---|---|---|
| `backend/app/api/analytics.py` | Production | **41 of 55 `app/` hits.** One route handler (`get_tear_sheet`, L6011-6420) + one shared guard (`_q`, L498-510) |
| `backend/app/services/analytics_engine.py` | Production | 2 functions (L1037-1050, L1053-1152) — *restatements of* quantstats, not calls into it |
| `backend/pyproject.toml:21` | Manifest | `"quantstats",` — **unpinned** |
| `backend/uv.lock:3049-3064` | Lock | `0.0.81`, uploaded 2026-01-13 |
| `backend/tests/test_uncertainty_disclosure.py` | Test | `import quantstats as qs` (L36); asserts vectorised restatements reproduce `qs.stats.*` (L296-355, 512-514, 595, 720-737, 763) |
| `frontend/src/lib/api.ts:482` | Frontend | comment only — `// Get quantstats tear-sheet vs NIFTY` |
| `frontend/src/components/layout/Sidebar.tsx:120` | Frontend | subtitle string only |
| `.scratch/**`, `RELEASE_NOTES.md`, `README.md`, `PROJECT.md`, `CONTEXT.md`, `instructions/**` | Docs | 100+ hits, no code |

The remaining `.scratch/backend-deep-audit/quant/evidence/*.py` files are audit harnesses that **import quantstats directly as the reference oracle** — e.g. `verify-risk-timeseries.py:1019-1029,1053`. Those are the project's own numerical ground truth and are a strong reason to be careful about the upgrade.

### Exactly what is called

**15 of quantstats' 84 `qs.stats` functions = 18% of the stat surface.** (`dir(qs.stats)` VERIFIED: 84 public names in 0.0.81.)

| Call site | Functions |
|---|---|
| `api/analytics.py:6096-6106` (requested window) | `comp`, `cagr`, `sharpe(rf=0.02)`, `sortino(rf=0.02)`, `calmar`, `omega`, `tail_ratio`, `volatility`, `max_drawdown`, `skew`, `kurtosis` — **11** |
| `api/analytics.py:6141-6147` (full-history leg) | `comp`, `cagr`, `sharpe(rf=0.02)`, `sortino(rf=0.02)`, `calmar`, `volatility`, `max_drawdown` — **7** (5 duplicates + 2 new) |
| `api/analytics.py:6247-6250` (benchmark) | `sharpe(rf=0.02)`, `volatility`, `max_drawdown`, `comp` — **4** |
| `api/analytics.py:6315` (underwater curve) | `to_drawdown_series` — last 250 points |

**Distinct functions used: 12** (`comp`, `cagr`, `sharpe`, `sortino`, `calmar`, `omega`, `tail_ratio`, `volatility`, `max_drawdown`, `skew`, `kurtosis`, `to_drawdown_series`).

**Modules used: 1 of 4.** `qs.stats` only. **`qs.plots` (25 functions), `qs.reports` (5 public), and `qs.utils` (14 public) are used ZERO times in production code.**

**Zero quantstats imports in:** `backtest_service.py`, `benchmark_service.py`, `monte_carlo_service.py`, `regime_service.py`, `analytics_engine.py` (other than the two restatement helpers), `correlation_service.py`, `volatility_service.py`, `tail_risk_service.py`, `cointegration_service.py`, `screener_service.py`, `optimization_service.py`.

### What FinEngine hand-rolls that quantstats already does

| FinEngine location | Hand-rolled | quantstats equivalent | Note |
|---|---|---|---|
| `api/analytics.py:6303` | `(1.0 + port_ret).groupby([port_ret.index.year, port_ret.index.month]).prod() - 1.0` | `qs.stats.monthly_returns(port_ret, eoy=True)` | ⚠️ The weekly variant of this same idiom (`aggregate_returns`) is **broken on pandas 3.0.6 in 0.0.81** — see below. The hand-rolled version is a workaround for a bug FinEngine does not know it has. |
| `api/analytics.py:6263-6267` | `beta = p.cov(b)/b.var()`; `alpha_ann = (p.mean() - beta*b.mean())*252` | `qs.stats.greeks(port_ret, bench)` | Returns `{'alpha','beta'}` |
| `backtest_service.py:188-207` | CAGR, annualised vol, Sharpe, MDD, Calmar over a simulated curve | `qs.reports.metrics(rets, display=False, mode="full")` | **~20 lines → 1 call returning 81 metrics** |
| `analytics_engine.py:1113-1127` | `max_drawdown` restatement with a hand-coded baseline ladder `prices[0] > 1000 → 1e5, > 10 → 100, else 1.0` | n/a — *this is a restatement, not a replacement* | ⚠️ **This exact heuristic was upstream's bug #541, fixed in 0.0.82.** FinEngine faithfully reproduced a defect. |

### Unused capability surface — the highest-value list

**Tier 1 — one call, 67 additional metrics (VERIFIED).**

```python
metrics_df = qs.reports.metrics(returns, benchmark=bench, rf=0.02,
                                mode="full", display=False)
# VERIFIED: pandas.DataFrame, shape (81, 2)
```

FinEngine publishes **12**. `mode="basic"` gives **39** (VERIFIED). The 81 rows, with the 12 FinEngine already has marked ★:

```
Start Period, End Period, Risk-Free Rate, Time in Market, Cumulative Return★,
CAGR★, Sharpe★, Prob. Sharpe Ratio, Smart Sharpe, Sortino★, Smart Sortino,
Sortino/√2, Smart Sortino/√2, Omega★, Max Drawdown★, Max DD Date,
Max DD Period Start, Max DD Period End, Longest DD Days, Volatility (ann.)★,
R^2, Information Ratio, Calmar★, Skew★, Kurtosis★, Ulcer Performance Index,
Risk-Adjusted Return, Risk-Return Ratio, Avg. Return, Avg. Win, Avg. Loss,
Win/Loss Ratio, Profit Ratio, Expected Daily, Expected Monthly, Expected Yearly,
Kelly Criterion, Risk of Ruin, Daily Value-at-Risk, Expected Shortfall (cVaR),
Max Consecutive Wins, Max Consecutive Losses, Gain/Pain Ratio, Gain/Pain (1M),
Payoff Ratio, Profit Factor, Common Sense Ratio, CPC Index, Tail Ratio★,
Outlier Win Ratio, Outlier Loss Ratio, MTD, 3M, 6M, YTD, 1Y, 3Y (ann.),
5Y (ann.), 10Y (ann.), All-time (ann.), Best Day, Worst Day, Best Month,
Worst Month, Best Year, Worst Year, Avg. Drawdown, Avg. Drawdown Days,
Recovery Factor, Ulcer Index, Serenity Index, Avg. Up Month, Avg. Down Month,
Win Days, Win Month, Win Quarter, Win Year, Beta★, Alpha★, Correlation,
Treynor Ratio
```

The `MTD / 3M / 6M / YTD / 1Y / 3Y / 5Y / 10Y / All-time` block alone is a 9-metric period-return table FinEngine does not have, and it is exactly what a frontend "return over period" selector needs.

**Tier 2 — single functions, all VERIFIED working in 0.0.81 on pandas 3.0.6:**

| Function | Sample output | FinEngine value |
|---|---|---|
| `qs.stats.drawdown_details(dd_series)` | DataFrame | Top-5 worst drawdowns with start/end/peak/trough dates — a natural "regime" tab |
| `qs.stats.recovery_factor(r)` | 1.1305 | Return/max-DD; complements the existing MDD |
| `qs.stats.ulcer_index(r)` | 0.3664 | Drawdown *duration×depth*; complements MDD |
| `qs.stats.serenity_index(r)` | -0.0304 | Ulcer-adjusted return |
| `qs.stats.value_at_risk(r)` | -0.0177 | ⚠️ Duplicates `tail_risk_service.py` — **use as a parity check**, not a replacement |
| `qs.stats.conditional_value_at_risk(r)` | -0.02148 | ⚠️ Same; and **be aware** its 0.0.81 estimator is the one fixed in 0.0.83 |
| `qs.stats.probabilistic_sharpe_ratio(r)` | 0.0254 | **Probability the Sharpe exceeds a hurdle** — pairs perfectly with the existing bootstrap bands |
| `qs.stats.probabilistic_sortino_ratio(r)` | 0.0041 | Same for Sortino |
| `qs.stats.greeks(r, bench)["beta"]` | 0.0495 | Replaces hand-rolled beta/alpha |
| `qs.stats.r_squared(r, bench)` | 0.0024 | How much of portfolio variance NIFTY explains |
| `qs.stats.information_ratio(r, bench)` | -0.0607 | Active risk vs NIFTY |
| `qs.stats.treynor_ratio(r, bench)` | -9.7101 | Per-unit-of-beta excess return |
| `qs.stats.compare(r, bench)` | (900, 4) DataFrame | Side-by-side series for a chart |
| `qs.stats.rolling_sharpe(r, rolling_period=252)` | Series | ⚠️ **Watch #549** — pre-0.0.83 subtracts 2× the risk-free rate when `rf != 0` |
| `qs.stats.rolling_volatility(r, 252)` | 0.1697 | Rolling vol band |
| `qs.stats.implied_volatility(r)` | Series | ⚠️ Returns a Series for daily input, not a float — will surprise |
| `qs.plots.monthly_heatmap(r, benchmark=..., active=True)` | matplotlib fig | The monthly table FinEngine hand-rolls, as a chart |
| `qs.plots.snapshot(r)` | 3-panel fig | Cumulative + drawdown + daily returns, one figure |
| `qs.plots.drawdowns_periods(r, periods=5)` | fig | Worst-5 drawdown chart |
| `qs.reports.html(r, benchmark=bench, output=path)` | **844,363-byte HTML** (VERIFIED) | Server-side HTML export alongside `export.ts` |

**Tier 3 — VERIFIED broken or unsuitable in the pinned 0.0.81 (all fixed by 0.0.85):**

| Call | Failure in 0.0.81 | Fixed in |
|---|---|---|
| `qs.utils.aggregate_returns(r, "weekly")` / `(r, "W")` | `AttributeError: 'DatetimeIndex' object has no attribute 'week'` | 0.0.82 (#533) |
| `qs.stats.rar(r, rf=0.05)` | returns `-1.0` (pinned to −100%) | 0.0.85 (#552) |
| `qs.stats.ghpr(r, bench)` | `ValueError: The truth value of a Series is ambiguous` | — |
| `qs.reports.metrics(..., display=True)` | `UnicodeEncodeError` on cp1252 consoles (glyph in `Sortino/√2`) | Not a library bug — use `display=False` |

**Tier 4 — does not exist (the brief guessed these; corrected):**

- ❌ `qs.stats.turnover` — **absent from 0.0.81 and from main/0.0.85.** Neither does any turnover metric. FinEngine's `0.5*Σ|dw|` at `backtest_service.py:118` has no library replacement. (skfolio's `Portfolio.turnover` does, if skfolio is adopted.)
- ❌ `qs.stats.rolling_beta` — it is `qs.plots.rolling_beta`, a plotting function.
- ❌ `qs.reports.metrics` ≠ `qs.stats.*` — [open issue #556](https://github.com/ranaroussi/quantstats/issues/556) reports they disagree on some metrics. FinEngine uses `stats.*` and is unaffected, but do not cross-wire them.

### Is the current usage compatible with the latest version? Is the pin stale?

**The pin is stale by 4 versions and 8 months, and the gap is not cosmetic.**

- Installed: `0.0.81`, uploaded **2026-01-13** (`backend/uv.lock:3062-3064`)
- Latest: `0.0.85`, uploaded **2026-09-26**
- Releases skipped: v0.0.82, v0.0.83, v0.0.84, v0.0.85 — all four on a single day

**Direct impact on FinEngine's 12 published metrics:**

| Metric | Risk on upgrade | Why |
|---|---|---|
| `max_drawdown` | **HIGH** | 0.0.82 (#541) changed the baseline derivation. **FinEngine reimplemented the old baseline heuristic at `analytics_engine.py:1121-1123` and will need rewriting.** |
| `to_drawdown_series` (underwater curve, L6315) | **HIGH** | Same #541/#545 change. Baseline + gap carry-forward. |
| `cagr` | **MEDIUM** | 0.0.82 (#548) fixed a `compounded=False` case turning a >−100% loss positive; 0.0.83 changed period counting to *observed* periods. |
| `sortino` | **MEDIUM** | 0.0.83 counts observed periods. |
| `volatility`, `max_drawdown` | **MEDIUM** | 0.0.83 (#546) stopped zero-filling gaps → higher measured vol, deeper drawdowns, different ratios. **This is more correct**, but it changes published numbers. |
| `sharpe`, `calmar`, `omega`, `tail_ratio`, `comp` | LOW | 0.0.83's gap-handling change applies uniformly |
| `skew`, `kurtosis` | LOW | 0.0.83 corrected probabilistic/statistical estimators (#549, #546, #547, #493) but not these |

**The 9 vectorised restatements in `analytics_engine.py` are the tripwire.** `backend/tests/test_uncertainty_disclosure.py:296` (`test_tear_sheet_ratio_restatements_reproduce_quantstats_exactly`) exists to catch drift, and `.scratch/backend-deep-audit/quant/outputs/verify-portfolio-correlation.txt:119-129` records the current baseline (max abs diff `3.124e-7`, tolerance `5.1e-7`). **That test suite is the instrument for the migration** — and it will very likely fail on `max_drawdown` first.

**Also note:** the two helpers encode assumptions that upstream has now changed:
- `quantstats_returns_look_like_prices()` (L1047-1050) replicates `quantstats.utils._prepare_returns`'s `min >= 0 and max > 1` gate. Still valid (0.0.82 kept the gate), but re-verify.
- `analytics_engine.py:1067-1072` documents that quantstats de-annualises the risk-free rate as `(1+rf)**(1/252) - 1` (compounded, not divided). 0.0.83/0.0.84/0.0.85 swept exactly this bug class across `stats`. The restatement is right; the comment should cite the fix.

### Recommended quantstats actions, ranked

1. **Bump `"quantstats"` → `"quantstats>=0.0.85"`, resync, run the suite.** Highest ROI, zero new deps, and it fixes a verified pandas-3 crash.
2. **Fix `analytics_engine.py:1113-1127`** (`max_drawdown` restatement) to mirror the post-0.0.82 baseline logic, and re-baseline `verify-portfolio-correlation.txt`.
3. **Hoist `import quantstats as qs` out of `get_tear_sheet`** (`analytics.py:6024`) to module scope.
4. **Wrap the `qs.stats.*` block in `anyio.to_thread.run_sync`** — ~21 synchronous CPU calls currently on the event loop.
5. **Rewrite the `methodology` strings** at L3455 and L6408; add `quantstats==<version>` for traceability.
6. **Adopt Tier 1 (`reports.metrics(display=False)`) as an additive block** — 67 more metrics, reusing `_q` for per-metric `None` degradation. Do **not** replace the existing 12.
7. **Delegate** the monthly groupby (L6303) and beta/alpha (L6263-6267) — each needs its own regression test first, and beta/alpha must keep the `MIN_ANNUALIZE_DAYS` gate.
8. **Delegate `backtest_service.py:188-207`** to `reports.metrics(display=False)` — removes ~20 lines of hand-rolled math on a series FinEngine itself produces.
9. **Consider `qs.reports.html` as a server-side HTML export** alongside `export.ts` — not a replacement for the PDF.

---

## backtrader vs backtesting.py head-to-head

Framed for FinEngine's actual need: **validate allocation and rebalancing strategies over Indian equity data in an async FastAPI request, on pandas 3.0.6 / Python 3.12.**

| Dimension | backtrader 1.9.78.123 | backtesting.py 0.6.6 | Winner |
|---|---|---|---|
| **License** | GPL-3.0-or-later | **AGPL-3.0** (network copyleft) | **Neither** — both block |
| **Source disclosure on network use** | No (§13 GPL has no AGPL clause) | **Yes — §13 fires on use** | backtrader (marginally) |
| **Last commit on default branch** | 2023-04-19 (**~3.5 yr**) | 2026-08-05 (~7 wk) | **backtesting.py** |
| **Latest release** | 1.9.78.123, 2023-04-19 | 0.6.6, 2026-07-22 | **backtesting.py** |
| **Open issues / PRs** | 0 issues, **63 PRs**, creation disabled | 86 issues, 11 in 2026 | **backtesting.py** |
| **Status** | **ABANDONED** | ACTIVE (moderate) | **backtesting.py** |
| **py3.12** | ✅ VERIFIED works | ✅ VERIFIED works | tie |
| **pandas 3.0.6** | ✅ VERIFIED works | ⚠️ works, but 0.6.6 **predates** the pandas-3 fix (PR #1410 open) | **backtrader** (by accident) |
| **Declared Python support** | classifiers stop at **3.7**; `requires_python` empty | `>=3.9`, `3 :: Only` | **backtesting.py** |
| **Hard deps** | **ZERO** | `numpy`, `pandas`, **`bokeh`** (new, ~10 transitive) | **backtrader** |
| **Hard deps fit FinEngine's lock** | Perfect (nothing to move) | Needs bokeh | **backtrader** |
| **Multi-asset portfolio rebalancing** | ✅ Native (`adddata` × N, `order_target_percent`, `self.datas`) | ❌ **Impossible** — one `pd.DataFrame`; project states *"does not support multi-asset portfolio rebalancing or arbitrage strategies"* | **backtrader** |
| **Call FinEngine's cvxpy `optimize()`** | ❌ No hook | ❌ No hook | tie (both fail) |
| **Determinism** | Deterministic given fixed inputs; pure-Python loop, no RNG | Deterministic; `optimize()` has `random_state` for the sweep | tie |
| **Speed — vectorized vs event loop** | Both are Python bar loops. backtrader's 900-bar/3-feed run completed in well under a second | Comparable per-instrument | tie |
| **100s of small backtests in a web request** | Multi-asset in one `Cerebro`; 100 strategies = 100 `Cerebro` runs | **100s of separate single-instrument runs — answers the wrong question** | **backtrader** |
| **Testability / determinism of results** | `stdstats=False` silences console output (VERIFIED). Order-matching is inspectable via `strat.orders` | `stats["_trades"]`, `stats["_equity_curve"]` (VERIFIED). But `optimize()` **fails silently** (issue #1333) | **backtrader** |
| **Out-of-box risk analytics** | ⚠️ VERIFIED: `SharpeRatio` → `{'sharperatio': None}`, `Calmar` → **all `NaN`** on 250 bars, silently | Trade stats: profit factor, expectancy, SQN, Sharpe, Sortino, Calmar | backtesting.py |
| **NSE/yfinance data feed** | ❌ No native feed. Workaround: `bt.feeds.PandasData(dataname=yfinance_df)` — **VERIFIED working** | ❌ No feed. Workaround: build an OHLC DataFrame — **VERIFIED working**. NSE tickers (`RELIANCE.NS`) are just index labels | tie (identical workaround) |
| **NSE index benchmark (`^NSEI`)** | ❌ not supported natively; same PandasData workaround | ❌ same | tie |
| **Async fit** | Sync, blocking | Sync, blocking | tie |
| **Indian cost model (STT/stamp/SEBI/GST)** | ❌ symmetric commission only | ❌ symmetric commission only | tie — both need a custom `costs.py` |

### The asymmetry that decides it

Three independent disqualifiers, any one of which is sufficient:

1. **backtrader is GPL-3.0-or-later.** §5(c) forces the entire combined work — FinEngine's whole backend — under GPLv3. Verified in the `LICENSE` and in every source-file header.
2. **backtesting.py is AGPL-3.0.** §13 attaches on *network use*, which is precisely FinEngine's delivery model. Verified in `LICENSE.md`.
3. **backtesting.py cannot do FinEngine's task.** Its own docs exclude multi-asset portfolio rebalancing; `Backtest.__init__` takes one `pd.DataFrame`. Verified by signature and by execution.

And the one that would survive if the licences were fixed — **backtrader wins every architecture row** (multi-asset, `optimize()`-callable via a custom `next()`, zero deps, correct `order_target_percent` semantics) **and loses every maintenance row** (3.5 years dark, 63 untriaged PRs, Python-3.7 classifiers).

**Both also share a fatal gap that has nothing to do with the libraries:** neither can call FinEngine's `optimize(train_window, strategy=...)`. FinEngine's walk-forward is fundamentally *"re-optimize weights with cvxpy every 21 days, then simulate."* A framework that expects you to express your logic as per-bar `self.buy()`/`self.position.close()` calls is the wrong shape. You'd end up reimplementing the inner loop anyway.

## PICK: NEITHER

**Do not adopt either backtester. Keep and extend `backtest_service.run_walk_forward_backtest`.**

**Reasoning, in priority order:**

1. **Both are legally unusable** in a proprietary FastAPI backend — GPL-3.0-or-later for backtrader, AGPL-3.0 §13 for backtesting.py. No architectural merit overrides a licence that forces source disclosure of FinEngine's own code.

2. **FinEngine already has the better tool.** `backtest_service.py:19-237` is a 199-line, vectorized walk-forward portfolio rebalancer that encodes four deliberate, documented Indian-market choices neither library models:
   - **One-way turnover** `0.5*Σ|Δw|` (L115-118), with the comment *"sum|Δw| double-counts (10% A→B reads 0.2 turnover)"* — the numerically correct convention.
   - **Self-financing weight drift** `w[t+1] = w[t](1+r)/(1+w·r)` (L156-158).
   - **An explicitly labelled equal-weight buy-and-hold benchmark** that also drifts, with no rebalance and no costs (L88-89, L228) — so the two curves are economically comparable.
   - **Drawdown from an initial peak of 1.0** (L175), with the comment *"The first out-of-sample loss must be able to create a drawdown immediately."* That is exactly the baseline class of bug that backtrader's `DrawDown` and quantstats 0.0.81's `max_drawdown` each got wrong.
   Plus `STRATEGIES` routing into cvxpy, input validation that fails fast on a bogus strategy, and a per-window optimizer-failure fallback that retains previous weights (L111-113).

3. **backtesting.py is architecturally disqualified for the stated task**, by its own first-party documentation. Adopting it to answer "is my HRP rebalance schedule better than monthly?" would be adopting a tool whose docs say it cannot answer that.

4. **backtrader is the better architecture and a worse bet.** If the licence were permissive it would be the clear choice. GPL-3.0-or-later plus 3.5 years of darkness plus 63 untriaged PRs plus Python-3.7 classifiers means the first pandas-3.0 or security break you hit is yours forever. FinEngine would end up maintaining a GPL fork.

**If a library IS wanted for this need, adopt skfolio's `WalkForward` + `cross_val_predict` instead** — it is multi-asset, BSD-3-Clause, pandas-3.0-targeted, and folds/embargoes are exactly the discipline FinEngine's audits say is missing. Keep the existing inner accounting. See the skfolio implementation guide.

**Where a backtester would genuinely fit FinEngine someday: single-ticker signal screening in `screener_service.py`.** Neither is available (licence), and FinEngine's own gap analysis does not list it as a priority. Revisit only if (a) that need materialises, and (b) a permissively-licensed, multi-asset-capable option exists.

---

## Cross-library comparison

| | **quantstats 0.0.85** | **skfolio 1.4.1** | **backtrader 1.9.78.123** | **backtesting.py 0.6.6** |
|---|---|---|---|---|
| **Verdict** | **ADOPT** (installed) | **ADOPT_PARTIAL** | **AVOID** | **AVOID** |
| **License** | Apache-2.0 | BSD-3-Clause | **GPL-3.0-or-later** | **AGPL-3.0** |
| **SPDX** | `Apache-2.0` | `BSD-3-Clause` | `GPL-3.0` | `AGPL-3.0` |
| **Copyleft** | None | None | **Strong, whole-work (§5(c))** | **Strong + network (§13)** |
| **Proprietary backend OK?** | ✅ Yes | ✅ Yes | ❌ **No — whole work becomes GPLv3** | ❌ **No — source must be offered to remote users** |
| **Status** | ACTIVE (hyper) | ACTIVE (hyper) | **ABANDONED** | ACTIVE (moderate) |
| **Last commit** | 2026-09-26 | 2026-09-26 | **2023-04-19** | 2026-08-05 |
| **Latest release** | 0.0.85 (2026-09-26) | 1.4.1 (2026-09-26) | 1.9.78.123 (2023-04-19) | 0.6.6 (2026-07-22) |
| **Since last release** | hours | hours | **3 yr 5 mo** | ~7 weeks |
| **Open issues** | 5–9 | 18 | **0** (+63 PRs, creation disabled) | 86 |
| **Python** | `>=3.10` (3.10–3.13) | `>=3.10` (3.10–**3.14**) | classifiers to **3.7**; empty `requires_python` | `>=3.9` |
| **py3.12** | ✅ verified | ✅ verified | ✅ verified (undocumented) | ✅ verified |
| **pandas 3.0** | ✅ 0.0.85 (`>=2.0.0`); **0.0.81 has a verified crash** | ✅ **PR #216 closed 2026-08-23** | ✅ verified (undocumented) | ⚠️ works; 0.6.6 predates PR #1410 |
| **numpy 2.x** | ✅ `>=1.24` | ✅ `>=1.24` | ✅ `>=1.17` (no declared dep) | ✅ `>=1.17` |
| **New deps for FinEngine** | **ZERO** | `plotly>=6` (~40 MB) | **ZERO** | `bokeh>=3` (~10 pkgs) |
| **Conflict risk** | **None** | **Low** (cvxpy-base resolves to matching 1.9.3) | **None** | **Low** |
| **Multi-asset portfolio** | ❌ (single return series) | ✅ **native** | ✅ **native** | ❌ **explicitly excluded by its docs** |
| **Optimization** | ❌ | ✅ **11 optimizers + 20+ estimators** | ❌ | ❌ |
| **Risk metrics** | ✅ 84 `stats` functions | ✅ 30+ `measures` | ⚠️ analyzers verified to return `None`/`NaN` | ⚠️ trade stats only |
| **Euler risk contribution** | ❌ | ✅ `Portfolio.contribution()` | ❌ | ❌ |
| **Tearsheet / report** | ✅ `reports.html` (844 KB VERIFIED) | ✅ `Portfolio.summary()` | ⚠️ PyFolio (unmaintained) | ❌ |
| **Walk-forward / CPCV** | ❌ | ✅ `WalkForward`, `CombinatorialPurgedCV` | Manual | ❌ (signal-level) |
| **Can call cvxpy `optimize()`** | ❌ | ❌ | ❌ | ❌ |
| **yfinance/NSE feed** | ✅ `utils.download_returns` | ❌ (pass a DataFrame) | ❌ `PandasData` workaround | ❌ DataFrame workaround |
| **Async fit** | ⚠️ sync, blocking | ⚠️ sync, blocking (joblib for CV) | ⚠️ sync, blocking | ⚠️ sync, blocking |
| **FinEngine usage today** | **12 of 84 `stats` fns; `plots`/`reports`/`utils` = 0** | none | none | none |

---

## Recommended adoption order

Ranked by ROI per unit of risk. Items 1–3 are the whole near-term plan.

### 1. Upgrade `quantstats` 0.0.81 → 0.0.85 — **DO FIRST**
- **Effort:** S. **Risk:** Low-Medium. **ROI: highest in this document.**
- `"quantstats"` → `"quantstats>=0.0.85"` in `backend/pyproject.toml:21`; `uv sync --extra dev --group dev`; run `pytest`.
- Fixes a **verified pandas-3.0 crash** (`aggregate_returns` weekly, bug #533), a **verified −100% `rar()`** (#552), a `ghpr` `ValueError`, and the `rolling_sharpe`/`rolling_sortino` double-rf bug (#549).
- **Expect `test_uncertainty_disclosure.py::test_tear_sheet_ratio_restatements_reproduce_quantstats_exactly` to fail on `max_drawdown` first** — 0.0.82 changed the baseline derivation that `analytics_engine.py:1113-1127` hard-codes. That is the work item, not a blocker.
- Zero new dependencies. Cannot break the lockfile.

### 2. Repair the `max_drawdown` restatement + re-baseline
- **Effort:** M. **Risk:** Medium. **ROI: high — it is the correctness proof for the upgrade.**
- Rewrite `analytics_engine.py:1113-1127` to mirror post-0.0.82 logic (baseline from *how* the series was built, not a magnitude ladder).
- Re-baseline `.scratch/backend-deep-audit/quant/outputs/verify-portfolio-correlation.txt:127` (currently max abs diff `3.124e-7`).
- Then re-run the full `verify-portfolio-correlation` + `verify-risk-timeseries` harnesses — they are the project's own quantstats oracle and will catch any other drift.

### 3. Fix the tear-sheet's event-loop blocking + import hygiene
- **Effort:** S. **Risk:** Low. **ROI: high — responsiveness, not features.**
- Hoist `import quantstats as qs` from `analytics.py:6024` to module scope (recorded twice as "skipped" in FinEngine's own audits).
- Wrap the L6096-6250 `qs.stats.*` block in `anyio.to_thread.run_sync` — ~21 synchronous CPU calls per request today.
- Rewrite the two `methodology` strings (L3455, L6408) to name a method and pin `quantstats==<version>`.

### 4. Adopt `qs.reports.metrics(display=False)` — 67 new metrics
- **Effort:** M. **Risk:** Low. **ROI: high — the single largest capability gain available.**
- Verified: `mode="full"` → DataFrame `(81, 2)`; `mode="basic"` → `(39, 2)`. FinEngine publishes 12.
- Reuse the existing `_q` guard so each metric degrades to `None` independently — **do not** replace the existing block, and **do not** cross-wire with `qs.stats.*` (open issue #556).
- Additive only, with its own regression test.
- **Gotcha:** never `display=True` on Windows (cp1252 `UnicodeEncodeError` on the `√` glyphs).

### 5. Pilot skfolio behind `optimize()` — **one strategy, shadow mode**
- **Effort:** M. **Risk:** Low if shadowed. **ROI: high but not urgent.**
- `"skfolio>=1.4,<2"` (a `<2` bound **is** warranted here — post-1.0 with daily releases and observed intra-minor API moves). Costs `plotly` (~40 MB).
- Write the parity test **first**, against `min_cvar` (best parity: both Rockafellar-Uryasev). Add `optimize(..., backend="cvxpy")` defaulting to today. Publish the weight delta per rebalance event.
- `backtest_service.py` stays untouched. `hrp` stays on the hand-rolled path permanently — skfolio's distance default is not FinEngine's linkage choice.
- Only after the delta is stable for a release: flip `min_cvar`.

### 6. Delegate FinEngine's duplicate math to what it already has
- **Effort:** S each. **Risk:** Low. **ROI: medium.**
- `analytics.py:6303` monthly groupby → `qs.stats.monthly_returns`
- `analytics.py:6263-6267` beta/alpha → `qs.stats.greeks` (**keep the `MIN_ANNUALIZE_DAYS` gate at L6254-6256** — that gate is a lookahead defence)
- `backtest_service.py:188-207` → `qs.reports.metrics(display=False)` (removes ~20 hand-rolled lines)
- Each needs its own regression test *before* the swap.

### 7. skfolio: add capabilities FinEngine does not have
- **Effort:** M each. **Risk:** Low. **ROI: medium — deferred.**
- **Euler risk contribution** via `Portfolio.contribution()` — already on FinEngine's roadmap as pending.
- `CombinatorialPurgedCV` for fold/embargo discipline inside `backtest_service` — **set `purged_size`/`embargo_size` explicitly; the defaults are `0`.**
- `DenoiseCovariance` / `OAS` / `ShrunkMu`; `RiskBudgeting`; `EffectiveNumberAssets` as an HHI cross-check.
- Additive, behind flags. Do not disturb `analytics_engine.py`.

### 8. `qs.reports.html` as a server-side HTML export
- **Effort:** M. **Risk:** Low. **ROI: low-medium — a nice-to-have.**
- **Alongside** `export.ts`, never instead. Verified 844 KB output. Needs `matplotlib.use("Agg")` before first import and `to_thread` (seconds of GIL-holding work + disk write per call).

### 9. Reconsider nothing on the backtester track
- **Effort:** 0. **Risk:** 0. **ROI: n/a.**
- The licence blockers are permanent. Close the question.

---

## What NOT to adopt, and why

### Do NOT adopt **backtesting.py** — AVOID
1. **AGPL-3.0 §13 is dispositive.** FinEngine is a network server. §13 attaches on *use*, not distribution, and obliges FinEngine to "prominently offer all users interacting with it remotely through a computer network … an opportunity to receive the Corresponding Source of your version." The "internal use only" argument that works for the GPL was written shut by the AGPL.
2. **Its own docs exclude FinEngine's use case** — *"It does not support multi-asset portfolio rebalancing or arbitrage strategies."* `Backtest.__init__` takes one `pd.DataFrame`. VERIFIED.
3. **It cannot call FinEngine's cvxpy `optimize()`**, which is the whole point of the walk-forward.
4. **`bokeh` (~10 packages) added purely for `plot()`** — a chart FinEngine renders in Next.js.
5. **0.6.6 predates the pandas-3 fixes** (PR #1410 open) and has live silent-failure issues (#1333 `optimize()` errors with no info; #1339 NA-indicator bars silently skipped).
6. **Tempting and wrong:** "it only runs a few metrics on my server, nothing is distributed, so AGPL doesn't apply." That is precisely the reading §13 exists to defeat. **UNVERIFIED against counsel — get a legal opinion before relying on any interpretation.**

### Do NOT adopt **backtrader** — AVOID
1. **GPL-3.0-or-later §5(c) is dispositive.** *"You must license the entire work, as a whole, under this License."* Python `import backtrader` is a linked dependency, not mere aggregation — there is no CPython equivalent of the JVM classpath carve-out. FinEngine's entire backend would have to be released under GPLv3.
2. **ABANDONED — 3.5 years.** Last commit on `master` 2023-04-19; last substantive maintainer code commit **2021-07-17**; 0 open issues with **creation disabled**; **63 untriaged open PRs**. No pandas-3 or security fix will ever arrive.
3. **README is wrong about modern Python** — claims 3.2+, classifiers stop at 3.7, `requires_python` is empty. It works on 3.12 + pandas 3.0.6 (VERIFIED) only because it declares zero dependencies. That is luck, not support.
4. **Its analyzers silently return `None`/`NaN`** — VERIFIED: `SharpeRatio` → `{'sharperatio': None}`, `Calmar` → 12 all-`NaN` values on 250 bars, no exception. Unacceptable in a platform that publishes precision intervals.
5. **Forks are not a workaround.** `backtrader2`/`bt` carry their own licences; verify each independently; none inherits upstream maintenance.
6. **Context7's `_autodocs/` tree is unreliable** — documents `analyzers[0].get_analysis()` and `_riskfreerate=`, both wrong for 1.9.78.123. Use it with suspicion.

### Do NOT replace `backtest_service.run_walk_forward_backtest`
- 199 lines, vectorized, deterministic, with four deliberate Indian-market behaviours neither library models: one-way turnover `0.5*Σ|Δw|`, self-financing weight drift, a cost-free drifting equal-weight buy-and-hold benchmark, and a drawdown baseline that includes the initial peak of 1.0.
- It already routes into cvxpy `optimize()` with `STRATEGIES` — which is precisely what neither backtester can do.
- FinEngine's own audit history (`.scratch/`, `verify-portfolio-correlation.txt`, `test_uncertainty_disclosure.py`) shows the codebase has invested heavily in proving this code's math. Replacing it with a slower, less transparent, legally unusable framework is a large regression for zero gain.
- **The right move is to add skfolio's fold/embargo discipline *around* it, never to swap it out.**

### Do NOT delete `quantstats_ratio_statistics()` as "duplicated quantstats"
- It looks like 100 lines reimplementing `qs.stats.*`. It is the opposite: it is a **vectorised restatement over `(n, draws, k)` blocks** that `measure_estimate_uncertainty` uses to *verify the bootstrap is resampling the same statistic it published* (documented at `analytics_engine.py:1053-1065`). quantstats' `stats` functions are scalar-only and cannot be vectorised over resampling draws.
- Deleting it removes the guarantee that FinEngine never attaches a confidence band to a neighbouring statistic — the core of its SI-5 estimator-uncertainty disclosure.
- `.scratch/v5-review/05-adversarial.md:227` documents a *live* instance of exactly this class of defect (two near-identical Sharpes, `3.487604` vs `3.485603`, published side by side with no reconciliation). The restatements are the defence against it. Keep them, and keep them tested.

### Do NOT replace the 12-metric `_q` block with `qs.reports.metrics`
- `_q` (L498-510) degrades **each metric independently** to `None`; `reports.metrics` is all-or-nothing. FinEngine's P1 fix at `.scratch/backend-audit/00-INDEX.md:42` exists specifically because one NaN used to 500 the whole tear-sheet.
- `reports.metrics` and `stats.*` **disagree** on some metrics — [open issue #556](https://github.com/ranaroussi/quantstats/issues/556), filed 2026-09-27.
- Use `reports.metrics(display=False)` **additively** for the 67 unexposed metrics, reusing `_q` per row. Never as a replacement.

### Do NOT add `qs.stats.turnover` as a dependency assumption
- **It does not exist** — not in 0.0.81, not in 0.0.85/main. VERIFIED by enumerating every public name in both.
- FinEngine's turnover (`backtest_service.py:118`, `portfolio.py:2107`) is correct and hand-rolled. Leave it. If skfolio is adopted, `Portfolio.turnover` is the library answer.

### Do NOT add `skfolio` cardinality / threshold constraints
- `MeanRisk(cardinality=, threshold_long=, threshold_short=)` requires SCIP, GUROBI, or MOSEK. FinEngine has only Clarabel. Ship long-only + budget constraints only, and document the limit.

### Do NOT chase quantstats' matplotlib/seaborn plotting stack
- `matplotlib` 3.11.2 and `seaborn` 0.13.2 are already installed *because* quantstats pulls them, and they account for a large share of FinEngine's cold-start time and image size — for a library FinEngine uses **zero** of whose 25 `qs.plots` functions.
- Adopting `qs.plots.monthly_heatmap` (Tier 2) would deepen that dependency for a chart the frontend already renders better. **Prefer returning data** from the `reports.metrics`/statistics path and letting Next.js draw it. Revisit only if a genuinely quantstats-only chart is wanted — and even then, set `matplotlib.use("Agg")`.

---

## Source inventory

**GitHub API / releases / commits / tags / search:** `ranaroussi/quantstats`, `skfolio/skfolio`, `mementum/backtrader`, `kernc/backtesting.py`
**Licences (authoritative):** [quantstats LICENSE.txt](https://github.com/ranaroussi/quantstats/blob/main/LICENSE.txt) · [quantstats pyproject.toml](https://github.com/ranaroussi/quantstats/blob/main/pyproject.toml) · [backtrader LICENSE](https://github.com/mementum/backtrader/blob/master/LICENSE) · [backtrader setup.py](https://github.com/mementum/backtrader/blob/master/setup.py) · [backtesting.py LICENSE.md](https://github.com/kernc/backtesting.py/blob/master/LICENSE.md) · skfolio licence via PyPI `license` field
**PyPI metadata:** [quantstats](https://pypi.org/project/quantstats/) · [skfolio](https://pypi.org/project/skfolio/) · [backtrader](https://pypi.org/project/backtrader/) · [backtesting](https://pypi.org/project/backtesting/)
**Official docs:** [skfolio.org](https://skfolio.org) · [skfolio API ref](https://skfolio.org/api.html) · [backtesting.py docs](https://kernc.github.io/backtesting.py/doc/backtesting/) · [backtrader README](https://github.com/mementum/backtrader/blob/master/README.rst)
**Context7:** `/ranaroussi/quantstats` (benchmark 81.21) · `/skfolio/skfolio` (79.26) · `/mementum/backtrader` (77.6) · `/kernc/backtesting.py` (83.47)
**Empirical verification:** throwaway venvs at `%LOCALAPPDATA%\Temp\opencode\libcheck\{v1,v2,v3}` — backtrader 1.9.78.123 on py3.12.9/pandas 3.0.6/numpy 2.5.3; backtesting 0.6.6 on the same; skfolio 1.4.1 on py3.12.9/pandas 3.0.6/numpy 2.5.3/cvxpy 1.9.3/clarabel 0.11.1/scikit-learn 1.9.1; quantstats 0.0.81 probes inside FinEngine's own `uv` venv.
**FinEngine sources read:** `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/api/analytics.py` (L490-630, L6010-6420), `backend/app/services/analytics_engine.py` (L1030-1154), `backend/app/services/backtest_service.py` (full), `backend/app/services/benchmark_service.py`, `backend/app/services/optimization_service.py`, `backend/tests/test_uncertainty_disclosure.py`, `frontend/src/lib/export.ts`, `frontend/src/lib/api.ts`, `frontend/src/components/layout/Sidebar.tsx`, plus `.scratch/backend-deep-audit/**`, `.scratch/backend-audit-2026/**`, `.scratch/v5-review/**`.

**No FinEngine source code was modified by this review.**

## Unverified — needs manual check

1. **Licence conclusions are a technical reading, not legal advice.** The AGPL §13 and GPL §5(c) analyses should be confirmed by counsel before any commercial deployment decision. This is the single highest-stakes item in this document.
2. **backtesting.py commercial licensing** — the author is understood to sell commercial AGPL licences, but the terms, scope, and whether they cover a SaaS deployment are **UNVERIFIED**. Requires direct contact.
3. **backtrader's `pandas>=2.0` breakage** — the widely-repeated claim that backtrader is broken on modern pandas is **NOT** confirmed and appears **false** for the paths I tested. Given §5(c) it is moot, but the claim should not be repeated as fact.
4. **skfolio API stability at 1.4.x** — three releases in 48 h and observed intra-minor API moves (`get_measures` relocated, `predict()` gained a required argument). The `<2` pin is mitigation, not a guarantee. Re-verify at pin-bump time.
5. **quantstats 0.0.85's final state.** 0.0.84 reverted part of 0.0.83 in the same day; 0.0.85 fixed half of #552 that 0.0.84 missed. This is a fast-moving release line. Run the full regression suite on any bump, and consider a short `>=0.0.85,<0.0.86` trial pin before relaxing to `>=0.0.85`.
