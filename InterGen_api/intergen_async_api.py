# InterGen GPU 异步服务主入口。
# 负责文本翻译与规范化、双人动作采样、SMPL 预览、BVH 导出、角色重定向、
# 任务状态管理和结果下载；耗时任务由单线程执行器串行执行，避免并发占满显存。
import os
import sys
import socket
import threading
import traceback
import uuid
import re
import random
import secrets
import shutil
import json
import subprocess
import gc
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
SUBPROCESS_ENCODING = os.getenv("INTERGEN_SUBPROCESS_ENCODING", "utf-8")
SUBPROCESS_ERRORS = os.getenv("INTERGEN_SUBPROCESS_ERRORS", "replace")


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

from shared.skin_catalog import (
    SkinCatalogError,
    public_skin_catalog,
    resolve_skin_resource,
    resolve_skins,
    skin_requires_retarget,
)
from shared.task_manifest import restore_task_manifests, write_task_manifest
# 【实验功能，未应用于实际生产默认逻辑链路】
# Motion Planner 与候选审计仅保留为显式 API 实验能力。当前生产前端不发送相关字段，
# 两个开关默认均为关闭；最终结果仍由 _pick_best_candidate 的物理质量规则选出。
try:
    from InterGen_api.motion_planner import (
        MotionPlan,
        MotionPlannerError,
        PlannerSettings,
        compile_intergen_prompt,
        request_motion_plan,
    )
    from InterGen_api.candidate_pool_audit import write_candidate_audit_manifest
except ImportError:
    # Direct execution from InterGen_api/ keeps that folder on sys.path.
    from motion_planner import (
        MotionPlan,
        MotionPlannerError,
        PlannerSettings,
        compile_intergen_prompt,
        request_motion_plan,
    )
    from candidate_pool_audit import write_candidate_audit_manifest

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
    person_a_skin_id: Optional[str] = Field(
        default=None,
        description="Skin id for InterGen person A; must be provided with person_b_skin_id",
    )
    person_b_skin_id: Optional[str] = Field(
        default=None,
        description="Skin id for InterGen person B; must be provided with person_a_skin_id",
    )
    skin_ids: Optional[List[str]] = Field(
        default=None,
        description="One or more requested skin ids; takes precedence over legacy skin_id",
    )
    skin_id: Optional[str] = Field(
        default=None,
        description="Requested skin id from config/skin_catalog.json; defaults to smpl",
    )
    num_samples: Optional[int] = Field(default=None, ge=1, le=8, description="Number of candidates to sample before selecting best")
    candidate_audit: bool = Field(
        default=False,
        description=(
            "Retain every SMPL candidate and write a human-review audit manifest; "
            "disabled by default and uses 8 samples when num_samples is omitted"
        ),
    )
    motion_frames: Optional[int] = Field(
        default=None,
        ge=180,
        le=210,
        description="Optional motion length in frames (180-210, equal to 6-7 seconds at 30 FPS)",
    )
    cfg_weight: Optional[float] = Field(default=None, ge=1.0, le=9.0, description="Optional classifier-free guidance weight")
    seed: Optional[int] = Field(
        default=None,
        ge=0,
        le=2147483646,
        description="Optional replay seed; a random seed is assigned and returned when omitted",
    )
    experiment_group: Optional[str] = Field(
        default=None,
        max_length=96,
        description="Optional experiment group used to associate baseline and planner variants",
    )
    experiment_variant: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Optional experiment variant label such as baseline, manual-plan, or planner-api",
    )
    translation_required: bool = Field(
        default=False,
        description="Fail before motion generation when a CJK prompt cannot be translated; intended for controlled experiments",
    )
    planner_enabled: bool = Field(
        default=False,
        description="Use the configured API Motion Planner before InterGen; disabled by default",
    )
    planner_required: bool = Field(
        default=False,
        description="Fail instead of falling back to the baseline prompt when planning fails",
    )
    planner_model: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Optional planner model override; provider and base URL remain server controlled",
    )
    motion_plan: Optional[MotionPlan] = Field(
        default=None,
        description="Optional validated manual plan for reproducible planner-vs-baseline experiments",
    )
    retarget_enabled: bool = Field(default=False, description="Export BVH and run Blender/Rokoko retarget for person1")
    retarget_strict: bool = Field(default=False, description="Fail the task if retargeting fails")
    target_fbx: Optional[str] = Field(default=None, description="Target character FBX path")
    mapping_file: Optional[str] = Field(default=None, description="Rokoko bone mapping JSON path")
    blender_executable: Optional[str] = Field(default=None, description="Blender executable path")
    retarget_script: Optional[str] = Field(default=None, description="Blender Python retarget script path")


class RetryRetargetRequest(BaseModel):
    skin_id: Optional[str] = Field(
        default="robot",
        description="Requested retarget skin id from config/skin_catalog.json",
    )
    retarget_strict: bool = Field(default=False, description="Fail the retry if retargeting fails")
    target_fbx: Optional[str] = Field(default=None, description="Target character FBX path")
    mapping_file: Optional[str] = Field(default=None, description="Rokoko bone mapping JSON path")
    blender_executable: Optional[str] = Field(default=None, description="Blender executable path")
    retarget_script: Optional[str] = Field(default=None, description="Blender Python retarget script path")
    motion_prompt: Optional[str] = Field(
        default=None,
        description="Optional prompt used to resolve an action-aware target spacing for historical tasks",
    )


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text to be translated")
    target_lang: str = Field(default="English", description="Translation target language")


class CandidateReviewRequest(BaseModel):
    mutual_facing: bool
    racket_swing_proxy: bool
    receiver_ready_and_reacts: bool
    role_consistency: bool
    badminton_semantic_match: bool
    reviewer: str = Field(default="", max_length=96)
    notes: str = Field(default="", max_length=2000)


class TaskInfo(BaseModel):
    task_id: str
    status: str
    created_at: str
    updated_at: str
    skin_id: str = "smpl"
    requested_skin_ids: List[str] = Field(default_factory=lambda: ["smpl"])
    available_skin_ids: List[str] = Field(default_factory=list)
    person_skin_ids: List[str] = Field(default_factory=list)
    message: str = ""
    progress: int = 0
    original_prompt: str = ""
    translated_prompt: str = ""
    translation_status: str = "not-started"
    translation_error: str = ""
    baseline_prompt: str = ""
    final_prompt: str = ""
    seed: Optional[int] = None
    experiment_group: str = ""
    experiment_variant: str = "baseline"
    planner_status: str = "disabled"
    planner_provider: str = ""
    planner_model: str = ""
    planner_error: str = ""
    motion_plan: Optional[Dict[str, object]] = None
    selected_sample: Optional[int] = None
    num_samples: Optional[int] = None
    candidate_summaries: List[Dict[str, object]] = Field(default_factory=list)
    candidate_audit: bool = False
    candidate_audit_manifest_path: Optional[str] = None
    experiment_manifest_path: Optional[str] = None
    output_mp4_path: Optional[str] = None
    output_bvh_path: Optional[str] = None
    output_retarget_path: Optional[str] = None
    output_retarget_mp4_path: Optional[str] = None
    generated_frames: Optional[int] = None
    fps: Optional[int] = None
    duration_seconds: Optional[float] = None
    retarget_status: str = ""
    retarget_message: str = ""
    stdout_tail: str = ""
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
        del prompt
        hard_maximum_frames = 720
        minimum_frames = _clamp_int(
            int(os.getenv("INTERGEN_MIN_MOTION_FRAMES", "180")),
            180,
            hard_maximum_frames,
        )
        configured_maximum_frames = _clamp_int(
            int(os.getenv("INTERGEN_MAX_MOTION_FRAMES", "210")),
            minimum_frames,
            hard_maximum_frames,
        )
        default_frames = _clamp_int(
            int(
                os.getenv(
                    "INTERGEN_DEFAULT_MOTION_FRAMES",
                    os.getenv("INTERGEN_MOTION_FRAMES", "180"),
                )
            ),
            minimum_frames,
            hard_maximum_frames,
        )
        maximum_frames = max(configured_maximum_frames, default_frames)
        if motion_frames is not None:
            return _clamp_int(motion_frames, minimum_frames, maximum_frames)
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
        render_preview: bool = True,
    ) -> Dict[str, object]:
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

        generation_attempts = max(1, _env_int("INTERGEN_GENERATION_ATTEMPTS_PER_SAMPLE", 2))
        motion_output = None
        frame_counts = []
        try:
            for attempt in range(1, generation_attempts + 1):
                motion_output = self.generate_loop(batch, window_size)
                frame_counts = [int(len(sequence)) for sequence in motion_output]
                if len(frame_counts) == 2 and all(count == window_size for count in frame_counts):
                    break
                print(
                    "[Generate] Frame-count mismatch: "
                    f"expected={window_size}, actual={frame_counts}, "
                    f"attempt={attempt}/{generation_attempts}"
                )
            else:
                raise RuntimeError(
                    "InterGen returned an invalid motion length after retries: "
                    f"expected={window_size}, actual={frame_counts}"
                )
        finally:
            if old_cfg_weight is not None:
                self.model.decoder.cfg_weight = old_cfg_weight

        generated_frames = int(frame_counts[0])
        raw_dir = Path(output_path).parent / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_joints_files = []
        for person_idx, joints3d in enumerate(motion_output, start=1):
            raw_path = raw_dir / f"{Path(output_path).stem}_person{person_idx}_joints22.npy"
            np.save(str(raw_path), joints3d.astype(np.float32))
            raw_joints_files.append(str(raw_path.resolve()))

        if not render_preview:
            fps = _clamp_int(int(os.getenv("INTERGEN_FPS", "30")), 15, 30)
            target_duration_sec = generated_frames / float(max(fps, 1))
            print("[Render] skipped by skin selection (retarget-only task)")
            return {
                "render_mode": "skipped",
                "message": "Motion generated; SMPL preview skipped by skin selection",
                "fallback_used": "0",
                "raw_joints_files": raw_joints_files,
                "generated_frames": generated_frames,
                "fps": fps,
                "duration_seconds": round(target_duration_sec, 3),
            }

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
        min_duration_sec = max(6.0, float(os.getenv("INTERGEN_MIN_DURATION_SEC", str(defaults["min_duration_sec"]))))
        fit_early_stop_patience = int(os.getenv("INTERGEN_FIT_EARLY_STOP_PATIENCE", str(defaults["fit_early_stop_patience"])))
        fit_early_stop_check_every = int(os.getenv("INTERGEN_FIT_EARLY_STOP_CHECK_EVERY", str(defaults["fit_early_stop_check_every"])))
        fit_early_stop_rel_tol = float(os.getenv("INTERGEN_FIT_EARLY_STOP_REL_TOL", str(defaults["fit_early_stop_rel_tol"])))

        fps = _clamp_int(fps, 15, 30)
        camera_elev = _clamp_float(camera_elev, 0.0, 89.0)
        camera_azim_offset = _clamp_float(camera_azim_offset, -180.0, 180.0)
        camera_orbit_speed = _clamp_float(camera_orbit_speed, 0.0, 0.2)
        min_duration_sec = _clamp_float(min_duration_sec, 6.0, 20.0)
        target_duration_sec = generated_frames / float(max(fps, 1))
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
                    "raw_joints_files": raw_joints_files,
                    "generated_frames": generated_frames,
                    "fps": fps,
                    "duration_seconds": round(target_duration_sec, 3),
                }
            except Exception as exc:
                strict_mode = os.getenv("INTERGEN_SMPL_STRICT", "0").strip() == "1"
                if strict_mode:
                    raise
                self.plot_t2m([motion_output[0], motion_output[1]], output_path, batch["prompt"])
                return {
                    "render_mode": "skeleton",
                    "message": "动作生成完成；SMPL 渲染失败，已提供骨架预览",
                    "fallback_used": "1",
                    "fallback_reason": str(exc),
                    "raw_joints_files": raw_joints_files,
                    "generated_frames": generated_frames,
                    "fps": fps,
                    "duration_seconds": round(target_duration_sec, 3),
                }
        else:
            self.plot_t2m([motion_output[0], motion_output[1]], output_path, batch["prompt"])
            return {
                "render_mode": "skeleton",
                "message": "动作生成完成（骨架预览）",
                "fallback_used": "0",
                "raw_joints_files": raw_joints_files,
                "generated_frames": generated_frames,
                "fps": fps,
                "duration_seconds": round(target_duration_sec, 3),
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


def _resolve_runtime_device(preferred: str = "cuda:0") -> torch.device:
    choice = (preferred or "cuda:0").strip().lower()
    if choice.startswith("cuda"):
        if torch.cuda.is_available():
            try:
                return torch.device(choice)
            except Exception:
                return torch.device("cuda:0")
        return torch.device("cpu")
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


def _resolved_seed(seed: Optional[int]) -> int:
    if seed is None:
        return secrets.randbelow(2147483647)
    return int(seed) % 2147483647


def _set_inference_seed(seed: int) -> None:
    seed = _resolved_seed(seed)
    random.seed(seed)
    np.random.seed(seed % (2**32 - 1))
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def _model_dict(value) -> Optional[Dict[str, object]]:
    if value is None:
        return None
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    raise TypeError(f"Cannot serialize model value: {type(value).__name__}")


def _clean_experiment_label(value: Optional[str], fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip("-.")
    return (cleaned[:96] or fallback)


def _write_experiment_manifest(
    task_root: Path,
    task_id: str,
    req: GenerateMotionRequest,
    prompt_context: Dict[str, object],
    *,
    status: str,
    generation: Optional[Dict[str, object]] = None,
    error: str = "",
) -> Path:
    task_root.mkdir(parents=True, exist_ok=True)
    manifest_path = task_root / "experiment_manifest.json"
    existing: Dict[str, object] = {}
    if manifest_path.is_file():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    seed = _resolved_seed(req.seed)
    variant = _clean_experiment_label(
        req.experiment_variant,
        "manual-plan" if req.motion_plan is not None else ("planner-api" if req.planner_enabled else "baseline"),
    )
    group = _clean_experiment_label(req.experiment_group, task_id)
    payload: Dict[str, object] = {
        "schema_version": 1,
        "task_id": task_id,
        "created_at": existing.get("created_at") or _utc_now(),
        "updated_at": _utc_now(),
        "status": status,
        "experiment": {
            "group": group,
            "variant": variant,
            "seed": seed,
        },
        "prompt": prompt_context,
        "request": {
            "num_samples": req.num_samples,
            "candidate_audit": bool(req.candidate_audit),
            "motion_frames": req.motion_frames,
            "cfg_weight": req.cfg_weight,
            "planner_enabled": bool(req.planner_enabled),
            "planner_required": bool(req.planner_required),
            "translation_required": bool(req.translation_required),
            "planner_model_override": req.planner_model or "",
            "requested_skin_ids": list(req.skin_ids or []),
            "person_skin_ids": [
                value
                for value in [req.person_a_skin_id, req.person_b_skin_id]
                if value
            ],
        },
        "runtime": {
            "checkpoint": os.getenv("INTERGEN_FIXED_CHECKPOINT", ""),
            "sampling_strategy": os.getenv("INTERGEN_FIXED_SAMPLING_STRATEGY", "ddim50"),
            "candidate_selection": "physical-quality-only",
            "semantic_critic": "unavailable",
            "candidate_audit": "human-review-required" if req.candidate_audit else "disabled",
        },
        "generation": generation or {},
        "error": _tail_text(error) if error else "",
    }
    temp_path = manifest_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(manifest_path)
    return manifest_path.resolve()


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


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _motion_profile(prompt: str) -> str:
    prompt_l = (prompt or "").lower()
    if any(k in prompt_l for k in ["fencing", "fencer", "foil", "sabre", "sword", "duel", "击剑", "剑术"]):
        return "fencing"
    if any(k in prompt_l for k in [
        "fight", "fighting", "boxing", "boxer", "punch", "jab", "kick", "combat",
        "拳击", "格斗", "搏斗",
    ]):
        return "boxing"
    if any(k in prompt_l for k in ["dance", "dancing", "waltz", "tango", "跳舞", "舞蹈"]):
        return "dance"
    if any(k in prompt_l for k in ["run", "running", "jog", "jogging", "sprint", "奔跑", "跑步"]):
        return "running"
    if any(k in prompt_l for k in [
        "slap", "hit", "high five", "handshake", "shake hands", "hug", "embrace",
        "击掌", "握手", "拥抱",
    ]):
        return "short_interaction"
    return "default"


def _resolve_retarget_spacing(prompt: str) -> Tuple[str, float]:
    profile = _motion_profile(prompt)
    settings = {
        "dance": ("INTERGEN_RETARGET_DANCE_SPACING", 1.25),
        "boxing": ("INTERGEN_RETARGET_BOXING_SPACING", 0.45),
        "fencing": ("INTERGEN_RETARGET_FENCING_SPACING", 0.65),
        "running": ("INTERGEN_RETARGET_RUNNING_SPACING", 1.0),
        "short_interaction": ("INTERGEN_RETARGET_SHORT_INTERACTION_SPACING", 0.75),
        "default": ("INTERGEN_RETARGET_TARGET_SPACING", 1.0),
    }
    env_name, default_spacing = settings[profile]
    spacing = _clamp_float(float(os.getenv(env_name, str(default_spacing))), 0.0, 3.0)
    return profile, spacing


def _pick_best_candidate(candidates: list) -> dict:
    """按渲染成功和自碰撞等物理指标选择实际生产输出，不执行语义判断。"""
    # Rank by the weaker person's post-correction result, not an aggregate that
    # can hide a poor second actor behind a clean first actor.
    def _rank(item: dict):
        fallback_used = 1 if str(item.get("fallback_used", "0")) == "1" else 0
        collision = item.get("self_collision") or {}
        hard_violation_count = int(collision.get("hard_violation_count", 0) or 0)
        motionlint = item.get("motionlint") or {}
        motionlint_score = float(motionlint.get("overall_score", 0) or 0)
        max_person_ratio = float(collision.get("max_person_collision_ratio", 0.0) or 0.0)
        minimum_distance = collision.get("minimum_distance")
        minimum_distance = float(minimum_distance) if minimum_distance is not None else float("inf")
        collision_frames = int(collision.get("collision_frames", 0) or 0)
        penetration = float(collision.get("penetration_sum", 0.0) or 0.0)
        file_size = int(item.get("file_size", 0) or 0)
        return (
            fallback_used,
            hard_violation_count,
            max_person_ratio,
            -motionlint_score,
            -minimum_distance,
            collision_frames,
            penetration,
            -file_size,
        )

    return sorted(candidates, key=_rank)[0]


def _candidate_motionlint_metrics(raw_joints_files: List[str]) -> dict:
    """Score candidate joint tracks without loading another generation model."""
    if not raw_joints_files:
        return {"status": "unavailable", "reason": "No raw joint tracks"}
    try:
        from motionlint.adapters.intergen_adapter import load_intergen_joints
        from motionlint.pipeline.inspector import inspect

        report = inspect(load_intergen_joints(raw_joints_files))
        return {
            "status": "ok",
            "overall_score": report.overall_score,
            "critical_issue_count": report.critical_issue_count,
            "test_scores": {test.test_name: test.score for test in report.tests},
        }
    except (OSError, ValueError, ImportError) as exc:
        return {"status": "unavailable", "reason": str(exc)[:200]}


def _raw_hand_head_collision_metrics(raw_joints_files: List[str]) -> dict:
    from intergen_joints2bvh import (
        _correct_hand_head_collisions,
        _hand_head_metrics,
        _stabilize_upper_body_joints,
    )

    clearance_scale = max(0.1, float(os.getenv("INTERGEN_BVH_HAND_HEAD_CLEARANCE_SCALE", "2.0")))
    minimum_clearance = max(0.0, float(os.getenv("INTERGEN_BVH_HAND_HEAD_MIN_CLEARANCE", "0.15")))
    forearm_clearance_scale = max(
        0.1,
        float(os.getenv("INTERGEN_BVH_HAND_HEAD_FOREARM_CLEARANCE_SCALE", "1.5")),
    )
    forearm_minimum_clearance = max(
        0.0,
        float(os.getenv("INTERGEN_BVH_HAND_HEAD_FOREARM_MIN_CLEARANCE", "0.11")),
    )
    hard_ratio = max(0.0, float(os.getenv("INTERGEN_BVH_HARD_SELF_COLLISION_RATIO", "0.15")))
    hard_minimum_distance = max(
        0.0,
        float(os.getenv("INTERGEN_BVH_HARD_SELF_COLLISION_MIN_DISTANCE", "0.05")),
    )
    collision_frames = 0
    penetration_sum = 0.0
    minimum_distance = float("inf")
    max_person_collision_ratio = 0.0
    hard_violation_count = 0
    persons = []

    for person_idx, raw_file in enumerate(raw_joints_files, start=1):
        joints = np.load(str(raw_file), allow_pickle=False)
        if joints.ndim != 3 or joints.shape[1:] != (22, 3):
            continue
        if _env_flag("INTERGEN_BVH_UPPER_BODY_STABILIZATION", True):
            joints, _ = _stabilize_upper_body_joints(
                joints,
                upper_body_window=max(1, _env_int("INTERGEN_BVH_UPPER_BODY_JOINT_WINDOW", 5)),
                neck_window=max(1, _env_int("INTERGEN_BVH_NECK_JOINT_WINDOW", 7)),
                neck_max_position_correction=max(
                    0.0,
                    float(os.getenv("INTERGEN_BVH_NECK_MAX_POSITION_CORRECTION", "0.04")),
                ),
                head_max_position_correction=max(
                    0.0,
                    float(os.getenv("INTERGEN_BVH_HEAD_MAX_POSITION_CORRECTION", "0.03")),
                ),
            )
        head = joints[:, 15]
        head_lengths = np.linalg.norm(head - joints[:, 12], axis=-1)
        valid_head_lengths = head_lengths[head_lengths > 1e-6]
        head_length = float(np.median(valid_head_lengths)) if len(valid_head_lengths) else 0.0
        wrist_clearance = max(minimum_clearance, clearance_scale * head_length)
        forearm_clearance = max(
            forearm_minimum_clearance,
            forearm_clearance_scale * head_length,
        )
        if _env_flag("INTERGEN_BVH_HAND_HEAD_COLLISION", True):
            _, correction = _correct_hand_head_collisions(
                joints,
                clearance_scale=clearance_scale,
                minimum_clearance=minimum_clearance,
                forearm_clearance_scale=forearm_clearance_scale,
                forearm_minimum_clearance=forearm_minimum_clearance,
                blend_window=max(1, _env_int("INTERGEN_BVH_HAND_HEAD_BLEND_WINDOW", 7)),
                elbow_max_correction=max(
                    0.0,
                    float(os.getenv("INTERGEN_BVH_HAND_HEAD_ELBOW_MAX_CORRECTION", "0.03")),
                ),
                wrist_max_correction=max(
                    0.0,
                    float(os.getenv("INTERGEN_BVH_HAND_HEAD_MAX_CORRECTION", "0.05")),
                ),
            )
            metrics = correction["after"]
        else:
            metrics = _hand_head_metrics(joints, wrist_clearance, forearm_clearance)

        person_minimum_distance = float(metrics["minimum_distance"])
        person_collision_ratio = float(metrics["collision_ratio"])
        severe = (
            person_collision_ratio > hard_ratio
            or person_minimum_distance < hard_minimum_distance
        )
        minimum_distance = min(minimum_distance, person_minimum_distance)
        max_person_collision_ratio = max(max_person_collision_ratio, person_collision_ratio)
        penetration_sum += float(metrics["penetration_sum"])
        collision_frames += int(metrics["collision_frame_count"])
        hard_violation_count += int(severe)
        persons.append({
            "person": person_idx,
            "collision_frames": int(metrics["collision_frame_count"]),
            "collision_ratio": round(person_collision_ratio, 6),
            "minimum_distance": round(person_minimum_distance, 6),
            "penetration_sum": round(float(metrics["penetration_sum"]), 6),
            "hard_violation": severe,
        })

    return {
        "hard_violation_count": hard_violation_count,
        "max_person_collision_ratio": round(max_person_collision_ratio, 6),
        "collision_frames": collision_frames,
        "penetration_sum": round(penetration_sum, 6),
        "minimum_distance": round(minimum_distance, 6) if np.isfinite(minimum_distance) else None,
        "persons": persons,
    }


def _default_target_fbx() -> str:
    return str((PROJECT_ROOT.parent / "X Bot.fbx").resolve())


def _default_mapping_file() -> str:
    return str((PROJECT_ROOT.parent / "momask-main" / "assets" / "mapping.json").resolve())


def _default_retarget_script() -> str:
    return str((PROJECT_ROOT / "LODGE_api" / "blender_rokoko_retarget.py").resolve())


def _default_joints2bvh_script() -> str:
    return str((APP_ROOT / "intergen_joints2bvh.py").resolve())


def _resolve_optional_path(raw_value: Optional[str], env_name: str, default_value: str = "") -> Optional[Path]:
    raw = (raw_value or os.getenv(env_name, "") or default_value).strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _run_subprocess(command: List[str], cwd: Path, timeout_sec: Optional[int] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding=SUBPROCESS_ENCODING,
        errors=SUBPROCESS_ERRORS,
        check=False,
        timeout=timeout_sec,
    )


def _export_intergen_bvh(task_id: str, task_root: Path, raw_joints_file: Path, person_idx: int = 1) -> Path:
    retarget_dir = task_root / "retarget"
    retarget_dir.mkdir(parents=True, exist_ok=True)
    output_bvh = retarget_dir / f"{task_id}_person{person_idx}.bvh"
    output_report = retarget_dir / f"{task_id}_person{person_idx}_bvh_report.json"
    script = _resolve_optional_path(None, "INTERGEN_JOINTS2BVH_SCRIPT", _default_joints2bvh_script())
    momask_root = _resolve_optional_path(None, "INTERGEN_MOMASK_ROOT", str((PROJECT_ROOT.parent / "momask-main").resolve()))
    if script is None or not script.exists():
        raise FileNotFoundError(f"INTERGEN_JOINTS2BVH_SCRIPT not found: {script}")
    if momask_root is None or not momask_root.exists():
        raise FileNotFoundError(f"INTERGEN_MOMASK_ROOT not found: {momask_root}")

    command = [
        sys.executable,
        str(script),
        "--input",
        str(raw_joints_file),
        "--output",
        str(output_bvh),
        "--momask-root",
        str(momask_root),
        "--fps",
        str(int(os.getenv("INTERGEN_FPS", "30"))),
        "--report",
        str(output_report),
    ]
    _update_task(task_id, message=f"Exporting InterGen person{person_idx} joints to BVH", progress=74)
    proc = _run_subprocess(command, cwd=APP_ROOT, timeout_sec=_env_int("INTERGEN_BVH_TIMEOUT_SEC", 900))
    if proc.returncode != 0 or not output_bvh.exists():
        raise RuntimeError(_last_nonempty_line(proc.stderr) or _last_nonempty_line(proc.stdout) or "InterGen BVH export failed")
    return output_bvh


def _run_intergen_retarget_if_requested(
    task_id: str,
    task_root: Path,
    output_path: Path,
    raw_joints_files: List[str],
    req: GenerateMotionRequest,
    motion_prompt: str = "",
) -> None:
    """按角色选择导出双人 BVH，并在需要时调用 Blender/Rokoko 完成重定向。"""
    requested_profiles = _resolve_request_skins(req)
    person_profiles = _resolve_person_skin_profiles(req)
    person_retarget_profiles = [
        profile for profile in person_profiles if skin_requires_retarget(profile)
    ]
    skin_profile = (
        person_retarget_profiles[0]
        if person_retarget_profiles
        else next(
            (profile for profile in requested_profiles if skin_requires_retarget(profile)),
            None,
        )
    )
    if skin_profile is None:
        _update_task(task_id, retarget_status="skipped", retarget_message="Retarget disabled")
        return

    strict = bool(req.retarget_strict) or _env_flag("INTERGEN_RETARGET_STRICT", False)
    if not raw_joints_files:
        message = "Retarget skipped, no raw joints files were generated"
        _update_task(task_id, retarget_status="skipped", retarget_message=message)
        if strict:
            raise RuntimeError(message)
        return

    try:
        source_bvhs = []
        for person_idx, raw_joints_file in enumerate(raw_joints_files[:2], start=1):
            source_bvhs.append(_export_intergen_bvh(task_id, task_root, Path(raw_joints_file).resolve(), person_idx=person_idx))
        if not source_bvhs:
            raise RuntimeError("No InterGen BVH files were exported")
        _update_task(task_id, output_bvh_path=";".join(str(path.resolve()) for path in source_bvhs))
    except Exception as exc:
        _update_task(task_id, retarget_status="failed", retarget_message=str(exc), stderr_tail=_tail_text(traceback.format_exc()))
        if strict:
            raise
        return

    blender_exe = _resolve_optional_path(req.blender_executable, "INTERGEN_BLENDER_EXE")
    if person_retarget_profiles:
        target_fbx_files = [
            Path(resolve_skin_resource(PROJECT_ROOT, profile, "target_fbx") or "").resolve()
            for profile in person_retarget_profiles
        ]
        mapping_files = [
            Path(resolve_skin_resource(PROJECT_ROOT, profile, "mapping_file") or "").resolve()
            for profile in person_retarget_profiles
        ]
    else:
        profile_target_fbx = resolve_skin_resource(PROJECT_ROOT, skin_profile, "target_fbx")
        profile_mapping_file = resolve_skin_resource(PROJECT_ROOT, skin_profile, "mapping_file")
        target_fbx = _resolve_optional_path(
            req.target_fbx or profile_target_fbx,
            "INTERGEN_TARGET_FBX",
            _default_target_fbx(),
        )
        mapping_file = _resolve_optional_path(
            req.mapping_file or profile_mapping_file,
            "INTERGEN_RETARGET_MAPPING",
            _default_mapping_file(),
        )
        target_fbx_files = [target_fbx]
        mapping_files = [mapping_file]
    retarget_script = _resolve_optional_path(req.retarget_script, "INTERGEN_RETARGET_SCRIPT", _default_retarget_script())

    retarget_dir = task_root / "retarget"
    output_mp4 = retarget_dir / f"{task_id}_dual_retarget.mp4"
    report_path = retarget_dir / "rokoko_retarget_report.json"
    manifest_path = retarget_dir / "retarget_manifest.json"
    source_frame_counts = []
    for raw_joints_file in raw_joints_files[:2]:
        joints = np.load(str(raw_joints_file), mmap_mode="r", allow_pickle=False)
        source_frame_counts.append(int(joints.shape[0]))
    generated_frames = min(source_frame_counts) if source_frame_counts else 0
    manifest_fps = int(os.getenv("INTERGEN_FPS", "30"))
    effective_motion_prompt = _sanitize_prompt_text(motion_prompt or req.text)
    motion_profile, target_spacing = _resolve_retarget_spacing(effective_motion_prompt)
    manifest = {
        "task_id": task_id,
        "skin_id": str(skin_profile["id"]),
        "person_skin_ids": [str(profile["id"]) for profile in person_profiles],
        "engine": "blender-rokoko",
        "source_bvh": str(source_bvhs[0].resolve()),
        "source_bvh_files": [str(path.resolve()) for path in source_bvhs],
        "source_bvh_reports": [
            str(path.with_name(f"{path.stem}_bvh_report.json").resolve())
            for path in source_bvhs
        ],
        "target_fbx": str(target_fbx_files[0]),
        "target_fbx_files": [str(path) for path in target_fbx_files],
        "mapping_file": str(mapping_files[0]),
        "mapping_files": [str(path) for path in mapping_files],
        "raw_joints_files": raw_joints_files,
        "source_preview_mp4": str(output_path.resolve()) if output_path.exists() else None,
        "output_mp4": str(output_mp4.resolve()),
        "report_path": str(report_path.resolve()),
        "debug_blend": str((retarget_dir / "retarget_debug.blend").resolve()),
        "fps": manifest_fps,
        "source_frame_counts": source_frame_counts,
        "generated_frames": generated_frames,
        "duration_seconds": round(generated_frames / float(max(manifest_fps, 1)), 3),
        "max_render_frames": _env_int("INTERGEN_RETARGET_MAX_RENDER_FRAMES", 120),
        "render_size": os.getenv("INTERGEN_RETARGET_RENDER_SIZE", "1080x1080"),
        "camera_distance_scale": float(os.getenv("INTERGEN_RETARGET_CAMERA_DISTANCE_SCALE", "1.15")),
        "motion_prompt": effective_motion_prompt,
        "motion_profile": motion_profile,
        "target_spacing": target_spacing,
        "bvh_temporal_ik": _env_flag("INTERGEN_BVH_TEMPORAL_IK", True),
        "bvh_upper_body_stabilization": _env_flag("INTERGEN_BVH_UPPER_BODY_STABILIZATION", True),
        "bvh_neck_max_position_correction": float(
            os.getenv("INTERGEN_BVH_NECK_MAX_POSITION_CORRECTION", "0.04")
        ),
        "bvh_head_max_position_correction": float(
            os.getenv("INTERGEN_BVH_HEAD_MAX_POSITION_CORRECTION", "0.03")
        ),
        "bvh_root_anomaly_degrees": float(os.getenv("INTERGEN_BVH_ROOT_ANOMALY_DEGREES", "30.0")),
        "bvh_quality_gate": _env_flag("INTERGEN_BVH_QUALITY_GATE", True),
        "bvh_max_anomaly_ratio": float(os.getenv("INTERGEN_BVH_MAX_ANOMALY_RATIO", "0.10")),
        "bvh_max_ik_p95_error": float(os.getenv("INTERGEN_BVH_MAX_IK_P95_ERROR", "0.10")),
        "bvh_hand_head_collision": _env_flag("INTERGEN_BVH_HAND_HEAD_COLLISION", True),
        "bvh_hand_head_clearance_scale": float(
            os.getenv("INTERGEN_BVH_HAND_HEAD_CLEARANCE_SCALE", "2.0")
        ),
        "bvh_hand_head_min_clearance": float(
            os.getenv("INTERGEN_BVH_HAND_HEAD_MIN_CLEARANCE", "0.15")
        ),
        "bvh_hand_head_forearm_clearance_scale": float(
            os.getenv("INTERGEN_BVH_HAND_HEAD_FOREARM_CLEARANCE_SCALE", "1.5")
        ),
        "bvh_hand_head_forearm_min_clearance": float(
            os.getenv("INTERGEN_BVH_HAND_HEAD_FOREARM_MIN_CLEARANCE", "0.11")
        ),
        "bvh_hand_head_blend_window": _env_int("INTERGEN_BVH_HAND_HEAD_BLEND_WINDOW", 7),
        "bvh_hand_head_elbow_max_correction": float(
            os.getenv("INTERGEN_BVH_HAND_HEAD_ELBOW_MAX_CORRECTION", "0.03")
        ),
        "bvh_hand_head_max_correction": float(
            os.getenv("INTERGEN_BVH_HAND_HEAD_MAX_CORRECTION", "0.05")
        ),
        "bvh_max_self_collision_ratio": float(
            os.getenv("INTERGEN_BVH_MAX_SELF_COLLISION_RATIO", "0.02")
        ),
        "bvh_hard_self_collision_ratio": float(
            os.getenv("INTERGEN_BVH_HARD_SELF_COLLISION_RATIO", "0.15")
        ),
        "bvh_hard_self_collision_min_distance": float(
            os.getenv("INTERGEN_BVH_HARD_SELF_COLLISION_MIN_DISTANCE", "0.05")
        ),
        "core_smoothing_window": _env_int("INTERGEN_RETARGET_CORE_SMOOTHING_WINDOW", 5),
        "spine_smoothing_window": _env_int("INTERGEN_RETARGET_SPINE_SMOOTHING_WINDOW", 5),
        "core_max_rotation_degrees_per_frame": float(
            os.getenv("INTERGEN_RETARGET_CORE_MAX_ROTATION_DEGREES_PER_FRAME", "20.0")
        ),
        "spine_max_rotation_degrees_per_frame": float(
            os.getenv("INTERGEN_RETARGET_SPINE_MAX_ROTATION_DEGREES_PER_FRAME", "20.0")
        ),
        "core_max_acceleration_degrees_per_frame2": float(
            os.getenv("INTERGEN_RETARGET_CORE_MAX_ACCELERATION_DEGREES_PER_FRAME2", "6.0")
        ),
        "spine_max_acceleration_degrees_per_frame2": float(
            os.getenv("INTERGEN_RETARGET_SPINE_MAX_ACCELERATION_DEGREES_PER_FRAME2", "8.0")
        ),
        "chest_smoothing_window": _env_int("INTERGEN_RETARGET_CHEST_SMOOTHING_WINDOW", 5),
        "chest_max_rotation_degrees_per_frame": float(
            os.getenv("INTERGEN_RETARGET_CHEST_MAX_ROTATION_DEGREES_PER_FRAME", "18.0")
        ),
        "chest_max_acceleration_degrees_per_frame2": float(
            os.getenv("INTERGEN_RETARGET_CHEST_MAX_ACCELERATION_DEGREES_PER_FRAME2", "8.0")
        ),
        "neck_smoothing_window": _env_int("INTERGEN_RETARGET_NECK_SMOOTHING_WINDOW", 7),
        "neck_max_rotation_degrees_per_frame": float(
            os.getenv("INTERGEN_RETARGET_NECK_MAX_ROTATION_DEGREES_PER_FRAME", "15.0")
        ),
        "neck_max_acceleration_degrees_per_frame2": float(
            os.getenv("INTERGEN_RETARGET_NECK_MAX_ACCELERATION_DEGREES_PER_FRAME2", "6.0")
        ),
        "head_smoothing_window": _env_int("INTERGEN_RETARGET_HEAD_SMOOTHING_WINDOW", 7),
        "head_max_rotation_degrees_per_frame": float(
            os.getenv("INTERGEN_RETARGET_HEAD_MAX_ROTATION_DEGREES_PER_FRAME", "12.0")
        ),
        "head_max_acceleration_degrees_per_frame2": float(
            os.getenv("INTERGEN_RETARGET_HEAD_MAX_ACCELERATION_DEGREES_PER_FRAME2", "6.0")
        ),
        "head_world_stabilization_enabled": _env_flag(
            "INTERGEN_RETARGET_HEAD_WORLD_STABILIZATION_ENABLED", True
        ),
        "head_world_smoothing_window": _env_int("INTERGEN_RETARGET_HEAD_WORLD_SMOOTHING_WINDOW", 3),
        "head_world_max_rotation_degrees_per_frame": float(
            os.getenv("INTERGEN_RETARGET_HEAD_WORLD_MAX_ROTATION_DEGREES_PER_FRAME", "20.0")
        ),
        "head_world_max_acceleration_degrees_per_frame2": float(
            os.getenv("INTERGEN_RETARGET_HEAD_WORLD_MAX_ACCELERATION_DEGREES_PER_FRAME2", "6.0")
        ),
        "foot_lock_enabled": _env_flag("INTERGEN_RETARGET_FOOT_LOCK_ENABLED", True),
        "foot_lock_height_threshold": float(
            os.getenv("INTERGEN_RETARGET_FOOT_LOCK_HEIGHT_THRESHOLD", "0.065")
        ),
        "foot_lock_velocity_threshold": float(
            os.getenv("INTERGEN_RETARGET_FOOT_LOCK_VELOCITY_THRESHOLD", "0.08")
        ),
        "foot_lock_min_contact_frames": _env_int("INTERGEN_RETARGET_FOOT_LOCK_MIN_CONTACT_FRAMES", 3),
        "foot_lock_blend_frames": _env_int("INTERGEN_RETARGET_FOOT_LOCK_BLEND_FRAMES", 2),
        "foot_lock_max_correction": float(
            os.getenv("INTERGEN_RETARGET_FOOT_LOCK_MAX_CORRECTION", "0.15")
        ),
        "created_at": _utc_now(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    required_paths = [blender_exe, retarget_script, *target_fbx_files, *mapping_files, *source_bvhs]
    missing = [str(path) if path is not None else "(empty)" for path in required_paths if path is None or not path.exists()]
    if missing:
        message = "Retarget skipped, missing required path(s): " + "; ".join(missing)
        _update_task(task_id, retarget_status="skipped", retarget_message=message)
        if strict:
            raise FileNotFoundError(message)
        return

    command = [
        str(blender_exe),
        "--background",
        "--python",
        str(retarget_script),
        "--",
        "--manifest",
        str(manifest_path),
    ]
    _update_task(task_id, message="Running Blender/Rokoko retarget", progress=82, retarget_status="running")
    proc = _run_subprocess(command, cwd=retarget_dir, timeout_sec=_env_int("INTERGEN_RETARGET_TIMEOUT_SEC", 3600))
    if proc.returncode == 0 and output_mp4.exists():
        _update_task(
            task_id,
            output_retarget_path=str(output_mp4.resolve()),
            retarget_status="succeeded",
            retarget_message="Rokoko retarget completed",
            stdout_tail=_tail_text(proc.stdout or ""),
            stderr_tail=_tail_text(proc.stderr or ""),
        )
        return

    message = _last_nonempty_line(proc.stderr) or _last_nonempty_line(proc.stdout) or "Blender/Rokoko retarget failed"
    _update_task(
        task_id,
        retarget_status="failed",
        retarget_message=message,
        stdout_tail=_tail_text(proc.stdout or ""),
        stderr_tail=_tail_text(proc.stderr or ""),
    )
    if strict:
        raise RuntimeError(message)


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
    """封装模型冷启动、串行推理、多样本物理选优和稳定产物写盘。"""
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

        low_memory_init = os.getenv("INTERGEN_LOW_MEMORY_INIT") == "1"
        if low_memory_init:
            with torch.device("meta"):
                model = _build_model(model_cfg)
        else:
            model = _build_model(model_cfg)
        if model_cfg.CHECKPOINT:
            if not ckpt_path.exists():
                raise FileNotFoundError(f"Checkpoint not found: {ckpt_path}")
            mapped_checkpoint = False
            try:
                ckpt = torch.load(str(ckpt_path), map_location="cpu", mmap=True, weights_only=True)
                mapped_checkpoint = True
            except (RuntimeError, ValueError, TypeError, OSError):
                ckpt = torch.load(str(ckpt_path), map_location="cpu", weights_only=False)
            state_dict = ckpt.get("state_dict", {})
            for key in list(state_dict.keys()):
                if key.startswith("model."):
                    state_dict[key.replace("model.", "", 1)] = state_dict.pop(key)
            incompatible = model.load_state_dict(state_dict, strict=False, assign=mapped_checkpoint)
            if low_memory_init and incompatible.missing_keys:
                raise RuntimeError(f"Checkpoint missing model keys: {incompatible.missing_keys[:10]}")
            if low_memory_init:
                # These tensors are ordinary attributes and are absent from the
                # checkpoint, so materialize them after leaving the meta context.
                mask = torch.empty(77, 77).fill_(float("-inf")).triu_(1)
                for block in model.clip_transformer.resblocks:
                    block.attn_mask = mask
                model.decoder.diffusion.normalizer.motion_mean = torch.from_numpy(
                    np.load(MODEL_SOURCE_ROOT / "data" / "global_mean.npy")
                ).float()
                model.decoder.diffusion.normalizer.motion_std = torch.from_numpy(
                    np.load(MODEL_SOURCE_ROOT / "data" / "global_std.npy")
                ).float()

        preferred_device = os.getenv("INTERGEN_DEVICE", "cuda:0")
        device = _resolve_runtime_device(preferred_device)
        self._model = LitGenModel(model, infer_cfg).to(device)
        print(f"[Device] preferred={preferred_device}, selected={device}")

    def unload(self):
        with self._infer_lock:
            self._model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def generate(
        self,
        prompt: str,
        output_path: Path,
        num_samples: Optional[int] = None,
        motion_frames: Optional[int] = None,
        cfg_weight: Optional[float] = None,
        render_preview: bool = True,
        seed: Optional[int] = None,
        candidate_audit: bool = False,
    ):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with self._infer_lock:
            if self._model is None:
                self.load()
            with torch.no_grad():
                default_samples = _env_int("INTERGEN_DEFAULT_NUM_SAMPLES", 5)
                if candidate_audit and num_samples is None:
                    default_samples = _env_int("INTERGEN_AUDIT_NUM_SAMPLES", 8)
                prompt_l = prompt.lower()
                if num_samples is None and any(
                    k in prompt_l for k in ["fight", "fighting", "boxing", "boxing match", "boxers"]
                ):
                    default_samples = max(default_samples, _env_int("INTERGEN_COMBAT_NUM_SAMPLES", 2))
                sample_count = _clamp_int(num_samples if num_samples is not None else default_samples, 1, 8)
                replay_seed = _resolved_seed(seed)
                candidate_dir = output_path.parent / "candidates"
                candidate_dir.mkdir(parents=True, exist_ok=True)

                candidates = []
                for i in range(sample_count):
                    candidate_seed = (replay_seed + i) % 2147483647
                    _set_inference_seed(candidate_seed)
                    candidate_path = candidate_dir / f"{output_path.stem}_sample{i+1}.mp4"
                    result = self._model.generate_one_sample(
                        prompt,
                        str(candidate_path),
                        motion_frames=motion_frames,
                        cfg_weight=cfg_weight,
                        render_preview=render_preview,
                    )
                    if render_preview and not candidate_path.exists():
                        raise FileNotFoundError(f"Expected sample output not found: {candidate_path}")
                    collision_metrics = _raw_hand_head_collision_metrics(
                        list((result or {}).get("raw_joints_files") or [])
                    )
                    motionlint_metrics = _candidate_motionlint_metrics(
                        list((result or {}).get("raw_joints_files") or [])
                    )
                    candidates.append(
                        {
                            "path": candidate_path,
                            "candidate_index": i + 1,
                            "seed": candidate_seed,
                            "file_size": candidate_path.stat().st_size if candidate_path.exists() else 0,
                            "self_collision": collision_metrics,
                            "motionlint": motionlint_metrics,
                            **(result or {}),
                        }
                    )

                best = _pick_best_candidate(candidates)
                best_path = Path(best["path"])
                if render_preview:
                    shutil.copy2(str(best_path), str(output_path))
                stable_raw_files = []
                raw_files = best.get("raw_joints_files") or []
                raw_dir = output_path.parent / "raw"
                raw_dir.mkdir(parents=True, exist_ok=True)
                for person_idx, raw_file in enumerate(raw_files, start=1):
                    src = Path(raw_file)
                    if not src.exists():
                        continue
                    dst = raw_dir / f"{output_path.stem}_person{person_idx}_joints22.npy"
                    shutil.copy2(str(src), str(dst))
                    stable_raw_files.append(str(dst.resolve()))

                keep_all = candidate_audit or _env_flag("INTERGEN_KEEP_ALL_SAMPLES", False)
                if not keep_all:
                    for item in candidates:
                        p = Path(item["path"])
                        if p != best_path and p.exists():
                            p.unlink()

                best_idx = candidates.index(best) + 1
                candidate_summaries = []
                for item in candidates:
                    candidate_summaries.append(
                        {
                            "candidate_index": int(item.get("candidate_index") or 0),
                            "seed": int(item.get("seed") or 0),
                            "file_path": str(Path(item["path"]).resolve()),
                            "file_size": int(item.get("file_size") or 0),
                            "generated_frames": int(item.get("generated_frames") or 0),
                            "fps": int(item.get("fps") or 0),
                            "raw_joints_files": [
                                str(Path(path).resolve())
                                for path in list(item.get("raw_joints_files") or [])
                            ],
                            "self_collision": dict(item.get("self_collision") or {}),
                            "motionlint": dict(item.get("motionlint") or {}),
                            "selected": item is best,
                            "retained": Path(item["path"]).is_file(),
                        }
                    )
                summary_message = f"Best-of-{sample_count} selected sample #{best_idx}."
                merged = dict(best)
                merged["seed"] = replay_seed
                merged["selected_sample"] = best_idx
                merged["num_samples"] = sample_count
                merged["candidate_summaries"] = candidate_summaries
                merged["candidate_audit"] = bool(candidate_audit)
                merged["raw_joints_files"] = stable_raw_files
                merged["message"] = f"{best.get('message', 'Task completed')} {summary_message}".strip()
                return merged


app = FastAPI(title="InterGen Async API", version="1.0.0")

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


def _persist_task(task: TaskInfo) -> None:
    write_task_manifest(DEFAULT_TASK_ROOT / task.task_id, task)


def _restore_task_artifacts(task: TaskInfo) -> TaskInfo:
    """Fill output paths for manifests recovered from pre-persistence runs."""

    task_root = DEFAULT_TASK_ROOT / task.task_id
    data = task.model_dump() if hasattr(task, "model_dump") else task.dict()
    experiment_path = task_root / "experiment_manifest.json"
    retarget_path = task_root / "retarget" / "retarget_manifest.json"
    experiment = {}
    retarget = {}
    try:
        if experiment_path.is_file():
            experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
        if retarget_path.is_file():
            retarget = json.loads(retarget_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        experiment = {}
        retarget = {}
    prompt = experiment.get("prompt") or {}
    request = experiment.get("request") or {}
    generation = experiment.get("generation") or {}
    if prompt:
        for key in ("original_prompt", "translated_prompt", "translation_status", "translation_error", "baseline_prompt", "final_prompt", "planner_status", "planner_provider", "planner_model", "planner_error", "motion_plan"):
            if data.get(key) in (None, "", "not-started", "disabled") and key in prompt:
                data[key] = prompt[key]
    if request:
        person_skin_ids = list(request.get("person_skin_ids") or data.get("person_skin_ids") or [])
        data["person_skin_ids"] = person_skin_ids
        data["requested_skin_ids"] = list(request.get("requested_skin_ids") or dict.fromkeys(person_skin_ids) or data.get("requested_skin_ids") or [])
        data["num_samples"] = request.get("num_samples") or data.get("num_samples")
    if generation:
        for key in ("selected_sample", "num_samples", "candidate_summaries", "generated_frames", "fps", "duration_seconds"):
            if generation.get(key) is not None:
                data[key] = generation[key]
    raw_files = sorted((task_root / "output" / "raw").glob(f"{task.task_id}_person*_joints22.npy"))
    if raw_files and not data.get("generated_frames"):
        try:
            data["generated_frames"] = int(np.load(raw_files[0], mmap_mode="r", allow_pickle=False).shape[0])
        except (OSError, ValueError):
            pass
    if experiment_path.is_file():
        data["experiment_manifest_path"] = str(experiment_path.resolve())
    output_bvhs = sorted((task_root / "retarget").glob(f"{task.task_id}_person*.bvh"))
    if output_bvhs and not data.get("output_bvh_path"):
        data["output_bvh_path"] = str(output_bvhs[0].resolve())
    smpl_video = task_root / "output" / f"{task.task_id}.mp4"
    if smpl_video.is_file():
        data["output_mp4_path"] = str(smpl_video.resolve())
        available = list(data.get("available_skin_ids") or [])
        if "smpl" not in available:
            available.append("smpl")
        data["available_skin_ids"] = available
    output_video = task_root / "retarget" / f"{task.task_id}_dual_retarget.mp4"
    if output_video.is_file():
        data["output_retarget_path"] = str(output_video.resolve())
        data["output_retarget_mp4_path"] = str(output_video.resolve())
        data["retarget_status"] = "succeeded"
        person_ids = data.get("person_skin_ids") or retarget.get("person_skin_ids") or []
        data["available_skin_ids"] = list(dict.fromkeys((data.get("available_skin_ids") or []) + (person_ids or [retarget.get("skin_id", "robot")])))
        data["skin_id"] = data["available_skin_ids"][-1]
    if data.get("output_mp4_path") or data.get("output_retarget_mp4_path"):
        data["status"] = "succeeded"
        data["progress"] = 100
    elif data.get("status") == "succeeded":
        data["status"] = "failed"
        data["message"] = "未找到可播放的最终视频；任务产物仍保留。"
    return TaskInfo(**data)


def _restore_tasks() -> Dict[str, TaskInfo]:
    restored = restore_task_manifests(DEFAULT_TASK_ROOT, TaskInfo)
    enriched = {task_id: _restore_task_artifacts(task) for task_id, task in restored.items()}
    for task in enriched.values():
        _persist_task(task)
    return enriched


_tasks.update(_restore_tasks())


def _requested_person_skin_ids(req) -> List[str]:
    person_ids = [
        str(getattr(req, "person_a_skin_id", None) or "").strip(),
        str(getattr(req, "person_b_skin_id", None) or "").strip(),
    ]
    if not any(person_ids):
        return []
    if not all(person_ids):
        raise SkinCatalogError(
            "person_a_skin_id and person_b_skin_id must be provided together"
        )
    return person_ids


def _resolve_person_skin_profiles(req) -> List[Dict[str, object]]:
    person_ids = _requested_person_skin_ids(req)
    if not person_ids:
        return []
    profiles = [resolve_skins(PROJECT_ROOT, [skin_id])[0] for skin_id in person_ids]
    output_kinds = {str(profile.get("output_kind") or "") for profile in profiles}
    if len(output_kinds) != 1:
        raise SkinCatalogError(
            "InterGen cannot mix SMPL and Blender-retargetable person skins in one video"
        )
    return profiles


def _resolve_request_skins(req) -> List[Dict[str, object]]:
    person_profiles = _resolve_person_skin_profiles(req)
    if person_profiles:
        return list({str(profile["id"]): profile for profile in person_profiles}.values())
    return resolve_skins(
        PROJECT_ROOT,
        getattr(req, "skin_ids", None),
        skin_id=getattr(req, "skin_id", None),
        legacy_retarget_enabled=bool(getattr(req, "retarget_enabled", False)),
    )


def _resolve_request_skin(req) -> Dict[str, object]:
    return _resolve_request_skins(req)[0]


def _validate_request_skins(req, require_retarget: bool = False) -> List[Dict[str, object]]:
    try:
        profiles = _resolve_request_skins(req)
    except SkinCatalogError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if require_retarget and not any(skin_requires_retarget(profile) for profile in profiles):
        raise HTTPException(
            status_code=422,
            detail="At least one requested skin must be a retarget skin",
        )
    return profiles


def _validate_request_skin(req, require_retarget: bool = False) -> Dict[str, object]:
    return _validate_request_skins(req, require_retarget=require_retarget)[0]


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
        retarget_path = data.get("output_retarget_mp4_path") or data.get("output_retarget_path")
        if retarget_path:
            data["output_retarget_path"] = retarget_path
            data["output_retarget_mp4_path"] = retarget_path
        available_skin_ids = []
        if data.get("output_mp4_path"):
            available_skin_ids.append("smpl")
        if data.get("retarget_status") == "succeeded" and retarget_path:
            requested_skin_ids = list(data.get("requested_skin_ids") or [])
            retarget_skin_id = next(
                (skin_id for skin_id in requested_skin_ids if skin_id != "smpl"),
                "robot",
            )
            available_skin_ids.append(retarget_skin_id)
        data["available_skin_ids"] = available_skin_ids
        data["updated_at"] = _utc_now()
        updated = TaskInfo(**data)
        _tasks[task_id] = updated
        _persist_task(updated)


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
        if any(k in prompt for k in ["奔跑", "跑步", "跑", "冲刺"]):
            return "Two people are happily running forward side by side with energetic arm swings, keeping a safe distance between them."
        if any(k in prompt for k in ["跳舞", "舞蹈", "舞"]):
            return "Two people are dancing together face to face with synchronized body movements."
        if any(k in prompt for k in ["握手"]):
            return "Two people are shaking hands while standing face to face."
        if any(k in prompt for k in ["拥抱", "抱"]):
            return "Two people are hugging each other while standing face to face."
        return "Two people are interacting physically while keeping a clear distance between their bodies."

    prompt_l = prompt.lower()

    if any(k in prompt_l for k in ["run", "running", "jog", "jogging", "sprint"]):
        return "Two people are happily running forward side by side with energetic arm swings, keeping a safe distance between them."
    if any(k in prompt_l for k in ["dance", "dancing", "waltz", "tango"]):
        return "Two people are dancing together face to face with synchronized body movements."
    if any(k in prompt_l for k in ["fencing", "fencer", "foil", "sabre", "sword", "duel"]):
        return "Two fencers are rapidly lunging, parrying, and stepping in an intense duel."
    if any(k in prompt_l for k in ["hug", "embrace"]):
        return "Two people approach, share a brief hug, release each other, and step back."
    if "high five" in prompt_l:
        return "Two people approach, raise their hands, exchange a high five, lower their arms, and step back."
    if any(k in prompt_l for k in ["fight", "boxing", "box", "punch", "kick"]):
        return (
            "In an intense boxing match, two people face each other in stable fighting stances. "
            "They alternate straight punches, blocks, and dodges while keeping their guarding hands clear of the head."
        )
    if any(k in prompt_l for k in ["handshake", "shake hands"]):
        return "Two people approach, shake hands briefly, release their hands, and step back."

    if not re.search(r"\b(two|2)\b", prompt_l):
        prompt = f"Two people are {prompt.rstrip('.')}"

    max_words = _clamp_int(_env_int("INTERGEN_BASELINE_MAX_PROMPT_WORDS", 48), 24, 64)
    words = prompt.split()
    if len(words) > max_words:
        kept = words[:max_words]
        incomplete_tail = {"a", "an", "and", "at", "for", "from", "in", "of", "the", "to", "toward", "with"}
        while len(kept) > 2 and kept[-1].lower().rstrip(",.;:") in incomplete_tail:
            kept.pop()
        prompt = " ".join(kept)
    if not prompt.endswith("."):
        prompt += "."
    return prompt


def _translate_with_provenance(text: str) -> Tuple[str, str, str]:
    """Return translated text, status, and a sanitized error description."""
    if not _contains_cjk(text):
        return _sanitize_prompt_text(text), "not-needed", ""

    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        error = "DASHSCOPE_API_KEY not configured"
        print(f"[Translate] {error}; skipping translation.")
        return _sanitize_prompt_text(text), "skipped", error

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
            return translated, "succeeded", ""
        error = "DashScope returned empty translation content"
        print(f"[Translate] {error}")
        return _sanitize_prompt_text(text), "failed", error
    except Exception as e:
        error = _tail_text(str(e), max_chars=1000)
        print(f"[Translate] Error during translation: {error}")
        return _sanitize_prompt_text(text), "failed", error


def _translate_if_needed(text: str) -> str:
    """Compatibility wrapper for callers that only need translated text."""
    translated, _, _ = _translate_with_provenance(text)
    return translated


def _prepare_prompt_for_model(text: str) -> str:
    translated = _translate_if_needed(text)
    optimized = _optimize_prompt_for_intergen(translated)
    print(f"[Prompt] model_input={optimized}")
    return optimized


def _prepare_prompt_context(req: GenerateMotionRequest) -> Dict[str, object]:
    # 【实验功能，未应用于实际生产默认逻辑链路】只有调用方显式启用时才进入规划分支；
    # 默认请求直接使用翻译和基础提示词规范化结果，规划失败也不会改变默认生产路径。
    original_prompt = _sanitize_prompt_text(req.text)
    translated_prompt, translation_status, translation_error = _translate_with_provenance(req.text)
    baseline_prompt = _optimize_prompt_for_intergen(translated_prompt)
    final_prompt = baseline_prompt
    plan: Optional[MotionPlan] = None
    planner_status = "disabled"
    planner_provider = ""
    planner_model = req.planner_model or ""
    planner_error = ""
    max_prompt_words = _clamp_int(
        _env_int("INTERGEN_MOTION_PLANNER_MAX_PROMPT_WORDS", 48),
        24,
        64,
    )

    if req.motion_plan is not None:
        plan = req.motion_plan
        planner_status = "manual"
        planner_provider = "manual"
        planner_model = "manual"
        final_prompt = compile_intergen_prompt(plan, max_words=max_prompt_words)
    elif req.planner_enabled:
        planner_status = "requested"
        planner_provider = os.getenv("INTERGEN_MOTION_PLANNER_PROVIDER", "dashscope").strip().lower()
        try:
            settings = PlannerSettings.from_env(model_override=req.planner_model)
            planner_provider = settings.provider
            planner_model = settings.model
            plan = request_motion_plan(req.text, translated_prompt, settings)
            final_prompt = compile_intergen_prompt(plan, max_words=settings.max_prompt_words)
            planner_status = "succeeded"
        except MotionPlannerError as exc:
            planner_status = "failed"
            planner_error = str(exc)
            if req.planner_required:
                raise
            planner_status = "fallback"
            print(f"[MotionPlanner] Falling back to baseline prompt: {planner_error}")

    context: Dict[str, object] = {
        "original_prompt": original_prompt,
        "translated_prompt": translated_prompt,
        "translation_status": translation_status,
        "translation_error": translation_error,
        "baseline_prompt": baseline_prompt,
        "final_prompt": final_prompt,
        "planner_status": planner_status,
        "planner_provider": planner_provider,
        "planner_model": planner_model,
        "planner_error": planner_error,
        "motion_plan": _model_dict(plan),
    }
    print(
        "[Prompt] "
        f"planner_status={planner_status}, baseline={baseline_prompt}, model_input={final_prompt}"
    )
    return context


def _run_generate_task(task_id: str, req: GenerateMotionRequest) -> None:
    """后台生成主流程：准备提示词 → InterGen → 可选预览/重定向 → 更新任务结果。"""
    task_root = DEFAULT_TASK_ROOT / task_id
    req.seed = _resolved_seed(req.seed)
    prompt_context: Dict[str, object] = {
        "original_prompt": _sanitize_prompt_text(req.text),
        "translated_prompt": "",
        "translation_status": "not-started",
        "translation_error": "",
        "baseline_prompt": "",
        "final_prompt": "",
        "planner_status": "not-started",
        "planner_provider": "",
        "planner_model": req.planner_model or "",
        "planner_error": "",
        "motion_plan": _model_dict(req.motion_plan),
    }
    try:
        requested_profiles = _resolve_request_skins(req)
        requested_skin_ids = [str(profile["id"]) for profile in requested_profiles]
        smpl_requested = any(
            str(profile.get("output_kind") or "") == "smpl"
            for profile in requested_profiles
        )
        retarget_requested = any(
            skin_requires_retarget(profile)
            for profile in requested_profiles
        )
        _update_task(task_id, status="running", message="Translating prompt...", progress=10)
        prompt_context = _prepare_prompt_context(req)
        final_prompt = str(prompt_context["final_prompt"])
        manifest_path = _write_experiment_manifest(
            task_root,
            task_id,
            req,
            prompt_context,
            status="prepared",
        )
        experiment_variant = _clean_experiment_label(
            req.experiment_variant,
            "manual-plan" if req.motion_plan is not None else ("planner-api" if req.planner_enabled else "baseline"),
        )
        experiment_group = _clean_experiment_label(req.experiment_group, task_id)
        _update_task(
            task_id,
            original_prompt=str(prompt_context["original_prompt"]),
            translated_prompt=str(prompt_context["translated_prompt"]),
            translation_status=str(prompt_context["translation_status"]),
            translation_error=str(prompt_context["translation_error"]),
            baseline_prompt=str(prompt_context["baseline_prompt"]),
            final_prompt=final_prompt,
            seed=req.seed,
            experiment_group=experiment_group,
            experiment_variant=experiment_variant,
            planner_status=str(prompt_context["planner_status"]),
            planner_provider=str(prompt_context["planner_provider"]),
            planner_model=str(prompt_context["planner_model"]),
            planner_error=str(prompt_context["planner_error"]),
            motion_plan=prompt_context.get("motion_plan"),
            experiment_manifest_path=str(manifest_path),
        )
        if req.translation_required and prompt_context["translation_status"] not in {
            "succeeded",
            "not-needed",
        }:
            raise RuntimeError(
                "Required prompt translation failed: "
                + str(prompt_context["translation_error"] or prompt_context["translation_status"])
            )

        _update_task(task_id, status="running", message="Generating motion...", progress=30)

        output_path = task_root / "output" / f"{task_id}.mp4"

        try:
            render_result = service.generate(
                final_prompt,
                output_path,
                num_samples=req.num_samples,
                motion_frames=req.motion_frames,
                cfg_weight=req.cfg_weight,
                render_preview=smpl_requested,
                seed=req.seed,
                candidate_audit=req.candidate_audit,
            )
        finally:
            if _env_flag("INTERGEN_RELEASE_GPU_WHEN_IDLE", False):
                service.unload()

        if smpl_requested and not output_path.exists():
            raise FileNotFoundError(f"Expected output not found: {output_path}")

        task_message = (render_result or {}).get("message", "Task completed")
        fallback_reason = (render_result or {}).get("fallback_reason", "")
        stderr_tail = _tail_text(fallback_reason) if fallback_reason else ""
        raw_joints_files = list((render_result or {}).get("raw_joints_files") or [])
        generated_frames = int((render_result or {}).get("generated_frames") or 0) or None
        generated_fps = int((render_result or {}).get("fps") or os.getenv("INTERGEN_FPS", "30"))
        duration_seconds = (
            round(generated_frames / float(max(generated_fps, 1)), 3)
            if generated_frames is not None
            else None
        )
        generation_summary = {
            "seed": int((render_result or {}).get("seed") or req.seed),
            "selected_sample": int((render_result or {}).get("selected_sample") or 0) or None,
            "num_samples": int((render_result or {}).get("num_samples") or 0) or None,
            "generated_frames": generated_frames,
            "fps": generated_fps,
            "duration_seconds": duration_seconds,
            "candidate_summaries": list((render_result or {}).get("candidate_summaries") or []),
        }
        candidate_audit_manifest_path: Optional[Path] = None
        if req.candidate_audit:
            candidate_audit_manifest_path = write_candidate_audit_manifest(
                task_root / "output" / "candidate_audit.json",
                task_id=task_id,
                prompt=final_prompt,
                candidate_summaries=generation_summary["candidate_summaries"],
                selected_sample=generation_summary["selected_sample"],
                motion_plan=prompt_context.get("motion_plan"),
                experiment_group=experiment_group,
                experiment_variant=experiment_variant,
            )
            generation_summary["candidate_audit"] = {
                "enabled": True,
                "status": "awaiting-human-review",
                "manifest_path": str(candidate_audit_manifest_path),
            }
        manifest_path = _write_experiment_manifest(
            task_root,
            task_id,
            req,
            prompt_context,
            status="motion-generated",
            generation=generation_summary,
        )

        _run_intergen_retarget_if_requested(
            task_id=task_id,
            task_root=task_root,
            output_path=output_path,
            raw_joints_files=raw_joints_files,
            req=req,
            motion_prompt=final_prompt,
        )

        if not smpl_requested:
            if output_path.exists():
                output_path.unlink()
            candidate_dir = output_path.parent / "candidates"
            if candidate_dir.is_dir():
                for candidate_mp4 in candidate_dir.glob("*.mp4"):
                    candidate_mp4.unlink()

        with _task_lock:
            current_task = _tasks.get(task_id)
        retarget_succeeded = bool(
            current_task
            and current_task.retarget_status == "succeeded"
            and (current_task.output_retarget_mp4_path or current_task.output_retarget_path)
        )
        if retarget_requested and not retarget_succeeded and not smpl_requested:
            reason = current_task.retarget_message if current_task else "Retarget state unavailable"
            raise RuntimeError(f"Requested retarget skin was not generated: {reason}")
        if retarget_requested and not retarget_succeeded:
            task_message = f"{task_message} Retarget output failed; SMPL output is available."

        manifest_path = _write_experiment_manifest(
            task_root,
            task_id,
            req,
            prompt_context,
            status="succeeded",
            generation=generation_summary,
        )
        _update_task(
            task_id,
            status="succeeded",
            message=task_message,
            progress=100,
            original_prompt=str(prompt_context["original_prompt"]),
            translated_prompt=str(prompt_context["translated_prompt"]),
            translation_status=str(prompt_context["translation_status"]),
            translation_error=str(prompt_context["translation_error"]),
            baseline_prompt=str(prompt_context["baseline_prompt"]),
            final_prompt=final_prompt,
            seed=int((render_result or {}).get("seed") or req.seed),
            planner_status=str(prompt_context["planner_status"]),
            planner_provider=str(prompt_context["planner_provider"]),
            planner_model=str(prompt_context["planner_model"]),
            planner_error=str(prompt_context["planner_error"]),
            motion_plan=prompt_context.get("motion_plan"),
            selected_sample=int((render_result or {}).get("selected_sample") or 0) or None,
            num_samples=int((render_result or {}).get("num_samples") or 0) or None,
            candidate_summaries=list((render_result or {}).get("candidate_summaries") or []),
            candidate_audit=bool(req.candidate_audit),
            candidate_audit_manifest_path=(
                str(candidate_audit_manifest_path) if candidate_audit_manifest_path else None
            ),
            experiment_manifest_path=str(manifest_path),
            output_mp4_path=str(output_path.resolve()) if smpl_requested else None,
            generated_frames=generated_frames,
            fps=generated_fps,
            duration_seconds=duration_seconds,
            stderr_tail=stderr_tail,
        )
    except Exception as exc:
        manifest_path = _write_experiment_manifest(
            task_root,
            task_id,
            req,
            prompt_context,
            status="failed",
            error=traceback.format_exc(),
        )
        _update_task(
            task_id,
            status="failed",
            message=str(exc),
            progress=100,
            seed=req.seed,
            original_prompt=str(prompt_context.get("original_prompt") or ""),
            translated_prompt=str(prompt_context.get("translated_prompt") or ""),
            translation_status=str(prompt_context.get("translation_status") or "failed"),
            translation_error=str(prompt_context.get("translation_error") or ""),
            baseline_prompt=str(prompt_context.get("baseline_prompt") or ""),
            final_prompt=str(prompt_context.get("final_prompt") or ""),
            planner_status=str(prompt_context.get("planner_status") or "failed"),
            planner_provider=str(prompt_context.get("planner_provider") or ""),
            planner_model=str(prompt_context.get("planner_model") or ""),
            planner_error=str(prompt_context.get("planner_error") or ""),
            motion_plan=prompt_context.get("motion_plan"),
            candidate_audit=bool(req.candidate_audit),
            experiment_manifest_path=str(manifest_path),
            stderr_tail=_tail_text(traceback.format_exc()),
        )


def _existing_task_motion_files(task_id: str) -> Tuple[Path, Path, List[str]]:
    if Path(task_id).name != task_id or not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
        raise ValueError("Invalid task id")
    task_root = (DEFAULT_TASK_ROOT / task_id).resolve()
    if task_root.parent != DEFAULT_TASK_ROOT.resolve() or not task_root.is_dir():
        raise FileNotFoundError(f"Task directory not found: {task_id}")

    output_path = task_root / "output" / f"{task_id}.mp4"
    if not output_path.is_file():
        raise FileNotFoundError(f"SMPL preview not found: {output_path}")

    def _person_number(path: Path) -> int:
        match = re.search(r"_person(\d+)_joints22\.npy$", path.name)
        return int(match.group(1)) if match else 999

    raw_dir = task_root / "output" / "raw"
    raw_paths = sorted(raw_dir.glob(f"{task_id}_person*_joints22.npy"), key=_person_number)
    if len(raw_paths) < 2:
        raise FileNotFoundError(f"Expected two raw joints files under: {raw_dir}")
    return task_root, output_path, [str(path.resolve()) for path in raw_paths[:2]]


def _run_retry_retarget_task(task_id: str, req: RetryRetargetRequest) -> None:
    try:
        _update_task(
            task_id,
            status="running",
            message="Retrying retarget from existing joints...",
            progress=70,
            retarget_status="running",
            retarget_message="",
        )
        task_root, output_path, raw_joints_files = _existing_task_motion_files(task_id)
        retry_frame_counts = [
            int(np.load(path, mmap_mode="r", allow_pickle=False).shape[0])
            for path in raw_joints_files
        ]
        retry_frames = min(retry_frame_counts)
        retry_fps = int(os.getenv("INTERGEN_FPS", "30"))
        _update_task(
            task_id,
            generated_frames=retry_frames,
            fps=retry_fps,
            duration_seconds=round(retry_frames / float(max(retry_fps, 1)), 3),
        )
        with _task_lock:
            current_task = _tasks.get(task_id)
        retry_motion_prompt = (req.motion_prompt or (current_task.final_prompt if current_task else "")).strip()
        if not retry_motion_prompt:
            previous_manifest = task_root / "retarget" / "retarget_manifest.json"
            if previous_manifest.is_file():
                try:
                    previous_data = json.loads(previous_manifest.read_text(encoding="utf-8"))
                    retry_motion_prompt = str(previous_data.get("motion_prompt") or "").strip()
                except Exception:
                    retry_motion_prompt = ""
        retarget_req = GenerateMotionRequest(
            text="Retry existing InterGen motion retarget",
            skin_id=req.skin_id,
            retarget_enabled=True,
            retarget_strict=req.retarget_strict,
            target_fbx=req.target_fbx,
            mapping_file=req.mapping_file,
            blender_executable=req.blender_executable,
            retarget_script=req.retarget_script,
        )
        _run_intergen_retarget_if_requested(
            task_id=task_id,
            task_root=task_root,
            output_path=output_path,
            raw_joints_files=raw_joints_files,
            req=retarget_req,
            motion_prompt=retry_motion_prompt,
        )
        with _task_lock:
            current = _tasks.get(task_id)
        retarget_status = current.retarget_status if current else "failed"
        retarget_message = current.retarget_message if current else "Retarget retry state unavailable"
        if retarget_status != "succeeded":
            _update_task(
                task_id,
                status="succeeded",
                message="SMPL preview preserved; retarget retry did not complete",
                progress=100,
                output_mp4_path=str(output_path.resolve()),
            )
            return
        _update_task(
            task_id,
            status="succeeded",
            message="Retarget retry completed",
            progress=100,
            output_mp4_path=str(output_path.resolve()),
            retarget_message=retarget_message,
        )
    except Exception as exc:
        _update_task(
            task_id,
            status="failed" if req.retarget_strict else "succeeded",
            message="Retarget retry failed",
            progress=100,
            retarget_status="failed",
            retarget_message=str(exc),
            stderr_tail=_tail_text(traceback.format_exc()),
        )


@app.on_event("startup")
def _on_startup() -> None:
    service.load()
    if _env_flag("INTERGEN_RELEASE_GPU_WHEN_IDLE", False):
        service.unload()


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


@app.get("/v1/intergen/skins")
def get_supported_skins() -> Dict[str, object]:
    try:
        return public_skin_catalog(PROJECT_ROOT)
    except SkinCatalogError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/v1/intergen/tasks/generate", response_model=TaskInfo)
def create_generate_task(req: GenerateMotionRequest) -> TaskInfo:
    skin_profiles = _validate_request_skins(req)
    if req.candidate_audit and not any(
        str(profile.get("output_kind") or "") == "smpl"
        for profile in skin_profiles
    ):
        raise HTTPException(
            status_code=422,
            detail="candidate_audit requires an SMPL preview output so every candidate can be reviewed",
        )
    requested_skin_ids = [str(profile["id"]) for profile in skin_profiles]
    person_skin_ids = _requested_person_skin_ids(req)
    task_id = str(uuid.uuid4())
    req.seed = _resolved_seed(req.seed)
    experiment_variant = _clean_experiment_label(
        req.experiment_variant,
        "manual-plan" if req.motion_plan is not None else ("planner-api" if req.planner_enabled else "baseline"),
    )
    experiment_group = _clean_experiment_label(req.experiment_group, task_id)
    now = _utc_now()
    task = TaskInfo(
        task_id=task_id,
        status="queued",
        created_at=now,
        updated_at=now,
        skin_id=requested_skin_ids[0],
        requested_skin_ids=requested_skin_ids,
        person_skin_ids=person_skin_ids,
        message="Task queued",
        original_prompt=_sanitize_prompt_text(req.text),
        translation_status=("queued" if _contains_cjk(req.text) else "not-needed"),
        seed=req.seed,
        experiment_group=experiment_group,
        experiment_variant=experiment_variant,
        planner_status=("manual" if req.motion_plan is not None else ("queued" if req.planner_enabled else "disabled")),
        planner_model=("manual" if req.motion_plan is not None else (req.planner_model or "")),
        motion_plan=_model_dict(req.motion_plan),
        candidate_audit=bool(req.candidate_audit),
    )
    with _task_lock:
        _tasks[task_id] = task
        _persist_task(task)

    executor.submit(_run_generate_task, task_id, req)
    return task


@app.post("/v1/intergen/tasks/{task_id}/retry-retarget", response_model=TaskInfo)
def retry_task_retarget(task_id: str, req: RetryRetargetRequest) -> TaskInfo:
    skin_profile = _validate_request_skin(req, require_retarget=True)
    try:
        _, output_path, _ = _existing_task_motion_files(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    with _task_lock:
        existing = _tasks.get(task_id)
        now = _utc_now()
        task = TaskInfo(
            task_id=task_id,
            status="queued",
            created_at=existing.created_at if existing else now,
            updated_at=now,
            skin_id=str(skin_profile["id"]),
            requested_skin_ids=[str(skin_profile["id"])],
            message="Retarget retry queued",
            progress=65,
            original_prompt=existing.original_prompt if existing else "",
            translated_prompt=existing.translated_prompt if existing else "",
            translation_status=existing.translation_status if existing else "not-started",
            translation_error=existing.translation_error if existing else "",
            baseline_prompt=existing.baseline_prompt if existing else "",
            final_prompt=existing.final_prompt if existing else "",
            seed=existing.seed if existing else None,
            experiment_group=existing.experiment_group if existing else "",
            experiment_variant=existing.experiment_variant if existing else "baseline",
            planner_status=existing.planner_status if existing else "disabled",
            planner_provider=existing.planner_provider if existing else "",
            planner_model=existing.planner_model if existing else "",
            planner_error=existing.planner_error if existing else "",
            motion_plan=existing.motion_plan if existing else None,
            selected_sample=existing.selected_sample if existing else None,
            num_samples=existing.num_samples if existing else None,
            candidate_summaries=existing.candidate_summaries if existing else [],
            candidate_audit=existing.candidate_audit if existing else False,
            candidate_audit_manifest_path=(
                existing.candidate_audit_manifest_path if existing else None
            ),
            experiment_manifest_path=existing.experiment_manifest_path if existing else None,
            output_mp4_path=str(output_path.resolve()),
            output_bvh_path=existing.output_bvh_path if existing else None,
            output_retarget_path=None,
            output_retarget_mp4_path=None,
            generated_frames=existing.generated_frames if existing else None,
            fps=existing.fps if existing else None,
            duration_seconds=existing.duration_seconds if existing else None,
            retarget_status="queued",
            retarget_message="",
        )
        _tasks[task_id] = task
        _persist_task(task)

    executor.submit(_run_retry_retarget_task, task_id, req)
    return task


@app.get("/v1/intergen/tasks/{task_id}", response_model=TaskInfo)
def get_task(task_id: str) -> TaskInfo:
    with _task_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _task_owned_file(task_id: str, raw_path: str) -> Path:
    task_root = (DEFAULT_TASK_ROOT / task_id).resolve()
    path = Path(raw_path).resolve()
    try:
        path.relative_to(task_root)
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="Task artifact path escaped the task directory") from exc
    return path


def _candidate_audit_payload(task: TaskInfo) -> Tuple[Path, Dict[str, object]]:
    # 【实验功能，未应用于实际生产逻辑链路】审计读取的是生成后的旁路清单，
    # 人工审核结果不会回写 selected_sample，也不会替换已经生成的最终视频。
    if not task.candidate_audit or not task.candidate_audit_manifest_path:
        raise HTTPException(status_code=404, detail="Candidate audit is not enabled for this task")
    manifest_path = _task_owned_file(task.task_id, task.candidate_audit_manifest_path)
    if not manifest_path.is_file():
        raise HTTPException(status_code=410, detail="Candidate audit manifest no longer exists")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Candidate audit manifest is invalid: {exc}") from exc
    return manifest_path, payload


@app.get("/v1/intergen/tasks/{task_id}/candidate-audit")
def get_candidate_audit(task_id: str) -> Dict[str, object]:
    with _task_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    _, payload = _candidate_audit_payload(task)
    return payload


@app.post("/v1/intergen/tasks/{task_id}/candidate-audit/candidates/{candidate_index}/review")
def review_candidate(
    task_id: str,
    candidate_index: int,
    review: CandidateReviewRequest,
) -> Dict[str, object]:
    with _task_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    manifest_path, payload = _candidate_audit_payload(task)
    candidates = list(payload.get("candidates") or [])
    candidate = next(
        (item for item in candidates if int(item.get("candidate_index") or 0) == candidate_index),
        None,
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found in audit manifest")

    review_fields = {
        "mutual_facing": bool(review.mutual_facing),
        "racket_swing_proxy": bool(review.racket_swing_proxy),
        "receiver_ready_and_reacts": bool(review.receiver_ready_and_reacts),
        "role_consistency": bool(review.role_consistency),
        "badminton_semantic_match": bool(review.badminton_semantic_match),
    }
    candidate["human_review"] = {
        "review_status": "completed",
        **review_fields,
        "semantic_pass": all(review_fields.values()),
        "reviewer": review.reviewer.strip(),
        "notes": review.notes.strip(),
        "reviewed_at": _utc_now(),
    }
    reviewed_count = sum(
        1
        for item in candidates
        if dict(item.get("human_review") or {}).get("review_status") == "completed"
    )
    pass_count = sum(
        1
        for item in candidates
        if dict(item.get("human_review") or {}).get("semantic_pass") is True
    )
    summary = dict(payload.get("summary") or {})
    summary["human_reviewed_count"] = reviewed_count
    summary["semantic_pass_count"] = pass_count
    if pass_count > 0:
        summary["gate_decision"] = "candidate-qualified-by-motion-quality-evaluator"
        payload["status"] = "candidate-found"
    elif reviewed_count == len(candidates):
        summary["gate_decision"] = "no-qualifying-candidate-refine-planner-or-structured-prompt"
        payload["status"] = "no-qualifying-candidate"
    else:
        summary["gate_decision"] = "pending-human-review"
        payload["status"] = "awaiting-human-review"
    payload["summary"] = summary
    payload["updated_at"] = _utc_now()
    temp_path = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(manifest_path)
    return {
        "task_id": task_id,
        "candidate_index": candidate_index,
        "human_review": candidate["human_review"],
        "summary": summary,
    }


@app.get("/v1/intergen/tasks/{task_id}/candidates/{candidate_index}/download")
def download_task_candidate(task_id: str, candidate_index: int) -> FileResponse:
    with _task_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task.candidate_audit:
        raise HTTPException(status_code=404, detail="Candidate audit is not enabled for this task")
    candidate = next(
        (
            item
            for item in task.candidate_summaries
            if int(item.get("candidate_index") or 0) == candidate_index
        ),
        None,
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    video_path = _task_owned_file(task_id, str(candidate.get("file_path") or ""))
    if not video_path.is_file():
        raise HTTPException(status_code=410, detail="Candidate video no longer exists")
    return FileResponse(path=str(video_path), media_type="video/mp4", filename=video_path.name)


def _selected_task_video_path(task: TaskInfo, skin_id: Optional[str]) -> Path:
    selected_skin_id = (skin_id or task.skin_id or "smpl").strip()
    if selected_skin_id != "smpl":
        retarget_path = task.output_retarget_mp4_path or task.output_retarget_path
        if task.retarget_status != "succeeded" or not retarget_path:
            raise HTTPException(status_code=409, detail="Selected skin result not completed")
        return Path(retarget_path)
    if task.status != "succeeded" or not task.output_mp4_path:
        raise HTTPException(status_code=409, detail="Task not completed")
    return Path(task.output_mp4_path)


@app.post("/v1/intergen/tasks/{task_id}/open-output-folder")
def open_task_output_folder(task_id: str, skin_id: Optional[str] = None) -> Dict[str, str]:
    with _task_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    mp4_path = _selected_task_video_path(task, skin_id)
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
        raise HTTPException(status_code=500, detail=f"Failed to open folder: {exc}") from exc
    return {"status": "ok", "opened_path": str(parent_dir)}


@app.post("/v1/intergen/tasks/{task_id}/open-output-player")
def open_task_output_player(task_id: str, skin_id: Optional[str] = None) -> Dict[str, str]:
    with _task_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    mp4_path = _selected_task_video_path(task, skin_id)
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
        raise HTTPException(status_code=500, detail=f"Failed to open player: {exc}") from exc
    return {"status": "ok", "opened_file": str(mp4_path)}


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


@app.get("/v1/intergen/tasks/{task_id}/download-retarget")
def download_task_retarget_result(task_id: str, as_attachment: bool = False) -> FileResponse:
    with _task_lock:
        task = _tasks.get(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    retarget_path = task.output_retarget_mp4_path or task.output_retarget_path
    if task.retarget_status != "succeeded" or not retarget_path:
        raise HTTPException(status_code=409, detail="Retarget result not completed")

    mp4_path = Path(retarget_path)
    if not mp4_path.exists():
        raise HTTPException(status_code=410, detail="Retarget output file no longer exists")

    disposition = "attachment" if as_attachment else "inline"
    return FileResponse(
        path=str(mp4_path),
        media_type="video/mp4",
        filename=mp4_path.name if as_attachment else None,
        headers={
            "Content-Disposition": f'{disposition}; filename="{mp4_path.name}"',
            "Accept-Ranges": "bytes",
        },
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
