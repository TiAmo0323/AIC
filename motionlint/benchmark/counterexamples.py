"""Persisted adverse candidates and malformed files with predeclared outcomes."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import contextlib
import io
import json
import numpy as np
from motionlint.benchmark.fixtures import standing
from motionlint.adapters.intergen_adapter import load_intergen_joints
from motionlint.artifacts import save_motion, read_motion, sha256
from motionlint.cli.main import main, _write_json
from motionlint.core.config import load_config
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.regression import compare
from motionlint.pipeline.safety import audit

KINDS = ('new_location', 'other_actor', 'contact_loss', 'step_bound', 'total_bound',
         'bone_change', 'mapping', 'nan', 'inf', 'truncated', 'timeline', 'export_regression')


def build(folder):
    folder = Path(folder).resolve()
    if (folder / 'manifest.json').exists():
        raise ValueError('Counterexample output already exists; choose a new version')
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for kind in KINDS:
        for seed in range(5):
            case = folder / f'{kind}_{seed}'
            case.mkdir()
            p = standing(40)
            np.save(case / 'source.npy', p)
            baseline = load_intergen_joints(case / 'source.npy', fps=10.)
            baseline.metadata.update(floor_height_m=0., stage='raw', evidence_type='self_authored_adverse_candidate')
            candidate = replace(baseline, positions=baseline.positions.copy(), metadata=dict(baseline.metadata))
            operation, bound = 'audit', .20
            expected_codes = []
            if kind in {'new_location', 'other_actor'}:
                baseline.positions[:17, 0, :, 0] += (np.arange(17) % 2 * (.019 + seed * .0001))[:, None]
                if kind == 'other_actor':
                    baseline = replace(baseline, actor_count=2, root_translation=None, positions=np.concatenate(
                        [baseline.positions, standing(40)[:, None] + [2., 0., 0.]], axis=1))
                    candidate = replace(baseline, positions=np.concatenate(
                        [standing(40)[:, None], standing(40)[:, None] + [2., 0., 0.]], axis=1))
                candidate.positions[27 + seed, int(kind == 'other_actor'), :, 0] += .019
                expected_codes = ['new_severe_issue_frames']
            elif kind == 'contact_loss':
                baseline = replace(baseline, contacts=np.ones((40, 1, 4)))
                candidate = replace(candidate, contacts=np.zeros((40, 1, 4)))
                expected_codes = ['original_contact_lost']
            elif kind in {'step_bound', 'total_bound'}:
                bound = .15 if kind == 'step_bound' else .20
                candidate.positions[..., 0] += bound + .0002 + seed * .0001
                expected_codes = ['movement_bound_exceeded']
            elif kind == 'bone_change':
                candidate.positions[:, 0, 4, 1] += .03 + seed * .002
                expected_codes = ['bone_constraint_violated']
            elif kind == 'mapping':
                if seed == 0:
                    candidate.joint_names = ['unmapped' if x == 'Head' else x for x in candidate.joint_names]
                elif seed == 1:
                    candidate.metadata['parents'] = [-1] + [i for i in range(1, 22)]
                elif seed == 2:
                    candidate.metadata['foot_joint_ids'] = []
                elif seed == 3:
                    candidate.metadata['up_axis'] = 2
                else:
                    candidate.metadata['time_origin_seconds'] = 1.
                operation = 'incomplete_compare'
            elif kind in {'nan', 'inf', 'truncated'}:
                path = case / 'input.npy'
                malformed = p.copy()
                if kind in {'nan', 'inf'}:
                    malformed[seed, 0, 0] = np.nan if kind == 'nan' else np.inf
                np.save(path, malformed, allow_pickle=False)
                if kind == 'truncated':
                    if seed % 2:
                        from motionlint.bvh_writer import write_bvh
                        from motionlint.core.skeleton import BVH_NAMES
                        path = case / 'input.bvh'
                        write_bvh(path, np.zeros((3, 3)), np.zeros((3, len(BVH_NAMES), 3)), 30.)
                        path.write_text('\n'.join(path.read_text(encoding='utf-8').splitlines()[:-1]) + '\n', encoding='utf-8')
                    else:
                        path.write_bytes(path.read_bytes()[:153])
                operation = 'input_error'
            elif kind == 'timeline':
                candidate = replace(candidate, frame_count=39, positions=candidate.positions[:39], root_translation=None)
                operation = 'incomplete_compare'
            else:
                candidate.positions[25 + seed, :, :, 0] += .019
                candidate.metadata['stage'] = 'bvh'
                expected_codes = ['new_severe_issue_frames']
            if operation != 'input_error':
                baseline.root_translation = baseline.positions[:, :, 0].copy()
                candidate.root_translation = candidate.positions[:, :, 0].copy()
                save_motion(case / 'baseline.npz', baseline)
                save_motion(case / 'candidate.npz', candidate)
            files = [{'path': p.relative_to(folder).as_posix(), 'sha256': sha256(p)} for p in sorted(case.iterdir())]
            rows.append({'id': case.name, 'kind': kind, 'seed': seed, 'operation': operation,
                         'movement_bound_m': bound, 'expected_codes': expected_codes,
                         'expected_input_exit_code': 2 if operation == 'input_error' else None,
                         'source': 'self_authored_adverse_candidate', 'split': 'safety_test',
                         'evidence_type': 'predeclared_engineering_counterexample', 'files': files,
                         'input': path.relative_to(folder).as_posix() if operation == 'input_error' else None})
    manifest = {'schema_version': 3, 'version': 'safety-1', 'count': 60, 'kinds': list(KINDS), 'samples': rows}
    _write_json(folder / 'manifest.json', manifest)
    return manifest


def run(manifest_path, output, config_path=None):
    manifest_path, output = Path(manifest_path), Path(output)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    config = load_config(config_path)
    rows = []
    for entry in manifest['samples']:
        root = manifest_path.parent
        if any(sha256(root / item['path']) != item['sha256'] for item in entry['files']):
            raise ValueError(f'Counterexample input was changed: {entry["id"]}')
        row = {'id': entry['id'], 'kind': entry['kind'], 'expected_codes': entry['expected_codes']}
        if entry['operation'] == 'input_error':
            console = io.StringIO()
            with contextlib.redirect_stdout(console), contextlib.redirect_stderr(console):
                code = main(['check', str(root / entry['input']), '--output-dir', str(output / entry['id'])])
            row.update(exit_code=code, diagnostic=console.getvalue(), passed=code == 2)
        else:
            old, new = [read_motion(root / f'{entry["id"]}/{name}.npz') for name in ('baseline', 'candidate')]
            before, after = [inspect(m, config_path=config_path) for m in (old, new)]
            result = audit(before, after, config, baseline_motion=old, candidate_motion=new,
                           movement_bound_m=entry['movement_bound_m'])
            comparison = compare(before, after, config_path=config_path, baseline_motion=old, candidate_motion=new)
            passed = bool(result['incomplete_reasons']) if entry['operation'] == 'incomplete_compare' else (
                all(code in result['rejection_codes'] for code in entry['expected_codes']))
            row.update(passed=passed and comparison['status'] != 'PASS' if entry['kind'] != 'step_bound' else passed,
                       audit=result, comparison=comparison, before_score=before.overall_score, after_score=after.overall_score)
        row['input_hashes_unchanged'] = all(sha256(root / item['path']) == item['sha256'] for item in entry['files'])
        row['passed'] = row['passed'] and row['input_hashes_unchanged']
        rows.append(row)
    summary = {'schema_version': 3, 'count': len(rows), 'passed_count': sum(r['passed'] for r in rows),
               'manifest_sha256': sha256(manifest_path), 'rules_version': config['version'],
               'status': 'PASS' if all(r['passed'] for r in rows) else 'FAIL', 'rows': rows}
    _write_json(output / 'summary.json', summary)
    return summary
