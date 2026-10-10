"""Persist replay inputs separately from task status, without running work."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID


def task_folder(root, task_id):
    if str(UUID(task_id)) != task_id:
        raise ValueError("task_id must be a canonical UUID")
    folder = Path(root) / task_id
    if not folder.is_dir():
        raise FileNotFoundError("Task output folder not found")
    return folder


def save_request(root, task_id, operation, payload):
    folder = task_folder(root, task_id)
    data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict() if hasattr(payload, "dict") else payload
    path = folder / "retry_request.json"
    temporary = path.with_suffix(".tmp.json")
    temporary.write_text(json.dumps({"operation": operation, "request": data}, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def load_request(root, task_id):
    path = task_folder(root, task_id) / "retry_request.json"
    if not path.is_file():
        raise FileNotFoundError("该历史任务未保存重试参数，请重新提交输入。")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("request"), dict):
        raise ValueError("Saved retry request is invalid")
    return data
