"""
FastAPI router for the Eval_Harness (correctness evaluation).

Routes:
  POST /api/v1/eval/runs
      → start an eval run over a labeled set (Req 12.1, 12.2, 12.3)
      An empty labeled set returns ``400 {"error": "at least one labeled pair
      required"}`` and produces no score (Req 12.3).
  GET  /api/v1/eval/runs/{evalRunId}/report
      → retrieve the accuracy report for a completed run (Req 12.2, 12.4)

``tenant_id`` is passed as a query parameter for the MVP; production would
resolve it from the bearer token.

Eval-run reports are held in an in-process registry keyed by ``evalRunId``.
The labeled set referenced by ``labeledSetId`` is resolved from the shipped
golden set (``backend/metrics/eval_golden_set.json``); an unknown or empty set
resolves to zero pairs and is rejected per Req 12.3.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from tallyai.db.session import get_db
from tallyai.services.eval_harness import (
    EmptyLabeledSetError,
    EvalHarness,
    LabeledPair,
    load_golden_set,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["eval"])

# In-process registry of completed eval runs: evalRunId -> report dict.
_EVAL_RUNS: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Dependencies (overridable in tests)
# ---------------------------------------------------------------------------


def get_eval_harness() -> EvalHarness:
    """Provide the eval harness (default: production NL_Translator)."""
    return EvalHarness()


def resolve_labeled_set(labeled_set_id: str) -> list[LabeledPair]:
    """Resolve *labeled_set_id* to its labeled pairs (Req 12.1).

    The shipped golden set is matched by its ``labeledSetId``. Any other id
    resolves to an empty list, which the run endpoint rejects per Req 12.3.
    """
    try:
        golden_id, pairs = load_golden_set()
    except Exception as exc:  # noqa: BLE001
        logger.warning("resolve_labeled_set: failed to load golden set: %s", exc)
        return []
    if labeled_set_id == golden_id:
        return pairs
    return []


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class EvalRunRequest(BaseModel):
    """Request body for ``POST /eval/runs``."""

    labeledSetId: str = Field(..., description="Identifier of the labeled set to evaluate")


class EvalRunResponse(BaseModel):
    """Response body for ``POST /eval/runs``."""

    evalRunId: str
    status: str


class PairReport(BaseModel):
    pairId: str
    question: str
    expectedSql: str
    generatedSql: Optional[str]
    match: bool


class EvalReportResponse(BaseModel):
    """Response body for ``GET /eval/runs/{evalRunId}/report``."""

    evalRunId: str
    accuracy: float
    perPair: list[PairReport]
    traceRefs: list[str]


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post(
    "/eval/runs",
    response_model=EvalRunResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run the eval harness over a labeled NL->SQL set",
)
async def create_eval_run(
    body: EvalRunRequest,
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
    harness: EvalHarness = Depends(get_eval_harness),
) -> EvalRunResponse:
    """Evaluate the labeled set and store the resulting report (Req 12.2).

    Returns ``400`` with ``"at least one labeled pair required"`` when the
    referenced labeled set is empty (Req 12.3).
    """
    pairs = resolve_labeled_set(body.labeledSetId)

    try:
        report = await harness.run(
            pairs,
            tenant_id=tenant_id,
            db=db,
            labeled_set_id=body.labeledSetId,
        )
    except EmptyLabeledSetError as exc:
        # Req 12.3 — empty labeled set: 400, no score.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    eval_run_id = str(uuid.uuid4())
    _EVAL_RUNS[eval_run_id] = report.to_dict()

    return EvalRunResponse(evalRunId=eval_run_id, status="completed")


@router.get(
    "/eval/runs/{evalRunId}/report",
    response_model=EvalReportResponse,
    summary="Retrieve the accuracy report for a completed eval run",
)
async def get_eval_report(evalRunId: str) -> EvalReportResponse:
    """Return the stored accuracy report for *evalRunId* (Req 12.2, 12.4)."""
    report = _EVAL_RUNS.get(evalRunId)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No eval run found for evalRunId={evalRunId!r}",
        )

    return EvalReportResponse(
        evalRunId=evalRunId,
        accuracy=report["accuracy"],
        perPair=[PairReport(**p) for p in report["perPair"]],
        traceRefs=report["traceRefs"],
    )
