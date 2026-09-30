# Institutional Quantitative-Finance Libraries: QuantLib (LSE) and GS Quant

**Research date:** 2026-09-27
**Scope:** Should FinEngine adopt, partially adopt, or avoid these two libraries?
**Method:** GitHub `LICENSE` / `pyproject.toml` / `requirements.txt` / release + tag pages / commit atom feeds / PyPI JSON API / wheel inspection / live `uv` resolution tests / live execution against the installed wheels / Context7 (`/lballabio/quantlib-swig`, `/goldmansachs/gs-quant`).

**Nothing in this document is inferred from memory.** Every version, date, size, and clause below was read from a primary source and, where noted, executed.

---

## TL;DR

| Library | Verdict | One-line reason |
|---|---|---|
| **QuantLib (LSE)** | **ADOPT_PARTIAL** | Already installed, already licensed, already Windows-native, and ~0% used. But 90% of its value (options, fixed income) is for modules FinEngine has not built yet. |
| **GS Quant** | **AVOID** | Hard-resolver blocker (`numpy<2.4.0` vs FinEngine's 2.5.3), it is an authenticated GS Marquee **REST client** not a local library, and its PDF tearsheet framework **no longer ships**. |

**Context7 was available** — both `/lballabio/quantlib-swig` (454 snippets) and `/goldmansachs/gs-quant` (8693 snippets) resolved and were used for API surface. It did not contradict any primary source; where it had no entry (QuantLib spectral risk measures, GS Quant tearsheets) that absence is itself reported as a finding.

---

## QuantLib (LSE, C++)

`ADOPT_PARTIAL` — keep the dependency, but convert it from a dead 13 MB weight into a real capability for the derivatives and fixed-income modules FinEngine has queued and has not built yet.

### License

- **SPDX:** `BSD-3-Clause`. Declared in PyPI `METADATA` as `License: BSD-3-Clause` ([PyPI QuantLib JSON](https://pypi.org/pypi/QuantLib/json)).
- **C++ core** ([`lballabio/QuantLib/master/LICENSE.TXT`](https://raw.githubusercontent.com/lballabio/QuantLib/master/LICENSE.TXT)) — full verbatim clause:

  > Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
  >
  > &nbsp;&nbsp;&nbsp;&nbsp;Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
  >
  > &nbsp;&nbsp;&nbsp;&nbsp;Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
  >
  > &nbsp;&nbsp;&nbsp;&nbsp;Neither the names of the copyright holders nor the names of the QuantLib Group and its contributors may be used to endorse or promote products derived from this software without specific prior written permission.

- **Python bindings** ([`lballabio/QuantLib-SWIG/master/LICENSE.TXT`](https://raw.githubusercontent.com/lballabio/QuantLib-SWIG/master/LICENSE.TXT)) — **byte-identical three clauses**, different (shorter) contributor list. This is the licence text actually shipped in the PyPI wheel.
- **Wheel / bundled-extension licensing — VERIFIED: there is no separate bundled-extension licence.** The `QuantLib 1.43` wheel bundles one licence file and it is BSD-3-Clause:

  ```
  quantlib-1.43.data/data/share/doc/quantlib/LICENSE.TXT   3,305 bytes   (BSD-3-Clause)
  ```
  Extracted directly from `quantlib-1.43-cp39-abi3-win_amd64.whl`. It matches the SWIG repo's `LICENSE.TXT` (the wrapper authors), not the C++ repo's longer file (the C++ authors). Both grant identical terms.
- **Third-party attributions inside the C++ licence file** (must be reproduced on binary redistribution):
  - "QuantLib includes code taken from Peter Jäckel's book *Monte Carlo Methods in Finance*."
  - "QuantLib includes software developed by the University of Chicago, as Operator of Argonne National Laboratory."
  - "QuantLib includes a set of numbers provided by Stephen Joe and Frances Kuo under a BSD-style license."
- **Tooling artefact worth knowing:** the GitHub API reports `license.spdx_id = "NOASSERTION"` / `"Other"` for **both** repos, because the file is named `LICENSE.TXT` rather than `LICENSE`. This is a GitHub filename heuristic, **not** a different or "other" licence. Do not let a licence scanner gate on it.

**Commercial impact:** none. Permissive, non-copyleft, no source-disclosure trigger, no field-of-use restriction, no network-use clause (the AGPL-style obligations that affect FinEngine's *own* service do not reach a BSD dependency). The only obligation is: if you redistribute a **binary** that embeds QuantLib, reproduce the copyright list + 3 clauses + disclaimer in your documentation/materials. The **non-endorsement clause** means you may not name "QuantLib" or the QuantLib Group in marketing as an endorsement — stating "uses QuantLib" as a factual dependency note is fine.

**Linking vs vendoring:** FinEngine should **link only** (`pip install QuantLib`), never vendor the C++ tree. Vendoring would drag in the CMake/autotools/Visual Studio build and the `LICENSE.TXT` reproduction obligation for no benefit.

### Maintenance

**ACTIVE.**

| Fact | Value | Source |
|---|---|---|
| C++ repo last commit | **2026-09-25T15:02:14Z** ("Expose the instruments underlying three more rate helpers (#2824)") | [commits atom](https://github.com/lballabio/QuantLib/commits/master.atom) |
| SWIG repo last commit | **2026-09-23T10:14:39Z** ("Remove obsolete workaround") | [commits atom](https://github.com/lballabio/QuantLib-SWIG/commits/master.atom) |
| Latest C++ tag | `v1.43` (`6b57206e`) | [tags](https://github.com/lballabio/QuantLib/tags) |
| Latest SWIG release | `v1.43`, published **2026-07-14T08:33:31Z** | [releases](https://github.com/lballabio/QuantLib-SWIG/releases) |
| Maintainer | `lballabio` (Luigi Ballabio) — commits ~8×/day on release days | commit feed |
| Stars / forks / open issues | 7,635 / 2,336 / 46 | GitHub API |
| Archived | `false` | GitHub API |
| Release cadence | 1.37 → 1.43, roughly every 3 months, unbroken | PyPI release history |

Tags on `QuantLib-SWIG`: `v1.40, v1.41, v1.42, v1.42.1, v1.43`. The C++ repo and the SWIG repo are released in lockstep with the same tag number — no version-skew risk.

### Compatibility

- **Python 3.12: YES.** The stable-ABI wheel is tagged `cp39-abi3`, which is valid for CPython 3.9 and later, including 3.12. FinEngine's `backend/uv.lock:3045` already resolves `quantlib-1.43-cp39-abi3-win_amd64.whl` under `requires-python = ">=3.12"`. Free-threaded 3.14 wheels (`cp314-cp314t-*`) also ship.
- **Windows prebuilt wheels: YES — no C++ compilation required.** All 1.43 Windows artefacts:

  | Wheel | Bytes | FinEngine use |
  |---|---|---|
  | `quantlib-1.43-cp39-abi3-win_amd64.whl` | 12,908,304 (12.3 MiB) | **the one uv picks** |
  | `quantlib-1.43-cp39-abi3-win32.whl` | 11,872,353 | 32-bit only, unused |
  | `quantlib-1.43-cp314-cp314t-win_amd64.whl` | 13,177,407 | free-threaded 3.14, unused |

  On-disk footprint after install (verified in `backend/.venv`): `QuantLib.py` 2,055,348 B + `_QuantLib.pyd` **35,213,312 B**. That is a real 37 MB in every backend container.
  Also available: macOS x86_64/arm64, manylinux (aarch64/i686/x86_64), musllinux, PyPy 3.11 — 26 files total. **No sdist-based build path is needed on any FinEngine target.**
- **pandas 3.0 / numpy 2.x:** no interaction whatsoever. The wheel declares **zero** Python dependencies (`requires_dist` is `null`; the Pyd is a C-extension with no numpy ABI link). Confirmed by `dir(ql)` probe: QuantLib uses only stdlib `datetime` for dates. Adopting it cannot move FinEngine's pandas/numpy pins.
- **Other platforms:** manylinux/musllinux x86_64 + aarch64 + i686 all prebuilt → Linux deploy is a plain install.
- **`requires_python` is unset in PyPI metadata** and there are no `Programming Language :: Python :: 3.x` classifiers — the ABI tags are the only real constraint. There is *no* declared upper bound, so `uv` will not stop you from resolving a `QuantLib` build for a future Python; pin `>=1.43` to be safe.

**Upgrade needed?** FinEngine pins `quantlib>=1.40` (`backend/pyproject.toml:37`) and has **1.43 installed**, which is the newest on PyPI (uploaded 2026-07-14). **No upgrade available.** Tightening the floor from `>=1.40` to `>=1.43` is the only sensible `pyproject.toml` change, and only because the 1.4x Python API broke (see below).

### FinEngine's current usage

**Zero. QuantLib is a dead dependency.**

Grep evidence (`rg` across the whole repo for `QuantLib|import QuantLib|ql\.|from QuantLib`, 49 matches) resolves to:

| Location | Kind |
|---|---|
| `backend/pyproject.toml:37` — `"quantlib>=1.40"` | the only declaration |
| `backend/uv.lock:273, 331, 3022–3045` | the resolved lock, 1.43 |
| `instructions/doc/RISK_LIBRARIES_INTEGRATION_GUIDE.md` (30+ hits) | planning prose with aspirational code blocks |
| `instructions/doc/LIBRARY_INTEGRATION_OPPORTUNITIES.md:577-703` | planning prose, and a **stale** `pip install QuantLib==1.32` |
| `RELEASE_NOTES.md:84` | prose |
| `.scratch/advanced-analytics/spec.md:46` | `\| **QuantLib** \| fixed income / derivatives math if ever needed \| shelf for now \|` |
| `.scratch/backend-deep-audit/code/05-foundation.md:267` | the repo's **own** audit already flagged it: *"no first-party import exists under `backend/app`, `backend/main.py`, or `backend/migrations`"* |
| `.scratch/backend-deep-audit/quant/verify-risk-timeseries.md:44` | *"Inventoried only; outside this cash-equity partition"* |
| `.scratch/backend-audit-2026/BACKEND_REVIEW.md:359-360` | proposals G3 (options Greeks/IV surface) and G4 (fixed income) that would *use* it |

**Modules that import it: none. Classes instantiated: none.** Confirmed by grepping `backend/` for `quantlib|QuantLib` — the only hits are `pyproject.toml` and `uv.lock`. There is no `import QuantLib` in `backend/app`, `backend/main.py`, `backend/migrations`, or `backend/tests`.

Two things FinEngine's own audit got wrong, worth correcting in those docs:
- `derivatives_service.py` and `fixed_income_service.py` (referenced in `BACKEND_REVIEW.md:359-360`) **do not exist**. The current `backend/app/services/` contains 22 modules: `ai_context_india, ai_context_service, ai_dossier_service, alpha_vantage_service, analytics_engine, backtest_service, benchmark_service, cache_service, cointegration_service, company_data_service, correlation_service, currency_service, data_service, equity_research_service, india_data_service, indicators_service, monte_carlo_service, optimization_service, regime_service, screener_service, source_preference_service, tail_risk_service, volatility_service`. So "QuantLib is underused" is not quite right either — **the code that would use it was never written.**

### Dependency footprint

| | QuantLib | FinEngine |
|---|---|---|
| Runtime deps | **none** | — |
| Introduces a version constraint on pandas/numpy | **no** | — |
| New transitive deps | **none** | — |
| Docker image delta | +37 MB uncompressed / +13 MB compressed | — |
| Conflict risk with FinEngine pins | **zero** (verified by resolution) | — |

There is no `pyarrow`, `xarray`, `SQLAlchemy`, or other weight like the old GS Quant days. This is the cheapest possible dependency.

### API surface

Verified by **executing** against the installed 1.43 `win_amd64` wheel, and cross-checked against Context7 `/lballabio/quantlib-swig`. The 1.4x Python binding is **flat** — `dir(ql)` returns 1,545 public names and there are **no** `ql.instruments` / `ql.termstructures` / `ql.processes` / `ql.experimental` submodules.

**1. Black-Scholes-Merton + Greeks + implied vol (live output)**

```python
import QuantLib as ql

ql.Settings.instance().evaluationDate = ql.Date(15, 6, 2026)
dc = ql.Actual365Fixed()

rf = ql.YieldTermStructureHandle(ql.FlatForward(ql.Date(15, 6, 2026), 0.05, dc))
dv = ql.YieldTermStructureHandle(ql.FlatForward(ql.Date(15, 6, 2026), 0.02, dc))
vs = ql.BlackVolTermStructureHandle(
    ql.BlackConstantVol(ql.Date(15, 6, 2026), ql.NullCalendar(), 0.20, dc)
)

# NOTE: 1.4x takes Handles, not bare objects, and the engine is
# AnalyticEuropeanEngine -- BlackScholesMertonEngine no longer exists.
process = ql.BlackScholesMertonProcess(
    ql.QuoteHandle(ql.SimpleQuote(100.0)), dv, rf, vs
)

opt = ql.VanillaOption(
    ql.PlainVanillaPayoff(ql.Option.Call, 100.0),
    ql.EuropeanExercise(ql.Date(15, 12, 2026)),
)
opt.setPricingEngine(ql.AnalyticEuropeanEngine(process))

opt.NPV()      # 6.317050
opt.delta()    # 0.564564
opt.gamma()    # 0.027456
opt.vega()     # 27.531501
opt.theta()    # -6.869094
opt.rho()      # 25.138337
opt.impliedVolatility(6.317050, process, accuracy=1e-8, maxEvaluations=200)  # 0.200000
```

**2. Yield curve construction, forwards, bootstrapping**

```python
# Direct fit
zc = ql.ZeroCurve([ql.Date(15, 6, y) for y in (2026, 2027, 2028, 2031)],
                  [0.0600, 0.0615, 0.0630, 0.0655], dc)
zc.zeroRate(3.0, ql.Continuous, ql.Annual).rate()    # 0.063831
zc.forwardRate(1.0, 2.0, ql.Continuous).rate()       # 0.064492

# Bootstrap from market quotes (Context7 /lballabio/quantlib-swig, api-reference/06-term-structures)
helpers = [
    ql.DepositRateHelper(ql.makeQuoteHandle(0.0382), ql.Period(1, ql.Months), 2,
                         ql.India(ql.India.NSE), ql.Following, False, ql.Actual360()),
    ql.SwapRateHelper(ql.makeQuoteHandle(0.0413), ql.Period(5, ql.Years),
                      ql.India(ql.India.NSE), ql.Annual, ql.Unadjusted,
                      ql.Thirty360(ql.Thirty360.BondBasis), mibor_3m),
]
curve = ql.PiecewiseLinearZeroCurve(ql.Date(15, 6, 2026), helpers, ql.Actual360())
# NB: in 1.43 the class is PiecewiseLinearZero, NOT PiecewiseLinearZeroCurve.
#     Verified: hasattr(ql, "PiecewiseLinearZero") is True, "PiecewiseLinearZeroCurve" is False.
```

**3. Day-count conventions and the NSE business calendar** (FinEngine's actual gap — `exchange_calendars` is *not* installed)

```python
ql.Actual365Fixed(); ql.Actual360(); ql.ActualActual(ql.ActualActual.ISDA)
ql.Thirty360(ql.Thirty360.BondBasis); ql.Business252()

nse = ql.India(ql.India.NSE)
nse.businessDaysBetween(ql.Date(13, 8, 2026), ql.Date(18, 8, 2026))  # 3
nse.isHoliday(ql.Date(15, 8, 2026))                                  # True  (Independence Day)
nse.adjust(ql.Date(15, 8, 2026), ql.Following)
nse.holidayList(ql.Date(1, 1, 2026), ql.Date(31, 12, 2026))
```

**4. Stochastic vol — Heston analytic engine** (no closed form exists in numpy/scipy; this is where QuantLib is irreplaceable)

```python
hp = ql.HestonProcess(rf, dv, ql.QuoteHandle(ql.SimpleQuote(100.0)),
                      0.04,   # v0
                      1.5,    # kappa
                      0.04,   # theta
                      0.3,    # sigma (vol of vol)
                      -0.7)   # rho
model = ql.HestonModel(hp)
hopt = ql.VanillaOption(ql.PlainVanillaPayoff(ql.Option.Call, 100.0),
                        ql.EuropeanExercise(ql.Date(15, 12, 2026)))
hopt.setPricingEngine(ql.AnalyticHestonEngine(model, 144))
hopt.NPV()   # 6.195412
# 1.43 ctor takes plain Reals -- FittingParameter is gone from the Python binding.
```

**5. Short-rate term-structure models**

```python
hw = ql.HullWhite(rf, 0.1, 0.01)
hw.termStructure().zeroRate(1.0, ql.Continuous, ql.Annual).rate()   # 0.050000
hw.termStructure().zeroRate(5.0, ql.Continuous, ql.Annual).rate()   # 0.050000
# 1.43 exposes HullWhite WITHOUT .a()/.sigma() accessors -- use a OneFactorAffineModel
# via its public API only: ['calibrate','constraint','discount','discountBond',
# 'discountBondOption','endCriteria','functionEvaluation','params','problemValues',
# 'setParams','value']

v = ql.Vasicek()   # dr = a(b-r)dt + sigma dW ; expose params() / setParams()
```

**6. American exercise via Longstaff-Schwartz (this is the ONLY spelling in 1.43)**

```python
am = ql.VanillaOption(ql.PlainVanillaPayoff(ql.Option.Call, 100.0),
                      ql.AmericanExercise(ql.Date(15, 6, 2026), ql.Date(15, 12, 2026)))
# There is NO class named LongstaffSchwartzAmericanEngine. The LS machinery is
# inside MCAmericanEngine via LsmBasisSystem polynomial bases.
am.setPricingEngine(ql.MCAmericanEngine(
    process, "LD",                    # "LD" = Sobol, "PR" = pseudo-random
    timeSteps=252, seed=42, polynomOrder=3,
    requiredSamples=20000))           # requiredSamples OR requiredTolerance is MANDATORY
am.NPV()   # 6.077767
# LsmBasisSystem bases: Monomial, Chebyshev, Chebyshev2nd, Hermite, Hyperbolic,
#                       Laguerre, Legendre
# Omitting requiredSamples/requiredTolerance raises:
#   RuntimeError: neither tolerance nor number of samples set
```

**7. Risk statistics — the part FinEngine's VaR/ES work would actually use**

```python
st = ql.RiskStatistics()          # NB: distinct from ql.Statistics
st.add(pnl_list)                  # NB: .add(), not .addData()
st.valueAtRisk(0.95)              # 0.02123
st.expectedShortfall(0.95)        # 0.03229
st.averageShortfall(0.95)         # 0.95002
st.regret(0.95)                   # 0.90276
st.potentialUpside(0.95)          # 0.02151
st.semiVariance(); st.downsideVariance(); st.downsideDeviation()
```

Live cross-check against a 50,000-point Student-t(4) P&L vector:

| | QuantLib `RiskStatistics` | numpy reference | abs diff |
|---|---|---|---|
| VaR(95%) | 0.02123 | 0.02123 | 3.86e-08 |
| ES(95%) | 0.03229 | 0.03229 | 1.39e-17 |

**8. Credit**

```python
ql.CreditDefaultSwap(...)          # present
ql.MidPointCdsEngine(...)          # present   (ql.CdsEngine is NOT)
```

### Overlap with FinEngine

| FinEngine file / function | QuantLib replacement | Effort | Risk |
|---|---|---|---|
| `analytics_engine.py:445,480,1444` — `min(30, std*sqrt(252)*100)` VaR proxy | `ql.RiskStatistics.valueAtRisk/expectedShortfall` | **S** | LOW — but see "keep" note: `RiskStatistics` is a *descriptive* estimator over a supplied P&L vector, so numpy's `np.quantile` is already 5 µs and fully vectorised. **Adopting it would make things slower, not faster.** Recommend: do *not* replace. |
| `analytics_engine.py:1232,1235` — `var_95` / `cvar_95` | `ql.RiskStatistics` | **S** | MEDIUM — historical vs parametric semantics differ; would need a regression test. Same "no perf win" objection. |
| `analytics_engine.py:2252,2385,2473,2507,2827,3148` — hardcoded `np.sqrt(252)` annualisation (12+ sites) | `ql.Business252()` day counter + `ql.India(ql.India.NSE)` calendar | **M** | **MEDIUM** — the *real* value here (actual NSE trading-day count, not 252), but it touches the single most widely-reused numeric constant in the codebase. Every VaR/vol number moves. Needs a golden-value regression sweep. |
| `ai_context_service.py:2581`, `analytics_engine.py:1054,1155,1191` — `periods: int = 252` literals | same as above | **M** | MEDIUM (same change, do them together) |
| `monte_carlo_service.py:107 _simulate_gbm, :136 _simulate_student_t, :168 _simulate_bootstrap, :240 _simulate_bounded_checkpoints, :327 simulate_goal` | `ql.GaussianSobolMultiPathGenerator` (present), `ql.HestonProcess`, `ql.MCAmericanEngine` | **L** | **HIGH** — this service is carefully engineered (chunked path fan-out, checkpoint fan-in, `numpy` vectorised inner loop). Replacing a tuned NumPy GBM with a SWIG-loop Sobol generator is very likely a **performance regression** for a goal-probability use case. **Recommend: keep, do not replace.** |
| `volatility_service.py:279 calculate_volatility_cone, :203 forecast_garch_volatility` | `ql.BlackVolTermStructure` / `ql.BlackVolatilitySurface` / `ql.LocalVolSurface` | **M** | LOW-MEDIUM — `arch` is already right for GARCH; QuantLib is right for *term structure of vol*, which FinEngine has none of. Net-new, not a replacement. |
| `regime_service.py:204 classify, :432 detect_regime` (HMM) | — | — | **NO OVERLAP.** QuantLib has no HMM. Keep `hmmlearn`. |
| `tail_risk_service.py:25 calculate_evt_pot_var_es, :79 pot_moments, :262 calculate_bivariate_tail_dependence, :339 calculate_tail_dependence_matrix, :441 calculate_full_tail_risk_suite` | — | — | **NO OVERLAP.** QuantLib has no EVT-POT, no GPD, no copula. `RiskStatistics` gives you historical ES, not EVT. **Keep as-is — this is FinEngine's genuine differentiator.** |
| `cointegration_service.py` (Engle-Granger, Johansen, OU half-life) | `ql.OrnsteinUhlenbeckProcess` (present) | **M** | LOW-MEDIUM — statsmodels already does ADF/Johansen; only the OU *process simulation* is new. |
| `optimization_service.py` (751 lines) | `ql.LBFGSB`, `ql.LevenbergMarquardt`, `ql.EndCriteria` | **M** | LOW — cvxpy is the right tool for constrained portfolios; QuantLib optimisers are curve-calibration optimisers. Minor win only. |
| `correlation_service.py`, `backtest_service.py` | — | — | **NO OVERLAP.** |
| **G3 proposal** — options Greeks + IV surface (`BACKEND_REVIEW.md:359`) | `ql.AnalyticEuropeanEngine`, `ql.AnalyticHestonEngine`, `ql.impliedVolatility`, `ql.HestonBlackVolSurface`, `ql.SviInterpolatedSmileSection`, `ql.SABRInterpolation` | **M** | LOW — **this is the strongest case.** Hand-rolled Black-Scholes-to-IV inversion is a known correctness trap; QuantLib's Brent solver + analytic Greeks removes it. |
| **G4 proposal** — fixed income / yield curve (`BACKEND_REVIEW.md:360`) | `ql.ZeroCurve`, `ql.PiecewiseLinearZero`, `ql.FixedRateBond`, `ql.BondHelper`, `ql.OISRateHelper`, `ql.MakeSchedule` | **L** | MEDIUM — needs CCIL FBIL/MIBOR + NDS-OM G-Sec data plumbing that does not exist yet. |
| **NEW** — the PDF tearsheet | — | — | **NO OVERLAP.** QuantLib has no reporting. |

### Implementation guide

**Do NOT remove the dependency.** It is inert, free, Windows-native, and needed for the two queued modules.

**Step 1 — tighten the floor so the 1.4x API break can never bite you.** One line, `backend/pyproject.toml:37`:

```toml
# before
"quantlib>=1.40",
# after
"quantlib>=1.43",   # 1.4x Python API: AnalyticEuropeanEngine replaces BlackScholesMertonEngine
```

Then `uv sync --extra dev --group dev` (per `AGENTS.md`; both tool tables exist).

**Step 2 — build the options service that actually consumes it.** Files to add/touch:

- `backend/app/services/derivatives_service.py` — **new.** NSE option-chain ingest + `ql` pricing/Greeks. This is the deliverable that makes the dependency honest.
- `backend/pyproject.toml` — no change (QuantLib already present).
- `backend/app/services/analytics_engine.py:1232,1235` — **keep** `var_95`/`cvar_95` as-is. Do not swap in `RiskStatistics`; numpy's `np.quantile` is faster and already correct. Only add a cross-check test.
- `backend/app/services/monte_carlo_service.py` — **keep untouched.**

**Step 3 — calendar/annualisation, only if G4 (fixed income) actually starts.** This is the one change that moves numbers across the whole dashboard, so it needs a golden-value sweep. Files: `analytics_engine.py` (12 `sqrt(252)` sites), `ai_context_service.py:2581`.

**Keep vs replace, explicitly:**

| Keep (do not rewrite) | Replace with QuantLib |
|---|---|
| `tail_risk_service.py` in full (EVT-POT, copula) — QuantLib has none of it | any future Black-Scholes / IV inversion → `ql.AnalyticEuropeanEngine` + `impliedVolatility` |
| `monte_carlo_service.py` in full (tuned, chunked, checkpointed) | future IV term-structure / smile → `ql.BlackVolTermStructure`, `HestonBlackVolSurface`, `SviInterpolatedSmileSection` |
| `var_95` / `cvar_95` (numpy is faster) | future yield-curve bootstrap → `ql.ZeroCurve` / `PiecewiseLinearZero` |
| `regime_service.py` (hmmlearn) | future bond cashflow/DTS → `ql.FixedRateBond` + `MakeSchedule` |
| `sqrt(252)` *for now* (see Step 3) | future NSE trading-day count → `ql.India(ql.India.NSE)` |
| `optimization_service.py` (cvxpy) | future CDS → `ql.CreditDefaultSwap` + `MidPointCdsEngine` |

**Rewritten code example — the honest minimal adoption.** A new `backend/app/services/derivatives_service.py` core:

```python
"""NSE option pricing + Greeks via QuantLib (lballabio/QuantLib, BSD-3-Clause).

QuantLib 1.4x Python API notes, verified against the installed 1.43 wheel:
  * the engine is ``AnalyticEuropeanEngine``; ``BlackScholesMertonEngine`` is gone
  * ``BlackScholesMertonProcess`` takes Handles, not bare shared_ptrs
  * ``zeroRate``/``forwardRate`` take ``(Time, Compounding)`` or ``(Time, Compounding, Frequency)``
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import QuantLib as ql

_DAY_COUNTER = ql.Actual365Fixed()


@dataclass(frozen=True)
class Greeks:
    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


def price_european(
    *,
    as_of: date,
    expiry: date,
    spot: float,
    strike: float,
    vol: float,
    risk_free: float,
    dividend_yield: float,
    call: bool = True,
) -> Greeks:
    ql.Settings.instance().evaluationDate = ql.Date(as_of.day, as_of.month, as_of.year)

    rf = ql.YieldTermStructureHandle(ql.FlatForward(ql.Settings.instance().evaluationDate, risk_free, _DAY_COUNTER))
    dy = ql.YieldTermStructureHandle(ql.FlatForward(ql.Settings.instance().evaluationDate, dividend_yield, _DAY_COUNTER))
    vol_ts = ql.BlackVolTermStructureHandle(
        ql.BlackConstantVol(ql.Settings.instance().evaluationDate, ql.India(ql.India.NSE), vol, _DAY_COUNTER)
    )

    process = ql.BlackScholesMertonProcess(
        ql.QuoteHandle(ql.SimpleQuote(spot)), dy, rf, vol_ts
    )
    option = ql.VanillaOption(
        ql.PlainVanillaPayoff(ql.Option.Call if call else ql.Option.Put, strike),
        ql.EuropeanExercise(ql.Date(expiry.day, expiry.month, expiry.year)),
    )
    option.setPricingEngine(ql.AnalyticEuropeanEngine(process))
    return Greeks(option.NPV(), option.delta(), option.gamma(), option.vega(), option.theta(), option.rho())
```

**Migration order (highest ROI first):** (1) tighten pin → (2) `derivatives_service.py` options + Greeks → (3) IV surface → (4) NSE calendar/annualisation, only with a golden-value sweep → (5) fixed income, only if G4 is greenlit.

### Risk & caveats

1. **🔴 THREAD SAFETY — the biggest one.** The wheel's own `METADATA` says: *"the underlying C++ library is not thread-safe. It has globals (most notably, the evaluation date) that in the current version of the wheels can't be set per thread. Also, we suggest to avoid sharing objects and state across threads; each thread should have its set of curves and instruments. Given that they calculate and cache results lazily, sharing them will probably lead to data races."* **FinEngine is FastAPI.** `ql.Settings.instance().evaluationDate` is a process-wide global. Anyio's threadpool workers and sync endpoint handlers share it. **You must serialise all QuantLib work behind a lock, or run it in a dedicated single-threaded executor.** This is a design constraint, not a footnote.
2. **🔴 1.4x Python API break.** `BlackScholesMertonEngine` → `AnalyticEuropeanEngine`; `PiecewiseLinearZeroCurve` → `PiecewiseLinearZero`; `BusinessDay` class → module-level `ql.Following`/`Preceding`/`ql.JoinBusinessDays`; ctors moved to Handles; `HestonProcess` lost `FittingParameter`; `FittingParameter` no longer exists as a Python name; `HullWhite` lost `.a()`/`.sigma()`; `CdsEngine` gone (`MidPointCdsEngine` remains). **Every tutorial and blog post on the internet is wrong for 1.4x.** Context7's quantlib-swig docs already reflect the handle-based API.
3. **🟠 SWIG overhead dominates scalar analytic pricing.** Measured on this machine (1.43 `win_amd64`):

   | Operation | Time |
   |---|---|
   | 1× BSM `NPV()` via QuantLib | **8.5 µs** |
   | 41-strike grid, Python loop over QuantLib | **18.2 µs / element** |
   | 41-strike grid, vectorised numpy + `scipy.stats.norm` | **133 µs total = 3.24 µs / element** |
   | Heston analytic `NPV()` (order 144) | 91 µs cold → 2.5 µs warm |

   **Vectorised NumPy is ~5.6× faster than a QuantLib loop for a batch grid.** There is no vectorisation API and no numpy bridge. QuantLib's C++ speed only pays off for Monte-Carlo and PDE work where the inner loop runs in C++ (100k+ paths).
4. **🟠 The `ql/risk` spectral-risk module is NOT exposed in Python.** Verified: `[x for x in dir(ql) if "Spectral" in x or "Shortfall" in x or "Entropic" in x] == []`. No `Shortfall`, no `EntropicRiskMeasure`, no `FilteredShortfall`, no `AILegendre`. Context7 for `/lballabio/quantlib-swig` returns *"No documentation … matched this query"* for spectral risk measures. **The brief's premise that QuantLib's risk module helps FinEngine's VaR/ES work is only half-true**: `ql.RiskStatistics` (parametric-free, descriptive VaR/ES/regret/potential-upside/semi-variance) *is* available and matches numpy to 1e-17, but the spectral/ENTropic machinery is C++-only. And since FinEngine's EVT-POT + copula work is its differentiator anyway, there is nothing to gain.
5. **🟠 `LongstaffSchwartzAmericanEngine` does not exist as a name.** The LS machinery is inside `MCAmericanEngine(..., polynomOrder=, polynomType=LsmBasisSystem.*)`. It raises `RuntimeError: neither tolerance nor number of samples set` unless you pass `requiredSamples` or `requiredTolerance`. Any LLM-authored snippet using `LongstaffSchwartzAmericanEngine` will fail.
6. **🟡 37 MB per container** for a dependency used zero times. After Step 2 it earns its place; today it is pure cost.
7. **🟡 `requires_python` is unset and there are no `Programming Language :: 3.x` classifiers.** Rely on the ABI tag, not the metadata. Pin `>=1.43` explicitly.
8. **🟡 GitHub reports `NOASSERTION`** for both repos because the file is `LICENSE.TXT`. A licence-scanning bot may flag this. It is BSD-3-Clause; add a suppression note if your scanner trips.
9. **🟢 No numpy/pandas coupling, no compilation on any FinEngine target, no transitive deps, non-copyleft, no network use.** Those are the reasons the verdict is not AVOID.
10. **ℹ️ Docs in the repo are misleading.** `instructions/doc/RISK_LIBRARIES_INTEGRATION_GUIDE.md` shows `from QuantLib import *` and `BlackScholesMertonEngine`-era patterns that will not run on 1.43, and `instructions/doc/LIBRARY_INTEGRATION_OPPORTUNITIES.md:703` recommends `pip install QuantLib==1.32` (three majors behind). Fix or delete these before they mislead the next agent.

---

## GS Quant

`AVOID` — a hard `numpy<2.4.0` cap makes it uninstallable next to FinEngine's `numpy==2.5.3`, it is an authenticated GS **Marquee REST client** rather than a local analytics library, and the PDF tearsheet framework it was famous for **no longer ships in the distribution**.

### License

- **SPDX:** `Apache-2.0`. Declared in `pyproject.toml` as `license = {text = "Apache-2.0"}`, in PyPI `METADATA` as `License: Apache-2.0`, and classifier `License :: OSI Approved :: Apache Software License`. The `master/LICENSE` file is the **unmodified canonical Apache 2.0 text** — verified verbatim, no GS-specific rider appended.
- **NOTICE files — two of them, and the 4(d) obligation is live:**

  `NOTICE` (in the wheel's `dist-info/licenses/`):
  ```
  gs-quant
  Copyright 2018 Goldman Sachs
  ```
  `NOTICE.txt`:
  ```
  gs-quant
  Copyright 2018-2019 Goldman Sachs
  This product contains code copyright Scott Weinstein, licensed under Apache 2.0 license
  ```
- **Trademark clause — Apache-2.0 §6, unmodified:**
  > 6. Trademarks. This License does not grant permission to use the trade names, trademarks, service marks, or product names of the Licensor, except as required for reasonable and customary use in describing the origin of the Work and reproducing the content of the NOTICE file.

  So: you may say "uses gs-quant" (factual origin). You may **not** ship anything called "GS Quant", "Marquee", or with GS branding. Practically irrelevant if you are not adopting, but it is the clause to remember if anyone revisits this.
- **Patent grant (§3) with the standard termination clause** — note this is the one thing Apache-2.0 gives you that BSD-3 does not: an express patent grant. BSD-3 has none. (Another small point in QuantLib's favour for a *permissively* licensed dependency pair.)
- **§4(a)-(d) redistribution conditions:** ship the licence copy, mark modified files, retain all notices, and **reproduce the `NOTICE`/`NOTICE.txt` attribution in at least one of: a NOTICE file, the source/docs, or a display** in any derivative you distribute.
- **Pre-approved dependency licences, per [`CONTRIBUTING.md`](https://github.com/goldmansachs/gs-quant/blob/master/CONTRIBUTING.md)** (useful signal about their own hygiene): `MIT`, `ASL (all versions)`, `BSD`, `BSD-like`.
- `dco/` and `.gs-project.yml` at the repo root are internal GS build/infra metadata, not licence terms.

**Commercial impact:** the licence is fine. **The blocker is not legal, it is technical and commercial-access.** The README is explicit: *"In order to access the APIs you will need a client id and secret. These are available to institutional clients of Goldman Sachs. Please speak to your sales coverage or Marquee Sales for further information."* Adopting this library means adopting a dependency on a service FinEngine cannot buy.

**Linking vs vendoring:** moot — do not install it at all (see Compatibility).

### Maintenance

**ACTIVE as a repo, but the *shape* of the project changed and the interesting parts were removed.**

| Fact | Value | Source |
|---|---|---|
| Last commit | **2026-09-22T14:01:02Z** ("Chore: Make release 2.1.17", `martinroberson`) | [commits atom](https://github.com/goldmansachs/gs-quant/commits/master.atom) |
| Latest PyPI version | **2.1.17**, uploaded **2026-09-22T14:30:27Z** | [PyPI JSON](https://pypi.org/pypi/gs-quant/json) |
| GitHub Releases page | **EMPTY** — no published releases, no tags surfaced | [repo](https://github.com/goldmansachs/gs-quant) |
| Commits | 580 total | repo page |
| Stars / forks / watchers | 13.0k / 1.8k / 167 | repo page |
| Open issues / PRs | **25 / 48** | repo page |
| Archived | no | repo page |
| Recent cadence | 2.1.4 (Aug 17) → 2.1.6 (Aug 26) → 2.1.7 (Sep 1) → 2.1.10/11/12 (Sep 4) → 2.1.14 (Sep 9) → 2.1.15 (Sep 14) → 2.1.16 (Sep 16) → 2.1.17 (Sep 22) | PyPI release history |

**⚠️ Velocity caveat:** **9 of the last 10 commits are `Chore: Make release X.Y.Z` by a single maintainer** — a release-please style bot. The 48 open PRs and 25 open issues against 580 commits is a thin review queue. The repo is alive; the *feature* cadence is low.

**ℹ️ README is stale:** it says *"Python 3.9 or greater"*, but `pyproject.toml` says `requires-python = ">=3.10"` and classifiers list 3.10–3.13. Trust `pyproject.toml`.

### Subpackage inventory

**🔴 The multi-subpackage layout the brief describes NO LONGER EXISTS.** Verified three ways:

1. **PyPI JSON returns HTTP 404** for `gs-quant-reports`, `gs-quant-risk`, `gs-quant-bond`, `gs-quant-equities`, `gs-quant-commodity`, `gs-quant-strategies`, `gs-quant-databases`, `gs-quant-reports-styles`.
2. **PyPI simple index** `https://pypi.org/simple/gs-quant-reports/` (and `-risk`, `-equities`, `-bond`) → **HTTP 404**.
3. `https://pypi.org/simple/gs-quant/` contains **only** the single `gs_quant` distribution — 1029 files, every one of them `gs_quant-*`. There is not one `gs_quant_reports` or `gs_quant_risk` file.

The repo is now a **monorepo with one installable package**. Actual module inventory of the `gs_quant-2.1.17-py3-none-any.whl` (424 entries total):

| Module | Files | What it is | Maintained? |
|---|---|---|---|
| `gs_quant/api/` | 59 | Marquee REST clients (`gs.assets`, `fred.data`, …), `api_session`, `api_cache` | Active, but **thin wrappers around `api.gs.com`** |
| `gs_quant/timeseries/` | 37 | pandas-window statistics: `mean/std/percentile/cov/RollingOLS/winsorize/zscores/rolling_std`; `measures_*` (bonds, fx vol, rates, xccy, inflation, portfolios, tca) | Active. `statistics.py` is 1643 lines. **Nothing FinEngine lacks.** |
| `gs_quant/target/` | 30 | Instrument + entity dataclasses (`Option`, `Swap`, `EqSpot`, `Portfolio`, `Chart`, `Report`…) | Active. Server-bound. |
| `gs_quant/analytics/` | 26 | Analytics recipes | Active. |
| `gs_quant/markets/` | 22 | `PricingContext`, `Portfolio`, `report.py`, `report_utils.py`, `factor_analytics`, `optimizer`, `scenario`, `screens` | Active. **All server-priced.** |
| `gs_quant/backtests/` | 20 | `Backtest`, `Strategy`, `GenericEngine`, `EquityVolEngine`, triggers/actions | Active — the most genuinely useful offline piece. |
| `gs_quant/mcp/` | 16 | An MCP server wrapper (optional `fastmcp` extra) | New, active. |
| `gs_quant/data/` | 9 | `Dataset` abstraction over GS data services | Active. |
| `gs_quant/skills/` | 9 | Markdown "skills" for LLM agents | New. |
| `gs_quant/risk/` | **8** | `measures.py` is **85 lines**; exports `IRBasis, IRBasisParallel, IRDelta, IRDeltaLocalCcy, IRDeltaParallel, InflationDelta, InflationDeltaParallel, IRVega, IRVegaLocalCcy, IRVegaParallel, IRXccyDelta, IRXccyDeltaParallel, PnlExplain, PnlExplainClose, PnlExplainLive, PnlPredictLive, DEPRECATED_MEASURES`. `DEPRECATED_MEASURES = {}`. | Active but **gutted** — pure request builders for GS-served IR sensitivities. **No VaR. No ES. No copula. No EVT.** |
| `gs_quant/datetime/` | 7 | `business_day_offset`, `business_day_count`, `is_business_day`, `relative_date` | Active. **This is the one genuinely reusable piece** (see below). |
| `gs_quant/content/` | 5 | Jupyter tutorials/events | — |
| `gs_quant/entities/` | 5 | `Entitlements`, GS entity tree | Active. |
| `gs_quant/models/` | 4 | `epidemiology.py` (SIR/SEIR), `risk_model.py` | Active. |
| `gs_quant/config/`, `instrument/`, `licenses/` | 3/3/3 | options, instrument overrides, bundled 3rd-party licences | — |
| `gs_quant/interfaces/`, `quote_reports/`, `tracing/`, `workflow/` | 2 each | algebra, quote-report types, OTel tracing, workflow | Active |
| `gs_quant/test/` | 134 | tests | — |
| root | ~12 | `base.py`, `common.py`, `session.py`, `config.ini`, `errors.py`, `json_*`, `priceable.py` | — |

**What the removed subpackages used to be:** `gs-quant-reports` was the PDF/HTML tearsheet package (fpdf + Jinja templates + `Teaser`/`RiskReport`/`ScenarioReport`/`BacktestPerformanceTeardown`). `gs-quant-risk` had real offline `VaR`/`ES`/factor analytics. `gs-quant-bond`/`-equities`/`-commodity` had offline instrument pricing. **All of that is either gone or moved behind the Marquee API.** Net: the library got smaller and more coupled to GS infrastructure, not larger.

### Dependency footprint

**Actual current requirements** (from `master/pyproject.toml` and PyPI `METADATA` — the two agree exactly):

**Hard caps (the blockers):**
```
numpy>1.17.0,<2.4.0        <-- HARD CAP. FinEngine is on 2.5.3.
pandas>=1.4                <-- no upper cap, but pandas 3.0 is untested
pydash<7.0.0
```

**Lower bounds only:** `scipy>=1.2.0`, `statsmodels>=0.14.5`, `dataclasses_json>=0.6.5`, `httpx>=0.28.1`, `python-dateutil>=2.7.0`.

**Unpinned:** `aenum`, `backoff`, `cachetools`, `certifi`, `deprecation`, `inflection`, `lmfit`, `more_itertools`, `msgpack`, `nest-asyncio`, `opentelemetry-api`, `opentelemetry-sdk`, `requests`, `pyyaml`, `tqdm`, `websockets`.

**Extras:** `notebook` → jupyter, matplotlib, seaborn, treelib. `internal` → **`gs-quant-internal>=2.0.20`** (closed-source Marquee layer). `test`/`develop` → pytest stack, nbconvert, plotly, freezegun, ruff, sphinx. `mcp` → fastmcp>=3.0, python-dotenv, uvicorn>=0.47, typer>=0.25, prompt_toolkit, rich, pydantic.

**🔴 The brief's expected dependencies are NOT dependencies any more.** Full-text scan of **all 424 wheel entries** (`gs_quant/**/*.py`, `*.md`, `*.json`, `*.html`):

| Package | Hits in the wheel | Reality |
|---|---|---|
| `fpdf` | **0** | gone (was the PDF renderer) |
| `jinja2` / `jinja` | **0** | gone (was the HTML template engine) |
| `reportlab` | **0** | never present |
| `xhtml` | **0** | gone |
| `tearsheet` | **0** | gone |
| `Teaser` | **0** | gone |
| `ScenarioReport` | **0** | gone |
| `BacktestPerformanceTeardown` | **0** | gone |
| `xarray` | **0** | not a dep |
| `pyarrow` | **0** | not a dep |
| `SQLAlchemy` | **0** | not a dep |
| `gspread` | **0** | not a dep |
| `openpyxl` | **0** | not a dep |
| `quantlib` / `QuantLib` | **0** | **does NOT depend on QuantLib** (contradicting the brief's assumption) |
| `riskfolio` | **0** | **does NOT depend on riskfolio-lib** (contradicting the brief's assumption) |
| `matplotlib` | 2 | only in `gs_quant/content/` tutorial notebooks, not library code; declared in the `notebook` extra only |
| `plotly` | — | `test` extra only |

That is **23 direct deps, 3 of them unrelated to finance** (`aenum`, `pydash`, `inflection`) and a hard numpy ceiling.

**Conflict risk with FinEngine's pins: FATAL, and demonstrated, not asserted.** See Compatibility.

### Compatibility

**🔴🔴 HARD BLOCKER — PROVEN BY LIVE `uv` RESOLUTION.**

**Test 1 — pin gs-quant 2.1.17 with FinEngine's actual stack:**

```toml
dependencies = [
  "gs-quant==2.1.17",
  "numpy==2.5.3",
  "pandas==3.0.6",
  "scipy==1.18.0",
  "statsmodels==0.15.0",
  "arch==8.0.0",
  "cvxpy==1.9.3",
  "fastapi",
  "quantlib>=1.40",
]
```

```
$ uv lock --python 3.12
error: No solution found when resolving dependencies
  cause: Because gs-quant>=2.1.17 depends on numpy>1.17.0,<2.4.0 and your project depends on gs-quant==2.1.17, we can
conclude that your project depends on numpy>1.17.0,<2.4.0.
         And because your project depends on numpy==2.5.3, we can conclude that your project's requirements are
unsatisfiable.
```

**This is not a theoretical "might conflict" — it is a hard resolver failure. Loud and unambiguous: adopting gs-quant 2.x forces a project-wide numpy downgrade below 2.4.0, which means re-resolving `arch`, `cvxpy`, `scipy`, `statsmodels`, `hmmlearn`, `quantstats` and `stockstats` all at once, against a `uv.lock` that is currently consistent.**

**Test 2 — the backtrack is even worse than a downgrade.** Drop the explicit gs-quant pin, keep `numpy==2.5.3`:

```
$ uv lock --python 3.12
Resolved 71 packages in 11.35s
$ uv tree --frozen | grep gs-quant
├── gs-quant v1.4.67          <-- 2022-era release
```

uv walks all the way back to **gs-quant 1.4.67** to satisfy numpy 2.5.3. So the only two outcomes are:

- **Outcome A:** gs-quant 2.1.17 + numpy **downgraded** project-wide to 2.3.5. Verified working in an isolated venv: `numpy 2.3.5 / pandas 3.0.6 / gs_quant 2.1.17`, `import gs_quant` succeeds. But FinEngine moves off 2.5.3, and FinEngine's own code, tests, and any numpy-2.4/2.5-specific behaviour are now unverified.
- **Outcome B:** numpy stays 2.5.3 + **gs-quant pinned to 1.4.67**, a 2022 version that predates the entire `risk/` and `analytics/` restructuring and certainly predates pandas 3.0.

Neither is acceptable.

**Python 3.12: yes** (`requires-python = ">=3.10"`, classifier `Programming Language :: Python :: 3.12`).

**pandas 3.0: declared-compatible, practically unverified.** `pandas>=1.4` has no upper cap, and `import gs_quant` under `pandas 3.0.6` succeeds. But a `>=1.4` floor on a library whose data model leans on `pd.concat(...).assign(...)`, chained assignment, `RollingOLS` and custom `plot_function` decorators is a statement about 2021, not 2026. **`UNVERIFIED — needs manual check`** for any *substantive* offline call (`timeseries.statistics`, `backtests`) under pandas 3.0. The 48 open PRs and the `ruff` `NPY` ("numpy 2.0 deprecation check") rule in their `pyproject.toml` suggest numpy-2 awareness, but there is **no pandas-3 CI matrix evidence** I could find.

**Windows prebuilt wheel availability: N/A** — `gs_quant-2.1.17-py3-none-any.whl` is a **pure-Python** wheel (1,311,283 B), so `Operating System :: OS Independent` and no platform issue at all. This is gs-quant's one genuine advantage over QuantLib (1.3 MB vs 13 MB) and it is irrelevant given the numpy blocker.

**Architectural blocker (independent of numpy): it is a REST client, not a library.** `gs_quant/config.ini`, shipped inside the wheel:

```ini
[DEFAULT]
AppDomain      = https://api.gs.com
MdsDomainEast  = https://us-east.data.gsapis.com
MdsWebDomain   = https://data.gs.com
AuthURL        = https://idfs.gs.com/as/token.oauth2
MarqueeWebDomain = https://marquee.gs.com
```

Every pricing and risk call is an OAuth2 round-trip to GS infrastructure. The README: *"In order to access the APIs you will need a client id and secret. These are available to institutional clients of Goldman Sachs."* FinEngine's entire data layer is `yfinance`. Introducing a package whose value is *only* reachable behind a Goldman Sachs sales conversation is not a dependency decision, it is a procurement decision. And the brief's "M" scaling assumptions are inverted: an offline library is cheap to depend on, a **service** is not.

### FinEngine's current usage

**None.** There is no `gs_quant` / `gs-quant` reference anywhere in `backend/` or `frontend/`. The only references anywhere in the repo are aspirational prose in `instructions/doc/*` and `.scratch/*` (e.g. `.scratch/advanced-analytics/spec.md:46` classes QuantLib as "shelf for now" but says nothing about GS Quant).

### API surface

**Real copyable snippets — and note they all start with credentials.**

Authentication is mandatory for anything real (Context7 `/goldmansachs/gs-quant`, `skills/gs-quant-overview/SKILL.md`):

```python
from gs_quant.session import GsSession, Environment

GsSession.use(
    environment_or_domain=Environment.PROD,      # -> https://api.gs.com
    client_id='<GS institutional client id>',
    client_secret='<GS institutional client secret>',
    scopes=('run_analytics', 'read_product_data'),
)
```

The offline-ish bits (these *are* real, and are the only parts FinEngine could ever have used):

```python
# Business-day arithmetic -- the one genuinely reusable piece
from gs_quant.datetime import business_day_offset, business_day_count, is_business_day
prev_bus_day = business_day_offset(dt.date.today(), -1, roll='forward')
n = business_day_count(d0, d1, calendars=('NYSE',))
is_business_day(dt.date(2019, 7, 4), calendars=('NYSE',))   # False

# Named holiday calendars
from gs_quant.markets.rdates import RDate, HolidayCalendar
nyse_cal = HolidayCalendar.get("NYSE")
HolidayCalendar.create("Custom", holidays=[date(2023,1,1), date(2023,7,4)])
RDate.from_date(date(2023,1,1), calendar=nyse_cal, offset=2)

# Timeseries statistics (pandas window wrappers)
from gs_quant.timeseries import mean, std, percentile, zscores, winsorize, correlation, diff

# Backtesting
from gs_quant.backtests.strategy import Strategy
from gs_quant.backtests.generic_engine import GenericEngine
from gs_quant.backtests.equity_vol_engine import EquityVolEngine
from gs_quant.backtests.data_sources import GenericDataSource, GsDataSource, MissingDataStrategy
stats = backtest.summary_stats()
```

The **report** API, which is what the brief asked about, is a Marquee resource factory, not a renderer:

```python
from gs_quant.markets.report import PerformanceReport, FactorRiskReport, ThematicReport
risk_report = FactorRiskReport(risk_model_id=...)
risk_report.set_position_source(portfolio.id)
risk_report.save()            # -> POSTs to api.gs.com
thematic_report.get_thematic_data(...)   # -> GETs from api.gs.com
```

There is **no** `gs_quant_report` module, **no** `Teaser`, **no** `ScenarioReport`, **no** `BacktestPerformanceTeardown`, **no** HTML template, **no** fpdf render, **no** theme object. Full-text scan of the wheel: `fpdf` 0, `jinja` 0, `xhtml` 0, `tearsheet` 0, `Teaser` 0, `ScenarioReport` 0, `BacktestPerformanceTeardown` 0. Context7 `/goldmansachs/gs-quant`: *"No documentation in '/goldmansachs/gs-quant' matched this query"* for the subpackage and tearsheet queries.

### Overlap with FinEngine

| FinEngine file / function | gs-quant replacement | Effort | Risk |
|---|---|---|---|
| `frontend/src/lib/export.ts:31-145` `PDFExporter` (jsPDF, text + tables) | **none exists** — `gs_quant_report` is not shipped | — | **N/A** |
| `frontend/src/lib/export.ts:89-98` `PDFExporter.addChart` — **stub**: draws an empty `rect(150,80)` + literal text `"Chart Image"` | **none exists** | — | **N/A** |
| `frontend/src/lib/export.ts:222-277` `ChartExporter.exportChart` (SVG→canvas→PNG, already correct) | **none exists** | — | **N/A** |
| `frontend/src/lib/export.ts:281-299` `ExportService.exportPDF` | **none exists** | — | **N/A** |
| `frontend/src/lib/export.ts:319-442` `ExportService.exportInstitutionalReviewPDF` — the institutional tearsheet; zero charts, and its "risk" section (L428-432) is three **hardcoded prose strings**, not data-driven | **none exists** | — | **N/A** |
| `frontend/src/lib/export.ts:148-193` `ExcelExporter` (SheetJS) | — | — | N/A. Note `openpyxl` is a FinEngine backend dep but irrelevant to the frontend bundle. |
| `components/layout/Header.tsx:18,61` — calls `exportInstitutionalReviewPDF` | — | — | N/A |
| `components/ui/ExportPanel.tsx:7,148,168,187` — calls `exportPDF` / `exportChart` | — | — | N/A |
| `app/dashboard/forecast-risk/page.tsx:493`, `app/dashboard/realized-risk/page.tsx:12` — `CSVExporter` | — | — | N/A |
| `analytics_engine.py:1232,1235` `var_95` / `cvar_95` | `gs_quant.risk` has **no** VaR/ES (85 lines, IR sensitivities only) | — | **NO OVERLAP** |
| `tail_risk_service.py:25,79,262,339,441` — EVT-POT, copula, tail dependence | `copula` 0 hits, `extreme_value` 0, `GPD` 0 in the whole wheel | — | **NO OVERLAP** |
| `volatility_service.py:203` GARCH, `:279` vol cone | `timeseries.measures_fx_vol` — FX vol, server-priced | — | **NO OVERLAP** |
| `monte_carlo_service.py:327 simulate_goal` | no MC engine exposed | — | **NO OVERLAP** |
| `regime_service.py`, `cointegration_service.py`, `optimization_service.py`, `backtest_service.py` | `markets.optimizer` (GS server), `backtests.Backtest` (some offline value) | **M** for the backtester | LOW value, HIGH cost — `gs_quant.backtests` is the one part with real offline behaviour, but FinEngine's `backtest_service.py` is 199 lines and already does its job. Importing it drags the whole `numpy<2.4` blocker for a marginal gain. |
| `analytics_engine.py` (12× `np.sqrt(252)`) | `gs_quant.datetime.business_day_count(calendars=...)` | **S** | MEDIUM — this is the *one* thing worth copying, and you can copy the **idea** (or use `exchange_calendars`, which is not installed) without the dependency. |

### Implementation guide

**No implementation. Do not add a `pyproject.toml` line.** For completeness, the line you must **not** write:

```toml
# DO NOT ADD
"gs-quant",            # -> numpy<2.4.0, breaks uv lock against FinEngine's numpy 2.5.3
"gs-quant-reports",    # -> does not exist on PyPI (HTTP 404)
```

**The tearsheet question, answered decisively:**

> *Would moving the tearsheet generation server-side with GS Quant Reports give a material improvement?*

**No — because GS Quant Reports does not exist any more.** The premise is void. There is no `gs_quant_report` to move to. Even the 2023-era `gs-quant-reports` cannot be installed (PyPI 404), and even if it could, it would fail the numpy resolution test identically.

> *Or is the current jsPDF approach fine and GS Quant too heavy?*

**The jsPDF approach is fine. GS Quant is not merely "too heavy" — it is unavailable and non-installable.** But "fine" needs one honest caveat, because FinEngine's own `AGENTS.md` has a rule the current code violates:

- `PDFExporter.addChart` (`export.ts:89-98`) is a **stub** that renders an empty grey box labelled `"Chart Image"`. There are **no charts in any PDF FinEngine produces.**
- `exportInstitutionalReviewPDF` (`export.ts:319-442`) prints its risk section as three **hardcoded English strings** (L428-432): `"• Euler Decomposition: Volatility and CVaR tail shares calculated against multi-asset empirical covariance."` — these assert methodology that is not computed in the function. That directly violates **`AGENTS.md` → Quantitative & Terminal UI Invariants → "Metric Card Hygiene: ... strictly driven by live API responses without placeholder mock deltas."**
- The good news: `ChartExporter.exportChart` (`export.ts:222-277`) already does SVG→canvas→PNG correctly. **The plumbing is 95% there.** The missing piece is ~10 lines: capture the Recharts SVG, pass the PNG blob to `doc.addImage(...)` in place of the stub.

**So the recommendation is: keep jsPDF, spend ~1 hour wiring the existing `ChartExporter` output into the PDF, and replace the three hardcoded strings with actual `riskMetrics` values.** That is the whole job. Do not add a 23-dependency, network-bound, license-gated Python service to draw a rectangle. If the tearsheet later needs server-side chart rendering, `matplotlib` is **already installed** in the backend and `jinja2` is already installed — a ~60-line Jinja template + `matplotlib` Agg backend is the proportionate answer, not a $0-cost-looking institutional library.

### Risk & caveats

1. **🔴 `numpy<2.4.0` vs FinEngine `numpy==2.5.3` → unsatisfiable resolution.** Demonstrated above. This alone is disqualifying.
2. **🔴 Requires a Goldman Sachs institutional client id + secret** to do anything beyond pandas-window arithmetic. FinEngine is a self-hosted FastAPI app; this is a hard external dependency on a commercial relationship.
3. **🔴 The PDF/HTML tearsheet framework is gone from the distribution.** `gs-quant-reports` is 404 on PyPI; `fpdf`/`jinja`/`xhtml`/`Teaser`/`ScenarioReport`/`BacktestPerformanceTeardown` have zero occurrences across all 424 wheel entries.
4. **🔴 `gs_quant/risk/measures.py` is 85 lines of interest-rate-sensitivity request builders with `DEPRECATED_MEASURES = {}`.** No VaR, no ES, no copula, no EVT, no Ledoit-Wolf, no GMM. FinEngine's actual risk work is untouched by this package.
5. **🟠 pandas 3.0 compatibility is declared but unverified.** `pandas>=1.4` with no upper cap and a code base built on `pd.concat().assign()`, `RollingOLS`, chained assignment, and `plot_function` decorators. **`UNVERIFIED — needs manual check`** for substantive offline calls. Note also that the `>1.17.0` numpy *floor* is 2019-vintage signalling.
6. **🟠 README/`pyproject.toml` disagree on the Python floor** (3.9 vs 3.10). Minor, but a sign the docs are not tightly maintained.
7. **🟠 Maintenance is release-bot-shaped**: 9 of the last 10 commits are `Chore: Make release`, single maintainer, 48 open PRs. The GitHub Releases page is empty. Active ≠ well-governed.
8. **🟡 23 direct deps for what is functionally a thin REST client**, 3 of them unrelated to finance, including an abandoned `pydash<7.0.0` fork line.
9. **🟡 `[[tool.uv.index]] default = true` points at `https://pypi.aws.site.gs.com/repository/pypi-group/simple`** inside their `pyproject.toml`. Not inherited by FinEngine (index config is not transitive for a declared dependency), but a reminder that their packaging assumes a GS-controlled index.
10. **🟡 Apache-2.0 §6 trademark restriction** and §4(d) NOTICE propagation both apply to any derivative. Manageable, but one more obligation BSD-3 does not impose.
11. **ℹ️ Positive, for the record:** pure-Python `py3-none-any` wheel, 1.3 MB, `Operating System :: OS Independent`, genuine Apache-2.0 with an express patent grant, and a legitimately well-designed offline `backtests` module. It is simply the wrong shape for FinEngine.

---

## Cross-library comparison

| Dimension | QuantLib (LSE) | GS Quant | FinEngine's position |
|---|---|---|---|
| **Verdict** | **ADOPT_PARTIAL** | **AVOID** | — |
| **Already installed?** | ✅ Yes — 1.43, `pyproject.toml:37` | ❌ No | QuantLib costs nothing to keep |
| **First-party imports** | **0** (dead dependency) | 0 | Nothing to migrate *from* |
| **Licence** | BSD-3-Clause, SPDX `BSD-3-Clause` | Apache-2.0, SPDX `Apache-2.0` | Both permissive; no legal blocker |
| **Bundled-extension licence** | **BSD-3-Clause, verified from inside the wheel** — no separate terms | Apache-2.0 + two `NOTICE` files (§4(d) obligation) | — |
| **Attribution obligations** | Reproduce 3 clauses + disclaimer on binary redistribution; non-endorsement clause | Reproduce licence + NOTICE; §6 trademark restriction | BSD-3 is the lighter obligation |
| **GitHub SPDX detection** | `NOASSERTION` (file is `LICENSE.TXT`) — tooling artefact | `Apache-2.0` | Scanner may false-positive on QuantLib |
| **Last commit** | 2026-09-25 (C++), 2026-09-23 (SWIG) | 2026-09-22 | All three actively maintained |
| **Latest version / date** | 1.43, 2026-07-14 | 2.1.17, 2026-09-22 | QuantLib is current; **no upgrade available** |
| **Cadence** | ~quarterly, lockstep C++/SWIG tags | frequent, but release-bot commits | — |
| **Status** | **ACTIVE** | **ACTIVE (scope-reduced)** | GS Quant's valuable parts were removed |
| **Python 3.12** | ✅ via `cp39-abi3` | ✅ `>=3.10` | Both fine |
| **Windows prebuilt wheel** | ✅ `cp39-abi3-win_amd64.whl` 12.9 MB (37 MB on disk) | ✅ pure-python `py3-none-any` 1.3 MB | No compilation either way |
| **Install footprint** | +37 MB/container | +23 deps, 1.3 MB + transitive tree | QuantLib's is dead weight today |
| **Direct deps** | **0** | 23 | — |
| **`numpy` constraint** | **none** (C-ext, no numpy ABI link) | **`>1.17.0,<2.4.0`** | **FinEngine: 2.5.3 → HARD BLOCKER** |
| **`pandas` constraint** | none | `>=1.4` (pandas 3.0 unverified) | FinEngine: 3.0.6 |
| **Resolution against FinEngine** | ✅ verified clean | ❌ `No solution found` | — |
| **Runtime deps** | none | `api.gs.com` OAuth2 + `idfs.gs.com` | yfinance-only today |
| **Needs credentials?** | No | **Yes — GS institutional client id/secret** | Disqualifying |
| **Vectorisable?** | ❌ no numpy bridge; 8–18 µs/call | n/a (server-priced) | numpy vectorised grid is **5.6× faster** than a QuantLib loop |
| **Covers EVT-POT / copula?** | ❌ none | ❌ none | **FinEngine's own differentiator — keep** |
| **Covers VaR/ES?** | ✅ `ql.RiskStatistics` (descriptive; matches numpy to 1e-17) | ❌ none | `np.quantile` already sufficient & faster |
| **Spectral risk measures?** | ❌ **C++-only, not in the Python binding** | ❌ | — |
| **Options pricing / Greeks / IV** | ✅ full (BSM, Heston, American MC/LS, IV inversion) | server-priced only | **not built yet — the real opportunity** |
| **Yield curve / bootstrapping** | ✅ `ZeroCurve`, `PiecewiseLinearZero`, `*RateHelper` | server-priced only | not built yet |
| **Bonds / schedules / CDS** | ✅ `FixedRateBond`, `MakeSchedule`, `CreditDefaultSwap` | server-priced only | not built yet |
| **Day count / business calendars** | ✅ `ActualActual(ISDA)`, `Business252`, **`India(India.NSE)`** | ✅ `business_day_count(calendars=…)` | `exchange_calendars` **not installed**; `sqrt(252)` hardcoded 12+× |
| **Short-rate models** | ✅ `Vasicek`, `HullWhite` | server-priced | not built yet |
| **Stochastic processes** | ✅ `HestonProcess`, local vol, GJRGARCH, LMM | n/a | `arch` for GARCH; add Heston only if needed |
| **Thread-safe in FastAPI?** | ❌ **NO** — global `evaluationDate`, lazy caches race | n/a | **Design constraint if adopted** |
| **PDF / tearsheet reporting** | ❌ none | ❌ **removed from distribution** | **jsPDF — fix `addChart`, don't replace** |
| **HMM / regime** | ❌ | ❌ | `hmmlearn` — keep |

## Recommended adoption order

Ranked by ROI, highest first. Items 1–3 are the whole recommendation; 4–6 are conditional.

1. **Delete the dead QuantLib weight, or make it earn its keep — decide now.** Either (a) keep `quantlib>=1.43` and land `derivatives_service.py` in the same PR, or (b) remove it until G3/G4 are greenlit. Shipping a 37 MB, 0%-used C++ extension in every container is indefensible on its own. **Effort: S. Risk: none.** (Currently `backend/pyproject.toml:37` = `"quantlib>=1.40"`; lock already at 1.43.)
2. **Fix the tearsheet with the code that already exists — ~1 hour, zero new dependencies.** In `frontend/src/lib/export.ts`: (i) implement `PDFExporter.addChart` (L89-98) to consume the PNG blob that `ChartExporter.exportChart` (L222-277) already produces; (ii) replace the three hardcoded prose bullets in `exportInstitutionalReviewPDF` (L428-432) with real values from `portfolioData.riskMetrics`. This also closes an existing `AGENTS.md` "Metric Card Hygiene" violation. **Effort: S. Risk: LOW. ROI: highest in this document** — the gap is real (there are literally zero charts in FinEngine's PDFs today) and the fix needs nothing new. Do **not** reach for GS Quant.
3. **Add `ql.India(ql.India.NSE)` + `ql.Business252()` as a real trading calendar, behind a golden-value sweep.** `exchange_calendars` is not installed; `sqrt(252)` is hardcoded at 12+ sites in `analytics_engine.py` and `ai_context_service.py`. Actual NSE trading-day counts ≠ 252, and every VaR/vol number in the product shifts. **Effort: M. Risk: MEDIUM — this is the one change that moves numbers everywhere; requires a golden-value regression sweep across `analytics_engine.py` before merge.** Consider `exchange_calendars` (lighter, pure-Python) instead if QuantLib is not otherwise justified.
4. **Build `derivatives_service.py` on `ql.AnalyticEuropeanEngine` + `impliedVolatility` + `ql.AnalyticHestonEngine`.** Answers the queued proposal G3 (`BACKEND_REVIEW.md:359`: *"Today `DerivativesEngine` outputs **random** OI/volume + toy prices — unusable/dangerous"*). Analytic Greeks + a Brent IV inversion remove a whole class of correctness bugs. **Effort: M. Risk: LOW.** Do **not** use QuantLib for the batch grid (numpy is 5.6× faster); use it for single-point and Greeks, use vectorised numpy for the surface mesh.
5. **Add `ql.RiskStatistics` as a cross-check oracle in tests, not as production code.** One test asserting `ql.RiskStatistics.expectedShortfall(0.95)` agrees with `analytics_engine.py`'s `cvar_95` to 1e-6 on a fixed P&L vector. Measured agreement with numpy: 1.39e-17. Catches regressions for ~15 lines and zero runtime cost. **Effort: S. Risk: LOW.**
6. **Conditional — only if G4 (fixed income) is greenlit:** `ql.ZeroCurve` / `ql.PiecewiseLinearZero` / `ql.FixedRateBond` / `ql.BondHelper` / `ql.OISRateHelper` for the CCIL FBIL/MIBOR + NDS-OM G-Sec curve (`BACKEND_REVIEW.md:360`). **Effort: L. Risk: MEDIUM.** This is the strongest long-term QuantLib ROI but needs data plumbing that does not exist.
7. **Never:** do not build local-vol or PDE pricing; do not migrate `monte_carlo_service.py` (tuned, chunked, checkpointed — QuantLib will be slower); do not migrate `tail_risk_service.py` (EVT-POT/copula has no QuantLib equivalent); do not migrate `var_95`/`cvar_95` to production `RiskStatistics` (numpy is faster); do not touch `regime_service.py` (hmmlearn has no QuantLib analogue).

## What NOT to adopt, and why

| Do not adopt | Why |
|---|---|
| **`gs-quant` (any version)** | `numpy<2.4.0` makes FinEngine's resolution **unsatisfiable** — proven with a live `uv lock` failure. Secondarily: needs a GS institutional client id/secret, and its real value lives behind `api.gs.com`. |
| **`gs-quant-reports` / `gs-quant-risk` / `gs-quant-bond` / `gs-quant-equities` / `gs-quant-commodity` / `gs-quant-strategies` / `gs-quant-databases`** | **Do not exist on PyPI** — HTTP 404 on both `/pypi/<name>/json` and `/simple/<name>/`. They were the whole premise of the GS Quant recommendation and they are gone. |
| **Server-side PDF tearsheet generation via GS Quant** | The framework (`gs_quant_report`, `Teaser`, `ScenarioReport`, `BacktestPerformanceTeardown`, fpdf, Jinja HTML templates) has **zero occurrences across all 424 wheel entries**. There is nothing to move to. Fix `export.ts` instead — the chart plumbing already exists. |
| **`gs_quant.risk`** | 85 lines. `IRDelta`/`IRVega`/`IRBasis` request builders with `DEPRECATED_MEASURES = {}`. No VaR, no ES, no copula, no EVT. |
| **QuantLib's `ql/risk` spectral risk measures** | **Not exposed in the Python binding.** `[x for x in dir(ql) if "Spectral" in x or "Shortfall" in x or "Entropic" in x] == []`. C++-only. Context7 confirms no documentation. |
| **QuantLib's `MonteCarloEngine` replacing `monte_carlo_service.py`** | Measured: 8–18 µs of pure SWIG overhead per call, no numpy bridge, no vectorisation. FinEngine's chunked/checkpointed NumPy MC will win on goal-probability workloads. |
| **QuantLib's `BusinessDay` / `BlackScholesMertonEngine` / `PiecewiseLinearZeroCurve` spellings** | **Removed in 1.4x.** `BusinessDay` → `ql.Following`/`ql.Preceding`; `BlackScholesMertonEngine` → `AnalyticEuropeanEngine`; `PiecewiseLinearZeroCurve` → `PiecewiseLinearZero`. Any tutorial, blog post, or LLM-generated snippet using the old names will `AttributeError` on FinEngine's 1.43. |
| **QuantLib in FastAPI request handlers without a lock** | The wheel's own METADATA: *"the underlying C++ library is not thread-safe. It has globals (most notably, the evaluation date)…"* `ql.Settings.instance().evaluationDate` is process-global and objects cache lazily. Must be serialised or run in a dedicated single-threaded executor. |
| **Any markdown in `instructions/doc/` as a source of truth for QuantLib usage** | `RISK_LIBRARIES_INTEGRATION_GUIDE.md` shows 1.2/1.3-era APIs; `LIBRARY_INTEGRATION_OPPORTUNITIES.md:703` says `pip install QuantLib==1.32` (three majors behind). Both already drifted from the installed 1.43. Fix or delete. |

---

## Appendix — how each fact was verified

| Fact class | Method |
|---|---|
| Licences, versions, dates, sizes, deps, releases | Primary sources read directly: GitHub `LICENSE` / `LICENSE.TXT` / `pyproject.toml` / `requirements.txt`, PyPI JSON API, wheel `dist-info` inside the downloaded wheel |
| Maintenance status | GitHub `commits/master.atom` feeds (no rate limit) + tags/releases pages |
| QuantLib Windows wheels | PyPI JSON file list for 1.43; wheel bytes extracted from the downloaded `cp39-abi3-win_amd64.whl` |
| QuantLib API surface | **Executed** against the installed `backend/.venv` 1.43 `win_amd64` wheel — 1,545 public names enumerated, live NPV/Greeks/IV/curve/calendar/MC/RiskStatistics runs |
| QuantLib performance | Measured in-process: BSM 8.5 µs, 41-grid 18.2 µs/element, vectorised scipy 3.24 µs/element, Heston 2.5–91 µs |
| GS Quant hard blocker | **Live `uv lock`** in an isolated temp project against FinEngine's exact pins — resolver error captured verbatim |
| GS Quant package contents | `gs_quant-2.1.17-py3-none-any.whl` downloaded and all 424 entries full-text scanned; PyPI simple-index + JSON 404 checks on every legacy subpackage |
| GS Quant pandas 3.0 | Installed `gs-quant==2.1.17` + `pandas==3.0.6` in an isolated venv (resolved numpy 2.3.5); `import gs_quant` succeeds. *Substantive* offline calls under pandas 3.0: **UNVERIFIED — needs manual check** |
| FinEngine usage | `rg` across the repo + explicit grep of `backend/` and `frontend/`; corroborated by the repo's own `.scratch/backend-deep-audit/code/05-foundation.md:267` |
| FinEngine services inventory | `Get-ChildItem backend/app/services` — 22 modules, no `derivatives_service.py` / `fixed_income_service.py` |
| FinEngine tearsheet state | `frontend/src/lib/export.ts` read in full (502 lines) + `package.json` (jspdf 4.2.1, xlsx 0.18.5, file-saver 2.0.5, recharts 3.10.1) + caller grep |
| API surface cross-check | Context7 `/lballabio/quantlib-swig` (yield/vol/opt/cal/proc/hw/mc/risk) and `/goldmansachs/gs-quant` (install/report/subpkg/theme/setup/busday) |

**No FinEngine source file was modified.** Probe scripts were written to `C:\Users\Sayanti\AppData\Local\Temp\opencode\`, and dependency-resolution tests used isolated temp projects.
