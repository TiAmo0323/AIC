"""Small JSON persistence helpers for the local generator task registries.

The generator APIs deliberately keep their in-process dictionaries for fast
polling.  A task manifest beside the artifacts makes that state recoverable
after a service restart without introducing a database dependency.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, TypeVar


T = TypeVar("T")
MANIFEST_NAME = "task_manifest.json"


def _model_data(task: Any) -> dict:
    if hasattr(task, "model_dump"):
        return task.model_dump(mode="json")
    if hasattr(task, "dict"):
        return task.dict()
    raise TypeError(f"Task model does not expose model_dump/dict: {type(task)!r}")


def write_task_manifest(task_root: str | Path, task: Any) -> Path:
    """Atomically write the serializable task state beside its artifacts."""

    root = Path(task_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / MANIFEST_NAME
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_model_data(task), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def restore_task_manifests(
    task_root: str | Path,
    model: Callable[..., T],
) -> Dict[str, T]:
    """Load valid task manifests, ignoring incomplete/corrupt directories.

    A task that was still queued or running when the API process stopped is
    marked failed on recovery.  Its partial files remain available for
    inspection and a caller can start a new retry task explicitly.
    """

    root = Path(task_root)
    restored: Dict[str, T] = {}
    if not root.is_dir():
        return restored
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        path = folder / MANIFEST_NAME
        if not path.is_file():
            # Older task directories predate persistence.  Recover a minimal
            # succeeded/failed record from their artifacts so an API restart
            # does not make the task id disappear.  Detailed fields remain
            # available in the original output manifests.
            has_artifacts = any(child.is_file() for child in folder.rglob("*"))
            if not has_artifacts:
                continue
            timestamp = datetime.fromtimestamp(
                folder.stat().st_mtime,
                tz=timezone.utc,
            ).isoformat(timespec="seconds")
            data = {
                "task_id": folder.name,
                "status": "succeeded",
                "created_at": timestamp,
                "updated_at": timestamp,
                "message": "从已有任务文件恢复；详细输出信息保留在任务目录中。",
            }
            try:
                task = model(**data)
                write_task_manifest(folder, task)
            except (OSError, ValueError, TypeError):
                continue
            restored[str(getattr(task, "task_id", folder.name))] = task
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            status = str(data.get("status") or "").lower()
            if status in {"queued", "running", "processing"}:
                data["status"] = "failed"
                data["message"] = (
                    "服务重启时任务仍在运行，已恢复为 failed；原始任务文件仍保留。"
                )
            task = model(**data)
        except (OSError, ValueError, TypeError):
            continue
        task_id = str(getattr(task, "task_id", folder.name))
        restored[task_id] = task
    return restored
