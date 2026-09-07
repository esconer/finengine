zcode last session — CLOSED 2026-09-07.

All three workstreams landed and verified (backend 372/372 pytest, ruff
clean; frontend tsc clean, 66/66 vitest):

1. Backend risk — tear-sheet `full_history` split + frontend "Instrument
   Risk — Full Exchange History" section (the 8 N/A fields now have real
   full-history values alongside); risk-contribution full-history
   covariance; `/analytics/tails` 15-min TTL cache. Also fixed a
   SyntaxError the cache insert had introduced (consts between the
   stacked `@router.get` decorators broke backend import).
2. Pairs — `NOT_COINTEGRATED` gating at p>=0.05 + "Not cointegrated"
   rendering + regression test.
3. Frontend polish — india-flows `<0.1d`, screener cold-cache hint,
   Forecast/Sizing vol-reconciliation captions.

Still open, out of scope: regime posterior saturation, header timestamp
unification, liquidity skeleton, dashboard vol gate, monte-carlo copy.
