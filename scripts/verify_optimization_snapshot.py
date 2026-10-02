"""Verify unchanged inputs/policy and re-inspect the saved optimized arrays."""
from pathlib import Path
import hashlib
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from motionlint.cli.main import _write_json, load_motion
from motionlint.core.config import load_config
from motionlint.core.foot_support import estimate_support
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect


def verify():
    previous = json.loads((ROOT / "reports/constraint_ik_20260930/diagnosis.json").read_text(encoding="utf-8"))
    folder = ROOT / "reports/optimization_20260930"
    latest = json.loads((folder / "diagnosis.json").read_text(encoding="utf-8"))
    assert previous["policy"] == latest["policy"] == load_config()["gate"]
    assert previous["config_version"] == latest["config_version"]
    old = {item["name"]: item for item in previous["records"]}
    rows = []
    for item in latest["records"]:
        paths = [Path(path) for path in item["input_paths"]]
        digest = hashlib.sha256(b"".join(path.read_bytes() for path in paths)).hexdigest()
        assert digest == item["sha256"] == old[item["name"]]["sha256"]
        before_signature = [(test["test"], test["score"], test["status"]) for test in item["current"]["tests"]]
        assert before_signature == [(test["test"], test["score"], test["status"]) for test in old[item["name"]]["current"]["tests"]]
        if "repair" not in item:
            continue
        files = [folder / item["name"] / "repaired.npy"] if item["source"] == "lodge" else [folder / item["name"] / f"repaired_actor{actor}.npy" for actor in (1, 2)]
        saved = load_motion(files[0], files[1] if len(files) == 2 else None)
        actual = inspect(saved)
        expected = item["repair"]["after"]
        assert actual.overall_score == expected["overall_score"]
        assert [(test.test_name, test.score, test.status) for test in actual.tests] == [(test["test"], test["score"], test["status"]) for test in expected["tests"]]
        gate = evaluate_gate(actual)
        assert gate.to_dict() == expected["gate"]
        original = load_motion(paths[0], paths[1] if len(paths) == 2 else None)
        support = estimate_support(original, load_config()["tests"]["foot_sliding"])
        horizontal = [axis for axis in range(3) if axis != int(original.metadata["up_axis"])]
        speed = np.linalg.norm(np.diff(saved.positions[:, :, support.feet][..., horizontal], axis=0), axis=-1) * saved.fps
        threshold = load_config()["tests"]["foot_sliding"]["horizontal_speed_m_s"]
        remaining_on_original_support = int(np.count_nonzero((speed > threshold) & support.intervals))
        if item["source"] == "lodge":
            np.testing.assert_array_equal(np.load(files[0], allow_pickle=False)[:, :4], np.load(paths[0], allow_pickle=False)[:, :4])
        rows.append({"name": item["name"], "score": actual.overall_score, "gate": gate.status,
                     "sliding_intervals_on_original_support": remaining_on_original_support})
    result = {"input_hashes_unchanged": True, "gate_policy_unchanged": True, "baseline_scores_and_statuses_unchanged": True,
              "saved_outputs_match_fresh_inspection": True, "records": rows}
    _write_json(folder / "snapshot_verification.json", result)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    verify()
