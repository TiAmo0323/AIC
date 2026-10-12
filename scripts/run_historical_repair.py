"""Run untouched b833b32 repair v5 in a separate import namespace/process."""
import argparse
from dataclasses import fields
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--jobs', type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.source.resolve()))
import numpy as np
from motionlint.core.motion_sequence import MotionSequence
from motionlint.pipeline.repair_pipeline import repair
assert 'b833b32' in str(Path(sys.modules['motionlint'].__file__).resolve()), 'Historical package isolation failed'
names = {field.name for field in fields(MotionSequence)}
for row in json.loads(args.jobs.read_text(encoding='utf-8')):
    output = Path(row['output'])
    if output.exists() and 'candidate_attempts' in json.loads(output.with_suffix('.json').read_text(encoding='utf-8')):
        continue
    output.parent.mkdir(parents=True, exist_ok=True)
    with np.load(row['input'], allow_pickle=False) as archive:
        description = json.loads(str(archive['description'].item()))
        arrays = {key: archive[key] for key in names if key in archive}
    motion = MotionSequence(**{k: v for k, v in description.items() if k in names}, **arrays)
    if motion.source == 'bvh':
        # The historical adapter did not support these non-root translations.
        selected, status = motion, 'unsupported_original_adapter'
        attempts = acceptances = 0
    else:
        result = repair(motion)
        selected = result.motion
        status = 'accepted' if any(s['applied'] for s in result.steps) else 'not_accepted'
        attempts = sum(len(s.get('candidate_trials', [])) for s in result.steps)
        acceptances = sum(bool(t.get('applied')) for s in result.steps for t in s.get('candidate_trials', []))
        with output.with_suffix('.repair.json').open('w', encoding='utf-8') as handle:
            json.dump(result.to_dict(), handle, indent=2)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload, values = {}, {}
    for field in fields(selected):
        value = getattr(selected, field.name)
        if isinstance(value, np.ndarray):
            values[field.name] = value
        else:
            payload[field.name] = value
    if output.exists():
        with np.load(output, allow_pickle=False) as old:
            assert np.array_equal(old['positions'], values['positions']), 'Historical candidate changed during statistics restoration'
    else:
        np.savez_compressed(output, description=json.dumps(payload), **values)
    output.with_suffix('.json').write_text(json.dumps({'status': status, 'algorithm_version': 5,
        'candidate_attempts': attempts, 'candidate_acceptances': acceptances,
        'source_commit': 'b833b32cb22a1c27b6b978d15fe68379c8868c5c', 'internal_policy': 'untouched historical v4'}), encoding='utf-8')
print('Historical candidates:', len(json.loads(args.jobs.read_text(encoding='utf-8'))))
