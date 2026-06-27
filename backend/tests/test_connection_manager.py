"""
Tests for ConnectionManager (Req 1.3, 1.6, 1.7).

All asyncpg.connect calls are mocked so no real Postgres is needed.

Covers:
  - Valid read-only credentials → {"ok": True, "connection_id": ..., "read_only": True}
  - Write-capable credentials   → {"ok": False, "error": "disallowed_privileges", "privileges": [...]}
  - Privilege detection failure → {"ok": False, "error": "privilege_detection_failed"}
  - Connection refused          → {"ok": False, "error": "connection_failed"} AND no TenantConnection persisted
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from tallyai.db.models import TenantConnection
from tallyai.services.connection_manager import ConnectionManager

os.environ.setdefault("SECRET_KEY", "test-secret-for-unit-tests")

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

TENANT = "tenant-test"
HOST = "localhost"
PORT = 5432
DATABASE = "testdb"
ROLE = "readonly_role"
CREDS = {"user": "readonly_role", "password": "testpass"}


def _make_mock_conn(
    is_superuser: str = "off",
    db_create: bool = False,
    schema_create: bool = False,
) -> AsyncMock:
    """Build a mock asyncpg connection whose fetchrow returns controlled values."""
    conn = AsyncMock()
    conn.is_closed.return_value = False

    async def fetchrow(sql: str):
        row = MagicMock()
        if "is_superuser" in sql:
            row.__getitem__ = MagicMock(return_value=is_superuser)
        elif "has_database_privilege" in sql:
            row.__getitem__ = MagicMock(return_value=db_create)
        elif "has_schema_privilege" in sql:
            row.__getitem__ = MagicMock(return_value=schema_create)
        else:
            row.__getitem__ = MagicMock(return_value=None)
        return row

    conn.fetchrow = fetchrow
    conn.close = AsyncMock()
    return conn


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_connection_read_only_success(db_session):
    """Valid read-only credentials should persist a TenantConnection and return ok=True."""
    mock_conn = _make_mock_conn(is_superuser="off", db_create=False, schema_create=False)

    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
        manager = ConnectionManager()
        result = await manager.create_connection(
            host=HOST,
            port=PORT,
            database=DATABASE,
            role=ROLE,
            credentials=CREDS,
            tenant_id=TENANT,
            db=db_session,
        )

    assert result["ok"] is True
    assert "connection_id" in result
    assert result["read_only"] is True

    # Verify TenantConnection was persisted.
    rows = await db_session.execute(
        select(TenantConnection).where(TenantConnection.tenant_id == TENANT)
    )
    tc = rows.scalars().first()
    assert tc is not None, "TenantConnection must be persisted on success"
    assert tc.connection_id == result["connection_id"]
    assert tc.host == HOST
    assert tc.database == DATABASE


@pytest.mark.asyncio
async def test_create_connection_superuser_rejected(db_session):
    """is_superuser=on must be rejected with disallowed_privileges (Req 1.6)."""
    mock_conn = _make_mock_conn(is_superuser="on", db_create=False, schema_create=False)

    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
        manager = ConnectionManager()
        result = await manager.create_connection(
            host=HOST, port=PORT, database=DATABASE,
            role=ROLE, credentials=CREDS, tenant_id=TENANT, db=db_session,
        )

    assert result["ok"] is False
    assert result["error"] == "disallowed_privileges"
    assert "is_superuser" in result["privileges"]

    # No TenantConnection should be persisted.
    rows = await db_session.execute(
        select(TenantConnection).where(TenantConnection.tenant_id == TENANT)
    )
    assert rows.scalars().first() is None


@pytest.mark.asyncio
async def test_create_connection_db_create_privilege_rejected(db_session):
    """has_database_privilege CREATE=true must be rejected (Req 1.6)."""
    mock_conn = _make_mock_conn(is_superuser="off", db_create=True, schema_create=False)

    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
        manager = ConnectionManager()
        result = await manager.create_connection(
            host=HOST, port=PORT, database=DATABASE,
            role=ROLE, credentials=CREDS, tenant_id=TENANT, db=db_session,
        )

    assert result["ok"] is False
    assert result["error"] == "disallowed_privileges"
    assert "database_create" in result["privileges"]


@pytest.mark.asyncio
async def test_create_connection_schema_create_privilege_rejected(db_session):
    """has_schema_privilege CREATE=true must be rejected (Req 1.6)."""
    mock_conn = _make_mock_conn(is_superuser="off", db_create=False, schema_create=True)

    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
        manager = ConnectionManager()
        result = await manager.create_connection(
            host=HOST, port=PORT, database=DATABASE,
            role=ROLE, credentials=CREDS, tenant_id=TENANT, db=db_session,
        )

    assert result["ok"] is False
    assert result["error"] == "disallowed_privileges"
    assert "schema_create" in result["privileges"]


@pytest.mark.asyncio
async def test_create_connection_all_privileges_listed(db_session):
    """All disallowed privileges must appear in the error list (Req 1.6)."""
    mock_conn = _make_mock_conn(is_superuser="on", db_create=True, schema_create=True)

    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
        manager = ConnectionManager()
        result = await manager.create_connection(
            host=HOST, port=PORT, database=DATABASE,
            role=ROLE, credentials=CREDS, tenant_id=TENANT, db=db_session,
        )

    assert result["ok"] is False
    assert result["error"] == "disallowed_privileges"
    assert set(result["privileges"]) == {"is_superuser", "database_create", "schema_create"}


@pytest.mark.asyncio
async def test_create_connection_privilege_detection_exception(db_session):
    """If privilege detection raises, reject with privilege_detection_failed (Req 1.7)."""
    conn = AsyncMock()
    conn.is_closed.return_value = False
    conn.close = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=Exception("pg error"))

    with patch("asyncpg.connect", new=AsyncMock(return_value=conn)):
        manager = ConnectionManager()
        result = await manager.create_connection(
            host=HOST, port=PORT, database=DATABASE,
            role=ROLE, credentials=CREDS, tenant_id=TENANT, db=db_session,
        )

    assert result["ok"] is False
    assert result["error"] == "privilege_detection_failed"
    assert "detail" in result

    # No TenantConnection should be persisted.
    rows = await db_session.execute(
        select(TenantConnection).where(TenantConnection.tenant_id == TENANT)
    )
    assert rows.scalars().first() is None


@pytest.mark.asyncio
async def test_create_connection_connection_refused(db_session):
    """Connection failure must return connection_failed and persist NO TenantConnection (Req 1.3)."""
    with patch(
        "asyncpg.connect",
        new=AsyncMock(side_effect=OSError("Connection refused")),
    ):
        manager = ConnectionManager()
        result = await manager.create_connection(
            host=HOST, port=PORT, database=DATABASE,
            role=ROLE, credentials=CREDS, tenant_id=TENANT, db=db_session,
        )

    assert result["ok"] is False
    assert result["error"] == "connection_failed"
    assert "Connection refused" in result["detail"]

    # Req 1.3 — no active connection persisted.
    rows = await db_session.execute(
        select(TenantConnection).where(TenantConnection.tenant_id == TENANT)
    )
    assert rows.scalars().first() is None, (
        "No TenantConnection must be persisted after a non-privilege connection failure (Req 1.3)"
    )


@pytest.mark.asyncio
async def test_test_connection_read_only(db_session):
    """test_connection() should return ok=True for a read-only re-check."""
    # First create a valid connection.
    mock_conn = _make_mock_conn(is_superuser="off", db_create=False, schema_create=False)
    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
        manager = ConnectionManager()
        create_result = await manager.create_connection(
            host=HOST, port=PORT, database=DATABASE,
            role=ROLE, credentials=CREDS, tenant_id=TENANT, db=db_session,
        )

    assert create_result["ok"] is True
    connection_id = create_result["connection_id"]

    # Now test it.
    mock_conn2 = _make_mock_conn(is_superuser="off", db_create=False, schema_create=False)
    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn2)):
        test_result = await manager.test_connection(connection_id, TENANT, db_session)

    assert test_result["ok"] is True
    assert test_result["reason"] is None


@pytest.mark.asyncio
async def test_test_connection_unknown_returns_false(db_session):
    """test_connection() for an unknown connection_id must return ok=False."""
    manager = ConnectionManager()
    result = await manager.test_connection("nonexistent-id", TENANT, db_session)
    assert result["ok"] is False
    assert result["reason"] is not None
