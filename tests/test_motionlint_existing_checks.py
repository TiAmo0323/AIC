"""Synthetic defects must be located by the first MotionLint checks."""

from __future__ import annotations

import numpy as np

from motionlint import MotionSequence
from motionlint.adapters.intergen_adapter import JOINT_NAMES, PARENTS
from motionlint.tests import collision, motion_jerk, skeleton_integrity, temporal_continuity
from motionlint.pipeline.inspector import inspect


def _motion(positions: np.ndarray) -> MotionSequence:
    frames, actors = positions.shape[:2]
    return MotionSequence(
        source="intergen", fps=30, frame_count=frames, actor_count=actors,
        positions=positions, root_translation=positions[:, :, 0].copy(),
        joint_names=JOINT_NAMES.copy(), metadata={"parents": PARENTS.copy()},
    )


def test_temporal_jump_is_located() -> None:
    positions = np.zeros((130, 1, 22, 3))
    positions[65:, :, :, 0] = 1.0
    report = temporal_continuity.check(_motion(positions), {"chunk_frames": 64, "root_step_m": 0.18, "angular_step_deg": 65})
    assert report.status == "FAIL"
    assert any(issue.start_frame == 65 and issue.metric == "root_step_m" for issue in report.issues)


def test_bone_length_change_is_located() -> None:
    positions = np.zeros((12, 1, 22, 3))
    positions[:, :, 1, 0] = 0.4
    positions[6, :, 1, 0] = 1.4
    report = skeleton_integrity.check(_motion(positions), {"bone_length_variation_ratio": 0.12, "joint_collapse_m": 0.015})
    assert report.status == "FAIL"
    assert any(issue.start_frame == 6 and issue.joint_ids == [0, 1] for issue in report.issues)


def test_hand_head_collision_is_located() -> None:
    positions = np.zeros((10, 1, 22, 3))
    positions[:, :, 15, :] = [0, 1.5, 0]
    positions[:, :, 20, :] = [1, 1.5, 0]
    positions[:, :, 18, :] = [1, 1.2, 0]
    positions[:, :, 21, :] = [-1, 1.5, 0]
    positions[:, :, 19, :] = [-1, 1.2, 0]
    positions[4:7, :, 20, :] = [0.02, 1.5, 0]
    report = collision.check(_motion(positions), {
        "wrist_head_clearance_m": 0.12, "forearm_head_clearance_m": 0.09,
        "head_head_clearance_m": 0.18, "torso_torso_clearance_m": 0.20,
    })
    assert report.status == "FAIL"
    assert any(issue.start_frame == 4 and issue.end_frame == 6 for issue in report.issues)


def test_position_jerk_and_six_test_report() -> None:
    positions = np.zeros((16, 1, 22, 3))
    positions[8, 0, 1, 0] = 0.5
    motion = _motion(positions)
    jerk = motion_jerk.check(motion, {"joint_jerk_m_s3": 450, "angular_acceleration_deg_s2": 18000})
    assert jerk.status == "WARN"
    assert any(issue.joint_ids == [1] for issue in jerk.issues)
    report = inspect(motion)
    assert len(report.tests) == 6
    assert report.overall_score < 100
    assert report.issue_count > 0
