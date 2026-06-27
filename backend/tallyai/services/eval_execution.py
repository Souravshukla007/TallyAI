"""
Execution-based SQL equivalence for the eval harness.

The default eval comparison is a normalized *string* match (``normalize_sql``),
which under-counts correctness: two queries that return identical data but differ
in alias names, ``COUNT(*)`` vs ``COUNT(id)``, positional vs expression
``GROUP BY``, or row ordering are scored as misses even though they are
functionally identical.

This module compares queries by *what they return*: it executes both the
expected and generated SQL against a small, deterministic in-process database
(DuckDB — Postgres-compatible enough for the golden set, no server required) and
compares their result sets. Two queries are equivalent when they return the same
bag of rows (compared positionally, alias-insensitive, with float tolerance).
Ordering differences are ignored unless they change the multiset of rows.

The seed dataset is crafted so that genuinely different queries (e.g. one that
drops a ``status = 'active'`` filter) produce different results and are correctly
scored as misses, while cosmetic differences compare equal.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deterministic seed data
# ---------------------------------------------------------------------------
# Rows are chosen so that:
#   * payments span two months and multiple plans/statuses (revenue grouping)
#   * one subscription has trial_converted = TRUE but status = 'canceled', so a
#     query that forgets the status filter diverges from one that keeps it.
#   * all id columns are non-null, so COUNT(id) == COUNT(*).

_SEED_SQL = """
CREATE TABLE customers (
    id INTEGER, total_spend DOUBLE, created_at TIMESTAMP
);
INSERT INTO customers VALUES
    (1, 1200.0, TIMESTAMP '2024-01-05'),
    (2,  300.0, TIMESTAMP '2024-02-10'),
    (3,  900.0, DATE_TRUNC('month', NOW())),          -- signed up this month
    (4,  150.0, DATE_TRUNC('month', NOW()) + INTERVAL '3 days');

CREATE TABLE payments (
    id INTEGER, customer_id INTEGER, amount DOUBLE,
    status VARCHAR, plan VARCHAR, created_at TIMESTAMP
);
INSERT INTO payments VALUES
    (1, 1, 100.0, 'completed', 'pro',     TIMESTAMP '2024-01-15'),
    (2, 1, 200.0, 'completed', 'pro',     TIMESTAMP '2024-02-15'),
    (3, 2,  50.0, 'completed', 'starter', TIMESTAMP '2024-02-20'),
    (4, 3, 300.0, 'completed', 'team',    TIMESTAMP '2024-02-25'),
    (5, 2,  75.0, 'failed',    'starter', TIMESTAMP '2024-02-26');

CREATE TABLE subscriptions (
    id INTEGER, customer_id INTEGER, status VARCHAR,
    monthly_amount DOUBLE, trial_converted BOOLEAN, created_at TIMESTAMP
);
INSERT INTO subscriptions VALUES
    (1, 1, 'active',   100.0, TRUE,  TIMESTAMP '2024-01-01'),
    (2, 2, 'active',    50.0, FALSE, TIMESTAMP '2024-02-01'),
    (3, 3, 'canceled',  80.0, TRUE,  TIMESTAMP '2024-02-05'),  -- converted but not active
    (4, 4, 'active',   120.0, TRUE,  TIMESTAMP '2024-03-01');

CREATE TABLE users (
    id INTEGER, last_login TIMESTAMP, created_at TIMESTAMP
);
INSERT INTO users VALUES
    (1, NOW() - INTERVAL '2 days',  TIMESTAMP '2024-01-01'),
    (2, NOW() - INTERVAL '10 days', TIMESTAMP '2024-01-10'),
    (3, NOW() - INTERVAL '90 days', TIMESTAMP '2024-01-20');
"""


def build_seed_connection() -> Any:
    """Create an in-memory DuckDB connection seeded with the golden-set schema."""
    import duckdb

    conn = duckdb.connect(database=":memory:")
    conn.execute(_SEED_SQL)
    return conn


def _to_duckdb(sql: str) -> str:
    """Transpile Postgres SQL to DuckDB dialect; fall back to the raw SQL."""
    try:
        import sqlglot

        out = sqlglot.transpile(sql, read="postgres", write="duckdb")
        if out:
            return out[0]
    except Exception as exc:  # noqa: BLE001 — best-effort; DuckDB is largely PG-compatible
        logger.debug("eval_execution: transpile failed, using raw SQL: %s", exc)
    return sql


def _normalize_cell(value: Any) -> Any:
    """Make a single result cell comparable (float tolerance, Decimal/bool coercion)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int,)):
        return float(value)
    try:
        from decimal import Decimal

        if isinstance(value, Decimal):
            return round(float(value), 6)
    except Exception:  # noqa: BLE001
        pass
    if isinstance(value, float):
        return round(value, 6)
    return value


def _normalize_rows(rows: list[tuple]) -> list[tuple]:
    """Normalize cells and sort rows so comparison is order-insensitive (multiset)."""
    norm = [tuple(_normalize_cell(c) for c in row) for row in rows]
    # Sort by string projection so heterogeneous types compare deterministically.
    return sorted(norm, key=lambda r: tuple(str(c) for c in r))


def _execute(conn: Any, sql: str) -> Optional[list[tuple]]:
    try:
        return conn.execute(_to_duckdb(sql)).fetchall()
    except Exception as exc:  # noqa: BLE001 — an unrunnable query cannot be equivalent
        logger.debug("eval_execution: query failed (%s): %s", exc, sql)
        return None


def results_equivalent(
    expected_sql: str,
    generated_sql: Optional[str],
    conn: Any = None,
) -> bool:
    """Return True when *generated_sql* returns the same rows as *expected_sql*.

    Comparison is positional (alias-insensitive), order-insensitive (multiset),
    and float-tolerant. A ``None`` or unrunnable generated query is never
    equivalent.
    """
    if not generated_sql:
        return False

    own_conn = conn is None
    if own_conn:
        conn = build_seed_connection()
    try:
        expected_rows = _execute(conn, expected_sql)
        generated_rows = _execute(conn, generated_sql)
        if expected_rows is None or generated_rows is None:
            return False
        if len(expected_rows) != len(generated_rows):
            return False
        # Column counts must match for a positional comparison to be meaningful.
        if expected_rows and len(expected_rows[0]) != len(generated_rows[0]):
            return False
        return _normalize_rows(expected_rows) == _normalize_rows(generated_rows)
    finally:
        if own_conn:
            conn.close()


def make_comparator() -> Any:
    """Build a reusable ``(expected_sql, generated_sql) -> bool`` comparator.

    Holds a single seeded connection for the lifetime of the comparator so an
    eval run does not rebuild the database per pair.
    """
    conn = build_seed_connection()

    def _compare(expected_sql: str, generated_sql: Optional[str]) -> bool:
        return results_equivalent(expected_sql, generated_sql, conn=conn)

    return _compare
