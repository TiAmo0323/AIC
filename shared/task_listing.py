"""Public task summaries, without exposing local paths or full retry inputs."""
from __future__ import annotations

from pathlib import Path

from shared.task_requests import load_request

ACTIVE_STATUSES = {"queued", "running", "processing"}
_UNLOADED = object()


def _file_exists(raw):
    try:
        return bool(raw and Path(raw).is_file())
    except (OSError, ValueError, TypeError):
        return False


def _read_request(root, task_id):
    try:
        return load_request(root, task_id)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _title(data, saved):
    request = saved["request"] if saved else {}
    title = data.get("original_prompt") or request.get("text") or request.get("song_id") or ""
    return str(title)[:240] or f'任务 {data["task_id"][:8]}'


def _task_summary(root, backend, data, saved=_UNLOADED):
    task_id = data["task_id"]
    if saved is _UNLOADED:
        saved = _read_request(root, task_id)
    retry_reason = ""
    if saved:
        request = saved["request"]
        allowed = {"generate"} if backend == "intergen" else {
            "_run_render_task", "_run_infer_and_render_task", "_run_infer_from_audio_task",
            "_run_infer_from_feature_npy_task", "render-npy",
        }
        operation = saved.get("operation")
        if not isinstance(operation, str) or operation not in allowed:
            retry_reason = "该任务的重试方式暂不支持，请重新提交输入。"
        elif any(request.get(field) and not _file_exists(request[field])
                 for field in ("audio_path", "feature_npy_path", "uploaded_npy_path")):
            retry_reason = "原始输入文件已不可用，请重新上传。"
    else:
        retry_reason = "该历史任务未保存可用的重试参数，请重新提交输入。"
    if data["status"] in ACTIVE_STATUSES:
        retry_reason = "任务仍在运行，请等待结束后重试。"
    summary = {key: data.get(key) for key in (
        "task_id", "status", "progress", "created_at", "updated_at", "message",
        "skin_id", "requested_skin_ids", "person_skin_ids", "retarget_status",
    )}
    summary.update(source=backend, title=_title(data, saved),
        preview_available=(data["status"] not in ACTIVE_STATUSES and (
            _file_exists(data.get("output_mp4_path")) or (data.get("retarget_status") == "succeeded" and any(
                _file_exists(data.get(key)) for key in ("output_retarget_mp4_path", "output_retarget_path"))))),
        retry_available=not retry_reason, retry_unavailable_reason=retry_reason)
    return summary


def task_summary(root, backend, task):
    data = task.model_dump() if hasattr(task, "model_dump") else task.dict()
    return _task_summary(root, backend, data)


def task_page(root, backend, tasks, *, status="", search="", offset=0, limit=20):
    rows = [task.model_dump() if hasattr(task, "model_dump") else task.dict() for task in tasks]
    if status:
        rows = [row for row in rows if row["status"] in ACTIVE_STATUSES] if status == "active" else [row for row in rows if row["status"] == status]
    needle = search.strip().casefold()
    saved_requests = {}
    if needle:
        matches = []
        for row in rows:
            saved = _UNLOADED
            if not row.get("original_prompt") and needle not in row["task_id"].casefold():
                saved = _read_request(root, row["task_id"])
                saved_requests[row["task_id"]] = saved
            title = _title(row, None if saved is _UNLOADED else saved)
            if needle in f'{row["task_id"]} {title}'.casefold():
                matches.append(row)
        rows = matches
    rows.sort(key=lambda row: (row["created_at"] or "", row["task_id"]), reverse=True)
    page = [_task_summary(root, backend, row, saved_requests.get(row["task_id"], _UNLOADED))
            for row in rows[offset:offset + limit]]
    return {"items": page, "total": len(rows), "offset": offset,
            "limit": limit, "has_more": offset + limit < len(rows)}
