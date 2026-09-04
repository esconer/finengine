"""
Database configuration and initialization for Daisy Risk Engine
"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy import event
import os
import sqlite3
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
    Set SQLite pragmas for better performance and data integrity
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA temp_store=memory")
        cursor.execute("PRAGMA mmap_size=268435456")  # 256MB
        cursor.close()


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