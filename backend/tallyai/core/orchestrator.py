"""
LangGraph orchestration graph for TallyAI.

This module wires the deterministic query pipeline described in the design
state machine into a single LangGraph ``StateGraph``. Agents propose; code
disposes — the ``safety_gate`` and ``grounding_filter`` nodes are deterministic
non-model code, while ``sql_generation`` and ``reasoning_recommendations`` are
the model-driven steps.

Node flow (design §"LangGraph Orchestration"):

    schema_context → semantic_resolution → sql_generation → safety_gate
        safety_gate --reject--> END (rejection message, no execution)   (Req 3.8)
        safety_gate --approve--> (preview? user_confirm : execution)
        user_confirm --confirmed--> execution                           (Req 8.4)
        user_confirm --awaiting/rejected--> END (no execution)          (Req 8.2)
    execution → analytics_charts → reasoning_recommendations → grounding_filter → END

Key invariants enforced here:

* ``safety_gate`` calls **only** ``SafetyLayer.validate()`` — never an LLM
  (Req 3.7). A non-SELECT (or otherwise unsafe) query is rejected before the
  executor is ever reached (Req 3.8).
* A translation failure (``sql_generation`` returns ``None``) short-circuits to
  a user-facing message and executes nothing (Req 2.3).
* ``grounding_filter`` deterministically suppresses any quantitative claim that
  has no backing ``query_id`` (Req 9.5).

The ``reasoning`` (Task 10) and ``analytics`` (Task 11) collaborators are
injected through :class:`OrchestratorDeps`. Minimal in-module stub
implementations are used by default so the graph is structurally complete and
end-to-end testable; Tasks 10 and 11 replace them by passing real
implementations into :func:`build_query_graph`.
"""

from __future__ import annotations

import inspect
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from tallyai.core.safety import SafetyDecision, SafetyLayer, SafetyPolicy
from tallyai.core.semantic_layer import SemanticLayer
from tallyai.db.models import Trace
from tallyai.services.analytics import build_chart_response
from tallyai.services.explainer import Explainer
from tallyai.services.nl_translator import NLTranslator
from tallyai.services.query_executor import QueryExecutor
from tallyai.services.reasoning_layer import ReasoningLayer
from tallyai.services.schema_introspector import SchemaIntrospector

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status constants (mirrored in the API previewState / state vocabulary)
# ---------------------------------------------------------------------------

STATUS_TRANSLATION_FAILED = "translation_failed"
STATUS_REJECTED_BY_SAFETY = "rejected_by_safety"
STATUS_AWAITING_CONFIRMATION = "awaiting_confirmation"
STATUS_DISCARDED = "discarded"
STATUS_COMPLETED = "completed"


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------


class QueryState(TypedDict, total=False):
    """Mutable state threaded through every orchestration node.

    ``total=False`` so nodes may contribute only the keys they own; the default
    channel reducer is last-write-wins.
    """

    # --- Inputs ---
    question: str
    connection_id: str
    tenant_id: str
    user_id: str
    preview_enabled: bool
    confirmed: bool | None          # None=not decided, True=confirm, False=reject

    # --- Runtime collaborators / target DB credentials ---
    db: Any                          # AsyncSession for app DB (log, metrics)
    db_host: str
    db_port: int
    db_database: str
    db_user: str
    db_password: str

    # --- Intermediate ---
    schema: dict
    schema_version: str
    resolved_metrics: list[dict]
    candidate_sql: str | None
    explanation: str | None
    decision: SafetyDecision
    safe_sql: str | None

    # --- Execution results ---
    query_id: str | None
    rows: list[dict]
    row_count: int
    truncated: bool
    latency_ms: int

    # --- Downstream ---
    analytics: dict
    reasoning: dict
    claims: list[dict]
    suppressed_claims: list[dict]

    # --- Output envelope ---
    status: str
    message: str | None
    response: dict


# ---------------------------------------------------------------------------
# Dependency container
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorDeps:
    """Collaborators injected into the graph.

    Defaults wire the production services. ``reasoning`` is left ``None`` and
    falls back to the in-module stub until Task 10 provides a real
    implementation; ``analytics`` falls back to the Task 11
    :func:`tallyai.services.analytics.build_chart_response`.
    """

    safety_layer: Any = SafetyLayer
    semantic_layer: Any = field(default_factory=SemanticLayer)
    nl_translator: Any = field(default_factory=NLTranslator)
    explainer: Any = field(default_factory=Explainer)
    query_executor: Any = field(default_factory=QueryExecutor)
    schema_introspector: Any = field(default_factory=SchemaIntrospector)
    reasoning: Any = field(default_factory=lambda: ReasoningLayer().reason)  # callable(state) -> dict (Task 10)
    analytics: Any = None            # callable(state) -> dict; defaults to build_chart_response (Task 11)
    policy: SafetyPolicy = field(default_factory=SafetyPolicy)


# ---------------------------------------------------------------------------
# Stub integration points (reasoning replaced by Task 10; analytics is the
# real Task 11 implementation in tallyai.services.analytics)
# ---------------------------------------------------------------------------


def _default_reasoning(state: QueryState) -> dict:
    """Minimal reasoning stub (Task 10 replaces this).

    Separates facts from interpretation and binds each quantitative claim to the
    producing ``query_id`` (Req 9.2, 11.1). Claims with no backing query are
    later suppressed by ``grounding_filter`` (Req 9.5).
    """
    rows = state.get("rows", []) or []
    query_id = state.get("query_id")
    claims: list[dict] = []
    if query_id is not None:
        claims.append(
            {
                "text": f"The query returned {len(rows)} row(s).",
                "value": float(len(rows)),
                "supporting_query_ids": [query_id],
                "confidence": "medium",
                "coverage": "full",
            }
        )
    return {
        "facts": [f"{len(rows)} row(s) returned by the executed query."],
        "interpretation": [],
        "recommendations": [],
        "claims": claims,
        "correlation_flag": None,
        "chain": {
            "question": state.get("question"),
            "executed_query_id": query_id,
        },
    }


async def _maybe_await(value: Any) -> Any:
    """Await *value* if it is awaitable, otherwise return it unchanged."""
    if inspect.isawaitable(value):
        return await value
    return value


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def build_query_graph(deps: OrchestratorDeps | None = None):
    """Build and compile the TallyAI orchestration graph.

    Parameters
    ----------
    deps:
        Optional dependency container. When omitted, production services are
        wired with the reasoning/analytics stubs.

    Returns
    -------
    A compiled LangGraph runnable invoked with ``await graph.ainvoke(state)``.
    """
    deps = deps or OrchestratorDeps()

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    async def schema_context(state: QueryState) -> dict:
        """Load the cached schema for the connection (Req 2.2, 5.3)."""
        if state.get("schema") is not None:
            return {"schema_version": state.get("schema_version", "")}

        db = state.get("db")
        introspector = deps.schema_introspector
        if db is not None and introspector is not None:
            try:
                cached = await introspector.get_cached(
                    state["connection_id"], state["tenant_id"], db
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("schema_context: get_cached failed: %s", exc)
                cached = None
            if cached:
                return {
                    "schema": {"tables": cached.get("tables", [])},
                    "schema_version": cached.get("schema_version", ""),
                }
        return {"schema": {"tables": []}, "schema_version": state.get("schema_version", "")}

    async def semantic_resolution(state: QueryState) -> dict:
        """Resolve business terms to canonical metric definitions (Req 6.2, 6.4)."""
        metrics = state.get("resolved_metrics") or []
        db = state.get("db")
        if deps.semantic_layer is not None and db is not None:
            try:
                metrics = await deps.semantic_layer.resolve(
                    state["question"],
                    state["connection_id"],
                    state.get("schema_version", ""),
                    state["tenant_id"],
                    db,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("semantic_resolution failed: %s", exc)
        return {"resolved_metrics": metrics}

    async def sql_generation(state: QueryState) -> dict:
        """Generate candidate SQL from schema + canonical formulas (Req 2.1, 6.3).

        On a confirm re-invocation the prior ``candidate_sql`` is reused so the
        confirmed query is the one re-validated and executed (Req 8.4).
        Returns ``candidate_sql=None`` on translation failure (Req 2.3).
        """
        if state.get("candidate_sql"):
            return {}

        sql = await deps.nl_translator.generate_sql(
            state["question"],
            state.get("schema", {}) or {},
            state.get("resolved_metrics", []) or [],
        )

        if sql is None:
            message = "The question could not be translated into a SQL query."
            return {
                "candidate_sql": None,
                "status": STATUS_TRANSLATION_FAILED,
                "message": message,
                "response": {
                    "status": STATUS_TRANSLATION_FAILED,
                    "message": message,
                    "generatedSql": None,
                },
            }

        explanation = None
        if deps.explainer is not None:
            explanation = await deps.explainer.explain(
                sql, state.get("resolved_metrics", []) or []
            )
        return {"candidate_sql": sql, "explanation": explanation}

    async def safety_gate(state: QueryState) -> dict:
        """Deterministic gate — calls ONLY SafetyLayer.validate(), no LLM (Req 3.7).

        Rejection short-circuits before execution (Req 3.3, 3.8).
        """
        decision: SafetyDecision = deps.safety_layer.validate(
            state["candidate_sql"], deps.policy
        )
        if not decision.approved:
            return {
                "decision": decision,
                "safe_sql": None,
                "query_id": None,
                "status": STATUS_REJECTED_BY_SAFETY,
                "message": decision.reason,
                "response": {
                    "status": STATUS_REJECTED_BY_SAFETY,
                    "previewState": "REJECTED_BY_SAFETY",
                    "rejectionReason": decision.reason,
                    "generatedSql": state.get("candidate_sql"),
                },
            }
        return {"decision": decision, "safe_sql": decision.safe_sql}

    async def user_confirm(state: QueryState) -> dict:
        """Preview gate — halt until the user confirms (Req 8.1, 8.2, 8.3)."""
        confirmed = state.get("confirmed")
        if confirmed is True:
            # Proceed to execution; nothing to add to state.
            return {}
        if confirmed is False:
            message = "Query discarded by user before execution."
            return {
                "status": STATUS_DISCARDED,
                "message": message,
                "query_id": None,
                "response": {
                    "status": STATUS_DISCARDED,
                    "state": "DISCARDED",
                    "message": message,
                },
            }
        # confirmed is None → awaiting user decision; no execution (Req 8.2).
        message = "Awaiting user confirmation of the previewed query."
        return {
            "status": STATUS_AWAITING_CONFIRMATION,
            "message": message,
            "query_id": None,
            "response": {
                "status": STATUS_AWAITING_CONFIRMATION,
                "previewState": "AWAITING_CONFIRMATION",
                "generatedSql": state.get("safe_sql"),
                "explanation": state.get("explanation"),
            },
        }

    async def execution(state: QueryState) -> dict:
        """Execute the approved query and write the execution log (Req 4.1, 9.1)."""
        result = await deps.query_executor.execute(
            decision=state["decision"],
            connection_id=state["connection_id"],
            tenant_id=state["tenant_id"],
            user_id=state.get("user_id", ""),
            host=state["db_host"],
            port=state["db_port"],
            database=state["db_database"],
            user=state["db_user"],
            password=state["db_password"],
            policy=deps.policy,
            db=state.get("db"),
        )
        return {
            "query_id": result.query_id,
            "rows": result.rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "latency_ms": result.latency_ms,
        }

    async def analytics_charts(state: QueryState) -> dict:
        """Build chart/summary/insights (Req 10.1-10.4); Task 11 implementation."""
        fn = deps.analytics or build_chart_response
        analytics = await _maybe_await(fn(state))
        return {"analytics": analytics}

    async def reasoning_recommendations(state: QueryState) -> dict:
        """Produce facts/interpretation/recommendations (Req 11); Task 10 stub."""
        fn = deps.reasoning or _default_reasoning
        reasoning = await _maybe_await(fn(state))
        return {"reasoning": reasoning, "claims": reasoning.get("claims", [])}

    async def grounding_filter(state: QueryState) -> dict:
        """Deterministically suppress claims with no backing query_id (Req 9.5).

        Pure non-model code: a claim survives iff it carries at least one
        ``supporting_query_ids`` entry.
        """
        reasoning = dict(state.get("reasoning", {}) or {})
        claims = reasoning.get("claims", []) or []
        grounded = [c for c in claims if c.get("supporting_query_ids")]
        suppressed = [c for c in claims if not c.get("supporting_query_ids")]
        reasoning["claims"] = grounded

        response = {
            "status": STATUS_COMPLETED,
            "queryId": state.get("query_id"),
            "rows": state.get("rows", []),
            "rowCount": state.get("row_count", 0),
            "truncated": state.get("truncated", False),
            "analytics": state.get("analytics", {}),
            "reasoning": reasoning,
        }
        return {
            "reasoning": reasoning,
            "claims": grounded,
            "suppressed_claims": suppressed,
            "status": STATUS_COMPLETED,
            "response": response,
        }

    # ------------------------------------------------------------------
    # Routers (deterministic)
    # ------------------------------------------------------------------

    def route_after_sql(state: QueryState) -> str:
        return "safety_gate" if state.get("candidate_sql") else END

    def route_after_safety(state: QueryState) -> str:
        decision = state.get("decision")
        if decision is None or not decision.approved:
            return END
        if state.get("preview_enabled"):
            return "user_confirm"
        return "execution"

    def route_after_confirm(state: QueryState) -> str:
        return "execution" if state.get("confirmed") is True else END

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    graph = StateGraph(QueryState)

    graph.add_node("schema_context", schema_context)
    graph.add_node("semantic_resolution", semantic_resolution)
    graph.add_node("sql_generation", sql_generation)
    graph.add_node("safety_gate", safety_gate)
    graph.add_node("user_confirm", user_confirm)
    graph.add_node("execution", execution)
    graph.add_node("analytics_charts", analytics_charts)
    graph.add_node("reasoning_recommendations", reasoning_recommendations)
    graph.add_node("grounding_filter", grounding_filter)

    graph.add_edge(START, "schema_context")
    graph.add_edge("schema_context", "semantic_resolution")
    graph.add_edge("semantic_resolution", "sql_generation")

    graph.add_conditional_edges(
        "sql_generation",
        route_after_sql,
        {"safety_gate": "safety_gate", END: END},
    )
    graph.add_conditional_edges(
        "safety_gate",
        route_after_safety,
        {"user_confirm": "user_confirm", "execution": "execution", END: END},
    )
    graph.add_conditional_edges(
        "user_confirm",
        route_after_confirm,
        {"execution": "execution", END: END},
    )

    graph.add_edge("execution", "analytics_charts")
    graph.add_edge("analytics_charts", "reasoning_recommendations")
    graph.add_edge("reasoning_recommendations", "grounding_filter")
    graph.add_edge("grounding_filter", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Tracing and observability (Req 12.4, 12.5)
# ---------------------------------------------------------------------------


def _build_tool_calls(state: QueryState) -> list[dict]:
    """Derive the ordered list of tool calls a run made from its final state.

    The orchestration nodes act as the "tools" of the run. We reconstruct the
    call list from the markers each node leaves on the state so the trace
    faithfully reflects which steps actually executed for this question
    (Req 12.4). Steps that never ran (e.g. ``execution`` after a safety
    rejection) are omitted.
    """
    tool_calls: list[dict] = [
        {"tool": "schema_context", "schemaVersion": state.get("schema_version", "")},
        {
            "tool": "semantic_resolution",
            "resolvedMetrics": len(state.get("resolved_metrics") or []),
        },
        {"tool": "sql_generation", "generatedSql": state.get("candidate_sql")},
    ]

    decision = state.get("decision")
    if decision is not None:
        tool_calls.append(
            {
                "tool": "safety_gate",
                "approved": bool(getattr(decision, "approved", False)),
                "reason": getattr(decision, "reason", None),
            }
        )

    if state.get("query_id"):
        tool_calls.append(
            {
                "tool": "execution",
                "queryId": state.get("query_id"),
                "rowCount": state.get("row_count", 0),
                "truncated": state.get("truncated", False),
                "latencyMs": state.get("latency_ms", 0),
            }
        )

    return tool_calls


async def record_trace(
    state: QueryState,
    result: QueryState,
    *,
    latency_ms: int,
    cost: float = 0.0,
) -> str | None:
    """Persist a :class:`~tallyai.db.models.Trace` for a completed run (Req 12.4).

    Captures the question, generated SQL, tool calls, total run latency, and
    cost. The write is **best-effort**: any failure is logged and swallowed so
    that trace recording can never interrupt question processing (Req 12.5).
    The session is *not* committed here — like the execution log it is flushed
    within the caller's transaction so the caller controls commit boundaries.

    Returns the new ``trace_id`` on success, or ``None`` when tracing is
    skipped (no session) or fails.
    """
    db = result.get("db") or state.get("db")
    if db is None:
        return None

    trace_id = str(uuid.uuid4())
    try:
        trace = Trace(
            trace_id=trace_id,
            tenant_id=result.get("tenant_id") or state.get("tenant_id") or "default",
            question=result.get("question") or state.get("question") or "",
            generated_sql=result.get("candidate_sql"),
            tool_calls=_build_tool_calls(result),
            latency_ms=int(latency_ms),
            cost=float(result.get("cost", cost) or 0.0),
        )
        db.add(trace)
        await db.flush()
        return trace_id
    except Exception as exc:  # noqa: BLE001 — Req 12.5: never abort on trace failure
        logger.warning("orchestrator: trace recording failed: %s", exc)
        return None


async def run_question(
    state: QueryState,
    *,
    graph: Any | None = None,
    deps: OrchestratorDeps | None = None,
    cost: float = 0.0,
) -> dict:
    """Run a question through the orchestration graph and record a trace.

    This is the trace-aware entry point for processing a question. It wraps
    ``graph.ainvoke`` so that, regardless of how the run terminates (translation
    failure, safety rejection, preview pause, discard, or completion), a single
    observability trace is recorded for the run (Req 12.4).

    Trace recording is best-effort and happens *after* the answer is computed:
    a failed trace write is logged and swallowed, and the question's result is
    always returned (Req 12.5).

    Parameters
    ----------
    state:
        The initial :class:`QueryState`.
    graph:
        An already-compiled graph. When omitted, one is built from *deps*.
    deps:
        Dependency container used to build the graph when *graph* is omitted.
    cost:
        Run cost to record when the state does not carry its own ``cost`` value.

    Returns
    -------
    dict
        The final graph state (the question's result), unchanged by tracing.
    """
    if graph is None:
        graph = build_query_graph(deps)

    start = time.perf_counter()
    result = await graph.ainvoke(state)
    latency_ms = int((time.perf_counter() - start) * 1000)

    # Best-effort observability — must not interrupt the question (Req 12.5).
    await record_trace(state, result, latency_ms=latency_ms, cost=cost)

    return result
