"""Safety cases that must survive packaging and optional dependencies."""
from dataclasses import replace
from pathlib import Path
import numpy as np
import pytest
from motionlint.benchmark.fixtures import standing
from motionlint.adapters.intergen_adapter import load_intergen_joints
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.regression import compare
from motionlint.core.config import load_config


def test_explicit_contact_exempts_only_declared_pair_and_frames(tmp_path):
    path = tmp_path / 'source.npy'
    p = standing(30)
    p[:, 20] = p[:, 15]
    np.save(path, p)
    baseline = load_intergen_joints(path)
    candidate = replace(baseline, metadata={**baseline.metadata, 'allowed_contacts': [
        {'actor_id': 0, 'other_actor_id': 0, 'joint': 'LeftHand', 'other_joint': 'Head', 'start_frame': 8, 'end_frame': 15}]})
    report = inspect(candidate)
    collision = next(t for t in report.tests if t.test_name == 'collision')
    assert [(i.start_frame, i.end_frame) for i in collision.issues if i.metric == 'wrist_head_distance_m'] == [(0, 7), (16, 29)]
    assert collision.metrics['contact_exclusions'][0]['excluded_risk_frames'] == 8
    assert collision.metrics['distance_measurements'][0]['distance_m'][10] == 0
    assert compare(inspect(baseline), report, baseline_motion=baseline, candidate_motion=candidate)['status'] != 'PASS'


def test_all_persisted_adverse_cases_are_blocked_and_inputs_survive(tmp_path):
    from motionlint.benchmark.counterexamples import build, run
    build(tmp_path / 'cases')
    report = run(tmp_path / 'cases/manifest.json', tmp_path / 'output')
    assert report['passed_count'] == report['count'] == 60
    assert all(r['input_hashes_unchanged'] for r in report['rows'])


def test_known_helper_edge_is_not_an_anatomical_bone(tmp_path):
    from motionlint.bvh_writer import write_bvh
    from motionlint.adapters.bvh_adapter import load_bvh
    from motionlint.core.skeleton import BVH_NAMES, BVH_PARENTS, BVH_OFFSETS
    names = ['joint_Root', *BVH_NAMES]
    parents = [-1, 0, *[p + 1 for p in BVH_PARENTS[1:]]]
    offsets = np.vstack([[0, 0, 0], BVH_OFFSETS])
    path = tmp_path / 'helper.bvh'
    write_bvh(path, np.zeros((3, 3)), np.zeros((3, len(names), 3)), 30., names=names, parents=parents, offsets=offsets)
    motion = load_bvh(path)
    skeleton = next(t for t in inspect(motion).tests if t.test_name == 'skeleton_integrity')
    assert skeleton.metrics['excluded_helper_edges'] == [1]
    assert all(1 not in i.joint_ids or i.joint_ids != [0, 1] for i in skeleton.issues)


def test_normal_motion_returns_no_repair_and_offline_html(tmp_path):
    from motionlint.cli.main import main
    p = tmp_path / 'clean.npy'
    np.save(p, standing(30))
    assert main(['repair', str(p), '--output-dir', str(tmp_path / 'out')]) == 0
    np.testing.assert_array_equal(np.load(tmp_path / 'out/repaired_actor1.npy'), np.load(p))
    content = (tmp_path / 'out/after/report.html').read_text(encoding='utf-8')
    assert 'application/json' in content and '<script src=' not in content
