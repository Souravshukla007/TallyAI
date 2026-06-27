"""
Tests for QueryExecutor and ExecutionLog.

Covers:
- test_execute_writes_log_entry        : log entry is written with exact_sql = decision.safe_sql
- test_row_cap_truncation              : 1001 rows with row_cap=1000 → truncated=True, row_count=1000
- test_timeout_raises                  : asyncpg QueryCanceledError → TimeoutError
- test_unapproved_decision_raises      : approved=False → ValueError, no DB call (Req 3.8, 3.9)
- test_unparsed_decision_raises        : parsed_ok=False → ValueError
- test_cross_tenant_get_returns_none   : tenant mismatch on get() → None (Req 14.4)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tallyai.core.safety import SafetyDecision, SafetyPolicy
from tallyai.services.execution_log import ExecutionLog
from tallyai.services.query_executor import ExecutionResult, QueryExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _approved_decision(sql: str = "SELECT id FROM users LIMIT 1000") -> SafetyDecision:
    return SafetyDecision(
        approved=True,
        safe_sql=sql,
        reason=None,
        parsed_ok=True,
    )


def _make_records(n: int) -> list[MagicMock]:
    """Return a list of mock asyncpg Record objects."""
    records = []
    for i in range(n):
        record = MagicMock()
        record.__iter__ = MagicMock(return_value=iter([("id", i)]))
        # dict(record) is called — make the mock behave like a mapping
        record.items = MagicMock(return_value=iter([("id", i)]))
        records.append(record)
    return records


def _make_asyncpg_mock(rows: list) -> MagicMock:
    """Return a mock asyncpg connection whose fetch() returns *rows*."""
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=rows)
    conn.close = AsyncMock(return_value=None)
    return conn


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_writes_log_entry(db_session):
    """Executing a query should write an ExecutionLogEntry with exact_sql == decision.safe_sql."""
    sql = "SELECT id FROM orders LIMIT 1000"
    decision = _approved_decision(sql)
    policy = SafetyPolicy(row_cap=1000, query_timeout_ms=5000)

    raw_rows = [{"id": 1}, {"id": 2}]
    mock_conn = _make_asyncpg_mock(raw_rows)

    with patch("tallyai.services.query_executor.asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
        executor = QueryExecutor()
        result = await executor.execute(
            decision=decision,
            connection_id="conn-1",
            tenant_id="tenant-A",
            user_id="user-1",
            host="localhost",
            port=5432,
            database="testdb",
            user="reader",
            password="secret",
            policy=policy,
            db=db_session,
        )

    # Confirm the return value
    assert isinstance(result, ExecutionResult)
    assert result.query_id is not None
    assert result.row_count == 2
    assert result.truncated is False

    # Confirm the log entry was persisted
    await db_session.commit()
    entry = await ExecutionLog.get(
        query_id=result.query_id,
        tenant_id="tenant-A",
        db=db_session,
    )
    assert entry is not None
    assert entry.exact_sql == sql  # verbatim (Req 9.3, 9.4)
    assert entry.row_count == 2
    assert entry.truncated is False


@pytest.mark.asyncio
async def test_row_cap_truncation(db_session):
    """When asyncpg returns 1001 rows with row_cap=1000 → truncated=True, row_count=1000."""
    decision = _approved_decision()
    policy = SafetyPolicy(row_cap=1000, query_timeout_ms=5000)

    # 1001 raw rows — each is a plain dict (dict(record) is called)
    raw_rows = [{"id": i} for i in range(1001)]
    mock_conn = _make_asyncpg_mock(raw_rows)

    with patch("tallyai.services.query_executor.asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
        executor = QueryExecutor()
        result = await executor.execute(
            decision=decision,
            connection_id="conn-1",
            tenant_id="tenant-A",
            user_id="user-1",
            host="localhost",
            port=5432,
            database="testdb",
            user="reader",
            password="secret",
            policy=policy,
            db=db_session,
        )

    assert result.truncated is True
    assert result.row_count == 1000
    assert len(result.rows) == 1000


@pytest.mark.asyncio
async def test_timeout_raises(db_session):
    """asyncpg.exceptions.QueryCanceledError should be re-raised as TimeoutError."""
    import asyncpg.exceptions

    decision = _approved_decision()
    policy = SafetyPolicy(row_cap=1000, query_timeout_ms=100)

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=None)
    mock_conn.fetch = AsyncMock(
        side_effect=asyncpg.exceptions.QueryCanceledError("statement timeout")
    )
    mock_conn.close = AsyncMock(return_value=None)

    with patch("tallyai.services.query_executor.asyncpg.connect", new=AsyncMock(return_value=mock_conn)):
        executor = QueryExecutor()
        with pytest.raises(TimeoutError, match="Query exceeded timeout"):
            await executor.execute(
                decision=decision,
                connection_id="conn-1",
                tenant_id="tenant-A",
                user_id="user-1",
                host="localhost",
                port=5432,
                database="testdb",
                user="reader",
                password="secret",
                policy=policy,
                db=db_session,
            )


@pytest.mark.asyncio
async def test_unapproved_decision_raises(db_session):
    """approved=False must raise ValueError without opening any DB connection (Req 3.8, 3.9)."""
    decision = SafetyDecision(
        approved=False,
        safe_sql=None,
        reason="Statement type not allowed",
        parsed_ok=True,
    )
    policy = SafetyPolicy()

    with patch("tallyai.services.query_executor.asyncpg.connect") as mock_connect:
        executor = QueryExecutor()
        with pytest.raises(ValueError, match="Execution blocked"):
            await executor.execute(
                decision=decision,
                connection_id="conn-1",
                tenant_id="tenant-A",
                user_id="user-1",
                host="localhost",
                port=5432,
                database="testdb",
                user="reader",
                password="secret",
                policy=policy,
                db=db_session,
            )

        # asyncpg.connect must NOT have been called
        mock_connect.assert_not_called()


@pytest.mark.asyncio
async def test_unparsed_decision_raises(db_session):
    """parsed_ok=False must raise ValueError without opening any DB connection."""
    decision = SafetyDecision(
        approved=True,
        safe_sql=None,
        reason=None,
        parsed_ok=False,
    )
    policy = SafetyPolicy()

    with patch("tallyai.services.query_executor.asyncpg.connect") as mock_connect:
        executor = QueryExecutor()
        with pytest.raises(ValueError, match="Execution blocked"):
            await executor.execute(
                decision=decision,
                connection_id="conn-1",
                tenant_id="tenant-A",
                user_id="user-1",
                host="localhost",
                port=5432,
                database="testdb",
                user="reader",
                password="secret",
                policy=policy,
                db=db_session,
            )

        mock_connect.assert_not_called()


@pytest.mark.asyncio
async def test_cross_tenant_get_returns_none(db_session):
    """Log entry written for tenant A must not be visible to tenant B (Req 14.4)."""
    query_id = await ExecutionLog.record(
        entry_data={
            "query_id": "qid-cross-tenant-test",
            "tenant_id": "tenant-A",
            "connection_id": "conn-1",
            "user_id": "user-1",
            "exact_sql": "SELECT 1",
            "parameters": {},
            "result_ref": "",
            "row_count": 1,
            "truncated": False,
            "latency_ms": 5,
        },
        db=db_session,
    )
    await db_session.commit()

    # Tenant A can see it
    entry_a = await ExecutionLog.get(
        query_id=query_id,
        tenant_id="tenant-A",
        db=db_session,
    )
    assert entry_a is not None

    # Tenant B must get None
    entry_b = await ExecutionLog.get(
        query_id=query_id,
        tenant_id="tenant-B",
        db=db_session,
    )
    assert entry_b is None
