# 05 — Drawdown-path risk measures

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: —
Repo: `backend/`
Effort: S | Score: 35

## What

For a single long-only book, the **path** is the experience. None of these exist.

| Measure | Definition |
|---|---|
| **CDaR** (Conditional Drawdown at Risk) | CVaR of the drawdown series — the average drawdown *conditional on being in the worst 5%* |
| **EDaR** (Expected Drawdown at Risk) | Mean of the drawdown series, in the loss domain |
| **Ulcer Index** | `sqrt(mean(drawdown_pct²))` — depth-squared, so prolonged shallow pain counts |
| **Time under water** | Fraction of days below a prior peak |
| **Longest drawdown** | Max consecutive days below a prior peak |
| **Recovery-time distribution** | The distribution of time-to-recovery, not just the mean |
| **Drawdown at Risk** | A quantile of the drawdown distribution at a chosen confidence |

All are ~30 lines on a series the app already builds (the tear sheet already computes the
underwater curve at `:342-343` and the monthly heatmap).

## Why

MDD, which the app has, is a single worst-case number. It tells you nothing about the *shape* of
the pain: a 20% drawdown recovered in a week and a 20% drawdown that took two years are the same
MDD and completely different experiences.

For a personal book, **the duration and shape of the pain is what determines whether you stick to
the plan.** Time under water and recovery-time distribution are the most actionable of this set,
because they are what a user actually lives through.

## Change

- Compute on the portfolio return series, alongside the existing MDD.
- Report CDaR at the same confidence levels as the existing VaR/ES, for comparability.
- Report the **recovery-time distribution** (median, 75th, 90th, and the current episode) rather
  than just its mean.
- Where a drawdown has not yet recovered, the current episode's age and depth are reported
  explicitly. An open drawdown is a censored observation, not a completed one.

## Proof of done

- [ ] Each measure is validated against a **closed-form reference** on a constructed series.
- [ ] CDaR is consistent with CDaR ≤ MDD, and EDaR ≤ CDaR. A test asserts the ordering.
- [ ] Ulcer Index is `0.0` only for a series with no drawdown. A test asserts a small positive
      value for a real drawdown.
- [ ] An **open** drawdown is reported as censored — current age and depth, with the recovery
      estimate marked as not-yet-observed. A test forces an unrecovered drawdown.
- [ ] Recovery-time distribution returns `None` with a reason when no drawdown has recovered.
- [ ] The existing MDD is unchanged, and the new measures are consistent with it.
- [ ] The frontend renders the measures and the recovery-time distribution, with `N/A` states.

## Notes

Riskfolio-Lib offers all of these not just as reports but as **optimisation objectives**
(`upperCDaR`, `upperuci`), and skfolio carries the same set. If issue 02 or a later optimiser
iteration wants a drawdown-aware objective, this is the metric family to plug in.

The existing `drawdown_at_risk` / `conditional_drawdown_at_risk` naming from Riskfolio is a good
convention to follow so the concepts are recognisable.

Refs: `../spec.md`, `backend/app/api/analytics.py:342-343,5485-5497,5511-5520,5647-5678`
