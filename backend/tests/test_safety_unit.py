"""
Unit tests for the Deterministic Safety Layer.

Covers specific examples and edge cases for SafetyLayer.validate().

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10
"""

from __future__ import annotations

import pytest

from tallyai.core.safety import SafetyDecision, SafetyLayer, SafetyPolicy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_POLICY = SafetyPolicy()


def validate(sql: str, policy: SafetyPolicy = DEFAULT_POLICY) -> SafetyDecision:
    return SafetyLayer.validate(sql, policy)


# ---------------------------------------------------------------------------
# Statement-type allowlist
# ---------------------------------------------------------------------------


def test_select_passes() -> None:
    """A plain SELECT is approved with parsed_ok=True and a LIMIT in safe_sql."""
    decision = validate("SELECT id FROM users")
    assert decision.approved is True
    assert decision.parsed_ok is True
    assert decision.safe_sql is not None
    assert "LIMIT" in decision.safe_sql.upper()
    assert decision.reason is None


def test_insert_rejected() -> None:
    """INSERT must be rejected under the default (SELECT-only) policy."""
    decision = validate("INSERT INTO users VALUES (1)")
    assert decision.approved is False
    assert decision.reason is not None


def test_update_rejected() -> None:
    """UPDATE must be rejected under the default policy."""
    decision = validate("UPDATE users SET name='x'")
    assert decision.approved is False
    assert decision.reason is not None


def test_delete_rejected() -> None:
    """DELETE must be rejected under the default policy."""
    decision = validate("DELETE FROM users")
    assert decision.approved is False
    assert decision.reason is not None


# ---------------------------------------------------------------------------
# Parse errors
# ---------------------------------------------------------------------------


def test_parse_error_rejected() -> None:
    """Completely unparseable input must be rejected with parsed_ok=False."""
    decision = validate("NOT VALID SQL @@@@")
    assert decision.approved is False
    assert decision.parsed_ok is False
    assert decision.safe_sql is None
    assert decision.reason is not None
    assert "parse" in decision.reason.lower()


# ---------------------------------------------------------------------------
# LIMIT enforcement
# ---------------------------------------------------------------------------


def test_explicit_limit_under_cap_passes() -> None:
    """LIMIT 10 with row_cap=1000 is fine; safe_sql must preserve LIMIT 10."""
    policy = SafetyPolicy(row_cap=1000)
    decision = validate("SELECT id FROM users LIMIT 10", policy)
    assert decision.approved is True
    assert decision.safe_sql is not None
    assert "LIMIT 10" in decision.safe_sql.upper()


def test_explicit_limit_over_cap_rejected() -> None:
    """LIMIT 5000 with row_cap=1000 must be rejected."""
    policy = SafetyPolicy(row_cap=1000)
    decision = validate("SELECT id FROM users LIMIT 5000", policy)
    assert decision.approved is False
    assert "5000" in (decision.reason or "")


def test_no_limit_gets_injected() -> None:
    """A SELECT without LIMIT must have LIMIT 1000 injected into safe_sql."""
    decision = validate("SELECT id FROM users")
    assert decision.approved is True
    assert decision.safe_sql is not None
    assert "LIMIT 1000" in decision.safe_sql.upper()


# ---------------------------------------------------------------------------
# Credential column blocking
# ---------------------------------------------------------------------------


def test_credential_column_blocked() -> None:
    """A SELECT that references 'password' must be rejected. (Req 3.8)"""
    decision = validate("SELECT password FROM users")
    assert decision.approved is False
    assert decision.parsed_ok is True  # valid SQL — rejection is policy-based
    assert decision.reason is not None
    assert "password" in decision.reason.lower()


# ---------------------------------------------------------------------------
# QueryExecutor respects SafetyDecision (Req 3.8, 3.9)
# ---------------------------------------------------------------------------


class QueryExecutor:
    """Minimal executor that enforces the safety gate decision."""

    def run(self, decision: SafetyDecision) -> list[dict]:
        if not decision.approved:
            raise ValueError(
                f"Execution blocked by safety layer. Reason: {decision.reason}"
            )
        # In production this would call the database; here we return a stub.
        return []


def test_query_executor_refuses_unapproved() -> None:
    """QueryExecutor must raise ValueError for any unapproved decision. (Req 3.8, 3.9)"""
    bad_decision = SafetyDecision(
        approved=False,
        safe_sql=None,
        reason="statement type not allowed",
        parsed_ok=True,
    )
    executor = QueryExecutor()
    with pytest.raises(ValueError, match="safety layer"):
        executor.run(bad_decision)


def test_query_executor_accepts_approved() -> None:
    """QueryExecutor must NOT raise for an approved decision."""
    good_decision = validate("SELECT id FROM users")
    assert good_decision.approved is True  # pre-condition
    executor = QueryExecutor()
    result = executor.run(good_decision)
    assert result == []


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_string_rejected() -> None:
    """An empty string must be rejected with parsed_ok=False."""
    decision = validate("")
    assert decision.approved is False
    assert decision.parsed_ok is False


def test_whitespace_only_rejected() -> None:
    """A whitespace-only string must be rejected with parsed_ok=False."""
    decision = validate("   \n\t  ")
    assert decision.approved is False
    assert decision.parsed_ok is False


def test_case_insensitive_select_passes() -> None:
    """Lowercase 'select' must be approved (SQL is case-insensitive)."""
    decision = validate("select id from users")
    assert decision.approved is True


def test_custom_policy_allows_insert() -> None:
    """A custom policy that allows INSERT must approve an INSERT statement."""
    policy = SafetyPolicy(allowed_statements=frozenset({"INSERT"}))
    decision = validate("INSERT INTO logs VALUES (1)", policy)
    assert decision.approved is True
    # INSERT statements don't have a LIMIT clause — safe_sql is the statement as-is
    assert decision.safe_sql is not None
    assert decision.parsed_ok is True


def test_determinism_same_sql() -> None:
    """validate() must be deterministic — same input produces same output."""
    sql = "SELECT name FROM customers"
    assert validate(sql) == validate(sql)
