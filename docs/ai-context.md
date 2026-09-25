# Portfolio AI Context Export

FinEngine exposes one AI-ready snapshot of the portfolio analytics pages. It does not scrape the rendered UI and does not call Equity Research or Screener Studio.

## Endpoint

```http
GET /api/v1/ai/context?format=json&detail=summary
GET /api/v1/ai/context?format=markdown&detail=full
```

`format=json` returns the canonical envelope. `format=markdown` renders the same payload as Markdown. `detail=summary` shortens bulky chart/history series; `detail=full` retains them.

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
- `data`: the canonical result, or `null`
- `as_of`, `currency`, `warnings`, and `error` when applicable
- `omitted_fields` when summary mode shortened raw series

`base_currency` controls the portfolio snapshot. Analytics sections retain the monetary unit declared by their underlying endpoint (currently INR for most analytics); the top-level `currency_policy` makes this explicit.

The export never fabricates missing values. A failed provider or insufficient history is represented as an unavailable/partial section so an AI can distinguish absence from zero.

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
