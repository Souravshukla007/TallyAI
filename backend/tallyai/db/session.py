"""
Async SQLAlchemy engine and session factory for TallyAI.

Usage (FastAPI dependency injection):

    from tallyai.db.session import get_db
    from sqlalchemy.ext.asyncio import AsyncSession

    @app.get("/example")
    async def example(db: AsyncSession = Depends(get_db)):
        ...
"""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# DATABASE_URL must use an async-compatible driver scheme, e.g.:
#   postgresql+asyncpg://user:password@host/dbname
#   sqlite+aiosqlite:///./test.db
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./tallyai.db")

engine = create_async_engine(
    DATABASE_URL,
    # Echo SQL statements in debug builds; set DATABASE_ECHO=false in production.
    echo=os.getenv("DATABASE_ECHO", "false").lower() == "true",
    # Pool settings are only meaningful for server-side databases.
    # SQLite / aiosqlite ignores them safely.
    pool_pre_ping=True,
)

# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Async generator that yields a database session and closes it afterwards.

    Intended for use as a FastAPI ``Depends`` dependency::

        async def my_route(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
