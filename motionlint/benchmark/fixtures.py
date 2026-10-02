"""Self-authored motion fixtures; no model, licensed geometry or checkpoint."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
from motionlint.adapters.intergen_adapter import JOINT_NAMES, PARENTS

TESTS = ("temporal_continuity", "skeleton_integrity", "foot_sliding", "ground_contact", "collision", "motion_jerk")


def standing(frames=300):
    # Independently authored coordinates, metres/Y-up; not SMPL-X rest joints.
    point = np.array([[0,1,0], [.1,.9,0], [-.1,.9,0], [0,1.12,0], [.1,.45,.025], [-.1,.45,.025],
                      [0,1.25,0], [.1,.03,0], [-.1,.03,0], [0,1.4,0], [.1,0,.15], [-.1,0,.15],
                      [0,1.55,0], [.14,1.45,0], [-.14,1.45,0], [0,1.72,0], [.3,1.44,0], [-.3,1.44,0],
                      [.55,1.42,0], [-.55,1.42,0], [.8,1.4,0], [-.8,1.4,0]], dtype=float)
    return np.repeat(point[None], frames, axis=0)


def build(output: str | Path):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for kind in (*TESTS, "clean"):
        count = 30 if kind == "clean" else 15
        for index in range(count):
            seed, severity = 41000 + index, index // 5
            rng = np.random.default_rng(seed)
            positions = standing()
            positions *= rng.uniform(.9,1.1)
            positions[..., 0] *= rng.uniform(.9,1.1)
            positions[..., 2] += rng.uniform(-.01, .01)
            start = int(rng.integers(90,160))
            end, value, joints = start+int(rng.integers(25,50)), 0., []
            original_arm_length = float(np.linalg.norm(positions[0,20]-positions[0,18]))
            if kind == "temporal_continuity":
                value = (.24, .36, .48)[severity]
                positions[start:, :, 0] += value
                end, joints = start, [0]
            elif kind == "skeleton_integrity":
                value = (.2, .35, .5)[severity]
                positions[start:end+1, 20, 0] += value
                joints = [18, 20]
            elif kind == "foot_sliding":
                value = (.20, .28, .36)[severity]
                # Translate the whole rigid skeleton: no change to bone lengths.
                ramp = np.clip(np.arange(len(positions)) - (start-1), 0, end-start+1) * value / 30
                positions[..., 0] += ramp[:, None]
                joints = [10, 11]
            elif kind == "ground_contact":
                value = (.06, .09, .12)[severity]
                positions[start:end+1, :, 1] -= value
                joints = [7, 8, 10, 11]
            elif kind == "collision":
                value = (.08, .05, .02)[severity]
                positions[start:end+1, 20] = positions[start:end+1, 15] + [value, 0, 0]
                joints = [20, 15]
            elif kind == "motion_jerk":
                value = (.01, .015, .02)[severity]
                positions[start:end+1, 20, 2] += value * np.where(np.arange(end-start+1) % 2, 1., -1.)
                # Third differences include the next three derivative frames.
                end += 3
                joints = [20]
            path = output / f"{kind}_{index:02d}.npy"
            np.save(path, positions)
            # Analytic quantities describe the injection, independently of detectors.
            actual_arm_length = float(np.linalg.norm(positions[start,20]-positions[start,18]))
            actual = {"temporal_continuity": value, "skeleton_integrity": abs(actual_arm_length-original_arm_length) / original_arm_length,
                      "foot_sliding": value, "ground_contact": value, "collision": value,
                      "motion_jerk": 8*value*30**3}.get(kind, 0.)
            truth = [] if kind == "clean" else [{"test_name": kind, "actor_id": 0, "joint_ids": joints,
                                                "start_frame": start, "end_frame": end, "uncertain": False}]
            rows.append({"id": path.stem, "input": path.name, "fps": 30, "seed": seed,
                         "floor_height_m": 0., "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                         "evaluated_tests": list(TESTS) if kind == "clean" else [kind], "events": truth,
                         "injection": {"type": kind, "severity": severity, "parameter": value, "analytic_quantity": actual}})
    manifest = {"schema_version": 1, "purpose": "Controlled target-test evaluation; collateral checks on injected clips are unlabelled, not negatives",
                "provenance": "Self-authored procedural skeleton and injected defects; not human validation", "motions": rows}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import sys
    result = build(sys.argv[1] if len(sys.argv) > 1 else "demo")
    print(f"Created {len(result['motions'])} self-authored fixtures")
