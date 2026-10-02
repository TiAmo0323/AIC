"""Task state survives an API process restart through a local JSON manifest."""

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from shared.task_manifest import MANIFEST_NAME, restore_task_manifests, write_task_manifest


@dataclass
class FakeTask:
    task_id: str
    status: str
    message: str = ""

    def model_dump(self, mode: str = "python") -> dict:
        del mode
        return {
            "task_id": self.task_id,
            "status": self.status,
            "message": self.message,
        }


def test_task_manifest_is_atomic_and_recovers_interrupted_task() -> None:
    # Some Windows workstations deny pytest's default global temp directory.
    # Keep this tiny test's scratch data inside the repository's ignored reports.
    Path("reports").mkdir(exist_ok=True)
    with TemporaryDirectory(dir="reports") as scratch:
        task_root = Path(scratch) / "task_runs"
        task = FakeTask("demo", "running")
        path = write_task_manifest(task_root / task.task_id, task)
        assert path.name == MANIFEST_NAME
        assert not path.with_suffix(path.suffix + ".tmp").exists()

        restored = restore_task_manifests(task_root, FakeTask)
        assert restored["demo"].status == "failed"
        assert "服务重启" in restored["demo"].message
