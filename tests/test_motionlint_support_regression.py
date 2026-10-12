"""Reject physical regressions that aggregate quality scores can conceal."""
import numpy as np
import pytest

from motionlint import MotionSequence, MotionIssue
from motionlint.adapters.intergen_adapter import JOINT_NAMES, PARENTS
from motionlint.benchmark.fixtures import standing
from motionlint.core.config import load_config
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.repair_pipeline import _assess, repair
from motionlint.repairs.foot_lock import repair_foot_sliding
from motionlint.repairs.support_metrics import compare_support


def motion(positions, fps=30., up_axis=1):
    if positions.ndim == 3:
        positions = positions[:, None]
    return MotionSequence("intergen", fps, len(positions), positions.shape[1], positions=positions,
                          root_translation=positions[:, :, 0].copy(), joint_names=JOINT_NAMES.copy(),
                          metadata={"parents": PARENTS.copy(), "up_axis": up_axis, "floor_height_m": 0.,
                                    "foot_joint_ids": [7, 8, 10, 11], "left_foot_joint_ids": [7, 10],
                                    "right_foot_joint_ids": [8, 11]})


def assessment(original, candidate, name="foot_lock", target="foot_sliding"):
    return _assess(name, target, original, candidate, inspect(original), inspect(candidate), load_config())


def test_fewer_sliding_frames_cannot_hide_a_longer_sliding_path():
    before = standing(20)
    before[:13, :, 0] += (np.arange(13) % 2 * .019)[:, None]
    after = standing(20)
    after[7, :, 0] += .125
    original, candidate = motion(before, 10.), motion(after, 10.)
    result = assessment(original, candidate)
    guard = result["support_guard"]
    assert guard["original_support_sliding_after"] < guard["original_support_sliding_before"]
    assert result["overall_after"] > result["overall_before"]
    assert not result["newly_failed_tests"]
    assert guard["original_support_distance_after_m"] > guard["original_support_distance_before_m"]
    assert not result["applied"]
    assert "supported_foot_distance_increased" in result["rejection_codes"]


def test_one_actor_improving_cannot_hide_new_sliding_on_another_actor():
    before = np.stack([standing(20), standing(20)], axis=1)
    before[:, 1, :, 0] += 3.
    before[:13, 0, :, 0] += (np.arange(13) % 2 * .019)[:, None]
    after = np.stack([standing(20), standing(20)], axis=1)
    after[:, 1, :, 0] += 3.
    after[7, 1, :, 0] += .04
    result = assessment(motion(before, 10.), motion(after, 10.))
    assert result["support_guard"]["original_support_sliding_after"] < result["support_guard"]["original_support_sliding_before"]
    assert not result["applied"]
    assert "supported_foot_sliding_increased" in result["rejection_codes"]
    assert any(r["actor_id"] == 1 and not r["distance_not_worsened"] for r in result["support_guard"]["per_foot"])


def test_less_total_sliding_cannot_hide_new_severe_sliding_at_another_time():
    before = standing(40)
    before[:17, :, 0] += (np.arange(17) % 2 * .019)[:, None]
    after = standing(40)
    after[27, :, 0] += .019
    result = assessment(motion(before, 10.), motion(after, 10.))
    assert result["overall_after"] > result["overall_before"]
    assert result["support_guard"]["improved"]
    assert not result["newly_failed_tests"]
    assert not result["applied"]
    assert result["new_severe_issue_frames"]["foot_sliding"] > 0
    assert "new_severe_issue_frames" in result["rejection_codes"]


def test_bone_improvement_cannot_introduce_below_threshold_foot_drift():
    before = standing(24)
    before[:, 20, 0] += np.linspace(-.05, .05, 24)
    after = standing(24)
    after[..., 0] += np.linspace(-.023, .023, 24)[:, None]
    original, candidate = motion(before), motion(after)
    assert evaluate_gate(inspect(candidate)).status == "PASS"
    result = assessment(original, candidate, "bone_length_projection", "skeleton_integrity")
    assert result["target_after"] > result["target_before"]
    assert not result["bound_exceeded"] and not result["newly_failed_tests"]
    assert not result["applied"]
    assert "supported_foot_distance_increased" in result["rejection_codes"]


def test_existing_failed_test_cannot_hide_a_new_severe_issue_location():
    original = motion(standing(40))
    before, after = inspect(original), inspect(original)
    for report in (before, after):
        collision = next(t for t in report.tests if t.test_name == "collision")
        collision.status, collision.score = "FAIL", 97
        collision.issues.append(MotionIssue("collision", "high", 10, 12, "distance", .01, .1,
                                            "risk", actor_id=0, joint_ids=[20, 15]))
    next(t for t in before.tests if t.test_name == "skeleton_integrity").score = 90
    before.overall_score, after.overall_score = 95, 98
    next(t for t in after.tests if t.test_name == "collision").issues.append(
        MotionIssue("collision", "high", 10, 12, "distance", .01, .1, "risk", actor_id=0, joint_ids=[21, 15]))
    result = _assess("bone_length_projection", "skeleton_integrity", original, original, before, after, load_config())
    assert not result["applied"] and not result["newly_failed_tests"]
    assert result["new_severe_issue_frames"] == {"collision": 3}
    assert "new_severe_issue_frames" in result["rejection_codes"]


def test_common_planted_drift_is_repaired_inside_bound_without_bone_changes():
    positions = standing(90)
    positions[..., 0] += np.clip(np.arange(90) - 29, 0, 30)[:, None] * .006666666666666667
    original = motion(positions)
    snapshot = original.positions.copy()
    result = repair(original)
    assert evaluate_gate(result.before).status == "FAIL"
    assert evaluate_gate(result.after).status == "PASS"
    assert result.to_dict()["algorithm_version"] == 6
    assert result.steps[0]["applied"]
    assert result.support_comparison["original_support_distance_after_m"] < 1e-7
    assert np.linalg.norm(result.motion.positions - snapshot, axis=-1).max() <= .15 + 1e-6
    for value in (original, result.motion):
        lengths = np.linalg.norm(value.positions[:, :, 1:] - value.positions[:, :, np.asarray(PARENTS[1:])], axis=-1)
        np.testing.assert_allclose(lengths, np.broadcast_to(lengths[0], lengths.shape), atol=1e-7)
    np.testing.assert_array_equal(original.positions, snapshot)


def test_foot_repair_leaves_an_actor_without_foot_issues_unchanged():
    positions = np.stack([standing(60), standing(60)], axis=1)
    positions[..., 0] += np.arange(60)[:, None, None] * np.array([.008, .002])[None, :, None]
    positions[:, 1, :, 0] += 3.
    original = motion(positions)
    issues = next(t for t in inspect(original).tests if t.test_name == "foot_sliding").issues
    assert {i.actor_id for i in issues} == {0}
    repaired, _, detail = repair_foot_sliding(original, issues, anchor_method="interval", root_method="support",
                                             root_follow=True, center_method="bounds")
    assert detail["affected_actor_ids"] == [0]
    np.testing.assert_array_equal(repaired.positions[:, 1], original.positions[:, 1])
    assert np.linalg.norm(repaired.positions - original.positions, axis=-1).max() <= .15 + 1e-6


def test_shared_support_handles_z_up_and_fractional_fps():
    positions = standing(24)[..., [0, 2, 1]]
    positions[..., 0] += np.arange(24)[:, None] * .008
    positions[..., 1] += np.arange(24)[:, None] * .004
    original = motion(positions, 29.97, 2)
    issues = next(t for t in inspect(original).tests if t.test_name == "foot_sliding").issues
    repaired, _, _ = repair_foot_sliding(original, issues, anchor_method="interval", root_method="support",
                                         center_method="bounds", root_follow=True)
    np.testing.assert_array_equal(repaired.positions[..., 2], original.positions[..., 2])
    assert repaired.fps == 29.97
    assert compare_support(original, repaired, load_config()["tests"]["foot_sliding"])["original_support_distance_after_m"] < 1e-7


@pytest.mark.parametrize("value", [0., -.1, float("nan"), float("inf")])
def test_invalid_foot_displacement_bound_is_rejected(value):
    with pytest.raises(ValueError, match="finite and positive"):
        repair_foot_sliding(motion(standing(24)), [], max_correction_m=value)
