"""Locate root and joint rotation jumps, including known chunk boundaries."""

from __future__ import annotations

import numpy as np

from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.result import MotionIssue, TestResult
from motionlint.tests.common import result, segments


def check(motion: MotionSequence, settings: dict) -> TestResult:
    name = "temporal_continuity"
    issues: list[MotionIssue] = []
    metrics: dict = {"chunk_frames": int(settings["chunk_frames"])}
    if motion.frame_count < 2:
        return TestResult(name, "WARN", 0, metrics={"reason": "Need at least two frames"})
    if motion.root_translation is None and motion.positions is None and motion.rotation_matrices is None:
        return TestResult(name, "WARN", 0, metrics={"reason": "No root or rotation data"})

    root = motion.root_translation
    if root is None and motion.positions is not None:
        root = motion.positions[:, :, 0, :]
    if root is not None:
        step = np.linalg.norm(np.diff(root, axis=0), axis=-1)
        finite_step = np.where(np.isfinite(step), step, np.inf)
        metrics["max_root_step_m"] = float(np.max(finite_step))
        metrics["max_root_velocity_m_s"] = float(np.max(finite_step) * motion.fps)
        threshold = float(settings["root_step_m"])
        for actor in range(motion.actor_count):
            for start, end in segments(finite_step[:, actor] > threshold):
                issues.append(MotionIssue(name, "high", start + 1, end + 1, "root_step_m", float(np.max(finite_step[start:end + 1, actor])), threshold, "Root trajectory jump", actor_id=actor, joint_ids=[0], repairable=motion.source == "lodge", recommended_repair="seam_repair" if motion.source == "lodge" else None))
        if len(root) >= 3:
            acceleration = np.linalg.norm(np.diff(root, n=2, axis=0), axis=-1) * motion.fps ** 2
            metrics["max_root_acceleration_m_s2"] = float(np.nanmax(acceleration))
    else:
        metrics["root_available"] = False

    if motion.rotation_matrices is not None:
        matrices = motion.rotation_matrices
        relative = np.matmul(matrices[1:], np.swapaxes(matrices[:-1], -1, -2))
        cosine = (np.trace(relative, axis1=-2, axis2=-1) - 1.0) / 2.0
        step_degrees = np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0)))
        metrics["max_angular_velocity_deg_s"] = float(np.nanmax(step_degrees) * motion.fps)
        metrics["max_angular_acceleration_deg_s2"] = float(np.nanmax(np.abs(np.diff(step_degrees, axis=0))) * motion.fps ** 2) if len(step_degrees) > 1 else 0.0
        threshold = float(settings["angular_step_deg"])
        for actor in range(motion.actor_count):
            for joint in range(step_degrees.shape[2]):
                for start, end in segments(step_degrees[:, actor, joint] > threshold):
                    issues.append(MotionIssue(name, "high", start + 1, end + 1, "angular_step_deg", float(np.max(step_degrees[start:end + 1, actor, joint])), threshold, "Joint rotation jump", actor_id=actor, joint_ids=[joint], repairable=motion.source == "lodge", recommended_repair="seam_repair" if motion.source == "lodge" else None))
    else:
        metrics["rotations_available"] = False

    chunk = int(settings["chunk_frames"])
    metrics["boundaries"] = [frame for frame in range(chunk, motion.frame_count, chunk)] if motion.source == "lodge" else []
    scope_count = motion.rotation_matrices.shape[2] if motion.rotation_matrices is not None else 1
    return result(name, issues, metrics, motion.frame_count, motion.actor_count, scope_count)
