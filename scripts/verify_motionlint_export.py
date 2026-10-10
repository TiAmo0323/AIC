"""Verify historical repaired exports and write reproducible delivery evidence."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.archived_export_evidence import fingerprint, repaired_inputs, read_export
from motionlint.adapters.bvh_adapter import load_bvh_pair
from motionlint.adapters.character_adapter import load_character
from motionlint.pipeline.inspector import inspect
from motionlint.core.quality_gate import evaluate_gate
from motionlint.cli.main import _write_json


def verify(task_id: str, ffmpeg: Path) -> dict:
    task = REPO_ROOT / "InterGen_api/task_runs" / task_id
    state = read_export(task)
    if state["status"] != "ready":
        raise RuntimeError(f"{task_id}: export is {state['status']}")
    output = Path(state["export_dir"])
    assert fingerprint([output / path.name for path in repaired_inputs(task)]) == state["input_fingerprints"]
    with zipfile.ZipFile(state["bundle_path"]) as archive:
        names = archive.namelist()
        assert archive.testzip() is None
        assert not any(Path(name).suffix in {".fbx", ".blend", ".ckpt", ".pth"} for name in names)
        summary = json.loads(archive.read("export_summary.json"))
        assert summary["status"] == "ready"
        assert summary["quality"] == state["quality"]
        assert all(name in names for name in ("repaired_actor1.npy", "repaired_actor2.npy", "repaired_actor1.bvh",
                                              "repaired_actor2.bvh", "repaired_kenney.mp4", "character.npz"))
    stages = {}
    for stage in ("repaired_bvh", "repaired_character"):
        motion = load_bvh_pair(state["bvh_files"]) if stage == "repaired_bvh" else load_character(state["character_path"])
        policy = output / "quality.yaml"
        report = inspect(motion, config_path=policy)
        gate = evaluate_gate(report, config_path=policy)
        assert report.overall_score == state["quality"][stage]["score"]
        assert gate.to_dict() == state["quality"][stage]["gate"]
        stages[stage] = {"score": report.overall_score, "gate": gate.to_dict(), "frames": motion.frame_count}
    video = Path(state["video_path"])
    assert video.is_relative_to(output) and video.is_file()
    subprocess.run([str(ffmpeg), "-v", "error", "-i", str(video), "-f", "null", "-"],
                   check=True, capture_output=True, timeout=120)
    return {"task_id": task_id, "input_fingerprints": state["input_fingerprints"], "quality": stages,
            "video_path": str(video), "bundle_path": state["bundle_path"],
            "full_video_decode": "PASS", "zip_integrity": "PASS", "local_assets_excluded": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_ids", nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    binaries = REPO_ROOT.parent / "HumanAction-runtime/envs/lodge/Lib/site-packages/imageio_ffmpeg/binaries"
    ffmpeg = next(binaries.glob("ffmpeg*.exe"))
    rows = [verify(task_id, ffmpeg) for task_id in args.task_ids]
    _write_json(args.output, rows)
    print(json.dumps([{ "task": row["task_id"], "quality": row["quality"], "decode": row["full_video_decode"] } for row in rows], ensure_ascii=False, indent=2))
