# Portfolio AI Context v3 Remediation

## Goal

Turn the v3 portfolio AI-context export into a self-consistent, authoritative JSON/Markdown contract after the completed v3 audit.

## Source of truth

- Portfolio and analytics responses remain canonical API results.
- Dashboard composition reuses those canonical section results.
- Requested, available, measured, and calculated values remain explicitly distinguishable.
- No unavailable value is replaced with a plausible zero, score, date, or assumption.

## Shared vocabularies

- Section `status`: `available`, `partial`, `unavailable`.
- Public `data_status`: `available`, `partial`, `unavailable`.
- Coverage `status`: `complete`, `partial`, `unavailable`, `unknown`.
- Input provenance: `measured`, `derived`, `estimated`, `fallback`, `unavailable`.
- The export is a breaking contract revision and moves to `schema_version: 2.0`; `not_requested` is removed from documentation/types because unselected sections are omitted rather than serialized.

## Required outcomes

- Coverage metadata describes only the universe relevant to the section.
- `weight_basis` appears only when active weights were actually dropped and renormalized.
- Requested and delivered time windows, observation counts, freshness, and calculation basis are explicit.
- Position-level and portfolio-level annualization gates use their own measured samples.
- Full-history hypothetical calculations do not masquerade as holding-window calculations.
- Volatility-sizing output is safe to interpret and, when presented as executable, is executable.
- Dashboard values link to sibling canonical components instead of unexplained nulls or placeholders.
- India composite coverage represents heterogeneous flow, delivery, and liquidity components honestly.
- The exported status and currency vocabularies are stable and documented.
- Every partial/unavailable section or dashboard component carries a machine-readable reason; successful sections omit inapplicable error fields.
- Two exports of the same unchanged book are deterministic except allow-listed run metadata (`export_id`, `generated_at`, `completed_at`, `snapshot_consistency`).

## bfinance boundary

This remediation does **not** modify the bfinance source project. No current v3 finding requires a bfinance change. If a future dependency investigation identifies a necessary bfinance modification, create a separate source-specific proposal, document evidence/design/compatibility/tests, and request explicit user approval before editing bfinance.

## Delivery strategy

1. Normalize shared export contracts.
2. Fix independent engine semantics in parallel where file ownership is separate.
3. Integrate endpoint and frontend behavior after shared contracts stabilize.
4. Generate a new v4 export and repeat the full invariant audit.

## Verification

- Focused backend regression tests for every ticket.
- Frontend tests and production build for UI-facing changes.
- Ruff on changed backend Python.
- Full backend suite, with pre-existing unrelated failures reported separately.
- Fresh v4 JSON audit covering all 17 sections, arithmetic, coverage, statuses, timestamps, currencies, calculation universes, and cross-section consistency.
