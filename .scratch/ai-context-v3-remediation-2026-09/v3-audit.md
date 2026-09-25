# v3 Audit Evidence Ledger

Artifact: `C:\Users\Sayanti\Downloads\finengine-portfolio-ai-context v3.json`

SHA-256: `7CFBDEFB0F0B1CC05A9EC12BE5D1E2CDD0411151B12410308FAB60A9403FF49E`

Generated: `2026-09-25T14:18:18.798623Z`

Completed: `2026-09-25T14:18:43.392401Z`

## Findings

| ID | Severity | Evidence | Owner |
|---|---|---|---|
| V3-01 | High | 47/49 `weight_basis` values claim active-weight renormalization although all 14 tickers are covered; weightless analyses carry the claim. | 01 |
| V3-02 | High | Dashboard requests 90 performance days but returns 20 rows, `2026-08-25` to `2026-09-22`, with no warning while dashboard `as_of` is `2026-09-25`. | 02 |
| V3-03 | High | Volatility sizing gross weights sum to `1.290041`, `cash_weight=0`, `leveraged=true`, and net trades buy INR 12,648.30 without a financing leg; rebalance normalizes targets to 100%. | 03 |
| V3-04 | High | Eight volatility-sizing `shares_delta` values are zero despite large trade amounts inconsistent with the exported portfolio quotes. | 03 |
| V3-05 | High | Factor Exposure and Risk Contribution use full exchange history but report holding-window `effective_start`/`truncated` metadata as if the model were truncated. | 05 |
| V3-06 | Medium | NIFTYIETF has 20 return observations, but warnings use portfolio/global 39/176-day counts, generic `limited_history` disagrees, and wording says “held since” an inferred pre-`added_on` date. | 04 |
| V3-07 | Medium | Dashboard summary leaves forecast/liquidity null despite available siblings; Risk Score publishes hardcoded `change=0`; partial nulls have no field-level reason. | 02 |
| V3-08 | Medium | Concentration `Industrials=0.0984`; exact recomputation is `0.0983` because sector values are rounded during accumulation, producing a 1.0001 displayed total. | 06 |
| V3-09 | Medium | Liquidity reports score 8 with Medium band; SELECTIPO market cap is an undisclosed INR 1bn floor; currency/as-of/window evidence is incomplete. | 06 |
| V3-10 | Medium | Stress `max_drawdown` is `portfolio_impact × 1.15` and confidence is hardcoded 0.95, but labels imply simulated statistics. | 06 |
| V3-11 | Medium | Monte Carlo has no success semantics, currency, or as-of; `0.335` is terminal year-5 success, not path-touch success. | 07 |
| V3-12 | Low/Medium | Optimizer omits risk-free rate, model window/observation count, and exact execution-normalization rule. | 07 (consumes 03 normalization) |
| V3-13 | Medium | Regime probabilities and transition rows are percentage points summing to 100 but the AI contract does not state the unit, benchmark series, or posterior type. | 07 |
| V3-14 | Medium | Pairs counts pass, but NIFTYIETF pairs have roughly 106–109 observations versus 168–174 for peers while status remains `complete`; Johansen’s diagnostic-only role is unlabeled. | 07 |
| V3-15 | Medium | India composite coverage is `unknown` with meaningless weight basis despite nested liquidity coverage being 14/14; component inputs and date scopes are incomplete. | 08 |
| V3-16 | Medium | `data_status=complete` leaks coverage vocabulary; successful sections publish `error:null`; ordering is not uniformly deterministic; currency/freshness fallbacks are untested. | 01 |
| V3-17 | Medium | Portfolio, summary, Forecast Risk, Risk Studio, and Tear Sheet need explicit delivered window/calculation-basis evidence or a documented “no change required” verification. | 02/04/05/09 |

## Verified passes

- Strict JSON, schema shape, timestamp ordering, and finite-number semantics.
- All 14 portfolio positions, totals, weights, costs, P&L, and currency identity.
- Byte-identical dashboard portfolio reuse.
- Per-position NIFTYIETF annualization suppression.
- Risk Contribution sums, sector rollups, and Risk Studio matrix/cone/correlation invariants.
- Optimizer 14-asset universe and weight-delta arithmetic.
- Regime HMM sample/transition structure and conditional annualization gate.
- Monte Carlo fan monotonicity and 2× target policy.
- Pairs combinatorial counts and Engle–Granger classification.
- Honest India unavailable/available component states.
- bfinance approval gate: v3 used yfinance for effective windows; no bfinance change is justified by this artifact.

## Pre-existing full-suite baseline

Current full backend run before remediation: **674 passed, 6 failed, 680 collected**.

Known unrelated/order-dependent failures:

1. `test_bug_sweep_2026_09.py::test_rebalance_rejects_zero_portfolio_value`
2. `test_bugfix_api_layer.py::test_summary_passes_benchmark_to_risk_scoring` (passes in isolation; order-dependent)
3. `test_bugfix_api_layer.py::test_config_get_propagates_errors`
4. `test_bugfix_api_layer.py::test_stock_data_reports_source_and_from_cache`
5. `test_bugfix_equity_research_503.py::test_full_profile_runtime_error_maps_to_503`
6. `test_phase2_disclosure.py::test_realized_risk_case_a_intersection_copy`

Ticket 09 must report any additional regression by test ID.

## bfinance fail-closed rule

No ticket may edit bfinance. A bfinance limitation must never be hidden through fabricated zero data, assumed market cap, silent backfill, or a bfinance change. Mark the affected FinEngine field `estimated`, `fallback`, or `unavailable` using the shared provenance vocabulary. If bfinance itself must change, stop the ticket, write a source-specific proposal under `.scratch/` containing evidence, design, compatibility impact, and verification, request explicit user approval, and keep the ticket blocked.
