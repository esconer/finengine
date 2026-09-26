# Fix wave 2: close the open defects

Follows `open-defects.md` and the audit CLI (`app.debugging.context_audit`),
which reports 41 pass / 6 fail against the current export. The 6 failures are
this wave's acceptance criteria: **all six must go green, and no new rule may
break.**

Every defect here was found by a machine check, not by reading code, so every
fix must be verifiable by re-running the checker. A fix that makes a rule green
by deleting the field the rule reads is a regression, not a fix.

## Ownership split

`backend/app/api/analytics.py` is a ~5000-line monolith and six of the eight
defects live in it. It is split by SYMBOL, and the two owners are told exactly
which functions they may touch.

| Owner | File | Defects | Symbols owned |
|---|---|---|---|
| A | `services/analytics_engine.py`, `models/schemas.py` | D-04, D-07 | `risk_scoring`; `CointScannerResponse` |
| B | `api/analytics.py` | D-01, D-02, D-06, D-08 | `get_realized_risk`, `_build_wide_returns`, `get_risk_score` |
| C | `api/analytics.py` | D-03, D-05 | `get_liquidity_metrics`, `get_performance_history` |

B and C edit the same file in disjoint functions. **Re-read immediately before
editing** — line numbers drift while the other owner works. No `git stash`, no
`git checkout`, no whole-file rewrites: a previous agent's stash cycle briefly
deleted another agent's hunk from this exact file.

## Defects

### D-01 — `realized_risk` publishes no `covered_days_scope`
Catches: `XS-002`

`realized_risk` is the section the other four holding-window sections are
defined against, and it is the only one that does not declare what unit its
`covered_days` is in. Counts are already correct (39, start 2026-08-03); this is
the label. Owner B.

### D-02 — per-ticker counts in mixed units
Catches: `XS-005`

NIFTYIETF: `raw_days=108, masked_days=23, return_observations=20` — the last two
do not reconcile. `masked_days` is a price-row count in `regime`/`tear_sheet` and
a return-row count in `risk_contribution`. The block-level count was unified;
the per-ticker level was not. This is the root of the one genuinely-red product
test (`test_realized_risk_case_a_intersection_copy`, 25 vs 24). Owner B.

### D-03 — liquidity headline over estimated inputs
Catches: `NUM-006`

`overall_score: 8.0`, `data_status: available`, **0 warnings**, while 5 of 14
market caps are non-measured (4 implied from turnover, SELECTIPO on the ₹1 bn
floor), with no count anywhere. A fallback-derived score presented as a clean
measurement — the same fabrication class as the original SELECTIPO finding, one
level up. Owner C.

### D-04 — `risk_score.components.correlation` is a hard zero
Catches: `NUM-018`

`correlation: 0` with `excluded_components: []` is indistinguishable from "not
computed", and drags `overall_score` (12.7, LOW) downward. `risk_studio` measures
0.1404 independently. Owner A (engine); B wires the route side.

### D-05 — performance benchmark series wrong at both ends
Catches: `NUM-019`

Row 0 `benchmark_value` is bit-identical to its own `portfolio_value`; row 0
publishes a `return` derived from a value never delivered; the newest row has no
benchmark at all. A chart starts the benchmark exactly on the portfolio and ends
a day short. Owner C.

### D-06 — two R², one window undeclared
Catches: `XS-009`

`factor_exposure.r_squared = 0.6511` (174 obs) vs `risk_score.factor_r_squared =
0.2391` (39 obs), and `risk_score` publishes no window or count while driving a
user-facing "High unexplained risk" alert. Owner B.

### D-07 — pairs `currency` / `warnings` stripped from HTTP
No rule — structurally invisible in a JSON artifact.

The route returns a local `extra="allow"` subclass so the in-process exporter sees
the new fields, but the decorator's `response_model=CointScannerResponse` makes
FastAPI re-serialize against the base model and drop them. One line in
`schemas.py`. Owner A.

### D-08 — zero-weight `added_on` can drive the holding-window mask
No rule — publishes nothing.

`_build_wide_returns` filters holdings to active tickers for price data but not
for the mask cutoff, so a persisted zero-value row can set the window start and
mask a book to a window it has no data for. Unchanged behaviour, recorded
because it is a latent way for the holding window to be wrong. Owner B.

## Acceptance

1. `uv run python -m app.debugging.context_audit check --export <fresh>` reports
   **47/47 pass, 0 findings, exit 0**.
2. `tests/test_debug_context_audit.py` still passes — a fix must not delete a
   field a rule reads.
3. `test_realized_risk_case_a_intersection_copy` goes green (it is a real
   product defect, not a baseline failure).
4. Full backend suite: no new failures beyond the five remaining pre-existing
   ones. `ruff check app tests` clean. Frontend untouched and green.
5. The `catches D-0x` labels in the rule table are removed for the rules that
   now pass, so the tool stops advertising a defect that no longer exists.

## Non-goals

- The 30-day annualization gate stays. It is a policy decision, not a defect.
- No bfinance changes. If any fix appears to need one, stop and report.
- No new third-party dependencies.
