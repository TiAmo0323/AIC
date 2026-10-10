"""Uploaded motions retain their conventions, reports, actor order and raw bytes."""
import asyncio
import io
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException, UploadFile

import motionlint.api as api
from motionlint.adapters.bvh_adapter import load_bvh
from motionlint.benchmark.fixtures import standing
from LODGE_api.lodge2bvh import BVH_NAMES, write_bvh


@pytest.fixture
def import_root(tmp_path, monkeypatch):
    root = tmp_path / "imports"
    monkeypatch.setitem(api.TASK_ROOTS, "import", root)
    monkeypatch.setitem(api.TASK_ROOTS, "intergen", tmp_path / "no_intergen")
    monkeypatch.setitem(api.TASK_ROOTS, "lodge", tmp_path / "no_lodge")
    monkeypatch.setattr(api, "REPO_ROOT", tmp_path)
    return root


def npy_bytes(array):
    contents = io.BytesIO()
    np.save(contents, array)
    return contents.getvalue()


def upload(name, contents):
    return UploadFile(filename=name, file=io.BytesIO(contents))


def submit(files, **options):
    return asyncio.run(api.import_motion(files=files, fps=options.get("fps", 30), unit_scale=options.get("unit_scale", 1),
        up_axis=options.get("up_axis", 1), joint_mapping=options.get("joint_mapping", "{}")))


def test_joint_pair_import_preserves_order_bytes_and_exact_preview_frame(import_root):
    first = standing(frames=24)
    first[7:, :, 0] += .3
    second = first + [2, 0, 0]
    raw = [npy_bytes(first), npy_bytes(second)]
    result = submit([upload("人物A.npy", raw[0]), upload("人物B.npy", raw[1])], fps=24)
    task_id = result["task"]["task_id"]
    assert result["import"]["fps"] == 24 and result["import"]["actor_count"] == 2
    assert result["report"]["metadata"]["inspection_stage"] == "raw"
    for actor, original in enumerate(raw, 1):
        assert (import_root / task_id / f"actor{actor}.npy").read_bytes() == original
    frame = api.imported_preview(task_id, start=7, count=1)
    np.testing.assert_allclose(frame["positions"][0][0], first[7], atol=1e-6)
    np.testing.assert_allclose(frame["positions"][0][1], second[7], atol=1e-6)
    assert frame["start"] == 7 and frame["parents"][0] == -1
    rechecked = api.inspect_stage(api.StageRequest(source="import", task_id=task_id))
    assert rechecked["report"]["metadata"]["input_sha256"] == result["report"]["metadata"]["input_sha256"]
    assert api.list_tasks()[0]["title"] == "人物A.npy + 人物B.npy"
    bundle = json.loads(api.imported_report(task_id).body)
    assert bundle["import"]["files"] == ["人物A.npy", "人物B.npy"]
    assert bundle["gate"]["status"] == result["gate"]["status"]
    assert len(bundle["report"]["tests"]) == 6


def test_lodge_import_is_cpu_only_and_not_music_features(import_root, monkeypatch):
    import motionlint.adapters.lodge_adapter as adapter
    monkeypatch.setattr(adapter, "resolve_model", lambda path: None)
    raw = np.zeros((20, 139))
    raw[:, :4] = 1
    raw[:, 7:] = np.tile([1, 0, 0, 0, 1, 0], 22)
    result = submit([upload("dance.npy", npy_bytes(raw))])
    assert result["import"]["format"] == "lodge_npy"
    assert result["import"]["geometry_source"] == "fixed_bvh_proxy"
    assert result["import"]["warnings"]
    assert result["report"]["metadata"]["frame_count"] == 20
    def changed_model(path):
        raise AssertionError("Rechecking must use the frozen geometry without reloading a model")
    monkeypatch.setattr(adapter, "resolve_model", changed_model)
    rechecked = api.inspect_stage(api.StageRequest(**result["task"]))
    assert rechecked["report"]["metadata"]["evaluated_array_sha256"] == result["report"]["metadata"]["evaluated_array_sha256"]


def test_bvh_uses_file_fps_scale_axis_and_mapping(import_root, tmp_path):
    source = tmp_path / "motion.bvh"
    write_bvh(source, np.tile([0, 0, 100.], (12, 1)), np.zeros((12, len(BVH_NAMES), 3)), fps=60)
    original = source.read_bytes()
    result = submit([upload("motion.BVH", original)], fps=30, unit_scale=.01, up_axis=2)
    assert result["import"]["fps"] == pytest.approx(60, abs=.002) and result["import"]["up_axis"] == 2
    assert result["import"]["unit_scale"] == .01
    expected = load_bvh(source, unit_scale=.01, up_axis=2)
    frame = api.imported_preview(result["task"]["task_id"], start=3, count=2)
    np.testing.assert_allclose(frame["positions"], expected.positions[3:5], atol=1e-6)
    assert (import_root / result["task"]["task_id"] / "actor1.bvh").read_bytes() == original
    unknown_feet = original.decode().replace("LeftFoot", "left_ankle").replace("RightFoot", "right_ankle").replace("LeftToe", "left_toe").replace("RightToe", "right_toe").encode()
    missing = submit([upload("custom.bvh", unknown_feet)])
    assert any("足部" in warning for warning in missing["import"]["warnings"])
    mapping = json.dumps({"left_ankle": "LeftFoot", "right_ankle": "RightFoot", "left_toe": "LeftToe", "right_toe": "RightToe"})
    mapped = submit([upload("mapped.bvh", unknown_feet)], joint_mapping=mapping)
    assert not any("足部" in warning for warning in mapped["import"]["warnings"])
    assert mapped["import"]["conventions"]["joint_mapping"]["left_ankle"] == "LeftFoot"


@pytest.mark.parametrize("case", ["missing_frames", "extra_frames", "missing_values", "extra_values", "channels", "axis", "child_translation", "large_frames", "large_joints"])
def test_bvh_validation_rejects_bad_data_before_inspection(import_root, tmp_path, monkeypatch, case):
    path = tmp_path / "source.bvh"
    write_bvh(path, np.zeros((2, 3)), np.zeros((2, len(BVH_NAMES), 3)), fps=30)
    text = path.read_text()
    if case == "missing_frames": text = text.replace("Frames: 2", "Frames: 6")
    elif case == "extra_frames": text = text.replace("Frames: 2", "Frames: 1")
    elif case in {"missing_values", "extra_values"}:
        lines = text.splitlines()
        values = lines[-1].split()
        lines[-1] = " ".join(values[:-1] if case == "missing_values" else values + ["0"])
        text = "\n".join(lines)
    elif case == "channels": text = text.replace("CHANNELS 6", "CHANNELS 4", 1)
    elif case == "axis": text = text.replace("Xposition", "Qposition", 1)
    elif case == "child_translation":
        text = text.replace("CHANNELS 3", "CHANNELS 6 Xposition Yposition Zposition", 1)
    elif case == "large_frames": text = text.replace("Frames: 2", "Frames: 1000000000")
    elif case == "large_joints":
        import motionlint.adapters.bvh_reader as reader
        original = reader.read_bvh
        monkeypatch.setattr("motionlint.adapters.bvh_adapter.read_bvh", lambda path, **kwargs: original(path, max_frames=12000, max_joints=2))
    # An invalid upload must never reach expensive inspection/model geometry.
    monkeypatch.setattr("motionlint.import_io.inspect", lambda *args: pytest.fail("Invalid BVH reached inspection"))
    with pytest.raises(HTTPException) as error:
        submit([upload("bad.bvh", text.encode())])
    assert error.value.status_code == 422
    assert not list(import_root.iterdir())


@pytest.mark.parametrize("case", ["shape", "pickle", "empty", "nan", "malformed_bvh", "complex_actor2", "frame_mismatch", "mixed", "mapping", "npy_units", "zero_fps", "oversized"])
def test_invalid_upload_is_rejected_without_partial_task(import_root, monkeypatch, case):
    files = [upload("motion.npy", npy_bytes(standing(12)))]
    options = {}
    if case == "shape": files = [upload("features.npy", npy_bytes(np.zeros((12, 35))))]
    elif case == "pickle": files = [upload("object.npy", npy_bytes(np.array([{"data": 1}], dtype=object)))]
    elif case == "empty": files = [upload("empty.npy", b"")]
    elif case == "malformed_bvh": files = [upload("broken.bvh", b"not a BVH hierarchy")]
    elif case == "nan":
        motion = standing(12); motion[3, 2, 0] = np.nan
        files = [upload("nan.npy", npy_bytes(motion))]
    elif case == "frame_mismatch": files.append(upload("actor2.npy", npy_bytes(standing(10))))
    elif case == "complex_actor2": files.append(upload("actor2.npy", npy_bytes(standing(12).astype(complex) + 1j)))
    elif case == "mixed": files.append(upload("actor2.bvh", b"invalid"))
    elif case == "mapping": options["joint_mapping"] = "[]"
    elif case == "npy_units": options["unit_scale"] = .01
    elif case == "zero_fps": options["fps"] = 0
    elif case == "oversized": monkeypatch.setattr(api, "MAX_IMPORT_BYTES", 100)
    with pytest.raises(HTTPException) as error:
        submit(files, **options)
    assert error.value.status_code == (413 if case == "oversized" else 422)
    assert not import_root.exists() or not list(import_root.iterdir())


def test_imports_reject_other_stages_and_incompatible_regression(import_root):
    first = submit([upload("a.npy", npy_bytes(standing(20)))], fps=30)
    second = submit([upload("b.npy", npy_bytes(standing(20)))], fps=60)
    ref = api.TaskRef(**first["task"])
    for stage in ("repaired", "bvh", "character"):
        with pytest.raises(HTTPException) as error:
            api.inspect_stage(api.StageRequest(**ref.model_dump(), stage=stage))
        assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        api.repair_task(ref)
    assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        api.compare_tasks(api.CompareRequest(baseline=ref, candidate=api.TaskRef(**second["task"])))
    assert error.value.status_code == 422
    assert api.compare_tasks(api.CompareRequest(baseline=ref, candidate=ref))["overall_change"] == 0


def test_import_manifest_cannot_reference_file_outside_its_folder(import_root):
    result = submit([upload("a.npy", npy_bytes(standing(20)))])
    task_id = result["task"]["task_id"]
    path = import_root / task_id / "import.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["files"][0]["path"] = "../outside.npy"
    np.save(import_root / "outside.npy", standing(20))
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(HTTPException) as error:
        api.imported_motion(task_id)
    assert error.value.status_code == 422


def test_failed_import_never_removes_an_existing_import(import_root):
    original = npy_bytes(standing(20))
    accepted = submit([upload("valid.npy", original)])
    task_id = accepted["task"]["task_id"]
    with pytest.raises(HTTPException):
        submit([upload("invalid.npy", npy_bytes(np.zeros((10, 5))))])
    assert [folder.name for folder in import_root.iterdir()] == [task_id]
    assert (import_root / task_id / "actor1.npy").read_bytes() == original


def test_http_upload_preview_download_and_restore(import_root):
    import http.client
    import socket
    import threading
    import time
    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(api.app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()

    def request(method, path, body=None, content_type="application/json"):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        try:
            connection.request(method, path, body, {"Content-Type": content_type})
            response = connection.getresponse()
            return response.status, json.loads(response.read()), response.getheader("Content-Disposition", "")
        finally: connection.close()

    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline: time.sleep(.01)
        assert server.started
        motion = standing(24)
        motion[7:, :, 0] += .3
        original = npy_bytes(motion)
        boundary = "aic-import-test"
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="fps"\r\n\r\n24\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="motion.npy"\r\nContent-Type: application/octet-stream\r\n\r\n').encode() + original + f'\r\n--{boundary}--\r\n'.encode()
        status, result, _ = request("POST", "/v1/motionlint/imports", body, f"multipart/form-data; boundary={boundary}")
        assert status == 200 and result["import"]["fps"] == 24
        task_id = result["task"]["task_id"]
        status, preview, _ = request("GET", f"/v1/motionlint/imports/{task_id}/preview?start=7&count=1")
        assert status == 200 and preview["start"] == 7 and len(preview["positions"]) == 1
        np.testing.assert_allclose(preview["positions"][0][0], motion[7], atol=1e-6)
        for query in ("start=-1", "count=0", "count=241", "start=24"):
            assert request("GET", f"/v1/motionlint/imports/{task_id}/preview?{query}")[0] == 422
        status, bundle, disposition = request("GET", f"/v1/motionlint/imports/{task_id}/report")
        assert status == 200 and "attachment" in disposition and len(bundle["report"]["tests"]) == 6
        status, restored, _ = request("POST", "/v1/motionlint/inspect-stage", json.dumps({"source": "import", "task_id": task_id, "stage": "raw"}))
        assert status == 200 and restored["import"]["fps"] == 24
        assert (import_root / task_id / "actor1.npy").read_bytes() == original
        assert request("GET", "/v1/motionlint/imports/not-a-uuid")[0] == 422
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        assert not thread.is_alive()
