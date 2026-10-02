"""Render LODGE 139D dance motion with an officially downloaded SMPL-X model.

The model is read from the sibling HumanAction-runtime directory and is never
copied into this repository. This replaces the upstream render.py's Linux-only
paths and works with the platform's existing ``--modir`` API invocation.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pyrender
import smplx
import torch
import trimesh


DEFAULT_MODEL = (
    Path(__file__).resolve().parents[2]
    / "HumanAction-runtime"
    / "InterGen"
    / "InterGen_master"
    / "human_models"
    / "smplx"
    / "SMPLX_NEUTRAL.npz"
)


def _camera_pose(position: np.ndarray, target: np.ndarray) -> np.ndarray:
    z = position - target
    z /= np.linalg.norm(z)
    x = np.cross(np.array([0.0, 1.0, 0.0]), z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    pose = np.eye(4)
    pose[:3, :3] = np.stack((x, y, z), axis=1)
    pose[:3, 3] = position
    return pose


def _motion_to_smplx(motion: np.ndarray) -> tuple[torch.Tensor, torch.Tensor]:
    if motion.ndim != 2 or motion.shape[1] != 139:
        raise ValueError(f"Expected LODGE motion with shape (frames, 139); got {motion.shape}")
    # LODGE uses four contact channels, XYZ translation, then 22 joint rotations
    # in the same 6D format consumed by the upstream render.py.
    lodge_root = Path(__file__).resolve().parents[2] / "HumanAction-runtime" / "LODGE-main"
    if str(lodge_root) not in sys.path:
        sys.path.insert(0, str(lodge_root))
    from pytorch3d.transforms import matrix_to_axis_angle, rotation_6d_to_matrix

    rotations = torch.from_numpy(np.ascontiguousarray(motion[:, 7:])).reshape(-1, 22, 6)
    axis_angle = matrix_to_axis_angle(rotation_6d_to_matrix(rotations)).reshape(-1, 66)
    translation = torch.from_numpy(np.ascontiguousarray(motion[:, 4:7]))
    return translation.float(), axis_angle.float()


def render(input_path: Path, output_path: Path, model_path: Path, fps: int, size: int, max_frames: int) -> None:
    if not model_path.is_file():
        raise FileNotFoundError(f"SMPL-X model not found: {model_path}")
    motion = np.load(input_path, allow_pickle=False)
    if max_frames > 0:
        motion = motion[:max_frames]
    if len(motion) == 0:
        raise ValueError(f"No motion frames: {input_path}")
    translation, axis_angle = _motion_to_smplx(motion)
    batch_size = 8
    model = smplx.SMPLX(str(model_path), use_pca=False, flat_hand_mean=True, batch_size=batch_size).eval()

    scene = pyrender.Scene(bg_color=[0.96, 0.97, 0.98, 1.0], ambient_light=[0.52, 0.52, 0.52])
    camera_pose = _camera_pose(np.array([0.0, 1.05, 3.3]), np.array([0.0, 0.9, 0.0]))
    scene.add(pyrender.PerspectiveCamera(yfov=np.pi / 4), pose=camera_pose)
    scene.add(pyrender.DirectionalLight(color=np.ones(3), intensity=3.0), pose=camera_pose)
    fill_pose = _camera_pose(np.array([-2.0, 3.0, 1.0]), np.array([0.0, 0.8, 0.0]))
    scene.add(pyrender.DirectionalLight(color=np.ones(3), intensity=1.5), pose=fill_pose)
    floor = trimesh.creation.box(extents=(7.0, 0.02, 7.0))
    floor.apply_translation((0.0, -0.035, 0.0))
    scene.add(
        pyrender.Mesh.from_trimesh(
            floor,
            material=pyrender.MetallicRoughnessMaterial(
                baseColorFactor=(0.85, 0.88, 0.92, 1.0), metallicFactor=0.0, roughnessFactor=1.0
            ),
        )
    )
    human_material = pyrender.MetallicRoughnessMaterial(
        baseColorFactor=(0.28, 0.52, 0.78, 1.0), metallicFactor=0.0, roughnessFactor=0.8
    )

    ffmpeg = os.getenv("LODGE_FFMPEG_EXE") or shutil.which("ffmpeg")
    if not ffmpeg:
        raise FileNotFoundError("FFmpeg not found; set LODGE_FFMPEG_EXE")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        str(ffmpeg), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{size}x{size}", "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264",
        "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(output_path),
    ]
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    renderer = None
    try:
        renderer = pyrender.OffscreenRenderer(size, size)
        for start in range(0, len(motion), batch_size):
            stop = min(start + batch_size, len(motion))
            trans_batch = translation[start:stop]
            pose_batch = axis_angle[start:stop]
            if stop - start < batch_size:
                padding = batch_size - (stop - start)
                trans_batch = torch.cat((trans_batch, trans_batch[-1:].expand(padding, -1)))
                pose_batch = torch.cat((pose_batch, pose_batch[-1:].expand(padding, -1)))
            with torch.no_grad():
                vertices = model(
                    transl=trans_batch,
                    global_orient=pose_batch[:, :3],
                    body_pose=pose_batch[:, 3:],
                ).vertices.numpy()
            for frame_vertices in vertices[:stop - start]:
                mesh = trimesh.Trimesh(vertices=frame_vertices, faces=model.faces, process=False)
                node = scene.add(pyrender.Mesh.from_trimesh(mesh, material=human_material, smooth=True))
                try:
                    color, _ = renderer.render(scene)
                    assert encoder.stdin is not None
                    encoder.stdin.write(color.tobytes())
                finally:
                    scene.remove_node(node)
            print(f"Rendered {stop}/{len(motion)} frames", flush=True)
        assert encoder.stdin is not None
        encoder.stdin.close()
        errors = encoder.stderr.read().decode("utf-8", errors="replace") if encoder.stderr else ""
        if encoder.wait() != 0:
            raise RuntimeError(f"FFmpeg failed: {errors[-1000:]}")
    except Exception:
        if encoder.poll() is None:
            encoder.kill()
            encoder.wait()
        output_path.unlink(missing_ok=True)
        raise
    finally:
        if renderer is not None:
            renderer.delete()
    print(f"Saved {output_path}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--modir", type=Path)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mode", default="smplx", choices=["smplx"])
    parser.add_argument("--device", default="0")
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--size", type=int, default=int(os.getenv("LODGE_SMPLX_RENDER_SIZE", "720")))
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--model", type=Path, default=Path(os.getenv("LODGE_SMPLX_MODEL", str(DEFAULT_MODEL))))
    args = parser.parse_args()
    if args.fps <= 0 or args.size < 128 or args.size % 2:
        parser.error("FPS must be positive and size must be an even number >= 128")
    if args.input:
        if not args.output:
            parser.error("--output is required with --input")
        render(args.input, args.output, args.model, args.fps, args.size, args.max_frames)
        return
    if not args.modir:
        parser.error("Provide --modir or --input and --output")
    motion_files = sorted(args.modir.glob("*.npy"))
    motion_files = [path for path in motion_files if not path.stem.endswith(".raw")]
    if not motion_files:
        raise FileNotFoundError(f"No NPY motion files in {args.modir}")
    for path in motion_files:
        render(path, args.modir / "video" / f"{path.stem}-smplx.mp4", args.model, args.fps, args.size, args.max_frames)


if __name__ == "__main__":
    main()
