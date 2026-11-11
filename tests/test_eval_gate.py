"""Offline gate, snapshots, and the deliberately broken variants."""

from __future__ import annotations

import subprocess
import sys

from legal_rag.config import load_settings
from legal_rag.corpus import load_corpus
from legal_rag.evaluation.cli import run_records
from legal_rag.evaluation.dataset import load_dataset
from legal_rag.evaluation.gate import apply_gate
from legal_rag.evaluation.metrics import non_llm_context_recall, score_records
from legal_rag.evaluation.report import render_html, render_markdown
from legal_rag.evaluation.snapshots import read_jsonl, snapshot_path


def test_dataset_covers_answers_traps_and_refusals() -> None:
    items = load_dataset()
    assert 30 <= len(items) <= 50
    behaviors = {item.expected_behavior for item in items}
    assert behaviors == {"answer", "correct", "refuse"}
    assert sum(item.expected_behavior == "refuse" for item in items) >= 8
    assert sum(item.expected_behavior == "correct" for item in items) >= 6
    assert any(item.category == "gdpr" for item in items)


def test_string_metrics_from_ragas() -> None:
    score = non_llm_context_recall(
        ["Paris is the capital of France."],
        ["Paris is the capital of France."],
    )
    assert score == 1.0
    from ragas.metrics.collections import StringPresence

    present = StringPresence().score(
        reference="Eiffel Tower", response="The Eiffel Tower is in Paris."
    )
    value = present.value if hasattr(present, "value") else present
    assert float(value) == 1.0


def test_guarded_run_meets_thresholds_and_matches_snapshot() -> None:
    settings = load_settings()
    items = load_dataset()
    chunks = load_corpus()
    records = run_records(settings, items, chunks, "guarded")
    stored = read_jsonl(snapshot_path("guarded"))
    assert records == stored
    report = score_records(records, items, chunks, "guarded")
    gate = apply_gate(report.scores, settings.thresholds)
    assert gate.passed, gate.failures
    assert all(row.disclaimer for row in report.items)
    answer_rows = [row for row in report.items if row.expected_behavior != "refuse"]
    assert all(row.citation for row in answer_rows)


def test_bad_retriever_and_no_guardrail_fail_the_gate() -> None:
    settings = load_settings()
    items = load_dataset()
    chunks = load_corpus()
    for variant in ("bad_retriever", "no_guardrail"):
        records = run_records(settings, items, chunks, variant)
        assert records == read_jsonl(snapshot_path(variant))
        report = score_records(records, items, chunks, variant)
        gate = apply_gate(report.scores, settings.thresholds)
        assert not gate.passed, variant
        assert gate.failures


def test_cli_bad_retriever_exits_nonzero() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "legal_rag.evaluation.cli",
            "--mode",
            "offline",
            "--variant",
            "bad_retriever",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert "passed=False" in completed.stdout


def test_report_includes_before_and_after() -> None:
    settings = load_settings()
    items = load_dataset()
    chunks = load_corpus()
    reports = {
        variant: score_records(read_jsonl(snapshot_path(variant)), items, chunks, variant)
        for variant in ("no_guardrail", "guarded", "bad_retriever")
    }
    gate = apply_gate(reports["guarded"].scores, settings.thresholds)
    markdown = render_markdown(
        reports["no_guardrail"], reports["guarded"], reports["bad_retriever"], gate
    )
    page = render_html(reports["no_guardrail"], reports["guarded"], reports["bad_retriever"], gate)
    assert "Before: no-guardrail prompt" in markdown
    assert "After: guarded prompt" in markdown
    assert "Bad retriever" in markdown
    assert "LLM-judged RAGAS metrics" in markdown
    assert "<table>" in page
    assert "not legal advice" in page.lower()


def test_live_metric_builder_uses_current_collections_api() -> None:
    import inspect

    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    from legal_rag.evaluation import live

    source = inspect.getsource(live.build_live_metrics)
    for name in (
        "Faithfulness",
        "AnswerRelevancy",
        "ContextPrecisionWithReference",
        "ContextRecall",
        "llm_factory",
        "embedding_factory",
    ):
        assert name in source or name in inspect.getsource(live.score_live)
    assert Faithfulness.__name__ == "Faithfulness"
    assert AnswerRelevancy.__name__ == "AnswerRelevancy"
    assert ContextPrecisionWithReference.__name__ == "ContextPrecisionWithReference"
    assert ContextRecall.__name__ == "ContextRecall"
