"""Export raw skeleton playback without detector predictions or scores."""
import hashlib
import json
import shutil
import sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from motionlint.cli.main import load_motion


def main():
    output=ROOT/"reports/first_prize/study"
    state=json.loads((output/"generation.json").read_text(encoding="utf-8"))
    clips=[]
    for entry in state["samples"]:
        if entry.get("status")!="succeeded":continue
        paths=entry["paths"]
        if [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths]!=entry["sha256"]:
            raise ValueError("Generated input hash changed")
        motion=load_motion(paths[0],paths[1] if len(paths)>1 else None)
        clips.append({"id":entry["id"],"sha256":entry["sha256"],"fps":motion.fps,"frame_count":motion.frame_count,
                      "actor_count":motion.actor_count,"prompt":entry.get("prompt",entry.get("title","")),
                      "joint_names":motion.joint_names,"parents":motion.metadata["parents"],
                      "geometry_source":motion.metadata.get("geometry_source","native_joint_positions"),
                      "positions":np.round(motion.positions,5).tolist()})
    pack=output/"annotation_pack"
    pack.mkdir(exist_ok=True)
    (pack/"clips.json").write_text(json.dumps({"protocol_sha256":state["protocol_sha256"],"clips":clips},ensure_ascii=False),encoding="utf-8")
    shutil.copyfile(ROOT/"tools/annotation/index.html",pack/"index.html")
    shutil.copyfile(ROOT/"docs/MOTIONLINT_HUMAN_VALIDATION.md",pack/"INSTRUCTIONS.md")
    print(f"Annotation pack: {len(clips)} available clips; no scores included")

if __name__=="__main__":main()
