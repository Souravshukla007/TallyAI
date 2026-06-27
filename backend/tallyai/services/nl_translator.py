"""
NL_Translator — converts natural-language questions to candidate SQL.

Req 2.1, 2.2: Uses cached schema + resolved metric formulas as context.
Req 2.3:      Returns None when no SQL can be produced.
Req 1.5:      Credentials are never placed in prompts.
"""
from __future__ import annotations
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

_SQL_BLOCK_RE = re.compile(r"```sql\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_SELECT_RE = re.compile(r"\bSELECT\b", re.IGNORECASE)


def _build_llm_from_env():
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    model = os.getenv("LLM_MODEL")
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model or "gpt-4o")
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model or "claude-3-5-sonnet-latest")
    elif provider in ("gemini", "google", "google-genai"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model or "gemini-2.0-flash")
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")


def _build_system_prompt(schema: dict, resolved_metrics: list[dict]) -> str:
    """Build the SQL generation system prompt from schema and metrics.
    Credentials are never included (Req 1.5)."""
    tables_section = ""
    for table in schema.get("tables", []):
        col_names = [c["name"] for c in table.get("columns", [])]
        tables_section += f"  - {table['name']}: {', '.join(col_names)}\n"

    metrics_section = ""
    for m in resolved_metrics:
        metrics_section += f"  - {m['name']}: formula={m['formula']}"
        if m.get("condition"):
            metrics_section += f", condition={m['condition']}"
        metrics_section += "\n"

    prompt = (
        "You are a SQL generation assistant. Generate a single valid PostgreSQL SELECT query.\n\n"
        "Database schema:\n" + (tables_section or "  (no schema provided)\n") +
        "\nBusiness metric definitions to use:\n" + (metrics_section or "  (none)\n") +
        "\nRules:\n"
        "- Output ONLY a SQL code block (```sql ... ```) with a single SELECT statement.\n"
        "- Do not modify data (no INSERT/UPDATE/DELETE/DROP).\n"
        "- Use COUNT(*) to count rows; use COUNT(column) only when explicitly counting non-null values.\n"
        "- When grouping by a computed expression (e.g. date_trunc), reference it positionally in GROUP BY/ORDER BY (GROUP BY 1).\n"
        "- Alias the primary aggregate with a concise business name (e.g. revenue, mrr), not a verbose one.\n"
        "- When grouping by a category, ORDER BY the aggregate descending; when grouping by a time bucket, ORDER BY the time column ascending.\n"
        "- For a single lower-bound date filter (e.g. 'this month', 'last 30 days'), use one comparison; do not add an upper bound unless the question asks for a closed range.\n"
        "- Keep clauses concise; do not pretty-print across many lines.\n"
        "- If the question cannot be answered with SQL, respond with: NO_SQL\n"
    )
    return prompt


def _extract_sql(text: str) -> str | None:
    match = _SQL_BLOCK_RE.search(text)
    if match:
        return match.group(1).strip()
    if _SELECT_RE.search(text):
        return text.strip()
    return None


class NLTranslator:
    def __init__(self, llm=None):
        self._llm = llm  # lazy-loaded if None

    def _get_llm(self):
        if self._llm is None:
            self._llm = _build_llm_from_env()
        return self._llm

    async def generate_sql(
        self,
        question: str,
        schema: dict,
        resolved_metrics: list[dict],
    ) -> str | None:
        from langchain_core.messages import HumanMessage, SystemMessage
        try:
            system_prompt = _build_system_prompt(schema, resolved_metrics)
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=question)]
            response = await self._get_llm().ainvoke(messages)
            content = getattr(response, "content", str(response))
            if "NO_SQL" in content:
                return None
            return _extract_sql(content)
        except Exception as exc:
            logger.warning("NLTranslator.generate_sql failed: %s", exc)
            return None
