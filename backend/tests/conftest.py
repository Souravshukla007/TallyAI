"""
Pytest fixtures for TallyAI backend tests.

Provides an in-memory SQLite async engine and a session fixture that
creates all tables before each test and tears them down after.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tallyai.db.models import Base


# ---------------------------------------------------------------------------
# Engine — per-session in-memory SQLite (aiosqlite).
# We use a unique URL per test session so tests are fully isolated.
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def async_engine():
    """Create a fresh in-memory SQLite engine and schema for each test."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        # SQLite in-memory databases vanish when the connection closes, so we
        # must keep at least one connection open for the duration of the test.
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # Create all tables.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop all tables and dispose the engine.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session bound to the in-memory test engine."""
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        bind=async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    async with factory() as session:
        yield session
