"""Common in-memory representation for one or more synchronized actors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class MotionSequence:
    """A motion with the frame and actor axes kept explicit.

    All populated per-frame arrays start with ``(frame_count, actor_count)``.
    Joint arrays then use the skeleton joint order recorded in ``joint_names``.
    Arrays absent from a source format remain ``None``; they are not inferred
    from an unrelated representation.
    """

    source: str
    fps: float
    frame_count: int
    actor_count: int
    positions: np.ndarray | None = None  # (T, A, J, 3), global
    rotations_6d: np.ndarray | None = None  # (T, A, J, 6), first two matrix rows
    rotation_matrices: np.ndarray | None = None  # (T, A, J, 3, 3), local
    root_translation: np.ndarray | None = None  # (T, A, 3)
    contacts: np.ndarray | None = None  # (T, A, C)
    joint_names: list[str] | None = None
    skeleton_type: str | None = None
    prompt: str | None = None
    music_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("source must be non-empty")
        if not np.isfinite(self.fps) or self.fps <= 0:
            raise ValueError("fps must be a positive finite number")
        if self.frame_count < 1 or self.actor_count < 1:
            raise ValueError("frame_count and actor_count must be positive")

        joint_count: int | None = None
        for name, trailing_shape in (
            ("positions", (3,)),
            ("rotations_6d", (6,)),
            ("rotation_matrices", (3, 3)),
        ):
            value = getattr(self, name)
            if value is None:
                continue
            array = np.asarray(value)
            if not np.isfinite(array).all():
                raise ValueError(f"{name} contains NaN or Inf")
            expected_prefix = (self.frame_count, self.actor_count)
            if array.ndim != len(trailing_shape) + 3 or array.shape[:2] != expected_prefix or array.shape[-len(trailing_shape):] != trailing_shape:
                raise ValueError(f"{name} must have shape (T, A, J, {', '.join(map(str, trailing_shape))}); got {array.shape}")
            if joint_count is not None and array.shape[2] != joint_count:
                raise ValueError(f"{name} has {array.shape[2]} joints; expected {joint_count}")
            joint_count = array.shape[2]
            setattr(self, name, array)

        if self.root_translation is not None:
            root = np.asarray(self.root_translation)
            if not np.isfinite(root).all():
                raise ValueError("root_translation contains NaN or Inf")
            if root.shape != (self.frame_count, self.actor_count, 3):
                raise ValueError(f"root_translation must have shape (T, A, 3); got {root.shape}")
            self.root_translation = root

        if self.contacts is not None:
            contacts = np.asarray(self.contacts)
            if not np.isfinite(contacts).all():
                raise ValueError("contacts contains NaN or Inf")
            if contacts.ndim != 3 or contacts.shape[:2] != (self.frame_count, self.actor_count):
                raise ValueError(f"contacts must have shape (T, A, C); got {contacts.shape}")
            self.contacts = contacts

        if self.joint_names is not None and joint_count is not None and len(self.joint_names) != joint_count:
            raise ValueError(f"joint_names has {len(self.joint_names)} entries; expected {joint_count}")

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.fps
