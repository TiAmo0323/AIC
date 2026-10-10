"""Rejected uploads never create queued registry entries or dispatch workers."""
import asyncio
import io

import numpy as np
import pytest
from fastapi import HTTPException, UploadFile

from LODGE_api import lodge_async_api as api
from test_generation_retries import environment


def parameters(root, file):
    return dict(lodge_root=str(root), song_id="sample", python_executable=None, mode="smplx", device="0", fps=30,
        skin_ids=["robot"], skin_id=None, retarget_enabled=False, target_fbx=None, mapping_file=None,
        blender_executable=None, retarget_script=None, retarget_strict=False)


@pytest.mark.parametrize("case", ["fps", "mode", "empty", "extension", "size", "read_error"])
def test_audio_upload_rejects_before_queuing(environment, monkeypatch, case):
    root, tasks, calls = environment
    file = UploadFile(filename="audio.wav", file=io.BytesIO(b"audio"))
    kwargs = parameters(root, file)
    kwargs.update(audio_file=file, infer_args="")
    if case == "fps": kwargs["fps"] = 0
    elif case == "mode": kwargs["mode"] = "bad"
    elif case == "empty": file.file = io.BytesIO(b"")
    elif case == "extension": file.filename = "script.exe"
    elif case == "size": monkeypatch.setattr(api, "AUDIO_UPLOAD_LIMIT", 1)
    elif case == "read_error":
        async def fail(*args): raise OSError("Upload interrupted")
        monkeypatch.setattr(file, "read", fail)
    with pytest.raises(OSError if case == "read_error" else HTTPException) as error:
        asyncio.run(api.create_infer_from_audio_upload_task(**kwargs))
    if case != "read_error": assert error.value.status_code == (413 if case == "size" else 422)
    assert not api._tasks and not calls and not list(tasks.iterdir())


@pytest.mark.parametrize("operation", ["feature", "motion"])
@pytest.mark.parametrize("case", ["invalid", "object", "complex", "nan", "empty", "shape"])
def test_invalid_npy_upload_never_queues(environment, operation, case):
    root, tasks, calls = environment
    array = np.zeros((12, 35 if operation == "feature" else 139))
    if case == "object": array = np.array([[object()]], dtype=object)
    elif case == "complex": array = array.astype(complex)
    elif case == "nan": array[0, 0] = np.nan
    elif case == "empty": array = np.zeros((0, 139))
    elif case == "shape": array = np.zeros((2, 22, 3))
    buffer = io.BytesIO(); np.save(buffer, array)
    file = UploadFile(filename="motion.npy", file=io.BytesIO(b"bad" if case == "invalid" else buffer.getvalue()))
    kwargs = parameters(root, file); kwargs["npy_file"] = file
    handler = api.create_infer_from_feature_npy_upload_task if operation == "feature" else api.create_render_from_npy_upload_task
    if operation == "feature": kwargs["infer_args"] = ""
    with pytest.raises(HTTPException) as error:
        asyncio.run(handler(**kwargs))
    assert error.value.status_code == 422
    assert not api._tasks and not calls and not list(tasks.iterdir())


def test_queue_submission_failure_is_failed_instead_of_stuck(environment, monkeypatch):
    root, tasks, _ = environment
    def fail(*args): raise RuntimeError("executor stopped")
    monkeypatch.setattr(api, "_submit_request", fail)
    file = UploadFile(filename="audio.wav", file=io.BytesIO(b"audio"))
    task = asyncio.run(api.create_infer_from_audio_upload_task(**parameters(root, file), audio_file=file, infer_args=""))
    assert task.status == "failed"
    assert api._tasks[task.task_id].status == "failed"
    assert (tasks / task.task_id / "input/uploaded.wav").read_bytes() == b"audio"


def test_music_upload_rejects_motion_array(environment):
    root, tasks, calls = environment
    buffer = io.BytesIO(); np.save(buffer, np.zeros((12, 139)))
    file = UploadFile(filename="dance.npy", file=io.BytesIO(buffer.getvalue()))
    with pytest.raises(HTTPException) as error:
        asyncio.run(api.create_infer_from_feature_npy_upload_task(**parameters(root, file), npy_file=file, infer_args=""))
    assert error.value.status_code == 422 and "35" in error.value.detail
    assert not api._tasks and not calls and not list(tasks.iterdir())
