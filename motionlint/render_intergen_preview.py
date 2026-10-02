"""Render two-person joint tracks with a fixed camera for QA comparisons."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

import imageio_ffmpeg
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FFMpegWriter
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motionlint.adapters.intergen_adapter import PARENTS


def render(paths: list[Path], output: Path, fps: int = 30, camera_reference: list[Path] | None = None) -> None:
    actors = [np.load(path, allow_pickle=False) for path in paths]
    if not actors or any(actor.shape != actors[0].shape for actor in actors):
        raise ValueError("Actor tracks must have matching (frames, 22, 3) shapes")
    if actors[0].ndim != 3 or actors[0].shape[1:] != (22, 3):
        raise ValueError("Expected joints22 tracks")
    data = np.stack(actors, axis=1)
    reference = np.stack([np.load(path, allow_pickle=False) for path in camera_reference], axis=1) if camera_reference else data
    extent = np.nanpercentile(reference[..., [0, 2]], [1, 99], axis=(0, 1, 2))
    center = extent.mean(axis=0)
    radius = max(1.5, float(np.max(extent[1] - extent[0])) * 0.65)
    y_min = float(np.nanpercentile(reference[..., 1], 1)) - 0.15
    y_max = float(np.nanpercentile(reference[..., 1], 99)) + 0.15
    fig, ax = plt.subplots(figsize=(5, 5), dpi=100)
    fig.patch.set_facecolor("#f6f8fb")
    ax.set_facecolor("#f6f8fb")
    ax.set_xlim(center[0] - radius, center[0] + radius)
    ax.set_ylim(y_min, y_max)
    ax.set_aspect("equal", adjustable="box")
    ax.axis("off")
    colors = ["#2476c5", "#ed7b4d"]
    lines = []
    for actor in range(data.shape[1]):
        actor_lines = []
        for joint, parent in enumerate(PARENTS):
            if parent < 0:
                continue
            (line,) = ax.plot([], [], color=colors[actor % len(colors)], lw=2.5, solid_capstyle="round")
            actor_lines.append((joint, parent, line))
        lines.append(actor_lines)
    output.parent.mkdir(parents=True, exist_ok=True)
    matplotlib.rcParams["animation.ffmpeg_path"] = os.getenv("MOTIONLINT_FFMPEG_EXE") or imageio_ffmpeg.get_ffmpeg_exe()
    writer = FFMpegWriter(fps=fps, codec="libx264", extra_args=["-pix_fmt", "yuv420p", "-movflags", "+faststart"])
    with writer.saving(fig, str(output), dpi=100):
        for frame in range(data.shape[0]):
            for actor, actor_lines in enumerate(lines):
                for joint, parent, line in actor_lines:
                    segment = data[frame, actor, [parent, joint]]
                    line.set_data(segment[:, 0], segment[:, 1])
            writer.grab_frame()
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--camera-reference", type=Path, nargs="+")
    args = parser.parse_args()
    render(args.input, args.output, args.fps, args.camera_reference)
