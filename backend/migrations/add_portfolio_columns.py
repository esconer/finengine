"""
Database migration to add quantity and buy_price columns to portfolio_positions table

Never fabricates values: legacy rows keep whatever they had after the ALTER
(server default 0.0 = unknown cost basis; the API surfaces that, this script
must not invent quantity=100 / buy_price=mv/100 — audit B1). A backup via the
SQLite backup API is taken before any mutation (same pattern as
cleanup_duplicates_and_add_constraints.create_backup).
"""

import sqlite3
from datetime import datetime
from pathlib import Path


def create_backup(db_path: Path) -> Path:
    """Snapshot the database before mutating it (SQLite backup API)."""
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"daisy_backup_{timestamp}.db"
    with sqlite3.connect(str(db_path)) as source:
        with sqlite3.connect(str(backup_path)) as backup:
            source.backup(backup)
    print(f"Backup created: {backup_path}")
    return backup_path


def migrate_database(db_path: Path | None = None):
    """Add new columns to portfolio_positions table (never rewrites rows)."""

    # Database path (overridable for tests; default stays the live DB)
    if db_path is None:
        db_path = Path(__file__).parent.parent / "data" / "daisy.db"

    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return False

    print(f"Connecting to database: {db_path}")
    conn = None

    try:
        # Backup BEFORE any mutation — if connect itself fails here the
        # finally-block below still sees conn = None (no UnboundLocalError).
        create_backup(db_path)

        # Connect to database
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        # Check if columns already exist
        cursor.execute("PRAGMA table_info(portfolio_positions)")
        columns = [column[1] for column in cursor.fetchall()]

        print(f"Current columns: {columns}")

        # Add quantity column if it doesn't exist
        if 'quantity' not in columns:
            print("Adding 'quantity' column...")
            cursor.execute("ALTER TABLE portfolio_positions ADD COLUMN quantity REAL DEFAULT 0.0")
            print("✓ Added 'quantity' column")
        else:
            print("✓ 'quantity' column already exists")

        # Add buy_price column if it doesn't exist
        if 'buy_price' not in columns:
            print("Adding 'buy_price' column...")
            cursor.execute("ALTER TABLE portfolio_positions ADD COLUMN buy_price REAL DEFAULT 0.0")
            print("✓ Added 'buy_price' column")
        else:
            print("✓ 'buy_price' column already exists")

        # Legacy rows are deliberately left as-is: quantity/buy_price stay at
        # the ALTER default (0.0 = unknown cost basis). Rewriting them would
        # fabricate P&L forever (previous SET quantity=100.0 clause removed).

        # Commit changes
        conn.commit()
        print("✓ Migration completed successfully!")

        # Verify the changes
        cursor.execute("PRAGMA table_info(portfolio_positions)")
        final_columns = [column[1] for column in cursor.fetchall()]
        print(f"Final columns: {final_columns}")

        return True

    except Exception as e:
        print(f"✗ Migration failed: {e}")
        return False

    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    print("Starting database migration...")
    success = migrate_database()
    if success:
        print("Migration completed successfully!")
    else:
        print("Migration failed!")
        exit(1)
