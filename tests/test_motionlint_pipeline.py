"""Repair acceptance, quality gate, and regression checks."""

from __future__ import annotations

import runpy
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from motionlint import MotionQualityReport, TestResult as QualityTestResult
from motionlint.adapters.lodge_adapter import normalize_lodge_array
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.regression import compare
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.experiment import run_batch
from motionlint.pipeline.repair_pipeline import repair


def test_seam_repair_loop_accepts_measured_improvement() -> None:
    raw = runpy.run_path("tests/test_lodge_motion_continuity.py")["synthetic_motion"]()
    outcome = repair(normalize_lodge_array(raw), raw_lodge=raw)
    assert outcome.after.overall_score > outcome.before.overall_score
    seam = next(step for step in outcome.steps if step["repair"] == "seam_repair")
    assert outcome.steps[0]["repair"] == "foot_lock"
    assert seam["applied"] is True
    assert seam["max_joint_shift_m"] <= seam["movement_bound_m"]
    assert outcome.raw_lodge is not None
    # A root-only jump must not smooth otherwise valid joint rotations.
    np.testing.assert_array_equal(outcome.raw_lodge[:,7:], raw[:,7:])


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
    comparison = compare(baseline, candidate)
    assert comparison["status"] == "REGRESSION DETECTED"
    assert any("foot_sliding decreased" in reason for reason in comparison["reasons"])
    assert next(row for row in comparison["tests"] if row["test"] == "temporal_continuity")["status"] == "IMPROVED"


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
