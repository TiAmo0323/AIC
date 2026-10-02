"""Normalize LODGE's 139D motion, retaining contact channels."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from motionlint.core.skeleton import BVH_NAMES, BVH_OFFSETS, BVH_PARENTS, SMPL_TO_BVH22
from motionlint.adapters.smplx_geometry import resolve_model, rest_offsets
from motionlint.core.motion_sequence import MotionSequence


def load_lodge_npy(path: str | Path, *, fps: float = 30, model_path: str | Path | None = None) -> MotionSequence:
    path = Path(path).expanduser().resolve()
    raw = np.load(path, allow_pickle=False)
    return normalize_lodge_array(raw, fps=fps, source_path=path, model_path=model_path)


def normalize_lodge_array(raw: np.ndarray, *, fps: float = 30, source_path: str | Path | None = None, model_path: str | Path | None = None) -> MotionSequence:
    try:
        from pymotion.ops.skeleton import fk
        from pymotion.rotations import ortho6d, quat
    except ImportError as exc:
        raise ImportError("LODGE adapter requires upc-pymotion==0.3.4") from exc

    raw = np.asarray(raw)
    if raw.ndim != 2 or raw.shape[1] not in {135, 139, 315, 319}:
        raise ValueError(f"Expected LODGE motion (T, 135/139/315/319); got {raw.shape}")
    has_contacts = raw.shape[1] in {139, 319}
    contact_count = 4 if has_contacts else 0
    root = raw[:, contact_count:contact_count + 3].astype(np.float64)
    rotations_smpl = raw[:, contact_count + 3:].reshape(len(raw), -1, 6)
    rotations = rotations_smpl[:, SMPL_TO_BVH22].astype(np.float64)

    # LODGE / PyTorch3D store the first two matrix rows. PyMotion expects
    # the first two columns in (..., 3, 2), so transpose both input and output.
    column_6d = rotations.reshape(len(raw), 22, 2, 3).swapaxes(-1, -2)
    matrices = ortho6d.to_matrix(column_6d).swapaxes(-1, -2)
    quaternions = quat.from_matrix(matrices)
    model = resolve_model(model_path)
    offsets = rest_offsets(model) if model is not None else BVH_OFFSETS.copy()
    # SMPL-X transl offsets the body's rest pelvis; PyMotion expects the
    # pelvis position itself. A constant root offset does not alter motion.
    pelvis = root + offsets[0] if model is not None else root
    positions, _ = fk(quaternions, pelvis, offsets, BVH_PARENTS)

    return MotionSequence(
        source="lodge",
        fps=fps,
        frame_count=len(raw),
        actor_count=1,
        positions=positions[:, np.newaxis],
        rotations_6d=rotations[:, np.newaxis],
        rotation_matrices=matrices[:, np.newaxis],
        root_translation=root[:, np.newaxis],
        contacts=raw[:, np.newaxis, :4].copy() if has_contacts else None,
        joint_names=BVH_NAMES.copy(),
        skeleton_type="smpl_22_bvh_order",
        metadata={
            "source_path": str(source_path) if source_path is not None else None,
            "feature_count": int(raw.shape[1]),
            "parents": BVH_PARENTS.tolist(),
            "offsets": offsets.tolist(),
            "geometry_source": "smplx_neutral_model" if model is not None else "fixed_bvh_proxy",
            "geometry_model_path": str(model) if model is not None else None,
            "up_axis": 1,
            "foot_joint_ids": [3, 7, 4, 8],
            "left_foot_joint_ids": [3, 4],
            "right_foot_joint_ids": [7, 8],
            "contact_joint_ids": [3, 7, 4, 8] if has_contacts else [],
        },
    )
