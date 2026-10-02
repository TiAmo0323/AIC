"""Foot checks locate planted sliding, penetration, and floating."""

from __future__ import annotations

import numpy as np

from motionlint import MotionSequence
from motionlint.adapters.lodge_adapter import normalize_lodge_array
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect
from motionlint.tests import foot_sliding, ground_contact


def _motion(positions: np.ndarray, contacts: np.ndarray | None = None) -> MotionSequence:
    return MotionSequence(
        source="lodge", fps=30, frame_count=len(positions), actor_count=1,
        positions=positions, contacts=contacts,
        metadata={"up_axis": 1, "foot_joint_ids": [3, 7, 4, 8]},
    )


def test_planted_foot_slide_is_located() -> None:
    positions = np.zeros((15, 1, 22, 3))
    positions[5:10, 0, 3, 0] = np.arange(5) * 0.025
    positions[10:, 0, 3, 0] = 0.1
    contacts = np.ones((15, 1, 4))
    result = foot_sliding.check(_motion(positions, contacts), {"contact_height_m": 0.06, "horizontal_speed_m_s": 0.16})
    assert result.status == "FAIL"
    assert result.metrics["sliding_frame_count"] >= 4
    assert any(issue.joint_ids == [3] and issue.start_frame == 6 for issue in result.issues)


def test_penetration_and_floating_are_located() -> None:
    positions = np.zeros((20, 1, 22, 3))
    positions[5, 0, 3, 1] = -0.2
    positions[12, 0, 7, 1] = 0.3
    contacts = np.ones((20, 1, 4))
    result = ground_contact.check(_motion(positions, contacts), {"penetration_m": 0.035, "floating_m": 0.10, "contact_height_m": 0.06})
    assert result.status == "FAIL"
    assert any(issue.metric == "ground_penetration_m" and issue.start_frame == 5 for issue in result.issues)
    assert any(issue.metric == "floating_height_m" and issue.start_frame == 12 for issue in result.issues)


def test_clean_static_motion_passes_gate_but_injected_root_slide_fails() -> None:
    raw = np.zeros((30, 139), dtype=np.float32)
    raw[:, :4] = 1
    raw[:, 5] = 1
    raw[:, 7:] = np.tile([1, 0, 0, 0, 1, 0], 22)
    clean = inspect(normalize_lodge_array(raw))
    assert evaluate_gate(clean).status == "PASS"
    raw[:, 4] = np.arange(30) * 0.008
    sliding = inspect(normalize_lodge_array(raw))
    assert evaluate_gate(sliding).status == "FAIL"
    assert next(test for test in sliding.tests if test.test_name == "foot_sliding").score < 100
