"""Safe versioned convergence for legacy analytics_cache schemas.

Duplicate-free legacy databases gain the current unique key.  Databases with
conflicting cache rows are blocked with a backup and retain every row; cache
repair must never silently discard user-visible data.
"""

import sqlite3
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.database as db_mod
from app.db.database import init_db
from app.services.cache_service import CacheService
from migrations.schema_version import MigrationBlocked

LEGACY_DDL = [
    "CREATE TABLE analytics_cache ("
    "id INTEGER NOT NULL, "
    "ticker VARCHAR(20) NOT NULL, "
    "metric_name VARCHAR(50) NOT NULL, "
    "metric_value FLOAT NOT NULL, "
    "calculation_date DATETIME NOT NULL, "
    "calculated_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
    "expires_at DATETIME NOT NULL, "
    "model_params JSON, "
    "PRIMARY KEY (id))",
    "CREATE INDEX ix_ticker_metric ON analytics_cache (ticker, metric_name)",
    "CREATE UNIQUE INDEX idx_analytics_cache_unique "
    "ON analytics_cache(ticker, metric_name, calculation_date)",
    "INSERT INTO analytics_cache (id, ticker, metric_name, metric_value,"
    " calculation_date, expires_at, model_params)"
    " VALUES (1, 'AAPL', 'sharpe', 1.0, '2026-01-01', '2030-01-01', '{}')",
    "INSERT INTO analytics_cache (id, ticker, metric_name, metric_value,"
    " calculation_date, expires_at, model_params)"
    " VALUES (3, 'MSFT', 'beta', 3.0, '2026-01-01', '2030-01-01', '{}')",
]


def _legacy_db(path, *, duplicate: bool = False) -> None:
    conn = sqlite3.connect(path)
    for statement in LEGACY_DDL:
        conn.execute(statement)
    if duplicate:
        conn.execute(
            "INSERT INTO analytics_cache (id, ticker, metric_name, metric_value,"
            " calculation_date, expires_at, model_params)"
            " VALUES (2, 'AAPL', 'sharpe', 2.0, '2026-02-01', '2030-01-01', '{}')"
        )
    conn.commit()
    conn.close()


@pytest_asyncio.fixture
async def healed_legacy_engine(tmp_path, monkeypatch):
    db_file = tmp_path / "legacy.db"
    _legacy_db(db_file)
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    engine = create_async_engine(url, echo=False)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod.settings, "database_url", url)
    await init_db()
    yield engine
    await engine.dispose()


async def test_unique_index_exists_after_init(healed_legacy_engine):
    async with healed_legacy_engine.connect() as conn:
        indexes = (
            await conn.execute(
                text("PRAGMA index_list('analytics_cache')")
            )
        ).all()
        matching = []
        for index in indexes:
            name = index[1]
            if not index[2]:
                continue
            cols = [row[2] for row in (await conn.execute(text(f'PRAGMA index_info("{name}")'))).all()]
            if cols == ["ticker", "metric_name"]:
                matching.append(name)
        assert matching, "no UNIQUE(ticker, metric_name) index after migration"


async def test_existing_rows_are_preserved(healed_legacy_engine):
    async with healed_legacy_engine.connect() as conn:
        assert (await conn.execute(text("SELECT COUNT(*) FROM analytics_cache"))).scalar() == 2
        assert (await conn.execute(text("PRAGMA user_version"))).scalar() == 1


async def test_upsert_succeeds_after_migration(healed_legacy_engine):
    session_factory = async_sessionmaker(healed_legacy_engine, expire_on_commit=False)
    async with session_factory() as session:
        service = CacheService(session)
        await service.set_cached_analytics(
            "AAPL", "sharpe", 9.0, datetime(2026, 3, 1), {"v": 9}
        )
        rows = (
            await session.execute(
                text(
                    "SELECT metric_value FROM analytics_cache "
                    "WHERE ticker='AAPL' AND metric_name='sharpe'"
                )
            )
        ).all()
        assert rows == [(9.0,)]


async def test_duplicate_cache_rows_block_safely_and_keep_backup(tmp_path, monkeypatch):
    db_file = tmp_path / "duplicates.db"
    _legacy_db(db_file, duplicate=True)
    before = db_file.read_bytes()
    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    engine = create_async_engine(url, echo=False)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod.settings, "database_url", url)
    try:
        with pytest.raises(MigrationBlocked):
            await init_db()
    finally:
        await engine.dispose()

    conn = sqlite3.connect(db_file)
    assert conn.execute("SELECT COUNT(*) FROM analytics_cache").fetchone()[0] == 3
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()
    assert db_file.read_bytes() == before
    assert len(list((tmp_path / "backups").glob("daisy_backup_*.db"))) == 1
