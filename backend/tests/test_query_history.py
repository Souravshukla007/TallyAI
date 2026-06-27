"""
Tests for QueryHistory service.

Covers:
- test_append_persists_question_and_query_ids : append stores question + query_ids (Req 13.1)
- test_list_returns_correct_entries           : list returns the user's entries (Req 13.2)
- test_search_filters_by_term                 : search matches on question text (Req 13.3)
- test_search_is_case_insensitive             : search is a case-insensitive substring match (Req 13.3)
- test_list_scoped_to_user_and_connection     : list does not leak across users/connections (Req 13.2)
- test_cross_tenant_list_returns_empty        : another tenant sees no entries (Req 14.2, 14.4)
- test_cross_tenant_search_returns_empty      : another tenant's search is empty (Req 14.2, 14.4)
"""

from __future__ import annotations

import pytest

from tallyai.services.query_history import QueryHistory

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"
USER_1 = "user-1"
USER_2 = "user-2"
CONN_1 = "conn-1"
CONN_2 = "conn-2"


@pytest.mark.asyncio
async def test_append_persists_question_and_query_ids(db_session):
    """append() persists the question and associated query identifiers (Req 13.1)."""
    history_id = await QueryHistory.append(
        user_id=USER_1,
        connection_id=CONN_1,
        question="How many active users?",
        query_ids=["q1", "q2"],
        tenant_id=TENANT_A,
        db=db_session,
    )
    await db_session.commit()

    assert history_id

    entries = await QueryHistory.list(USER_1, CONN_1, TENANT_A, db_session)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.history_id == history_id
    assert entry.question == "How many active users?"
    assert entry.query_ids == ["q1", "q2"]
    assert entry.tenant_id == TENANT_A
    assert entry.user_id == USER_1
    assert entry.connection_id == CONN_1


@pytest.mark.asyncio
async def test_list_returns_correct_entries(db_session):
    """list() returns all persisted entries for the user/connection (Req 13.2)."""
    await QueryHistory.append(USER_1, CONN_1, "first question", ["q1"], TENANT_A, db_session)
    await QueryHistory.append(USER_1, CONN_1, "second question", ["q2"], TENANT_A, db_session)
    await db_session.commit()

    entries = await QueryHistory.list(USER_1, CONN_1, TENANT_A, db_session)
    questions = {e.question for e in entries}
    assert questions == {"first question", "second question"}


@pytest.mark.asyncio
async def test_search_filters_by_term(db_session):
    """search() returns only entries whose question matches the term (Req 13.3)."""
    await QueryHistory.append(USER_1, CONN_1, "revenue last quarter", ["q1"], TENANT_A, db_session)
    await QueryHistory.append(USER_1, CONN_1, "active user count", ["q2"], TENANT_A, db_session)
    await db_session.commit()

    results = await QueryHistory.search(USER_1, CONN_1, "revenue", TENANT_A, db_session)
    assert len(results) == 1
    assert results[0].question == "revenue last quarter"

    # A term that matches nothing returns no entries.
    assert await QueryHistory.search(USER_1, CONN_1, "nonexistent", TENANT_A, db_session) == []


@pytest.mark.asyncio
async def test_search_is_case_insensitive(db_session):
    """search() performs a case-insensitive substring match (Req 13.3)."""
    await QueryHistory.append(USER_1, CONN_1, "Revenue By Region", ["q1"], TENANT_A, db_session)
    await db_session.commit()

    results = await QueryHistory.search(USER_1, CONN_1, "revenue", TENANT_A, db_session)
    assert len(results) == 1
    assert results[0].question == "Revenue By Region"


@pytest.mark.asyncio
async def test_list_scoped_to_user_and_connection(db_session):
    """list() is scoped to the requesting user and connection (Req 13.2)."""
    await QueryHistory.append(USER_1, CONN_1, "u1 c1", ["q1"], TENANT_A, db_session)
    await QueryHistory.append(USER_2, CONN_1, "u2 c1", ["q2"], TENANT_A, db_session)
    await QueryHistory.append(USER_1, CONN_2, "u1 c2", ["q3"], TENANT_A, db_session)
    await db_session.commit()

    entries = await QueryHistory.list(USER_1, CONN_1, TENANT_A, db_session)
    assert len(entries) == 1
    assert entries[0].question == "u1 c1"


@pytest.mark.asyncio
async def test_cross_tenant_list_returns_empty(db_session):
    """A different tenant sees no history entries (Req 14.2, 14.4)."""
    await QueryHistory.append(USER_1, CONN_1, "tenant A question", ["q1"], TENANT_A, db_session)
    await db_session.commit()

    # Same user/connection identifiers but a different tenant.
    entries = await QueryHistory.list(USER_1, CONN_1, TENANT_B, db_session)
    assert entries == []


@pytest.mark.asyncio
async def test_cross_tenant_search_returns_empty(db_session):
    """A different tenant's search returns no entries (Req 14.2, 14.4)."""
    await QueryHistory.append(USER_1, CONN_1, "tenant A question", ["q1"], TENANT_A, db_session)
    await db_session.commit()

    results = await QueryHistory.search(USER_1, CONN_1, "tenant", TENANT_B, db_session)
    assert results == []
