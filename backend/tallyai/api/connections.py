"""
FastAPI router for database connection management.

Routes:
  POST /api/v1/connections                        → create_connection
  POST /api/v1/connections/{connectionId}/test   → test_connection

Req 1.1–1.7.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tallyai.db.models import TenantConnection
from tallyai.db.session import get_db
from tallyai.services.connection_manager import ConnectionManager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["connections"])

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ConnectionCreate(BaseModel):
    """Request body for ``POST /connections``."""

    host: str = Field(..., description="Database host")
    port: int = Field(5432, description="Database port")
    database: str = Field(..., description="Database name")
    role: str = Field(..., description="Read-only role / username to connect as")
    credentials: dict = Field(
        ...,
        description="Connection credentials (e.g. {\"user\": \"...\", \"password\": \"...\"})",
    )
    tenant_id: str = Field(..., description="Owning tenant identifier")


class ConnectionCreateResponse(BaseModel):
    """Response body for a successful ``POST /connections``."""

    ok: bool
    connection_id: Optional[str] = None
    read_only: Optional[bool] = None
    # Error fields — present only when ok=False.
    error: Optional[str] = None
    privileges: Optional[list[str]] = None
    detail: Optional[str] = None


class TestConnectionResponse(BaseModel):
    """Response body for ``POST /connections/{connectionId}/test``."""

    ok: bool
    reason: Optional[str] = None


class ConnectionListItem(BaseModel):
    """One connection as the UI's ``Connection`` type expects it."""

    id: str
    name: str
    engine: str
    host: str
    status: str
    readOnly: bool


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

_manager = ConnectionManager()


@router.get(
    "/connections",
    response_model=list[ConnectionListItem],
    summary="List the calling tenant's registered connections",
)
async def list_connections(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[ConnectionListItem]:
    """Return all active connections owned by ``tenant_id``.

    ``tenant_id`` is supplied as a query parameter for the MVP (production
    resolves it from the bearer token). Results are scoped to that tenant so a
    caller can never see another tenant's connections (Req 14).
    """
    result = await db.execute(
        select(TenantConnection)
        .where(TenantConnection.tenant_id == tenant_id)
        .order_by(TenantConnection.created_at.desc())
    )
    rows = result.scalars().all()
    return [
        ConnectionListItem(
            id=tc.connection_id,
            name=tc.database or tc.host,
            engine="PostgreSQL",
            host=tc.host,
            status="Connected" if tc.is_active else "Error",
            readOnly=True,
        )
        for tc in rows
    ]


@router.post(
    "/connections",
    response_model=ConnectionCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register and validate a new database connection",
)
async def create_connection(
    body: ConnectionCreate,
    db: AsyncSession = Depends(get_db),
) -> ConnectionCreateResponse:
    """Attempt to connect with the supplied credentials, run privilege
    detection, and persist the connection if read-only.

    Returns HTTP 201 on success, HTTP 400 on any failure.
    """
    result = await _manager.create_connection(
        host=body.host,
        port=body.port,
        database=body.database,
        role=body.role,
        credentials=body.credentials,
        tenant_id=body.tenant_id,
        db=db,
    )

    if not result["ok"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result,
        )

    return ConnectionCreateResponse(**result)


@router.post(
    "/connections/{connectionId}/test",
    response_model=TestConnectionResponse,
    summary="Re-validate an existing connection",
)
async def test_connection(
    connectionId: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
) -> TestConnectionResponse:
    """Re-fetch stored credentials and re-run privilege detection.

    ``tenant_id`` is passed as a query parameter for the MVP.  Production
    would resolve it from the bearer token.
    """
    result = await _manager.test_connection(
        connection_id=connectionId,
        tenant_id=tenant_id,
        db=db,
    )
    return TestConnectionResponse(**result)
