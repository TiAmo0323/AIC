"""Run production request/queue functions without importing the GPU model stack."""
import ast
from concurrent.futures import Future
from datetime import datetime
from pathlib import Path
import re
import secrets
import threading
from typing import Dict, List, Optional, Tuple
import uuid

import numpy as np
import pytest
from fastapi import HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from shared.runtime_checks import runtime_report
from shared.skin_catalog import SkinCatalogError, resolve_skins, skin_requires_retarget
from shared.task_manifest import write_task_manifest
from shared.task_requests import save_request, load_request
from shared.task_listing import task_page
from test_runtime_checks import runtime_fixture, write


@pytest.fixture
def api(tmp_path, monkeypatch):
    project, _, _, _ = runtime_fixture(tmp_path, monkeypatch)
    source = tmp_path / "intergen"
    configs = source / "configs"
    write(configs / "model.yaml", 'CHECKPOINT: checkpoint.ckpt')
    write(configs / "infer.yaml")
    write(source / "checkpoint.ckpt")
    write(tmp_path / "momask/visualization/joints2bvh.py")
    monkeypatch.delenv("INTERGEN_CONFIG_DIR", raising=False)
    monkeypatch.delenv("INTERGEN_FIXED_CHECKPOINT", raising=False)
    monkeypatch.delenv("INTERGEN_RETARGET_SCRIPT", raising=False)
    monkeypatch.setenv("INTERGEN_BLENDER_EXE", str(tmp_path / "blender.exe"))
    monkeypatch.setenv("INTERGEN_MOMASK_ROOT", str(tmp_path / "momask"))
    path = Path(__file__).resolve().parents[1] / "InterGen_api/intergen_async_api.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {"GenerateMotionRequest", "RetryRetargetRequest", "TaskInfo", "_utc_now", "_resolved_seed",
        "_model_dict", "_clean_experiment_label", "_persist_task", "_requested_person_skin_ids", "_resolve_person_skin_profiles",
        "_resolve_request_skins", "_validate_request_skins", "_resource_report", "_ensure_resources", "_update_task",
        "_contains_cjk", "_sanitize_prompt_text", "_existing_task_motion_files", "_run_retry_retarget_task",
        "create_generate_task", "retry_generation", "retry_task_retarget", "list_tasks", "_restore_task_artifacts", "download_task_result"}
    selected = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in functions]
    for node in selected:
        node.decorator_list = []
    namespace = {**globals(), "MotionPlan": dict, "PROJECT_ROOT": project, "MODEL_SOURCE_ROOT": source,
        "DEFAULT_TASK_ROOT": tmp_path / "tasks", "_tasks": {}, "_task_lock": threading.Lock(),
        "_run_generate_task": lambda *args: None, "_tail_text": lambda value: value}
    import os
    import traceback
    namespace.update(os=os, traceback=traceback)
    calls = []

    class Executor:
        def submit(self, *args):
            calls.append(args)
            return Future()

    namespace["executor"] = Executor()
    namespace["calls"] = calls
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def test_generation_retry_preserves_seed_and_pair_in_new_task(api):
    request = api["GenerateMotionRequest"](text="Two people dance.", person_a_skin_id="robot", person_b_skin_id="robot", seed=17)
    task = api["create_generate_task"](request)
    with pytest.raises(HTTPException) as error:
        api["retry_generation"](task.task_id)
    assert error.value.status_code == 409
    api["_update_task"](task.task_id, status="failed")
    replay = api["retry_generation"](task.task_id)
    assert replay.task_id != task.task_id and replay.seed == 17
    assert replay.person_skin_ids == ["robot", "robot"]
    assert load_request(api["DEFAULT_TASK_ROOT"], replay.task_id)["request"]["text"] == request.text
    assert len(api["calls"]) == 2


def test_render_retry_uses_existing_joints_without_smpl_preview(api):
    task_id = "11111111-1111-4111-8111-111111111111"
    folder = api["DEFAULT_TASK_ROOT"] / task_id / "output/raw"
    folder.mkdir(parents=True)
    for person in (1, 2):
        np.save(folder / f"{task_id}_person{person}_joints22.npy", np.zeros((20, 22, 3)))
    req = api["RetryRetargetRequest"](person_a_skin_id="robot", person_b_skin_id="robot", retarget_strict=True)
    task = api["retry_task_retarget"](task_id, req)
    assert task.person_skin_ids == ["robot", "robot"]
    assert task.output_mp4_path is None
    captured = []

    def render(**kwargs):
        captured.append(kwargs)
        api["_update_task"](task_id, retarget_status="succeeded")

    api["_run_intergen_retarget_if_requested"] = render
    api["_run_retry_retarget_task"](task_id, req)
    assert captured[0]["req"].person_a_skin_id == "robot"
    assert captured[0]["req"].person_b_skin_id == "robot"
    assert len(captured[0]["raw_joints_files"]) == 2
    assert api["_tasks"][task_id].status == "succeeded"
    assert api["_tasks"][task_id].output_mp4_path is None


def test_missing_second_person_asset_is_rejected_before_queueing(api):
    req = api["GenerateMotionRequest"](text="Two people dance.", person_a_skin_id="robot", person_b_skin_id="missing")
    with pytest.raises(HTTPException) as error:
        api["create_generate_task"](req)
    assert error.value.status_code == 422
    assert not api["calls"] and not api["_tasks"]


def test_intergen_listing_and_recovery_keep_render_failure(api):
    task = api["create_generate_task"](api["GenerateMotionRequest"](text="Two people dance.", person_a_skin_id="robot", person_b_skin_id="robot"))
    folder = api["DEFAULT_TASK_ROOT"] / task.task_id / "output"
    folder.mkdir(exist_ok=True)
    video = folder / f"{task.task_id}.mp4"
    video.write_bytes(b"preserved preview")
    api["_update_task"](task.task_id, status="failed", progress=85, message="renderer failed", retarget_status="failed", output_mp4_path=str(video))
    recovered = api["_restore_task_artifacts"](api["_tasks"][task.task_id])
    assert recovered.status == "failed" and recovered.message == "renderer failed"
    assert recovered.retarget_status == "failed"
    api["_tasks"][task.task_id] = recovered
    page = api["list_tasks"](status="failed", search="dance", offset=0, limit=10)
    assert page["total"] == 1 and page["items"][0]["preview_available"]
    assert page["items"][0]["retry_available"]
    response = api["download_task_result"](task.task_id)
    assert Path(response.path).read_bytes() == b"preserved preview"
