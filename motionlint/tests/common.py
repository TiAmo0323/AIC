"""Issue aggregation shared by motion quality checks."""

from __future__ import annotations

import numpy as np

from motionlint.core.result import MotionIssue, TestResult


def segments(mask: np.ndarray) -> list[tuple[int, int]]:
    indices = np.flatnonzero(mask)
    if not len(indices):
        return []
    breaks = np.flatnonzero(np.diff(indices) > 1) + 1
    return [(int(part[0]), int(part[-1])) for part in np.split(indices, breaks)]


def result(name: str, issues: list[MotionIssue], metrics: dict, frame_count: int, actor_count: int, scope_count: int = 1) -> TestResult:
    # Normalize by the number of inspected joints/feet, so long sequences and
    # multi-actor clips remain comparable. Segment count has a capped effect.
    covered = sum(issue.end_frame - issue.start_frame + 1 for issue in issues)
    ratio = min(1.0, covered / max(1, frame_count * actor_count * scope_count))
    severity_penalty = max(({"low": 1, "medium": 3, "high": 10, "critical": 20}[issue.severity] for issue in issues), default=0)
    fragment_penalty = min(15.0, 3.0 * np.log1p(len(issues)))
    score = float(round(max(0.0, 100.0 - severity_penalty - 60.0 * ratio - fragment_penalty), 2))
    metrics["affected_scope_ratio"] = round(ratio, 6)
    status = "FAIL" if any(issue.severity in {"high", "critical"} for issue in issues) else ("WARN" if issues else "PASS")
    return TestResult(name, status, score, issues, metrics)
