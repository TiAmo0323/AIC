"""Run the configured test suite on a normalized motion."""

from __future__ import annotations

from pathlib import Path

from motionlint.core.config import load_config
from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.registry import TestRegistry
from motionlint.core.result import MotionQualityReport
from motionlint.core.provenance import input_hashes, rule_hash, evaluated_array_hashes
from motionlint.tests import collision, foot_sliding, ground_contact, motion_jerk, skeleton_integrity, temporal_continuity


def default_registry() -> TestRegistry:
    registry = TestRegistry()
    for name, module in (
        ("temporal_continuity", temporal_continuity),
        ("skeleton_integrity", skeleton_integrity),
        ("foot_sliding", foot_sliding),
        ("ground_contact", ground_contact),
        ("collision", collision),
        ("motion_jerk", motion_jerk),
    ):
        registry.register(name, module.check)
    return registry


def inspect(motion: MotionSequence, *, config_path: str | Path | None = None) -> MotionQualityReport:
    config = load_config(config_path) if config_path is not None else load_config()
    registry = default_registry()
    tests = [registry.run(name, motion, settings) for name, settings in config["tests"].items()]
    for test in tests:
        test.metrics["evaluation_status"] = "unavailable" if test.metrics.get("reason") else "evaluated"
        for issue in test.issues:
            issue.timestamp_seconds = round(issue.start_frame / motion.fps, 6)
    score = round(sum(test.score * float(config["tests"][test.test_name]["weight"]) for test in tests), 2)
    return MotionQualityReport(
        overall_score=score,
        tests=tests,
        metadata={"schema_version": 2, "source": motion.source, "fps": motion.fps, "frame_count": motion.frame_count, "actor_count": motion.actor_count, "config_version": config["version"],
                  "config_sha256": rule_hash(config), "input_sha256": input_hashes(motion.metadata),
                  "evaluated_array_sha256": evaluated_array_hashes(motion),
                  "stage": motion.metadata.get("stage", "repaired" if motion.metadata.get("repair") else "input"),
                  "evaluation_coverage": {test.test_name: test.metrics["evaluation_status"] for test in tests},
                  "geometry_source": motion.metadata.get("geometry_source", "native_joint_positions" if motion.source == "intergen" else "bvh_fk")},
    )
