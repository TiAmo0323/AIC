"""Apply bounded repairs, inspect again, and reject harmful candidates."""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from motionlint.core.config import load_config
from motionlint.core.foot_support import estimate_support
from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.result import MotionQualityReport
from motionlint.pipeline.inspector import inspect
from motionlint.repairs.collision_repair import repair_collisions, repair_lodge_collisions
from motionlint.repairs.bone_length import project_bone_lengths
from motionlint.repairs.inter_actor import separate_actors
from motionlint.repairs.foot_lock import repair_foot_sliding
from motionlint.repairs.seam_repair import repair_seams


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

    def to_dict(self) -> dict:
        return {"algorithm_version": 4, "before_score": self.before.overall_score, "after_score": self.after.overall_score,
                "improvement": round(self.after.overall_score - self.before.overall_score, 2), "steps": self.steps,
                "schema_version": 2, "metadata": self.after.metadata,
                "before_metadata": self.before.metadata,
                "final_selection": [{"repair": step["repair"], "status": step["status"], "variant": step.get("variant"), "applied": step["applied"]} for step in self.steps],
                "issue_summary": summarize_issues(self.before.to_dict(), self.after.to_dict())}


def _test(report: MotionQualityReport, name: str):
    return next(test for test in report.tests if test.test_name == name)


def _assess(name, target, original, candidate, before, after, config, ablations=frozenset()):
    previous = {test.test_name: test for test in before.tests}
    drops = {test.test_name: round(previous[test.test_name].score - test.score, 2)
             for test in after.tests if test.test_name != target
             and previous[test.test_name].score - test.score > config["regression"]["max_test_score_drop"]}
    newly_failed = [test.test_name for test in after.tests if test.test_name != target
                    and test.status == "FAIL" and previous[test.test_name].status != "FAIL"]
    displacement = np.linalg.norm(candidate.positions - original.positions, axis=-1)
    maximum = float(displacement.max())
    limits = config["repairs"][name]
    bound = limits.get("max_correction_m", limits.get("max_actor_shift_m", limits.get("max_wrist_shift_m")))
    bound_exceeded = bound is not None and maximum > float(bound) + 1e-6
    old_critical = {(i.test_name, i.actor_id, tuple(i.joint_ids), i.start_frame, i.end_frame)
                    for t in before.tests for i in t.issues if i.severity == "critical"}
    new_critical = {(i.test_name, i.actor_id, tuple(i.joint_ids), i.start_frame, i.end_frame)
                    for t in after.tests for i in t.issues if i.severity == "critical"} - old_critical
    guard = {}
    if name in {"foot_lock", "inter_actor_separation"}:
        support = estimate_support(original, config["tests"]["foot_sliding"])
        up = int(original.metadata.get("up_axis", 1))
        axes = [axis for axis in range(3) if axis != up]
        counts = []
        for value in (original, candidate):
            speed = np.linalg.norm(np.diff(value.positions[:, :, support.feet][:, :, :, axes], axis=0), axis=-1) * value.fps
            counts.append(int(np.count_nonzero((speed > config["tests"]["foot_sliding"]["horizontal_speed_m_s"]) & support.intervals)))
        guard = {"original_support_sliding_before": counts[0], "original_support_sliding_after": counts[1],
                 "improved": counts[1] < counts[0], "not_worsened": counts[1] <= counts[0]}
    regression_ok = "regression" in ablations or (after.overall_score >= before.overall_score and not drops and not newly_failed)
    contact_ok = "contact" in ablations or guard.get("improved" if name == "foot_lock" else "not_worsened", True)
    bone_ok = (target == "skeleton_integrity" or _test(after,"skeleton_integrity").score >= previous["skeleton_integrity"].score - .001)
    accepted = (_test(after, target).score > previous[target].score and regression_ok
                and after.critical_issue_count <= before.critical_issue_count
                and not bound_exceeded and not new_critical
                and bone_ok
                and contact_ok)
    return {"repair": name, "applied": accepted, "target_before": previous[target].score,
            "target_after": _test(after, target).score, "overall_before": before.overall_score,
            "overall_after": after.overall_score, "other_test_drops": drops,
            "newly_failed_tests": newly_failed, "support_guard": guard, "bone_constraint_ok": bone_ok, "max_joint_shift_m": maximum, "movement_bound_m": bound, "bound_exceeded": bound_exceeded, "new_critical_issue_count": len(new_critical)}


def repair(motion: MotionSequence, *, raw_lodge: np.ndarray | None = None, config_path=None, experimental_ablations=frozenset()) -> RepairOutcome:
    if not set(experimental_ablations) <= {"contact", "regression"}:
        raise ValueError("Unknown experimental ablation")
    config = load_config(config_path) if config_path is not None else load_config()
    before = inspect(motion, config_path=config_path)
    current_motion, current_report, current_raw = motion, before, raw_lodge
    steps = []
    for name, target in (("foot_lock", "foot_sliding"), ("seam_repair", "temporal_continuity"),
                         ("bone_length_projection", "skeleton_integrity"), ("inter_actor_separation", "collision"), ("collision_repair", "collision")):
        repairable = [issue for issue in _test(current_report, target).issues
                      if issue.repairable and issue.recommended_repair == name]
        if not repairable:
            steps.append({"repair": name, "applied": False, "reason": "No supported repairable issue", "status": "unsupported" if _test(current_report, target).issues else "no_op"})
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
        trials, best = [], None
        for variant in variants:
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
                    candidate, candidate_raw, detail = repair_foot_sliding(foot_source, repairable, raw=current_raw,
                        support_settings=support_settings, **settings)
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
            cumulative = float(np.linalg.norm(candidate.positions - motion.positions, axis=-1).max())
            total_bound = float(config["repairs"].get("max_total_shift_m", .20))
            trial.update(cumulative_max_joint_shift_m=cumulative, cumulative_movement_bound_m=total_bound)
            if cumulative > total_bound + 1e-6:
                trial["applied"] = False
                trial["reason"] = "Total movement from original input exceeds configured bound"
            if experimental_ablations:
                trial["experimental_only"] = True
                trial["ablations"] = sorted(experimental_ablations)
            trial["status"] = "accepted" if trial["applied"] else "rejected"
            trial["detail"], trial["variant"] = detail, variant
            if not trial["applied"]:
                trial.setdefault("reason", detail.get("reason", "Candidate did not improve within the movement, bone, regression and support constraints"))
            trials.append(trial)
            key = (candidate_report.overall_score, _test(candidate_report, target).score)
            if trial["applied"] and (best is None or key > best[0]):
                best = (key, candidate, candidate_report, candidate_raw, trial)
        if best is not None:
            _, current_motion, current_report, current_raw, selected = best
            step = dict(selected)
        else:
            step = dict(trials[0])
        step["candidate_trials"] = trials
        steps.append(step)
    return RepairOutcome(current_motion, before, current_report, current_raw, steps)
