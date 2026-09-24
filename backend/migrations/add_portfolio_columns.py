"""Compatibility entry point for the historical portfolio-column migration.

The implementation now lives in the versioned migration runner.  This wrapper
keeps the old callable/CLI contract while ensuring every mutation is backed up,
recorded in ``PRAGMA user_version``, and safe for existing data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

try:
    from migrations.schema_version import apply_migrations, create_database_backup
except ImportError:  # direct execution from the migrations directory
    from schema_version import apply_migrations, create_database_backup


def create_backup(db_path: Path) -> Path | None:
    """Snapshot the database before the compatibility entry point mutates it."""

    return create_database_backup(db_path)


def migrate_database(db_path: Path | None = None) -> bool:
    """Converge an existing database to the current version without fabricating rows."""

    path = (
        Path(db_path)
        if db_path is not None
        else Path(__file__).resolve().parent.parent / "data" / "daisy.db"
    )
    if not path.exists():
        print(f"Database not found at {path}")
        return False

    print(f"Connecting to database: {path}")
    try:
        result = apply_migrations(path, connect_factory=sqlite3.connect)
    except Exception as exc:
        print(f"Migration failed: {exc}")
        return False

    print(
        "Migration completed successfully: "
        f"version={result.current_version}, backup={result.backup_path or 'not-needed'}"
    )
    return True


if __name__ == "__main__":
    print("Starting database migration...")
    success = migrate_database()
    if success:
        print("Migration completed successfully!")
    else:
        print("Migration failed!")
    raise SystemExit(0 if success else 1)
