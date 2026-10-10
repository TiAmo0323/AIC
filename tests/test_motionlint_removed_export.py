"""Retire the export API while keeping existing motion repair usable."""
import json
from concurrent.futures import Future

import numpy as np
import pytest
from pydantic import ValidationError

import motionlint.api as api
from motionlint.benchmark.fixtures import standing


def test_export_endpoints_are_absent_and_core_routes_remain():
    routes = api.app.openapi()["paths"]
    assert not any("export-character" in path or "character-export" in path for path in routes)
    for path in ("/v1/motionlint/repair", "/v1/motionlint/inspect-stage", "/v1/motionlint/compare"):
        assert "post" in routes[path]


@pytest.mark.parametrize("stage", ["repaired_bvh", "repaired_character"])
def test_removed_stages_are_rejected_by_request_validation(stage):
    with pytest.raises(ValidationError):
        api.StageRequest(source="intergen", task_id="11111111-1111-4111-8111-111111111111", stage=stage)
    schema = api.app.openapi()
    parameters = schema["paths"]["/v1/motionlint/settings"]["get"]["parameters"]
    allowed = next(parameter["schema"]["enum"] for parameter in parameters if parameter["name"] == "stage")
    assert stage not in allowed


def test_legacy_export_state_cannot_block_repair(tmp_path, monkeypatch):
    task_id = "11111111-1111-4111-8111-111111111111"
    task = tmp_path / task_id
    raw = task / "output/raw"
    raw.mkdir(parents=True)
    folder = task / "motionlint"
    folder.mkdir()
    state = folder / "character_export.json"
    state.write_text(json.dumps({"status": "running", "pid": 123}), encoding="utf-8")
    paths = []
    for actor in (1, 2):
        motion = standing(frames=20)
        motion[..., 0] += (actor - 1) * 3
        path = raw / f"{task_id}_person{actor}_joints22.npy"
        np.save(path, motion)
        paths.append(path)
    originals = [path.read_bytes() for path in paths]
    monkeypatch.setitem(api.TASK_ROOTS, "intergen", tmp_path)

    class PreviewExecutor:
        def submit(self, *args):
            future = Future()
            future.set_result(None)
            return future

    monkeypatch.setattr(api, "RENDER_EXECUTOR", PreviewExecutor())
    monkeypatch.setattr(api, "RENDER_JOBS", {})
    result = api.repair_task(api.TaskRef(source="intergen", task_id=task_id))
    assert result["after"]["metadata"]["inspection_stage"] == "repaired"
    assert (folder / "repair_report.json").is_file()
    assert (folder / "after/quality_gate.json").is_file()
    for actor, path in enumerate(paths, 1):
        repaired = np.load(folder / f"repaired_actor{actor}.npy", allow_pickle=False)
        assert repaired.shape == (20, 22, 3)
        assert np.isfinite(repaired).all()
        assert path.read_bytes() == originals[actor - 1]
    assert json.loads(state.read_text(encoding="utf-8"))["status"] == "running"
