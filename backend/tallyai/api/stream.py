"""
FastAPI router for streaming run progress to the UI.

Routes:
  WS  /api/v1/runs/{runId}/stream  — WebSocket channel of node transitions
  GET /api/v1/runs/{runId}/events  — SSE fallback carrying the same events

Both transports carry the identical event schema
``{runId, node, phase, payload?}`` (design §"Streaming agent progress to the
UI"). The stream is presentation-only: it never carries credentials, never
lets the client influence the safety decision, and is tenant-scoped exactly
like the REST endpoints (Req 14). The authoritative results remain the REST
``/results`` and ``/reasoning`` payloads.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from starlette.websockets import WebSocket, WebSocketDisconnect

from tallyai.services.run_events import RunEvent, RunEventBroker, get_broker

router = APIRouter(tags=["stream"])


def _format_sse(event: RunEvent) -> str:
    """Serialize a RunEvent as a single SSE frame.

    Uses the node name as the SSE ``event:`` type and the full event schema as
    the JSON ``data:`` body so consumers can switch on either.
    """
    data = json.dumps(event.model_dump(), separators=(",", ":"))
    return f"event: {event.node}\ndata: {data}\n\n"


@router.get(
    "/runs/{runId}/events",
    summary="SSE fallback stream of run node transitions (tenant-scoped)",
)
async def stream_run_events_sse(
    runId: str,
    request: Request,
    tenant_id: str = Query(...),
) -> StreamingResponse:
    """Server-Sent Events stream for *runId*, scoped to ``tenant_id``.

    ``tenant_id`` is a query parameter for the MVP; production resolves it from
    the bearer token. An unknown run or a cross-tenant request yields a stream
    that immediately closes with a single ``error`` frame and HTTP 404 status
    (Req 14.4).
    """
    broker: RunEventBroker = get_broker()
    queue = broker.subscribe(runId, tenant_id)

    if queue is None:
        # Tenant-scoped denial: no such run for this tenant (Req 14.4).
        async def _denied():
            payload = {"runId": runId, "error": "run not found"}
            yield f"event: error\ndata: {json.dumps(payload)}\n\n"

        return StreamingResponse(
            _denied(), media_type="text/event-stream", status_code=404
        )

    async def event_generator():
        try:
            while True:
                # Stop promptly if the client disconnects.
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # SSE keep-alive comment; keeps proxies from closing idle
                    # connections without emitting a spurious event.
                    yield ": keep-alive\n\n"
                    continue
                if item is None:  # end-of-run sentinel
                    break
                yield _format_sse(item)
        finally:
            broker.unsubscribe(runId, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.websocket("/runs/{runId}/stream")
async def stream_run_events_ws(
    websocket: WebSocket,
    runId: str,
    tenant_id: str = Query(...),
) -> None:
    """WebSocket stream for *runId*, scoped to ``tenant_id``.

    Carries the same ``{runId, node, phase, payload?}`` events as the SSE
    fallback. The channel is one-way (server→client); the server never reads
    application state from the socket, so a client cannot influence the safety
    decision (presentation-only, Req 14).
    """
    broker: RunEventBroker = get_broker()
    queue = broker.subscribe(runId, tenant_id)

    if queue is None:
        # Reject before accepting the handshake (cross-tenant / unknown run).
        await websocket.close(code=4404)
        return

    await websocket.accept()
    try:
        while True:
            item = await queue.get()
            if item is None:  # end-of-run sentinel
                break
            await websocket.send_json(item.model_dump())
        await websocket.close()
    except WebSocketDisconnect:
        pass
    finally:
        broker.unsubscribe(runId, queue)
