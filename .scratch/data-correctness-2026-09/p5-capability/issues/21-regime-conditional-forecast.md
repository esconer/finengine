# 21 — Regime-conditional forward risk forecast

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: 20
Repo: `backend/`
Effort: M | Score: 18 — deliberately last

## What

The regime page gives 120 days of history and per-state behaviour. Add the **forward** view:

- The forward transition matrix, giving `P(state_t+1 | state_t)`.
- **Per-regime** VaR and ES, blended into a conditional forecast:
  `VaR_conditional = Σ_s P(state_t+1 = s | state_t) · VaR_s`
- "What should my target weight be in each regime?"

## Why

The regime engine is currently descriptive — it tells you what happened. This makes it forward
looking, which is the point of detecting regimes at all.

**But this is score 18 out of ~50 for a reason, and the reason is in the next section. Read it
before building anything.**

## The constraint: this must never gate capital allocation

Three Gaussian states fitted on `^NSEI` log-returns + 21-day realised vol over a few years of a
single index is a **low-identification problem**. The regime page already publishes a stability
index, which is the right instinct. Add Phase 3 issues 19 and 20's convergence and
label-stability guards before trusting any of this.

The dangerous outcome is a sentence like *"the optimiser says hold 5% cash in Crisis state"*. That
converts a noisy label into a capital decision, and a user who follows it once will blame the app.

## Required safeguards

- **Gate on posterior probability with a minimum-confidence threshold.** If the most likely next
  state has a posterior below the threshold, publish **no** conditional forecast — publish the
  uncertainty instead.
- **Render the uncertainty, not a clean state name.** "Crisis (62% posterior)" is honest.
  "Crisis" is not.
- **Publish the transition matrix** so the user can see the model's own uncertainty about its
  forecast.
- **Never let this feed the optimiser automatically.** It may inform a human; it must not silently
  change a weight.
- Apply the `converged: false` guard from Phase 3 issue 20. A conditional forecast from a
  non-converged fit is meaningless.

## Change

- Forward transition probabilities from the fitted HMM.
- Per-regime risk measures, computed on the historical data of each regime — which is thin, so
  each must carry its own observation count and a `None` state when underpowered. **A regime with 15
  observations cannot support a 99% ES**, and saying so is the whole point.
- The blended conditional forecast, with the confidence gate.
- Display-only target weights per regime, clearly marked as illustrative.

## Proof of done

- [ ] The transition matrix is published and is **row-stochastic**. A test asserts row sums to 1.
- [ ] The conditional forecast is `None` when the posterior is below the confidence threshold. **A
      test forces this** — it is the most important criterion on this ticket.
- [ ] A regime with insufficient observations yields `None` with a reason, not a fitted number. A
      test constructs an underpowered regime.
- [ ] A non-converged HMM (Phase 3 issue 20) yields no conditional forecast.
- [ ] The posterior probability is displayed alongside the state name. A test asserts the
      rendering.
- [ ] Conditional VaR is `None`, not silently skipped, when any contributing regime is unpowered.
- [ ] The optimiser is **structurally unable** to consume the regime forecast without an explicit
      opt-in. A test asserts the default path ignores it.
- [ ] The UI states that this is a low-identification model and should not drive allocation.

## Notes

This is last in the phase for a reason. Issues 01, 02, 03, 06, and 12 are each worth more and carry
no such risk of being wrong in a way that damages a capital decision.

If you build only one part of this, build the **per-regime risk measures with honest `None`
states** — that is genuinely informative. Skip the target-weight suggestion entirely; the app
already has a rebalancer, and telling it what to do based on a 3-state label fit to one index is a
worse version of what issue 20's MCTR already gives you.

Refs: `../spec.md`, Phase 3 issues 19, 20, Phase 5 issues 06, 20
