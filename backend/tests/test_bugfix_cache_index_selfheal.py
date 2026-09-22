"""P1: init_db self-heals legacy analytics_cache unique index.

Legacy DBs created before the AnalyticsCache UniqueConstraint lack
UNIQUE(ticker, metric_name) (create_all never alters existing tables), so
CacheService's ON CONFLICT (ticker, metric_name) upsert fails at runtime.
The real daisy.db only carried a 3-col unique index (ticker, metric_name,
calculation_date), which does not satisfy that ON CONFLICT.

Gates the init_db heal: dedupe keeping MAX(id) per (ticker, metric_name),
then CREATE UNIQUE INDEX IF NOT EXISTS uq_analytics_cache_ticker_metric.
Hermetic — temp sqlite file, never backend/data/daisy.db.
"""

import sqlite3
from datetime import datetime

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.db.database as db_mod
from app.db.database import init_db
from app.services.cache_service import CacheService

# Legacy table exactly as pre-constraint DBs have it: PK id, non-unique
# (ticker, metric_name) index, and the old 3-col unique index that does NOT
# match the upsert's ON CONFLICT columns.
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
    # duplicate (ticker, metric_name): legal under the 3-col index
    "INSERT INTO analytics_cache (id, ticker, metric_name, metric_value,"
    " calculation_date, expires_at, model_params)"
    " VALUES (1, 'AAPL', 'sharpe', 1.0, '2026-01-01', '2030-01-01', '{}')",
    "INSERT INTO analytics_cache (id, ticker, metric_name, metric_value,"
    " calculation_date, expires_at, model_params)"
    " VALUES (2, 'AAPL', 'sharpe', 2.0, '2026-02-01', '2030-01-01', '{}')",
    "INSERT INTO analytics_cache (id, ticker, metric_name, metric_value,"
    " calculation_date, expires_at, model_params)"
    " VALUES (3, 'MSFT', 'beta', 3.0, '2026-01-01', '2030-01-01', '{}')",
]


@pytest_asyncio.fixture
async def healed_legacy_engine(tmp_path, monkeypatch):
    """Legacy-simulated temp DB run through the real init_db path."""
    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_file)
    for stmt in LEGACY_DDL:
        conn.execute(stmt)
    conn.commit()
    conn.close()

    url = f"sqlite+aiosqlite:///{db_file.as_posix()}"
    engine = create_async_engine(url, echo=False)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod.settings, "database_url", url)
    await init_db()
    yield engine
    await engine.dispose()


async def test_unique_index_exists_after_init(healed_legacy_engine):
    async with healed_legacy_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT sql FROM sqlite_master"
                    " WHERE type='index' AND name='uq_analytics_cache_ticker_metric'"
                )
            )
        ).fetchone()
        assert row is not None, "uq_analytics_cache_ticker_metric not created by init_db"
        assert "UNIQUE" in row[0].upper()
        cols = [
            r[2]
            for r in await conn.execute(
                text("PRAGMA index_info(uq_analytics_cache_ticker_metric)")
            )
        ]
        assert cols == ["ticker", "metric_name"]


async def test_duplicates_deduped_keeping_max_id(healed_legacy_engine):
    async with healed_legacy_engine.connect() as conn:
        dupes = (
            await conn.execute(
                text(
                    "SELECT ticker, metric_name, COUNT(*) FROM analytics_cache"
                    " GROUP BY ticker, metric_name HAVING COUNT(*) > 1"
                )
            )
        ).fetchall()
        assert dupes == [], f"duplicate cache keys survived: {dupes}"
        # MAX(id) kept: row 2 (value 2.0) wins over row 1 (value 1.0)
        value = (
            await conn.execute(
                text(
                    "SELECT metric_value FROM analytics_cache"
                    " WHERE ticker='AAPL' AND metric_name='sharpe'"
                )
            )
        ).scalar()
        assert value == 2.0, f"expected MAX(id) row kept, got value {value}"
        msft = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM analytics_cache"
                    " WHERE ticker='MSFT' AND metric_name='beta'"
                )
            )
        ).scalar()
        assert msft == 1


async def test_upsert_succeeds_after_selfheal(healed_legacy_engine):
    session_factory = async_sessionmaker(
        healed_legacy_engine, expire_on_commit=False
    )
    async with session_factory() as session:
        svc = CacheService(session)
        # set_cached_analytics swallows exceptions (logs + rolls back), so
        # success is asserted by the row actually taking the new value.
        await svc.set_cached_analytics(
            "AAPL", "sharpe", 9.0, datetime(2026, 3, 1), {"v": 9}
        )
        rows = (
            await session.execute(
                text(
                    "SELECT metric_value FROM analytics_cache"
                    " WHERE ticker='AAPL' AND metric_name='sharpe'"
                )
            )
        ).fetchall()
        assert len(rows) == 1, f"upsert created {len(rows)} rows"
        assert rows[0][0] == 9.0, (
            "upsert did not update the row — ON CONFLICT likely failed "
            "(unique index missing?)"
        )
