# Phase 3 — Honesty and quantitative correctness

Status: ready-for-agent
Repo: this project, `backend/` + `frontend/`
Tickets: 28
Gate: **the `0.0` → `None` changes are breaking API contract changes.** Backend and frontend must
land in the same PR, and the OpenAPI schema diff must be reviewed deliberately.

## The problem in one paragraph

The app has excellent quantitative machinery — EVT-POT, Student-t copulas, HMM regimes, stationary
bootstrap, HRP, Black-Litterman, cointegration, Euler attribution — and it publishes a number for
almost every one of them **whether or not it has a measurement**. It also has a mature disclosure
contract (`data_status`, `universe_coverage`, `confidence_interval_status`) that it does not
consistently apply. On top of that, several metric cards render fabricated or mis-scaled values
that look entirely real.

This violates the repo's own stated principle, `CONTEXT.md` §9.23:

> *"engines must never render placeholder fallbacks (`_empty_factor_exposure`'s `{alpha:0, market:1}`
> showed as 'β +1.000 Market-Like' for every position) — return N/A + a flag, or compute on the full
> window."*

## Ticket map

### Frontend honesty (01–07)

| # | Ticket | Severity | Summary |
|---|---|---|---|
| 01 | Delete the fabricated `EXPLAINERS` numbers | HIGH | 7 pages present invented portfolio-specific figures as a "Quantitative Benchmark" |
| 02 | `stress-testing` is not a simulation | HIGH | Labels a deterministic proxy "Multi-Factor Simulation Engine"; never renders the `*_basis` fields the backend publishes |
| 03 | `portfolio/manage` unit + badge bugs | **CRITICAL** | Volatility rendered 100× low; **every position shows a green "Low" risk badge** |
| 04 | `pairs` z-score crash | **CRITICAL** | Unguarded `Optional[float]` → TypeError → white screen |
| 05 | Missing transport-error states | HIGH | 2 pages render a plausible all-`N/A` page on a 500 |
| 06 | `liveDataMode` pill | MEDIUM | "Live Data Active" from a local boolean; green through a full outage |
| 07 | Small frontend truthfulness | LOW/MED | 6 minor fabricated/mis-bound values |

### Quantitative correctness (08–18)

Every one was executed or proved by algebra. **None are in the known-24 gotcha list.**

| # | Ticket | Severity | Measured defect |
|---|---|---|---|
| 08 | Degenerate concentration returns | HIGH | 1-stock book publishes `diversification_score: 0.0` **and** `diversification_ratio: 1.0` |
| 09 | `_empty_concentration` is scored | HIGH | `HHI=0.0` contributes **minimum risk** to `overall_score` |
| 10 | `annual_return` is unannualized | HIGH | 5-day series published as 5.5% vs true annualized 277% — **50× understatement** |
| 11 | Black-Litterman publishes the wrong Sharpe | HIGH | Asserts it maximised the BL posterior; publishes the sample-μ Sharpe. **+11% off** |
| 12 | Stress vol drops zero-return days | HIGH | **+11.8% vol** → every stress loss inflated |
| 13 | WebSocket Sharpe `0.0` as "measured" | HIGH | Fabricated `0.0` passes the `data_status` guard |
| 14 | Three different EWMA implementations | MED | 0.65% divergence; the 60-day cap alone is worth 11% |
| 15 | GARCH "multi-step" has no √h | MED | `horizon=63` returns 19.1% instead of ≈87% |
| 16 | Liquidity turnover formula | MED | `mean(vol) × last_close` → **2× error** moves names across tier boundaries |
| 17 | Missing close column scored as illiquid | MED | Missing column → measured 3.0/10 "Low" score, "High" risk |
| 18 | CVaR contributions normalized by `Σ\|c\|` | MED | A genuine hedge makes shares sum to ≠1; shortfall published as `rounding_residual` |

### Regime, cointegration, and residual degenerate zeros (19–22)

| # | Ticket | Severity |
|---|---|---|
| 19 | Unoccupied HMM state ranked on a fabricated `0.0` | MED |
| 20 | HMM convergence never checked | MED |
| 21 | Cointegration z-score `0.0` for a flat spread | MED |
| 22 | Remaining degenerate zeros across services | MED |

### Units and status contracts (23–28)

| # | Ticket | Severity |
|---|---|---|
| 23 | Declare a `units` block per response field | HIGH — **root cause RC4** |
| 24 | Delete every scale-sniffing formatter | HIGH |
| 25 | Unify the 6-way status-code split for one outage | MED |
| 26 | `/performance-history` hides its own warnings | HIGH |
| 27 | Real risk-free rate and Total-Return benchmark | HIGH — **two wrong constants** |
| 28 | Remove the fabricated `0.0` API defaults; drift-guard the globals | MED |

## Root cause RC4 in detail

`market_cap` has **four spellings in three units** with no declaration at the quote boundary:

```
data_service.py:934            fast_info.market_cap         ← unit undeclared
data_service.py:981            info["marketCap"]            ← absolute ₹
equity_research_service.py:87  market_cap / marketCapInCr   ← ₹ Cr
company_data_service.py:186    r.market_cap * 1e7           ← absolute ₹
```

Its consumer compares against hardcoded rupee thresholds
(`analytics_engine.py:751,755,759`) and publishes `market_cap_provenance: "measured"`. A Cr-valued
reading drops a mega-cap two tiers with no error.

The frontend then guesses the scale with `Math.abs(v) <= 1.0 ? v*100 : v` in four places — a
heuristic that mis-renders any legitimate value in `(-1, 1]`.

## Duplicated and drifting formulas — consolidate to one definition each

| Quantity | Site A | Site B | Divergence |
|---|---|---|---|
| EWMA vol | `volatility_service:109-117` | `analytics_engine:2207-2211`, `regime_service:165,191` | 3 implementations |
| GARCH multi-step | `volatility_service:164-170` | `analytics_engine:2037-2049` | `horizon=63` differs by √63 ≈ 7.9× |
| BL Sharpe | `optimization_service:503,513-517` | `optimization_service:582` | +11% |
| Zero-return policy | `analytics_engine:1013` **drops** | `analytics_engine:2334-2336` **keeps** | +11.8% vol |
| VaR (≥4 constructions) | empirical `pctile(r,5)`: `analytics_engine:1808`, `analytics.py:6048`, `tail_risk_service:71` | fitted `σ×1.645`: `analytics_engine:2050-2054`, `analytics.py:3266` | all labelled "VaR" |
| Contribution normalization | `analytics.py:6040-6042` signed | `analytics.py:6075-6077` `Σ\|c\|` | shares ≠ 1 |
| CAGR fallback | `regime_service:238` | `holdings.py:465` | same silent switch |
| Empty concentration | `analytics_engine:669-674` guarded | `analytics_engine:2523-2536` | inverted semantics |

## The two wrong constants (issue 27)

```
config.py:53            risk_free_rate = 0.02      # India is 5–7.5%
benchmark_service.py:20  ^NSEI close, price-only   # understates by ~1.2–1.4%/yr
```

These two contaminate **every** relative-performance number the app publishes: alpha, Sharpe,
Sortino, information ratio, the Black-Litterman posterior, Monte Carlo drift, and factor R². They
are roughly 150 lines to fix correctly, and every Phase 5 feature inherits the error until they are
fixed.

## Verified-correct — do not "fix" these

A quant audit specifically probed these and found them **correct**:

- EVT/POT Expected Shortfall at `tail_risk_service.py:89` — proved algebraically and numerically
  that `(VaR+β−ξu)/(1−ξ) ≡ E[X|X>VaR]`
- `_cumulative_forecast_volatility` cumsum logic
- HRP recursive bisection and `_quasi_diag` — `pandas 3.0.6` in-place `s.iloc[list] *= x` works, so
  HRP is **not** silently equal-weighted
- `_min_cvar` LP — verified it produces the lowest realized CVaR95 vs min_vol / hrp / max_sharpe
- Walk-forward backtester no-look-ahead
- OU parameters, Johansen, Engle-Granger
- Correlation ρ̄ formula
- QuantStats integration

## Verification

- Extend `tests/test_quantitative_invariants.py` with every quantitative ticket.
- Component tests assert `N/A` rendering for each `0.0` → `None` change, the `pairs` null guard,
  and the `portfolio/manage` ×100.
- A test asserts no `EXPLAINERS` string contains a bare percentage that is not bound to the
  response.
- Snapshot the `/api/v1` OpenAPI schema before and after. Every `0.0` → `None` change must appear
  in the diff deliberately.
- `pytest --cov-fail-under=80`, ruff `E9`+`F`, and `bun run test:run` stay green.
