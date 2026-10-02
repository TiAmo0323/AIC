"""Check geometry against analytic poses, without licensed model fixtures."""

from pathlib import Path

import numpy as np
import pytest

from LODGE_api.lodge2bvh import BVH_OFFSETS, BVH_PARENTS, SMPL_TO_BVH22
from LODGE_api.lodge2bvh import BVH_NAMES
from motionlint.adapters import smplx_geometry
from motionlint.adapters.lodge_adapter import normalize_lodge_array
from motionlint.repairs.foot_lock import repair_foot_sliding
from motionlint.repairs.collision_repair import repair_lodge_collisions
from motionlint.core.config import load_config
from motionlint.tests import collision
from motionlint.tests.foot_sliding import check


def _model(path: Path) -> np.ndarray:
    offsets = BVH_OFFSETS * 1.13
    offsets[0] = [.12, -.3, .08]
    rest_bvh = offsets.copy()
    for joint, parent in enumerate(BVH_PARENTS):
        if parent >= 0:
            rest_bvh[joint] += rest_bvh[parent]
    rest = np.empty_like(rest_bvh)
    rest[SMPL_TO_BVH22] = rest_bvh
    parents = np.full(22, -1, dtype=int)
    parents[np.array(SMPL_TO_BVH22)[1:]] = np.array(SMPL_TO_BVH22)[BVH_PARENTS[1:]]
    np.savez(path, v_template=rest, J_regressor=np.eye(22),
             kintree_table=np.stack([parents, np.arange(22)]))
    return rest_bvh


def _raw() -> np.ndarray:
    raw = np.zeros((18, 139), dtype=np.float32)
    raw[:, :4] = 1
    raw[:, 5] = 1
    raw[:, 4] = np.arange(18) * .008
    raw[:, 7:] = np.tile([1, 0, 0, 0, 1, 0], 22)
    return raw


def test_model_joints_match_analytic_rotated_pose(tmp_path) -> None:
    model = tmp_path / "neutral.npz"
    rest = _model(model)
    raw = _raw()
    raw[:, 7:13] = [0, -1, 0, 1, 0, 0]
    rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]])
    expected = raw[:, None, 4:7] + rest[0] + (rotation @ (rest - rest[0]).T).T
    motion = normalize_lodge_array(raw, model_path=model)
    np.testing.assert_allclose(motion.positions[:, 0], expected, atol=1e-6)
    np.testing.assert_array_equal(motion.root_translation[:, 0], raw[:, 4:7])
    assert motion.metadata["geometry_source"] == "smplx_neutral_model"


def test_foot_repair_preserves_explicit_geometry_model(tmp_path) -> None:
    model = tmp_path / "neutral.npz"
    _model(model)
    raw = _raw()
    motion = normalize_lodge_array(raw, model_path=model)
    issues = check(motion, {"contact_height_m": .06, "horizontal_speed_m_s": .16}).issues
    repaired, _, _ = repair_foot_sliding(motion, issues, raw=raw)
    assert repaired.metadata["geometry_model_path"] == str(model.resolve())
    np.testing.assert_array_equal(repaired.metadata["offsets"], motion.metadata["offsets"])


def test_missing_default_model_uses_labeled_proxy(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(smplx_geometry, "DEFAULT_MODEL", tmp_path / "absent.npz")
    monkeypatch.delenv("MOTIONLINT_SMPLX_MODEL", raising=False)
    monkeypatch.delenv("LODGE_SMPLX_MODEL", raising=False)
    motion = normalize_lodge_array(_raw())
    assert motion.metadata["geometry_source"] == "fixed_bvh_proxy"
    assert motion.metadata["geometry_model_path"] is None
    np.testing.assert_allclose(motion.positions[:, 0, 0], _raw()[:, 4:7])


def test_explicit_missing_model_does_not_silently_use_proxy(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="Configured SMPL-X"):
        normalize_lodge_array(_raw(), model_path=tmp_path / "absent.npz")


def test_arm_ik_preserves_bones_source_channels_and_fk(tmp_path):
    model = tmp_path / "arm_fixture.npz"
    rest = _model(model)
    head = rest[BVH_NAMES.index("Head")].copy()
    arm_ids = [BVH_NAMES.index("Right" + suffix) for suffix in ("Arm", "ForeArm", "Hand")]
    rest[arm_ids] = head + np.array([[.3, -.15, 0], [.1, -.3, 0], [.08, 0, 0]])
    rest_smpl = np.empty_like(rest)
    rest_smpl[SMPL_TO_BVH22] = rest
    with np.load(model, allow_pickle=False) as data:
        parents = data["kintree_table"].copy()
    np.savez(model, v_template=rest_smpl, J_regressor=np.eye(22), kintree_table=parents)
    raw = _raw()
    raw[:, 4] = 0
    motion = normalize_lodge_array(raw, model_path=model)
    settings = load_config()["tests"]["collision"]
    assert collision.check(motion, settings).status == "FAIL"
    repaired, repaired_raw, detail = repair_lodge_collisions(motion, raw=raw, settings=settings)
    assert collision.check(repaired, settings).status == "PASS"
    assert detail["max_wrist_shift_m"] <= .05
    parents_bvh = BVH_PARENTS[1:]
    for value in (motion, repaired):
        lengths = np.linalg.norm(value.positions[:, :, 1:] - value.positions[:, :, parents_bvh], axis=-1)
        if value is motion:
            reference_lengths = lengths
        else:
            np.testing.assert_allclose(lengths, reference_lengths, atol=1e-7)
    np.testing.assert_array_equal(raw[:, :7], repaired_raw[:, :7])
    untouched = [joint for joint in range(22) if joint not in np.array(SMPL_TO_BVH22)[arm_ids]]
    np.testing.assert_array_equal(raw[:, 7:].reshape(18, 22, 6)[:, untouched],
                                  repaired_raw[:, 7:].reshape(18, 22, 6)[:, untouched])
    np.testing.assert_allclose(repaired.positions, normalize_lodge_array(repaired_raw, model_path=model).positions, atol=1e-7)
