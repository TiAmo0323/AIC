"""Compare the same MotionLint checks across two motions or reports."""

from __future__ import annotations

from pathlib import Path

from motionlint.core.config import load_config
from motionlint.core.result import MotionQualityReport
from motionlint.core.provenance import rule_hash


def compare(baseline: MotionQualityReport, candidate: MotionQualityReport, *, config_path: str | Path | None = None) -> dict:
    config = load_config(config_path) if config_path is not None else load_config()
    policy = {"config_version": config["version"], "config_sha256": rule_hash(config)}
    for field, expected in policy.items():
        old, new = baseline.metadata.get(field), candidate.metadata.get(field)
        if old is None or new is None or old != new:
            raise ValueError(f"Cannot compare different or missing {field}; re-inspect both inputs with the same policy")
        if old != expected:
            raise ValueError(f"Cannot compare reports with a different comparison policy ({field}); use the original policy or re-inspect both inputs")
    allowed_drop = float(config["regression"]["max_test_score_drop"])
    baseline_tests = {test.test_name: test for test in baseline.tests}
    candidate_tests = {test.test_name: test for test in candidate.tests}
    rows = []
    regressions = []
    incomplete = []
    for name in config["tests"]:
        if name not in baseline_tests or name not in candidate_tests:
            incomplete.append(f"Missing comparison test: {name}")
            continue
        old = baseline_tests[name].score
        new = candidate_tests[name].score
        reasons = []
        baseline_unavailable = baseline_tests[name].metrics.get("evaluation_status") == "unavailable"
        if baseline_unavailable:
            reasons.append(f"{name} unavailable in baseline")
        if candidate_tests[name].metrics.get("evaluation_status") == "unavailable":
            reasons.append(f"{name} unavailable in candidate")
        if not baseline_unavailable and candidate_tests[name].status == "FAIL" and baseline_tests[name].status != "FAIL":
            reasons.append(f"{name} newly failed")
        if not baseline_unavailable and any(issue.severity == "critical" for issue in candidate_tests[name].issues) and not any(issue.severity == "critical" for issue in baseline_tests[name].issues):
            reasons.append(f"{name} has new critical issues")
        if baseline_unavailable:
            rows.append({"test": name, "baseline": old, "candidate": new, "change": None, "status": "INCOMPARABLE", "reasons": reasons})
            incomplete.extend(reasons)
            continue
        delta = round(new - old, 2)
        if delta < -allowed_drop:
            reasons.append(f"{name} decreased by {-delta:.2f} points")
        status = "REGRESSION" if reasons else ("IMPROVED" if delta > 0 else "UNCHANGED")
        rows.append({"test": name, "baseline": old, "candidate": new, "change": delta, "status": status, "reasons": reasons})
        regressions.extend(reasons)
    overall_change = None if incomplete else round(candidate.overall_score - baseline.overall_score, 2)
    if overall_change is not None and overall_change < -float(config["regression"]["max_overall_score_drop"]):
        regressions.append(f"Overall score decreased by {-overall_change:.2f} points")
    status = "REGRESSION DETECTED" if regressions else "COMPARISON INCOMPLETE" if incomplete else "PASS"
    return {"status": status, "overall_change": overall_change, "tests": rows, "reasons": regressions + incomplete}
