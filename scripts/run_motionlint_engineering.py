"""Serial real-input engineering evaluation and six preselected actual flows."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from motionlint.cli.main import load_motion, _write_json, _write_report
from motionlint.core.context import freeze_floor
from motionlint.core.config import load_config
from motionlint.core.quality_gate import evaluate_gate
from motionlint.core.provenance import rule_hash
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.repair_pipeline import repair
from motionlint.artifacts import save_motion, sha256
from motionlint.pipeline.local import run_pipeline

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('manifest', type=Path)
parser.add_argument('--cache', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--config', type=Path)
parser.add_argument('--split', choices=('all', 'development', 'holdout'), default='all')
parser.add_argument('--flows', action='store_true')
parser.add_argument('--runtime', type=Path)
parser.add_argument('--freeze', type=Path)
args = parser.parse_args()
manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
if args.split in ('all', 'holdout') or args.flows:
    if args.freeze is None:
        raise ValueError('Held-out engineering inputs require a pre-evaluation code/rule freeze')
    from motionlint.benchmark.runner import code_hashes
    frozen = json.loads(args.freeze.read_text(encoding='utf-8'))
    if frozen['code_sha256'] != code_hashes() or frozen['rules_sha256'] != rule_hash(load_config(args.config)):
        raise ValueError('Frozen rule or implementation changed')
rows = []
for entry in manifest['motions']:
    if args.split != 'all' and entry['split'] != args.split:
        continue
    if args.flows and entry['id'] not in manifest['complete_flow_ids']:
        continue
    folder = args.output / entry['id']
    folder.mkdir(parents=True, exist_ok=True)
    result_path = folder / 'result.json'
    if result_path.exists():
        saved = json.loads(result_path.read_text(encoding='utf-8'))
        if saved.get('status') == 'ready':
            rows.append(saved)
            continue
        (folder / f'failed-{uuid4()}.json').write_bytes(result_path.read_bytes())
    record = {'id': entry['id'], 'source': entry['source'], 'split': entry['split'], 'group_id': entry['group_id'],
              'input_files': entry['files'], 'evidence_type': entry['evidence_type']}
    try:
        started = time.perf_counter()
        paths = [args.cache / item['path'] for item in entry['files']]
        if any(sha256(p) != item['sha256'] for p, item in zip(paths, entry['files'])):
            raise ValueError('Input hash mismatch')
        if args.flows:
            result = run_pipeline(paths, output=folder / 'task', config_path=args.config,
                character=True, runtime=args.runtime, repo=ROOT, **entry.get('options', {'fps': entry.get('fps', 30.)}))
            record.update(status='ready', flow=result, seconds=time.perf_counter()-started)
        else:
            motion = load_motion(paths[0], paths[1] if len(paths) == 2 else None, **entry.get('options', {'fps': entry.get('fps', 30.)}))
            motion = freeze_floor(motion, load_config(args.config))
            motion.metadata.update(evidence_type=entry['evidence_type'], stage='raw')
            report = inspect(motion, config_path=args.config)
            record['detect_seconds'] = time.perf_counter()-started
            _write_report(folder / 'raw', report)
            save_motion(folder / 'raw_motion.npz', motion)
            repair_started = time.perf_counter()
            outcome = repair(motion, config_path=args.config)
            _write_report(folder / 'repaired', outcome.after)
            _write_json(folder / 'repair.json', outcome.to_dict())
            save_motion(folder / 'selected_motion.npz', outcome.motion)
            record.update(status='ready', repair_seconds=time.perf_counter()-repair_started,
                raw_gate=evaluate_gate(report, config_path=args.config).to_dict(),
                repaired_gate=evaluate_gate(outcome.after, config_path=args.config).to_dict(),
                repair_status=outcome.to_dict()['status'], support=outcome.support_comparison,
                raw_score=report.overall_score, selected_score=outcome.after.overall_score,
                coverage=report.metadata['evaluation_coverage'],
                metrics_before={t.test_name: {k: v for k,v in t.metrics.items() if k != 'distance_measurements'} for t in report.tests},
                metrics_after={t.test_name: {k: v for k,v in t.metrics.items() if k != 'distance_measurements'} for t in outcome.after.tests},
                rules_sha256=report.metadata['config_sha256'], detector_sha256=report.metadata['detector_code_sha256'])
        record['input_hashes_unchanged'] = all(sha256(p) == item['sha256'] for p, item in zip(paths, entry['files']))
    except Exception as exc:
        record.update(status='failed', error=f'{type(exc).__name__}: {exc}')
    _write_json(result_path, record)
    rows.append(record)
    print(entry['id'], record['status'], record.get('error', ''), flush=True)
    _write_json(args.output / 'summary.json', {'schema_version': 3, 'manifest_sha256': sha256(args.manifest),
        'count': len(rows), 'ready_count': sum(r['status'] == 'ready' for r in rows), 'rows': rows,
        'evidence_type': 'actual_exports' if args.flows else 'real_input_engineering_no_human_truth'})
