"""Agent D isolated migration, constraint, and backup regressions."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.db.database import Base
from app.models.database import PortfolioPosition, StockTimeseries
from migrations.schema_version import (
    LATEST_SCHEMA_VERSION,
    MigrationBlocked,
    apply_migrations,
    downgrade_database,
)
from migrations.schema_version import main as migration_main
from migrations.sqlite_backup import backup_database, restore_database, verify_database


def _legacy_database(path: Path, *, duplicate_ticker: bool = False, invalid_ohlc: bool = False) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE portfolio_positions (
            id INTEGER PRIMARY KEY,
            ticker TEXT,
            weight REAL,
            market_value REAL DEFAULT 0.0,
            sector TEXT,
            industry TEXT
        );
        CREATE TABLE stock_timeseries (
            id INTEGER PRIMARY KEY,
            ticker TEXT,
            date DATETIME,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            adj_close REAL,
            volume INTEGER
        );
        INSERT INTO portfolio_positions
            (id, ticker, weight, market_value, sector, industry)
        VALUES
            (1, 'AAPL', 1.0, 100.0, 'Technology', NULL);
        INSERT INTO stock_timeseries
            (id, ticker, date, open, high, low, close, adj_close, volume)
        VALUES
            (1, 'AAPL', '2025-01-01', 10, 11, 9, 10, 10, 100);
        """
    )
    if duplicate_ticker:
        conn.execute(
            "INSERT INTO portfolio_positions "
            "(id, ticker, weight, market_value, sector, industry) "
            "VALUES (2, 'aapl', 0.5, 50, 'Technology', 'Hardware')"
        )
    if invalid_ohlc:
        conn.execute(
            "INSERT INTO stock_timeseries "
            "(id, ticker, date, open, high, low, close, adj_close, volume) "
            "VALUES (2, 'MSFT', '2025-01-01', -1, 11, 9, 10, 10, 100)"
        )
    conn.commit()
    conn.close()


def _table_info(conn: sqlite3.Connection, table: str) -> dict[str, tuple[int, int]]:
    return {
        str(row[1]): (int(row[3]), int(row[5]))
        for row in conn.execute(f'PRAGMA table_info("{table}")')
    }


def test_versioned_migration_converges_legacy_schema_and_backs_up(tmp_path):
    db = tmp_path / "legacy.db"
    _legacy_database(db)

    result = apply_migrations(db)

    assert result.applied is True
    assert result.previous_version == 0
    assert result.current_version == LATEST_SCHEMA_VERSION
    assert result.backup_path is not None and result.backup_path.is_file()
    assert result.mapped_null_metadata == 1

    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    portfolio = _table_info(conn, "portfolio_positions")
    assert all(portfolio[column][0] == 1 for column in ("ticker", "weight", "quantity", "buy_price", "sector", "industry"))
    assert conn.execute("SELECT quantity, buy_price, industry FROM portfolio_positions").fetchone() == (0.0, 0.0, "Unknown")
    assert conn.execute("SELECT COUNT(*) FROM stock_timeseries").fetchone()[0] == 1
    conn.close()

    # A second startup is a verified no-op and does not create another backup.
    second = apply_migrations(db)
    assert second.applied is False
    assert second.backup_path is None
    assert len(list((tmp_path / "backups").glob("daisy_backup_*.db"))) == 1


def _owned_schema_contract(path: Path, table: str) -> tuple[set[tuple[str, int, int]], set[tuple[str, ...]], set[str]]:
    conn = sqlite3.connect(path)
    columns = {
        str(row[1]): (int(row[3]), int(row[5]))
        for row in conn.execute(f'PRAGMA table_info("{table}")')
    }
    unique_keys: set[tuple[str, ...]] = set()
    for index in conn.execute(f'PRAGMA index_list("{table}")').fetchall():
        if not int(index[2]):
            continue
        name = str(index[1])
        key = tuple(
            str(row[2])
            for row in conn.execute(f'PRAGMA index_info("{name}")').fetchall()
            if row[2] is not None
        )
        unique_keys.add(key)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    sql = str(row[0]) if row else ""
    checks = {
        part.split()[0]
        for part in sql.split("CONSTRAINT ")[1:]
        if part.lstrip().startswith("ck_")
    }
    conn.close()
    return set(columns.items()), unique_keys, checks


def test_fresh_and_migrated_owned_tables_have_same_integrity_contract(tmp_path):
    fresh = tmp_path / "fresh.db"
    engine = create_engine(f"sqlite:///{fresh.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()

    migrated = tmp_path / "migrated.db"
    _legacy_database(migrated)
    apply_migrations(migrated)

    for table in ("portfolio_positions", "stock_timeseries"):
        assert _owned_schema_contract(migrated, table) == _owned_schema_contract(fresh, table)


def test_duplicate_ticker_blocks_without_deletion_or_version_change(tmp_path):
    db = tmp_path / "duplicates.db"
    _legacy_database(db, duplicate_ticker=True)
    before = db.read_bytes()

    with pytest.raises(MigrationBlocked) as exc_info:
        apply_migrations(db)

    assert exc_info.value.issues
    assert exc_info.value.issues[0]["kind"] in {"duplicate_or_empty_ticker", "duplicate_natural_key"}
    assert exc_info.value.backup_path is not None and exc_info.value.backup_path.is_file()
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM portfolio_positions").fetchone()[0] == 2
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()
    # A blocked migration is read-only; the only new artifact is its backup.
    assert db.read_bytes() == before


def test_migration_cli_returns_nonzero_on_blocked_data(tmp_path):
    db = tmp_path / "cli-duplicates.db"
    _legacy_database(db, duplicate_ticker=True)
    assert migration_main(["--db", str(db)]) == 1


def test_invalid_ohlc_blocks_without_destructive_repair(tmp_path):
    db = tmp_path / "invalid.db"
    _legacy_database(db, invalid_ohlc=True)

    with pytest.raises(MigrationBlocked) as exc_info:
        apply_migrations(db)

    assert any(issue["kind"] == "invalid_ohlc" for issue in exc_info.value.issues)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM stock_timeseries").fetchone()[0] == 2
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()


def test_migration_is_reversible_without_losing_rows(tmp_path):
    db = tmp_path / "roundtrip.db"
    _legacy_database(db)
    apply_migrations(db)

    result = downgrade_database(db)

    assert result.applied is True
    conn = sqlite3.connect(db)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    assert conn.execute("SELECT COUNT(*) FROM portfolio_positions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM stock_timeseries").fetchone()[0] == 1
    conn.close()
    assert result.backup_path is not None and result.backup_path.is_file()


def test_sqlite_backup_api_restores_counts_and_quick_check(tmp_path):
    source = tmp_path / "source.db"
    conn = sqlite3.connect(source)
    conn.execute("CREATE TABLE holdings (ticker TEXT, quantity REAL)")
    conn.executemany("INSERT INTO holdings VALUES (?, ?)", [("AAPL", 2), ("MSFT", 3)])
    conn.commit()
    conn.close()

    backup = tmp_path / "backups" / "verified.db"
    result = backup_database(source, backup)
    restored = tmp_path / "restored.db"
    restored_result = restore_database(backup, restored)

    assert result["quick_check"] == "ok"
    assert result["table_counts"] == {"holdings": 2}
    assert restored_result["table_counts"] == {"holdings": 2}
    assert verify_database(source, restored)["quick_check"] == "ok"
    conn = sqlite3.connect(restored)
    assert conn.execute("SELECT ticker, quantity FROM holdings ORDER BY ticker").fetchall() == [
        ("AAPL", 2.0),
        ("MSFT", 3.0),
    ]
    conn.close()


async def test_current_models_reject_duplicate_case_variant_and_invalid_ohlc(test_db):
    test_db.add(PortfolioPosition(ticker="AAPL", weight=1.0, sector="Tech", industry="Hardware"))
    await test_db.commit()

    test_db.add(PortfolioPosition(ticker="aapl", weight=1.0, sector="Tech", industry="Hardware"))
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()

    test_db.add(
        StockTimeseries(
            ticker="AAPL",
            date=datetime(2025, 1, 1),
            open=-1,
            high=2,
            low=-2,
            close=1,
            adj_close=1,
            volume=10,
        )
    )
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()

    test_db.add(
        StockTimeseries(
            ticker="AAPL",
            date=datetime(2025, 1, 2),
            open=1,
            high=2,
            low=0.5,
            close=1,
            adj_close=float("inf"),
            volume=10,
        )
    )
    with pytest.raises(IntegrityError):
        await test_db.commit()
    await test_db.rollback()


async def test_portfolio_metadata_nullability_is_enforced(test_db):
    with pytest.raises(IntegrityError):
        await test_db.execute(
            text(
                "INSERT INTO portfolio_positions "
                "(ticker, weight, quantity, buy_price, sector, industry) "
                "VALUES ('MSFT', 1.0, 1.0, 1.0, NULL, 'Software')"
            )
        )
    await test_db.rollback()
