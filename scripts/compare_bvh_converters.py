"""Compare fixed-template MoMask exports with a continuous-frame candidate."""
import json
from pathlib import Path
import sys

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from motionlint.export_intergen import read_export
from motionlint.joints_to_bvh import convert_continuous_joints, fidelity
from motionlint.adapters.bvh_adapter import load_bvh_pair
from motionlint.adapters.intergen_adapter import load_intergen_joints
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.regression import compare
from motionlint.core.quality_gate import evaluate_gate
from motionlint.cli.main import _write_json, _write_report
from LODGE_api.lodge2bvh import SMPL_TO_BVH22

rows = []
for task_id in sys.argv[1:]:
    task = REPO_ROOT / "InterGen_api/task_runs" / task_id
    state = read_export(task)
    if state.get("status") != "ready":
        raise ValueError(f"{task_id}: no current completed export")
    output = REPO_ROOT / "reports/bvh_conversion_20261002" / task_id
    output.mkdir(parents=True, exist_ok=True)
    paths = [task / "motionlint" / f"repaired_actor{actor}.npy" for actor in (1, 2)]
    candidate = []
    for actor, path in enumerate(paths, 1):
        bvh = output / f"continuous_actor{actor}.bvh"
        convert_continuous_joints(path, bvh)
        candidate.append(bvh)
    original_motion = load_intergen_joints(paths)
    export_root = Path(state["export_dir"])
    # New exports preserve the legacy candidate even after selecting continuous.
    # Re-running this script must not compare continuous with itself.
    legacy_paths = [export_root / "conversion_candidates/momask" / f"repaired_actor{actor}.bvh" for actor in (1, 2)]
    baseline_paths = legacy_paths if all(path.is_file() for path in legacy_paths) else state["bvh_files"]
    old_motion = load_bvh_pair(baseline_paths)
    new_motion = load_bvh_pair(candidate)
    policy = export_root / "quality.yaml"
    baseline, result = inspect(old_motion, config_path=policy), inspect(new_motion, config_path=policy)
    _write_report(output / "baseline", baseline)
    _write_report(output / "candidate", result)
    target = original_motion.positions[:, :, SMPL_TO_BVH22]
    row = {"task": task_id, "baseline": baseline.overall_score, "candidate": result.overall_score,
           "gate": evaluate_gate(result, config_path=policy).to_dict(), "comparison": compare(baseline, result, config_path=policy),
           "baseline_bvh_files": [str(path) for path in baseline_paths],
           "baseline_fidelity": [fidelity(target[:, actor], old_motion.positions[:, actor]) for actor in range(2)],
           "candidate_fidelity": [fidelity(target[:, actor], new_motion.positions[:, actor]) for actor in range(2)],
           "candidate_bvh_files": [str(path) for path in candidate]}
    rows.append(row)
_write_json(REPO_ROOT / "reports/bvh_conversion_20261002/summary.json", rows)
print(json.dumps(rows, ensure_ascii=False, indent=2))
