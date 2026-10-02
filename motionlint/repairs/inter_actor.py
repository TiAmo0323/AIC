"""Bounded, symmetric actor separation with unchanged local skeletons."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from motionlint.core.motion_sequence import MotionSequence
from motionlint.repairs.kinematics import smooth_envelope, unit


def separate_actors(motion: MotionSequence, settings: dict, *, max_actor_shift_m: float = .15, blend_frames: int = 6):
    if motion.source != "intergen" or motion.positions is None or motion.actor_count != 2:
        raise ValueError("Actor separation currently needs two InterGen actors")
    original = motion.positions.astype(np.float64)
    lookup = {name: index for index, name in enumerate(motion.joint_names)}
    up = int(motion.metadata.get("up_axis", 1))
    difference = np.median(original[:, 1, lookup["Hips"]] - original[:, 0, lookup["Hips"]], axis=0)
    difference[up] = 0
    fallback = np.zeros(3)
    fallback[(up + 1) % 3] = 1
    reference_direction = unit(difference, fallback)
    angles = np.linspace(0., 2 * np.pi, 64, endpoint=False)
    directions = np.zeros((64, 3))
    directions[:, (up + 1) % 3] = np.cos(angles)
    directions[:, (up + 2) % 3] = np.sin(angles)
    directions = directions[directions @ reference_direction >= -1e-8]
    requirements = np.zeros((motion.frame_count, len(directions)))
    pairs = [("Head", "Head", settings["head_head_clearance_m"]),
             ("Hips", "Hips", settings["torso_torso_clearance_m"])]
    for first, second, clearance in pairs:
        delta = original[:, 1, lookup[second]] - original[:, 0, lookup[first]]
        projection = delta @ directions.T
        perpendicular_sq = np.sum(delta * delta, axis=-1)[:, None] - projection**2
        shift = np.maximum(0., np.sqrt(np.maximum(0., (float(clearance) + .005)**2 - perpendicular_sq)) - projection)
        requirements = np.maximum(requirements, np.where((np.linalg.norm(delta, axis=-1) < clearance)[:, None], shift, 0.))
    # Select the bounded horizontal direction that needs the least movement
    # for both head and pelvis, including dancers leaning in opposite ways.
    best = int(np.argmin(requirements.max(axis=0) + .01 * requirements.mean(axis=0)))
    direction = directions[best]
    required = requirements[:, best]
    relative = np.minimum(smooth_envelope(required, blend_frames), 2 * max_actor_shift_m)
    shifts = relative[:, None] * direction / 2
    corrected = original.copy()
    corrected[:, 0] -= shifts[:, None]
    corrected[:, 1] += shifts[:, None]
    root = corrected[:, :, lookup["Hips"]].copy()
    return replace(motion, positions=corrected.astype(motion.positions.dtype), root_translation=root,
                   metadata={**motion.metadata, "repair": "inter_actor_separation"}), {
                       "method": "symmetric horizontal separation", "max_actor_shift_m": float(np.linalg.norm(shifts, axis=-1).max()),
                       "bound_limited_frames": int(np.count_nonzero(required > 2 * max_actor_shift_m)),
                       "shifted_frames": int(np.count_nonzero(relative)), "direction": direction.tolist()}
