# Wave 3 — decision support: what the user asked for

**Date:** 2026-09-30
**Status:** proposed, pending adversarial review
**Predecessor:** wave 2 (11 backend defects + instrument; PDF rebuilt; marginal-impact endpoint in flight)

## 0. The goal, verbatim

> "a system that helps user make decision whether to buy new stock or adjust the current
> portfolio or how new buy or sell or effect the portfolio or any kind of analytics you can give
> that helps make decisions. i dont need real time order execution or similar."
> "i want to maximize returns and minimize risk. that is my main goal."

## 1. What the evidence established, and what it forbids

Three independent findings converge, and they constrain the design rather than suggest it.

**The composite score is structurally incapable of being a decision instrument.** Of five
hand-typed weights, `market_risk` and `volatility` are byte-identical at 39 return rows
(0.35 combined, documented by the repo's own test), `factor_risk` is pinned at its 30 ceiling
for any R² ≤ 0.70, and only **concentration (0.20) is a function of the user's decisions.**
Observed movement 12.7 → 12.8 → 13.1 on a 0–30 scale — 0.4 points, 1.3%, all inside the LOW
band, `risk_level` never changed. It is substantially a volatility meter with an invented scale.
**The weights are published in the API payload and appear nowhere in the frontend**, and
`RiskMetricsDisplay.tsx` shows a "Risk Alert if > 50" threshold that is **unreachable on a 0–30
scale.**

**Do not collapse two objectives into one number.** Sharpe's own text: the ratio *"will not by
itself provide sufficient information to determine a set of decisions that will produce an
optimal combination of asset risk and return"* — and correlations are exactly the binding term
in a multi-asset long-only book. The literature's one route to resolving the trade-off without
asking the user, **Tobin's separation theorem, requires a riskless asset** this product does not
have. DeMiguel et al.: across seven datasets no optimized model beat 1/N out-of-sample.

**Do not ask the user for a risk-aversion coefficient.** Elicitation methods "do not converge
well with one another or with real-world behavior, and have poor temporal stability."

**Do not call a historical mean "expected return."** `mu = returns.mean() * 252`. The engine
already publishes a bootstrap CI on it: at n=39 the standard error is 2.54σ, so the 95% interval
is wider than the plausible return range. A per-asset 1-year mean is a defensible **X axis for
ranking held alternatives on one stated window** and indefensible as a forecast.

**The engine persists no price frame**, so **no measure here can produce a decision-attributable
before/after delta** (`change_reason: "no_persisted_prior_score"`). The only decision-caused
quantities are **functions of the weights alone** — HHI, effective-N, risk-contribution shares,
concentration tiers.

**Windows disagree across sections** — 0.0881 to 0.2076 for "this portfolio's volatility" across
eight, with no cross-reference. A chart putting a 252-day axis beside a 365-day bubble size
reproduces that defect in a more persuasive-looking chart.

## 2. Tasks

### T1 — The optimizer's trade list gets an apply path

**Files:** `frontend/src/app/dashboard/optimize/page.tsx`, new test files
**Depends on:** nothing
**Why first:** highest decision value per unit of effort in the whole product.

`/dashboard/optimize` publishes a reconciled trade list — `trades_required` with
`current_weight` / `recommended_weight` / `weight_delta` and an explicit reconciliation rule —
and **stops there.** The user transcribes the trades by hand. Meanwhile
`frontend/src/app/dashboard/volatility-sizing/page.tsx:757-802` already implements exactly this:
a dry run through `rebalancePortfolio(weights, true)`, a confirm dialog, then
`rebalancePortfolio(weights, false)`, fail-closed behind `executionEligible` /
`executionBlockReason`.

**Copy the existing pattern. Do not invent a second execution flow.** The trade list must be
applied from the values the optimizer published, and the reconciliation rule must be surfaced so
the user can see what the apply will do before confirming.

**Also fix, same file, same task:** `page.tsx:275-276` does
`result.current_weights[ticker] ?? 0`. A ticker absent from `current_weights` therefore reads as
0% current weight and the table shows a **full-size buy for a position the optimizer simply
omitted.** That is the most actionable artifact in the product displaying a wrong instruction.

**Verify:**
```
cd frontend
bun x tsc --noEmit
bun x vitest run src/test/pages/OptimizeApplyRebalance.test.tsx
bun x eslint src/app/dashboard/optimize/
```
Plus a test that a ticker absent from `current_weights` does **not** render as a full-size buy.

### T2 — The shared null-discipline breach

**Files:** `frontend/src/lib/utils.ts`, and the `?? 0` call sites named below
**Depends on:** nothing

`formatPercentage` (`utils.ts:56`) is exported and shared, and has **no null guard**:
`formatPercentage(null)` → `(null*100).toFixed(2)` → **`"0.00%"`**. It is the one formatter
outside `format-invariants.test.tsx`'s net. This is a standing violation of the project's
absolute rule for every page importing it.

The same class, individually named by the audit:
- `dashboard/page.tsx:158-161` — `totalValue || 0` renders an empty or unmeasured book as `₹0.00`
- `dashboard/page.tsx:697-701` — weight-drift `.toFixed(1)%` unguarded
- `dashboard/page.tsx:533`, `RiskMetricsDisplay.tsx:139,146` — truthiness guards, so a legitimate
  measured `0` renders as `N/A` (the opposite error)
- `realized-risk/page.tsx:111-113` — `p.portfolio_value || 0` seeds the drawdown chart series
- `factor-exposure/page.tsx:762,771,780` — `?? 0` as progress-bar **widths**: an unmeasured R²
  decomposition renders as three empty bars, indistinguishable from "0% systematic"
- `risk-contribution/page.tsx:554` — absent tail contribution reads as zero tail risk
- `liquidity/page.tsx:690` — `highVolumeCount` filters on `score != null`, silently dropping
  unscorable positions from the denominator
- `risk-studio/page.tsx:267` — `(volShare || 0) * 100`

**The rule, applied uniformly:** null/undefined/NaN → `N/A` or a dash, **never `0`**; and a
measured `0` must still render as `0`, not `N/A`. Both halves. Widen
`format-invariants.test.tsx`'s net to cover every exported formatter.

**Verify:**
```
cd frontend
bun x tsc --noEmit
bun x vitest run src/test/unit/format-invariants.test.tsx
bun x eslint src/
```
Plus a test per named site proving null renders as `N/A` and a measured `0` renders as `0`.

### T3 — A stale number must not look live

**Files:** the section pages named below, plus a shared component
**Depends on:** nothing

`as_of` and `as_of_semantics` are computed and published on **15 of 17 sections. Only `regime`
and `india-flows` display a date.** Realized-risk, forecast-risk, factor-exposure, concentration,
liquidity, stress-testing, tear-sheet, risk-contribution, risk-studio, optimize, monte-carlo,
pairs and volatility-sizing show **no measurement date at all.** A stale risk number is currently
visually identical to a live one.

Similarly `coverage.missing_tickers` renders on **1 of 17 routes** — a holding silently dropped
from a computation leaves no on-screen trace. And `warnings[]` is never rendered outside the JSON
dump, as is the entire `snapshot_consistency` evidence block, so a user cannot tell a
single-instant snapshot from a drifting one.

**One shared component, applied to every section page.** Do not solve this 15 times.

**Verify:**
```
cd frontend
bun x tsc --noEmit
bun x vitest run src/test/unit/section-provenance.test.tsx
bun x eslint src/
```
Plus: a test per page asserting the measurement date and the missing-ticker disclosure are on
screen, including when `as_of` is null.

### T4 — The return/risk view that replaces 13.1

**Files:** `backend/app/api/analytics.py` (the `instrument_risk.positions` dict literal), then
`frontend/src/components/charts/` (new), `realized-risk/page.tsx`
**Depends on:** the marginal-impact endpoint, and T3 for the provenance labelling

**The backend change is five keys — but NOT a bare dict-literal copy.** `_calculate_basic_metrics`
(`analytics_engine.py:5481-5487`) already computes `annual_return`, `annual_volatility`,
`sharpe_ratio`, `sortino_ratio`, `hit_ratio`, and `_calculate_risk_metrics` (`:5503-5506`)
computes `var_95`, `cvar_95` — all per position, on the 252-day frame, assembled by
`_calculate_position_metrics` (def at `:5672`). The `instrument_risk` dict literal at
`analytics.py:4498-4504` reads **3 of 8** and substitutes a cumulative `total_return` of its own.

> **CORRECTION after adversarial review — "no engine change, it's a dict-literal edit" was
> wrong, and following it would have published a fabricated point on the chart's X axis.**
> `_calculate_basic_metrics` returns `None` for `annual_return`/`sortino_ratio` only below **10**
> observations (`analytics_engine.py:5436`). The route's own gate is the **next statement**,
> `analytics.py:4505`:
> `apply_annualization_gate(row, ["annual_volatility", "sharpe_ratio"], own_days)` — and
> `MIN_ANNUALIZE_DAYS = 30` (`app/utils/holdings.py:35`).
>
> So an asset with **10–29 return observations yields a non-null `annual_return` that the current
> gate does not list.** A naive copy publishes it. `full_portfolio` two lines up *does* gate
> `["annual_return", "annual_volatility", "sharpe_ratio", "sortino_ratio"]` (`:4484-4488`) — so the
> per-position block is the odd one out, and the fix is to **add `annual_return` and
> `sortino_ratio` to the list at `:4505`**, making the two blocks agree. No engine change; the
> gate is already correct, it is just not being asked to cover these keys.

**Also per adversarial review — the panel distinction is cosmetic, not protective.** Separating
the weight-derived quantities changes the visual channel, not the inference; a user still reads
"18% return, 30% vol → buy it." What actually blocks the misattribution is the three together:
the axis label, the observation count on every point, and **a greyed or hidden treatment for
sub-30-observation points**. Do all three.

**The view, in this order:**
1. Per-asset points at (annual_return, annual_volatility) from `instrument_risk.positions`, all
   on the 252-day frame. **X axis labelled as a 1-year historical mean on a stated window, never
   "expected return."** Each point annotated with its `return_observations`.
2. The portfolio's own point from `instrument_risk.portfolio`.
3. **A separately, explicitly labelled panel for the weight-derived quantities** — HHI, effective
   positions, top-3 from `get_concentration_metrics`, and the risk-contribution shares. **These
   are the only numbers that move because the user traded**, and they are the decision content.
4. The composite score, **demoted**: shown with its weights, its band, and the structural note
   that 0.35 of its nominal weight is double-counted on this book. It is retained for
   completeness, per the owner — not deleted, not presented as the headline.

**`recharts` is already a dependency and already ships `ScatterChart`;** the existing
`optimize/page.tsx` already renders one. **No new dependency and probably no new chart
component** — establish that before writing one.

**Verify:**
```
cd backend
uv run --extra dev pytest tests/test_per_position_return_risk.py -q --no-cov
cd ../frontend
bun x tsc --noEmit
bun x vitest run src/test/pages/ReturnRiskView.test.tsx
```
Plus a test asserting every axis states its window, and that no label reads "expected return".

### T5 — Charts where the data already is

**Files:** the page files below. **Depends on:** T2 (a chart fed a defaulted `0` is worse than no
chart) and T3.

**8 of the 9 chart-less exported sections already have the data.** This is rendering work, not
analytics work. `pairs` is the sole exception — the endpoint returns per-pair summary statistics
only, so a spread chart needs a backend change and is out of scope here.

Ranked by decision value: `risk_contribution` (per-position vol/VaR/CVaR shares), `liquidity`
(per-position volume, turnover, spread), `india_flows` (30-day FII/DII daily series),
`volatility_sizing` (current vs recommended weight), `stress_testing` (per-scenario,
per-position impact), `regime` (120-day history, today CSS blocks), `factor_exposure` (per-position
loadings), `portfolio` (allocation).

**Verify:** per page, `bun x vitest run <its test file>` plus a test asserting the chart is fed
the section's own fields and that a null reaches it as a gap, not as a zero.

## 3. Dependencies

**CORRECTED after adversarial review.** The previous claim — "T1, T2 and T3 are independent and
dispatch together" — was **false**, and following it would have lost edits. Enumerated against the
actual tree:

- **T1 ∩ T3 = `{optimize/page.tsx}`** — T1 writes it (the `?? 0` fix at `:275-276` plus the whole
  apply path); T3 names `optimize` in its page list.
- **T2 ∩ T3 = 5 files** — `realized-risk`, `factor-exposure`, `risk-contribution`, `liquidity`,
  `risk-studio` are all in T2's call-site list *and* T3's page list.
- **T1 ∩ T2 = ∅** — the only genuine independence in the graph.

Revised edges:

```
T1  ──────────────┐   (T1 ∩ T2 = ∅: the only true independence)
T2  ──────────────┤
                  ├──► T3   (serialized after BOTH; shares optimize/page.tsx with T1
                  │          and five more files with T2)
                  ├──► T4   (needs T3's provenance labelling + the marginal-impact endpoint)
                  └──► T5   (needs T2's null discipline and T3's provenance labelling)
```

**Dispatch order: T1 and T2 together. T3 after both. T4 and T5 after T3.**

## 4. Wave exit criteria

1. Every `Verify:` command run by the **parent**, output pasted.
2. Full frontend suite: `bun x vitest run` — currently **39 files / 339 tests**, and it must
   not lose one. `bun x tsc --noEmit` clean. `bun x eslint src/` error count must not rise from
   **0** (271 warnings is baseline).
3. Full backend suite uncontended — the suite shares a file-backed `test.db`. Baseline **5
   failures**: 3 order-dependent in `test_bugfix_api_layer.py`,
   `test_compose_services::test_published_backend_and_frontend` (no server), and
   `test_agent_a_quant_fixes::test_a13` (a pre-existing nondeterministic test that fails in
   isolation).
4. `oracle` over the final diff — T1 adds a mutation path to a product that currently mutates
   from exactly one page, which is the single largest behavioural change this project has made.

## 5. Deliberately not in this wave

- **Any new composite score.** Omega, Sortino, Calmar, Ulcer, a deflated Sharpe — all are the
  same collapse, and worse, because the number becomes a ratio of two estimated quantities. The
  owner's rejection was of the *behaviour*, and no replacement addresses that reason.
- **A risk-aversion slider.** The elicitation literature is against it, and the optimizer loses
  out-of-sample anyway.
- **A `what-if` UI on top of T1's apply path.** The marginal-impact endpoint is the what-if; a
  second, competing one would be a worse version of the same thing.
- **Persisting a price frame** to enable before/after deltas. It is a schema change, not a small
  one, and the engine has explicitly declined it. The weight-derived quantities are the
  decision-attributable ones.
- **Charts for `pairs`** — needs a backend endpoint that returns spread history.
- **`data_ref` resolver.** The audit confirmed a resolver can never dangle, but no consumer needs
  one: every page re-derives from its own REST endpoint, and the default export is
  `detail=summary`, which trims the series a chart would need. Building the resolver before a
  consumer exists is speculative.
