## Agent skills

### Issue tracker

Local markdown: issues live as files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: root `CONTEXT.md` + `docs/adr/`. See `docs/agents/domain.md`.

## Execution & Command Rules

- All `uv` commands (`uv run`, `uv sync`, `uv tool run`, `uvx`) are pre-approved and should run non-interactively without user confirmation prompts.
- Always include `-y` or `--yes` when executing `uv tool run` or `uvx` tools.

