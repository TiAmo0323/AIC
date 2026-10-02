"""Frozen stage settings and truthful counts for overlapping repair issues."""
import hashlib
import json
from motionlint.core.config import DEFAULT_CONFIG
from motionlint.core.config import load_config
import yaml
from motionlint.pipeline.repair_pipeline import summarize_issues
import motionlint.api as api
from tests.test_motionlint_export import ready_task


def test_settings_use_the_selected_exports_frozen_policy(tmp_path, monkeypatch):
    task, _, video = ready_task(tmp_path, monkeypatch)
    output = video.parent
    manifest = output / "retarget_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    policy = output / "quality.yaml"
    frozen_config = load_config()
    frozen_config["version"] = 2
    policy.write_text(yaml.safe_dump(frozen_config), encoding="utf-8")
    state = json.loads((task / "motionlint/character_export.json").read_text(encoding="utf-8"))
    state["manifest_path"] = str(manifest)
    (task / "motionlint/character_export.json").write_text(json.dumps(state), encoding="utf-8")
    result = api.motion_settings("intergen", task.name, "repaired_character")
    assert result["frozen"] is True and result["policy"]["version"] == 2
    assert result["sha256"] == hashlib.sha256(policy.read_bytes()).hexdigest()
    assert api.motion_settings()["policy"]["version"] == load_config()["version"]


def test_repair_summary_deduplicates_overlapping_frames():
    before = {"tests": [{"test_name": "foot_sliding", "issues": [{"start_frame": 1, "end_frame": 5}, {"start_frame": 3, "end_frame": 7}], "metrics": {"sliding_frame_count": 10}}]}
    after = {"tests": [{"test_name": "foot_sliding", "issues": [{"start_frame": 4, "end_frame": 6}], "metrics": {"sliding_frame_count": 3}}]}
    row = summarize_issues(before, after)[0]
    assert row["frames_before"] == 7 and row["frames_after"] == 3
    assert row["segments_before"] == 2 and row["sliding_frames_before"] == 10
