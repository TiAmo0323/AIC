"""Check observable geometry and continuity through an independent BVH reader."""
import numpy as np
import pytest

from LODGE_api.lodge2bvh import BVH_OFFSETS, BVH_PARENTS, SMPL_TO_BVH22
from motionlint.adapters.bvh_adapter import load_bvh
from motionlint.core.result import MotionQualityReport, TestResult as QualityTestResult
from motionlint.export_intergen import select_converter
from motionlint.joints_to_bvh import convert_continuous_joints, fit_positions


def synthetic_joints(frames=60):
    """Independent FK: unequal bone scales, global turn, leg and arm bends."""
    offsets = BVH_OFFSETS * np.linspace(.82, 1.18, 22)[:, None]
    offsets[0] = 0
    positions = np.zeros((frames, 22, 3))
    world = np.zeros((frames, 22, 3, 3))
    for frame in range(frames):
        positions[frame, 0] = [frame * .002, 1.2, frame * .001]
        for joint, parent in enumerate(BVH_PARENTS):
            angle = .02 * frame if joint == 0 else (.12 * np.sin(frame * .05) if joint in (2, 15) else 0)
            c, s = np.cos(angle), np.sin(angle)
            local = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
            parent_rotation = world[frame, parent] if parent >= 0 else np.eye(3)
            world[frame, joint] = parent_rotation @ local
            if parent >= 0:
                positions[frame, joint] = positions[frame, parent] + parent_rotation @ offsets[joint]
    return positions[:, np.argsort(SMPL_TO_BVH22)], offsets


def test_scaled_articulated_geometry_survives_bvh_round_trip(tmp_path):
    joints, offsets = synthetic_joints()
    source, destination = tmp_path / "source.npy", tmp_path / "motion.bvh"
    np.save(source, joints)
    report = convert_continuous_joints(source, destination)
    decoded = load_bvh(destination)
    assert decoded.frame_count == 60 and decoded.fps == 30
    np.testing.assert_allclose(decoded.positions[:, 0], joints[:, SMPL_TO_BVH22], atol=3e-6)
    np.testing.assert_allclose(np.linalg.norm(report["offsets"], axis=-1), np.linalg.norm(offsets, axis=-1), atol=1e-7)
    rotations = decoded.rotation_matrices[:, 0]
    differences = np.swapaxes(rotations[:-1], -1, -2) @ rotations[1:]
    angles = np.degrees(np.arccos(np.clip((np.trace(differences, axis1=-2, axis2=-1) - 1) / 2, -1, 1)))
    assert angles.max() < 5
    assert report["round_trip_max_coordinate_error_m"] < 1e-5


def test_nonrigid_input_keeps_horizontal_root_and_caps_vertical_change():
    joints, _ = synthetic_joints()
    joints[:, 1:, 1] += np.sin(np.arange(len(joints)) * .2)[:, None] * .03
    target, fitted, _, _ = fit_positions(joints)
    np.testing.assert_allclose(fitted[:, 0, [0, 2]], target[:, 0, [0, 2]], atol=1e-12)
    assert np.abs(fitted[:, 0, 1] - target[:, 0, 1]).max() <= .010000001


@pytest.mark.parametrize("invalid", [np.zeros((6, 22, 3)), np.full((6, 22, 3), np.nan), np.zeros((1, 22, 3))])
def test_invalid_or_collapsed_bones_are_rejected(invalid):
    with pytest.raises(ValueError):
        fit_positions(invalid)


def reports(scores, statuses=None):
    names = ("temporal_continuity", "skeleton_integrity", "foot_sliding", "ground_contact", "collision", "motion_jerk")
    statuses = statuses or {}
    return MotionQualityReport(float(np.mean(list(scores.values()))),
                               [QualityTestResult(name, statuses.get(name, "PASS"), scores.get(name, 100)) for name in names])


def fidelity_rows(mean=.02, p95=.05, root=0):
    return [{"position_error_mean_m": mean, "position_error_p95_m": p95, "position_error_max_m": p95 * 2, "root_error_max_m": root}]


def test_converter_rejects_ground_regression_despite_temporal_gain():
    baseline = reports({"temporal_continuity": 75, "ground_contact": 100})
    candidate = reports({"temporal_continuity": 100, "ground_contact": 88})
    result = select_converter(baseline, candidate, fidelity_rows(), fidelity_rows(.004, .01, .008))
    assert result["selected"] == "momask"
    assert result["regression"]["status"] == "REGRESSION DETECTED"


def test_converter_rejects_new_failure_or_worse_geometry():
    baseline = reports({"temporal_continuity": 90, "foot_sliding": 90})
    candidate = reports({"temporal_continuity": 100, "foot_sliding": 89}, {"foot_sliding": "FAIL"})
    result = select_converter(baseline, candidate, fidelity_rows(), fidelity_rows(.004, .01))
    assert result["selected"] == "momask" and any("New failed test" in reason for reason in result["reasons"])
    candidate = reports({"temporal_continuity": 100, "foot_sliding": 100})
    result = select_converter(baseline, candidate, fidelity_rows(), fidelity_rows(.03, .06))
    assert result["selected"] == "momask" and any("fidelity" in reason for reason in result["reasons"])
    result = select_converter(baseline, candidate, fidelity_rows(), fidelity_rows(.004, .01, .011))
    assert result["selected"] == "momask" and any("1 cm" in reason for reason in result["reasons"])


def test_converter_accepts_continuity_and_geometry_gains():
    baseline = reports({"temporal_continuity": 80, "foot_sliding": 90}, {"temporal_continuity": "FAIL"})
    candidate = reports({"temporal_continuity": 100, "foot_sliding": 92})
    result = select_converter(baseline, candidate, fidelity_rows(), fidelity_rows(.004, .01, .008))
    assert result["selected"] == "continuous" and result["reasons"] == []


def test_candidate_exception_keeps_valid_legacy_bvh(tmp_path, monkeypatch):
    import sys
    from types import ModuleType
    import motionlint.joints_to_bvh as continuous
    from motionlint.core.config import DEFAULT_CONFIG
    from motionlint.export_intergen import convert_snapshot

    # Supply a working legacy writer without importing the GPU generation stack.
    legacy = ModuleType("InterGen_api.intergen_joints2bvh")
    writer = continuous.convert_continuous_joints
    legacy.convert_joints_to_bvh = lambda source, output, runtime, **kwargs: writer(source, output, fps=kwargs["fps"])
    monkeypatch.setitem(sys.modules, legacy.__name__, legacy)

    def broken_candidate(*args, **kwargs):
        raise ValueError("Injected candidate failure")

    monkeypatch.setattr(continuous, "convert_continuous_joints", broken_candidate)
    paths = []
    for actor in (1, 2):
        joints, _ = synthetic_joints()
        joints[..., 0] += 3 * actor
        source = tmp_path / f"actor{actor}.npy"
        np.save(source, joints)
        paths.append(source)
    output = tmp_path / "export"
    output.mkdir()
    selection = convert_snapshot(paths, output, fps=30, policy=DEFAULT_CONFIG)
    assert selection["selected"] == "momask"
    assert "Injected candidate failure" in selection["reasons"][0]
    for actor in (1, 2):
        published = output / f"repaired_actor{actor}.bvh"
        original = output / "conversion_candidates/momask" / published.name
        assert published.read_bytes() == original.read_bytes()
        assert load_bvh(published).frame_count == 60
