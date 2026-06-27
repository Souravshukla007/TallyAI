"""
FastAPI router for schema introspection endpoints.

Routes:
  GET  /api/v1/connections/{connectionId}/schema         → get cached schema
  POST /api/v1/connections/{connectionId}/schema/refresh → refresh schema

Requirements: 5.2, 5.3, 5.4, 5.5
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tallyai.db.session import get_db
from tallyai.services.schema_introspector import SchemaIntrospector

logger = logging.getLogger(__name__)

router = APIRouter(tags=["schema"])

_introspector = SchemaIntrospector()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class SchemaResponse(BaseModel):
    """Response body for the cached schema endpoint."""

    schema_version: str
    tables: list[Any]
    introspected_at: str


class SchemaRefreshResponse(BaseModel):
    """Response body for the schema refresh endpoint."""

    refreshed: bool
    schema_version: Optional[str] = None
    tables: Optional[list[Any]] = None
    introspected_at: Optional[str] = None
    reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get(
    "/connections/{connectionId}/schema",
    response_model=SchemaResponse,
    summary="Return the cached schema for a connection (Req 5.2, 5.3)",
)
async def get_schema(
    connectionId: str,
    tenant_id: str = Query(..., description="Owning tenant identifier"),
    db: AsyncSession = Depends(get_db),
) -> SchemaResponse:
    """Serve the schema from cache without connecting to the target DB.

    Returns HTTP 404 when no cached schema exists for the given connection.
    """
    cached = await _introspector.get_cached(
        connection_id=connectionId,
        tenant_id=tenant_id,
        db=db,
    )
    if cached is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No cached schema found for connection '{connectionId}'.",
        )
    return SchemaResponse(**cached)


@router.post(
    "/connections/{connectionId}/schema/refresh",
    response_model=SchemaRefreshResponse,
    summary="Re-introspect and refresh the cached schema (Req 5.4, 5.5)",
)
async def refresh_schema(
    connectionId: str,
    host: str = Query(...),
    port: int = Query(5432),
    database: str = Query(...),
    user: str = Query(...),
    password: str = Query(...),
    tenant_id: str = Query(..., description="Owning tenant identifier"),
    db: AsyncSession = Depends(get_db),
) -> SchemaRefreshResponse:
    """Re-connect to the target DB and rebuild the schema cache.

    On failure the existing cache is retained and the response contains
    ``refreshed=False`` with a human-readable ``reason``.
    """
    result = await _introspector.refresh(
        conn_id=connectionId,
        tenant_id=tenant_id,
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        db=db,
    )
    return SchemaRefreshResponse(**result)
