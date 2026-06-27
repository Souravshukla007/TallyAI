"""
Deterministic Safety Layer for TallyAI.

This module is a pure function — it has no model calls, no DB access, and no
side effects. Its only inputs are a SQL string and a SafetyPolicy; its only
output is a SafetyDecision. (Req 3.7, 3.10)

Steps performed by SafetyLayer.validate():
  1. Parse the SQL with sqlglot (Req 3.1, 3.2)
  2. Check statement type against allowed_statements allowlist (Req 3.3, 3.4)
  2.5. Scan column names for blocked credential patterns (Req 3.8)
  3. Reject if explicit LIMIT > row_cap (Req 3.6)
  4. Inject LIMIT row_cap when no LIMIT is present (Req 3.5)
  5. Return approved decision (Req 3.9)
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
import sqlglot.expressions as exp
import sqlglot.errors

# ---------------------------------------------------------------------------
# Blocked credential-related column name patterns (Req 3.8)
# ---------------------------------------------------------------------------

BLOCKED_COLUMN_PATTERNS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "api_key",
        "token",
        "secret",
        "private_key",
        "ssn",
        "credit_card",
        "cvv",
    }
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SafetyPolicy:
    """Configuration for the safety gate.

    Attributes:
        allowed_statements: Set of upper-cased sqlglot class names that are
            permitted. Defaults to SELECT-only. (Req 3.4)
        row_cap: Maximum number of rows a query may return. Queries without an
            explicit LIMIT receive this cap automatically. (Req 3.5)
        query_timeout_ms: Advisory query timeout forwarded to the executor.
            (Req 4.3)
    """

    allowed_statements: frozenset[str] = frozenset({"SELECT"})
    row_cap: int = 1000
    query_timeout_ms: int = 30_000


@dataclass(frozen=True)
class SafetyDecision:
    """Result returned by SafetyLayer.validate().

    Attributes:
        approved: True iff the query may proceed to execution.
        safe_sql: Row-cap-injected SQL text when approved; None when rejected.
        reason: Human-readable rejection reason; None when approved.
        parsed_ok: True iff sqlglot was able to parse the input. (Req 3.9)
    """

    approved: bool
    safe_sql: str | None
    reason: str | None
    parsed_ok: bool


# ---------------------------------------------------------------------------
# Safety layer
# ---------------------------------------------------------------------------


class SafetyLayer:
    """Deterministic SQL safety gate (no model calls, no DB access)."""

    @staticmethod
    def validate(sql_text: str, policy: SafetyPolicy = SafetyPolicy()) -> SafetyDecision:
        """Validate *sql_text* against *policy* and return a SafetyDecision.

        This is a pure function: identical inputs always produce identical
        outputs. (Req 3.7, 3.10)
        """
        # ------------------------------------------------------------------
        # Step 1 — Parse
        # ------------------------------------------------------------------
        try:
            parsed = sqlglot.parse_one(sql_text)
        except (sqlglot.errors.ParseError, sqlglot.errors.TokenError, Exception) as exc:
            # sqlglot can raise ParseError, TokenError, or other internal errors
            # on malformed input — treat all of them as unparseable.
            return SafetyDecision(
                approved=False,
                safe_sql=None,
                reason=f"SQL parse error: {exc}",
                parsed_ok=False,
            )

        # parse_one returns None for empty / whitespace-only input
        if parsed is None:
            return SafetyDecision(
                approved=False,
                safe_sql=None,
                reason="SQL parse error: empty or unrecognisable input",
                parsed_ok=False,
            )

        # ------------------------------------------------------------------
        # Step 2 — Statement-type allowlist (Req 3.3, 3.4)
        # ------------------------------------------------------------------
        stmt_type = type(parsed).__name__.upper()
        if stmt_type not in policy.allowed_statements:
            return SafetyDecision(
                approved=False,
                safe_sql=None,
                reason=(
                    f"Statement type '{stmt_type}' is not allowed. "
                    f"Allowed: {sorted(policy.allowed_statements)}"
                ),
                parsed_ok=True,
            )

        # ------------------------------------------------------------------
        # Step 2.5 — Blocked credential column patterns (Req 3.8)
        # ------------------------------------------------------------------
        for col_node in parsed.find_all(exp.Column):
            col_name: str = col_node.name.lower()
            for pattern in BLOCKED_COLUMN_PATTERNS:
                if pattern in col_name:
                    return SafetyDecision(
                        approved=False,
                        safe_sql=None,
                        reason=(
                            f"Query references a blocked column name '{col_node.name}' "
                            f"(matched pattern: '{pattern}')"
                        ),
                        parsed_ok=True,
                    )

        # ------------------------------------------------------------------
        # Step 3 — Explicit LIMIT check (Req 3.6)
        # ------------------------------------------------------------------
        limit_clause = parsed.find(exp.Limit)
        if limit_clause is not None:
            try:
                explicit_limit = int(limit_clause.expression.name)
            except (AttributeError, ValueError, TypeError):
                explicit_limit = None

            if explicit_limit is not None and explicit_limit > policy.row_cap:
                return SafetyDecision(
                    approved=False,
                    safe_sql=None,
                    reason=(
                        f"Explicit LIMIT {explicit_limit} exceeds the row cap of "
                        f"{policy.row_cap}"
                    ),
                    parsed_ok=True,
                )

        # ------------------------------------------------------------------
        # Step 4 — Inject LIMIT when absent (Req 3.5)
        # Only SELECT statements support .limit(); skip for others (they would
        # have been rejected in Step 2 under the default policy anyway, but a
        # custom policy could allow INSERT etc.).
        # ------------------------------------------------------------------
        if limit_clause is None and isinstance(parsed, exp.Select):
            parsed = parsed.limit(policy.row_cap)

        # ------------------------------------------------------------------
        # Step 5 — Approved
        # ------------------------------------------------------------------
        return SafetyDecision(
            approved=True,
            safe_sql=parsed.sql(),
            reason=None,
            parsed_ok=True,
        )
