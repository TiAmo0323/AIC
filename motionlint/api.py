"""Local API for inspecting and repairing persisted generator task artifacts."""

from __future__ import annotations

from pathlib import Path
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import os
import shutil
import subprocess
from uuid import UUID
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from motionlint.cli.main import _write_json, _write_report, load_motion
from motionlint.adapters.character_adapter import load_character
from motionlint.adapters.bvh_adapter import load_bvh_pair
from motionlint.core.config import load_config
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.regression import compare
from motionlint.pipeline.repair_pipeline import repair, summarize_issues
from motionlint.export_intergen import read_export, export_artifact, publish_export_status


REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_ROOTS = {
    "intergen": REPO_ROOT / "InterGen_api" / "task_runs",
    "lodge": REPO_ROOT / "LODGE_api" / "task_runs",
}
RUNTIME_ROOT = REPO_ROOT.parent / "HumanAction-runtime"
RENDER_EXECUTOR = ThreadPoolExecutor(max_workers=1)
RENDER_JOBS = {}
EXPORT_JOBS = {}
MOTION_MUTATION_LOCK = Lock()

app = FastAPI(title="MotionLint Local API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["GET", "POST"], allow_headers=["*"])


class TaskRef(BaseModel):
    source: Literal["intergen", "lodge"]
    task_id: str


class CompareRequest(BaseModel):
    baseline: TaskRef
    candidate: TaskRef


class StageRequest(TaskRef):
    stage: Literal["raw", "repaired", "bvh", "character", "repaired_bvh", "repaired_character"] = "raw"


def _stage_video_path(ref: TaskRef, stage: str) -> Path | None:
    task = _task_folder(ref)
    if stage == "repaired_character":
        if ref.source != "intergen":
            return None
        try:
            return export_artifact(task, "video_path")
        except (ValueError, KeyError):
            return None
    if stage == "repaired_bvh":
        return None
    if stage == "character":
        path = task / "retarget/retarget_manifest.json"
        if path.is_file():
            manifest = json.loads(path.read_text(encoding="utf-8"))
            video = Path(manifest["output_mp4"]).resolve()
            if video.is_relative_to(task.resolve()) and video.is_file():
                return video
        return None
    if stage == "bvh":
        return None  # A retargeted character is a different geometry stage.
    path = task / "motionlint" / ("repaired.mp4" if stage == "repaired" else "original.mp4")
    if stage == "repaired":
        status_path = task / "motionlint/render_status.json"
        if not status_path.is_file() or json.loads(status_path.read_text(encoding="utf-8")).get("status") != "ready":
            return None
        arrays = ([task / "motionlint/repaired.npy"] if ref.source == "lodge" else
                  [task / "motionlint" / f"repaired_actor{actor}.npy" for actor in (1, 2)])
        if not path.is_file() or any(not array.is_file() or array.stat().st_mtime > path.stat().st_mtime for array in arrays):
            return None
    if path.is_file():
        return path
    if stage == "raw":
        candidates = (sorted((task / "output").glob("*.mp4")) if ref.source == "intergen"
                      else sorted((task / "input/video").glob("*smplx.mp4")))
        return candidates[0] if candidates else None
    return None


def _stage_motion(req: StageRequest):
    task = _task_folder(req)
    if req.stage in {"repaired_bvh", "repaired_character"}:
        if req.source != "intergen":
            raise HTTPException(422, "该角色导出入口目前支持 InterGen 双人动作")
        try:
            if req.stage == "repaired_bvh":
                manifest = json.loads(export_artifact(task, "manifest_path").read_text(encoding="utf-8"))
                paths = [Path(path).resolve() for path in manifest["source_bvh_files"]]
                root = (task / "motionlint/exports").resolve()
                if not all(path.is_relative_to(root) and path.is_file() for path in paths):
                    raise ValueError("修复后的 BVH 产物不可用")
                return load_bvh_pair(paths)
            motion = load_character(export_artifact(task, "character_path"))
            import hashlib
            blend = Path(motion.metadata["blend_path"])
            if not blend.is_file() or hashlib.sha256(blend.read_bytes()).hexdigest() != motion.metadata["blend_sha256"]:
                raise ValueError("修复角色场景已变化，请重新导出")
            return motion
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc
    if req.stage == "raw":
        return _motion(req)
    if req.stage == "repaired":
        paths = ([task / "motionlint/repaired.npy"] if req.source == "lodge" else
                 [task / "motionlint" / f"repaired_actor{actor}.npy" for actor in (1, 2)])
        if not all(path.is_file() for path in paths):
            raise HTTPException(404, "请先修复这条动作，再检查修复结果")
        return load_motion(paths[0], paths[1] if len(paths) == 2 else None)
    if req.stage == "bvh":
        paths = (sorted((task / "input").glob("*.bvh")) if req.source == "lodge" else
                 [task / "retarget" / f"{req.task_id}_person{actor}.bvh" for actor in (1, 2)])
        if not paths or not all(path.is_file() for path in paths):
            raise HTTPException(404, "这条任务尚未导出 BVH")
        return load_bvh_pair(paths)
    export = task / "motionlint/stages/character/character.npz"
    if not export.is_file():
        manifest_path = task / "retarget/retarget_manifest.json"
        if not manifest_path.is_file():
            raise HTTPException(404, "这条任务没有可检查的角色重定向场景")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        blend = Path(manifest.get("debug_blend", "")).resolve()
        if not blend.is_relative_to(task.resolve()) or not blend.is_file():
            raise HTTPException(404, "角色场景文件不可用，无法核对视频对应的骨架")
        command = [str(RUNTIME_ROOT / "blender-4.2.23-windows-x64/blender.exe"), "-b", str(blend),
                   "--python", str(REPO_ROOT / "scripts/export_blender_motionlint.py"), "--", "--manifest", str(manifest_path),
                   "--output", str(export)]
        try:
            subprocess.run(command, cwd=REPO_ROOT, capture_output=True, check=True, timeout=180)
        except (OSError, subprocess.SubprocessError) as exc:
            raise HTTPException(500, "角色骨架导出失败，请查看本地 Blender 场景") from exc
        if not export.is_file():
            raise HTTPException(500, "Blender 未产生角色骨架导出文件")
    motion = load_character(export)
    blend_path = Path(motion.metadata["blend_path"])
    import hashlib
    if not blend_path.is_file() or hashlib.sha256(blend_path.read_bytes()).hexdigest() != motion.metadata["blend_sha256"]:
        raise HTTPException(409, "角色场景已变化，请重新导出骨架后检查")
    return motion


def _task_folder(ref: TaskRef) -> Path:
    try:
        normalized = str(UUID(ref.task_id))
    except ValueError as exc:
        raise HTTPException(422, "task_id must be a UUID") from exc
    if normalized != ref.task_id:
        raise HTTPException(422, "task_id must be a canonical UUID")
    folder = TASK_ROOTS[ref.source] / normalized
    if not folder.is_dir():
        raise HTTPException(404, "Task output folder not found")
    return folder


def _motion_paths(ref: TaskRef) -> list[Path]:
    folder = _task_folder(ref)
    if ref.source == "intergen":
        raw = folder / "output" / "raw"
        paths = [raw / f"{ref.task_id}_person{actor}_joints22.npy" for actor in (1, 2)]
        if all(path.is_file() for path in paths):
            return paths
        raise HTTPException(404, "InterGen two-person joints22 NPY files not found")
    candidates = sorted((folder / "input").glob("*.npy"))
    for path in candidates:
        try:
            data = np.load(path, allow_pickle=False, mmap_mode="r")
            if data.ndim == 2 and data.shape[1] in {135, 139, 315, 319}:
                return [path]
        except (OSError, ValueError):
            continue
    raise HTTPException(404, "LODGE motion NPY not found")


def _motion(ref: TaskRef):
    paths = _motion_paths(ref)
    return load_motion(paths[0], paths[1] if len(paths) > 1 else None)


def _inspect_task(ref: TaskRef):
    motion = _motion(ref)
    report = inspect(motion)
    gate = evaluate_gate(report)
    folder = _task_folder(ref) / "motionlint"
    _write_report(folder, report)
    _write_json(folder / "quality_gate.json", gate.to_dict())
    return motion, report, gate, folder


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/v1/motionlint/config")
def quality_config() -> dict:
    return load_config()


@app.get("/v1/motionlint/settings")
def motion_settings(source: Literal["intergen", "lodge"] | None = None, task_id: str | None = None,
                    stage: Literal["raw", "repaired", "bvh", "character", "repaired_bvh", "repaired_character"] = "raw"):
    from motionlint.core.config import DEFAULT_CONFIG
    import hashlib
    policy = DEFAULT_CONFIG
    frozen = False
    if (source is None) != (task_id is None):
        raise HTTPException(422, "source 和 task_id 需要一起指定")
    if source is not None:
        task = _task_folder(TaskRef(source=source, task_id=task_id))
        if stage in {"repaired_bvh", "repaired_character"}:
            try:
                policy = export_artifact(task, "manifest_path").parent / "quality.yaml"
            except (ValueError, KeyError) as exc:
                raise HTTPException(409, str(exc))
            frozen = True
    return {"policy": load_config(policy), "frozen": frozen, "sha256": hashlib.sha256(policy.read_bytes()).hexdigest()}


@app.get("/v1/motionlint/tasks/{source}/{task_id}/repair-summary")
def repair_summary(source: Literal["intergen", "lodge"], task_id: str):
    folder = _task_folder(TaskRef(source=source, task_id=task_id)) / "motionlint"
    report = folder / "repair_report.json"
    if not report.is_file():
        return {"repair": None}
    summary = json.loads(report.read_text(encoding="utf-8"))
    if "metadata" not in summary and (folder / "after/motionlint_report.json").is_file():
        historical = json.loads((folder / "after/motionlint_report.json").read_text(encoding="utf-8"))
        summary["metadata"] = historical.get("metadata", {})
        summary["historical_report"] = True
    if "issue_summary" not in summary and all((folder / stage / "motionlint_report.json").is_file() for stage in ("before", "after")):
        reports = [json.loads((folder / stage / "motionlint_report.json").read_text(encoding="utf-8")) for stage in ("before", "after")]
        summary["issue_summary"] = summarize_issues(*reports)
    return {"repair": summary}


@app.get("/v1/motionlint/tasks")
def list_tasks() -> list[dict]:
    rows = []
    for source, root in TASK_ROOTS.items():
        if not root.is_dir():
            continue
        for folder in root.iterdir():
            if not folder.is_dir():
                continue
            try:
                ref = TaskRef(source=source, task_id=folder.name)
                _motion_paths(ref)
            except (HTTPException, ValueError):
                continue
            rows.append({"source": source, "task_id": folder.name, "modified": folder.stat().st_mtime})
    return sorted(rows, key=lambda row: row["modified"], reverse=True)[:50]


@app.post("/v1/motionlint/inspect")
def inspect_task(ref: TaskRef) -> dict:
    _, report, gate, _ = _inspect_task(ref)
    report.metadata["inspection_stage"] = "raw"
    video = _stage_video_path(ref, "raw")
    return {"task": ref.model_dump(), "stage": "raw", "report": report.to_dict(), "gate": gate.to_dict(),
            "video_url": f"/v1/motionlint/tasks/{ref.source}/{ref.task_id}/stage-video/raw" if video else None}


@app.post("/v1/motionlint/inspect-stage")
def inspect_stage(req: StageRequest) -> dict:
    motion = _stage_motion(req)
    policy = None
    if req.stage in {"repaired_bvh", "repaired_character"}:
        policy = export_artifact(_task_folder(req), "manifest_path").parent / "quality.yaml"
    report = inspect(motion, config_path=policy)
    report.metadata["inspection_stage"] = req.stage
    gate = evaluate_gate(report, config_path=policy)
    folder = _task_folder(req) / "motionlint/stages" / req.stage
    _write_report(folder, report)
    _write_json(folder / "quality_gate.json", gate.to_dict())
    video = _stage_video_path(req, req.stage)
    return {"task": {"source": req.source, "task_id": req.task_id}, "stage": req.stage,
            "report": report.to_dict(), "gate": gate.to_dict(),
            "video_path": str(video) if video else None,
            "video_url": f"/v1/motionlint/tasks/{req.source}/{req.task_id}/stage-video/{req.stage}" if video else None}


@app.get("/v1/motionlint/tasks/{source}/{task_id}/stage-video/{stage}")
def stage_video(source: Literal["intergen", "lodge"], task_id: str, stage: Literal["raw", "repaired", "character", "repaired_character"]):
    path = _stage_video_path(TaskRef(source=source, task_id=task_id), stage)
    if path is None:
        raise HTTPException(404, "No matching video for this inspection stage")
    return FileResponse(path, media_type="video/mp4")


@app.post("/v1/motionlint/repair")
def repair_task(ref: TaskRef) -> dict:
    with MOTION_MUTATION_LOCK:
        return _repair_task(ref)


def _repair_task(ref: TaskRef) -> dict:
    key = (ref.source, ref.task_id)
    if (key in EXPORT_JOBS and not EXPORT_JOBS[key].done()) or read_export(_task_folder(ref)).get("status") in {"queued", "running"}:
        raise HTTPException(409, "角色导出正在读取修复动作，请等待导出完成后再修复")
    motion, _, _, folder = _inspect_task(ref)
    outcome = repair(motion)
    outcome.before.metadata["inspection_stage"] = "raw"
    outcome.after.metadata["inspection_stage"] = "repaired"
    _write_report(folder / "before", outcome.before)
    _write_report(folder / "after", outcome.after)
    comparison = compare(outcome.before, outcome.after)
    _write_json(folder / "repair_report.json", outcome.to_dict())
    _write_json(folder / "comparison.json", comparison)
    if ref.source == "lodge":
        raw = outcome.raw_lodge if outcome.raw_lodge is not None else np.load(_motion_paths(ref)[0], allow_pickle=False)
        np.save(folder / "repaired.npy", raw)
    else:
        for actor in range(outcome.motion.actor_count):
            np.save(folder / f"repaired_actor{actor + 1}.npy", outcome.motion.positions[:, actor])
    gate = evaluate_gate(outcome.after)
    _write_json(folder / "after" / "quality_gate.json", gate.to_dict())
    render_status = "unchanged"
    if any(step["applied"] for step in outcome.steps):
        key = (ref.source, ref.task_id)
        if key not in RENDER_JOBS or RENDER_JOBS[key].done():
            _write_json(folder / "render_status.json", {"status": "queued"})
            RENDER_JOBS[key] = RENDER_EXECUTOR.submit(_render_comparison, ref, folder)
        render_status = "queued"
    return {"task": ref.model_dump(), "before": outcome.before.to_dict(), "after": outcome.after.to_dict(), "gate": gate.to_dict(), "repair": outcome.to_dict(), "comparison": comparison, "render_status": render_status}


def _export_character(ref: TaskRef, size: int) -> None:
    task = _task_folder(ref)
    status_path = task / "motionlint/character_export.json"
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTHONIOENCODING"] = "utf-8"
        python = RUNTIME_ROOT / "envs/intergen/Scripts/python.exe"
        with (task / "motionlint/character_export.log").open("w", encoding="utf-8") as log:
            result = subprocess.run([str(python), "-m", "motionlint.export_intergen", "--task", str(task),
                                     "--size", str(size)], cwd=REPO_ROOT, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=4200)
        if result.returncode:
            raise RuntimeError("角色导出失败，请查看任务 motionlint/character_export.log")
    except Exception as exc:
        state = json.loads(status_path.read_text(encoding="utf-8")) if status_path.is_file() else {}
        publish_export_status(task, {**state, "status": "failed", "error": str(exc)})


class CharacterExportRequest(TaskRef):
    size: Literal[360, 540, 720, 1080] = 540


@app.post("/v1/motionlint/export-character")
def export_character(req: CharacterExportRequest) -> dict:
    with MOTION_MUTATION_LOCK:
        return _queue_character_export(req)


def _queue_character_export(req: CharacterExportRequest) -> dict:
    if req.source != "intergen":
        raise HTTPException(422, "目前支持 InterGen 修复动作导出 Kenney 双人视频")
    task = _task_folder(req)
    paths = [task / "motionlint" / f"repaired_actor{actor}.npy" for actor in (1, 2)]
    if not all(path.is_file() for path in paths):
        raise HTTPException(409, "请先执行 Repair All，保存修复后的双人动作")
    key = (req.source, req.task_id)
    if (key in EXPORT_JOBS and not EXPORT_JOBS[key].done()) or read_export(task).get("status") in {"queued", "running"}:
        return read_export(task)
    publish_export_status(task, {"status": "queued", "phase": "queued", "pid": os.getpid()})
    EXPORT_JOBS[key] = RENDER_EXECUTOR.submit(_export_character, req, req.size)
    return {"status": "queued", "phase": "queued"}


@app.get("/v1/motionlint/tasks/{source}/{task_id}/character-export-status")
def character_export_status(source: Literal["intergen", "lodge"], task_id: str) -> dict:
    task = _task_folder(TaskRef(source=source, task_id=task_id))
    state = read_export(task)
    if state.get("status") == "ready":
        base = f"/v1/motionlint/tasks/{source}/{task_id}"
        state.update(video_url=f"{base}/stage-video/repaired_character", bundle_url=f"{base}/character-export-download")
    return state


@app.get("/v1/motionlint/tasks/{source}/{task_id}/character-export-download")
def character_export_download(source: Literal["intergen", "lodge"], task_id: str):
    task = _task_folder(TaskRef(source=source, task_id=task_id))
    try:
        path = export_artifact(task, "bundle_path")
    except (ValueError, KeyError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(path, media_type="application/zip", filename=f"{task_id}_repaired_kenney.zip")


def _render_comparison(ref: TaskRef, folder: Path) -> None:
    status_path = folder / "render_status.json"
    _write_json(status_path, {"status": "running"})
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            candidates = list((RUNTIME_ROOT / "envs" / "lodge" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries").glob("ffmpeg*.exe"))
            if not candidates:
                raise FileNotFoundError("FFmpeg is required to render the comparison video")
            ffmpeg = str(candidates[0])
        if ref.source == "lodge":
            python = RUNTIME_ROOT / "envs" / "lodge" / "Scripts" / "python.exe"
            env["LODGE_FFMPEG_EXE"] = str(ffmpeg)
            if not sorted((_task_folder(ref) / "input" / "video").glob("*smplx.mp4")):
                original_command = [str(python), str(REPO_ROOT / "LODGE_api" / "render_smplx_local.py"), "--input", str(_motion_paths(ref)[0]), "--output", str(folder / "original.mp4"), "--size", "360", "--fps", "30"]
                subprocess.run(original_command, cwd=REPO_ROOT, env=env, check=True, capture_output=True, text=True, timeout=3600)
            command = [str(python), str(REPO_ROOT / "LODGE_api" / "render_smplx_local.py"), "--input", str(folder / "repaired.npy"), "--output", str(folder / "repaired_silent.mp4"), "--size", "360", "--fps", "30"]
            subprocess.run(command, cwd=REPO_ROOT, env=env, check=True, capture_output=True, text=True, timeout=3600)
            original = _original_video(ref)
            mux = [str(ffmpeg), "-y", "-loglevel", "error", "-i", str(folder / "repaired_silent.mp4")]
            if original is not None:
                mux += ["-i", str(original), "-map", "0:v:0", "-map", "1:a:0?", "-c:v", "copy", "-c:a", "aac"]
            else:
                mux += ["-c", "copy"]
            duration = len(np.load(folder / "repaired.npy", mmap_mode="r", allow_pickle=False)) / 30
            mux += ["-t", f"{duration:.3f}", str(folder / "repaired.mp4")]
            subprocess.run(mux, cwd=REPO_ROOT, check=True, capture_output=True, text=True, timeout=300)
        else:
            python = RUNTIME_ROOT / "envs" / "intergen" / "Scripts" / "python.exe"
            script = REPO_ROOT / "motionlint" / "render_intergen_preview.py"
            original_paths = _motion_paths(ref)
            for name, paths in (("original", original_paths), ("repaired", [folder / f"repaired_actor{actor}.npy" for actor in (1, 2)])):
                command = [str(python), str(script), "--input", *(str(path) for path in paths), "--output", str(folder / f"{name}.mp4")]
                command += ["--camera-reference", *(str(path) for path in original_paths)]
                subprocess.run(command, cwd=REPO_ROOT, env=env, check=True, capture_output=True, text=True, timeout=1200)
        for kind in ("original", "repaired"):
            video = (folder / "original.mp4") if kind == "original" and (folder / "original.mp4").is_file() else (_original_video(ref) if kind == "original" else folder / "repaired.mp4")
            if video is not None:
                subprocess.run([str(ffmpeg), "-y", "-loglevel", "error", "-ss", "1", "-i", str(video), "-frames:v", "1", str(folder / f"{kind}.png")], cwd=REPO_ROOT, check=True, capture_output=True, text=True, timeout=60)
        _write_json(status_path, {"status": "ready"})
    except Exception as exc:
        _write_json(status_path, {"status": "failed", "error": str(exc)[-500:]})


def _original_video(ref: TaskRef) -> Path | None:
    folder = _task_folder(ref)
    if ref.source == "lodge":
        candidates = sorted((folder / "input" / "video").glob("*smplx.mp4"))
        candidates += sorted((folder / "retarget").glob("*.mp4"))
    else:
        candidates = sorted((folder / "retarget").glob("*dual_retarget.mp4"))
    return candidates[0] if candidates else None


@app.get("/v1/motionlint/tasks/{source}/{task_id}/render-status")
def comparison_render_status(source: Literal["intergen", "lodge"], task_id: str) -> dict:
    folder = _task_folder(TaskRef(source=source, task_id=task_id)) / "motionlint"
    path = folder / "render_status.json"
    if not path.is_file():
        return {"status": "unavailable"}
    import json
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/v1/motionlint/tasks/{source}/{task_id}/comparison-video/{kind}")
def comparison_video(source: Literal["intergen", "lodge"], task_id: str, kind: Literal["original", "repaired"]):
    ref = TaskRef(source=source, task_id=task_id)
    folder = _task_folder(ref) / "motionlint"
    if source == "lodge" and kind == "original":
        path = folder / "original.mp4" if (folder / "original.mp4").is_file() else _original_video(ref)
    else:
        path = folder / f"{kind}.mp4"
    if path is None or not path.is_file():
        raise HTTPException(404, "Comparison video is not ready")
    return FileResponse(path, media_type="video/mp4")


@app.get("/v1/motionlint/tasks/{source}/{task_id}/comparison-poster/{kind}")
def comparison_poster(source: Literal["intergen", "lodge"], task_id: str, kind: Literal["original", "repaired"]):
    folder = _task_folder(TaskRef(source=source, task_id=task_id)) / "motionlint"
    path = folder / f"{kind}.png"
    if not path.is_file():
        raise HTTPException(404, "Comparison poster is not ready")
    return FileResponse(path, media_type="image/png")


@app.post("/v1/motionlint/compare")
def compare_tasks(req: CompareRequest) -> dict:
    _, baseline, _, _ = _inspect_task(req.baseline)
    _, candidate, _, _ = _inspect_task(req.candidate)
    comparison = compare(baseline, candidate)
    folder = REPO_ROOT / "reports" / f"{req.baseline.task_id}_vs_{req.candidate.task_id}"
    _write_json(folder / "comparison.json", comparison)
    return comparison


@app.get("/v1/motionlint/tasks/{source}/{task_id}/video")
def task_video(source: Literal["intergen", "lodge"], task_id: str):
    folder = _task_folder(TaskRef(source=source, task_id=task_id))
    if source == "intergen":
        candidates = sorted((folder / "retarget").glob("*dual_retarget.mp4"))
        candidates += sorted((folder / "output").glob("*.mp4"))
    else:
        candidates = sorted((folder / "input" / "video").glob("*smplx.mp4"))
        candidates += sorted((folder / "retarget").glob("*.mp4"))
    if not candidates:
        raise HTTPException(404, "No preview video for this task")
    return FileResponse(candidates[0], media_type="video/mp4")
