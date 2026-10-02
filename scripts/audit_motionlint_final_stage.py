"""Audit existing BVH and the evaluated skeleton used by character videos."""
from dataclasses import replace
from pathlib import Path
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from motionlint.adapters.bvh_adapter import load_bvh_pair
from motionlint.core.motion_sequence import MotionSequence
from motionlint.cli.main import _write_json, _write_report
from motionlint.pipeline.inspector import inspect
from motionlint.core.quality_gate import evaluate_gate

OUT = ROOT / "reports/final_stage_20260930"

def metadata(names, extra):
    lookup = {name: index for index, name in enumerate(names)}
    required = ["LeftFoot", "RightFoot", "LeftToe", "RightToe"]
    assert all(name in lookup for name in required), "Unmapped feet must not receive a PASS"
    return {**extra, "up_axis": 1, "unit_scale_to_metres": 1.,
            "foot_joint_ids": [lookup[name] for name in required],
            "left_foot_joint_ids": [lookup["LeftFoot"], lookup["LeftToe"]],
            "right_foot_joint_ids": [lookup["RightFoot"], lookup["RightToe"]]}

def character(path):
    info = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    with np.load(path, allow_pickle=False) as data:
        positions, world = data["positions"], data["world_rotation_matrices"]
        names, parents = data["joint_names"].tolist(), data["parents"].tolist()
        local = world.copy()
        for joint, parent in enumerate(parents):
            if parent >= 0:
                local[:, :, joint] = np.swapaxes(world[:, :, parent], -1, -2) @ world[:, :, joint]
    return MotionSequence("character", info["fps"], len(positions), positions.shape[1], positions=positions,
                          rotation_matrices=local, joint_names=names,
                          root_translation=positions[:, :, names.index("Hips")], skeleton_type="kenney_character",
                          metadata=metadata(names, {**info, "parents": parents}))

def bvh_pair(paths):
    first = load_bvh_pair(paths)
    return replace(first, metadata=metadata(first.joint_names, {**first.metadata, "source_paths": [str(path) for path in paths],
                                    "geometry_source": "existing_exported_bvh_fk", "unit_basis": "Repository exporter stores metre offsets"}))

def main():
    cases = []
    for label, task_id in [("dance", "91d1b363-c453-4526-8bb2-8f933f25809b"),
                           ("handshake", "9323c3fd-d1a9-4a94-877d-c47bbca5dd4b")]:
        folder = ROOT / "InterGen_api/task_runs" / task_id / "retarget"
        cases += [(label + "_bvh", bvh_pair([folder / f"{task_id}_person{actor}.bvh" for actor in (1, 2)])),
                  (label + "_character", character(OUT / f"{label}_character.npz"))]
    for label, task_id, filename in [("lodge_a", "3eb8a74d-2729-40e5-9300-f1f0239c03db", "aic260929"),
                                    ("lodge_063", "a394daeb-6ca1-44e3-a5e8-970a73aea88c", "063")]:
        cases.append((label + "_bvh", bvh_pair([ROOT / "LODGE_api/task_runs" / task_id / "input" / f"{filename}.bvh"])))
    rows = []
    for name, motion in cases:
        report, folder = inspect(motion), OUT / name
        gate = evaluate_gate(report)
        _write_report(folder, report)
        _write_json(folder / "quality_gate.json", gate.to_dict())
        _write_json(folder / "provenance.json", motion.metadata)
        rows.append({"name": name, "stage": motion.metadata["geometry_source"], "score": report.overall_score,
                     "gate": gate.status, "reasons": gate.reasons,
                     "foot_sliding_count": next(test.metrics["sliding_frame_count"] for test in report.tests if test.test_name == "foot_sliding")})
        print(rows[-1], flush=True)
    _write_json(OUT / "summary.json", {"rows": rows, "limits": "Existing exports and existing character scenes, not repaired NPY; bone geometry, not mesh collisions"})

if __name__ == "__main__":
    main()
