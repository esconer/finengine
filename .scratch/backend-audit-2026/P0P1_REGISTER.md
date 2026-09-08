# Backend Audit P0/P1 Register — verified vs code 2026-09-07

Source: `.scratch/backend-audit-2026/BACKEND_REVIEW.md` (§3 catalog).
Method: full-doc read + two read-only subagents checking every item vs
current `main` (post-`82f824f`). Line numbers below are current-tree.

## P0 (9) — 8 fixed, 1 partial

| ID | Status | Evidence |
|---|---|---|
| P0-1 HRP bisection | FIXED | `optimization_service.py:46-64` `_cluster_var`, `:107-130` recursion, `:69-70` NaN guard |
| P0-2 Regime price/return guard | FIXED | `regime_service.py:59-75` heuristic, `:157-161` cumprod path |
| P0-3 Coint cache collision | FIXED | `cointegration_service.py:36-39` sha1 keys |
| P0-4 Liquidity NameError | FIXED | `analytics.py:149,762,770` `asyncio.iscoroutine`, no `inspect` refs |
| P0-5 Empty-portfolio crash | FIXED | `analytics.py:166-176`, `or {}` at `:1932` |
| P0-6 Mock-200 envelopes | FIXED 2026-09-07 | EVT raises; forecast/summary/realized-risk/stress/risk-score/liquidity → nulls + `error` keys; frontend N/A + banners (issues 08, 10) |
| P0-7 US ticker forcing | FIXED | `data_service.py:40-65` passthrough |
| P0-8 Cache blind-insert | FIXED | `cache_service.py:74-90` delete-then-insert |
| P0-9 Screener wrong-results | FIXED | universe key `:194`, post-rank slice `:239`, `.BO` `:39-46`, D/E fail-closed `:234-238` |

## P1 — already fixed (13)

DB-gate lock (`data_service.py:81`), validate cascade (`:445-460`),
suffix check (`:58,103`), AV `.BO` mapping, coint sha1, cache upsert,
monte initial-value (`analytics.py:1736-1741`), num_paths clamp,
concentration live weights (`:703-707`), regime n≠3 guard + returns path,
EVT raise, HRP NaN guard.

## P1 — fixing now (issues 10, 11)

Issue 10 (mock-200 remainder, backend+frontend): realized-risk / stress /
risk-score / liquidity-fallback nulls + N/A rendering.
Issue 11 (quant math, snippets in BACKEND_REVIEW §5 F2–F8): Sortino
downside-deviation; EWMA single-pass RiskMetrics + flat term structure;
CVaR free `alpha`; OU oscillatory → `(None,None)`+flag; MC `steps=int()`
+ bootstrap seed `int()`; backtest one-way turnover + mean-based Sharpe
ddof=1; max_sharpe `raw.sum` guard + forwarded `beta`; vol-cone synthetic
bounds → null+flag; factor OLS active-history filter; risk_scoring
benchmark-threaded factor leg (no silent R²=0→30) + drop singleton
`_previous_risk_score` bleed; target_volatility scale-to-target with cash
remainder + methodology update.
Issue 12 (contracts): `ValidateTickerRequest` max_length 10→20 +
pattern; DB tickers `String(10)`→`String(20)`; stress honors
`request.tickers`; rebalance `price<=0`→400 + float qty; `PUT /config`
persists ttl/cache in `app_settings`; FX unknown-pair raises (no `1.0`).

## P1 — deferred with reason (triage labels per `docs/agents/triage-labels.md`)

- HMM research chain (non-overlapping features, expanding scaler, real
  sticky priors, multi-restart, filtered probs), ADF/Johansen lags,
  copula PIT-MLE, Fisher-z/leave-one-out, Amihud methodology, Piotroski/
  Graham/EV (bfinance-upstream, see `BFINANCE_RECOMMENDATIONS.md`):
  research-grade, needs design + data work beyond snippet fixes.
  Triage: `ready-for-human`.
- `add` global renorm: product decision (frontend auto-calcs; 400 would
  break single-add UX) — left as-is deliberately. Triage: `wontfix`.
- WS auth, Alembic migration path, DB Unique/Check constraints, health env:
  infra decisions for a multi-user/auth milestone, not this batch.
  Triage: `ready-for-human`.
- FX stale-`83.0`, N+1 selects, `utcnow` deprecation sweep, O-table perf:
  backlog, fully specified; none fabricate user-visible numbers today.
  Triage: `ready-for-agent` (unscheduled).
- t28 cron (deferred), t29/t31 (needs-info): tracker state unchanged.
