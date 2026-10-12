"""Fixed-rule engineering comparison on self-authored foot-sliding fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from motionlint.benchmark.fixtures import build
from motionlint.cli.main import load_motion, _write_json
from motionlint.core.config import load_config
from motionlint.core.provenance import rule_hash
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.repair_pipeline import repair
from motionlint.repairs.support_metrics import compare_support


def run(output,config_path=None):
    output.mkdir(parents=True, exist_ok=True)
    manifest = build(output / "inputs")
    config = load_config(config_path) if config_path else load_config()
    rows = []
    for entry in manifest["motions"]:
        if entry["injection"]["type"] not in {"foot_sliding", "clean"}:
            continue
        motion = load_motion(output / "inputs" / entry["input"], fps=entry["fps"])
        motion.metadata["floor_height_m"] = 0.
        original = motion.positions.copy()
        outcome = repair(motion,config_path=config_path)
        assert np.array_equal(motion.positions, original), "Repair changed original input"
        support = compare_support(motion, outcome.motion, config["tests"]["foot_sliding"])
        result_dir = output / "results" / entry["id"]
        result_dir.mkdir(parents=True, exist_ok=True)
        np.save(result_dir / "repaired_actor1.npy", outcome.motion.positions[:, 0])
        _write_json(result_dir / "repair_report.json", outcome.to_dict())
        step = next(s for s in outcome.steps if s["repair"] == "foot_lock")
        parents = np.asarray(motion.metadata["parents"])[1:]
        bones = [np.linalg.norm(m.positions[:, :, 1:] - m.positions[:, :, parents], axis=-1)
                 for m in (motion, outcome.motion)]
        rows.append({"id": entry["id"], "kind": entry["injection"]["type"], "input_sha256": entry["sha256"],
                     "before_score": outcome.before.overall_score, "after_score": outcome.after.overall_score,
                     "gate_before": evaluate_gate(outcome.before,config_path=config_path).status, "gate_after": evaluate_gate(outcome.after,config_path=config_path).status,
                     "gate_after_reasons": evaluate_gate(outcome.after,config_path=config_path).reasons,
                     "foot_before": next(t.score for t in outcome.before.tests if t.test_name == "foot_sliding"),
                     "foot_after": next(t.score for t in outcome.after.tests if t.test_name == "foot_sliding"),
                     "status": step["status"], "variant": step.get("variant"),
                     "max_joint_shift_m": float(np.linalg.norm(outcome.motion.positions - original, axis=-1).max()),
                     "max_bone_length_change_m": float(np.abs(bones[1] - bones[0]).max()),
                     "support": support, "algorithm_version": outcome.to_dict()["algorithm_version"]})
    injected = [r for r in rows if r["kind"] == "foot_sliding"]
    clean = [r for r in rows if r["kind"] == "clean"]
    summary = {"schema_version": 1, "scope": "Self-authored engineering fixtures; not real-motion accuracy or human validation",
               "rules_version": config["version"], "rules_sha256": rule_hash(config),
               "source_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sorted((ROOT / "motionlint").rglob("*.py"))},
               "injected_count": len(injected), "clean_count": len(clean),
               "injected_gate_pass_count": sum(r["gate_after"] == "PASS" for r in injected),
               "injected_accepted_count": sum(r["status"] == "accepted" for r in injected),
               "clean_unchanged_count": sum(r["max_joint_shift_m"] == 0 for r in clean),
               "median_support_distance_reduction_ratio": float(np.median([r["support"]["original_support_distance_reduction_ratio"] for r in injected])),
               "max_joint_shift_m": max(r["max_joint_shift_m"] for r in rows),
               "max_bone_length_change_m": max(r["max_bone_length_change_m"] for r in rows), "rows": rows}
    _write_json(output / "summary.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in {"rows", "source_sha256"}}, indent=2))


def compare_runs(baseline_path, candidate_path, evidence_path):
    read = lambda p: json.loads(p.read_text(encoding="utf-8"))
    baseline, candidate = read(baseline_path), read(candidate_path)
    if (baseline["rules_sha256"] != candidate["rules_sha256"]
            or baseline["rules_version"] != candidate["rules_version"]):
        raise ValueError("Cannot compare runs evaluated under different rules")
    old = {r["id"]: r for r in baseline["rows"]}
    new = {r["id"]: r for r in candidate["rows"]}
    if old.keys() != new.keys():
        raise ValueError("Compared runs need exactly the same fixture set")
    rows = []
    for key in old:
        if (old[key]["input_sha256"] != new[key]["input_sha256"]
                or old[key]["before_score"] != new[key]["before_score"]):
            raise ValueError("Compared runs have different inputs or baseline evaluations")
        row = {"id": key, "kind": old[key]["kind"], "input_sha256": old[key]["input_sha256"],
               "before_score": old[key]["before_score"], "gate_before": old[key]["gate_before"]}
        for name, source, path in (("v4", old[key], baseline_path), ("v5", new[key], candidate_path)):
            repaired_path = path.parent / "results" / key / "repaired_actor1.npy"
            row[name] = {field: source[field] for field in ("after_score", "foot_after", "gate_after", "status",
                        "variant", "max_joint_shift_m", "max_bone_length_change_m", "algorithm_version")}
            row[name].update(support_distance_before_m=source["support"]["original_support_distance_before_m"],
                             support_distance_after_m=source["support"]["original_support_distance_after_m"],
                             support_distance_reduction_ratio=source["support"]["original_support_distance_reduction_ratio"],
                             sliding_intervals_after=source["support"]["original_support_sliding_after"],
                             gate_reasons=source.get("gate_after_reasons", []),
                             repaired_array_sha256=hashlib.sha256(repaired_path.read_bytes()).hexdigest())
        rows.append(row)
    summary_keys = ("injected_count", "clean_count", "injected_gate_pass_count", "injected_accepted_count",
                    "clean_unchanged_count", "median_support_distance_reduction_ratio", "max_joint_shift_m", "max_bone_length_change_m")
    evidence = {"schema_version": 1, "scope": "Development regression on self-authored fixtures; not blind evaluation or real-motion accuracy",
                "rules_version": baseline["rules_version"], "rules_sha256": baseline["rules_sha256"],
                "baseline": {k: baseline[k] for k in summary_keys}, "candidate": {k: candidate[k] for k in summary_keys},
                "source_sha256_v4": baseline["source_sha256"], "source_sha256_v5": candidate["source_sha256"],
                "reports_sha256": {"baseline": hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
                                   "candidate": hashlib.sha256(candidate_path.read_bytes()).hexdigest()}, "rows": rows}
    _write_json(evidence_path, evidence)
    print(json.dumps({k: v for k, v in evidence.items() if k not in {"rows", "source_sha256_v4", "source_sha256_v5"}}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, help="Saved summary.json from a run before algorithm changes")
    parser.add_argument("--evidence", type=Path, help="Publish a comparison after verifying identical rules and inputs")
    parser.add_argument("--config",type=Path)
    args = parser.parse_args()
    if bool(args.baseline) != bool(args.evidence):
        parser.error("--baseline and --evidence must be supplied together")
    run(args.output.resolve(),args.config)
    if args.baseline:
        compare_runs(args.baseline.resolve(), args.output.resolve() / "summary.json", args.evidence.resolve())
