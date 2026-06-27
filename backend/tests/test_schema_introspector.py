"""
Tests for SchemaIntrospector (Req 5.1–5.5, 14.2).

asyncpg.connect is mocked so no real Postgres is needed.

Covers:
  - test_introspect_populates_cache: mock asyncpg → CachedSchema persisted,
    get_cached() returns tables
  - test_get_cached_returns_none_for_unknown: unknown connection_id → None
  - test_refresh_failure_retains_cache: first introspect succeeds, then
    refresh with asyncpg raising → old cache unchanged (Req 5.5)
  - test_get_cached_is_tenant_scoped: tenant A cache not visible to tenant B
    (Req 14.2)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from tallyai.db.models import CachedSchema, TenantConnection
from tallyai.services.schema_introspector import SchemaIntrospector

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

TENANT_A = "tenant-alpha"
TENANT_B = "tenant-beta"
HOST = "db.example.com"
PORT = 5432
DATABASE = "mydb"
USER = "readonly"
PASSWORD = "secret"

# Two tables with columns and a FK that mock asyncpg will return
_MOCK_COL_ROWS = [
    {"table_name": "orders", "column_name": "id",          "data_type": "integer",           "is_nullable": "NO"},
    {"table_name": "orders", "column_name": "customer_id", "data_type": "integer",           "is_nullable": "YES"},
    {"table_name": "orders", "column_name": "amount",      "data_type": "numeric",           "is_nullable": "YES"},
    {"table_name": "customers", "column_name": "id",       "data_type": "integer",           "is_nullable": "NO"},
    {"table_name": "customers", "column_name": "name",     "data_type": "character varying", "is_nullable": "NO"},
]

_MOCK_FK_ROWS = [
    {
        "table_name": "orders",
        "column_name": "customer_id",
        "foreign_table_name": "customers",
        "foreign_column_name": "id",
    }
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_conn(col_rows=None, fk_rows=None, raise_on_fetch=False):
    """Return a mock asyncpg connection whose fetch() returns controlled rows."""
    if col_rows is None:
        col_rows = _MOCK_COL_ROWS
    if fk_rows is None:
        fk_rows = _MOCK_FK_ROWS

    conn = AsyncMock()
    conn.close = AsyncMock()

    call_count = 0

    async def fetch(sql: str):
        nonlocal call_count
        if raise_on_fetch:
            raise OSError("Connection refused")
        # First call → columns query, second → FK query
        call_count += 1
        if call_count == 1:
            return [_dict_to_record(r) for r in col_rows]
        return [_dict_to_record(r) for r in fk_rows]

    conn.fetch = fetch
    return conn


def _dict_to_record(d: dict) -> MagicMock:
    """Wrap a plain dict in a MagicMock that supports subscript access."""
    rec = MagicMock()
    rec.__getitem__ = MagicMock(side_effect=lambda k: d[k])
    # Also support .get() if needed
    rec.get = MagicMock(side_effect=lambda k, default=None: d.get(k, default))
    return rec


async def _insert_tenant_connection(db, connection_id: str, tenant_id: str) -> None:
    """Insert a minimal TenantConnection so the FK constraint is satisfied."""
    tc = TenantConnection(
        connection_id=connection_id,
        tenant_id=tenant_id,
        host=HOST,
        port=PORT,
        database=DATABASE,
        role=USER,
        is_active=True,
        schema_version="",
    )
    db.add(tc)
    await db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_introspect_populates_cache(db_session):
    """introspect() should persist a CachedSchema row; get_cached() returns tables."""
    conn_id = "conn-001"
    await _insert_tenant_connection(db_session, conn_id, TENANT_A)

    mock_conn = _make_mock_conn()
    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
        introspector = SchemaIntrospector()
        result = await introspector.introspect(
            conn_id=conn_id,
            tenant_id=TENANT_A,
            host=HOST,
            port=PORT,
            database=DATABASE,
            user=USER,
            password=PASSWORD,
            db=db_session,
        )

    # Return value must include schema_version, tables, introspected_at
    assert "schema_version" in result
    assert "tables" in result
    assert "introspected_at" in result

    tables = result["tables"]
    table_names = {t["name"] for t in tables}
    assert "orders" in table_names
    assert "customers" in table_names

    orders = next(t for t in tables if t["name"] == "orders")
    col_names = [c["name"] for c in orders["columns"]]
    assert "id" in col_names
    assert "customer_id" in col_names

    # FK should be populated
    assert len(orders["foreign_keys"]) == 1
    fk = orders["foreign_keys"][0]
    assert fk["column"] == "customer_id"
    assert fk["references_table"] == "customers"
    assert fk["references_column"] == "id"

    # Verify DB row was persisted
    rows = await db_session.execute(
        select(CachedSchema).where(
            CachedSchema.connection_id == conn_id,
            CachedSchema.tenant_id == TENANT_A,
        )
    )
    db_row = rows.scalars().first()
    assert db_row is not None
    assert db_row.schema_version == result["schema_version"]
    persisted_tables = json.loads(db_row.tables_json)
    assert len(persisted_tables) == 2

    # get_cached() should return the same data
    cached = await introspector.get_cached(conn_id, TENANT_A, db_session)
    assert cached is not None
    assert cached["schema_version"] == result["schema_version"]
    assert len(cached["tables"]) == 2


@pytest.mark.asyncio
async def test_get_cached_returns_none_for_unknown(db_session):
    """get_cached() must return None when no cache row exists (Req 5.3)."""
    introspector = SchemaIntrospector()
    result = await introspector.get_cached("nonexistent-conn", TENANT_A, db_session)
    assert result is None


@pytest.mark.asyncio
async def test_refresh_failure_retains_cache(db_session):
    """On asyncpg failure during refresh, old cached schema must be unchanged (Req 5.5)."""
    conn_id = "conn-002"
    await _insert_tenant_connection(db_session, conn_id, TENANT_A)

    # Step 1: successful introspect
    mock_conn_ok = _make_mock_conn()
    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn_ok)):
        introspector = SchemaIntrospector()
        first_result = await introspector.introspect(
            conn_id=conn_id,
            tenant_id=TENANT_A,
            host=HOST,
            port=PORT,
            database=DATABASE,
            user=USER,
            password=PASSWORD,
            db=db_session,
        )

    original_version = first_result["schema_version"]

    # Step 2: refresh with asyncpg raising an exception
    with patch("asyncpg.connect", new=AsyncMock(side_effect=OSError("Connection refused"))):
        refresh_result = await introspector.refresh(
            conn_id=conn_id,
            tenant_id=TENANT_A,
            host=HOST,
            port=PORT,
            database=DATABASE,
            user=USER,
            password=PASSWORD,
            db=db_session,
        )

    assert refresh_result["refreshed"] is False
    assert "reason" in refresh_result
    assert "Connection refused" in refresh_result["reason"]

    # The cached schema must still be the original
    cached = await introspector.get_cached(conn_id, TENANT_A, db_session)
    assert cached is not None
    assert cached["schema_version"] == original_version, (
        "Cached schema version must be unchanged after a failed refresh (Req 5.5)"
    )


@pytest.mark.asyncio
async def test_get_cached_is_tenant_scoped(db_session):
    """Tenant A's cached schema must not be visible to tenant B (Req 14.2)."""
    conn_id = "conn-003"
    # Insert TenantConnection for TENANT_A only
    await _insert_tenant_connection(db_session, conn_id, TENANT_A)

    mock_conn = _make_mock_conn()
    with patch("asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
        introspector = SchemaIntrospector()
        await introspector.introspect(
            conn_id=conn_id,
            tenant_id=TENANT_A,
            host=HOST,
            port=PORT,
            database=DATABASE,
            user=USER,
            password=PASSWORD,
            db=db_session,
        )

    # TENANT_A should have a cache
    cached_a = await introspector.get_cached(conn_id, TENANT_A, db_session)
    assert cached_a is not None, "Tenant A should have a cached schema"

    # TENANT_B must NOT see TENANT_A's cache
    cached_b = await introspector.get_cached(conn_id, TENANT_B, db_session)
    assert cached_b is None, (
        "Tenant B must not see Tenant A's cached schema (Req 14.2)"
    )
