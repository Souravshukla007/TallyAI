"""
Tests that every SQLAlchemy model can be created and queried.

Covers: TenantConnection, EncryptedCredential, CachedSchema,
        MetricDefinition, ExecutionLogEntry, HistoryEntry, Trace.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tallyai.db.models import (
    CachedSchema,
    EncryptedCredential,
    ExecutionLogEntry,
    HistoryEntry,
    MetricDefinition,
    TenantConnection,
    Trace,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TENANT_ID = "tenant-001"
USER_ID = "user-001"


def make_connection(**kwargs) -> TenantConnection:
    defaults = dict(
        connection_id=str(uuid.uuid4()),
        tenant_id=TENANT_ID,
        host="localhost",
        port=5432,
        database="mydb",
        role="readonly",
        is_active=True,
        schema_version="v1",
    )
    defaults.update(kwargs)
    return TenantConnection(**defaults)


# ---------------------------------------------------------------------------
# TenantConnection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_connection_create_and_query(db_session: AsyncSession) -> None:
    """TenantConnection can be persisted and retrieved."""
    conn = make_connection()
    db_session.add(conn)
    await db_session.commit()

    result = await db_session.execute(
        select(TenantConnection).where(
            TenantConnection.connection_id == conn.connection_id
        )
    )
    fetched = result.scalar_one()
    assert fetched.host == "localhost"
    assert fetched.port == 5432
    assert fetched.tenant_id == TENANT_ID
    assert fetched.is_active is True


# ---------------------------------------------------------------------------
# EncryptedCredential
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_encrypted_credential_create_and_query(db_session: AsyncSession) -> None:
    """EncryptedCredential stores ciphertext and links to a TenantConnection."""
    conn = make_connection()
    db_session.add(conn)
    await db_session.flush()

    cred = EncryptedCredential(
        connection_id=conn.connection_id,
        tenant_id=TENANT_ID,
        ciphertext=b"encrypted-bytes",
        kms_key_id="kms-key-123",
    )
    db_session.add(cred)
    await db_session.commit()

    result = await db_session.execute(
        select(EncryptedCredential).where(
            EncryptedCredential.connection_id == conn.connection_id
        )
    )
    fetched = result.scalar_one()
    assert fetched.ciphertext == b"encrypted-bytes"
    assert fetched.kms_key_id == "kms-key-123"
    assert fetched.tenant_id == TENANT_ID


# ---------------------------------------------------------------------------
# CachedSchema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cached_schema_create_and_query(db_session: AsyncSession) -> None:
    """CachedSchema stores schema JSON for a connection."""
    conn = make_connection()
    db_session.add(conn)
    await db_session.flush()

    schema = CachedSchema(
        id=str(uuid.uuid4()),
        connection_id=conn.connection_id,
        tenant_id=TENANT_ID,
        schema_version="v1",
        tables_json='[{"name": "users"}]',
    )
    db_session.add(schema)
    await db_session.commit()

    result = await db_session.execute(
        select(CachedSchema).where(
            CachedSchema.connection_id == conn.connection_id
        )
    )
    fetched = result.scalar_one()
    assert fetched.schema_version == "v1"
    assert "users" in fetched.tables_json


# ---------------------------------------------------------------------------
# MetricDefinition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metric_definition_create_and_query(db_session: AsyncSession) -> None:
    """MetricDefinition stores versioned canonical metric definitions."""
    metric = MetricDefinition(
        id=str(uuid.uuid4()),
        name="revenue",
        tenant_id=TENANT_ID,
        formula="SUM(payments.amount)",
        condition="payments.status = 'completed'",
        grain="monthly",
        description="Total completed payment revenue",
        version=1,
        superseded_by=None,
    )
    db_session.add(metric)
    await db_session.commit()

    result = await db_session.execute(
        select(MetricDefinition).where(MetricDefinition.name == "revenue")
    )
    fetched = result.scalar_one()
    assert fetched.formula == "SUM(payments.amount)"
    assert fetched.version == 1
    assert fetched.superseded_by is None
    assert fetched.tenant_id == TENANT_ID


# ---------------------------------------------------------------------------
# ExecutionLogEntry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execution_log_entry_create_and_query(db_session: AsyncSession) -> None:
    """ExecutionLogEntry records the exact SQL and execution metadata."""
    conn_id = str(uuid.uuid4())
    entry = ExecutionLogEntry(
        query_id=str(uuid.uuid4()),
        tenant_id=TENANT_ID,
        connection_id=conn_id,
        user_id=USER_ID,
        exact_sql="SELECT * FROM orders LIMIT 100",
        parameters={},
        result_ref="s3://bucket/results/abc",
        row_count=42,
        truncated=False,
        latency_ms=150,
    )
    db_session.add(entry)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry).where(
            ExecutionLogEntry.query_id == entry.query_id
        )
    )
    fetched = result.scalar_one()
    assert fetched.exact_sql == "SELECT * FROM orders LIMIT 100"
    assert fetched.row_count == 42
    assert fetched.truncated is False
    assert fetched.latency_ms == 150
    assert fetched.tenant_id == TENANT_ID


@pytest.mark.asyncio
async def test_execution_log_entry_truncated(db_session: AsyncSession) -> None:
    """ExecutionLogEntry correctly records a truncated result."""
    conn_id = str(uuid.uuid4())
    entry = ExecutionLogEntry(
        query_id=str(uuid.uuid4()),
        tenant_id=TENANT_ID,
        connection_id=conn_id,
        user_id=USER_ID,
        exact_sql="SELECT id FROM big_table LIMIT 1000",
        parameters={},
        result_ref="",
        row_count=1000,
        truncated=True,
        latency_ms=800,
    )
    db_session.add(entry)
    await db_session.commit()

    result = await db_session.execute(
        select(ExecutionLogEntry).where(
            ExecutionLogEntry.query_id == entry.query_id
        )
    )
    fetched = result.scalar_one()
    assert fetched.truncated is True
    assert fetched.row_count == 1000


# ---------------------------------------------------------------------------
# HistoryEntry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_entry_create_and_query(db_session: AsyncSession) -> None:
    """HistoryEntry stores a question with its associated query IDs."""
    query_id_1 = str(uuid.uuid4())
    query_id_2 = str(uuid.uuid4())
    conn_id = str(uuid.uuid4())

    entry = HistoryEntry(
        history_id=str(uuid.uuid4()),
        tenant_id=TENANT_ID,
        user_id=USER_ID,
        connection_id=conn_id,
        question="What was total revenue last month?",
        query_ids=[query_id_1, query_id_2],
    )
    db_session.add(entry)
    await db_session.commit()

    result = await db_session.execute(
        select(HistoryEntry).where(
            HistoryEntry.history_id == entry.history_id
        )
    )
    fetched = result.scalar_one()
    assert fetched.question == "What was total revenue last month?"
    assert query_id_1 in fetched.query_ids
    assert query_id_2 in fetched.query_ids
    assert fetched.tenant_id == TENANT_ID


@pytest.mark.asyncio
async def test_history_entry_multi_tenant_isolation(db_session: AsyncSession) -> None:
    """Only history entries for the queried tenant are returned."""
    conn_id = str(uuid.uuid4())

    entry_a = HistoryEntry(
        history_id=str(uuid.uuid4()),
        tenant_id="tenant-A",
        user_id=USER_ID,
        connection_id=conn_id,
        question="Tenant A question",
        query_ids=[],
    )
    entry_b = HistoryEntry(
        history_id=str(uuid.uuid4()),
        tenant_id="tenant-B",
        user_id=USER_ID,
        connection_id=conn_id,
        question="Tenant B question",
        query_ids=[],
    )
    db_session.add_all([entry_a, entry_b])
    await db_session.commit()

    result = await db_session.execute(
        select(HistoryEntry).where(HistoryEntry.tenant_id == "tenant-A")
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].question == "Tenant A question"


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trace_create_and_query(db_session: AsyncSession) -> None:
    """Trace records question, generated SQL, tool calls, latency, and cost."""
    trace = Trace(
        trace_id=str(uuid.uuid4()),
        tenant_id=TENANT_ID,
        question="Show me MRR trend",
        generated_sql="SELECT month, SUM(mrr) FROM metrics GROUP BY month LIMIT 100",
        tool_calls=[{"tool": "get_schema", "args": {}}],
        latency_ms=320,
        cost=0.002,
    )
    db_session.add(trace)
    await db_session.commit()

    result = await db_session.execute(
        select(Trace).where(Trace.trace_id == trace.trace_id)
    )
    fetched = result.scalar_one()
    assert fetched.question == "Show me MRR trend"
    assert "SUM(mrr)" in fetched.generated_sql
    assert fetched.latency_ms == 320
    assert abs(fetched.cost - 0.002) < 1e-9
    assert fetched.tenant_id == TENANT_ID


@pytest.mark.asyncio
async def test_trace_null_generated_sql(db_session: AsyncSession) -> None:
    """Trace allows generated_sql to be None (translation failure case)."""
    trace = Trace(
        trace_id=str(uuid.uuid4()),
        tenant_id=TENANT_ID,
        question="Untranslatable question",
        generated_sql=None,
        tool_calls=[],
        latency_ms=50,
        cost=0.0,
    )
    db_session.add(trace)
    await db_session.commit()

    result = await db_session.execute(
        select(Trace).where(Trace.trace_id == trace.trace_id)
    )
    fetched = result.scalar_one()
    assert fetched.generated_sql is None
