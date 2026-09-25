# 05: Separate full-history calculations from holding context

**What to build:** Make hypothetical current-weight calculations self-describing by separating actual model observations from ancillary holding context and by giving regime-conditional summaries their own sample coverage.

**Blocked by:** 04: Correct holding-window and per-position disclosure

**Status:** ready-for-agent

- [ ] Factor Exposure and Risk Contribution expose model start/end dates, observation counts, and full-history basis without claiming the model window was truncated to holdings.
- [ ] Holding context is clearly ancillary and cannot overwrite model coverage or annualization status.
- [ ] Full-history metrics with sparse or late-listed legs expose per-ticker usable observations and limited-history flags.
- [ ] Portfolio-in-current-regime uses a conditional coverage object whose covered days and annualization status match the conditional sample.
- [ ] Tests distinguish 39 total holding days from 19 days in the current regime and from 252 hypothetical model observations.
