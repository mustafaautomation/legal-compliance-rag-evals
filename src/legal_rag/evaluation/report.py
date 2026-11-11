"""Markdown and HTML evaluation reports."""

from __future__ import annotations

import html
from pathlib import Path

from legal_rag.evaluation.gate import GateResult
from legal_rag.evaluation.metrics import MetricReport

METRIC_NOTES = {
    "retrieval_hit_rate": "Share of answerable questions whose gold document appears in the retrieved clauses.",
    "mrr": "Mean reciprocal rank of the first gold document. Higher means the right clause is nearer the top.",
    "non_llm_context_recall": "RAGAS NonLLMContextRecall. Share of gold clauses matched by string similarity in the retrieved set.",
    "string_presence": "RAGAS StringPresence. Share of replies that contain the labelled phrase.",
    "disclaimer_rate": "Share of replies that say the answer is not legal advice.",
    "citation_rate": "Share of answerable replies that cite a clause id or GDPR article.",
    "refusal_correctness": "Share of replies that refuse out-of-scope questions and answer in-scope questions from the clause text.",
}


def render_markdown(
    before: MetricReport,
    after: MetricReport,
    broken: MetricReport,
    gate: GateResult,
) -> str:
    """Render the before/after report."""
    lines = [
        "# Helios Ledger eval report",
        "",
        "Offline scores from the deterministic pipeline in this repository.",
        "LLM-judged RAGAS metrics (faithfulness, answer relevancy, context precision, context recall) were not run.",
        "No judge scores are recorded in the snapshots.",
        "",
        "## Metric comparison",
        "",
        "| Metric | Before: no-guardrail prompt | After: guarded prompt | Bad retriever |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name in after.scores:
        lines.append(
            f"| {name} | {_fmt(before.scores[name])} | {_fmt(after.scores[name])} | {_fmt(broken.scores[name])} |"
        )
    lines.extend(
        [
            "",
            "## Gate on the guarded run",
            "",
            "Passed." if gate.passed else "Failed.",
            "",
        ]
    )
    if gate.failures:
        lines.extend(f"- {failure}" for failure in gate.failures)
        lines.append("")
    lines.extend(
        [
            "## What the metrics mean",
            "",
        ]
    )
    for name, note in METRIC_NOTES.items():
        lines.append(f"- **{name}**: {note}")
    lines.extend(["", "## Per-question failures", ""])
    lines.extend(_failure_section("After: guarded prompt", after))
    lines.extend(_failure_section("Before: no-guardrail prompt", before))
    lines.extend(_failure_section("Bad retriever", broken))
    lines.extend(
        [
            "## Data note",
            "",
            "Helios Ledger Ltd is fictional. Policy text is synthetic. GDPR passages are short EUR-Lex excerpts with attribution in the corpus files.",
            "This report is not legal advice.",
            "",
        ]
    )
    return "\n".join(lines)


def render_html(
    before: MetricReport,
    after: MetricReport,
    broken: MetricReport,
    gate: GateResult,
) -> str:
    """Render the same report as a single HTML page."""
    rows = []
    for name in after.scores:
        rows.append(
            "<tr>"
            f"<td>{html.escape(name)}</td>"
            f"<td>{_fmt(before.scores[name])}</td>"
            f"<td>{_fmt(after.scores[name])}</td>"
            f"<td>{_fmt(broken.scores[name])}</td>"
            "</tr>"
        )
    notes = "".join(
        f"<li><strong>{html.escape(name)}</strong>: {html.escape(note)}</li>"
        for name, note in METRIC_NOTES.items()
    )
    status = "Passed" if gate.passed else "Failed"
    failure_html = "".join(f"<li>{html.escape(item)}</li>" for item in gate.failures)
    sections = (
        _html_failures("After: guarded prompt", after)
        + _html_failures("Before: no-guardrail prompt", before)
        + _html_failures("Bad retriever", broken)
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Helios Ledger eval report</title>
  <style>
    body {{ font-family: Georgia, serif; margin: 2rem auto; max-width: 960px; color: #1c1917; }}
    h1 {{ font-size: 1.6rem; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; }}
    th, td {{ border: 1px solid #d6d3d1; padding: 0.45rem 0.6rem; text-align: left; }}
    th {{ background: #f5f5f4; }}
    td:nth-child(n+2), th:nth-child(n+2) {{ text-align: right; }}
    .status {{ font-weight: bold; }}
    .note {{ background: #fafaf9; border: 1px solid #e7e5e4; padding: 0.8rem 1rem; }}
  </style>
</head>
<body>
  <h1>Helios Ledger eval report</h1>
  <p class="note">Offline scores from the deterministic pipeline. LLM-judged RAGAS metrics were not run, and no judge scores are stored. This is not legal advice.</p>
  <h2>Metric comparison</h2>
  <table>
    <thead>
      <tr><th>Metric</th><th>Before: no-guardrail prompt</th><th>After: guarded prompt</th><th>Bad retriever</th></tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
  <h2>Gate on the guarded run</h2>
  <p class="status">{status}</p>
  <ul>{failure_html}</ul>
  <h2>What the metrics mean</h2>
  <ul>{notes}</ul>
  <h2>Per-question failures</h2>
  {sections}
  <p>Helios Ledger Ltd is fictional. Policy text is synthetic. GDPR passages are short EUR-Lex excerpts.</p>
</body>
</html>
"""


def write_report(
    directory: Path,
    before: MetricReport,
    after: MetricReport,
    broken: MetricReport,
    gate: GateResult,
) -> tuple[Path, Path]:
    """Write the markdown and HTML reports."""
    directory.mkdir(parents=True, exist_ok=True)
    markdown_path = directory / "eval_report.md"
    html_path = directory / "eval_report.html"
    markdown_path.write_text(render_markdown(before, after, broken, gate), encoding="utf-8")
    html_path.write_text(render_html(before, after, broken, gate), encoding="utf-8")
    return markdown_path, html_path


def _fmt(value: float) -> str:
    return f"{value:.4f}"


def _failure_section(title: str, report: MetricReport) -> list[str]:
    failed = [row for row in report.items if row.failure_reasons]
    lines = [f"### {title}", ""]
    if not failed:
        lines.extend(["No per-question failures.", ""])
        return lines
    lines.append(f"{len(failed)} of {len(report.items)} questions failed at least one check.")
    lines.append("")
    for row in failed:
        reason = "; ".join(row.failure_reasons)
        lines.append(f"- `{row.item_id}` ({row.category}): {row.question} — {reason}")
    lines.append("")
    return lines


def _html_failures(title: str, report: MetricReport) -> str:
    failed = [row for row in report.items if row.failure_reasons]
    if not failed:
        body = "<p>No per-question failures.</p>"
    else:
        items = "".join(
            "<li><code>{}</code> ({}): {} — {}</li>".format(
                html.escape(row.item_id),
                html.escape(row.category),
                html.escape(row.question),
                html.escape("; ".join(row.failure_reasons)),
            )
            for row in failed
        )
        body = f"<p>{len(failed)} of {len(report.items)} questions failed at least one check.</p><ul>{items}</ul>"
    return f"<h3>{html.escape(title)}</h3>{body}"
