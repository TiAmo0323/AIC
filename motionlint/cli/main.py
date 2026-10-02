"""Inspect, repair, and compare local motion files without model inference."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import numpy as np

from motionlint.adapters.bvh_adapter import load_bvh, load_bvh_pair
from motionlint.adapters.intergen_adapter import load_intergen_joints
from motionlint.adapters.lodge_adapter import load_lodge_npy
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.regression import compare
from motionlint.pipeline.repair_pipeline import repair


def load_motion(path: str | Path, actor2: str | Path | None = None, fps: float = 30, *, unit_scale: float = 1., up_axis: int = 1, joint_mapping: dict | None = None):
    if not math.isfinite(unit_scale) or unit_scale <= 0:
        raise ValueError("unit_scale must be positive and finite")
    path = Path(path)
    if path.suffix.lower() == ".bvh":
        if actor2 is not None:
            return load_bvh_pair([path, actor2], unit_scale=unit_scale, up_axis=up_axis, joint_mapping=joint_mapping)
        return load_bvh(path, unit_scale=unit_scale, up_axis=up_axis, joint_mapping=joint_mapping)
    if path.suffix.lower() != ".npy":
        raise ValueError("Expected .npy or .bvh input")
    if unit_scale != 1. or up_axis != 1 or joint_mapping:
        raise ValueError("NPY uses the fixed metre/Y-up skeleton convention; BVH options require .bvh")
    data = np.load(path, allow_pickle=False, mmap_mode="r")
    if not np.isfinite(data).all():
        raise ValueError("Motion input contains NaN or Inf")
    if data.ndim == 2 and data.shape[1] in {135, 139, 315, 319}:
        if actor2 is not None:
            raise ValueError("LODGE motion cannot be paired with --actor2")
        return load_lodge_npy(path, fps=fps)
    if data.ndim == 3 and data.shape[1:] == (22, 3):
        return load_intergen_joints([path, actor2] if actor2 is not None else path, fps=fps)
    raise ValueError(f"Unsupported NPY motion shape: {data.shape}")


def _json_safe(value):
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def _write_report(folder: Path, report) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    _write_json(folder / "motionlint_report.json", report.to_dict())
    _write_json(folder / "issues.json", [issue.to_dict() for test in report.tests for issue in test.issues])
    with (folder / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["test", "status", "score", "issue_count"])
        writer.writeheader()
        for test in report.tests:
            writer.writerow({"test": test.test_name, "status": test.status, "score": test.score, "issue_count": len(test.issues)})


def _print_report(report, gate) -> None:
    print(f"MotionLint  {report.metadata['source']}  {report.metadata['frame_count']} frames  {report.metadata['fps']:.2f} FPS")
    for test in report.tests:
        print(f"[{test.status:4}] {test.test_name:24} {test.score:6.2f}  issues={len(test.issues)}")
    print(f"Overall: {report.overall_score:.2f}  Quality Gate: {gate.status}")
    for reason in gate.reasons[:10]:
        print(f"  - {reason}")


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="motionlint", description="Quality checks and repair for human motion")
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check", help="Inspect a motion file")
    check_parser.add_argument("input")
    check_parser.add_argument("--actor2")
    check_parser.add_argument("--fps", type=float, default=30)
    check_parser.add_argument("--unit-scale", type=float, default=1., help="BVH stored-unit to metre scale")
    check_parser.add_argument("--up-axis", type=int, choices=(0, 1, 2), default=1, help="BVH vertical coordinate index")
    check_parser.add_argument("--output-dir", type=Path)
    repair_parser = sub.add_parser("repair", help="Repair and re-inspect a motion file")
    repair_parser.add_argument("input")
    repair_parser.add_argument("--actor2")
    repair_parser.add_argument("--fps", type=float, default=30)
    repair_parser.add_argument("--output-dir", type=Path)
    compare_parser = sub.add_parser("compare", help="Detect metric regression")
    compare_parser.add_argument("baseline")
    compare_parser.add_argument("candidate")
    compare_parser.add_argument("--baseline-actor2")
    compare_parser.add_argument("--candidate-actor2")
    compare_parser.add_argument("--fps", type=float, default=30)
    compare_parser.add_argument("--output-dir", type=Path)
    batch_parser = sub.add_parser("batch", help="Inspect a JSON manifest of existing motion files")
    batch_parser.add_argument("manifest")
    batch_parser.add_argument("--output-dir", type=Path, default=Path("reports") / "batch")
    for command_parser in (check_parser, repair_parser, compare_parser, batch_parser):
        command_parser.add_argument("--config", type=Path)
        if command_parser is not check_parser:
            command_parser.add_argument("--unit-scale", type=float, default=1.)
            command_parser.add_argument("--up-axis", type=int, choices=(0, 1, 2), default=1)
        command_parser.add_argument("--joint-map", type=Path, help="JSON stored-name to canonical-name mapping for BVH")
    args = parser.parse_args(argv)
    mapping = json.loads(args.joint_map.read_text(encoding="utf-8")) if args.joint_map else None
    if mapping is not None and not isinstance(mapping, dict):
        raise ValueError("Joint mapping must be a JSON object")
    options = dict(unit_scale=args.unit_scale, up_axis=args.up_axis, joint_mapping=mapping)

    if args.command == "batch":
        from motionlint.pipeline.experiment import run_manifest

        summary = run_manifest(args.manifest, args.output_dir, config_path=args.config, **options)
        print(
            f"Batch: {summary['success_count']}/{summary['count']} inspected; "
            f"quality gate PASS {summary['gate_pass_count']}"
        )
        return 2 if summary["success_count"] != summary["count"] else (0 if summary["gate_pass_count"] == summary["count"] else 1)

    if args.command == "compare":
        baseline = inspect(load_motion(args.baseline, args.baseline_actor2, args.fps, **options), config_path=args.config)
        candidate = inspect(load_motion(args.candidate, args.candidate_actor2, args.fps, **options), config_path=args.config)
        comparison = compare(baseline, candidate, config_path=args.config)
        folder = args.output_dir or Path("reports") / f"{Path(args.baseline).stem}_vs_{Path(args.candidate).stem}"
        _write_report(folder / "baseline", baseline)
        _write_report(folder / "candidate", candidate)
        _write_json(folder / "comparison.json", comparison)
        print(f"{comparison['status']}  overall change: {comparison['overall_change']:+.2f}")
        for row in comparison["tests"]:
            print(f"{row['test']:24} {row['baseline']:6.2f} -> {row['candidate']:6.2f}  {row['change']:+6.2f}  {row['status']}")
        return 1 if comparison["status"] != "PASS" else 0

    motion = load_motion(args.input, args.actor2, args.fps, **options)
    folder = args.output_dir or Path("reports") / Path(args.input).stem
    if args.command == "check":
        report = inspect(motion, config_path=args.config)
        gate = evaluate_gate(report, config_path=args.config)
        _write_report(folder, report)
        _write_json(folder / "quality_gate.json", gate.to_dict())
        _print_report(report, gate)
        return 1 if gate.status == "FAIL" else 0

    if motion.source not in {"lodge", "intergen"}:
        raise ValueError("Repair currently supports LODGE and InterGen NPY, not BVH")
    prospective = [folder / "repaired.npy"] if motion.source == "lodge" else [folder / f"repaired_actor{a+1}.npy" for a in range(motion.actor_count)]
    inputs = {Path(args.input).resolve()} | ({Path(args.actor2).resolve()} if args.actor2 else set())
    if any(path.resolve() in inputs for path in prospective):
        raise ValueError("Repair output would overwrite original input; choose a different output directory")
    outcome = repair(motion, config_path=args.config)
    _write_report(folder / "before", outcome.before)
    _write_report(folder / "after", outcome.after)
    _write_json(folder / "repair_report.json", outcome.to_dict())
    _write_json(folder / "comparison.json", compare(outcome.before, outcome.after, config_path=args.config))
    if motion.source == "lodge":
        raw = outcome.raw_lodge if outcome.raw_lodge is not None else np.load(args.input, allow_pickle=False)
        np.save(folder / "repaired.npy", raw)
    else:
        for actor in range(outcome.motion.actor_count):
            np.save(folder / f"repaired_actor{actor + 1}.npy", outcome.motion.positions[:, actor])
    gate = evaluate_gate(outcome.after, config_path=args.config)
    _write_json(folder / "quality_gate.json", gate.to_dict())
    _print_report(outcome.after, gate)
    print(f"Improvement: {outcome.after.overall_score - outcome.before.overall_score:+.2f}")
    return 1 if gate.status == "FAIL" else 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except (OSError, ValueError, TypeError, ImportError, KeyError, RuntimeError) as exc:
        print(f"MotionLint input/runtime error: {exc}", file=sys.stderr)
        return 2
