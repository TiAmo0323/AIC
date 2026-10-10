"""Current quality settings and truthful counts for overlapping repair issues."""
import hashlib
from motionlint.core.config import DEFAULT_CONFIG
from motionlint.core.config import load_config
from motionlint.pipeline.repair_pipeline import summarize_issues
import motionlint.api as api


def test_settings_use_current_policy_for_all_supported_stages(tmp_path, monkeypatch):
    task_id = "11111111-1111-4111-8111-111111111111"
    (tmp_path / task_id).mkdir()
    monkeypatch.setitem(api.TASK_ROOTS, "intergen", tmp_path)
    for stage in ("raw", "repaired", "bvh", "character"):
        result = api.motion_settings("intergen", task_id, stage)
        assert result["frozen"] is False
        assert result["policy"] == load_config()
        assert result["sha256"] == hashlib.sha256(DEFAULT_CONFIG.read_bytes()).hexdigest()


def test_repair_summary_deduplicates_overlapping_frames():
    before = {"tests": [{"test_name": "foot_sliding", "issues": [{"start_frame": 1, "end_frame": 5}, {"start_frame": 3, "end_frame": 7}], "metrics": {"sliding_frame_count": 10}}]}
    after = {"tests": [{"test_name": "foot_sliding", "issues": [{"start_frame": 4, "end_frame": 6}], "metrics": {"sliding_frame_count": 3}}]}
    row = summarize_issues(before, after)[0]
    assert row["frames_before"] == 7 and row["frames_after"] == 3
    assert row["segments_before"] == 2 and row["sliding_frames_before"] == 10
