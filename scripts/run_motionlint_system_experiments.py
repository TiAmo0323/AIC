"""Four isolated experiments with source hashes, rejected trials and CSV evidence."""
import argparse
import csv
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from motionlint.cli.main import load_motion, _write_json, _write_report
from motionlint.adapters.lodge_adapter import normalize_lodge_array
from motionlint.core.config import load_config, DEFAULT_CONFIG
from motionlint.core.quality_gate import evaluate_gate
from motionlint.core.foot_support import estimate_support
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.regression import compare
from motionlint.repairs.seam_repair import repair_seams
from motionlint.repairs.foot_lock import repair_foot_sliding
from motionlint.repairs.collision_repair import repair_collisions


def measurements(motion, report):
    tests = {test.test_name: test for test in report.tests}
    result = {"score": report.overall_score, "gate": evaluate_gate(report).to_dict(),
              "tests": {name: {"status": test.status, "score": test.score, "metrics": test.metrics} for name, test in tests.items()}}
    boundaries = np.arange(256, motion.frame_count, 256)
    if len(boundaries) and motion.rotation_matrices is not None:
        relative = motion.rotation_matrices[1:] @ np.swapaxes(motion.rotation_matrices[:-1], -1, -2)
        step = np.degrees(np.arccos(np.clip((np.trace(relative, axis1=-2, axis2=-1) - 1) / 2, -1, 1)))
        indices = np.unique(np.concatenate([np.arange(max(0, frame - 3), min(len(step) - 1, frame + 2)) for frame in boundaries]))
        result["boundary_angular_acceleration_deg_s2"] = float(np.abs(np.diff(step, axis=0))[indices].max() * motion.fps ** 2)
        result["boundary_root_step_m"] = float(np.linalg.norm(np.diff(motion.root_translation, axis=0)[boundaries - 1], axis=-1).max())
    return result


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    config = load_config()
    (output / "quality.yaml").write_bytes(DEFAULT_CONFIG.read_bytes())
    code_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((ROOT / "motionlint").rglob("*.py"))}
    baseline = json.loads((ROOT / "experiments/baseline_motions.json").read_text(encoding="utf-8"))["motions"]
    validation = json.loads((ROOT / "reports/validation_20260930/motions.json").read_text(encoding="utf-8"))["motions"]
    entries = []
    seen = set()
    for entry in baseline + validation:
        paths = [Path(entry["input"])] + ([Path(entry["actor2"])] if entry.get("actor2") else [])
        paths = [(ROOT / "experiments" / path).resolve() if not path.is_absolute() else path for path in paths]
        # Raw and preprocessed motions from one generation are not independent.
        if "raw" in entry["name"] or entry["name"] == "intergen_handshake_b":
            continue
        digest = hashlib.sha256(b"".join(path.read_bytes() for path in paths)).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        entries.append({"name": entry["name"], "paths": paths, "sha256": digest,
                        "sample_role": "reused_validation_for_system_evaluation" if entry in validation else "development"})
    records = []
    for entry in entries:
        motion = load_motion(entry["paths"][0], entry["paths"][1] if len(entry["paths"]) > 1 else None)
        trials = ["foot_lock"] + (["seam_repair"] if motion.source == "lodge" else ["collision_repair"])
        for method in trials:
            source = motion
            raw = np.load(entry["paths"][0], allow_pickle=False) if motion.source == "lodge" else None
            if method == "seam_repair":
                raw_path = entry["paths"][0].with_name(entry["paths"][0].stem + ".raw.npy")
                if raw_path.is_file():
                    raw = np.load(raw_path, allow_pickle=False)
                    source = normalize_lodge_array(raw, source_path=raw_path)
            actual_paths = [raw_path] if method == "seam_repair" and raw_path.is_file() else entry["paths"]
            source_digest = hashlib.sha256(b"".join(path.read_bytes() for path in actual_paths)).hexdigest()
            before = inspect(source)
            folder = output / method / entry["name"]
            _write_report(folder / "before", before)
            started = time.perf_counter()
            try:
                if method == "seam_repair":
                    candidate, _, details = repair_seams(source, raw=raw, **config["repairs"][method])
                    target = "temporal_continuity"
                elif method == "foot_lock":
                    foot = next(test for test in before.tests if test.test_name == "foot_sliding")
                    candidate, _, details = repair_foot_sliding(source, foot.issues, raw=raw, anchor_method="interval",
                        correction_strength=.5, root_follow=motion.source == "lodge", support_settings=config["tests"]["foot_sliding"],
                        **config["repairs"][method])
                    target = "foot_sliding"
                else:
                    candidate, details = repair_collisions(source)
                    target = "collision"
                elapsed = time.perf_counter() - started
                after = inspect(candidate)
                comparison = compare(before, after)
                old_tests = {test.test_name: test for test in before.tests}
                new_tests = {test.test_name: test for test in after.tests}
                accepted = (comparison["status"] == "PASS" and after.overall_score >= before.overall_score
                            and new_tests[target].score > old_tests[target].score
                            and not any(test.status == "FAIL" and old_tests[test.test_name].status != "FAIL" for test in after.tests))
                support_guard = None
                if method == "foot_lock":
                    support = estimate_support(source, config["tests"]["foot_sliding"])
                    counts = []
                    for sequence in (source, candidate):
                        axes = [axis for axis in range(3) if axis != int(sequence.metadata.get("up_axis", 1))]
                        speed = np.linalg.norm(np.diff(sequence.positions[:, :, support.feet][:, :, :, axes], axis=0), axis=-1) * sequence.fps
                        counts.append(int(np.count_nonzero((speed > config["tests"]["foot_sliding"]["horizontal_speed_m_s"]) & support.intervals)))
                    support_guard = {"sliding_before": counts[0], "sliding_candidate": counts[1], "improved": counts[1] < counts[0]}
                    accepted = accepted and support_guard["improved"]
                wrist_ids = [source.joint_names.index(name) for name in ("LeftHand", "RightHand")]
                displacement = float(np.linalg.norm(candidate.positions[:, :, wrist_ids] - source.positions[:, :, wrist_ids], axis=-1).max())
                _write_report(folder / "candidate", after)
                row = {"name": entry["name"], "sample_role": entry["sample_role"], "method": method,
                       "input_sha256": source_digest, "source_paths": [str(path) for path in actual_paths],
                       "seconds": elapsed, "accepted": accepted, "before": measurements(source, before),
                       "candidate": measurements(candidate, after), "selected_score": after.overall_score if accepted else before.overall_score,
                       "comparison": comparison, "support_guard": support_guard, "max_wrist_displacement_m": displacement, "detail": details}
            except Exception as exc:
                row = {"name": entry["name"], "method": method, "accepted": False, "error": f"{type(exc).__name__}: {exc}"}
            _write_json(folder / "experiment.json", row)
            records.append(row)
    # Deterministic positive control: improve a seam while injecting sliding.
    frames = 600
    raw = np.zeros((frames, 139), dtype=np.float32)
    raw[:, :4] = 1
    raw[:, 5] = 1.2
    raw[:, 7:] = np.tile([1, 0, 0, 0, 1, 0], 22)
    raw[256:, 4] = .3
    source = normalize_lodge_array(raw)
    candidate, smooth_raw, _ = repair_seams(source, raw=raw)
    injected = smooth_raw.copy()
    injected[:, 4] += np.arange(frames) * .012
    candidate = normalize_lodge_array(injected)
    before, after = inspect(source), inspect(candidate)
    comparison = compare(before, after)
    if comparison["status"] != "REGRESSION DETECTED":
        raise RuntimeError("Injected regression was not detected")
    for name, array, report in (("baseline", raw, before), ("candidate", injected, after)):
        np.save(output / f"regression_{name}.npy", array)
        _write_report(output / "regression" / name, report)
    regression = {"source": "synthetic_control", "purpose": "Seam smoothing plus injected 0.012 m/frame horizontal slide",
                  "before": measurements(source, before), "candidate": measurements(candidate, after), "comparison": comparison}
    _write_json(output / "regression/experiment.json", regression)
    ranking = sorted([{"name": row["name"], "before": row["before"]["score"], "candidate": row["candidate"]["score"],
                       "selected": row["selected_score"], "accepted": row["accepted"]} for row in records if row["method"] == "foot_lock" and "error" not in row], key=lambda row: row["selected"], reverse=True)
    summary = {"policy_version": config["version"], "policy_sha256": hashlib.sha256(DEFAULT_CONFIG.read_bytes()).hexdigest(),
               "code_hashes": code_hashes, "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "unique_source_generations": len(entries), "records": records,
               "regression_control": regression, "candidate_ranking": ranking,
               "limits": "Reuses development and previously seen validation motions, not a new held-out benchmark. LODGE music inputs are synthetic rhythm tests. Each repair is isolated; rejected candidates are retained. Character-video evidence is evaluated separately."}
    _write_json(output / "summary.json", summary)
    with (output / "summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        fields = ["name", "method", "sample_role", "accepted", "seconds", "before_score", "candidate_score", "selected_score", "regression", "gate_before", "gate_candidate", "foot_ratio_before", "foot_ratio_candidate", "foot_mean_before", "foot_mean_candidate", "collision_frames_before", "collision_frames_candidate", "wrist_displacement_m", "error"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in records:
            if "error" in row:
                writer.writerow({key: row.get(key) for key in ("name", "method", "accepted", "error")})
                continue
            old, new = row["before"], row["candidate"]
            writer.writerow({"name": row["name"], "method": row["method"], "sample_role": row["sample_role"], "accepted": row["accepted"], "seconds": row["seconds"], "before_score": old["score"], "candidate_score": new["score"], "selected_score": row["selected_score"], "regression": row["comparison"]["status"], "gate_before": old["gate"]["status"], "gate_candidate": new["gate"]["status"], "foot_ratio_before": old["tests"]["foot_sliding"]["metrics"].get("sliding_frame_ratio"), "foot_ratio_candidate": new["tests"]["foot_sliding"]["metrics"].get("sliding_frame_ratio"), "foot_mean_before": old["tests"]["foot_sliding"]["metrics"].get("mean_sliding_velocity_m_s"), "foot_mean_candidate": new["tests"]["foot_sliding"]["metrics"].get("mean_sliding_velocity_m_s"), "collision_frames_before": old["tests"]["collision"]["metrics"].get("collision_frame_count"), "collision_frames_candidate": new["tests"]["collision"]["metrics"].get("collision_frame_count"), "wrist_displacement_m": row["max_wrist_displacement_m"]})
    # A long-form numeric table keeps every scalar metric usable for plotting.
    with (output / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "experiment", "stage", "test", "metric", "value"])
        for row in records:
            if "error" in row:
                continue
            for stage in ("before", "candidate"):
                for test, result in row[stage]["tests"].items():
                    for metric, value in result["metrics"].items():
                        if isinstance(value, (float, int)) and not isinstance(value, bool):
                            writer.writerow([row["name"], row["method"], stage, test, metric, value])
                for key in ("boundary_angular_acceleration_deg_s2", "boundary_root_step_m"):
                    if key in row[stage]:
                        writer.writerow([row["name"], row["method"], stage, "temporal_continuity", key, row[stage][key]])
    print(json.dumps({"sources": len(entries), "trials": len(records), "errors": sum("error" in row for row in records), "regression": comparison["status"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "reports/system_experiments_20261002")
    run(parser.parse_args().output)
