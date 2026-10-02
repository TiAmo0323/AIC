"""【离线实验工具，未应用于实际生产逻辑链路】比较 A/B 双人 joints22 输出。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import numpy as np


PELVIS = 0
LEFT_WRIST = 20
RIGHT_WRIST = 21


def _load(path: Path) -> np.ndarray:
    joints = np.load(path, allow_pickle=False)
    if joints.ndim != 3 or joints.shape[1:] != (22, 3):
        raise ValueError(f"Expected [frames, 22, 3] joints at {path}, got {joints.shape}")
    return joints.astype(np.float64, copy=False)


def _path_length(points: np.ndarray) -> float:
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def _person_metrics(joints: np.ndarray) -> Dict[str, float]:
    pelvis = joints[:, PELVIS]
    horizontal_pelvis = pelvis[:, [0, 2]]
    wrists = joints[:, [LEFT_WRIST, RIGHT_WRIST]]
    wrist_speed = np.linalg.norm(np.diff(wrists, axis=0), axis=2)
    relative_wrist_height = wrists[:, :, 1] - pelvis[:, None, 1]
    return {
        "pelvis_horizontal_path_m": round(_path_length(horizontal_pelvis), 6),
        "pelvis_horizontal_net_m": round(
            float(np.linalg.norm(horizontal_pelvis[-1] - horizontal_pelvis[0])), 6
        ),
        "pelvis_vertical_range_m": round(float(np.ptp(pelvis[:, 1])), 6),
        "left_wrist_path_m": round(_path_length(wrists[:, 0]), 6),
        "right_wrist_path_m": round(_path_length(wrists[:, 1]), 6),
        "max_wrist_step_m": round(float(wrist_speed.max()), 6),
        "max_wrist_height_above_pelvis_m": round(float(relative_wrist_height.max()), 6),
    }


def analyze_variant(label: str, person_a_path: Path, person_b_path: Path) -> Dict[str, object]:
    person_a = _load(person_a_path)
    person_b = _load(person_b_path)
    frames = min(len(person_a), len(person_b))
    person_a = person_a[:frames]
    person_b = person_b[:frames]
    pelvis_distance = np.linalg.norm(
        person_a[:, PELVIS][:, [0, 2]] - person_b[:, PELVIS][:, [0, 2]],
        axis=1,
    )
    return {
        "label": label,
        "frames": frames,
        "person_a": _person_metrics(person_a),
        "person_b": _person_metrics(person_b),
        "pair_horizontal_pelvis_distance_m": {
            "minimum": round(float(pelvis_distance.min()), 6),
            "mean": round(float(pelvis_distance.mean()), 6),
            "maximum": round(float(pelvis_distance.max()), 6),
            "range": round(float(np.ptp(pelvis_distance)), 6),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--variant",
        action="append",
        nargs=3,
        metavar=("LABEL", "PERSON_A_NPY", "PERSON_B_NPY"),
        required=True,
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    variants: List[Dict[str, object]] = []
    for label, person_a, person_b in args.variant:
        variants.append(analyze_variant(label, Path(person_a), Path(person_b)))
    payload: Dict[str, object] = {
        "schema_version": 1,
        "coordinate_assumption": "HumanML3D joints22: Y vertical; X/Z horizontal",
        "variants": variants,
    }
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(f"Saved joint analysis: {args.output.resolve()}")


if __name__ == "__main__":
    main()
