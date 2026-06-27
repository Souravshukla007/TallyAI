"""initial schema — create all 7 TallyAI tables

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # tenant_connection
    # ------------------------------------------------------------------
    op.create_table(
        "tenant_connection",
        sa.Column("connection_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("host", sa.String(255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        sa.Column("database", sa.String(255), nullable=False),
        sa.Column("role", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("connection_id"),
    )
    op.create_index("ix_tenant_connection_tenant_id", "tenant_connection", ["tenant_id"])

    # ------------------------------------------------------------------
    # encrypted_credential
    # ------------------------------------------------------------------
    op.create_table(
        "encrypted_credential",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("connection_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("kms_key_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["tenant_connection.connection_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_encrypted_credential_connection_id",
        "encrypted_credential",
        ["connection_id"],
    )
    op.create_index(
        "ix_encrypted_credential_tenant_id", "encrypted_credential", ["tenant_id"]
    )

    # ------------------------------------------------------------------
    # cached_schema
    # ------------------------------------------------------------------
    op.create_table(
        "cached_schema",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("connection_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("tables_json", sa.Text(), nullable=False),
        sa.Column("introspected_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["tenant_connection.connection_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_cached_schema_connection_id", "cached_schema", ["connection_id"]
    )
    op.create_index("ix_cached_schema_tenant_id", "cached_schema", ["tenant_id"])

    # ------------------------------------------------------------------
    # metric_definition
    # ------------------------------------------------------------------
    op.create_table(
        "metric_definition",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("condition", sa.Text(), nullable=True),
        sa.Column("grain", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("superseded_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_metric_definition_name", "metric_definition", ["name"])
    op.create_index(
        "ix_metric_definition_tenant_id", "metric_definition", ["tenant_id"]
    )

    # ------------------------------------------------------------------
    # execution_log_entry
    # ------------------------------------------------------------------
    op.create_table(
        "execution_log_entry",
        sa.Column("query_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("connection_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("exact_sql", sa.Text(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("result_ref", sa.String(512), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("query_id"),
    )
    op.create_index(
        "ix_execution_log_entry_tenant_id", "execution_log_entry", ["tenant_id"]
    )
    op.create_index(
        "ix_execution_log_entry_connection_id",
        "execution_log_entry",
        ["connection_id"],
    )

    # ------------------------------------------------------------------
    # history_entry
    # ------------------------------------------------------------------
    op.create_table(
        "history_entry",
        sa.Column("history_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("connection_id", sa.String(36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("query_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("history_id"),
    )
    op.create_index("ix_history_entry_tenant_id", "history_entry", ["tenant_id"])
    op.create_index(
        "ix_history_entry_connection_id", "history_entry", ["connection_id"]
    )

    # ------------------------------------------------------------------
    # trace
    # ------------------------------------------------------------------
    op.create_table(
        "trace",
        sa.Column("trace_id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("generated_sql", sa.Text(), nullable=True),
        sa.Column("tool_calls", sa.JSON(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("trace_id"),
    )
    op.create_index("ix_trace_tenant_id", "trace", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("trace")
    op.drop_table("history_entry")
    op.drop_table("execution_log_entry")
    op.drop_table("metric_definition")
    op.drop_table("cached_schema")
    op.drop_table("encrypted_credential")
    op.drop_table("tenant_connection")
