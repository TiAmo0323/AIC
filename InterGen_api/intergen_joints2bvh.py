# 将 InterGen 的双人 joints22 关节序列转换为 BVH。
# 转换前会按环境开关执行上半身稳定、手/头碰撞修正、骨长恢复和质量门检查，
# 同时输出 JSON 报告，供后续 Blender/Rokoko 重定向判断是否继续。
import argparse
import inspect
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional, Tuple

import numpy as np


APP_ROOT = Path(__file__).resolve().parent
PLATFORM_ROOT = APP_ROOT.parent.parent


UPPER_BODY_JOINTS = (3, 6, 9, 12, 13, 14, 15)
HAND_HEAD_CHAINS = (
    ("left", 16, 18, 20),
    ("right", 17, 19, 21),
)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


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


def _restore_bone(joints: np.ndarray, original: np.ndarray, child: int, parent: int) -> None:
    fallback = _normalized(original[:, child] - original[:, parent])
    direction = _normalized(joints[:, child] - joints[:, parent], fallback=fallback)
    joints[:, child] = joints[:, parent] + direction * _median_bone_length(original, child, parent)


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


def _stabilize_upper_body_joints(
    joints: np.ndarray,
    upper_body_window: int,
    neck_window: int,
    neck_max_position_correction: float = 0.04,
    head_max_position_correction: float = 0.03,
) -> Tuple[np.ndarray, dict]:
    """平滑头颈和核心关节并恢复骨长，减少重定向后的旋转突变。"""
    original = np.asarray(joints, dtype=np.float64)
    stabilized = original.copy()
    for joint in UPPER_BODY_JOINTS:
        window = neck_window if joint in (12, 15) else upper_body_window
        stabilized[:, joint] = _temporal_smooth(original[:, joint], window)

    # Rebuild the torso with stable lengths so temporal averaging cannot compress it.
    for child, parent in ((3, 0), (6, 3), (9, 6)):
        _restore_bone(stabilized, original, child, parent)
    for child in (13, 14):
        _restore_bone(stabilized, original, child, 9)

    shoulder_axis = _normalized(stabilized[:, 14] - stabilized[:, 13])
    spine_axis = _normalized(stabilized[:, 9] - stabilized[:, 6])
    forward = _normalized(np.cross(shoulder_axis, spine_axis))
    stable_up = _normalized(np.cross(forward, shoulder_axis), fallback=spine_axis)
    opposing = np.sum(stable_up * spine_axis, axis=-1) < 0.0
    stable_up[opposing] *= -1.0

    neck_length = _median_bone_length(original, 12, 9)
    raw_neck_direction = _normalized(original[:, 12] - original[:, 9], fallback=stable_up)
    smooth_neck_direction = _temporal_smooth(raw_neck_direction, neck_window)
    neck_direction = _normalized(0.80 * smooth_neck_direction + 0.20 * stable_up, fallback=stable_up)
    neck_candidate = stabilized[:, 9] + neck_direction * neck_length
    neck_candidate = _limit_position_displacement(
        neck_candidate,
        original[:, 12],
        neck_max_position_correction,
    )
    neck_direction = _normalized(neck_candidate - stabilized[:, 9], fallback=neck_direction)
    stabilized[:, 12] = stabilized[:, 9] + neck_direction * neck_length

    raw_head_direction = _normalized(original[:, 15] - original[:, 12], fallback=stable_up)
    smooth_head_direction = _temporal_smooth(raw_head_direction, neck_window)
    head_direction = _normalized(0.80 * smooth_head_direction + 0.20 * stable_up, fallback=stable_up)
    head_length = _median_bone_length(original, 15, 12)
    head_candidate = stabilized[:, 12] + head_direction * head_length
    head_candidate = _limit_position_displacement(
        head_candidate,
        original[:, 15],
        head_max_position_correction,
    )
    head_direction = _normalized(head_candidate - stabilized[:, 12], fallback=head_direction)
    stabilized[:, 15] = stabilized[:, 12] + head_direction * head_length

    neck_displacement = np.linalg.norm(stabilized[:, 12] - original[:, 12], axis=-1)
    head_displacement = np.linalg.norm(stabilized[:, 15] - original[:, 15], axis=-1)

    report = {
        "enabled": True,
        "upper_body_window": int(upper_body_window),
        "neck_window": int(neck_window),
        "smoothed_joint_indices": list(UPPER_BODY_JOINTS),
        "neck_length": round(neck_length, 6),
        "head_length": round(head_length, 6),
        "neck_max_position_correction": float(neck_max_position_correction),
        "head_max_position_correction": float(head_max_position_correction),
        "neck_position_displacement_mean": round(float(np.mean(neck_displacement)), 6),
        "neck_position_displacement_max": round(float(np.max(neck_displacement)), 6),
        "head_position_displacement_mean": round(float(np.mean(head_displacement)), 6),
        "head_position_displacement_max": round(float(np.max(head_displacement)), 6),
    }
    return stabilized.astype(joints.dtype, copy=False), report


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


def _resolve_momask_root(raw: str) -> Path:
    candidates = [
        Path(raw).expanduser() if raw else None,
        PLATFORM_ROOT / "momask-main",
        PLATFORM_ROOT / "InterMask-main" / "InterMask-main",
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        candidate = candidate.resolve()
        if (candidate / "visualization" / "joints2bvh.py").exists():
            return candidate
    raise FileNotFoundError("Could not find momask/InterMask root with visualization/joints2bvh.py")


def convert_joints_to_bvh(
    input_path: Path,
    output_path: Path,
    momask_root: Path,
    foot_ik: bool = True,
    fps: int = 30,
    stabilize_upper_body: bool = True,
    upper_body_window: int = 5,
    neck_window: int = 7,
    neck_max_position_correction: float = 0.04,
    head_max_position_correction: float = 0.03,
    anomaly_degrees: float = 45.0,
    root_anomaly_degrees: float = 30.0,
    temporal_ik: bool = True,
    report_path: Optional[Path] = None,
    quality_gate: bool = True,
    max_anomaly_ratio: float = 0.10,
    max_ik_p95_error: float = 0.10,
    correct_hand_head_collisions: bool = True,
    hand_head_clearance_scale: float = 2.0,
    hand_head_min_clearance: float = 0.15,
    hand_head_forearm_clearance_scale: float = 1.5,
    hand_head_forearm_min_clearance: float = 0.11,
    hand_head_blend_window: int = 7,
    hand_head_elbow_max_correction: float = 0.03,
    hand_head_max_correction: float = 0.05,
    max_self_collision_ratio: float = 0.02,
    hard_self_collision_ratio: float = 0.15,
    hard_self_collision_min_distance: float = 0.05,
) -> Path:
    """执行完整 joints22→BVH 流程，并在旁路 JSON 中保存可审计质量报告。"""
    if str(momask_root) not in sys.path:
        sys.path.insert(0, str(momask_root))

    old_cwd = Path.cwd()
    os.chdir(str(momask_root))
    try:
        # momask/InterMask code still uses NumPy aliases removed in newer NumPy.
        np.float = getattr(np, "float64", float)
        np.int = int
        np.bool = bool
        from visualization.joints2bvh import Joint2BVHConvertor

        joints = np.load(str(input_path), allow_pickle=False)
        if joints.ndim != 3 or joints.shape[1:] != (22, 3):
            raise ValueError(f"Expected joints shape (N, 22, 3), got {joints.shape}")

        joint_report = {"enabled": False}
        if stabilize_upper_body:
            joints, joint_report = _stabilize_upper_body_joints(
                joints,
                upper_body_window,
                neck_window,
                neck_max_position_correction=neck_max_position_correction,
                head_max_position_correction=head_max_position_correction,
            )

        collision_report = {"enabled": False}
        if correct_hand_head_collisions:
            joints, collision_report = _correct_hand_head_collisions(
                joints,
                clearance_scale=hand_head_clearance_scale,
                minimum_clearance=hand_head_min_clearance,
                forearm_clearance_scale=hand_head_forearm_clearance_scale,
                forearm_minimum_clearance=hand_head_forearm_min_clearance,
                blend_window=hand_head_blend_window,
                elbow_max_correction=hand_head_elbow_max_correction,
                wrist_max_correction=hand_head_max_correction,
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        converter = Joint2BVHConvertor()
        extended_converter = "fps" in inspect.signature(converter.convert).parameters
        if extended_converter:
            converter.convert(
                joints,
                str(output_path),
                foot_ik=foot_ik,
                fps=fps,
                stabilize_upper_body=stabilize_upper_body,
                upper_body_window=upper_body_window,
                neck_window=neck_window,
                anomaly_degrees=anomaly_degrees,
                root_anomaly_degrees=root_anomaly_degrees,
                temporal_ik=temporal_ik,
            )
            rotation_report = converter.last_stabilization_report
            ik_report = converter.last_ik_report
        else:
            # The public MoMask converter supports only foot IK and writes 20 FPS.
            converter.convert(joints, str(output_path), foot_ik=foot_ik)
            bvh_text = output_path.read_text(encoding="utf-8")
            bvh_text, replacements = re.subn(
                r"(?m)^Frame Time:\s*[^\r\n]+$",
                f"Frame Time: {1.0 / fps:.6f}",
                bvh_text,
                count=1,
            )
            if replacements != 1:
                raise RuntimeError("BVH frame time header missing")
            output_path.write_text(bvh_text, encoding="utf-8")
            rotation_report = {"bones": [], "available": False}
            ik_report = {"available": False}
            quality_gate = False
        violations = []
        warnings = []
        if not extended_converter:
            warnings.append("Public MoMask converter lacks temporal IK and rotation quality metrics; quality gate disabled")
        frame_count = int(joints.shape[0])
        for bone in rotation_report.get("bones", []):
            repaired_count = int(bone.get("anomalies_repaired", 0))
            limited_count = int(bone.get("residual_steps_limited", 0))
            anomaly_ratio = (repaired_count + limited_count) / max(1, frame_count - 1)
            bone["anomaly_ratio"] = round(anomaly_ratio, 6)
            threshold = float(bone.get("threshold_degrees", anomaly_degrees))
            after_max = float(bone.get("after", {}).get("max_step_degrees", 0.0))
            if anomaly_ratio > max_anomaly_ratio:
                violations.append(
                    f"{bone.get('bone')}: anomaly ratio {anomaly_ratio:.3f} exceeds {max_anomaly_ratio:.3f}"
                )
            if after_max > threshold + 0.1:
                violations.append(
                    f"{bone.get('bone')}: final rotation step {after_max:.3f} exceeds {threshold:.3f} degrees"
                )

        ik_p95_error = float(ik_report.get("position_error_p95", 0.0))
        if extended_converter and temporal_ik and ik_p95_error > max_ik_p95_error:
            violations.append(
                f"IK position error p95 {ik_p95_error:.4f} exceeds {max_ik_p95_error:.4f}"
            )
        residual_collision_ratio = float(collision_report.get("after", {}).get("collision_ratio", 0.0))
        residual_min_distance = float(collision_report.get("after", {}).get("minimum_distance", float("inf")))
        if correct_hand_head_collisions and residual_collision_ratio > max_self_collision_ratio:
            warnings.append(
                "hand/head residual collision ratio "
                f"{residual_collision_ratio:.3f} exceeds {max_self_collision_ratio:.3f}"
            )
        if correct_hand_head_collisions and (
            residual_collision_ratio > hard_self_collision_ratio
            or residual_min_distance < hard_self_collision_min_distance
        ):
            violations.append(
                "severe hand/head residual collision: "
                f"ratio={residual_collision_ratio:.3f}, minimum_distance={residual_min_distance:.4f}"
            )

        quality_report = {
            "passed": not violations,
            "quality_gate_enabled": bool(quality_gate),
            "max_anomaly_ratio": float(max_anomaly_ratio),
            "max_ik_p95_error": float(max_ik_p95_error),
            "max_self_collision_ratio": float(max_self_collision_ratio),
            "hard_self_collision_ratio": float(hard_self_collision_ratio),
            "hard_self_collision_min_distance": float(hard_self_collision_min_distance),
            "warnings": warnings,
            "violations": violations,
        }
        report_payload = {
            "input": str(input_path),
            "output": str(output_path),
            "frames": frame_count,
            "fps": int(fps),
            "joint_stabilization": joint_report,
            "hand_head_collision": collision_report,
            "ik": ik_report,
            "rotation_stabilization": rotation_report,
            "quality": quality_report,
        }
        if report_path is not None:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"joint stabilization: {joint_report}")
        print(f"IK stabilization: {ik_report}")
        print(f"BVH rotation stabilization: {rotation_report}")
        print(f"BVH quality: {quality_report}")
        if quality_gate and violations:
            raise RuntimeError("BVH quality gate failed: " + "; ".join(violations))
        return output_path
    finally:
        os.chdir(str(old_cwd))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert InterGen joints22 .npy to BVH.")
    parser.add_argument("--input", required=True, help="Input joints22 .npy path")
    parser.add_argument("--output", required=True, help="Output .bvh path")
    parser.add_argument("--momask-root", default=os.getenv("INTERGEN_MOMASK_ROOT", ""), help="momask-main root")
    parser.add_argument("--no-foot-ik", action="store_true", help="Disable foot IK cleanup")
    parser.add_argument("--fps", type=int, default=int(os.getenv("INTERGEN_FPS", "30")), help="BVH frame rate")
    parser.add_argument(
        "--no-upper-body-stabilization",
        action="store_true",
        help="Disable upper-body joint and quaternion stabilization",
    )
    parser.add_argument(
        "--upper-body-window",
        type=int,
        default=int(os.getenv("INTERGEN_BVH_UPPER_BODY_JOINT_WINDOW", "5")),
    )
    parser.add_argument(
        "--neck-window",
        type=int,
        default=int(os.getenv("INTERGEN_BVH_NECK_JOINT_WINDOW", "7")),
    )
    parser.add_argument(
        "--neck-max-position-correction",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_NECK_MAX_POSITION_CORRECTION", "0.04")),
    )
    parser.add_argument(
        "--head-max-position-correction",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_HEAD_MAX_POSITION_CORRECTION", "0.03")),
    )
    parser.add_argument(
        "--anomaly-degrees",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_UPPER_BODY_ANOMALY_DEGREES", "45.0")),
    )
    parser.add_argument(
        "--root-anomaly-degrees",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_ROOT_ANOMALY_DEGREES", "30.0")),
    )
    parser.add_argument("--legacy-ik", action="store_true", help="Use the old frame-independent IK solver")
    parser.add_argument("--report", help="Write a JSON conversion and quality report")
    parser.add_argument("--no-quality-gate", action="store_true", help="Do not fail on BVH quality violations")
    parser.add_argument(
        "--max-anomaly-ratio",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_MAX_ANOMALY_RATIO", "0.10")),
    )
    parser.add_argument(
        "--max-ik-p95-error",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_MAX_IK_P95_ERROR", "0.10")),
    )
    parser.add_argument(
        "--no-hand-head-collision-correction",
        action="store_true",
        help="Disable hand/forearm self-collision correction around the head",
    )
    parser.add_argument(
        "--hand-head-clearance-scale",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_HAND_HEAD_CLEARANCE_SCALE", "2.0")),
    )
    parser.add_argument(
        "--hand-head-min-clearance",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_HAND_HEAD_MIN_CLEARANCE", "0.15")),
    )
    parser.add_argument(
        "--hand-head-forearm-clearance-scale",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_HAND_HEAD_FOREARM_CLEARANCE_SCALE", "1.5")),
    )
    parser.add_argument(
        "--hand-head-forearm-min-clearance",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_HAND_HEAD_FOREARM_MIN_CLEARANCE", "0.11")),
    )
    parser.add_argument(
        "--hand-head-blend-window",
        type=int,
        default=int(os.getenv("INTERGEN_BVH_HAND_HEAD_BLEND_WINDOW", "7")),
    )
    parser.add_argument(
        "--hand-head-max-correction",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_HAND_HEAD_MAX_CORRECTION", "0.05")),
    )
    parser.add_argument(
        "--hand-head-elbow-max-correction",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_HAND_HEAD_ELBOW_MAX_CORRECTION", "0.03")),
    )
    parser.add_argument(
        "--max-self-collision-ratio",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_MAX_SELF_COLLISION_RATIO", "0.02")),
    )
    parser.add_argument(
        "--hard-self-collision-ratio",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_HARD_SELF_COLLISION_RATIO", "0.15")),
    )
    parser.add_argument(
        "--hard-self-collision-min-distance",
        type=float,
        default=float(os.getenv("INTERGEN_BVH_HARD_SELF_COLLISION_MIN_DISTANCE", "0.05")),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    momask_root = _resolve_momask_root(args.momask_root)
    output = convert_joints_to_bvh(
        input_path=Path(args.input).expanduser().resolve(),
        output_path=Path(args.output).expanduser().resolve(),
        momask_root=momask_root,
        foot_ik=not args.no_foot_ik,
        fps=args.fps,
        stabilize_upper_body=(
            _env_flag("INTERGEN_BVH_UPPER_BODY_STABILIZATION", True)
            and not args.no_upper_body_stabilization
        ),
        upper_body_window=max(1, args.upper_body_window),
        neck_window=max(1, args.neck_window),
        neck_max_position_correction=max(0.0, args.neck_max_position_correction),
        head_max_position_correction=max(0.0, args.head_max_position_correction),
        anomaly_degrees=max(0.0, args.anomaly_degrees),
        root_anomaly_degrees=max(0.0, args.root_anomaly_degrees),
        temporal_ik=(
            _env_flag("INTERGEN_BVH_TEMPORAL_IK", True)
            and not args.legacy_ik
        ),
        report_path=Path(args.report).expanduser().resolve() if args.report else None,
        quality_gate=(
            _env_flag("INTERGEN_BVH_QUALITY_GATE", True)
            and not args.no_quality_gate
        ),
        max_anomaly_ratio=max(0.0, args.max_anomaly_ratio),
        max_ik_p95_error=max(0.0, args.max_ik_p95_error),
        correct_hand_head_collisions=(
            _env_flag("INTERGEN_BVH_HAND_HEAD_COLLISION", True)
            and not args.no_hand_head_collision_correction
        ),
        hand_head_clearance_scale=max(0.1, args.hand_head_clearance_scale),
        hand_head_min_clearance=max(0.0, args.hand_head_min_clearance),
        hand_head_forearm_clearance_scale=max(0.1, args.hand_head_forearm_clearance_scale),
        hand_head_forearm_min_clearance=max(0.0, args.hand_head_forearm_min_clearance),
        hand_head_blend_window=max(1, args.hand_head_blend_window),
        hand_head_elbow_max_correction=max(0.0, args.hand_head_elbow_max_correction),
        hand_head_max_correction=max(0.0, args.hand_head_max_correction),
        max_self_collision_ratio=max(0.0, args.max_self_collision_ratio),
        hard_self_collision_ratio=max(0.0, args.hard_self_collision_ratio),
        hard_self_collision_min_distance=max(0.0, args.hard_self_collision_min_distance),
    )
    print(f"saved BVH: {output}")


if __name__ == "__main__":
    main()
