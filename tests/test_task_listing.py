"""Task browsing and recovery retain failures and expose bounded summaries."""
import json
import uuid

from shared.task_listing import task_page
from shared.task_manifest import restore_task_manifests, write_task_manifest
from shared.task_requests import save_request
from LODGE_api import lodge_async_api as lodge


def create(root, index, status, **kwargs):
    task_id = str(uuid.uuid4())
    task = lodge.TaskInfo(task_id=task_id, status=status, created_at=f"2026-10-09T10:{index:02d}:00", updated_at="now", **kwargs)
    write_task_manifest(root / task_id, task)
    return task


def test_task_page_filters_searches_and_paginates_without_paths(tmp_path):
    tasks = [create(tmp_path, i, "failed" if i % 2 else "queued", message="failure reason") for i in range(6)]
    for i, task in enumerate(tasks):
        save_request(tmp_path, task.task_id, "_run_infer_and_render_task", {"song_id": f"Beat {i}", "lodge_root": "private path"})
    original = [task.model_dump() for task in tasks]
    page = task_page(tmp_path, "lodge", tasks, status="failed", search="bEAt", offset=1, limit=1)
    assert page["total"] == 3 and page["has_more"]
    assert page["items"][0]["title"] == "Beat 3"
    assert page["items"][0]["retry_available"]
    assert "private path" not in json.dumps(page)
    assert "failure reason" in json.dumps(page)
    assert "output_mp4_path" not in page["items"][0]
    assert task_page(tmp_path, "lodge", tasks, search=tasks[0].task_id)["total"] == 1
    assert task_page(tmp_path, "lodge", tasks, status="active")["total"] == 3
    assert not task_page(tmp_path, "lodge", tasks, offset=100)["items"]
    assert [task.model_dump() for task in tasks] == original


def test_retry_availability_tracks_missing_inputs_and_corrupt_records(tmp_path):
    task = create(tmp_path, 0, "failed")
    source = tmp_path / "beat.wav"
    source.write_bytes(b"original")
    save_request(tmp_path, task.task_id, "_run_infer_from_audio_task", {"song_id": "beat", "audio_path": str(source)})
    assert task_page(tmp_path, "lodge", [task])["items"][0]["retry_available"]
    source.unlink()
    summary = task_page(tmp_path, "lodge", [task])["items"][0]
    assert not summary["retry_available"] and "重新上传" in summary["retry_unavailable_reason"]
    (tmp_path / task.task_id / "retry_request.json").write_text("[]", encoding="utf-8")
    assert not task_page(tmp_path, "lodge", [task])["items"][0]["retry_available"]


def test_recovery_keeps_failed_state_and_partial_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(lodge, "DEFAULT_TASK_ROOT", tmp_path)
    video = tmp_path / "preview.mp4"
    video.write_bytes(b"preview")
    task = create(tmp_path, 0, "running", progress=85, output_mp4_path=str(video), retarget_status="failed", retarget_message="original renderer error")
    recovered = lodge._restore_tasks()[task.task_id]
    assert recovered.status == "failed" and "服务重启" in recovered.message
    assert recovered.retarget_status == "failed" and recovered.retarget_message == "original renderer error"
    assert recovered.output_mp4_path == str(video)
    summary = task_page(tmp_path, "lodge", [recovered])["items"][0]
    assert summary["preview_available"] and not summary["retry_available"]
    again = restore_task_manifests(tmp_path, lodge.TaskInfo)[task.task_id]
    assert again.status == "failed"


def test_restore_ignores_corrupt_and_mismatched_manifest(tmp_path):
    valid = create(tmp_path, 0, "failed")
    for name, payload in (("corrupt", "[]"), ("mismatched", json.dumps(valid.model_dump()))):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "task_manifest.json").write_text(payload, encoding="utf-8")
    restored = restore_task_manifests(tmp_path, lodge.TaskInfo)
    assert list(restored) == [valid.task_id]


def test_recovery_does_not_report_deleted_video_as_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(lodge, "DEFAULT_TASK_ROOT", tmp_path)
    task = create(tmp_path, 0, "succeeded", output_mp4_path=str(tmp_path / "deleted.mp4"))
    recovered = lodge._restore_tasks()[task.task_id]
    assert recovered.status == "failed" and recovered.output_mp4_path is None
    assert not task_page(tmp_path, "lodge", [recovered])["items"][0]["preview_available"]


def test_pagination_reads_inputs_and_checks_files_only_for_visible_rows(tmp_path, monkeypatch):
    import shared.task_listing as listing
    tasks = [create(tmp_path, i, "failed") for i in range(40)]
    calls = []
    checks = []
    def read(root, task_id):
        calls.append(task_id)
        return {"operation": "_run_infer_from_audio_task", "request": {"song_id": "beat", "audio_path": "input.wav"}}
    monkeypatch.setattr(listing, "load_request", read)
    monkeypatch.setattr(listing, "_file_exists", lambda raw: checks.append(raw) or bool(raw))
    page = task_page(tmp_path, "lodge", tasks, offset=5, limit=3)
    assert page["total"] == 40 and page["has_more"]
    assert calls == [task.task_id for task in reversed(tasks)][5:8]
    assert checks.count("input.wav") == 3
    calls.clear(); checks.clear()
    assert not task_page(tmp_path, "lodge", tasks, offset=100)["items"]
    assert not calls and not checks


def test_search_reuses_titles_without_checking_hidden_task_files(tmp_path, monkeypatch):
    import shared.task_listing as listing
    tasks = [create(tmp_path, i, "failed" if i % 2 else "queued") for i in range(12)]
    calls = []
    checks = []
    def read(root, task_id):
        calls.append(task_id)
        return {"operation": "_run_infer_from_audio_task", "request": {"song_id": "BEAT", "audio_path": "input.wav"}}
    monkeypatch.setattr(listing, "load_request", read)
    monkeypatch.setattr(listing, "_file_exists", lambda raw: checks.append(raw) or bool(raw))
    page = task_page(tmp_path, "lodge", tasks, status="failed", search="beat", limit=2)
    assert page["total"] == 6 and len(page["items"]) == 2
    assert len(calls) == len(set(calls)) == 6, "Visible search results should reuse loaded request records"
    assert checks.count("input.wav") == 2


def test_malformed_retry_operation_cannot_break_task_listing(tmp_path):
    task = create(tmp_path, 0, "failed")
    path = tmp_path / task.task_id / "retry_request.json"
    path.write_text(json.dumps({"operation": [], "request": {"song_id": "beat"}}), encoding="utf-8")
    summary = task_page(tmp_path, "lodge", [task])["items"][0]
    assert summary["title"] == "beat" and not summary["retry_available"]
