# 20 — HMM convergence is never checked

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: 19
Repo: `backend/`
Severity: **MEDIUM**

## What

`regime_service.py:226-228`
```python
hmm.fit(x_scaled)
states = hmm.predict(x_scaled)
probas = hmm.predict_proba(x_scaled)
```

`hmm.monitor_.converged` is referenced **nowhere in the file** (verified by grep). It is readable
on the installed hmmlearn 0.3.3.

## Why

A `n_iter=200` exhaustion publishes **byte-identical metadata** to a converged fit:
`stability_pct`, `regime_probabilities`, and `transition_matrix` are all presented as fit output
with no indication that the optimiser gave up.

With `tol=1e-4` and only 2 standardized features, this is a live possibility rather than a
theoretical one. And it fails on exactly the inputs where the HMM is least trustworthy — flat or
volatile NIFTY windows, and short `lookback_days`.

## Change

- Check `hmm.monitor_.converged` after fitting.
- Publish a `converged: bool` field.
- When `converged` is `False`, suppress `regime_probabilities` (or the whole block) and set
  `data_status` accordingly, with a reason. The `confidence_interval_status` /
  `confidence_interval_reason` pattern from `forecast-risk` is the right precedent — reuse it.
- Consider whether a non-converged fit should return an error instead. A regime history built on a
  fit that did not converge is worse than no regime history.

## Proof of done

- [ ] `converged` is present in the response.
- [ ] A forced non-convergence (patch `monitor_.converged` to `False`, or use data that cannot
      converge) produces `converged: false` and a suppressed or flagged probability block. A test
      asserts this.
- [ ] `data_status` reflects non-convergence.
- [ ] The frontend renders the non-converged state distinctly. The regime page must not present a
      stability index from a fit that did not converge.
- [ ] The stability index itself is defined in terms of converged fits only, or its docstring says
      what it means when the fit did not converge.
- [ ] The `confidence_interval_status` + `_reason` idiom is reused rather than a new convention
      invented.

## Notes

Pair with issue 19. Together they answer a question the regime page currently cannot: **should I
trust this fit at all?** The page already publishes a stability index, which is the right instinct.
These two tickets complete it.

Refs: `../spec.md`, `backend/app/services/regime_service.py:226-228,236-248,252`
