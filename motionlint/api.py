"""Local API for inspecting and repairing persisted generator task artifacts."""

from __future__ import annotations

from pathlib import Path
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import os
import shutil
import subprocess
from uuid import UUID, uuid4
from typing import Literal

import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from motionlint.cli.main import _write_json, _write_report, load_motion
from motionlint.adapters.character_adapter import load_character
from motionlint.adapters.bvh_adapter import load_bvh_pair
from motionlint.core.config import load_config
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.regression import compare
from motionlint.pipeline.repair_pipeline import repair, summarize_issues
from motionlint.import_io import MAX_IMPORT_BYTES, finish_import, import_manifest, imported_paths, load_imported_motion, preview_frames, public_import


REPO_ROOT = Path(__file__).resolve().parents[1]
TASK_ROOTS = {
    "intergen": REPO_ROOT / "InterGen_api" / "task_runs",
    "lodge": REPO_ROOT / "LODGE_api" / "task_runs",
    "import": REPO_ROOT / "motionlint/task_runs/imports",
}
RUNTIME_ROOT = REPO_ROOT.parent / "HumanAction-runtime"
RENDER_EXECUTOR = ThreadPoolExecutor(max_workers=1)
RENDER_JOBS = {}
MOTION_MUTATION_LOCK = Lock()

app = FastAPI(title="MotionLint Local API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"], allow_methods=["GET", "POST"], allow_headers=["*"])


class TaskRef(BaseModel):
    source: Literal["intergen", "lodge", "import"]
    task_id: str


class CompareRequest(BaseModel):
    baseline: TaskRef
    candidate: TaskRef


class StageRequest(TaskRef):
    stage: Literal["raw", "repaired", "bvh", "character"] = "raw"


class ImportOptions(BaseModel):
    fps: float = Field(default=30, gt=0, le=240, allow_inf_nan=False)
    unit_scale: float = Field(default=1, gt=0, le=100, allow_inf_nan=False)
    up_axis: Literal[0, 1, 2] = 1
    joint_mapping: dict[str, str] = Field(default_factory=dict)


def _stage_video_path(ref: TaskRef, stage: str) -> Path | None:
    task = _task_folder(ref)
    if ref.source == "import":
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
        if comparison_render_status(ref.source, ref.task_id).get("status") != "ready":
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
    if req.source == "import" and req.stage != "raw":
        raise HTTPException(422, "导入动作当前支持原始数据检查与回归比较。")
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
        command = [os.getenv("INTERGEN_BLENDER_EXE", str(RUNTIME_ROOT / "blender-4.2.23-windows-x64/blender.exe")), "-b", str(blend),
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
    if ref.source == "import":
        try:
            return imported_paths(folder)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, "导入记录或原始文件不可用，请重新导入。") from exc
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
    if ref.source == "import":
        try:
            return load_imported_motion(_task_folder(ref))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, "导入动作数据无法读取，请重新导入。") from exc
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


@app.post("/v1/motionlint/imports")
async def import_motion(files: list[UploadFile] = File(...), fps: float = Form(30), unit_scale: float = Form(1),
                        up_axis: int = Form(1), joint_mapping: str = Form("{}", max_length=65536)):
    if not 1 <= len(files) <= 2:
        raise HTTPException(422, "请选择一个动作文件，或一对同步的关节 NPY / BVH 文件。")
    names = [Path((file.filename or "").replace("\\", "/")).name for file in files]
    suffixes = [Path(name).suffix.lower() for name in names]
    if any(suffix not in {".npy", ".bvh"} for suffix in suffixes) or len(set(suffixes)) != 1:
        raise HTTPException(422, "仅支持 NPY 或 BVH；双人文件需要使用同一种格式。")
    try:
        options = ImportOptions(fps=fps, unit_scale=unit_scale, up_axis=up_axis,
                                joint_mapping=json.loads(joint_mapping)).model_dump()
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "帧率、单位、坐标轴或关节映射参数无效；映射需要是 JSON 名称对应表。") from exc
    if suffixes[0] == ".npy" and (unit_scale != 1 or up_axis != 1 or options["joint_mapping"]):
        raise HTTPException(422, "NPY 使用固定的米 / Y-up 约定；单位、坐标轴和映射选项仅用于 BVH。")
    root = TASK_ROOTS["import"].resolve()
    folder = root / str(uuid4())
    root.mkdir(parents=True, exist_ok=True)
    folder.mkdir()
    entries = []
    total = 0
    try:
        for index, upload in enumerate(files):
            name = f"actor{index + 1}{suffixes[index]}"
            path = folder / name
            with path.open("wb") as output:
                while chunk := await upload.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_IMPORT_BYTES:
                        raise HTTPException(413, "动作文件合计不能超过 32 MB，请裁剪文件后导入。")
                    output.write(chunk)
            if path.stat().st_size == 0:
                raise HTTPException(422, "动作文件为空，请重新选择。")
            entries.append({"name": names[index], "path": name})
        result = await run_in_threadpool(finish_import, folder, entries, options)
        result["preview_url"] = f"/v1/motionlint/imports/{folder.name}/preview"
        return result
    except Exception as exc:
        # Only this request's newly created UUID directory may be removed.
        checked = folder.resolve()
        checked.relative_to(root)
        if checked.parent == root and checked.name == folder.name:
            shutil.rmtree(checked)
        if isinstance(exc, HTTPException):
            raise
        if isinstance(exc, (ValueError, OSError, KeyError, IndexError, AssertionError, TypeError)):
            raise HTTPException(422, "无法解析动作文件：" + str(exc)[:300]) from exc
        raise
    finally:
        for upload in files:
            await upload.close()


@app.get("/v1/motionlint/imports/{task_id}")
def imported_motion(task_id: str):
    folder = _task_folder(TaskRef(source="import", task_id=task_id))
    try:
        return public_import(import_manifest(folder))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, "导入记录或原始文件不可用，请重新导入。") from exc


@app.get("/v1/motionlint/imports/{task_id}/preview")
def imported_preview(task_id: str, start: int = Query(0, ge=0), count: int = Query(120, ge=1, le=240)):
    folder = _task_folder(TaskRef(source="import", task_id=task_id))
    try:
        return preview_frames(folder, start, count)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, "骨架预览不可用或帧超出范围，请重新导入。") from exc


@app.get("/v1/motionlint/imports/{task_id}/report")
def imported_report(task_id: str):
    folder = _task_folder(TaskRef(source="import", task_id=task_id))
    stage = folder / "motionlint/stages/raw"
    try:
        contents = {"import": public_import(import_manifest(folder)),
            "report": json.loads((stage / "motionlint_report.json").read_text(encoding="utf-8")),
            "gate": json.loads((stage / "quality_gate.json").read_text(encoding="utf-8"))}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(404, "导入检查报告不可用，请重新检查动作。") from exc
    return JSONResponse(contents, headers={"Content-Disposition": f'attachment; filename="motionlint-{task_id}.json"'})


@app.get("/v1/motionlint/config")
def quality_config() -> dict:
    return load_config()


@app.get("/v1/motionlint/settings")
def motion_settings(source: Literal["intergen", "lodge", "import"] | None = None, task_id: str | None = None,
                    stage: Literal["raw", "repaired", "bvh", "character"] = "raw"):
    from motionlint.core.config import DEFAULT_CONFIG
    import hashlib
    policy = DEFAULT_CONFIG
    if (source is None) != (task_id is None):
        raise HTTPException(422, "source 和 task_id 需要一起指定")
    if source is not None:
        _task_folder(TaskRef(source=source, task_id=task_id))
    return {"policy": load_config(policy), "frozen": False, "sha256": hashlib.sha256(policy.read_bytes()).hexdigest()}


@app.get("/v1/motionlint/tasks/{source}/{task_id}/repair-summary")
def repair_summary(source: Literal["intergen", "lodge", "import"], task_id: str):
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
            row = {"source": source, "task_id": folder.name, "modified": folder.stat().st_mtime}
            if source == "import":
                row["title"] = imported_motion(folder.name)["title"]
            rows.append(row)
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
    report = inspect(motion)
    report.metadata["inspection_stage"] = req.stage
    gate = evaluate_gate(report)
    folder = _task_folder(req) / "motionlint/stages" / req.stage
    _write_report(folder, report)
    _write_json(folder / "quality_gate.json", gate.to_dict())
    video = _stage_video_path(req, req.stage)
    result = {"task": {"source": req.source, "task_id": req.task_id}, "stage": req.stage,
            "report": report.to_dict(), "gate": gate.to_dict(),
            "video_path": str(video) if video else None,
            "video_url": f"/v1/motionlint/tasks/{req.source}/{req.task_id}/stage-video/{req.stage}" if video else None}
    if req.source == "import":
        result["import"] = imported_motion(req.task_id)
    return result


@app.get("/v1/motionlint/tasks/{source}/{task_id}/stage-video/{stage}")
def stage_video(source: Literal["intergen", "lodge", "import"], task_id: str, stage: Literal["raw", "repaired", "character"]):
    path = _stage_video_path(TaskRef(source=source, task_id=task_id), stage)
    if path is None:
        raise HTTPException(404, "No matching video for this inspection stage")
    return FileResponse(path, media_type="video/mp4")


@app.post("/v1/motionlint/repair")
def repair_task(ref: TaskRef) -> dict:
    with MOTION_MUTATION_LOCK:
        return _repair_task(ref)


def _repair_task(ref: TaskRef) -> dict:
    if ref.source == "import":
        raise HTTPException(422, "导入动作当前支持检查与回归比较，尚未提供修复导出。")
    job = RENDER_JOBS.get((ref.source, ref.task_id))
    if job is not None and not job.done():
        raise HTTPException(409, "修复视频仍在渲染，请完成后再重新修复。")
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
        _queue_comparison_render(ref, folder)
        render_status = "queued"
    elif (folder / "render_status.json").is_file():
        _write_json(folder / "render_status.json", {"status": "unavailable", "error": "本次未接受修复，之前的修复视频已失效。"})
    return {"task": ref.model_dump(), "before": outcome.before.to_dict(), "after": outcome.after.to_dict(), "gate": gate.to_dict(), "repair": outcome.to_dict(), "comparison": comparison, "render_status": render_status}


def _repaired_paths(ref, folder):
    return ([folder / "repaired.npy"] if ref.source == "lodge" else
            [folder / f"repaired_actor{actor}.npy" for actor in (1, 2)])


def _render_inputs(ref, folder):
    task = _task_folder(ref).resolve()
    result = {}
    for path in [*_motion_paths(ref), *_repaired_paths(ref, folder)]:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        result[str(path.resolve().relative_to(task))] = digest.hexdigest()
    return result


def _render_fresh(ref, folder, status):
    video = folder / "repaired.mp4"
    if not video.is_file():
        return False
    try:
        if status.get("inputs"):
            return status["inputs"] == _render_inputs(ref, folder)
        # Legacy renders have no hash; still enforce the existing freshness rule.
        paths = [*_motion_paths(ref), *_repaired_paths(ref, folder)]
        return all(path.is_file() and path.stat().st_mtime_ns <= video.stat().st_mtime_ns for path in paths)
    except (HTTPException, OSError, ValueError):
        return False


def _queue_comparison_render(ref, folder):
    state = {"status": "queued", "version": str(uuid4()), "inputs": _render_inputs(ref, folder)}
    _write_json(folder / "render_status.json", state)
    try:
        RENDER_JOBS[(ref.source, ref.task_id)] = RENDER_EXECUTOR.submit(_render_comparison, ref, folder, state)
    except Exception as exc:
        _write_json(folder / "render_status.json", {**state, "status": "failed", "error": f"渲染任务提交失败：{exc}"})
        raise HTTPException(503, "渲染任务未能提交，请重新渲染。") from exc


@app.post("/v1/motionlint/tasks/{source}/{task_id}/render")
def retry_comparison_render(source: Literal["intergen", "lodge", "import"], task_id: str):
    if source == "import":
        raise HTTPException(422, "导入动作使用骨架预览，无需渲染视频。")
    ref = TaskRef(source=source, task_id=task_id)
    folder = _task_folder(ref) / "motionlint"
    with MOTION_MUTATION_LOCK:
        job = RENDER_JOBS.get((source, task_id))
        if job is not None and not job.done():
            return {"status": "running"}
        if not (folder / "repair_report.json").is_file() or not all(path.is_file() for path in _repaired_paths(ref, folder)):
            raise HTTPException(404, "请先修复动作，再生成对比视频。")
        _queue_comparison_render(ref, folder)
    return {"status": "queued"}


def _render_comparison(ref: TaskRef, folder: Path, state: dict) -> None:
    status_path = folder / "render_status.json"
    _write_json(status_path, {**state, "status": "running"})
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
        ffmpeg = os.getenv("LODGE_FFMPEG_EXE") or shutil.which("ffmpeg")
        if not ffmpeg:
            candidates = list((RUNTIME_ROOT / "envs" / "lodge" / "Lib" / "site-packages" / "imageio_ffmpeg" / "binaries").glob("ffmpeg*.exe"))
            if not candidates:
                raise FileNotFoundError("FFmpeg is required to render the comparison video")
            ffmpeg = str(candidates[0])
        if ref.source == "lodge":
            python = os.getenv("LODGE_PYTHON", str(RUNTIME_ROOT / "envs" / "lodge" / "Scripts" / "python.exe"))
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
            duration = len(np.load(folder / "repaired.npy", allow_pickle=False)) / 30
            mux += ["-t", f"{duration:.3f}", str(folder / "repaired.mp4")]
            subprocess.run(mux, cwd=REPO_ROOT, check=True, capture_output=True, text=True, timeout=300)
        else:
            python = os.getenv("MOTIONLINT_PREVIEW_PYTHON") or os.getenv("INTERGEN_PYTHON", str(RUNTIME_ROOT / "envs" / "intergen" / "Scripts" / "python.exe"))
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
        with MOTION_MUTATION_LOCK:
            if state["inputs"] != _render_inputs(ref, folder):
                raise ValueError("渲染期间动作数据发生变化，请重新渲染。")
            _write_json(status_path, {**state, "status": "ready"})
    except Exception as exc:
        _write_json(status_path, {**state, "status": "failed", "error": str(exc)[-500:]})


def _original_video(ref: TaskRef) -> Path | None:
    folder = _task_folder(ref)
    if ref.source == "lodge":
        candidates = sorted((folder / "input" / "video").glob("*smplx.mp4"))
        candidates += sorted((folder / "retarget").glob("*.mp4"))
    else:
        candidates = sorted((folder / "retarget").glob("*dual_retarget.mp4"))
    return candidates[0] if candidates else None


@app.get("/v1/motionlint/tasks/{source}/{task_id}/render-status")
def comparison_render_status(source: Literal["intergen", "lodge", "import"], task_id: str) -> dict:
    with MOTION_MUTATION_LOCK:
        return _comparison_render_status(source, task_id)


def _comparison_render_status(source, task_id):
    ref = TaskRef(source=source, task_id=task_id)
    folder = _task_folder(ref) / "motionlint"
    path = folder / "render_status.json"
    if not path.is_file():
        return {"status": "unavailable"}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("Invalid render status")
    except (OSError, ValueError):
        return {"status": "failed", "error": "渲染状态记录不可读取，请重新渲染。"}
    job = RENDER_JOBS.get((source, task_id))
    if state.get("status") in {"queued", "running"} and (job is None or job.done()):
        state = {**state, "status": "failed", "error": "服务重启或渲染任务中断，请重新渲染。"}
        _write_json(path, state)
    if state.get("status") == "ready" and not _render_fresh(ref, folder, state):
        return {**state, "status": "failed", "error": "动作数据已变化或视频缺失，请重新渲染。"}
    return state


@app.get("/v1/motionlint/tasks/{source}/{task_id}/comparison-video/{kind}")
def comparison_video(source: Literal["intergen", "lodge", "import"], task_id: str, kind: Literal["original", "repaired"]):
    ref = TaskRef(source=source, task_id=task_id)
    folder = _task_folder(ref) / "motionlint"
    if comparison_render_status(source, task_id).get("status") != "ready":
        raise HTTPException(404, "Comparison video is not ready or no longer matches the motion")
    if source == "lodge" and kind == "original":
        path = folder / "original.mp4" if (folder / "original.mp4").is_file() else _original_video(ref)
    else:
        path = folder / f"{kind}.mp4"
    if path is None or not path.is_file():
        raise HTTPException(404, "Comparison video is not ready")
    return FileResponse(path, media_type="video/mp4")


@app.get("/v1/motionlint/tasks/{source}/{task_id}/comparison-poster/{kind}")
def comparison_poster(source: Literal["intergen", "lodge", "import"], task_id: str, kind: Literal["original", "repaired"]):
    folder = _task_folder(TaskRef(source=source, task_id=task_id)) / "motionlint"
    if comparison_render_status(source, task_id).get("status") != "ready":
        raise HTTPException(404, "Comparison poster is not ready or no longer matches the motion")
    path = folder / f"{kind}.png"
    if not path.is_file():
        raise HTTPException(404, "Comparison poster is not ready")
    return FileResponse(path, media_type="image/png")


@app.post("/v1/motionlint/compare")
def compare_tasks(req: CompareRequest) -> dict:
    baseline_motion, baseline, _, _ = _inspect_task(req.baseline)
    candidate_motion, candidate, _, _ = _inspect_task(req.candidate)
    if "import" in {req.baseline.source, req.candidate.source} and (
            baseline_motion.joint_names != candidate_motion.joint_names
            or baseline_motion.actor_count != candidate_motion.actor_count
            or not np.isclose(baseline_motion.fps, candidate_motion.fps)
            or baseline_motion.metadata.get("up_axis", 1) != candidate_motion.metadata.get("up_axis", 1)
            or baseline.metadata["geometry_source"] != candidate.metadata["geometry_source"]):
        raise HTTPException(422, "导入动作的回归比较需要相同的骨架、人数、帧率、竖直轴与几何来源。")
    comparison = compare(baseline, candidate)
    folder = REPO_ROOT / "reports" / f"{req.baseline.task_id}_vs_{req.candidate.task_id}"
    _write_json(folder / "comparison.json", comparison)
    return comparison


@app.get("/v1/motionlint/tasks/{source}/{task_id}/video")
def task_video(source: Literal["intergen", "lodge", "import"], task_id: str):
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
