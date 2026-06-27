"""
Unit tests for the analytics and charts layer (Task 11).

Covers ``build_chart_response`` against the default-response acceptance
criteria:

- chartable result   → chart + summary + insights bound to query_ids (Req 10.1, 10.4)
- non-chartable result → table + summary, no chart (Req 10.3)
- truncated result   → ``truncated: True`` surfaced (Req 4.5, 10.x)
- underlying table is always available for chartable results (Req 10.2)
"""

from __future__ import annotations

from datetime import date

from tallyai.services.analytics import build_chart_response

QUERY_ID = "query-123"


# ---------------------------------------------------------------------------
# Chartable results (Req 10.1, 10.2, 10.4)
# ---------------------------------------------------------------------------


def test_categorical_plus_numeric_is_chartable_with_chart_summary_insights():
    """A category + measure result is chartable: chart + summary + grounded insights."""
    state = {
        "rows": [
            {"region": "north", "revenue": 100},
            {"region": "south", "revenue": 250},
            {"region": "east", "revenue": 175},
        ],
        "query_id": QUERY_ID,
        "truncated": False,
    }

    resp = build_chart_response(state)

    assert resp["chartable"] is True
    assert resp["chart"] is not None
    assert resp["summary"]
    assert resp["insights"]  # at least one insight

    # Every insight is bound to the producing query_id (Req 10.4).
    for insight in resp["insights"]:
        assert insight["supporting_query_ids"] == [QUERY_ID]

    # Underlying table remains available (Req 10.2).
    assert resp["table"] == state["rows"]
    assert resp["truncated"] is False


def test_chart_spec_is_vega_lite_with_encodings():
    """The chart is a self-contained Vega-Lite spec with x/y encodings and inline data."""
    state = {
        "rows": [
            {"region": "north", "revenue": 100},
            {"region": "south", "revenue": 250},
        ],
        "query_id": QUERY_ID,
    }

    chart = build_chart_response(state)["chart"]

    assert chart["$schema"].startswith("https://vega.github.io/schema/vega-lite")
    assert chart["encoding"]["x"]["field"] == "region"
    assert chart["encoding"]["y"]["field"] == "revenue"
    assert chart["encoding"]["x"]["type"] == "nominal"
    assert chart["encoding"]["y"]["type"] == "quantitative"
    assert chart["mark"] == "bar"
    assert chart["data"]["values"] == state["rows"]


def test_temporal_x_axis_uses_line_mark_and_iso_dates():
    """A date dimension yields a line chart with JSON-safe ISO date values."""
    state = {
        "rows": [
            {"day": date(2025, 1, 1), "signups": 5},
            {"day": date(2025, 1, 2), "signups": 9},
        ],
        "query_id": QUERY_ID,
    }

    resp = build_chart_response(state)
    chart = resp["chart"]

    assert resp["chartable"] is True
    assert chart["mark"] == "line"
    assert chart["encoding"]["x"]["type"] == "temporal"
    # date coerced to ISO string for JSON safety.
    assert chart["data"]["values"][0]["day"] == "2025-01-01"


def test_insights_report_total_and_top_value():
    """Insights surface the total and the top measure bound by dimension."""
    state = {
        "rows": [
            {"region": "north", "revenue": 100},
            {"region": "south", "revenue": 250},
        ],
        "query_id": QUERY_ID,
    }

    texts = " ".join(i["text"] for i in build_chart_response(state)["insights"])

    assert "row(s)" in texts
    assert "Total revenue" in texts
    assert "south" in texts  # the highest-revenue dimension label


# ---------------------------------------------------------------------------
# Non-chartable results (Req 10.3)
# ---------------------------------------------------------------------------


def test_single_column_scalar_is_not_chartable_table_and_summary():
    """A single aggregate column is not chartable → table + summary, no chart."""
    state = {
        "rows": [{"total_orders": 42}],
        "query_id": QUERY_ID,
    }

    resp = build_chart_response(state)

    assert resp["chartable"] is False
    assert resp["chart"] is None
    assert resp["table"] == state["rows"]
    assert resp["summary"]


def test_all_categorical_columns_not_chartable():
    """Rows with no numeric measure cannot be charted (Req 10.3)."""
    state = {
        "rows": [
            {"name": "Ada", "city": "London"},
            {"name": "Bob", "city": "Paris"},
        ],
        "query_id": QUERY_ID,
    }

    resp = build_chart_response(state)

    assert resp["chartable"] is False
    assert resp["chart"] is None
    assert resp["table"] == state["rows"]
    assert resp["summary"]


def test_empty_result_is_not_chartable():
    """An empty result set is not chartable and emits no insights."""
    resp = build_chart_response({"rows": [], "query_id": QUERY_ID})

    assert resp["chartable"] is False
    assert resp["chart"] is None
    assert resp["table"] == []
    assert resp["insights"] == []
    assert "no rows" in resp["summary"].lower()


# ---------------------------------------------------------------------------
# Truncation (Req 4.5)
# ---------------------------------------------------------------------------


def test_truncated_result_flags_truncation_true():
    """When the executor truncated to Row_Cap, the envelope flags truncated=True."""
    state = {
        "rows": [
            {"region": "north", "revenue": 100},
            {"region": "south", "revenue": 250},
        ],
        "query_id": QUERY_ID,
        "truncated": True,
    }

    resp = build_chart_response(state)

    assert resp["truncated"] is True
    assert "truncated" in resp["summary"].lower()


def test_truncated_defaults_to_false_when_absent():
    """Absent truncation flag defaults to False."""
    resp = build_chart_response({"rows": [{"a": "x", "b": 1}], "query_id": QUERY_ID})
    assert resp["truncated"] is False


# ---------------------------------------------------------------------------
# Grounding (Req 10.4) — no query_id means no ungrounded insights
# ---------------------------------------------------------------------------


def test_no_query_id_yields_no_insights():
    """Without a backing query_id no insight is emitted (keeps insights grounded)."""
    state = {
        "rows": [{"region": "north", "revenue": 100}],
        "query_id": None,
    }

    resp = build_chart_response(state)

    assert resp["insights"] == []
    # Chartability is independent of grounding.
    assert resp["chartable"] is True


def test_boolean_column_is_not_treated_as_numeric_measure():
    """Booleans must not count as a numeric measure (would mis-classify charts)."""
    state = {
        "rows": [
            {"name": "Ada", "active": True},
            {"name": "Bob", "active": False},
        ],
        "query_id": QUERY_ID,
    }

    resp = build_chart_response(state)

    assert resp["chartable"] is False
    assert resp["chart"] is None
