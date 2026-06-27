"""
SQLAlchemy 2 ORM models for TallyAI.

Every model carries ``tenant_id`` for multi-tenant isolation (Req 14).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uuid_str() -> str:
    """Return a new UUID4 as a string (used as server-side default)."""
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TenantConnection(Base):
    """Persisted connection record per tenant (Req 1, 5, 14)."""

    __tablename__ = "tenant_connection"

    connection_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid_str
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    database: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )


class EncryptedCredential(Base):
    """Credential ciphertext stored encrypted at rest (Req 1.1, 1.4, 1.5)."""

    __tablename__ = "encrypted_credential"

    # Surrogate PK so we can always have one row per connection; the business
    # key is (connection_id, tenant_id).
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenant_connection.connection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kms_key_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )


class CachedSchema(Base):
    """Cached introspected schema for a connection (Req 5)."""

    __tablename__ = "cached_schema"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid_str
    )
    connection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tenant_connection.connection_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    tables_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    introspected_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )


class MetricDefinition(Base):
    """Versioned canonical business metric definition (Req 6)."""

    __tablename__ = "metric_definition"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid_str
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    grain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    superseded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )


class ExecutionLogEntry(Base):
    """Append-only log of every executed query (Req 9.1, 14.2)."""

    __tablename__ = "execution_log_entry"

    query_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid_str
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    connection_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    exact_sql: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[Any] = mapped_column(JSON, nullable=False, default=dict)
    result_ref: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )


class HistoryEntry(Base):
    """Per-user, per-connection question history (Req 13, 14.2)."""

    __tablename__ = "history_entry"

    history_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid_str
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    query_ids: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )


class Trace(Base):
    """Observability trace for a single TallyAI question run (Req 12.4)."""

    __tablename__ = "trace"

    trace_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid_str
    )
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    generated_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[Any] = mapped_column(JSON, nullable=False, default=list)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=_utcnow
    )
