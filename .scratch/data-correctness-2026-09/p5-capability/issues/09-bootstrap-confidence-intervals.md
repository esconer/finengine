# 09 — Bootstrap confidence intervals on published estimates

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: —
Repo: `backend/`
Effort: S/M | Score: 28

## What

The codebase already has the right instinct and implements it as a **refusal**:

> `confidence_interval_status` / `_reason`: *"The engine computed no sampling distribution for a
> conditional-volatility point estimate, and says so rather than inventing one"*

That is exactly correct behaviour, and it is the right **idiom**. This ticket keeps the refusal
where a valid interval cannot be computed, and implements an actual interval everywhere one can be.

Eligible: VaR, ES, volatility, HHI, TCTR, tracking error, `prob_success`, and the drawdown-path
measures from issue 05.

## Why

Point estimates without error bars are how a risk terminal becomes confidently wrong. The app
already refuses to invent intervals where it cannot compute them — extending that to compute them
properly where it can is a natural completion rather than a new idea.

`arch.bootstrap.StationaryBootstrap` is **already imported** by the Monte Carlo service, so the
machinery is present.

## The trap, stated explicitly

**Bootstrapping your own VaR resamples the same series that fitted the model.**

With EVT-POT fitting a GPD to the 5% tail, a 250-day window gives roughly **12 exceedances** — and
the GPD shape parameter ξ is genuinely unstable at that sample size. A bootstrap interval around
an unstable point estimate conveys false precision.

So the acceptance criteria must include the guard, not just the interval:

- **Publish the CI, the exceedance count, AND a minimum-tail-sample refusal.** All three.
- Refuse to fit POT below a minimum tail sample at all, and say why.
- The Monte Carlo service's tail-fitted-on-the-same-sample behaviour gets the same treatment.

## Change

- A shared bootstrap helper based on `arch.bootstrap.StationaryBootstrap`, applied to the eligible
  metrics.
- Reuse the existing `confidence_interval_status` + `confidence_interval_reason` fields. Do not
  invent a second convention — extend the one that is already correct.
- Statuses: `computed`, `refused_insufficient_sample`, `refused_unsupported_metric`,
  `refused_model_instability`.
- Widen the existing `confidence_interval` block on `forecast-risk`, which is the seam to extend.
- Record `n_bootstrap_samples` and the resampling method in the response.

## Proof of done

- [ ] Each eligible metric returns an interval with `n_bootstrap_samples` and the method.
- [ ] A metric with too few observations returns `refused_insufficient_sample` with a reason, and
      **no interval**. A test forces this.
- [ ] POT fitting is refused below the minimum tail sample, and the refusal states the exceedance
      count. A test constructs a short tail.
- [ ] The exceedance count is published alongside every tail-derived interval. A test asserts it
      is present.
- [ ] The existing `confidence_interval_status` vocabulary is used. A grep confirms no second
      convention was introduced.
- [ ] The Monte Carlo service's tail-model diagnostics receive the same minimum-sample guard.
- [ ] The frontend renders the interval and the refusal states distinctly.

## Notes

The refusal is the more valuable half of this ticket. An honest "I cannot put an error bar on this
number" is worth more than a confident wrong interval, and this codebase already knows that — it
just has not finished applying the principle.

Refs: `../spec.md`, `backend/app/services/monte_carlo_service.py`, `backend/app/services/tail_risk_service.py`
