# Backend audit remediation todo

Status: completed
Scope: latest user-authorized implementation follow-up; preserve the completed A/B/C/D remediation and all existing dirty-tree work.

- [x] Trace `/v1/models` callers and configuration; no in-repo caller or LLM provider exists.
- [x] Confirm current OpenAI-compatible model-list contract from current Context7 documentation.
- [x] Add an honest `/v1/models` discovery response with an empty model list and no fabricated capability claims.
- [x] Add regression coverage for status, schema, and no fabricated model IDs.
- [x] Run focused API tests, Ruff, and scoped diff checks.
- [x] Update the fix index/evidence with the endpoint decision and remaining limitations.

Decision: do not invent chat-model IDs or claim chat/completions support; FinEngine currently provides prompts/dossiers and analytics, not an LLM server. `GET /v1/models` now returns HTTP 200 with `{"object":"list","data":[]}` so generic discovery probes do not receive a misleading 404. Focused API: 39 passed; refreshed integrated gate: 224 passed; independent endpoint verifier: PASS.
