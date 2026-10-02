"""Create reproducible video samples and audit contact-mask changes."""
from pathlib import Path
import io
import json
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from motionlint.cli.main import load_motion, _write_json
from motionlint.core.config import load_config
from motionlint.core.foot_support import estimate_support
from motionlint.tests.common import segments

OUT = ROOT / "reports/visual_review_20260930"
FFMPEG = ROOT.parent / "HumanAction-runtime/bin/ffmpeg.exe"
CASES = [
    ("intergen_20260929_pair", "InterGen_api", "91d1b363-c453-4526-8bb2-8f933f25809b", [35, 85, 112, 128, 151, 175]),
    ("intergen_handshake_a", "InterGen_api", "9323c3fd-d1a9-4a94-877d-c47bbca5dd4b", [15, 45, 85, 128, 143, 171]),
    ("intergen_wave", "InterGen_api", "ceba9ca5-6d9f-41a2-8039-e460f32dd243", [15, 45, 60, 94, 114, 170]),
    ("lodge_20260929_processed", "LODGE_api", "3eb8a74d-2729-40e5-9300-f1f0239c03db", [30, 180, 420, 719, 724, 900]),
    ("lodge_063_processed", "LODGE_api", "a394daeb-6ca1-44e3-a5e8-970a73aea88c", [174, 300, 429, 447, 801, 855]),
]

def frame(path, index):
    result = subprocess.run([str(FFMPEG), "-v", "error", "-ss", str(index / 30), "-i", str(path),
                             "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
                            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return Image.open(io.BytesIO(result.stdout)).convert("RGB")

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    baseline = json.loads((ROOT / "experiments/baseline_motions.json").read_text(encoding="utf-8"))
    review = []
    for name, api, task_id, indices in CASES:
        folder = ROOT / api / "task_runs" / task_id / "motionlint"
        before_video, after_video = folder / "original.mp4", folder / "repaired.mp4"
        if not before_video.is_file():
            before_video = ROOT / api / "task_runs" / task_id / "input/video/aic260929-smplx.mp4"
        sheet = Image.new("RGB", (960, len(indices) * 270), "white")
        draw = ImageDraw.Draw(sheet)
        for row, index in enumerate(indices):
            for column, path in enumerate((before_video, after_video)):
                thumbnail = frame(path, index)
                thumbnail.thumbnail((480, 240))
                sheet.paste(thumbnail, (column * 480 + (480-thumbnail.width)//2, row * 270 + 28))
                draw.text((column * 480 + 10, row * 270 + 8),
                          f"{'Original' if column == 0 else 'Repaired'} | frame {index} | {index/30:.2f}s", fill="black")
        path = OUT / f"{name}_frames.png"
        sheet.save(path)
        record = {"name": name, "sampled_frames": indices, "contact_sheet": str(path),
                  "original_video": str(before_video), "repaired_video": str(after_video),
                  "scope": "Selected stills; cannot certify full-video contact or temporal continuity"}
        if api == "InterGen_api":
            entry = next(item for item in baseline["motions"] if item["name"] == name)
            original = load_motion(ROOT / "experiments" / entry["input"], ROOT / "experiments" / entry["actor2"])
            final = load_motion(folder / "repaired_actor1.npy", folder / "repaired_actor2.npy")
            settings = load_config()["tests"]["foot_sliding"]
            a, b = estimate_support(original, settings), estimate_support(final, settings)
            speed = np.linalg.norm(np.diff(final.positions[:, :, a.feet][..., [0, 2]], axis=0), axis=-1) * final.fps
            lost = a.intervals & ~b.intervals
            risky = lost & (speed > settings["horizontal_speed_m_s"])
            events = []
            for actor in range(final.actor_count):
                for local, joint in enumerate(a.feet):
                    height = final.positions[:, actor, joint, 1]
                    baseline_height = float(np.percentile(height, 5))
                    vertical = np.abs(np.diff(height)) * final.fps
                    for start, end in segments(risky[:, actor, local]):
                        events.append({"actor": actor, "joint": final.joint_names[joint], "start_frame": start,
                                       "end_frame": end+1, "final_max_horizontal_speed_m_s": float(speed[start:end+1, actor, local].max()),
                                       "final_max_vertical_speed_m_s": float(vertical[start:end+1].max()),
                                       "final_max_height_above_own_baseline_m": float((height[start:end+2]-baseline_height).max()),
                                       "review_label": "unconfirmed_contact_change"})
            record["contact_audit"] = {"original_support_count": int(a.intervals.sum()), "final_support_count": int(b.intervals.sum()),
                                       "fixed_original_support_sliding_count": int(((speed > settings["horizontal_speed_m_s"]) & a.intervals).sum()),
                                       "lost_support_slipping_count": int(risky.sum()), "events": events,
                                       "human_ground_truth": False}
        review.append(record)
        print("Created", path, flush=True)
    _write_json(OUT / "audit.json", {"cases": review, "scope": "Automated measurements plus selected frame review; no human contact labels"})

if __name__ == "__main__":
    main()
