"""Trial evaluated-character foot repair, publish only accepted actual results."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
from motionlint.adapters.character_adapter import load_character
from motionlint.character_feet import plan_character_feet
from motionlint.cli.main import _write_json, _write_report
from motionlint.core.quality_gate import evaluate_gate
from motionlint.export_intergen import RUNTIME_ROOT, _run, read_export, publish_export_status, write_bundle, fingerprint, repaired_inputs
from motionlint.core.foot_support import estimate_support
from motionlint.core.config import load_config
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.regression import compare


def verify_rendered_video(path, expected_frames):
    """Decode the whole render before exposing it as a ready export."""
    path = Path(path)
    if not path.is_file():
        raise RuntimeError("Character repair did not produce its matching video")
    result = subprocess.run([str(RUNTIME_ROOT / "bin/ffmpeg.exe"), "-v", "error", "-nostats",
        "-progress", "pipe:1", "-i", str(path), "-f", "null", "-"],
        check=True, capture_output=True, text=True, timeout=120)
    frames = [int(line.partition("=")[2]) for line in result.stdout.splitlines() if line.startswith("frame=")]
    if not frames or frames[-1] != expected_frames or "progress=end" not in result.stdout:
        raise RuntimeError(f"Incomplete character video: expected {expected_frames} frames, decoded {frames[-1:]}")


def optimize(task_id, *, baseline=None, publish=True):
    task = REPO_ROOT / "InterGen_api/task_runs" / task_id
    baseline = baseline or read_export(task)
    if baseline["status"] != "ready":
        raise ValueError("Complete the repaired-character export first")
    original = Path(baseline["export_dir"])
    output = task / "motionlint/exports" / ("feet-" + uuid4().hex)
    shutil.copytree(original, output, ignore=shutil.ignore_patterns("*.blend", "*.mp4", "*.zip", "*.log"))
    _write_json(output / "foot_repair_baseline.json", baseline)
    # Paths in the render manifest must identify the candidate's actual inputs.
    def rebase(value):
        if isinstance(value, str) and value.startswith(str(original)):
            return str(output) + value[len(str(original)):]
        if isinstance(value, list):
            return [rebase(item) for item in value]
        if isinstance(value, dict):
            return {key: rebase(item) for key, item in value.items()}
        return value
    manifest = rebase(json.loads(Path(baseline["manifest_path"]).read_text(encoding="utf-8")))
    manifest["motionlint_character_foot_repair"] = True
    manifest_path = output / "retarget_manifest.json"
    _write_json(manifest_path, manifest)
    policy = output / "quality.yaml"
    plan_path = output / "character_foot_plan.json"
    _write_json(plan_path, plan_character_feet(Path(baseline["character_path"]), config_path=policy))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    env["BLENDER_USER_SCRIPTS"] = str(RUNTIME_ROOT / "blender-scripts")
    blender = str(RUNTIME_ROOT / "blender-4.2.23-windows-x64/blender.exe")
    _run([blender, "-b", str(original / "repaired_kenney.blend"), "--python",
          str(REPO_ROOT / "scripts/apply_character_feet_blender.py"), "--", "--plan", str(plan_path),
          "--manifest", str(manifest_path)], output, "foot_repair", env, 300)
    character = output / "character.npz"
    _run([blender, "-b", manifest["debug_blend"], "--python", str(REPO_ROOT / "scripts/export_blender_motionlint.py"),
          "--", "--manifest", str(manifest_path), "--output", str(character)], output, "character_export", env, 180)
    reference_motion = load_character(baseline["character_path"])
    before = inspect(reference_motion, config_path=policy)
    sequence = load_character(character)
    after = inspect(sequence, config_path=policy)
    result = compare(before, after, config_path=policy)
    old_tests = {test.test_name: test for test in before.tests}
    new_tests = {test.test_name: test for test in after.tests}
    position_change = np.linalg.norm(sequence.positions - reference_motion.positions, axis=-1)
    config = load_config(policy)
    support = estimate_support(reference_motion, config["tests"]["foot_sliding"])
    counts = []
    for motion in (reference_motion, sequence):
        speeds = np.linalg.norm(np.diff(motion.positions[:, :, support.feet][:, :, :, [0, 2]], axis=0), axis=-1) * motion.fps
        counts.append(int(np.count_nonzero((speeds > config["tests"]["foot_sliding"]["horizontal_speed_m_s"]) & support.intervals)))
    acceptable = bool(result["status"] == "PASS" and after.overall_score >= before.overall_score
                  and new_tests["foot_sliding"].score > old_tests["foot_sliding"].score
                  and all(test.status != "FAIL" or old_tests[test.test_name].status == "FAIL" for test in after.tests)
                  and position_change.max() <= .151 and counts[1] < counts[0])
    result.update(accepted=acceptable, baseline_export=str(original), candidate_export=str(output),
                  maximum_observed_joint_displacement_m=float(position_change.max()),
                  original_support_sliding_before=counts[0], original_support_sliding_after=counts[1])
    _write_json(output / "character_foot_comparison.json", result)
    _write_report(output / "repaired_character", after)
    gate = evaluate_gate(after, config_path=policy)
    _write_json(output / "repaired_character/quality_gate.json", gate.to_dict())
    if acceptable:
        _run([blender, "-b", manifest["debug_blend"], "--python", str(REPO_ROOT / "scripts/render_saved_character.py"),
              "--", str(manifest_path)], output, "render", env, 3600)
        verify_rendered_video(manifest["output_mp4"], sequence.frame_count)
        state = rebase(baseline)
        state.update(status="ready", phase="complete", pid=os.getpid(), character_foot_repair=result)
        state["quality"]["repaired_character"] = {"score": after.overall_score, "gate": gate.to_dict(), "frames": sequence.frame_count}
        state["bundle_path"] = str(write_bundle(output, state))
        if fingerprint(repaired_inputs(task)) != baseline["input_fingerprints"]:
            raise RuntimeError("Repaired inputs changed during character foot repair")
        if publish:
            if read_export(task).get("export_dir") != baseline["export_dir"]:
                raise RuntimeError("Another export replaced the baseline during character foot repair")
            publish_export_status(task, state)
    else:
        _write_json(output / "rejected_export.json", result)
        _write_json(output / "export_summary.json", {"status": "rejected", "character_foot_repair": result})
    return {"task": task_id, "accepted": acceptable, "before": before.overall_score, "after": after.overall_score,
            "feet_before": old_tests["foot_sliding"].score, "feet_after": new_tests["foot_sliding"].score,
            "gate": gate.to_dict(), "comparison": result, "candidate_export": str(output),
            "export_state": state if acceptable else baseline}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_ids", nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = [optimize(task_id) for task_id in args.task_ids]
    _write_json(args.output, rows)
    print(json.dumps(rows, ensure_ascii=False, indent=2))
