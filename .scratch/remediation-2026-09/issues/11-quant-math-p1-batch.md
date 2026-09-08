# 11 — Quant-math P1 batch (audit snippets F2–F8)

Status: ready-for-agent | Pri: P1 | Owner: builder-Q (backend only)

## Items (all in `backend/app/`, snippets in `BACKEND_REVIEW.md` §5 — read them)

1. Sortino → downside deviation `sqrt(mean(min(0,r-target)²))·sqrt252` (F3).
2. EWMA → single-pass RiskMetrics `σ²=λσ²+(1-λ)r²`, flat term structure (F4).
3. CVaR `alpha=cp.Variable(neg=True)` → free `cp.Variable()` (F2).
4. OU oscillatory branch `-2<γ≤-1` → `(None,None)` + flag, no `half_life=1.0` (§5 F8/line 317).
5. MC `steps=int(round(h*252))` + bootstrap seed `int(rng.integers(...))` (F8).
6. Backtest one-way turnover `0.5·Σ|Δw|` + multiplicative day-0 cost + mean-based Sharpe ddof=1 (F6).
7. max_sharpe `raw.sum()≤0` guard + forwarded `beta` param (default 0.95).
8. Vol-cone synthetic single-obs bounds → null + `insufficient_data` flag.
9. Factor OLS active-history index filter (F7; HAC only if trivially local).
10. risk_scoring: thread benchmark into factor leg (no silent R²=0→30) or exclude+renormalize; remove singleton `_previous_risk_score` bleed (read callers/tests, least-breakage honest fix).
11. target_volatility: scale-to-target with cash remainder + methodology string update (F5 first option).

## Rules

Each item gets a regression test proving the new behavior (hand-checks where
the audit gives them: Sortino, EWMA-vs-RiskMetrics, positive-loss VaR, OU
oscillatory, float horizon, turnover one-way, Sharpe mean-based). Update
pinned tests that assert old numbers. Full `pytest --no-cov -q` green + ruff
clean on touched files. No other files.
