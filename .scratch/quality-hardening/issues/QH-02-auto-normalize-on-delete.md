# QH-02 — Auto-normalize portfolio weights on position delete

Status: closed
Type: task
Blocked by: —

## What

`DELETE /portfolio/{ticker}` removes a position but does NOT re-normalize remaining weights.
After deleting one of three equal-weight positions, the remaining two still show `weight=0.333`
each (total 0.666), silently corrupting every downstream analytics computation that assumes
weights sum to 1.0 (concentration, risk contribution, optimization, volatility sizing).

## Fix

After successful delete, proportionally re-normalize remaining position weights to sum to 1.0,
using the same logic as `POST /portfolio/normalize`.

## Open question

Should this auto-normalize silently, or return a response indicating weights were adjusted?
Suggest: auto-normalize + include `weights_renormalized: true` in the response body.

## Why

Weight corruption propagates silently to 9+ analytics endpoints. Users won't know their
risk numbers are wrong until they manually trigger rebalance.

## Proof of done
- [ ] Delete position → remaining weights sum to 1.0
- [ ] Response includes indicator that normalization occurred
- [ ] Regression test: delete from 3-position portfolio, assert remaining weights sum to 1.0
