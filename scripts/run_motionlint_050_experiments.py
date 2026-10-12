"""Fixed-input methods and ablations, grouped uncertainty, all failures retained."""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from zipfile import ZipFile
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from motionlint.artifacts import save_motion, read_motion, sha256
from motionlint.benchmark.runner import load_sample, code_hashes
from motionlint.core.config import load_config, DEFAULT_CONFIG
from motionlint.core.context import freeze_floor
from motionlint.core.quality_gate import evaluate_gate
from motionlint.core.provenance import rule_hash
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.repair_pipeline import repair
from motionlint.pipeline.regression import compare
from motionlint.repairs.support_metrics import compare_support
from motionlint.cli.main import _write_json

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--freeze', type=Path, required=True)
parser.add_argument('--stage', choices=('prepare', 'run'), default='run')
parser.add_argument('--policy', choices=('v4', 'v5'), default='v5')
parser.add_argument('--ids', nargs='+', help=argparse.SUPPRESS)
parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
parser.add_argument('--chunk-size', type=int, default=12)
args = parser.parse_args()
output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
frozen = json.loads(args.freeze.read_text(encoding='utf-8'))
if code_hashes() != frozen['code_sha256']:
    raise ValueError('Detector/repair freeze changed; rebuild the held-out dataset before any calibration')
jobs_path = output / 'jobs.json'
if not jobs_path.exists():
    dynamic = ROOT / 'reports/iteration_050/dynamic-2/manifest.json'
    entries = json.loads(dynamic.read_text(encoding='utf-8'))['motions']
    jobs = []
    for row in entries:
        path = output / 'inputs' / f"{row['id']}.npz"
        path.parent.mkdir(exist_ok=True)
        save_motion(path, load_sample(dynamic.parent, row))
        jobs.append({'id': row['id'], 'input': str(path), 'group_id': row['group_id'], 'split': row['split'],
                     'evidence_type': 'controlled_injection_only', 'known_repairable': row['repairable_by_known_reference'],
                     'output': str(output / 'historical' / f"{row['id']}.npz"), 'kind': row['injection']['type']})
    for scope in ('engineering-development', 'engineering-holdout'):
        for row in json.loads((ROOT / f'reports/iteration_050/{scope}/summary.json').read_text(encoding='utf-8'))['rows']:
            if row['status'] != 'ready':
                raise ValueError('Real engineering input failed; preserve and resolve execution before method experiments')
            jobs.append({'id': row['id'], 'input': str(ROOT / f'reports/iteration_050/{scope}' / row['id'] / 'raw_motion.npz'),
                         'group_id': row['group_id'], 'split': row['split'], 'evidence_type': 'real_input_engineering_no_human_truth',
                         'known_repairable': False, 'output': str(output / 'historical' / f"{row['id']}.npz"), 'kind': row['source']})
    _write_json(jobs_path, jobs)
jobs = json.loads(jobs_path.read_text(encoding='utf-8'))
if args.ids:
    jobs = [job for job in jobs if job['id'] in args.ids]
historical = ROOT.parent / 'HumanAction-runtime/baselines/b833b32'
if not historical.exists():
    historical.mkdir(parents=True)
    with ZipFile(ROOT / 'reports/iteration_050/baseline/source.zip') as archive:
        archive.extractall(historical)
if args.stage == 'prepare':
    env = dict(os.environ); env.pop('PYTHONPATH', None)
    subprocess.run([sys.executable, str(ROOT / 'scripts/run_historical_repair.py'), '--source', str(historical),
        '--jobs', str(jobs_path)], cwd=historical, env=env, check=True)
    sys.exit(0)
policy = ROOT / 'motionlint/configs/quality_v4.yaml' if args.policy == 'v4' else DEFAULT_CONFIG
config = load_config(policy)
methods = ('none', 'time_smooth', 'historical_v5', 'repair_v6', 'no_contact', 'no_regression')
results = output / args.policy
results.mkdir(exist_ok=True)
if not args.worker:
    # Release solver/JSON allocations between small serial chunks. Preserve failed
    # execution attempts, and retry errors without reselecting quality failures.
    pending = []
    for job in jobs:
        result_path = results / f"{job['id']}.json"
        if result_path.exists():
            previous = json.loads(result_path.read_text(encoding='utf-8'))
            if any(item.get('status') == 'failed' for item in previous['methods'].values()):
                history = results / 'failed-attempts' / job['id']
                history.mkdir(parents=True, exist_ok=True)
                result_path.replace(history / f'{time.time_ns()}.json')
            else:
                continue
        pending.append(job['id'])
    for start in range(0, len(pending), args.chunk_size):
        subprocess.run([sys.executable, str(Path(__file__)), '--output', str(output),
            '--freeze', str(args.freeze.resolve()), '--policy', args.policy, '--worker',
            '--ids', *pending[start:start+args.chunk_size]], check=True)
    jobs = json.loads(jobs_path.read_text(encoding='utf-8'))
rows = []
for job in jobs:
    path = results / f"{job['id']}.json"
    if path.exists():
        rows.append(json.loads(path.read_text(encoding='utf-8')))
        continue
    if not args.worker:
        raise ValueError(f'Missing worker result: {path.name}')
    raw = freeze_floor(read_motion(job['input']), config)
    original_hash = sha256(job['input'])
    before = inspect(raw, config_path=policy)
    row = {key: job[key] for key in ('id', 'group_id', 'split', 'evidence_type', 'known_repairable', 'kind')}
    row.update(input_sha256=original_hash, methods={}, rule_version=config['version'], rules_sha256=rule_hash(config))
    for method in methods:
        started = time.perf_counter()
        try:
            candidate, status, trials, accepted = raw, 'no_op', 0, 0
            if method == 'time_smooth':
                p = raw.positions
                q = (np.pad(p, ((1,1),(0,0),(0,0),(0,0)), mode='edge')[:-2] + p +
                     np.pad(p, ((1,1),(0,0),(0,0),(0,0)), mode='edge')[2:]) / 3
                candidate = replace(raw, positions=q, root_translation=q[:, :, 0].copy())
                status = 'unconstrained_position_average'; trials = accepted = 1
            elif method == 'historical_v5':
                candidate = read_motion(job['output'])
                old_record = json.loads(Path(job['output']).with_suffix('.json').read_text(encoding='utf-8'))
                status = old_record['status']
                trials = old_record['candidate_attempts']; accepted = old_record['candidate_acceptances']
            elif method != 'none':
                ablation = frozenset({'contact'}) if method == 'no_contact' else frozenset({'regression'}) if method == 'no_regression' else frozenset()
                outcome = repair(raw, config_path=policy, experimental_ablations=ablation)
                candidate = outcome.motion; status = outcome.to_dict()['status']
                trials = sum(len(step.get('candidate_trials', [])) for step in outcome.steps)
                accepted = sum(bool(trial.get('applied')) for step in outcome.steps for trial in step.get('candidate_trials', []))
                trial_path = results / method / f"{job['id']}-candidates.json"
                trial_path.parent.mkdir(exist_ok=True)
                if trial_path.exists():
                    trial_path.replace(trial_path.with_name(f'{trial_path.stem}.attempt-{time.time_ns()}.json'))
                with trial_path.open('w', encoding='utf-8') as handle:
                    json.dump(outcome.to_dict(), handle, indent=2)
            after = inspect(candidate, config_path=policy)
            support = compare_support(raw, candidate, config['tests']['foot_sliding'])
            comparison = compare(before, after, config_path=policy, baseline_motion=raw, candidate_motion=candidate)
            shift = np.linalg.norm(candidate.positions - raw.positions, axis=-1)
            row['methods'][method] = {'status': status, 'score_before': before.overall_score, 'score_after': after.overall_score,
                'gate_before': evaluate_gate(before, config_path=policy).status, 'gate_after': evaluate_gate(after, config_path=policy).status,
                'physical_distance_before_m': support['original_support_distance_before_m'],
                'physical_distance_after_m': support['original_support_distance_after_m'],
                'physical_reduction_ratio': support['original_support_distance_reduction_ratio'],
                'comparison_status': comparison['status'], 'regression_codes': comparison['audit']['rejection_codes'],
                'candidate_attempts': trials, 'candidate_acceptances': accepted, 'max_joint_shift_m': float(shift.max()),
                'unchanged': bool(np.array_equal(candidate.positions, raw.positions)),
                'rms_motion_change_m': float(np.sqrt(np.mean(shift**2))),
                'root_path_before_m': float(np.linalg.norm(np.diff(raw.positions[:, :, 0], axis=0), axis=-1).sum()),
                'root_path_after_m': float(np.linalg.norm(np.diff(candidate.positions[:, :, 0], axis=0), axis=-1).sum()),
                'automatic_motion_preservation_not_semantic_accuracy': True, 'seconds': time.perf_counter()-started}
        except Exception as exc:
            row['methods'][method] = {'status': 'failed', 'error': f'{type(exc).__name__}: {exc}', 'seconds': time.perf_counter()-started}
    row['input_hashes_unchanged'] = sha256(job['input']) == original_hash
    _write_json(path, row)
    rows.append(row)
    print(args.policy, job['id'], flush=True)

if args.worker:
    sys.exit(0)


def summarize(selected):
    summary = {}
    for method in methods:
        items = [r['methods'][method] for r in selected]
        supported = [i for i in items if i['status'] != 'failed']
        values = [r['methods'][method]['physical_reduction_ratio'] for r in selected
                  if r['known_repairable'] and r['methods'][method].get('physical_reduction_ratio') is not None]
        summary[method] = {'count': len(items), 'execution_failures': sum(i['status'] == 'failed' for i in items),
            'strict_pass_count': sum(i.get('gate_after') == 'PASS' for i in items),
            'sample_accepted_count': sum(i['status'] == 'accepted' for i in items),
            'regression_count': sum(i.get('comparison_status') == 'REGRESSION DETECTED' for i in items),
            'candidate_attempts': sum(i.get('candidate_attempts', 0) for i in items),
            'candidate_acceptances': sum(i.get('candidate_acceptances', 0) for i in items),
            'known_repairable_distance_reduction_median': float(np.median(values)) if values else None,
            'seconds_median': float(np.median([i['seconds'] for i in items])),
            'normal_control_unchanged_count': sum(r['kind'] == 'clean' and r['methods'][method].get('unchanged', False) for r in selected)}
        groups = sorted({r['group_id'] for r in selected}); rng = np.random.default_rng(500061)
        grouped = {g: [r for r in selected if r['group_id'] == g] for g in groups}
        boot = []
        for _ in range(1000):
            sampled = [r for g in rng.choice(groups, len(groups), replace=True) for r in grouped[g]]
            boot.append(np.mean([r['methods'][method].get('gate_after') == 'PASS' for r in sampled]))
        summary[method]['grouped_strict_pass_fraction_95pct'] = np.percentile(boot, [2.5,97.5]).tolist()
    return summary

_write_json(results / 'summary.json', {'schema_version': 3, 'rules_sha256': rule_hash(config), 'rules_version': config['version'],
    'freeze_sha256': sha256(args.freeze), 'count': len(rows), 'summary': summarize(rows),
    'holdout_controlled': summarize([r for r in rows if r['split']=='holdout' and r['evidence_type']=='controlled_injection_only']),
    'holdout_real': summarize([r for r in rows if r['split']=='holdout' and r['evidence_type']!='controlled_injection_only']),
    'all_failures_included': True, 'historical_method_policy': 'Untouched b833b32 repair uses its original internal v4 policy; all outputs are re-evaluated under the same displayed current frozen rule',
    'rows': rows})
