"""
Integration tests for the full REST API contract (Task 12).

Exercises the question → results/reasoning surface end-to-end through the
FastAPI app with a shared in-memory SQLite app DB, a mocked NL_Translator /
Explainer (no network), and a mocked target-DB asyncpg connection.

Covers the three required properties (design properties 18-20):

- ``test_response_schema_valid``      : /questions, /results, /reasoning, and
                                        /history return the contracted shapes.
- ``test_sse_events_ordered``         : node-transition events for a real run
                                        arrive over SSE in declared order.
- ``test_error_response_structured``  : error responses carry a structured
                                        ``{code, message}`` detail.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from tallyai.api import runs as runs_api
from tallyai.api.runs import get_query_graph
from tallyai.core.orchestrator import OrchestratorDeps, build_query_graph
from tallyai.core.safety import SafetyPolicy
from tallyai.db.models import Base, TenantConnection
from tallyai.db.session import get_db
from tallyai.main import app
from tallyai.services.credential_store import CredentialStore
from tallyai.services.explainer import Explainer
from tallyai.services.nl_translator import NLTranslator

TENANT = "tenant-A"
OTHER_TENANT = "tenant-B"
CONNECTION = "conn-1"
USER = "default-user"

EXPECTED_EVENT_ORDER = [
    "schema_context",
    "semantic_resolution",
    "sql_generation",
    "safety_gate",
    "execution",
    "analytics_charts",
    "reasoning_recommendations",
    "grounding_filter",
]


# ---------------------------------------------------------------------------
# Mocked LLM / deps / target connection
# ---------------------------------------------------------------------------


def _mock_llm(content: str) -> MagicMock:
    llm = MagicMock()
    response = MagicMock()
    response.content = content
    llm.ainvoke = AsyncMock(return_value=response)
    return llm


def _deps(sql_content: str = "```sql\nSELECT id, amount FROM orders\n```") -> OrchestratorDeps:
    return OrchestratorDeps(
        nl_translator=NLTranslator(llm=_mock_llm(sql_content)),
        explainer=Explainer(llm=_mock_llm("This query reads id and amount from orders.")),
        policy=SafetyPolicy(row_cap=1000, query_timeout_ms=5000),
    )


def _make_asyncpg_mock(rows: list) -> AsyncMock:
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=rows)
    conn.close = AsyncMock(return_value=None)
    return conn


# ---------------------------------------------------------------------------
# App fixture — shared in-memory DB, overridden get_db + graph, seeded conn
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared connection → shared :memory: DB
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    # Seed a tenant connection + encrypted credentials so /questions can resolve
    # a target. asyncpg is mocked in the tests, so the values just need to exist.
    async with factory() as session:
        session.add(
            TenantConnection(
                connection_id=CONNECTION,
                tenant_id=TENANT,
                host="localhost",
                port=5432,
                database="testdb",
                role="reader",
                is_active=True,
                schema_version="",
            )
        )
        await session.flush()
        await CredentialStore().save(
            CONNECTION, TENANT, {"user": "reader", "password": "secret"}, session
        )
        await session.commit()

    async def _override_get_db():
        async with factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_query_graph] = lambda: build_query_graph(_deps())

    # Isolate the in-process run registry per test.
    runs_api._RUNS.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    runs_api._RUNS.clear()
    await engine.dispose()


def _parse_sse(text: str) -> list[dict]:
    events: list[dict] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            body = line[len("data:"):].strip()
            if body and not body.startswith(":"):
                events.append(json.loads(body))
    return events


# ---------------------------------------------------------------------------
# Property 18/19: response_schema_valid
# ---------------------------------------------------------------------------


async def test_response_schema_valid(client: AsyncClient):
    rows = [{"id": 1, "amount": 10}, {"id": 2, "amount": 20}]
    mock_conn = _make_asyncpg_mock(rows)

    with patch(
        "tallyai.services.query_executor.asyncpg.connect",
        new=AsyncMock(return_value=mock_conn),
    ):
        resp = await client.post(
            f"/api/v1/connections/{CONNECTION}/questions",
            params={"tenant_id": TENANT, "user_id": USER},
            json={"question": "How many orders are there?", "previewEnabled": False},
        )

    assert resp.status_code == 200, resp.text
    q = resp.json()
    # /questions contract
    assert q["runId"]
    assert q["generatedSql"] and "SELECT" in q["generatedSql"].upper()
    assert "resolvedMetrics" in q
    assert q["previewState"] == "EXECUTING"
    run_id = q["runId"]

    # /results contract (Req 4.4, 4.5, 10.1-10.4)
    r = await client.get(
        f"/api/v1/runs/{run_id}/results", params={"tenant_id": TENANT}
    )
    assert r.status_code == 200, r.text
    results = r.json()
    for key in ("chartable", "table", "summary", "insights", "truncated"):
        assert key in results
    assert isinstance(results["chartable"], bool)
    assert results["truncated"] is False
    for insight in results["insights"]:
        assert "text" in insight and "supportingQueryIds" in insight

    # /reasoning contract — only grounded claims (Req 9.2, 9.5, 11.1-11.7)
    rr = await client.get(
        f"/api/v1/runs/{run_id}/reasoning", params={"tenant_id": TENANT}
    )
    assert rr.status_code == 200, rr.text
    reasoning = rr.json()
    for key in ("facts", "interpretation", "recommendations", "claims", "chain"):
        assert key in reasoning
    assert len(reasoning["claims"]) >= 1
    for claim in reasoning["claims"]:
        assert claim["supportingQueryIds"], "every surviving claim must be grounded"
        assert claim["confidence"] and claim["coverage"]

    # /history reflects the executed question (Req 13.1, 13.2)
    h = await client.get(
        f"/api/v1/connections/{CONNECTION}/history",
        params={"tenant_id": TENANT, "user_id": USER},
    )
    assert h.status_code == 200, h.text
    entries = h.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["question"] == "How many orders are there?"
    assert entries[0]["queryIds"]

    # Search filters (Req 13.3)
    h_match = await client.get(
        f"/api/v1/connections/{CONNECTION}/history",
        params={"tenant_id": TENANT, "user_id": USER, "search": "orders"},
    )
    assert len(h_match.json()["entries"]) == 1
    h_miss = await client.get(
        f"/api/v1/connections/{CONNECTION}/history",
        params={"tenant_id": TENANT, "user_id": USER, "search": "zzz-nomatch"},
    )
    assert h_miss.json()["entries"] == []

    # Cross-tenant history is denied / empty (Req 14.2, 14.4)
    h_other = await client.get(
        f"/api/v1/connections/{CONNECTION}/history",
        params={"tenant_id": OTHER_TENANT, "user_id": USER},
    )
    assert h_other.json()["entries"] == []


# ---------------------------------------------------------------------------
# sse_events_ordered
# ---------------------------------------------------------------------------


async def test_sse_events_ordered(client: AsyncClient):
    rows = [{"id": 1, "amount": 10}, {"id": 2, "amount": 20}]
    mock_conn = _make_asyncpg_mock(rows)

    with patch(
        "tallyai.services.query_executor.asyncpg.connect",
        new=AsyncMock(return_value=mock_conn),
    ):
        resp = await client.post(
            f"/api/v1/connections/{CONNECTION}/questions",
            params={"tenant_id": TENANT},
            json={"question": "How many orders?", "previewEnabled": False},
        )
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["runId"]

    # The run has completed and closed its channel; SSE replays the full,
    # ordered event history then terminates.
    sse = await client.get(
        f"/api/v1/runs/{run_id}/events", params={"tenant_id": TENANT}
    )
    assert sse.status_code == 200
    events = _parse_sse(sse.text)

    nodes = [e["node"] for e in events]
    assert nodes == EXPECTED_EVENT_ORDER
    assert all(e["runId"] == run_id for e in events)

    # No credential values leaked into any event payload (Req 14).
    assert "secret" not in sse.text


async def test_sse_cross_tenant_denied(client: AsyncClient):
    mock_conn = _make_asyncpg_mock([{"id": 1, "amount": 10}])
    with patch(
        "tallyai.services.query_executor.asyncpg.connect",
        new=AsyncMock(return_value=mock_conn),
    ):
        resp = await client.post(
            f"/api/v1/connections/{CONNECTION}/questions",
            params={"tenant_id": TENANT},
            json={"question": "How many orders?", "previewEnabled": False},
        )
    run_id = resp.json()["runId"]

    denied = await client.get(
        f"/api/v1/runs/{run_id}/events", params={"tenant_id": OTHER_TENANT}
    )
    assert denied.status_code == 404


# ---------------------------------------------------------------------------
# error_response_structured (code + message)
# ---------------------------------------------------------------------------


async def test_error_response_structured(client: AsyncClient):
    # Unknown run → structured 404.
    r = await client.get(
        "/api/v1/runs/does-not-exist/results", params={"tenant_id": TENANT}
    )
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert detail["code"] == "run_not_found"
    assert detail["message"]

    # Unknown connection → structured 404.
    q = await client.post(
        "/api/v1/connections/missing-conn/questions",
        params={"tenant_id": TENANT},
        json={"question": "anything", "previewEnabled": False},
    )
    assert q.status_code == 404
    qdetail = q.json()["detail"]
    assert qdetail["code"] == "connection_not_found"
    assert qdetail["message"]

    # Unknown supporting query → structured 404.
    s = await client.get(
        "/api/v1/runs/whatever/claims/no-such-query/supporting-query",
        params={"tenant_id": TENANT},
    )
    assert s.status_code == 404
    assert s.json()["detail"]["code"] == "supporting_query_not_found"


# ---------------------------------------------------------------------------
# Preview → confirm / reject (Req 8.2-8.4)
# ---------------------------------------------------------------------------


async def test_preview_confirm_executes(client: AsyncClient):
    mock_conn = _make_asyncpg_mock([{"id": 1, "amount": 10}])

    with patch(
        "tallyai.services.query_executor.asyncpg.connect",
        new=AsyncMock(return_value=mock_conn),
    ) as mock_connect:
        # Preview enabled → halts awaiting confirmation, no execution yet.
        resp = await client.post(
            f"/api/v1/connections/{CONNECTION}/questions",
            params={"tenant_id": TENANT},
            json={"question": "How many orders?", "previewEnabled": True},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["previewState"] == "AWAITING_CONFIRMATION"
        mock_connect.assert_not_called()
        run_id = body["runId"]

        # Results not available before confirmation.
        early = await client.get(
            f"/api/v1/runs/{run_id}/results", params={"tenant_id": TENANT}
        )
        assert early.status_code == 409
        assert early.json()["detail"]["code"] == "run_not_completed"

        # Confirm → re-validates through safety + executes.
        confirm = await client.post(
            f"/api/v1/runs/{run_id}/confirm",
            params={"tenant_id": TENANT},
            json={"decision": "confirm"},
        )
        assert confirm.status_code == 200, confirm.text
        assert confirm.json()["state"] == "EXECUTING"
        mock_connect.assert_called()  # execution happened only after confirm

    done = await client.get(
        f"/api/v1/runs/{run_id}/results", params={"tenant_id": TENANT}
    )
    assert done.status_code == 200


async def test_preview_reject_discards(client: AsyncClient):
    with patch(
        "tallyai.services.query_executor.asyncpg.connect",
        new=AsyncMock(),
    ) as mock_connect:
        resp = await client.post(
            f"/api/v1/connections/{CONNECTION}/questions",
            params={"tenant_id": TENANT},
            json={"question": "How many orders?", "previewEnabled": True},
        )
        run_id = resp.json()["runId"]

        reject = await client.post(
            f"/api/v1/runs/{run_id}/confirm",
            params={"tenant_id": TENANT},
            json={"decision": "reject"},
        )
        assert reject.status_code == 200, reject.text
        assert reject.json()["state"] == "DISCARDED"
        # Reject discards without ever executing (Req 8.3).
        mock_connect.assert_not_called()


async def test_non_select_rejected_by_safety(client: AsyncClient):
    app.dependency_overrides[get_query_graph] = lambda: build_query_graph(
        _deps("```sql\nDELETE FROM orders\n```")
    )
    with patch("tallyai.services.query_executor.asyncpg.connect") as mock_connect:
        resp = await client.post(
            f"/api/v1/connections/{CONNECTION}/questions",
            params={"tenant_id": TENANT},
            json={"question": "delete the orders", "previewEnabled": False},
        )
        mock_connect.assert_not_called()

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["previewState"] == "REJECTED_BY_SAFETY"
    assert body["rejectionReason"]
