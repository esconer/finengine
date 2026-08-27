# QH-10 — SQLite upsert robustness + unused dependency cleanup

Status: closed
Type: task
Blocked by: —

## What

**Fragile upsert** (`data_service.py`, ~line 588): The caching logic tries `INSERT`, catches
the exception, and string-matches `"UNIQUE constraint failed"` to trigger an `UPDATE`. This
is fragile and SQLite-version-dependent.

**Unused backend deps** (`pyproject.toml`): `scikit-learn` and `alembic` are installed but
unused in any import. `alembic` was intended for migrations but ad-hoc scripts are used instead.

**Unused frontend deps** (`package.json`): `jspdf`, `papaparse`, `xlsx`, `file-saver` are
installed but CSV export uses manual string concatenation. Either use them or remove them.

## Fix

1. Replace string-matching upsert with SQLAlchemy's native
   `sqlite.insert(...).on_conflict_do_update(...)` for atomic, robust upserts.
2. Remove `scikit-learn` and `alembic` from `pyproject.toml` (hmmlearn is used by
   regime_service, keep it).
3. Either wire `papaparse` for CSV export and `jspdf` for PDF generation (both are planned
   features in t19/t23), or remove them until those tickets land.

## Why

String-matching exception handling breaks across SQLite versions. Unused deps bloat the
install and create false dependency chains.

## Proof of done
- [ ] `data_service.py` uses `on_conflict_do_update` — no string matching
- [ ] `uv sync --extra dev` completes without scikit-learn/alembic
- [ ] Frontend `bun install` doesn't pull unused large packages
