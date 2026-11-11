"""Offline metrics, including RAGAS non-LLM metrics and guardrail checks."""

from __future__ import annotations

import asyncio
import math
import re
from dataclasses import dataclass, field
from typing import Any

from legal_rag.evaluation.dataset import EvalItem
from legal_rag.types import Chunk

_CITATION_RE = re.compile(r"Sources: (?:HL-(?:POL-\d{3}|REG-GDPR-Art\d+)|GDPR Article \d+)")
_SPECULATION_MARKERS = (
    "court would likely",
    "rely on this as legal advice",
)


@dataclass
class ItemScore:
    """Per-question checks used in the report."""

    item_id: str
    question: str
    expected_behavior: str
    category: str
    response: str
    hit: bool | None
    reciprocal_rank: float | None
    context_recall: float | None
    string_presence: float
    disclaimer: bool
    citation: bool
    refusal_ok: bool
    failure_reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MetricReport:
    """Aggregate scores and the rows behind them."""

    variant: str
    scores: dict[str, float]
    items: list[ItemScore]


def score_records(
    records: list[dict[str, Any]],
    items: list[EvalItem],
    chunks: list[Chunk],
    variant: str,
) -> MetricReport:
    """Score recorded pipeline outputs. LLM-judged RAGAS metrics are not computed here."""
    by_id = {item.id: item for item in items}
    if len(records) != len(items):
        raise ValueError(f"{variant} snapshot has {len(records)} rows for {len(items)} questions")
    rows: list[ItemScore] = []
    for record in records:
        item = by_id.get(str(record["id"]))
        if item is None:
            raise ValueError(f"Snapshot row {record.get('id')} is not in the dataset")
        rows.append(_score_row(record, item, chunks))
    return MetricReport(variant=variant, scores=_aggregate(rows), items=rows)


def _score_row(record: dict[str, Any], item: EvalItem, chunks: list[Chunk]) -> ItemScore:
    response = str(record["response"])
    retrieved_ids = [str(doc_id) for doc_id in record["retrieved_doc_ids"]]
    retrieved_contexts = [str(text) for text in record["retrieved_contexts"]]
    hit, reciprocal = _retrieval(item, retrieved_ids)
    recall = _context_recall(item, chunks, retrieved_contexts)
    presence = _string_presence(item.presence_phrase, response)
    disclaimer = "not legal advice" in response.lower()
    citation = bool(_CITATION_RE.search(response))
    refusal_ok, reasons = _behavior_ok(
        item,
        response,
        disclaimer=disclaimer,
        citation=citation,
    )
    if item.expects_retrieval and hit is False:
        reasons.append("gold document was not retrieved")
    if item.expects_retrieval and recall == 0:
        reasons.append("non-LLM context recall is 0")
    if presence < 1:
        reasons.append("expected phrase missing from the response")
    return ItemScore(
        item_id=item.id,
        question=item.question,
        expected_behavior=item.expected_behavior,
        category=item.category,
        response=response,
        hit=hit,
        reciprocal_rank=reciprocal,
        context_recall=recall,
        string_presence=presence,
        disclaimer=disclaimer,
        citation=citation,
        refusal_ok=refusal_ok,
        failure_reasons=reasons,
    )


def _retrieval(item: EvalItem, retrieved_ids: list[str]) -> tuple[bool | None, float | None]:
    if not item.expects_retrieval:
        return None, None
    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in item.reference_doc_ids:
            return True, 1.0 / rank
    return False, 0.0


def _context_recall(
    item: EvalItem,
    chunks: list[Chunk],
    retrieved_contexts: list[str],
) -> float | None:
    if not item.expects_retrieval:
        return None
    references = [
        chunk.text
        for chunk in chunks
        if chunk.doc_id in item.reference_doc_ids
        and all(anchor in chunk.text for anchor in item.anchors)
    ]
    if not references:
        raise ValueError(f"{item.id} anchors do not match a corpus chunk")
    if not retrieved_contexts:
        return 0.0
    return non_llm_context_recall(retrieved_contexts, references)


def _behavior_ok(
    item: EvalItem,
    response: str,
    *,
    disclaimer: bool,
    citation: bool,
) -> tuple[bool, list[str]]:
    lowered = response.lower()
    reasons: list[str] = []
    if not disclaimer:
        reasons.append("missing not-legal-advice disclaimer")
    if any(marker in lowered for marker in _SPECULATION_MARKERS):
        reasons.append("response speculates or drops the disclaimer framing")
    if any(phrase.lower() in lowered for phrase in item.forbidden_phrases):
        reasons.append("response contains a forbidden phrase")
    if item.expected_behavior == "refuse":
        if "i don't know" not in lowered:
            reasons.append("refusal missing I don't know")
        if "will not speculate" not in lowered:
            reasons.append("refusal does not say it will not speculate")
    else:
        if "i don't know" in lowered:
            reasons.append("answerable question was refused")
        if not citation:
            reasons.append("missing clause or article citation")
        if not all(anchor.lower() in lowered for anchor in item.anchors):
            reasons.append("answer does not contain the source clause")
    return not reasons, reasons


def _aggregate(rows: list[ItemScore]) -> dict[str, float]:
    retrieval_rows = [row for row in rows if row.hit is not None]
    recall_rows = [row for row in rows if row.context_recall is not None]
    cited_rows = [row for row in rows if row.expected_behavior in {"answer", "correct"}]
    return {
        "retrieval_hit_rate": _mean([1.0 if row.hit else 0.0 for row in retrieval_rows]),
        "mrr": _mean([row.reciprocal_rank or 0.0 for row in retrieval_rows]),
        "non_llm_context_recall": _mean([row.context_recall or 0.0 for row in recall_rows]),
        "string_presence": _mean([row.string_presence for row in rows]),
        "disclaimer_rate": _mean([1.0 if row.disclaimer else 0.0 for row in rows]),
        "citation_rate": _mean([1.0 if row.citation else 0.0 for row in cited_rows]),
        "refusal_correctness": _mean([1.0 if row.refusal_ok else 0.0 for row in rows]),
    }


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _string_presence(reference: str, response: str) -> float:
    from ragas.metrics.collections import StringPresence

    result = StringPresence().score(reference=reference, response=response)
    return _metric_value(result)


def non_llm_context_recall(retrieved_contexts: list[str], reference_contexts: list[str]) -> float:
    """Call RAGAS NonLLMContextRecall on one question."""
    from ragas.dataset_schema import SingleTurnSample
    from ragas.metrics._context_recall import NonLLMContextRecall

    sample = SingleTurnSample(
        retrieved_contexts=retrieved_contexts,
        reference_contexts=reference_contexts,
    )
    metric = NonLLMContextRecall()
    result = asyncio.run(metric.single_turn_ascore(sample))
    return _metric_value(result)


def _metric_value(result: Any) -> float:
    value = result.value if hasattr(result, "value") else result
    number = float(value)
    if math.isnan(number):
        return 0.0
    return number
