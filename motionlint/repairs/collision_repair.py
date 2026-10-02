"""Reuse InterGen's verified hand/head arm-chain correction."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from motionlint.core.legacy_arm_clearance import _correct_hand_head_collisions
from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.skeleton import SMPL_TO_BVH22
from motionlint.adapters.lodge_adapter import normalize_lodge_array
from motionlint.repairs.kinematics import align_rotation, smooth_envelope, two_bone_ik, unit, world_rotations


def repair_lodge_collisions(motion: MotionSequence, *, raw: np.ndarray | None, settings: dict,
                            max_wrist_shift_m: float = .05, blend_frames: int = 6):
    """Move a near-head wrist with bone-preserving arm IK and real rotations."""
    if motion.source != "lodge" or motion.rotation_matrices is None:
        raise ValueError("LODGE arm IK requires source rotations")
    if raw is None:
        source = motion.metadata.get("source_path")
        if not source:
            raise ValueError("LODGE arm IK requires raw motion or source_path")
        raw = np.load(source, allow_pickle=False)
    local = motion.rotation_matrices[:, 0].copy()
    world = world_rotations(local, motion.metadata["parents"])
    positions = motion.positions[:, 0]
    lookup = {name: index for index, name in enumerate(motion.joint_names)}
    modified = set()
    details = []
    for side in ("Left", "Right"):
        shoulder, elbow, wrist = [lookup[side + suffix] for suffix in ("Arm", "ForeArm", "Hand")]
        delta = positions[:, wrist] - positions[:, lookup["Head"]]
        distance = np.linalg.norm(delta, axis=-1)
        amount = np.maximum(0., float(settings["wrist_head_clearance_m"]) + .004 - distance)
        amount = np.minimum(smooth_envelope(amount, blend_frames), max_wrist_shift_m)
        selected = amount > 1e-8
        if not selected.any():
            continue
        target = positions[:, wrist] + unit(delta, np.array([1., 0, 0])) * amount[:, None]
        new_elbow, new_wrist = two_bone_ik(positions[:, shoulder], positions[:, elbow], positions[:, wrist], target)
        upper_world = align_rotation(positions[:, elbow] - positions[:, shoulder], new_elbow - positions[:, shoulder]) @ world[:, shoulder]
        lower_world = upper_world @ local[:, elbow]
        lower = np.einsum("tij,j->ti", lower_world, np.asarray(motion.metadata["offsets"])[wrist])
        lower_world = align_rotation(lower, new_wrist - new_elbow) @ lower_world
        parent = motion.metadata["parents"][shoulder]
        local[selected, shoulder] = (np.swapaxes(world[:, parent], -1, -2) @ upper_world)[selected]
        local[selected, elbow] = (np.swapaxes(upper_world, -1, -2) @ lower_world)[selected]
        local[selected, wrist] = (np.swapaxes(lower_world, -1, -2) @ world[:, wrist])[selected]
        modified.update((shoulder, elbow, wrist))
        details.append({"side": side, "modified_frames": int(selected.sum()),
                        "max_unreachable_target_error_m": float(np.linalg.norm(new_wrist[selected] - target[selected], axis=-1).max())})
    repaired_raw = np.asarray(raw).copy()
    start = 4 if raw.shape[1] in {139, 319} else 0
    for joint in modified:
        first = start + 3 + 6 * SMPL_TO_BVH22[joint]
        repaired_raw[:, first:first + 6] = local[:, joint, :2].reshape(-1, 6).astype(raw.dtype)
    repaired = normalize_lodge_array(repaired_raw, fps=motion.fps, source_path=motion.metadata.get("source_path"),
                                     model_path=motion.metadata.get("geometry_model_path"))
    wrists = [lookup[side + "Hand"] for side in ("Left", "Right")]
    shift = float(np.linalg.norm(repaired.positions[:, 0, wrists] - positions[:, wrists], axis=-1).max())
    max_joint = float(np.linalg.norm(repaired.positions - motion.positions, axis=-1).max())
    if shift > max_wrist_shift_m + 1e-6 or max_joint > .10:
        raise ValueError("Arm IK exceeds the wrist or joint movement bound")
    return repaired, repaired_raw, {"method": "bounded wrist clearance with bone-preserving arm IK",
        "max_wrist_shift_m": shift, "max_joint_shift_m": max_joint, "arms": details}


def repair_collisions(motion: MotionSequence) -> tuple[MotionSequence, dict]:
    if motion.source != "intergen" or motion.positions is None or motion.positions.shape[2] != 22:
        raise ValueError("Collision repair currently supports InterGen 22-joint trajectories")
    corrected = np.asarray(motion.positions, dtype=np.float64).copy()
    details = []
    for actor in range(motion.actor_count):
        corrected[:, actor], report = _correct_hand_head_collisions(
            corrected[:, actor],
            clearance_scale=2.0,
            minimum_clearance=0.15,
            forearm_clearance_scale=1.5,
            forearm_minimum_clearance=0.11,
            blend_window=7,
            elbow_max_correction=0.03,
            wrist_max_correction=0.05,
        )
        details.append({"actor_id": actor, **report})
    repaired = replace(motion, positions=corrected.astype(motion.positions.dtype, copy=False), metadata={**motion.metadata, "repair": "collision_repair"})
    return repaired, {"method": "existing InterGen hand/head correction", "actors": details}
