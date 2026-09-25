# 01: Normalize the AI export contract

**What to build:** Make shared coverage, status, freshness, currency, ordering, and error metadata truthful across every exported section, so consumers can distinguish complete coverage, partial measurement, unavailable data, and calculation-only assumptions without guessing.

**Blocked by:** None (can start immediately)

**Status:** claimed

- [ ] `weight_basis` is emitted only when an active leg was actually dropped and weights were renormalized; weightless analyses do not claim an allocation basis.
- [ ] Public `data_status` values are normalized to the documented vocabulary and coverage status remains separately available.
- [ ] Successful sections omit inapplicable error fields rather than publishing misleading null-error sentinels.
- [ ] Ticker ordering is deterministic and repeated universes preserve a stable request order.
- [ ] Currency and freshness inference has explicit, tested fallback rules.
- [ ] Regression tests and public AI-context documentation cover the normalized contract.
