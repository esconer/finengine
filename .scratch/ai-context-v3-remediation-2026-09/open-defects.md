# Open defects after the v4 remediation

Recorded 2026-09-26, after the v4 export passed 127/127 invariants. These are
the things a fresh audit found that the remediation did **not** close, plus the
suite failures that were already red at `HEAD` and remain so.

Each entry states what is observed, why it matters, and what closing it would
take. Verified against the fresh export (`export_id portfolio-01aa73807a73`),
not from memory.

---

## 1. Real defects still in the export

### D-01 `realized_risk` is missing its `covered_days_scope` label

**Severity:** high (documentation integrity; the numbers are correct)

`factor_exposure`, `risk_contribution`, `tear_sheet` and `regime` all publish
`covered_days_scope: "holding_window_aligned_return_rows"`. `realized_risk` —
the section the other four are defined against — publishes an empty string.

```
realized_risk      covered_days=39   scope=''                              start=2026-08-03
factor_exposure    covered_days=39   scope='holding_window_aligned_return_rows'
risk_contribution  covered_days=39   scope='holding_window_aligned_return_rows'
tear_sheet         covered_days=39   scope='holding_window_aligned_return_rows'
regime             covered_days=39   scope='holding_window_aligned_return_rows'
```

The counts and start dates agree, so no number is wrong. But the reference
section is the one a consumer reads first, and it is the only one that does not
say what unit its count is in. The remediation report claimed all sections
agreed under one label; they do not.

**Close by:** threading the scope label into the `realized_risk`
`holding_coverage` call, and asserting the label is non-empty in the checker.

### D-02 Per-ticker counts are still in mixed units

**Severity:** high (this is the root of the one pre-existing red test)

`NIFTYIETF.NS` in `realized_risk.data.history_coverage.tickers`:

```
raw_days=108   masked_days=23   return_observations=20
```

23 and 20 do not reconcile, and neither is derivable from 108 without knowing
which unit each field uses. `regime` and `tear_sheet` still publish `masked_days`
as a **price-row** count while `risk_contribution` publishes it as a
**return-row** count. The block-level count was unified; the per-ticker level
was not.

**Close by:** one per-ticker counting rule, and a per-section
`per_ticker_count_units` declaration. `_build_wide_returns` is the shared
consumer and currently is not labelled.

### D-03 Liquidity publishes a clean score over estimated inputs

**Severity:** high (a fallback value presented as measured)

```
liquidity: overall_score=8.0  data_status=available  warnings=0
non-measured market caps: 5/14
  NIFTYIETF.NS, MIDCAPIETF.NS, JUNIORBEES.NS, MAFANG.NS  (estimated, implied from turnover)
  SELECTIPO.NS                                               (fallback, fixed INR 1bn floor)
no estimate_count or estimated_market_cap_count field anywhere
```

Per-position `market_cap_provenance` and `is_estimate` are correct. The section
headline aggregates none of them: a score derived partly from a hard-coded floor
is reported as `available` with no warning and no count. This is the same
fabrication class as the original `SELECTIPO` finding, one level up.

**Close by:** publish `estimated_market_cap_count` and demote the section to
`partial` (or at minimum warn) when any leg is not `measured`.

### D-04 `risk_score.components.correlation` is a hard zero

**Severity:** high (an unmeasured sub-score indistinguishable from a real zero)

```
risk_score.components = {"concentration":8.6,"volatility":9.8,"correlation":0,
                         "factor_risk":30,"market_risk":9.8}
risk_score.excluded_components = []
```

`correlation: 0` is indistinguishable from "not computed", and it drags
`overall_score` (12.7, `LOW`) downward. `risk_studio` independently measures
`current_avg_correlation = 0.1404` over a 756-day lookback. No sub-score formula
is published for any of the five components, so the weighting is unverifiable.

**Close by:** `null` plus a `sub_score_status`, or compute it. Publishing the
weighting would also make the total auditable.

### D-05 Performance history benchmark series is wrong at both ends

**Severity:** high (a chart draws a wrong line)

```
row 0   portfolio_value=42981.74  benchmark_value=42981.74   <-- bit-identical warm-up copy
row 0   return=-0.000117                                    <-- derived from a value never delivered
last    date=2026-09-22  benchmark_value ABSENT             <-- 19 of 20 rows have one
```

Row 0 copies the portfolio value into the benchmark slot, so any chart starts
the benchmark exactly on the portfolio. Row 0 also publishes a return computed
against an undelivered prior value. The newest observation — the one a reader
cares about most — has no benchmark point at all.

**Close by:** drop or flag the warm-up row, suppress the first return, and
guarantee a benchmark value on every delivered row.

### D-06 Two R² for one factor model, neither window declared

**Severity:** medium (contradictory model diagnostics)

```
factor_exposure.r_squared      = 0.6511   (174 observations, full exchange history)
risk_score.factor_r_squared    = 0.2391   (39 observations, holding window)
risk_score window/observation fields: none
```

Both are internally consistent, but `risk_score` drives a user-facing alert
("High unexplained risk (low R-squared: 0.24)") from a 39-day factor fit
without saying so. A reader comparing the two R² has no way to know they are
different models.

**Close by:** publish the factor leg's window and observation count in
`risk_score`, as `factor_exposure` already does.

### D-07 Pairs `currency` / `warnings` are stripped from the HTTP wire

**Severity:** medium (the AI path is fixed, the API path is not)

The pairs route returns a local `extra="allow"` subclass so the in-process
exporter sees `currency`, `warnings`, `universe_scope` and the depth block. The
route decorator still declares `response_model=CointScannerResponse`, so FastAPI
re-serializes against the base model and drops them. A direct HTTP consumer
sees the unaudited shape.

**Close by:** promoting the four fields to `Optional[...]` on
`CointScannerResponse` in `app/models/schemas.py`. One line; deliberately not
done unilaterally because `schemas.py` is foundation-owned contract code.

### D-08 A zero-weight position's `added_on` can drive the holding-window mask

**Severity:** medium (can mask a book to a window with no data)

`_build_wide_returns` filters holdings to the leg's active tickers for price
data but not for the mask cutoff, so a persisted zero-value row can set the
window start. Behaviour is unchanged from before this work; it is recorded
because it is a latent way for the holding window to be wrong.

**Close by:** filtering `active_from` to `active_tickers` in the same call.

---

## 2. Suite failures that were already red at `HEAD`

| Test | Cause | Status |
|---|---|---|
| `test_realized_risk_case_a_intersection_copy` | 25 price rows vs 24 return observations | **Real unit bug** — this is D-02, still open |
| `test_rebalance_rejects_zero_portfolio_value` | "Missing price" raise precedes the market-value check | error-wording only |
| `test_full_profile_runtime_error_maps_to_503` | 503 wording mismatch | error-wording only |
| `test_summary_passes_benchmark_to_risk_scoring` | order-dependent, passes alone | test isolation |
| `test_config_get_propagates_errors` | order-dependent, passes alone | test isolation |
| `test_stock_data_reports_source_and_from_cache` | order-dependent, passes alone | test isolation |

Only the first is a product defect. The other five are pre-existing test-hygiene
or wording issues and were out of scope for the remediation.

---

## 3. Consistency and documentation gaps

Not incorrect, but a consumer can still get them wrong.

- **India composite reads `complete` beside `partial` in one object.**
  `coverage.status: "complete"` describes the promoted liquidity universe while
  `composite_coverage_status: "partial"` describes the composite. Deliberate —
  `_section_coverage` recomputes `status` from ticker math and would overwrite a
  composite `partial`, and faking a missing ticker to force it is worse. Flagged
  as a shape a consumer can misread.
- **`sector_weight_basis` is a second weight-basis literal** outside the
  canonical `ACTIVE_WEIGHT_BASIS`. Truthful, but a consumer substring-matching
  `weight_basis` sees two vocabularies.
- **`liquidity.overall_score_raw` is the mean of the ROUNDED per-position
  scores**, not of the raw ones (7.971429 vs 7.977300). Defensible; undocumented.
- **`diversification_score` is published at 1 dp** where the rest of the
  section uses 4 dp, and no formula is given. HHI 0.0862 -> 91.4, DR 0.83 -> 83,
  N_eff 11.61/14 -> 82.9; none reproduce 98.4 from published fields.
- **`risk_studio.high_tail_risk_pairs` risk categories have no published
  threshold rule.** Liquidity ships a full `scoring.bands` table; this does not.
- **Monte Carlo `expected_shortfall_vs_target` is not derivable** from the five
  published percentiles. Inherent to publishing percentiles only; the figure is
  coherent but independently unverifiable.

---

## 4. Deliberate decisions, not defects

- **The 30-day annualization gate is unchanged.** It still annualizes
  36-39-observation samples; the portfolio Tear Sheet reports a ~43% CAGR from a
  39-day return. The window is now labelled and the measured days are published,
  but tightening the gate is a policy decision, not a bug fix.
- **Liquidity currency is `INR` with `currency_provenance: "derived"`** — the
  unit is a property of the engine's fixed INR thresholds, not read off a quote.
  Stated in `currency_basis` rather than inferred silently.
- **A sub-lot trade rounding to zero shares is reported, not executed.** MCX.NS
  has a ₹1,109.62 notional against a ₹3,262.60 share price. It publishes
  `status: below_minimum_notional` with the notional preserved and a reason.

---

## 5. How these get caught from now on

Every item above is encoded as a hard-failing rule in the new checker
(`backend/app/debugging/context_audit.py`). D-01 through D-06 are expected to be
**red** until fixed; they are deliberately recorded as failures rather than
suppressed, so the tool reports the real state of the export rather than a
comfortable one.
