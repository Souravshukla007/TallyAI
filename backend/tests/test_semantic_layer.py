"""
Tests for the SemanticLayer (semantic business layer).

Covers:
  - Req 6.4  metric resolution is deterministic / idempotent
  - Req 6.5  unknown terms produce an empty list (no error)
  - Req 6.6  version history is retained; superseded_by is set on old rows
  - YAML schema validity
  - SQL-injection safety of YAML formulas (sqlglot parsing)
"""

from __future__ import annotations

import os
from pathlib import Path

import asyncio

import pytest
import sqlglot
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from tallyai.core.semantic_layer import SemanticLayer
from tallyai.db.models import Base, MetricDefinition

# Path to the canonical YAML file relative to this test file.
YAML_PATH = Path(__file__).parent.parent / "metrics" / "saas_metrics.yaml"
TENANT = "tenant-test-001"
CONNECTION_ID = "conn-test-001"
SCHEMA_VERSION = "v1"


@pytest.fixture
def layer() -> SemanticLayer:
    return SemanticLayer()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _seed_metric(
    db: AsyncSession,
    name: str,
    formula: str,
    version: int = 1,
    tenant_id: str = TENANT,
) -> MetricDefinition:
    """Insert a MetricDefinition row directly (bypasses upsert logic)."""
    row = MetricDefinition(
        name=name,
        tenant_id=tenant_id,
        formula=formula,
        condition=None,
        grain=None,
        description=f"Test metric: {name}",
        version=version,
        superseded_by=None,
    )
    db.add(row)
    await db.flush()
    return row


# ---------------------------------------------------------------------------
# Req 6.4 — deterministic resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metric_resolver_idempotent(db_session: AsyncSession, layer: SemanticLayer) -> None:
    """Resolving the same question twice must return identical results (Req 6.4)."""
    await _seed_metric(db_session, "revenue", "SUM(payments.amount)")
    await _seed_metric(db_session, "mrr", "SUM(subscriptions.monthly_amount)")

    question = "What is the revenue and mrr for this month?"

    result_1 = await layer.resolve(question, CONNECTION_ID, SCHEMA_VERSION, TENANT, db_session)
    result_2 = await layer.resolve(question, CONNECTION_ID, SCHEMA_VERSION, TENANT, db_session)

    assert result_1 == result_2, "Resolution must be deterministic for identical inputs"
    assert len(result_1) == 2
    names = {r["name"] for r in result_1}
    assert names == {"revenue", "mrr"}


# ---------------------------------------------------------------------------
# YAML schema validity
# ---------------------------------------------------------------------------


def test_yaml_schema_valid() -> None:
    """Load saas_metrics.yaml and verify all 5 expected metrics are present
    with non-empty formulas."""
    import yaml

    assert YAML_PATH.exists(), f"YAML file not found at {YAML_PATH}"

    with YAML_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    metrics = data.get("metrics", {})
    expected_names = {"revenue", "mrr", "churn_rate", "ltv", "active_users"}

    assert expected_names == set(metrics.keys()), (
        f"Expected {expected_names}, found {set(metrics.keys())}"
    )

    for name, defn in metrics.items():
        formula = defn.get("formula", "")
        assert formula, f"Metric '{name}' has an empty formula"


# ---------------------------------------------------------------------------
# SQL injection safety — each formula must be parseable by sqlglot
# ---------------------------------------------------------------------------


def test_formula_sql_injectable() -> None:
    """Each formula from saas_metrics.yaml must produce a valid SQL fragment
    when wrapped as ``SELECT {formula} FROM t``."""
    import yaml

    with YAML_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    metrics = data.get("metrics", {})
    failures: list[str] = []

    for name, defn in metrics.items():
        formula = defn["formula"]
        sql_fragment = f"SELECT {formula} FROM t"
        try:
            parsed = sqlglot.parse(sql_fragment, error_level=sqlglot.ErrorLevel.RAISE)
            assert parsed, f"sqlglot returned empty parse for metric '{name}'"
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {exc}")

    assert not failures, "Some formulas could not be parsed:\n" + "\n".join(failures)


# ---------------------------------------------------------------------------
# Req 6.5 — unknown terms produce empty result, no error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_undefined_term_omitted(db_session: AsyncSession, layer: SemanticLayer) -> None:
    """A question with no matching metrics must return an empty list (Req 6.5)."""
    await _seed_metric(db_session, "revenue", "SUM(payments.amount)")

    result = await layer.resolve(
        "How many widgets were sold last quarter?",
        CONNECTION_ID,
        SCHEMA_VERSION,
        TENANT,
        db_session,
    )

    assert result == [], f"Expected empty list, got: {result}"


# ---------------------------------------------------------------------------
# Req 6.6 — version history is retained; superseded_by is set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_version_history_retained(db_session: AsyncSession, layer: SemanticLayer) -> None:
    """Upserting a metric twice must yield 2 rows; the first must have
    superseded_by pointing at version 2 (Req 6.6)."""
    from sqlalchemy import select

    # First upsert — version 1.
    v1_result = await layer.upsert_metric(
        name="revenue",
        formula="SUM(payments.amount)",
        condition=None,
        grain=None,
        description="Initial definition",
        tenant_id=TENANT,
        db=db_session,
    )
    assert v1_result == {"name": "revenue", "version": 1}

    # Second upsert — should create version 2.
    v2_result = await layer.upsert_metric(
        name="revenue",
        formula="SUM(payments.net_amount)",
        condition="payments.status = 'completed'",
        grain=None,
        description="Refined definition",
        tenant_id=TENANT,
        db=db_session,
    )
    assert v2_result == {"name": "revenue", "version": 2}

    # Verify both rows exist in the DB.
    stmt = (
        select(MetricDefinition)
        .where(
            MetricDefinition.name == "revenue",
            MetricDefinition.tenant_id == TENANT,
        )
        .order_by(MetricDefinition.version.asc())
    )
    result = await db_session.execute(stmt)
    rows = list(result.scalars().all())

    assert len(rows) == 2, f"Expected 2 rows, found {len(rows)}"

    v1_row, v2_row = rows
    assert v1_row.version == 1
    assert v2_row.version == 2
    assert v1_row.superseded_by == 2, (
        f"v1 superseded_by should be 2, got {v1_row.superseded_by}"
    )
    assert v2_row.superseded_by is None, (
        f"v2 superseded_by should be None, got {v2_row.superseded_by}"
    )

    # Also verify get_metric_versions returns both.
    history = await layer.get_metric_versions("revenue", TENANT, db_session)
    assert len(history) == 2
    assert history[0]["version"] == 1
    assert history[1]["version"] == 2


# ---------------------------------------------------------------------------
# Req 14.2, 14.4 — resolution and version history are tenant-scoped
# ---------------------------------------------------------------------------

OTHER_TENANT = "tenant-other-002"


@pytest.mark.asyncio
async def test_cross_tenant_resolve_returns_empty(
    db_session: AsyncSession, layer: SemanticLayer
) -> None:
    """A different tenant must not resolve another tenant's metrics (Req 14.2, 14.4)."""
    await _seed_metric(db_session, "revenue", "SUM(payments.amount)", tenant_id=TENANT)
    await db_session.flush()

    question = "What is the revenue this month?"

    # Owning tenant resolves the metric.
    own = await layer.resolve(question, CONNECTION_ID, SCHEMA_VERSION, TENANT, db_session)
    assert {r["name"] for r in own} == {"revenue"}

    # A different tenant sees nothing — the metric is not theirs.
    other = await layer.resolve(
        question, CONNECTION_ID, SCHEMA_VERSION, OTHER_TENANT, db_session
    )
    assert other == [], "Cross-tenant metric resolution must return no metrics (Req 14.4)"


@pytest.mark.asyncio
async def test_cross_tenant_version_history_returns_empty(
    db_session: AsyncSession, layer: SemanticLayer
) -> None:
    """Version history is tenant-scoped; another tenant sees none (Req 14.2, 14.4)."""
    await layer.upsert_metric(
        name="revenue",
        formula="SUM(payments.amount)",
        condition=None,
        grain=None,
        description="Initial",
        tenant_id=TENANT,
        db=db_session,
    )
    await db_session.flush()

    own_history = await layer.get_metric_versions("revenue", TENANT, db_session)
    assert len(own_history) == 1

    other_history = await layer.get_metric_versions("revenue", OTHER_TENANT, db_session)
    assert other_history == [], "Cross-tenant version history must be empty (Req 14.4)"


# ---------------------------------------------------------------------------
# Feature: tallyai, Property 9: Semantic-layer consistency — for any
# business term that has a Metric_Definition, resolving that term against the
# same connection and the same schema version always yields the same canonical
# Metric_Definition, regardless of how the question referencing it is phrased.
#
# **Validates: Requirements 6.2, 6.4**
#
# This is a Hypothesis property-based test (the design names the Semantic Layer
# resolver as a trust-critical PBT target). It varies the casing and the
# surrounding natural-language phrasing of a question that references a known
# metric term and asserts the resolver returns the same canonical definition
# every time.
# ---------------------------------------------------------------------------

# Canonical metrics seeded for the property test. Human-readable names are the
# metric name with underscores replaced by spaces (mirrors SemanticLayer.resolve).
_PBT_METRICS = {
    "revenue": "SUM(payments.amount)",
    "mrr": "SUM(subscriptions.monthly_amount)",
    "churn_rate": "COUNT(churned) / COUNT(*)",
    "ltv": "AVG(customer.lifetime_value)",
    "active_users": "COUNT(DISTINCT events.user_id)",
}

# Filler words used to build varied phrasings. None of these contain any metric
# human-name as a substring, so they never introduce a spurious match.
_FILLER_WORDS = [
    "what", "is", "the", "for", "this", "month", "show", "me", "please",
    "and", "today", "quarter", "total", "by", "give", "us", "last", "year",
]


def _randomly_cased(text: str, seed: int) -> str:
    """Deterministically vary the casing of *text* based on *seed*."""
    out = []
    for i, ch in enumerate(text):
        out.append(ch.upper() if (seed >> (i % 16)) & 1 else ch.lower())
    return "".join(out)


async def _resolve_in_fresh_db(question: str) -> list[dict]:
    """Seed the canonical metrics into a throwaway in-memory DB and resolve
    *question* against it. Returns the resolver output."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False,
            autoflush=False, autocommit=False,
        )
        async with factory() as session:
            for name, formula in _PBT_METRICS.items():
                session.add(
                    MetricDefinition(
                        name=name, tenant_id=TENANT, formula=formula,
                        condition=None, grain=None,
                        description=f"Test metric: {name}",
                        version=1, superseded_by=None,
                    )
                )
            await session.flush()
            layer = SemanticLayer()
            return await layer.resolve(
                question, CONNECTION_ID, SCHEMA_VERSION, TENANT, session
            )
    finally:
        await engine.dispose()


@given(
    term=st.sampled_from(list(_PBT_METRICS.keys())),
    case_seed=st.integers(min_value=0, max_value=2**16 - 1),
    prefix=st.lists(st.sampled_from(_FILLER_WORDS), max_size=5),
    suffix=st.lists(st.sampled_from(_FILLER_WORDS), max_size=5),
)
@settings(max_examples=120, deadline=None)
def test_semantic_resolution_is_phrasing_invariant(
    term: str, case_seed: int, prefix: list[str], suffix: list[str]
) -> None:
    """**Validates: Requirements 6.2, 6.4**

    Feature: tallyai, Property 9: regardless of casing or surrounding
    phrasing, resolving a question that references a defined metric term always
    yields that metric's single canonical definition, and the result is
    deterministic across repeated resolves.
    """
    human_name = term.replace("_", " ")
    phrased_term = _randomly_cased(human_name, case_seed)
    question = " ".join(prefix + [phrased_term] + suffix)

    # Resolve twice (determinism) and against a canonical lowercase baseline
    # phrasing (phrasing-invariance).
    result_a = asyncio.run(_resolve_in_fresh_db(question))
    result_b = asyncio.run(_resolve_in_fresh_db(question))
    baseline = asyncio.run(
        _resolve_in_fresh_db(f"what is the {human_name}")
    )

    # Determinism: identical inputs → identical output.
    assert result_a == result_b

    # Exactly the referenced metric resolves (filler never introduces matches).
    assert len(result_a) == 1, f"expected 1 match for {question!r}, got {result_a}"
    matched = result_a[0]
    assert matched["name"] == term
    assert matched["formula"] == _PBT_METRICS[term]

    # Phrasing-invariance: same canonical definition regardless of phrasing.
    assert len(baseline) == 1
    assert baseline[0]["name"] == matched["name"]
    assert baseline[0]["formula"] == matched["formula"]
    assert baseline[0]["version"] == matched["version"]
