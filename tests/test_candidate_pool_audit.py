# 【实验测试，非生产链路验收】只验证候选审计代理指标和清单结构，
# 不会改变生产选中样本，也不能替代人工动作语义判断。
import json
import sys
import tempfile
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
INTERGEN_API_ROOT = REPO_ROOT / "InterGen_api"
if str(INTERGEN_API_ROOT) not in sys.path:
    sys.path.insert(0, str(INTERGEN_API_ROOT))

from candidate_pool_audit import compute_candidate_metrics, write_candidate_audit_manifest  # noqa: E402


def _actor(frames: int, pelvis_z: float, facing_positive_z: bool) -> np.ndarray:
    joints = np.zeros((frames, 22, 3), dtype=np.float32)
    joints[:, 0] = [0.0, 0.0, pelvis_z]
    joints[:, 12] = [0.0, 1.0, pelvis_z]
    left_x, right_x = (-0.3, 0.3) if facing_positive_z else (0.3, -0.3)
    joints[:, 16] = [left_x, 0.8, pelvis_z]
    joints[:, 17] = [right_x, 0.8, pelvis_z]
    joints[:, 20] = [left_x - 0.2, 0.6, pelvis_z]
    joints[:, 21] = [right_x + 0.2, 0.6, pelvis_z]
    return joints


def test_metrics_are_navigation_proxies():
    frames = 30
    actor_a = _actor(frames, pelvis_z=0.0, facing_positive_z=True)
    actor_b = _actor(frames, pelvis_z=2.0, facing_positive_z=False)
    actor_a[:, 21, 0] += np.sin(np.linspace(0.0, 2.0 * np.pi, frames))
    metrics = compute_candidate_metrics(actor_a, actor_b, fps=30)
    pair = metrics["pair_geometry"]
    assert metrics["metric_scope"] == "kinematic-proxies-only-not-semantic-acceptance"
    assert pair["mutual_facing_proxy_ratio"] == 1.0
    assert pair["forward_opposition_ratio"] == 1.0
    assert pair["horizontal_distance_mean"] == 2.0
    assert metrics["actor_a_arm_motion"]["dominant_motion_side"] == "right"


def test_manifest_retains_human_gate_as_pending():
    frames = 30
    actor_a = _actor(frames, pelvis_z=0.0, facing_positive_z=True)
    actor_b = _actor(frames, pelvis_z=2.0, facing_positive_z=False)
    with tempfile.TemporaryDirectory(prefix="candidate_audit_test_") as temp_dir:
        root = Path(temp_dir)
        video = root / "candidate.mp4"
        video.write_bytes(b"test-video")
        actor_a_path = root / "actor_a.npy"
        actor_b_path = root / "actor_b.npy"
        np.save(actor_a_path, actor_a)
        np.save(actor_b_path, actor_b)
        manifest_path = write_candidate_audit_manifest(
            root / "candidate_audit.json",
            task_id="audit-task",
            prompt="Two people play badminton.",
            candidate_summaries=[
                {
                    "candidate_index": 1,
                    "seed": 20260727,
                    "file_path": str(video),
                    "file_size": video.stat().st_size,
                    "fps": 30,
                    "raw_joints_files": [str(actor_a_path), str(actor_b_path)],
                    "self_collision": {},
                    "selected": True,
                }
            ],
            selected_sample=1,
            experiment_group="badminton-audit",
            experiment_variant="manual-plan",
        )
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert payload["status"] == "awaiting-human-review"
    assert payload["summary"] == {
        "candidate_count": 1,
        "retained_video_count": 1,
        "automatic_metrics_completed": 1,
        "human_reviewed_count": 0,
        "semantic_pass_count": 0,
        "gate_decision": "pending-human-review",
    }
    candidate = payload["candidates"][0]
    assert candidate["automatic_metrics"] is not None
    assert candidate["human_review"]["semantic_pass"] is None
    assert candidate["video"]["download_path"].endswith("/candidates/1/download")


def main():
    tests = [
        test_metrics_are_navigation_proxies,
        test_manifest_retains_human_gate_as_pending,
    ]
    for test in tests:
        test()
    print(json.dumps({"status": "passed", "tests": [test.__name__ for test in tests]}, indent=2))


if __name__ == "__main__":
    main()
