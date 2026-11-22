"""Restatement dimension on nse_shareholding_patterns.

A company re-files its shareholding pattern for a quarter that is already on
record.  While the table was keyed on (symbol, period_ended) alone, that filing
upserted onto the original row: the restatement looked like an update and the
pre-restatement row became unreadable.  The filing's own revision date is the
third key part, so a restatement inserts and both filings stay readable, while a
re-file at the same revision still upserts.

Covers the model's key contract and the versioned migration that carries an
existing table onto it.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from app.models.database import NSEShareholdingPattern
from migrations.schema_version import LATEST_SCHEMA_VERSION, MigrationBlocked, apply_migrations

SYMBOL = "RELIANCE"
PERIOD = "2024-12-31"
FIRST_FILING = datetime(2026, 2, 10, 9, 30)
RESTATED_FILING = datetime(2026, 8, 14, 18, 5)
KEY = ["symbol", "period_ended", "revision_date"]

# The pre-restatement filing as the company reported it in February.
ORIGINAL = {"promoter_pct": 0.5123, "promoter_pledged_pct": 0.004}
# The same quarter as re-filed in August, promoter holding restated downward.
RESTATED = {"promoter_pct": 0.4801, "promoter_pledged_pct": 0.004}


def _table_engine(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    NSEShareholdingPattern.__table__.create(engine)
    return engine


def _upsert(engine: Engine, revision: datetime, **values: float) -> None:
    """The writer a producer must use: conflict on the full revision key."""

    with engine.begin() as conn:
        conn.execute(
            sqlite_insert(NSEShareholdingPattern)
            .values(symbol=SYMBOL, period_ended=PERIOD, revision_date=revision, **values)
            .on_conflict_do_update(
                index_elements=KEY,
                set_={column: values[column] for column in values},
            )
        )


def _rows(engine: Engine) -> list[tuple]:
    with engine.connect() as conn:
        return conn.exec_driver_sql(
            "SELECT symbol, period_ended, revision_date, promoter_pct, promoter_pledged_pct "
            "FROM nse_shareholding_patterns ORDER BY revision_date"
        ).all()


def _unique_index_columns(conn: sqlite3.Connection, table: str) -> list[tuple[str, ...]]:
    keys: list[tuple[str, ...]] = []
    for row in conn.execute(f'PRAGMA index_list("{table}")').fetchall():
        if not int(row[2]):
            continue
        keys.append(
            tuple(
                str(info[2])
                for info in conn.execute(f'PRAGMA index_info("{row[1]}")').fetchall()
                if info[2] is not None
            )
        )
    return keys


def test_restated_filing_inserts_instead_of_overwriting_the_original(tmp_path):
    engine = _table_engine(tmp_path / "restatement.db")

    _upsert(engine, FIRST_FILING, **ORIGINAL)
    _upsert(engine, RESTATED_FILING, **RESTATED)

    rows = _rows(engine)
    assert len(rows) == 2, "a restatement must not replace the filing it restates"
    assert [str(row[2]) for row in rows] == ["2026-02-10 09:30:00.000000", "2026-08-14 18:05:00.000000"]
    assert [row[3] for row in rows] == [ORIGINAL["promoter_pct"], RESTATED["promoter_pct"]]
    assert [row[4] for row in rows] == [ORIGINAL["promoter_pledged_pct"], RESTATED["promoter_pledged_pct"]]
    engine.dispose()


def test_refiling_at_the_same_revision_upserts_instead_of_duplicating(tmp_path):
    engine = _table_engine(tmp_path / "same-revision.db")

    _upsert(engine, FIRST_FILING, **ORIGINAL)
    _upsert(engine, RESTATED_FILING, **RESTATED)
    _upsert(engine, FIRST_FILING, promoter_pct=0.5, promoter_pledged_pct=0.004)

    rows = _rows(engine)
    assert len(rows) == 2
    assert [row[3] for row in rows] == [0.5, RESTATED["promoter_pct"]]
    engine.dispose()


def test_symbol_period_alone_is_no_longer_a_conflict_target(tmp_path):
    """The overwrite-capable arbiter is gone from the schema, not just unused.

    An ON CONFLICT (symbol, period_ended) writer is exactly the shape that
    silently destroyed history; SQLite refuses it because no unique constraint
    covers that pair any more.
    """

    engine = _table_engine(tmp_path / "stale-arbiter.db")
    _upsert(engine, FIRST_FILING, **ORIGINAL)

    with pytest.raises(OperationalError) as exc_info:
        with engine.begin() as conn:
            conn.execute(
                sqlite_insert(NSEShareholdingPattern)
                .values(symbol=SYMBOL, period_ended=PERIOD, revision_date=RESTATED_FILING, **RESTATED)
                .on_conflict_do_update(
                    index_elements=["symbol", "period_ended"],
                    set_={"promoter_pct": RESTATED["promoter_pct"]},
                )
            )
    assert "does not match any PRIMARY KEY or UNIQUE constraint" in str(exc_info.value)
    assert len(_rows(engine)) == 1
    engine.dispose()


def test_revision_date_is_not_null_and_defaults_to_an_ingest_stamp(tmp_path):
    engine = _table_engine(tmp_path / "default.db")

    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO nse_shareholding_patterns "
            "(symbol, period_ended, promoter_pct) VALUES ('TCS', '2025-03-31', 0.44)"
        )

    rows = _rows(engine)
    assert len(rows) == 1
    assert rows[0][2] is not None, "a defaulted revision must not be NULL"
    engine.dispose()


_LEGACY_DDL = """
CREATE TABLE nse_shareholding_patterns (
    id INTEGER NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    period_ended VARCHAR(20) NOT NULL,
    promoter_pct FLOAT NOT NULL,
    promoter_pledged_pct FLOAT,
    fii_pct FLOAT,
    dii_pct FLOAT,
    public_pct FLOAT,
    updated_on DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    CONSTRAINT uq_shp_symbol_period UNIQUE (symbol, period_ended)
);
INSERT INTO nse_shareholding_patterns
    (id, symbol, period_ended, promoter_pct, promoter_pledged_pct, fii_pct, dii_pct, public_pct)
VALUES
    (1, 'RELIANCE', '2024-12-31', 0.5123, 0.004, 0.22, 0.13, 0.14);
"""


def _legacy_database(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(_LEGACY_DDL)
    conn.commit()
    conn.close()


def test_migration_adds_the_revision_dimension_and_keeps_existing_rows(tmp_path):
    db = tmp_path / "legacy.db"
    _legacy_database(db)

    result = apply_migrations(db)

    assert result.applied is True
    assert result.previous_version == 0
    assert result.current_version == LATEST_SCHEMA_VERSION
    assert result.backup_path is not None and result.backup_path.is_file()

    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert conn.execute("SELECT COUNT(*) FROM nse_shareholding_patterns").fetchone()[0] == 1
    row = conn.execute(
        "SELECT symbol, period_ended, revision_date, promoter_pct, promoter_pledged_pct, "
        "fii_pct, dii_pct, public_pct FROM nse_shareholding_patterns"
    ).fetchone()
    assert row[0] == SYMBOL and row[1] == PERIOD
    assert row[2] is not None, "the pre-existing filing must get a revision, never NULL"
    assert row[3:] == (0.5123, 0.004, 0.22, 0.13, 0.14)

    keys = _unique_index_columns(conn, "nse_shareholding_patterns")
    assert ("symbol", "period_ended", "revision_date") in keys
    assert ("symbol", "period_ended") not in keys, "the overwrite-capable key must be gone"

    # The migrated table accepts the restatement the old schema would reject.
    conn.execute(
        "INSERT INTO nse_shareholding_patterns "
        "(symbol, period_ended, revision_date, promoter_pct) "
        "VALUES ('RELIANCE', '2024-12-31', '2026-08-14 18:05:00', 0.4801)"
    )
    assert conn.execute("SELECT COUNT(*) FROM nse_shareholding_patterns").fetchone()[0] == 2
    conn.close()

    # Replay is a verified no-op: no second backup, no second mutation.
    second = apply_migrations(db)
    assert second.applied is False
    assert second.backup_path is None
    assert len(list((tmp_path / "backups").glob("daisy_backup_*.db"))) == 1


def _duplicate_legacy_database(path: Path) -> None:
    """Legacy table with no unique key and two filings for the same quarter."""

    conn = sqlite3.connect(path)
    conn.executescript(
        _LEGACY_DDL.replace(
            "    PRIMARY KEY (id),\n"
            "    CONSTRAINT uq_shp_symbol_period UNIQUE (symbol, period_ended)\n",
            "    PRIMARY KEY (id)\n",
        )
    )
    conn.execute(
        "INSERT INTO nse_shareholding_patterns "
        "(id, symbol, period_ended, promoter_pct, promoter_pledged_pct, fii_pct, dii_pct, public_pct) "
        "VALUES (2, 'RELIANCE', '2024-12-31', 0.4900, 0.004, 0.22, 0.13, 0.14)"
    )
    conn.commit()
    conn.close()


def test_legacy_duplicates_block_instead_of_being_collapsed(tmp_path):
    """The added key column is stamped identically on every row, so two filings
    of one quarter stay duplicates of the new key and block the migration rather
    than resolving into one row."""

    db = tmp_path / "duplicates.db"
    _duplicate_legacy_database(db)
    before = db.read_bytes()

    with pytest.raises(MigrationBlocked) as exc_info:
        apply_migrations(db)

    assert [issue["table"] for issue in exc_info.value.issues] == ["nse_shareholding_patterns"]
    assert exc_info.value.issues[0]["kind"] == "duplicate_natural_key"
    assert exc_info.value.backup_path is not None and exc_info.value.backup_path.is_file()

    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM nse_shareholding_patterns").fetchone()[0] == 2
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()
    assert db.read_bytes() == before


def _revision_contract(path: Path, table: str) -> tuple[dict[str, tuple[int, int]], set]:
    """Nullability per column plus every unique key the table enforces."""

    conn = sqlite3.connect(path)
    columns = {
        str(row[1]): (int(row[3]), int(row[5]))
        for row in conn.execute(f'PRAGMA table_info("{table}")')
    }
    keys = set(_unique_index_columns(conn, table))
    conn.close()
    return columns, keys


def test_fresh_and_migrated_shareholding_tables_agree(tmp_path):
    fresh = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{fresh.as_posix()}")
    NSEShareholdingPattern.__table__.create(engine)
    engine.dispose()

    migrated = tmp_path / "migrated.db"
    _legacy_database(migrated)
    apply_migrations(migrated)

    for path in (fresh, migrated):
        columns, keys = _revision_contract(path, "nse_shareholding_patterns")
        assert columns["revision_date"][0] == 1, f"{path.name}: revision_date must be NOT NULL"
        assert ("symbol", "period_ended", "revision_date") in keys

    assert _revision_contract(migrated, "nse_shareholding_patterns") == _revision_contract(
        fresh, "nse_shareholding_patterns"
    )