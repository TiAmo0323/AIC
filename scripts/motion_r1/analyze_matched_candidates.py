"""【离线实验工具，未应用于实际生产逻辑链路】按索引和 seed 比较两组候选。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

from analyze_ab_joints import analyze_variant


METRICS = {
    "person_a_pelvis_path_m": ("person_a", "pelvis_horizontal_path_m"),
    "person_b_pelvis_path_m": ("person_b", "pelvis_horizontal_path_m"),
    "person_a_left_wrist_path_m": ("person_a", "left_wrist_path_m"),
    "person_a_right_wrist_path_m": ("person_a", "right_wrist_path_m"),
    "person_b_left_wrist_path_m": ("person_b", "left_wrist_path_m"),
    "person_b_right_wrist_path_m": ("person_b", "right_wrist_path_m"),
    "person_a_vertical_range_m": ("person_a", "pelvis_vertical_range_m"),
    "person_b_vertical_range_m": ("person_b", "pelvis_vertical_range_m"),
    "pair_distance_mean_m": ("pair_horizontal_pelvis_distance_m", "mean"),
    "pair_distance_max_m": ("pair_horizontal_pelvis_distance_m", "maximum"),
    "pair_distance_range_m": ("pair_horizontal_pelvis_distance_m", "range"),
}


def _candidate_paths(task_root: Path, task_id: str, candidate_index: int):
    raw_root = task_root / task_id / "output" / "candidates" / "raw"
    stem = f"{task_id}_sample{candidate_index}"
    return (
        raw_root / f"{stem}_person1_joints22.npy",
        raw_root / f"{stem}_person2_joints22.npy",
    )


def _metric_values(analysis: Dict[str, object]) -> Dict[str, float]:
    return {
        name: float(analysis[group][field])
        for name, (group, field) in METRICS.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--task-a", required=True)
    parser.add_argument("--task-b", required=True)
    parser.add_argument("--label-a", default="baseline")
    parser.add_argument("--label-b", default="planner")
    parser.add_argument("--base-seed", type=int, required=True)
    parser.add_argument("--num-candidates", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    matched: List[Dict[str, object]] = []
    values_a: Dict[str, List[float]] = {name: [] for name in METRICS}
    values_b: Dict[str, List[float]] = {name: [] for name in METRICS}
    for candidate_index in range(1, args.num_candidates + 1):
        a_person1, a_person2 = _candidate_paths(args.task_root, args.task_a, candidate_index)
        b_person1, b_person2 = _candidate_paths(args.task_root, args.task_b, candidate_index)
        analysis_a = analyze_variant(args.label_a, a_person1, a_person2)
        analysis_b = analyze_variant(args.label_b, b_person1, b_person2)
        metrics_a = _metric_values(analysis_a)
        metrics_b = _metric_values(analysis_b)
        for name in METRICS:
            values_a[name].append(metrics_a[name])
            values_b[name].append(metrics_b[name])
        matched.append(
            {
                "candidate_index": candidate_index,
                "seed": (args.base_seed + candidate_index - 1) % 2147483647,
                args.label_a: metrics_a,
                args.label_b: metrics_b,
            }
        )

    summary = {}
    for name in METRICS:
        mean_a = sum(values_a[name]) / len(values_a[name])
        mean_b = sum(values_b[name]) / len(values_b[name])
        summary[name] = {
            f"{args.label_a}_mean": round(mean_a, 6),
            f"{args.label_b}_mean": round(mean_b, 6),
            "planner_minus_baseline": round(mean_b - mean_a, 6),
            "planner_over_baseline": round(mean_b / mean_a, 6) if mean_a else None,
        }

    payload = {
        "schema_version": 1,
        "task_a": args.task_a,
        "task_b": args.task_b,
        "label_a": args.label_a,
        "label_b": args.label_b,
        "base_seed": args.base_seed,
        "num_matched_candidates": args.num_candidates,
        "matched_candidates": matched,
        "mean_summary": summary,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Saved matched analysis: {args.output.resolve()}")


if __name__ == "__main__":
    main()
