"""
Run event pub/sub broker for streaming LangGraph progress to the UI.

The orchestration graph is multi-step (schema → semantic resolution → SQL
generation → safety gate → optional preview → execution → analytics →
reasoning → grounding). The API layer streams these node transitions to the
frontend over WebSocket / SSE so either client can show live progress
(design §"Streaming agent progress to the UI").

This module provides a transport-agnostic, in-memory pub/sub abstraction so the
stream endpoints can be driven by a real graph run *or* by a mocked run in
tests, without depending on a live graph execution.

Trust rules enforced here (Req 14, design §"Streaming agent progress"):

* **Presentation only** — events never carry credentials. Every published
  payload is run through :func:`sanitize_payload`, which redacts any
  credential-like key defensively, regardless of caller discipline.
* **No safety influence** — this is a one-way server→client push channel. The
  broker exposes no API for a subscriber to mutate run state or vote on a
  safety decision.
* **Tenant-scoped** — each run is registered against a single ``tenant_id`` and
  a subscriber must present the matching tenant to receive events. A mismatched
  or unknown run yields no subscription (mapped to HTTP 404 by the router,
  Req 14.4).
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Event schema
# ---------------------------------------------------------------------------

# Phase vocabulary surfaced to the UI. ``rejected`` lets the client reflect the
# fail-closed safety_gate / grounding_filter behavior without making any
# decision itself.
PHASE_STARTED = "started"
PHASE_COMPLETED = "completed"
PHASE_REJECTED = "rejected"
VALID_PHASES = (PHASE_STARTED, PHASE_COMPLETED, PHASE_REJECTED)

# Orchestration node names (mirror tallyai.core.orchestrator). Kept as a
# reference set; the broker does not reject unknown node names so the graph can
# evolve without breaking the stream.
ORCHESTRATION_NODES = (
    "schema_context",
    "semantic_resolution",
    "sql_generation",
    "safety_gate",
    "user_confirm",
    "execution",
    "analytics_charts",
    "reasoning_recommendations",
    "grounding_filter",
)


class RunEvent(BaseModel):
    """A single node-transition event pushed to stream subscribers.

    Matches the design event schema ``{runId, node, phase, payload?}``.
    """

    runId: str
    node: str
    phase: str
    payload: Optional[dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Credential sanitization
# ---------------------------------------------------------------------------

# Substrings that mark a dict key as credential-bearing. Matched
# case-insensitively against any key at any depth.
_CREDENTIAL_KEY_TOKENS = (
    "password",
    "passwd",
    "secret",
    "credential",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "privatekey",
    "access_key",
    "db_user",
    "db_password",
    "db_host",
)

_REDACTED = "[REDACTED]"


def _is_sensitive_key(key: Any) -> bool:
    k = str(key).lower()
    return any(token in k for token in _CREDENTIAL_KEY_TOKENS)


def sanitize_payload(value: Any) -> Any:
    """Recursively redact credential-bearing keys from a payload.

    Any mapping key whose name contains a credential token has its value
    replaced with ``"[REDACTED]"``. Lists/tuples are walked element-wise. This
    is a defensive belt-and-braces guard: the stream is presentation-only and
    must never carry credentials (Req 14, design §"Streaming agent progress").
    """
    if isinstance(value, dict):
        return {
            k: (_REDACTED if _is_sensitive_key(k) else sanitize_payload(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_payload(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Broker
# ---------------------------------------------------------------------------


class _RunChannel:
    """Per-run fan-out channel: tenant binding, subscribers, and replay buffer."""

    __slots__ = ("tenant_id", "subscribers", "history", "closed")

    def __init__(self, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self.subscribers: set[asyncio.Queue] = set()
        self.history: list[RunEvent] = []
        self.closed = False


class RunEventBroker:
    """In-memory pub/sub broker keyed by ``run_id``.

    A run must be registered (with its owning tenant) before events are
    published. Each subscriber receives the full event history followed by all
    live events, terminated by a ``None`` sentinel when the run closes — so late
    subscribers still observe the complete, ordered stream.
    """

    def __init__(self) -> None:
        self._channels: dict[str, _RunChannel] = {}

    # -- lifecycle ----------------------------------------------------------

    def register_run(self, run_id: str, tenant_id: str) -> None:
        """Bind *run_id* to *tenant_id*. Idempotent for the same tenant."""
        existing = self._channels.get(run_id)
        if existing is None:
            self._channels[run_id] = _RunChannel(tenant_id)
        elif existing.tenant_id != tenant_id:
            raise ValueError(
                f"run {run_id!r} already registered to a different tenant"
            )

    def close_run(self, run_id: str) -> None:
        """Mark a run complete and signal end-of-stream to all subscribers."""
        channel = self._channels.get(run_id)
        if channel is None or channel.closed:
            return
        channel.closed = True
        for queue in channel.subscribers:
            queue.put_nowait(None)  # sentinel → terminates each consumer

    def forget_run(self, run_id: str) -> None:
        """Drop all state for a run (call after the stream has drained)."""
        self._channels.pop(run_id, None)

    # -- publish ------------------------------------------------------------

    def publish(
        self,
        run_id: str,
        node: str,
        phase: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        tenant_id: Optional[str] = None,
    ) -> RunEvent:
        """Publish a node transition. Returns the (sanitized) stored event.

        ``payload`` is sanitized of credential-bearing keys before storage or
        delivery. Publishing to an unregistered run auto-registers it when
        ``tenant_id`` is supplied (convenience for run executors); otherwise it
        raises.
        """
        if phase not in VALID_PHASES:
            raise ValueError(
                f"invalid phase {phase!r}; expected one of {VALID_PHASES}"
            )

        channel = self._channels.get(run_id)
        if channel is None:
            if tenant_id is None:
                raise KeyError(f"run {run_id!r} is not registered")
            self.register_run(run_id, tenant_id)
            channel = self._channels[run_id]

        event = RunEvent(
            runId=run_id,
            node=node,
            phase=phase,
            payload=sanitize_payload(payload) if payload is not None else None,
        )
        channel.history.append(event)
        for queue in channel.subscribers:
            queue.put_nowait(event)
        return event

    # -- subscribe ----------------------------------------------------------

    def subscribe(self, run_id: str, tenant_id: str) -> Optional[asyncio.Queue]:
        """Subscribe to a run's stream, tenant-scoped.

        Returns a fresh queue pre-loaded with the run's event history (and a
        terminating ``None`` sentinel if the run is already closed). Returns
        ``None`` when the run is unknown or owned by a different tenant — the
        router maps this to HTTP 404 (Req 14.4).
        """
        channel = self._channels.get(run_id)
        if channel is None or channel.tenant_id != tenant_id:
            return None

        queue: asyncio.Queue = asyncio.Queue()
        # Replay history so a subscriber that connects mid/post-run still sees
        # the full ordered stream.
        for event in channel.history:
            queue.put_nowait(event)
        if channel.closed:
            queue.put_nowait(None)
        channel.subscribers.add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        """Detach a subscriber queue from a run channel."""
        channel = self._channels.get(run_id)
        if channel is not None:
            channel.subscribers.discard(queue)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_broker: Optional[RunEventBroker] = None


def get_broker() -> RunEventBroker:
    """Return the process-wide run event broker (created lazily)."""
    global _broker
    if _broker is None:
        _broker = RunEventBroker()
    return _broker
