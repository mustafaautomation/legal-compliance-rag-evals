"""Repository paths and threshold config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = REPO_ROOT / "data" / "corpus"
EVAL_PATH = REPO_ROOT / "data" / "eval" / "questions.jsonl"
SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshots"
THRESHOLD_PATH = REPO_ROOT / "configs" / "thresholds.yaml"
DOCS_DIR = REPO_ROOT / "docs"


@dataclass(frozen=True)
class Settings:
    """Runtime settings that the gate and the guarded generator share."""

    top_k: int
    min_term_overlap: int
    bad_retriever_doc_id: str
    thresholds: dict[str, float]
    live_thresholds: dict[str, float]


def load_settings(path: Path = THRESHOLD_PATH) -> Settings:
    """Load thresholds and retrieval settings from YAML."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Config at {path} must be a mapping")
    thresholds = _float_map(raw.get("thresholds"), "thresholds")
    live = _float_map(raw.get("live_thresholds"), "live_thresholds")
    return Settings(
        top_k=int(raw["top_k"]),
        min_term_overlap=int(raw["min_term_overlap"]),
        bad_retriever_doc_id=str(raw["bad_retriever_doc_id"]),
        thresholds=thresholds,
        live_thresholds=live,
    )


def _float_map(value: object, label: str) -> dict[str, float]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{label} must be a non-empty mapping")
    mapped: dict[str, float] = {}
    for key, item in value.items():
        mapped[str(key)] = float(item)
    return mapped
