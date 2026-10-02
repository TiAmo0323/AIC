"""Read evaluated Blender bone heads exported by export_blender_motionlint.py."""
from pathlib import Path
import json

import numpy as np

from motionlint.core.motion_sequence import MotionSequence


def load_character(path: str | Path) -> MotionSequence:
    path = Path(path).resolve()
    info = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    with np.load(path, allow_pickle=False) as data:
        positions = data["positions"]
        world = data["world_rotation_matrices"]
        names, parents = data["joint_names"].tolist(), data["parents"].tolist()
    if len(parents) != len(names) or world.shape != positions.shape[:-1] + (3, 3):
        raise ValueError("Character export needs matching bones and world rotations")
    lookup = {name: index for index, name in enumerate(names)}
    feet = ("LeftFoot", "RightFoot", "LeftToe", "RightToe")
    if not all(name in lookup for name in ("Hips", *feet)):
        raise ValueError("Character export is missing required canonical hip/foot names")
    local = world.copy()
    for joint, parent in enumerate(parents):
        if parent >= 0:
            local[:, :, joint] = np.swapaxes(world[:, :, parent], -1, -2) @ world[:, :, joint]
    return MotionSequence("character", float(info["fps"]), len(positions), positions.shape[1], positions=positions,
        rotation_matrices=local, root_translation=positions[:, :, lookup["Hips"]], joint_names=names,
        skeleton_type="evaluated_character", metadata={**info, "source_path": str(path), "parents": parents,
            "up_axis": 1, "unit_scale_to_metres": 1., "foot_joint_ids": [lookup[name] for name in feet],
            "left_foot_joint_ids": [lookup["LeftFoot"], lookup["LeftToe"]],
            "right_foot_joint_ids": [lookup["RightFoot"], lookup["RightToe"]]})
