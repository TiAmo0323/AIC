"""Cross-entry physical counterexample and missing-evidence contract."""
import json
import numpy as np
from motionlint.benchmark.fixtures import standing
from motionlint.cli.main import main, load_motion
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.regression import compare
from motionlint.pipeline.repair_pipeline import _assess
from motionlint.core.config import load_config


def inputs(tmp_path):
    before, after = standing(40), standing(40)
    before[:17, :, 0] += (np.arange(17) % 2 * .019)[:, None]
    after[27, :, 0] += .019
    paths = [tmp_path / 'before.npy', tmp_path / 'after.npy']
    for path, array in zip(paths, (before, after)):
        np.save(path, array)
    return paths, [load_motion(path, fps=10.) for path in paths]


def test_score_gain_does_not_hide_new_severe_location_across_entries(tmp_path, monkeypatch):
    paths, motions = inputs(tmp_path)
    old, new = [inspect(m) for m in motions]
    assert new.overall_score > old.overall_score
    comparison = compare(old, new, baseline_motion=motions[0], candidate_motion=motions[1])
    assert comparison['status'] == 'REGRESSION DETECTED'
    assert comparison['audit']['new_severe_issue_frames']['foot_sliding'] > 0
    internal = _assess('foot_lock', 'foot_sliding', *motions, old, new, load_config())
    assert not internal['applied']
    assert internal['new_severe_issue_frames'] == comparison['audit']['new_severe_issue_frames']
    assert main(['compare', *map(str, paths), '--fps', '10', '--output-dir', str(tmp_path / 'cli')]) == 1
    cli = json.loads((tmp_path / 'cli/comparison.json').read_text(encoding='utf-8'))
    assert cli['status'] == comparison['status']
    import motionlint.api as api
    monkeypatch.setattr(api, 'REPO_ROOT', tmp_path)
    monkeypatch.setattr(api, '_inspect_task', lambda ref: (motions[ref.task_id == 'after'], new if ref.task_id == 'after' else old, None, tmp_path))
    web = api.compare_tasks(api.CompareRequest(baseline=api.TaskRef(source='intergen', task_id='before'), candidate=api.TaskRef(source='intergen', task_id='after')))
    assert web['status'] == cli['status']
    assert web['audit']['rejection_codes'] == cli['audit']['rejection_codes']


def test_reports_alone_cannot_pass_strict_comparison(tmp_path):
    _, motions = inputs(tmp_path)
    report = inspect(motions[0])
    assert compare(report, report)['status'] == 'COMPARISON INCOMPLETE'
    assert compare(report, report, baseline_motion=motions[0], candidate_motion=motions[0])['status'] == 'PASS'
