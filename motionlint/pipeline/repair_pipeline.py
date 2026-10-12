"""Apply bounded repairs, inspect again, and reject harmful candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np

from motionlint.core.config import load_config
from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.result import MotionQualityReport
from motionlint.pipeline.inspector import inspect
from motionlint.repairs.collision_repair import repair_collisions, repair_lodge_collisions
from motionlint.repairs.bone_length import project_bone_lengths
from motionlint.repairs.inter_actor import separate_actors
from motionlint.repairs.foot_lock import repair_foot_sliding
from motionlint.repairs.seam_repair import repair_seams
from motionlint.repairs.support_metrics import compare_support

REPAIR_ALGORITHM_VERSION = 6


def summarize_issues(before: dict, after: dict) -> list[dict]:
    """Report unique affected frames, rather than calling every issue fixed."""
    current = {test["test_name"]: test for test in after["tests"]}
    rows = []
    def frames(test):
        values = set()
        for issue in test["issues"]:
            values.update(range(issue["start_frame"], issue["end_frame"] + 1))
        return len(values)
    for old in before["tests"]:
        new = current[old["test_name"]]
        row = {"test": old["test_name"], "segments_before": len(old["issues"]), "segments_after": len(new["issues"]),
               "frames_before": frames(old), "frames_after": frames(new)}
        if old["test_name"] == "foot_sliding":
            row.update(sliding_frames_before=old["metrics"].get("sliding_frame_count"),
                       sliding_frames_after=new["metrics"].get("sliding_frame_count"))
        rows.append(row)
    return rows


@dataclass
class RepairOutcome:
    motion: MotionSequence
    before: MotionQualityReport
    after: MotionQualityReport
    raw_lodge: np.ndarray | None
    steps: list[dict]
    support_comparison: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        statuses = {s['status'] for s in self.steps}
        status = 'accepted' if any(s['applied'] for s in self.steps) else next(
            (s for s in ('failed', 'rejected', 'unsupported', 'no_op') if s in statuses), 'no_op')
        return {"algorithm_version": REPAIR_ALGORITHM_VERSION, "status": status,
                "reason_codes": sorted({code for step in self.steps for code in step.get('rejection_codes', [])}),
                "before_score": self.before.overall_score, "after_score": self.after.overall_score,
                "improvement": round(self.after.overall_score - self.before.overall_score, 2), "steps": self.steps,
                "schema_version": 3, "metadata": self.after.metadata,
                "before_metadata": self.before.metadata,
                "support_comparison": self.support_comparison,
                "final_selection": [{"repair": step["repair"], "status": step["status"], "variant": step.get("variant"), "applied": step["applied"]} for step in self.steps],
                "issue_summary": summarize_issues(self.before.to_dict(), self.after.to_dict())}


def _test(report: MotionQualityReport, name: str):
    return next(test for test in report.tests if test.test_name == name)


def _support_comparison(original, candidate, report, config):
    if (_test(report, "foot_sliding").metrics.get("evaluation_status") == "unavailable"
            or not original.metadata.get("foot_joint_ids") or original.frame_count < 2):
        return {"available": False, "reason": "No original support intervals could be evaluated"}
    result = compare_support(original, candidate, config["tests"]["foot_sliding"])
    return {"available": bool(result["per_foot"]), **result}


def _assess(name, target, original, candidate, before, after, config, ablations=frozenset()):
    from motionlint.pipeline.safety import audit
    limits = config["repairs"][name]
    bound = limits.get("max_correction_m", limits.get("max_actor_shift_m", limits.get("max_wrist_shift_m")))
    safety = audit(before, after, config, baseline_motion=original, candidate_motion=candidate,
                   movement_bound_m=bound, allow_bone_repair=target == "skeleton_integrity", ignore=ablations)
    previous = {t.test_name: t for t in before.tests}
    guard = safety["support_guard"]
    reasons, codes = list(safety["regression_reasons"]), list(safety["rejection_codes"])
    target_improved = (_test(after, target).score > previous[target].score or (name == "foot_lock" and guard.get("improved", False)))
    if not target_improved:
        codes.append("target_not_improved"); reasons.append("Target metric did not improve")
    contact_ok = "contact" in ablations or guard.get("improved" if name == "foot_lock" else "not_worsened", True)
    if not contact_ok and not codes:
        codes.append("fixed_support_not_improved"); reasons.append("Original support intervals did not improve")
    # Existing partially evaluated inputs can receive supported repairs, but the
    # public strict comparison remains incomplete and the full gate fails.
    assessment = {"repair": name, "applied": target_improved and not reasons and contact_ok,
                  "target_before": previous[target].score, "target_after": _test(after, target).score,
                  "overall_before": before.overall_score, "overall_after": after.overall_score,
                  **{k: safety[k] for k in ("other_test_drops", "newly_failed_tests", "new_severe_issue_frames",
                     "newly_unavailable_tests", "support_guard", "bone_constraint_ok", "max_joint_shift_m",
                     "movement_bound_m", "bound_exceeded")},
                  "comparison_incomplete_reasons": safety["incomplete_reasons"],
                  "rejection_codes": codes, "rejection_reasons": reasons,
                  "new_critical_issue_count": sum(i.severity == "critical" for t in after.tests for i in t.issues)
                      - sum(i.severity == "critical" for t in before.tests for i in t.issues)}
    if reasons: assessment["reason"] = reasons[0]
    return assessment


def repair(motion: MotionSequence, *, raw_lodge: np.ndarray | None = None, config_path=None, experimental_ablations=frozenset()) -> RepairOutcome:
    if not set(experimental_ablations) <= {"contact", "regression"}:
        raise ValueError("Unknown experimental ablation")
    config = load_config(config_path) if config_path is not None else load_config()
    from motionlint.core.context import freeze_floor
    motion = freeze_floor(motion, config)
    before = inspect(motion, config_path=config_path)
    current_motion, current_report, current_raw = motion, before, raw_lodge
    steps = []
    for name, target in (("foot_lock", "foot_sliding"), ("seam_repair", "temporal_continuity"),
                         ("bone_length_projection", "skeleton_integrity"), ("inter_actor_separation", "collision"), ("collision_repair", "collision")):
        step_input = current_motion
        repairable = [issue for issue in _test(current_report, target).issues
                      if issue.repairable and issue.recommended_repair == name]
        if not repairable:
            steps.append({"repair": name, "applied": False, "reason": "No supported repairable issue", "status": "unsupported" if _test(current_report, target).issues or _test(current_report, target).metrics.get('reason') else "no_op"})
            continue
        if current_motion.source == 'bvh' and name != 'foot_lock':
            steps.append({'repair': name, 'applied': False, 'status': 'unsupported',
                          'reason': 'BVH currently supports mapped leg IK only; other changes require animation authoring'})
            continue
        if current_motion.source == 'bvh' and name == 'foot_lock':
            lookup = {joint: index for index, joint in enumerate(current_motion.joint_names)}
            chains = [[lookup.get(side + suffix) for suffix in ('UpLeg', 'Leg', 'Foot', 'Toe')] for side in ('Left', 'Right')]
            complete = all(all(joint is not None for joint in chain) for chain in chains)
            if not complete or any(current_motion.metadata['parents'][child] != parent for chain in chains for parent, child in zip(chain, chain[1:])):
                steps.append({'repair': name, 'applied': False, 'status': 'unsupported',
                              'reason': 'BVH foot lock needs mapped hip/knee/ankle/toe chains with a direct hierarchy'})
                continue
        # A small fixed candidate set limits movement and allows a gentler IK
        # candidate when full locking would cause a jerk regression.
        variants = [{}]
        if name == "bone_length_projection":
            variants = [{"endpoint_strength": value} for value in (0., .25, .5, 1.)]
        elif name == "foot_lock":
            follow = current_motion.source == "lodge"
            variants = [{"correction_strength": value, "root_follow": follow} for value in (1., .5, .25)]
            variants.append({"correction_strength": 1., "blend_frames": 8, "root_follow": follow})
            variants.append({"passes": 2, "max_correction_m": .075, "root_follow": follow})
            variants.extend({"anchor_method": "interval", "correction_strength": strength, "root_follow": follow}
                            for strength in (1., .5))
            variants.extend({"anchor_method": "interval", "correction_strength": strength,
                             "root_follow": follow, "smooth_frames": window}
                            for strength, window in ((1., 5), (.5, 5), (1., 9)))
            if not follow:
                variants.append({"correction_strength": .5, "root_follow": True})
            variants.extend({"anchor_method": method, "root_follow": True, "root_method": "support",
                             "smooth_frames": smooth, "center_method": "bounds"}
                            for method, smooth in (("interval", 0), ("velocity", 0), ("velocity", 5)))
        if name == "foot_lock":
            from motionlint.repairs.optimized_root import available
            if available():
                variants.extend({"optimizer_mode": mode} for mode in ("coupled", "shared"))
        trials, best = [], None
        for variant in variants:
            if "optimizer_mode" in variant and best is not None and best[4]["support_guard"].get("original_support_distance_after_m", 1) < 1e-7:
                continue
            settings = {**config["repairs"][name], **variant}
            passes = settings.pop("passes", 1)
            try:
                if name == "seam_repair":
                    settings["boundary_frames"] = sorted({issue.start_frame for issue in repairable})
                    settings["rotation_joint_ids"] = sorted({joint for issue in repairable if issue.metric == "angular_step_deg" for joint in issue.joint_ids})
                    settings["repair_translation"] = any(issue.metric == "root_step_m" for issue in repairable)
                    candidate, candidate_raw, detail = repair_seams(current_motion, raw=current_raw, **settings)
                elif name == "foot_lock":
                    support_settings = config["tests"]["foot_sliding"]
                    foot_source = current_motion
                    if "contact" in experimental_ablations:
                        from dataclasses import replace
                        foot_source = replace(current_motion, contacts=None)
                        support_settings = {**support_settings, "contact_height_m": 1000., "vertical_speed_m_s": 1e12}
                    if "optimizer_mode" in settings:
                        from motionlint.repairs.optimized_root import repair_optimized
                        candidate, candidate_raw, detail = repair_optimized(foot_source, repairable, raw=current_raw, support_settings=support_settings, **settings)
                    else:
                        candidate, candidate_raw, detail = repair_foot_sliding(foot_source, repairable, raw=current_raw, support_settings=support_settings, **settings)
                    repetitions = []
                    for _ in range(passes - 1):
                        remaining = _test(inspect(candidate, config_path=config_path), "foot_sliding").issues
                        if not remaining:
                            break
                        candidate, candidate_raw, repeated = repair_foot_sliding(candidate, remaining, raw=candidate_raw,
                            support_settings=support_settings, **settings)
                        repetitions.append(repeated)
                    detail["repeat_passes"] = repetitions
                    up = int(current_motion.metadata.get("up_axis", 1))
                    axes = [axis for axis in range(3) if axis != up]
                    feet = current_motion.metadata["foot_joint_ids"]
                    displacement = candidate.positions[:, :, feet][:, :, :, axes] - current_motion.positions[:, :, feet][:, :, :, axes]
                    detail["cumulative_foot_shift_m"] = float(np.linalg.norm(displacement, axis=-1).max())
                    if detail["cumulative_foot_shift_m"] > config["repairs"][name]["max_correction_m"] + 1e-6:
                        trials.append({"repair": name, "applied": False, "reason": "Cumulative foot movement exceeds bound",
                                       "detail": detail, "status": "rejected", "variant": variant})
                        continue
                elif name == "bone_length_projection":
                    candidate, detail = project_bone_lengths(current_motion, **settings)
                    candidate_raw = current_raw
                elif name == "inter_actor_separation":
                    candidate, detail = separate_actors(current_motion, config["tests"]["collision"], **settings)
                    candidate_raw = current_raw
                    foot_test = _test(inspect(candidate, config_path=config_path), "foot_sliding")
                    if foot_test.issues:
                        candidate, _, foot_detail = repair_foot_sliding(candidate, foot_test.issues,
                            support_settings=config["tests"]["foot_sliding"], root_follow=False, **config["repairs"]["foot_lock"])
                        detail["followup_foot_ik"] = foot_detail
                else:
                    if current_motion.source == "lodge":
                        candidate, candidate_raw, detail = repair_lodge_collisions(current_motion, raw=current_raw,
                            settings=config["tests"]["collision"], **settings)
                    else:
                        candidate, detail = repair_collisions(current_motion)
                        candidate_raw = current_raw
            except ValueError as exc:
                trials.append({"repair": name, "applied": False, "reason": str(exc), "status": "failed", "variant": variant})
                continue
            candidate.metadata = {**candidate.metadata, "stage": "repaired"}
            candidate_report = inspect(candidate, config_path=config_path)
            trial = _assess(name, target, current_motion, candidate, current_report, candidate_report, config, experimental_ablations)
            input_guard = _support_comparison(motion, candidate, before, config)
            trial["input_support_guard"] = input_guard
            if input_guard["available"] and not input_guard["not_worsened"] and "contact" not in experimental_ablations:
                trial["applied"] = False
                trial["reason"] = "Supported feet regressed against the original input"
                trial["rejection_codes"].append("input_support_regressed")
                trial["rejection_reasons"].append(trial["reason"])
            cumulative = float(np.linalg.norm(candidate.positions - motion.positions, axis=-1).max())
            total_bound = float(config["repairs"].get("max_total_shift_m", .20))
            trial.update(cumulative_max_joint_shift_m=cumulative, cumulative_movement_bound_m=total_bound)
            if cumulative > total_bound + 1e-6:
                trial["applied"] = False
                trial["reason"] = "Total movement from original input exceeds configured bound"
                trial["rejection_codes"].append("total_movement_bound_exceeded")
                trial["rejection_reasons"].append(trial["reason"])
            if experimental_ablations:
                trial["experimental_only"] = True
                trial["ablations"] = sorted(experimental_ablations)
            trial["status"] = "accepted" if trial["applied"] else "rejected"
            trial["detail"], trial["variant"] = detail, variant
            trial["candidate_report"] = candidate_report.to_dict()
            if not trial["applied"]:
                if detail.get("reason"):
                    trial["reason"] = detail["reason"]
                    trial["rejection_reasons"].insert(0, detail["reason"])
                trial.setdefault("reason", "Candidate did not improve within the movement, bone, regression and support constraints")
            trials.append(trial)
            key = ((-round(trial["support_guard"].get("original_support_distance_after_m", 0.), 6) if name == "foot_lock" else _test(candidate_report, target).score),
                   -trial["max_joint_shift_m"], candidate_report.overall_score)
            if trial["applied"] and (best is None or key > best[0]):
                best = (key, candidate, candidate_report, candidate_raw, trial)
        if best is not None:
            _, current_motion, current_report, current_raw, selected = best
            step = dict(selected)
        else:
            step = dict(trials[0])
        step["candidate_trials"] = trials
        if name == "foot_lock":
            from motionlint.repairs.optimized_root import available, budget_diagnostic
            step["optimization_available"] = available()
            step["constraint_diagnostic"] = budget_diagnostic(step_input, config["tests"]["foot_sliding"], config["repairs"]["foot_lock"]["max_correction_m"])
            step["solver_scope"] = "Convex subproblem followed by geometry and full regression checks; solver failure is not full-problem infeasibility"
        steps.append(step)
    return RepairOutcome(current_motion, before, current_report, current_raw, steps,
                         _support_comparison(motion, current_motion, before, config))
