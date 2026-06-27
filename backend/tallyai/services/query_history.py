"""
QueryHistory service — persists and retrieves per-user, per-connection
question history.

Req 13.1: A submitted question is persisted with its associated executed
          query identifiers for that user and connection.
Req 13.2: Listing returns the persisted questions/queries for that user and
          connection.
Req 13.3: Searching returns history entries matching the search term.
Req 14.2, 14.4: All reads and writes are scoped to the requesting tenant;
                cross-tenant access returns no entries.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tallyai.db.models import HistoryEntry


class QueryHistory:
    """Service class for managing query history entries."""

    @staticmethod
    async def append(
        user_id: str,
        connection_id: str,
        question: str,
        query_ids: list[str],
        tenant_id: str,
        db: AsyncSession,
    ) -> str:
        """Persist a history entry for a submitted question (Req 13.1).

        Parameters
        ----------
        user_id:
            Identifier of the user who submitted the question.
        connection_id:
            Connection the question was asked against.
        question:
            The natural-language question text.
        query_ids:
            Identifiers of the executed queries associated with the question.
        tenant_id:
            Tenant the entry belongs to (Req 14.2).
        db:
            Active async SQLAlchemy session.

        Returns
        -------
        str
            The ``history_id`` of the persisted entry.
        """
        history_id = str(uuid.uuid4())

        entry = HistoryEntry(
            history_id=history_id,
            tenant_id=tenant_id,
            user_id=user_id,
            connection_id=connection_id,
            question=question,
            query_ids=list(query_ids),
        )

        db.add(entry)
        await db.flush()  # Persist within the current transaction.
        return history_id

    @staticmethod
    async def list(
        user_id: str,
        connection_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[HistoryEntry]:
        """Return history entries for a user/connection (Req 13.2).

        Results are scoped to ``tenant_id`` so a tenant can never observe
        another tenant's history (Req 14.2, 14.4) and are ordered most-recent
        first.
        """
        stmt = (
            select(HistoryEntry)
            .where(
                HistoryEntry.tenant_id == tenant_id,
                HistoryEntry.user_id == user_id,
                HistoryEntry.connection_id == connection_id,
            )
            .order_by(HistoryEntry.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def search(
        user_id: str,
        connection_id: str,
        term: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> list[HistoryEntry]:
        """Return history entries whose question matches ``term`` (Req 13.3).

        Matching is a case-insensitive substring match on the question text.
        Results remain tenant-scoped (Req 14.2, 14.4) and ordered most-recent
        first. An empty term matches all of the user's entries.
        """
        pattern = f"%{term}%"
        stmt = (
            select(HistoryEntry)
            .where(
                HistoryEntry.tenant_id == tenant_id,
                HistoryEntry.user_id == user_id,
                HistoryEntry.connection_id == connection_id,
                HistoryEntry.question.ilike(pattern),
            )
            .order_by(HistoryEntry.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())
