# 07 — NSE sector index returns as a first-class series

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: —
Repo: `backend/`
Effort: S | Score: 35

## What

Ingest the 13 GICS sector indices as real return series.

```python
SECTOR_INDICES = {
    "Technology":              "^CNXIT",
    "Healthcare":              "^CNXPHARMA",
    "Automobile":              "^CNXAUTO",
    "Energy":                  "^CNXENERGY",
    "Infrastructure":          "^CNXINFRA",
    "Metal":                   "^CNXMETAL",
    "FMCG":                    "^CNXFMCG",
    "Private Sector Bank":     "^CNXPSUBANK",
    "Financial Services":      "^CNXFINANCE",
    "Realty":                  "^CNXREALTY",
    "Media":                   "^CNXMEDIA",
    "PSU Bank":                "^CNXPSE",
    "Services":                "^CNXSERVICE",
}
```

All available via the existing yfinance/bfinance tier. **Free, no new source needed.**

## Why

This replaces a fabricated input with a measured one.

`CONTEXT.md` §9.13 documents the current stress-test sector elasticity multipliers as
**hand-tuned, unsourced, unbounded** constants:

> Healthcare 0.25–0.55×, Utilities 0.20–0.70×, Tech 1.10–1.80×, Financials 0.50–1.50×,
> Cyclicals 0.60–1.55×

The gotcha's own comment admits the problem — *"artificial −98% bankruptcy wipeout artifacts and
flat −26.3% clamp clusters"*. The multipliers were invented to stop the model producing absurd
numbers, which is a sign the input was missing.

With real sector index returns, those elasticities become **estimated betas from actual
regressions**. The multipliers are not tuned; they are fitted.

Sector indices are also a precondition for issues 14 (Brinson needs sector returns and
constituent weights) and 15 (sector-relative factor exposure). Those are blocked on this.

## Change

- A sector-index series store, or reuse the existing benchmark machinery with multiple benchmarks.
- Map every portfolio holding to its GICS sector. The app has a 4-level taxonomy from
  `equity_research_service`; align it to these 13 buckets and make the mapping explicit and
  inspectable. An unmapped ticker must be visible, not silently bucketed.
- Estimate sector betas by regressing each sector index against `^NSEI` over a stated window.
- Replace the `CONTEXT.md` §9.13 elasticity constants with the estimated betas. **If any elasticity
  is retained, label it `assumed_not_estimated`** — the codebase already has that vocabulary.
- Expose sector returns as a time series for use by issues 08, 14, and 15.

## Proof of done

- [ ] All 13 sector indices return real return series.
- [ ] Every portfolio holding maps to a sector, or is listed as unmapped. A test asserts no silent
      bucketing.
- [ ] Sector betas are estimated from actual regressions and are reported with their window,
      R², and observation count.
- [ ] The stress test uses estimated betas and **no longer uses the hand-tuned multipliers**. A
      test asserts the constants are unreferenced.
- [ ] A residual check: the estimated betas should broadly agree with the old hand-tuned ranges.
      A large divergence means the mapping is wrong, not that the hand-tuning was right. Record
      the comparison in `## Comments`.
- [ ] A sector with insufficient data returns `None` with a reason, and the stress test degrades
      visibly rather than using a default.
- [ ] `CONTEXT.md` §9.13 is updated to describe the estimated-betas approach.

## Notes

The residual check in the proof-of-done is the important one. If an estimated beta comes out at 0.1
where the hand-tuned value said 0.55, the likely cause is a sector-mapping error, not a discovery.
Check the mapping before trusting the number.

Do this **before** issue 08. Historical scenario replay is far more valuable once the sector
elasticity problem is solved, because replay can then use real co-movement rather than proxies.

Refs: `../spec.md`, `CONTEXT.md` §9.13, Phase 5 issues 08, 14, 15
