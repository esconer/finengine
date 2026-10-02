# 06 — The "Live Data Active" pill is a local boolean

Status: ready-for-agent
Type: task
Phase: 3
Blocked by: Phase 2 issue 10
Repo: `frontend/`
Severity: **MEDIUM**

## What

`dashboard/page.tsx:372-374`
```tsx
<span className="text-sm">{liveDataMode ? 'Live Data Active' : 'Live Data Off'}</span>
```

`liveDataMode` comes from `store.ts:361-363` — a **persisted local boolean** in the Zustand UI
store.

## Why

No live or websocket health is ever consulted. The pill reads **"Live Data Active" with a green
dot through a complete backend outage.**

The label also describes the wrong thing: `liveDataMode` is a user preference for whether
auto-refresh is *enabled*, not a statement about whether data *is* live. The wording converts a
setting into a claim.

Phase 2 issue 10 makes the WebSocket able to report real staleness, which is the input this needs.

## Change

- Drive the indicator from the actual connection and data-freshness state: the WebSocket
  connection status plus the server-published `data_as_of` (Phase 2 issue 10).
- Distinguish three states, not two:
  - connected and fresh → "Live"
  - connected but data is stale → "Stale" with the age
  - disconnected → "Reconnecting" or "Offline"
- If the rename is not wanted, relabel to "Auto-refresh on" / "Auto-refresh off", which is an
  honest description of what the boolean controls.
- Use the server's observation timestamps, not client receipt time — the `india-flows` page already
  does this correctly at `:75-80` and is the reference implementation.

## Proof of done

- [ ] The pill reflects real connection state. A test simulates a dropped connection and asserts
      the state changes.
- [ ] A full backend outage does **not** render "Live Data Active".
- [ ] Staleness is shown with an age derived from the server's `data_as_of`, not from client time.
- [ ] The three states are visually distinguishable.
- [ ] `liveDataMode` remains as the auto-refresh preference, clearly labelled as such.

## Notes

Small change, but it is the kind of detail that determines whether a user trusts the rest of the
dashboard. An indicator that is always green trains the user to ignore it.

Refs: `../spec.md`, `frontend/src/app/dashboard/page.tsx:372-374`, `frontend/src/lib/store.ts:361-363`, `frontend/src/app/dashboard/india-flows/page.tsx:75-80`
