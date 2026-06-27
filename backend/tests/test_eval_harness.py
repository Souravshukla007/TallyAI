"""
Tests for the Eval_Harness service and the /eval API routes (Req 12.1-12.4).

Service-level (EvalHarness):
- test_empty_set_raises                : empty labeled set → EmptyLabeledSetError, no score (Req 12.3)
- test_single_pair_perfect_accuracy    : one matching pair → accuracy 1.0 (Req 12.2)
- test_single_pair_mismatch_zero       : one mismatching pair → accuracy 0.0 (Req 12.2)
- test_mixed_accuracy_fraction         : k of n match → accuracy k/n (Req 12.2)
- test_normalization_ignores_formatting: whitespace/case/quote differences still match (Req 12.2)
- test_translation_failure_scores_miss : generator returning None counts as a miss (Req 12.2)
- test_trace_written_per_run           : a Trace row is persisted per run (Req 12.4)
- test_trace_failure_does_not_abort    : a trace write failure never aborts the run (Req 12.5)

Golden set (Req 12.1):
- test_golden_set_has_at_least_10_pairs : the shipped set has >= 10 valid pairs

API (httpx against the FastAPI app):
- test_api_empty_set_returns_400       : POST with empty set → 400 + Req 12.3 message
- test_api_run_and_report              : POST golden set → 201; GET report → 200 with accuracy
- test_api_report_unknown_run_404      : GET unknown evalRunId → 404
"""

from __future__ import annotations

import sqlglot
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from tallyai.db.models import Trace
from tallyai.services.eval_harness import (
    EMPTY_SET_MESSAGE,
    EmptyLabeledSetError,
    EvalHarness,
    LabeledPair,
    load_golden_set,
    normalize_sql,
)

TENANT_A = "tenant-a"


# ---------------------------------------------------------------------------
# Stub translators
# ---------------------------------------------------------------------------


class _MappingTranslator:
    """Translator that returns a canned SQL string per question."""

    def __init__(self, mapping: dict[str, str | None]):
        self._mapping = mapping

    async def generate_sql(self, question, schema, resolved_metrics):
        return self._mapping.get(question)


def _echo_translator(expected_by_question: dict[str, str]):
    """Return a plain callable that echoes the expected SQL (a perfect model)."""

    async def _gen(question: str):
        return expected_by_question.get(question)

    return _gen


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_set_raises():
    """An empty labeled set raises with the Req 12.3 message and no score."""
    harness = EvalHarness(translator=_MappingTranslator({}))
    with pytest.raises(EmptyLabeledSetError) as exc:
        await harness.run([])
    assert str(exc.value) == EMPTY_SET_MESSAGE
    assert "at least one labeled pair required" == EMPTY_SET_MESSAGE


@pytest.mark.asyncio
async def test_single_pair_perfect_accuracy():
    """A single pair whose generated SQL matches → accuracy 1.0 (Req 12.2)."""
    q = "What is total revenue?"
    expected = "SELECT SUM(amount) FROM payments"
    harness = EvalHarness(translator=_MappingTranslator({q: expected}))

    report = await harness.run([LabeledPair(question=q, expected_sql=expected, pair_id="p1")])

    assert report.total == 1
    assert report.matched == 1
    assert report.accuracy == 1.0
    assert report.per_pair[0].match is True
    assert report.per_pair[0].pair_id == "p1"


@pytest.mark.asyncio
async def test_single_pair_mismatch_zero():
    """A single mismatching pair → accuracy 0.0 (Req 12.2)."""
    q = "What is total revenue?"
    harness = EvalHarness(
        translator=_MappingTranslator({q: "SELECT 1"})
    )
    report = await harness.run(
        [LabeledPair(question=q, expected_sql="SELECT SUM(amount) FROM payments", pair_id="p1")]
    )
    assert report.accuracy == 0.0
    assert report.matched == 0
    assert report.per_pair[0].match is False


@pytest.mark.asyncio
async def test_mixed_accuracy_fraction():
    """k of n matching pairs → accuracy k/n (Req 12.2)."""
    pairs = [
        LabeledPair(question="q1", expected_sql="SELECT a FROM t", pair_id="p1"),
        LabeledPair(question="q2", expected_sql="SELECT b FROM t", pair_id="p2"),
        LabeledPair(question="q3", expected_sql="SELECT c FROM t", pair_id="p3"),
        LabeledPair(question="q4", expected_sql="SELECT d FROM t", pair_id="p4"),
    ]
    mapping = {
        "q1": "SELECT a FROM t",   # match
        "q2": "SELECT b FROM t",   # match
        "q3": "SELECT x FROM t",   # miss
        "q4": None,                # miss (no SQL)
    }
    harness = EvalHarness(translator=_MappingTranslator(mapping))
    report = await harness.run(pairs)
    assert report.total == 4
    assert report.matched == 2
    assert report.accuracy == 0.5


@pytest.mark.asyncio
async def test_normalization_ignores_formatting():
    """Whitespace/case/quoting differences still count as a match (Req 12.2)."""
    q = "revenue"
    expected = "SELECT SUM(amount) FROM payments WHERE status = 'completed'"
    # Same query, different formatting/case.
    generated = "select  sum(amount)\nfrom payments\nwhere status = 'completed';"
    harness = EvalHarness(translator=_MappingTranslator({q: generated}))
    report = await harness.run([LabeledPair(question=q, expected_sql=expected, pair_id="p1")])
    assert report.accuracy == 1.0


@pytest.mark.asyncio
async def test_translation_failure_scores_miss():
    """A translator returning None counts as a miss, not an error (Req 12.2)."""
    q = "unanswerable"
    harness = EvalHarness(translator=_MappingTranslator({q: None}))
    report = await harness.run([LabeledPair(question=q, expected_sql="SELECT 1", pair_id="p1")])
    assert report.accuracy == 0.0
    assert report.per_pair[0].generated_sql is None
    assert report.per_pair[0].match is False


@pytest.mark.asyncio
async def test_trace_written_per_run(db_session):
    """A Trace is persisted for each eval run (Req 12.4)."""
    q = "What is total revenue?"
    expected = "SELECT SUM(amount) FROM payments"
    harness = EvalHarness(translator=_MappingTranslator({q: expected}))

    report = await harness.run(
        [LabeledPair(question=q, expected_sql=expected, pair_id="p1")],
        tenant_id=TENANT_A,
        db=db_session,
        labeled_set_id="set-1",
    )
    await db_session.commit()

    # Exactly one trace ref returned, and one Trace row persisted for the tenant.
    assert len(report.trace_refs) == 1

    count = await db_session.scalar(
        select(func.count()).select_from(Trace).where(Trace.tenant_id == TENANT_A)
    )
    assert count == 1

    trace = (
        await db_session.execute(select(Trace).where(Trace.trace_id == report.trace_refs[0]))
    ).scalars().first()
    assert trace is not None
    assert trace.tenant_id == TENANT_A
    # Tool calls capture each evaluated pair.
    assert isinstance(trace.tool_calls, list)
    assert len(trace.tool_calls) == 1
    assert trace.tool_calls[0]["pairId"] == "p1"


@pytest.mark.asyncio
async def test_trace_failure_does_not_abort():
    """A trace write failure must not abort the run (Req 12.5)."""

    class _BrokenDB:
        def add(self, *_args, **_kwargs):
            raise RuntimeError("db is down")

        async def flush(self):  # pragma: no cover - never reached
            raise RuntimeError("db is down")

    q = "What is total revenue?"
    expected = "SELECT SUM(amount) FROM payments"
    harness = EvalHarness(translator=_MappingTranslator({q: expected}))

    report = await harness.run(
        [LabeledPair(question=q, expected_sql=expected, pair_id="p1")],
        tenant_id=TENANT_A,
        db=_BrokenDB(),
    )
    # Run still completes with a valid score; no trace ref recorded.
    assert report.accuracy == 1.0
    assert report.trace_refs == []


# ---------------------------------------------------------------------------
# Golden set (Req 12.1)
# ---------------------------------------------------------------------------


def test_golden_set_has_at_least_10_pairs():
    """The shipped golden set contains at least 10 valid NL->SQL pairs (Req 12.1)."""
    labeled_set_id, pairs = load_golden_set()
    assert labeled_set_id
    assert len(pairs) >= 10

    seen_ids: set[str] = set()
    for pair in pairs:
        assert pair.question.strip(), "every pair must have a question"
        assert pair.expected_sql.strip(), "every pair must have expected SQL"
        # pair ids are unique
        assert pair.pair_id not in seen_ids
        seen_ids.add(pair.pair_id)
        # expected SQL must parse and be a SELECT
        parsed = sqlglot.parse_one(pair.expected_sql, read="postgres")
        assert parsed.key.lower() == "select", f"{pair.pair_id} must be a SELECT"
        # normalization is stable
        assert normalize_sql(pair.expected_sql) is not None


# ---------------------------------------------------------------------------
# API-level tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client bound to the app with the test DB session and a stub harness."""
    from tallyai.db.session import get_db
    from tallyai.main import app
    from tallyai.api.eval import get_eval_harness

    async def _override_db():
        yield db_session

    # A perfect translator over the golden set so the API reports a real score.
    golden_id, pairs = load_golden_set()
    mapping = {p.question: p.expected_sql for p in pairs}

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_eval_harness] = lambda: EvalHarness(
        translator=_MappingTranslator(mapping)
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_empty_set_returns_400(client):
    """POST with an unknown/empty labeled set → 400 with the Req 12.3 message."""
    resp = await client.post(
        "/api/v1/eval/runs",
        params={"tenant_id": TENANT_A},
        json={"labeledSetId": "does-not-exist"},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "at least one labeled pair required"


@pytest.mark.asyncio
async def test_api_run_and_report(client, db_session):
    """POST golden set → 201 with evalRunId; GET report → 200 with accuracy (Req 12.2, 12.4)."""
    golden_id, pairs = load_golden_set()

    run_resp = await client.post(
        "/api/v1/eval/runs",
        params={"tenant_id": TENANT_A},
        json={"labeledSetId": golden_id},
    )
    assert run_resp.status_code == 201
    body = run_resp.json()
    eval_run_id = body["evalRunId"]
    assert body["status"] == "completed"

    report_resp = await client.get(f"/api/v1/eval/runs/{eval_run_id}/report")
    assert report_resp.status_code == 200
    report = report_resp.json()
    # Perfect stub translator over the golden set → accuracy 1.0.
    assert report["accuracy"] == 1.0
    assert len(report["perPair"]) == len(pairs)
    assert len(report["traceRefs"]) == 1

    # A Trace was persisted for the run (Req 12.4).
    count = await db_session.scalar(
        select(func.count()).select_from(Trace).where(Trace.tenant_id == TENANT_A)
    )
    assert count == 1


@pytest.mark.asyncio
async def test_api_report_unknown_run_404(client):
    """GET report for an unknown evalRunId → 404."""
    resp = await client.get("/api/v1/eval/runs/nonexistent/report")
    assert resp.status_code == 404
