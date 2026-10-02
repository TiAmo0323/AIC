"""Check real stage risks: BVH root semantics, scaling, pairing and preview mismatch."""
import json
from pathlib import Path

import numpy as np
import pytest

from LODGE_api.lodge2bvh import BVH_NAMES, write_bvh
from motionlint.adapters.bvh_adapter import load_bvh, load_bvh_pair
from motionlint.core.config import load_config
from motionlint.tests.skeleton_integrity import check
from motionlint.api import TaskRef, StageRequest, _stage_video_path, _stage_motion
from fastapi import HTTPException


def test_bvh_root_is_not_collapsed_and_units_scale(tmp_path):
    path = tmp_path / "motion.bvh"
    write_bvh(path, np.zeros((6, 3)), np.zeros((6, len(BVH_NAMES), 3)), fps=30)
    motion = load_bvh(path)
    assert motion.metadata["parents"][0] == -1
    assert check(motion, load_config()["tests"]["skeleton_integrity"]).status == "PASS"
    assert [motion.joint_names[index] for index in motion.metadata["foot_joint_ids"]] == ["LeftFoot", "RightFoot", "LeftToe", "RightToe"]
    centimetres = load_bvh(path, unit_scale=.01, up_axis=2)
    np.testing.assert_allclose(centimetres.positions, motion.positions * .01)
    assert centimetres.metadata["up_axis"] == 2
    with pytest.raises(ValueError):
        load_bvh(path, unit_scale=-1)


def test_pair_keeps_spacing_and_rejects_different_lengths(tmp_path):
    paths = [tmp_path / "a.bvh", tmp_path / "b.bvh"]
    rotations = np.zeros((6, len(BVH_NAMES), 3))
    write_bvh(paths[0], np.zeros((6, 3)), rotations, fps=30)
    write_bvh(paths[1], np.tile([1., 0, 0], (6, 1)), rotations, fps=30)
    motion = load_bvh_pair(paths)
    assert motion.actor_count == 2
    np.testing.assert_allclose(motion.positions[:, 1] - motion.positions[:, 0], np.broadcast_to([1., 0, 0], (6, 22, 3)), atol=1e-6)
    write_bvh(paths[1], np.zeros((3, 3)), rotations[:3], fps=30)
    with pytest.raises(ValueError):
        load_bvh_pair(paths)


def test_raw_video_does_not_silently_use_character(monkeypatch, tmp_path):
    import motionlint.api as api
    task_id = "11111111-1111-4111-8111-111111111111"
    task = tmp_path / task_id
    (task / "retarget").mkdir(parents=True)
    video = task / "retarget/character.mp4"
    video.write_bytes(b"test")
    (task / "retarget/retarget_manifest.json").write_text(json.dumps({"output_mp4": str(video)}), encoding="utf-8")
    monkeypatch.setitem(api.TASK_ROOTS, "intergen", tmp_path)
    ref = TaskRef(source="intergen", task_id=task_id)
    assert _stage_video_path(ref, "raw") is None
    assert _stage_video_path(ref, "bvh") is None
    assert _stage_video_path(ref, "character") == video
    with pytest.raises(HTTPException) as error:
        _stage_motion(StageRequest(source="intergen", task_id=task_id, stage="bvh"))
    assert error.value.status_code == 404


def test_repaired_video_needs_completed_render(monkeypatch, tmp_path):
    import motionlint.api as api
    task_id = "11111111-1111-4111-8111-111111111111"
    folder = tmp_path / task_id / "motionlint"
    folder.mkdir(parents=True)
    (folder / "repaired.mp4").write_bytes(b"old preview")
    (folder / "render_status.json").write_text('{"status":"queued"}', encoding="utf-8")
    monkeypatch.setitem(api.TASK_ROOTS, "lodge", tmp_path)
    assert _stage_video_path(TaskRef(source="lodge", task_id=task_id), "repaired") is None
