"""A report, comparison video and poster must refer to the same motion arrays."""
import json
import os
from concurrent.futures import Future
from pathlib import Path
import time

import numpy as np
import pytest
from fastapi import HTTPException

import motionlint.api as api


@pytest.fixture
def rendered(tmp_path, monkeypatch):
    task_id = "11111111-1111-4111-8111-111111111111"
    task = tmp_path / task_id
    folder = task / "motionlint"
    folder.mkdir(parents=True)
    (task / "input").mkdir()
    np.save(task / "input/raw.npy", np.zeros((5, 135)))
    np.save(folder / "repaired.npy", np.ones((5, 135)))
    (folder / "repair_report.json").write_text('{}')
    (folder / "original.mp4").write_bytes(b"before")
    (folder / "repaired.mp4").write_bytes(b"after")
    for kind in ("original", "repaired"):
        (folder / f"{kind}.png").write_bytes(b"poster")
    monkeypatch.setitem(api.TASK_ROOTS, "lodge", tmp_path)
    monkeypatch.setattr(api, "RENDER_JOBS", {})
    ref = api.TaskRef(source="lodge", task_id=task_id)
    state = {"status": "ready", "version": "render-v1", "inputs": api._render_inputs(ref, folder)}
    api._write_json(folder / "render_status.json", state)
    return ref, folder, state


def test_updated_arrays_invalidate_all_video_and_poster_endpoints(rendered):
    ref, folder, state = rendered
    assert api.comparison_render_status(ref.source, ref.task_id)["status"] == "ready"
    assert Path(api.comparison_video(ref.source, ref.task_id, "repaired").path).is_file()
    # Same timestamp and byte length: hashes must detect the change.
    array = folder / "repaired.npy"
    timestamp = array.stat().st_mtime_ns
    np.save(array, np.full((5, 135), 2.))
    os.utime(array, ns=(timestamp, timestamp))
    assert api.comparison_render_status(ref.source, ref.task_id)["status"] == "failed"
    assert api._stage_video_path(ref, "repaired") is None
    for kind in ("original", "repaired"):
        for handler in (api.comparison_video, api.comparison_poster):
            with pytest.raises(HTTPException) as error:
                handler(ref.source, ref.task_id, kind)
            assert error.value.status_code == 404


def test_legacy_video_freshness_is_also_enforced(rendered):
    ref, folder, _ = rendered
    api._write_json(folder / "render_status.json", {"status": "ready"})
    old = time.time() - 60
    os.utime(folder / "repaired.mp4", (old, old))
    assert api.comparison_render_status(ref.source, ref.task_id)["status"] == "failed"


def test_interrupted_render_can_retry_without_repairing_again(rendered, monkeypatch):
    ref, folder, state = rendered
    api._write_json(folder / "render_status.json", {**state, "status": "running"})
    assert api.comparison_render_status(ref.source, ref.task_id)["status"] == "failed"
    assert json.loads((folder / "render_status.json").read_text(encoding="utf-8"))["status"] == "failed"
    before = (folder / "repaired.npy").read_bytes()
    calls = []

    class Executor:
        def submit(self, *args):
            calls.append(args)
            return Future()

    monkeypatch.setattr(api, "RENDER_EXECUTOR", Executor())
    assert api.retry_comparison_render(ref.source, ref.task_id)["status"] == "queued"
    assert api.comparison_render_status(ref.source, ref.task_id)["status"] == "queued"
    queued = json.loads((folder / "render_status.json").read_text(encoding="utf-8"))
    assert queued["inputs"] == state["inputs"] and queued["version"] != state["version"]
    assert api.retry_comparison_render(ref.source, ref.task_id)["status"] == "running"
    assert len(calls) == 1 and (folder / "repaired.npy").read_bytes() == before
    with pytest.raises(HTTPException) as error:
        api.repair_task(ref)
    assert error.value.status_code == 409


def test_render_worker_refuses_publish_if_inputs_change(rendered, monkeypatch):
    ref, folder, state = rendered
    monkeypatch.setattr(api.shutil, "which", lambda *args: "ffmpeg")

    def run(*args, **kwargs):
        np.save(folder / "repaired.npy", np.full((5, 135), 3.))

    monkeypatch.setattr(api.subprocess, "run", run)
    api._render_comparison(ref, folder, state)
    status = api.comparison_render_status(ref.source, ref.task_id)
    assert status["status"] == "failed" and "数据发生变化" in status["error"]
