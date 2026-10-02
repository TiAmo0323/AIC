"""Repair tests require measured improvement and preserved source channels."""

from __future__ import annotations

import runpy

import numpy as np

from motionlint import MotionSequence
from motionlint.adapters.intergen_adapter import JOINT_NAMES, PARENTS
from motionlint.adapters.lodge_adapter import normalize_lodge_array
from motionlint.repairs.collision_repair import repair_collisions
from motionlint.repairs.foot_lock import repair_foot_sliding
from motionlint.repairs.seam_repair import repair_seams
from motionlint.tests import collision, foot_sliding, temporal_continuity


def test_seam_repair_reduces_detected_jump() -> None:
    raw = runpy.run_path("tests/test_lodge_motion_continuity.py")["synthetic_motion"]()
    motion = normalize_lodge_array(raw)
    settings = {"chunk_frames": 256, "root_step_m": 0.18, "angular_step_deg": 45}
    before = temporal_continuity.check(motion, settings)
    repaired, repaired_raw, detail = repair_seams(motion, raw=raw)
    after = temporal_continuity.check(repaired, settings)
    assert before.status == "FAIL" and after.status == "PASS"
    assert after.metrics["max_root_step_m"] < before.metrics["max_root_step_m"]
    assert np.array_equal(repaired_raw[:, :4], raw[:, :4])
    assert detail["boundaries"][0]["boundary_frame"] == 256


def test_foot_lock_reduces_single_contact_sliding() -> None:
    raw = np.zeros((18, 139), dtype=np.float32)
    raw[:, 0] = 1
    raw[:, 5] = 1.0
    raw[:, 4] = np.arange(18) * 0.02
    raw[:, 7:] = np.tile([1, 0, 0, 0, 1, 0], 22)
    motion = normalize_lodge_array(raw)
    settings = {"contact_height_m": 0.06, "horizontal_speed_m_s": 0.16}
    before = foot_sliding.check(motion, settings)
    repaired, repaired_raw, detail = repair_foot_sliding(motion, before.issues, raw=raw)
    after = foot_sliding.check(repaired, settings)
    assert before.metrics["sliding_frame_count"] > 0
    assert after.metrics["sliding_frame_count"] < before.metrics["sliding_frame_count"]
    assert detail["applied_joint_frames"] > 0
    assert np.array_equal(repaired_raw[:, :4], raw[:, :4])


def test_foot_lock_reduces_common_drift_with_both_feet_planted() -> None:
    raw = np.zeros((30, 139), dtype=np.float32)
    raw[:, :4] = 1
    raw[:, 5] = 1.0
    raw[:, 4] = np.arange(30) * 0.008
    raw[:, 7:] = np.tile([1, 0, 0, 0, 1, 0], 22)
    motion = normalize_lodge_array(raw)
    settings = {"contact_height_m": 0.06, "horizontal_speed_m_s": 0.16}
    before = foot_sliding.check(motion, settings)
    repaired, repaired_raw, detail = repair_foot_sliding(motion, before.issues, raw=raw)
    after = foot_sliding.check(repaired, settings)
    assert after.score > before.score
    assert detail["applied_joint_frames"] > 0
    assert np.array_equal(repaired_raw[:, :4], raw[:, :4])
    # IK can change hip/knee/ankle rotations; other joints stay untouched.
    changed_smpl_joints = {1, 2, 4, 5, 7, 8}
    untouched = [joint for joint in range(22) if joint not in changed_smpl_joints]
    np.testing.assert_array_equal(repaired_raw[:, 7:].reshape(30, 22, 6)[:, untouched], raw[:, 7:].reshape(30, 22, 6)[:, untouched])
    np.testing.assert_allclose(repaired.positions, normalize_lodge_array(repaired_raw).positions)


def test_existing_collision_repair_removes_mild_hand_head_overlap() -> None:
    positions = np.zeros((20, 1, 22, 3))
    positions[:, :, 12] = [0, 1.45, 0]
    positions[:, :, 15] = [0, 1.525, 0]
    positions[:, :, 16] = [-0.3, 1.35, 0]
    positions[:, :, 18] = [-0.3, 1.25, 0]
    positions[:, :, 20] = [-0.4, 1.2, 0]
    positions[8:11, :, 20] = [0.11, 1.525, 0]
    positions[:, :, 17] = [0.3, 1.35, 0]
    positions[:, :, 19] = [0.35, 1.25, 0]
    positions[:, :, 21] = [0.4, 1.2, 0]
    motion = MotionSequence("intergen", 30, 20, 1, positions=positions, joint_names=JOINT_NAMES, metadata={"parents": PARENTS})
    settings = {"wrist_head_clearance_m": 0.12, "forearm_head_clearance_m": 0.09, "head_head_clearance_m": 0.18, "torso_torso_clearance_m": 0.20}
    before = collision.check(motion, settings)
    repaired, detail = repair_collisions(motion)
    after = collision.check(repaired, settings)
    assert before.status == "FAIL" and after.status == "PASS"
    assert detail["actors"][0]["corrected_frame_count"] > 0
