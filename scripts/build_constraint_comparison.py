"""Build a silent, full-length comparison from the current repaired task videos."""
from pathlib import Path
import argparse
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT.parent / "HumanAction-runtime" / "bin" / "ffmpeg.exe"


def build(diagnosis_path=None, output=None):
    diagnosis_path = diagnosis_path or ROOT / "reports/optimization_20260930/diagnosis.json"
    diagnosis = json.loads(diagnosis_path.read_text(encoding="utf-8"))
    output = output or ROOT / "output/video/motionlint_optimization_comparison_20260930.mp4"
    clips = ROOT / "tmp/constraint_comparison"
    clips.mkdir(parents=True, exist_ok=True)
    names = {"lodge_20260929_processed": "LODGE aic260929", "lodge_063_processed": "LODGE 063",
             "intergen_20260929_pair": "InterGen dance", "intergen_handshake_a": "InterGen handshake",
             "intergen_wave": "InterGen wave"}
    files = []
    for record in diagnosis["records"]:
        if "repair" not in record:
            continue
        source = Path(record["input_paths"][0])
        task = source.parent.parent if record["source"] == "lodge" else source.parent.parent.parent
        folder = task / "motionlint"
        before = folder / "original.mp4"
        if not before.is_file():
            before = next((task / "input/video").glob("*smplx.mp4"))
        after = folder / "repaired.mp4"
        saved = json.loads((folder / "after/motionlint_report.json").read_text(encoding="utf-8"))
        expected = record["repair"]["after"]
        if saved["overall_score"] != expected["overall_score"] or [(test["test_name"], test["score"], test["status"]) for test in saved["tests"]] != [(test["test"], test["score"], test["status"]) for test in expected["tests"]]:
            raise ValueError(f"Task report does not match comparison diagnosis: {record['name']}")
        arrays = [folder / "repaired.npy"] if record["source"] == "lodge" else [folder / f"repaired_actor{actor}.npy" for actor in (1, 2)]
        if any(path.stat().st_mtime > after.stat().st_mtime for path in arrays):
            raise ValueError(f"Task video has not been rendered from the current arrays: {record['name']}")
        target = clips / f"clip_{len(files):02}.mp4"
        title = names[record["name"]]
        score_before = record["current"]["overall_score"]
        score_after = record["repair"]["after"]["overall_score"]
        gate = expected["gate"]["status"]
        failed = {test["test"] for test in expected["tests"] if test["status"] == "FAIL"}
        remaining = "foot sliding remains" if "foot_sliding" in failed else "proximity risk remains" if "collision" in failed else "quality requirements remain"
        gate_text = "Strict gate PASS - all six checks completed" if gate == "PASS" else f"Strict gate FAIL - {remaining}"
        gate_color = "0xaff3bd" if gate == "PASS" else "0xffc6a1"
        font = "C\\:/Windows/Fonts/arial.ttf"
        filters = (
            "[0:v]fps=30,scale=360:360,setsar=1,setpts=PTS-STARTPTS[left];"
            "[1:v]fps=30,scale=360:360,setsar=1,setpts=PTS-STARTPTS[right];"
            "[left][right]hstack=inputs=2:shortest=1,pad=720:480:0:50:color=0x182335,"
            f"drawtext=fontfile='{font}':text='{title} - config v2':fontcolor=white:fontsize=21:x=18:y=12,"
            f"drawtext=fontfile='{font}':text='Before {score_before:.2f}':fontcolor=white:fontsize=18:x=18:y=415,"
            f"drawtext=fontfile='{font}':text='After {score_after:.2f}':fontcolor=white:fontsize=18:x=378:y=415,"
            f"drawtext=fontfile='{font}':text='{gate_text}':fontcolor={gate_color}:fontsize=16:x=18:y=450[v]"
        )
        subprocess.run([str(FFMPEG), "-y", "-v", "error", "-i", str(before), "-i", str(after),
            "-filter_complex", filters, "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "20", "-pix_fmt", "yuv420p", str(target)], check=True)
        files.append(target)
        print(f"Built {record['name']}", flush=True)
    listing = clips / "concat.txt"
    listing.write_text("\n".join(f"file '{path.name}'" for path in files) + "\n", encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(FFMPEG), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-vf", "fps=30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                    "-an", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output)], check=True)
    subprocess.run([str(FFMPEG), "-y", "-v", "error", "-ss", "1", "-i", str(output), "-frames:v", "1",
                    str(output.with_suffix(".png"))], check=True)
    print(str(output))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnosis", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    build(args.diagnosis, args.output)
