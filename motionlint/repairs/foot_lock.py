"""Bounded support anchors and two-bone leg IK for both source formats."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from motionlint.core.skeleton import SMPL_TO_BVH22
from motionlint.adapters.lodge_adapter import normalize_lodge_array
from motionlint.core.config import load_config
from motionlint.core.foot_support import estimate_support
from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.result import MotionIssue
from motionlint.repairs.kinematics import align_rotation, two_bone_ik, world_rotations
from motionlint.tests.common import segments


def _anchors(motion, support, horizontal, maximum, blend):
    correction = np.zeros((motion.frame_count, motion.actor_count, 2, 2))
    active = np.zeros((motion.frame_count, motion.actor_count, 2), dtype=bool)
    lookup = {name: index for index, name in enumerate(motion.joint_names)}
    chains = []
    for side_index, side in enumerate(("Left", "Right")):
        chains.append([lookup[side + suffix] for suffix in ("UpLeg", "Leg", "Foot", "Toe")])
        ankle, toe = motion.metadata.get(side.lower() + "_foot_joint_ids", [])
        ankle_id, toe_id = support.feet.index(ankle), support.feet.index(toe)
        for actor in range(motion.actor_count):
            modes = np.full(motion.frame_count, -1, dtype=int)
            for joint, local in ((ankle, ankle_id), (toe, toe_id)):
                frames = np.zeros(motion.frame_count, dtype=bool)
                frames[:-1] |= support.intervals[:, actor, local]
                frames[1:] |= support.intervals[:, actor, local]
                modes[frames] = joint
            for start, end in segments(modes >= 0):
                previous_joint = int(modes[start])
                anchor = motion.positions[start, actor, previous_joint, horizontal].copy()
                for frame in range(start, end + 1):
                    joint = int(modes[frame])
                    point = motion.positions[frame, actor, joint, horizontal]
                    if joint != previous_joint:
                        anchor = point + correction[frame - 1, actor, side_index]
                    delta = anchor - point
                    delta *= min(1., maximum / max(np.linalg.norm(delta), 1e-10))
                    correction[frame, actor, side_index] = delta
                    active[frame, actor, side_index] = True
                    previous_joint = joint
                for offset in range(1, blend + 1):
                    frame = end + offset
                    if frame >= motion.frame_count:
                        break
                    weight = .5 * (1 + np.cos(np.pi * offset / (blend + 1)))
                    correction[frame, actor, side_index] = delta * weight
                    active[frame, actor, side_index] = True
    return chains, correction, active


def _anchor_center(integrated, method):
    if method == "median":
        return np.median(integrated, axis=0)
    if method == "bounds":
        return .5 * (integrated.min(axis=0) + integrated.max(axis=0))
    raise ValueError("Unknown foot anchor center method")


def _speed_limited_correction(integrated, maximum, max_step, center_method="median"):
    """Bound each displacement while reducing support-path speed.

    Unlike a stationary anchor, this may move slowly along a long support run.
    Alternating projections need not satisfy every speed bound when the path
    and displacement balls are incompatible. The inspector must recheck it.
    """
    values = _anchor_center(integrated, center_method) - integrated
    values *= np.minimum(1., maximum / np.maximum(np.linalg.norm(values, axis=-1), 1e-10))[:, None]
    target = integrated + values
    for _ in range(80):
        for parity in (0, 1):
            left = np.arange(parity, len(target) - 1, 2)
            right = left + 1
            delta = target[right] - target[left]
            distance = np.linalg.norm(delta, axis=-1)
            adjustment = .5 * delta * np.maximum(0., 1. - max_step / np.maximum(distance, 1e-10))[:, None]
            target[left] += adjustment
            target[right] -= adjustment
            offset = target - integrated
            offset *= np.minimum(1., maximum / np.maximum(np.linalg.norm(offset, axis=-1), 1e-10))[:, None]
            target = integrated + offset
    return target - integrated


def _interval_anchors(motion, support, horizontal, maximum, blend, max_step=None, center_method="median"):
    """Integrate the supported point per interval, including heel/toe switches."""
    lookup = {name: index for index, name in enumerate(motion.joint_names)}
    chains = [[lookup[side + suffix] for suffix in ("UpLeg", "Leg", "Foot", "Toe")]
              for side in ("Left", "Right")]
    correction = np.zeros((motion.frame_count, motion.actor_count, 2, 2))
    active = np.zeros(correction.shape[:-1], dtype=bool)
    for side, chain in enumerate(chains):
        ankle, toe = chain[2:]
        ankle_id, toe_id = support.feet.index(ankle), support.feet.index(toe)
        for actor in range(motion.actor_count):
            supported = support.intervals[:, actor, ankle_id] | support.intervals[:, actor, toe_id]
            planted_frames = np.zeros(motion.frame_count, dtype=bool)
            for start, end in segments(supported):
                intervals = np.arange(start, end + 1)
                joints = np.where(support.intervals[intervals, actor, toe_id], toe, ankle)
                displacement = (motion.positions[intervals + 1, actor, joints][:, horizontal]
                                - motion.positions[intervals, actor, joints][:, horizontal])
                integrated = np.concatenate([np.zeros((1, 2)), np.cumsum(displacement, axis=0)])
                # Center the anchor over the complete support, reducing the
                # movement needed compared with fixing it at the first frame.
                values = _anchor_center(integrated, center_method) - integrated
                values *= np.minimum(1., maximum / np.maximum(np.linalg.norm(values, axis=-1), 1e-10))[:, None]
                if max_step is not None:
                    values = _speed_limited_correction(integrated, maximum, max_step, center_method)
                correction[start:end + 2, actor, side] = values
                planted_frames[start:end + 2] = True
            planted = np.flatnonzero(planted_frames)
            if not len(planted):
                continue
            # Blend only the unplanted frames. Release curves cannot overwrite
            # the next contact, and every selected interval keeps its target.
            for start, end in segments(~planted_frames):
                left, right = start - 1, end + 1
                for frame in range(start, end + 1):
                    value = np.zeros(2)
                    if left >= 0 and frame - left <= blend:
                        weight = .5 * (1 + np.cos(np.pi * (frame - left) / (blend + 1)))
                        value += weight * correction[left, actor, side]
                    if right < motion.frame_count and right - frame <= blend:
                        weight = .5 * (1 + np.cos(np.pi * (right - frame) / (blend + 1)))
                        value += weight * correction[right, actor, side]
                    if left >= 0 and right < motion.frame_count and right - left <= 2 * blend:
                        phase = (frame - left) / (right - left)
                        weight = phase * phase * (3 - 2 * phase)
                        value = (1 - weight) * correction[left, actor, side] + weight * correction[right, actor, side]
                    correction[frame, actor, side] = value
            # A centered contact can have zero anchor offset while the pelvis
            # still moves. It must remain selected for the leg IK.
            active[:, actor, side] = planted_frames | (np.linalg.norm(correction[:, actor, side], axis=-1) > 1e-9)
    return chains, correction, active


def _smooth_track(values, frames):
    if frames == 0:
        return values
    if frames < 3 or frames % 2 == 0:
        raise ValueError("Smoothing window must be zero or an odd integer >= 3")
    radius = frames // 2
    weights = np.hanning(frames + 2)[1:-1]
    weights /= weights.sum()
    padded = np.pad(values, [(radius, radius)] + [(0, 0)] * (values.ndim - 1), mode="edge")
    return sum(weight * padded[offset:offset + len(values)] for offset, weight in enumerate(weights))


def repair_foot_sliding(motion: MotionSequence, issues: list[MotionIssue], *,
                        raw: np.ndarray | None = None, max_correction_m: float = .15,
                        support_settings: dict | None = None, blend_frames: int = 4,
                        correction_strength: float = 1., root_follow: bool = True,
                        anchor_method: str = "legacy", smooth_frames: int = 0,
                        root_method: str = "legacy", center_method: str = "median",
                        contact_correction=None, root_correction=None):
    if motion.positions is None or motion.source not in {"lodge", "intergen", "bvh"}:
        raise ValueError("Foot lock needs LODGE, InterGen or mapped BVH global joints")
    lookup = {name: i for i, name in enumerate(motion.joint_names)}
    for side in ("Left", "Right"):
        chain = [lookup.get(side + suffix) for suffix in ("UpLeg", "Leg", "Foot", "Toe")]
        if any(joint is None for joint in chain) or len(motion.metadata.get(side.lower() + "_foot_joint_ids", [])) != 2:
            raise ValueError("Foot lock needs mapped hip/knee/ankle/toe chains on both legs")
        if motion.source == "bvh" and any(motion.metadata['parents'][child] != parent for parent, child in zip(chain, chain[1:])):
            raise ValueError("BVH foot lock needs a direct hip/knee/ankle/toe hierarchy")
    if not np.isfinite(max_correction_m) or max_correction_m <= 0:
        raise ValueError("Foot correction bound must be finite and positive")
    if root_method not in {"legacy", "support"}:
        raise ValueError("Unknown foot root correction method")
    affected_actors = (set(range(motion.actor_count)) if not issues or any(issue.actor_id is None for issue in issues)
                       else {issue.actor_id for issue in issues})
    if any(not isinstance(actor, int) or not 0 <= actor < motion.actor_count for actor in affected_actors):
        raise ValueError("Foot issue refers to an invalid actor")
    settings = support_settings or load_config()["tests"]["foot_sliding"]
    support = estimate_support(motion, settings)
    up = int(motion.metadata.get("up_axis", 1))
    horizontal = [axis for axis in range(3) if axis != up]
    builder = {"legacy": _anchors, "interval": _interval_anchors, "velocity": _interval_anchors}.get(anchor_method)
    if builder is None:
        raise ValueError("Unknown foot anchor method")
    options = {"max_step": .8 * float(settings["horizontal_speed_m_s"]) / motion.fps} if anchor_method == "velocity" else {}
    if anchor_method != "legacy":
        options["center_method"] = center_method
    elif center_method != "median":
        raise ValueError("Legacy anchors do not support a different center method")
    chains, correction, active = builder(motion, support, horizontal, max_correction_m, blend_frames, **options)
    if contact_correction is not None:
        if contact_correction.shape!=correction.shape or not np.isfinite(contact_correction).all():
            raise ValueError('Invalid optimization foot correction')
        correction=contact_correction.copy()
        active=np.linalg.norm(correction,axis=-1)>1e-10
    for actor in range(motion.actor_count):
        if actor not in affected_actors:
            correction[:, actor] = 0.
            active[:, actor] = False
    correction = _smooth_track(correction, smooth_frames)
    active |= np.linalg.norm(correction, axis=-1) > 1e-9
    if not 0 < correction_strength <= 1:
        raise ValueError("Correction strength must be in (0, 1]")
    correction *= correction_strength
    reference = motion.positions.astype(np.float64).copy()
    root_delta = np.zeros((motion.frame_count, motion.actor_count, 3))
    if root_correction is not None:
        if root_correction.shape!=root_delta.shape or not np.isfinite(root_correction).all():
            raise ValueError('Invalid optimization root correction')
        root_delta=root_correction.copy()
        reference+=root_delta[:,:,None]
    elif root_follow and root_method == "support":
        # Follow the same bounded anchors as the legs. A common planted drift
        # can then move the whole body coherently, rather than forcing nearly
        # straight legs to reach targets outside their original length.
        weights = active.astype(np.float64)
        shared = np.sum(correction * weights[..., None], axis=2) / np.maximum(weights.sum(axis=2)[..., None], 1.)
        shared *= np.minimum(1., max_correction_m / np.maximum(np.linalg.norm(shared, axis=-1), 1e-10))[..., None]
        root_delta[..., horizontal] = shared
        reference += root_delta[:, :, None]
    elif root_follow:
        tracks = reference[:, :, support.feet]
        for actor in range(motion.actor_count):
            if actor not in affected_actors:
                continue
            for frame in range(1, motion.frame_count):
                planted = support.intervals[frame - 1, actor]
                if np.any(planted):
                    displacement = tracks[frame, actor, planted][:, horizontal] - tracks[frame - 1, actor, planted][:, horizontal]
                    delta = .97 * root_delta[frame - 1, actor, horizontal] - np.mean(displacement, axis=0)
                    delta *= min(1., max_correction_m / max(np.linalg.norm(delta), 1e-10))
                else:
                    delta = .9 * root_delta[frame - 1, actor, horizontal]
                root_delta[frame, actor, horizontal] = delta
        root_delta *= correction_strength
        root_delta = _smooth_track(root_delta, smooth_frames)
        reference += root_delta[:, :, None]
    corrected = reference.copy()
    local = motion.rotation_matrices.copy() if motion.source in {"lodge", "bvh"} else None
    world = np.stack([world_rotations(local[:, actor], motion.metadata["parents"]) for actor in range(motion.actor_count)], axis=1) if local is not None else None
    changed_joints = []
    count = 0
    max_error = 0.
    for side, (hip, knee, ankle, toe) in enumerate(chains):
        for actor in range(motion.actor_count):
            target = motion.positions[:, actor, ankle].astype(np.float64).copy()
            target[:, horizontal] += correction[:, actor, side]
            selected = active[:, actor, side]
            target[~selected] = reference[~selected, actor, ankle]
            changed = selected & (np.linalg.norm(target - reference[:, actor, ankle], axis=-1) > 1e-7)
            new_knee, new_ankle = two_bone_ik(reference[:, actor, hip], reference[:, actor, knee], reference[:, actor, ankle], target)
            corrected[changed, actor, knee] = new_knee[changed]
            corrected[changed, actor, ankle] = new_ankle[changed]
            corrected[changed, actor, toe] = new_ankle[changed] + reference[changed, actor, toe] - reference[changed, actor, ankle]
            count += int(changed.sum())
            if np.any(changed):
                max_error = max(max_error, float(np.linalg.norm(new_ankle[changed] - target[changed], axis=-1).max()))
            if local is not None:
                # Update local rotations so the raw array and renderer agree.
                # Preserve ankle world orientation, including the toe offset.
                hip_world = align_rotation(reference[:, actor, knee] - reference[:, actor, hip], new_knee - reference[:, actor, hip]) @ world[:, actor, hip]
                knee_world = hip_world @ local[:, actor, knee]
                offsets = np.asarray(motion.metadata.get('actor_offsets', [motion.metadata['offsets']] * motion.actor_count))[actor]
                lower_vector = motion.local_positions[:,actor,ankle] if motion.local_positions is not None else offsets[ankle]
                lower = np.einsum("tij,tj->ti", knee_world, lower_vector) if np.ndim(lower_vector)==2 else np.einsum('tij,j->ti',knee_world,lower_vector)
                knee_world = align_rotation(lower, new_ankle - new_knee) @ knee_world
                parent = motion.metadata["parents"][hip]
                local[changed, actor, hip] = (np.swapaxes(world[:, actor, parent], -1, -2) @ hip_world)[changed]
                local[changed, actor, knee] = (np.swapaxes(hip_world, -1, -2) @ knee_world)[changed]
                local[changed, actor, ankle] = (np.swapaxes(knee_world, -1, -2) @ world[:, actor, ankle])[changed]
                changed_joints.extend([hip, knee, ankle])
    if motion.source == "lodge":
        if raw is None:
            source = motion.metadata.get("source_path")
            if not source:
                raise ValueError("LODGE foot lock requires raw motion or source_path")
            raw = np.load(source, allow_pickle=False)
        repaired_raw = np.asarray(raw).copy()
        start = 4 if raw.shape[1] in {139, 319} else 0
        repaired_raw[:, start:start + 3] += root_delta[:, 0].astype(raw.dtype)
        for joint in set(changed_joints):
            first = start + 3 + 6 * SMPL_TO_BVH22[joint]
            repaired_raw[:, first:first + 6] = local[:, 0, joint, :2].reshape(-1, 6).astype(raw.dtype)
        repaired = normalize_lodge_array(repaired_raw, fps=motion.fps, source_path=motion.metadata.get("source_path"), frozen_geometry=motion.metadata)
    elif motion.source == 'bvh':
        from motionlint.core.fk import forward_positions
        repaired_raw = None
        root = motion.root_translation + root_delta
        offsets = motion.metadata.get('actor_offsets', [motion.metadata['offsets']] * motion.actor_count)
        parents = np.asarray(motion.metadata['parents']).copy()
        local_positions = motion.local_positions.copy()
        local_positions[:,:,0] = root
        positions, _ = forward_positions(local,local_positions,parents)
        repaired = replace(motion, positions=positions, rotation_matrices=local,
                           rotations_6d=local[..., :2, :].reshape(*local.shape[:3], 6),
                           root_translation=root, local_positions=local_positions, metadata={**motion.metadata})
    else:
        repaired_raw = None
        repaired = replace(motion, positions=corrected.astype(motion.positions.dtype),
                           root_translation=corrected[:, :, 0].astype(motion.positions.dtype), metadata={**motion.metadata})
    repaired.metadata["repair"] = "foot_lock"
    return repaired, repaired_raw, {"method": "support anchors and two-bone IK", "applied_joint_frames": count,
        "max_correction_m": max_correction_m, "correction_strength": correction_strength, "root_follow": root_follow,
        "root_method": root_method, "affected_actor_ids": sorted(affected_actors),
        "center_method": center_method,
        "anchor_method": anchor_method,
        "smooth_frames": smooth_frames,
        "max_unreachable_target_error_m": max_error,
        "root_max_shift_m": float(np.linalg.norm(root_delta, axis=-1).max()), "support": support.metrics}
