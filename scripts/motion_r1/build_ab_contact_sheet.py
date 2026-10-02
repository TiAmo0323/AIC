"""【离线实验工具，未应用于实际生产逻辑链路】生成两段实验视频的时间对齐联系表。"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import List

import cv2
from PIL import Image, ImageDraw


def _read_frame(video_path: Path, time_seconds: float) -> Image.Image:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 1)
        frame_index = min(max(int(round(time_seconds * fps)), 0), frame_count - 1)
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"Cannot read frame {frame_index} from: {video_path}")
        return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    finally:
        capture.release()


def _fit(frame: Image.Image, width: int) -> Image.Image:
    height = max(1, round(frame.height * width / frame.width))
    return frame.resize((width, height), Image.Resampling.LANCZOS)


def build_sheet(
    video_a: Path,
    video_b: Path,
    output: Path,
    times: List[float],
    label_a: str,
    label_b: str,
    cell_width: int,
) -> None:
    rows = []
    for video_path in (video_a, video_b):
        rows.append([_fit(_read_frame(video_path, value), cell_width) for value in times])

    cell_height = max(frame.height for row in rows for frame in row)
    label_height = 36
    time_height = 24
    sheet = Image.new(
        "RGB",
        (cell_width * len(times), (label_height + cell_height + time_height) * 2),
        "white",
    )
    draw = ImageDraw.Draw(sheet)
    for row_index, (label, frames) in enumerate(zip((label_a, label_b), rows)):
        row_top = row_index * (label_height + cell_height + time_height)
        draw.text((8, row_top + 9), label, fill="black")
        for column, (time_seconds, frame) in enumerate(zip(times, frames)):
            left = column * cell_width
            sheet.paste(frame, (left, row_top + label_height))
            draw.text(
                (left + 8, row_top + label_height + cell_height + 4),
                f"t={time_seconds:.1f}s",
                fill="black",
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output, quality=92)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-a", type=Path, required=True)
    parser.add_argument("--video-b", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--label-a", default="A / baseline")
    parser.add_argument("--label-b", default="B / planner")
    parser.add_argument("--times", type=float, nargs="+", default=[0.0, 1.5, 3.0, 4.5, 5.9])
    parser.add_argument("--cell-width", type=int, default=320)
    args = parser.parse_args()
    build_sheet(
        args.video_a,
        args.video_b,
        args.output,
        args.times,
        args.label_a,
        args.label_b,
        max(160, min(args.cell_width, 640)),
    )
    print(f"Saved contact sheet: {args.output.resolve()}")


if __name__ == "__main__":
    main()
