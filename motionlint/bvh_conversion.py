"""Compare BVH converters using motion quality and source fidelity."""
from __future__ import annotations

from pathlib import Path
import json
import shutil

import numpy as np

from motionlint.adapters.bvh_adapter import load_bvh_pair
from motionlint.adapters.intergen_adapter import load_intergen_joints
from motionlint.cli.main import _write_json, _write_report
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.regression import compare

RUNTIME_ROOT = Path(__file__).resolve().parents[2] / "HumanAction-runtime"


def select_converter(baseline, candidate, baseline_fidelity: list[dict], candidate_fidelity: list[dict], *, config_path=None) -> dict:
    """Accept measured BVH gains without hiding a new failed test or worse fit."""
    comparison = compare(baseline, candidate, config_path=config_path)
    reasons = list(comparison["reasons"])
    if candidate.overall_score < baseline.overall_score:
        reasons.append("Overall score decreased")
    old_tests = {test.test_name: test for test in baseline.tests}
    for test in candidate.tests:
        if test.status == "FAIL" and test.test_name in old_tests and old_tests[test.test_name].status != "FAIL":
            reasons.append(f"New failed test: {test.test_name}")
    if len(baseline_fidelity) != len(candidate_fidelity) or not candidate_fidelity:
        reasons.append("Missing actor fidelity comparison")
    for old, new in zip(baseline_fidelity, candidate_fidelity):
        for metric in ("position_error_mean_m", "position_error_p95_m", "position_error_max_m"):
            if not np.isfinite(new[metric]) or new[metric] > old[metric] + 1e-5:
                reasons.append(f"Worse source fidelity: {metric}")
        if not np.isfinite(new["root_error_max_m"]) or new["root_error_max_m"] > .01001:
            reasons.append("Root adjustment exceeded 1 cm")
    return {"selected": "momask" if reasons else "continuous", "reasons": reasons, "regression": comparison,
            "baseline_score": baseline.overall_score, "candidate_score": candidate.overall_score,
            "baseline_fidelity": baseline_fidelity, "candidate_fidelity": candidate_fidelity,
            "limits": "Selection checks BVH only. Actual character quality is checked after rendering."}


def convert_snapshot(snapshots: list[Path], output: Path, *, fps: int, policy: Path) -> dict:
    from InterGen_api.intergen_joints2bvh import convert_joints_to_bvh
    from motionlint.joints_to_bvh import convert_continuous_joints, fidelity
    from LODGE_api.lodge2bvh import SMPL_TO_BVH22
    candidates = {}
    reports = {}
    fidelity_rows = {}
    target = load_intergen_joints(snapshots, fps=fps).positions[:, :, SMPL_TO_BVH22]
    for method in ("momask", "continuous"):
        directory = output / "conversion_candidates" / method
        directory.mkdir(parents=True)
        paths = []
        try:
            for actor, snapshot in enumerate(snapshots, 1):
                bvh = directory / f"repaired_actor{actor}.bvh"
                if method == "momask":
                    convert_joints_to_bvh(snapshot, bvh, RUNTIME_ROOT / "momask-main", fps=fps,
                                          foot_ik=False, stabilize_upper_body=False,
                                          correct_hand_head_collisions=False, quality_gate=False,
                                          report_path=bvh.with_suffix(".conversion.json"))
                else:
                    convert_continuous_joints(snapshot, bvh, fps=fps)
                paths.append(bvh)
            sequence = load_bvh_pair(paths)
            reports[method] = inspect(sequence, config_path=policy)
            _write_report(directory / "quality", reports[method])
            fidelity_rows[method] = [fidelity(target[:, actor], sequence.positions[:, actor]) for actor in range(len(snapshots))]
            candidates[method] = paths
        except Exception as exc:
            if method == "momask":
                raise
            # A candidate failure leaves the established converter available.
            selection = {"selected": "momask", "reasons": [f"Continuous converter unavailable: {type(exc).__name__}: {exc}"]}
    if "continuous" in candidates:
        selection = select_converter(reports["momask"], reports["continuous"], fidelity_rows["momask"],
                                     fidelity_rows["continuous"], config_path=policy)
    for actor, source in enumerate(candidates[selection["selected"]], 1):
        destination = output / f"repaired_actor{actor}.bvh"
        shutil.copyfile(source, destination)
        provenance = json.loads(source.with_suffix(".conversion.json").read_text(encoding="utf-8"))
        provenance.update(published_bvh=str(destination), selected_converter=selection["selected"],
                          selection_report=str(output / "converter_selection.json"))
        _write_json(destination.with_suffix(".conversion.json"), provenance)
    _write_json(output / "converter_selection.json", selection)
    return selection
