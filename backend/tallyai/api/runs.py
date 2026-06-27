"""
FastAPI router for the TallyAI run lifecycle and connection history.

This router implements the question → preview → confirm → results/reasoning
surface of the REST contract (design §"API contract"), plus the existing
supporting-query lookup and the per-connection query history endpoint.

Routes
------
POST /api/v1/connections/{connectionId}/questions
    Invoke the orchestrator for a question and return the run handle:
    ``runId``, ``generatedSql``, ``explanation``, ``resolvedMetrics`` and
    ``previewState`` (Req 2.1, 2.3, 7.1-7.3, 8.1).
POST /api/v1/runs/{runId}/confirm
    Confirm re-submits the previewed query to the Safety Layer then the
    executor; reject discards it without executing (Req 8.2-8.4).
GET  /api/v1/runs/{runId}/results
    Chart / table / summary / insights + truncation flag (Req 4.4, 4.5,
    10.1-10.4).
GET  /api/v1/runs/{runId}/reasoning
    Grounded facts, interpretation, recommendations, claims and chain — only
    backed claims are returned (Req 9.2, 11.1-11.7).
GET  /api/v1/runs/{runId}/claims/{queryId}/supporting-query
    Verbatim SQL from the execution log (Req 9.3, 9.4).
GET  /api/v1/connections/{connectionId}/history
    Per-user, per-connection history, optionally filtered by ``?search=``
    (Req 13.1-13.3).

``tenant_id`` (and ``user_id``) are passed as query parameters for the MVP,
mirroring ``eval.py`` / ``stream.py``; production resolves them from the bearer
token. Every read is tenant-scoped and any cross-tenant reference is denied
(Req 14.2, 14.4).

Run state is held in an in-process registry (``_RUNS``) keyed by ``runId``,
mirroring ``eval.py``'s pattern. It carries just enough state between the
``questions`` / ``confirm`` / ``results`` / ``reasoning`` calls; credentials are
never stored in it — they are re-resolved from the encrypted store on demand.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tallyai.core.orchestrator import (
    STATUS_AWAITING_CONFIRMATION,
    STATUS_COMPLETED,
    STATUS_DISCARDED,
    STATUS_REJECTED_BY_SAFETY,
    STATUS_TRANSLATION_FAILED,
    build_query_graph,
    record_trace,
)
from tallyai.db.models import TenantConnection
from tallyai.db.session import get_db
from tallyai.services.credential_store import CredentialStore
from tallyai.services.execution_log import ExecutionLog
from tallyai.services.query_history import QueryHistory
from tallyai.services.run_events import (
    PHASE_COMPLETED,
    PHASE_REJECTED,
    get_broker,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["runs"])


# ---------------------------------------------------------------------------
# In-process run registry (MVP — mirrors eval.py's _EVAL_RUNS pattern)
# ---------------------------------------------------------------------------

# runId -> run record dict. Holds no credentials (Req 1.4): the target DB
# credentials are re-resolved from the encrypted store on confirm.
_RUNS: dict[str, dict[str, Any]] = {}

# Maps an orchestrator status to the contract's ``previewState`` vocabulary.
_PREVIEW_STATE = {
    STATUS_AWAITING_CONFIRMATION: "AWAITING_CONFIRMATION",
    STATUS_REJECTED_BY_SAFETY: "REJECTED_BY_SAFETY",
    STATUS_COMPLETED: "EXECUTING",
    STATUS_TRANSLATION_FAILED: "TRANSLATION_FAILED",
    STATUS_DISCARDED: "DISCARDED",
}


# ---------------------------------------------------------------------------
# Dependencies (overridable in tests)
# ---------------------------------------------------------------------------


def get_query_graph():
    """Provide the compiled orchestration graph (default: production deps).

    Tests override this with ``build_query_graph(mocked_deps)`` so the LLM and
    target-DB connection are mocked.
    """
    return build_query_graph()


# ---------------------------------------------------------------------------
# Structured error helper (design property 20: errors carry code + message)
# ---------------------------------------------------------------------------


def _error(status_code: int, code: str, message: str) -> HTTPException:
    """Build an HTTPException whose detail is a structured ``{code, message}``."""
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class QuestionRequest(BaseModel):
    """Request body for ``POST /connections/{connectionId}/questions``."""

    question: str
    previewEnabled: bool = False


class QuestionResponse(BaseModel):
    """Run handle returned after a question is submitted."""

    runId: str
    generatedSql: Optional[str] = None
    explanation: Optional[str] = None
    resolvedMetrics: list[Any] = []
    previewState: Optional[str] = None
    rejectionReason: Optional[str] = None
    message: Optional[str] = None


class ConfirmRequest(BaseModel):
    """Request body for ``POST /runs/{runId}/confirm``."""

    decision: str  # "confirm" | "reject"


class ConfirmResponse(BaseModel):
    runId: str
    state: str  # "EXECUTING" | "DISCARDED"


class InsightModel(BaseModel):
    text: str
    supportingQueryIds: list[str] = []


class ResultsResponse(BaseModel):
    """Default analytics envelope (Req 10.1-10.4, 4.5)."""

    runId: str
    chartable: bool
    chart: Optional[dict] = None
    table: list[dict] = []
    summary: str
    insights: list[InsightModel] = []
    truncated: bool = False


class RecommendationModel(BaseModel):
    hypothesis: str
    supportingSignal: Optional[str] = None
    supportingQueryIds: list[str] = []


class ClaimModel(BaseModel):
    text: str
    value: Optional[float] = None
    supportingQueryIds: list[str] = []
    confidence: Optional[str] = None
    coverage: Optional[str] = None


class ReasoningResponse(BaseModel):
    """Grounded reasoning envelope (Req 9.2, 11.1-11.7)."""

    runId: str
    facts: list[str] = []
    interpretation: list[str] = []
    recommendations: list[RecommendationModel] = []
    claims: list[ClaimModel] = []
    correlationFlag: Optional[str] = None
    chain: dict = {}


class SupportingQueryResponse(BaseModel):
    """Response body for the supporting-query endpoint."""

    queryId: str
    exactSql: str
    parameters: Any
    executedAt: Optional[str]
    latencyMs: int


class HistoryEntryModel(BaseModel):
    historyId: str
    question: str
    queryIds: list[str] = []
    createdAt: Optional[str] = None


class HistoryResponse(BaseModel):
    entries: list[HistoryEntryModel] = []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_target(
    connection_id: str, tenant_id: str, db: AsyncSession
) -> Optional[dict]:
    """Resolve the target DB coordinates + credentials for a connection.

    Returns ``None`` when the connection does not exist or belongs to another
    tenant (Req 14.4). Credentials are decrypted only transiently here and are
    never persisted into the run registry (Req 1.4).
    """
    result = await db.execute(
        select(TenantConnection).where(
            TenantConnection.connection_id == connection_id,
            TenantConnection.tenant_id == tenant_id,
        )
    )
    tc: TenantConnection | None = result.scalars().first()
    if tc is None:
        return None

    creds = await CredentialStore().get_connection(connection_id, tenant_id, db)
    if creds is None:
        return None

    return {
        "db_host": tc.host,
        "db_port": tc.port,
        "db_database": tc.database,
        "db_user": creds.get("user") or creds.get("username") or tc.role,
        "db_password": creds.get("password", ""),
    }


def _safe_event_payload(node: str, state: dict) -> Optional[dict]:
    """Build a small, credential-free progress payload for a node transition.

    The broker additionally sanitizes any credential-bearing key, but we keep
    payloads minimal so the stream stays presentation-only (Req 14).
    """
    if node == "schema_context":
        return {"schemaVersion": state.get("schema_version", "")}
    if node == "semantic_resolution":
        return {"resolvedMetrics": len(state.get("resolved_metrics") or [])}
    if node == "sql_generation":
        return {"status": state.get("status"), "hasSql": bool(state.get("candidate_sql"))}
    if node == "safety_gate":
        decision = state.get("decision")
        return {"approved": bool(getattr(decision, "approved", False))}
    if node == "user_confirm":
        return {"status": state.get("status")}
    if node == "execution":
        return {
            "queryId": state.get("query_id"),
            "rowCount": state.get("row_count", 0),
            "truncated": state.get("truncated", False),
        }
    if node == "analytics_charts":
        return {"chartable": bool((state.get("analytics") or {}).get("chartable"))}
    if node == "reasoning_recommendations":
        return {"claims": len((state.get("reasoning") or {}).get("claims", []))}
    if node == "grounding_filter":
        return {"suppressed": len(state.get("suppressed_claims") or [])}
    return None


async def _run_with_events(
    graph: Any, state: dict, run_id: str, tenant_id: str
) -> dict:
    """Stream the graph, publishing an ordered event per node transition.

    Returns the accumulated final state (equivalent to ``graph.ainvoke``). The
    broker channel is closed when the run reaches a terminal state; an
    ``AWAITING_CONFIRMATION`` pause leaves it open so a subsequent confirm can
    continue the same ordered stream.

    Event publishing is best-effort and never affects the authoritative result.
    """
    broker = get_broker()
    broker.register_run(run_id, tenant_id)

    accumulated: dict = dict(state)
    start = time.perf_counter()

    async for chunk in graph.astream(state, stream_mode="updates"):
        for node, update in chunk.items():
            if isinstance(update, dict):
                accumulated.update(update)
            phase = PHASE_COMPLETED
            if (
                node == "safety_gate"
                and accumulated.get("status") == STATUS_REJECTED_BY_SAFETY
            ):
                phase = PHASE_REJECTED
            try:
                broker.publish(
                    run_id, node, phase, _safe_event_payload(node, accumulated)
                )
            except Exception as exc:  # noqa: BLE001 — streaming is non-authoritative
                logger.debug("run %s: event publish failed for %s: %s", run_id, node, exc)

    latency_ms = int((time.perf_counter() - start) * 1000)
    # Best-effort observability — never interrupts the question (Req 12.5).
    await record_trace(state, accumulated, latency_ms=latency_ms)

    if accumulated.get("status") != STATUS_AWAITING_CONFIRMATION:
        broker.close_run(run_id)

    return accumulated


def _store_run(run_id: str, tenant_id: str, connection_id: str, user_id: str, result: dict) -> None:
    """Persist the run's terminal/paused state into the in-process registry.

    The session handle and any ``db_*`` credential coordinates are stripped so
    no credentials live in the registry (Req 1.4).
    """
    resume_state = {
        k: v
        for k, v in result.items()
        if k != "db" and not k.startswith("db_")
    }
    record = _RUNS.get(run_id, {})
    record.update(
        {
            "run_id": run_id,
            "tenant_id": tenant_id,
            "connection_id": connection_id,
            "user_id": user_id,
            "question": result.get("question"),
            "status": result.get("status"),
            "generated_sql": result.get("candidate_sql"),
            "explanation": result.get("explanation"),
            "resolved_metrics": result.get("resolved_metrics") or [],
            "analytics": result.get("analytics") or {},
            "reasoning": result.get("reasoning") or {},
            "query_id": result.get("query_id"),
            "rejection_reason": (result.get("message") if result.get("status") == STATUS_REJECTED_BY_SAFETY else None),
            "message": result.get("message"),
            "resume_state": resume_state,
        }
    )
    _RUNS[run_id] = record


def _get_run_or_404(run_id: str, tenant_id: str) -> dict:
    """Fetch a run record, enforcing tenant ownership (Req 14.4)."""
    record = _RUNS.get(run_id)
    if record is None or record.get("tenant_id") != tenant_id:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "run_not_found",
            f"No run found for runId={run_id!r}",
        )
    return record


async def _maybe_append_history(
    record: dict, result: dict, db: AsyncSession
) -> None:
    """Append a history entry once the run has an executed query (Req 13.1)."""
    if record.get("history_appended"):
        return
    query_id = result.get("query_id")
    if not query_id:
        return
    try:
        await QueryHistory.append(
            user_id=record["user_id"],
            connection_id=record["connection_id"],
            question=record.get("question") or "",
            query_ids=[query_id],
            tenant_id=record["tenant_id"],
            db=db,
        )
        record["history_appended"] = True
    except Exception as exc:  # noqa: BLE001 — history must not break the run
        logger.warning("history append failed for run %s: %s", record["run_id"], exc)


# ---------------------------------------------------------------------------
# POST /connections/{connectionId}/questions
# ---------------------------------------------------------------------------


@router.post(
    "/connections/{connectionId}/questions",
    response_model=QuestionResponse,
    summary="Submit a natural-language question and start an orchestration run",
)
async def submit_question(
    connectionId: str,
    body: QuestionRequest,
    tenant_id: str = Query(...),
    user_id: str = Query("default-user"),
    db: AsyncSession = Depends(get_db),
    graph: Any = Depends(get_query_graph),
) -> QuestionResponse:
    """Run the orchestrator for *body.question* and return the run handle.

    The candidate SQL has already passed (or been rejected by) the deterministic
    Safety Layer when this returns; when ``previewEnabled`` is true the run
    halts before execution and awaits a confirm (Req 8.1).
    """
    target = await _resolve_target(connectionId, tenant_id, db)
    if target is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "connection_not_found",
            f"No connection found for connectionId={connectionId!r}",
        )

    run_id = str(uuid.uuid4())
    state: dict = {
        "question": body.question,
        "connection_id": connectionId,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "preview_enabled": body.previewEnabled,
        "confirmed": None,
        "db": db,
        **target,
    }

    result = await _run_with_events(graph, state, run_id, tenant_id)

    _store_run(run_id, tenant_id, connectionId, user_id, result)
    record = _RUNS[run_id]
    await _maybe_append_history(record, result, db)

    run_status = result.get("status")
    return QuestionResponse(
        runId=run_id,
        generatedSql=result.get("candidate_sql"),
        explanation=result.get("explanation"),
        resolvedMetrics=result.get("resolved_metrics") or [],
        previewState=_PREVIEW_STATE.get(run_status),
        rejectionReason=(result.get("message") if run_status == STATUS_REJECTED_BY_SAFETY else None),
        message=(result.get("message") if run_status == STATUS_TRANSLATION_FAILED else None),
    )


# ---------------------------------------------------------------------------
# POST /runs/{runId}/confirm
# ---------------------------------------------------------------------------


@router.post(
    "/runs/{runId}/confirm",
    response_model=ConfirmResponse,
    summary="Confirm or reject a previewed query",
)
async def confirm_run(
    runId: str,
    body: ConfirmRequest,
    tenant_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    graph: Any = Depends(get_query_graph),
) -> ConfirmResponse:
    """Confirm re-validates + executes the previewed query; reject discards it.

    Confirm re-submits the query to the Safety Layer and then the Query Executor
    (Req 8.4). Reject discards the query without ever executing it (Req 8.3).
    """
    record = _get_run_or_404(runId, tenant_id)

    decision = (body.decision or "").strip().lower()
    if decision not in ("confirm", "reject"):
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "invalid_decision",
            "decision must be 'confirm' or 'reject'",
        )

    if record.get("status") != STATUS_AWAITING_CONFIRMATION:
        raise _error(
            status.HTTP_409_CONFLICT,
            "not_awaiting_confirmation",
            "run is not awaiting confirmation",
        )

    # ----- Reject: discard without executing (Req 8.3) -----
    if decision == "reject":
        record["status"] = STATUS_DISCARDED
        get_broker().close_run(runId)
        return ConfirmResponse(runId=runId, state="DISCARDED")

    # ----- Confirm: re-resolve target, re-run through safety + executor -----
    target = await _resolve_target(record["connection_id"], tenant_id, db)
    if target is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "connection_not_found",
            "connection for this run no longer resolves",
        )

    resume_state = dict(record["resume_state"])
    resume_state.update(
        {
            "confirmed": True,
            "db": db,
            **target,
        }
    )

    result = await _run_with_events(graph, resume_state, runId, tenant_id)
    _store_run(runId, tenant_id, record["connection_id"], record["user_id"], result)
    await _maybe_append_history(_RUNS[runId], result, db)

    return ConfirmResponse(runId=runId, state="EXECUTING")


# ---------------------------------------------------------------------------
# GET /runs/{runId}/results
# ---------------------------------------------------------------------------


@router.get(
    "/runs/{runId}/results",
    response_model=ResultsResponse,
    summary="Chart / table / summary / insights for a completed run",
)
async def get_run_results(
    runId: str,
    tenant_id: str = Query(...),
) -> ResultsResponse:
    """Return the default analytics envelope for *runId* (Req 4.4, 4.5, 10.1-10.4)."""
    record = _get_run_or_404(runId, tenant_id)

    if record.get("status") != STATUS_COMPLETED:
        raise _error(
            status.HTTP_409_CONFLICT,
            "run_not_completed",
            f"run has no results (status={record.get('status')!r})",
        )

    analytics = record.get("analytics") or {}
    insights = [
        InsightModel(
            text=i.get("text", ""),
            supportingQueryIds=i.get("supporting_query_ids", []),
        )
        for i in analytics.get("insights", [])
    ]

    return ResultsResponse(
        runId=runId,
        chartable=bool(analytics.get("chartable", False)),
        chart=analytics.get("chart"),
        table=analytics.get("table", []),
        summary=analytics.get("summary", ""),
        insights=insights,
        truncated=bool(analytics.get("truncated", False)),
    )


# ---------------------------------------------------------------------------
# GET /runs/{runId}/reasoning
# ---------------------------------------------------------------------------


@router.get(
    "/runs/{runId}/reasoning",
    response_model=ReasoningResponse,
    summary="Grounded reasoning, recommendations and claims for a run",
)
async def get_run_reasoning(
    runId: str,
    tenant_id: str = Query(...),
) -> ReasoningResponse:
    """Return the grounded reasoning envelope for *runId* (Req 9.2, 11.1-11.7).

    Only claims backed by a query id survive the grounding filter; they are the
    only claims present here (Req 9.5).
    """
    record = _get_run_or_404(runId, tenant_id)

    if record.get("status") != STATUS_COMPLETED:
        raise _error(
            status.HTTP_409_CONFLICT,
            "run_not_completed",
            f"run has no reasoning (status={record.get('status')!r})",
        )

    reasoning = record.get("reasoning") or {}

    recommendations = [
        RecommendationModel(
            hypothesis=r.get("hypothesis", ""),
            supportingSignal=r.get("supporting_signal"),
            supportingQueryIds=r.get("supporting_query_ids", []),
        )
        for r in reasoning.get("recommendations", [])
    ]
    claims = [
        ClaimModel(
            text=c.get("text", ""),
            value=c.get("value"),
            supportingQueryIds=c.get("supporting_query_ids", []),
            confidence=c.get("confidence"),
            coverage=c.get("coverage"),
        )
        for c in reasoning.get("claims", [])
    ]

    return ReasoningResponse(
        runId=runId,
        facts=reasoning.get("facts", []),
        interpretation=reasoning.get("interpretation", []),
        recommendations=recommendations,
        claims=claims,
        correlationFlag=reasoning.get("correlation_flag"),
        chain=reasoning.get("chain", {}),
    )


# ---------------------------------------------------------------------------
# GET /runs/{runId}/claims/{queryId}/supporting-query
# ---------------------------------------------------------------------------


@router.get(
    "/runs/{runId}/claims/{queryId}/supporting-query",
    response_model=SupportingQueryResponse,
    summary="Retrieve the exact SQL that backed a specific claim in a run",
)
async def get_supporting_query(
    runId: str,
    queryId: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
) -> SupportingQueryResponse:
    """Return the verbatim SQL used to support *queryId* within *runId*.

    ``exactSql`` is read verbatim from the execution log — never regenerated
    (Req 9.3, 9.4). Returns HTTP 404 when the entry does not exist or belongs to
    a different tenant (Req 14.4).
    """
    entry = await ExecutionLog.get(query_id=queryId, tenant_id=tenant_id, db=db)

    if entry is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "supporting_query_not_found",
            f"No execution log entry found for queryId={queryId!r}",
        )

    executed_at_str: Optional[str] = (
        entry.executed_at.isoformat() if entry.executed_at is not None else None
    )

    return SupportingQueryResponse(
        queryId=entry.query_id,
        # exactSql read verbatim — never regenerated (Req 9.3, 9.4)
        exactSql=entry.exact_sql,
        parameters=entry.parameters,
        executedAt=executed_at_str,
        latencyMs=entry.latency_ms,
    )


# ---------------------------------------------------------------------------
# GET /connections/{connectionId}/history
# ---------------------------------------------------------------------------


@router.get(
    "/connections/{connectionId}/history",
    response_model=HistoryResponse,
    summary="Per-user, per-connection query history (optionally searched)",
)
async def get_connection_history(
    connectionId: str,
    tenant_id: str = Query(...),
    user_id: str = Query("default-user"),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> HistoryResponse:
    """List history for a connection, or filter it by ``search`` (Req 13.1-13.3).

    Results are tenant- and user-scoped; another tenant's history is never
    returned (Req 14.2, 14.4).
    """
    if search is not None and search != "":
        entries = await QueryHistory.search(
            user_id=user_id,
            connection_id=connectionId,
            term=search,
            tenant_id=tenant_id,
            db=db,
        )
    else:
        entries = await QueryHistory.list(
            user_id=user_id,
            connection_id=connectionId,
            tenant_id=tenant_id,
            db=db,
        )

    return HistoryResponse(
        entries=[
            HistoryEntryModel(
                historyId=e.history_id,
                question=e.question,
                queryIds=list(e.query_ids or []),
                createdAt=e.created_at.isoformat() if e.created_at is not None else None,
            )
            for e in entries
        ]
    )
