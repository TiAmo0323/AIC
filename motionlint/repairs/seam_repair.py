"""Wrap the existing LODGE SLERP / Hermite seam repair without duplicating it."""

from __future__ import annotations

import numpy as np

from motionlint.adapters.lodge_adapter import normalize_lodge_array
from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.continuity import smooth_chunk_seams


def repair_seams(
    motion: MotionSequence,
    *,
    raw: np.ndarray | None = None,
    chunk_frames: int = 256,
    window_frames: int = 8,
    boundary_frames: list[int] | None = None,
    max_correction_m: float = .10,
    rotation_joint_ids: list[int] | None = None,
    repair_translation: bool = True,
) -> tuple[MotionSequence, np.ndarray, dict]:
    if motion.source != "lodge":
        raise ValueError("Seam repair currently requires LODGE raw motion")
    if raw is None:
        source_path = motion.metadata.get("source_path")
        if not source_path:
            raise ValueError("Seam repair requires raw motion or source_path")
        raw = np.load(source_path, allow_pickle=False)
    repaired_raw, details = smooth_chunk_seams(raw, chunk_frames=chunk_frames, window_frames=window_frames, boundary_frames=boundary_frames, rotation_joint_ids=rotation_joint_ids, repair_translation=repair_translation)
    details["movement_bound_m"] = max_correction_m
    repaired = normalize_lodge_array(repaired_raw, fps=motion.fps, source_path=motion.metadata.get("source_path"), model_path=motion.metadata.get("geometry_model_path"))
    repaired.metadata["repair"] = "seam_repair"
    return repaired, repaired_raw, details
