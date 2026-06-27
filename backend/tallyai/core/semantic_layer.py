"""
Semantic business layer for TallyAI.

Provides metric resolution (mapping natural-language questions to canonical
metric definitions) and CRUD operations for versioned MetricDefinitions.

Req 6.1, 6.2, 6.4, 6.5, 6.6
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tallyai.db.models import MetricDefinition

logger = logging.getLogger(__name__)


class SemanticLayer:
    """Resolve natural-language terms to versioned metric definitions and
    manage the lifecycle of those definitions."""

    # ------------------------------------------------------------------
    # Resolution (Req 6.2, 6.4, 6.5)
    # ------------------------------------------------------------------

    async def resolve(
        self,
        question: str,
        connection_id: str,
        schema_version: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Map terms in *question* to MetricDefinition rows for *tenant_id*.

        - Only the **latest** (highest version) row per metric name is
          considered (Req 6.6).
        - Each metric whose human-readable name appears in *question* is
          included; unrecognised terms are silently omitted (Req 6.5).
        - Given the same inputs and unchanged DB state the result is
          deterministic (Req 6.4).

        Returns
        -------
        list[dict]
            Each element contains ``term``, ``name``, ``formula``,
            ``condition``, ``description``, ``version``.
        """
        question_lower = question.lower()

        # Fetch all metric rows for this tenant.
        stmt = select(MetricDefinition).where(
            MetricDefinition.tenant_id == tenant_id
        )
        result = await db.execute(stmt)
        all_rows: list[MetricDefinition] = list(result.scalars().all())

        # Keep only the latest version per (name, tenant_id).
        latest: dict[str, MetricDefinition] = {}
        for row in all_rows:
            existing = latest.get(row.name)
            if existing is None or row.version > existing.version:
                latest[row.name] = row

        # Filter to metrics whose human-readable name appears in the question.
        matched: list[dict[str, Any]] = []
        for name, metric in sorted(latest.items()):  # sort for determinism
            human_name = name.lower().replace("_", " ")
            if human_name in question_lower:
                matched.append(
                    {
                        "term": human_name,
                        "name": metric.name,
                        "formula": metric.formula,
                        "condition": metric.condition,
                        "description": metric.description,
                        "version": metric.version,
                    }
                )

        return matched

    # ------------------------------------------------------------------
    # Upsert (Req 6.1, 6.6)
    # ------------------------------------------------------------------

    async def upsert_metric(
        self,
        name: str,
        formula: str,
        condition: str | None,
        grain: str | None,
        description: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Create a new version of *name* for *tenant_id*.

        If a prior version exists its ``superseded_by`` field is set to the
        new version number (Req 6.6).

        Returns
        -------
        dict
            ``{"name": str, "version": int}``
        """
        # Find the current latest version row.
        stmt = (
            select(MetricDefinition)
            .where(
                MetricDefinition.name == name,
                MetricDefinition.tenant_id == tenant_id,
            )
            .order_by(MetricDefinition.version.desc())
        )
        result = await db.execute(stmt)
        latest_row: MetricDefinition | None = result.scalars().first()

        new_version = 1 if latest_row is None else latest_row.version + 1

        new_metric = MetricDefinition(
            name=name,
            tenant_id=tenant_id,
            formula=formula,
            condition=condition,
            grain=grain,
            description=description,
            version=new_version,
            superseded_by=None,
        )
        db.add(new_metric)

        # Update the previous row to point at the new version.
        if latest_row is not None:
            latest_row.superseded_by = new_version

        await db.flush()
        return {"name": name, "version": new_version}

    # ------------------------------------------------------------------
    # Version history
    # ------------------------------------------------------------------

    async def get_metric_versions(
        self,
        name: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[dict[str, Any]]:
        """Return all historical versions for *name* ordered ascending.

        Returns
        -------
        list[dict]
            Each element contains ``version``, ``formula``, ``created_at``.
        """
        stmt = (
            select(MetricDefinition)
            .where(
                MetricDefinition.name == name,
                MetricDefinition.tenant_id == tenant_id,
            )
            .order_by(MetricDefinition.version.asc())
        )
        result = await db.execute(stmt)
        rows: list[MetricDefinition] = list(result.scalars().all())

        return [
            {
                "version": row.version,
                "formula": row.formula,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # YAML seeding
    # ------------------------------------------------------------------

    async def load_yaml_metrics(
        self,
        yaml_path: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> int:
        """Parse *yaml_path* and upsert every metric into the DB.

        Returns the number of metrics upserted.
        """
        path = Path(yaml_path)
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        metrics: dict[str, Any] = data.get("metrics", {})
        count = 0
        for name, defn in metrics.items():
            await self.upsert_metric(
                name=name,
                formula=defn["formula"],
                condition=defn.get("condition"),
                grain=defn.get("table"),  # 'table' maps to grain for now
                description=defn.get("description", ""),
                tenant_id=tenant_id,
                db=db,
            )
            count += 1

        return count
