"""Export-check ablation and candidate-selection engineering measurements."""
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from motionlint.artifacts import read_motion, sha256
from motionlint.cli.main import _write_json

base = ROOT / 'reports/iteration_050'
flows = json.loads((base / 'complete-flows-v3/summary.json').read_text(encoding='utf-8'))
rows = []
for row in flows['rows']:
    flow = row['flow']
    stages = {name: entry['gate']['status'] for name, entry in flow['stages'].items()}
    stages['character'] = flow['character']['gate']['status']
    before_export = stages['repaired']
    with_export = 'PASS' if stages['bvh'] == stages['character'] == stages['repaired'] == 'PASS' else 'FAIL'
    rows.append({'id': row['id'], 'stage_gates': stages, 'without_export_reinspection': before_export,
                 'with_export_reinspection': with_export,
                 'false_complete_pass_without_export_check': before_export == 'PASS' and with_export == 'FAIL',
                 'video': flow['character']['video'],
                 'actual_mesh_metrics_sha256': sha256(Path(flow['character_dir']) / 'character/mesh_metrics.json'),
                 'render_transform_sha256': sha256(Path(flow['character_dir']) / 'render_transform.json')})
_write_json(base / 'export-check-ablation.json', {'schema_version': 3, 'count': len(rows),
    'false_complete_pass_without_export_check_count': sum(r['false_complete_pass_without_export_check'] for r in rows),
    'evidence_type': 'actual_written_bvh_and_evaluated_character', 'rows': rows,
    'ablation_policy': 'Remove the export gate only from the completion decision; retain and publish actual stage checks for audit'})
all_rows = []
for scope in ('engineering-development', 'engineering-holdout'):
    all_rows += json.loads((base / scope / 'summary.json').read_text(encoding='utf-8'))['rows']
groups = {}
for row in all_rows:
    if row['source'] != 'intergen':
        continue
    motion = read_motion(base / ('engineering-development' if row['split'] == 'development' else 'engineering-holdout') /
                         row['id'] / 'raw_motion.npz')
    p = motion.positions
    groups.setdefault(row['group_id'], []).append({'id': row['id'], 'score': row['raw_score'], 'split': row['split'],
        'quality_gate': row['raw_gate']['status'], 'root_path_m': float(np.linalg.norm(np.diff(p[:, :, 0], axis=0), axis=-1).sum()),
        'motion_amplitude_rms_m': float(np.sqrt(np.mean((p - p.mean(axis=0))**2))),
        'upper_body_amplitude_rms_m': float(np.sqrt(np.mean((p[:, :, 12:] - p[:, :, 12:].mean(axis=0))**2)))})
comparison = []
for group, options in sorted(groups.items()):
    first = min(options, key=lambda r: r['id'])
    chosen = max(options, key=lambda r: (r['score'], -int(r['id'].rsplit('_', 1)[1])))
    comparison.append({'prompt_group': group, 'first': first, 'quality_ranked': chosen, 'all_candidates': options,
                       'raw_score_gain_same_frozen_rule': chosen['score']-first['score'],
                       'root_path_change_m': chosen['root_path_m']-first['root_path_m'],
                       'motion_amplitude_change_m': chosen['motion_amplitude_rms_m']-first['motion_amplitude_rms_m'],
                       'non_target_upper_body_amplitude_change_m': chosen['upper_body_amplitude_rms_m']-first['upper_body_amplitude_rms_m']})
_write_json(base / 'candidate-selection.json', {'schema_version': 3, 'prompt_groups': len(groups), 'samples': 36,
    'truth_policy': 'No human semantic labels. Amplitude and trajectory are engineering observations, not semantic accuracy.',
    'ranking_policy': 'Raw quality score under one frozen rule; ties choose the lowest predeclared seed index', 'rows': comparison})
print('Export false complete passes:', sum(r['false_complete_pass_without_export_check'] for r in rows), 'of', len(rows))
