"""Plan bounded foot corrections from evaluated character geometry."""
from pathlib import Path
import numpy as np

from motionlint.adapters.character_adapter import load_character
from motionlint.core.config import load_config
from motionlint.core.foot_support import estimate_support
from motionlint.repairs.foot_lock import _interval_anchors


def plan_character_feet(path: Path, *, config_path=None) -> dict:
    motion = load_character(path)
    config = load_config(config_path) if config_path else load_config()
    support = estimate_support(motion, config["tests"]["foot_sliding"])
    settings = config["repairs"]["foot_lock"]
    maximum = float(settings["max_correction_m"])
    chains, corrections, active = _interval_anchors(
        motion, support, [0, 2], maximum, int(settings["blend_frames"]),
        max_step=.8 * float(config["tests"]["foot_sliding"]["horizontal_speed_m_s"]) / motion.fps)
    if not np.isfinite(corrections).all() or np.linalg.norm(corrections, axis=-1).max() > maximum + 1e-8:
        raise ValueError("Invalid bounded character correction")
    world = np.load(path, allow_pickle=False)["world_rotation_matrices"]
    return {"version": 1, "character_path": str(path.resolve()), "frames": motion.frame_count,
            "fps": motion.fps, "frame_start": motion.metadata["frame_start"],
            "target_names": motion.metadata["target_names"], "joint_names": motion.joint_names,
            "reference_positions": motion.positions.tolist(), "chains": chains,
            "corrections_xz_m": corrections.tolist(), "active": active.tolist(),
            "foot_world_rotations": world[:, :, [chain[2] for chain in chains]].tolist(),
            "maximum_correction_m": maximum, "support_metrics": support.metrics,
            "limits": "No vertical or root correction; fixed foot-world orientation preserves the observed toe offset. Reachability and resulting quality must be rechecked."}
