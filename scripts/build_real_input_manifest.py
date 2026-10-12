"""Finalize the preselected 60 inputs without inspecting any quality result."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--cache', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
selection_path = ROOT / 'resources/real-input-selection.json'
selection = json.loads(selection_path.read_text(encoding='utf-8'))
resources = json.loads((ROOT / 'resources/manifest.json').read_text(encoding='utf-8'))
entries = {r['id']: r for r in resources['resources']}
def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()
rows = []
for entry in selection['motions']:
    row = dict(entry)
    if entry['source'] == 'intergen':
        generation = args.cache / 'intergen' / entry['id'] / 'generation.json'
        if generation.exists():
            receipt = json.loads(generation.read_text(encoding='utf-8'))
            paths = [generation.parent / f'actor{a}.npy' for a in (1, 2)]
            row.update(status=receipt['status'], files=[{'path': p.relative_to(args.cache).as_posix(), 'sha256': sha(p)} for p in paths if p.exists()],
                       generation_receipt_sha256=sha(generation), checkpoint_sha256=resources['upstreams']['intergen']['checkpoint_sha256'],
                       license=resources['upstreams']['intergen']['license'], upstream_commit=resources['upstreams']['intergen']['commit'],
                       generator_seconds=receipt.get('seconds'), evidence_type='generated_motion_no_human_truth',
                       group_id=entry['id'].rsplit('_', 1)[0])
        else:
            row.update(status='unavailable', files=[], error='Generation receipt missing')
    else:
        p = args.cache / entry['input']
        row.update(status='ready' if p.is_file() and sha(p) == entries[entry['id']]['sha256'] else 'unavailable',
                   files=[{'path': entry['input'], 'sha256': entries[entry['id']]['sha256']}],
                   license=entries[entry['id']]['license'], source_url=entries[entry['id']]['url'],
                   attribution=entries[entry['id']]['attribution'], upstream_commit=resources['upstreams']['bandai']['commit'],
                   modifications='Stored centimetres normalized to metres; explicit joint mapping; original input retained',
                   evidence_type='external_motion_no_human_truth', group_id='bandai_' + entry['content'])
    row['expected_scope'] = ['temporal_continuity', 'skeleton_integrity', 'foot_sliding', 'ground_contact', 'collision', 'motion_jerk']
    rows.append(row)
payload = {'schema_version': 3, 'dataset_version': 'engineering-1', 'count': len(rows),
           'ready_count': sum(r['status'] == 'ready' for r in rows),
           'selection_sha256': sha(selection_path), 'complete_flow_ids': selection['complete_flow_ids'],
           'truth_policy': 'No human defect truth. Report physical metrics, coverage, acceptance and failures only.', 'motions': rows}
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(payload, indent=2), encoding='utf-8')
print(payload['ready_count'], '/', payload['count'], 'ready')
