"""Shared physical regression audit. Reports alone cannot establish a PASS."""
from __future__ import annotations
import numpy as np
from motionlint.core.floor import floor_heights
from motionlint.core.provenance import evaluated_array_hashes
from motionlint.repairs.support_metrics import compare_support


def new_severe_frames(before, after):
    def windows(report):
        result = {}
        for test in report.tests:
            for issue in test.issues:
                if issue.severity not in {"high", "critical"}:
                    continue
                key = (test.test_name, issue.actor_id, tuple(sorted(issue.joint_ids)),
                       issue.other_actor_id, tuple(sorted(issue.other_joint_ids)), issue.metric)
                result.setdefault(key, set()).update(range(max(0, issue.start_frame), issue.end_frame + 1))
        return result
    old, counts = windows(before), {}
    for key, frames in windows(after).items():
        count = len(frames - old.get(key, set()))
        if count:
            counts[key[0]] = counts.get(key[0], 0) + count
    return counts


def audit(baseline, candidate, config, *, baseline_motion=None, candidate_motion=None,
          movement_bound_m=None, allow_bone_repair=False, ignore=frozenset()):
    old = {test.test_name: test for test in baseline.tests}
    new = {test.test_name: test for test in candidate.tests}
    reasons, codes, incomplete = [], [], []
    def reject(code, message):
        if code not in codes:
            codes.append(code)
        reasons.append(message)
    drops, failures, lost = {}, [], []
    for name in config["tests"]:
        if name not in old or name not in new:
            incomplete.append(f"Missing comparison test: {name}")
            continue
        unavailable = old[name].metrics.get("evaluation_status") == "unavailable"
        if unavailable:
            incomplete.append(f"{name} unavailable in baseline")
        if new[name].metrics.get("evaluation_status") == "unavailable":
            incomplete.append(f"{name} unavailable in candidate")
            if not unavailable:
                lost.append(name)
        if not unavailable:
            if new[name].status == "FAIL" and old[name].status != "FAIL":
                failures.append(name)
            if old[name].score - new[name].score > config["regression"]["max_test_score_drop"]:
                drops[name] = round(old[name].score - new[name].score, 2)
    severe = new_severe_frames(baseline, candidate)
    if "regression" not in ignore:
        for name, drop in drops.items():
            reject("other_test_score_decreased", f"{name} decreased by {drop:.2f} points")
        for name in failures:
            reject("new_failed_test", f"{name} newly failed")
        for name in lost:
            reject("evaluation_coverage_lost", f"{name} unavailable in candidate; evaluation coverage was lost")
        for name, count in severe.items():
            reject("new_severe_issue_frames", f"{name} has {count} new severe issue frames")
        if baseline.overall_score > candidate.overall_score + .001:
            reject("overall_score_decreased", "Overall quality score decreased")
    support, maximum, bone_ok = {}, None, True
    bound = float(movement_bound_m if movement_bound_m is not None else config["repairs"].get("max_total_shift_m", .20))
    if baseline_motion is None or candidate_motion is None:
        incomplete.append("Original and candidate arrays with a shared timeline are required")
    else:
        a, b = baseline_motion, candidate_motion
        old_code, new_code = baseline.metadata.get('detector_code_sha256'), candidate.metadata.get('detector_code_sha256')
        if old_code != new_code:
            incomplete.append('Detector code differs; re-inspect both arrays with one frozen implementation')
        context_old=baseline.metadata.get('evaluation_context')
        context_new=candidate.metadata.get('evaluation_context')
        if context_old is not None and context_new is not None:
            differences=[field for field in context_old if context_old.get(field)!=context_new.get(field)]
            if differences:
                incomplete.append('Evaluation context differs: '+', '.join(differences))
        else:
            incomplete.append('Missing evaluation context; re-inspect both arrays')
        mismatches = [field for field in ("fps", "frame_count", "actor_count", "joint_names") if getattr(a, field) != getattr(b, field)]
        for field, default in (("up_axis", 1), ("unit_scale", 1.), ("parents", None), ("foot_joint_ids", [])):
            if a.metadata.get(field, default) != b.metadata.get(field, default):
                mismatches.append(field)
        if a.positions is None or b.positions is None or a.positions.shape != b.positions.shape:
            mismatches.append("positions")
        if mismatches:
            incomplete.append("Motions lack consistent mapping or time correspondence: " + ", ".join(mismatches))
        else:
            for motion, report, label in ((a, baseline, "baseline"), (b, candidate, "candidate")):
                expected = report.metadata.get("evaluated_array_sha256", {}).get("positions")
                if expected and expected != evaluated_array_hashes(motion)["positions"]:
                    incomplete.append(f"{label} report does not describe the supplied arrays")
            maximum = float(np.linalg.norm(b.positions - a.positions, axis=-1).max())
            if maximum > bound + 1e-6:
                reject("movement_bound_exceeded", "Joint movement exceeds the configured bound")
            parents = a.metadata.get("parents")
            if parents is None:
                incomplete.append("Missing skeleton hierarchy for bone constraint audit")
            else:
                helpers = set(a.metadata.get('non_anatomical_bone_ids', [])) if config['tests']['skeleton_integrity'].get('ignore_declared_helpers') else set()
                ids = [i for i, p in enumerate(parents) if p >= 0 and i not in helpers]
                parent_ids = np.asarray(parents)[ids]
                lengths = [np.linalg.norm(m.positions[:, :, ids] - m.positions[:, :, parent_ids], axis=-1) for m in (a, b)]
                reference = np.median(lengths[0], axis=0)
                old_error = np.max(np.abs(lengths[0] - reference), axis=0)
                new_error = np.max(np.abs(lengths[1] - reference), axis=0)
                bone_ok = bool(np.all(new_error <= old_error + 1e-5))
                if not bone_ok:
                    reject("bone_constraint_violated", "Bone lengths depart further from the input rest dimensions")
            feet = a.metadata.get("foot_joint_ids", [])
            if feet and a.frame_count >= 2 and old.get("foot_sliding"):
                up = int(a.metadata.get("up_axis", 1))
                settings = config["tests"]["foot_sliding"]
                floors = [floor_heights(m, m.positions[:, :, feet, up], settings)[0] for m in (a, b)]
                if not np.allclose(floors[0], floors[1], atol=1e-6, rtol=0):
                    incomplete.append("Ground conditions differ; re-inspect with a frozen explicit floor")
                support = compare_support(a, b, settings)
                support["available"] = bool(support["per_foot"])
                if not support["available"]:
                    incomplete.append("No original support intervals could be evaluated")
                if "contact" not in ignore:
                    if not support['contact_preserved']:
                        reject('original_contact_lost', 'An originally supported foot lost its contact evidence or height constraint')
                    if not support["distance_not_worsened"]:
                        reject("supported_foot_distance_increased", "A supported foot accumulated more sliding distance")
                    if any(not row["sliding_not_worsened"] for row in support["per_foot"]):
                        reject("supported_foot_sliding_increased", "A supported foot gained sliding intervals")
                    if any(not row["peak_not_worsened"] for row in support["per_foot"]):
                        reject("supported_foot_peak_speed_increased", "A supported foot gained excessive peak sliding speed")
            else:
                incomplete.append("No original support data for physical comparison")
    return {"regression_reasons": reasons, "rejection_codes": codes, "incomplete_reasons": list(dict.fromkeys(incomplete)),
            "new_severe_issue_frames": severe, "newly_failed_tests": failures, "newly_unavailable_tests": lost,
            "other_test_drops": drops, "support_guard": support, "max_joint_shift_m": maximum,
            "movement_bound_m": bound, "bound_exceeded": maximum is not None and maximum > bound + 1e-6,
            "bone_constraint_ok": bone_ok}
