"""Local API for inspecting and repairing persisted generator task artifacts."""

from __future__ import annotations

from pathlib import Path
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, RLock
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
from motionlint.artifacts import persist_repair, current_run, stage_motion, public_run, sha256
from motionlint.character_export import resources as character_resources, export_character, checked_character
from motionlint.jobs import data_root, Job, list_jobs


REPO_ROOT = Path(os.environ.get('MOTIONLINT_REPO', Path(__file__).resolve().parents[1])).resolve()
DATA_ROOT = data_root()
TASK_ROOTS = {
    "intergen": REPO_ROOT / "InterGen_api" / "task_runs" if (REPO_ROOT / "InterGen_api/task_runs").is_dir() else DATA_ROOT / 'intergen',
    "lodge": REPO_ROOT / "LODGE_api" / "task_runs" if (REPO_ROOT / "LODGE_api/task_runs").is_dir() else DATA_ROOT / 'lodge',
    "import": DATA_ROOT / 'imports',
}
RUNTIME_ROOT = Path(os.environ.get('MOTIONLINT_RUNTIME', REPO_ROOT.parent / "HumanAction-runtime"))
RENDER_EXECUTOR = ThreadPoolExecutor(max_workers=1)
RENDER_JOBS = {}
CHARACTER_EXECUTOR = ThreadPoolExecutor(max_workers=1)
CHARACTER_JOBS = {}
MOTION_MUTATION_LOCK = Lock()

app = FastAPI(title="MotionLint Local API", version="0.5.0")
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


class ReimportRequest(TaskRef):
    stage: Literal['repaired', 'bvh'] = 'repaired'
    run_id: str | None = None


class PipelineRequest(TaskRef):
    character: bool = False


PIPELINE_EXECUTOR = ThreadPoolExecutor(max_workers=1)
PIPELINE_JOBS = {}
PIPELINE_QUEUE_LOCK = RLock()


def _pipeline_worker(job, req):
    from motionlint.pipeline.local import run_pipeline
    from motionlint.import_io import import_manifest
    try:
        task = _task_folder(req)
        options = import_manifest(task)['options'] if req.source == 'import' else {'fps': _inspect_task(req)[0].fps}
        run_pipeline(_motion_paths(req), output=TASK_ROOTS['import'] / str(uuid4()), job=job,
            character=req.character, runtime=RUNTIME_ROOT, repo=REPO_ROOT, **options)
    except Exception as exc:
        if job.state['status'] not in {'failed', 'cancelled'}:
            job.update('failed', error=f'{type(exc).__name__}: {exc}')


@app.post('/v1/motionlint/pipeline')
def queue_pipeline(req: PipelineRequest):
    _task_folder(req)
    with PIPELINE_QUEUE_LOCK:
        for job_id, future in PIPELINE_JOBS.items():
            old = Job(job_id=job_id, create=False)
            if not future.done() and old.state.get('request') == req.model_dump():
                return old.state
        job = Job()
        job.update(request=req.model_dump())
        PIPELINE_JOBS[job.id] = PIPELINE_EXECUTOR.submit(_pipeline_worker, job, req)
        return job.state


@app.get('/v1/motionlint/jobs')
def persistent_jobs():
    return list_jobs()


@app.get('/v1/motionlint/jobs/{job_id}')
def persistent_job(job_id: str):
    try:
        return Job(job_id=job_id, create=False).recover()
    except (ValueError, OSError) as exc:
        raise HTTPException(404, '任务记录不存在') from exc


@app.post('/v1/motionlint/jobs/{job_id}/cancel')
def cancel_persistent_job(job_id: str):
    job = Job(job_id=job_id, create=False)
    job.cancel()
    return job.state


@app.post('/v1/motionlint/jobs/{job_id}/retry')
def retry_persistent_job(job_id: str):
    old = Job(job_id=job_id, create=False)
    if old.recover()['status'] not in {'failed', 'interrupted', 'cancelled'}:
        raise HTTPException(409, '仅失败、中断或取消的任务可重试')
    if 'request' not in old.state:
        raise HTTPException(422, '此任务由命令行启动，请使用原命令重试；已有产物会保留')
    request = PipelineRequest(**old.state['request'])
    result = queue_pipeline(request)
    fresh = Job(job_id=result['job_id'], create=False)
    fresh.update(parent_job_id=job_id, attempt=old.state['attempt'] + 1)
    return fresh.state


@app.get('/v1/motionlint/tasks/{source}/{task_id}/repairs/{run_id}/html')
def repair_html(source: str, task_id: str, run_id: str):
    ref = TaskRef(source=source, task_id=task_id)
    folder, _ = _checked_run(ref, run_id)
    return FileResponse(folder / 'report.html', media_type='text/html', filename='motionlint-report.html')


def _preview_description(motion, ref, run_id=None):
    return {'task_id': ref.task_id, 'source': ref.source, 'fps': motion.fps, 'frame_count': motion.frame_count,
            'actor_count': motion.actor_count, 'joint_count': len(motion.joint_names), 'up_axis': motion.metadata.get('up_axis', 1),
            'run_id': run_id}


def _checked_run(ref, run_id=None):
    try:
        return current_run(_task_folder(ref), run_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, '请先完成修复，再查看对应产物。') from exc
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get('/v1/motionlint/tasks/{source}/{task_id}/preview')
def task_preview(source: Literal['intergen', 'lodge', 'import'], task_id: str,
                 stage: Literal['raw', 'repaired', 'bvh', 'character'] = 'raw',
                 start: int = Query(0, ge=0), count: int = Query(120, ge=1, le=240), run_id: str | None = None):
    ref = StageRequest(source=source, task_id=task_id, stage=stage)
    if stage == 'character':
        motion = _stage_motion(ref)
        if run_id and motion.metadata.get('repair_run_id') != run_id:
            # The scene adapter records the original run in its sidecar manifest.
            folder, state = checked_character(_task_folder(ref))
            if state['source_run_id'] != run_id:
                raise HTTPException(409, '角色骨架对应不同的修复记录')
    elif run_id:
        folder, manifest = _checked_run(ref, run_id)
        if stage not in manifest['stages']:
            raise HTTPException(404, '对应处理阶段尚未导出')
        from motionlint.artifacts import read_motion
        motion = read_motion(folder / manifest['stages'][stage]['snapshot'])
    else:
        motion = _stage_motion(ref)
    if start >= motion.frame_count:
        raise HTTPException(422, '预览帧超出了动作范围')
    return {'start': start, 'positions': motion.positions[start:start + count].tolist(), 'fps': motion.fps,
            'frame_count': motion.frame_count, 'joint_names': motion.joint_names, 'parents': motion.metadata['parents'],
            'up_axis': motion.metadata.get('up_axis', 1), 'stage': stage,
            'bounds': [motion.positions.min(axis=(0, 1, 2)).tolist(), motion.positions.max(axis=(0, 1, 2)).tolist()]}


@app.get('/v1/motionlint/tasks/{source}/{task_id}/repairs')
def repair_artifacts(source: Literal['intergen', 'lodge', 'import'], task_id: str):
    _, manifest = _checked_run(TaskRef(source=source, task_id=task_id))
    return public_run(manifest, source, task_id)


@app.get('/v1/motionlint/tasks/{source}/{task_id}/repairs/{run_id}/bundle')
def repair_bundle(source: Literal['intergen', 'lodge', 'import'], task_id: str, run_id: str):
    folder, _ = _checked_run(TaskRef(source=source, task_id=task_id), run_id)
    ready = json.loads((folder / 'ready.json').read_text(encoding='utf-8'))
    path = folder / 'bundle.zip'
    if not path.is_file() or sha256(path) != ready['bundle_sha256']:
        raise HTTPException(409, '下载包已变化，请重新修复')
    return FileResponse(path, media_type='application/zip', filename=f'motionlint-{task_id}-{run_id[:8]}.zip')


@app.get('/v1/motionlint/tasks/{source}/{task_id}/repairs/{run_id}/files/{key}')
def repair_file(source: Literal['intergen', 'lodge', 'import'], task_id: str, run_id: str, key: str):
    folder, manifest = _checked_run(TaskRef(source=source, task_id=task_id), run_id)
    entry = next((entry for entry in manifest['files'] if entry['key'] == key and entry['download']), None)
    if not entry:
        raise HTTPException(404, '该文件不可下载')
    path = folder / entry['path']
    return FileResponse(path, media_type='application/octet-stream', filename=path.name)


@app.post('/v1/motionlint/reimport')
def reimport_artifact(req: ReimportRequest):
    run, manifest = _checked_run(req, req.run_id)
    if req.stage not in manifest['stages']:
        raise HTTPException(404, '对应处理阶段尚未导出')
    if req.stage == 'repaired':
        entries = manifest['export']
    else:
        bvh_options = next((entry['options'] for entry in manifest['export'] if entry['format'] == 'bvh'),
            {'fps': manifest['stages']['bvh']['fps'], 'unit_scale': 1, 'up_axis': manifest['stages']['bvh']['up_axis'], 'joint_mapping': {}})
        entries = [{'key': entry['key'], 'options': bvh_options}
                   for entry in manifest['files'] if entry['download'] and entry['path'].endswith('.bvh')]
    root = TASK_ROOTS['import']
    folder = root / str(uuid4())
    folder.mkdir(parents=True)
    files = []
    try:
        for actor, entry in enumerate(entries, 1):
            record = next(record for record in manifest['files'] if record['key'] == entry['key'])
            original = run / record['path']
            filename = f'actor{actor}{original.suffix}'
            shutil.copyfile(original, folder / filename)
            files.append({'name': original.name, 'path': filename})
        result = finish_import(folder, files, entries[0]['options'])
        data = import_manifest(folder)
        data['parent_artifact'] = {'source': req.source, 'task_id': req.task_id, 'run_id': manifest['run_id'], 'stage': req.stage}
        _write_json(folder / 'import.json', data)
        return result
    except Exception as exc:
        checked = folder.resolve()
        if checked.parent == root.resolve() and checked.name == folder.name:
            shutil.rmtree(checked)
        raise HTTPException(422, f'实际导出文件重新导入失败：{exc}') from exc


def _stage_video_path(ref: TaskRef, stage: str) -> Path | None:
    task = _task_folder(ref)
    if stage == 'character' and (task / 'motionlint/current_repair.json').is_file():
        try:
            folder, _ = checked_character(task)
            return folder / 'kenney.mp4'
        except (OSError, ValueError, KeyError):
            return None
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
    if req.stage == 'character' and (task / 'motionlint/current_repair.json').is_file():
        try:
            folder, state = checked_character(task)
            motion = load_character(folder / 'character.npz')
            motion.metadata.update(stage='character', repair_run_id=state['source_run_id'])
            return motion
        except FileNotFoundError as exc:
            raise HTTPException(404, '请先完成当前修复结果的 Kenney 角色导出。') from exc
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc
    if req.stage != 'raw' and (task / 'motionlint/current_repair.json').is_file():
        try:
            return stage_motion(task, req.stage)[0]
        except FileNotFoundError as exc:
            raise HTTPException(404, '该修复阶段尚未导出，请先完成对应导出。') from exc
        except (ValueError, KeyError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc
    if req.source == "import" and req.stage != "raw":
        raise HTTPException(404, "请先修复导入动作，再检查修复或导出阶段。")
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
    frozen = False
    if source is not None:
        task = _task_folder(TaskRef(source=source, task_id=task_id))
        if (task / 'motionlint/current_repair.json').is_file():
            try:
                folder, _ = current_run(task)
                policy = folder / 'quality.yaml'
                frozen = True
            except (ValueError, OSError, KeyError) as exc:
                raise HTTPException(409, str(exc)) from exc
    return {"policy": load_config(policy), "frozen": frozen, "sha256": hashlib.sha256(policy.read_bytes()).hexdigest()}


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
    motion.metadata = {**motion.metadata, 'stage': req.stage}
    policy = None
    task = _task_folder(req)
    artifact = None
    if (task / 'motionlint/current_repair.json').is_file():
        try:
            run, manifest = current_run(task)
            policy = run / 'quality.yaml'
            artifact = public_run(manifest, req.source, req.task_id)
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc
    report = inspect(motion, config_path=policy)
    report.metadata["inspection_stage"] = req.stage
    gate = evaluate_gate(report, config_path=policy)
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
    if artifact:
        result['artifacts'] = artifact
        result['preview'] = _preview_description(motion, req, artifact['run_id'])
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
    job = RENDER_JOBS.get((ref.source, ref.task_id))
    if job is not None and not job.done():
        raise HTTPException(409, "修复视频仍在渲染，请完成后再重新修复。")
    motion, _, _, folder = _inspect_task(ref)
    outcome = repair(motion)
    try:
        run, manifest = persist_repair(_task_folder(ref), outcome, motion, _motion_paths(ref))
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(422, f'修复结果无法可靠导出：{exc}') from exc
    outcome.before.metadata["inspection_stage"] = "raw"
    outcome.after.metadata["inspection_stage"] = "repaired"
    _write_report(folder / "before", outcome.before)
    _write_report(folder / "after", outcome.after)
    comparison = compare(outcome.before, outcome.after, baseline_motion=motion, candidate_motion=outcome.motion)
    _write_json(folder / "repair_report.json", outcome.to_dict())
    _write_json(folder / "comparison.json", comparison)
    if ref.source == "lodge":
        raw = outcome.raw_lodge if outcome.raw_lodge is not None else np.load(_motion_paths(ref)[0], allow_pickle=False)
        np.save(folder / "repaired.npy", raw)
    elif ref.source != 'import':
        for actor in range(outcome.motion.actor_count):
            np.save(folder / f"repaired_actor{actor + 1}.npy", outcome.motion.positions[:, actor])
    gate = evaluate_gate(outcome.after)
    _write_json(folder / "after" / "quality_gate.json", gate.to_dict())
    render_status = "unchanged"
    if ref.source == 'import':
        render_status = 'skeleton_ready'
    elif any(step["applied"] for step in outcome.steps):
        _queue_comparison_render(ref, folder)
        render_status = "queued"
    elif (folder / "render_status.json").is_file():
        _write_json(folder / "render_status.json", {"status": "unavailable", "error": "本次未接受修复，之前的修复视频已失效。"})
    return {"task": ref.model_dump(), "before": outcome.before.to_dict(), "after": outcome.after.to_dict(), "gate": gate.to_dict(), "repair": outcome.to_dict(), "comparison": comparison, "render_status": render_status,
            'artifacts': public_run(manifest, ref.source, ref.task_id),
            'preview': _preview_description(outcome.motion, ref, manifest['run_id'])}


def _repaired_paths(ref, folder):
    return ([folder / "repaired.npy"] if ref.source == "lodge" else
            [folder / f"repaired_actor{actor}.npy" for actor in (1, 2)])


@app.get('/v1/motionlint/character-resources')
def character_resource_status():
    return character_resources(REPO_ROOT, RUNTIME_ROOT)


@app.post('/v1/motionlint/export-character')
def start_character_export(ref: TaskRef):
    task = _task_folder(ref)
    _, manifest = _checked_run(ref)
    available = character_resources(REPO_ROOT, RUNTIME_ROOT)
    if not available['available']:
        raise HTTPException(422, '缺少角色导出资源：' + ', '.join(name for name, exists in available['checks'].items() if not exists))
    if 'bvh' not in manifest['stages']:
        raise HTTPException(422, '当前修复结果没有可用的 BVH，请查看导出失败原因。')
    with MOTION_MUTATION_LOCK:
        job = CHARACTER_JOBS.get((ref.source, ref.task_id))
        if job is not None and not job.done():
            return {'status': 'running'}
        export_id = str(uuid4())
        folder = task / 'motionlint/character_exports' / export_id
        folder.mkdir(parents=True)
        _write_json(folder / 'status.json', {'status': 'queued', 'export_id': export_id, 'source_run_id': manifest['run_id']})
        _write_json(task / 'motionlint/character_request.json', {'export_id': export_id, 'source_run_id': manifest['run_id']})
        try:
            CHARACTER_JOBS[(ref.source, ref.task_id)] = CHARACTER_EXECUTOR.submit(export_character, task, REPO_ROOT, RUNTIME_ROOT, export_id, manifest['run_id'])
        except Exception as exc:
            _write_json(folder / 'status.json', {'status': 'failed', 'export_id': export_id, 'source_run_id': manifest['run_id'], 'error': str(exc)})
            raise HTTPException(503, '角色任务提交失败，请重试。') from exc
    return {'status': 'queued', 'export_id': export_id}


@app.get('/v1/motionlint/tasks/{source}/{task_id}/character-export')
def character_export_status(source: Literal['intergen', 'lodge', 'import'], task_id: str):
    ref = TaskRef(source=source, task_id=task_id)
    task = _task_folder(ref)
    path = task / 'motionlint/character_request.json'
    if not path.is_file():
        return {'status': 'unavailable'}
    request = json.loads(path.read_text(encoding='utf-8'))
    try:
        if str(UUID(request['export_id'])) != request['export_id']:
            raise ValueError('非标准导出编号')
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(409, '角色任务记录无效，请重新导出。') from exc
    state = json.loads((task / 'motionlint/character_exports' / request['export_id'] / 'status.json').read_text(encoding='utf-8'))
    _, current = _checked_run(ref)
    if state['source_run_id'] != current['run_id']:
        return {'status': 'stale', 'error': '角色对应旧的修复记录，请重新导出。'}
    if state['status'] == 'ready':
        try:
            checked_character(task, state['export_id'])
        except (ValueError, OSError, KeyError) as exc:
            return {'status': 'stale', 'error': str(exc)}
        state['video_url'] = f'/v1/motionlint/tasks/{source}/{task_id}/stage-video/character'
        state['download_url'] = f'/v1/motionlint/tasks/{source}/{task_id}/character-exports/{state["export_id"]}/bundle'
    elif state['status'] in {'queued', 'running'}:
        job = CHARACTER_JOBS.get((source, task_id))
        if job is None:
            return {'status': 'failed', 'error': '导出被服务重启中断，请重新导出。'}
        if job.done():
            return {'status': 'failed', 'error': str(job.exception() or '导出未产生完整状态记录，请重试。')}
    return state


@app.get('/v1/motionlint/tasks/{source}/{task_id}/character-exports/{export_id}/bundle')
def character_export_bundle(source: Literal['intergen', 'lodge', 'import'], task_id: str, export_id: str):
    try:
        folder, state = checked_character(_task_folder(TaskRef(source=source, task_id=task_id)), export_id)
        path = folder / 'bundle.zip'
        if sha256(path) != state['bundle_sha256']:
            raise ValueError('角色下载包已变化')
    except FileNotFoundError as exc:
        raise HTTPException(404, '角色导出尚未完成') from exc
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return FileResponse(path, media_type='application/zip', filename=f'motionlint-kenney-{export_id}.zip')


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
    from motionlint.core.context import freeze_pair
    baseline_motion, candidate_motion = freeze_pair(baseline_motion, candidate_motion, load_config())
    baseline, candidate = inspect(baseline_motion), inspect(candidate_motion)
    comparison = compare(baseline, candidate, baseline_motion=baseline_motion, candidate_motion=candidate_motion)
    folder = DATA_ROOT / "comparisons" / str(uuid4())
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
