"""
Analytics and charts layer (Task 11).

Builds the default ``/results`` response envelope from an executed query's
result rows. This is the implementation behind the ``analytics_charts``
orchestration node and replaces the ``_default_analytics`` stub.

Responsibilities (Req 10.1-10.4, 4.5):

* **Chartability** — classify whether the result set can be charted. A result
  is chartable when it has at least one row, at least two columns, at least one
  quantitative (numeric) measure column, and at least one column to plot it
  against (Req 10.1, 10.3).
* **Chart spec** — when chartable, build a self-contained Vega-Lite JSON spec
  (mark + encodings + inline data). When not chartable the chart is ``None`` and
  the caller falls back to the result table (Req 10.1, 10.2, 10.3).
* **Summary** — always produce a plain-language summary string (Req 10.1, 10.3).
* **Insights** — derive a small set of grounded insights, each bound to the
  producing ``query_id`` so they remain traceable (Req 10.4). Insights are only
  emitted when a backing ``query_id`` is present, so an ungrounded insight is
  never produced.
* **Truncation** — surface the executor's Row_Cap truncation flag (Req 4.5).

The function is deterministic and model-free: chart/summary/insights are a pure
function of the result rows and the execution metadata in ``state``.

Returned envelope (keys consumed by the orchestrator / ``GET /results``)::

    {
        "chartable": bool,
        "chart": dict | None,        # Vega-Lite spec when chartable
        "table": list[dict],         # always available (Req 10.2, 10.3)
        "summary": str,
        "insights": [{"text": str, "supporting_query_ids": list[str]}],
        "truncated": bool,
    }
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

# A bool is an int subclass in Python; exclude it from numeric measures.
_NUMERIC_TYPES = (int, float)


def _is_numeric(value: Any) -> bool:
    """True for int/float values, excluding bool (Req 10.1 measure detection)."""
    return isinstance(value, _NUMERIC_TYPES) and not isinstance(value, bool)


def _is_temporal(value: Any) -> bool:
    """True for date / datetime values (used to pick a line-chart x-axis)."""
    return isinstance(value, (date, datetime))


def _column_names(rows: list[dict]) -> list[str]:
    """Stable, order-preserving union of column names across all rows."""
    seen: dict[str, None] = {}
    for row in rows:
        for key in row.keys():
            seen.setdefault(key, None)
    return list(seen.keys())


def _classify_columns(
    rows: list[dict], columns: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """Partition columns into (numeric, temporal, categorical).

    A column is numeric only when at least one non-null value is present and
    every non-null value is numeric. Temporal columns hold date/datetime
    values. Everything else (strings, mixed, all-null) is categorical.
    """
    numeric: list[str] = []
    temporal: list[str] = []
    categorical: list[str] = []

    for col in columns:
        values = [row.get(col) for row in rows]
        non_null = [v for v in values if v is not None]
        if non_null and all(_is_numeric(v) for v in non_null):
            numeric.append(col)
        elif non_null and all(_is_temporal(v) for v in non_null):
            temporal.append(col)
        else:
            categorical.append(col)

    return numeric, temporal, categorical


def _vega_type(col: str, numeric: list[str], temporal: list[str]) -> str:
    """Map a column to a Vega-Lite measurement type."""
    if col in temporal:
        return "temporal"
    if col in numeric:
        return "quantitative"
    return "nominal"


def _json_safe(value: Any) -> Any:
    """Coerce a cell value into something JSON/Vega-Lite friendly."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _build_vega_lite_spec(
    rows: list[dict],
    x_field: str,
    y_field: str,
    numeric: list[str],
    temporal: list[str],
) -> dict:
    """Build a minimal, self-contained Vega-Lite v5 spec.

    Mark is chosen from the x-axis type: line for temporal, bar for nominal,
    point for quantitative-vs-quantitative (scatter).
    """
    x_type = _vega_type(x_field, numeric, temporal)
    if x_type == "temporal":
        mark = "line"
    elif x_type == "quantitative":
        mark = "point"
    else:
        mark = "bar"

    data_values = [
        {k: _json_safe(v) for k, v in row.items()} for row in rows
    ]

    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": data_values},
        "mark": mark,
        "encoding": {
            "x": {"field": x_field, "type": x_type},
            "y": {"field": y_field, "type": "quantitative"},
        },
    }


def _format_number(value: Any) -> str:
    """Render a numeric value compactly for summary/insight text."""
    if isinstance(value, float):
        # Trim trailing zeros while keeping reasonable precision.
        return f"{value:.4g}"
    return str(value)


def _build_insights(
    rows: list[dict],
    measure: str | None,
    dimension: str | None,
    query_id: str | None,
) -> list[dict]:
    """Derive grounded insights, each bound to *query_id* (Req 10.4).

    No insight is emitted without a backing ``query_id`` so every presented
    insight is traceable to the query that produced it.
    """
    if not query_id or not rows:
        return []

    qids = [query_id]
    insights: list[dict] = [
        {
            "text": f"The result set contains {len(rows)} row(s).",
            "supporting_query_ids": qids,
        }
    ]

    if measure is not None:
        measured = [
            (row.get(measure), row) for row in rows if _is_numeric(row.get(measure))
        ]
        if measured:
            values = [v for v, _ in measured]
            total = sum(values)
            top_value, top_row = max(measured, key=lambda pair: pair[0])

            insights.append(
                {
                    "text": (
                        f"Total {measure} across {len(measured)} row(s) is "
                        f"{_format_number(total)}."
                    ),
                    "supporting_query_ids": qids,
                }
            )

            if dimension is not None and dimension in top_row:
                label = top_row.get(dimension)
                insights.append(
                    {
                        "text": (
                            f"The highest {measure} is {_format_number(top_value)} "
                            f"for {dimension} = {label}."
                        ),
                        "supporting_query_ids": qids,
                    }
                )
            else:
                insights.append(
                    {
                        "text": (
                            f"The highest {measure} observed is "
                            f"{_format_number(top_value)}."
                        ),
                        "supporting_query_ids": qids,
                    }
                )

    return insights


def build_chart_response(state: Mapping[str, Any]) -> dict:
    """Build the default analytics/chart response envelope from *state*.

    Parameters
    ----------
    state:
        Orchestration state (or any mapping) carrying ``rows``, ``query_id``,
        and ``truncated`` produced by the ``execution`` node.

    Returns
    -------
    dict
        Envelope with ``chartable``, ``chart``, ``table``, ``summary``,
        ``insights`` and ``truncated`` keys (Req 10.1-10.4, 4.5).
    """
    rows_raw = state.get("rows") or []
    rows: list[dict] = [r for r in rows_raw if isinstance(r, dict)]
    query_id = state.get("query_id")
    truncated = bool(state.get("truncated", False))

    columns = _column_names(rows)
    numeric, temporal, categorical = _classify_columns(rows, columns)

    # ------------------------------------------------------------------
    # Chartability (Req 10.1, 10.3)
    # A chart needs a measure (numeric y) and a separate axis to plot against.
    # ------------------------------------------------------------------
    chartable = bool(rows) and len(columns) >= 2 and len(numeric) >= 1 and (
        len(temporal) >= 1 or len(categorical) >= 1 or len(numeric) >= 2
    )

    chart: dict | None = None
    measure: str | None = None
    dimension: str | None = None

    if chartable:
        measure = numeric[0]
        # Prefer a temporal or categorical x-axis; otherwise scatter on a
        # second numeric column.
        if temporal:
            dimension = temporal[0]
        elif categorical:
            dimension = categorical[0]
        else:
            # numeric vs numeric — use the next numeric column as x.
            dimension = numeric[1]
            measure = numeric[0]

        chart = _build_vega_lite_spec(rows, dimension, measure, numeric, temporal)

    # ------------------------------------------------------------------
    # Summary (Req 10.1, 10.3)
    # ------------------------------------------------------------------
    if not rows:
        summary = "The query returned no rows."
    elif chartable:
        summary = (
            f"Query returned {len(rows)} row(s); charting {measure} "
            f"by {dimension}."
        )
    else:
        summary = (
            f"Query returned {len(rows)} row(s) across "
            f"{len(columns)} column(s); showing the result table."
        )
    if truncated:
        summary += " Results were truncated to the configured row cap."

    insights = _build_insights(rows, measure, dimension, query_id)

    return {
        "chartable": chartable,
        "chart": chart,
        "table": rows,
        "summary": summary,
        "insights": insights,
        "truncated": truncated,
    }
