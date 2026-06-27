"""
Connection manager — validates database credentials, detects privilege levels,
and persists ``TenantConnection`` + ``EncryptedCredential`` rows only when a
connection is confirmed safe (read-only).

Security invariants (Req 1.3, 1.6, 1.7):
  - Req 1.3  Non-privilege connection failures do NOT persist a TenantConnection.
  - Req 1.6  Write / DDL / admin privileges → reject and name them.
  - Req 1.7  Privilege detection failure → reject and name the failed step.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession

from tallyai.db.models import TenantConnection
from tallyai.services.credential_store import CredentialStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Privilege-detection SQL
# ---------------------------------------------------------------------------
# Each entry is (step_name, sql, "disallowed" value that triggers rejection).
_PRIVILEGE_CHECKS: list[tuple[str, str, Any]] = [
    (
        "is_superuser",
        "SELECT current_setting('is_superuser')",
        "on",
    ),
    (
        "database_create",
        "SELECT has_database_privilege(current_user, current_database(), 'CREATE')",
        True,
    ),
    (
        "schema_create",
        "SELECT has_schema_privilege(current_user, 'public', 'CREATE')",
        True,
    ),
]


async def _detect_privileges(conn: asyncpg.Connection) -> list[str]:
    """Run privilege-detection queries and return a list of disallowed privilege names.

    Raises any exception that is *not* caught here so the caller can
    distinguish privilege detection failure (Req 1.7) from privilege
    detection success with disallowed privs (Req 1.6).
    """
    disallowed: list[str] = []

    for step_name, sql, bad_value in _PRIVILEGE_CHECKS:
        row = await conn.fetchrow(sql)
        raw_value = row[0]

        # ``current_setting`` returns a string; cast booleans as needed.
        if isinstance(bad_value, bool):
            detected_value: Any = bool(raw_value)
        else:
            detected_value = str(raw_value).lower()

        if detected_value == bad_value:
            disallowed.append(step_name)

    return disallowed


class ConnectionManager:
    """Validates and persists tenant database connections."""

    def __init__(self) -> None:
        self._store = CredentialStore()

    # ------------------------------------------------------------------
    # create_connection
    # ------------------------------------------------------------------

    async def create_connection(
        self,
        host: str,
        port: int,
        database: str,
        role: str,
        credentials: dict,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """Attempt to open a real asyncpg connection, run privilege detection,
        and persist on success.

        Returns a dict shaped like one of:
          - ``{"ok": True, "connection_id": str, "read_only": True}``
          - ``{"ok": False, "error": "disallowed_privileges", "privileges": [...]}``
          - ``{"ok": False, "error": "privilege_detection_failed", "detail": str}``
          - ``{"ok": False, "error": "connection_failed", "detail": str}``

        Req 1.3  On connection_failed, NO TenantConnection is persisted.
        Req 1.6  On disallowed_privileges, reject and list them.
        Req 1.7  On privilege_detection_failed, reject and name the step.
        """
        # Build asyncpg DSN from supplied credentials.
        password = credentials.get("password", "")
        user = credentials.get("user", credentials.get("username", role))

        conn: asyncpg.Connection | None = None
        try:
            conn = await asyncpg.connect(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
            )
        except Exception as exc:
            # Non-privilege connection failure: report error, persist NOTHING
            # (Req 1.3).
            logger.info(
                "create_connection: connection failed host=%s port=%s database=%s — %s",
                host,
                port,
                database,
                type(exc).__name__,
            )
            return {"ok": False, "error": "connection_failed", "detail": str(exc)}

        # ----- Connection is open — run privilege detection -----
        try:
            disallowed = await _detect_privileges(conn)
        except Exception as exc:
            # Privilege detection itself raised — reject (Req 1.7).
            logger.warning(
                "create_connection: privilege detection failed host=%s — %s",
                host,
                type(exc).__name__,
            )
            await conn.close()
            return {
                "ok": False,
                "error": "privilege_detection_failed",
                "detail": str(exc),
            }
        finally:
            # Always close the probe connection.
            if not conn.is_closed():
                await conn.close()

        if disallowed:
            # Write-capable credentials — reject (Req 1.6).
            logger.warning(
                "create_connection: disallowed privileges detected host=%s privileges=%s",
                host,
                disallowed,
            )
            return {
                "ok": False,
                "error": "disallowed_privileges",
                "privileges": disallowed,
            }

        # ----- All checks passed — persist connection -----
        connection_id = str(uuid.uuid4())

        tenant_conn = TenantConnection(
            connection_id=connection_id,
            tenant_id=tenant_id,
            host=host,
            port=port,
            database=database,
            role=role,
            is_active=True,
            schema_version="",
        )
        db.add(tenant_conn)
        await db.flush()  # obtain PK before saving credentials

        await self._store.save(connection_id, tenant_id, credentials, db)
        await db.commit()

        logger.info(
            "create_connection: persisted connection_id=%s tenant_id=%s host=%s",
            connection_id,
            tenant_id,
            host,
        )
        return {"ok": True, "connection_id": connection_id, "read_only": True}

    # ------------------------------------------------------------------
    # test_connection
    # ------------------------------------------------------------------

    async def test_connection(
        self,
        connection_id: str,
        tenant_id: str,
        db: AsyncSession,
    ) -> dict:
        """Re-fetch credentials and re-run privilege detection.

        Returns ``{"ok": bool, "reason": str | None}``.
        """
        credentials = await self._store.get_connection(connection_id, tenant_id, db)
        if credentials is None:
            return {"ok": False, "reason": "connection not found or access denied"}

        # Fetch the TenantConnection row to get host/port/database.
        from sqlalchemy import select
        from tallyai.db.models import TenantConnection as TC

        result = await db.execute(
            select(TC).where(
                TC.connection_id == connection_id,
                TC.tenant_id == tenant_id,
            )
        )
        tc = result.scalars().first()
        if tc is None:
            return {"ok": False, "reason": "connection record not found"}

        user = credentials.get("user", credentials.get("username", tc.role))
        password = credentials.get("password", "")

        conn: asyncpg.Connection | None = None
        try:
            conn = await asyncpg.connect(
                host=tc.host,
                port=tc.port,
                database=tc.database,
                user=user,
                password=password,
            )
        except Exception as exc:
            return {"ok": False, "reason": f"connection_failed: {exc}"}

        try:
            disallowed = await _detect_privileges(conn)
        except Exception as exc:
            await conn.close()
            return {"ok": False, "reason": f"privilege_detection_failed: {exc}"}
        finally:
            if not conn.is_closed():
                await conn.close()

        if disallowed:
            return {
                "ok": False,
                "reason": f"disallowed_privileges: {', '.join(disallowed)}",
            }

        return {"ok": True, "reason": None}
