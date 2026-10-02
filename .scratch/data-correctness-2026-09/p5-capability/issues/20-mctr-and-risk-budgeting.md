# 20 — MCTR, component VaR/ES, and risk budgeting by sector

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: 18
Repo: `backend/`
Effort: S | Score: 30

## What

Euler TCTR exists. Add the rest of the marginal-contribution family.

| Measure | Definition | Use |
|---|---|---|
| **MCTR** | `∂σ/∂w_i` — marginal contribution to risk | **The gradient a rebalancer needs.** A position with high MCTR is the cheapest place to reduce risk |
| **TCTR** | `w_i · MCTR_i` — exists already | Component contribution |
| **Component VaR** | `w_i · VaR_i` | Per-position VaR attribution |
| **Component ES** | ES contribution per position | Per-position tail attribution — exists at `analytics.py:6075`, with the normalisation bug from Phase 3 issue 18 |
| **Risk parity** | `RC_i = b_i · R(x)`, `Σb_i = 1` | Equal risk budgets per position or sector |

## Why

MCTR is the single most useful missing number.

TCTR says *"this position contributes 19.9% of your risk"*. MCTR says *"reducing this position by
1% reduces your portfolio vol by 0.14%"*. The first is a fact; the second is an **actionable
gradient**.

That distinction is what separates a diagnostic from an adviser. Maillard, Roncalli, and Teiletche
(JPM 2010) showed that **all TCTRs are equal at the ERC portfolio** and that it is MSR-optimal under
constant correlation — so TCTR identifies the *current* state, while MCTR identifies the *direction
of improvement*.

The existing risk-contribution page already does TCTR for volatility and CVaR. This is the natural
completion, and it feeds the rebalancer directly.

## Change

- MCTR per position, for volatility and for ES.
- **Component VaR** per position, reconciled against total VaR.
- Risk budgeting: allocate a total risk budget across positions or sectors, with per-unit risk
  budgets `b_i`.
- An **equal-risk-contribution** target portfolio, which is the continuous optimum of the risk
  budgeting problem (Amundi's "Constrained Risk Budgeting Portfolios" is the reference).
- Feed MCTR into the rebalancer (issues 11 and 13) as the objective's sensitivity term.
- Reuse the existing sector rollup pattern.

## Proof of done

- [ ] MCTR is validated against a **finite-difference** reference: perturb `w_i` numerically and
      compare. A test asserts agreement — this is the right way to verify a derivative.
- [ ] `TCTR_i = w_i · MCTR_i` holds for every position. **This is the identity test.**
- [ ] Component VaR sums to total VaR within tolerance. A test asserts the reconciliation.
- [ ] At the ERC portfolio, all TCTRs are approximately equal. A test constructs the ERC portfolio
      and asserts it — this is Maillard et al.'s result and a strong correctness check.
- [ ] The ERC portfolio is verified to be MSR-optimal under constant correlation, or the response
      states the condition under which it holds.
- [ ] Sector risk budgets sum to 1 and reconcile with the sector rollup.
- [ ] `None` with a reason for positions where MCTR is undefined (e.g. zero weight).
- [ ] Phase 3 issue 18's signed-normalisation fix is respected, so a genuine hedge does not break
      the sum-to-1 identity.

## Notes

Fix Phase 3 issue 18 **first**. The CVaR contribution normalisation bug directly affects this
ticket's component-ES work, and building risk budgeting on a component measure that does not sum to
1 would compound the error.

The ERC result is worth surfacing to the user explicitly: it explains *why* the optimiser's answer
looks the way it does, which is more useful than the number itself.

Refs: `../spec.md`, Phase 3 issue 18, Phase 5 issues 11, 13
