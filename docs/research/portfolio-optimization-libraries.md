# Portfolio Optimisation Libraries — Evaluation for FinEngine

**Research date:** 2026-09-27
**Scope:** FinQuant, PyPortfolioOpt, Riskfolio-Lib — for a FastAPI 3.12 + Next.js institutional risk
analytics platform pinned to `pandas 3.0.6`, `numpy 2.5.3`, `scipy 1.18`, `cvxpy 1.9.3`.

**Method note (important):** every compatibility claim below was **empirically verified**, not inferred
from metadata. Each library was installed into a throwaway `uv` environment pinned to FinEngine's
exact versions and exercised through a real portfolio-optimization workflow. Raw measurements are
reproduced inline. Licensing facts come from the repositories' `LICENSE` files; maintenance facts
from the GitHub REST API and PyPI JSON API, observed **2026-09-27**.

---

## PyPortfolioOpt

> **ADOPT_PARTIAL** — the only library here that actually runs on FinEngine's pandas 3.0.6 / numpy 2.5.3
> stack today, MIT-licensed, still actively maintained, and it fills the single biggest methodological
> hole in FinEngine (no covariance shrinkage anywhere). One hard blocker (HRP on scipy 1.18) and one
> silent breaking API change in 1.6.0 must be handled.

### Verdict

**ADOPT_PARTIAL.**

Adopt the covariance-shrinkage, downside-risk-frontier, regularisation/turnover and discrete-allocation
surfaces immediately. Do **not** adopt `HRPOpt` — it is broken on FinEngine's pinned scipy 1.18, and FinEngine's
own hand-rolled `_hrp_weights()` in `optimization_service.py` currently works better than the library's version,
so there is no reason to swap it. The 1.6.0 change of `portfolio_performance()` from dict to tuple is a silent
breaking change that will not fail at import time, so it must be pinned deliberately.

### License

- **Exact license:** MIT License
- **SPDX identifier:** `MIT` (confirmed via GitHub API `license.spdx_id` and PyPI classifier
  `License :: OSI Approved :: MIT License`)
- **Source:** https://github.com/PyPortfolio/PyPortfolioOpt/blob/main/LICENSE

Clause (the only operative obligation):

> "The above copyright notice and this permission notice shall be included in all copies or substantial
> portions of the Software."

and the grant:

> "Permission is hereby granted, free of charge, to any person obtaining a copy of this software … to deal
> in the Software without restriction, including without limitation the rights to use, copy, modify, merge,
> publish, distribute, sublicense, and/or sell copies of the Software"

- **Commercial use:** explicitly permitted (`and/or sell copies`). No revenue share, no CLA, no
  non-commercial rider. Safe for a commercial institutional product.
- **Copyleft:** none. **Not** GPL/LGPL. No source-disclosure obligation.
- **Linking vs vendoring:**
  - *As a PyPI dependency (recommended):* no action required. The MIT notice obligation attaches to
    redistribution of the software itself, not to your use of it. Standard practice is to keep the
    notice in a `THIRD_PARTY_NOTICES.md` — good hygiene, and required if you ever ship a frozen/embedded copy.
  - *Vendoring code into FinEngine:* you **must** include the copyright line `Copyright (c) 2018 Robert
    Andrew Martin` plus the full MIT text in your repo.
  - *Subprocessing / SaaS:* no obligation at all. Serving results from a FastAPI backend is use, not redistribution.
- **Not a business-source / non-commercial license.** No legal review needed beyond notice retention.

### Maintenance

**Activity: ACTIVE** (with a caveat — see below).

| Fact | Value | Source |
|---|---|---|
| Latest release | **1.6.0**, published **2026-02-26** | https://pypi.org/pypi/pyportfolioopt/json · https://github.com/PyPortfolio/PyPortfolioOpt/releases/tag/v1.6.0 |
| Last commit on `main` | **2026-07-07** (`[DOC] fix outdated links and badges in README (#735)`) | GitHub API `repos/PyPortfolio/PyPortfolioOpt/commits` |
| Prior commits | 2026-03-10, 2026-03-08 (×2), 2026-02-27 | same |
| `pushed_at` | 2026-07-07T21:18:14Z | GitHub API repo object |
| Open issues | **84** | GitHub search API `is:issue is:open` |
| Open PRs | **32** | GitHub search API `is:pr is:open` |
| Archived | `false` | GitHub API repo object |
| Stars | 6,056 | GitHub API |
| CI matrix | `os: [ubuntu, macos, windows]` × `python-version: ["3.10","3.11","3.12","3.13","3.14"]`, two jobs (`nosoftdeps` + with soft deps) | https://github.com/PyPortfolio/PyPortfolioOpt/blob/main/.github/workflows/main.yml |
| Citation | JOSS paper: Martin, R. A. (2021), *JOSS* 6(61), 3066, doi:10.21105/joss.03066 | repo README |

**Caveat worth noting:** the 1.6.0 release was cut by user `fkiraly`, not the original author
(`robertmartin8`). The project moved to the `PyPortfolio` GitHub org and 1.5.x → 1.6.0 is a large
maintenance-driven release (packaging moved to `pyproject.toml`, linting to `ruff`, CI to `uv`, module
layout reorganisation). Release cadence is slow — v1.4.1 shipped 2021-05-06, v1.6.0 shipped 2026-02-26 —
but the maintainer is responsive. The 32 open PRs and 84 open issues indicate an active-but-bottlenecked
project, not a healthy one. Treat as **ACTIVE with moderate bus factor**.

**Note on issue-tracker cross-references:** I could not enumerate individual upstream issues for the
scipy breakage below, because the unauthenticated GitHub REST API rate limit (60 req/h) was exhausted
during research and GitHub's HTML search requires JavaScript. **UNVERIFIED — needs manual check** whether
an upstream issue or PR already exists for the `scipy 1.18` / `HRPOpt` failure. The reproduction below is
first-hand and does not depend on that.

### Compatibility

| Dimension | Status | Evidence |
|---|---|---|
| Python 3.12 | ✅ Supported | `requires-python = ">=3.10,<3.15"`; classifier `Programming Language :: Python :: 3.12`; CI matrix includes 3.12. Ran on 3.12.9. |
| Python 3.14 | ✅ Supported | Added in 1.6.0: *"Support for python 3.14, end-of-life for python 3.8 and 3.9"* |
| **pandas 3.0** | ✅ **Explicitly supported** | v1.6.0 release notes: *"Support for `pandas 3.0`"* via [PR #703](https://github.com/PyPortfolio/PyPortfolioOpt/pull/703). Metadata bound is `pandas>=1.0.0,<4.0.0` — pandas 3 is inside the range. **Verified running** (full workflow below). |
| **numpy 2.x** | ✅ Supported | `numpy>=1.26.0,<3.0.0`. **Verified running** on numpy 2.5.3. |
| scipy 1.18 | ⚠️ **Partial — one hard blocker** | See below. |
| quantlib coexistence | ✅ No conflict | quantlib 1.43 is a self-contained compiled extension with **no `requires_dist`** on PyPI; no shared symbol or dtype contract with pypfopt. No import interaction. |
| cvxpy coexistence | ✅ Same solver stack | pypfopt needs `cvxpy>=1.1.19`; FinEngine already has 1.9.3 with Clarabel/ECOS/OSQP/HiGHS/SCS. pypfopt will reuse the **already-installed** cvxpy — no new solver binaries. |

#### 🛑 BLOCKER 1 — `HRPOpt` is broken on scipy 1.18 (FinEngine's pin)

`pypfopt/hierarchical_portfolio.py:152` reads:

```python
if linkage_method not in sch._LINKAGE_METHODS:
```

`scipy.cluster.hierarchy._LINKAGE_METHODS` is a **private** SciPy attribute. SciPy removed it in
**1.18.0**. Reproduced by bisecting the SciPy attribute across seven versions:

| scipy | `_LINKAGE_METHODS` present? |
|---|---|
| 1.11.4 | ✅ True |
| 1.13.1 | ✅ True |
| 1.14.1 | ✅ True |
| 1.15.3 | ✅ True |
| 1.16.3 | ✅ True |
| 1.17.0 | ✅ True |
| **1.18.0** | ❌ **False** |

Result on FinEngine's exact stack (`scipy==1.18.0`, pandas 3.0.6, numpy 2.5.3, py3.12):

```
AttributeError: module 'scipy.cluster.hierarchy' has no attribute '_LINKAGE_METHODS'
```

**Every** `HRPOpt(...).optimize()` call raises. The one-line upstream fix is trivial (validate against
`scipy.cluster.hierarchy` public linkage names, or delete the check and let SciPy raise). But you should
not depend on an unpatched release. See "What NOT to adopt".

#### ⚠️ BREAKING CHANGE 2 — `portfolio_performance()` returns a tuple in 1.6.0 (was a dict)

Verified at runtime and confirmed against the official docs via Context7
(`/pyportfolio/pyportfolioopt`, docstring `Returns` section: *"Returns a tuple (expected annual return,
annual volatility, Sharpe ratio)"*). The repo README uses tuple unpacking:

```python
exp_return, volatility, sharpe = ef.portfolio_performance(verbose=True)
```

Measured on FinEngine's stack:

```
portfolio_performance type=tuple value=(0.1979, 0.1198, 1.1094)
  dict-style access: BREAKS (v1.6.0 returns tuple, <=1.5.x returned dict)
  -> TypeError: tuple indices must be integers or slices, not str
```

`BaseConvexOptimizer.portfolio_performance` is also a static method you can call directly:

```python
from pypfopt.base_optimizer import BaseConvexOptimizer
BaseConvexOptimizer.portfolio_performance(weights, expected_returns, cov_matrix, verbose, risk_free_rate)
```

This is a **silent** break: it will pass review, pass type hints loosely, and only fail at runtime on a
`.items()` or `["sharpe_ratio"]` access. Any FinEngine wrapper must unpack a tuple.

#### Other observations

- `risk_models.min_cov_determinant()` still ships in 1.6.0 but emits
  `UserWarning: min_cov_determinant is deprecated and will be removed in v1.5` — the warning text is stale
  (it names a version already passed). Do not use.
- `max_sharpe()` emits `UserWarning: max_sharpe transforms the optimization problem so additional
  objectives may not work as expected` when you also call `add_objective()`. Design consequence: use
  `min_volatility()`/`efficient_return()`/`efficient_risk()` when you want regularisation or turnover
  penalties to actually bind.
- `pyproject.toml` core deps are deliberately minimal: *"this set should be kept minimal!"*

### Dependency footprint

**Core (`[project].dependencies`)** — https://github.com/PyPortfolio/PyPortfolioOpt/blob/main/pyproject.toml

```
cvxpy>=1.1.19
numpy>=1.26.0,<3.0.0
pandas>=1.0.0,<4.0.0
scikit-base<0.14.0
scikit-learn>=0.24.1
scipy>=1.3.0
```

**Optional `all_extras`:** `matplotlib>=3.2.0`, `ecos>=2.0.14,<2.1`, `plotly>=5.0.0,<7`,
`cvxopt; python_version < '3.14'`

**Transitive bloat: essentially zero new packages.** This is the standout advantage. Everything is
already in FinEngine's tree except one:

| Package | New to FinEngine? | Assessment |
|---|---|---|
| `cvxpy` | already installed (1.9.3) | Reused, no change |
| `numpy` / `pandas` / `scipy` / `scikit-learn` | already installed | Reused |
| `matplotlib` | already installed | Reused |
| **`scikit-base`** | **YES — 1 new package** | See below |
| `ecos` (only via `all_extras`) | already installed via cvxpy | pypfopt pins `>=2.0.14,<2.1`; PyPI latest is **2.0.14** → satisfied, no change |
| `plotly` (only via `all_extras`) | YES if you install extras | Do **not** install `all_extras`; you already have matplotlib and don't render pypfopt plots in the backend |

**`scikit-base` risk assessment:** version **1.2.0**, `requires-python <3.16,>=3.10`, **BSD-3-Clause**,
pure-Python, and its own `requires_dist` contains **no unconditional runtime dependencies** (`numpy` and
`pandas` appear only under the `all-extras` extra; `scikit-learn` only under `dev`). Because it is
pure-Python it carries no compiled ABI and therefore no numpy/pandas version coupling. **Low risk.**
It exists so pypfopt can run `check_estimator`-style validation (PR #674, "Isolate `scikit-learn`
dependency with checks") and so pypfopt classes can participate in the scikit-learn estimator ecosystem.

**Conflict risk with FinEngine's pin set: essentially none.** It is the *only* one of the three
libraries whose dependency closure does not add compiled extensions or heavy transitive trees.

### API surface

Verified signatures read from source on `main` (post-1.6.0 layout) and cross-checked against Context7
(`/pyportfolio/pyportfolioopt`).

```python
import pypfopt
from pypfopt import (
    EfficientFrontier, EfficientSemivariance, EfficientCVaR, EfficientCDaR,
    HRPOpt, BlackLittermanModel, CLA, CovarianceShrinkage,
    DiscreteAllocation, get_latest_prices,
    market_implied_prior_returns, market_implied_risk_aversion,
)
from pypfopt import risk_models, expected_returns, objective_functions
from pypfopt.base_optimizer import BaseOptimizer, BaseConvexOptimizer
```

> Note the 1.6.0 module reorganisation. These paths are **new**: `pypfopt.black_litterman` (was
> `black_litterman_model`), `pypfopt.hierarchical_portfolio` (was `hrpopt`), `pypfopt.cla` (was
> `efficient_frontier/cla.py`), `pypfopt.base` (new home of `BaseConvexOptimizer`). Thin
> `pypfopt.base_optimizer` / `pypfopt.efficient_frontier` shims re-export the old names, so old
> `from pypfopt.efficient_frontier import EfficientFrontier` code keeps working.

**Top API surface:**

| Class / function | Signature | Solves |
|---|---|---|
| `EfficientFrontier` | `EfficientFrontier(expected_returns, cov_matrix, weight_bounds=(0,1), solver=None, verbose=False, solver_options=None)` | Convex mean-variance problem |
| ↳ `.min_volatility()` | → weights | Global minimum-variance portfolio |
| ↳ `.max_sharpe(risk_free_rate=0.0)` | → weights | Tangency (max-Sharpe) portfolio |
| ↳ `.efficient_return(target_return, market_neutral=False)` | → weights | Min vol for a target return |
| ↳ `.efficient_risk(target_volatility, market_neutral=False)` | → weights | Max Sharpe for a target vol |
| ↳ `.max_quadratic_utility(risk_aversion=1, market_neutral=False)` | → weights | Mean-variance utility |
| ↳ `.portfolio_performance(verbose=False, risk_free_rate=0.0)` | → **tuple** `(exp_ret, vol, sharpe)` | ⚠️ tuple in 1.6.0, was dict |
| ↳ `.clean_weights(cutoff=1e-4, rounding=5)` | → `OrderedDict` | Drop dust weights |
| ↳ `.save_weights_to_file(filename="weights.csv")` | → None | Export |
| `EfficientCVaR` | `EfficientCVaR(expected_returns, returns, beta=0.95, weight_bounds=(0,1), ...)`; `.min_cvar()`, `.efficient_risk(target_cvar)` | CVaR-minimising frontier (Rockafellar-Uryasev LP) |
| `EfficientSemivariance` | `EfficientSemivariance(expected_returns, returns, frequency=252, benchmark=0, ...)`; `.min_semivariance()` | Downside-risk frontier |
| `EfficientCDaR` | `EfficientCDaR(expected_returns, returns, beta=0.95, ...)`; `.min_cdar()` | Conditional drawdown-at-risk frontier |
| `HRPOpt` | `HRPOpt(returns=None, cov_matrix=None)`; `.optimize(linkage_method="single")` | López de Prado HRP — **⚠️ broken on scipy ≥1.18** |
| `BlackLittermanModel` | `BlackLittermanModel(cov_matrix, pi=None, absolute_views=None, Q=None, P=None, omega=None, view_confidences=None, tau=0.05, risk_aversion=1.0, method="market_implied_prior")`; `.bl_returns()`, `.bl_cov()`, `.bl_weights(risk_aversion=None)`, `.optimize()` | Bayesian expected-return blending |
| ↳ `market_implied_prior_returns(market_caps, risk_aversion, cov_matrix, risk_free_rate=0.0)` | | Reverse-optimised equilibrium returns |
| ↳ `market_implied_risk_aversion(market_prices, frequency=252, risk_free_rate=0.0)` | | Estimate δ from index data |
| `risk_models.sample_cov` | `sample_cov(prices, returns_data=False, frequency=252, log_returns=False, **kwargs)` | Unbiased sample covariance |
| `risk_models.exp_cov` | `exp_cov(prices, returns_data=False, span=180, frequency=252, log_returns=False)` | EWMA covariance |
| `risk_models.semicovariance` | `semicovariance(prices, returns_data=False, benchmark=0.000079, frequency=252, log_returns=False)` | Downside covariance |
| `risk_models.CovarianceShrinkage` | `.ledoit_wolf(shrinkage_target="constant_variance")`, `.oracle_approximating()`, `.shrunk_covariance(delta=0.2)` | **Ledoit–Wolf** shrinkage (3 targets: `constant_variance`, `single_factor`, `constant_correlation`) and **Oracle Approximating Shrinkage** (Chen et al. 2010) |
| `risk_models.fix_nonpositive_semidefinite` | `fix_nonpositive_semidefinite(matrix, fix_method="spectral")` | Repair non-PSD covariance |
| `expected_returns.mean_historical_return` | `(prices, returns_data=False, compounding=True, frequency=252, log_returns=False)` | Arithmetic/geometric mean return |
| `expected_returns.ema_historical_return` | `(prices, returns_data=False, compounding=True, span=500, frequency=252, log_returns=False)` | Recency-weighted mean |
| `expected_returns.capm_return` | `(prices, market_prices=None, returns_data=False, risk_free_rate=0.0, compounding=True, frequency=252, log_returns=False)` | CAPM / beta-implied returns |
| `objective_functions.L2_reg` | `L2_reg(w, gamma=1)` | Zero-weight penalty |
| `objective_functions.transaction_cost` | `transaction_cost(w, w_prev, k=0.001)` | Turnover penalty |
| `objective_functions.ex_ante_tracking_error` | `ex_ante_tracking_error(w, cov_matrix, benchmark_weights)` | Benchmark-relative risk |
| `objective_functions.ex_post_tracking_error` | `ex_post_tracking_error(w, historic_returns, benchmark_returns)` | Realised tracking error |
| `DiscreteAllocation` | `DiscreteAllocation(weights, latest_prices, total_portfolio_value=10000, short_ratio=None)`; `.greedy_portfolio(reinvest=False)`, `.lp_portfolio(reinvest=False, solver=None)` | Continuous weights → whole shares |
| `BaseConvexOptimizer` | `.add_objective(new_objective, **kwargs)`, `.add_constraint(new_constraint)`, `.add_sector_constraints(sector_mapper, sector_lower, sector_upper)`, `.convex_objective(...)`, `.nonconvex_objective(..., solver="SLSQP")` | Compose custom problems |

**Verified end-to-end run on FinEngine's exact stack** (6 assets × 750 business days, synthetic):

```
python 3.12.9 | pandas 3.0.6 | numpy 2.5.3
pypfopt 1.6.0
mu/S ok  0.008s  mu dtype=float64
max_sharpe weights sum=1.0000000000  n_nonzero=4
portfolio_performance type=tuple value=(0.1979, 0.1198, 1.1094)
  exp_cov        ok  0.017s shape=(6, 6)
  semicovariance ok  0.004s shape=(6, 6)
  ledoit_wolf    ok  7.005s shape=(6, 6)      <-- see performance note
  oracle_approx  ok  0.015s shape=(6, 6)
  min_cov_det    ok  1.625s shape=(6, 6)      <-- DEPRECATED
  ema_hist_ret   ok  0.004s shape=(6,)
L2_reg n_nonzero = 4
bounds+sector sum=1.000000
  EfficientCVaR          ok  0.046s sum=1.000000
  EfficientSemivariance  ok  0.033s sum=1.000000
  EfficientCDaR          ok  0.059s sum=1.000000
```

```python
# Real, working usage on FinEngine's stack
import pandas as pd, numpy as np
from pypfopt import EfficientFrontier, EfficientCVaR, risk_models, expected_returns, objective_functions
from pypfopt.discrete_allocation import DiscreteAllocation, get_latest_prices

# `prices` = yfinance OHLCV pivoted to one float column per NSE/BSE ticker
mu = expected_returns.mean_historical_return(prices)              # or .capm_return(prices)
S  = risk_models.CovarianceShrinkage(prices).ledoit_wolf()        # Ledoit-Wolf shrinkage
S  = risk_models.fix_nonpositive_semidefinite(S)                  # guard for NSE near-singularity

ef = EfficientFrontier(mu, S, weight_bounds=(0, 0.15))            # 15% max position (SEBI-style cap)
ef.add_objective(objective_functions.L2_reg, gamma=0.5)           # reduce zero-weight names
ef.add_constraint(lambda w: w[mu.index.get_loc("RELIANCE.NS")] + w[mu.index.get_loc("HDFCBANK.NS")] <= 0.20)
w = ef.max_sharpe(risk_free_rate=0.065)                           # G-Sec ~6.5%
clean = ef.clean_weights(cutoff=1e-4)
exp_ret, vol, sharpe = ef.portfolio_performance(risk_free_rate=0.065)   # TUPLE, not dict

# CVaR frontier on the actual return matrix
cvar_ef = EfficientCVaR(mu, returns_df, beta=0.95)
w_cvar = cvar_ef.min_cvar()

# whole-share allocation (add Indian lot-size quantisation on top — pypfopt does not know about NSE lots)
da = DiscreteAllocation(clean, get_latest_prices(prices), total_portfolio_value=50_000_000)
shares, leftover = da.greedy_portfolio()          # or da.lp_portfolio() for the optimal leftover
```

### Overlap with FinEngine

| FinEngine file / function | Library replacement | Effort | Risk |
|---|---|---|---|
| `optimization_service.py::_min_vol` (L619) | `EfficientFrontier.min_volatility()` | **S** | Low — pypfopt's cvxpy formulation is provably better-conditioned than a hand-rolled QP |
| `optimization_service.py::_max_sharpe` (L632) | `EfficientFrontier.max_sharpe(risk_free_rate=...)` | **S** | Low |
| `optimization_service.py::_min_cvar` (L652) | `EfficientCVaR.min_cvar()` | **S** | Low |
| `optimization_service.py::_black_litterman` (L670) | `BlackLittermanModel` | **M** | Medium — FinEngine's has Indian risk-free-rate/market-cap handling; port that, don't discard |
| `optimization_service.py::_hrp_weights` (L549) + `_cluster_var` (L528) | `HRPOpt.optimize()` | **M** | **High — do not migrate.** Broken on scipy 1.18, and FinEngine's own implementation works |
| `optimization_service.py::_moments` (L108) | `expected_returns.mean_historical_return` / `ema_historical_return` / `capm_return` | **S** | Low |
| `optimization_service.py::_solve` (L519) + `cp.Problem` | `EfficientFrontier` internals | **S** | Low — same cvxpy stack, so you can keep your `_solve` error handling |
| `analytics_engine.py::_sample_covariance_volatility` (L2347) | `risk_models.CovarianceShrinkage(...).ledoit_wolf()` / `.oracle_approximating()` | **M** | **Medium** — highest-value change, but this function also feeds the risk-parity sizing at L2399–2674; test heavily |
| `analytics_engine.py::effective_sample_size` (L608) / `measure_estimate_uncertainty` (L793) | *(no replacement — keep)* | — | FinEngine's estimation-error disclosure is **better** than anything in these libraries |
| `benchmark_service.py::get_returns` (L89) | `objective_functions.ex_ante_tracking_error` / `ex_post_tracking_error` | **M** | Medium — new capability (TE-constrained optimisation), not a like-for-like swap |
| `tail_risk_service.py::calculate_full_tail_risk_suite` (L441) | `EfficientCVaR` / `EfficientCDaR` (optimisation *of* CVaR/CDaR) | **M** | Low — orthogonal: FinEngine *measures* tail risk, pypfopt *minimises* it |
| `monte_carlo_service.py::simulate_goal` (L327) | `EfficientFrontier` (replace MC weight-search) | **L** | Medium-high — MC is a strictly worse optimiser; but the MC *forward simulation* for goal probability is a separate concern and must be kept |
| `allocations.py::build_trade_instructions` (L563) | `DiscreteAllocation.greedy_portfolio()` / `lp_portfolio()` | **M** | Medium — must preserve NSE/BSE **lot sizes** and FinEngine's half-up rounding; pypfopt has no concept of lots |
| `allocations.py::_clean_weights` (L188) | `BaseOptimizer.clean_weights(cutoff, rounding)` | **S** | Low — near-identical semantics |
| `allocations.py::normalization_block` / `normalize_rebalance_weights` | *(no replacement — keep)* | — | Domain logic (lot sizes, notional floors), not portfolio optimisation |
| `correlation_service.py`, `cointegration_service.py`, `regime_service.py`, `volatility_service.py`, GARCH, EVT-POT, copulas, volatility cone | *(no replacement in any of the 3 libs)* | — | Out of scope entirely |
| Moving averages / Bollinger (`indicators_service.py`) | `finquant.moving_average` (only if FinQuant were adoptable — it is not) | — | n/a |

### Implementation guide

**Step 1 — add the dependency.** In `backend/pyproject.toml`, inside the `dependencies = [...]` array,
immediately after the existing `"cvxpy>=1.6.0",` line (currently line 36):

```toml
    "cvxpy>=1.6.0",
    "pyportfolioopt>=1.6.0,<2.0",
    "quantlib>=1.40",
```

Do **not** install extras. Do **not** add `pyportfolioopt[all_extras]` — it would pull `plotly` and
`cvxopt` for no benefit, since FinEngine already has matplotlib and renders its own charts.

**Step 2 — resync the environment.** The repo has two dev tool tables
(`[project.optional-dependencies] dev` for pytest, `[dependency-groups] dev` for ruff), so per
`AGENTS.md` you must resync both after editing:

```
uv sync --extra dev --group dev
```

**Step 3 — add a thin adapter, do not call pypfopt from `services/`.** Create
`backend/app/services/pypfopt_adapter.py` (new file) owning every pypfopt import, the tuple-unpacking
fix, and solver-error translation. This keeps the library swappable and keeps `optimization_service.py`
readable. It must also re-export a numpy-scalar-only view, because pypfopt returns numpy scalars/arrays
that Pydantic will not serialise directly.

```python
# backend/app/services/pypfopt_adapter.py
"""All PyPortfolioOpt interaction is funnelled through this module.

Two version-specific hazards are handled here, both verified on
pandas 3.0.6 / numpy 2.5.3 / scipy 1.18 / py3.12:
  * v1.6.0 changed portfolio_performance() from dict -> tuple.
  * HRPOpt.optimize() raises on scipy >= 1.18 (_LINKAGE_METHODS removed); we refuse it explicitly.
"""
from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd
from pypfopt import EfficientFrontier, EfficientCVaR, risk_models, expected_returns
from pypfopt.base_optimizer import BaseConvexOptimizer

_HRP_UNAVAILABLE = (
    "PyPortfolioOpt HRPOpt is unusable on scipy>=1.18: it reads the private attribute "
    "scipy.cluster.hierarchy._LINKAGE_METHODS, removed in scipy 1.18.0. "
    "Keep using optimization_service._hrp_weights() until upstream patches it."
)


def shrunk_covariance(
    prices: pd.DataFrame,
    shrinkage: str = "ledoit_wolf",
) -> pd.DataFrame:
    """Annualised covariance with Ledoit-Wolf / OAS shrinkage.

    The plain sample covariance FinEngine uses today is unbiased but has a
    high estimation error, which is precisely what makes mean-variance
    optimisation overfit. Shrinkage is the cheapest large improvement available.
    """
    est = risk_models.CovarianceShrinkage(prices, frequency=252)
    if shrinkage == "ledoit_wolf":
        cov = est.ledoit_wolf()
    elif shrinkage == "oas":
        cov = est.oracle_approximating()
    else:
        cov = risk_models.sample_cov(prices)
    # NSE/BSE small caps can make the sample matrix non-PSD; repair before any cvxpy solve.
    return risk_models.fix_nonpositive_semidefinite(cov)


def expected_returns_vector(
    prices: pd.DataFrame,
    method: str = "mean_historical_return",
    market_prices: pd.Series | None = None,
) -> pd.Series:
    if method == "capm_return":
        return expected_returns.capm_return(prices, market_prices=market_prices)
    if method == "ema_historical_return":
        return expected_returns.ema_historical_return(prices)
    return expected_returns.mean_historical_return(prices)


def max_sharpe_weights(
    mu: pd.Series,
    cov: pd.DataFrame,
    risk_free_rate: float,
    max_position: float = 0.15,
) -> dict[str, float]:
    """Long-only max-Sharpe weights with a position cap. Returns JSON-safe floats."""
    ef = EfficientFrontier(mu, cov, weight_bounds=(0.0, max_position))
    ef.max_sharpe(risk_free_rate=risk_free_rate)
    # v1.6.0 returns a TUPLE. (v1.5.x and earlier returned a dict.)
    exp_return, volatility, sharpe = ef.portfolio_performance(
        verbose=False, risk_free_rate=risk_free_rate
    )
    weights = ef.clean_weights(cutoff=1e-4)
    return {
        "weights": {str(k): float(v) for k, v in weights.items()},
        "expected_return": float(exp_return),
        "volatility": float(volatility),
        "sharpe_ratio": float(sharpe),
    }


def min_cvar_weights(mu: pd.Series, returns: pd.DataFrame, beta: float = 0.95) -> dict[str, float]:
    ef = EfficientCVaR(mu, returns, beta=beta)
    w = ef.min_cvar()
    return {str(k): float(v) for k, v in ef.clean_weights().items()}


def performance_of(weights, mu, cov, risk_free_rate: float) -> tuple[float, float, float]:
    """Tuple-returning, matching pypfopt >= 1.6.0."""
    return BaseConvexOptimizer.portfolio_performance(
        np.asarray(weights, dtype=float), mu, cov, False, risk_free_rate
    )
```

**Step 4 — migrate, in this order.** Each step is independently shippable; do not batch them.

1. **Covariance shrinkage (biggest ROI, zero risk of regression).**
   Touch only `analytics_engine.py::_sample_covariance_volatility` (L2347). Add an
   `estimator: str = "ledoit_wolf"` parameter, defaulting to today's behaviour, and switch the default
   once `tests/` proves the shrinkaged matrix is PSD and produces sane weights.
   **This is the single highest-ROI change in this report.**
2. **Performance/tuple wrapper.** Nothing to migrate — just make sure no existing FinEngine code assumed
   dict semantics (nothing does today, because pypfopt is not yet a dependency; the hazard is entirely
   forward-looking). Add a regression test asserting the unpacked 3-tuple.
3. **CVaR frontier.** `optimization_service.py::_min_cvar` (L652) → `min_cvar_weights`. Keep the old
   implementation for one release behind a feature flag.
4. **Constraints.** Add `max_position` + sector/group caps to `optimize()` (L759) rather than replacing
   `_solve`/`_as_matrices`. FinEngine's `_solve` error handling and `_as_matrices` alignment logic are
   better than anything pypfopt provides; keep them.
5. **Do NOT migrate:** `_hrp_weights`, `monte_carlo_service`, `allocations.py` rounding/lot logic, and
   anything in `analytics_engine.py` relating to estimation-uncertainty disclosure.

**What to keep (all of it):** `_as_matrices`, `_weight_vector`, `_solve`, `optimizer_estimate_uncertainty`,
`no_estimate_uncertainty`, `measure_estimate_uncertainty`, `effective_sample_size`, the whole of
`allocations.py`, and all of FinEngine's GARCH / EVT-POT / copula / regime / cointegration / volatility-cone code.

**Regression tests to add** (repo convention is permanent tests in `backend/tests/`, not throwaway scripts):

- `test_pypfopt_adapter.py::test_shrunk_covariance_is_psd` — eigenvalues ≥ 0 for the shipped NSE universe.
- `test_pypfopt_adapter.py::test_max_sharpe_weights_sum_to_one` — guards the AGENTS.md zero-state/normalisation invariants.
- `test_pypfopt_adapter.py::test_portfolio_performance_returns_three_tuple` — pins the 1.6.0 contract.
- `test_pypfopt_adapter.py::test_weights_serialise_through_pydantic` — numpy-scalar leakage guard.
- `test_pypfopt_adapter.py::test_hrpopt_rejected_on_scipy_118` — asserts the guard message, so the day
  upstream fixes it the test tells you to revisit.

### Risk & caveats

1. **HRP is dead on scipy 1.18.** Do not plan around it. If you want HRP from pypfopt, you must either pin
   `scipy<1.18` (incompatible with FinEngine's other needs) or vendor-patch 6 lines. FinEngine's own
   `_hrp_weights` makes this a non-issue.
2. **`portfolio_performance()` is a tuple.** Silent break. Pin `>=1.6.0,<2.0` and test the unpack.
3. **`CovarianceShrinkage.ledoit_wolf()` is slow: 7.0 s for a 6×6 matrix.** It grid-searches the
   shrinkage intensity `delta`. FinEngine is a request/response API — this must be cached (e.g. keyed on
   `(asset tuple, window end, frequency)`) or computed in a background task, never inline in a request
   handler. `oracle_approximating()` is 0.015 s and is the better default if 7 s is unacceptable.
4. **`max_sharpe()` + `add_objective()` is mathematically incoherent** — pypfopt itself warns
   *"max_sharpe transforms the optimization problem so additional objectives may not work as expected"*.
   If you add `L2_reg` or `transaction_cost`, switch the objective to `min_volatility()` or
   `efficient_return()`.
5. **Zero-weight explosion.** Pure mean-variance returns many exact zeros; `L2_reg` is a mitigation, not a
   guarantee. Expect to post-process weights anyway.
6. **NSE/BSE lot sizes are invisible to `DiscreteAllocation`.** It will produce share counts that are
   untradeable. You must floor to lot size *after* calling it (or subclass). Do not trust its output
   directly.
7. **`min_cov_determinant` is deprecated but still ships**, with a stale warning naming a version already
   passed. Avoid.
8. **Tail risk measures are Monte-Carlo-free here, but CVaR is LP-sized.** `EfficientCVaR` on 750 rows ×
   8 assets took 46 ms — fine. On 500+ assets expect LP size to bite; check against your concurrency budget.
9. **Mean-variance is fragile regardless of library.** Adopting pypfopt does not make FinEngine's
   optimisation *good* — it makes it *standard*. FinEngine's existing
   `optimizer_estimate_uncertainty` / `no_estimate_uncertainty` machinery is a genuine differentiator
   that none of these libraries has; keep it front and centre in the UI.
10. **Single-maintainer org, slow release cadence.** Pin with an upper bound (`<2.0`) and re-run the smoke
    tests on every upgrade. The 1.5→1.6 module reorganisation and tuple change show breaking changes do land.

---

## Riskfolio-Lib

> **EVALUATE_LATER** — by far the deepest functionality (26+ convex risk measures, risk factors, entropy
> pooling, MVSK, OWA) and genuinely excellent on pandas 3.0.6 / numpy 2.5.3 / Python 3.12, BSD-3-Clause with
> no copyleft. But the latest release has two shipped-on-`master` functional bugs, a hard dependency on an
> unused heavyweight (`vectorbt` → `numba`, `plotly`, `ipywidgets`), and a 202-second optimisation path.

### Verdict

**EVALUATE_LATER.**

The technical fit is the best of the three: it installs cleanly on FinEngine's exact stack, all 14
`covar_matrix` methods and all 6 `mean_vector` methods work, 12 core risk measures optimise correctly with
weights summing to 1.0, and its mean-variance core is fast and well-scaled (0.37 s at 200 assets). But
`HERC`/`HERC2` are 100 % broken in the current release, `linkage="DBHT"` is broken on numpy 2.x, and the
`vectorbt` dependency is a hard pin on a package the library never imports. Revisit once 7.4.x lands and
those are fixed; do not adopt the risk-parity or clustering surface in the meantime.

### License

- **Exact license:** BSD 3-Clause
- **SPDX identifier:** `BSD-3-Clause` (confirmed via GitHub API `license.spdx_id` and PyPI classifier
  `License :: OSI Approved :: BSD License`)
- **Source:** https://github.com/dcajasn/Riskfolio-Lib/blob/master/LICENSE.txt

Relevant clauses, quoted:

> "* Redistributions of source code must retain the above copyright notice, this list of conditions and the
>   following disclaimer.
>
> * Redistributions in binary form must reproduce the above copyright notice, this list of conditions and
>   the following disclaimer in the documentation and/or other materials provided with the distribution.
>
> * Neither the name of Riskfolio-Lib nor the names of its contributors may be used to endorse or promote
>   products derived from this software without specific prior written permission."

> "Redistribution and use in source and binary forms, with or without modification, are permitted provided
> that the following conditions are met"

and the warranty disclaimer:

> "THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED
> WARRANTIES … ARE DISCLAIMED."

- **Commercial use:** permitted. BSD-3 places **no** restriction on commercial use and requires **no**
  revenue share and **no** CLA.
- **The one clause that matters commercially is the no-endorsement clause.** You may not name
  "Riskfolio-Lib" or its contributors in marketing in a way that suggests endorsement. Practically: fine to
  list it in a "third-party libraries" / attribution section, **not** fine to write
  "Riskfolio-Lib-powered institutional optimisation". Have legal review the exact wording if you plan
  product copy.
- **Copyleft:** none. **Not** GPL/LGPL. No source-disclosure trigger, no reciprocal-licence trigger.
- **Linking vs vendoring:**
  - *As a PyPI dependency:* keep the copyright + 3 conditions + disclaimer in
    `THIRD_PARTY_NOTICES.md`. That is the whole obligation.
  - *Vendoring / forking:* you must keep the header in each copied file and in your docs, and you must
    **not** use the name "Riskfolio-Lib" or contributor names to endorse.
  - *Note the compiled component.* Riskfolio ships a **pybind11 + Eigen + Spectra C++ extension**
    (`riskfolio/external/cppfunctions`, built via `Pybind11Extension` in `setup.py`). If you ever vendor
    source you are also vendoring third-party Eigen and Spectra code — check *their* licences (both
    MPL-2.0). This is a reason to prefer the wheel, not the source.
- **Not a business-source or non-commercial license.** The paid course/book/sponsorship links in the README
  are **funding**, not licence conditions. The code itself is BSD-3-Clause with no use restriction.

### Maintenance

**Activity: ACTIVE — the most actively maintained of the three.**

| Fact | Value | Source |
|---|---|---|
| Latest release | **7.3.0**, published **2026-05-31** | https://pypi.org/pypi/riskfolio-lib/json |
| Last commit on `master` | **2026-09-24** (3 days before observation) — *"Delete docs/source/robots.txt"*; prior commits same day, incl. *"Upgrade GitHub Actions to latest versions"* | GitHub API `repos/dcajasn/Riskfolio-Lib/commits` |
| `pushed_at` | 2026-09-24T05:23:00Z | GitHub API repo object |
| Open issues | **9** (very low for 4.5k stars) | GitHub search API `is:issue is:open` |
| Open PRs | **8** | GitHub search API `is:pr is:open` |
| Archived | `false` | GitHub API |
| Stars | 4,518 | GitHub API |
| Wheels published for 7.3.0 | `cp310`, `cp311`, `cp312`, `cp313`, `cp314` × {macosx universal2, manylinux x86_64/aarch64, **win_amd64**} + sdist | PyPI `releases["7.3.0"]` |
| CI matrix | `os: [ubuntu-22.04, macos-15, windows-2022]` × `python-version: ["3.10"…"3.14"]` | https://github.com/dcajasn/Riskfolio-Lib/blob/master/.github/workflows/build.yml |
| Citation | `@misc{riskfolio, author={Dany Cajas}, title={Riskfolio-Lib (7.3)}, year={2026}}` | repo README |
| Branches | `master`, `Beta_Install`, `dcajasn-patch-1`, `revert-238-fxmacrodata-portfolio-example` | GitHub API |

**Verdict: ACTIVE.** Commits within the last week, 9 open issues total, wheels for every supported Python
including 3.14 and Windows. This is a healthy maintenance signal.

**Two honest caveats:**
1. **Single maintainer** (`dcajasn`, 424 commits total since 2020). Everything — code, docs, CI, releases,
   issue triage — is one person. Bus factor 1. He monetises via a Springer book, a paid course,
   GitHub Sponsors and Ko-fi, and the README is explicit that *"community support plays a vital role in
   its continued development"*. That is currently working; it is not a guarantee.
2. **The bugs below ship on `master` in the current release.** High commit velocity does not imply
   release quality — there is no test-coverage gate visible in CI, and the two failures I found are
   in well-exercised headline features.

### Compatibility

| Dimension | Status | Evidence |
|---|---|---|
| Python 3.12 | ✅ Supported | `python_requires = ">=3.10"`; classifiers 3.10–3.14; CI includes 3.12; `cp312-win_amd64` wheel published. Ran on 3.12.9. |
| Python 3.14 | ✅ Supported | classifier + CI matrix + `cp314` wheels |
| **pandas 3.0** | ✅ **Works** | No upper bound (`pandas>=2.2.2`). **Verified running** (see below). |
| **numpy 2.x** | ✅ **Works, with one exception** | No upper bound (`numpy>=1.26.4`). **Verified running** on numpy 2.5.3. Exception: the `DBHT` clustering code path (below). |
| scipy 1.18 | ✅ Works | No upper bound (`scipy>=1.16.1`). **Verified running.** (Uses only public `scipy.cluster.hierarchy` / `scipy.spatial.distance` APIs — unlike pypfopt.) |
| quantlib coexistence | ✅ No conflict observed | Both are large compiled extensions but share no symbols, headers, or dtype contracts. Neither imports the other. `riskfolio` is pure-Python + its own pybind11 module; quantlib is its own wheel. **UNVERIFIED** — I did not install quantlib into the same test env as riskfolio; reasoned from import graphs. |
| cvxpy coexistence | ✅ Compatible | Requires `cvxpy>=1.6.6`; FinEngine has 1.9.3. Requires `clarabel>=0.11.1` and `SCS>=3.2.7` — **both already installed** per the brief. No new solvers. |
| Removed-pandas-API scan | ✅ **Clean** | I fetched and scanned all 12 modules in `riskfolio/src/` against ~26 deprecated/removed patterns (`.applymap(`, `.iteritems(`, `pd.Panel`, `pd.np`, `.as_matrix(`, `.get_values(`, `.set_value(`, `.convert_objects(`, `.mad(`, `.tshift(`, `.weekofyear`, `.lookup(`, `np.bool/float/int/object`, `.ix[`, `is_categorical_dtype`, `freq='M'`, `pd.tseries`, …). **Zero hits** beyond benign `list.append`. |

#### Verified working on FinEngine's exact stack (`py3.12.9 / pandas 3.0.6 / numpy 2.5.3 / scipy 1.18.0`)

```
== covar_matrix with DOCUMENTED methods (input=returns) ==
   hist      ok  0.001s shape=(8, 8)      semi      ok  0.004s
   ewma1     ok  0.046s                    ewma2     ok  0.026s
   ledoit    ok  0.055s   <-- Ledoit-Wolf   oas       ok  0.002s   <-- OAS
   shrunk    ok  0.003s                    gl        ok  0.161s   <-- graphical lasso
   jlogo     ok  0.006s                    fixed     ok  0.014s   <-- denoising
   spectral  ok  0.012s                    shrink    ok  0.011s
   gerber1   ok  0.466s                    gerber2   ok  0.001s
== mean_vector with DOCUMENTED methods (input=prices) ==
   hist ok   ewma1 ok   ewma2 ok   JS ok   BS ok   BOP ok
```

All 14 `covar_matrix` methods and all 6 `mean_vector` methods work. `Portfolio.optimization()` across
risk measures, **all with `sum(weights) == 1.000000`**:

```
MV ok 0.054s | MSV ok 0.066s | MAD ok 0.044s | CVaR ok 0.049s | FLPM ok 0.048s
SLPM ok 0.068s | EVaR ok 0.091s | RLVaR ok 0.605s | UCI ok 0.086s | MDD ok 0.070s
RG ok 0.053s | EDaR ok 0.123s | RLDaR ok 0.207s
CVaR + Ledoit-Wolf covariance: ok 0.070s, sum=1.000000
Risk_Contribution ok 0.000s (also CVaR, EVaR, RLVaR, TG, GMD, EDaR, RLDaR)
frontier_limits ok 0.072s | efficient_frontier(20pts) ok 0.873s | bootstrapping ok 1.012s
```

#### 🛑 BUG 1 — `HERC` and `HERC2` are 100 % broken in 7.3.0 (all 12 param combinations tested)

```
HERC  pearson     FAIL TypeError: HCPortfolio._hierarchical_recursive_bisection() got an unexpected keyw
HERC  spearman    FAIL TypeError: …                        HERC  kendall     FAIL …
HERC  distance    FAIL TypeError: …                        HERC  mutual_info FAIL …
HERC  tail        FAIL TypeError: …
HERC2 pearson     FAIL TypeError: …   (… and all 6 codependence variants)
```

Root cause, read directly from `riskfolio/src/HCPortfolio.py` on `master`:

```python
# HCPortfolio.py:1093-1103  — the HERC/HERC2 branch
elif model in ["HERC", "HERC2"]:
    weights = self._hierarchical_recursive_bisection(
        self.clustering,
        rm=rm,
        rf=rf,
        linkage=linkage,        # <-- callee has no `linkage`
        model=model,
        upper_bound=upper_bound,  # <-- callee has no `upper_bound`
        lower_bound=lower_bound,  # <-- callee has no `lower_bound`
    )

# HCPortfolio.py:522-528  — the actual signature
def _hierarchical_recursive_bisection(
    self,
    Z,
    rm="MV",
    rf=0,
    model="HERC",
):
```

The caller passes three keyword arguments the callee does not accept. `HRP` and `NCO` take different
branches (L1080-1092 and L1104+) and work fine. This kills
"Hierarchical Equal Risk Contribution with 37 risk measures" — a headline advertised feature, with a
dedicated example notebook (`examples/Tutorial 44 - Hierarchical Equal Risk Contribution (HERC)…`).

#### 🛑 BUG 2 — `linkage="DBHT"` is broken on numpy 2.x

`linkage="DBHT"` is a documented, advertised option (Direct Bubble Hierarchical Tree, Song et al.
"Hierarchical information clustering by means of topologically embedded graphs"). It fails:

```
ValueError: setting an array element with a sequence.
  File ".../riskfolio/src/DBHT.py", line 81,  in DBHTs
    H1, Hb, Mb, CliqList, Sb = CliqHierarchyTree2s(Rpm, method1="uniqueroot")
  File ".../riskfolio/src/DBHT.py", line 433, in CliqHierarchyTree2s
    Pred = BuildHierarchy(M)
  File ".../riskfolio/src/DBHT.py", line 491, in BuildHierarchy
    Pred[n] = Parents[a]
TypeError: only 0-dimensional arrays can be converted to Python scalars   <-- the numpy 2 removal
```

`HCPortfolio.py:371-388` routes `linkage == "DBHT"` straight into `db.DBHTs(...)`, so the failure is
unavoidable. Cause is numpy ≥ 2.x no longer coercing size-1 arrays to scalars on assignment.

#### ⚠️ ISSUE 3 — `optimization()` before `assets_stats()` gives an inscrutable error

Calling `Portfolio(returns=r).optimization(...)` **without** first calling `assets_stats()` produces:

```
File ".../riskfolio/src/Portfolio.py", line 2196, in optimization
    G = sqrtm(sigma)
TypeError: '<' not supported between instances of 'NoneType' and 'int'
```

Not a crash on *correct* usage, but a genuine developer-experience defect: the failure surfaces deep
inside `scipy.linalg.sqrtm` instead of as "call `assets_stats()` first". Budget time for this when
integrating.

#### ⚠️ ISSUE 4 — deprecated CVXPY idioms

Riskfolio itself emits, on the currently-installed CVXPY:

```
UserWarning: This use of ``*`` has resulted in matrix multiplication.
Using ``*`` for matrix multiplication has been deprecated since CVXPY 1.1.
Use ``*`` for matrix-scalar and vector-scalar multiplication. Use ``@`` for matrix-matrix…
```

plus `RuntimeWarning: invalid value encountered in divide` at `AuxFunctions.py:117`
(`corr = np.clip(cov1 / np.outer(std, std), …)`). Not fatal today; a future CVXPY major will break it.
`portfoliooptimization.org` exists precisely because a commercial solver (MOSEK) is sometimes needed.

### Dependency footprint

**Hard dependencies — `setup.py` `INSTALL_REQUIRES` (verified identical to the published
`requires_dist`):**

```
numpy>=1.26.4        scipy>=1.16.1        pandas>=2.2.2       matplotlib>=3.9.2
clarabel>=0.11.1     SCS>=3.2.7           cvxpy>=1.6.6        scikit-learn>=1.3.0
statsmodels>=0.14.5  arch>=7.2            xlsxwriter>=3.2.2   networkx>=3.4.2
astropy>=6.1.3       pybind11>=2.13.6     vectorbt>=0.28.0     <-- see below
```

#### 🛑 `vectorbt` is a hard dependency that Riskfolio never imports

- The repo README lists `vectorbt` under **"Examples requires"**, alongside `yfinance` and `mosek`.
- But `setup.py` puts `'vectorbt>=0.28.0'` inside `INSTALL_REQUIRES`, so it is an **unconditional runtime
  dependency** — confirmed in the published PyPI `requires_dist`.
- **I fetched and scanned all 12 modules in `riskfolio/src/`
  (`AuxFunctions`, `ConstraintsFunctions`, `DBHT`, `GerberStatistic`, `HCPortfolio`, `OwaWeights`,
  `ParamsEstimation`, `PlotFunctions`, `Portfolio`, `Reports`, `RiskFunctions`, `__init__`).
  There is no `import vectorbt` and no occurrence of the string `vectorbt` in any of them.**
  Actual third-party imports are only: `numpy, pandas, cvxpy, scipy, sklearn, statsmodels, arch.bootstrap,
  astropy.stats, networkx, xlsxwriter, matplotlib` + `riskfolio.external.cppfunctions`.

So the cost is real and the benefit is zero. Resolving `vectorbt>=0.28.0` today pulls **vectorbt 1.1.1**
(released 2026-09-26), whose own `requires_dist` adds:

`numba>=0.66`, `plotly>=4.12.0`, `ipywidgets>=7.0.0`, `anywidget`, `dill`, `tqdm`, `dateparser`,
`imageio`, `schedule`, `requests`, `pytz`, `mypy_extensions` (and `numpy>=2.4.6`, `pandas>=3.0.3`).

**Measured:** installing `riskfolio-lib==7.3.0` alone reported **`Installed 86 packages`** — versus 34 for
`pyportfolioopt==1.6.0` and 41 for `FinQuant==0.7.0` (both in equivalent environments).

**Conflict risk with FinEngine's pin set:**
- `numpy>=2.4.6` (from vectorbt) — FinEngine has 2.5.3, satisfied.
- `pandas>=3.0.3` — FinEngine has 3.0.6, satisfied.
- `numba>=0.66` — **new LLVM-backed compiled dependency.** Second heavy compiled extension alongside
  quantlib. It is the most likely source of future resolver pain, and it is installed for nothing.
- `matplotlib>=3.9.2` — already present.
- `statsmodels>=0.14.5`, `arch>=7.2` — already present, satisfied.
- `pybind11>=2.13.6` is both a runtime dep **and** a build requirement (`[build-system] requires`), and
  `setup.py` pins `setuptools == 78.1.1` exactly. This is fragile if you ever build from source; use the
  wheel.
- `astropy` (~30 MB) is needed for one thing: `astropy.stats` in `AuxFunctions.py` (mutual-information
  codependence). Heavy for that.

**Mitigation if you ever adopt it:** install with `--no-deps` and add the 13 genuinely-needed packages
yourself, omitting `vectorbt`. That works because nothing imports it, but it is a supply-chain decision
you should make deliberately and document, not do silently.

### API surface

Verified from `riskfolio/src/*.py` on `master` and cross-checked against Context7 (`/dcajasn/riskfolio-lib`).

```python
import riskfolio as rp
from riskfolio import Portfolio, HCPortfolio
from riskfolio.src import ParamsEstimation as PE, RiskFunctions as RF, DBHT, AuxFunctions as af
```

| Class / function | Signature | Solves |
|---|---|---|
| `Portfolio` | `Portfolio(returns=None, sht=False, uppersht=0.2, upperlng=1, lowerlng=0, budget=1, budgetsht=0.2, nea=None, …)` | Main optimiser object; holds returns + constraints |
| ↳ `.assets_stats` | `assets_stats(method_mu="hist", method_cov="hist", method_kurt=None, dict_mu={}, dict_cov={}, dict_kurt={})` | **Required before optimising.** Populates `mu`, `cov`. `method_mu ∈ {hist, ewma1, ewma2, JS, BS, BOP}`; `method_cov ∈ {hist, semi, ewma1, ewma2, ledoit, oas, shrunk, gl, jlogo, fixed, spectral, shrink, gerber1, gerber2}` |
| ↳ `.optimization` | `optimization(model="Classic", rm="MV", obj="Sharpe", kelly=None, rf=0, l=2, hist=True)` → DataFrame | Solve. `model ∈ {Classic, BL, FM, BLFM, EP}`; `obj ∈ {MinRisk, MaxRet, Utility, Sharpe}`; `rm` ∈ 26 convex risk measures |
| ↳ `.rp_optimization` | `rp_optimization(model="Classic", rm="MV", rf=0, b=None, b_f=None, hist=True)` | Risk budgeting / risk parity (Roncalli). `model ∈ {Classic, FM, FC}` **only** |
| ↳ `.rrp_optimization` | `rrp_optimization(model="A", version="A", l=1, b=None, hist=True)` | **Relaxed** risk parity (convex, faster) |
| ↳ `.owa_optimization` | `owa_optimization(obj="Sharpe", owa_w=None, kelly=None, rf=0, l=2)` | Ordered Weighted Averaging. ⚠️ 202 s for 8 assets |
| ↳ `.wc_optimization` | `wc_optimization(obj="Sharpe", rf=0, l=2, Umu="box", Ucov="box")` | Worst-case (uncertainty-set) optimisation |
| ↳ `.mvsk_optimization` | `mvsk_optimization(model="Classic", obj="Sharpe", rf=0, l=[2,3,4], solvers=["SCS"])` | Mean-Variance-Skewness-Kurtosis, semidefinite relaxation. Needs coskewness/cokurtosis first |
| ↳ `.efficient_frontier` | `efficient_frontier(model="Classic", rm="MV", kelly=None, points=20, rf=0, solver="CLARABEL", hist=True)` | Frontier. Docs: **avoid > 100 assets** with scenario risk measures |
| ↳ `.frontier_limits` | `frontier_limits(model="Classic", rm="MV", kelly=None, rf=0, hist=True)` | min-risk / max-return corners only — *"preferable (faster)"* |
| ↳ `.blacklitterman_stats` | `blacklitterman_stats(P, Q, rf=0, w=None, delta=None, eq=True, method_mu="hist", method_cov="hist", …)` | Black-Litterman via market caps |
| ↳ `.entropy_pooling_stats` | `entropy_pooling_stats(P_eq, Q_eq, P_in, Q_in, higher_comoments=False, solver="CLARABEL")` | Meucci entropy pooling (7.3.0 new) |
| ↳ `.factors_stats` | `factors_stats(method_mu="hist", method_cov="hist", method_kurt="hist", B=None, const=True, …)` | Risk-factor model (needs a factor DataFrame `X`) |
| ↳ `.wc_stats` | `wc_stats(box="s", ellip="s", q=0.05, n_sim=3000, window=3, …)` | Uncertainty sets for mean/cov |
| `HCPortfolio` | `HCPortfolio(returns=None, alpha=0.05, a_sim=100, beta=None, b_sim=None, kappa=0.30, …)` | Hierarchical clustering portfolios |
| ↳ `.optimization` | `optimization(model="HRP", codependence="pearson", obj="MinRisk", rm="MV", rf=0, l=2, method_mu="hist", method_cov="hist", custom_mu=None, custom_cov=None, linkage="single", opt_k_method="twodiff", k=None, max_k=10, bins_info="KN", alpha_tail=0.05, gs_threshold=0.5, leaf_order=True, dict_mu={}, dict_cov={})` → **ndarray** | `model ∈ {HRP, HERC, HERC2, NCO}`. `codependence ∈ {pearson, spearman, kendall, gerber1, gerber2, custom_cov, abs_pearson, abs_spearman, abs_kendall, distance, mutual_info, tail}`. `linkage ∈ {ward, single, average, complete, DBHT, …}` |
| `PE.mean_vector` | `mean_vector(X, method="hist", d=0.94, target="b1")` → 1-D array | μ estimator: `hist, ewma1, ewma2, JS, BS, BOP` |
| `PE.covar_matrix` | `covar_matrix(X, method="hist", d=0.94, alpha=0.1, bWidth=0.01, detone=False, mkt_comp=1, threshold=0.5)` | Σ estimator: 14 methods incl. `ledoit` (**Ledoit–Wolf**), `oas` (**OAS**), `gl` (graphical lasso), `jlogo`, `fixed`/`spectral`/`shrink` (denoising) |
| `PE.cokurt_matrix` | `cokurt_matrix(X, method="hist", alpha=0.1, bWidth=0.01, detone=False, mkt_comp=1)` | Co-kurtosis for MVSK (7.3.0) |
| `PE.risk_factors` | `risk_factors(X, Y, B=None, const=True, method_mu="hist", …)` | Factor model + loadings |
| `PE.loadings_matrix` | `loadings_matrix(X, Y, feature_selection="stepwise", stepwise="Forward", criterion="pvalue", threshold=0.05, n_components=0.95)` | Stepwise / PCR loadings |
| `PE.bootstrapping` | `bootstrapping(X, kind="stationary", q=0.05, n_sim=6000, window=3, diag=False, threshold=1e-15, seed=0)` → **tuple** | Stationary/iid/bootstrap uncertainty sets |
| `PE.black_litterman` / `augmented_black_litterman` / `black_litterman_bayesian` | see source | BL variants incl. Bayesian (7.3.0 entropy pooling) |
| `RF.Risk_Contribution` | `Risk_Contribution(w, returns, cov=None, rm="MV", rf=0, alpha=0.05, a_sim=100, beta=None, b_sim=None, kappa=0.3, kappa_g=None, p_em=2, p_esm=2, solver="CLARABEL")` | Per-asset risk contribution under **any** of the 26 measures |
| `RF.Risk_Margin` | same signature family | EVaR/EVRG/EDaR/RLVaR/RVRG/RLDaR margin |
| `RF.Sharpe` / `RF.Sharpe_Risk` | `Sharpe(returns, w=None, mu=None, cov=None, rm="MV", rf=0, alpha=0.05, …)` | Risk-adjusted return with a *convex risk measure in the denominator* |
| `RF.NEA` | `NEA(w)` | **Number of effective assets** — directly relevant to FinEngine's HHI diversification invariant |
| `RF.BrinsonAttribution` | `BrinsonAttribution(prices, w, wb, start, end, asset_classes, classes_col, method="nearest")` | Brinson-Fachler performance attribution |
| `RF.Factors_Risk_Contribution` | `(w, returns, factors, cov=None, B=None, const=False, rm="MV", …)` | Per-factor risk contribution |
| `DBHT.DBHTs` / `DBHT.PMFG_T2s` | `DBHTs(D, S, leaf_order=True)` | Direct Bubble Hierarchical Tree / Triangulated Maximally Filtered Graph clustering. **⚠️ broken on numpy 2.x** |
| `af.hrp_constraints` | `hrp_constraints(constraints, asset_classes)` | Bounds for HRP/HERC |
| `rp.plot_frontier` | `plot_frontier(w_frontier, mu, cov, returns, rm="MV", kelly=False, rf=0, alpha=0.05, …, solver="CLARABEL", t_factor=252, ax=None)` | Frontier plot (matplotlib) |

**Verified working run on FinEngine's stack** (8 assets × 750 business days):

```python
# Mean-variance with Ledoit-Wolf shrinkage, CVaR objective
port = rp.Portfolio(returns=returns)
port.assets_stats(method_mu="hist", method_cov="ledoit")
w = port.optimization(model="Classic", rm="CVaR", obj="Sharpe", rf=0.065, l=2)
# -> 0.070s, sum(w) == 1.000000

# Hierarchical Risk Parity (works; note: returns an ndarray, not a dict)
hc = rp.HCPortfolio(returns=returns)
w_hrp = hc.optimization(model="HRP", codependence="spearman", rm="MV", rf=0.065, linkage="ward")
# -> 0.050s, sum(w_hrp) == 1.000000

# Nested Clustered Optimization
w_nco = rp.HCPortfolio(returns=returns).optimization(model="NCO", rm="MV", rf=0.065)
# -> 0.172s, sum == 1.000000

# Risk contribution under a convex risk measure
rc = RF.Risk_Contribution(w, returns, rm="CVaR")     # also EVaR, RLVaR, TG, GMD, EDaR, RLDaR
nea = RF.NEA(w)                                        # number of effective assets
```

### Overlap with FinEngine

| FinEngine file / function | Library replacement | Effort | Risk |
|---|---|---|---|
| `optimization_service.py::_min_vol` (L619) | `Portfolio.optimization(rm="MV", obj="MinRisk")` | **S** | Low |
| `optimization_service.py::_max_sharpe` (L632) | `Portfolio.optimization(obj="Sharpe", rf=…)` | **S** | Low |
| `optimization_service.py::_min_cvar` (L652) | `Portfolio.optimization(rm="CVaR")` | **S** | Low |
| `optimization_service.py::_black_litterman` (L670) | `Portfolio.blacklitterman_stats()` or `PE.black_litterman()` | **M** | Medium |
| `optimization_service.py::_hrp_weights` (L549) | `HCPortfolio.optimization(model="HRP")` | **M** | Medium — library adds `codependence`/`linkage`/`opt_k_method` options FinEngine lacks, but returns ndarray and has the scipy-1.18-adjacent fragility of clustering code |
| `analytics_engine.py` inverse-volatility risk parity (L2399–2674, inside `_sample_covariance_volatility`) | `Portfolio.rp_optimization(model="Classic", rm="MV")` (exact risk budgeting) or `rrp_optimization` (relaxed, convex) | **M** | **Medium-high** — FinEngine's version scales inverse-vol weights to a *target volatility*; that specific behaviour has no direct library equivalent. Keep FinEngine's scaling, consider replacing the kernel |
| `analytics_engine.py::_sample_covariance_volatility` (L2347) | `PE.covar_matrix(method="ledoit"/"oas"/"gl"/"spectral")` | **M** | Medium — but **pypfopt's Ledoit-Wolf is faster (0.055 s vs 0.466 s for gerber) and simpler**; prefer pypfopt here |
| `analytics_engine.py` HHI / diversification score (`N_eff = 1/HHI`) | `RF.NEA(w)` | **S** | Low — but see AGENTS.md: FinEngine has a hard invariant that single-holding renders 0 %; `NEA` is **not** a drop-in for that rule. Keep FinEngine's. |
| `analytics_engine.py::_calculate_risk_metrics` (L3180) | `RF.Sharpe(returns, w=…, rm=…)` with non-MV denominators | **M** | Medium |
| `tail_risk_service.py::calculate_full_tail_risk_suite` (L441) | `optimization(rm="CVaR"/"EVaR"/"RLVaR"/"CDaR"/"EDaR"/"RLDaR")` | **M** | Low — orthogonal (optimise vs measure) |
| `tail_risk_service.py::calculate_evt_pot_var_es` (L25) | *(no replacement)* | — | Riskfolio has **no** EVT-POT. FinEngine is strictly ahead. |
| `benchmark_service.py` | `RF.BrinsonAttribution(prices, w, wb, start, end, asset_classes, classes_col)` | **M** | Low — genuinely new capability FinEngine lacks |
| *(no FinEngine equivalent)* | `rp.entropy_pooling_stats(...)` | — | **New feature** — Meucci entropy pooling for view-driven distributions. High research value. |
| *(no FinEngine equivalent)* | `PE.bootstrapping(kind="stationary"/"iid")` + `wc_stats` | — | **New feature** — worst-case / uncertainty-set optimisation. Pairs with FinEngine's estimation-uncertainty disclosure. |
| *(no FinEngine equivalent)* | `mvsk_optimization` (needs `cokurt_matrix`, 7.3.0) | — | New — higher-moment optimisation. |
| *(no FinEngine equivalent)* | `optimization(rm=…)` for GMD, Tail Gini, Even Moments, Ranges, UCI | — | New — but see the performance wall below. |
| `monte_carlo_service.py::simulate_goal` (L327) | *(no replacement)* | — | Riskfolio's MC is for covariance uncertainty, not goal-probability simulation. **Keep FinEngine's.** |
| GARCH, EVT-POT, copula tail dependence, correlation regime breaks, cointegration, volatility cone, HMM regimes | *(nothing in any of the 3 libs)* | — | FinEngine's core differentiators. Untouched. |

### Implementation guide

**Do this when/if 7.4.x fixes HERC + DBHT.** Steps 1–3 are the only ones safe today.

**Step 1 — add the dependency, deliberately omitting the dead weight.**

In `backend/pyproject.toml`, after the existing `"quantlib>=1.40",` line (line 37):

```toml
    "quantlib>=1.40",
    "riskfolio-lib>=7.3.0,<8.0",
```

Then immediately after editing, per `AGENTS.md`, resync both dev tool tables:

```
uv sync --extra dev --group dev
```

**And then remove the dependency you don't want.** `vectorbt` is installed unconditionally but never
imported. Suppress it without patching the library by filtering the requirement in
`backend/pyproject.toml` with uv's `[tool.uv] override-dependencies` (add alongside the existing
`[tool.uv] python-downloads = "automatic"`):

```toml
[tool.uv]
python-downloads = "automatic"
# riskfolio-lib declares vectorbt as a runtime dep but never imports it (verified: all 12
# modules of riskfolio/src/ scanned). Dropping it avoids pulling numba, plotly, ipywidgets,
# anywidget, dill, tqdm, dateparser, imageio, schedule, requests and pytz for nothing.
override-dependencies = ["vectorbt ; sys_platform == 'never'"]
```

Verify after sync that `vectorbt` is absent and that `import riskfolio` still succeeds. If the override
syntax misbehaves, fall back to `uv pip install --no-deps riskfolio-lib==7.3.0` plus the 13 real deps,
and record that decision in `docs/adr/`.

**Step 2 — adapter module, not direct calls.** New file
`backend/app/services/riskfolio_adapter.py`, owning all imports plus these three normalisations:

1. `HCPortfolio.optimization()` returns a **`numpy.ndarray`**; `Portfolio.optimization()` returns a
   **`DataFrame`**. Convert both to `{ticker: float}` at the boundary.
2. `PE.bootstrapping()` returns a **tuple**.
3. Assert `assets_stats()` was called — otherwise you get `TypeError: '<' not supported between
   instances of 'NoneType' and 'int'` from inside `sqrtm`.

```python
# backend/app/services/riskfolio_adapter.py
"""All Riskfolio-Lib interaction is funnelled through this module.

Verified on python 3.12.9 / pandas 3.0.6 / numpy 2.5.3 / scipy 1.18.0.
Known upstream defects in riskfolio-lib 7.3.0 that this module refuses rather than
propagates:
  * HCPortfolio.optimization(model="HERC"/"HERC2") raises TypeError on every input
    (HCPortfolio.py:1095 passes linkage/upper_bound/lower_bound to a callee whose
    signature is (self, Z, rm, rf, model) at HCPortfolio.py:522).
  * linkage="DBHT" raises on numpy >= 2 (DBHT.py:491).
"""
from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd
import riskfolio as rp
from riskfolio.src import ParamsEstimation as PE

_HERC_BROKEN = (
    "riskfolio-lib 7.3.0: HCPortfolio model='HERC'/'HERC2' is broken upstream "
    "(unexpected keyword 'linkage'). Use model='HRP' or model='NCO' instead."
)
_DBHT_BROKEN = (
    "riskfolio-lib 7.3.0: linkage='DBHT' raises on numpy>=2 (DBHT.py:491). "
    "Use linkage='ward'/'single'/'average'/'complete' instead."
)


def _as_weights(raw) -> dict[str, float]:
    """Portfolio.optimization() -> DataFrame, HCPortfolio.optimization() -> ndarray."""
    values = raw.to_numpy().ravel() if isinstance(raw, (pd.DataFrame, pd.Series)) else np.asarray(raw).ravel()
    if raw is not None:
        index = raw.index if isinstance(raw, (pd.DataFrame, pd.Series)) else range(len(values))
        return {str(i): float(v) for i, v in zip(index, values)}
    raise TypeError(f"unexpected weight container: {type(raw)!r}")


def optimise(
    returns: pd.DataFrame,
    rm: str = "MV",
    obj: str = "Sharpe",
    risk_free_rate: float = 0.0,
    method_cov: str = "ledoit",
    max_position: float | None = 0.15,
) -> dict[str, float]:
    """Convex mean-risk optimisation with Ledoit-Wolf covariance by default."""
    port = rp.Portfolio(returns=returns)
    if max_position is not None:
        port.upperlng = max_position
    port.assets_stats(method_mu="hist", method_cov=method_cov)  # MUST precede optimisation
    weights = port.optimization(model="Classic", rm=rm, obj=obj, rf=risk_free_rate, l=2)
    return _as_weights(weights)


def hierarchical_risk_parity(
    returns: pd.DataFrame,
    risk_free_rate: float = 0.0,
    codependence: str = "spearman",
    linkage: str = "ward",
) -> dict[str, float]:
    if linkage.upper() == "DBHT":
        raise NotImplementedError(_DBHT_BROKEN)
    hc = rp.HCPortfolio(returns=returns)
    weights = hc.optimization(
        model="HRP", codependence=codependence, rm="MV", rf=risk_free_rate, linkage=linkage
    )
    return _as_weights(weights)


def risk_parity(returns: pd.DataFrame, risk_free_rate: float = 0.0) -> dict[str, float]:
    """Exact risk budgeting (Roncalli). Distinct from FinEngine's inverse-vol heuristic."""
    port = rp.Portfolio(returns=returns)
    port.assets_stats(method_mu="hist", method_cov="ledoit")
    return _as_weights(port.rp_optimization(model="Classic", rm="MV", rf=risk_free_rate))


def shrunk_covariance(returns: pd.DataFrame, method: str = "ledoit") -> np.ndarray:
    return PE.covar_matrix(returns, method=method)
```

**Step 3 — the only genuinely new capability worth taking first.**
`rf.entropy_pooling_stats(...)` (Meucci entropy pooling, added in 7.3.0) and
`PE.bootstrapping(kind="stationary", n_sim=6000)` are things FinEngine does not have at all, and both
compose naturally with the existing `optimizer_estimate_uncertainty` /
`measure_estimate_uncertainty` disclosure. Ship these behind a new endpoint before touching any
existing optimiser.

**Step 4 — only after upstream fixes.** `rp_optimization` to replace the inverse-volatility kernel;
Brinson attribution for `benchmark_service.py`.

**Files to touch:** `backend/pyproject.toml`; new `backend/app/services/riskfolio_adapter.py`;
`backend/app/api/analytics.py` (new endpoints only); `backend/app/services/optimization_service.py`
(step 4 only); `backend/tests/test_riskfolio_adapter.py` (new).

**What to keep (all of it):** `_hrp_weights` and `_cluster_var` (they work and HRP from the library is
currently broken anyway); the inverse-volatility-to-target-volatility scaling logic at
`analytics_engine.py` L2399–2674; `_sample_covariance_volatility` as the *production* path (pypfopt's
shrinkage is faster and simpler — see comparison); the HHI diversification invariant; all of
`monte_carlo_service.py`; all of `tail_risk_service.py`.

**Regression tests:** `test_riskfolio_adapter.py::test_optimise_weights_sum_to_one`;
`::test_portfolio_and_hcportfolio_return_containers_normalised`; `::test_herc_raises_not_implemented_error`;
`::test_dbht_linkage_raises_not_implemented_error`; `::test_rp_optimization_equal_risk_contributions`
(the real invariant: each asset's contribution to total risk should be ≈ equal);
`::test_entropy_pooling_probabilities_sum_to_one`.

### Risk & caveats

1. **HERC/HERC2 are broken in 7.3.0.** Do not build a product feature on them. Confirmed against source
   on `master`, not just a released wheel.
2. **DBHT clustering is broken on numpy 2.x.** One of the library's two genuinely novel clustering
   contributions is unavailable. Use scipy `linkage` instead.
3. **`vectorbt` (→ numba, plotly, ipywidgets, anywidget, …) is a mandatory install for zero benefit.**
   86 packages vs pypfopt's 34. Override it or use `--no-deps`.
4. **Two optimisation paths are unusably slow.** Measured on 8 assets × 750 days:
   `owa_optimization` = **202 s**; `rm="TG"` (Tail Gini, `a_sim=100` → Monte Carlo *inside* the solve) =
   **36–63 s and highly variable**. Everything else I tested was 0.03–0.12 s. Never expose OWA or TG in a
   synchronous request path. Riskfolio's own CHANGELOG (6.0.0) admits the newer GMD/Tail-Gini/Range
   formulations were introduced precisely to avoid the OWA formulation.
5. **The docs warn `efficient_frontier` is unsafe > 100 assets** with scenario risk measures; use
   `frontier_limits` for the range and sample the frontier separately. FinEngine's portfolio sizes should
   mostly be fine, but the screener can return large universes.
6. **MOSEK is recommended** for RLVaR/RLDaR/Tail-Gini-Range/EVRG/RLVaR-Range and GMD (power cones):
   *"For these models is highly recommended to use MOSEK as solver, due to in some cases CLARABEL cannot
   find a solution and SCS takes too much time to solve them."* MOSEK is **commercial and requires a
   licence**. Without it you are on Clarabel/SCS, which is why `RLVaR` was 7× slower than `MV` in my
   measurements. This is a hidden cost driver.
7. **Single maintainer, bus factor 1**, monetised via book/course/sponsorship. Vendor-fork risk if he
   stops. BSD-3 makes forking legally trivial — which is the mitigation.
8. **no-endorsement clause** — do not put "Riskfolio-Lib" in product marketing copy.
9. **Compiled C++ extension (pybind11 + Eigen + Spectra) in every wheel.** Large binary, no source-only
   install, and `setup.py` pins `setuptools == 78.1.1` exactly. Fine from a wheel; painful if you ever
   need to build. Note also that vendoring pulls in MPL-2.0 Eigen/Spectra.
10. **`assets_stats()` must precede every optimisation**, and the failure mode is terrible. Encapsulate.
11. **Return-type inconsistency**: `Portfolio.optimization()` → DataFrame, `HCPortfolio.optimization()`
    → ndarray, `PE.bootstrapping()` → tuple. Normalise at the adapter.
12. **Invalid enum values fail with confusing errors.** An unknown `codependence` falls through
    `HCPortfolio._hierarchical_clustering`'s if/elif chain and dies with
    `UnboundLocalError: cannot access local variable 'dist'` (`HCPortfolio.py:369`) rather than
    "unknown codependence". I hit this myself. Validate enums in your adapter.

---

## FinQuant

> **AVOID** — MIT-licensed so legally a non-issue, but it is ~3 years unmaintained, its default data
> source (`quandl`) is a dead 2021 package, and it is **provably broken on FinEngine's numpy 2.5.3** — every
> entry point raises `TypeError` before doing any work.

### Verdict

**AVOID.**

Do not adopt, do not vendor, do not fork. FinQuant is a teaching library whose entire
runtime type-validation layer depends on `np.dtype('float64') == np.floating`, a coercion that NumPy
**silently removed**. I proved this with a 2×2 matrix isolating pandas from numpy: it works on
pandas 2.2.3 + numpy 2.1.0, and fails on *both* pandas 3.0.6 and numpy 2.5.3 independently. On top of
that the last commit was 2023-09-03, the last release 2023-09-04, CI only ever tested Python 3.10/3.11,
and its default `data_api="quandl"` pulls a package last released in 2021. It also duplicates functionality
FinEngine already has and does better.

### License

- **Exact license:** MIT License
- **SPDX identifier:** `MIT` (GitHub API `license.spdx_id` = `"MIT"`; PyPI classifier
  `License :: OSI Approved :: MIT License`; `setup.py` `license="MIT"`)
- **Source:** https://github.com/fmilthaler/FinQuant/blob/master/LICENSE.txt

Full text (verbatim):

> Copyright (C) 2019 Frank Milthaler
>
> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
> associated documentation files (the "Software"), to deal in the Software without restriction, including
> without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to
> the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial
> portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
> LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO
> EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
> IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR
> THE USE OR OTHER DEALINGS IN THE SOFTWARE.

- **Commercial use:** explicitly permitted (`and/or sell copies`). No revenue share, no CLA, no
  non-commercial rider.
- **Copyleft:** none. **Not** GPL/LGPL. No source-disclosure obligation.
- **Linking vs vendoring:**
  - *As a PyPI dependency:* keep the notice in `THIRD_PARTY_NOTICES.md`; no other obligation.
  - *Vendoring:* must retain the copyright line and full MIT text.
- **Not a business-source or non-commercial license.** The license is the *least* of FinQuant's problems.
  (Note: the file is named `LICENSE.txt` and begins directly with the copyright line — there is no
  "MIT License" title line, which is a cosmetic SPDX-detection nit only.)

### Maintenance

**Activity: ABANDONED** (in practice; not literally — `archived: false`).

| Fact | Value | Source |
|---|---|---|
| Latest release | **0.7.0**, published **2023-09-04** | https://pypi.org/pypi/FinQuant/json · https://github.com/fmilthaler/FinQuant/releases/tag/v0.7.0 |
| Last commit on `master` | **2023-09-03** — *"Introducing the R-squared coefficient and Treynor Ratio for a financial portfolio (#134)"* | GitHub API commits |
| `pushed_at` | 2023-11-04T08:38:31Z (the only activity after the last `master` commit) | GitHub API repo object |
| Previous release | v0.6.2, 2023-08-17 | GitHub API releases |
| Open issues | **16** | GitHub search API `is:issue is:open` |
| Open PRs | **2** | GitHub search API `is:pr is:open` |
| Archived | `false` | GitHub API |
| Stars | 1,826 | GitHub API |
| Branches | `master`, `develop`, `feature/new-feature`, `feature/rsi-indicator`, `feature/stocks-clustering` | GitHub API |
| Total commits | 508 since 2019-01-20 | repo page |
| CI matrix | `python-version: ['3.10','3.11']` on `ubuntu-latest` only | https://github.com/fmilthaler/FinQuant/blob/master/.github/workflows/pytest.yml |

**Verdict: ABANDONED.** As of 2026-09-27 the last commit is **~3 years old**. There are no releases, no
commits, and no upstream maintenance. All three years of FinEngine-relevant changes in the ecosystem
(pandas 2.1→3.0, numpy 1.x→2.x, scipy private-attribute removals, CVXPY 1.5→1.9) postdate the last commit
and are unaddressed. The `feature/*` branches suggest contributor effort that was never merged.

Notably, its own CI workflow has `continue-on-error: true` on the test, pylint, and mypy steps, and the
`version` file plus `setup.py` read the version from disk at build time — signs of a project in decline
before it stopped.

### Compatibility

| Dimension | Status | Evidence |
|---|---|---|
| Python 3.12 | ⚠️ **Untested** | `python_requires=">=3.10"`, so pip allows 3.12, but classifiers list only `3.10`/`3.11` and CI tests only 3.10/3.11. It *does* import and run on 3.12.9 (verified on a working config) — but nothing upstream guarantees it. |
| **numpy 2.5** | 🛑 **BROKEN — hard blocker** | See 2×2 matrix below. |
| numpy 2.1 | ✅ Works | Verified |
| **pandas 3.0** | 🛑 **BROKEN — independent second blocker** | Verified |
| pandas 2.2 | ✅ Works | Verified |
| quantlib coexistence | ❌ N/A | Would be moot. |
| cvxpy coexistence | ❌ **Does not use cvxpy** | FinQuant solves with `scipy.optimize.minimize(method="SLSQP")`. It would **not** reuse FinEngine's Clarabel/ECOS/OSQP/HiGHS stack — a different, slower, non-convex-capable solver path. |

#### 🛑 Empirical 2×2 matrix — reproduced, isolating pandas from numpy

All four cells: `FinQuant==0.7.0`, `scipy==1.18.0` (A) / `1.13.1` (B), `py3.12.9`, 5 assets × 500 days.

| # | pandas | numpy | scipy | Result |
|---|---|---|---|---|
| **1** | **3.0.6** | **2.5.3** | 1.18.0 | 🛑 **FAIL** — `TypeError: Error: data is expected to be Series, DataFrame with dtype 'floating'` |
| **2** | 2.2.3 | **2.5.3** | 1.18.0 | 🛑 **FAIL** — *same* `TypeError` ⇒ **numpy 2.5 is the culprit, pandas is irrelevant** |
| **3** | **3.0.6** | 2.1.0 | 1.13.1 | 🛑 **FAIL** — *different* `TypeError: Error: names is expected to be List, ndarray with dtype 'str'` ⇒ **an independent pandas-3 bug** |
| **4** | 2.2.3 | 2.1.0 | 1.13.1 | ✅ **ALL PASS** — every `comp_*`, every `ef_*`, `mc_optimisation`, `sma`, `ema` |

Cell 4 output (for reference — this is FinQuant *at its best*):

```
build_portfolio(from df) ok 0.035s
  comp_mean_returns 0.3538 | comp_stock_volatility 0.19138 | comp_weights 0.2
  comp_expected_return 0.23966 | comp_volatility 0.093 | comp_cov 0.00015
  comp_sharpe 2.52328 | comp_var 0.39263 | comp_sortino 2.19245 | comp_downside_risk 0.10703
  ef_minimum_volatility 0.011s | ef_maximum_sharpe_ratio 0.009s
  ef_efficient_return(0.1) 0.028s | ef_efficient_frontier 3.582s
  mc_optimisation(200) 0.097s   MC 1000 trials took 0.465s
```

#### Root cause (exact)

`finquant/type_utilities.py` defines a whitelist of argument types, and `data` is declared as
floating-typed (line 117):

```python
type_dict = {
    # DataFrames, Series, Array:
    "data": ((pd.Series, pd.DataFrame), np.floating),     # <-- line 117
    ...
}
```

and `_check_type` validates element dtype with (lines 66-69):

```python
if isinstance(arg_values, pd.DataFrame) and not all(
    arg_values.dtypes == element_type
):
    validation_failed = True
```

The whole thing hinges on `np.dtype('float64') == np.floating`. Probed directly:

| | `df.dtypes == float` | `df.dtypes == np.floating` | `np.dtype('float64') == np.floating` |
|---|---|---|---|
| numpy 2.1.0 | True | **True** (with `DeprecationWarning: Converting np.inexact or np.floating to a dtype is deprecated`) | **True** |
| numpy 2.5.3 | True | **False** | **False** |

NumPy deprecated this coercion and then removed it. Because `element_type` is the *abstract* type
`np.floating` rather than a concrete dtype, **every** DataFrame/Series input now fails validation — so
FinQuant raises `TypeError` at the very first call, for every function, forever. One-line upstream fix
(`np.floating` → `np.float64`), but upstream is dead.

The pandas-3 failure in cell 3 is a **separate** defect in the sibling `names` validation
(`type_dict["names"] = ((List, np.ndarray), str)`, checked with `isinstance(arg_values, List) and not
all(isinstance(val, str) …)`) — a `pd.Index` is neither `typing.List` nor `np.ndarray`, so it falls
through every branch and sets `validation_failed = True`.

#### Additional issues found (version-independent)

- **Default data source is dead.** `build_portfolio(data_api="quandl")` is the default, and
  `requirements.txt` hard-pins `quandl>=3.4.5`. `quandl` 3.7.0 was last released **2021-11-11**, has
  classifiers only up to Python 3.8, and is superseded by `nasdaq-data-link`. It does *import* on
  3.12 (verified), but the API it calls is retired.
- **`comp_beta`, `comp_treynor`, `comp_rsquared` all raise** `TypeError: unsupported operand type(s) for
  *: 'NoneType' and 'float'` when `market_index` is not set — which is the default. So three of the
  headline "Analysis" metrics in the README simply do not work out of the box.
- **No `py.typed` / no type-checking of consumers**; it is `mypy --strict`-clean internally only.

### Dependency footprint

`requirements.txt` / `setup.py` `install_requires` (identical; also in PyPI `requires_dist`):

```
numpy>=1.22.0   scipy>=1.2.0   pandas>=2.0   matplotlib>=3.0
quandl>=3.4.5   yfinance>=0.1.43   scikit-learn>=1.3.0
```

**New-to-FinEngine packages: exactly one — `quandl`.** And it is the worst possible one: a 2021
dead package that FinQuant does not even use unless you keep the default `data_api`. (Measured install:
`Installed 41 packages` in the equivalent env, vs 34 for pypfopt and 86 for Riskfolio.)

| Package | Status | Assessment |
|---|---|---|
| `quandl` | **NEW, and dead** | Last release 2021-11-11; py≤3.8 classifiers; API retired. **Do not install.** |
| `yfinance` | already installed | Reused |
| `numpy`/`scipy`/`pandas`/`matplotlib`/`scikit-learn` | already installed | Reused (but see compatibility) |

**No upper bounds** on numpy or pandas, so `pip install FinQuant` cheerfully pulls pandas 3.0.6 and
numpy 2.5.3 into FinEngine's environment and then crashes. There is no resolver-level protection.

### API surface

Read from `finquant/*.py` on `master`.

```python
from finquant.portfolio import build_portfolio, Portfolio
from finquant.stock import Stock
from finquant.efficient_frontier import EfficientFrontier
from finquant.monte_carlo import MonteCarlo, MonteCarloOpt
from finquant import returns, moving_average
```

| Class / function | Signature | Solves |
|---|---|---|
| `build_portfolio` | `build_portfolio(pf_allocation=None, names=None, start_date=None, end_date=None, data=None, data_api="quandl", market_index=None)` → `Portfolio` | Build from a DataFrame, or download. ⚠️ raises an explicit `ValueError` listing unsupported kwargs — my first two attempts failed this way |
| `Portfolio` | `Portfolio()` — no-arg constructor | Mutable portfolio object |
| ↳ `.add_stock(stock, defer_update=False)` | | Add a `Stock` |
| ↳ `.comp_mean_returns(freq=252)` | → `pd.Series` | Annualised mean return per stock |
| ↳ `.comp_stock_volatility(freq=252)` | → `pd.Series` | Annualised vol per stock |
| ↳ `.comp_weights()` | → `pd.Series` | Allocation weights |
| ↳ `.comp_expected_return(freq=252)` | → float | Portfolio expected return |
| ↳ `.comp_volatility(freq=252)` | → float | Portfolio vol |
| ↳ `.comp_downside_risk(freq=252)` | → float | Downside risk |
| ↳ `.comp_cov()` | → `pd.DataFrame` | Covariance matrix |
| ↳ `.comp_sharpe()` | → float | Sharpe |
| ↳ `.comp_var()` | → float | Historical VaR at `var_confidence_level` |
| ↳ `.comp_sortino()` | → float | Sortino |
| ↳ `.comp_beta()` / `.comp_treynor()` / `.comp_rsquared()` | → `Optional[float]` | ⚠️ **need `market_index`; raise otherwise** |
| ↳ `.comp_cumulative_returns()` | → `pd.DataFrame` | Cumulative returns |
| ↳ `.ef_minimum_volatility(verbose=False)` | → DataFrame | Min-vol weights |
| ↳ `.ef_maximum_sharpe_ratio(verbose=False)` | → DataFrame | Tangency weights |
| ↳ `.ef_efficient_return(target, verbose=False)` | → DataFrame | Min vol at target return |
| ↳ `.ef_efficient_volatility(target)` | → DataFrame | Max Sharpe at target vol |
| ↳ `.ef_efficient_frontier(targets=None)` | → ndarray | ⚠️ **3.58 s for 5 assets** |
| ↳ `.mc_optimisation(num_trials=1000)` | → `(DataFrame, DataFrame)` | MC weight search (0.465 s / 1000 trials) |
| ↳ `.properties()` | → None | **Prints** a summary table to stdout |
| `EfficientFrontier` | `EfficientFrontier(mean_returns, cov_matrix, risk_free_rate=0.005, freq=252, method="SLSQP")` | **`scipy.optimize` SLSQP, not cvxpy** |
| `returns.cumulative_returns(data, dividend=0)` | → DataFrame | (p_t − p_0 + d) / p_0 |
| `returns.daily_returns(data)` | → DataFrame | `data.pct_change()` |
| `returns.daily_log_returns(data)` | → DataFrame | Log returns |
| `returns.historical_mean_return(data, freq=252)` | → `pd.Series` | Arithmetic mean annualised |
| `returns.weighted_mean_daily_returns(data, weights)` | → ndarray | Weighted mean daily return |
| `moving_average.sma(data, span=100)` / `.ema(...)` | → DataFrame | Moving averages |
| `moving_average.compute_ma(data, fun, spans, plot=True)` | → DataFrame | MA band + buy/sell signals |
| `moving_average.plot_bollinger_band(data, fun, span=100)` | → None | Bollinger bands |

### Overlap with FinEngine

| FinEngine file / function | FinQuant equivalent | Effort | Risk |
|---|---|---|---|
| `analytics_engine.py::quantstats_ratio_statistics` (L1053) — sharpe/sortino/omega/cagr/max_drawdown/calmar | `pf.comp_sharpe()`, `comp_sortino()`, … | **M** | **High value of "no"** — FinEngine already uses `quantstats` (installed) and has estimation-uncertainty disclosure FinQuant lacks |
| `analytics_engine.py::engine_risk_statistics` (L1190) — incl. `var_95` (L1232) / `cvar_95` (L1235) | `pf.comp_var()` (historical VaR only) | **M** | FinEngine's parametric + historical + EVT VaR/ES is strictly superior. FinQuant offers **no ES/CVaR at all**. |
| `optimization_service.py::_min_vol` (L619) / `_max_sharpe` (L632) | `pf.ef_minimum_volatility()` / `ef_maximum_sharpe_ratio()` | **M** | High — FinQuant's SLSQP is non-convex-capable, slower, and less precise than FinEngine's existing cvxpy solve |
| `optimization_service.py::_min_cvar` (L652) | **none** | — | FinQuant has no CVaR optimisation |
| `optimization_service.py::_hrp_weights` (L549) | **none** | — | FinQuant has no HRP |
| `optimization_service.py::_black_litterman` (L670) | **none** | — | FinQuant has no Black-Litterman |
| `analytics_engine.py::_sample_covariance_volatility` (L2347) | `pf.comp_cov()` | **M** | FinQuant is plain sample covariance — a *downgrade*. No shrinkage, no Ledoit-Wolf, no OAS, no denoising. |
| `analytics_engine.py` inverse-vol risk parity (L2399–2674) | `pf.comp_weights()` (equal or investment-weighted) | **M** | Not a substitute — FinQuant has no risk-parity machinery |
| `monte_carlo_service.py::simulate_goal` (L327) | `pf.mc_optimisation(num_trials)` | **L** | **Clear regression.** FinQuant's MC searches *weights* by brute force; FinEngine's does goal-probability forward simulation with Student-t, bootstrap, GBM and checkpoint fan-out. Replacing would be a large functional loss. |
| `indicators_service.py` (technical indicators) | `moving_average.sma/ema`, `compute_ma`, `plot_bollinger_band` | **S** | Genuinely redundant, and FinEngine has `stockstats` + `bfinance` installed, which cover a superset |
| `analytics_engine.py::market_model_statistics` (L1155) | `pf.comp_beta()` + market index | **M** | Redundant, and FinQuant's version crashes without `market_index` |
| ADV, days-to-liquidate, Amihud illiquidity | **none** | — | FinQuant has no liquidity analytics |
| GARCH, EVT-POT, copula tail dependence, correlation regime breaks, cointegration pairs, HMM regimes, volatility cone, benchmark comparison, screener | **none** | — | Entirely out of scope |

**Summary: ~90 % of FinQuant's surface duplicates something FinEngine already has, and the remaining
10 % is weaker. FinQuant offers exactly one thing FinEngine lacks — moving-average bands and Bollinger
plots — which `stockstats` already covers.**

### Implementation guide

**There is no implementation guide. Do not add a line to `backend/pyproject.toml`.**

If a future requirement makes FinQuant look attractive anyway, the minimum viable shim would be:

```python
# backend/app/utils/finquant_numpy2_compat.py
"""DO NOT ENABLE. Documents the exact blocker, in case this is revisited.

FinQuant 0.7.0 (last release 2023-09-04) fails on numpy >= 2.2 because
finquant/type_utilities.py:117 declares
    "data": ((pd.Series, pd.DataFrame), np.floating)
and _check_type (type_utilities.py:66-69) asserts
    all(df.dtypes == element_type)
NumPy removed the coercion of the abstract type np.floating to a dtype
(np.dtype("float64") == np.floating is False on 2.5.3, True on 2.1.0),
so every DataFrame/Series argument is rejected with
    TypeError: Error: data is expected to be Series, DataFrame with dtype 'floating'
Reproduced on py3.12.9 / pandas 3.0.6 / numpy 2.5.3 and on py3.12.9 /
pandas 2.2.3 / numpy 2.5.3. Additionally FinQuant's `names` validation
fails independently on pandas 3.0.6.
Upstream is unmaintained, so a fork would be required.
"""
import numpy as np

def finquant_dtype_check_would_pass() -> bool:
    return np.dtype("float64") == np.floating   # False on FinEngine's numpy 2.5.3
```

Do not add this. Recording it here so the next person does not re-investigate.

### Risk & caveats

1. **Broken on FinEngine's numpy.** Every entry point raises `TypeError` immediately. Verified in a 2×2
   matrix isolating pandas from numpy.
2. **~3 years abandoned.** Last commit 2023-09-03, last release 2023-09-04, no CI beyond 3.10/3.11.
3. **Dead default dependency.** `quandl` (2021) is a hard install requirement and the default data source.
4. **Does not use cvxpy.** SLSQP via `scipy.optimize`. FinEngine's Clarabel/ECOS/OSQP/HiGHS stack is
   bypassed.
5. **Slow and brute-force.** `ef_efficient_frontier()` = 3.58 s for **5** assets (Python loop calling SLSQP
   per target return). `mc_optimisation` is a Python loop (`monte_carlo.py:45`, `result.append(res)`).
6. **Three headline metrics crash by default** (`comp_beta`, `comp_treynor`, `comp_rsquared` need
   `market_index`).
7. **No CVaR/ES, no Black-Litterman, no HRP, no covariance shrinkage, no liquidity analytics** — the
   things FinEngine actually differentiates on.
8. **No upper bounds on numpy/pandas**, so installing it into FinEngine's env silently pulls pandas 3 and
   numpy 2.5 and then crashes. There is no resolver-level guard.
9. **Prints to stdout** (`.properties()`, `.mc_properties()`) — unusable in a FastAPI service without capture.
10. **Sole maintainer** (`fmilthaler`), effectively inactive.

---

## Cross-library comparison

| | **PyPortfolioOpt** | **Riskfolio-Lib** | **FinQuant** |
|---|---|---|---|
| **Verdict** | **ADOPT_PARTIAL** | **EVALUATE_LATER** | **AVOID** |
| License | MIT | BSD-3-Clause | MIT |
| SPDX | `MIT` | `BSD-3-Clause` | `MIT` |
| Commercial use | ✅ permitted | ✅ permitted | ✅ permitted |
| Copyleft / GPL | ❌ none | ❌ none (no-endorsement clause only) | ❌ none |
| **Last commit** | 2026-07-07 | **2026-09-24** | 2023-09-03 |
| Latest version | **1.6.0 (2026-02-26)** | **7.3.0 (2026-05-31)** | 0.7.0 (2023-09-04) |
| **Activity** | ACTIVE (slow cadence, 1–2 maintainers) | **ACTIVE** (bus factor 1) | **ABANDONED** (~3 yr) |
| Open issues / PRs | 84 / 32 | **9 / 8** | 16 / 2 |
| Archived | no | no | no |
| Python 3.12 | ✅ (3.10–3.14) | ✅ (3.10–3.14) | ⚠️ untested (CI 3.10/3.11 only) |
| **pandas 3.0** | ✅ **explicitly supported in 1.6.0** | ✅ works (verified) | 🛑 **broken** |
| **numpy 2.x** | ✅ works (verified) | ✅ works (verified, 1 DBHT path broken) | 🛑 **broken on ≥2.2** |
| scipy 1.18 | ⚠️ **HRP broken** (`_LINKAGE_METHODS` removed) | ✅ works | n/a |
| **Verified on FinEngine's stack** | ✅ **full workflow** | ✅ core paths (2 upstream bugs) | 🛑 **fails immediately** |
| Solver | cvxpy (reuse FinEngine's) | cvxpy (reuse FinEngine's; MOSEK needed for some) | `scipy.optimize` SLSQP (no reuse) |
| Direct deps | 6 | 14 | 7 |
| **Packages installed (measured)** | **34** | **86** | 41 |
| New packages | 1 (`scikit-base`, pure-Python) | 8+ incl. `vectorbt`→`numba`, `plotly`, `astropy`, `networkx`, `xlsxwriter` | 1 (`quandl`, dead) |
| Compiled ext shipped | no | yes (pybind11+Eigen+Spectra) | no |
| **Hard blockers** | `HRPOpt` on scipy 1.18 | `HERC`/`HERC2` 100% broken; DBHT on numpy 2 | **numpy 2.5 — everything broken** |
| Silent API breaks | ⚠️ `portfolio_performance()` dict→tuple in 1.6.0 | ⚠️ DataFrame vs ndarray vs tuple returns | — |
| Core perf | ~30 ms/solve; `ledoit_wolf` **7.0 s**; `min_cov_det` 1.6 s (deprecated) | 0.036 s @10 → 0.366 s @200 assets; `owa` **202 s**; `TG` 36–63 s | `ef_efficient_frontier` **3.58 s @5**; MC 1000 = 0.465 s |
| Risk measures | MV, semivariance, CVaR, CDaR | **26 convex** + ranges + drawdown | MV only (+ historical VaR) |
| Covariance estimators | sample, exp, semi, **Ledoit-Wolf ×3, OAS**, MCD | 14 incl. ledoit, oas, gl, jlogo, fixed, spectral, shrink, gerber | sample only |
| HRP | ✅ (broken on scipy 1.18) | ✅ HRP + NCO; ❌ HERC | ❌ |
| Black-Litterman | ✅ `BlackLittermanModel` | ✅ BL, BL Bayesian, augmented BL, factors | ❌ |
| Entropy pooling | ❌ | ✅ (7.3.0) | ❌ |
| Brinson attribution | ❌ | ✅ | ❌ |
| MVSK / higher moments | ❌ | ✅ (7.3.0) | ❌ |
| Discrete allocation | ✅ `greedy_portfolio` / `lp_portfolio` | ❌ | ❌ |
| Turnover / TE objectives | ✅ | ✅ constraints | ❌ |
| **Best for** | **Replacing hand-rolled mean-variance + adding shrinkage to FinEngine today** | Advanced research features (entropy pooling, uncertainty sets, MVSK, Brinson) once 7.4 fixes HERC/DBHT | Nothing |
| Weight to add to `pyproject.toml` | **+1 line, 1 pure-Python dep** | +1 line **plus a `vectorbt` override** | **none** |
| Migration effort | **M** (mostly M, some S) | L | n/a |
| Overall risk if adopted | **Low** | **Medium** | **High (currently unusable)** |

---

## Recommended adoption order

### 1️⃣ HIGHEST ROI — Add PyPortfolioOpt for **covariance shrinkage only** (do this first)

`backend/pyproject.toml`: add `"pyportfolioopt>=1.6.0,<2.0",` after line 36 (`"cvxpy>=1.6.0",`), then
`uv sync --extra dev --group dev`.

Then route **only** `analytics_engine.py::_sample_covariance_volatility` (L2347) through
`risk_models.CovarianceShrinkage(...).ledoit_wolf()` (or `.oracle_approximating()`, 0.015 s vs
`ledoit_wolf`'s 7.0 s).

**Why this is the single highest-ROI change of the three libraries:** the sample covariance matrix is
unbiased but has high estimation error, and mean-variance optimisation is *specifically* the procedure
that converts estimation error into a bad portfolio by overweighting the noisiest estimated
correlations. FinEngine runs a full convex optimiser on a plain sample covariance. Ledoit-Wolf shrinkage
is the textbook fix, costs 0.055 s in Riskfolio / is a thin `sklearn` call in pypfopt, needs **no new
packages beyond the one line above**, and has **zero blockers** on FinEngine's stack. The observable
effect is that weights stop concentrating in illiquid small caps and stop flipping between rebalances.
Everything else on this list is a feature; this one is a correctness fix.

Prefer `oracle_approximating()` if the 7 s `ledoit_wolf()` grid search is unacceptable inline — cache on
`(asset tuple, window end, frequency)` either way.

### 2️⃣ Downside-risk frontiers + regularisation/turnover (PyPortfolioOpt)

`optimization_service.py`: `_min_cvar` (L652) → `EfficientCVaR.min_cvar()`; add
`EfficientSemivariance` and `EfficientCDaR`; add `objective_functions.L2_reg` to kill zero-weight
explosion; add `objective_functions.transaction_cost` for turnover control; add
`max_position` / group caps via `weight_bounds` + `add_constraint`.

**Why:** turns FinEngine's single-objective optimiser into a menu an institutional user actually needs,
and FinEngine currently has **no** downside-risk optimisation at all. Same 1-line dependency from step 1 —
this is pure incremental ROI on an install you already justified. Remember the `max_sharpe()` +
`add_objective()` warning: switch the objective to `min_volatility()`/`efficient_return()` when
regularisation must bind.

### 3️⃣ Turn continuous weights into tradeable instructions (PyPortfolioOpt `DiscreteAllocation`)

`allocations.py::build_trade_instructions` (L563) ← `DiscreteAllocation.greedy_portfolio()`, with
`lp_portfolio()` for optimal cash residual.

**Why:** closes the gap between "target weights" and "orders you can actually send". **Mandatory caveat:**
wrap it, don't adopt it bare — pypfopt has no concept of NSE/BSE **lot sizes**, so floor to lot size
afterwards and preserve FinEngine's `half_up_to` / `resolve_notional_floor` logic.

### 4️⃣ Tracking-error-constrained optimisation (PyPortfolioOpt) — `benchmark_service.py`

`objective_functions.ex_ante_tracking_error` / `ex_post_tracking_error`. FinEngine compares against
benchmarks but cannot *optimise* against them. Same dependency.

### 5️⃣ Re-evaluate Riskfolio-Lib at 7.4.x — then take entropy pooling + uncertainty sets

Revisit only after `HERC`/`HERC2` and `DBHT` are fixed. When you do, land the `vectorbt` override
**first**, then add `entropy_pooling_stats` and `PE.bootstrapping` as new endpoints. Both compose
naturally with FinEngine's existing `measure_estimate_uncertainty` disclosure and are the only genuinely
novel quant capability any of these three libraries offers.

### 6️⃣ Never — FinQuant

---

## What NOT to adopt, and why

| Do not adopt | Library | Reason |
|---|---|---|
| **FinQuant, in any form** | FinQuant | **Provably broken on FinEngine's numpy 2.5.3** — every entry point raises `TypeError` at argument validation. Proven by a 2×2 pandas×numpy matrix. Also ~3 years abandoned, defaults to the dead `quandl` (2021), bypasses FinEngine's cvxpy/solver stack, and duplicates functionality FinEngine already has (and has better, via `quantstats` + `statsmodels` + `arch`). Adopting it would be a net capability **loss**, not a gain. |
| **`HRPOpt`** | PyPortfolioOpt | Reads `scipy.cluster.hierarchy._LINKAGE_METHODS`, a private attribute **removed in scipy 1.18.0** — FinEngine's exact pin. Every call raises `AttributeError`. FinEngine's own `_hrp_weights()` works today, so migrating would be a pure regression. |
| **`vectorbt`** (as a transitive dep) | Riskfolio-Lib | Hard `install_requires` entry that Riskfolio **never imports** (verified across all 12 `riskfolio/src/` modules). Drags in `numba`, `plotly`, `ipywidgets`, `anywidget`, `dill`, `tqdm`, `dateparser`, `imageio`, `schedule`, `requests`, `pytz` — 86 packages vs 34. Override it or never install. |
| **`owa_optimization` and `rm="TG"`** | Riskfolio-Lib | **202 s** and **36–63 s** respectively for 8 assets, measured. Monte Carlo *inside* the solve loop. Unusable in a synchronous FastAPI request. |
| **`HERC` / `HERC2` models** | Riskfolio-Lib | 100 % broken in 7.3.0 — `HCPortfolio.py:1095` passes `linkage`/`upper_bound`/`lower_bound` to a method whose signature (`HCPortfolio.py:522`) accepts only `(self, Z, rm, rf, model)`. Advertised headline feature, non-functional. |
| **`linkage="DBHT"` clustering** | Riskfolio-Lib | `ValueError`/`TypeError` on numpy 2.x at `DBHT.py:491` (`Pred[n] = Parents[a]`) — NumPy removed implicit size-1-array→scalar conversion. |
| **`min_cov_determinant`** | PyPortfolioOpt | Deprecated; still ships with a stale warning naming the already-passed version `v1.5`. 1.6 s for a 6×6 matrix. |
| **`pyportfolioopt[all_extras]`** | PyPortfolioOpt | Pulls `plotly` and `cvxopt` for no benefit. FinEngine already has matplotlib and renders its own charts. |
| **MOSEK as a dependency** | Riskfolio-Lib | Commercially licensed. Riskfolio's own docs say it is *"highly recommended"* for RLVaR/RLDaR/Tail-Gini-Range/GMD. Adopting those risk measures silently creates a **paid licence** dependency. Clarabel/SCS — which FinEngine already has — are the only free path, and they are the reason `RLVaR` measured 7× slower than `MV`. |
| **Replacing FinEngine's inverse-volatility-to-target-volatility allocation** | Riskfolio-Lib | `rp_optimization` is a better risk-budgeting kernel, but FinEngine's specific *scale-inverse-vol-to-a-target-volatility* behaviour has no library equivalent. Keep the scaling; consider swapping only the kernel, and only after step 5. |
| **Replacing `monte_carlo_service.py`** | All three | FinEngine's Student-t / bootstrap / GBM forward simulation with checkpoint fan-out answers "what is the probability I hit my goal". FinQuant's `mc_optimisation` and Riskfolio's `bootstrapping` answer a different question (uncertainty about mean/covariance). FinQuant's version is strictly worse for FinEngine's purpose. |
| **Replacing the HHI diversification invariant** | Riskfolio-Lib (`RF.NEA`) | FinEngine's `AGENTS.md` mandates: single-holding portfolio ⇒ diversification score renders exactly `0%`. `NEA(w)` is a different quantity and will not honour that rule. Keep FinEngine's. |
| **Vendoring any of the three** | All | All three are permissive (MIT/BSD-3) and all three are *importable dependencies*. Vendoring buys nothing and costs you upstream fixes. The only argument for vendoring Riskfolio is the bus-factor-1 risk — and if you ever do, remember the compiled extension pulls in MPL-2.0 Eigen and Spectra. |
| **The estimation-uncertainty disclosure stack** | All | `analytics_engine.py::measure_estimate_uncertainty` (L793), `effective_sample_size` (L608), `optimizer_estimate_uncertainty` (L213), `no_estimate_uncertainty` (L286), `moving_block_size` (L661) are a **genuine differentiator** that none of these libraries has. Do not let an adoption PR weaken or bypass them. |

---

## Verification appendix — reproducibility

Every measurement above was produced with `uv run --no-project --python 3.12` in throwaway environments.
No FinEngine source file, lockfile, or virtualenv was modified. Scripts live in
`C:\Users\Sayanti\AppData\Local\Temp\opencode\`:

| Script | Purpose |
|---|---|
| `smoke_pypfopt.py` | Full pypfopt 1.6.0 workflow on py3.12.9 / pandas 3.0.6 / numpy 2.5.3 |
| `smoke_finquant.py` | FinQuant 0.7.0 across a 2×2 pandas×numpy matrix |
| `smoke_riskfolio.py`, `smoke_riskfolio3.py`, `smoke_riskfolio4.py` | Riskfolio 7.3.0; v4 uses only documented-valid enum values |
| `smoke_hrp_scipy.py`, `smoke_hrp_tb.py`, `smoke_hc_tb.py` | scipy 1.18 / HRP / HCPortfolio failure isolation |
| `probe_pandas3.py` | `np.dtype('float64') == np.floating` across numpy 2.1.0 vs 2.5.3 |

Sources for non-executable facts (licensing, maintenance, versions): GitHub REST API
`repos/*` + `releases` + `commits`, PyPI JSON API `/pypi/<pkg>/json`, the repositories' `LICENSE`/
`pyproject.toml`/`setup.py`/`requirements.txt`/`CHANGELOG.rst`/CI workflow files, and Context7
(`/pyportfolio/pyportfolioopt`, `/dcajasn/riskfolio-lib`, `/fmilthaler/finquant`) for API grounding.
**Licensing was taken from the `LICENSE` files, not from Context7.** Issue-tracker cross-references for
the two upstream bugs are **UNVERIFIED** (GitHub API rate limit + JS-gated HTML search) — the
reproductions above are first-hand and stand on their own.
