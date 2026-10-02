"""Floor provenance shared by contact checks; no horizontal-speed filtering."""
import numpy as np


def floor_heights(motion, heights, settings):
    explicit = motion.metadata.get("floor_height_m")
    if settings.get("use_explicit_floor", False) and explicit is not None:
        floor = np.broadcast_to(np.asarray(explicit, dtype=float), (motion.actor_count,)).copy()
        if not np.isfinite(floor).all():
            raise ValueError("Explicit floor height must be finite")
        return floor, "explicit_metadata"
    return np.percentile(heights, 5, axis=(0, 2)), "estimated_fifth_percentile"
