"""
Tests for orchestrator tracing and observability (Task 17, Req 12.4, 12.5).

Covers:
- test_successful_run_writes_trace        : a completed run persists one Trace
  capturing question, generated SQL, tool calls, latency, and cost (Req 12.4).
- test_trace_records_on_safety_rejection  : a run that ends without execution
  still records a trace (Req 12.4).
- test_trace_write_failure_does_not_interrupt : when trace recording fails the
  question still completes and returns its answer (Req 12.5).
- test_run_question_skips_trace_without_db : no session → tracing is skipped,
  run still returns its result.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from tallyai.core.orchestrator import (
    STATUS_COMPLETED,
    STATUS_REJECTED_BY_SAFETY,
    OrchestratorDeps,
    build_query_graph,
    record_trace,
    run_question,
)
from tallyai.core.safety import SafetyPolicy
from tallyai.db.models import Trace
from tallyai.services.explainer import Explainer
from tallyai.services.nl_translator import NLTranslator

SCHEMA = {
    "tables": [
        {"name": "orders", "columns": [{"name": "id"}, {"name": "amount"}, {"name": "status"}]},
    ]
}


# ---------------------------------------------------------------------------
# Helpers (mirror test_orchestrator.py conventions)
# ---------------------------------------------------------------------------


def _mock_llm(content: str) -> MagicMock:
    llm = MagicMock()
    response = MagicMock()
    response.content = content
    llm.ainvoke = AsyncMock(return_value=response)
    return llm


def _make_asyncpg_mock(rows: list) -> AsyncMock:
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=rows)
    conn.close = AsyncMock(return_value=None)
    return conn


def _deps(sql_content: str) -> OrchestratorDeps:
    return OrchestratorDeps(
        nl_translator=NLTranslator(llm=_mock_llm(sql_content)),
        explainer=Explainer(llm=_mock_llm("This query reads from orders.")),
        policy=SafetyPolicy(row_cap=1000, query_timeout_ms=5000),
    )


def _base_state(db_session, **overrides) -> dict:
    state = {
        "question": "How many orders are there?",
        "connection_id": "conn-1",
        "tenant_id": "tenant-A",
        "user_id": "user-1",
        "preview_enabled": False,
        "confirmed": None,
        "db": db_session,
        "schema": SCHEMA,
        "schema_version": "v1",
        "db_host": "localhost",
        "db_port": 5432,
        "db_database": "testdb",
        "db_user": "reader",
        "db_password": "secret",
    }
    state.update(overrides)
    return state


async def _all_traces(db_session) -> list[Trace]:
    result = await db_session.execute(select(Trace))
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_successful_run_writes_trace(db_session):
    """A successful question run persists a Trace with question, SQL, tool calls,
    latency and cost (Req 12.4)."""
    graph = build_query_graph(_deps("```sql\nSELECT id, amount FROM orders\n```"))
    mock_conn = _make_asyncpg_mock([{"id": 1, "amount": 10}, {"id": 2, "amount": 20}])

    with patch(
        "tallyai.services.query_executor.asyncpg.connect",
        new=AsyncMock(return_value=mock_conn),
    ):
        result = await run_question(_base_state(db_session), graph=graph, cost=0.0042)

    assert result["status"] == STATUS_COMPLETED
    assert result["query_id"] is not None

    traces = await _all_traces(db_session)
    assert len(traces) == 1
    trace = traces[0]

    assert trace.tenant_id == "tenant-A"
    assert trace.question == "How many orders are there?"
    assert trace.generated_sql is not None
    assert "SELECT" in trace.generated_sql.upper()
    assert trace.latency_ms >= 0
    assert trace.cost == pytest.approx(0.0042)

    # tool_calls capture the executed pipeline, including the execution step
    # bound to the produced query_id.
    tools = {call["tool"] for call in trace.tool_calls}
    assert {"schema_context", "semantic_resolution", "sql_generation", "safety_gate", "execution"} <= tools
    exec_call = next(c for c in trace.tool_calls if c["tool"] == "execution")
    assert exec_call["queryId"] == result["query_id"]


@pytest.mark.asyncio
async def test_trace_records_on_safety_rejection(db_session):
    """A run rejected at the safety gate (no execution) still records a trace (Req 12.4)."""
    graph = build_query_graph(_deps("```sql\nDELETE FROM orders\n```"))

    with patch("tallyai.services.query_executor.asyncpg.connect") as mock_connect:
        result = await run_question(_base_state(db_session), graph=graph)
        mock_connect.assert_not_called()

    assert result["status"] == STATUS_REJECTED_BY_SAFETY

    traces = await _all_traces(db_session)
    assert len(traces) == 1
    trace = traces[0]
    tools = {call["tool"] for call in trace.tool_calls}
    # safety_gate ran and rejected; execution never did.
    assert "safety_gate" in tools
    assert "execution" not in tools


@pytest.mark.asyncio
async def test_trace_write_failure_does_not_interrupt(db_session):
    """If trace recording fails, the question still completes and returns its answer (Req 12.5)."""
    graph = build_query_graph(_deps("```sql\nSELECT id, amount FROM orders\n```"))
    mock_conn = _make_asyncpg_mock([{"id": 1, "amount": 10}])

    # Force the Trace write to blow up at construction time. The question has
    # already been answered by the time tracing runs, so the failure must be
    # swallowed (Req 12.5).
    with patch(
        "tallyai.services.query_executor.asyncpg.connect",
        new=AsyncMock(return_value=mock_conn),
    ), patch(
        "tallyai.core.orchestrator.Trace",
        side_effect=RuntimeError("simulated trace store outage"),
    ):
        result = await run_question(_base_state(db_session), graph=graph)

    # Question completed normally despite the trace failure.
    assert result["status"] == STATUS_COMPLETED
    assert result["query_id"] is not None
    assert result["row_count"] == 1

    # No trace persisted, and the session was not poisoned for the caller.
    traces = await _all_traces(db_session)
    assert traces == []


@pytest.mark.asyncio
async def test_record_trace_returns_none_without_db():
    """record_trace is a no-op (returns None) when no DB session is present."""
    state = {"question": "q", "tenant_id": "t", "db": None}
    trace_id = await record_trace(state, dict(state), latency_ms=5, cost=0.0)
    assert trace_id is None


@pytest.mark.asyncio
async def test_run_question_completes_without_db():
    """run_question still returns the result when tracing is skipped (no session)."""
    graph = build_query_graph(_deps("Sorry, I cannot answer that. NO_SQL"))
    # No 'db' key → schema_context/semantic_resolution skip DB work and the
    # translation failure short-circuits before execution.
    state = {
        "question": "unanswerable",
        "connection_id": "conn-1",
        "tenant_id": "tenant-A",
        "user_id": "user-1",
        "preview_enabled": False,
        "confirmed": None,
        "schema": SCHEMA,
        "schema_version": "v1",
    }
    result = await run_question(state, graph=graph)
    assert result.get("candidate_sql") is None
    assert result.get("query_id") is None
