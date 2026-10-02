"""Contact-aware horizontal foot velocity check."""

from __future__ import annotations

import numpy as np

from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.foot_support import estimate_support
from motionlint.core.result import MotionIssue, TestResult
from motionlint.tests.common import result, segments


def check(motion: MotionSequence, settings: dict) -> TestResult:
    name = "foot_sliding"
    if motion.positions is None or motion.frame_count < 2:
        return TestResult(name, "WARN", 0, metrics={"reason": "Need at least two frames with global positions"})
    feet = list(motion.metadata.get("foot_joint_ids", []))
    if not feet:
        return TestResult(name, "WARN", 0, metrics={"reason": "No foot joint mapping"})
    up = int(motion.metadata.get("up_axis", 1))
    horizontal = [axis for axis in range(3) if axis != up]
    foot_positions = motion.positions[:, :, feet, :]
    speed = np.linalg.norm(np.diff(foot_positions[..., horizontal], axis=0), axis=-1) * motion.fps
    estimated = estimate_support(motion, settings)
    support = estimated.intervals
    if not np.any(support):
        return TestResult(name, "WARN", 0, metrics={**estimated.metrics, "reason": "No credible support intervals; foot sliding could not be evaluated"})
    threshold = float(settings["horizontal_speed_m_s"])
    sliding = (speed > threshold) & support
    issues: list[MotionIssue] = []
    for actor in range(motion.actor_count):
        for local_joint, joint in enumerate(feet):
            for start, end in segments(sliding[:, actor, local_joint]):
                issues.append(MotionIssue(name, "high", start + 1, end + 1, "horizontal_speed_m_s", float(np.max(speed[start:end + 1, actor, local_joint])), threshold, "Foot slides during contact", actor_id=actor, joint_ids=[joint], repairable=True, recommended_repair="foot_lock"))
    contact_speeds = speed[support]
    sliding_speeds = speed[sliding]
    metrics = {
        **estimated.metrics,
        "sliding_frame_ratio": float(np.count_nonzero(sliding) / max(1, np.count_nonzero(support))),
        "mean_sliding_velocity_m_s": float(np.mean(sliding_speeds)) if len(sliding_speeds) else 0.0,
        "max_sliding_velocity_m_s": float(np.max(sliding_speeds)) if len(sliding_speeds) else 0.0,
        "mean_contact_velocity_m_s": float(np.mean(contact_speeds)) if len(contact_speeds) else 0.0,
        "sliding_frame_count": int(np.count_nonzero(sliding)),
    }
    return result(name, issues, metrics, motion.frame_count, motion.actor_count, len(feet))
