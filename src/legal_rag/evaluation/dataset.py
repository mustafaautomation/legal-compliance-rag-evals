"""Labelled evaluation questions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from legal_rag.config import EVAL_PATH

BEHAVIORS = frozenset({"answer", "correct", "refuse"})


@dataclass(frozen=True)
class EvalItem:
    """One labelled question."""

    id: str
    question: str
    reference_answer: str
    reference_doc_ids: list[str]
    anchors: list[str]
    expected_behavior: str
    forbidden_phrases: list[str]
    category: str
    presence_phrase: str

    @property
    def expects_retrieval(self) -> bool:
        return self.expected_behavior in {"answer", "correct"}


def load_dataset(path: Path = EVAL_PATH) -> list[EvalItem]:
    """Load the JSONL eval set."""
    items: list[EvalItem] = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        if not isinstance(raw, dict):
            raise ValueError(f"Line {line_number} is not an object")
        behavior = str(raw["expected_behavior"])
        if behavior not in BEHAVIORS:
            raise ValueError(f"Line {line_number} has unknown behavior {behavior}")
        item = EvalItem(
            id=str(raw["id"]),
            question=str(raw["question"]),
            reference_answer=str(raw["reference_answer"]),
            reference_doc_ids=[str(doc_id) for doc_id in raw["reference_doc_ids"]],
            anchors=[str(anchor) for anchor in raw["anchors"]],
            expected_behavior=behavior,
            forbidden_phrases=[str(phrase) for phrase in raw["forbidden_phrases"]],
            category=str(raw["category"]),
            presence_phrase=str(raw["presence_phrase"]),
        )
        if item.id in seen:
            raise ValueError(f"Duplicate question id {item.id}")
        seen.add(item.id)
        if item.expects_retrieval and (not item.reference_doc_ids or not item.anchors):
            raise ValueError(f"{item.id} needs reference documents and anchors")
        if not item.expects_retrieval and item.reference_doc_ids:
            raise ValueError(f"Refusal item {item.id} should not list reference documents")
        items.append(item)
    if not items:
        raise ValueError(f"No questions in {path}")
    return items
