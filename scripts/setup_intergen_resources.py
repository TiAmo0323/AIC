"""Recover the isolated Windows/Linux InterGen environment and verified model.

Use only for the separately licensed optional generator, never core installation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime', type=Path, required=True)
parser.add_argument('--uv', default=shutil.which('uv') or str(Path.home() / '.local/bin/uv.exe'))
parser.add_argument('--generate', action='store_true')
args = parser.parse_args()
runtime = args.runtime.resolve()
cache = runtime / 'resources'
cache.mkdir(parents=True, exist_ok=True)
manifest = json.loads((ROOT / 'resources/manifest.json').read_text(encoding='utf-8'))
spec = manifest['upstreams']['intergen']
records = []


def record(stage, status, **fields):
    records.append({'stage': stage, 'status': status, 'time': time.time(), **fields})
    (cache / 'intergen-setup.json').write_text(json.dumps({'records': records}, indent=2), encoding='utf-8')
    print(stage, status, flush=True)


def execute(command, **options):
    subprocess.run(command, check=True, **options)


try:
    if shutil.disk_usage(cache).free < 10 * 1024**3:
        raise OSError('InterGen recovery requires 10 GiB free on the runtime drive')
    source = cache / 'src/InterGen'
    if not source.exists():
        execute(['git', 'clone', '--filter=blob:none', '--no-checkout', spec['repo'], str(source)])
        execute(['git', 'sparse-checkout', 'set', 'configs', 'models', 'utils', 'common', 'data', 'tools', 'prepare'], cwd=source)
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=source, text=True, capture_output=True).stdout.strip()
    if head != spec['commit'] or not (source / 'models').exists():
        dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=source, text=True, capture_output=True, check=True).stdout
        if dirty:
            raise ValueError('Managed upstream checkout has edits; preserve them before restoring the pinned commit')
        execute(['git', 'fetch', '--depth=1', 'origin', spec['commit']], cwd=source)
        execute(['git', 'checkout', '--detach', spec['commit']], cwd=source)
    record('source', 'verified', commit=spec['commit'], license=spec['license'])
    environment = runtime / 'envs/intergen311'
    if not environment.exists():
        execute([args.uv, 'venv', '--python', '3.11', str(environment)])
    python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    env = {**os.environ, 'UV_CACHE_DIR': str(runtime / 'review-tools/uv-cache'),
           'TEMP': str(runtime / 'review-tools/temp'), 'TMP': str(runtime / 'review-tools/temp')}
    Path(env['TEMP']).mkdir(parents=True, exist_ok=True)
    execute([args.uv, 'pip', 'sync', '--python', str(python), str(ROOT / 'locks/intergen311.txt')], env=env)
    record('environment', 'installed', lock_sha256=hashlib.sha256((ROOT / 'locks/intergen311.txt').read_bytes()).hexdigest())
    checkpoint = cache / spec['checkpoint_path']
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    def digest(path):
        with path.open('rb') as handle:
            return hashlib.file_digest(handle, 'sha256').hexdigest()
    if checkpoint.exists() and digest(checkpoint) != spec['checkpoint_sha256']:
        raise ValueError('Existing checkpoint failed SHA256; retained for investigation')
    if not checkpoint.exists():
        if shutil.disk_usage(cache).free < 10 * 1024**3 + spec['checkpoint_bytes']:
            raise OSError('Checkpoint download would consume the reserved 10 GiB')
        partial = checkpoint.with_suffix('.ckpt.part')
        execute([str(python), '-m', 'gdown', spec['checkpoint_url'], '--fuzzy', '--continue', '-O', str(partial)], env=env)
        if digest(partial) != spec['checkpoint_sha256']:
            raise ValueError('Downloaded checkpoint failed SHA256; partial file retained')
        partial.replace(checkpoint)
    record('checkpoint', 'verified', sha256=spec['checkpoint_sha256'], bytes=checkpoint.stat().st_size,
           source=spec['checkpoint_url'], redistribution='excluded from public package')
    if args.generate:
        execute([str(python), str(ROOT / 'scripts/generate_intergen_engineering.py'), '--source', str(source),
                 '--checkpoint', str(checkpoint), '--selection', str(ROOT / 'resources/real-input-selection.json'),
                 '--output', str(cache / 'intergen')], env=env)
        record('generation', 'complete')
except Exception as exc:
    record('recovery', 'unavailable', error=f'{type(exc).__name__}: {exc}')
    sys.exit(2)
