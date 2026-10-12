"""Measure both outputs on the input's fixed support intervals."""
from __future__ import annotations

import numpy as np

from motionlint.core.foot_support import estimate_support


def compare_support(original, candidate, settings):
    if (original.positions.shape != candidate.positions.shape or original.fps != candidate.fps
            or original.joint_names != candidate.joint_names or original.actor_count != candidate.actor_count
            or original.metadata.get("up_axis", 1) != candidate.metadata.get("up_axis", 1)):
        raise ValueError("Fixed support comparison needs synchronized, matching motions")
    support = estimate_support(original, settings)
    axes = [axis for axis in range(3) if axis != int(original.metadata.get("up_axis", 1))]
    threshold = float(settings["horizontal_speed_m_s"])
    distances = [np.linalg.norm(np.diff(m.positions[:, :, support.feet][..., axes], axis=0), axis=-1)
                 for m in (original, candidate)]
    rows = []
    for actor in range(original.actor_count):
        for local, joint in enumerate(support.feet):
            mask = support.intervals[:, actor, local]
            if not mask.any():
                continue
            paths = [float(d[:, actor, local][mask].sum()) for d in distances]
            peaks = [float(d[:, actor, local][mask].max() * original.fps) for d in distances]
            counts = [int(np.count_nonzero(d[:, actor, local][mask] * original.fps > threshold)) for d in distances]
            tolerance = 1e-5 + 1e-6 * paths[0]
            up = int(original.metadata.get('up_axis', 1))
            height_limit = np.maximum(original.positions[:-1, actor, joint, up], original.positions[1:, actor, joint, up]) + float(settings['contact_height_m'])
            lost = (np.maximum(candidate.positions[:-1, actor, joint, up], candidate.positions[1:, actor, joint, up]) > height_limit + 1e-6) & mask
            if original.contacts is not None and original.contacts.shape[2] == len(support.feet):
                if candidate.contacts is None or candidate.contacts.shape != original.contacts.shape:
                    lost |= mask
                else:
                    lost |= mask & ((candidate.contacts[:-1, actor, local] <= .5) | (candidate.contacts[1:, actor, local] <= .5))
            rows.append({"actor_id": actor, "joint_id": joint,
                         "joint_name": original.joint_names[joint], "support_interval_count": int(mask.sum()),
                         "distance_before_m": paths[0], "distance_after_m": paths[1],
                         "sliding_intervals_before": counts[0], "sliding_intervals_after": counts[1],
                         "peak_speed_before_m_s": peaks[0], "peak_speed_after_m_s": peaks[1],
                         "distance_tolerance_m": tolerance,
                         "contact_loss_interval_count": int(lost.sum()),
                         "distance_not_worsened": paths[1] <= paths[0] + tolerance,
                         "sliding_not_worsened": counts[1] <= counts[0],
                         "peak_not_worsened": peaks[1] <= max(peaks[0], threshold) + 1e-5})
    counts = [sum(r[f"sliding_intervals_{phase}"] for r in rows) for phase in ("before", "after")]
    paths = [sum(r[f"distance_{phase}_m"] for r in rows) for phase in ("before", "after")]
    not_worsened = all(r["distance_not_worsened"] and r["sliding_not_worsened"] and r["peak_not_worsened"] and not r['contact_loss_interval_count'] for r in rows)
    return {"original_support_sliding_before": counts[0], "original_support_sliding_after": counts[1],
            "original_support_distance_before_m": paths[0], "original_support_distance_after_m": paths[1],
            "original_support_distance_reduction_ratio": (paths[0] - paths[1]) / paths[0] if paths[0] > 1e-10 else None,
            "support_joint_interval_count": int(support.intervals.sum()), "per_foot": rows,
            "distance_not_worsened": all(r["distance_not_worsened"] for r in rows),
            "contact_preserved": not any(r['contact_loss_interval_count'] for r in rows),
            "not_worsened": not_worsened,
            "improved": bool(rows) and not_worsened and paths[1] < paths[0] - 1e-5}
