# 18 — Point-in-time fundamental snapshots

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: Phase 1 issue 07
Repo: `backend/`
Effort: M | Score: 24

## What

Screener.in and bfinance's Ind AS statements are **current vintage**. Store dated snapshots so
historical analysis uses the fundamentals that were actually available at the time.

```sql
CREATE TABLE fundamental_snapshots (
    id           INTEGER PRIMARY KEY,
    ticker       TEXT NOT NULL,
    as_of        DATE NOT NULL,          -- the filing/publication date
    period_end   DATE NOT NULL,          -- the fiscal period the figures describe
    statement    TEXT NOT NULL,
    payload      JSON NOT NULL,
    source       TEXT NOT NULL,
    UNIQUE (ticker, as_of, period_end, statement)
);
```

## Why

**Any backtest or historical screen using today's fundamentals on a 2019 rebalance has look-ahead
bias.** This is not a subtle statistical issue — it is a straightforward use of information that did
not exist.

Concretely, the app's screener and its equity-research fundamentals are all current-vintage. A
historical screen run through them is systematically biased toward stocks that look good now and
looked different then.

Compustat Point-in-Time and Refinitiv both ship **as-of-dated** fundamentals for exactly this
reason. This is baseline hygiene for any backtesting product, not an advanced feature.

## Change

- A dated snapshot table, keyed by `(ticker, as_of, period_end, statement)`.
- **The filing/publication date, not the period end.** A FY2024 annual report published in May 2025
  was not available in March 2025, and the difference is the entire point.
- Populate from bfinance's Ind AS statements (Phase 1 issue 07 delivers the corrected yfinance
  shape and real ex-dates).
- Corporate actions matter here too: Phase 1 issue 05's real ex-dates let a fundamentals time series
  be adjusted consistently.
- Add a `fundamentals_as_of` parameter to the screener and to any historical query, so a caller can
  ask "what did I know on date X".
- **Refuse or warn** when a backtest or screen requests current-vintage fundamentals for a
  historical date. Silent look-ahead is worse than an error.

## Proof of done

- [ ] Snapshots are keyed by publication date and a period-end/publish-date ordering test confirms
      they cannot be confused.
- [ ] A query with `fundamentals_as_of='2019-06-30'` returns only what was published by that date.
      **This is the key correctness test** — a fixture with a deliberately late-filed period proves
      it.
- [ ] A restatement creates a new snapshot rather than overwriting, consistent with Phase 4 issue
      07's restatement handling.
- [ ] A historical screen that would use look-ahead fundamentals **warns or refuses**. A test
      asserts the refusal.
- [ ] The response states the fundamentals vintage used, alongside the existing provenance
      convention.
- [ ] The snapshot table does not grow unboundedly. A retention or compaction policy is documented.
- [ ] Current-vintage queries are unaffected and fast — the common case must not regress.

## Notes

This is unglamorous and it is one of the two or three things that separate a real backtester from a
curve-fitter. Bailey & López de Prado's Deflated Sharpe work is essentially about this class of
problem: a backtest that leaks future information will produce an apparently excellent strategy
that does not work.

Pair with issue 09's bootstrap intervals and the phase spec's anti-pattern 3 on deflated Sharpe.
All three are about not fooling yourself.

Refs: `../spec.md`, Phase 1 issues 05, 07, Phase 4 issue 07
