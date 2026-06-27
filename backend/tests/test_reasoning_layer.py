"""
Tests for the Reasoning_Layer (Task 10).

Combines Hypothesis property-based tests for the universally-quantified
grounding/structural invariants with example unit tests for concrete
behaviours.

Property coverage (design Correctness Properties):
- Property 15 — Grounding invariant suppresses unbacked claims
  (``insights_are_grounded``, ``every_claim_has_source``).
- Property 17 — Answer structure completeness
  (``confidence_range_valid``, facts-vs-interpretation separation, chain).
- Property 18 — Causal questions flag correlation
  (``correlation_not_causation``).
- Req 11.2 recommendation framing (``recommendations_are_hedged``).
- Req 11.5 insufficient-data handling (``confidence_degrades_gracefully``).
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from tallyai.services.reasoning_layer import (
    CORRELATION_NOT_CAUSATION_FLAG,
    INSUFFICIENT_DATA_MESSAGE,
    VALID_CONFIDENCE,
    VALID_COVERAGE,
    ReasoningLayer,
)

# Hedge markers that prove a recommendation is framed as a hypothesis, not a
# command (Req 11.2).
HEDGE_MARKERS = (
    "consider",
    "investigat",
    "explore",
    "whether",
    "may ",
    "might",
    "could",
    "hypothesis",
    "potential",
    "possibly",
)


# ---------------------------------------------------------------------------
# Helpers / generators
# ---------------------------------------------------------------------------


def _reason(state: dict) -> dict:
    """Synchronously drive the async ReasoningLayer.reason for a test."""
    return asyncio.run(ReasoningLayer().reason(state))


_NUMERIC_COLS = ("amount", "revenue", "users", "count")
_TEXT_COLS = ("region", "status", "month")


@st.composite
def result_states(draw, *, allow_empty: bool = True, causal: bool | None = None):
    """Generate a plausible orchestrator state with executed-query results."""
    min_rows = 0 if allow_empty else 1
    n = draw(st.integers(min_value=min_rows, max_value=40))

    num_cols = draw(
        st.lists(st.sampled_from(_NUMERIC_COLS), unique=True, max_size=3)
    )
    txt_cols = draw(st.lists(st.sampled_from(_TEXT_COLS), unique=True, max_size=2))

    rows: list[dict] = []
    for _ in range(n):
        row: dict = {}
        for c in num_cols:
            row[c] = draw(
                st.one_of(
                    st.integers(min_value=-1000, max_value=1000),
                    st.floats(
                        min_value=-1e6,
                        max_value=1e6,
                        allow_nan=False,
                        allow_infinity=False,
                    ),
                )
            )
        for c in txt_cols:
            row[c] = draw(st.sampled_from(["north", "south", "active", "churned"]))
        if not row:  # guarantee at least one column so rows are non-trivial
            row["value"] = draw(st.integers(min_value=0, max_value=100))
        rows.append(row)

    truncated = draw(st.booleans())

    if causal is True:
        question = draw(
            st.sampled_from(
                [
                    "Why did revenue drop last month?",
                    "What caused the churn increase?",
                    "Why is active users declining?",
                ]
            )
        )
    elif causal is False:
        question = draw(
            st.sampled_from(
                [
                    "How many orders are there?",
                    "List total revenue by region.",
                    "Show me active users.",
                ]
            )
        )
    else:
        question = draw(
            st.sampled_from(
                [
                    "Why did revenue drop?",
                    "How many orders are there?",
                    "What caused churn?",
                    "List revenue by region.",
                ]
            )
        )

    query_id = draw(st.sampled_from(["q-1", "q-abc", "00000000-0000-0000-0000-000000000001"]))

    return {
        "question": question,
        "query_id": query_id,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# Property: every claim is grounded (Property 15, Req 9.2, 9.5)
# ---------------------------------------------------------------------------


@given(state=result_states())
@settings(max_examples=150, deadline=None)
def test_every_claim_has_source(state: dict) -> None:
    """**Validates: Requirements 9.2, 9.5**

    For any executed-query state, every presented QuantitativeClaim is bound to
    at least one backing query id, and that id is the query that produced it.
    """
    answer = _reason(state)
    for claim in answer["claims"]:
        assert claim["supporting_query_ids"], f"Ungrounded claim: {claim!r}"
        assert state["query_id"] in claim["supporting_query_ids"]


# ---------------------------------------------------------------------------
# Property: insights (claims + recommendations) are grounded (Property 15,
# Req 9.5, 11.3)
# ---------------------------------------------------------------------------


@given(state=result_states(allow_empty=False))
@settings(max_examples=150, deadline=None)
def test_insights_are_grounded(state: dict) -> None:
    """**Validates: Requirements 9.5, 11.3**

    Every claim and every recommendation surfaced by the reasoning layer cites
    a backing query id; nothing unbacked is ever presented.
    """
    answer = _reason(state)
    for item in (*answer["claims"], *answer["recommendations"]):
        assert item["supporting_query_ids"], f"Ungrounded item: {item!r}"
        assert state["query_id"] in item["supporting_query_ids"]


# ---------------------------------------------------------------------------
# Property: recommendations are hedged hypotheses (Req 11.2, 11.3)
# ---------------------------------------------------------------------------


@given(state=result_states(allow_empty=False))
@settings(max_examples=150, deadline=None)
def test_recommendations_are_hedged(state: dict) -> None:
    """**Validates: Requirements 11.2, 11.3**

    Every recommendation is phrased as a hypothesis to investigate (contains a
    hedge marker, never an imperative command) and carries its supporting
    signal plus backing query ids.
    """
    answer = _reason(state)
    assert answer["recommendations"], "Expected at least one recommendation"
    for rec in answer["recommendations"]:
        hypothesis = rec["hypothesis"].lower()
        assert any(marker in hypothesis for marker in HEDGE_MARKERS), (
            f"Recommendation not hedged as a hypothesis: {rec['hypothesis']!r}"
        )
        assert rec["supporting_signal"], "Recommendation missing supporting signal"
        assert rec["supporting_query_ids"], "Recommendation missing query ids"


# ---------------------------------------------------------------------------
# Property: causal questions flag correlation≠causation (Property 18, Req 11.4)
# ---------------------------------------------------------------------------


@given(state=result_states(allow_empty=False, causal=True))
@settings(max_examples=150, deadline=None)
def test_correlation_not_causation(state: dict) -> None:
    """**Validates: Requirements 11.4**

    For any "why did X change" question with sufficient data, the answer
    surfaces correlated drivers and always flags that correlation does not
    establish causation.
    """
    answer = _reason(state)
    assert answer["correlation_flag"] == CORRELATION_NOT_CAUSATION_FLAG
    assert "causation" in answer["correlation_flag"].lower()
    # Correlated drivers are surfaced in the interpretation, not as fact.
    assert answer["interpretation"], "Expected correlated-driver interpretation"


# ---------------------------------------------------------------------------
# Property: confidence degrades gracefully on insufficient data (Req 11.5)
# ---------------------------------------------------------------------------


@given(
    question=st.sampled_from(
        ["Why did revenue drop?", "How many orders?", "Show me churn."]
    ),
    has_query_id=st.booleans(),
)
@settings(max_examples=100, deadline=None)
def test_confidence_degrades_gracefully(question: str, has_query_id: bool) -> None:
    """**Validates: Requirements 11.5**

    When the executed results are insufficient (no rows, or no executed query),
    the layer states the data is insufficient, fabricates no claims, no
    interpretation, and no recommendations, and reports low/none indicators.
    """
    state = {
        "question": question,
        "query_id": "q-1" if has_query_id else None,
        "rows": [],
        "row_count": 0,
        "truncated": False,
    }
    answer = _reason(state)

    assert answer["insufficient_data"] is True
    assert answer["claims"] == []
    assert answer["recommendations"] == []
    assert answer["interpretation"] == []
    assert answer["correlation_flag"] is None
    assert INSUFFICIENT_DATA_MESSAGE in answer["facts"]
    assert answer["confidence"] == "low"
    assert answer["coverage"] == "none"


# ---------------------------------------------------------------------------
# Property: confidence/coverage indicators are always valid (Property 17,
# Req 11.7)
# ---------------------------------------------------------------------------


@given(state=result_states())
@settings(max_examples=150, deadline=None)
def test_confidence_range_valid(state: dict) -> None:
    """**Validates: Requirements 11.7**

    Every claim — and the overall conclusion — carries a confidence indicator
    and a coverage indicator drawn from the valid vocabularies.
    """
    answer = _reason(state)
    assert answer["confidence"] in VALID_CONFIDENCE
    assert answer["coverage"] in VALID_COVERAGE
    for claim in answer["claims"]:
        assert claim["confidence"] in VALID_CONFIDENCE
        assert claim["coverage"] in VALID_COVERAGE


# ---------------------------------------------------------------------------
# Example unit tests
# ---------------------------------------------------------------------------


def test_facts_are_separate_from_interpretation() -> None:
    """**Validates: Requirements 11.1**

    Computed facts and interpretation live in structurally distinct fields.
    """
    state = {
        "question": "List revenue by region.",
        "query_id": "q-1",
        "rows": [{"region": "north", "revenue": 100}, {"region": "south", "revenue": 50}],
        "row_count": 2,
        "truncated": False,
    }
    answer = _reason(state)
    assert "facts" in answer and "interpretation" in answer
    assert answer["facts"] and isinstance(answer["facts"], list)
    # Facts and interpretation are different objects with no shared entries.
    assert set(answer["facts"]).isdisjoint(set(answer["interpretation"]))


def test_chain_exposes_full_reasoning_path() -> None:
    """**Validates: Requirements 11.6**

    The chain exposes the question, executed query ids, computed numbers,
    reasoning and recommendations for review.
    """
    state = {
        "question": "How many orders are there?",
        "query_id": "q-42",
        "rows": [{"amount": 10}, {"amount": 20}, {"amount": 30}],
        "row_count": 3,
        "truncated": False,
    }
    answer = _reason(state)
    chain = answer["chain"]
    assert chain["question"] == "How many orders are there?"
    assert chain["executed_query_ids"] == ["q-42"]
    assert chain["computed_numbers"]  # at least the row-count claim value
    assert chain["reasoning"]
    assert chain["recommendations"]


def test_truncated_results_reduce_coverage() -> None:
    """**Validates: Requirements 11.7**

    A truncated result set yields partial coverage rather than full.
    """
    state = {
        "question": "List revenue by region.",
        "query_id": "q-1",
        "rows": [{"revenue": 1} for _ in range(40)],
        "row_count": 40,
        "truncated": True,
    }
    answer = _reason(state)
    assert answer["coverage"] == "partial"
    for claim in answer["claims"]:
        assert claim["coverage"] == "partial"


def test_non_causal_question_has_no_correlation_flag() -> None:
    """**Validates: Requirements 11.4**

    A non-causal question does not raise the correlation-vs-causation flag.
    """
    state = {
        "question": "How many active users are there?",
        "query_id": "q-1",
        "rows": [{"users": 5}],
        "row_count": 1,
        "truncated": False,
    }
    answer = _reason(state)
    assert answer["correlation_flag"] is None
