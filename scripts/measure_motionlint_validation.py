"""Measure every generated sample with the frozen repair, including FAILs."""
from pathlib import Path
import csv
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FROZEN = ROOT / "reports/validation_20260930/frozen_code"
if FROZEN.is_dir():
    sys.path.insert(0, str(FROZEN))
from scripts.run_motionlint_validation import OUTPUT, code_hashes
from scripts.diagnose_motionlint_gate import run
from motionlint.cli.main import _write_json


def main():
    state = json.loads((OUTPUT / "generation.json").read_text(encoding="utf-8"))
    assert state["status"] == "generation_complete"
    frozen_exists = FROZEN.is_dir()
    basis = FROZEN if frozen_exists else ROOT
    def verify():
        actual = {relative: hashlib.sha256((basis / relative).read_bytes()).hexdigest() for relative in state["code_hashes"]}
        assert actual == state["code_hashes"], "Frozen code snapshot changed"
    verify()
    if not frozen_exists:
        for relative in state["code_hashes"]:
            destination = OUTPUT / "frozen_code" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
    manifest = {"fps": 30, "motions": [], "generation_failures": []}
    for sample in state["samples"]:
        if sample["generation_status"] != "succeeded":
            manifest["generation_failures"].append({"name": sample["name"], "task_id": sample["task_id"],
                                                     "message": sample.get("generation_message")})
            continue
        if sample["source"] == "intergen":
            folder = ROOT / "InterGen_api/task_runs" / sample["task_id"] / "output/raw"
            paths = [folder / f"{sample['task_id']}_person{actor}_joints22.npy" for actor in (1, 2)]
        else:
            paths = [Path(sample["task_result"]["output_npy_path"])]
        assert all(path.is_file() for path in paths), paths
        entry = {"name": sample["name"], "input": str(paths[0])}
        if len(paths) == 2:
            entry["actor2"] = str(paths[1])
        manifest["motions"].append(entry)
    _write_json(OUTPUT / "motions.json", manifest)
    result = run(OUTPUT / "motions.json", OUTPUT / "measurements", None, True, True)
    verify()
    records = result["records"]
    summary = {"attempted_sample_count": len(state["samples"]), "generated_count": len(records),
               "generation_failure_count": len(manifest["generation_failures"]),
               "unique_generated_count": sum(item["duplicate_of"] is None for item in records),
               "original_pass_count": result["pass_count"], "repaired_pass_count": result["repaired_pass_count"],
               "frozen_code_verified": True, "rows": []}
    for item in records:
        row = {"name": item["name"], "duplicate_of": item["duplicate_of"], "before": item["current"]["overall_score"],
               "after": item["repair"]["after"]["overall_score"], "gate": item["repair"]["after"]["gate"]["status"],
               "reasons": " | ".join(item["repair"]["after"]["gate"]["reasons"])}
        summary["rows"].append(row)
    _write_json(OUTPUT / "summary.json", summary)
    with (OUTPUT / "summary.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary["rows"][0]))
        writer.writeheader()
        writer.writerows(summary["rows"])
    print(json.dumps(summary, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
