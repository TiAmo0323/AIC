# InterGen CPU 兼容服务入口。
# 保留文本生成、任务轮询和普通预览能力，适合无 CUDA 环境的功能验证；
# 它不是当前前端推荐的生产入口，能力和速度均低于 GPU/重定向版本。
import os
import sys
import socket
import threading
import traceback
import uuid
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import copy
try:
    import lightning as L
except Exception:
    import pytorch_lightning as L
import numpy as np
import scipy.ndimage as filters
import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from openai import OpenAI
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware


# Keep runtime stable on Windows scientific stacks.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

APP_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = APP_ROOT.parent
DEFAULT_TASK_ROOT = APP_ROOT / "task_runs"
DEFAULT_TASK_ROOT.mkdir(parents=True, exist_ok=True)


def _looks_like_intergen_root(path: Path) -> bool:
    return (
        (path / "configs" / "model.yaml").exists()
        and (path / "configs" / "infer.yaml").exists()
        and (path / "models").exists()
        and (path / "utils" / "human_mesh_renderer_fast.py").exists()
        and (path / "utils" / "human_mesh_renderer.py").exists()
        and (path / "utils" / "human_model_paths.py").exists()
    )


def _detect_source_root() -> str:
    candidates = [
        PROJECT_ROOT,
        PROJECT_ROOT.parent / "InterGen" / "InterGen_master",
        PROJECT_ROOT / "InterGen" / "InterGen_master",
        Path(os.getenv("INTERGEN_SOURCE_ROOT_DEFAULT", "")).expanduser() if os.getenv("INTERGEN_SOURCE_ROOT_DEFAULT") else None,
        Path("D:/InterGen/InterGen_master"),
        Path("D:/HumanAction_Platform/InterGen/InterGen_master"),
        Path("D:/InterGen"),
    ]
    for c in candidates:
        if c is None:
            continue
        c = c.resolve()
        if _looks_like_intergen_root(c):
            return str(c)
    return ""

# Optional external source root that contains InterGen package folders like
# configs/, models/, and utils/. Useful when API code is separated from model code.
INTERGEN_SOURCE_ROOT = os.getenv("INTERGEN_SOURCE_ROOT", "").strip()
if not INTERGEN_SOURCE_ROOT:
    INTERGEN_SOURCE_ROOT = _detect_source_root()
if INTERGEN_SOURCE_ROOT:
    _source_root_path = Path(INTERGEN_SOURCE_ROOT).expanduser().resolve()
    if _source_root_path.exists() and str(_source_root_path) not in sys.path:
        sys.path.insert(0, str(_source_root_path))

# Optional external config directory. If provided, its parent is treated as the
# source root so `from configs import ...` remains importable.
INTERGEN_CONFIG_DIR = os.getenv("INTERGEN_CONFIG_DIR", "").strip()
if INTERGEN_CONFIG_DIR:
    _config_dir_path = Path(INTERGEN_CONFIG_DIR).expanduser().resolve()
    _config_parent = _config_dir_path.parent
    if _config_parent.exists() and str(_config_parent) not in sys.path:
        sys.path.insert(0, str(_config_parent))

# Ensure project modules are importable when running from this folder.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from collections import OrderedDict
from os.path import join as pjoin

from configs import get_config
from models import InterGen
from utils import paramUtil
from utils.human_mesh_renderer_fast import render_two_person_smpl_video_pyrender as render_two_person_smpl_video_fast
from utils.human_model_paths import get_human_models_root, validate_human_models
from utils.plot_script import plot_3d_motion
import utils.human_mesh_renderer_fast as _human_mesh_renderer_fast
import utils.human_mesh_renderer as _human_mesh_renderer
import utils.human_model_paths as _human_model_paths
try:
    from utils.utils import MotionNormalizer
except Exception:
    from utils.preprocess import MotionNormalizer

try:
    import configs as _configs_pkg

    CONFIGS_ROOT = Path(_configs_pkg.__file__).resolve().parent
    MODEL_SOURCE_ROOT = CONFIGS_ROOT.parent
except Exception:
    CONFIGS_ROOT = PROJECT_ROOT / "configs"
    MODEL_SOURCE_ROOT = PROJECT_ROOT


class GenerateMotionRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text prompt for two-person motion generation")
    num_samples: int = Field(default=5, ge=1, le=8, description="Number of candidates to sample before selecting best")
    motion_frames: Optional[int] = Field(default=None, ge=60, le=240, description="Optional motion length in frames")
    cfg_weight: Optional[float] = Field(default=None, ge=1.0, le=9.0, description="Optional classifier-free guidance weight")


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text to be translated")
    target_lang: str = Field(default="English", description="Translation target language")


class TaskInfo(BaseModel):
    task_id: str
    status: str
    created_at: str
    updated_at: str
    message: str = ""
    progress: int = 0
    final_prompt: str = ""
    output_mp4_path: Optional[str] = None
    stderr_tail: str = ""


class LitGenModel(L.LightningModule):
    def __init__(self, model, cfg):
        super().__init__()
        self.cfg = cfg
        self.automatic_optimization = False
        self.save_root = pjoin(self.cfg.GENERAL.CHECKPOINT, self.cfg.GENERAL.EXP_NAME)
        self.model_dir = pjoin(self.save_root, "model")
        self.meta_dir = pjoin(self.save_root, "meta")
        self.log_dir = pjoin(self.save_root, "log")
        os.makedirs(self.model_dir, exist_ok=True)
        os.makedirs(self.meta_dir, exist_ok=True)
        os.makedirs(self.log_dir, exist_ok=True)
        self.model = model
        self.normalizer = MotionNormalizer()

    def _runtime_device(self) -> torch.device:
        return next(self.model.parameters()).device

    def plot_t2m(self, mp_data, result_path: str, caption: str):
        mp_joint = []
        for data in mp_data:
            joint = data[:, : 22 * 3].reshape(-1, 22, 3)
            mp_joint.append(joint)
        plot_3d_motion(result_path, paramUtil.t2m_kinematic_chain, mp_joint, title=caption, fps=30)

    def _resolve_window_size(self, prompt: str, motion_frames: Optional[int]) -> int:
        if motion_frames is not None:
            return _clamp_int(motion_frames, 60, 240)

        default_frames = _clamp_int(int(os.getenv("INTERGEN_MOTION_FRAMES", "168")), 60, 240)
        prompt_l = prompt.lower()
        if any(k in prompt_l for k in ["punch", "kick", "slap", "hit", "high five", "handshake"]):
            return min(default_frames, 132)
        if any(k in prompt_l for k in ["fencing", "fencer", "foil", "sabre", "sword", "duel"]):
            return min(default_frames, 144)
        if any(k in prompt_l for k in ["dance", "dancing", "waltz", "tango"]):
            return max(default_frames, 180)
        return default_frames

    def _resolve_request_cfg_weight(self, prompt: str, cfg_weight: Optional[float]) -> float:
        if cfg_weight is not None:
            return _clamp_float(cfg_weight, 1.0, 9.0)

        base = _clamp_float(float(os.getenv("INTERGEN_DEFAULT_REQUEST_CFG_WEIGHT", "5.0")), 1.0, 9.0)
        prompt_l = prompt.lower()
        if any(k in prompt_l for k in ["fencing", "fencer", "foil", "sabre", "sword", "duel"]):
            # Slightly lower CFG helps avoid frozen poses for highly dynamic duels.
            return min(base, 4.2)
        if any(k in prompt_l for k in ["fight", "boxing", "box", "punch", "kick"]):
            return min(base, 4.6)
        return base

    def generate_one_sample(
        self,
        prompt: str,
        output_path: str,
        motion_frames: Optional[int] = None,
        cfg_weight: Optional[float] = None,
    ) -> Dict[str, str]:
        self.model.eval()
        run_device = self._runtime_device()
        batch = OrderedDict({})
        batch["motion_lens"] = torch.zeros(1, 1, device=run_device).long()
        batch["prompt"] = prompt

        window_size = self._resolve_window_size(prompt, motion_frames)
        request_cfg_weight = self._resolve_request_cfg_weight(prompt, cfg_weight)

        old_cfg_weight = None
        if hasattr(self.model, "decoder") and hasattr(self.model.decoder, "cfg_weight"):
            old_cfg_weight = float(self.model.decoder.cfg_weight)
            self.model.decoder.cfg_weight = request_cfg_weight

        motion_output = self.generate_loop(batch, window_size)

        if old_cfg_weight is not None:
            self.model.decoder.cfg_weight = old_cfg_weight

        render_mode = os.getenv("INTERGEN_RENDER_MODE", "smpl").strip().lower()
        body_model_type = os.getenv("INTERGEN_BODY_MODEL", "smplx").strip().lower()
        profile_name = os.getenv("INTERGEN_RENDER_PROFILE", "balanced")
        defaults = _render_profile_defaults(profile_name)

        fps = int(os.getenv("INTERGEN_FPS", str(defaults["fps"])))
        num_fit_iters = int(os.getenv("INTERGEN_SMPL_ITERS", str(defaults["iters"])))
        max_render_frames = int(os.getenv("INTERGEN_MAX_RENDER_FRAMES", str(defaults["max_frames"])))
        camera_elev = float(os.getenv("INTERGEN_CAMERA_ELEV", str(defaults["camera_elev"])))
        camera_azim_env = os.getenv("INTERGEN_CAMERA_AZIM", str(defaults["camera_azim"]))
        camera_azim = None if camera_azim_env in (None, "", "auto", "AUTO") else float(camera_azim_env)
        camera_azim_offset = float(os.getenv("INTERGEN_CAMERA_AZIM_OFFSET", str(defaults["camera_azim_offset"])))
        camera_orbit_speed = float(os.getenv("INTERGEN_CAMERA_ORBIT_SPEED", str(defaults["camera_orbit_speed"])))
        render_size = _parse_render_size(
            os.getenv("INTERGEN_RENDER_SIZE", f"{defaults['size'][0]}x{defaults['size'][1]}"),
            default=defaults["size"],
        )
        ffmpeg_preset = os.getenv("INTERGEN_FFMPEG_PRESET", defaults["ffmpeg_preset"])
        ffmpeg_crf = int(os.getenv("INTERGEN_FFMPEG_CRF", str(defaults["ffmpeg_crf"])))
        dynamic_lighting = os.getenv("INTERGEN_DYNAMIC_LIGHTING", "1" if defaults["dynamic_lighting"] else "0").strip() == "1"
        align_with_stickman_axes = os.getenv(
            "INTERGEN_ALIGN_WITH_STICKMAN_AXES",
            "1" if defaults["align_with_stickman_axes"] else "0",
        ).strip() == "1"
        vertex_smooth_sigma = float(os.getenv("INTERGEN_VERTEX_SMOOTH_SIGMA", str(defaults["vertex_smooth_sigma"])))
        vertex_median_window = int(os.getenv("INTERGEN_VERTEX_MEDIAN_WINDOW", str(defaults["vertex_median_window"])))
        vertex_spike_z_thresh = float(os.getenv("INTERGEN_VERTEX_SPIKE_Z_THRESH", str(defaults["vertex_spike_z_thresh"])))
        target_duration_sec = float(os.getenv("INTERGEN_TARGET_DURATION_SEC", str(defaults["target_duration_sec"])))
        min_duration_sec = max(6.0, float(os.getenv("INTERGEN_MIN_DURATION_SEC", str(defaults["min_duration_sec"]))))
        fit_early_stop_patience = int(os.getenv("INTERGEN_FIT_EARLY_STOP_PATIENCE", str(defaults["fit_early_stop_patience"])))
        fit_early_stop_check_every = int(os.getenv("INTERGEN_FIT_EARLY_STOP_CHECK_EVERY", str(defaults["fit_early_stop_check_every"])))
        fit_early_stop_rel_tol = float(os.getenv("INTERGEN_FIT_EARLY_STOP_REL_TOL", str(defaults["fit_early_stop_rel_tol"])))

        fps = _clamp_int(fps, 15, 30)
        camera_elev = _clamp_float(camera_elev, 0.0, 89.0)
        camera_azim_offset = _clamp_float(camera_azim_offset, -180.0, 180.0)
        camera_orbit_speed = _clamp_float(camera_orbit_speed, 0.0, 0.2)
        target_duration_sec = _clamp_float(target_duration_sec, 6.0, 20.0)
        min_duration_sec = _clamp_float(min_duration_sec, 6.0, 20.0)
        vertex_median_window = _clamp_int(vertex_median_window, 1, 9)
        vertex_spike_z_thresh = _clamp_float(vertex_spike_z_thresh, 2.0, 10.0)
        if vertex_median_window % 2 == 0:
            vertex_median_window += 1

        force_stickman_axes = os.getenv("INTERGEN_FORCE_STICKMAN_AXES")
        if force_stickman_axes is not None:
            align_with_stickman_axes = force_stickman_axes.strip() == "1"

        print(f"[Render] mode={render_mode}")
        print("[Render] backend=fast")
        print(f"[Render] body_model={body_model_type}")
        print(f"[Render] profile={profile_name}")
        print(f"[Render] device={run_device}")
        print(f"[Render] request_cfg_weight={request_cfg_weight:.2f}")
        print(
            "[Render] effective "
            f"fps={fps}, dur_target={target_duration_sec:.2f}, dur_min={min_duration_sec:.2f}, "
            f"cam_elev={camera_elev:.1f}, cam_azim={('auto-front' if camera_azim is None else f'{camera_azim:.1f}')}, cam_azim_offset={camera_azim_offset:.1f}, stickman_axes={int(align_with_stickman_axes)}, "
            f"median_w={vertex_median_window}, sigma={vertex_smooth_sigma:.2f}, spike_z={vertex_spike_z_thresh:.2f}"
        )

        if render_mode == "smpl":
            human_models_root = _resolve_human_models_root()
            try:
                render_two_person_smpl_video_fast(
                    joints_a_22=motion_output[0],
                    joints_b_22=motion_output[1],
                    result_path=output_path,
                    human_models_root=human_models_root,
                    gender=os.getenv("INTERGEN_SMPL_GENDER", "neutral"),
                    fps=fps,
                    num_fit_iters=num_fit_iters,
                    device=run_device,
                    body_model_type=body_model_type,
                    max_render_frames=max_render_frames,
                    camera_elev=camera_elev,
                    camera_azim=camera_azim,
                    camera_azim_offset=camera_azim_offset,
                    camera_orbit_speed=camera_orbit_speed,
                    render_size=render_size,
                    ffmpeg_preset=ffmpeg_preset,
                    ffmpeg_crf=ffmpeg_crf,
                    dynamic_lighting=dynamic_lighting,
                    align_with_stickman_axes=align_with_stickman_axes,
                    vertex_smooth_sigma=vertex_smooth_sigma,
                    vertex_median_window=vertex_median_window,
                    vertex_spike_z_thresh=vertex_spike_z_thresh,
                    target_duration_sec=target_duration_sec,
                    min_duration_sec=min_duration_sec,
                    fit_early_stop_patience=fit_early_stop_patience,
                    fit_early_stop_check_every=fit_early_stop_check_every,
                    fit_early_stop_rel_tol=fit_early_stop_rel_tol,
                )
                return {
                    "render_mode": "smpl",
                    "message": "Task completed",
                    "fallback_used": "0",
                }
            except Exception as exc:
                strict_mode = os.getenv("INTERGEN_SMPL_STRICT", "0").strip() == "1"
                if strict_mode:
                    raise
                self.plot_t2m([motion_output[0], motion_output[1]], output_path, batch["prompt"])
                return {
                    "render_mode": "skeleton",
                    "message": "模型生成失败，回退至火柴人模型，请重新生成视频",
                    "fallback_used": "1",
                    "fallback_reason": str(exc),
                }
        else:
            self.plot_t2m([motion_output[0], motion_output[1]], output_path, batch["prompt"])
            return {
                "render_mode": "skeleton",
                "message": "Task completed (skeleton render mode)",
                "fallback_used": "0",
            }

    def generate_loop(self, batch, window_size):
        prompt = batch["prompt"]
        batch = copy.deepcopy(batch)
        batch["motion_lens"][:] = window_size
        sequences = [[], []]
        batch["text"] = [prompt]
        batch = self.model.forward_test(batch)
        motion_output_both = batch["output"][0].reshape(batch["output"][0].shape[0], 2, -1)
        motion_output_both = self.normalizer.backward(motion_output_both.cpu().detach().numpy())
        for j in range(2):
            motion_output = motion_output_both[:, j]
            joints3d = motion_output[:, : 22 * 3].reshape(-1, 22, 3)
            joints3d = filters.gaussian_filter1d(joints3d, 1, axis=0, mode="nearest")
            sequences[j].append(joints3d)
        sequences[0] = np.concatenate(sequences[0], axis=0)
        sequences[1] = np.concatenate(sequences[1], axis=0)
        return sequences


def _resolve_runtime_device(preferred: str = "cpu") -> torch.device:
    # CPU edition: always run inference/render fitting on CPU.
    return torch.device("cpu")


def _parse_render_size(env_value: str, default=(960, 960)):
    value = (env_value or "").lower().strip()
    if "x" not in value:
        return default
    try:
        w_str, h_str = value.split("x", 1)
        width = max(320, int(w_str))
        height = max(320, int(h_str))
        return (width, height)
    except Exception:
        return default


def _render_profile_defaults(profile_name: str) -> dict:
    profile = (profile_name or "balanced").strip().lower()
    presets = {
        "fast": {
            "fps": 22,
            "iters": 60,
            "max_frames": 140,
            "size": (960, 960),
            "ffmpeg_preset": "ultrafast",
            "ffmpeg_crf": 22,
            "camera_elev": 18.0,
            "camera_azim": "auto",
            "camera_orbit_speed": 0.0,
            "camera_azim_offset": 0.0,
            "dynamic_lighting": False,
            "align_with_stickman_axes": True,
            "vertex_smooth_sigma": 0.6,
            "vertex_median_window": 3,
            "vertex_spike_z_thresh": 4.0,
            "target_duration_sec": 7.0,
            "min_duration_sec": 6.0,
            "fit_early_stop_patience": 5,
            "fit_early_stop_check_every": 5,
            "fit_early_stop_rel_tol": 2.0e-4,
        },
        "balanced": {
            "fps": 24,
            "iters": 120,
            "max_frames": 168,
            "size": (1280, 1280),
            "ffmpeg_preset": "veryfast",
            "ffmpeg_crf": 18,
            "camera_elev": 18.0,
            "camera_azim": "auto",
            "camera_orbit_speed": 0.0,
            "camera_azim_offset": 0.0,
            "dynamic_lighting": False,
            "align_with_stickman_axes": True,
            "vertex_smooth_sigma": 1.0,
            "vertex_median_window": 5,
            "vertex_spike_z_thresh": 3.0,
            "target_duration_sec": 7.0,
            "min_duration_sec": 6.0,
            "fit_early_stop_patience": 6,
            "fit_early_stop_check_every": 5,
            "fit_early_stop_rel_tol": 1.5e-4,
        },
        "quality": {
            "fps": 30,
            "iters": 200,
            "max_frames": 210,
            "size": (1440, 1440),
            "ffmpeg_preset": "medium",
            "ffmpeg_crf": 15,
            "camera_elev": 18.0,
            "camera_azim": "auto",
            "camera_orbit_speed": 0.0,
            "camera_azim_offset": 0.0,
            "dynamic_lighting": True,
            "align_with_stickman_axes": True,
            "vertex_smooth_sigma": 1.2,
            "vertex_median_window": 7,
            "vertex_spike_z_thresh": 3.0,
            "target_duration_sec": 7.0,
            "min_duration_sec": 6.0,
            "fit_early_stop_patience": 8,
            "fit_early_stop_check_every": 5,
            "fit_early_stop_rel_tol": 1.0e-4,
        },
    }
    return presets.get(profile, presets["balanced"])


def _clamp_int(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(x)))


def _clamp_float(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def _build_model(model_cfg):
    if model_cfg.NAME != "InterGen":
        raise ValueError(f"Unsupported model config NAME: {model_cfg.NAME}")
    return InterGen(model_cfg)


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _tail_text(text: str, max_chars: int = 6000) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _pick_best_candidate(candidates: list) -> dict:
    # Priority: prefer non-fallback SMPL result; tie-break by larger mp4 size.
    def _rank(item: dict):
        fallback_used = 1 if str(item.get("fallback_used", "0")) == "1" else 0
        file_size = int(item.get("file_size", 0) or 0)
        return (fallback_used, -file_size)

    return sorted(candidates, key=_rank)[0]


def _resolve_human_models_root() -> str:
    # Priority: explicit env > model source root > API project root.
    env_root = os.getenv("INTERGEN_HUMAN_MODELS_ROOT", "").strip()
    if env_root:
        return str(Path(env_root).expanduser().resolve())

    source_default = MODEL_SOURCE_ROOT / "human_models"
    if source_default.exists():
        return str(source_default)

    return get_human_models_root(str(PROJECT_ROOT))


def _resolve_checkpoint_path(raw_checkpoint: str) -> Path:
    raw = (raw_checkpoint or "").strip()
    if not raw:
        raise FileNotFoundError("Empty checkpoint path")

    p = Path(raw).expanduser()
    candidates = []

    if p.is_absolute():
        candidates.append(p.resolve())
    else:
        candidates.append((MODEL_SOURCE_ROOT / p).resolve())
        candidates.append((PROJECT_ROOT / p).resolve())

    # Portable fallbacks for common InterGen workspace layouts.
    candidates.extend([
        (MODEL_SOURCE_ROOT.parent / "checkpoints" / "intergen.ckpt").resolve(),
        (PROJECT_ROOT.parent / "InterGen" / "checkpoints" / "intergen.ckpt").resolve(),
    ])

    seen = set()
    for c in candidates:
        key = str(c).lower()
        if key in seen:
            continue
        seen.add(key)
        if c.exists():
            return c

    return candidates[0]


class InterGenService:
    def __init__(self):
        self._model = None
        self._infer_lock = threading.Lock()

    def load(self):
        human_models_root = _resolve_human_models_root()
        status = validate_human_models(human_models_root)
        print("Human model assets:")
        print(f"  root: {status['human_models_root']}")
        print(f"  exists: {status['exists']}")
        print(f"  smpl_ready: {status['smpl_ready']}")
        print(f"  smplx_ready: {status['smplx_ready']}")
        print(f"  render_mode(default): {os.getenv('INTERGEN_RENDER_MODE', 'smpl')}")
        print("Code source resolution:")
        print(f"  INTERGEN_SOURCE_ROOT: {INTERGEN_SOURCE_ROOT or '(auto-not-found)'}")
        print(f"  CONFIGS_ROOT: {CONFIGS_ROOT}")
        print(f"  human_mesh_renderer_fast: {Path(_human_mesh_renderer_fast.__file__).resolve()}")
        print(f"  human_mesh_renderer: {Path(_human_mesh_renderer.__file__).resolve()}")
        print(f"  human_model_paths: {Path(_human_model_paths.__file__).resolve()}")
        if not status["smpl_ready"] and not status["smplx_ready"]:
            print("  note: SMPL assets unavailable, rendering may fall back to skeleton mode.")

        config_dir_env = os.getenv("INTERGEN_CONFIG_DIR", "").strip()
        config_dir = Path(config_dir_env).expanduser().resolve() if config_dir_env else CONFIGS_ROOT
        model_yaml = config_dir / "model.yaml"
        infer_yaml = config_dir / "infer.yaml"
        if not model_yaml.exists() or not infer_yaml.exists():
            raise FileNotFoundError(
                f"InterGen config files not found under: {config_dir}. "
                "Set INTERGEN_CONFIG_DIR to a directory that contains model.yaml and infer.yaml."
            )

        model_cfg = get_config(str(model_yaml))
        infer_cfg = get_config(str(infer_yaml))

        # yacs CfgNode loaded by get_config is frozen (immutable) by default.
        # Temporarily defrost to apply startup-locked inference overrides.
        model_cfg.defrost()

        # Lock startup inference config so same service name always uses the same core inference knobs.
        fixed_checkpoint_env = os.getenv("INTERGEN_FIXED_CHECKPOINT", "").strip()
        if fixed_checkpoint_env:
            ckpt_path = Path(fixed_checkpoint_env).expanduser().resolve()
            if not ckpt_path.exists():
                raise FileNotFoundError(f"INTERGEN_FIXED_CHECKPOINT not found: {ckpt_path}")
            checkpoint_source = "INTERGEN_FIXED_CHECKPOINT"
        else:
            ckpt_path = _resolve_checkpoint_path(str(model_cfg.CHECKPOINT))
            checkpoint_source = "model.yaml/CHECKPOINT(auto-resolved)"

        fixed_cfg_weight_raw = os.getenv("INTERGEN_FIXED_CFG_WEIGHT", "5.0").strip()
        fixed_strategy = os.getenv("INTERGEN_FIXED_SAMPLING_STRATEGY", "ddim50").strip() or "ddim50"
        cfg_weight = _clamp_float(float(fixed_cfg_weight_raw), 1.0, 9.0)

        model_cfg.CFG_WEIGHT = cfg_weight
        model_cfg.STRATEGY = fixed_strategy
        model_cfg.CHECKPOINT = str(ckpt_path)
        model_cfg.freeze()

        print("[Infer] Locked startup config:")
        print(f"  checkpoint_source: {checkpoint_source}")
        print(f"  checkpoint_path: {ckpt_path}")
        print(f"  cfg_weight: {model_cfg.CFG_WEIGHT}")
        print(f"  sampling_strategy: {model_cfg.STRATEGY}")

        model = _build_model(model_cfg)
        if model_cfg.CHECKPOINT:
            if not ckpt_path.exists():
                raise FileNotFoundError(f"Checkpoint not found: {ckpt_path}")
            ckpt = torch.load(str(ckpt_path), map_location="cpu")
            state_dict = ckpt.get("state_dict", {})
            for key in list(state_dict.keys()):
                if key.startswith("model."):
                    state_dict[key.replace("model.", "", 1)] = state_dict.pop(key)
            model.load_state_dict(state_dict, strict=False)

        preferred_device = os.getenv("INTERGEN_DEVICE", "cpu")
        device = _resolve_runtime_device(preferred_device)
        self._model = LitGenModel(model, infer_cfg).to(device)
        print(f"[Device] forced_cpu=1, preferred={preferred_device}, selected={device}")

    def generate(
        self,
        prompt: str,
        output_path: Path,
        num_samples: int = 5,
        motion_frames: Optional[int] = None,
        cfg_weight: Optional[float] = None,
    ):
        if self._model is None:
            raise RuntimeError("Model not loaded")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with self._infer_lock:
            with torch.no_grad():
                sample_count = _clamp_int(num_samples, 1, 8)
                candidate_dir = output_path.parent / "candidates"
                candidate_dir.mkdir(parents=True, exist_ok=True)

                candidates = []
                for i in range(sample_count):
                    candidate_path = candidate_dir / f"{output_path.stem}_sample{i+1}.mp4"
                    result = self._model.generate_one_sample(
                        prompt,
                        str(candidate_path),
                        motion_frames=motion_frames,
                        cfg_weight=cfg_weight,
                    )
                    if not candidate_path.exists():
                        raise FileNotFoundError(f"Expected sample output not found: {candidate_path}")
                    candidates.append(
                        {
                            "path": candidate_path,
                            "file_size": candidate_path.stat().st_size,
                            **(result or {}),
                        }
                    )

                best = _pick_best_candidate(candidates)
                best_path = Path(best["path"])
                shutil.copy2(str(best_path), str(output_path))

                keep_all = os.getenv("INTERGEN_KEEP_ALL_SAMPLES", "0").strip() == "1"
                if not keep_all:
                    for item in candidates:
                        p = Path(item["path"])
                        if p != best_path and p.exists():
                            p.unlink()

                best_idx = candidates.index(best) + 1
                summary_message = f"Best-of-{sample_count} selected sample #{best_idx}."
                merged = dict(best)
                merged["selected_sample"] = str(best_idx)
                merged["num_samples"] = str(sample_count)
                merged["message"] = f"{best.get('message', 'Task completed')} {summary_message}".strip()
                return merged


app = FastAPI(title="InterGen Async API (CPU)", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=1)
service = InterGenService()
_tasks: Dict[str, TaskInfo] = {}
_task_lock = threading.Lock()


def _update_task(task_id: str, **kwargs) -> None:
    with _task_lock:
        task = _tasks.get(task_id)
        if task is None:
            return
        if hasattr(task, "model_dump"):
            data = task.model_dump()
        else:
            data = task.dict()
        data.update(kwargs)
        data["updated_at"] = _utc_now()
        _tasks[task_id] = TaskInfo(**data)


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _sanitize_prompt_text(text: str) -> str:
    cleaned = (text or "").strip().replace("\n", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"^(translation|translated|english)\s*[:：-]\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" \t\"'“”‘’")


def _optimize_prompt_for_intergen(text: str) -> str:
    prompt = _sanitize_prompt_text(text)
    if not prompt:
        return "Two people are interacting physically."

    if _contains_cjk(prompt):
        # Translation failed or returned mixed-language text.
        return "Two people are dancing together."

    prompt_l = prompt.lower()

    if any(k in prompt_l for k in ["dance", "dancing", "waltz", "tango"]):
        return "Two people are dancing together face to face with synchronized body movements."
    if any(k in prompt_l for k in ["fencing", "fencer", "foil", "sabre", "sword", "duel"]):
        return "Two fencers are rapidly lunging, parrying, and stepping in an intense duel."
    if any(k in prompt_l for k in ["hug", "embrace"]):
        return "Two people are hugging each other while standing face to face."
    if any(k in prompt_l for k in ["fight", "boxing", "box", "punch", "kick"]):
        return "Two people are fighting with coordinated punches and defensive movements."
    if any(k in prompt_l for k in ["handshake", "shake hands"]):
        return "Two people are shaking hands while standing face to face."

    if not re.search(r"\b(two|2)\b", prompt_l):
        prompt = f"Two people are {prompt.rstrip('.')}"

    words = prompt.split()
    if len(words) > 24:
        prompt = " ".join(words[:24])
    if not prompt.endswith("."):
        prompt += "."
    return prompt


def _translate_if_needed(text: str) -> str:
    """
    If the text contains Chinese characters, attempt to translate to English using DashScope.
    If DashScope is not configured or errors occur, returns the original text to let the model try.
    """
    if not _contains_cjk(text):
        return _sanitize_prompt_text(text)

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        print("[Translate] Dashscope API Key missing, skipping translation.")
        return text

    base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=base_url)
        completion = client.chat.completions.create(
            model="qwen-mt-flash",
            messages=[{"role": "user", "content": text}],
            extra_body={
                "translation_options": {
                    "source_lang": "auto",
                    "target_lang": "English",
                }
            },
        )
        translated = completion.choices[0].message.content
        if translated:
            translated = _sanitize_prompt_text(translated)
            print(f"[Translate] {text} -> {translated}")
            return translated
    except Exception as e:
        print(f"[Translate] Error during translation: {e}")
    return _sanitize_prompt_text(text)


def _prepare_prompt_for_model(text: str) -> str:
    translated = _translate_if_needed(text)
    optimized = _optimize_prompt_for_intergen(translated)
    print(f"[Prompt] model_input={optimized}")
    return optimized


def _run_generate_task(task_id: str, req: GenerateMotionRequest) -> None:
    try:
        _update_task(task_id, status="running", message="Translating prompt...", progress=10)
        final_prompt = _prepare_prompt_for_model(req.text)

        _update_task(task_id, status="running", message="Generating motion...", progress=30)

        task_root = DEFAULT_TASK_ROOT / task_id
        output_path = task_root / "output" / f"{task_id}.mp4"

        render_result = service.generate(
            final_prompt,
            output_path,
            num_samples=req.num_samples,
            motion_frames=req.motion_frames,
            cfg_weight=req.cfg_weight,
        )

        if not output_path.exists():
            raise FileNotFoundError(f"Expected output not found: {output_path}")

        task_message = (render_result or {}).get("message", "Task completed")
        fallback_reason = (render_result or {}).get("fallback_reason", "")
        stderr_tail = _tail_text(fallback_reason) if fallback_reason else ""

        _update_task(
            task_id,
            status="succeeded",
            message=task_message,
            progress=100,
            final_prompt=final_prompt,
            output_mp4_path=str(output_path.resolve()),
            stderr_tail=stderr_tail,
        )
    except Exception as exc:
        _update_task(
            task_id,
            status="failed",
            message=str(exc),
            progress=100,
            stderr_tail=_tail_text(traceback.format_exc()),
        )


@app.on_event("startup")
def _on_startup() -> None:
    service.load()


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/translate")
def translate(req: TranslateRequest) -> Dict[str, str]:
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="DASHSCOPE_API_KEY not configured")

    base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        completion = client.chat.completions.create(
            model="qwen-mt-flash",
            messages=[{"role": "user", "content": req.text}],
            extra_body={
                "translation_options": {
                    "source_lang": "auto",
                    "target_lang": req.target_lang,
                }
            },
        )
        translated = completion.choices[0].message.content
        if not translated:
            raise HTTPException(status_code=502, detail="Translation service returned empty response")
        return {"translation": translated}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.post("/v1/intergen/tasks/generate", response_model=TaskInfo)
def create_generate_task(req: GenerateMotionRequest) -> TaskInfo:
    task_id = str(uuid.uuid4())
    now = _utc_now()
    task = TaskInfo(
        task_id=task_id,
        status="queued",
        created_at=now,
        updated_at=now,
        message="Task queued",
    )
    with _task_lock:
        _tasks[task_id] = task

    executor.submit(_run_generate_task, task_id, req)
    return task


@app.get("/v1/intergen/tasks/{task_id}", response_model=TaskInfo)
def get_task(task_id: str) -> TaskInfo:
    with _task_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/v1/intergen/tasks/{task_id}/download")
def download_task_result(task_id: str) -> FileResponse:
    with _task_lock:
        task = _tasks.get(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != "succeeded" or not task.output_mp4_path:
        raise HTTPException(status_code=409, detail="Task not completed")

    mp4_path = Path(task.output_mp4_path)
    if not mp4_path.exists():
        raise HTTPException(status_code=410, detail="Output file no longer exists")

    return FileResponse(
        path=str(mp4_path),
        media_type="video/mp4",
        filename=mp4_path.name,
    )


if __name__ == "__main__":
    host = os.getenv("INTERGEN_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = int(os.getenv("INTERGEN_PORT", "8001"))

    # Fail fast on port conflicts before model startup work.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((host, port))
    except OSError:
        raise SystemExit(f"Port {port} is already in use. Set INTERGEN_PORT to another value and retry.")
    finally:
        probe.close()

    uvicorn.run(app, host=host, port=port)
