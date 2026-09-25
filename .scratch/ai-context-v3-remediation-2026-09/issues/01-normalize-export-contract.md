# 01: Normalize the AI export contract

**What to build:** Make shared coverage, status, freshness, currency, ordering, and error metadata truthful across every exported section, so consumers can distinguish complete coverage, partial measurement, unavailable data, and calculation-only assumptions without guessing.

**Blocked by:** None (can start immediately)

**Closes:** V3-01, V3-16, shared contract portion of V3-17

**Evidence:** 47/49 blanket `weight_basis` claims; `data_status=complete` leakage; unconditional `error:null`; unstable derived ticker order; missing currency/as-of fallbacks.

**Work area:** Shared AI envelope/coverage/status helpers, shared universe-coverage helper, API serialization boundary, AI-context documentation/types, and dedicated contract tests. Other tickets consume these helpers rather than redefining them.

**bfinance gate:** No bfinance edits. A bfinance limitation must be labelled `estimated`, `fallback`, or `unavailable`; if a source change is genuinely required, stop and write a source-specific proposal for explicit user approval.

**Status:** claimed

## Comments

### Contract wave landed and verified (integrator)

Backend contract helpers are in place and verified: `data_status` normalized to
`available|partial|unavailable` with coverage status kept separate, conditional
`weight_basis` (all five blanket claims removed), deterministic request-order
ticker lists, `as_of` resolved as the oldest component observation date, currency
conflict detection, and `error` dropped at the API boundary by a serializer
subclass on `AIContextSectionExport`.

**Integrator fixes applied on review:**

1. `_ticker_sequence` used `value or ()`, which raises on a pandas `Index`
   (`test_coverage_direct_unit_routes` 500'd). Now short-circuits on `None`.
2. `not_requested` was documented and typed but never emitted. Removed from
   `AIContextSection.status`, the Pydantic schema, the service vocabulary
   constant, the TS union, the AI-context page badge maps, and the docs. An
   unrequested section is absent, not serialized as a placeholder row.

**Verification:** 32/32 export-contract + AI-context tests, 170-test focused
regression set green (1 known pre-existing baseline failure), frontend 203/203,
`tsc` exit 0, `ruff check app tests` clean.

**Still outstanding for this ticket:**

- Bump `SCHEMA_VERSION` to `2.0` (breaking contract revision) and update the
  docs/`schema_version` references. Deferred to avoid a mid-wave edit of a file
  the contract agent still owned.
- Ticket 02 must add explicit `as_of_semantics` to the section model once the
  dashboard/India components publish one.

- [ ] `weight_basis` is emitted only when an active leg was actually dropped and weights were renormalized; weightless analyses do not claim an allocation basis.
- [ ] Public `data_status` values are normalized to `available|partial|unavailable`; coverage keeps `complete|partial|unavailable|unknown`; coverage values never leak into `data_status`.
- [ ] `not_requested` is removed from the documented/type vocabulary because unselected sections are omitted rather than serialized.
- [ ] The breaking contract revision moves `schema_version` to `2.0`, with documentation and frontend types updated together.
- [ ] Successful sections omit inapplicable error fields; every partial/unavailable section or dashboard component carries a machine-readable reason.
- [ ] Requested ticker order is never reordered; derived available/covered lists are deterministic and two different request orders cannot contaminate ordered response caches.
- [ ] Shared input provenance is one documented vocabulary: `measured|derived|estimated|fallback|unavailable`.
- [ ] Currency and freshness inference has explicit, tested fallback rules; market-wide/weightless analyses do not inherit portfolio weight semantics.
- [ ] Regression tests and public AI-context documentation cover the normalized contract.
