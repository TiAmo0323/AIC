"""Render a checked Blender scene in bounded processes, then join its MP4 parts.

Each Blender process releases its allocations on exit. This keeps long EEVEE
renders usable on the local 16 GB machine while the model APIs remain running.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frames", type=int, required=True)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--chunk-frames", type=int, default=120)
    parser.add_argument("--render-size", default="720x720")
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    if min(args.frames, args.fps, args.chunk_frames) < 1:
        parser.error("Frame counts and fps must be positive")
    repo = Path(__file__).resolve().parents[1]
    runtime = repo.parent / "HumanAction-runtime"
    scene = args.scene.resolve(strict=True)
    output = args.output.resolve()
    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    blender = runtime / "blender-4.2.23-windows-x64/blender.exe"
    ffmpeg = runtime / "bin/ffmpeg.exe"
    chunks = []
    for index, start in enumerate(range(1, args.frames + 1, args.chunk_frames), 1):
        end = min(start + args.chunk_frames - 1, args.frames)
        part = work / f"chunk_{index:04d}.mp4"
        manifest_path = work / f"chunk_{index:04d}.json"
        manifest = {"output_mp4": str(part), "fps": args.fps,
            "frame_start": start, "generated_frames": end,
            "render_size": args.render_size, "report_path": str(part.with_suffix(".report.json"))}
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Rendering frames {start}..{end}", flush=True)
        with part.with_suffix(".log").open("w", encoding="utf-8") as log:
            subprocess.run([str(blender), "-b", str(scene), "--disable-autoexec", "--python-exit-code", "1",
                "--python", str(repo / "scripts/render_saved_character.py"), "--", str(manifest_path)],
                cwd=repo, stdout=log, stderr=subprocess.STDOUT, check=True)
        if not part.is_file() or not part.stat().st_size:
            raise RuntimeError(f"Missing rendered part: {part}")
        chunks.append({"file": part.name, "start": start, "end": end})
    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{chunk['file']}'\n" for chunk in chunks), encoding="utf-8")
    subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat), "-c", "copy", "-movflags", "+faststart", str(output)], check=True)
    # Count and decode every frame, including the joins between render parts.
    decoded = subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-xerror", "-i", str(output),
        "-map", "0:v:0", "-progress", "pipe:1", "-nostats", "-f", "null", "-"],
        capture_output=True, text=True, check=True)
    counts = [int(line.split("=", 1)[1]) for line in decoded.stdout.splitlines() if line.startswith("frame=")]
    if not counts or counts[-1] != args.frames:
        raise RuntimeError(f"Expected {args.frames} decoded frames, got {counts[-1] if counts else 0}")
    report = {"status": "completed", "scene": str(scene),
        "scene_sha256": hashlib.sha256(scene.read_bytes()).hexdigest(), "output": str(output),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(), "fps": args.fps,
        "decoded_frames": counts[-1], "duration_seconds": args.frames / args.fps,
        "render_size": args.render_size, "chunks": chunks, "full_decode_passed": True}
    (work / "render_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
