"""Diagnose core and optional integrations without importing generation code."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from motionlint.resources import cache_root


def diagnose(runtime=None):
    runtime = Path(runtime or os.environ.get('MOTIONLINT_RUNTIME', Path(__file__).resolve().parents[2] / 'HumanAction-runtime'))
    cache = cache_root()
    cache.mkdir(parents=True, exist_ok=True)
    components = {}
    for name in ('numpy', 'yaml', 'pymotion', 'cvxpy', 'clarabel', 'fastapi', 'uvicorn', 'imageio_ffmpeg'):
        components[name] = {'available': importlib.util.find_spec(name) is not None, 'required': name in ('numpy', 'yaml', 'pymotion')}
    blender = next(iter(runtime.glob('blender*/blender.exe')), None) or shutil.which('blender')
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg and components['imageio_ffmpeg']['available']:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    for name, path in (('blender', blender), ('ffmpeg', ffmpeg), ('kenney', runtime / 'assets/kenney/protagonists/Model/characterMedium.fbx'),
                       ('intergen_checkpoint', runtime / 'resources/src/InterGen/checkpoints/intergen.ckpt')):
        components[name] = {'available': bool(path and Path(path).is_file()), 'required': False, 'path': str(path) if path else None}
    gpu = {'available': False, 'required': False}
    executable = shutil.which('nvidia-smi')
    if executable:
        try:
            value = subprocess.run([executable, '--query-gpu=name,memory.total,driver_version', '--format=csv,noheader'], text=True, capture_output=True, timeout=10)
            gpu = {'available': value.returncode == 0, 'required': False, 'devices': value.stdout.strip()}
        except (OSError, subprocess.TimeoutExpired) as exc:
            gpu['reason'] = str(exc)
    components['gpu'] = gpu
    python_supported = (3, 10) <= sys.version_info[:2] <= (3, 11)
    free = shutil.disk_usage(cache).free
    return {'schema_version': 3, 'python': platform.python_version(), 'python_supported': python_supported,
            'platform': platform.platform(), 'cache_root': str(cache), 'free_bytes': free,
            'resource_space_ready': free >= 10 * 1024**3, 'components': components,
            'core_ready': python_supported and all(row['available'] for row in components.values() if row['required']),
            'scope': 'Optional resource absence is an environment condition, never motion quality FAIL.'}
