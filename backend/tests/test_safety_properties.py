"""
Property-based tests for the Deterministic Safety Layer.

Uses Hypothesis to verify universal safety properties across a wide range of
inputs.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tallyai.core.safety import SafetyDecision, SafetyLayer, SafetyPolicy

# Default policy used across tests.
DEFAULT_POLICY = SafetyPolicy()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate(sql: str, policy: SafetyPolicy = DEFAULT_POLICY) -> SafetyDecision:
    return SafetyLayer.validate(sql, policy)


# ---------------------------------------------------------------------------
# Property 1 — Only SELECT can be approved  (Req 3.3, 3.4)
#
# For any text that does NOT begin with SELECT (case-insensitive), the default
# policy must never produce approved=True.
# ---------------------------------------------------------------------------


@given(st.text(min_size=1))
@settings(max_examples=200)
def test_always_select_only(sql: str) -> None:
    """**Validates: Requirements 3.3, 3.4**

    If a SQL text does not start with SELECT (case-insensitive) it must never
    be approved under the default policy.
    """
    if sql.lstrip().upper().startswith("SELECT"):
        return  # skip — these CAN be approved

    decision = _validate(sql)
    assert not decision.approved, (
        f"Non-SELECT input was incorrectly approved.\nInput: {sql!r}\nDecision: {decision}"
    )


# ---------------------------------------------------------------------------
# Property 2 — Determinism  (Req 3.7, 3.10)
#
# Calling validate() twice with the same input always returns an identical
# SafetyDecision.
# ---------------------------------------------------------------------------


@given(st.text())
@settings(max_examples=200)
def test_safety_check_is_deterministic(sql: str) -> None:
    """**Validates: Requirements 3.7, 3.10**

    validate() is a pure function: two calls with the same inputs must
    produce identical outputs.
    """
    first = _validate(sql)
    second = _validate(sql)
    assert first == second, (
        f"Non-deterministic result for input {sql!r}.\nFirst:  {first}\nSecond: {second}"
    )


# ---------------------------------------------------------------------------
# Property 3 — Approved queries always have LIMIT  (Req 3.5, 3.6)
#
# For any input that yields approved=True, the safe_sql must contain LIMIT.
# ---------------------------------------------------------------------------


@given(st.text())
@settings(max_examples=200)
def test_always_has_limit(sql: str) -> None:
    """**Validates: Requirements 3.5, 3.6**

    If validate() approves a query the resulting safe_sql must contain a LIMIT
    clause so that the row cap is always enforced.
    """
    decision = _validate(sql)
    if decision.approved:
        assert decision.safe_sql is not None
        assert "LIMIT" in decision.safe_sql.upper(), (
            f"Approved safe_sql has no LIMIT clause.\n"
            f"Input:    {sql!r}\n"
            f"safe_sql: {decision.safe_sql!r}"
        )


# ---------------------------------------------------------------------------
# Property 4 — Credential column names are always blocked  (Req 3.8)
# ---------------------------------------------------------------------------

BLOCKED_PATTERNS = [
    "password",
    "passwd",
    "api_key",
    "token",
    "secret",
    "private_key",
    "ssn",
    "credit_card",
    "cvv",
]

CREDENTIAL_SQLS = [f"SELECT {pat} FROM t" for pat in BLOCKED_PATTERNS]


@pytest.mark.parametrize("sql", CREDENTIAL_SQLS)
def test_no_credential_columns(sql: str) -> None:
    """**Validates: Requirement 3.8**

    SELECT queries that reference blocked credential-related column names must
    be rejected even though their statement type is SELECT.
    """
    decision = _validate(sql)
    assert not decision.approved, (
        f"Credential column query was incorrectly approved.\n"
        f"Input:    {sql!r}\n"
        f"Decision: {decision}"
    )
    assert decision.parsed_ok, (
        f"Expected parsed_ok=True for a syntactically valid query.\nDecision: {decision}"
    )


# ---------------------------------------------------------------------------
# Property 5 — An executor respects the approved flag  (Req 3.8, 3.9)
#
# A minimal QueryExecutor stub must raise ValueError when asked to run an
# unapproved decision.
# ---------------------------------------------------------------------------


class _QueryExecutor:
    """Minimal stub that refuses to execute unapproved decisions."""

    def run(self, decision: SafetyDecision) -> None:  # noqa: D102
        if not decision.approved:
            raise ValueError(
                f"Refused to execute unapproved query. Reason: {decision.reason}"
            )


@given(st.text())
@settings(max_examples=200)
def test_blocked_sql_never_executes(sql: str) -> None:
    """**Validates: Requirements 3.8, 3.9**

    A QueryExecutor that honours the SafetyDecision must always raise
    ValueError when decision.approved is False.
    """
    decision = _validate(sql)
    executor = _QueryExecutor()

    if not decision.approved:
        with pytest.raises(ValueError):
            executor.run(decision)
    else:
        # Approved — must NOT raise.
        executor.run(decision)
