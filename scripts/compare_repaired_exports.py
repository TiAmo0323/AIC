"""Compare actual BVH/character exports with identical inputs and render settings."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from motionlint.adapters.bvh_adapter import load_bvh_pair
from motionlint.adapters.character_adapter import load_character
from motionlint.cli.main import _write_json
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.regression import compare
from motionlint.export_intergen import fingerprint


def compare_exports(baseline_path: Path, candidate_path: Path):
    states = [json.loads(path.read_text(encoding="utf-8")) for path in (baseline_path, candidate_path)]
    if any(state["status"] != "ready" for state in states):
        raise ValueError("Both exports must be complete")
    old, new = states
    for state in states:
        digest = hashlib.sha256((Path(state["export_dir"]) / "quality.yaml").read_bytes()).hexdigest()
        if digest != state["config_sha256"]:
            raise ValueError("Frozen quality configuration was modified")
        snapshots = [Path(state["export_dir"]) / row["name"] for row in state["input_fingerprints"]]
        if fingerprint(snapshots) != state["input_fingerprints"]:
            raise ValueError("Frozen input arrays were modified")
    for key in ("input_fingerprints", "config_sha256"):
        if old[key] != new[key]:
            raise ValueError(f"Changed experimental control: {key}")
    manifests = [json.loads(Path(state["manifest_path"]).read_text(encoding="utf-8")) for state in states]
    settings = ("fps", "generated_frames", "source_frame_counts", "duration_seconds", "max_render_frames",
                "skin_id", "person_skin_ids", "target_fbx_files", "mapping_files", "render_size",
                "camera_distance_scale", "motion_prompt", "motion_profile", "target_spacing", "core_smoothing_window",
                "spine_smoothing_window", "foot_lock_enabled", "foot_lock_max_correction",
                "head_world_stabilization_enabled", "hand_torso_collision_enabled")
    for key in settings:
        if manifests[0].get(key) != manifests[1].get(key):
            raise ValueError(f"Changed render setting: {key}")
    stages = {}
    for stage in ("repaired_bvh", "repaired_character"):
        reports = []
        gates = []
        for state in states:
            sequence = load_bvh_pair(state["bvh_files"]) if stage == "repaired_bvh" else load_character(state["character_path"])
            policy = Path(state["export_dir"]) / "quality.yaml"
            report = inspect(sequence, config_path=policy)
            gate = evaluate_gate(report, config_path=policy)
            if report.overall_score != state["quality"][stage]["score"] or gate.to_dict() != state["quality"][stage]["gate"]:
                raise ValueError("Independent stage result differs from recorded result")
            reports.append(report)
            gates.append(gate.to_dict())
        stages[stage] = {"baseline_score": reports[0].overall_score, "candidate_score": reports[1].overall_score,
                         "baseline_gate": gates[0], "candidate_gate": gates[1],
                         "comparison": compare(*reports, config_path=Path(new["export_dir"]) / "quality.yaml")}
    return {"baseline_export": old["export_dir"], "candidate_export": new["export_dir"],
            "input_fingerprints": new["input_fingerprints"], "config_sha256": new["config_sha256"],
            "same_render_settings": {key: manifests[1].get(key) for key in settings}, "stages": stages,
            "converter_selection": new.get("converter_selection"), "video_path": new["video_path"],
            "limits": "Development sample comparison; regression PASS does not mean strict quality gate PASS."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    row = compare_exports(args.baseline, args.candidate)
    _write_json(args.output, row)
    print(json.dumps(row["stages"], ensure_ascii=False, indent=2))
