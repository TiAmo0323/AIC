"""【实验功能，未应用于实际生产逻辑链路】InterGen 候选池人工审计工具。

自动指标只是运动学代理，用于帮助人工浏览候选，不能判断羽毛球或其他动作语义。
审计清单在生产物理选优完成后旁路生成；人工审核不会重新排序候选、修改
selected_sample 或替换最终输出，当前生产前端也不会启用该功能。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np


AUDIT_SCHEMA_VERSION = 1
PELVIS = 0
NECK = 12
LEFT_SHOULDER = 16
RIGHT_SHOULDER = 17
LEFT_WRIST = 20
RIGHT_WRIST = 21


def _round(value: float, digits: int = 6) -> float:
    return round(float(value), digits)


def _unit_rows(values: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(values, axis=-1, keepdims=True)
    return values / np.maximum(norms, 1e-8)


def _horizontal(values: np.ndarray) -> np.ndarray:
    result = np.asarray(values, dtype=np.float64).copy()
    # InterGen's recovered joints use Y as the vertical axis.
    result[..., 1] = 0.0
    return result


def _path_length(points: np.ndarray) -> float:
    if len(points) < 2:
        return 0.0
    return float(np.linalg.norm(np.diff(points, axis=0), axis=-1).sum())


def _load_joint_pair(raw_joint_files: Sequence[str]) -> tuple[np.ndarray, np.ndarray]:
    if len(raw_joint_files) < 2:
        raise ValueError("Candidate must contain two raw joints files")
    actors = []
    for raw_path in raw_joint_files[:2]:
        path = Path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(f"Raw joints file not found: {path}")
        joints = np.asarray(np.load(path, allow_pickle=False), dtype=np.float64)
        if joints.ndim != 3 or joints.shape[1] < 22 or joints.shape[2] != 3:
            raise ValueError(f"Expected [frames, >=22, 3] joints, got {joints.shape} from {path}")
        if not np.isfinite(joints).all():
            raise ValueError(f"Raw joints contain non-finite values: {path}")
        actors.append(joints[:, :22, :])
    frame_count = min(len(actors[0]), len(actors[1]))
    if frame_count < 2:
        raise ValueError("Candidate must contain at least two frames for each actor")
    return actors[0][:frame_count], actors[1][:frame_count]


def _arm_metrics(joints: np.ndarray, fps: int) -> Dict[str, object]:
    arms = {}
    for side, shoulder_index, wrist_index in (
        ("left", LEFT_SHOULDER, LEFT_WRIST),
        ("right", RIGHT_SHOULDER, RIGHT_WRIST),
    ):
        wrist = joints[:, wrist_index]
        shoulder = joints[:, shoulder_index]
        velocity = np.diff(wrist, axis=0) * float(fps)
        speed = np.linalg.norm(velocity, axis=-1)
        peak_offset = int(np.argmax(speed)) if len(speed) else 0
        horizontal_velocity = _horizontal(velocity)
        velocity_unit = _unit_rows(horizontal_velocity)
        reversal_count = 0
        if len(velocity_unit) >= 2:
            direction_cosine = np.sum(velocity_unit[1:] * velocity_unit[:-1], axis=-1)
            moving = (
                np.linalg.norm(horizontal_velocity[1:], axis=-1) > 1e-5
            ) & (
                np.linalg.norm(horizontal_velocity[:-1], axis=-1) > 1e-5
            )
            reversal_count = int(np.sum((direction_cosine < -0.25) & moving))
        relative_wrist = wrist - shoulder
        arms[side] = {
            "wrist_path_length": _round(_path_length(wrist)),
            "wrist_speed_p95": _round(np.percentile(speed, 95) if len(speed) else 0.0),
            "wrist_speed_peak": _round(np.max(speed) if len(speed) else 0.0),
            "peak_speed_frame": peak_offset + 1,
            "peak_speed_time_seconds": _round((peak_offset + 1) / float(max(fps, 1)), 3),
            "shoulder_relative_vertical_range": _round(np.ptp(relative_wrist[:, 1])),
            "horizontal_direction_reversal_count": reversal_count,
        }

    dominant_side = max(
        arms,
        key=lambda side: (
            float(arms[side]["wrist_path_length"]),
            float(arms[side]["wrist_speed_peak"]),
        ),
    )
    return {
        "dominant_motion_side": dominant_side,
        "dominant_peak_speed_frame": int(arms[dominant_side]["peak_speed_frame"]),
        "left": arms["left"],
        "right": arms["right"],
    }


def compute_candidate_metrics(
    actor_a: np.ndarray,
    actor_b: np.ndarray,
    fps: int = 30,
) -> Dict[str, object]:
    """Compute navigation proxies without making a semantic pass/fail claim."""

    frame_count = min(len(actor_a), len(actor_b))
    actor_a = np.asarray(actor_a[:frame_count], dtype=np.float64)
    actor_b = np.asarray(actor_b[:frame_count], dtype=np.float64)
    if frame_count < 2:
        raise ValueError("At least two frames are required")

    pelvis_a = actor_a[:, PELVIS]
    pelvis_b = actor_b[:, PELVIS]
    separation = np.linalg.norm(_horizontal(pelvis_b - pelvis_a), axis=-1)

    def body_forward(joints: np.ndarray) -> np.ndarray:
        right = joints[:, RIGHT_SHOULDER] - joints[:, LEFT_SHOULDER]
        up = joints[:, NECK] - joints[:, PELVIS]
        return _unit_rows(_horizontal(np.cross(right, up)))

    forward_a = body_forward(actor_a)
    forward_b = body_forward(actor_b)
    direction_ab = _unit_rows(_horizontal(pelvis_b - pelvis_a))
    direction_ba = -direction_ab
    toward_a = np.sum(forward_a * direction_ab, axis=-1)
    toward_b = np.sum(forward_b * direction_ba, axis=-1)
    forward_opposition = np.sum(forward_a * forward_b, axis=-1)
    facing_threshold = 0.5  # within 60 degrees of the other actor

    arm_a = _arm_metrics(actor_a, fps)
    arm_b = _arm_metrics(actor_b, fps)
    a_peak_frame = int(arm_a["dominant_peak_speed_frame"])
    b_peak_frame = int(arm_b["dominant_peak_speed_frame"])

    return {
        "metric_scope": "kinematic-proxies-only-not-semantic-acceptance",
        "frames": frame_count,
        "fps": int(fps),
        "duration_seconds": _round(frame_count / float(max(fps, 1)), 3),
        "pair_geometry": {
            "horizontal_distance_min": _round(np.min(separation)),
            "horizontal_distance_mean": _round(np.mean(separation)),
            "horizontal_distance_max": _round(np.max(separation)),
            "horizontal_distance_range": _round(np.ptp(separation)),
            "forward_opposition_ratio": _round(np.mean(forward_opposition < -0.5)),
            "mutual_facing_proxy_ratio": _round(
                np.mean((toward_a > facing_threshold) & (toward_b > facing_threshold))
            ),
            "actor_a_toward_actor_b_mean_cosine": _round(np.mean(toward_a)),
            "actor_b_toward_actor_a_mean_cosine": _round(np.mean(toward_b)),
        },
        "actor_a_arm_motion": arm_a,
        "actor_b_arm_motion": arm_b,
        "timing_proxy": {
            "actor_a_dominant_wrist_peak_frame": a_peak_frame,
            "actor_b_dominant_wrist_peak_frame": b_peak_frame,
            "actor_b_minus_actor_a_peak_seconds": _round(
                (b_peak_frame - a_peak_frame) / float(max(fps, 1)), 3
            ),
        },
    }


def _human_review_template() -> Dict[str, object]:
    return {
        "review_status": "pending",
        "mutual_facing": None,
        "racket_swing_proxy": None,
        "receiver_ready_and_reacts": None,
        "role_consistency": None,
        "badminton_semantic_match": None,
        "semantic_pass": None,
        "reviewer": "",
        "notes": "",
    }


def write_candidate_audit_manifest(
    manifest_path: Path,
    *,
    task_id: str,
    prompt: str,
    candidate_summaries: Sequence[Dict[str, object]],
    selected_sample: Optional[int],
    motion_plan: Optional[Dict[str, object]] = None,
    experiment_group: str = "",
    experiment_variant: str = "baseline",
) -> Path:
    """Write an atomic audit manifest with metrics and pending human fields."""

    candidates: List[Dict[str, object]] = []
    retained_video_count = 0
    metrics_count = 0
    for summary in candidate_summaries:
        candidate_index = int(summary.get("candidate_index") or 0)
        video_path = Path(str(summary.get("file_path") or "")).resolve()
        video_exists = video_path.is_file()
        if video_exists:
            retained_video_count += 1
        raw_joint_files = [
            str(Path(str(path)).resolve())
            for path in list(summary.get("raw_joints_files") or [])
        ]
        automatic_metrics: Optional[Dict[str, object]] = None
        metric_error = ""
        try:
            actor_a, actor_b = _load_joint_pair(raw_joint_files)
            automatic_metrics = compute_candidate_metrics(
                actor_a,
                actor_b,
                fps=int(summary.get("fps") or 30),
            )
            metrics_count += 1
        except Exception as exc:  # Preserve the rest of the audit pool.
            metric_error = str(exc)

        candidates.append(
            {
                "candidate_index": candidate_index,
                "seed": int(summary.get("seed") or 0),
                "selected_by_physical_quality": bool(summary.get("selected")),
                "video": {
                    "file_path": str(video_path),
                    "file_name": video_path.name,
                    "exists": video_exists,
                    "file_size": int(summary.get("file_size") or 0),
                    "download_path": (
                        f"/v1/intergen/tasks/{task_id}/candidates/{candidate_index}/download"
                        if video_exists
                        else None
                    ),
                },
                "raw_joints_files": raw_joint_files,
                "self_collision": dict(summary.get("self_collision") or {}),
                "automatic_metrics": automatic_metrics,
                "automatic_metric_error": metric_error,
                "human_review": _human_review_template(),
            }
        )

    payload: Dict[str, object] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "audit_type": "candidate-pool-semantic-feasibility",
        "status": "awaiting-human-review",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
        "experiment": {
            "group": experiment_group,
            "variant": experiment_variant,
        },
        "prompt": prompt,
        "motion_plan": motion_plan,
        "selected_sample": selected_sample,
        "automatic_metrics_disclaimer": (
            "Kinematic proxies support navigation only. They do not prove that a candidate "
            "faces correctly, swings a racket, preserves roles, or looks like badminton."
        ),
        "acceptance_rule": {
            "semantic_pass_requires_all_true": [
                "mutual_facing",
                "racket_swing_proxy",
                "receiver_ready_and_reacts",
                "role_consistency",
                "badminton_semantic_match",
            ],
            "gate": (
                "At least one human-reviewed semantic_pass=true candidate is required before "
                "automated candidate selection is considered."
            ),
        },
        "summary": {
            "candidate_count": len(candidates),
            "retained_video_count": retained_video_count,
            "automatic_metrics_completed": metrics_count,
            "human_reviewed_count": 0,
            "semantic_pass_count": 0,
            "gate_decision": "pending-human-review",
        },
        "candidates": candidates,
    }
    manifest_path = manifest_path.resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(manifest_path)
    return manifest_path
