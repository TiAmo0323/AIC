"""Repair acceptance, quality gate, and regression checks."""

from __future__ import annotations

import runpy
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pytest

from motionlint import MotionQualityReport, MotionIssue, TestResult as QualityTestResult
from motionlint.core.config import load_config
from motionlint.core.provenance import rule_hash
from motionlint.adapters.lodge_adapter import normalize_lodge_array
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.regression import compare
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.experiment import run_batch
from motionlint.pipeline.repair_pipeline import repair


def test_seam_repair_loop_accepts_measured_improvement(monkeypatch) -> None:
    import motionlint.pipeline.repair_pipeline as pipeline
    original_seam_repair = pipeline.repair_seams
    seam_calls = []

    def verify_seam_channels(motion, *, raw, **settings):
        source = raw.copy()
        result = original_seam_repair(motion, raw=raw, **settings)
        # This fixture has only a translation discontinuity above the configured
        # threshold. Compare the seam step with its own input, after foot IK.
        assert settings["rotation_joint_ids"] == []
        np.testing.assert_array_equal(result[1][:, 7:], source[:, 7:])
        np.testing.assert_array_equal(result[1][:, :4], source[:, :4])
        np.testing.assert_array_equal(raw, source)
        seam_calls.append(settings)
        return result

    monkeypatch.setattr(pipeline, "repair_seams", verify_seam_channels)
    raw = runpy.run_path("tests/test_lodge_motion_continuity.py")["synthetic_motion"]()
    original = raw.copy()
    outcome = repair(normalize_lodge_array(raw), raw_lodge=raw)
    assert outcome.after.overall_score > outcome.before.overall_score
    seam = next(step for step in outcome.steps if step["repair"] == "seam_repair")
    assert outcome.steps[0]["repair"] == "foot_lock"
    assert seam["applied"] is True
    assert seam["max_joint_shift_m"] <= seam["movement_bound_m"]
    assert outcome.raw_lodge is not None
    assert seam_calls
    np.testing.assert_array_equal(raw, original)
    np.testing.assert_array_equal(outcome.raw_lodge[:, :4], raw[:, :4])


def test_quality_gate_rejects_a_failed_test_despite_high_overall() -> None:
    tests = [QualityTestResult(name, "PASS", 100) for name in (
        "temporal_continuity", "skeleton_integrity", "foot_sliding",
        "ground_contact", "collision", "motion_jerk",
    )]
    passed = MotionQualityReport(100, tests)
    assert evaluate_gate(passed).status == "PASS"
    tests[4] = QualityTestResult("collision", "FAIL", 90)
    failed = MotionQualityReport(98, tests)
    gate = evaluate_gate(failed)
    assert gate.status == "FAIL"
    assert any("collision has high-severity" in reason for reason in gate.reasons)


def test_regression_catches_foot_decline_while_temporal_improves() -> None:
    names = ("temporal_continuity", "skeleton_integrity", "foot_sliding", "ground_contact", "collision", "motion_jerk")
    baseline = MotionQualityReport(82, [QualityTestResult(name, "PASS", 80) for name in names])
    candidate_scores = {name: 80 for name in names}
    candidate_scores["temporal_continuity"] = 95
    candidate_scores["foot_sliding"] = 70
    candidate = MotionQualityReport(83, [QualityTestResult(name, "PASS", candidate_scores[name]) for name in names])
    policy = load_config()
    for report in (baseline, candidate):
        report.metadata.update(config_version=policy["version"], config_sha256=rule_hash(policy))
    comparison = compare(baseline, candidate)
    assert comparison["status"] == "REGRESSION DETECTED"
    assert any("foot_sliding decreased" in reason for reason in comparison["reasons"])
    assert next(row for row in comparison["tests"] if row["test"] == "temporal_continuity")["status"] == "IMPROVED"


@pytest.mark.parametrize("reason", ["failure", "critical", "unavailable"])
def test_regression_marks_new_failures_even_when_scores_increase(reason):
    policy = load_config()
    metadata = {"config_version": policy["version"], "config_sha256": rule_hash(policy)}
    baseline = MotionQualityReport(90, [QualityTestResult(name, "PASS", 90) for name in policy["tests"]], metadata=dict(metadata))
    candidate = MotionQualityReport(95, [QualityTestResult(name, "PASS", 95) for name in policy["tests"]], metadata=dict(metadata))
    test = candidate.tests[0]
    if reason == "failure":
        test.status = "FAIL"
    elif reason == "critical":
        test.issues.append(MotionIssue(test.test_name, "critical", 0, 1, "jump", 1, .1, "new issue"))
    else:
        test.metrics["evaluation_status"] = "unavailable"
    result = compare(baseline, candidate)
    row = next(row for row in result["tests"] if row["test"] == test.test_name)
    assert result["status"] == "REGRESSION DETECTED"
    assert row["status"] == "REGRESSION" and row["change"] == 5
    assert len(row["reasons"]) == 1 and row["reasons"][0] in result["reasons"]
    assert not any("decreased" in reason for reason in result["reasons"])


@pytest.mark.parametrize("field", ["config_version", "config_sha256"])
def test_regression_rejects_reports_with_both_policy_fields_missing(field):
    raw = np.zeros((4, 139), dtype=np.float32)
    raw[:, 7:] = np.tile([1, 0, 0, 0, 1, 0], 22)
    baseline = inspect(normalize_lodge_array(raw))
    candidate = inspect(normalize_lodge_array(raw))
    del baseline.metadata[field]; del candidate.metadata[field]
    with pytest.raises(ValueError, match=field):
        compare(baseline, candidate)


def test_regression_requires_the_policy_used_to_inspect_reports(tmp_path):
    from copy import deepcopy
    import yaml
    policy = deepcopy(load_config())
    policy["regression"]["max_test_score_drop"] += 1
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    raw = np.zeros((4, 139), dtype=np.float32)
    raw[:, 7:] = np.tile([1, 0, 0, 0, 1, 0], 22)
    baseline = inspect(normalize_lodge_array(raw), config_path=path)
    candidate = inspect(normalize_lodge_array(raw), config_path=path)
    with pytest.raises(ValueError, match="comparison policy"):
        compare(baseline, candidate)
    # The policy is accepted; this root-at-zero fixture lacks support coverage,
    # so the honest result is incomplete rather than a numerical improvement.
    assert compare(baseline, candidate, config_path=path)["status"] == "COMPARISON INCOMPLETE"


@pytest.mark.parametrize("candidate_unavailable", [False, True])
def test_regression_cannot_claim_improvement_over_unavailable_baseline(candidate_unavailable):
    policy = load_config()
    metadata = {"config_version": policy["version"], "config_sha256": rule_hash(policy)}
    baseline = MotionQualityReport(80, [QualityTestResult(name, "PASS", 80) for name in policy["tests"]], metadata=dict(metadata))
    candidate = MotionQualityReport(90, [QualityTestResult(name, "PASS", 90) for name in policy["tests"]], metadata=dict(metadata))
    baseline.tests[0].score = 0
    baseline.tests[0].metrics["evaluation_status"] = "unavailable"
    if candidate_unavailable:
        candidate.tests[0].metrics["evaluation_status"] = "unavailable"
    result = compare(baseline, candidate)
    assert result["status"] == "COMPARISON INCOMPLETE"
    assert result["overall_change"] is None
    row = result["tests"][0]
    assert row["status"] == "INCOMPARABLE" and row["change"] is None
    assert any("unavailable in baseline" in reason for reason in result["reasons"])


def test_incomplete_regression_still_reports_declines_in_evaluated_tests():
    policy = load_config()
    metadata = {"config_version": policy["version"], "config_sha256": rule_hash(policy)}
    baseline = MotionQualityReport(80, [QualityTestResult(name, "PASS", 80) for name in policy["tests"]], metadata=dict(metadata))
    candidate = MotionQualityReport(80, [QualityTestResult(name, "PASS", 80) for name in policy["tests"]], metadata=dict(metadata))
    baseline.tests.pop()
    candidate.tests[0].score = 60
    result = compare(baseline, candidate)
    assert result["status"] == "REGRESSION DETECTED"
    assert result["overall_change"] is None
    assert any("Missing comparison test" in reason for reason in result["reasons"])
    assert any("decreased by 20" in reason for reason in result["reasons"])


def test_regression_detects_injected_slide_in_real_motion_arrays() -> None:
    raw = np.zeros((30, 139), dtype=np.float32)
    raw[:, :4] = 1
    raw[:, 5] = 1
    raw[:, 7:] = np.tile([1, 0, 0, 0, 1, 0], 22)
    baseline = inspect(normalize_lodge_array(raw))
    raw[:, 4] = np.arange(30) * 0.008
    candidate = inspect(normalize_lodge_array(raw))
    outcome = compare(baseline, candidate)
    assert outcome["status"] == "REGRESSION DETECTED"
    assert next(row for row in outcome["tests"] if row["test"] == "foot_sliding")["status"] == "REGRESSION"


def test_batch_runner_exports_csv_and_json() -> None:
    raw = runpy.run_path("tests/test_lodge_motion_continuity.py")["synthetic_motion"]()
    Path("reports").mkdir(exist_ok=True)
    with TemporaryDirectory(dir="reports") as scratch:
        root = Path(scratch)
        motion_path = root / "demo.npy"
        np.save(motion_path, raw)
        summary = run_batch(
            [{"name": "demo", "input": "demo.npy"}],
            root / "batch",
            base_dir=root,
        )
        assert summary["count"] == 1
        assert summary["success_count"] == 1
        assert (root / "batch" / "summary.csv").is_file()
        assert (root / "batch" / "summary.json").is_file()
        assert (root / "batch" / "demo" / "motionlint_report.json").is_file()
