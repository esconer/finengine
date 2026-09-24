"""
Database configuration and initialization for Daisy Risk Engine
"""

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy import event
from sqlalchemy.engine import make_url
from pathlib import Path
from typing import AsyncGenerator

from app.config import settings


# Base class for SQLAlchemy models
Base = declarative_base()

# Async database engine. SQL echo only in a development environment AND with
# debug on: debug alone must not stream every statement to stdout (audit B7/O1).
engine = create_async_engine(
    settings.database_url,
    echo=bool(settings.debug and settings.environment == "development"),
    pool_pre_ping=True,
)

# Session factory
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


def ensure_sqlite_dir(database_url: str) -> None:
    """Create the parent directory of a file-based sqlite DB URL.

    No-op for in-memory sqlite, non-sqlite dialects, and `file:` URIs.
    Must run BEFORE create_all/connect: sqlite does not create missing
    directories (`OperationalError: unable to open database file`).
    """
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return
    database = url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return
    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)


async def init_db() -> None:
    """Apply versioned migrations, then create any missing current tables."""
    # Register all models on Base.metadata so init_db works even when called
    # without routers having been imported. create_all remains useful for new
    # tables, but is no longer treated as an existing-schema migration.
    from app.models import database as _models  # noqa: F401
    from migrations.schema_version import (
        apply_migrations,
        resolve_sqlite_database_path,
    )

    ensure_sqlite_dir(settings.database_url)
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite":
        database = url.database or ""
        is_memory = database == ":memory:" or "mode=memory" in (url.query.get("uri", "") or "")
        if not is_memory:
            db_path = resolve_sqlite_database_path(settings.database_url)
            # SQLite backup/table rebuilds are synchronous. Keep startup async
            # without blocking the event loop and fail closed on blocked data.
            await asyncio.to_thread(apply_migrations, db_path)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Get database session dependency for FastAPI
    """
    async with SessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            raise e
        finally:
            await session.close()


@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    Set SQLite pragmas for better performance and data integrity.

    IMPORTANT: with the aiosqlite dialect the connection arrives as
    SQLAlchemy's AsyncAdapt_aiosqlite_connection, NOT sqlite3.Connection.
    The previous isinstance(dbapi_connection, sqlite3.Connection) guard never
    matched, so this whole block silently never ran (journal_mode stayed
    'delete', busy_timeout stayed at the 5s sqlite default). The adapter's
    synchronous execute() applies pragmas correctly — do not restore the
    isinstance check.
    """
    dbapi_connection.execute("PRAGMA foreign_keys=ON")
    dbapi_connection.execute("PRAGMA journal_mode=WAL")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")
    dbapi_connection.execute("PRAGMA temp_store=memory")
    dbapi_connection.execute("PRAGMA mmap_size=268435456")  # 256MB
    # WAL permits one writer + many readers, but the dashboard fires many
    # parallel requests that all write (price upserts, fetch logs, analytics
    # cache). Writers still queue on the single write lock; without a busy
    # timeout they fail with "database is locked" after sqlite's 5s default
    # (15 dropped stores in one 20s burst on 2026-09-06). Wait up to 30s.
    dbapi_connection.execute("PRAGMA busy_timeout=30000")


# For manual database operations
async def create_tables():
    """Create database tables"""
    ensure_sqlite_dir(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables():
    """Drop database tables (for testing)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def close_db_connections():
    """Close database connections"""
    await engine.dispose()