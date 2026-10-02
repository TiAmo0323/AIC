"""NumPy geometry primitives independent of motion generators."""
import numpy as np


def segment_point_distances(starts, ends, points):
    direction = np.asarray(ends) - starts
    amount = np.sum((points - starts) * direction, axis=-1) / np.maximum(np.sum(direction**2, axis=-1), 1e-8)
    amount = np.clip(amount, 0., 1.)
    closest = starts + amount[..., None] * direction
    return np.linalg.norm(closest - points, axis=-1), closest, amount
