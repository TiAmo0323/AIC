"""Locate the previously missing opposite-actor hand and torso checks."""
import numpy as np
from motionlint import MotionSequence
from motionlint.adapters.intergen_adapter import JOINT_NAMES
from motionlint.core.config import load_config
from motionlint.tests.collision import check


def pair():
    positions = np.zeros((10, 2, 22, 3))
    lookup = {name: index for index, name in enumerate(JOINT_NAMES)}
    for actor, x in enumerate((0, 3)):
        positions[:, actor] = [x, 1, 0]
        for name, y in (("Hips", 1), ("Neck", 1.5), ("Head", 1.8)):
            positions[:, actor, lookup[name]] = [x, y, 0]
        for side in ("Left", "Right"):
            positions[:, actor, lookup[side + "Hand"]] = [x + 1, 2.3, 0]
            positions[:, actor, lookup[side + "ForeArm"]] = [x + 1.2, 2.3, 0]
    return positions, lookup


def test_opposite_actor_hand_head_is_detected_and_old_policy_is_preserved():
    positions, lookup = pair()
    positions[4:7, 1, lookup["LeftHand"]] = [.02, 1.8, 0]
    motion = MotionSequence("intergen", 30, 10, 2, positions=positions, joint_names=JOINT_NAMES)
    settings = load_config()["tests"]["collision"]
    result = check(motion, settings)
    issues = [issue for issue in result.issues if issue.metric == "hand_head_distance_m" and issue.actor_id == 1]
    assert issues and issues[0].start_frame == 4 and issues[0].end_frame == 6
    assert issues[0].other_actor_id == 0 and issues[0].penetration_estimate_m > 0
    legacy = check(motion, {**settings, "extended_inter_actor_checks": False})
    assert not any(issue.metric == "hand_head_distance_m" and issue.actor_id == 1 for issue in legacy.issues)


def test_hand_torso_reports_both_actor_joints_and_clearance_deficit():
    positions, lookup = pair()
    positions[4:7, 1, lookup["LeftHand"]] = [.03, 1.3, 0]
    motion = MotionSequence("intergen", 30, 10, 2, positions=positions, joint_names=JOINT_NAMES)
    result = check(motion, load_config()["tests"]["collision"])
    issue = next(issue for issue in result.issues if issue.metric == "hand_torso_distance_m" and issue.actor_id == 1)
    assert issue.start_frame == 4 and issue.end_frame == 6
    assert issue.other_joint_ids == [lookup["Hips"], lookup["Neck"]]
    assert abs(issue.penetration_estimate_m - .09) < 1e-8
    assert issue.repairable is False
