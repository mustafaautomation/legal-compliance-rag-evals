"""Live RAGAS scoring. This module calls the network only when invoked."""

from __future__ import annotations

import os
from typing import Any

from legal_rag.evaluation.dataset import EvalItem


def build_live_metrics(llm: Any, embeddings: Any) -> list[Any]:
    """Construct the current RAGAS collections metrics used in live mode."""
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    return [
        Faithfulness(llm=llm, name="faithfulness"),
        AnswerRelevancy(llm=llm, embeddings=embeddings, name="answer_relevancy"),
        ContextPrecisionWithReference(llm=llm, name="context_precision"),
        ContextRecall(llm=llm, name="context_recall"),
    ]


async def score_live(records: list[dict[str, Any]], items: list[EvalItem]) -> dict[str, float]:
    """Run faithfulness, answer relevancy, context precision, and context recall.

    Context precision and context recall are averaged on answerable questions,
    because refusal rows have no gold clause. Faithfulness and answer relevancy
    cover every row.
    """
    from openai import AsyncOpenAI
    from ragas.embeddings.base import embedding_factory
    from ragas.llms import llm_factory

    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set")
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    embedding_model = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    client = AsyncOpenAI()
    llm = llm_factory(model, client=client)
    embeddings = embedding_factory("openai", model=embedding_model, client=client)
    metrics = build_live_metrics(llm, embeddings)
    by_name = {metric.name: metric for metric in metrics}
    buckets: dict[str, list[float]] = {name: [] for name in by_name}
    by_id = {item.id: item for item in items}
    for record in records:
        item = by_id[str(record["id"])]
        contexts = [str(text) for text in record["retrieved_contexts"]] or [
            "(no context retrieved)"
        ]
        response = str(record["response"])
        faithfulness = await by_name["faithfulness"].ascore(
            user_input=item.question,
            response=response,
            retrieved_contexts=contexts,
        )
        relevancy = await by_name["answer_relevancy"].ascore(
            user_input=item.question,
            response=response,
        )
        buckets["faithfulness"].append(_value(faithfulness))
        buckets["answer_relevancy"].append(_value(relevancy))
        if item.expected_behavior == "refuse":
            continue
        precision = await by_name["context_precision"].ascore(
            user_input=item.question,
            reference=item.reference_answer,
            retrieved_contexts=contexts,
        )
        recall = await by_name["context_recall"].ascore(
            user_input=item.question,
            reference=item.reference_answer,
            retrieved_contexts=contexts,
        )
        buckets["context_precision"].append(_value(precision))
        buckets["context_recall"].append(_value(recall))
    return {name: sum(values) / len(values) for name, values in buckets.items() if values}


def _value(result: Any) -> float:
    value = result.value if hasattr(result, "value") else result
    return float(value)
