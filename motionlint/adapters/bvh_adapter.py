"""BVH input via the MIT-licensed upc-pymotion library."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import numpy as np

from motionlint.core.motion_sequence import MotionSequence


def load_bvh(path: str | Path, *, source: str = "bvh", unit_scale: float = 1., up_axis: int = 1, joint_mapping: dict | None = None) -> MotionSequence:
    """Read one actor's BVH and compute global joint positions using FK."""
    try:
        from pymotion.io.bvh import BVH
        from pymotion.ops.skeleton import fk
        from pymotion.rotations import quat
    except ImportError as exc:
        raise ImportError("BVH adapter requires upc-pymotion==0.3.4") from exc

    path = Path(path).expanduser().resolve()
    if not np.isfinite(unit_scale) or unit_scale <= 0:
        raise ValueError("BVH unit_scale must be positive and finite")
    if up_axis not in (0, 1, 2):
        raise ValueError("BVH up_axis must be 0, 1 or 2")
    bvh = BVH()
    bvh.load(str(path))
    local_quaternions, local_positions, parents, offsets, _, _ = bvh.get_data()
    if not all(np.isfinite(value).all() for value in (local_quaternions, local_positions, offsets)):
        raise ValueError("BVH contains non-finite rotation, translation or offsets")
    world_positions, _ = fk(local_quaternions, local_positions[:, 0, :], offsets, parents)
    local_matrices = quat.to_matrix(local_quaternions)
    frame_time = float(bvh.data["frame_time"])
    if not np.isfinite(frame_time) or frame_time <= 0:
        raise ValueError(f"Invalid BVH frame_time: {frame_time}")
    fps = 1.0 / frame_time
    # Existing BVH writers store 1/30 as 0.033333; recover the intended FPS.
    if abs(fps - round(fps)) < 1e-3:
        fps = float(round(fps))
    frames, joints = local_quaternions.shape[:2]
    names = [str(name) for name in bvh.data["names"]]
    if joint_mapping:
        unknown = set(joint_mapping) - set(names)
        if unknown:
            raise ValueError(f"Joint mapping refers to missing BVH names: {sorted(unknown)}")
        if not all(isinstance(value, str) and value for value in joint_mapping.values()):
            raise ValueError("Joint mapping values must be non-empty canonical joint names")
        names = [joint_mapping.get(name, name) for name in names]
    aliases = {"LeftToes": "LeftToe", "RightToes": "RightToe", "Chest": "Spine1", "UpperChest": "Spine2"}
    names = [aliases.get(name, name) for name in names]
    if len(set(names)) != len(names):
        raise ValueError("Joint mapping creates duplicate canonical names")
    lookup = {name: index for index, name in enumerate(names)}
    foot_names = ("LeftFoot", "RightFoot", "LeftToe", "RightToe")
    feet = [lookup[name] for name in foot_names if name in lookup]
    # PyMotion uses root parent 0 for FK. Our shared skeleton contract uses -1.
    analysis_parents = np.asarray(parents).copy()
    analysis_parents[0] = -1

    return MotionSequence(
        source=source,
        fps=fps,
        frame_count=frames,
        actor_count=1,
        positions=world_positions[:, np.newaxis, :, :] * unit_scale,
        rotations_6d=local_matrices[..., :2, :].reshape(frames, 1, joints, 6),
        rotation_matrices=local_matrices[:, np.newaxis, :, :, :],
        root_translation=local_positions[:, np.newaxis, 0, :] * unit_scale,
        joint_names=names,
        skeleton_type="bvh",
        metadata={
            "source_path": str(path),
            "frame_time": frame_time,
            "parents": analysis_parents.tolist(),
            "offsets": (offsets * unit_scale).tolist(),
            "up_axis": up_axis,
            "unit_scale_to_metres": unit_scale,
            "unit_basis": "Explicit scale; default assumes repository exporter metres",
            "foot_joint_ids": feet,
            "left_foot_joint_ids": [lookup[name] for name in ("LeftFoot", "LeftToe") if name in lookup],
            "right_foot_joint_ids": [lookup[name] for name in ("RightFoot", "RightToe") if name in lookup],
            "geometry_source": "bvh_fk",
            "coordinate_system": "BVH coordinates as stored",
        },
    )


def load_bvh_pair(paths, *, unit_scale: float = 1., up_axis: int = 1, joint_mapping: dict | None = None) -> MotionSequence:
    actors = [load_bvh(path, unit_scale=unit_scale, up_axis=up_axis, joint_mapping=joint_mapping) for path in paths]
    if not actors:
        raise ValueError("At least one BVH file is required")
    first = actors[0]
    for actor in actors[1:]:
        if (actor.joint_names != first.joint_names or actor.frame_count != first.frame_count
                or not np.isclose(actor.fps, first.fps) or actor.metadata["parents"] != first.metadata["parents"]):
            raise ValueError("BVH actors need matching joints, hierarchy, FPS and frame counts")
    return replace(first, actor_count=len(actors),
                   positions=np.concatenate([actor.positions for actor in actors], axis=1),
                   rotations_6d=np.concatenate([actor.rotations_6d for actor in actors], axis=1),
                   rotation_matrices=np.concatenate([actor.rotation_matrices for actor in actors], axis=1),
                   root_translation=np.concatenate([actor.root_translation for actor in actors], axis=1),
                   metadata={**first.metadata, "source_paths": [actor.metadata["source_path"] for actor in actors],
                             "actor_offsets": [actor.metadata["offsets"] for actor in actors]})
