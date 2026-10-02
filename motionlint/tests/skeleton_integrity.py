"""Detect invalid positions, changing bone lengths, and collapsed joints."""

from __future__ import annotations

import numpy as np

from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.result import MotionIssue, TestResult
from motionlint.tests.common import result, segments


def check(motion: MotionSequence, settings: dict) -> TestResult:
    name = "skeleton_integrity"
    issues: list[MotionIssue] = []
    if motion.positions is None:
        return TestResult(name, "WARN", 0, metrics={"reason": "No global joint positions"})
    positions = motion.positions
    parents = motion.metadata.get("parents")
    if parents is None or len(parents) != positions.shape[2]:
        return TestResult(name, "WARN", 0, metrics={"reason": "No compatible skeleton parent mapping"})

    nonfinite = ~np.isfinite(positions).all(axis=-1)
    for actor in range(motion.actor_count):
        for joint in range(positions.shape[2]):
            for start, end in segments(nonfinite[:, actor, joint]):
                issues.append(MotionIssue(name, "critical", start, end, "nonfinite_position", 1.0, 0.0, "Joint has NaN or Inf", actor_id=actor, joint_ids=[joint]))

    variation_limit = float(settings["bone_length_variation_ratio"])
    collapse_limit = float(settings["joint_collapse_m"])
    max_variation = 0.0
    for joint, parent in enumerate(parents):
        if parent < 0:
            continue
        lengths = np.linalg.norm(positions[:, :, joint] - positions[:, :, parent], axis=-1)
        for actor in range(motion.actor_count):
            finite = lengths[:, actor][np.isfinite(lengths[:, actor])]
            if not len(finite):
                continue
            median = float(np.median(finite))
            if median > collapse_limit:
                relative = np.abs(lengths[:, actor] - median) / median
                max_variation = max(max_variation, float(np.nanmax(relative)))
                for start, end in segments(relative > variation_limit):
                    issues.append(MotionIssue(name, "high", start, end, "bone_length_variation_ratio", float(np.nanmax(relative[start:end + 1])), variation_limit, "Bone length changed", actor_id=actor, joint_ids=[parent, joint], repairable=motion.source == "intergen", recommended_repair="bone_length_projection" if motion.source == "intergen" else None))
            else:
                for start, end in segments(lengths[:, actor] < collapse_limit):
                    issues.append(MotionIssue(name, "high", start, end, "joint_collapse_m", float(np.nanmin(lengths[start:end + 1, actor])), collapse_limit, "Joint is collapsed onto its parent", actor_id=actor, joint_ids=[parent, joint]))

    metrics = {"nonfinite_joint_frames": int(np.count_nonzero(nonfinite)), "max_bone_length_variation_ratio": max_variation}
    return result(name, issues, metrics, motion.frame_count, motion.actor_count, positions.shape[2])
