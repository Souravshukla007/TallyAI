"""
Integration tests for the LangGraph orchestration graph (Task 9).

Covers the four design-critical flows with a SQLite app DB (via the
``db_session`` fixture) and a mocked LLM / mocked target-DB connection:

- test_happy_path_select_flow          : SELECT flows end-to-end → grounded response (Req 2, 4, 9, 10, 11)
- test_non_select_rejected_at_safety_gate : non-SELECT rejected, executor never reached (Req 3.3, 3.8)
- test_preview_halts_until_confirm     : preview halts; execution only after confirm (Req 8.2, 8.4)
- test_translation_failure_returns_message : None SQL → user message, no execution (Req 2.3)
- test_grounding_filter_suppresses_unbacked_claims : deterministic suppression (Req 9.5)
- test_safety_gate_uses_no_llm         : safety_gate decision is model-independent (Req 3.7)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tallyai.core.orchestrator import (
    STATUS_AWAITING_CONFIRMATION,
    STATUS_COMPLETED,
    STATUS_REJECTED_BY_SAFETY,
    STATUS_TRANSLATION_FAILED,
    OrchestratorDeps,
    build_query_graph,
)
from tallyai.core.safety import SafetyPolicy
from tallyai.services.explainer import Explainer
from tallyai.services.nl_translator import NLTranslator

SCHEMA = {
    "tables": [
        {"name": "orders", "columns": [{"name": "id"}, {"name": "amount"}, {"name": "status"}]},
    ]
}


# ---------------------------------------------------------------------------
# Helpers
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
    """Deps with a mocked NL translator and explainer (no network)."""
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_select_flow(db_session):
    """A valid SELECT flows end-to-end and returns a grounded response."""
    graph = build_query_graph(_deps("```sql\nSELECT id, amount FROM orders\n```"))
    raw_rows = [{"id": 1, "amount": 10}, {"id": 2, "amount": 20}]
    mock_conn = _make_asyncpg_mock(raw_rows)

    with patch(
        "tallyai.services.query_executor.asyncpg.connect",
        new=AsyncMock(return_value=mock_conn),
    ):
        result = await graph.ainvoke(_base_state(db_session))

    assert result["status"] == STATUS_COMPLETED
    assert result["query_id"] is not None
    assert result["row_count"] == 2

    # Reasoning is grounded: every surviving claim cites a backing query_id.
    claims = result["reasoning"]["claims"]
    assert len(claims) >= 1
    for claim in claims:
        assert claim["supporting_query_ids"]
        assert result["query_id"] in claim["supporting_query_ids"]

    # Response envelope is fully populated.
    assert result["response"]["queryId"] == result["query_id"]
    assert result["response"]["analytics"]["summary"]


@pytest.mark.asyncio
async def test_non_select_rejected_at_safety_gate(db_session):
    """A non-SELECT query is rejected at safety_gate and never reaches the executor."""
    graph = build_query_graph(_deps("```sql\nDELETE FROM orders\n```"))

    with patch("tallyai.services.query_executor.asyncpg.connect") as mock_connect:
        result = await graph.ainvoke(_base_state(db_session))
        mock_connect.assert_not_called()

    assert result["status"] == STATUS_REJECTED_BY_SAFETY
    assert result.get("query_id") is None
    assert result["message"]  # rejection reason present


@pytest.mark.asyncio
async def test_preview_halts_until_confirm(db_session):
    """With preview enabled the graph halts awaiting confirmation; execution only on confirm."""
    graph = build_query_graph(_deps("```sql\nSELECT id, amount FROM orders\n```"))
    raw_rows = [{"id": 1, "amount": 10}]
    mock_conn = _make_asyncpg_mock(raw_rows)

    # Phase 1 — preview enabled, not yet confirmed → halt, no execution.
    with patch("tallyai.services.query_executor.asyncpg.connect") as mock_connect:
        paused = await graph.ainvoke(
            _base_state(db_session, preview_enabled=True, confirmed=None)
        )
        mock_connect.assert_not_called()

    assert paused["status"] == STATUS_AWAITING_CONFIRMATION
    assert paused.get("query_id") is None
    assert paused["candidate_sql"] is not None

    # Phase 2 — user confirms; carry prior state forward and re-invoke.
    resume_state = dict(paused)
    resume_state["db"] = db_session
    resume_state["confirmed"] = True

    with patch(
        "tallyai.services.query_executor.asyncpg.connect",
        new=AsyncMock(return_value=mock_conn),
    ):
        done = await graph.ainvoke(resume_state)

    assert done["status"] == STATUS_COMPLETED
    assert done["query_id"] is not None
    assert done["row_count"] == 1


@pytest.mark.asyncio
async def test_translation_failure_returns_message(db_session):
    """When the translator yields no SQL, a user message is returned and nothing executes."""
    graph = build_query_graph(_deps("Sorry, I cannot answer that. NO_SQL"))

    with patch("tallyai.services.query_executor.asyncpg.connect") as mock_connect:
        result = await graph.ainvoke(_base_state(db_session))
        mock_connect.assert_not_called()

    assert result["status"] == STATUS_TRANSLATION_FAILED
    assert result.get("candidate_sql") is None
    assert result.get("query_id") is None
    assert "could not be translated" in result["message"].lower()


@pytest.mark.asyncio
async def test_grounding_filter_suppresses_unbacked_claims(db_session):
    """grounding_filter deterministically drops claims with no supporting query_id (Req 9.5)."""

    def reasoning_with_unbacked(state):
        qid = state.get("query_id")
        return {
            "facts": [],
            "interpretation": [],
            "recommendations": [],
            "claims": [
                {"text": "backed", "supporting_query_ids": [qid]},
                {"text": "fabricated", "supporting_query_ids": []},
            ],
            "chain": {},
        }

    deps = _deps("```sql\nSELECT id, amount FROM orders\n```")
    deps.reasoning = reasoning_with_unbacked
    graph = build_query_graph(deps)

    mock_conn = _make_asyncpg_mock([{"id": 1, "amount": 10}])
    with patch(
        "tallyai.services.query_executor.asyncpg.connect",
        new=AsyncMock(return_value=mock_conn),
    ):
        result = await graph.ainvoke(_base_state(db_session))

    surviving = {c["text"] for c in result["reasoning"]["claims"]}
    assert "backed" in surviving
    assert "fabricated" not in surviving
    assert any(c["text"] == "fabricated" for c in result["suppressed_claims"])


@pytest.mark.asyncio
async def test_safety_gate_uses_no_llm(db_session):
    """safety_gate must reject a non-SELECT regardless of any LLM 'approval' text.

    The mocked translator emits a destructive statement; the deterministic gate
    rejects it on statement type alone (Req 3.7) — the model has no vote.
    """
    graph = build_query_graph(_deps("```sql\nDROP TABLE orders\n```"))

    with patch("tallyai.services.query_executor.asyncpg.connect") as mock_connect:
        result = await graph.ainvoke(_base_state(db_session))
        mock_connect.assert_not_called()

    assert result["status"] == STATUS_REJECTED_BY_SAFETY
