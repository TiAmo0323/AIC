# LODGE CPU 兼容服务入口。
# 提供上传、特征提取、CPU 推理和普通预览，主要用于无 CUDA 环境的兼容测试；
# 当前不具备 GPU 主入口完整的 BVH、Rokoko 重定向与音轨处理契约。
import shutil
import subprocess
import sys
import threading
import uuid
import os
import numpy as np
import uvicorn
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi import Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware


APP_ROOT = Path(__file__).resolve().parent
DEFAULT_TASK_ROOT = APP_ROOT / "task_runs"
DEFAULT_TASK_ROOT.mkdir(parents=True, exist_ok=True)
SUBPROCESS_ENCODING = os.getenv("LODGE_SUBPROCESS_ENCODING", "utf-8")
SUBPROCESS_ERRORS = os.getenv("LODGE_SUBPROCESS_ERRORS", "replace")

CPU_INFER_SCRIPT = os.getenv("LODGE_CPU_INFER_SCRIPT", "infer_lodge_cpu.py").strip() or "infer_lodge_cpu.py"
CPU_RENDER_SCRIPT = os.getenv("LODGE_CPU_RENDER_SCRIPT", "render_cpu.py").strip() or "render_cpu.py"


class RenderSongRequest(BaseModel):
    lodge_root: str = Field(..., description="LODGE project root path, e.g. D:/LODGE-main")
    sample_dir: str = Field(..., description="Inference sample dir containing concat/npy, e.g. .../samples_dod_xxx")
    song_id: str = Field(..., description="Song id like 132")
    python_executable: Optional[str] = Field(default=sys.executable, description="Python executable in lodge conda env")
    mode: str = Field(default="smplx", pattern="^(smpl|smplh|smplx)$")
    device: str = Field(default="cpu", description="CPU mode placeholder, ignored in CPU API")
    fps: int = Field(default=30, ge=1, le=120)


class InferAndRenderRequest(BaseModel):
    lodge_root: str = Field(..., description="LODGE project root path, e.g. D:/LODGE-main")
    song_id: str = Field(..., description="Song id like 132")
    python_executable: Optional[str] = Field(default=sys.executable, description="Python executable in lodge conda env")
    infer_args: List[str] = Field(
        default_factory=list,
        description="Extra args passed to infer_lodge.py, e.g. ['--soft', '1.0']",
    )
    sample_dir_hint: Optional[str] = Field(
        default=None,
        description="Optional explicit sample dir. If omitted, API auto-detects latest samples_dod_* dir",
    )
    mode: str = Field(default="smplx", pattern="^(smpl|smplh|smplx)$")
    device: str = Field(default="cpu", description="CPU mode placeholder, ignored in CPU API")
    fps: int = Field(default=30, ge=1, le=120)


class InferFromAudioRequest(BaseModel):
    lodge_root: str = Field(..., description="LODGE project root path, e.g. D:/LODGE-main")
    audio_path: str = Field(..., description="Local audio/video path (.wav/.mp3/.m4a/.mp4)")
    song_id: str = Field(..., description="Song id, recommend existing FineDance id like 132")
    python_executable: Optional[str] = Field(default=sys.executable, description="Python executable in lodge conda env")
    infer_args: List[str] = Field(
        default_factory=list,
        description="Extra args passed to infer_lodge.py, e.g. ['--soft', '1.0']",
    )
    mode: str = Field(default="smplx", pattern="^(smpl|smplh|smplx)$")
    device: str = Field(default="cpu", description="CPU mode placeholder, ignored in CPU API")
    fps: int = Field(default=30, ge=1, le=120)


class InferFromFeatureNpyRequest(BaseModel):
    lodge_root: str = Field(..., description="LODGE project root path, e.g. D:/LODGE-main")
    feature_npy_path: str = Field(..., description="Local audio-feature npy path")
    song_id: str = Field(..., description="Song id used as feature file stem")
    python_executable: Optional[str] = Field(default=sys.executable, description="Python executable in lodge conda env")
    infer_args: List[str] = Field(
        default_factory=list,
        description="Extra args passed to infer_lodge.py, e.g. ['--soft', '1.0']",
    )
    mode: str = Field(default="smplx", pattern="^(smpl|smplh|smplx)$")
    device: str = Field(default="cpu", description="CPU mode placeholder, ignored in CPU API")
    fps: int = Field(default=30, ge=1, le=120)


class TaskInfo(BaseModel):
    task_id: str
    status: str
    progress: int = Field(default=0, ge=0, le=100)
    created_at: str
    updated_at: str
    message: str = ""
    output_mp4_path: Optional[str] = None
    stdout_tail: str = ""
    stderr_tail: str = ""


app = FastAPI(title="LODGE Async API (CPU)", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_tasks: Dict[str, TaskInfo] = {}
_task_lock = threading.Lock()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


executor = ThreadPoolExecutor(max_workers=max(1, _env_int("LODGE_MAX_CONCURRENT_TASKS", 1)))


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _tail_text(text: str, max_chars: int = 6000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _last_nonempty_line(text: str) -> str:
    for line in reversed((text or "").splitlines()):
        clean = line.strip()
        if clean:
            return clean
    return ""


def _update_task(task_id: str, **kwargs) -> None:
    with _task_lock:
        task = _tasks.get(task_id)
        if task is None:
            return
        data = task.model_dump()
        data.update(kwargs)
        data["updated_at"] = _utc_now()
        _tasks[task_id] = TaskInfo(**data)


def _find_rendered_mp4(video_dir: Path, song_id: str) -> Path:
    if not video_dir.exists():
        raise FileNotFoundError(f"Render output dir not found: {video_dir}")

    candidates = sorted(video_dir.glob(f"{song_id}*.mp4"))
    if not candidates:
        # Fallback: return latest mp4 in case naming changes.
        candidates = sorted(video_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime)

    if not candidates:
        raise FileNotFoundError(f"No mp4 generated under: {video_dir}")

    return candidates[-1]


def _detect_latest_sample_dir(lodge_root: Path) -> Path:
    experiments_root = lodge_root / "experiments"
    if not experiments_root.exists():
        raise FileNotFoundError(f"experiments dir not found: {experiments_root}")

    candidates = [
        p for p in experiments_root.rglob("samples_dod_*") if p.is_dir() and (p / "concat" / "npy").exists()
    ]
    if not candidates:
        raise FileNotFoundError("No samples_dod_* dir with concat/npy found under experiments")

    candidates.sort(key=lambda p: p.stat().st_mtime)
    return candidates[-1]


def _run_command(command: List[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding=SUBPROCESS_ENCODING,
        errors=SUBPROCESS_ERRORS,
        check=False,
    )


def _run_command_with_heartbeat(
    command: List[str],
    cwd: Path,
    task_id: str,
    running_message: str,
    progress: int,
    timeout_sec: Optional[int] = None,
    heartbeat_sec: int = 15,
    env_overrides: Optional[Dict[str, str]] = None,
) -> subprocess.CompletedProcess:
    _update_task(task_id, message=running_message, progress=progress)
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "-1"
    if env_overrides:
        env.update({k: str(v) for k, v in env_overrides.items()})

    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding=SUBPROCESS_ENCODING,
        errors=SUBPROCESS_ERRORS,
        env=env,
    )

    start_ts = datetime.utcnow().timestamp()
    while True:
        elapsed = int(datetime.utcnow().timestamp() - start_ts)
        if timeout_sec is not None and elapsed >= timeout_sec:
            process.kill()
            stdout, stderr = process.communicate()
            stderr = (stderr or "") + f"\nProcess timeout after {timeout_sec} seconds"
            return subprocess.CompletedProcess(command, 124, stdout or "", stderr)

        try:
            stdout, stderr = process.communicate(timeout=heartbeat_sec)
            return subprocess.CompletedProcess(command, process.returncode or 0, stdout or "", stderr or "")
        except subprocess.TimeoutExpired:
            _update_task(
                task_id,
                message=f"{running_message} ({elapsed}s elapsed)",
                progress=progress,
            )


def _run_command_inherit_cwd(command: List[str], cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = "-1"
    return subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding=SUBPROCESS_ENCODING,
        errors=SUBPROCESS_ERRORS,
        check=False,
        env=env,
    )


def _cap_motion_frames_inplace(npy_path: Path, max_frames: int) -> Optional[str]:
    if max_frames <= 0:
        return None

    try:
        data = np.load(str(npy_path), allow_pickle=False)
    except Exception:
        # Best effort: if shape cannot be parsed, skip truncation instead of failing the whole task.
        return None

    if getattr(data, "ndim", 0) < 1:
        return None

    frame_count = int(data.shape[0])
    if frame_count <= max_frames:
        return None

    np.save(str(npy_path), data[:max_frames])
    return f"Frame count clipped from {frame_count} to {max_frames}"


def _build_render_attempts(mode: str, fps: int) -> List[Tuple[str, int]]:
    attempts: List[Tuple[str, int]] = [(mode, fps)]
    if not _env_flag("LODGE_RENDER_RETRY_ENABLED", True):
        return attempts

    fallback_mode = os.getenv("LODGE_RENDER_FALLBACK_MODE", "smpl").strip() or "smpl"
    fallback_fps = _env_int("LODGE_RENDER_FALLBACK_FPS", min(fps, 24))
    fallback = (fallback_mode, fallback_fps)
    if fallback not in attempts:
        attempts.append(fallback)
    return attempts


def _render_with_retry(
    task_id: str,
    lodge_root: Path,
    input_dir: Path,
    song_id: str,
    python_exe: str,
    mode: str,
    device: str,
    fps: int,
) -> None:
    render_timeout_sec = _env_int("LODGE_RENDER_TIMEOUT_SEC", 3600)
    attempts = _build_render_attempts(mode=mode, fps=fps)
    stdout_blocks: List[str] = []
    stderr_blocks: List[str] = []

    for idx, (attempt_mode, attempt_fps) in enumerate(attempts, start=1):
        render_command = [
            python_exe,
            CPU_RENDER_SCRIPT,
            "--modir",
            str(input_dir),
            "--mode",
            attempt_mode,
            "--device",
            "cpu",
            "--fps",
            str(attempt_fps),
        ]

        progress = 80 if idx == 1 else 88
        running_message = f"Rendering mp4 (attempt {idx}/{len(attempts)}, mode={attempt_mode}, fps={attempt_fps})"
        proc = _run_command_with_heartbeat(
            command=render_command,
            cwd=lodge_root,
            task_id=task_id,
            running_message=running_message,
            progress=progress,
            timeout_sec=render_timeout_sec,
            heartbeat_sec=10,
        )

        stdout_blocks.append(f"[attempt {idx}]\n{proc.stdout or ''}")
        stderr_blocks.append(f"[attempt {idx}]\n{proc.stderr or ''}")

        if proc.returncode == 0:
            video_dir = input_dir / "video"
            output_mp4 = _find_rendered_mp4(video_dir, song_id)
            _update_task(
                task_id,
                status="succeeded",
                progress=100,
                message="Task completed",
                output_mp4_path=str(output_mp4.resolve()),
                stdout_tail=_tail_text("\n\n".join(stdout_blocks)),
                stderr_tail=_tail_text("\n\n".join(stderr_blocks)),
            )
            return

        if idx < len(attempts):
            _update_task(task_id, message="Render attempt failed, retrying with fallback settings", progress=86)

    _update_task(
        task_id,
        status="failed",
        message="render.py failed after fallback retry",
        stdout_tail=_tail_text("\n\n".join(stdout_blocks)),
        stderr_tail=_tail_text("\n\n".join(stderr_blocks)),
    )


def _resolve_music_npy_dir(lodge_root: Path) -> Path:
    candidates = [
        lodge_root / "data" / "finedance" / "music_npy",
        lodge_root / "data" / "finedance" / "music_npynew",
        lodge_root / "data" / "finedance" / "music_npynew" / "music_npy_new",
    ]
    for c in candidates:
        if c.exists():
            return c
    candidates[0].mkdir(parents=True, exist_ok=True)
    return candidates[0]


def _detect_latest_sample_dir_after(lodge_root: Path, min_mtime: float) -> Path:
    experiments_root = lodge_root / "experiments"
    if not experiments_root.exists():
        raise FileNotFoundError(f"experiments dir not found: {experiments_root}")

    candidates = [
        p
        for p in experiments_root.rglob("samples_dod_*")
        if p.is_dir() and (p / "concat" / "npy").exists() and p.stat().st_mtime >= min_mtime
    ]
    if not candidates:
        raise FileNotFoundError("No new samples_dod_* dir generated after infer started")

    candidates.sort(key=lambda p: p.stat().st_mtime)
    return candidates[-1]


def _normalize_song_id(song_id: str) -> str:
    clean = (song_id or "").strip()
    if not clean:
        raise ValueError("song_id is empty")
    return clean


def _ensure_wav_source(task_root: Path, source_audio: Path, lodge_root: Path) -> Path:
    input_dir = task_root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    suffix = source_audio.suffix.lower()
    if suffix == ".wav":
        dst = input_dir / "input.wav"
        shutil.copy2(source_audio, dst)
        return dst

    if suffix in {".mp4", ".m4a", ".mp3", ".aac", ".flac", ".ogg"}:
        dst = input_dir / "input.wav"
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_audio),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "15360",
            str(dst),
        ]
        proc = _run_command_inherit_cwd(ffmpeg_cmd, lodge_root)
        if proc.returncode != 0 or not dst.exists():
            raise RuntimeError(f"ffmpeg convert failed: {proc.stderr or proc.stdout}")
        return dst

    raise ValueError(f"Unsupported audio format: {source_audio.suffix}")


def _extract_music_feature_npy(lodge_root: Path, python_exe: str, wav_path: Path, out_npy: Path) -> subprocess.CompletedProcess:
    code = (
        "import numpy as np; "
        "from dld.data.utils.audio import extract; "
        f"fea,_=extract(r'{str(wav_path)}'); "
        f"np.save(r'{str(out_npy)}', fea)"
    )
    return _run_command_inherit_cwd([python_exe, "-c", code], lodge_root)


def _render_from_sample_dir(task_id: str, lodge_root: Path, sample_dir: Path, song_id: str, python_exe: str, mode: str, device: str, fps: int) -> None:
    source_npy = sample_dir / "concat" / "npy" / f"{song_id}.npy"
    if not source_npy.exists():
        raise FileNotFoundError(f"Source npy not found: {source_npy}")

    task_root = DEFAULT_TASK_ROOT / task_id
    input_dir = task_root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    target_npy = input_dir / f"{song_id}.npy"
    shutil.copy2(source_npy, target_npy)
    clip_note = _cap_motion_frames_inplace(target_npy, _env_int("LODGE_MAX_RENDER_FRAMES", 2000))
    if clip_note:
        _update_task(task_id, message=clip_note, progress=75)

    _render_with_retry(
        task_id=task_id,
        lodge_root=lodge_root,
        input_dir=input_dir,
        song_id=song_id,
        python_exe=python_exe,
        mode=mode,
        device=device,
        fps=fps,
    )


def _render_from_npy_file(task_id: str, lodge_root: Path, source_npy: Path, song_id: str, python_exe: str, mode: str, device: str, fps: int) -> None:
    if not source_npy.exists():
        raise FileNotFoundError(f"Source npy not found: {source_npy}")

    task_root = DEFAULT_TASK_ROOT / task_id
    input_dir = task_root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    target_npy = input_dir / f"{song_id}.npy"
    shutil.copy2(source_npy, target_npy)
    clip_note = _cap_motion_frames_inplace(target_npy, _env_int("LODGE_MAX_RENDER_FRAMES", 2000))
    if clip_note:
        _update_task(task_id, message=clip_note, progress=75)

    _render_with_retry(
        task_id=task_id,
        lodge_root=lodge_root,
        input_dir=input_dir,
        song_id=song_id,
        python_exe=python_exe,
        mode=mode,
        device=device,
        fps=fps,
    )


def _run_render_task(task_id: str, req: RenderSongRequest) -> None:
    try:
        _update_task(task_id, status="running", progress=10, message="Task is running")

        lodge_root = Path(req.lodge_root).resolve()
        sample_dir = Path(req.sample_dir).resolve()

        if not lodge_root.exists():
            raise FileNotFoundError(f"lodge_root not found: {lodge_root}")
        if not sample_dir.exists():
            raise FileNotFoundError(f"sample_dir not found: {sample_dir}")

        _render_from_sample_dir(
            task_id=task_id,
            lodge_root=lodge_root,
            sample_dir=sample_dir,
            song_id=req.song_id,
            python_exe=req.python_executable or sys.executable,
            mode=req.mode,
            device=req.device,
            fps=req.fps,
        )

    except Exception as exc:
        _update_task(task_id, status="failed", message=str(exc))


def _run_infer_and_render_task(task_id: str, req: InferAndRenderRequest) -> None:
    try:
        _update_task(task_id, status="running", progress=10, message="Running infer_lodge.py")

        lodge_root = Path(req.lodge_root).resolve()
        if not lodge_root.exists():
            raise FileNotFoundError(f"lodge_root not found: {lodge_root}")

        infer_timeout_sec = int(os.getenv("LODGE_INFER_TIMEOUT_SEC", "3600"))
        infer_command = [req.python_executable or sys.executable, CPU_INFER_SCRIPT] + req.infer_args
        infer_proc = _run_command_with_heartbeat(
            command=infer_command,
            cwd=lodge_root,
            task_id=task_id,
            running_message=f"Running {CPU_INFER_SCRIPT}",
            progress=45,
            timeout_sec=infer_timeout_sec,
            env_overrides={"LODGE_SONG_IDS": req.song_id},
        )
        infer_stdout = _tail_text(infer_proc.stdout or "")
        infer_stderr = _tail_text(infer_proc.stderr or "")

        if infer_proc.returncode != 0:
            reason = _last_nonempty_line(infer_stderr) or _last_nonempty_line(infer_stdout)
            msg = f"{CPU_INFER_SCRIPT} failed with return code {infer_proc.returncode}"
            if reason:
                msg = f"{msg}: {reason}"
            _update_task(
                task_id,
                status="failed",
                message=msg,
                stdout_tail=infer_stdout,
                stderr_tail=infer_stderr,
            )
            return

        _update_task(task_id, progress=65, message="Inference done, rendering mp4")

        sample_dir = Path(req.sample_dir_hint).resolve() if req.sample_dir_hint else _detect_latest_sample_dir(lodge_root)
        _render_from_sample_dir(
            task_id=task_id,
            lodge_root=lodge_root,
            sample_dir=sample_dir,
            song_id=req.song_id,
            python_exe=req.python_executable or sys.executable,
            mode=req.mode,
            device=req.device,
            fps=req.fps,
        )

    except Exception as exc:
        _update_task(task_id, status="failed", message=str(exc))


def _run_infer_from_audio_task(task_id: str, req: InferFromAudioRequest) -> None:
    try:
        _update_task(task_id, status="running", progress=10, message="Preparing audio features")

        lodge_root = Path(req.lodge_root).resolve()
        audio_path = Path(req.audio_path).resolve()
        song_id = _normalize_song_id(req.song_id)

        if not lodge_root.exists():
            raise FileNotFoundError(f"lodge_root not found: {lodge_root}")
        if not audio_path.exists():
            raise FileNotFoundError(f"audio_path not found: {audio_path}")

        task_root = DEFAULT_TASK_ROOT / task_id
        wav_path = _ensure_wav_source(task_root, audio_path, lodge_root)

        music_npy_dir = _resolve_music_npy_dir(lodge_root)
        out_npy = music_npy_dir / f"{song_id}.npy"

        _update_task(task_id, progress=25, message="Extracting audio features to npy")
        fea_proc = _extract_music_feature_npy(
            lodge_root=lodge_root,
            python_exe=req.python_executable or sys.executable,
            wav_path=wav_path,
            out_npy=out_npy,
        )
        if fea_proc.returncode != 0 or not out_npy.exists():
            _update_task(
                task_id,
                status="failed",
                message="Feature extraction failed",
                stdout_tail=_tail_text(fea_proc.stdout or ""),
                stderr_tail=_tail_text(fea_proc.stderr or ""),
            )
            return

        _update_task(task_id, progress=45, message=f"Running {CPU_INFER_SCRIPT}")
        start_ts = datetime.utcnow().timestamp()
        infer_timeout_sec = int(os.getenv("LODGE_INFER_TIMEOUT_SEC", "3600"))
        infer_command = [req.python_executable or sys.executable, CPU_INFER_SCRIPT] + req.infer_args
        infer_proc = _run_command_with_heartbeat(
            command=infer_command,
            cwd=lodge_root,
            task_id=task_id,
            running_message=f"Running {CPU_INFER_SCRIPT}",
            progress=45,
            timeout_sec=infer_timeout_sec,
            env_overrides={
                "LODGE_FORCE_CACHED_FEATURES": "1",
                "LODGE_MUSIC_DIR": str(music_npy_dir),
                "LODGE_SONG_IDS": song_id,
            },
        )
        infer_stdout = _tail_text(infer_proc.stdout or "")
        infer_stderr = _tail_text(infer_proc.stderr or "")

        if infer_proc.returncode != 0:
            reason = _last_nonempty_line(infer_stderr) or _last_nonempty_line(infer_stdout)
            msg = f"{CPU_INFER_SCRIPT} failed with return code {infer_proc.returncode}"
            if reason:
                msg = f"{msg}: {reason}"
            _update_task(
                task_id,
                status="failed",
                message=msg,
                stdout_tail=infer_stdout,
                stderr_tail=infer_stderr,
            )
            return

        _update_task(task_id, progress=70, message="Inference done, rendering mp4")
        sample_dir = _detect_latest_sample_dir_after(lodge_root, start_ts)
        _render_from_sample_dir(
            task_id=task_id,
            lodge_root=lodge_root,
            sample_dir=sample_dir,
            song_id=song_id,
            python_exe=req.python_executable or sys.executable,
            mode=req.mode,
            device=req.device,
            fps=req.fps,
        )

    except Exception as exc:
        _update_task(task_id, status="failed", message=str(exc))


def _run_infer_from_feature_npy_task(task_id: str, req: InferFromFeatureNpyRequest) -> None:
    try:
        _update_task(task_id, status="running", progress=10, message="Preparing feature npy")

        lodge_root = Path(req.lodge_root).resolve()
        feature_npy_path = Path(req.feature_npy_path).resolve()
        song_id = _normalize_song_id(req.song_id)

        if not lodge_root.exists():
            raise FileNotFoundError(f"lodge_root not found: {lodge_root}")
        if not feature_npy_path.exists():
            raise FileNotFoundError(f"feature_npy_path not found: {feature_npy_path}")

        music_npy_dir = _resolve_music_npy_dir(lodge_root)
        out_npy = music_npy_dir / f"{song_id}.npy"
        shutil.copy2(feature_npy_path, out_npy)

        _update_task(task_id, progress=45, message=f"Running {CPU_INFER_SCRIPT}")
        start_ts = datetime.utcnow().timestamp()
        infer_timeout_sec = int(os.getenv("LODGE_INFER_TIMEOUT_SEC", "3600"))
        infer_command = [req.python_executable or sys.executable, CPU_INFER_SCRIPT] + req.infer_args
        infer_proc = _run_command_with_heartbeat(
            command=infer_command,
            cwd=lodge_root,
            task_id=task_id,
            running_message=f"Running {CPU_INFER_SCRIPT}",
            progress=45,
            timeout_sec=infer_timeout_sec,
            env_overrides={
                "LODGE_FORCE_CACHED_FEATURES": "1",
                "LODGE_MUSIC_DIR": str(music_npy_dir),
                "LODGE_SONG_IDS": song_id,
            },
        )
        infer_stdout = _tail_text(infer_proc.stdout or "")
        infer_stderr = _tail_text(infer_proc.stderr or "")

        if infer_proc.returncode != 0:
            reason = _last_nonempty_line(infer_stderr) or _last_nonempty_line(infer_stdout)
            msg = f"{CPU_INFER_SCRIPT} failed with return code {infer_proc.returncode}"
            if reason:
                msg = f"{msg}: {reason}"
            _update_task(
                task_id,
                status="failed",
                message=msg,
                stdout_tail=infer_stdout,
                stderr_tail=infer_stderr,
            )
            return

        _update_task(task_id, progress=70, message="Inference done, rendering mp4")
        sample_dir = _detect_latest_sample_dir_after(lodge_root, start_ts)
        _render_from_sample_dir(
            task_id=task_id,
            lodge_root=lodge_root,
            sample_dir=sample_dir,
            song_id=song_id,
            python_exe=req.python_executable or sys.executable,
            mode=req.mode,
            device=req.device,
            fps=req.fps,
        )

    except Exception as exc:
        _update_task(task_id, status="failed", message=str(exc))


def _run_render_from_uploaded_npy_task(
    task_id: str,
    lodge_root: str,
    uploaded_npy_path: str,
    song_id: str,
    python_executable: Optional[str],
    mode: str,
    device: str,
    fps: int,
) -> None:
    try:
        _update_task(task_id, status="running", progress=20, message="Rendering uploaded npy")

        root_path = Path(lodge_root).resolve()
        npy_path = Path(uploaded_npy_path).resolve()
        if not root_path.exists():
            raise FileNotFoundError(f"lodge_root not found: {root_path}")
        if not npy_path.exists():
            raise FileNotFoundError(f"uploaded npy not found: {npy_path}")

        _render_from_npy_file(
            task_id=task_id,
            lodge_root=root_path,
            source_npy=npy_path,
            song_id=song_id,
            python_exe=python_executable or sys.executable,
            mode=mode,
            device=device,
            fps=fps,
        )
    except Exception as exc:
        _update_task(task_id, status="failed", message=str(exc))


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/lodge/tasks/render-song", response_model=TaskInfo)
def create_render_song_task(req: RenderSongRequest) -> TaskInfo:
    task_id = str(uuid.uuid4())
    now = _utc_now()
    task = TaskInfo(
        task_id=task_id,
        status="queued",
        progress=0,
        created_at=now,
        updated_at=now,
        message="Task queued",
    )
    with _task_lock:
        _tasks[task_id] = task

    executor.submit(_run_render_task, task_id, req)
    return task


@app.post("/v1/lodge/tasks/infer-and-render", response_model=TaskInfo)
def create_infer_and_render_task(req: InferAndRenderRequest) -> TaskInfo:
    task_id = str(uuid.uuid4())
    now = _utc_now()
    task = TaskInfo(
        task_id=task_id,
        status="queued",
        progress=0,
        created_at=now,
        updated_at=now,
        message="Task queued",
    )
    with _task_lock:
        _tasks[task_id] = task

    executor.submit(_run_infer_and_render_task, task_id, req)
    return task


@app.post("/v1/lodge/tasks/infer-from-audio", response_model=TaskInfo)
def create_infer_from_audio_task(req: InferFromAudioRequest) -> TaskInfo:
    task_id = str(uuid.uuid4())
    now = _utc_now()
    task = TaskInfo(
        task_id=task_id,
        status="queued",
        progress=0,
        created_at=now,
        updated_at=now,
        message="Task queued",
    )
    with _task_lock:
        _tasks[task_id] = task

    executor.submit(_run_infer_from_audio_task, task_id, req)
    return task


@app.post("/v1/lodge/tasks/infer-from-audio-upload", response_model=TaskInfo)
async def create_infer_from_audio_upload_task(
    lodge_root: str = Form(...),
    song_id: str = Form(...),
    audio_file: UploadFile = File(...),
    python_executable: Optional[str] = Form(default=None),
    mode: str = Form(default="smplx"),
    device: str = Form(default="cpu"),
    fps: int = Form(default=30),
    infer_args: str = Form(default=""),
) -> TaskInfo:
    task_id = str(uuid.uuid4())
    now = _utc_now()
    task = TaskInfo(
        task_id=task_id,
        status="queued",
        progress=0,
        created_at=now,
        updated_at=now,
        message="Task queued",
    )
    with _task_lock:
        _tasks[task_id] = task

    task_root = DEFAULT_TASK_ROOT / task_id
    input_dir = task_root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(audio_file.filename or "upload.wav").suffix or ".wav"
    saved_path = input_dir / f"uploaded{suffix}"
    content = await audio_file.read()
    saved_path.write_bytes(content)

    args = [x.strip() for x in infer_args.split(",") if x.strip()] if infer_args else []
    req = InferFromAudioRequest(
        lodge_root=lodge_root,
        audio_path=str(saved_path),
        song_id=song_id,
        python_executable=python_executable or sys.executable,
        infer_args=args,
        mode=mode,
        device=device,
        fps=fps,
    )

    executor.submit(_run_infer_from_audio_task, task_id, req)
    return task


@app.post("/v1/lodge/tasks/render-from-npy-upload", response_model=TaskInfo)
async def create_render_from_npy_upload_task(
    lodge_root: str = Form(...),
    song_id: str = Form(...),
    npy_file: UploadFile = File(...),
    python_executable: Optional[str] = Form(default=None),
    mode: str = Form(default="smplx"),
    device: str = Form(default="cpu"),
    fps: int = Form(default=30),
) -> TaskInfo:
    task_id = str(uuid.uuid4())
    now = _utc_now()
    task = TaskInfo(
        task_id=task_id,
        status="queued",
        progress=0,
        created_at=now,
        updated_at=now,
        message="Task queued",
    )
    with _task_lock:
        _tasks[task_id] = task

    task_root = DEFAULT_TASK_ROOT / task_id
    input_dir = task_root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    saved_path = input_dir / "uploaded.npy"
    saved_path.write_bytes(await npy_file.read())

    executor.submit(
        _run_render_from_uploaded_npy_task,
        task_id,
        lodge_root,
        str(saved_path),
        song_id,
        python_executable,
        mode,
        device,
        fps,
    )
    return task


@app.post("/v1/lodge/tasks/infer-from-feature-npy-upload", response_model=TaskInfo)
async def create_infer_from_feature_npy_upload_task(
    lodge_root: str = Form(...),
    song_id: str = Form(...),
    npy_file: UploadFile = File(...),
    python_executable: Optional[str] = Form(default=None),
    mode: str = Form(default="smplx"),
    device: str = Form(default="cpu"),
    fps: int = Form(default=30),
    infer_args: str = Form(default=""),
) -> TaskInfo:
    task_id = str(uuid.uuid4())
    now = _utc_now()
    task = TaskInfo(
        task_id=task_id,
        status="queued",
        progress=0,
        created_at=now,
        updated_at=now,
        message="Task queued",
    )
    with _task_lock:
        _tasks[task_id] = task

    task_root = DEFAULT_TASK_ROOT / task_id
    input_dir = task_root / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    saved_path = input_dir / "uploaded_feature.npy"
    saved_path.write_bytes(await npy_file.read())

    args = [x.strip() for x in infer_args.split(",") if x.strip()] if infer_args else []
    req = InferFromFeatureNpyRequest(
        lodge_root=lodge_root,
        feature_npy_path=str(saved_path),
        song_id=song_id,
        python_executable=python_executable or sys.executable,
        infer_args=args,
        mode=mode,
        device=device,
        fps=fps,
    )

    executor.submit(_run_infer_from_feature_npy_task, task_id, req)
    return task


@app.get("/v1/lodge/tasks/{task_id}", response_model=TaskInfo)
def get_task(task_id: str) -> TaskInfo:
    with _task_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.post("/v1/lodge/tasks/{task_id}/open-output-folder")
def open_task_output_folder(task_id: str) -> Dict[str, str]:
    with _task_lock:
        task = _tasks.get(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "succeeded" or not task.output_mp4_path:
        raise HTTPException(status_code=409, detail="Task not completed")

    mp4_path = Path(task.output_mp4_path)
    if not mp4_path.exists():
        raise HTTPException(status_code=410, detail="Output file no longer exists")

    parent_dir = mp4_path.parent
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer", f"/select,{str(mp4_path)}"])  # nosec B603
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(parent_dir)])  # nosec B603
        else:
            subprocess.Popen(["xdg-open", str(parent_dir)])  # nosec B603
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to open folder: {exc}")

    return {"status": "ok", "opened_path": str(parent_dir)}


@app.post("/v1/lodge/tasks/{task_id}/open-output-player")
def open_task_output_player(task_id: str) -> Dict[str, str]:
    with _task_lock:
        task = _tasks.get(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "succeeded" or not task.output_mp4_path:
        raise HTTPException(status_code=409, detail="Task not completed")

    mp4_path = Path(task.output_mp4_path)
    if not mp4_path.exists():
        raise HTTPException(status_code=410, detail="Output file no longer exists")

    try:
        if os.name == "nt":
            os.startfile(str(mp4_path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(mp4_path)])  # nosec B603
        else:
            subprocess.Popen(["xdg-open", str(mp4_path)])  # nosec B603
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to open player: {exc}")

    return {"status": "ok", "opened_file": str(mp4_path)}


@app.get("/v1/lodge/tasks/{task_id}/download")
def download_task_result(task_id: str, request: Request, as_attachment: bool = False):
    with _task_lock:
        task = _tasks.get(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "succeeded" or not task.output_mp4_path:
        raise HTTPException(status_code=409, detail="Task not completed")

    mp4_path = Path(task.output_mp4_path)
    if not mp4_path.exists():
        raise HTTPException(status_code=410, detail="Output file no longer exists")

    file_size = mp4_path.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        try:
            units, range_spec = range_header.split("=", 1)
            if units.strip().lower() != "bytes":
                raise ValueError("Only bytes range is supported")
            start_str, end_str = range_spec.split("-", 1)
            if start_str.strip() == "":
                # suffix-byte-range-spec: bytes=-N
                suffix_len = int(end_str)
                start = max(file_size - suffix_len, 0)
                end = file_size - 1
            else:
                start = int(start_str)
                end = int(end_str) if end_str.strip() else file_size - 1
            if start < 0 or end < start or end >= file_size:
                raise ValueError("Invalid range")
        except Exception:
            raise HTTPException(status_code=416, detail="Invalid Range header")

        chunk_size = 1024 * 1024

        def iter_file_range(path: Path, start_pos: int, end_pos: int):
            with open(path, "rb") as f:
                f.seek(start_pos)
                remaining = end_pos - start_pos + 1
                while remaining > 0:
                    read_size = min(chunk_size, remaining)
                    data = f.read(read_size)
                    if not data:
                        break
                    yield data
                    remaining -= len(data)

        disposition = "attachment" if as_attachment else "inline"
        headers = {
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
            "Content-Disposition": f'{disposition}; filename="{mp4_path.name}"',
        }
        return StreamingResponse(
            iter_file_range(mp4_path, start, end),
            status_code=206,
            media_type="video/mp4",
            headers=headers,
        )

    if as_attachment:
        return FileResponse(
            path=str(mp4_path),
            media_type="video/mp4",
            filename=mp4_path.name,
            headers={"Accept-Ranges": "bytes"},
        )

    return FileResponse(
        path=str(mp4_path),
        media_type="video/mp4",
        headers={
            "Content-Disposition": f'inline; filename="{mp4_path.name}"',
            "Accept-Ranges": "bytes",
        },
    )

if __name__ == "__main__":
    access_log_enabled = os.getenv("LODGE_ACCESS_LOG", "0").strip().lower() in {"1", "true", "yes", "on"}
    uvicorn.run(app, host="0.0.0.0", port=8002, access_log=access_log_enabled)
