"""Reduce Windows checkpoint loading commit pressure, preserving model weights."""
import difflib
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
path=ROOT.parent/"HumanAction-runtime/LODGE-main/infer_lodge.py"
output=ROOT/"reports/first_prize/lodge_loading"
output.mkdir(parents=True,exist_ok=True)
original=path.read_text(encoding="utf-8")
if 'map_location="cpu", mmap=True)' in original:
    print("Memory-mapped checkpoint loading already enabled")
else:
    needle='map_location="cpu")["state_dict"]'
    if original.count(needle)!=2:raise ValueError("Unexpected upstream checkpoint loader; refusing an unreviewed patch")
    patched=original.replace(needle,'map_location="cpu", mmap=True)["state_dict"]')
    patched=patched.replace('model_coarse.load_state_dict(state_dict, strict=True)','model_coarse.load_state_dict(state_dict, strict=True)\n    del state_dict')
    patched=patched.replace('model_fine.load_state_dict(state_dict, strict=True)','model_fine.load_state_dict(state_dict, strict=True)\n    del state_dict')
    backup=output/"infer_lodge.before.py"
    if backup.exists():raise ValueError("Prior backup exists; do not overwrite provenance")
    backup.write_text(original,encoding="utf-8")
    path.write_text(patched,encoding="utf-8")
    patch="".join(difflib.unified_diff(original.splitlines(True),patched.splitlines(True),fromfile="a/infer_lodge.py",tofile="b/infer_lodge.py"))
    (output/"checkpoint_mmap.patch").write_text(patch,encoding="utf-8")
    (output/"manifest.json").write_text(json.dumps({"before_sha256":hashlib.sha256(original.encode()).hexdigest(),
                       "after_sha256":hashlib.sha256(patched.encode()).hexdigest(),"scope":"Checkpoint I/O only; strict state loading remains enabled",
                       "reason":"Observed Windows process crashes 0xC0000005 during full checkpoint deserialization; causality not yet proven",
                       "community_status":"not_submitted"},indent=2),encoding="utf-8")
    print("Patched both checkpoint loads; original source and review patch saved")
