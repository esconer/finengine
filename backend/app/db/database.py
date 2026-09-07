"""
Database configuration and initialization for Daisy Risk Engine
"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy import event
import os
from typing import AsyncGenerator

from app.config import settings


# Base class for SQLAlchemy models
Base = declarative_base()

# Async database engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)

# Session factory
SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_db() -> None:
    """
    Initialize database tables
    """
    async with engine.begin() as conn:
        # Import all models to ensure they're registered
        
        # Create all tables
        await conn.run_sync(Base.metadata.create_all)
    
    # Create data directory if it doesn't exist
    os.makedirs("data", exist_ok=True)


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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_tables():
    """Drop database tables (for testing)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def close_db_connections():
    """Close database connections"""
    await engine.dispose()