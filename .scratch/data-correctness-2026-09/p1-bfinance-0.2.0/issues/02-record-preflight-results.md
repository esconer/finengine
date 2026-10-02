# 02 — Close the pre-flight findings in the master spec

Status: ready-for-agent
Type: task
Phase: 1
Blocked by: —
Repo: `C:\es\coding\bfinance`

## What

Phase 0 produces four answers. This ticket records them in one place so the Phase 1 and Phase 2
tickets can be scoped against facts rather than assumptions.

## Why

Two load-bearing assumptions in the master spec are unverified:

1. The NSE CM bhavcopy **legacy path was discontinued 08-Jul-2024** (NSE Circular 62424). The
   current UDiFF path is presumed to work and is presumed cookie-free.
2. `stock_timeseries` is presumed to hold months of synthetic bfinance bars.

If either is wrong, issues 06 and Phase 2 issue 02 are mis-sized. This ticket is the single place
that finding is recorded, so every downstream agent reads the same facts.

## Proof of done

- [ ] A `## Pre-flight results` section is appended to `../spec.md` with all four answers.
- [ ] The chosen Phase 2 migration strategy (bulk purge vs lazy per-ticker refetch) is stated
      explicitly, with the row count that justifies it.
- [ ] If the bhavcopy route turned out to need a session or be unreachable, issue 06 is
      re-scoped and the revised estimate is recorded.
- [ ] If bfinance is installed from PyPI rather than a local path, the Phase 1 release sequencing
      is revised to publish-then-bump and recorded.
- [ ] Any other consumer of bfinance found on this machine is recorded, since it determines
      whether 0.2.0 can be a clean break.
- [ ] The Phase 0 issue files are updated to `Status: resolved` with the date.

## Notes

Pure documentation. No code changes.

Refs: `../../p0-preflight/spec.md`, `../spec.md`
