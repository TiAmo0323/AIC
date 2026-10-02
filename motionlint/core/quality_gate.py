"""Deterministic quality gate driven by YAML policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from motionlint.core.config import load_config
from motionlint.core.result import MotionQualityReport


@dataclass
class GateResult:
    status: str
    reasons: list[str]

    def to_dict(self) -> dict:
        return {"status": self.status, "reasons": self.reasons}


def evaluate_gate(report: MotionQualityReport, *, config_path: str | Path | None = None) -> GateResult:
    config = load_config(config_path) if config_path is not None else load_config()
    gate = config["gate"]
    reasons = []
    if report.overall_score < float(gate["overall_min_score"]):
        reasons.append(f"Overall score {report.overall_score:.2f} is below {gate['overall_min_score']}")
    if report.critical_issue_count > int(gate["max_critical_issues"]):
        reasons.append(f"Critical issues {report.critical_issue_count} exceed {gate['max_critical_issues']}")
    tests = {test.test_name: test for test in report.tests}
    for name in config["tests"]:
        if name not in tests:
            reasons.append(f"Configured test {name} is missing")
    for name, minimum in gate["requirements"].items():
        test = tests.get(name)
        if test is None:
            reasons.append(f"Required test {name} is missing")
        elif test.score < float(minimum):
            reasons.append(f"{name} score {test.score:.2f} is below {minimum}")
    for test in report.tests:
        if test.status == "FAIL":
            reasons.append(f"{test.test_name} has high-severity issues")
        elif test.status == "WARN" and test.metrics.get("reason"):
            reasons.append(f"{test.test_name} could not run: {test.metrics['reason']}")
    return GateResult("FAIL" if reasons else "PASS", reasons)
