"""LODGE 分块动作的连续性后处理：平滑拼接处旋转和根轨迹，同时保持帧数不变。"""

from __future__ import annotations

import math
from typing import Dict, Tuple

import numpy as np


SUPPORTED_WITH_CONTACTS = {139, 319}
SUPPORTED_WITHOUT_CONTACTS = {135, 315}


def rotation_6d_to_matrix(rot6d: np.ndarray) -> np.ndarray:
    """Match PyTorch3D: the two 3D vectors become the first two matrix rows."""
    a1 = rot6d[..., 0:3]
    a2 = rot6d[..., 3:6]
    b1 = _normalize(a1)
    b2 = _normalize(a2 - np.sum(b1 * a2, axis=-1, keepdims=True) * b1)
    b3 = np.cross(b1, b2)
    return np.stack((b1, b2, b3), axis=-2)


def matrix_to_rotation_6d(matrix: np.ndarray) -> np.ndarray:
    return matrix[..., :2, :].reshape(matrix.shape[:-2] + (6,))


def _normalize(values: np.ndarray) -> np.ndarray:
    return values / np.maximum(np.linalg.norm(values, axis=-1, keepdims=True), 1e-12)


def _matrix_to_quaternion(matrix: np.ndarray) -> np.ndarray:
    """Convert rotation matrices to normalized WXYZ quaternions."""
    flat = np.asarray(matrix, dtype=np.float64).reshape(-1, 3, 3)
    output = np.empty((len(flat), 4), dtype=np.float64)
    for index, item in enumerate(flat):
        trace = float(np.trace(item))
        if trace > 0.0:
            scale = math.sqrt(trace + 1.0) * 2.0
            quat = np.array([
                0.25 * scale,
                (item[2, 1] - item[1, 2]) / scale,
                (item[0, 2] - item[2, 0]) / scale,
                (item[1, 0] - item[0, 1]) / scale,
            ])
        else:
            axis = int(np.argmax(np.diag(item)))
            if axis == 0:
                scale = math.sqrt(max(0.0, 1.0 + item[0, 0] - item[1, 1] - item[2, 2])) * 2.0
                quat = np.array([
                    (item[2, 1] - item[1, 2]) / max(scale, 1e-12),
                    0.25 * scale,
                    (item[0, 1] + item[1, 0]) / max(scale, 1e-12),
                    (item[0, 2] + item[2, 0]) / max(scale, 1e-12),
                ])
            elif axis == 1:
                scale = math.sqrt(max(0.0, 1.0 + item[1, 1] - item[0, 0] - item[2, 2])) * 2.0
                quat = np.array([
                    (item[0, 2] - item[2, 0]) / max(scale, 1e-12),
                    (item[0, 1] + item[1, 0]) / max(scale, 1e-12),
                    0.25 * scale,
                    (item[1, 2] + item[2, 1]) / max(scale, 1e-12),
                ])
            else:
                scale = math.sqrt(max(0.0, 1.0 + item[2, 2] - item[0, 0] - item[1, 1])) * 2.0
                quat = np.array([
                    (item[1, 0] - item[0, 1]) / max(scale, 1e-12),
                    (item[0, 2] + item[2, 0]) / max(scale, 1e-12),
                    (item[1, 2] + item[2, 1]) / max(scale, 1e-12),
                    0.25 * scale,
                ])
        output[index] = quat / max(np.linalg.norm(quat), 1e-12)
    return output.reshape(matrix.shape[:-2] + (4,))


def _quaternion_to_matrix(quaternion: np.ndarray) -> np.ndarray:
    q = _normalize(np.asarray(quaternion, dtype=np.float64))
    w, x, y, z = (q[..., index] for index in range(4))
    return np.stack(
        (
            1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
            2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
            2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y),
        ),
        axis=-1,
    ).reshape(q.shape[:-1] + (3, 3))


def _slerp(start: np.ndarray, end: np.ndarray, amount) -> np.ndarray:
    start = _normalize(start)
    end = _normalize(end)
    dot = np.sum(start * end, axis=-1, keepdims=True)
    end = np.where(dot < 0.0, -end, end)
    dot = np.clip(np.abs(dot), 0.0, 1.0)
    amount = np.asarray(amount, dtype=np.float64)
    while amount.ndim < start.ndim:
        amount = np.expand_dims(amount, axis=-1)
    angle = np.arccos(dot)
    sin_angle = np.sin(angle)
    linear = _normalize((1.0 - amount) * start + amount * end)
    spherical = (
        np.sin((1.0 - amount) * angle) / np.maximum(sin_angle, 1e-12) * start
        + np.sin(amount * angle) / np.maximum(sin_angle, 1e-12) * end
    )
    return _normalize(np.where(sin_angle < 1e-6, linear, spherical))


def _rotation_step_degrees(quaternions: np.ndarray) -> np.ndarray:
    dot = np.abs(np.sum(quaternions[:-1] * quaternions[1:], axis=-1))
    return np.degrees(2.0 * np.arccos(np.clip(dot, 0.0, 1.0)))


def _layout(feature_count: int) -> Tuple[int, int, int]:
    if feature_count in SUPPORTED_WITH_CONTACTS:
        rotation_start = 7
        contact_count = 4
    elif feature_count in SUPPORTED_WITHOUT_CONTACTS:
        rotation_start = 3
        contact_count = 0
    else:
        raise ValueError(f"Unsupported LODGE motion feature count: {feature_count}")
    joint_count = (feature_count - rotation_start) // 6
    return contact_count, rotation_start - 3, joint_count


def smooth_chunk_seams(
    motion: np.ndarray,
    chunk_frames: int = 256,
    window_frames: int = 8,
) -> Tuple[np.ndarray, Dict[str, object]]:
    """在固定分块边界用 SLERP/Hermite 平滑过渡，不改变帧数或 contact 值。"""
    original = np.asarray(motion)
    if original.ndim != 2:
        raise ValueError(f"Expected a 2D motion array, got shape={original.shape}")
    if chunk_frames < 2:
        raise ValueError("chunk_frames must be at least 2")
    if window_frames < 2 or window_frames * 2 >= chunk_frames:
        raise ValueError("window_frames must be >=2 and less than half chunk_frames")

    if len(original) <= chunk_frames:
        return original.copy(), {
            "enabled": True,
            "method": "raised-cosine quaternion SLERP and cubic-Hermite root bridge",
            "frame_count": int(len(original)),
            "feature_count": int(original.shape[1]),
            "joint_count": 0,
            "chunk_frames": int(chunk_frames),
            "window_frames": int(window_frames),
            "boundaries": [],
            "contact_channels_preserved": True,
            "max_root_displacement": 0.0,
            "max_joint_rotation_change_degrees": 0.0,
        }

    contact_count, translation_start, joint_count = _layout(original.shape[1])
    rotation_start = translation_start + 3
    result = original.astype(np.float64, copy=True)
    positions = result[:, translation_start:rotation_start]
    matrices = rotation_6d_to_matrix(
        result[:, rotation_start:].reshape(len(result), joint_count, 6)
    )
    quaternions = _matrix_to_quaternion(matrices)
    input_quaternions = quaternions.copy()
    input_positions = positions.copy()
    contacts_before = result[:, :contact_count].copy() if contact_count else None
    details = []
    modified_frames = np.zeros(len(result), dtype=bool)

    for boundary in range(chunk_frames, len(result), chunk_frames):
        start = boundary - window_frames
        end = boundary + window_frames - 1
        if start < 1 or end + 1 >= len(result):
            continue
        span = end - start
        u = np.linspace(0.0, 1.0, span + 1)
        blend = np.sin(np.pi * u) ** 2

        q_start = quaternions[start]
        q_end = quaternions[end]
        bridge = np.stack([_slerp(q_start, q_end, value) for value in u])
        quaternions[start:end + 1] = _slerp(
            quaternions[start:end + 1], bridge, blend[:, None]
        )

        p_start = positions[start].copy()
        p_end = positions[end].copy()
        tangent_start = positions[start] - positions[start - 1]
        tangent_end = positions[end + 1] - positions[end]
        u_column = u[:, None]
        h00 = 2 * u_column ** 3 - 3 * u_column ** 2 + 1
        h10 = u_column ** 3 - 2 * u_column ** 2 + u_column
        h01 = -2 * u_column ** 3 + 3 * u_column ** 2
        h11 = u_column ** 3 - u_column ** 2
        bridge_position = (
            h00 * p_start
            + h10 * span * tangent_start
            + h01 * p_end
            + h11 * span * tangent_end
        )
        positions[start:end + 1] = (
            (1.0 - blend[:, None]) * positions[start:end + 1]
            + blend[:, None] * bridge_position
        )
        modified_frames[start:end + 1] = True

        before_step = _rotation_step_degrees(input_quaternions)
        after_step = _rotation_step_degrees(quaternions)
        before_accel = np.abs(np.diff(before_step, axis=0))
        after_accel = np.abs(np.diff(after_step, axis=0))
        seam_accel_index = boundary - 2
        details.append({
            "boundary_frame": boundary,
            "window_start": start,
            "window_end": end,
            "max_joint_angular_acceleration_before": float(np.max(before_accel[seam_accel_index])),
            "max_joint_angular_acceleration_after": float(np.max(after_accel[seam_accel_index])),
        })

    result[:, translation_start:rotation_start] = positions
    converted_rotations = matrix_to_rotation_6d(
        _quaternion_to_matrix(quaternions)
    ).reshape(len(result), -1)
    result[modified_frames, rotation_start:] = converted_rotations[modified_frames]
    if contacts_before is not None:
        result[:, :contact_count] = contacts_before

    changed_dot = np.abs(np.sum(input_quaternions * quaternions, axis=-1))
    rotation_change = np.degrees(2.0 * np.arccos(np.clip(changed_dot, 0.0, 1.0)))
    report = {
        "enabled": True,
        "method": "raised-cosine quaternion SLERP and cubic-Hermite root bridge",
        "frame_count": int(len(result)),
        "feature_count": int(result.shape[1]),
        "joint_count": int(joint_count),
        "chunk_frames": int(chunk_frames),
        "window_frames": int(window_frames),
        "boundaries": details,
        "contact_channels_preserved": bool(
            contact_count == 0 or np.array_equal(result[:, :contact_count], contacts_before)
        ),
        "max_root_displacement": float(np.max(np.linalg.norm(positions - input_positions, axis=1))),
        "max_joint_rotation_change_degrees": float(np.max(rotation_change)),
    }
    return result.astype(original.dtype, copy=False), report
