"""将 LODGE 动作数组直接转换为 BVH，避免不稳定的矩阵—轴角往返转换。"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np


SMPL_TO_BVH22 = [0, 1, 4, 7, 10, 2, 5, 8, 11, 3, 6, 9, 12, 15, 13, 16, 18, 20, 14, 17, 19, 21]
BVH_NAMES = [
    "Hips", "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToe",
    "RightUpLeg", "RightLeg", "RightFoot", "RightToe",
    "Spine", "Spine1", "Spine2", "Neck", "Head",
    "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
    "RightShoulder", "RightArm", "RightForeArm", "RightHand",
]
BVH_PARENTS = np.array(
    [-1, 0, 1, 2, 3, 0, 5, 6, 7, 0, 9, 10, 11, 12, 11, 14, 15, 16, 11, 18, 19, 20],
    dtype=np.int64,
)
BVH_OFFSETS = np.array(
    [
        [-0.001795, -0.223333, 0.028219], [0.069520, -0.091406, -0.006815],
        [0.034277, -0.375199, -0.004496], [-0.013596, -0.397961, -0.043693],
        [0.026358, -0.055791, 0.119288], [-0.067670, -0.090522, -0.004320],
        [-0.038290, -0.382569, -0.008850], [0.015774, -0.398415, -0.042312],
        [-0.025372, -0.048144, 0.123348], [-0.002533, 0.108963, -0.026696],
        [0.005487, 0.135180, 0.001092], [0.001457, 0.052922, 0.025425],
        [-0.002778, 0.213870, -0.042857], [0.005152, 0.064970, 0.051349],
        [0.070682, 0.113999, -0.034942], [0.131151, 0.020969, -0.017528],
        [0.253106, 0.006564, -0.026820], [0.234605, 0.008539, -0.006011],
        [-0.068819, 0.113488, -0.034688], [-0.134624, 0.021356, -0.020510],
        [-0.254539, 0.007921, -0.026620], [-0.237194, 0.009012, -0.006273],
    ],
    dtype=np.float64,
)


def _normalize(values: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(values, axis=-1, keepdims=True)
    return values / np.maximum(norm, 1e-8)


def rotation_6d_to_matrix(rot6d: np.ndarray) -> np.ndarray:
    a1 = rot6d[..., 0:3]
    a2 = rot6d[..., 3:6]
    b1 = _normalize(a1)
    b2 = _normalize(a2 - np.sum(b1 * a2, axis=-1, keepdims=True) * b1)
    b3 = np.cross(b1, b2)
    return np.stack((b1, b2, b3), axis=-2)


def axis_angle_to_matrix(axis_angle: np.ndarray) -> np.ndarray:
    angle = np.linalg.norm(axis_angle, axis=-1, keepdims=True)
    axis = np.divide(axis_angle, angle, out=np.zeros_like(axis_angle), where=angle > 1e-8)
    x, y, z = axis[..., 0], axis[..., 1], axis[..., 2]
    zero = np.zeros_like(x)
    skew = np.stack((zero, -z, y, z, zero, -x, -y, x, zero), axis=-1).reshape(axis.shape[:-1] + (3, 3))
    eye = np.eye(3, dtype=np.float64)
    matrix = eye + np.sin(angle)[..., None] * skew + (1.0 - np.cos(angle))[..., None] * np.matmul(skew, skew)
    return np.where((angle <= 1e-8)[..., None], eye, matrix)


def matrix_to_zyx_euler_degrees(matrix: np.ndarray) -> np.ndarray:
    sy = -matrix[..., 2, 0]
    y = np.arcsin(np.clip(sy, -1.0, 1.0))
    cy = np.cos(y)
    regular = np.abs(cy) > 1e-6
    x = np.where(
        regular,
        np.arctan2(matrix[..., 2, 1], matrix[..., 2, 2]),
        np.arctan2(-matrix[..., 1, 2], matrix[..., 1, 1]),
    )
    z = np.where(regular, np.arctan2(matrix[..., 1, 0], matrix[..., 0, 0]), 0.0)
    return np.degrees(np.stack((z, y, x), axis=-1))


def load_lodge_motion(npy_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """解析 LODGE 特征布局，返回根节点位置和 22 个关节的旋转矩阵。"""
    data = np.load(str(npy_path), allow_pickle=False)
    if data.ndim == 3 and data.shape[0] == 1:
        data = data.squeeze(0)
    elif data.ndim == 3 and data.shape[1] % 8 == 0:
        data = data.reshape(-1, data.shape[-1])
    if data.ndim != 2:
        raise ValueError(f"Expected 2D motion array, got shape={data.shape}")
    if data.shape[-1] in {319, 139}:
        data = data[:, 4:]

    if data.shape[-1] in {315, 135}:
        translation = data[:, :3]
        rot6d = data[:, 3:].reshape(data.shape[0], -1, 6)
        matrices = rotation_6d_to_matrix(rot6d)
    elif data.shape[-1] == 159:
        translation = data[:, :3]
        axis_angle = data[:, 3:].reshape(data.shape[0], -1, 3)
        matrices = axis_angle_to_matrix(axis_angle)
    else:
        raise ValueError(f"Unsupported LODGE motion shape: {data.shape}")
    if matrices.shape[1] < 22:
        raise ValueError(f"Expected at least 22 joints, got {matrices.shape[1]}")
    return translation.astype(np.float64), matrices[:, :22].astype(np.float64)


def write_bvh(output_path: Path, positions: np.ndarray, rotations: np.ndarray, fps: int,
              *, offsets: np.ndarray | None = None) -> None:
    """按固定 SMPL→BVH22 层级写出骨架、根位移和 ZYX 欧拉旋转。"""
    offsets = BVH_OFFSETS if offsets is None else np.asarray(offsets, dtype=np.float64)
    if offsets.shape != BVH_OFFSETS.shape or not np.isfinite(offsets).all():
        raise ValueError("BVH offsets must be a finite (22, 3) array")
    children = {index: [] for index in range(len(BVH_NAMES))}
    for index, parent in enumerate(BVH_PARENTS):
        if parent >= 0:
            children[int(parent)].append(index)
    save_order = []

    def write_joint(handle, joint_index: int, indent: str) -> None:
        save_order.append(joint_index)
        label = "ROOT" if BVH_PARENTS[joint_index] < 0 else "JOINT"
        handle.write(f"{indent}{label} {BVH_NAMES[joint_index]}\n{indent}{{\n")
        child_indent = indent + "\t"
        offset = offsets[joint_index]
        handle.write(f"{child_indent}OFFSET {offset[0]:.6f} {offset[1]:.6f} {offset[2]:.6f}\n")
        if joint_index == 0:
            handle.write(f"{child_indent}CHANNELS 6 Xposition Yposition Zposition Zrotation Yrotation Xrotation\n")
        else:
            handle.write(f"{child_indent}CHANNELS 3 Zrotation Yrotation Xrotation\n")
        if children[joint_index]:
            for child_index in children[joint_index]:
                write_joint(handle, child_index, child_indent)
        else:
            handle.write(f"{child_indent}End Site\n{child_indent}{{\n")
            handle.write(f"{child_indent}\tOFFSET 0.000000 0.000000 0.000000\n{child_indent}}}\n")
        handle.write(f"{indent}}}\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("HIERARCHY\n")
        write_joint(handle, 0, "")
        handle.write(f"MOTION\nFrames: {rotations.shape[0]}\nFrame Time: {1.0 / fps:.6f}\n")
        for frame in range(rotations.shape[0]):
            values = []
            for joint_index in save_order:
                if joint_index == 0:
                    values.extend(positions[frame].tolist())
                values.extend(rotations[frame, joint_index].tolist())
            handle.write(" ".join(f"{value:.6f}" for value in values) + "\n")


def convert_lodge_npy_to_bvh(npy_path: Path, output_path: Path, fps: int = 30, root_scale: float = 1.0) -> Path:
    translation, matrices = load_lodge_motion(npy_path)
    matrices_bvh = matrices[:, SMPL_TO_BVH22]
    euler_zyx = matrix_to_zyx_euler_degrees(matrices_bvh)
    write_bvh(output_path, translation * root_scale, euler_zyx, fps)
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert LODGE motion npy to a Rokoko/Mixamo-friendly BVH file.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--root-scale", type=float, default=1.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = convert_lodge_npy_to_bvh(Path(args.input), Path(args.output), args.fps, args.root_scale)
    print(f"saved BVH: {output}")


if __name__ == "__main__":
    main()
