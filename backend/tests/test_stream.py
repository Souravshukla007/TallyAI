"""
Tests for run progress streaming (Task 13).

Covers the WebSocket endpoint ``WS /api/v1/runs/{runId}/stream`` and the SSE
fallback ``GET /api/v1/runs/{runId}/events``, both carrying the design event
schema ``{runId, node, phase, payload?}``.

Verifies:
- SSE events arrive in declared order for a mocked run
- a WebSocket client receives the same events in the same order
- no credential data appears in any event payload (sanitized at publish)
- the stream is tenant-scoped (cross-tenant / unknown run is denied, Req 14)
- the broker pub/sub abstraction (history replay, sanitization) in isolation
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tallyai.main import app
from tallyai.services.run_events import (
    PHASE_COMPLETED,
    PHASE_REJECTED,
    PHASE_STARTED,
    RunEventBroker,
    get_broker,
    sanitize_payload,
)

TENANT_A = "tenant-A"
TENANT_B = "tenant-B"


# ---------------------------------------------------------------------------
# A mocked run: an ordered sequence of node transitions, including a payload
# that deliberately carries credential-like keys to prove they are redacted.
# ---------------------------------------------------------------------------

MOCKED_RUN = [
    ("schema_context", PHASE_STARTED, None),
    ("schema_context", PHASE_COMPLETED, {"tables": 3}),
    ("semantic_resolution", PHASE_STARTED, None),
    ("semantic_resolution", PHASE_COMPLETED, {"metrics": ["revenue"]}),
    ("sql_generation", PHASE_STARTED, None),
    # Payload laced with secrets — must never reach the client verbatim.
    (
        "sql_generation",
        PHASE_COMPLETED,
        {
            "generatedSql": "SELECT 1",
            "db_password": "hunter2",
            "credentials": {"password": "topsecret", "token": "abc123"},
            "db_user": "reader",
        },
    ),
    ("safety_gate", PHASE_STARTED, None),
    ("safety_gate", PHASE_COMPLETED, {"approved": True}),
    ("execution", PHASE_STARTED, None),
    ("execution", PHASE_COMPLETED, {"rowCount": 2}),
    ("analytics_charts", PHASE_COMPLETED, {"chartable": True}),
    ("reasoning_recommendations", PHASE_COMPLETED, {"claims": 1}),
    ("grounding_filter", PHASE_COMPLETED, {"suppressed": 0}),
]

EXPECTED_ORDER = [(node, phase) for node, phase, _ in MOCKED_RUN]

# Secret values that must never appear anywhere in a serialized event.
SECRET_VALUES = ("hunter2", "topsecret", "abc123")


def _seed_mocked_run(run_id: str, tenant_id: str = TENANT_A) -> None:
    """Register a run and publish the full mocked transition sequence, then close."""
    broker = get_broker()
    broker.register_run(run_id, tenant_id)
    for node, phase, payload in MOCKED_RUN:
        broker.publish(run_id, node, phase, payload)
    broker.close_run(run_id)


def _parse_sse(text: str) -> list[dict]:
    """Extract the JSON object from each ``data:`` line of an SSE body."""
    events: list[dict] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            body = line[len("data:") :].strip()
            if body and not body.startswith(":"):
                events.append(json.loads(body))
    return events


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------


def test_sse_events_arrive_in_declared_order():
    run_id = "run-sse-order"
    _seed_mocked_run(run_id)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/v1/runs/{run_id}/events", params={"tenant_id": TENANT_A}
        )

    assert resp.status_code == 200
    events = _parse_sse(resp.text)

    assert [(e["node"], e["phase"]) for e in events] == EXPECTED_ORDER
    assert all(e["runId"] == run_id for e in events)


def test_sse_unknown_or_cross_tenant_run_denied():
    run_id = "run-sse-tenant"
    _seed_mocked_run(run_id, tenant_id=TENANT_A)

    with TestClient(app) as client:
        # Wrong tenant → denied (Req 14.4).
        resp = client.get(
            f"/api/v1/runs/{run_id}/events", params={"tenant_id": TENANT_B}
        )
    assert resp.status_code == 404
    # No run events leak; only the error frame.
    assert all(e.get("error") for e in _parse_sse(resp.text))


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


def test_websocket_receives_same_events_as_sse():
    run_id = "run-ws-order"
    _seed_mocked_run(run_id)

    received: list[dict] = []
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/runs/{run_id}/stream?tenant_id={TENANT_A}"
        ) as ws:
            try:
                while True:
                    received.append(ws.receive_json())
            except WebSocketDisconnect:
                pass

    assert [(e["node"], e["phase"]) for e in received] == EXPECTED_ORDER
    assert all(e["runId"] == run_id for e in received)


def test_websocket_cross_tenant_run_denied():
    run_id = "run-ws-tenant"
    _seed_mocked_run(run_id, tenant_id=TENANT_A)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                f"/api/v1/runs/{run_id}/stream?tenant_id={TENANT_B}"
            ) as ws:
                ws.receive_json()


# ---------------------------------------------------------------------------
# Credential confidentiality across both transports (Req 14)
# ---------------------------------------------------------------------------


def test_no_credential_data_in_sse_payloads():
    run_id = "run-sse-creds"
    _seed_mocked_run(run_id)

    with TestClient(app) as client:
        resp = client.get(
            f"/api/v1/runs/{run_id}/events", params={"tenant_id": TENANT_A}
        )

    # Raw stream text must not contain any secret value anywhere.
    for secret in SECRET_VALUES:
        assert secret not in resp.text

    # The legitimate non-secret field still flows through.
    assert "SELECT 1" in resp.text


def test_no_credential_data_in_websocket_payloads():
    run_id = "run-ws-creds"
    _seed_mocked_run(run_id)

    received: list[dict] = []
    with TestClient(app) as client:
        with client.websocket_connect(
            f"/api/v1/runs/{run_id}/stream?tenant_id={TENANT_A}"
        ) as ws:
            try:
                while True:
                    received.append(ws.receive_json())
            except WebSocketDisconnect:
                pass

    serialized = json.dumps(received)
    for secret in SECRET_VALUES:
        assert secret not in serialized
    assert "SELECT 1" in serialized


# ---------------------------------------------------------------------------
# Broker / sanitizer unit tests
# ---------------------------------------------------------------------------


def test_sanitize_payload_redacts_nested_credentials():
    payload = {
        "db_password": "p",
        "ok": "keep",
        "nested": {"api_key": "k", "value": 1},
        "items": [{"secret": "s"}, {"label": "fine"}],
    }
    cleaned = sanitize_payload(payload)

    assert cleaned["db_password"] == "[REDACTED]"
    assert cleaned["ok"] == "keep"
    assert cleaned["nested"]["api_key"] == "[REDACTED]"
    assert cleaned["nested"]["value"] == 1
    assert cleaned["items"][0]["secret"] == "[REDACTED]"
    assert cleaned["items"][1]["label"] == "fine"


def test_broker_rejects_invalid_phase():
    broker = RunEventBroker()
    broker.register_run("r1", TENANT_A)
    with pytest.raises(ValueError):
        broker.publish("r1", "execution", "bogus_phase")


def test_broker_publish_requires_registration_without_tenant():
    broker = RunEventBroker()
    with pytest.raises(KeyError):
        broker.publish("unregistered", "execution", PHASE_STARTED)


def test_broker_subscribe_is_tenant_scoped():
    broker = RunEventBroker()
    broker.register_run("r2", TENANT_A)
    broker.publish("r2", "safety_gate", PHASE_REJECTED, {"reason": "non-select"})
    broker.close_run("r2")

    assert broker.subscribe("r2", TENANT_B) is None  # cross-tenant denied
    assert broker.subscribe("missing", TENANT_A) is None  # unknown run

    queue = broker.subscribe("r2", TENANT_A)
    assert queue is not None
    first = queue.get_nowait()
    assert first.node == "safety_gate"
    assert first.phase == PHASE_REJECTED
    assert queue.get_nowait() is None  # closed → sentinel replayed
