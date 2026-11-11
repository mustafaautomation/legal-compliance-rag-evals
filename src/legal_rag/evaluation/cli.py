"""Evaluation command line. Exits non-zero when a metric misses its threshold."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from legal_rag.config import DOCS_DIR, SNAPSHOT_DIR, Settings, load_settings
from legal_rag.corpus import load_corpus
from legal_rag.evaluation.dataset import EvalItem, load_dataset
from legal_rag.evaluation.gate import GateResult, apply_gate
from legal_rag.evaluation.live import score_live
from legal_rag.evaluation.metrics import MetricReport, score_records
from legal_rag.evaluation.report import write_report
from legal_rag.evaluation.snapshots import (
    read_jsonl,
    record_from_answer,
    snapshot_path,
    write_jsonl,
)
from legal_rag.pipeline import build_pipeline
from legal_rag.types import Chunk


def main(argv: list[str] | None = None) -> int:
    """Run the offline gate or the live RAGAS evaluation."""
    parser = argparse.ArgumentParser(description="Score the compliance RAG pipeline.")
    parser.add_argument("--mode", choices=["offline", "live"], default="offline")
    parser.add_argument(
        "--variant",
        choices=["guarded", "no_guardrail", "bad_retriever"],
        default="guarded",
    )
    parser.add_argument("--write-snapshot", action="store_true")
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--provider", choices=["fake", "openai", "anthropic"], default="fake")
    args = parser.parse_args(argv)
    settings = load_settings()
    items = load_dataset()
    chunks = load_corpus()
    if args.mode == "live":
        return _live(settings, items, chunks, args.provider)
    if args.write_report:
        return _write_full_report(settings, items, chunks)
    records = _records_for_variant(
        settings,
        items,
        chunks,
        args.variant,
        write_snapshot=args.write_snapshot,
        provider_kind=args.provider,
    )
    report = score_records(records, items, chunks, args.variant)
    gate = apply_gate(report.scores, settings.thresholds)
    _print_gate(args.variant, gate)
    return 0 if gate.passed else 1


def run_records(
    settings: Settings,
    items: list[EvalItem],
    chunks: list[Chunk],
    variant: str,
    provider_kind: str = "fake",
) -> list[dict[str, Any]]:
    """Run one variant and return snapshot records."""
    pipeline = build_pipeline(
        settings,
        variant=variant,
        provider_kind=provider_kind,
        chunks=chunks,
    )
    records: list[dict[str, Any]] = []
    for item in items:
        answer = pipeline.answer(item.question)
        records.append(record_from_answer(item.id, answer))
    return records


def _records_for_variant(
    settings: Settings,
    items: list[EvalItem],
    chunks: list[Chunk],
    variant: str,
    *,
    write_snapshot: bool,
    provider_kind: str,
) -> list[dict[str, Any]]:
    if write_snapshot or provider_kind != "fake":
        records = run_records(settings, items, chunks, variant, provider_kind)
        if write_snapshot:
            write_jsonl(snapshot_path(variant), records)
        return records
    return read_jsonl(snapshot_path(variant))


def _write_full_report(settings: Settings, items: list[EvalItem], chunks: list[Chunk]) -> int:
    reports: dict[str, MetricReport] = {}
    for variant in ("no_guardrail", "guarded", "bad_retriever"):
        records = run_records(settings, items, chunks, variant)
        write_jsonl(snapshot_path(variant, SNAPSHOT_DIR), records)
        reports[variant] = score_records(records, items, chunks, variant)
    gate = apply_gate(reports["guarded"].scores, settings.thresholds)
    write_report(
        DOCS_DIR, reports["no_guardrail"], reports["guarded"], reports["bad_retriever"], gate
    )
    _print_gate("guarded", gate)
    return 0 if gate.passed else 1


def _live(
    settings: Settings,
    items: list[EvalItem],
    chunks: list[Chunk],
    provider_kind: str,
) -> int:
    if provider_kind == "fake":
        provider_kind = "openai"
    records = run_records(settings, items, chunks, "guarded", provider_kind)
    live_scores = asyncio.run(score_live(records, items))
    offline = score_records(records, items, chunks, "guarded")
    combined = dict(offline.scores)
    combined.update(live_scores)
    thresholds = dict(settings.thresholds)
    thresholds.update(settings.live_thresholds)
    gate = apply_gate(combined, thresholds)
    _print_gate("live", gate)
    return 0 if gate.passed else 1


def _print_gate(label: str, gate: GateResult) -> None:
    print(f"variant={label} passed={gate.passed}")
    for name, value in gate.scores.items():
        print(f"  {name}={value:.4f}")
    for failure in gate.failures:
        print(f"  FAIL {failure}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
