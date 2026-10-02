"""Platform arm correction extracted unchanged from the frozen v3 baseline.
Publication provenance must be reviewed alongside the other legacy helpers.
"""
from __future__ import annotations
from typing import Tuple
import numpy as np

HAND_HEAD_CHAINS = (
    ("left", 16, 18, 20),
    ("right", 17, 19, 21),
)

def _normalized(vectors: np.ndarray, fallback: Optional[np.ndarray] = None) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    result = vectors / np.maximum(norms, 1e-8)
    if fallback is not None:
        invalid = norms[:, 0] <= 1e-8
        result[invalid] = fallback[invalid]
    return result

def _temporal_smooth(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1 or len(values) < 3:
        return values.copy()
    radius = max(1, int(window) // 2)
    padded = np.pad(values, ((radius, radius), (0, 0)), mode="edge")
    weights = np.arange(1, radius + 2, dtype=np.float64)
    weights = np.concatenate((weights, weights[-2::-1]))
    weights /= weights.sum()
    return np.stack([
        np.sum(padded[frame:frame + len(weights)] * weights[:, None], axis=0)
        for frame in range(len(values))
    ])

def _median_bone_length(joints: np.ndarray, child: int, parent: int) -> float:
    lengths = np.linalg.norm(joints[:, child] - joints[:, parent], axis=-1)
    valid = lengths[lengths > 1e-6]
    return float(np.median(valid)) if len(valid) else 1.0

def _limit_position_displacement(
    candidate: np.ndarray,
    original: np.ndarray,
    max_displacement: float,
) -> np.ndarray:
    if max_displacement <= 0.0:
        return candidate
    displacement = candidate - original
    distance = np.linalg.norm(displacement, axis=-1, keepdims=True)
    scale = np.minimum(1.0, float(max_displacement) / np.maximum(distance, 1e-8))
    return original + displacement * scale

def _frame_segments(mask: np.ndarray) -> list:
    frames = np.flatnonzero(mask)
    if len(frames) == 0:
        return []
    segments = []
    start = previous = int(frames[0])
    for frame in frames[1:]:
        frame = int(frame)
        if frame != previous + 1:
            segments.append({"start_frame": start + 1, "end_frame": previous + 1})
            start = frame
        previous = frame
    segments.append({"start_frame": start + 1, "end_frame": previous + 1})
    return segments

def _segment_point_distances(
    starts: np.ndarray,
    ends: np.ndarray,
    points: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    segments = ends - starts
    denominator = np.sum(segments * segments, axis=-1)
    amount = np.sum((points - starts) * segments, axis=-1) / np.maximum(denominator, 1e-8)
    amount = np.clip(amount, 0.0, 1.0)
    closest = starts + amount[:, None] * segments
    distances = np.linalg.norm(closest - points, axis=-1)
    return distances, closest, amount

def _hand_head_metrics(
    joints: np.ndarray,
    wrist_clearance: float,
    forearm_clearance: float,
) -> dict:
    head = joints[:, 15]
    collision_any = np.zeros(len(joints), dtype=bool)
    details = []
    penetration_sum = 0.0
    minimum_wrist_distance = float("inf")
    minimum_forearm_distance = float("inf")

    for side, _, elbow_index, wrist_index in HAND_HEAD_CHAINS:
        forearm_distances, _, _ = _segment_point_distances(
            joints[:, elbow_index],
            joints[:, wrist_index],
            head,
        )
        wrist_distances = np.linalg.norm(joints[:, wrist_index] - head, axis=-1)
        wrist_collision = wrist_distances < max(0.0, wrist_clearance - 1e-5)
        forearm_collision = forearm_distances < max(0.0, forearm_clearance - 1e-5)
        collision = wrist_collision | forearm_collision
        wrist_penetration = np.maximum(wrist_clearance - wrist_distances, 0.0)
        forearm_penetration = np.maximum(forearm_clearance - forearm_distances, 0.0)
        collision_any |= collision
        penetration_sum += float(np.sum(wrist_penetration) + np.sum(forearm_penetration))
        minimum_wrist_distance = min(minimum_wrist_distance, float(np.min(wrist_distances)))
        minimum_forearm_distance = min(minimum_forearm_distance, float(np.min(forearm_distances)))
        details.append({
            "side": side,
            "minimum_wrist_distance": round(float(np.min(wrist_distances)), 6),
            "minimum_forearm_distance": round(float(np.min(forearm_distances)), 6),
            "wrist_collision_frame_count": int(np.count_nonzero(wrist_collision)),
            "forearm_collision_frame_count": int(np.count_nonzero(forearm_collision)),
            "collision_frame_count": int(np.count_nonzero(collision)),
            "collision_segments": _frame_segments(collision),
        })

    return {
        "minimum_distance": round(minimum_forearm_distance, 6),
        "minimum_wrist_distance": round(minimum_wrist_distance, 6),
        "minimum_forearm_distance": round(minimum_forearm_distance, 6),
        "collision_frame_count": int(np.count_nonzero(collision_any)),
        "collision_ratio": round(float(np.mean(collision_any)), 6),
        "penetration_sum": round(penetration_sum, 6),
        "details": details,
    }

def _restore_arm_lengths(
    shoulder: np.ndarray,
    elbow: np.ndarray,
    wrist: np.ndarray,
    upper_arm_length: np.ndarray,
    forearm_length: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    upper_direction = _normalized(elbow - shoulder)
    elbow = shoulder + upper_direction * upper_arm_length[:, None]
    forearm_direction = _normalized(wrist - elbow)
    wrist = elbow + forearm_direction * forearm_length[:, None]
    return elbow, wrist

def _project_arm_away_from_head(
    shoulder: np.ndarray,
    elbow: np.ndarray,
    wrist: np.ndarray,
    head: np.ndarray,
    wrist_clearance: float,
    forearm_clearance: float,
    original_elbow: np.ndarray,
    original_wrist: np.ndarray,
    elbow_max_correction: float,
    wrist_max_correction: float,
) -> Tuple[np.ndarray, np.ndarray]:
    candidate_elbow = elbow.copy()
    candidate_wrist = wrist.copy()
    upper_arm_length = np.linalg.norm(original_elbow - shoulder, axis=-1)
    forearm_length = np.linalg.norm(original_wrist - original_elbow, axis=-1)

    for _ in range(8):
        forearm_distances, closest, amount = _segment_point_distances(
            candidate_elbow,
            candidate_wrist,
            head,
        )
        wrist_distances = np.linalg.norm(candidate_wrist - head, axis=-1)
        forearm_penetration = np.maximum(forearm_clearance - forearm_distances, 0.0)
        wrist_penetration = np.maximum(wrist_clearance - wrist_distances, 0.0)
        active = (forearm_penetration > 1e-5) | (wrist_penetration > 1e-5)
        if not np.any(active):
            break

        outward = closest - head
        outward_norm = np.linalg.norm(outward, axis=-1, keepdims=True)
        fallback = candidate_wrist - head
        fallback /= np.maximum(np.linalg.norm(fallback, axis=-1, keepdims=True), 1e-8)
        outward = np.where(outward_norm > 1e-8, outward / np.maximum(outward_norm, 1e-8), fallback)
        candidate_elbow += outward * (forearm_penetration * (1.0 - amount) * 0.75)[:, None]
        candidate_wrist += outward * (forearm_penetration * (0.75 + amount))[:, None]

        wrist_outward = candidate_wrist - head
        wrist_outward /= np.maximum(np.linalg.norm(wrist_outward, axis=-1, keepdims=True), 1e-8)
        candidate_wrist += wrist_outward * wrist_penetration[:, None]

        candidate_elbow = _limit_position_displacement(
            candidate_elbow,
            original_elbow,
            elbow_max_correction,
        )
        candidate_wrist = _limit_position_displacement(
            candidate_wrist,
            original_wrist,
            wrist_max_correction,
        )
        candidate_elbow, candidate_wrist = _restore_arm_lengths(
            shoulder,
            candidate_elbow,
            candidate_wrist,
            upper_arm_length,
            forearm_length,
        )

    return candidate_elbow, candidate_wrist

def _correct_hand_head_collisions(
    joints: np.ndarray,
    clearance_scale: float,
    minimum_clearance: float,
    forearm_clearance_scale: float,
    forearm_minimum_clearance: float,
    blend_window: int,
    elbow_max_correction: float,
    wrist_max_correction: float,
) -> Tuple[np.ndarray, dict]:
    """通过局部手臂链修正降低手腕/前臂穿过头部的风险，并记录修正统计。"""
    original = np.asarray(joints, dtype=np.float64)
    corrected = original.copy()
    head_length = _median_bone_length(original, 15, 12)
    wrist_clearance = max(float(minimum_clearance), float(clearance_scale) * head_length)
    forearm_clearance = max(
        float(forearm_minimum_clearance),
        float(forearm_clearance_scale) * head_length,
    )
    before = _hand_head_metrics(original, wrist_clearance, forearm_clearance)

    for _, shoulder_index, elbow_index, wrist_index in HAND_HEAD_CHAINS:
        shoulder = original[:, shoulder_index]
        elbow = original[:, elbow_index]
        wrist = original[:, wrist_index]
        direct_elbow, direct_wrist = _project_arm_away_from_head(
            shoulder,
            elbow,
            wrist,
            original[:, 15],
            wrist_clearance,
            forearm_clearance,
            elbow,
            wrist,
            elbow_max_correction,
            wrist_max_correction,
        )
        blended_elbow = elbow + _temporal_smooth(direct_elbow - elbow, blend_window)
        blended_wrist = wrist + _temporal_smooth(direct_wrist - wrist, blend_window)
        blended_elbow, blended_wrist = _project_arm_away_from_head(
            shoulder,
            blended_elbow,
            blended_wrist,
            original[:, 15],
            wrist_clearance,
            forearm_clearance,
            elbow,
            wrist,
            elbow_max_correction,
            wrist_max_correction,
        )
        corrected[:, elbow_index] = blended_elbow
        corrected[:, wrist_index] = blended_wrist

    after = _hand_head_metrics(corrected, wrist_clearance, forearm_clearance)
    elbow_corrections = np.stack([
        np.linalg.norm(corrected[:, elbow_index] - original[:, elbow_index], axis=-1)
        for _, _, elbow_index, _ in HAND_HEAD_CHAINS
    ], axis=-1)
    wrist_corrections = np.stack([
        np.linalg.norm(corrected[:, wrist_index] - original[:, wrist_index], axis=-1)
        for _, _, _, wrist_index in HAND_HEAD_CHAINS
    ], axis=-1)
    changed = (elbow_corrections > 1e-5) | (wrist_corrections > 1e-5)
    report = {
        "enabled": True,
        "method": "separate wrist/head and forearm/head clearances with shoulder-elbow-wrist chain correction",
        "head_length": round(head_length, 6),
        "clearance_scale": float(clearance_scale),
        "minimum_clearance": float(minimum_clearance),
        "required_clearance": round(wrist_clearance, 6),
        "wrist_required_clearance": round(wrist_clearance, 6),
        "forearm_clearance_scale": float(forearm_clearance_scale),
        "forearm_minimum_clearance": float(forearm_minimum_clearance),
        "forearm_required_clearance": round(forearm_clearance, 6),
        "blend_window": int(blend_window),
        "max_correction": float(wrist_max_correction),
        "elbow_max_correction": float(elbow_max_correction),
        "wrist_max_correction": float(wrist_max_correction),
        "corrected_frame_count": int(np.count_nonzero(np.any(changed, axis=-1))),
        "elbow_correction_mean": round(float(np.mean(elbow_corrections[elbow_corrections > 1e-5])), 6)
        if np.any(elbow_corrections > 1e-5) else 0.0,
        "elbow_correction_max": round(float(np.max(elbow_corrections)), 6),
        "applied_correction_mean": round(float(np.mean(wrist_corrections[wrist_corrections > 1e-5])), 6)
        if np.any(wrist_corrections > 1e-5) else 0.0,
        "applied_correction_max": round(float(np.max(wrist_corrections)), 6),
        "before": before,
        "after": after,
    }
    return corrected.astype(joints.dtype, copy=False), report
