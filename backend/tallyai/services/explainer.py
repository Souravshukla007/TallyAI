"""
Explainer — produces plain-English descriptions of SQL queries.

Req 7.1, 7.3: Describes the query and names resolved metric definitions.
Req 7.4:      Returns None on failure (graceful degradation).
"""
from __future__ import annotations
import logging

from tallyai.services.nl_translator import _build_llm_from_env

logger = logging.getLogger(__name__)


class Explainer:
    def __init__(self, llm=None):
        self._llm = llm

    def _get_llm(self):
        if self._llm is None:
            self._llm = _build_llm_from_env()
        return self._llm

    async def explain(
        self,
        sql_text: str,
        resolved_metrics: list[dict],
    ) -> str | None:
        from langchain_core.messages import HumanMessage, SystemMessage
        try:
            metric_context = ""
            if resolved_metrics:
                names = ", ".join(m["name"] for m in resolved_metrics)
                metric_context = f"\nBusiness metrics referenced: {names}"

            system_prompt = (
                "You are a SQL explainer. Describe the following SQL query in plain English "
                "in 1-3 sentences. If business metrics are referenced, name them." + metric_context
            )
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"SQL:\n{sql_text}"),
            ]
            response = await self._get_llm().ainvoke(messages)
            return getattr(response, "content", str(response))
        except Exception as exc:
            logger.warning("Explainer.explain failed: %s", exc)
            return None
