"""Render an already checked scene with the existing local renderer."""
import json
from pathlib import Path
import sys
import bpy
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from LODGE_api.blender_rokoko_retarget import render_output
manifest = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
if manifest.get("render_size"):
    bpy.context.scene["retarget_render_size"] = str(manifest["render_size"])
report = {"render_settings": {}}
render_output(Path(manifest["output_mp4"]), fps=int(manifest["fps"]),
    frame_end=int(manifest["generated_frames"]), report=report,
    frame_start=int(manifest.get("frame_start", 1)))
if manifest.get("report_path"):
    report.update({"status": "completed", "output": manifest["output_mp4"]})
    Path(manifest["report_path"]).write_text(json.dumps(report, indent=2), encoding="utf-8")
