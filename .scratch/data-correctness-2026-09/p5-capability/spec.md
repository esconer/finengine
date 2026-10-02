# Phase 5 — New capability

Status: ready-for-agent
Tickets: 21 | Effort range: S to L
Gate: **issue 12 (lot ledger) blocks 11, 13, and 16.**

## The structural gap this phase addresses

A product-gap review found the most important thing, and it is not a missing page:

**There is no book of record.** No `transactions` table, no lot ledger, no cash balance.

`PortfolioPosition` is one row per ticker with `quantity / buy_price / added_on`, and
`GET /api/v1/analytics/performance-history` reconstructs history as `quantity × past_price` masked
to the buy-implied start.

So every "realized" P&L figure, tear-sheet number, and attribution output is a **hypothetical
buy-and-hold of today's book**. Add a second lot or take a partial exit and the entire foundation
shifts.

The app is currently an excellent cross-sectional analytics layer bolted onto a static holdings
snapshot. Issue 12 is what turns it into an account.

## Priority order

### Do first — cheap, unblocked, high value

| # | Ticket | Score | Effort | Note |
|---|---|---|---|---|
| 01 | **VaR/ES backtesting** | 45 | S | Three VaR engines, **zero** validation. Best value-per-hour in the backlog |
| 02 | Ledoit-Wolf covariance shrinkage | 40 | S | MVO is harvesting sampling noise at n=10–25 |
| 03 | Tracking error, active risk, IR, capture ratios | 40 | S | The most-asked equity question. **Zero occurrences** in the codebase |
| 04 | Specific (idiosyncratic) risk decomposition | 35 | S | `σ × √(1−R²)`. β and R² already computed |
| 05 | Drawdown-path risk: CDaR, Ulcer, time-under-water | 35 | S | ~30 lines on a series you already build |
| 06 | Risk policy limits layer | 32 | S | 21 pages of metrics, **zero** stated policy |
| 07 | NSE sector index returns | 35 | S | Replaces the invented stress elasticities |
| 08 | Historical scenario replay | 28 | S/M | Parameter-free stress. Zero free parameters |
| 09 | Bootstrap confidence intervals | 28 | S/M | The codebase already has the right *idiom* — a refusal. Make it an interval |
| 10 | Cornish-Fisher modified VaR + spectral measures | 24 | S | ESMA PRIIPs prescribes CF for retail VaR |
| 19 | FX history | 30 | S | One live rate is applied to the whole history today |

### Blocked on the ledger

| # | Ticket | Score | Effort | Note |
|---|---|---|---|---|
| 12 | **Lot/transaction ledger** | **50** | **L** | The single highest-scoring item in the backlog |
| 13 | Tax-aware rebalancing (India) | 36 | M | Dominates the rebalance decision for an Indian book |
| 16 | Portfolio snapshot / as-of versioning | 28 | M | M→S if snapshotting current weights only |
| 11 | Pre-trade what-if incremental risk | 28 | M | The engine and the rebalancer exist; nothing joins them |

### Later

| # | Ticket | Score | Effort | Note |
|---|---|---|---|---|
| 14 | Brinson-Hood-Beebower attribution | 32 | S/M | Needs 07 + 27's constituent weights |
| 15 | Factor breadth: sector-relative + style | 32 | L | Time-series form, **not** a Barra clone |
| 17 | Liquidity-adjusted VaR | 24 | M | ADV/DTL exist but never join the risk number |
| 18 | Point-in-time fundamental snapshots | 24 | M | Kills look-ahead bias in backtests |
| 20 | MCTR, component VaR/ES, risk budgeting | 30 | S | The gradient a rebalancer actually needs |
| 21 | Regime-conditional forward risk forecast | 18 | M | **Gate on posterior probability** — see anti-pattern 4 |

## Dependency graph

```
Phase 3 issue 27 (rf rate + NIFTY TR) ─┐
Phase 1 issue 15 (macro series)        ─┼─→ 01 VaR backtest ─→ 03 TE/IR ─→ 14 Brinson
                                       │        │
                                       └─→ 02 Ledoit-Wolf     └─→ 04/05/20
Phase 1 issue 16 (costs) ─→ backtest, optimize, tear-sheet, MC

Phase 5 issue 12 (ledger) ─→ 13 (tax rebalance)
     │      ├────→ 16 (snapshots)
     │      └────→ 11 (pre-trade)
Phase 5 issue 07 (sector idx) ─→ 15 (factor breadth) ─→ 14 (Brinson)
Phase 5 issue 07 ─→ 08 (historical replay)  [replaces §9.13 elasticities]
```

## Sequencing

```
Week 1    01 VaR backtest  →  02 shrinkage  →  03 TE/IR
Week 2    04/05/20 risk decomposition  →  06 policy limits  →  07 sector indices
Week 3    08 historical replay  →  09 bootstrap CIs  →  10 CF VaR  →  19 FX history
Week 4+   12 ledger  (+ Phase 1 issue 05 corporate actions, Phase 2 issue 16 route)
          → 13 tax-aware rebalance  →  16 snapshots
Later     07 → 15 factor breadth → 14 Brinson
Later     11 pre-trade  ·  17 L-VaR  ·  18 PIT fundamentals  ·  21 regime-conditional
```

## Anti-patterns to avoid while implementing

These are not hypothetical. Each is a documented way this kind of product goes wrong.

1. **A single-portfolio factor model is fake precision.** Barra's specific-risk estimate comes from
   a daily cross-sectional regression across thousands of names. With 10–20 holdings there is no
   cross-section — "country factor" is degenerate (1 for everything), size and value have no
   cross-sectional variance, and 6 factors on 20 observations is unidentified. **Do** the
   time-series form (issue 15). Publish R² and observation counts alongside every loading — the
   codebase already does this well via `universe_coverage` and `data_status`.

2. **VaR backtesting on 250 observations has almost no power.** 99% VaR expects 2.5 exceedances in
   250 days. A worked example shows 3 exceedances in 120 days yields a Kupiec p-value of **0.166** —
   a test that passes almost anything. **Report the hit count and worst breach severity as the
   headline; the p-value is supporting evidence, not a verdict.** Never present "Kupiec p = 0.62,
   model validated" — that is a false all-clear.

3. **Deflated Sharpe discipline applies to your own backtester.** The `POST /analytics/backtest`
   endpoint sweeps strategies × windows. Bailey & López de Prado's Deflated Sharpe Ratio exists
   because the naive Sharpe "does not punish you for how many variants you tested". Their worked
   corpus: **50,000 trials, best in-sample Sharpe 2.00 — and the expected maximum of 50,000
   skill-less trials is 2.72.** On one portfolio you are nowhere near enough trials for this to
   bite, but the habit matters: when the sweep grows, publish the full grid, not the winner.

4. **HMM regimes must never gate capital allocation.** Three Gaussian states on `^NSEI` alone is
   low-identification. The regime page already publishes a stability index, which is the right
   instinct. For issue 21, gate on **state posterior probability** with a minimum-confidence
   threshold and render the uncertainty — never a clean state name. "The optimiser says hold 5%
   cash in Crisis state" turns a noisy label into a capital decision.

5. **`CONTEXT.md` §9.13's sector elasticities are a fabricated beta presented as a risk output.**
   Hardcoded, unsourced, unbounded — and the comment itself admits the problem ("artificial −98%
   bankruptcy wipeout artifacts"). Issues 07 and 08 replace them with estimated betas and
   parameter-free replay. If any elasticity is kept, label it `assumed_not_estimated` — the
   codebase already has that vocabulary.

6. **Never ship optimiser output without a stability disclosure.** Recompute at ±1 window shift and
   ±20% μ perturbation and show how much the answer moves. A worked example: same universe, same μ,
   same objective — sample covariance gave 34% max drawdown, Ledoit-Wolf shrinkage gave 26%. That
   8pp is larger than most rebalancing decisions anyone will make off this app. **If the
   recommended weights swing 15pp under a 3-month window shift, say so loudly.**

7. **Bootstrapping your own VaR invites the tail-fitted-on-the-same-sample trap.** With EVT-POT
   fitting a GPD to the 5% tail, a 250-day window is ~12 exceedances, and the GPD shape parameter ξ
   is genuinely unstable there. Publish the CI **and** the exceedance count **and** refuse to fit
   POT below a minimum tail sample. `confidence_interval_status` + `confidence_interval_reason` is
   the existing idiom — extend it, do not invent a second one.

8. **Don't let metric count become the product.** The value proposition is "not on free sites", not
   "more numbers than Screener.in". 21 pages already; a visitor landing on `/dashboard` sees a
   metric wall with no entry point. The top three items (01, 06, 12) all **reduce** interpretive
   burden rather than add to it. Prefer those to any new card.

9. **Single-user means "audit trail", not "workflow engine".** GIPS traceability and eFront
   reporting are about many people acting on a shared record. You are the only actor. Issue 16 is
   justified because it lets you compare your own risk over time — build it as a time series you
   can chart, not a versioned store with approvals.

## Verification

- Every new metric ships with a formula reference (textbook or regulatory), its units, and its
  minimum-sample requirement.
- Every new metric returns `None` plus a reason when unmeasurable. The `data_status` /
  `universe_coverage` / `confidence_interval_status` conventions already in the codebase are the
  standard.
- VaR/ES backtesting results are validated against a closed-form reference (the tests are
  analytical, not snapshot-based).
- Optimizer changes ship with a stability disclosure per anti-pattern 6.
