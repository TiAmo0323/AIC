"""Small NumPy kinematic primitives with explicit length preservation."""

from __future__ import annotations

import numpy as np


def unit(value: np.ndarray, fallback: np.ndarray | None = None) -> np.ndarray:
    value = np.asarray(value, dtype=np.float64)
    length = np.linalg.norm(value, axis=-1, keepdims=True)
    result = value / np.maximum(length, 1e-10)
    if fallback is not None:
        default = np.broadcast_to(fallback, value.shape)
        default = default / np.maximum(np.linalg.norm(default, axis=-1, keepdims=True), 1e-10)
        result = np.where(length > 1e-10, result, default)
    return result


def two_bone_ik(start: np.ndarray, bend: np.ndarray, end: np.ndarray,
                target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Solve the limb in its original bend plane; clamp unreachable targets."""
    first = np.linalg.norm(bend - start, axis=-1)
    second = np.linalg.norm(end - bend, axis=-1)
    direction = unit(target - start, unit(end - start, np.array([0., -1., 0.])))
    requested = np.linalg.norm(target - start, axis=-1)
    distance = np.clip(requested, np.abs(first - second) + 1e-8, first + second - 1e-8)
    distance = np.maximum(distance, 1e-8)
    along = (first**2 - second**2 + distance**2) / (2 * distance)
    original_direction = unit(end - start, direction)
    original_normal = bend - start - np.sum((bend - start) * original_direction, axis=-1, keepdims=True) * original_direction
    # Carry the bend plane with the limb. Projecting the original knee directly
    # onto the new target axis can flip its side when a nearly straight leg
    # moves only a few centimetres, causing an artificial knee jerk.
    transport = align_rotation(original_direction, direction)
    normal = np.einsum("...ij,...j->...i", transport, original_normal)
    # A straight limb has no defined bend plane. Pick a deterministic axis
    # perpendicular to the target to avoid NaN and frame-dependent sign flips.
    axis = np.eye(3)[np.argmin(np.abs(direction), axis=-1)]
    perpendicular = unit(normal, np.cross(direction, axis))
    height = np.sqrt(np.maximum(0., first**2 - along**2))
    solved_bend = start + along[..., None] * direction + height[..., None] * perpendicular
    solved_end = start + distance[..., None] * direction
    return solved_bend, solved_end


def align_rotation(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Proper minimal rotation from source to target, including opposite axes."""
    source, target = unit(source), unit(target)
    cross = np.cross(source, target)
    cosine = np.clip(np.sum(source * target, axis=-1), -1., 1.)
    x, y, z = np.moveaxis(cross, -1, 0)
    zero = np.zeros_like(x)
    skew = np.stack([zero, -z, y, z, zero, -x, -y, x, zero], axis=-1).reshape(source.shape[:-1] + (3, 3))
    result = np.eye(3) + skew + (skew @ skew) / np.maximum(1 + cosine[..., None, None], 1e-10)
    axis = np.eye(3)[np.argmin(np.abs(source), axis=-1)]
    opposite_axis = unit(np.cross(source, axis))
    opposite = 2 * opposite_axis[..., :, None] * opposite_axis[..., None, :] - np.eye(3)
    return np.where((cosine < -1 + 1e-8)[..., None, None], opposite, result)


def world_rotations(local: np.ndarray, parents: list[int]) -> np.ndarray:
    world = np.empty_like(local)
    for joint, parent in enumerate(parents):
        world[:, joint] = local[:, joint] if parent < 0 else world[:, parent] @ local[:, joint]
    return world


def smooth_envelope(values: np.ndarray, frames: int) -> np.ndarray:
    """Ease around positive scalar corrections without undershooting them."""
    result = values.copy()
    for offset in range(1, frames + 1):
        weight = .5 * (1 + np.cos(np.pi * offset / (frames + 1)))
        result[offset:] = np.maximum(result[offset:], weight * values[:-offset])
        result[:-offset] = np.maximum(result[:-offset], weight * values[offset:])
    return result
