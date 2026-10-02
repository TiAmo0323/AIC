"""Kinematic repairs must preserve physical constraints and reject regressions."""
from dataclasses import replace

import numpy as np

from motionlint import MotionSequence, MotionQualityReport, TestResult as QualityTest
from motionlint.adapters.intergen_adapter import JOINT_NAMES, PARENTS
from motionlint.core.config import load_config
from motionlint.core.quality_gate import evaluate_gate
from motionlint.core.foot_support import FootSupport, estimate_support
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.repair_pipeline import _assess
from motionlint.repairs.bone_length import project_bone_lengths
from motionlint.repairs.foot_lock import _interval_anchors, _speed_limited_correction, repair_foot_sliding
from motionlint.repairs.inter_actor import separate_actors
from motionlint.repairs.kinematics import align_rotation, two_bone_ik
from motionlint.tests import foot_sliding, collision


def fixture(actors=1, frames=24):
    offsets = np.array([[0, 1, 0], [-.1, -.1, 0], [.1, -.1, 0], [0, .15, 0],
        [0, -.4, .04], [0, -.4, .04], [0, .15, 0], [0, -.4, -.04], [0, -.4, -.04],
        [0, .15, 0], [0, 0, .12], [0, 0, .12], [0, .15, 0], [-.12, 0, 0],
        [.12, 0, 0], [0, .15, 0], [-.15, 0, 0], [.15, 0, 0], [-.25, -.1, 0],
        [.25, -.1, 0], [-.2, -.1, 0], [.2, -.1, 0]])
    positions = np.zeros((frames, actors, 22, 3))
    for joint, parent in enumerate(PARENTS):
        positions[:, :, joint] = offsets[joint] if parent < 0 else positions[:, :, parent] + offsets[joint]
    return MotionSequence("intergen", 30, frames, actors, positions=positions,
        root_translation=positions[:, :, 0].copy(), joint_names=JOINT_NAMES,
        metadata={"parents": PARENTS, "up_axis": 1, "foot_joint_ids": [7, 8, 10, 11],
                  "left_foot_joint_ids": [7, 10], "right_foot_joint_ids": [8, 11]})


def lengths(motion):
    return np.linalg.norm(motion.positions[:, :, 1:] - motion.positions[:, :, np.array(PARENTS[1:])], axis=-1)


def test_two_bone_reachable_and_unreachable_targets_preserve_lengths():
    start = np.zeros((3, 3))
    bend = np.tile([.1, -.4, 0], (3, 1))
    end = np.tile([0, -.8, 0], (3, 1))
    target = np.array([[.1, -.7, .1], [0, -2, 0], [0, 0, 0]])
    knee, ankle = two_bone_ik(start, bend, end, target)
    np.testing.assert_allclose(np.linalg.norm(knee - start, axis=-1), np.linalg.norm(bend - start, axis=-1), atol=1e-7)
    np.testing.assert_allclose(np.linalg.norm(ankle - knee, axis=-1), np.linalg.norm(end - bend, axis=-1), atol=1e-7)
    np.testing.assert_allclose(ankle[0], target[0], atol=1e-7)
    assert np.isfinite(knee).all() and np.isfinite(ankle).all()


def test_opposite_vector_rotation_is_proper():
    rotation = align_rotation(np.array([[1., 0, 0]]), np.array([[-1., 0, 0]]))[0]
    np.testing.assert_allclose(rotation @ [1, 0, 0], [-1, 0, 0], atol=1e-7)
    np.testing.assert_allclose(rotation.T @ rotation, np.eye(3), atol=1e-7)
    np.testing.assert_allclose(np.linalg.det(rotation), 1, atol=1e-7)


def test_ik_keeps_knee_on_same_bend_side_as_target_axis_turns():
    angles = np.linspace(0, .15, 9)
    start = np.zeros((9, 3))
    bend = np.tile([.02, -.4, 0], (9, 1))
    end = np.tile([0, -.8, 0], (9, 1))
    target = .7 * np.stack([np.sin(angles), -np.cos(angles), np.zeros(9)], axis=-1)
    knee, _ = two_bone_ik(start, bend, end, target)
    outward = np.stack([np.cos(angles), np.sin(angles), np.zeros(9)], axis=-1)
    assert np.all(np.sum(knee * outward, axis=-1) > .1)
    assert np.linalg.norm(np.diff(knee, axis=0), axis=-1).max() < .03


def test_interval_anchors_preserve_velocity_across_heel_toe_switch():
    motion = fixture(frames=13)
    motion.positions[:, :, 7, 0] += np.arange(13)[:, None] * .004
    motion.positions[:, :, 10, 0] += np.arange(13)[:, None] * .008
    intervals = np.zeros((12, 1, 4), dtype=bool)
    intervals[:6, 0, 0] = True
    intervals[6:, 0, 2] = True
    support = FootSupport(intervals, [7, 8, 10, 11], {})
    _, correction, active = _interval_anchors(motion, support, [0, 2], .15, 4)
    for interval in range(12):
        joint = 7 if interval < 6 else 10
        repaired_velocity = (motion.positions[interval + 1, 0, joint, [0, 2]]
                             - motion.positions[interval, 0, joint, [0, 2]]
                             + correction[interval + 1, 0, 0] - correction[interval, 0, 0])
        np.testing.assert_allclose(repaired_velocity, 0, atol=1e-9)
    # A zero correction at the center is still an active contact: root-follow
    # can require IK at that frame even though the anchor offset is zero.
    np.testing.assert_allclose(correction[6, 0, 0], 0, atol=1e-9)
    assert active[6, 0, 0]


def test_moving_anchor_bounds_displacement_even_when_speed_constraint_is_infeasible():
    # Short drift admits a slow path with the requested displacement bound.
    short = np.column_stack([np.linspace(0., .2, 31), np.zeros(31)])
    delta = _speed_limited_correction(short, .15, .004)
    assert np.linalg.norm(delta, axis=-1).max() <= .15000001
    assert np.linalg.norm(np.diff(short + delta, axis=0), axis=-1).max() < .00401
    # A long planted drift cannot be fixed inside a 15 cm endpoint bound.
    long = short * 10
    delta = _speed_limited_correction(long, .15, .004)
    assert np.linalg.norm(delta, axis=-1).max() <= .15000001
    assert np.linalg.norm(np.diff(long + delta, axis=0), axis=-1).max() > .004


def test_toe_pivot_excludes_ankle_but_does_not_hide_toe_sliding():
    motion = fixture()
    motion.positions[:, :, 7, 0] += np.arange(motion.frame_count)[:, None] * .01
    settings = load_config()["tests"]["foot_sliding"]
    support = estimate_support(motion, settings)
    assert not support.intervals[..., 0].any() and support.intervals[..., 2].all()
    assert foot_sliding.check(motion, settings).status == "PASS"
    motion.positions[:, :, 10, 0] += np.arange(motion.frame_count)[:, None] * .01
    assert foot_sliding.check(motion, settings).status == "FAIL"


def test_vertical_swing_is_excluded_without_using_horizontal_speed():
    motion = fixture()
    motion.positions[:, :, 10, 1] += (np.arange(motion.frame_count) % 2)[:, None] * .02
    support = estimate_support(motion, load_config()["tests"]["foot_sliding"])
    assert not support.intervals[..., 2].any()
    assert support.metrics["vertical_swing_excluded_count"] > 0


def test_missing_support_is_not_a_clean_foot_test():
    motion = replace(fixture(), contacts=np.zeros((24, 1, 4)))
    result = foot_sliding.check(motion, load_config()["tests"]["foot_sliding"])
    assert result.status == "WARN" and result.score == 0
    assert evaluate_gate(inspect(motion)).status == "FAIL"


def test_projection_fixes_lengths_and_respects_movement_bound():
    motion = fixture()
    motion.positions[:, :, 20, 0] += np.linspace(-.025, .025, 24)[:, None]
    repaired, detail = project_bone_lengths(motion)
    assert detail["applied"]
    np.testing.assert_allclose(lengths(repaired), np.broadcast_to(np.median(lengths(motion), axis=0), lengths(motion).shape), atol=1e-7)
    np.testing.assert_array_equal(repaired.positions[:, :, 0], motion.positions[:, :, 0])
    unchanged, rejected = project_bone_lengths(motion, max_correction_m=.001)
    assert unchanged is motion and rejected["applied"] is False


def test_intergen_foot_ik_preserves_lengths_and_reduces_drift():
    motion = fixture()
    motion.positions[..., 0] += np.arange(24)[:, None, None] * .007
    motion.root_translation = motion.positions[:, :, 0].copy()
    settings = load_config()["tests"]["foot_sliding"]
    before = foot_sliding.check(motion, settings)
    repaired, _, _ = repair_foot_sliding(motion, before.issues, root_follow=False)
    np.testing.assert_allclose(lengths(repaired), lengths(motion), atol=1e-7)
    assert foot_sliding.check(repaired, settings).score > before.score


def test_actor_separation_preserves_bones_midpoint_and_bound():
    motion = fixture(actors=2)
    motion.positions[:, 1, :, 0] += .08
    settings = load_config()["tests"]["collision"]
    assert collision.check(motion, settings).status == "FAIL"
    repaired, detail = separate_actors(motion, settings)
    assert collision.check(repaired, settings).status == "PASS"
    np.testing.assert_allclose(lengths(repaired), lengths(motion), atol=1e-7)
    np.testing.assert_allclose(repaired.positions.mean(axis=1), motion.positions.mean(axis=1), atol=1e-7)
    assert detail["max_actor_shift_m"] <= .15
    np.testing.assert_allclose(repaired.root_translation, repaired.positions[:, :, 0])


def test_acceptance_rejects_new_fail_even_within_score_drop_budget():
    motion = fixture()
    before = inspect(motion)
    before.overall_score = 98
    next(test for test in before.tests if test.test_name == "skeleton_integrity").score = 97
    tests = [QualityTest(test.test_name, test.status, test.score, issues=test.issues, metrics=test.metrics) for test in before.tests]
    next(test for test in tests if test.test_name == "skeleton_integrity").score += 1
    new_fail = next(test for test in tests if test.test_name == "collision")
    new_fail.status, new_fail.score = "FAIL", 98
    after = MotionQualityReport(before.overall_score + 1, tests)
    assessment = _assess("bone_length_projection", "skeleton_integrity", motion, motion, before, after, load_config())
    assert not assessment["applied"] and assessment["newly_failed_tests"] == ["collision"]
