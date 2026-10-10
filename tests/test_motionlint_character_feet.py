"""Guard bounded support corrections and Blender exception propagation."""
import json
from pathlib import Path
import numpy as np
from LODGE_api.lodge2bvh import BVH_NAMES, BVH_OFFSETS, BVH_PARENTS
from motionlint.character_feet import plan_character_feet


def character_fixture(tmp_path, swing=False):
    frames = 60
    positions = np.zeros((frames, 1, 22, 3))
    positions[:, 0, 0, 1] = 1.2
    for joint, parent in enumerate(BVH_PARENTS):
        if parent >= 0:
            positions[:, 0, joint] = positions[:, 0, parent] + BVH_OFFSETS[joint]
    positions[..., 0] += np.arange(frames)[:, None, None] * .012
    if swing:
        positions[20:40, :, [3, 4, 7, 8], 1] += .6
    path = tmp_path / "character.npz"
    world = np.broadcast_to(np.eye(3), (frames, 1, 22, 3, 3)).copy()
    np.savez_compressed(path, positions=positions, world_rotation_matrices=world,
                        joint_names=np.array(BVH_NAMES), parents=BVH_PARENTS)
    path.with_suffix(".json").write_text(json.dumps({"fps": 30, "frame_start": 1, "frame_end": frames,
                                                     "target_names": ["Retarget_Target_1"]}), encoding="utf-8")
    return path


def test_character_plan_is_bounded_and_reduces_original_support_motion(tmp_path):
    path = character_fixture(tmp_path)
    original = path.read_bytes()
    plan = plan_character_feet(path)
    corrections = np.asarray(plan["corrections_xz_m"])
    assert np.linalg.norm(corrections, axis=-1).max() <= .15000001
    toe = np.array(plan["reference_positions"])[:, 0, 4][:, [0, 2]]
    repaired = toe + corrections[:, 0, 0]
    assert np.linalg.norm(np.diff(repaired, axis=0), axis=-1).mean() < np.linalg.norm(np.diff(toe, axis=0), axis=-1).mean()
    assert path.read_bytes() == original
    assert plan["support_metrics"]["support_joint_interval_count"] > 0


def test_swing_midpoint_does_not_get_a_contact_lock(tmp_path):
    plan = plan_character_feet(character_fixture(tmp_path, swing=True))
    assert not np.asarray(plan["active"])[28:32].any()
    np.testing.assert_allclose(np.asarray(plan["corrections_xz_m"])[28:32], 0)
