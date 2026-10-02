"""Stable result objects shared by all quality tests."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MotionIssue:
    test_name: str
    severity: str
    start_frame: int
    end_frame: int
    metric: str
    value: float
    threshold: float
    message: str
    actor_id: int | None = None
    joint_ids: list[int] = field(default_factory=list)
    repairable: bool = False
    recommended_repair: str | None = None
    timestamp_seconds: float | None = None
    other_actor_id: int | None = None
    other_joint_ids: list[int] = field(default_factory=list)
    penetration_estimate_m: float | None = None

    def __post_init__(self) -> None:
        if self.severity not in {"low", "medium", "high", "critical"}:
            raise ValueError(f"Invalid issue severity: {self.severity}")
        if self.start_frame < 0 or self.end_frame < self.start_frame:
            raise ValueError("Issue frame interval is invalid")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TestResult:
    test_name: str
    status: str
    score: float
    issues: list[MotionIssue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "WARN", "FAIL"}:
            raise ValueError(f"Invalid test status: {self.status}")
        if not 0 <= self.score <= 100:
            raise ValueError("score must be between 0 and 100")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MotionQualityReport:
    overall_score: float
    tests: list[TestResult] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0 <= self.overall_score <= 100:
            raise ValueError("overall_score must be between 0 and 100")

    @property
    def issue_count(self) -> int:
        return sum(len(result.issues) for result in self.tests)

    @property
    def critical_issue_count(self) -> int:
        return sum(issue.severity == "critical" for result in self.tests for issue in result.issues)

    @property
    def repairable_issue_count(self) -> int:
        return sum(issue.repairable for result in self.tests for issue in result.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "tests": [result.to_dict() for result in self.tests],
            "issue_count": self.issue_count,
            "critical_issue_count": self.critical_issue_count,
            "repairable_issue_count": self.repairable_issue_count,
            "metadata": self.metadata,
        }
