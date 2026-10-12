"""CPU BVH export, with explicit hierarchy, units and fractional FPS."""
from pathlib import Path

import numpy as np

from motionlint.core.skeleton import BVH_NAMES, BVH_PARENTS, BVH_OFFSETS


def matrix_to_zyx_euler_degrees(matrix):
    # R = Rz @ Ry @ Rx; choose the equivalent solution at gimbal lock.
    matrix = np.asarray(matrix, dtype=float)
    y = np.arcsin(np.clip(-matrix[..., 2, 0], -1, 1))
    regular = np.abs(np.cos(y)) > 1e-7
    x = np.where(regular, np.arctan2(matrix[..., 2, 1], matrix[..., 2, 2]),
                 np.arctan2(-matrix[..., 1, 2], matrix[..., 1, 1]))
    z = np.where(regular, np.arctan2(matrix[..., 1, 0], matrix[..., 0, 0]), 0.)
    return np.degrees(np.stack((z, y, x), axis=-1))


def write_bvh(path, positions, rotations, fps, *, offsets=None, names=None, parents=None):
    """Write metre-valued root positions/offsets and ZYX Euler degrees."""
    names = list(BVH_NAMES if names is None else names)
    parents = np.asarray(BVH_PARENTS if parents is None else parents, dtype=int)
    offsets = np.asarray(BVH_OFFSETS if offsets is None else offsets, dtype=float)
    positions, rotations = np.asarray(positions), np.asarray(rotations)
    n = len(names)
    if (not np.isfinite(fps) or fps <= 0 or positions.shape != (len(rotations), 3)
            or rotations.shape != (len(positions), n, 3) or offsets.shape != (n, 3)
            or parents.shape != (n,) or not n or parents[0] != -1
            or any(parent < 0 or parent >= joint for joint, parent in enumerate(parents[1:], 1))
            or len(set(names)) != n or any(not name or any(c.isspace() or c in '{}' for c in name) for name in names)
            or not all(np.isfinite(value).all() for value in (positions, rotations, offsets))):
        raise ValueError("BVH export needs finite arrays, positive FPS and a connected parent-first hierarchy")
    children = [np.flatnonzero(parents == joint).tolist() for joint in range(n)]
    order, lines = [], ["HIERARCHY"]

    def joint(index, depth):
        pad, inner = '\t' * depth, '\t' * (depth + 1)
        order.append(index)
        lines.extend([f"{pad}{'ROOT' if index == 0 else 'JOINT'} {names[index]}", pad + '{',
                      inner + 'OFFSET ' + ' '.join(f'{value:.10f}' for value in offsets[index]),
                      inner + ('CHANNELS 6 Xposition Yposition Zposition ' if index == 0 else 'CHANNELS 3 ')
                      + 'Zrotation Yrotation Xrotation'])
        for child in children[index]:
            joint(child, depth + 1)
        if not children[index]:
            lines.extend([inner + 'End Site', inner + '{', inner + '\tOFFSET 0 0 0', inner + '}'])
        lines.append(pad + '}')

    joint(0, 0)
    lines.extend(['MOTION', f'Frames: {len(positions)}', f'Frame Time: {1 / fps:.12f}'])
    for frame in range(len(positions)):
        values = np.concatenate((positions[frame], rotations[frame, order].reshape(-1)))
        lines.append(' '.join(f'{value:.10f}' for value in values))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
