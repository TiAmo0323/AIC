"""Measure third-order position changes and second-order angular changes."""

from __future__ import annotations

import numpy as np

from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.result import MotionIssue, TestResult
from motionlint.tests.common import result, segments


def check(motion: MotionSequence, settings: dict) -> TestResult:
    name = "motion_jerk"
    issues: list[MotionIssue] = []
    metrics: dict = {}
    if not ((motion.positions is not None and motion.frame_count >= 4) or (motion.rotation_matrices is not None and motion.frame_count >= 3)):
        return TestResult(name, "WARN", 0, metrics={"reason": "Need four position frames or three rotation frames"})
    if motion.positions is not None and motion.frame_count >= 4:
        jerk = np.linalg.norm(np.diff(motion.positions, n=3, axis=0), axis=-1) * motion.fps ** 3
        threshold = float(settings["joint_jerk_m_s3"])
        metrics["mean_joint_jerk_m_s3"] = float(np.nanmean(jerk))
        metrics["max_joint_jerk_m_s3"] = float(np.nanmax(jerk))
        for actor in range(motion.actor_count):
            for joint in range(jerk.shape[2]):
                for start, end in segments(jerk[:, actor, joint] > threshold):
                    issues.append(MotionIssue(name, "medium", start + 3, end + 3, "joint_jerk_m_s3", float(np.max(jerk[start:end + 1, actor, joint])), threshold, "Joint position jerk", actor_id=actor, joint_ids=[joint]))
    if motion.rotation_matrices is not None and motion.frame_count >= 3:
        matrices = motion.rotation_matrices
        relative = np.matmul(matrices[1:], np.swapaxes(matrices[:-1], -1, -2))
        step = np.degrees(np.arccos(np.clip((np.trace(relative, axis1=-2, axis2=-1) - 1) / 2, -1, 1)))
        acceleration = np.abs(np.diff(step, axis=0)) * motion.fps ** 2
        threshold = float(settings["angular_acceleration_deg_s2"])
        metrics["max_angular_acceleration_deg_s2"] = float(np.nanmax(acceleration))
        for actor in range(motion.actor_count):
            for joint in range(acceleration.shape[2]):
                for start, end in segments(acceleration[:, actor, joint] > threshold):
                    issues.append(MotionIssue(name, "medium", start + 2, end + 2, "angular_acceleration_deg_s2", float(np.max(acceleration[start:end + 1, actor, joint])), threshold, "Joint rotation acceleration spike", actor_id=actor, joint_ids=[joint]))
    if not metrics:
        return TestResult(name, "WARN", 0, metrics={"reason": "Need at least three rotations or four position frames"})
    scope_count = motion.positions.shape[2] if motion.positions is not None else motion.rotation_matrices.shape[2]
    return result(name, issues, metrics, motion.frame_count, motion.actor_count, scope_count)
