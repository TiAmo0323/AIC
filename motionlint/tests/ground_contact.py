"""Detect foot penetration and unsupported floating relative to a fitted floor."""

from __future__ import annotations

import numpy as np

from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.result import MotionIssue, TestResult
from motionlint.tests.common import result, segments
from motionlint.core.floor import floor_heights


def check(motion: MotionSequence, settings: dict) -> TestResult:
    name = "ground_contact"
    if motion.positions is None:
        return TestResult(name, "WARN", 0, metrics={"reason": "No global joint positions"})
    feet = list(motion.metadata.get("foot_joint_ids", []))
    if not feet:
        return TestResult(name, "WARN", 0, metrics={"reason": "No foot joint mapping"})
    up = int(motion.metadata.get("up_axis", 1))
    heights = motion.positions[:, :, feet, up]
    floor, floor_source = floor_heights(motion, heights, settings)
    penetration_limit = float(settings["penetration_m"])
    floating_limit = float(settings["floating_m"])
    penetration = heights < floor[np.newaxis, :, np.newaxis] - penetration_limit
    if motion.contacts is not None and motion.contacts.shape[2] == len(feet):
        floating = (motion.contacts > 0.5) & (heights > floor[np.newaxis, :, np.newaxis] + floating_limit)
        float_source = "lodge_contact_channels"
    else:
        # Without model contacts, test whether every foot leaves the fitted floor.
        floating_actor = np.min(heights, axis=2) > floor[np.newaxis, :] + floating_limit
        floating = np.repeat(floating_actor[:, :, np.newaxis], len(feet), axis=2)
        float_source = "all_feet_above_floor"
        if not settings.get("flag_unconfirmed_airborne", True):
            # Both feet in the air may be a valid jump. Retain the observation
            # without claiming a contact violation when no contact is supplied.
            floating = np.zeros_like(floating, dtype=bool)
            float_source = "airborne_observation_only_without_contact_labels"
    issues: list[MotionIssue] = []
    for actor in range(motion.actor_count):
        for local_joint, joint in enumerate(feet):
            for metric, mask, threshold, severity, message in (
                ("ground_penetration_m", penetration[:, actor, local_joint], penetration_limit, "high", "Foot penetrates the fitted floor"),
                ("floating_height_m", floating[:, actor, local_joint], floating_limit, "medium", "Contact foot floats above the fitted floor"),
            ):
                for start, end in segments(mask):
                    difference = np.abs(heights[start:end + 1, actor, local_joint] - floor[actor])
                    issues.append(MotionIssue(name, severity, start, end, metric, float(np.max(difference)), threshold, message, actor_id=actor, joint_ids=[joint]))
    metrics = {
        "estimated_floor_height_m": floor.tolist(),
        "floor_source": floor_source,
        "airborne_actor_frames": int(np.count_nonzero(np.min(heights, axis=2) > floor[None] + floating_limit)),
        "floating_source": float_source,
        "penetration_frame_count": int(np.count_nonzero(penetration)),
        "floating_frame_count": int(np.count_nonzero(floating)),
    }
    return result(name, issues, metrics, motion.frame_count, motion.actor_count, len(feet))
