"""Shared support estimate that never uses horizontal speed to hide sliding."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.floor import floor_heights


@dataclass
class FootSupport:
    intervals: np.ndarray  # (T-1, A, F), a point supported at both endpoints
    feet: list[int]
    metrics: dict


def estimate_support(motion: MotionSequence, settings: dict) -> FootSupport:
    feet = list(motion.metadata.get("foot_joint_ids", []))
    if motion.positions is None or not feet or motion.frame_count < 2:
        raise ValueError("Support estimation needs foot positions and two frames")
    up = int(motion.metadata.get("up_axis", 1))
    height = motion.positions[:, :, feet, up]
    baseline = np.nanpercentile(height, 5, axis=0)
    if settings.get("use_explicit_floor", False) and motion.metadata.get("floor_height_m") is not None:
        floor, _ = floor_heights(motion, height, settings)
        baseline = np.broadcast_to(floor[:, None], baseline.shape)
    near = height <= baseline[None] + float(settings["contact_height_m"])
    eligible = near[:-1] & near[1:]
    source = "height_and_vertical_motion"
    if motion.contacts is not None and motion.contacts.shape[2] == len(feet):
        eligible &= (motion.contacts[:-1] > .5) & (motion.contacts[1:] > .5)
        source = "model_contacts_height_and_vertical_motion"
    candidate_count = int(eligible.sum())
    # Swinging feet can pass close to the floor. Vertical motion distinguishes
    # those from support without rejecting a horizontally sliding planted foot.
    vertical_speed = np.abs(np.diff(height, axis=0)) * motion.fps
    eligible &= vertical_speed <= float(settings.get("vertical_speed_m_s", .15))
    vertical_excluded = candidate_count - int(eligible.sum())
    minimum = max(1, int(settings.get("min_contact_frames", 3)) - 1)
    for actor in range(motion.actor_count):
        for foot in range(len(feet)):
            indices = np.flatnonzero(eligible[:, actor, foot])
            if not len(indices):
                continue
            for segment in np.split(indices, np.flatnonzero(np.diff(indices) > 1) + 1):
                if len(segment) < minimum:
                    eligible[segment, actor, foot] = False
    # A foot rolling over a planted toe moves its ankle legitimately. Test the
    # toe when it supports the body, and the ankle only when the toe is absent.
    pivot_excluded = 0
    for side in ("left", "right"):
        pair = motion.metadata.get(f"{side}_foot_joint_ids", [])
        if len(pair) == 2 and all(joint in feet for joint in pair):
            ankle, toe = (feet.index(joint) for joint in pair)
            pivot_excluded += int(np.count_nonzero(eligible[..., ankle] & eligible[..., toe]))
            eligible[..., ankle] &= ~eligible[..., toe]
    return FootSupport(eligible, feet, {
        "contact_source": source,
        "support_joint_interval_count": int(eligible.sum()),
        "height_contact_candidate_count": candidate_count,
        "vertical_swing_excluded_count": vertical_excluded,
        "ankle_pivot_excluded_count": pivot_excluded,
        "vertical_speed_m_s": float(settings.get("vertical_speed_m_s", .15)),
        "min_contact_frames": int(settings.get("min_contact_frames", 3)),
    })
