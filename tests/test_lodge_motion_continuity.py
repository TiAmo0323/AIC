# LODGE 动作连续性回归测试。
# 验证 6D 旋转转换、分块边界平滑、帧数/contact 保持和 BVH 转换入口；
# 数值通过只能证明数据连续性，不代替 Blender 成片的主观验收。
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.motion_continuity import (
    matrix_to_rotation_6d,
    rotation_6d_to_matrix,
    smooth_chunk_seams,
)


def load_converter():
    path = PROJECT_ROOT / "LODGE_api" / "lodge2bvh.py"
    spec = importlib.util.spec_from_file_location("platform_lodge2bvh", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def z_rotation(angle):
    cosine = np.cos(angle)
    sine = np.sin(angle)
    matrix = np.zeros(angle.shape + (3, 3), dtype=np.float64)
    matrix[..., 0, 0] = cosine
    matrix[..., 0, 1] = -sine
    matrix[..., 1, 0] = sine
    matrix[..., 1, 1] = cosine
    matrix[..., 2, 2] = 1.0
    return matrix


def root_step_degrees(motion):
    matrices = rotation_6d_to_matrix(motion[:, 7:13])
    relative = np.einsum("...ji,...jk->...ik", matrices[:-1], matrices[1:])
    trace = np.trace(relative, axis1=-2, axis2=-1)
    return np.degrees(np.arccos(np.clip((trace - 1.0) * 0.5, -1.0, 1.0)))


def synthetic_motion():
    frames = 600
    motion = np.zeros((frames, 139), dtype=np.float32)
    motion[:, :4] = np.arange(frames)[:, None] % 2
    motion[:, 4] = np.arange(frames) * 0.001
    motion[256:, 4] += 0.2
    angles = np.arange(frames) * 0.002
    angles[256:] += 0.8
    matrices = np.repeat(z_rotation(angles)[:, None], 22, axis=1)
    motion[:, 7:] = matrix_to_rotation_6d(matrices).reshape(frames, -1)
    return motion


def test_seam_smoothing():
    motion = synthetic_motion()
    before_step = root_step_degrees(motion)
    before_root_velocity = np.diff(motion[:, 4:7], axis=0)
    before_root_accel = np.linalg.norm(np.diff(before_root_velocity, axis=0), axis=1)
    smoothed, report = smooth_chunk_seams(motion, chunk_frames=256, window_frames=8)
    after_step = root_step_degrees(smoothed)
    after_root_velocity = np.diff(smoothed[:, 4:7], axis=0)
    after_root_accel = np.linalg.norm(np.diff(after_root_velocity, axis=0), axis=1)

    assert smoothed.shape == motion.shape
    assert smoothed.dtype == motion.dtype
    assert np.array_equal(smoothed[:, :4], motion[:, :4])
    assert np.array_equal(smoothed[:248], motion[:248])
    assert np.array_equal(smoothed[264:504], motion[264:504])
    assert [item["boundary_frame"] for item in report["boundaries"]] == [256, 512]
    assert after_step[255] < before_step[255] * 0.25
    assert after_root_accel[254] < before_root_accel[254] * 0.25
    assert report["contact_channels_preserved"] is True

    matrices = rotation_6d_to_matrix(smoothed[:, 7:].reshape(len(smoothed), 22, 6))
    identity = np.eye(3)
    orthogonality = np.max(np.abs(np.swapaxes(matrices, -1, -2) @ matrices - identity))
    determinant_error = np.max(np.abs(np.linalg.det(matrices) - 1.0))
    assert orthogonality < 1e-5
    assert determinant_error < 1e-5
    return report


def test_converter_matrix_passthrough():
    converter = load_converter()
    frames = 8
    axes = np.array([[1.0, 0.2, -0.1], [1.0, 0.2, -0.1]], dtype=np.float64)
    axes /= np.linalg.norm(axes, axis=1, keepdims=True)
    angles = np.linspace(np.pi - 2e-7, np.pi + 2e-7, frames)
    axis = np.repeat(axes[:1], frames, axis=0)
    x, y, z = axis[:, 0], axis[:, 1], axis[:, 2]
    zero = np.zeros(frames)
    skew = np.stack((zero, -z, y, z, zero, -x, -y, x, zero), axis=-1).reshape(frames, 3, 3)
    matrices = np.eye(3) + np.sin(angles)[:, None, None] * skew + (1 - np.cos(angles))[:, None, None] * (skew @ skew)

    motion = np.zeros((frames, 139), dtype=np.float64)
    repeated = np.repeat(matrices[:, None], 22, axis=1)
    motion[:, 7:] = matrix_to_rotation_6d(repeated).reshape(frames, -1)
    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "near_pi.npy"
        np.save(path, motion)
        _, loaded = converter.load_lodge_motion(path)
    error = float(np.max(np.abs(loaded - repeated)))
    assert error < 1e-6
    return {"near_pi_matrix_max_abs_error": error}


def test_api_motion_preparation():
    api_path = PROJECT_ROOT / "LODGE_api" / "lodge_async_api.py"
    spec = importlib.util.spec_from_file_location("lodge_motion_api_test", api_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_values = {
        name: os.environ.get(name)
        for name in (
            "LODGE_MOTION_SEAM_SMOOTHING",
            "LODGE_MOTION_CHUNK_FRAMES",
            "LODGE_MOTION_SEAM_WINDOW_FRAMES",
        )
    }
    try:
        os.environ["LODGE_MOTION_SEAM_SMOOTHING"] = "1"
        os.environ["LODGE_MOTION_CHUNK_FRAMES"] = "256"
        os.environ["LODGE_MOTION_SEAM_WINDOW_FRAMES"] = "8"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "motion.npy"
            source = synthetic_motion()
            np.save(path, source)
            message = module._smooth_motion_chunk_seams_inplace(path)
            raw_path = path.with_name("motion.raw.npy")
            report_path = path.with_name("motion.motion_postprocess.json")
            processed = np.load(path)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            assert "Smoothed 2 LODGE chunk seam(s)" in message
            assert np.array_equal(np.load(raw_path), source)
            assert np.array_equal(processed[:, :4], source[:, :4])
            assert len(report["boundaries"]) == 2
            assert report["raw_motion"] == str(raw_path.resolve())
    finally:
        for name, value in original_values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    return {"raw_motion_preserved": True, "report_written": True}


def main():
    seam_report = test_seam_smoothing()
    converter_report = test_converter_matrix_passthrough()
    api_report = test_api_motion_preparation()
    print(json.dumps({
        "seam_smoothing": seam_report,
        "converter": converter_report,
        "api_integration": api_report,
    }, indent=2))


if __name__ == "__main__":
    main()
