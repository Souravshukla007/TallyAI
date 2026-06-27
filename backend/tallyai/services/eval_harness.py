"""
Eval_Harness — measures natural-language-to-SQL correctness against a labeled
question set (Req 12.1-12.4).

Responsibilities
----------------
* Maintain / consume a labeled set of ``question → expected SQL`` pairs
  (Req 12.1). The canonical set ships in ``backend/metrics/eval_golden_set.json``.
* Run every pair through the NL_Translator, compare the generated SQL to the
  expected SQL with a normalized exact-match, and report an accuracy score in
  ``[0, 1]`` (Req 12.2).
* Reject an empty labeled set with the error
  ``"at least one labeled pair required"`` and produce no score (Req 12.3).
* Record a :class:`~tallyai.db.models.Trace` per run capturing the questions,
  generated SQL, per-pair tool calls, latency, and cost (Req 12.4). Trace
  recording is best-effort — a recording failure never aborts the run (Req 12.5).

The harness is model-agnostic: it accepts any *translator* exposing an
``async generate_sql(question, schema, resolved_metrics)`` coroutine (the
production :class:`~tallyai.services.nl_translator.NLTranslator`) or a plain
callable ``question -> sql | None`` (handy for tests). The default translator is
the production NL_Translator.
"""

from __future__ import annotations

import inspect
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from tallyai.db.models import Trace

logger = logging.getLogger(__name__)

# The canonical golden set ships alongside the YAML metric definitions.
GOLDEN_SET_PATH = Path(__file__).resolve().parents[2] / "metrics" / "eval_golden_set.json"

#: The exact error message mandated by Req 12.3.
EMPTY_SET_MESSAGE = "at least one labeled pair required"


class EmptyLabeledSetError(ValueError):
    """Raised when :meth:`EvalHarness.run` is given an empty labeled set.

    Carries the Req 12.3 message ``"at least one labeled pair required"``.
    """

    def __init__(self, message: str = EMPTY_SET_MESSAGE) -> None:
        super().__init__(message)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LabeledPair:
    """A single labeled ``question → expected SQL`` example (Req 12.1)."""

    question: str
    expected_sql: str
    pair_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class PairResult:
    """The outcome of evaluating one :class:`LabeledPair`."""

    pair_id: str
    question: str
    expected_sql: str
    generated_sql: Optional[str]
    match: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "pairId": self.pair_id,
            "question": self.question,
            "expectedSql": self.expected_sql,
            "generatedSql": self.generated_sql,
            "match": self.match,
        }


@dataclass
class EvalReport:
    """The result of an eval run (Req 12.2)."""

    accuracy: float
    per_pair: list[PairResult]
    trace_refs: list[str]
    total: int
    matched: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "accuracy": self.accuracy,
            "perPair": [p.to_dict() for p in self.per_pair],
            "traceRefs": list(self.trace_refs),
            "total": self.total,
            "matched": self.matched,
        }


# ---------------------------------------------------------------------------
# SQL normalization for exact-match comparison
# ---------------------------------------------------------------------------


def normalize_sql(sql: Optional[str]) -> Optional[str]:
    """Return a canonical form of *sql* for exact-match comparison.

    Uses ``sqlglot`` to parse and re-render the statement so that semantically
    identical queries that differ only in whitespace, keyword case, or quoting
    compare equal. Falls back to whitespace/case normalization when the SQL is
    not parseable.

    Returns ``None`` when *sql* is ``None``.
    """
    if sql is None:
        return None

    raw = sql.strip().rstrip(";").strip()
    if not raw:
        return ""

    try:
        import sqlglot

        rendered = sqlglot.transpile(
            raw, read="postgres", write="postgres", pretty=False
        )
        if rendered:
            raw = rendered[0]
    except Exception as exc:  # noqa: BLE001 — fall back to lexical normalization
        logger.debug("normalize_sql: sqlglot failed, using lexical fallback: %s", exc)

    # Collapse whitespace and lower-case for a stable, case-insensitive compare.
    return " ".join(raw.split()).rstrip(";").strip().lower()


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

# A translator may be an object exposing ``generate_sql`` or a plain callable.
TranslatorCallable = Callable[[str], "str | None | Awaitable[str | None]"]


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


class EvalHarness:
    """Measure NL→SQL accuracy against a labeled question set (Req 12.1-12.4)."""

    def __init__(self, translator: Any = None) -> None:
        """Create a harness.

        Parameters
        ----------
        translator:
            Optional NL→SQL translator. May be an object with an async
            ``generate_sql(question, schema, resolved_metrics)`` method, or a
            plain callable ``question -> sql | None``. Defaults to the
            production :class:`NLTranslator`.
        """
        self._translator = translator

    # ------------------------------------------------------------------
    # Translation
    # ------------------------------------------------------------------

    async def _generate(
        self,
        question: str,
        schema: dict | None,
        resolved_metrics: list[dict] | None,
    ) -> Optional[str]:
        translator = self._translator
        if translator is None:
            # Lazy import to avoid pulling LLM deps when a translator is injected.
            from tallyai.services.nl_translator import NLTranslator

            translator = NLTranslator()

        try:
            if hasattr(translator, "generate_sql"):
                return await _maybe_await(
                    translator.generate_sql(
                        question, schema or {}, resolved_metrics or []
                    )
                )
            # Plain callable: question -> sql | None
            return await _maybe_await(translator(question))
        except Exception as exc:  # noqa: BLE001 — a translation failure scores as a miss
            logger.warning("EvalHarness: translation failed for question %r: %s", question, exc)
            return None

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    async def run(
        self,
        labeled_set: list[LabeledPair],
        *,
        tenant_id: str = "default",
        db: Any = None,
        schema: dict | None = None,
        resolved_metrics: list[dict] | None = None,
        labeled_set_id: str | None = None,
        comparator: Callable[[str, Optional[str]], bool] | None = None,
    ) -> EvalReport:
        """Evaluate every pair in *labeled_set* and report accuracy (Req 12.2).

        Parameters
        ----------
        labeled_set:
            The labeled ``question → expected SQL`` pairs. Must be non-empty.
        tenant_id:
            Tenant the run (and its Trace) belongs to (Req 14).
        db:
            Optional async SQLAlchemy session. When provided, a :class:`Trace`
            is recorded for the run (Req 12.4). When ``None``, tracing is
            skipped.
        schema / resolved_metrics:
            Optional translation context forwarded to the translator.
        labeled_set_id:
            Optional identifier of the labeled set (recorded in the trace).
        comparator:
            Optional ``(expected_sql, generated_sql) -> bool`` predicate used to
            decide whether a generated query matches. Defaults to a normalized
            string comparison (``normalize_sql``). Pass an execution-based
            comparator (see :mod:`tallyai.services.eval_execution`) to score by
            result-set equivalence instead.

        Returns
        -------
        EvalReport

        Raises
        ------
        EmptyLabeledSetError
            When *labeled_set* is empty (Req 12.3) — no score is produced.
        """
        if not labeled_set:
            # Req 12.3 — empty set is an error; no accuracy score is reported.
            raise EmptyLabeledSetError()

        start = time.perf_counter()
        per_pair: list[PairResult] = []
        tool_calls: list[dict[str, Any]] = []

        for pair in labeled_set:
            generated = await self._generate(pair.question, schema, resolved_metrics)
            if comparator is not None:
                try:
                    match = comparator(pair.expected_sql, generated)
                except Exception as exc:  # noqa: BLE001 — a broken compare scores as a miss
                    logger.warning("EvalHarness: comparator failed for %r: %s", pair.question, exc)
                    match = False
            else:
                match = normalize_sql(generated) == normalize_sql(pair.expected_sql)
            result = PairResult(
                pair_id=pair.pair_id,
                question=pair.question,
                expected_sql=pair.expected_sql,
                generated_sql=generated,
                match=match,
            )
            per_pair.append(result)
            tool_calls.append(
                {
                    "tool": "nl_translator.generate_sql",
                    "pairId": pair.pair_id,
                    "question": pair.question,
                    "generatedSql": generated,
                    "match": match,
                }
            )

        matched = sum(1 for p in per_pair if p.match)
        total = len(per_pair)
        accuracy = matched / total if total else 0.0
        latency_ms = int((time.perf_counter() - start) * 1000)

        trace_refs: list[str] = []
        trace_id = await self._record_trace(
            db=db,
            tenant_id=tenant_id,
            labeled_set_id=labeled_set_id,
            total=total,
            matched=matched,
            tool_calls=tool_calls,
            latency_ms=latency_ms,
        )
        if trace_id is not None:
            trace_refs.append(trace_id)

        return EvalReport(
            accuracy=accuracy,
            per_pair=per_pair,
            trace_refs=trace_refs,
            total=total,
            matched=matched,
        )

    # ------------------------------------------------------------------
    # Tracing (Req 12.4, 12.5)
    # ------------------------------------------------------------------

    async def _record_trace(
        self,
        *,
        db: Any,
        tenant_id: str,
        labeled_set_id: str | None,
        total: int,
        matched: int,
        tool_calls: list[dict[str, Any]],
        latency_ms: int,
    ) -> Optional[str]:
        """Persist a Trace for the eval run (Req 12.4).

        Best-effort: any failure is logged and swallowed so it never aborts the
        run (Req 12.5).
        """
        if db is None:
            return None

        trace_id = str(uuid.uuid4())
        try:
            trace = Trace(
                trace_id=trace_id,
                tenant_id=tenant_id,
                question=(
                    f"eval run [{labeled_set_id or 'inline'}]: "
                    f"{matched}/{total} matched"
                ),
                generated_sql=None,
                tool_calls=tool_calls,
                latency_ms=latency_ms,
                cost=0.0,
            )
            db.add(trace)
            await db.flush()
            return trace_id
        except Exception as exc:  # noqa: BLE001 — Req 12.5: never abort on trace failure
            logger.warning("EvalHarness: trace recording failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Labeled-set loading (Req 12.1)
# ---------------------------------------------------------------------------


def _pairs_from_raw(raw_pairs: list[dict[str, Any]]) -> list[LabeledPair]:
    pairs: list[LabeledPair] = []
    for item in raw_pairs:
        pairs.append(
            LabeledPair(
                question=item["question"],
                expected_sql=item["expectedSql"],
                pair_id=item.get("pairId") or str(uuid.uuid4()),
            )
        )
    return pairs


def load_golden_set(path: str | Path | None = None) -> tuple[str, list[LabeledPair]]:
    """Load the labeled golden set from JSON (Req 12.1).

    Returns
    -------
    tuple[str, list[LabeledPair]]
        The ``labeledSetId`` and the parsed labeled pairs.
    """
    p = Path(path) if path is not None else GOLDEN_SET_PATH
    with p.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    labeled_set_id = data.get("labeledSetId", p.stem)
    pairs = _pairs_from_raw(data.get("pairs", []))
    return labeled_set_id, pairs
