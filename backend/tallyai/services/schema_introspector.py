"""
Schema introspector service for TallyAI.

Connects to a target PostgreSQL database via asyncpg, queries the
information_schema, and caches the resulting table/column/FK structure
in the CachedSchema table.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

import asyncpg
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tallyai.db.models import CachedSchema

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQL queries executed against the *target* database (not the app DB)
# ---------------------------------------------------------------------------

_COLUMNS_QUERY = """
SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position
"""

_FK_QUERY = """
SELECT kcu.table_name, kcu.column_name,
       ccu.table_name  AS foreign_table_name,
       ccu.column_name AS foreign_column_name
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
     ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
     ON ccu.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema = 'public'
"""


class SchemaIntrospector:
    """Service that introspects a remote PostgreSQL schema and caches it."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def introspect(
        self,
        conn_id: str,
        tenant_id: str,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        db: AsyncSession,
    ) -> dict:
        """Connect to the target DB, build the schema structure, persist it.

        Returns:
            {"schema_version": str, "tables": [...], "introspected_at": str}
        """
        tables = await self._fetch_schema(host, port, database, user, password)
        schema_version = str(uuid.uuid4())[:8]
        tables_json = json.dumps(tables)
        now = datetime.utcnow()

        # Upsert: if a CachedSchema row already exists for (connection_id,
        # tenant_id), update it; otherwise insert a new row.
        result = await db.execute(
            select(CachedSchema).where(
                CachedSchema.connection_id == conn_id,
                CachedSchema.tenant_id == tenant_id,
            )
        )
        existing: CachedSchema | None = result.scalars().first()

        if existing is not None:
            existing.schema_version = schema_version
            existing.tables_json = tables_json
            existing.introspected_at = now
            db.add(existing)
        else:
            row = CachedSchema(
                connection_id=conn_id,
                tenant_id=tenant_id,
                schema_version=schema_version,
                tables_json=tables_json,
                introspected_at=now,
            )
            db.add(row)

        await db.commit()

        return {
            "schema_version": schema_version,
            "tables": tables,
            "introspected_at": now.isoformat(),
        }

    async def get_cached(
        self,
        connection_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict | None:
        """Return the most recent cached schema for (connection_id, tenant_id).

        Returns None when no cache entry exists (Req 5.3).
        """
        result = await db.execute(
            select(CachedSchema)
            .where(
                CachedSchema.connection_id == connection_id,
                CachedSchema.tenant_id == tenant_id,
            )
            .order_by(CachedSchema.introspected_at.desc())
            .limit(1)
        )
        row: CachedSchema | None = result.scalars().first()
        if row is None:
            return None

        return {
            "schema_version": row.schema_version,
            "tables": json.loads(row.tables_json),
            "introspected_at": row.introspected_at.isoformat(),
        }

    async def refresh(
        self,
        conn_id: str,
        tenant_id: str,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        db: AsyncSession,
    ) -> dict:
        """Re-introspect the schema; on failure keep the old cache intact.

        On success: {"refreshed": True, "schema_version": ..., "tables": [...]}
        On failure: {"refreshed": False, "reason": <error message>}   (Req 5.5)
        """
        try:
            result = await self.introspect(
                conn_id=conn_id,
                tenant_id=tenant_id,
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
                db=db,
            )
            return {"refreshed": True, **result}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Schema refresh failed for connection %s: %s", conn_id, exc)
            return {"refreshed": False, "reason": str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_schema(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
    ) -> list[dict]:
        """Open an asyncpg connection, query information_schema, and return
        a list of table dicts.

        Each dict: {"name": str, "columns": [...], "foreign_keys": [...]}
        """
        conn = await asyncpg.connect(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
        )
        try:
            col_rows = await conn.fetch(_COLUMNS_QUERY)
            fk_rows = await conn.fetch(_FK_QUERY)
        finally:
            await conn.close()

        # Build FK lookup: table_name -> [fk_dict, ...]
        fk_map: dict[str, list[dict]] = {}
        for row in fk_rows:
            table = row["table_name"]
            fk_map.setdefault(table, []).append(
                {
                    "column": row["column_name"],
                    "references_table": row["foreign_table_name"],
                    "references_column": row["foreign_column_name"],
                }
            )

        # Build tables structure
        tables_map: dict[str, dict] = {}
        for row in col_rows:
            table = row["table_name"]
            if table not in tables_map:
                tables_map[table] = {
                    "name": table,
                    "columns": [],
                    "foreign_keys": fk_map.get(table, []),
                }
            tables_map[table]["columns"].append(
                {
                    "name": row["column_name"],
                    "type": row["data_type"],
                    "nullable": row["is_nullable"].upper() == "YES",
                }
            )

        return list(tables_map.values())
