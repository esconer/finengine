# 02 — Ledoit-Wolf covariance shrinkage

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: —
Repo: `backend/`
Effort: S | Score: 40

## What

`MinVol`, `MaxSharpe`, and `MinCVaR` all use the **raw sample covariance** matrix. Add shrinkage.

```python
from sklearn.covariance import LedoitWolf
shrunk = LedoitWolf(assume_centered=False).fit(returns).covariance_
```

`sklearn>=1.7.2` is already a dependency.

## Why

With 10–25 names, minimum-variance optimisation **demonstrably harvests sampling noise**. The
sample covariance matrix of 20 assets estimated from ~500 daily observations has substantial
estimation error, and the optimiser finds the weights that exploit it. The result is a portfolio
that looks optimal in-sample and underperforms out-of-sample.

A documented worked example: same universe, same μ, same MVO objective — sample covariance gave
**34% max drawdown**, Ledoit-Wolf shrinkage gave **26%**. That 8pp gap is larger than most
rebalancing decisions anyone will make off this app.

**HRP already sidesteps this** — that is one of its main advantages, and it is why HRP exists. The
other three strategies do not.

## Change

- Add shrinkage to the covariance estimate used by `min_vol`, `max_sharpe`, and `min_cvar`.
- Expose the shrinkage target and the estimated shrinkage intensity in the response, so the user
  can see how much was shrunk.
- Per PyPortfolioOpt's documented sensible defaults, support
  `shrinkage_target ∈ {identity, constant_variance, single_index}`.
- Per the same source, `mean_historical_return` + `ledoit_wolf(single_index)` is the recommended
  default pairing.
- **Do not apply it to HRP** — HRP is built on a correlation-distance clustering and does not use a
  covariance matrix in the MVO sense.

Reference: Ledoit & Wolf (2004), *"Honey, I Shrank the Sample Covariance Matrix"*.

## Proof of done

- [ ] The shrunk covariance is used by all three affected strategies. A test asserts the weights
      differ from the unshrunk result on a seeded input.
- [ ] The shrinkage intensity is reported in the response.
- [ ] All three targets are supported and unit-tested.
- [ ] The identity target reproduces the **sample** covariance exactly — a test asserting equality.
      This is the control case.
- [ ] A drawdown comparison on a realistic input shows the expected improvement direction. Record
      the numbers in `## Comments`; they are the justification.
- [ ] HRP output is unchanged. A test asserts this.
- [ ] Per anti-pattern 6 in the phase spec, optimizer output ships with a stability disclosure.
      Verify the disclosure is still accurate with shrinkage in place.
- [ ] The response states which estimator was used, in the existing `provenance` style.

## Notes

Cheap: `sklearn.covariance.LedoitWolf` is one call, or ~5 lines of Ledoit-Wolf by hand.

Pair with issue 03. Shrinkage without tracking error is odd — you would have a de-noised optimiser
whose output you still cannot evaluate against a benchmark. Together they answer "is this better
than the index?", which is the question a user actually has.

Refs: `../spec.md`, `backend/app/services/optimization_service.py`
