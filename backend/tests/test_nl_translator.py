"""Tests for NLTranslator and Explainer (Req 2.1, 2.3, 7.4, 1.5)."""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock
import pytest
from tallyai.services.nl_translator import NLTranslator, _build_system_prompt
from tallyai.services.explainer import Explainer

SCHEMA = {
    "tables": [
        {"name": "orders", "columns": [{"name": "id"}, {"name": "amount"}, {"name": "status"}]},
        {"name": "users", "columns": [{"name": "id"}, {"name": "email"}, {"name": "last_login"}]},
    ]
}
METRICS = [
    {"name": "revenue", "formula": "SUM(payments.amount)", "condition": "payments.status = 'completed'", "description": "Total revenue"},
]

def _mock_llm(content: str) -> MagicMock:
    llm = MagicMock()
    response = MagicMock()
    response.content = content
    llm.ainvoke = AsyncMock(return_value=response)
    return llm

def _error_llm() -> MagicMock:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(side_effect=Exception("LLM unavailable"))
    return llm


def test_schema_in_prompt():
    prompt = _build_system_prompt(SCHEMA, [])
    assert "orders" in prompt
    assert "users" in prompt
    assert "id" in prompt
    assert "amount" in prompt

def test_metric_formulas_in_prompt():
    prompt = _build_system_prompt(SCHEMA, METRICS)
    assert "SUM(payments.amount)" in prompt
    assert "revenue" in prompt

def test_credentials_not_in_schema():
    """Schema passed to generate_sql must not contain credential keys (Req 1.5)."""
    prompt = _build_system_prompt(SCHEMA, [])
    assert "password" not in prompt.lower()
    assert "secret" not in prompt.lower()
    assert "credentials" not in prompt.lower()

@pytest.mark.asyncio
async def test_returns_none_when_no_sql_produced():
    llm = _mock_llm("I don't know how to answer that. NO_SQL")
    translator = NLTranslator(llm=llm)
    result = await translator.generate_sql("who is the CEO?", SCHEMA, [])
    assert result is None

@pytest.mark.asyncio
async def test_returns_none_on_llm_exception():
    translator = NLTranslator(llm=_error_llm())
    result = await translator.generate_sql("What is revenue?", SCHEMA, METRICS)
    assert result is None

@pytest.mark.asyncio
async def test_generates_sql_from_code_block():
    content = "Here is the query:\n```sql\nSELECT SUM(amount) FROM orders\n```"
    translator = NLTranslator(llm=_mock_llm(content))
    result = await translator.generate_sql("What is total revenue?", SCHEMA, METRICS)
    assert result is not None
    assert "SELECT" in result.upper()

@pytest.mark.asyncio
async def test_explainer_returns_none_on_failure():
    explainer = Explainer(llm=_error_llm())
    result = await explainer.explain("SELECT * FROM orders LIMIT 100", [])
    assert result is None

@pytest.mark.asyncio
async def test_explainer_returns_description():
    llm = _mock_llm("This query retrieves all orders limited to 100 rows.")
    explainer = Explainer(llm=llm)
    result = await explainer.explain("SELECT * FROM orders LIMIT 100", [])
    assert result is not None
    assert len(result) > 5
