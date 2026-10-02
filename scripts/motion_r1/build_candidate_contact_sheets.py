#!/usr/bin/env python3
"""【离线实验工具，未应用于实际生产逻辑链路】从审计清单生成候选时间联系表。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Sequence, Tuple

import cv2
import numpy as np


SAMPLE_FRACTIONS = (0.10, 0.35, 0.60, 0.85)
FRAME_WIDTH = 240
LABEL_WIDTH = 190
HEADER_HEIGHT = 30


def _read_frame(capture: cv2.VideoCapture, frame_index: int) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = capture.read()
    if not ok or frame is None:
        raise RuntimeError(f"Could not read video frame {frame_index}")
    height, width = frame.shape[:2]
    target_height = max(1, round(height * FRAME_WIDTH / float(max(width, 1))))
    return cv2.resize(frame, (FRAME_WIDTH, target_height), interpolation=cv2.INTER_AREA)


def _candidate_strip(candidate: dict) -> Tuple[np.ndarray, dict]:
    video = dict(candidate.get("video") or {})
    video_path = Path(str(video.get("file_path") or ""))
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open candidate video: {video_path}")
    try:
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 30.0)
        if frame_count < 2:
            raise RuntimeError(f"Candidate video has too few frames: {video_path}")
        indices = [min(frame_count - 1, round((frame_count - 1) * value)) for value in SAMPLE_FRACTIONS]
        frames = [_read_frame(capture, index) for index in indices]
    finally:
        capture.release()

    frame_height = min(frame.shape[0] for frame in frames)
    frames = [frame[:frame_height] for frame in frames]
    label = np.full((frame_height, LABEL_WIDTH, 3), 245, dtype=np.uint8)
    candidate_index = int(candidate.get("candidate_index") or 0)
    seed = int(candidate.get("seed") or 0)
    selected = bool(candidate.get("selected_by_physical_quality"))
    cv2.putText(label, f"candidate {candidate_index}", (10, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 2)
    cv2.putText(label, f"seed {seed}", (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (40, 40, 40), 1)
    cv2.putText(
        label,
        "physical SELECTED" if selected else "physical not selected",
        (10, 104),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        (0, 80, 180) if selected else (80, 80, 80),
        1,
    )
    cv2.putText(label, "human review: pending", (10, 138), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (80, 80, 80), 1)

    annotated_frames: List[np.ndarray] = []
    for fraction, frame_index, frame in zip(SAMPLE_FRACTIONS, indices, frames):
        annotated = frame.copy()
        time_seconds = frame_index / max(fps, 1e-6)
        cv2.rectangle(annotated, (0, 0), (FRAME_WIDTH, HEADER_HEIGHT), (255, 255, 255), -1)
        cv2.putText(
            annotated,
            f"{fraction:.0%} / {time_seconds:.2f}s",
            (8, 21),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (20, 20, 20),
            1,
        )
        annotated_frames.append(annotated)
    strip = np.hstack([label, *annotated_frames])
    metadata = {
        "candidate_index": candidate_index,
        "seed": seed,
        "selected_by_physical_quality": selected,
        "video_path": str(video_path.resolve()),
        "frame_count": frame_count,
        "fps": fps,
        "sampled_frame_indices": indices,
        "sampled_times_seconds": [round(index / max(fps, 1e-6), 3) for index in indices],
    }
    return strip, metadata


def build_contact_sheets(audit_manifest: Path, output_dir: Path, rows_per_sheet: int = 4) -> dict:
    payload = json.loads(audit_manifest.read_text(encoding="utf-8"))
    candidates = list(payload.get("candidates") or [])
    if not candidates:
        raise ValueError("Audit manifest contains no candidates")
    output_dir.mkdir(parents=True, exist_ok=True)

    strips = []
    candidate_metadata = []
    for candidate in candidates:
        strip, metadata = _candidate_strip(candidate)
        strips.append(strip)
        candidate_metadata.append(metadata)

    sheet_paths = []
    for start in range(0, len(strips), rows_per_sheet):
        page = strips[start : start + rows_per_sheet]
        width = max(strip.shape[1] for strip in page)
        padded = [
            cv2.copyMakeBorder(strip, 0, 0, 0, width - strip.shape[1], cv2.BORDER_CONSTANT, value=(255, 255, 255))
            for strip in page
        ]
        sheet = np.vstack(padded)
        first = start + 1
        last = start + len(page)
        sheet_path = output_dir / f"candidate-contact-sheet-{first:02d}-{last:02d}.jpg"
        if not cv2.imwrite(str(sheet_path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 92]):
            raise RuntimeError(f"Could not write contact sheet: {sheet_path}")
        sheet_paths.append(str(sheet_path.resolve()))

    result = {
        "schema_version": 1,
        "audit_manifest": str(audit_manifest.resolve()),
        "sample_fractions": list(SAMPLE_FRACTIONS),
        "rows_per_sheet": rows_per_sheet,
        "sheet_paths": sheet_paths,
        "candidates": candidate_metadata,
        "limitation": "Static frames support screening but cannot replace full-video human semantic review.",
    }
    metadata_path = output_dir / "candidate-contact-sheet-metadata.json"
    metadata_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["metadata_path"] = str(metadata_path.resolve())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--rows-per-sheet", type=int, default=4)
    args = parser.parse_args()
    if args.rows_per_sheet < 1 or args.rows_per_sheet > 8:
        parser.error("--rows-per-sheet must be between 1 and 8")
    result = build_contact_sheets(
        args.audit_manifest.resolve(),
        args.output_dir.resolve(),
        rows_per_sheet=args.rows_per_sheet,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
