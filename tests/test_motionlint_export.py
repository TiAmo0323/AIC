"""Prevent mismatched repaired exports, missing inputs and false stage scores."""
import json
import os
import zipfile
from pathlib import Path
from concurrent.futures import Future

import numpy as np
import pytest
from fastapi import HTTPException

import motionlint.api as api
from motionlint.export_intergen import build_manifest, fingerprint, read_export, export_artifact

TASK_ID = "11111111-1111-4111-8111-111111111111"


def ready_task(tmp_path, monkeypatch):
    task = tmp_path / TASK_ID
    folder = task / "motionlint"
    output = folder / "exports/run1"
    output.mkdir(parents=True)
    paths = [folder / f"repaired_actor{actor}.npy" for actor in (1, 2)]
    for path in paths:
        np.save(path, np.ones((6, 22, 3)))
    video = output / "repaired_kenney.mp4"
    video.write_bytes(b"video")
    state = {"status": "ready", "input_fingerprints": fingerprint(paths), "video_path": str(video)}
    (folder / "character_export.json").write_text(json.dumps(state), encoding="utf-8")
    monkeypatch.setitem(api.TASK_ROOTS, "intergen", tmp_path)
    return task, paths, video


def test_changed_motion_rejects_old_video_and_download(tmp_path, monkeypatch):
    task, paths, video = ready_task(tmp_path, monkeypatch)
    ref = api.TaskRef(source="intergen", task_id=TASK_ID)
    assert api._stage_video_path(ref, "repaired_character") == video
    np.save(paths[0], np.zeros((6, 22, 3)))
    assert read_export(task)["status"] == "stale"
    assert api._stage_video_path(ref, "repaired_character") is None
    with pytest.raises(HTTPException) as error:
        api.character_export_download("intergen", TASK_ID)
    assert error.value.status_code == 409


def test_export_does_not_replace_raw_character_or_bvh_video(tmp_path, monkeypatch):
    task, _, video = ready_task(tmp_path, monkeypatch)
    ref = api.TaskRef(source="intergen", task_id=TASK_ID)
    assert api._stage_video_path(ref, "character") is None
    assert api._stage_video_path(ref, "repaired_bvh") is None
    assert api._stage_video_path(ref, "repaired_character") == video


def test_export_manifest_has_full_length_and_repaired_inputs(tmp_path):
    output = tmp_path / "export"
    manifest = build_manifest(tmp_path, output, frames=240, fps=30, size=540)
    assert manifest["max_render_frames"] == 0
    assert manifest["source_frame_counts"] == [240, 240]
    assert manifest["duration_seconds"] == 8
    assert manifest["person_skin_ids"] == ["kenney_cc0"] * 2
    assert all(Path(path).parent == output for path in manifest["raw_joints_files"] + manifest["source_bvh_files"])
    assert manifest["motionlint_input_stage"] == "repaired"


def test_export_fails_without_saved_repair(tmp_path, monkeypatch):
    (tmp_path / TASK_ID).mkdir()
    monkeypatch.setitem(api.TASK_ROOTS, "intergen", tmp_path)
    with pytest.raises(HTTPException) as error:
        api.export_character(api.CharacterExportRequest(source="intergen", task_id=TASK_ID))
    assert error.value.status_code == 409


def test_artifact_must_be_inside_export_directory(tmp_path, monkeypatch):
    task, _, _ = ready_task(tmp_path, monkeypatch)
    state = read_export(task)
    outside = tmp_path / "unrelated.mp4"
    outside.write_bytes(b"other")
    state["video_path"] = str(outside)
    (task / "motionlint/character_export.json").write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError):
        export_artifact(task, "video_path")


def test_repair_waits_for_export_without_overwriting_input(tmp_path, monkeypatch):
    task, paths, _ = ready_task(tmp_path, monkeypatch)
    before = fingerprint(paths)
    monkeypatch.setitem(api.EXPORT_JOBS, ("intergen", TASK_ID), Future())
    with pytest.raises(HTTPException) as error:
        api.repair_task(api.TaskRef(source="intergen", task_id=TASK_ID))
    assert error.value.status_code == 409
    assert fingerprint(paths) == before


def test_stopped_worker_is_reported_instead_of_polling_forever(tmp_path, monkeypatch):
    import motionlint.export_intergen as exporter
    task, _, _ = ready_task(tmp_path, monkeypatch)
    (task / "motionlint/character_export.json").write_text(json.dumps({"status": "running", "pid": 123}), encoding="utf-8")
    monkeypatch.setattr(exporter, "_process_alive", lambda pid: False)
    assert read_export(task)["status"] == "failed"


def test_current_worker_is_alive():
    from motionlint.export_intergen import _process_alive
    assert _process_alive(os.getpid())


def test_bundle_retains_failed_gate_and_excludes_local_assets(tmp_path):
    from motionlint.export_intergen import write_bundle
    for name in ("character.fbx", "scene.blend", "weights.ckpt", "repaired_actor1.npy", "repaired_kenney.mp4"):
        (tmp_path / name).write_bytes(b"local")
    state = {"status": "running", "quality": {"repaired_character": {"score": 80, "gate": {"status": "FAIL"}}}}
    bundle = write_bundle(tmp_path, state)
    with zipfile.ZipFile(bundle) as archive:
        assert set(archive.namelist()) == {"repaired_actor1.npy", "repaired_kenney.mp4", "export_summary.json"}
        summary = json.loads(archive.read("export_summary.json"))
        assert summary["status"] == "ready"
        assert summary["quality"]["repaired_character"]["gate"]["status"] == "FAIL"
