"""Smoke checks against already generated local task artifacts."""

from pathlib import Path

from motionlint.api import REPO_ROOT, comparison_video, task_video


def test_existing_lodge_kenney_video_is_available() -> None:
    task_id = "a394daeb-6ca1-44e3-a5e8-970a73aea88c"
    task_folder = REPO_ROOT / "LODGE_api" / "task_runs" / task_id
    if not task_folder.is_dir():
        return  # Fresh clones have no local generator artifacts.
    response = task_video("lodge", task_id)
    assert Path(response.path).is_file()
    assert Path(response.path).parent.name == "retarget"


def test_lodge_comparison_uses_same_renderer_when_no_mesh_preview_exists() -> None:
    task_id = "a394daeb-6ca1-44e3-a5e8-970a73aea88c"
    folder = REPO_ROOT / "LODGE_api" / "task_runs" / task_id / "motionlint"
    if not (folder / "original.mp4").is_file():
        return  # The fresh clone has no local rendered task artifacts.
    before = comparison_video("lodge", task_id, "original")
    after = comparison_video("lodge", task_id, "repaired")
    assert Path(before.path) == folder / "original.mp4"
    assert Path(after.path) == folder / "repaired.mp4"
