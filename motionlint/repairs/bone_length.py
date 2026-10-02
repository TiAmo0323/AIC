"""Project raw InterGen positions onto the clip's fixed median bone lengths."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from motionlint.core.motion_sequence import MotionSequence
from motionlint.repairs.kinematics import unit, two_bone_ik


def project_bone_lengths(motion: MotionSequence, *, max_correction_m: float = .10,
                         endpoint_strength: float = 0.):
    if motion.source != "intergen" or motion.positions is None:
        raise ValueError("Bone projection needs InterGen global joints")
    parents = motion.metadata["parents"]
    original = motion.positions.astype(np.float64)
    corrected = original.copy()
    lengths = np.zeros((motion.actor_count, original.shape[2]))
    for joint, parent in enumerate(parents):
        if parent < 0:
            continue
        vector = original[:, :, joint] - original[:, :, parent]
        lengths[:, joint] = np.median(np.linalg.norm(vector, axis=-1), axis=0)
        if np.any(lengths[:, joint] < .015) or not np.isfinite(vector).all():
            raise ValueError("Cannot infer reliable bone lengths from collapsed or nonfinite joints")
        corrected[:, :, joint] = corrected[:, :, parent] + unit(vector) * lengths[None, :, joint, None]
    # Preserve measured ankle/wrist locations where reachable, instead of
    # accumulating all upstream length changes at hands and feet.
    lookup = {name: index for index, name in enumerate(motion.joint_names)}
    for side in ("Left", "Right"):
        for suffixes in (("UpLeg", "Leg", "Foot"), ("Arm", "ForeArm", "Hand")):
            start, bend, end = [lookup[side + suffix] for suffix in suffixes]
            old_end = corrected[:, :, end].copy()
            if endpoint_strength == 0:
                continue
            target = old_end + endpoint_strength * (original[:, :, end] - old_end)
            solved_bend, solved_end = two_bone_ik(corrected[:, :, start], corrected[:, :, bend], old_end, target)
            corrected[:, :, bend] = solved_bend
            corrected[:, :, end] = solved_end
            if suffixes[-1] == "Foot":
                corrected[:, :, lookup[side + "Toe"]] += solved_end - old_end
    displacement = float(np.linalg.norm(corrected - original, axis=-1).max())
    if displacement > max_correction_m:
        return motion, {"applied": False, "reason": "Fixed-length projection exceeds movement bound", "max_displacement_m": displacement}
    return replace(motion, positions=corrected.astype(motion.positions.dtype),
                   metadata={**motion.metadata, "bone_reference_lengths_m": lengths.tolist(), "repair": "bone_length_projection"}), {
                       "applied": True, "method": "fixed median bone lengths", "endpoint_strength": endpoint_strength,
                       "max_displacement_m": displacement}
