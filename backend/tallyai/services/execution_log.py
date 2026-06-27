"""
ExecutionLog service — wraps append-only writes and reads of ExecutionLogEntry.

Req 9.1: Every executed query is logged verbatim.
Req 14.2, 14.4: All reads are scoped to the requesting tenant; cross-tenant
                 access returns None.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tallyai.db.models import ExecutionLogEntry


class ExecutionLog:
    """Service class for managing execution log entries."""

    @staticmethod
    async def record(entry_data: dict, db: AsyncSession) -> str:
        """Create and persist an ExecutionLogEntry row.

        Parameters
        ----------
        entry_data:
            Dict with keys: query_id, tenant_id, connection_id, user_id,
            exact_sql, parameters, result_ref, row_count, truncated, latency_ms.
            If ``query_id`` is absent or None a new UUID is generated.
        db:
            Active async SQLAlchemy session.

        Returns
        -------
        str
            The ``query_id`` of the persisted entry.
        """
        query_id: str = entry_data.get("query_id") or str(uuid.uuid4())

        entry = ExecutionLogEntry(
            query_id=query_id,
            tenant_id=entry_data["tenant_id"],
            connection_id=entry_data["connection_id"],
            user_id=entry_data["user_id"],
            exact_sql=entry_data["exact_sql"],
            parameters=entry_data.get("parameters", {}),
            result_ref=entry_data.get("result_ref", ""),
            row_count=entry_data.get("row_count", 0),
            truncated=entry_data.get("truncated", False),
            latency_ms=entry_data.get("latency_ms", 0),
        )

        db.add(entry)
        await db.flush()  # Persist within the current transaction.
        return query_id

    @staticmethod
    async def get(
        query_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> ExecutionLogEntry | None:
        """Fetch a log entry filtered by (query_id, tenant_id).

        Cross-tenant access returns None (Req 14.4).

        Parameters
        ----------
        query_id:
            Primary key of the log entry.
        tenant_id:
            Tenant making the request.  If it does not match the stored
            tenant_id the entry is treated as not found.
        db:
            Active async SQLAlchemy session.
        """
        stmt = select(ExecutionLogEntry).where(
            ExecutionLogEntry.query_id == query_id,
            ExecutionLogEntry.tenant_id == tenant_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
