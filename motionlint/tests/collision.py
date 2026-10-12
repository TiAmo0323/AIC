"""Lightweight skeleton collision checks; reuses the existing segment geometry."""

from __future__ import annotations

import numpy as np

from motionlint.core.geometry import segment_point_distances as _segment_point_distances
from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.result import MotionIssue, TestResult
from motionlint.tests.common import result, segments


def check(motion: MotionSequence, settings: dict) -> TestResult:
    name = "collision"
    if motion.positions is None or motion.joint_names is None:
        return TestResult(name, "WARN", 0, metrics={"reason": "No global joints"})
    positions = motion.positions
    lookup = {joint: index for index, joint in enumerate(motion.joint_names)}
    if not {"Head", "LeftHand", "RightHand", "LeftForeArm", "RightForeArm", "LeftArm", "RightArm"} <= lookup.keys():
        return TestResult(name, "WARN", 0, metrics={"reason": "Missing canonical head/arm mapping; collision coverage unavailable"})
    issues: list[MotionIssue] = []
    measurements, exclusions = [], []
    allowed = motion.metadata.get('allowed_contacts', []) if settings.get('explicit_contact_intervals') else []
    if not isinstance(allowed, list):
        raise ValueError('allowed_contacts must be a list of explicit joint pairs and frame intervals')
    for contact in allowed:
        if (not isinstance(contact, dict) or not isinstance(contact.get('start_frame'), int)
                or not isinstance(contact.get('end_frame'), int)
                or not 0 <= contact['start_frame'] <= contact['end_frame'] < motion.frame_count
                or any(not isinstance(contact.get(key), int) or not 0 <= contact[key] < motion.actor_count
                       for key in ('actor_id', 'other_actor_id'))
                or any(contact.get(key) not in lookup for key in ('joint', 'other_joint'))):
            raise ValueError('Invalid explicit allowed contact: actors, mapped joints and inclusive frame interval required')

    def risk_mask(distance, threshold, metric, actor, joints, other_actor=None):
        mask = distance < threshold
        if settings.get('explicit_contact_intervals'):
            measurements.append({'metric': metric, 'actor_id': actor, 'joint_ids': joints,
                                 'other_actor_id': other_actor, 'threshold': threshold,
                                 'distance_m': distance.tolist()})
        # A segment test cannot be exempted by a point pair declaration.
        if len(joints) == 2:
            second_actor = actor if other_actor is None else other_actor
            pair = {(actor, motion.joint_names[joints[0]]), (second_actor, motion.joint_names[joints[1]])}
            for contact in allowed:
                declared = {(contact['actor_id'], contact['joint']), (contact['other_actor_id'], contact['other_joint'])}
                if pair == declared:
                    start, end = contact['start_frame'], contact['end_frame']
                    exclusions.append({'metric': metric, 'declaration': dict(contact),
                                       'excluded_risk_frames': int(mask[start:end + 1].sum()),
                                       'minimum_distance_m': float(distance[start:end + 1].min())})
                    mask[start:end + 1] = False
        return mask

    def compare_distance(a: np.ndarray, b: np.ndarray, threshold: float, metric: str, actor: int | None, joints: list[int], message: str, other_actor: int | None = None) -> None:
        distance = np.linalg.norm(a - b, axis=-1)
        for start, end in segments(risk_mask(distance, threshold, metric, actor, joints, other_actor)):
            repair_name = None
            if motion.source in {"intergen", "lodge"} and actor is not None:
                if other_actor is None:
                    repair_name = "collision_repair"
                elif motion.source == "intergen" and motion.actor_count == 2 and metric in {"head_head_distance_m", "torso_torso_distance_m"}:
                    repair_name = "inter_actor_separation"
            issues.append(MotionIssue(name, "high", start, end, metric, float(np.min(distance[start:end + 1])), threshold, message, actor_id=actor, joint_ids=joints[:1] if other_actor is not None else joints, repairable=repair_name is not None, recommended_repair=repair_name, other_actor_id=other_actor, other_joint_ids=joints[1:] if other_actor is not None else []))

    if {"Head", "LeftHand", "RightHand", "LeftForeArm", "RightForeArm", "LeftArm", "RightArm"} <= lookup.keys():
        head = lookup["Head"]
        for actor in range(motion.actor_count):
            for side in ("Left", "Right"):
                wrist = lookup[f"{side}Hand"]
                elbow = lookup[f"{side}ForeArm"]
                compare_distance(positions[:, actor, wrist], positions[:, actor, head], float(settings["wrist_head_clearance_m"]), "wrist_head_distance_m", actor, [wrist, head], f"{side} hand is near head")
                distances, _, _ = _segment_point_distances(positions[:, actor, elbow], positions[:, actor, wrist], positions[:, actor, head])
                threshold = float(settings["forearm_head_clearance_m"])
                for start, end in segments(risk_mask(distances, threshold, 'forearm_head_distance_m', actor, [elbow, wrist, head])):
                    supported = motion.source in {"intergen", "lodge"}
                    issues.append(MotionIssue(name, "high", start, end, "forearm_head_distance_m", float(np.min(distances[start:end + 1])), threshold, f"{side} forearm is near head", actor_id=actor, joint_ids=[elbow, wrist, head], repairable=supported, recommended_repair="collision_repair" if supported else None))

    if motion.actor_count >= 2 and {"Head", "Hips", "LeftHand", "RightHand"} <= lookup.keys():
        for left in range(motion.actor_count):
            for right in range(left + 1, motion.actor_count):
                for first, second, threshold_name, metric in (
                    ("Head", "Head", "head_head_clearance_m", "head_head_distance_m"),
                    ("Hips", "Hips", "torso_torso_clearance_m", "torso_torso_distance_m"),
                    ("LeftHand", "Head", "wrist_head_clearance_m", "hand_head_distance_m"),
                    ("RightHand", "Head", "wrist_head_clearance_m", "hand_head_distance_m"),
                ):
                    a, b = lookup[first], lookup[second]
                    compare_distance(positions[:, left, a], positions[:, right, b], float(settings[threshold_name]), metric, left, [a, b], f"Actor {left} {first} intersects actor {right} {second}", other_actor=right)

                # Versioned opt-in keeps reports frozen with older policies
                # reproducible. Check both directions and the torso segment.
                if settings.get("extended_inter_actor_checks", False):
                    for actor, other in ((left, right), (right, left)):
                        for side in ("Left", "Right"):
                            wrist = lookup[side + "Hand"]
                            if actor == right:
                                compare_distance(positions[:, actor, wrist], positions[:, other, lookup["Head"]],
                                                 float(settings["wrist_head_clearance_m"]), "hand_head_distance_m", actor,
                                                 [wrist, lookup["Head"]], "Other actor's hand is near head", other_actor=other)
                            torso_top = lookup.get("Neck", lookup.get("Spine2", lookup["Head"]))
                            distance, _, _ = _segment_point_distances(positions[:, other, lookup["Hips"]],
                                                                    positions[:, other, torso_top], positions[:, actor, wrist])
                            threshold = float(settings["wrist_head_clearance_m"])
                            for start, end in segments(risk_mask(distance, threshold, 'hand_torso_distance_m', actor, [wrist, lookup['Hips'], torso_top], other)):
                                issues.append(MotionIssue(name, "high", start, end, "hand_torso_distance_m",
                                    float(distance[start:end + 1].min()), threshold, "Hand is near the other actor's torso segment",
                                    actor_id=actor, joint_ids=[wrist], other_actor_id=other,
                                    other_joint_ids=[lookup["Hips"], torso_top], repairable=False))

    affected = np.zeros(motion.frame_count, dtype=bool)
    for issue in issues:
        issue.penetration_estimate_m = max(0., issue.threshold - issue.value)
        affected[issue.start_frame:issue.end_frame + 1] = True
    metrics = {"collision_segment_count": len(issues), "collision_frame_count": int(affected.sum()),
               "maximum_penetration_estimate_m": max((issue.penetration_estimate_m for issue in issues), default=0.),
               "minimum_distance_m": min((issue.value for issue in issues), default=None),
               "clearance_deficit_m": max((issue.penetration_estimate_m for issue in issues), default=0.),
               "expected_contact_policy": "Only explicitly declared joint pairs and frame intervals are exempted; no prompt-derived exemptions",
               "geometry_limits": "Skeleton clearance deficit; not measured mesh penetration"}
    if settings.get('explicit_contact_intervals'):
        metrics.update(distance_measurements=measurements, contact_exclusions=exclusions)
    return result(name, issues, metrics, motion.frame_count, motion.actor_count, 4)
