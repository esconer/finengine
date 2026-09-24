"""Verified SQLite backup/restore helper used by the deployment script.

The deployment runs this module inside a one-off backend container, so both
source and destination are resolved from the same ``DATABASE_URL`` and mounted
path as the application.  A backup is not reported successful until
``PRAGMA quick_check`` and per-table row counts match.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

try:  # normal module execution: python -m migrations.sqlite_backup
    from .schema_version import resolve_sqlite_database_path
except ImportError:  # direct file execution in isolated tests/tools
    from schema_version import resolve_sqlite_database_path


def quick_check(path: str | Path) -> str:
    db_path = Path(path).expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        rows = [str(row[0]) for row in conn.execute("PRAGMA quick_check").fetchall()]
    value = "ok" if rows == ["ok"] else "; ".join(rows)
    if value != "ok":
        raise sqlite3.DatabaseError(f"quick_check failed for {db_path}: {value}")
    return value


def table_counts(path: str | Path) -> dict[str, int]:
    db_path = Path(path).expanduser().resolve()
    with sqlite3.connect(str(db_path)) as conn:
        tables = [
            str(row[0])
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            ).fetchall()
        ]
        return {
            table: int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in tables
        }


def verify_database(source: str | Path, copy: str | Path) -> dict[str, Any]:
    source_counts = table_counts(source)
    copy_counts = table_counts(copy)
    if source_counts != copy_counts:
        raise sqlite3.DatabaseError(
            f"row-count mismatch: source={source_counts!r}, copy={copy_counts!r}"
        )
    return {
        "quick_check": quick_check(copy),
        "table_counts": copy_counts,
        "total_rows": sum(copy_counts.values()),
    }


def backup_database(source: str | Path, destination: str | Path) -> dict[str, Any]:
    source_path = Path(source).expanduser().resolve()
    destination_path = Path(destination).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if source_path == destination_path:
        raise ValueError("backup destination must differ from the configured database")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if destination_path.exists():
        raise FileExistsError(destination_path)

    with sqlite3.connect(str(source_path)) as source_conn:
        with sqlite3.connect(str(destination_path)) as destination_conn:
            source_conn.backup(destination_conn)
    return {
        "source": str(source_path),
        "destination": str(destination_path),
        **verify_database(source_path, destination_path),
    }


def restore_database(backup: str | Path, destination: str | Path) -> dict[str, Any]:
    """Restore into a new file through SQLite's backup API, never raw SQL."""

    return backup_database(backup, destination)


def _configured_path() -> Path:
    database_url = os.environ.get(
        "DATABASE_URL", "sqlite+aiosqlite:///./data/daisy.db"
    )
    return resolve_sqlite_database_path(database_url)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="source/backup database path")
    parser.add_argument("--destination", type=Path, help="new backup/restore path")
    parser.add_argument(
        "--print-configured-path",
        action="store_true",
        help="print the absolute path resolved from DATABASE_URL",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="run quick_check and print source table counts without writing",
    )
    args = parser.parse_args(argv)

    try:
        source = args.source or _configured_path()
        if args.print_configured_path:
            print(source.resolve())
        if args.print_configured_path and not args.verify_only and args.destination is None:
            return 0
        if args.verify_only:
            print(json.dumps({"source": str(source.resolve()), **verify_database(source, source)}, sort_keys=True))
            return 0
        if args.destination is None:
            parser.error("--destination is required unless only printing/verifying")
        result = backup_database(source, args.destination)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, sqlite3.DatabaseError) as exc:
        print(f"SQLite backup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
