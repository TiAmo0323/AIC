"""Read neutral rest joints from a locally licensed SMPL-X model with NumPy."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path

import numpy as np

from motionlint.core.skeleton import BVH_PARENTS, SMPL_TO_BVH22


DEFAULT_MODEL = (Path(__file__).resolve().parents[3] / "HumanAction-runtime" /
                 "InterGen" / "InterGen_master" / "human_models" / "smplx" / "SMPLX_NEUTRAL.npz")


def resolve_model(model_path: str | Path | None = None) -> Path | None:
    """Use the renderer's model when available; otherwise allow a BVH proxy."""
    configured = model_path or os.getenv("MOTIONLINT_SMPLX_MODEL") or os.getenv("LODGE_SMPLX_MODEL")
    path = Path(configured).expanduser().resolve() if configured else DEFAULT_MODEL
    if not path.is_file():
        if configured:
            raise FileNotFoundError(f"Configured SMPL-X geometry model not found: {path}")
        return None
    return path


@lru_cache(maxsize=4)
def _rest_offsets(path: str, modified_ns: int, size: int) -> np.ndarray:
    # The stat values invalidate cached geometry if the user replaces a model.
    with np.load(path, allow_pickle=False) as model:
        rest = model["J_regressor"] @ model["v_template"]
        parents = model["kintree_table"][0]
    order = np.array(SMPL_TO_BVH22)
    if rest.ndim != 2 or rest.shape[1] != 3 or len(rest) <= int(order.max()):
        raise ValueError("SMPL-X model has an incompatible joint regressor")
    if not np.array_equal(parents[order[1:]], order[BVH_PARENTS[1:]]):
        raise ValueError("SMPL-X model has an incompatible body skeleton")
    offsets = rest[order].astype(np.float64)
    offsets[1:] -= rest[order[BVH_PARENTS[1:]]]
    offsets.setflags(write=False)
    return offsets


def rest_offsets(model_path: str | Path) -> np.ndarray:
    path = Path(model_path).resolve()
    stat = path.stat()
    return _rest_offsets(str(path), stat.st_mtime_ns, stat.st_size).copy()
