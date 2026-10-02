"""Explain gate failures without changing policy or overwriting task outputs."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from LODGE_api.lodge2bvh import BVH_OFFSETS, BVH_PARENTS, SMPL_TO_BVH22
from motionlint.cli.main import _write_json, _write_report, load_motion
from motionlint.core.config import load_config
from motionlint.core.foot_support import estimate_support
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.repair_pipeline import repair
from motionlint.tests import foot_sliding
from motionlint.tests.common import segments


def foot_stats(motion) -> dict:
    settings = load_config()["tests"]["foot_sliding"]
    contact = estimate_support(motion, settings)
    feet = contact.feet
    tracks = motion.positions[:, :, feet]
    up = motion.metadata["up_axis"]
    horizontal = [axis for axis in range(3) if axis != up]
    support = contact.intervals
    velocities = np.diff(tracks[..., horizontal], axis=0) * motion.fps
    speeds = np.linalg.norm(velocities, axis=-1)
    contact_speeds = speeds[support]
    results = {
        "support_detection": contact.metrics,
        "support_joint_frames": int(support.sum()),
        "support_speed_percentiles_m_s": dict(zip(("p50", "p90", "p95", "p99", "max"),
            np.percentile(contact_speeds, [50, 90, 95, 99, 100]).tolist())) if contact_speeds.size else {},
        "threshold_sensitivity": [],
    }
    for height in (.02, .04, .06):
        test = foot_sliding.check(motion, {**settings, "contact_height_m": height})
        results["threshold_sensitivity"].append({"contact_height_m": height,
            "sliding_frame_count": test.metrics["sliding_frame_count"],
            "sliding_frame_ratio": test.metrics["sliding_frame_ratio"]})
    if motion.contacts is not None:
        results["contacts"] = {
            "fraction_above_0_5": float(np.mean(motion.contacts > .5)),
            "fraction_above_0_95": float(np.mean(motion.contacts > .95)),
            "all_four_active_frames": int(np.all(motion.contacts > .5, axis=-1).sum()),
        }
    # If two planted points have velocity difference > 2*threshold, no
    # horizontal root translation can bring both below the slip threshold.
    paired_support = support[..., :, None] & support[..., None, :]
    pair_difference = np.linalg.norm(velocities[..., :, None, :] - velocities[..., None, :, :], axis=-1)
    impossible = np.any((pair_difference > 2 * settings["horizontal_speed_m_s"]) & paired_support, axis=(-1, -2))
    results["root_translation_insufficient_actor_frames"] = int(impossible.sum())
    results["actor_frames_with_multiple_support_points"] = int((support.sum(axis=-1) >= 2).sum())
    maximum = float(load_config()["repairs"]["foot_lock"]["max_correction_m"])
    limited_runs = []
    for actor in range(motion.actor_count):
        for local, joint in enumerate(feet):
            for start, end in segments(support[:, actor, local]):
                travel = float(np.linalg.norm(tracks[end + 1, actor, local, horizontal] - tracks[start, actor, local, horizontal]))
                allowed = float(settings["horizontal_speed_m_s"]) * (end - start + 1) / motion.fps
                required = max(0., (travel - allowed) / 2)
                if required > maximum:
                    limited_runs.append({"actor_id": actor, "joint_id": joint, "start_frame": start,
                        "end_frame": end + 1, "minimum_endpoint_shift_m": required, "endpoint_travel_m": travel})
    results["movement_bound_analysis"] = {"max_horizontal_shift_m": maximum,
        "support_runs_exceeding_bound": len(limited_runs),
        "worst_runs": sorted(limited_runs, key=lambda item: item["minimum_endpoint_shift_m"], reverse=True)[:5],
        "assumption": "Preserve these support intervals and cap each endpoint displacement; this is a necessary bound, not proof of full IK feasibility"}
    return results


def describe(motion) -> dict:
    report = inspect(motion)
    gate = evaluate_gate(report)
    tests = []
    for test in report.tests:
        durations = np.array([issue.end_frame - issue.start_frame + 1 for issue in test.issues])
        tests.append({"test": test.test_name, "score": test.score, "status": test.status,
            "severity_counts": dict(Counter(issue.severity for issue in test.issues)),
            "issue_segments": len(test.issues),
            "one_frame_segments": int(np.count_nonzero(durations == 1)),
            "longest_segment_seconds": float(durations.max() / motion.fps) if durations.size else 0,
            "metrics": test.metrics,
            "worst_issues": [issue.to_dict() for issue in sorted(test.issues, key=lambda issue: (
                issue.value / max(issue.threshold, 1e-8) if "distance" not in issue.metric else -issue.value), reverse=True)[:3]],
        })
    return {"overall_score": report.overall_score, "critical_issue_count": report.critical_issue_count,
        "geometry_source": motion.metadata.get("geometry_source", "native_joint_positions"),
        "gate": gate.to_dict(), "tests": tests, "foot_stats": foot_stats(motion)}


def matching_smplx_motion(motion, rest: np.ndarray):
    # Independent matrix FK with the same zero-beta neutral body as the renderer.
    local = motion.rotation_matrices[:, 0]
    offsets = rest[SMPL_TO_BVH22].copy()
    offsets[1:] -= rest[np.array(SMPL_TO_BVH22)[BVH_PARENTS[1:]]]
    positions = np.zeros((motion.frame_count, 22, 3))
    world = np.zeros_like(local)
    for joint, parent in enumerate(BVH_PARENTS):
        if parent < 0:
            positions[:, joint] = motion.root_translation[:, 0] + offsets[0]
            world[:, joint] = local[:, joint]
        else:
            positions[:, joint] = positions[:, parent] + np.einsum("tij,j->ti", world[:, parent], offsets[joint])
            world[:, joint] = world[:, parent] @ local[:, joint]
    return replace(motion, positions=positions[:, None], metadata={**motion.metadata,
        "offsets": offsets.tolist(), "geometry_source": "renderer_smplx_neutral"})


def run(manifest: Path, output: Path, model: Path | None, run_repairs: bool = False, save_repaired: bool = False) -> dict:
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    rest = None
    if model is not None:
        with np.load(model, allow_pickle=False) as data:
            rest = data["J_regressor"] @ data["v_template"]
    records = []
    digests = {}
    for entry in payload["motions"]:
        paths = [(manifest.parent / entry["input"]).resolve()]
        if entry.get("actor2"):
            paths.append((manifest.parent / entry["actor2"]).resolve())
        motion = load_motion(paths[0], paths[1] if len(paths) > 1 else None, payload.get("fps", 30))
        digest = hashlib.sha256(b"".join(path.read_bytes() for path in paths)).hexdigest()
        item = {"name": entry["name"], "source": motion.source, "frames": motion.frame_count,
            "input_paths": [str(path) for path in paths], "sha256": digest,
            "duplicate_of": digests.get(digest), "current": describe(motion)}
        digests.setdefault(digest, entry["name"])
        if run_repairs and not entry["name"].endswith("_raw") and not item["duplicate_of"]:
            outcome = repair(motion)
            item["repair"] = {"algorithm_version": outcome.to_dict()["algorithm_version"], "steps": outcome.steps, "after": describe(outcome.motion)}
            if save_repaired:
                folder = output / entry["name"]
                _write_report(folder / "before", outcome.before)
                _write_report(folder / "after", outcome.after)
                _write_json(folder / "repair_report.json", outcome.to_dict())
                _write_json(folder / "quality_gate.json", evaluate_gate(outcome.after).to_dict())
                if motion.source == "lodge":
                    raw = outcome.raw_lodge if outcome.raw_lodge is not None else np.load(paths[0], allow_pickle=False)
                    np.save(folder / "repaired.npy", raw)
                else:
                    for actor in range(motion.actor_count):
                        np.save(folder / f"repaired_actor{actor + 1}.npy", outcome.motion.positions[:, actor])
        if motion.source == "lodge" and rest is not None:
            matched = matching_smplx_motion(motion, rest)
            item["renderer_geometry"] = describe(matched)
            offset_delta = np.linalg.norm(np.asarray(matched.metadata["offsets"]) - BVH_OFFSETS, axis=-1)
            item["geometry_difference"] = {"largest_nonroot_offset_m": float(offset_delta[1:].max()),
                "foot_offset_differences_m": offset_delta[motion.metadata["foot_joint_ids"]].tolist(),
                "independent_fk_max_difference_m": float(np.linalg.norm(matched.positions - motion.positions, axis=-1).max())}
        records.append(item)
    result = {"config_version": load_config()["version"], "policy": load_config()["gate"], "records": records,
        "pass_count": sum(item["current"]["gate"]["status"] == "PASS" for item in records),
        "repair_count": sum("repair" in item for item in records),
        "repaired_pass_count": sum(item.get("repair", {}).get("after", {}).get("gate", {}).get("status") == "PASS" for item in records)}
    _write_json(output / "diagnosis.json", result)
    for item in records:
        current = item["current"]
        foot = next(test for test in current["tests"] if test["test"] == "foot_sliding")
        print(item["name"], current["overall_score"], current["gate"]["reasons"],
              "sliding_ratio", round(foot["metrics"]["sliding_frame_ratio"], 3),
              "speed_p95", round(current["foot_stats"]["support_speed_percentiles_m_s"].get("p95", 0), 3))
        if "renderer_geometry" in item:
            matched = item["renderer_geometry"]
            foot = next(test for test in matched["tests"] if test["test"] == "foot_sliding")
            print("  matched_renderer", matched["overall_score"], matched["gate"]["reasons"],
                  "sliding_ratio", round(foot["metrics"]["sliding_frame_ratio"], 3))
        if "repair" in item:
            after = item["repair"]["after"]
            print("  repair", after["overall_score"], after["gate"]["reasons"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "experiments" / "baseline_motions.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "gate_diagnosis_20260930")
    parser.add_argument("--smplx-model", type=Path)
    parser.add_argument("--repair", action="store_true", help="Recheck repair candidates without overwriting task files")
    parser.add_argument("--save-repaired", action="store_true", help="Save repaired arrays and reports inside output-dir; implies --repair")
    args = parser.parse_args()
    run(args.manifest.resolve(), args.output_dir, args.smplx_model, args.repair or args.save_repaired, args.save_repaired)
