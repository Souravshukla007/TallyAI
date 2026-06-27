"""
FastAPI router for the semantic business-metric layer.

Routes:
  GET  /api/v1/connections/{connectionId}/metrics
      → list the latest metric version for every metric owned by a tenant
  POST /api/v1/connections/{connectionId}/metrics
      → create / version a metric definition  (Req 6.1, 6.6)
  GET  /api/v1/connections/{connectionId}/metrics/{name}/versions
      → full version history for a named metric  (Req 6.6)

``tenant_id`` is passed as a query parameter for the MVP.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tallyai.core.semantic_layer import SemanticLayer
from tallyai.db.models import MetricDefinition
from tallyai.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["metrics"])

_semantic_layer = SemanticLayer()


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class MetricCreate(BaseModel):
    """Request body for ``POST /connections/{connectionId}/metrics``."""

    name: str = Field(..., description="Metric identifier (snake_case)")
    formula: str = Field(..., description="SQL expression / aggregate formula")
    condition: Optional[str] = Field(None, description="Optional WHERE-clause fragment")
    grain: Optional[str] = Field(None, description="Optional grain / table hint")
    description: str = Field("", description="Human-readable description")
    tenant_id: str = Field(..., description="Owning tenant identifier")


class MetricResponse(BaseModel):
    """A single metric at its latest version."""

    name: str
    formula: str
    condition: Optional[str]
    grain: Optional[str]
    description: str
    version: int


class MetricVersionResponse(BaseModel):
    """A single row in the version history of a metric."""

    version: int
    formula: str
    created_at: str


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get(
    "/connections/{connectionId}/metrics",
    response_model=list[MetricResponse],
    summary="List latest metric definitions for a tenant",
)
async def list_metrics(
    connectionId: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[MetricResponse]:
    """Return one row per metric (the highest version) for *tenant_id*.

    *connectionId* is accepted in the path to keep the URL namespace
    consistent; it is not used to filter metrics (metrics are per-tenant,
    not per-connection).
    """
    stmt = select(MetricDefinition).where(
        MetricDefinition.tenant_id == tenant_id
    )
    result = await db.execute(stmt)
    all_rows = list(result.scalars().all())

    # Keep only the latest version per name.
    latest: dict[str, MetricDefinition] = {}
    for row in all_rows:
        existing = latest.get(row.name)
        if existing is None or row.version > existing.version:
            latest[row.name] = row

    return [
        MetricResponse(
            name=m.name,
            formula=m.formula,
            condition=m.condition,
            grain=m.grain,
            description=m.description,
            version=m.version,
        )
        for m in sorted(latest.values(), key=lambda r: r.name)
    ]


@router.post(
    "/connections/{connectionId}/metrics",
    response_model=MetricResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create or update a metric definition (creates a new version)",
)
async def create_metric(
    connectionId: str,
    body: MetricCreate,
    db: AsyncSession = Depends(get_db),
) -> MetricResponse:
    """Upsert a metric for *body.tenant_id*, incrementing the version counter.

    The previous version row is updated with ``superseded_by`` pointing at
    the new version (Req 6.1, 6.6).
    """
    result = await _semantic_layer.upsert_metric(
        name=body.name,
        formula=body.formula,
        condition=body.condition,
        grain=body.grain,
        description=body.description,
        tenant_id=body.tenant_id,
        db=db,
    )

    new_version = result["version"]

    # Fetch the newly created row to build the response.
    stmt = select(MetricDefinition).where(
        MetricDefinition.name == body.name,
        MetricDefinition.tenant_id == body.tenant_id,
        MetricDefinition.version == new_version,
    )
    row_result = await db.execute(stmt)
    new_row: MetricDefinition | None = row_result.scalars().first()

    if new_row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve newly created metric",
        )

    return MetricResponse(
        name=new_row.name,
        formula=new_row.formula,
        condition=new_row.condition,
        grain=new_row.grain,
        description=new_row.description,
        version=new_row.version,
    )


@router.get(
    "/connections/{connectionId}/metrics/{name}/versions",
    response_model=list[MetricVersionResponse],
    summary="Full version history for a named metric",
)
async def get_metric_versions(
    connectionId: str,
    name: str,
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
) -> list[MetricVersionResponse]:
    """Return all historical versions for metric *name* (Req 6.6).

    Results are ordered by version ascending.
    """
    versions = await _semantic_layer.get_metric_versions(
        name=name,
        tenant_id=tenant_id,
        db=db,
    )

    if not versions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No metric named '{name}' found for this tenant",
        )

    return [MetricVersionResponse(**v) for v in versions]
