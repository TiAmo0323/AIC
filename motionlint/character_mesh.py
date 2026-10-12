"""Additional actual mesh measurements, separate from six skeleton checks."""
import numpy as np


def measure_mesh(path, fps):
    with np.load(path, allow_pickle=False) as archive:
        needed = {'mesh_min_height_m', 'mesh_penetration_vertex_fraction', 'sole_positions'}
        if not needed <= set(archive.files):
            return {'status': 'unavailable', 'reason': 'This historical export contains bones only'}
        height, fraction, sole = [archive[name] for name in ('mesh_min_height_m', 'mesh_penetration_vertex_fraction', 'sole_positions')]
    rows = []
    for actor in range(sole.shape[1]):
        for side in range(2):
            p = sole[:, actor, side]
            if not np.isfinite(p).all():
                rows.append({'actor_id': actor, 'side': side, 'status': 'unavailable', 'reason': 'No mapped skin-weight sole vertices'})
                continue
            distance = np.linalg.norm(np.diff(p[:, [0, 2]], axis=0), axis=-1)
            vertical = np.abs(np.diff(p[:, 1])) * fps
            contact = (p[:-1, 1] <= .06) & (p[1:, 1] <= .06) & (vertical <= .15)
            rows.append({'actor_id': actor, 'side': side, 'status': 'evaluated',
                         'contact_interval_count': int(contact.sum()), 'height_m': p[:, 1].tolist(),
                         'trajectory_m': p.tolist(), 'total_horizontal_distance_m': float(distance.sum()),
                         'scene_plane_contact_distance_m': float(distance[contact].sum()),
                         'scene_plane_contact_peak_speed_m_s': float(distance[contact].max()*fps) if contact.any() else None})
    return {'schema_version': 3, 'status': 'evaluated' if np.isfinite(height).all() else 'partially_evaluated',
            'evidence_type': 'actual_deformed_mesh_vertices', 'separate_from_skeleton_quality_gate': True,
            'max_scene_plane_penetration_m': float(np.maximum(-height, 0).max()) if np.isfinite(height).all() else None,
            'minimum_vertex_height_m': height.tolist(), 'penetrating_vertex_fraction': fraction.tolist(), 'per_sole': rows,
            'limits': 'Plane/vertex penetration and sole trajectory; no triangle-to-triangle mesh collision or human labels'}
