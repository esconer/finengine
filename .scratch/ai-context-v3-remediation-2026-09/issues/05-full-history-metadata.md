# 05: Separate full-history calculations from holding context

**What to build:** Make hypothetical current-weight calculations self-describing by separating actual model observations from ancillary holding context and by giving regime-conditional summaries their own sample coverage.

**Blocked by:** 04: Correct holding-window and per-position disclosure

**Closes:** V3-05, Risk Studio/Tear Sheet portion of V3-17

**Evidence:** full-history models carry holding `effective_start`/`truncated`; regime conditional sample is 19 days while copied coverage says 39 days; hypothetical model observations are 176/252.

**Work area:** Full-history versus holding-context separation, Factor/Risk Contribution model coverage, and conditional regime coverage. Regime probability/units remain owned by ticket 07.

**bfinance gate:** No bfinance edits. Sparse or late-listed model history must remain sparse and labelled; never substitute a source-default price. If bfinance must change, stop and request explicit approval through a written proposal.

**Status:** ready-for-agent

- [ ] Factor Exposure and Risk Contribution expose model start/end dates, observation counts, and full-history basis without claiming the model window was truncated to holdings.
- [ ] Full-history evidence lives in a separate object with its own window, observation count, latest observation, and annualization flag; it is never merged into holding `history_coverage`.
- [ ] Holding context is clearly ancillary and cannot overwrite model coverage or annualization status.
- [ ] Full-history metrics with sparse or late-listed legs expose per-ticker usable observations and limited-history flags.
- [ ] Portfolio-in-current-regime uses a conditional coverage object whose covered days and annualization status match the conditional sample.
- [ ] Risk Studio component windows and portfolio/summary sections either gain explicit delivered evidence or are recorded as verified no-change.
- [ ] Tests distinguish 39 total holding days from 19 days in the current regime and from 252 hypothetical model observations.
