"""Normalize raw InterGen joint trajectories without changing the generator."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence

import numpy as np

from motionlint.core.motion_sequence import MotionSequence


JOINT_NAMES = [
    "Hips", "LeftUpLeg", "RightUpLeg", "Spine", "LeftLeg", "RightLeg",
    "Spine1", "LeftFoot", "RightFoot", "Spine2", "LeftToe", "RightToe",
    "Neck", "LeftShoulder", "RightShoulder", "Head", "LeftArm", "RightArm",
    "LeftForeArm", "RightForeArm", "LeftHand", "RightHand",
]
PARENTS = [-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19]


def load_intergen_joints(paths: str | Path | Sequence[str | Path], *, fps: float = 30) -> MotionSequence:
    if isinstance(paths, (str, Path)):
        paths = [paths]
    resolved = [Path(path).expanduser().resolve() for path in paths]
    if not resolved:
        raise ValueError("At least one InterGen joints22 NPY is required")
    actors = [np.load(path, allow_pickle=False) for path in resolved]
    for actor in actors:
        if actor.ndim != 3 or actor.shape[1:] != (22, 3):
            raise ValueError(f"InterGen joints must have shape (T, 22, 3); got {actor.shape}")
    if len({len(actor) for actor in actors}) != 1:
        raise ValueError("InterGen actors must have the same frame count")
    positions = np.stack(actors, axis=1)
    return MotionSequence(
        source="intergen",
        fps=fps,
        frame_count=len(positions),
        actor_count=len(actors),
        positions=positions,
        root_translation=positions[:, :, 0, :].copy(),
        joint_names=JOINT_NAMES.copy(),
        skeleton_type="humanml3d_22",
        metadata={
            "source_paths": [str(path) for path in resolved],
            "parents": PARENTS.copy(),
            "up_axis": 1,
            "foot_joint_ids": [7, 8, 10, 11],
            "left_foot_joint_ids": [7, 10],
            "right_foot_joint_ids": [8, 11],
        },
    )
