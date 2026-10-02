"""Export a snapshot of repaired joints through the existing MoMask/Kenney tools.

Run in the InterGen environment. Quality FAIL remains a recorded result: a
rendered artifact is not evidence that its independent quality gate passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4
import zipfile

import numpy as np

from motionlint.adapters.bvh_adapter import load_bvh_pair
from motionlint.adapters.character_adapter import load_character
from motionlint.adapters.intergen_adapter import load_intergen_joints
from motionlint.cli.main import _write_json, _write_report
from motionlint.core.config import DEFAULT_CONFIG
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.regression import compare

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = REPO_ROOT.parent / "HumanAction-runtime"


def repaired_inputs(task: Path) -> list[Path]:
    return [task / "motionlint" / f"repaired_actor{actor}.npy" for actor in (1, 2)]


def publish_export_status(task: Path, state: dict) -> None:
    path = task / "motionlint/character_export.json"
    temporary = path.with_suffix(".tmp.json")
    _write_json(temporary, state)
    temporary.replace(path)


def fingerprint(paths: list[Path]) -> list[dict]:
    return [{"name": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths]


def _process_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def read_export(task: Path) -> dict:
    """Reject a previous export after a new repair; do not serve mismatched video."""
    path = task / "motionlint/character_export.json"
    if not path.is_file():
        return {"status": "unavailable"}
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("status") in {"queued", "running"} and result.get("pid") and not _process_alive(int(result["pid"])):
        return {**result, "status": "failed", "error": "导出进程已退出，请重新导出"}
    if result.get("status") == "ready":
        paths = repaired_inputs(task)
        if not all(path.is_file() for path in paths) or fingerprint(paths) != result.get("input_fingerprints"):
            return {**result, "status": "stale", "error": "动作已重新修复，请重新导出角色视频"}
    return result


def export_artifact(task: Path, key: str) -> Path:
    result = read_export(task)
    if result.get("status") != "ready":
        raise ValueError("修复后的角色导出尚未完成或已过期")
    root = (task / "motionlint/exports").resolve()
    path = Path(result[key]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("角色导出产物不可用")
    return path


def build_manifest(task: Path, output: Path, frames: int, fps: int, size: int) -> dict:
    """Use licensed local Kenney resources and retain the full repaired sequence."""
    original_path = task / "retarget/retarget_manifest.json"
    original = json.loads(original_path.read_text(encoding="utf-8")) if original_path.is_file() else {}
    target = RUNTIME_ROOT / "assets/kenney-protagonists/Model/characterMedium.fbx"
    mapping = RUNTIME_ROOT / "assets/kenney_mapping.json"
    bvhs = [output / f"repaired_actor{actor}.bvh" for actor in (1, 2)]
    return {
        "task_id": task.name, "skin_id": "kenney_cc0", "person_skin_ids": ["kenney_cc0"] * 2,
        "engine": "blender-rokoko", "motionlint_input_stage": "repaired",
        "source_bvh": str(bvhs[0]), "source_bvh_files": [str(path) for path in bvhs],
        "source_bvh_reports": [str(path.with_suffix(".conversion.json")) for path in bvhs],
        "target_fbx": str(target), "target_fbx_files": [str(target)] * 2,
        "mapping_file": str(mapping), "mapping_files": [str(mapping)] * 2,
        "raw_joints_files": [str(output / f"repaired_actor{actor}.npy") for actor in (1, 2)],
        "output_mp4": str(output / "repaired_kenney.mp4"),
        "debug_blend": str(output / "repaired_kenney.blend"),
        "report_path": str(output / "retarget_report.json"),
        "fps": fps, "generated_frames": frames, "source_frame_counts": [frames] * 2,
        "duration_seconds": frames / fps, "max_render_frames": 0,
        "render_size": f"{size}x{size}", "camera_distance_scale": 1.15,
        "motion_prompt": original.get("motion_prompt", ""),
        "motion_profile": original.get("motion_profile", "default"),
        # Keep the existing presentation layout explicit; the resulting scene
        # is checked independently, including the applied spacing.
        "target_spacing": original.get("target_spacing", 1.25),
        "core_smoothing_window": 5, "spine_smoothing_window": 5,
        "foot_lock_enabled": True, "foot_lock_max_correction": .15,
        "head_world_stabilization_enabled": True,
        "hand_torso_collision_enabled": True,
    }


def _run(command: list[str], output: Path, name: str, env: dict, timeout: int) -> None:
    """Keep diagnostics in the export folder without filling API output."""
    if Path(command[0]).stem.lower() == "blender" and "--python-exit-code" not in command:
        command = [command[0], "--python-exit-code", "1", *command[1:]]
    with (output / f"{name}.log").open("w", encoding="utf-8") as log:
        process = subprocess.run(command, cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                 timeout=timeout)
    if process.returncode:
        raise RuntimeError(f"{name} failed ({process.returncode}); see {output / (name + '.log')}")


def write_bundle(output: Path, state: dict) -> Path:
    """Package motion and evidence while keeping local character assets out."""
    bundle = output / "repaired_export.zip"
    _write_json(output / "export_summary.json", {**state, "status": "ready", "phase": "complete",
                "bundle_path": str(bundle), "limits": "Rendered successfully; see the independent quality gate of each stage."})
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in output.rglob("*"):
            if path.is_file() and path.suffix in {".npy", ".npz", ".bvh", ".mp4", ".json", ".csv", ".yaml"}:
                archive.write(path, path.relative_to(output).as_posix())
    return bundle


def select_converter(baseline, candidate, baseline_fidelity: list[dict], candidate_fidelity: list[dict], *, config_path=None) -> dict:
    """Accept measured BVH gains without hiding a new failed test or worse fit."""
    comparison = compare(baseline, candidate, config_path=config_path)
    reasons = list(comparison["reasons"])
    if candidate.overall_score < baseline.overall_score:
        reasons.append("Overall score decreased")
    old_tests = {test.test_name: test for test in baseline.tests}
    for test in candidate.tests:
        if test.status == "FAIL" and test.test_name in old_tests and old_tests[test.test_name].status != "FAIL":
            reasons.append(f"New failed test: {test.test_name}")
    if len(baseline_fidelity) != len(candidate_fidelity) or not candidate_fidelity:
        reasons.append("Missing actor fidelity comparison")
    for old, new in zip(baseline_fidelity, candidate_fidelity):
        for metric in ("position_error_mean_m", "position_error_p95_m", "position_error_max_m"):
            if not np.isfinite(new[metric]) or new[metric] > old[metric] + 1e-5:
                reasons.append(f"Worse source fidelity: {metric}")
        if not np.isfinite(new["root_error_max_m"]) or new["root_error_max_m"] > .01001:
            reasons.append("Root adjustment exceeded 1 cm")
    return {"selected": "momask" if reasons else "continuous", "reasons": reasons, "regression": comparison,
            "baseline_score": baseline.overall_score, "candidate_score": candidate.overall_score,
            "baseline_fidelity": baseline_fidelity, "candidate_fidelity": candidate_fidelity,
            "limits": "Selection checks BVH only. Actual character quality is checked after rendering."}


def convert_snapshot(snapshots: list[Path], output: Path, *, fps: int, policy: Path) -> dict:
    from InterGen_api.intergen_joints2bvh import convert_joints_to_bvh
    from motionlint.joints_to_bvh import convert_continuous_joints, fidelity
    from LODGE_api.lodge2bvh import SMPL_TO_BVH22
    candidates = {}
    reports = {}
    fidelity_rows = {}
    target = load_intergen_joints(snapshots, fps=fps).positions[:, :, SMPL_TO_BVH22]
    for method in ("momask", "continuous"):
        directory = output / "conversion_candidates" / method
        directory.mkdir(parents=True)
        paths = []
        try:
            for actor, snapshot in enumerate(snapshots, 1):
                bvh = directory / f"repaired_actor{actor}.bvh"
                if method == "momask":
                    convert_joints_to_bvh(snapshot, bvh, RUNTIME_ROOT / "momask-main", fps=fps,
                                          foot_ik=False, stabilize_upper_body=False,
                                          correct_hand_head_collisions=False, quality_gate=False,
                                          report_path=bvh.with_suffix(".conversion.json"))
                else:
                    convert_continuous_joints(snapshot, bvh, fps=fps)
                paths.append(bvh)
            sequence = load_bvh_pair(paths)
            reports[method] = inspect(sequence, config_path=policy)
            _write_report(directory / "quality", reports[method])
            fidelity_rows[method] = [fidelity(target[:, actor], sequence.positions[:, actor]) for actor in range(len(snapshots))]
            candidates[method] = paths
        except Exception as exc:
            if method == "momask":
                raise
            # A candidate failure leaves the established converter available.
            selection = {"selected": "momask", "reasons": [f"Continuous converter unavailable: {type(exc).__name__}: {exc}"]}
    if "continuous" in candidates:
        selection = select_converter(reports["momask"], reports["continuous"], fidelity_rows["momask"],
                                     fidelity_rows["continuous"], config_path=policy)
    for actor, source in enumerate(candidates[selection["selected"]], 1):
        destination = output / f"repaired_actor{actor}.bvh"
        shutil.copyfile(source, destination)
        provenance = json.loads(source.with_suffix(".conversion.json").read_text(encoding="utf-8"))
        provenance.update(published_bvh=str(destination), selected_converter=selection["selected"],
                          selection_report=str(output / "converter_selection.json"))
        _write_json(destination.with_suffix(".conversion.json"), provenance)
    _write_json(output / "converter_selection.json", selection)
    return selection


def export_repaired(task: Path, *, size: int = 540, fps: int = 30) -> dict:
    task = task.resolve()
    output = task / "motionlint/exports" / uuid4().hex
    output.mkdir(parents=True)
    state = {"status": "running", "phase": "snapshot", "export_dir": str(output), "pid": os.getpid()}

    def update(phase: str, **extra):
        state.update(phase=phase, **extra)
        # Atomic pointer update: browser polling never reads half a JSON file.
        publish_export_status(task, state)

    try:
        paths = repaired_inputs(task)
        state["input_fingerprints"] = fingerprint(paths)
        update("snapshot")
        snapshots = []
        for path in paths:
            snapshot = output / path.name
            snapshot.write_bytes(path.read_bytes())
            snapshots.append(snapshot)
        if fingerprint(snapshots) != state["input_fingerprints"]:
            raise RuntimeError("动作在导出快照时发生变化，请重新导出")
        motion = load_intergen_joints(snapshots, fps=fps)
        if not np.isfinite(motion.positions).all() or motion.frame_count < 2:
            raise ValueError("Cannot export nonfinite or fewer than two motion frames")
        # Freeze the policy used at every export stage.
        policy = output / "quality.yaml"
        policy.write_bytes(DEFAULT_CONFIG.read_bytes())
        state["config_sha256"] = hashlib.sha256(policy.read_bytes()).hexdigest()
        manifest = build_manifest(task, output, motion.frame_count, fps, size)
        manifest_path = output / "retarget_manifest.json"
        _write_json(manifest_path, manifest)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONIOENCODING"] = "utf-8"
        env["BLENDER_USER_SCRIPTS"] = str(RUNTIME_ROOT / "blender-scripts")
        blender = RUNTIME_ROOT / "blender-4.2.23-windows-x64/blender.exe"
        for resource in (blender, Path(manifest["target_fbx"]), Path(manifest["mapping_file"])):
            if not resource.is_file():
                raise FileNotFoundError(f"Missing local export resource: {resource}")

        update("bvh")
        state["converter_selection"] = convert_snapshot(snapshots, output, fps=fps, policy=policy)
        bvhs = [Path(path) for path in manifest["source_bvh_files"]]

        def check_stage(stage: str, sequence):
            report = inspect(sequence, config_path=policy)
            report.metadata.update(inspection_stage=stage, input_stage="repaired", input_fingerprints=state["input_fingerprints"])
            gate = evaluate_gate(report, config_path=policy)
            _write_report(output / stage, report)
            _write_json(output / stage / "quality_gate.json", gate.to_dict())
            return {"score": report.overall_score, "gate": gate.to_dict(), "frames": sequence.frame_count}

        state["quality"] = {"repaired": check_stage("repaired", motion),
                            "repaired_bvh": check_stage("repaired_bvh", load_bvh_pair(bvhs))}
        update("retarget_render")
        _run([str(blender), "-b", "--python", str(REPO_ROOT / "LODGE_api/blender_rokoko_retarget.py"),
              "--", "--manifest", str(manifest_path)], output, "render", env, 3600)
        character = output / "character.npz"
        update("character_check")
        _run([str(blender), "-b", manifest["debug_blend"], "--python",
              str(REPO_ROOT / "scripts/export_blender_motionlint.py"), "--", "--manifest", str(manifest_path),
              "--output", str(character)], output, "character_export", env, 180)
        sequence = load_character(character)
        if sequence.frame_count != motion.frame_count or not np.isclose(sequence.fps, motion.fps):
            raise RuntimeError("角色场景的帧数或帧率与修复动作不一致")
        state["quality"]["repaired_character"] = check_stage("repaired_character", sequence)
        state.update(bvh_files=[str(path) for path in bvhs], character_path=str(character),
                     manifest_path=str(manifest_path), video_path=manifest["output_mp4"])
        for key in ("video_path", "character_path", "manifest_path"):
            if not Path(state[key]).is_file():
                raise FileNotFoundError(f"Missing export artifact: {key}")
        # Distribute motion, video and reports; local FBX and .blend assets stay
        # out of the downloadable bundle.
        bundle = write_bundle(output, state)
        state["bundle_path"] = str(bundle)
        update("character_foot_repair")
        from scripts.optimize_character_feet import optimize
        try:
            refined = optimize(task.name, baseline={**state, "status": "ready"}, publish=False)
            if refined["accepted"]:
                publish_export_status(task, refined["export_state"])
                return read_export(task)
            state["character_foot_repair"] = refined["comparison"]
        except Exception as exc:
            # Retain the completed base scene when an optional candidate fails.
            state["character_foot_repair"] = {"accepted": False, "error": f"{type(exc).__name__}: {exc}"}
        write_bundle(output, state)
        update("complete", status="ready")
        return read_export(task)
    except Exception as exc:
        update("failed", status="failed", error=str(exc)[-1000:])
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--size", type=int, choices=(360, 540, 720, 1080), default=540)
    args = parser.parse_args()
    result = export_repaired(args.task, size=args.size)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
