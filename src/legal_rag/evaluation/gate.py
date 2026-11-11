"""Compare metric scores with the configured thresholds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateResult:
    """Outcome of a threshold check."""

    passed: bool
    failures: list[str]
    scores: dict[str, float]


def apply_gate(scores: dict[str, float], thresholds: dict[str, float]) -> GateResult:
    """Fail when any configured metric is missing or below its threshold."""
    failures: list[str] = []
    for name, threshold in thresholds.items():
        if name not in scores:
            failures.append(f"{name} was not computed")
            continue
        value = scores[name]
        if value < threshold:
            failures.append(f"{name}={value:.4f} is below {threshold:.4f}")
    return GateResult(passed=not failures, failures=failures, scores=scores)
