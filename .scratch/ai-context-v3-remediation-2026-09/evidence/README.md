# v4 Evidence Directory

This directory will hold the post-remediation export artifacts.

Required before ticket 09 can close:

- `v4-export.json` — complete JSON export
- `v4-export.md` — Markdown rendering of the same envelope
- `v4-audit.md` — 17-section verdict table, field-level v3→v4 delta, arithmetic checks, coverage/status checks, and any remaining warnings
- `v4-determinism.md` — two-export comparison with allow-listed run-metadata differences

Do not commit secrets, live credentials, or a modified bfinance source tree.
