"""Compare the same MotionLint checks across two motions or reports."""

from __future__ import annotations

from pathlib import Path

from motionlint.core.config import load_config
from motionlint.core.result import MotionQualityReport


def compare(baseline: MotionQualityReport, candidate: MotionQualityReport, *, config_path: str | Path | None = None) -> dict:
    config = load_config(config_path) if config_path is not None else load_config()
    for field in ("config_version", "config_sha256"):
        old, new = baseline.metadata.get(field), candidate.metadata.get(field)
        if old != new:
            raise ValueError(f"Cannot compare different or missing {field}; re-inspect both inputs with the same policy")
    allowed_drop = float(config["regression"]["max_test_score_drop"])
    baseline_tests = {test.test_name: test for test in baseline.tests}
    candidate_tests = {test.test_name: test for test in candidate.tests}
    rows = []
    regressions = []
    for name in config["tests"]:
        if name not in baseline_tests or name not in candidate_tests:
            regressions.append(f"Missing comparison test: {name}")
            continue
        old = baseline_tests[name].score
        new = candidate_tests[name].score
        if candidate_tests[name].metrics.get("evaluation_status") == "unavailable":
            regressions.append(f"{name} unavailable in candidate")
        if candidate_tests[name].status == "FAIL" and baseline_tests[name].status != "FAIL":
            regressions.append(f"{name} newly failed")
        if any(issue.severity == "critical" for issue in candidate_tests[name].issues) and not any(issue.severity == "critical" for issue in baseline_tests[name].issues):
            regressions.append(f"{name} has new critical issues")
        delta = round(new - old, 2)
        status = "REGRESSION" if delta < -allowed_drop else ("IMPROVED" if delta > 0 else "UNCHANGED")
        rows.append({"test": name, "baseline": old, "candidate": new, "change": delta, "status": status})
        if status == "REGRESSION":
            regressions.append(f"{name} decreased by {-delta:.2f} points")
    overall_change = round(candidate.overall_score - baseline.overall_score, 2)
    if overall_change < -float(config["regression"]["max_overall_score_drop"]):
        regressions.append(f"Overall score decreased by {-overall_change:.2f} points")
    return {"status": "REGRESSION DETECTED" if regressions else "PASS", "overall_change": overall_change, "tests": rows, "reasons": regressions}
