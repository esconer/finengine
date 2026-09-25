# Portfolio AI Context Export

FinEngine exposes one AI-ready snapshot of the portfolio analytics pages. It does not scrape the rendered UI and does not call Equity Research or Screener Studio.

## Endpoint

```http
GET /api/v1/ai/context?format=json&detail=summary
GET /api/v1/ai/context?format=markdown&detail=full
```

`format=json` returns the canonical envelope. `format=markdown` renders the same payload as Markdown. `detail=summary` shortens bulky chart/history series; `detail=full` retains them. The current envelope `schema_version` is `1.1`.

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

- `status`: `available`, `partial`, `unavailable`, or `not_requested`
- `route`: the corresponding frontend page
- `inputs`: the exact model/window/scenario inputs used
- `coverage`: requested/available/missing tickers and coverage ratio
- `data`: the canonical result, or `null`
- `as_of`, `currency`, `warnings`, and `error` when applicable
- `omitted_fields` when summary mode shortened raw series

`base_currency` controls the portfolio snapshot. Analytics sections retain the monetary unit declared by their underlying endpoint (currently INR for most analytics); the top-level `currency_policy` makes this explicit. `generated_at` is the collection start, `completed_at` is the collection end, and `snapshot_consistency` is `best_effort` because live page endpoints can observe slightly different quote times during a full export.

The export never fabricates missing values. A failed provider or insufficient history is represented as an unavailable/partial section so an AI can distinguish absence from zero.

`coverage.requested_tickers` is the full persisted/request universe; `available_tickers` is the universe that produced the result; `missing_tickers` is never silently folded into a complete result. When an active-return calculation drops an unavailable leg, `weight_basis=active_weights_renormalized_to_100_percent` and the section is `partial` rather than a claim about the full book. Newly listed instruments may be retained as limited-history observations; no pre-listing prices are filled or back-filled.

The dashboard section composes the same canonical results used by its visible cards: portfolio, summary, performance history, realized/forecast/factor/concentration/liquidity/risk-score/regime/risk-contribution components. The export may still observe different quote times between live endpoint calls; this is why the envelope is explicitly `best_effort`, not an atomic market-data snapshot.

`as_of` prefers an actual latest observation date where the endpoint supplies one. Portfolio `as_of` comes from the newest persisted quote timestamp, while `holding_date_provenance` distinguishes stored `added_on`/quote `updated_on` fields from the effective holding start used by holding-window analytics. Requested window end dates are retained separately in inputs/data-range fields and are not substituted for an observation date.

India market components expose `data_status`: `available` means measured data exists, `partial` means only some symbols/legs are measurable, and `unavailable` means no usable stored/provider history exists. An empty anomaly list can therefore be a real zero-finding result or an unavailable result; consumers must inspect `data_status` and coverage.

Pairs responses distinguish requested/available universe size, analyzed combinations, returned rows, returned cointegrated/non-cointegrated rows, and tickers with insufficient pair overlap. Tail-dependence keeps the parent `tickers` list aligned with the nested matrix universe and stores the full requested list separately.

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
