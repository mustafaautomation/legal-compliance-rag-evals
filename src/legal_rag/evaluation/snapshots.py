"""Read and write recorded pipeline outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from legal_rag.config import SNAPSHOT_DIR
from legal_rag.types import Answer

SNAPSHOT_NAMES = {
    "guarded": "guarded.jsonl",
    "no_guardrail": "no_guardrail.jsonl",
    "bad_retriever": "bad_retriever.jsonl",
}


def snapshot_path(variant: str, directory: Path = SNAPSHOT_DIR) -> Path:
    """Path of the committed snapshot for a variant."""
    try:
        name = SNAPSHOT_NAMES[variant]
    except KeyError as exc:
        raise ValueError(f"Unknown variant: {variant}") from exc
    return directory / name


def record_from_answer(item_id: str, answer: Answer) -> dict[str, Any]:
    """Convert an answer into a JSON-ready record."""
    return {
        "id": item_id,
        "question": answer.question,
        "response": answer.response,
        "retrieved_chunk_ids": [hit.chunk.chunk_id for hit in answer.retrieved],
        "retrieved_contexts": [hit.chunk.text for hit in answer.retrieved],
        "retrieved_doc_ids": [hit.chunk.doc_id for hit in answer.retrieved],
        "variant": answer.variant,
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Write records in stable key order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a snapshot. Missing judge scores are intentional."""
    if not path.exists():
        raise FileNotFoundError(f"Snapshot not found: {path}")
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise ValueError(f"Snapshot row in {path} is not an object")
            records.append(raw)
    return records
