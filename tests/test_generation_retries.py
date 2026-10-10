"""Retry recorded inputs without running models or overwriting the source task."""
import asyncio
import io
import json
import numpy as np
from concurrent.futures import Future

import pytest
from fastapi import HTTPException, UploadFile
from LODGE_api import lodge_async_api as api
from shared.task_requests import load_request
from test_runtime_checks import runtime_fixture


@pytest.fixture
def environment(tmp_path, monkeypatch):
    project, root, fbx, mapping = runtime_fixture(tmp_path, monkeypatch)
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    monkeypatch.setattr(api, "PROJECT_ROOT", project)
    monkeypatch.setattr(api, "DEFAULT_TASK_ROOT", tasks)
    monkeypatch.setattr(api, "_tasks", {})
    calls = []

    class Executor:
        def submit(self, *args, **kwargs):
            calls.append((args, kwargs))
            return Future()

    monkeypatch.setattr(api, "executor", Executor())
    return root, tasks, calls


def test_missing_resource_is_rejected_before_queueing(environment):
    root, tasks, calls = environment
    req = api.InferFromAudioRequest(lodge_root=str(root), song_id="test", audio_path="input.wav", skin_ids=["missing"])
    with pytest.raises(HTTPException) as error:
        api.create_infer_from_audio_task(req)
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "resources_unavailable"
    assert not list(tasks.iterdir()) and not calls


def test_uploaded_inputs_can_be_retried_after_restart(environment, monkeypatch):
    from shared.task_manifest import restore_task_manifests
    root, tasks, calls = environment
    upload = UploadFile(filename="beat.wav", file=io.BytesIO(b"recorded input"))
    # Exercise the actual multipart handler; optional Form defaults are explicit.
    task = asyncio.run(api.create_infer_from_audio_upload_task(lodge_root=str(root), song_id="beat", audio_file=upload,
        python_executable=None, mode="smplx", device="0", fps=30, infer_args="", skin_ids=["robot"], skin_id=None,
        retarget_enabled=False, target_fbx=None, mapping_file=None, blender_executable=None, retarget_script=None, retarget_strict=False))
    with pytest.raises(HTTPException) as error:
        api.retry_task(task.task_id)
    assert error.value.status_code == 409
    assert len(calls) == 1
    saved = load_request(tasks, task.task_id)
    original = tasks / task.task_id / "input/uploaded.wav"
    assert original.read_bytes() == b"recorded input"
    monkeypatch.setattr(api, "_tasks", restore_task_manifests(tasks, api.TaskInfo))
    replay = api.retry_task(task.task_id)
    assert replay.task_id != task.task_id
    assert original.read_bytes() == b"recorded input"
    assert load_request(tasks, replay.task_id)["request"] == saved["request"]
    assert calls[-1][0][2].audio_path == str(original)


def test_retry_requires_existing_original_input(environment):
    root, tasks, calls = environment
    audio = root / "beat.wav"
    audio.write_bytes(b"input")
    task = api.create_infer_from_audio_task(api.InferFromAudioRequest(lodge_root=str(root), song_id="beat", audio_path=str(audio), skin_ids=["robot"]))
    api._update_task(task.task_id, status="failed")
    audio.unlink()
    with pytest.raises(HTTPException) as error:
        api.retry_task(task.task_id)
    assert error.value.status_code == 422
    assert len(calls) == 1


def test_legacy_task_reports_missing_retry_parameters(environment):
    root, tasks, calls = environment
    task_id = "11111111-1111-4111-8111-111111111111"
    task = api.TaskInfo(task_id=task_id, status="failed", created_at="now", updated_at="now")
    api._tasks[task_id] = task
    api._persist_task(task)
    with pytest.raises(HTTPException) as error:
        api.retry_task(task_id)
    assert error.value.status_code == 422
    assert "历史任务" in error.value.detail
    assert not calls


@pytest.mark.parametrize("operation", ["feature", "motion"])
def test_uploaded_npy_retry_preserves_worker_inputs(environment, operation):
    root, tasks, calls = environment
    contents = io.BytesIO()
    np.save(contents, np.zeros((12, 35 if operation == "feature" else 139)))
    common = dict(lodge_root=str(root), song_id="motion", npy_file=UploadFile(filename="motion.npy", file=io.BytesIO(contents.getvalue())),
        python_executable=None, mode="smplx", device="0", fps=24, skin_ids=["robot"], skin_id=None,
        retarget_enabled=False, target_fbx=None, mapping_file=None, blender_executable=None, retarget_script=None, retarget_strict=True)
    if operation == "feature":
        task = asyncio.run(api.create_infer_from_feature_npy_upload_task(**common, infer_args="--foo,bar"))
    else:
        # Rendering saved motion remains available when inference weights are gone.
        (root / "exp/Global_Module/FineDance_Global/checkpoints/epoch=2999.ckpt").unlink()
        task = asyncio.run(api.create_render_from_npy_upload_task(**common))
    api._update_task(task.task_id, status="failed")
    original = load_request(tasks, task.task_id)
    replay = api.retry_task(task.task_id)
    assert replay.task_id != task.task_id
    assert load_request(tasks, replay.task_id) == original
    assert len(calls) == 2
    if operation == "motion":
        assert calls[-1][1]["uploaded_npy_path"] == original["request"]["uploaded_npy_path"]
        assert calls[-1][1]["fps"] == 24
        assert calls[-1][1]["retarget_options"]["strict"]
    else:
        assert calls[-1][0][2].feature_npy_path == original["request"]["feature_npy_path"]
        assert calls[-1][0][2].infer_args == ["--foo", "bar"]


def test_http_preflight_upload_and_retry_contract(environment):
    import http.client
    import socket
    import threading
    import time
    import uvicorn

    root, tasks, calls = environment
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(api.app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()

    def request(method, path, payload=None, content_type="application/json"):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        body = json.dumps(payload).encode() if isinstance(payload, dict) else payload
        try:
            connection.request(method, path, body, {"Content-Type": content_type})
            response = connection.getresponse()
            contents = response.read()
            return response.status, json.loads(contents) if "application/json" in response.getheader("content-type", "") else contents
        finally:
            connection.close()

    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        status, catalog = request("GET", "/v1/lodge/skins")
        assert status == 200
        assert not next(skin for skin in catalog["skins"] if skin["id"] == "missing")["available"]
        payload = {"lodge_root": str(root), "skin_ids": ["robot"]}
        status, report = request("POST", "/v1/lodge/preflight", payload)
        assert status == 200 and report["ready"]
        payload["skin_ids"] = ["missing"]
        status, report = request("POST", "/v1/lodge/preflight", payload)
        assert status == 200 and not report["ready"]
        status, error = request("POST", "/v1/lodge/tasks/infer-from-audio", {**payload, "song_id": "beat", "audio_path": "input.wav"})
        assert status == 422 and error["detail"]["code"] == "resources_unavailable"
        assert not calls and not list(tasks.iterdir())

        boundary = "aic-http-test"
        fields = {"lodge_root": str(root), "song_id": "beat", "skin_ids": "robot", "retarget_strict": "true"}
        pieces = [f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode() for key, value in fields.items()]
        pieces.append(f'--{boundary}\r\nContent-Disposition: form-data; name="audio_file"; filename="beat.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + b"saved beat\r\n")
        pieces.append(f"--{boundary}--\r\n".encode())
        status, task = request("POST", "/v1/lodge/tasks/infer-from-audio-upload", b"".join(pieces), f"multipart/form-data; boundary={boundary}")
        assert status == 200 and task["requested_skin_ids"] == ["robot"]
        status, page = request("GET", "/v1/lodge/tasks?status=active&search=beat&limit=1")
        assert status == 200 and page["total"] == 1 and len(page["items"]) == 1
        assert not page["items"][0]["retry_available"]
        for query in ("limit=0", "offset=-1", "status=unknown"):
            status, _ = request("GET", f"/v1/lodge/tasks?{query}")
            assert status == 422
        status, _ = request("POST", f'/v1/lodge/tasks/{task["task_id"]}/retry')
        assert status == 409 and len(calls) == 1
        api._update_task(task["task_id"], status="failed")
        preview = tasks / task["task_id"] / "preview.mp4"
        preview.write_bytes(b"preserved video artifact")
        api._update_task(task["task_id"], output_mp4_path=str(preview), message="renderer failed", retarget_status="failed")
        status, page = request("GET", "/v1/lodge/tasks?status=failed&search=beat")
        assert status == 200 and page["items"][0]["preview_available"] and page["items"][0]["retry_available"]
        assert page["items"][0]["message"] == "renderer failed"
        status, contents = request("GET", f'/v1/lodge/tasks/{task["task_id"]}/download')
        assert status == 200 and contents == b"preserved video artifact"
        status, replay = request("POST", f'/v1/lodge/tasks/{task["task_id"]}/retry')
        assert status == 200 and replay["task_id"] != task["task_id"] and len(calls) == 2
        assert (tasks / task["task_id"] / "input/uploaded.wav").read_bytes() == b"saved beat"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()
