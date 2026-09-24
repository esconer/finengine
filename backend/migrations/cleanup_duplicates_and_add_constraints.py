"""Safe compatibility wrapper for the former destructive cleanup migration.

Duplicate records are user data.  This script no longer deletes them.  It
delegates to the versioned migration runner, which first reports the conflicting
natural keys, creates a SQLite backup, and fails closed until an operator has
reconciled those rows.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from migrations.schema_version import (
        LATEST_SCHEMA_VERSION,
        MigrationBlocked,
        apply_migrations,
        create_database_backup,
    )
except ImportError:  # direct execution from the migrations directory
    from schema_version import (
        LATEST_SCHEMA_VERSION,
        MigrationBlocked,
        apply_migrations,
        create_database_backup,
    )

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "daisy.db"


class DatabaseCleanupManager:
    """Backwards-compatible facade over the non-destructive migration runner."""

    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH):
        path = Path(db_path)
        if not path.exists():
            raise FileNotFoundError(
                f"Database not found at {path} — refusing to create an empty one"
            )
        self.db_path = str(path)
        self.backup_dir = str(path.parent / "backups")

    def create_backup(self) -> str | None:
        backup = create_database_backup(self.db_path)
        return str(backup) if backup else None

    def analyze_duplicates(self) -> dict[str, Any]:
        with sqlite3.connect(self.db_path) as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM stock_timeseries").fetchone()[0])
            rows = conn.execute(
                """
                SELECT upper(trim(ticker)) AS ticker, date, COUNT(*) AS count
                FROM stock_timeseries
                GROUP BY upper(trim(ticker)), date
                HAVING COUNT(*) > 1
                ORDER BY count DESC, ticker, date
                """
            ).fetchall()
        return {
            "total_records": total,
            "duplicate_combinations": len(rows),
            "total_duplicate_records": sum(int(row[2]) - 1 for row in rows),
            "duplicate_details": [dict(zip(("ticker", "date", "count"), row)) for row in rows[:10]],
        }

    def cleanup_duplicates(self) -> dict[str, Any]:
        raise RuntimeError(
            "destructive duplicate deletion was removed; reconcile reported keys explicitly"
        )

    def add_unique_constraints(self) -> bool:
        result = apply_migrations(self.db_path)
        return result.current_version == LATEST_SCHEMA_VERSION

    def validate_cleanup(self) -> dict[str, Any]:
        before = self.analyze_duplicates()
        return {
            "remaining_duplicates": before["duplicate_combinations"],
            "constraint_works": before["duplicate_combinations"] == 0,
            "cleanup_successful": before["duplicate_combinations"] == 0,
        }

    def run_full_cleanup(self) -> dict[str, Any]:
        before = self.analyze_duplicates()
        result: dict[str, Any] = {
            "before_cleanup": before,
            "timestamp": datetime.now().isoformat(),
        }
        try:
            migration = apply_migrations(self.db_path)
        except MigrationBlocked as exc:
            result.update(
                {
                    "backup_created": str(exc.backup_path) if exc.backup_path else None,
                    "blocked_issues": exc.issues,
                    "validation": {
                        "remaining_duplicates": before["duplicate_combinations"],
                        "constraint_works": False,
                        "cleanup_successful": False,
                    },
                    "success": False,
                }
            )
            return result
        result.update(
            {
                "backup_created": str(migration.backup_path) if migration.backup_path else None,
                "constraints_added": True,
                "validation": self.validate_cleanup(),
                "after_cleanup": self.analyze_duplicates(),
                "success": True,
            }
        )
        return result


def main() -> dict[str, Any]:
    result = DatabaseCleanupManager().run_full_cleanup()
    print(json.dumps(result, indent=2, default=str))
    return result


if __name__ == "__main__":
    outcome = main()
    raise SystemExit(0 if outcome.get("success") else 1)
