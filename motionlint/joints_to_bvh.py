"""Fit positions to a fixed-length BVH using continuous minimum-twist frames.

Positions do not identify axial twist or leaf rotations. Branch rotations use
their visible child directions; single-child rotations transport the previous
frame's local orientation. The root receives at most 1 cm of vertical adjustment
to retain the supplied lowest foot height after fitting; horizontal motion stays
unchanged. This does not recover unobserved axial twist.
"""
from pathlib import Path

import numpy as np

from LODGE_api.lodge2bvh import BVH_OFFSETS, BVH_PARENTS, SMPL_TO_BVH22, matrix_to_zyx_euler_degrees, write_bvh
from motionlint.adapters.bvh_adapter import load_bvh
from motionlint.cli.main import _write_json
from motionlint.repairs.kinematics import align_rotation, unit


def fit_positions(joints: np.ndarray):
    joints = np.asarray(joints, dtype=np.float64)
    if joints.ndim != 3 or joints.shape[1:] != (22, 3) or len(joints) < 2 or not np.isfinite(joints).all():
        raise ValueError("Expected at least two finite (22, 3) joint frames")
    target = joints[:, SMPL_TO_BVH22]
    offsets = BVH_OFFSETS.copy()
    offsets[0] = 0
    for joint, parent in enumerate(BVH_PARENTS):
        if parent >= 0:
            length = np.median(np.linalg.norm(target[:, joint] - target[:, parent], axis=-1))
            if length <= 1e-6:
                raise ValueError(f"Collapsed bone at BVH joint {joint}")
            offsets[joint] = unit(offsets[joint]) * length
    children = [np.flatnonzero(BVH_PARENTS == joint) for joint in range(22)]
    # Match each rigid branch's average shape as well as its bone lengths.
    # Otherwise a fixed hip/shoulder opening angle creates persistent endpoint
    # errors even with an optimal rotation. Keep the template as the initial
    # orientation and estimate only shape, using all frames equally.
    for joint, child_ids in enumerate(children):
        if len(child_ids) < 2:
            continue
        desired = unit(target[:, child_ids] - target[:, joint, None])
        lengths = np.linalg.norm(offsets[child_ids], axis=-1)
        for _ in range(8):
            rest = unit(offsets[child_ids])
            u, _, vt = np.linalg.svd(np.einsum("tci,cj->tij", desired, rest))
            signs = np.broadcast_to(np.eye(3), (len(target), 3, 3)).copy()
            signs[:, -1, -1] = np.linalg.det(u @ vt)
            rotations = u @ signs @ vt
            local_directions = np.einsum("tji,tcj->tci", rotations, desired)
            offsets[child_ids] = unit(local_directions.mean(axis=0)) * lengths[:, None]
    local = np.zeros((len(target), 22, 3, 3))
    world = np.zeros_like(local)
    fitted = np.zeros_like(target)
    fitted[:, 0] = target[:, 0]
    for frame in range(len(target)):
        for joint, parent in enumerate(BVH_PARENTS):
            parent_world = world[frame, parent] if parent >= 0 else np.eye(3)
            child_ids = children[joint]
            if len(child_ids) >= 2:
                rest = unit(offsets[child_ids])
                desired = unit(target[frame, child_ids] - target[frame, joint])
                u, _, vt = np.linalg.svd(desired.T @ rest)
                correction = np.eye(3)
                correction[-1, -1] = np.linalg.det(u @ vt)
                rotation = u @ correction @ vt
            elif len(child_ids) == 1:
                child = child_ids[0]
                previous = parent_world @ local[frame - 1, joint] if frame else parent_world
                direction = target[frame, child] - target[frame, joint]
                if np.linalg.norm(direction) <= 1e-8:
                    rotation = previous
                else:
                    rotation = align_rotation(previous @ offsets[child], direction) @ previous
            else:
                rotation = parent_world
            world[frame, joint] = rotation
            local[frame, joint] = parent_world.T @ rotation
            if parent >= 0:
                fitted[frame, joint] = fitted[frame, parent] + parent_world @ offsets[joint]
    # Restore the original lowest foot height lost through rigid-branch fitting.
    # This follows the supplied motion, not a guessed floor or contact label.
    # Cap the vertical root adjustment at 1 cm and expose it in fidelity data.
    feet = [3, 4, 7, 8]
    shift = np.min(target[:, feet, 1], axis=1) - np.min(fitted[:, feet, 1], axis=1)
    shift = np.clip(shift, -.01, .01)
    fitted[:, :, 1] += shift[:, None]
    return target, fitted, offsets, local


def fidelity(target: np.ndarray, actual: np.ndarray) -> dict:
    error = np.linalg.norm(target - actual, axis=-1)
    return {"position_error_mean_m": float(error.mean()), "position_error_p95_m": float(np.quantile(error, .95)),
            "position_error_max_m": float(error.max()), "root_error_max_m": float(error[:, 0].max())}


def convert_continuous_joints(input_path: Path, output_path: Path, *, fps: int = 30) -> dict:
    if not isinstance(fps, int) or isinstance(fps, bool) or fps <= 0:
        raise ValueError("FPS must be a positive integer")
    target, fitted, offsets, local = fit_positions(np.load(input_path, allow_pickle=False))
    euler = matrix_to_zyx_euler_degrees(local)
    write_bvh(output_path, fitted[:, 0], euler, fps, offsets=offsets)
    decoded = load_bvh(output_path)
    # The independent BVH reader must reproduce FK, not just the fitter's array.
    discrepancy = float(np.max(np.abs(decoded.positions[:, 0] - fitted)))
    if discrepancy > 1e-4:
        raise RuntimeError(f"BVH round-trip mismatch: {discrepancy:.6f} m")
    report = {"converter": "motionlint_continuous_frames_v1", "source": str(input_path), "output": str(output_path),
              "fps": fps, "frames": len(target), "offsets": offsets.tolist(),
              "fidelity": fidelity(target, decoded.positions[:, 0]), "round_trip_max_coordinate_error_m": discrepancy,
              "root_vertical_adjustment_max_m": float(np.max(np.abs(fitted[:, 0, 1] - target[:, 0, 1]))),
              "root_vertical_adjustment_limit_m": .01,
              "limits": "Single-child axial twist is underdetermined; minimum-change local transport is used. Multi-child shape/directions use a rigid least-squares fit. Input bone-length variation is approximated by its median. Root Y is adjusted by at most 1 cm to retain source foot height; root X/Z are unchanged."}
    _write_json(output_path.with_suffix(".conversion.json"), report)
    return report
