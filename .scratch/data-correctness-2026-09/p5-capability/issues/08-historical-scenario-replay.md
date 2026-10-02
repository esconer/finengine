# 08 — Historical scenario replay

Status: ready-for-agent
Type: task
Phase: 5
Blocked by: 07
Repo: `backend/`
Effort: S/M | Score: 28

## What

Replace parameter-free-unavailable stress scenarios with **actual historical windows**, replayed.

Candidate windows, all of which the app can already source from `^NSEI` plus issue 07's sector
indices:

| Window | Character |
|---|---|
| Jun–Sep 2013 | taper tantrum / rupee crisis |
| Oct 2014–Mar 2015 | index peak and 40%+ correction |
| Feb–Mar 2020 | COVID crash |
| Oct 2024 | sharp index correction |
| Budget day 2025 | event-day gap |
| 2008 | for the long tail |

Plus: "worst N-day drawdown in history", found by scanning rather than hand-picking.

## Why

**Zero free parameters. Uses only data already in the system.** Every other stress approach requires
choosing a shock size and a set of elasticities — and choosing them is where the fabrication enters.

`stress-testing` currently uses 4 hand-set macro shocks (Market Crash −35%, Interest Rate Shock
−15%, Volatility Spike −22%, Tech Correction −18%) multiplied by **hand-tuned sector elasticities**
from `CONTEXT.md` §9.13. A scenario grid whose sector betas were invented is the definition of fake
precision — and the gotcha's own comment documents the absurd outputs it was patched to fix.

A historical replay has no parameter to get wrong. It answers "what happened to a portfolio like
mine in 2020?" rather than "what if the market drops 35%?".

The worst-N-day scan is the strongest version, because it is **not** cherry-picked: it is derived
from the data, so it cannot be accused of scenario selection.

## Change

- Replay the actual return path for each window, position by position.
- Report each position's drawdown, portfolio drawdown, time to recovery, and days underwater.
- Add the **worst N-day drawdown scan** across full history, for several N (5, 20, 60, 120 days).
  This is the parameter-free headline.
- Keep the current synthetic scenarios, clearly labelled, for the *forward-looking* question
  ("what if the market drops 35%?") — replay cannot answer that. The two are complementary, not
  competing: replay is historical fact, synthetic is a hypothetical.
- With issue 07, use real sector co-movement rather than elasticities.

## Proof of done

- [ ] Each named window replays correctly, and the portfolio drawdown is verified against a
      hand-computed reference for at least one window.
- [ ] The worst-N-day scan returns the correct window for a synthetic series with a known worst
      drawdown. A test constructs one.
- [ ] Each replay reports per-position drawdown, portfolio drawdown, days underwater, and recovery
      time.
- [ ] An unrecovered historical window reports a censored recovery time, not a fabricated one.
- [ ] Replay and synthetic scenarios are clearly distinguished in the UI. Neither is presented as
      the other.
- [ ] The `CONTEXT.md` §9.13 elasticity constants are unused once issue 07 lands. A test asserts
      they are unreferenced.
- [ ] The response states the window's date range and the data source for every replay.

## Notes

The 2008 window needs care — the data may not reach back that far, and the index composition was
different. Prefer windows where the app has full, consistent data, and say so rather than
presenting a partial window as a full one.

The distinction between replay and synthetic is important to keep sharp in the UI. Replay is what
happened. Synthetic is what might. Conflating them would be a new instance of the exact problem
Phase 3 issue 02 fixes.

Refs: `../spec.md`, `CONTEXT.md` §9.13, Phase 3 issue 02, Phase 5 issue 07
