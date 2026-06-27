"""
Reasoning_Layer — turns executed query results into a grounded, consultant-style
answer (Req 9.2, 9.5, 11.1–11.7).

The layer is the model-driven ``reasoning_recommendations`` node from the design
state machine, but its *trust-critical* behaviour is implemented as deterministic
non-model code so the grounding and structural invariants hold regardless of any
LLM output:

* Computed **facts** are held in fields structurally distinct from
  **interpretation** (Req 11.1).
* Every :class:`QuantitativeClaim` is bound to the ``supporting_query_ids`` that
  produced it; claims with no backing query are suppressed and never presented
  (Req 9.2, 9.5).
* Recommendations are phrased as **hypotheses to investigate**, never as
  commands, and each carries its supporting signal + query ids (Req 11.2, 11.3).
* "Why / what caused" questions surface **correlated drivers** and always flag
  that correlation does not establish causation (Req 11.4).
* When the executed results are insufficient, the layer says so and fabricates
  **no** narrative (Req 11.5).
* The full chain (question → executed queries → computed numbers → reasoning →
  recommendations) is exposed for review (Req 11.6) and every claim/conclusion
  carries a **confidence** and **coverage** indicator (Req 11.7).

An LLM may be injected to enrich the prose *interpretation* only; it is fully
optional and mockable like :class:`NLTranslator` / :class:`Explainer`. The
deterministic core never depends on it, so the grounding and structural
properties remain provable.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Indicator vocabularies (Req 11.7)
# ---------------------------------------------------------------------------

VALID_CONFIDENCE: tuple[str, ...] = ("low", "medium", "high")
VALID_COVERAGE: tuple[str, ...] = ("none", "partial", "full")

# Standard, user-facing correlation-vs-causation disclaimer (Req 11.4).
CORRELATION_NOT_CAUSATION_FLAG: str = (
    "These are correlated drivers. Correlation does not establish causation; "
    "further investigation is required before drawing a causal conclusion."
)

# Message used when the executed results cannot support a narrative (Req 11.5).
INSUFFICIENT_DATA_MESSAGE: str = (
    "The available data is insufficient to support a narrative answer."
)

# Phrases that detect a causal ("why did X change") question (Req 11.4).
_CAUSAL_RE = re.compile(
    r"\b(why|cause[sd]?|causing|reason|because|driver|drove|driven|"
    r"led to|due to|attribut|explain|account for|root cause)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers (pure)
# ---------------------------------------------------------------------------


def _is_causal_question(question: str) -> bool:
    """True when *question* asks about the cause of an observed change."""
    return bool(question) and _CAUSAL_RE.search(question) is not None


def _numeric_columns(rows: list[dict]) -> list[str]:
    """Return the column names whose first-row value is a real number.

    ``bool`` is excluded even though it subclasses ``int`` — a boolean flag is
    not a quantitative measure.
    """
    if not rows or not isinstance(rows[0], dict):
        return []
    cols: list[str] = []
    for key, value in rows[0].items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            cols.append(key)
    return cols


def _column_total(rows: list[dict], column: str) -> float:
    """Sum a numeric column across rows, ignoring non-numeric / missing cells."""
    total = 0.0
    for row in rows:
        value = row.get(column)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            total += float(value)
    return total


def _confidence_for(row_count: int, truncated: bool) -> str:
    """Map result size to a confidence indicator (Req 11.7)."""
    if row_count <= 0:
        return "low"
    if truncated:
        # Truncation means we only saw part of the result set.
        return "medium"
    if row_count >= 30:
        return "high"
    if row_count >= 5:
        return "medium"
    return "low"


def _coverage_for(row_count: int, truncated: bool) -> str:
    """Map result completeness to a coverage indicator (Req 11.7)."""
    if row_count <= 0:
        return "none"
    return "partial" if truncated else "full"


# ---------------------------------------------------------------------------
# Reasoning layer
# ---------------------------------------------------------------------------


class ReasoningLayer:
    """Produces a grounded :class:`Answer`-shaped dict from executed results.

    The single entry point, :meth:`reason`, accepts the orchestrator's
    ``QueryState`` mapping so the instance can be injected directly as
    ``OrchestratorDeps.reasoning = ReasoningLayer().reason`` (replacing the old
    ``_default_reasoning`` stub).
    """

    def __init__(self, llm: Any = None) -> None:
        # Optional, mockable LLM used ONLY to enrich interpretation prose.
        self._llm = llm

    async def reason(self, state: dict) -> dict:
        """Build a grounded answer from the executed-query state.

        Parameters
        ----------
        state:
            The orchestrator ``QueryState`` (or any mapping) carrying at least
            ``question``, ``query_id``, ``rows``, ``row_count`` and
            ``truncated``.

        Returns
        -------
        dict
            An answer envelope with ``facts``, ``interpretation``,
            ``recommendations``, ``claims``, ``correlation_flag``,
            ``insufficient_data``, ``confidence``, ``coverage`` and ``chain``.
            Only grounded claims/recommendations are present (Req 9.5).
        """
        question: str = state.get("question") or ""
        query_id = state.get("query_id")
        rows: list[dict] = state.get("rows") or []
        row_count: int = state.get("row_count", len(rows))
        truncated: bool = bool(state.get("truncated", False))

        # ------------------------------------------------------------------
        # Insufficient data → say so, fabricate nothing (Req 11.5)
        # ------------------------------------------------------------------
        if query_id is None or row_count <= 0:
            return self._insufficient_answer(question, query_id)

        confidence = _confidence_for(row_count, truncated)
        coverage = _coverage_for(row_count, truncated)
        numeric_cols = _numeric_columns(rows)

        # ------------------------------------------------------------------
        # Facts — computed numbers, structurally separate from interpretation
        # (Req 11.1). Every fact-derived claim is bound to the query id that
        # produced it (Req 9.2).
        # ------------------------------------------------------------------
        facts: list[str] = [
            f"The executed query returned {row_count} row(s)"
            + (" (results were truncated to the row cap)." if truncated else ".")
        ]
        claims: list[dict] = [
            self._claim(
                text=f"The query returned {row_count} row(s).",
                value=float(row_count),
                query_id=query_id,
                confidence=confidence,
                coverage=coverage,
            )
        ]

        for column in numeric_cols[:3]:
            total = _column_total(rows, column)
            facts.append(f"Total of '{column}' across the result set is {total:g}.")
            claims.append(
                self._claim(
                    text=f"Total '{column}' is {total:g} across {row_count} row(s).",
                    value=total,
                    query_id=query_id,
                    confidence=confidence,
                    coverage=coverage,
                )
            )

        # ------------------------------------------------------------------
        # Interpretation — narrative, kept separate from facts (Req 11.1).
        # Optionally enriched by an injected LLM; never trusted for grounding.
        # ------------------------------------------------------------------
        interpretation: list[str] = []
        causal = _is_causal_question(question)
        correlation_flag: str | None = None

        if causal:
            # Surface correlated drivers and ALWAYS flag correlation≠causation
            # (Req 11.4).
            correlation_flag = CORRELATION_NOT_CAUSATION_FLAG
            if numeric_cols:
                driver = numeric_cols[0]
                interpretation.append(
                    f"'{driver}' moves alongside the observed change and is a "
                    f"correlated driver worth examining."
                )
            else:
                interpretation.append(
                    "The result rows are correlated with the observed change and "
                    "warrant closer examination."
                )
        else:
            interpretation.append(
                "The figures above summarise the result set; treat the "
                "interpretation below as analysis rather than established fact."
            )

        enriched = await self._maybe_enrich(question, facts, interpretation)
        if enriched:
            interpretation = enriched

        # ------------------------------------------------------------------
        # Recommendations — hypotheses to investigate, never commands
        # (Req 11.2), each with its supporting signal + query ids (Req 11.3).
        # ------------------------------------------------------------------
        recommendations: list[dict] = [
            self._recommendation(numeric_cols, rows, row_count, query_id)
        ]

        # ------------------------------------------------------------------
        # Grounding chokepoint (Req 9.5): suppress anything lacking a backing
        # query id. The deterministic builders above always attach one, but we
        # filter defensively so an unbacked item can never escape.
        # ------------------------------------------------------------------
        claims = [c for c in claims if c.get("supporting_query_ids")]
        recommendations = [
            r for r in recommendations if r.get("supporting_query_ids")
        ]

        chain = {
            "question": question,
            "executed_query_ids": [query_id],
            "computed_numbers": [c["value"] for c in claims],
            "reasoning": list(interpretation),
            "recommendations": [r["hypothesis"] for r in recommendations],
        }

        return {
            "facts": facts,
            "interpretation": interpretation,
            "recommendations": recommendations,
            "claims": claims,
            "correlation_flag": correlation_flag,
            "insufficient_data": False,
            "confidence": confidence,
            "coverage": coverage,
            "chain": chain,
        }

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    @staticmethod
    def _claim(
        *,
        text: str,
        value: float,
        query_id: str,
        confidence: str,
        coverage: str,
    ) -> dict:
        """Construct a grounded QuantitativeClaim dict (Req 9.2, 11.7)."""
        return {
            "text": text,
            "value": float(value),
            "supporting_query_ids": [query_id],
            "confidence": confidence,
            "coverage": coverage,
        }

    @staticmethod
    def _recommendation(
        numeric_cols: list[str],
        rows: list[dict],
        row_count: int,
        query_id: str,
    ) -> dict:
        """Build a hedged, grounded recommendation (Req 11.2, 11.3).

        The hypothesis is always phrased as an investigation prompt
        ("Consider investigating whether …"), never as an imperative command.
        """
        if numeric_cols:
            column = numeric_cols[0]
            total = _column_total(rows, column)
            return {
                "hypothesis": (
                    f"Consider investigating whether movements in '{column}' are "
                    f"driving the observed results, as a hypothesis to validate."
                ),
                "supporting_signal": (
                    f"'{column}' totals {total:g} across {row_count} row(s)."
                ),
                "supporting_query_ids": [query_id],
            }
        return {
            "hypothesis": (
                "Consider investigating whether the result volume reflects an "
                "underlying trend worth exploring further."
            ),
            "supporting_signal": f"The query returned {row_count} row(s).",
            "supporting_query_ids": [query_id],
        }

    @staticmethod
    def _insufficient_answer(question: str, query_id: Any) -> dict:
        """Answer envelope used when data cannot support a narrative (Req 11.5).

        Fabricates no claims, no interpretation, and no recommendations.
        """
        return {
            "facts": [INSUFFICIENT_DATA_MESSAGE],
            "interpretation": [],
            "recommendations": [],
            "claims": [],
            "correlation_flag": None,
            "insufficient_data": True,
            "confidence": "low",
            "coverage": "none",
            "chain": {
                "question": question,
                "executed_query_ids": [query_id] if query_id is not None else [],
                "computed_numbers": [],
                "reasoning": [],
                "recommendations": [],
            },
        }

    # ------------------------------------------------------------------
    # Optional LLM enrichment (prose only — never affects grounding)
    # ------------------------------------------------------------------

    async def _maybe_enrich(
        self, question: str, facts: list[str], interpretation: list[str]
    ) -> list[str] | None:
        """Use the injected LLM to refine interpretation prose, if available.

        Returns ``None`` (keeping the deterministic interpretation) on any
        failure, so reasoning degrades gracefully and never blocks on the model.
        """
        if self._llm is None:
            return None
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            system = (
                "You are a careful data analyst. Given computed facts, write a "
                "brief interpretation (1-3 sentences). Do not invent numbers; "
                "phrase any suggestion as a hypothesis, not a command."
            )
            human = (
                f"Question: {question}\n"
                f"Facts:\n- " + "\n- ".join(facts) + "\n\n"
                "Interpretation:"
            )
            response = self._llm.ainvoke(
                [SystemMessage(content=system), HumanMessage(content=human)]
            )
            if inspect.isawaitable(response):
                response = await response
            content = getattr(response, "content", str(response))
            text = (content or "").strip()
            return [text] if text else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("ReasoningLayer enrichment failed: %s", exc)
            return None
