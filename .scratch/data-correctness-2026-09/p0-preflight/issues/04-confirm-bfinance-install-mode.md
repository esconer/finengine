# 04 — Confirm how bfinance is installed in the backend venv

Status: ready-for-agent
Type: research
Phase: 0
Blocked by: —

## What

Determine whether the backend consumes bfinance from PyPI or from a local path/workspace link, and
whether a local 0.2.0 build can be picked up without publishing.

```powershell
cd C:\es\coding\finengine\backend
uv pip show bfinance
uv run python -c "import bfinance, pathlib; print(bfinance.__version__); print(pathlib.Path(bfinance.__file__).parent)"
Select-String -Path uv.lock -Pattern 'name = "bfinance"' -Context 0,6
```

`backend/uv.lock:363` pins `bfinance==0.1.3`. `backend/pyproject.toml` declares `"bfinance>=0.1.0"`
as an ordinary dependency with no `[tool.uv.sources]` workspace entry.

## Why

Phase 1 issues 06, 07, 08, and 13 are **breaking**. How bfinance is consumed determines the whole
release strategy:

- **PyPI pin** → the fixes must be published before this app can use them, and the app's
  `pyproject.toml` must be bumped in a coordinated commit. Cross-repo sequencing matters, and a
  half-published 0.2.0 leaves the app unable to start.
- **Local path / workspace source** → the two repos iterate independently, and Phase 1 can be
  developed and tested against the app in the same working tree with no publish step.
- **Vendored copy inside the venv** → there is a third stale copy in play and it must be found.

This also affects whether an existing deployed environment would pick up a 0.2.0 automatically.

## Proof of done

- [ ] `bfinance.__file__` resolves to a path, and whether that path is inside
      `C:\es\coding\bfinance` or inside `backend/.venv` is stated explicitly.
- [ ] The `uv.lock` entry and the `pyproject.toml` declaration are quoted verbatim.
- [ ] Whether a `[tool.uv.sources]` or `[tool.uv.workspace]` section exists anywhere is confirmed.
- [ ] The recommended Phase 1 release path is stated: publish-then-bump, or local path override.
- [ ] If a publish is required, whether `bfinance` is already on PyPI is confirmed and under what
      name, since the project is versioned 0.1.3 and PyPI-shaped.
- [ ] Any other consumer of bfinance on this machine is identified (other repos in
      `C:\es\coding`, scheduled jobs, notebooks), because it determines whether 0.2.0 can be a
      clean break or needs a deprecation window.

## Notes

Read-only. Do not change the pin in this ticket.

Refs: `../spec.md`, `backend/pyproject.toml`, `backend/uv.lock`
