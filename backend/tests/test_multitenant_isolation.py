"""
Multi-tenant isolation enforcement tests (Task 15, Req 14.1-14.4).

Two layers are exercised here:

1. API layer — the tenant-resolution middleware injects the authenticated
   tenant (MVP stub: the ``X-Tenant-Id`` header) into ``request.state`` and
   denies any request that scopes itself to a *different* tenant than the one
   it authenticated as (Req 14.1, 14.4):
     - referencing another tenant's ``connectionId`` → 403
     - reading another tenant's history → 403
     - backward compatibility: the query-param contract still works when no
       authenticated-tenant header is supplied.

2. Connection-pool layer — a target database connection (and therefore its
   pool) can only ever be resolved for the owning tenant; another tenant can
   never obtain the host/credentials needed to open a connection, confirming
   pools are scoped to a single tenant (Req 14.3).

The service-level cross-tenant denial tests for ``ExecutionLog``,
``QueryHistory``, ``CredentialStore``, ``SchemaIntrospector`` and
``SemanticLayer`` live alongside each service's own test module; this module
adds the API-level and pool-level enforcement tests.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from tallyai.api import runs as runs_api
from tallyai.api.runs import _resolve_target, get_query_graph
from tallyai.core.orchestrator import OrchestratorDeps, build_query_graph
from tallyai.core.safety import SafetyPolicy
from tallyai.db.models import Base, TenantConnection
from tallyai.db.session import get_db
from tallyai.main import TENANT_HEADER, app
from tallyai.services.credential_store import CredentialStore
from tallyai.services.explainer import Explainer
from tallyai.services.nl_translator import NLTranslator

TENANT_A = "tenant-A"
TENANT_B = "tenant-B"
CONNECTION = "conn-1"
USER = "default-user"


# ---------------------------------------------------------------------------
# Mocked LLM / deps (mirrors test_api_contract.py)
# ---------------------------------------------------------------------------


def _mock_llm(content: str):
    from unittest.mock import MagicMock

    llm = MagicMock()
    response = MagicMock()
    response.content = content
    llm.ainvoke = AsyncMock(return_value=response)
    return llm


def _deps() -> OrchestratorDeps:
    return OrchestratorDeps(
        nl_translator=NLTranslator(llm=_mock_llm("```sql\nSELECT id, amount FROM orders\n```")),
        explainer=Explainer(llm=_mock_llm("Reads id and amount from orders.")),
        policy=SafetyPolicy(row_cap=1000, query_timeout_ms=5000),
    )


def _make_asyncpg_mock(rows: list) -> AsyncMock:
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=rows)
    conn.close = AsyncMock(return_value=None)
    return conn


# ---------------------------------------------------------------------------
# App fixture — shared in-memory DB with a connection owned by TENANT_A
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

    # conn-1 belongs to TENANT_A only.
    async with factory() as session:
        session.add(
            TenantConnection(
                connection_id=CONNECTION,
                tenant_id=TENANT_A,
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
            CONNECTION, TENANT_A, {"user": "reader", "password": "secret"}, session
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
    runs_api._RUNS.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    runs_api._RUNS.clear()
    await engine.dispose()


# ---------------------------------------------------------------------------
# API layer: cross-tenant references are denied with 403 (Req 14.1, 14.4)
# ---------------------------------------------------------------------------


async def test_cross_tenant_connection_reference_denied(client: AsyncClient):
    """Authenticated as TENANT_B, referencing TENANT_A's connection scope → 403."""
    resp = await client.post(
        f"/api/v1/connections/{CONNECTION}/questions",
        params={"tenant_id": TENANT_A},  # another tenant's scope
        headers={TENANT_HEADER: TENANT_B},  # authenticated identity
        json={"question": "How many orders?", "previewEnabled": False},
    )
    assert resp.status_code == 403, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "cross_tenant_denied"
    assert detail["message"]


async def test_cross_tenant_history_reference_denied(client: AsyncClient):
    """Authenticated as TENANT_B, reading TENANT_A-scoped history → 403."""
    resp = await client.get(
        f"/api/v1/connections/{CONNECTION}/history",
        params={"tenant_id": TENANT_A, "user_id": USER},
        headers={TENANT_HEADER: TENANT_B},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "cross_tenant_denied"


async def test_cross_tenant_supporting_query_reference_denied(client: AsyncClient):
    """Authenticated as TENANT_B, reaching a TENANT_A-scoped execution log → 403."""
    resp = await client.get(
        f"/api/v1/runs/some-run/claims/some-query/supporting-query",
        params={"tenant_id": TENANT_A},
        headers={TENANT_HEADER: TENANT_B},
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "cross_tenant_denied"


# ---------------------------------------------------------------------------
# API layer: legitimate access still works (no false-positive denial)
# ---------------------------------------------------------------------------


async def test_matching_tenant_header_allows_history(client: AsyncClient):
    """Header tenant == query tenant → request proceeds (Req 14.2)."""
    resp = await client.get(
        f"/api/v1/connections/{CONNECTION}/history",
        params={"tenant_id": TENANT_A, "user_id": USER},
        headers={TENANT_HEADER: TENANT_A},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["entries"] == []  # no questions asked yet


async def test_backward_compatible_without_header(client: AsyncClient):
    """The MVP query-param contract still works when no auth header is sent."""
    resp = await client.get(
        f"/api/v1/connections/{CONNECTION}/history",
        params={"tenant_id": TENANT_A, "user_id": USER},
    )
    assert resp.status_code == 200, resp.text


async def test_health_unaffected_by_middleware(client: AsyncClient):
    """The tenant middleware never blocks non-tenant-scoped routes."""
    resp = await client.get("/health", headers={TENANT_HEADER: TENANT_B})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_full_question_flow_for_owning_tenant(client: AsyncClient):
    """A complete run for the owning tenant executes and is reachable (Req 14.1)."""
    mock_conn = _make_asyncpg_mock([{"id": 1, "amount": 10}, {"id": 2, "amount": 20}])
    with patch(
        "tallyai.services.query_executor.asyncpg.connect",
        new=AsyncMock(return_value=mock_conn),
    ):
        resp = await client.post(
            f"/api/v1/connections/{CONNECTION}/questions",
            params={"tenant_id": TENANT_A},
            headers={TENANT_HEADER: TENANT_A},
            json={"question": "How many orders?", "previewEnabled": False},
        )
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["runId"]

    # The completed run is readable by the owning tenant…
    ok = await client.get(
        f"/api/v1/runs/{run_id}/results",
        params={"tenant_id": TENANT_A},
        headers={TENANT_HEADER: TENANT_A},
    )
    assert ok.status_code == 200, ok.text

    # …but a different authenticated tenant is denied at the boundary (Req 14.4).
    denied = await client.get(
        f"/api/v1/runs/{run_id}/results",
        params={"tenant_id": TENANT_A},
        headers={TENANT_HEADER: TENANT_B},
    )
    assert denied.status_code == 403, denied.text


# ---------------------------------------------------------------------------
# Connection-pool layer: pools are scoped to a single tenant (Req 14.3)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def seeded_db():
    """A session with conn-1 (host + encrypted creds) owned by TENANT_A."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    async with factory() as session:
        session.add(
            TenantConnection(
                connection_id=CONNECTION,
                tenant_id=TENANT_A,
                host="db-a.internal",
                port=5432,
                database="tenant_a_db",
                role="reader",
                is_active=True,
                schema_version="",
            )
        )
        await session.flush()
        await CredentialStore().save(
            CONNECTION, TENANT_A, {"user": "reader_a", "password": "secret-a"}, session
        )
        await session.commit()
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_connection_pool_resolves_only_for_owning_tenant(seeded_db):
    """A target connection/pool can be built only for the owning tenant (Req 14.3)."""
    # The owning tenant resolves the target coordinates + credentials.
    owner_target = await _resolve_target(CONNECTION, TENANT_A, seeded_db)
    assert owner_target is not None
    assert owner_target["db_host"] == "db-a.internal"
    assert owner_target["db_user"] == "reader_a"
    assert owner_target["db_password"] == "secret-a"

    # A different tenant can never resolve the connection — so it can never open
    # a pool against another tenant's database (pools are per-tenant).
    other_target = await _resolve_target(CONNECTION, TENANT_B, seeded_db)
    assert other_target is None, (
        "Another tenant must not resolve a connection target — pools are "
        "scoped to a single tenant (Req 14.3)"
    )
