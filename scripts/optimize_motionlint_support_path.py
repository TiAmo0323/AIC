"""Evaluate bounded moving anchors only on the two existing development clips."""
from pathlib import Path
import json
import sys
from dataclasses import replace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from motionlint.cli.main import load_motion, _write_json, _write_report
from motionlint.core.config import load_config
from motionlint.core.foot_support import estimate_support
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.repair_pipeline import _assess
from motionlint.repairs.bone_length import project_bone_lengths
from motionlint.repairs.foot_lock import repair_foot_sliding
from motionlint.repairs.kinematics import unit

OUT = ROOT / "reports/support_path_20260930"
BASELINE = ROOT / "reports/optimization_20260930"


def smooth_knee_planes(motion, window):
    """Experimental bend-plane smoothing with fixed endpoints and bone lengths."""
    positions = motion.positions.copy()
    lookup = {name: index for index, name in enumerate(motion.joint_names)}
    for side in ("Left", "Right"):
        hip, knee, ankle = [lookup[side + suffix] for suffix in ("UpLeg", "Leg", "Foot")]
        start, bend, end = [positions[:, :, joint] for joint in (hip, knee, ankle)]
        axis = unit(end - start)
        center = start + np.sum((bend - start) * axis, axis=-1, keepdims=True) * axis
        radial = bend - center
        radius = np.linalg.norm(radial, axis=-1, keepdims=True)
        normal = unit(radial)
        weights = np.hanning(window + 2)[1:-1]
        weights /= weights.sum()
        padded = np.pad(normal, ((window//2, window//2), (0, 0), (0, 0)), mode="edge")
        smoothed = sum(weight * padded[offset:offset + len(normal)] for offset, weight in enumerate(weights))
        smoothed -= np.sum(smoothed * axis, axis=-1, keepdims=True) * axis
        proposed = center + radius * unit(smoothed, normal)
        permitted = (np.linalg.norm(proposed - bend, axis=-1) <= .03) & (np.sum(smoothed * normal, axis=-1) > 0)
        positions[:, :, knee] = np.where(permitted[..., None], proposed, bend)
    return replace(motion, positions=positions)

def main():
    manifest = json.loads((ROOT / "experiments/baseline_motions.json").read_text(encoding="utf-8"))
    rows = []
    for name in ("intergen_handshake_a", "intergen_wave"):
        entry = next(item for item in manifest["motions"] if item["name"] == name)
        original = load_motion(ROOT / "experiments" / entry["input"], ROOT / "experiments" / entry["actor2"])
        # Reconstruct the already accepted fixed-bone input to the foot stage.
        saved_report = json.loads((BASELINE / name / "repair_report.json").read_text(encoding="utf-8"))
        bone = next(step for step in saved_report["steps"] if step["repair"] == "bone_length_projection")
        motion, _ = project_bone_lengths(original, **{**load_config()["repairs"]["bone_length_projection"], **bone["variant"]}) if bone["applied"] else (original, {})
        before = inspect(motion)
        current = load_motion(BASELINE / name / "repaired_actor1.npy", BASELINE / name / "repaired_actor2.npy")
        current_report = inspect(current)
        support = estimate_support(motion, load_config()["tests"]["foot_sliding"])
        best, trials = None, []
        for smooth in (0, 3, 5, 9):
            for strength in (1., .5):
                candidate, _, detail = repair_foot_sliding(motion, [], anchor_method="velocity", root_follow=False,
                    smooth_frames=smooth, correction_strength=strength, **load_config()["repairs"]["foot_lock"])
                if smooth == 3:
                    candidate = smooth_knee_planes(candidate, 5)
                    detail["experimental_knee_plane_window"] = 5
                    detail["knee_plane_max_shift_m"] = .03
                after = inspect(candidate)
                assessment = _assess("foot_lock", "foot_sliding", motion, candidate, before, after, load_config())
                foot_shift = float(np.linalg.norm((candidate.positions-motion.positions)[:, :, support.feet][..., [0, 2]], axis=-1).max())
                assessment["movement_bound_ok"] = foot_shift <= .150001
                assessment["detail"] = detail
                assessment["foot_max_horizontal_shift_m"] = foot_shift
                assessment["score_vs_existing_repair"] = after.overall_score-current_report.overall_score
                assessment["foot_sliding_count"] = next(test.metrics["sliding_frame_count"] for test in after.tests if test.test_name=="foot_sliding")
                trials.append(assessment)
                print(name, smooth, strength, assessment["foot_sliding_count"], after.overall_score, assessment["applied"], flush=True)
                if assessment["applied"] and assessment["movement_bound_ok"] and after.overall_score > current_report.overall_score:
                    key = (after.overall_score, -assessment["foot_sliding_count"])
                    if best is None or key > best[0]:
                        best = (key, candidate, after, assessment)
        result = {"name": name, "existing_score": current_report.overall_score, "trials": trials, "improved": best is not None}
        if best:
            _, candidate, after, selected = best
            folder = OUT / name
            _write_report(folder, after)
            for actor in range(2):
                np.save(folder / f"repaired_actor{actor+1}.npy", candidate.positions[:, actor])
            _write_json(folder / "quality_gate.json", evaluate_gate(after).to_dict())
            result.update({"selected": selected, "score": after.overall_score, "gate": evaluate_gate(after).status})
        rows.append(result)
    _write_json(OUT / "summary.json", {"rows": rows, "scope": "Development clips only; held-out results remain frozen v2"})

if __name__ == "__main__":
    main()
