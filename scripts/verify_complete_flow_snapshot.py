"""Collect reproducible engineering evidence from actual immutable repair runs.

This validates saved files and video content; it does not simulate browser or
human studies. Browser tasks are documented separately in the flow guide.
"""
import argparse
from pathlib import Path
from uuid import UUID
import json
import platform
import subprocess

import numpy as np

from motionlint.artifacts import current_run, read_motion, sha256
from motionlint.character_export import checked_character, resources, verify_video
from motionlint.import_io import import_manifest, load_imported_motion
from motionlint.pipeline.inspector import inspect
from motionlint.core.quality_gate import evaluate_gate


ROOT = Path(__file__).resolve().parents[1]


def safe_task(root, task_id):
    if str(UUID(task_id)) != task_id:
        raise ValueError('Task IDs must be canonical UUIDs')
    return root / task_id


def report_row(motion, policy, stage):
    report = inspect(motion, config_path=policy)
    gate = evaluate_gate(report, config_path=policy)
    return {'stage': stage, 'score': report.overall_score, 'gate': gate.to_dict(),
            'issue_count': report.issue_count, 'actors': motion.actor_count, 'frames': motion.frame_count, 'fps': motion.fps,
            'array_sha256': report.metadata['evaluated_array_sha256'],
            'rule_sha256': report.metadata['config_sha256'], 'geometry_source': report.metadata['geometry_source']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tasks', nargs='+', required=True)
    parser.add_argument('--roundtrip-imports', nargs='*', default=[])
    parser.add_argument('--tasks-root', type=Path, default=ROOT / 'motionlint/task_runs/imports')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--wheel', type=Path, default=ROOT / 'output/packages/motionlint-0.4.0-py3-none-any.whl',
                        help='Wheel actually installed for this verification (historical default retained)')
    args = parser.parse_args()
    rows, roundtrips = [], []
    config = resources(ROOT, ROOT.parent / 'HumanAction-runtime')
    for task_id in args.tasks:
        task = safe_task(args.tasks_root, task_id)
        imported = import_manifest(task)
        run, manifest = current_run(task)
        policy = run / 'quality.yaml'
        stages = [report_row(read_motion(run / entry['snapshot']), policy, name) for name, entry in manifest['stages'].items()]
        repair = json.loads((run / 'repair_report.json').read_text(encoding='utf-8'))
        row = {'task_id': task_id, 'input_title': imported['title'], 'run_id': manifest['run_id'],
               'repair_algorithm_version': repair.get('algorithm_version'),
               'support_comparison': repair.get('support_comparison'),
               'input_files': manifest['inputs'], 'artifact_files': manifest['files'], 'stages': stages,
               'steps': [{'repair': step['repair'], 'status': step['status'], 'applied': step['applied'],
                          'reason': step.get('reason'), 'max_joint_shift_m': step.get('max_joint_shift_m')} for step in repair['steps']]}
        if (task / 'motionlint/current_character.json').is_file():
            folder, state = checked_character(task)
            character = read_motion(folder / 'character_motion.npz')
            row['stages'].append(report_row(character, folder / 'quality.yaml', 'character'))
            row['video'] = verify_video(folder / 'kenney.mp4', config['ffmpeg'], frames=character.frame_count, fps=character.fps)
            row['export_id'] = state['export_id']
        rows.append(row)
    for task_id in args.roundtrip_imports:
        task = safe_task(args.tasks_root, task_id)
        data = import_manifest(task)
        actual = load_imported_motion(task)
        matches = []
        for source_id in args.tasks:
            run, manifest = current_run(safe_task(args.tasks_root, source_id))
            for stage in ('repaired', 'bvh'):
                if stage not in manifest['stages']:
                    continue
                motion = read_motion(run / manifest['stages'][stage]['snapshot'])
                if (actual.positions.shape == motion.positions.shape and actual.joint_names == motion.joint_names
                        and np.isclose(actual.fps, motion.fps) and np.allclose(actual.positions, motion.positions, atol=1e-8)):
                    matches.append({'source_task_id': source_id, 'stage': stage,
                                    'max_coordinate_error_m': float(np.max(np.abs(actual.positions - motion.positions)))})
        if not matches:
            raise ValueError(f'Reimport {task_id} does not match a saved export')
        roundtrips.append({'task_id': task_id, 'title': data['title'], 'input_sha256': [entry['sha256'] for entry in data['files']], 'matches': matches})
    hashes = {str(path.relative_to(ROOT)).replace('\\', '/'): sha256(path) for path in sorted((ROOT / 'motionlint').rglob('*.py'))}
    for related in ('LODGE_api/blender_rokoko_retarget.py', 'scripts/export_blender_motionlint.py',
                    'scripts/verify_complete_flow_snapshot.py', 'project/src/App.vue', 'project/src/utils/zhDisplay.js'):
        hashes[related] = sha256(ROOT / related)
    wheel = args.wheel.resolve()
    try:
        commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    result = {'schema_version': 1, 'scope': 'Developer Windows engineering verification using self-authored fixtures; no human annotation or blind-test accuracy claim',
              'python': platform.python_version(), 'base_commit': commit,
              'wheel_path': str(wheel.relative_to(ROOT)) if wheel.is_relative_to(ROOT) else wheel.name,
              'source_sha256': hashes, 'wheel_sha256': sha256(wheel), 'samples': rows, 'reimports': roundtrips}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'samples': len(rows), 'reimports': len(roundtrips), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
