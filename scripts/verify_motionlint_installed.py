"""Installation contract in a fresh directory with source imports excluded."""
import argparse
import hashlib
import importlib.util
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--wheel', type=Path, required=True)
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--optimize', action='store_true')
args = parser.parse_args()
source = args.source.resolve()
os.environ.pop('PYTHONPATH', None)
sys.path = [p for p in sys.path if p and not Path(p).resolve().is_relative_to(source)]
import motionlint
assert not Path(motionlint.__file__).resolve().is_relative_to(source), 'Imported the source checkout instead of the installed wheel'
assert importlib.metadata.version('motionlint') == '0.5.0'
assert importlib.util.find_spec('InterGen_api') is None and importlib.util.find_spec('LODGE_api') is None
assert (Path(motionlint.__file__).parent / 'static/index.html').is_file(), 'Workbench not included in wheel'
if args.optimize:
    assert importlib.metadata.version('cvxpy') == '1.6.5'
    assert importlib.metadata.version('clarabel') == '0.11.1'
else:
    assert importlib.util.find_spec('cvxpy') is None, 'The minimal install unexpectedly requires a solver'
import numpy as np
from motionlint.benchmark.fixtures import build
from motionlint.cli.main import main
from motionlint.pipeline.inspector import inspect
from motionlint.cli.main import load_motion
from motionlint.artifacts import sha256
scratch = args.output.resolve()
scratch.mkdir(parents=True, exist_ok=True)
if scratch.is_relative_to(source):
    raise ValueError('Wheel verification directory must be outside the checkout')
os.chdir(scratch)
build(scratch / 'demo')
def execute(arguments):
    code = main(arguments)
    return {'command': arguments, 'exit_code': code}
rows = [execute(['doctor', '--output', 'doctor.json']),
    execute(['check', 'demo/clean_00.npy', '--output-dir', 'check']),
    execute(['check', 'demo/foot_sliding_00.npy', '--output-dir', 'defect']),
    execute(['repair', 'demo/foot_sliding_00.npy', '--output-dir', 'repair']),
    execute(['compare', 'demo/clean_00.npy', 'demo/foot_sliding_00.npy', '--output-dir', 'regression'])]
np.save('nan.npy', np.full((5,22,3), np.nan))
rows.append(execute(['check', 'nan.npy', '--output-dir', 'invalid']))
codes = [r['exit_code'] for r in rows]
assert codes[0:3] == [0,0,1] and codes[3] in {0,1} and codes[-2:] == [1,2], codes
original = sha256('demo/clean_00.npy')
rows.append(execute(['repair', 'demo/clean_00.npy', '--output-dir', 'no-op']))
assert sha256('demo/clean_00.npy') == original
np.testing.assert_array_equal(np.load('demo/clean_00.npy'), np.load('no-op/repaired_actor1.npy'))
assert (scratch / 'check/report.html').is_file()
report = {'schema_version': 3, 'status': 'PASS', 'python': sys.version, 'platform': sys.platform,
    'wheel_sha256': sha256(args.wheel), 'installed_module': motionlint.__file__,
    'source_imports_excluded': True, 'optimize': args.optimize, 'commands': rows,
    'dependencies': {d.metadata['Name']: d.version for d in importlib.metadata.distributions() if d.metadata.get('Name')},
    'scope': 'Automated fresh installation; no external user installation is claimed'}
(scratch / 'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('Installed wheel contract PASS', sys.platform, sys.version.split()[0], 'optimize=', args.optimize)
