# Portfolio AI Context Export

FinEngine exposes one AI-ready snapshot of the portfolio analytics pages. It does not scrape the rendered UI and does not call Equity Research or Screener Studio.

## Endpoint

```http
GET /api/v1/ai/context?format=json&detail=summary
GET /api/v1/ai/context?format=markdown&detail=full
```

`format=json` returns the canonical envelope. `format=markdown` renders the same payload as Markdown. `detail=summary` shortens bulky chart/history series; `detail=full` retains them. The current envelope `schema_version` is `2.0` (a breaking contract revision: `weight_basis` became conditional, the public status vocabularies were split, and successful sections no longer publish an `error` key).

The default scope contains:

- Portfolio Management and Dashboard
- Realized Risk
- Forecast Risk
- Factor Exposure
- Concentration
- Liquidity
- Stress Testing
- Volatility Sizing
- Tear Sheet
- Risk Contribution
- Risk Studio
- Optimizer
- Market Regime
- Goal Probability
- Pairs Scanner
- India Market Microstructure

## Section selection

Pass a comma-separated `include` value to limit the work:

```text
/api/v1/ai/context?include=portfolio,realized_risk,concentration
```

Unknown or excluded sections return `400`. A full default export runs the live analytics engines and can take longer than a single page request; use `include` to request a smaller snapshot when appropriate.

## Contract

Every section includes:

- `status`: `available`, `partial`, or `unavailable` (a section that was not requested is absent, not `not_requested`)
- `route`: the corresponding frontend page
- `inputs`: the exact model/window/scenario inputs used
- `coverage`: requested/available/covered/missing tickers plus coverage status, or `null` when the section has no ticker universe
- `data`: the canonical result, or `null`
- `as_of`, `currency`, and `warnings`
- `error` **only when the section failed** — see [Errors](#errors)
- `omitted_fields` when summary mode shortened raw series

`base_currency` controls the portfolio snapshot. Analytics sections retain the monetary unit declared by their underlying endpoint (currently INR for most analytics); the top-level `currency_policy` makes this explicit. `generated_at` is the collection start, `completed_at` is the collection end, and `snapshot_consistency` is `best_effort` because live page endpoints can observe slightly different quote times during a full export.

`snapshot_consistency` is a **collection mode** — `best_effort` or `frozen` — and says how the export was gathered. It does not say whether the prices that came back actually agreed. A v5 review counted 31 mismatching `(ticker, price)` pairs, up to 3.5% apart, across the same 14 holdings while the envelope still read `best_effort`, so the evidence now arrives beside the claim as `snapshot_consistency_measured` (`status`, `distinct_price_instants`, `distinct_delivered_bar_dates`, and both spreads). These are deliberately two keys: a `frozen` export whose clocks still disagree is a different finding from a `best_effort` one that happens to agree. The full block — per-ticker attribution under `per_position_price_as_of`, and a `what_this_invalidates` list — stays where it was measured, at `sections.portfolio.data.snapshot_consistency`.

**Price basis and cost accounting.** The portfolio section publishes an `accounting_basis` block: `gross_or_net: "gross"`, `net_of_costs: false`, `value_mark.adjusted: false`, and an explicit per-category `accounted_for: false` for dividends, corporate actions, fees, tax, slippage, turnover and survivorship. The artifact's numbers are gross and price-only. That block's `scope.does_not_cover` states that the basis of `monte_carlo`, the tear sheet and the optimiser is **unknown**, not gross — do not read the portfolio's declaration across sections.

The export never fabricates missing values. A failed provider or insufficient history is represented as an unavailable/partial section so an AI can distinguish absence from zero.

### Three separate status axes

Do not collapse these — they answer different questions, and each is derived independently.

| axis | vocabulary | question it answers |
| --- | --- | --- |
| `section.status` | `available`, `partial`, `unavailable` | Did this section produce a usable result? |
| payload `data_status` | `available`, `partial`, `unavailable` | Did measurable data exist for this component? |
| `coverage.status` | `complete`, `partial`, `unavailable`, `unknown` | How much of the requested universe reached the result? |

`data_status` is the **normalized public vocabulary** and never carries `complete` or `unknown`; those are coverage facts, not data-existence facts. A component can be `data_status=available` (measured data exists) while the section that carries it is `partial` because other requested tickers never became measurable. Coverage status remains available alongside it, so a consumer can always ask both questions.

### Coverage

`coverage.requested_tickers` is the full persisted/request universe; `available_tickers` is the universe that produced the result; `missing_tickers` is never silently folded into a complete result.

- `covered_tickers` is the requested ∩ available set, in requested order.
- `requested_count` / `available_count` size the universe without re-walking the arrays. `available_count` counts *covered* tickers, which is not necessarily `available_tickers.length`.
- `coverage_ratio` is covered/requested, or `null` when there is no requested universe.
- `complete` is tri-state: `true` only when nothing is missing, `false` when something is, `null` when coverage is unmeasured.
- `status` is the normalized axis: `unavailable` when the requested universe produced nothing measurable, `partial` when some tickers are missing, `unknown` when the endpoint does not report a result universe at all. **`unknown` is not `unavailable`** — it means "not reported", not "measured as empty", and the count fields are omitted in that case.
- `raw_available_tickers` preserves the endpoint's own wider `available_tickers` claim when the exporter had to subtract declared-missing tickers. It is an audit trail, not a coverage statement.

Any missing ticker downgrades an otherwise-`available` section to `partial` and appends a `Result coverage is missing requested ticker(s): …` warning, so a partial section always says which legs were dropped.

#### Conditional `weight_basis`

`weight_basis` is emitted **only** when an active leg was actually dropped and the surviving weights were renormalized to 100%:

```json
{ "weight_basis": "active_weights_renormalized_to_100_percent" }
```

The key is **absent otherwise**, and that is meaningful. A weightless analysis — correlation/tail matrices, pair scans, regime detection, calendar-series sections — has no allocation basis and must not claim one. Absence means "not renormalized, or not weight-bearing"; it never implies the full book was measured. When it is present, the section is `partial` rather than a claim about the full book. Newly listed instruments may be retained as limited-history observations; no pre-listing prices are filled or back-filled.

### Errors

A successful section **omits** the `error` key entirely. It is never published as `null`, `""`, or an empty array — a null-error sentinel on a healthy section is indistinguishable from a suppressed failure and must not be part of this contract.

```jsonc
// success — no `error` key
{ "key": "concentration", "status": "available", "warnings": [], "data": { … } }
// failure — `error` is a non-empty string
{ "key": "optimization", "status": "unavailable", "error": "Solver returned no feasible portfolio", "data": null }
```

Consumers must therefore test `section.error === undefined` (or `'error' in section`) and must not branch on `section.error === null`. `warnings` is always present, and is an array even when empty; `warnings` and `error` are not interchangeable — a section can warn and still succeed, and its `status` stays `available`/`partial` on its own merits.

### Deterministic ordering

Two exports of the same universe produce the same ordering:

- `sections` is keyed in `scope` order, and `scope` is the resolved request order (default catalog order when no `include` is passed). A key that was not requested is absent from both; a requested key that failed is present and carries its reason, so a section is never silently dropped.
- `requested_tickers` is uppercased, de-duplicated, and kept in stable persisted/request order. It is never sorted and never truncated.
- `covered_tickers` and `missing_tickers` follow `requested_tickers` order.
- `available_tickers` may be sorted, because a few sections union several result maps or pair rows (risk contribution, pairs, stress testing). Consumers must derive ordering from `requested_tickers` and must not assume alphabetical order from `available_tickers`.
- Pairs and tail-dependence responses likewise keep the parent `tickers` list aligned with the nested matrix universe and store the full requested list separately.

### Currency

`section.currency` is an **explicitly declared** unit or `null`. It is never inherited from the envelope.

Inference precedence, scanning `inputs` first, then `data`, then a nested `data`, then each component payload in order, taking the **first non-blank** of:

1. `currency`
2. `base_currency`
3. `portfolio_value_currency`
4. `value_currency`

Declared codes are uppercased. When no source declares one, `section.currency` is `null` — meaning *unknown unit*, not INR — even when the envelope `base_currency` is `INR`. Mixed-currency analytics stay explicitly unavailable rather than silently converting or assuming the base.

### Freshness

`section.as_of` is the newest **actual observation date** the endpoint supplies, or `null` when it supplies none. `null` means *unknown freshness*; it is never a claim that the data is current.

Inference precedence in the payload: `latest_observation_date`, `as_of`, `last_updated`, `updated_at`; then the same search under a nested `data`; then, for a composite, the **oldest** component timestamp — a composite is only as fresh as its stalest leg, so a dashboard can legitimately report an older `as_of` than its own portfolio quote. Requested window end dates are retained separately in `inputs`/data-range fields and are **not** substituted for an observation date. `generated_at` is never a fallback for `as_of`.

Sections that can measure their freshness differently publish an `as_of_semantics` label (e.g. `liquidity_component_only`, `latest_observation_date`) so a consumer can tell *what* the date measures rather than guessing.

`section.generated_at` is when the exporter collected that section, not when the data was observed. Portfolio `as_of` comes from the newest persisted quote timestamp, while `holding_date_provenance` distinguishes stored `added_on`/quote `updated_on` fields from the effective holding start used by holding-window analytics.

### Section behaviour notes

The dashboard section composes the same canonical results used by its visible cards: portfolio, summary, performance history, realized/forecast/factor/concentration/liquidity/risk-score/regime/risk-contribution components. Performance history is requested with delivered-window metadata, so a series materially shorter or staler than the request is reported as `partial` with the requested-versus-delivered ranges named; a bare legacy series is treated as `unknown` freshness rather than assumed complete. The dashboard also publishes a `component_as_of` map, and its summary links `forecast_volatility` / `liquidity_score` from the canonical sibling sections (copied, never mutated) with a machine-readable `field_status` reason when a sibling is unusable. Risk Score publishes `change: null` with `change_status: unavailable` and `change_reason: no_persisted_prior_score` because no prior score is persisted — an unchanged `0` is never presented as a measured delta. The export may still observe different quote times between live endpoint calls; this is why the envelope is explicitly `best_effort`, not an atomic market-data snapshot.

India market components expose the normalized `data_status` described above. The composite reports `component_inputs`, `component_coverage` and a per-component `component_as_of` map so heterogeneous components are never averaged into one claim: institutional flows are `scope: market_wide` with **no** ticker universe (and therefore no weight basis), delivery anomalies are symbol-scoped against the requested scrip roster, and only the portfolio-liquidity component carries ticker coverage. Section `universe_coverage` promotes the liquidity component with an explicit `source_component`; it is never populated from context tickers when liquidity is unavailable. `as_of` is the liquidity observation with `as_of_semantics: liquidity_component_only`, never the portfolio quote date. Missing FII/DII legs are `null` with `missing_categories` listed, never a measured zero, and an empty anomaly list is only a real zero-finding result when that component's status is `available`.

Active calculations use positive finite portfolio weights; zero-value persisted rows remain in the requested coverage universe but do not change portfolio scores or trigger FX calls. Mixed-currency Monte Carlo is explicitly unavailable until a base-currency total-return series is available; it must not silently treat local-currency returns as INR returns. Solvers and simulation routes return explicit unavailable/partial results below their minimum measured return sample rather than annualizing or solving a short/noisy history. Dashboard collection reuses request-scoped canonical section results, including Risk Contribution collected through Risk Studio.

Pairs responses distinguish requested/available universe size, analyzed combinations, returned rows, returned cointegrated/non-cointegrated rows, and tickers with insufficient pair overlap. They also publish `universe_scope` (`holdings_only` or an explicitly requested universe), per-ticker `usable_observations_by_ticker`, `depth_status` and `shallow_tickers`: a pair scanned off a materially shorter history than the deepest leg is a weaker result, so a shallow leg makes the scan `partial` rather than `complete`. `test_roles` states that the published decision is Engle–Granger and Johansen is diagnostic only.

#### Volatility sizing

A leveraged target is an analytical result, not a rebalance instruction. The section publishes `exposure` (gross/net exposure, cash weight, financing weight and amount) and `execution`, which carries `execution_eligible`, `block_reason(s)`, `financing_requirement` and the shared `normalization_rule`. The rebalance endpoint rejects a target whose weights sum above 1.0 with HTTP 400 instead of silently renormalizing it, so a leveraged target cannot be applied as a normal rebalance. `sizing_basis` names the one aligned price snapshot used to size every leg, with its currency and as-of date; a leg with no verified price is dropped from the sizing universe or marked `price_unavailable` rather than priced with a placeholder. `trades[ticker].shares_delta` is `null` — never `0` — when the notional is below the minimum lot or the price is unavailable, and `rounding_residual` reconciles `amount` against `shares_delta × price`.

#### Liquidity and stress semantics

Liquidity scores round once and the published band follows that same rounded value, so a score of `8.0` can never carry a `Medium` band. Per-position `market_cap_provenance` is `measured` (a quoted cap), `estimated` (annualized turnover) or `fallback` (the INR 1bn floor) with `is_estimate`; the floor is never presented as a measured cap. An unavailable liquidity result reports `null` score, risk level and window rather than a plausible mid score.

Stress scenarios are deterministic factor proxies: `max_drawdown` is `portfolio_impact × 1.15` and `confidence_level` is a nominal label. Both are tagged (`max_drawdown_basis: derived_from_shock_proxy`, `confidence_basis: nominal_label_not_simulated`) and the `methodology` string no longer implies an independently simulated statistic.

#### Regime, Monte Carlo and factor history

Regime probabilities and transition rows are **percentage points (0–100)**, declared by `probability_unit`/`transition_unit`. `posterior_type` is the filtered final-observation posterior while `current_regime` is the Viterbi decoded path, so the two can legitimately disagree — `current_regime_matches_posterior_argmax` reports it rather than hiding it. The benchmark series is named explicitly (`^NSEI`).

Monte Carlo `prob_success` is the fraction of paths whose **terminal** value at the horizon reaches the target. It is **not** a probability of touching the target at any earlier point; `success_definition: terminal_wealth_above_target` states this. `currency` is the unit the wealth levels are denominated in while `returns_currency` is the unit of the return series; the FX level cancels in the terminal/initial ratio, which is why the two are published apart.

Factor Exposure and Risk Contribution are hypothetical current-weight calculations over full exchange history. Their model window, observation count and annualization flag are reported separately from the holding-window context, and a `full_history_*` observation count never lengthens a short holding window.

## Optional controls

```text
base_currency=INR|USD
forecast_model=GARCH|EGARCH|EWMA
forecast_horizon=1..30
factor_lookback_days=30..756
optimization_strategy=hrp|min_vol|max_sharpe|min_cvar|black_litterman
monte_carlo_method=gbm|student_t|bootstrap
monte_carlo_horizon_years=1..40
monte_carlo_target_value=<positive number>
monte_carlo_seed=0..4294967295
```

When no Monte Carlo target is supplied, the exporter uses twice the current portfolio value and records that policy in the section inputs. The seed defaults to `42` so AI exports are reproducible.

## UI

Open `/dashboard/ai-context` to choose summary/full detail and JSON/Markdown, generate the report, preview it, copy it, or download it.

## TypeScript types

`frontend/src/types/index.ts` mirrors this contract: `AIContextResponse` / `AIContextSection` / `AIContextCoverage`, plus `AIContextStatus`, `AIContextCoverageStatus`, `AIDataStatus`, and `AIContextWeightBasis`. The doc comments there carry the same vocabularies and the same conditionality rules — notably that `weight_basis` is optional, that `error` is optional and absent on success, and that `currency`/`as_of` are nullable by design rather than defaulted. Contract fixtures live in `frontend/src/test/unit/ai-context-contract.test.ts` and fail `tsc` if these types drift from the documented contract.
