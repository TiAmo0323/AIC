"""MotionLint data contract and PyMotion BVH integration checks."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from LODGE_api.lodge2bvh import BVH_NAMES, write_bvh
from motionlint import MotionIssue, MotionQualityReport, MotionSequence, TestResult as QualityTestResult
from motionlint.adapters.bvh_adapter import load_bvh
from motionlint.adapters.intergen_adapter import load_intergen_joints
from motionlint.adapters.lodge_adapter import load_lodge_npy
from motionlint.core.config import load_config
from motionlint.core.registry import TestRegistry as QualityTestRegistry


class MotionSequenceTests(unittest.TestCase):
    def test_multi_actor_axes_and_duration(self) -> None:
        positions = np.zeros((180, 2, 22, 3), dtype=np.float32)
        motion = MotionSequence(
            source="intergen",
            fps=30,
            frame_count=180,
            actor_count=2,
            positions=positions,
            joint_names=[f"joint_{index}" for index in range(22)],
        )
        self.assertEqual(motion.positions.shape, (180, 2, 22, 3))
        self.assertEqual(motion.duration_seconds, 6)

    def test_rejects_inconsistent_actor_axis(self) -> None:
        with self.assertRaisesRegex(ValueError, "positions must have shape"):
            MotionSequence(
                source="intergen",
                fps=30,
                frame_count=180,
                actor_count=2,
                positions=np.zeros((180, 1, 22, 3)),
            )

    def test_report_counts_and_json_shape(self) -> None:
        issue = MotionIssue(
            test_name="temporal_continuity",
            severity="critical",
            start_frame=255,
            end_frame=256,
            metric="angular_acceleration",
            value=47.3,
            threshold=20.0,
            message="Chunk seam",
            repairable=True,
            recommended_repair="seam_repair",
        )
        report = MotionQualityReport(
            overall_score=72.3,
            tests=[QualityTestResult("temporal_continuity", "FAIL", 61.0, [issue])],
        )
        serialized = report.to_dict()
        self.assertEqual(serialized["issue_count"], 1)
        self.assertEqual(serialized["critical_issue_count"], 1)
        self.assertEqual(serialized["repairable_issue_count"], 1)
        self.assertEqual(serialized["tests"][0]["issues"][0]["start_frame"], 255)


class BVHAdapterTests(unittest.TestCase):
    def test_pymotion_fk_preserves_root_shift_and_skeleton(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "synthetic.bvh"
            root = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
            rotations = np.zeros((2, len(BVH_NAMES), 3))
            write_bvh(path, root, rotations, fps=30)

            motion = load_bvh(path)

        self.assertEqual(motion.positions.shape, (2, 1, 22, 3))
        self.assertEqual(motion.rotations_6d.shape, (2, 1, 22, 6))
        self.assertEqual(motion.joint_names, BVH_NAMES)
        self.assertEqual(motion.fps, 30)
        np.testing.assert_allclose(
            motion.positions[1, 0] - motion.positions[0, 0],
            np.broadcast_to([1.0, 0.0, 0.0], (22, 3)),
            atol=1e-6,
        )


class NativeAdapterTests(unittest.TestCase):
    def test_intergen_pair_keeps_actor_axis(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / "person1.npy"
            second = Path(folder) / "person2.npy"
            np.save(first, np.zeros((3, 22, 3), dtype=np.float32))
            np.save(second, np.ones((3, 22, 3), dtype=np.float32))
            motion = load_intergen_joints([first, second])
        self.assertEqual(motion.positions.shape, (3, 2, 22, 3))
        np.testing.assert_array_equal(motion.positions[:, 0], 0)
        np.testing.assert_array_equal(motion.positions[:, 1], 1)

    def test_lodge_contacts_and_root_are_preserved(self) -> None:
        raw = np.zeros((3, 139), dtype=np.float32)
        raw[:, :4] = [[1, 0, 1, 0], [0, 1, 0, 1], [1, 1, 0, 0]]
        raw[:, 4:7] = [[0, 1, 0], [1, 1, 0], [2, 1, 0]]
        identity_6d = np.array([1, 0, 0, 0, 1, 0], dtype=np.float32)
        raw[:, 7:] = np.tile(identity_6d, 22)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "lodge.npy"
            np.save(path, raw)
            motion = load_lodge_npy(path)
        np.testing.assert_array_equal(motion.contacts[:, 0], raw[:, :4])
        np.testing.assert_array_equal(motion.root_translation[:, 0], raw[:, 4:7])
        np.testing.assert_allclose(
            motion.positions[2, 0] - motion.positions[0, 0],
            np.broadcast_to([2.0, 0.0, 0.0], (22, 3)),
            atol=1e-6,
        )
        self.assertEqual(motion.metadata["contact_joint_ids"], [3, 7, 4, 8])

    def test_config_and_registry(self) -> None:
        config = load_config()
        self.assertEqual(len(config["tests"]), 6)
        registry = QualityTestRegistry()
        registry.register("synthetic", lambda motion, settings: QualityTestResult("synthetic", "PASS", 100))
        motion = MotionSequence("synthetic", 30, 1, 1)
        self.assertEqual(registry.run("synthetic", motion, {}).score, 100)
        with self.assertRaises(ValueError):
            registry.register("synthetic", lambda motion, settings: QualityTestResult("synthetic", "PASS", 100))


if __name__ == "__main__":
    unittest.main()
