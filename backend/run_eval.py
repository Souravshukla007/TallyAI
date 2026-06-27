"""
Ad-hoc runner for the NL->SQL eval harness against the live LLM (Req 12).

Loads backend/.env, supplies a schema + metric context matching the golden set,
runs every labeled pair through the configured provider, and prints the
normalized exact-match accuracy with per-pair detail.

Usage (from backend/):
    python run_eval.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import load_dotenv

# Load backend/.env so LLM_PROVIDER / LLM_MODEL / API key are available.
load_dotenv(Path(__file__).resolve().parent / ".env")

from tallyai.services.eval_harness import EvalHarness, load_golden_set  # noqa: E402

# Schema fixture aligned with the golden set's expected tables/columns so the
# model has the same context the production orchestrator would inject.
SCHEMA = {
    "tables": [
        {"name": "payments", "columns": [
            {"name": "id"}, {"name": "customer_id"}, {"name": "amount"},
            {"name": "status"}, {"name": "plan"}, {"name": "created_at"},
        ]},
        {"name": "subscriptions", "columns": [
            {"name": "id"}, {"name": "customer_id"}, {"name": "status"},
            {"name": "monthly_amount"}, {"name": "trial_converted"}, {"name": "created_at"},
        ]},
        {"name": "users", "columns": [
            {"name": "id"}, {"name": "last_login"}, {"name": "created_at"},
        ]},
        {"name": "customers", "columns": [
            {"name": "id"}, {"name": "total_spend"}, {"name": "created_at"},
        ]},
    ]
}

METRICS = [
    {"name": "revenue", "formula": "SUM(amount)", "condition": "status = 'completed'"},
    {"name": "mrr", "formula": "SUM(monthly_amount)", "condition": "status = 'active'"},
    {"name": "churn_rate",
     "formula": "COUNT(CASE WHEN status = 'canceled' THEN 1 END)::float / NULLIF(COUNT(*), 0)"},
    {"name": "active_users", "formula": "COUNT(DISTINCT id)",
     "condition": "last_login >= NOW() - INTERVAL '30 days'"},
    {"name": "ltv", "formula": "AVG(total_spend)"},
]


class _Throttled:
    """Wraps a translator to space out calls (respect free-tier RPM)."""

    def __init__(self, inner, delay: float = 6.0) -> None:
        self._inner = inner
        self._delay = delay
        self._first = True

    async def generate_sql(self, question, schema, resolved_metrics):
        import asyncio
        if not self._first:
            await asyncio.sleep(self._delay)
        self._first = False
        return await self._inner.generate_sql(question, schema, resolved_metrics)


async def main() -> None:
    import os
    from tallyai.services.nl_translator import NLTranslator

    set_id, pairs = load_golden_set()

    # Build a fail-fast LLM (max_retries=1) so an exhausted daily quota surfaces
    # quickly instead of hanging, and throttle calls to respect free-tier RPM.
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    model = os.getenv("LLM_MODEL")
    if provider in ("gemini", "google", "google-genai"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        llm = ChatGoogleGenerativeAI(model=model or "gemini-2.5-flash-lite", max_retries=1, timeout=30)
        translator = _Throttled(NLTranslator(llm=llm), delay=6.0)
    else:
        translator = _Throttled(NLTranslator(), delay=2.0)

    harness = EvalHarness(translator=translator)
    from tallyai.services.eval_execution import make_comparator
    comparator = make_comparator()
    report = await harness.run(
        pairs, schema=SCHEMA, resolved_metrics=METRICS, comparator=comparator
    )

    print(f"\nLabeled set : {set_id}")
    print(f"Accuracy    : {report.accuracy:.1%}  ({report.matched}/{report.total})")
    print("-" * 70)
    for p in report.per_pair:
        mark = "PASS" if p.match else "FAIL"
        print(f"[{mark}] {p.question}")
        if not p.match:
            print(f"       expected : {p.expected_sql}")
            print(f"       generated: {p.generated_sql}")
    print("-" * 70)
    target = 0.85
    verdict = "MEETS" if report.accuracy >= target else "BELOW"
    print(f"Target >= {target:.0%}: {verdict} target\n")


if __name__ == "__main__":
    asyncio.run(main())
