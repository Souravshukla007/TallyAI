"""
QueryExecutor — executes a safety-approved SQL query against a target database.

Req 3.8, 3.9 : Blocks execution when the decision is not approved or not parsed.
Req 4.2      : No retry on execution failure.
Req 4.3      : Raises TimeoutError on asyncpg query-cancelled timeout.
Req 4.5      : Enforces row_cap; sets truncated=True when cap is reached.
Req 9.1      : Writes an ExecutionLogEntry for every executed query.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import asyncpg
import asyncpg.exceptions
from sqlalchemy.ext.asyncio import AsyncSession

from tallyai.core.safety import SafetyDecision, SafetyPolicy
from tallyai.services.execution_log import ExecutionLog


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """Result returned by QueryExecutor.execute()."""

    query_id: str
    rows: list[dict]
    row_count: int
    truncated: bool
    latency_ms: int


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class QueryExecutor:
    """Executes a safety-approved query and records the run in the audit log."""

    async def execute(
        self,
        decision: SafetyDecision,
        connection_id: str,
        tenant_id: str,
        user_id: str,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        policy: SafetyPolicy,
        db: AsyncSession,
    ) -> ExecutionResult:
        """Execute *decision.safe_sql* against the target database.

        Parameters
        ----------
        decision:
            The SafetyDecision produced by SafetyLayer.validate().
        connection_id:
            Identifier of the TenantConnection record.
        tenant_id:
            Owning tenant.
        user_id:
            User that triggered the query.
        host, port, database, user, password:
            Target database credentials.
        policy:
            SafetyPolicy with row_cap and query_timeout_ms.
        db:
            Async SQLAlchemy session for writing the execution log.

        Raises
        ------
        ValueError
            When ``decision.approved`` is False or ``decision.parsed_ok`` is
            False (Req 3.8, 3.9).  No database connection is opened.
        TimeoutError
            When asyncpg raises QueryCanceledError due to statement_timeout
            (Req 4.3).
        RuntimeError
            On any other asyncpg execution failure (Req 4.2, no retry).
        """
        # ------------------------------------------------------------------
        # Precondition guard (Req 3.8, 3.9) — must happen before any DB call
        # ------------------------------------------------------------------
        if not decision.approved:
            raise ValueError(
                f"Execution blocked: query was not approved. Reason: {decision.reason}"
            )
        if not decision.parsed_ok:
            raise ValueError(
                "Execution blocked: query could not be parsed."
            )

        query_id = str(uuid.uuid4())
        truncated = False
        rows: list[dict] = []
        latency_ms = 0

        # ------------------------------------------------------------------
        # Connect to target database and run query
        # ------------------------------------------------------------------
        conn: asyncpg.Connection | None = None
        start = time.perf_counter()
        try:
            conn = await asyncpg.connect(
                host=host,
                port=port,
                database=database,
                user=user,
                password=password,
            )

            # Set statement timeout (Req 4.3)
            await conn.execute(
                f"SET statement_timeout = {policy.query_timeout_ms}"
            )

            # Execute query
            raw_rows = await conn.fetch(decision.safe_sql)

            elapsed = time.perf_counter() - start
            latency_ms = int(elapsed * 1000)

            # Enforce row cap (Req 4.5)
            if len(raw_rows) >= policy.row_cap:
                truncated = True
                raw_rows = raw_rows[: policy.row_cap]

            # Convert asyncpg Record objects to plain dicts
            rows = [dict(record) for record in raw_rows]

        except asyncpg.exceptions.QueryCanceledError as exc:
            # Re-raise as TimeoutError (Req 4.3)
            raise TimeoutError("Query exceeded timeout") from exc

        except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError) as exc:
            # Any other asyncpg failure — no retry (Req 4.2)
            raise RuntimeError(str(exc)) from exc

        finally:
            if conn is not None:
                await conn.close()

        # ------------------------------------------------------------------
        # Write execution log entry (Req 9.1)
        # ------------------------------------------------------------------
        await ExecutionLog.record(
            entry_data={
                "query_id": query_id,
                "tenant_id": tenant_id,
                "connection_id": connection_id,
                "user_id": user_id,
                "exact_sql": decision.safe_sql,
                "parameters": {},
                "result_ref": "",
                "row_count": len(rows),
                "truncated": truncated,
                "latency_ms": latency_ms,
            },
            db=db,
        )

        return ExecutionResult(
            query_id=query_id,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            latency_ms=latency_ms,
        )
