"""Resource recovery with immutable sources, partial files and content checks."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request


def cache_root():
    default = Path('D:/MotionLint-cache') if os.name == 'nt' and Path('D:/').exists() else Path.home() / '.cache/motionlint'
    return Path(os.environ.get('MOTIONLINT_CACHE', default)).resolve()


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def fetch(entry, root, *, reserve_bytes=10 * 1024**3, opener=urllib.request.urlopen):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / entry['path']).resolve()
    if not target.is_relative_to(root):
        raise ValueError('Resource path escapes the cache')
    if not entry['url'].startswith('https://'):
        raise ValueError('Remote resources require HTTPS')
    expected = entry.get('sha256')
    if target.is_file() and expected and digest(target) == expected:
        return {'status': 'verified', 'sha256': expected, 'bytes': target.stat().st_size}
    partial = target.with_suffix(target.suffix + '.part')
    target.parent.mkdir(parents=True, exist_ok=True)
    offset = partial.stat().st_size if partial.exists() else 0
    if shutil.disk_usage(root).free < reserve_bytes + 1024**2:
        raise OSError('Resource recovery requires at least 10 GiB free after download')
    headers = {'User-Agent': 'MotionLint/0.5.0'}
    if offset:
        headers['Range'] = f'bytes={offset}-'
    request = urllib.request.Request(entry['url'], headers=headers)
    with opener(request, timeout=60) as response:
        resumed = offset and response.status == 206
        if resumed and not response.headers.get('Content-Range', '').startswith(f'bytes {offset}-'):
            raise ValueError('Invalid range response; existing partial file retained')
        remaining = int(response.headers.get('Content-Length', 0))
        if remaining and shutil.disk_usage(root).free < reserve_bytes + remaining:
            raise OSError('Download would consume the reserved disk space')
        received = 0
        with partial.open('ab' if resumed else 'wb') as output:
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                if shutil.disk_usage(root).free < reserve_bytes + len(chunk):
                    raise OSError('Reserved disk space reached; resume after freeing space')
                output.write(chunk)
                received += len(chunk)
        if remaining and received != remaining:
            raise OSError('Truncated download; partial file retained for resumption')
    actual = digest(partial)
    if expected and actual != expected:
        raise ValueError('Resource SHA256 mismatch; candidate was not published')
    if entry.get('git_blob_sha1'):
        content = partial.read_bytes()
        blob = hashlib.sha1(f'blob {len(content)}\0'.encode() + content).hexdigest()
        if blob != entry['git_blob_sha1']:
            raise ValueError('Resource does not match its pinned upstream Git object')
    partial.replace(target)
    return {'status': 'downloaded', 'sha256': actual, 'bytes': target.stat().st_size,
            'source_verification': 'sha256' if expected else 'pinned_git_object' if entry.get('git_blob_sha1') else 'observed_hash_only'}


def restore(manifest_path, root=None):
    manifest = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    root = Path(root or cache_root())
    records = []
    for entry in manifest['resources']:
        try:
            receipt = fetch(entry, root)
        except (OSError, ValueError) as exc:
            receipt = {'status': 'unavailable', 'error': f'{type(exc).__name__}: {exc}'}
        records.append({'id': entry['id'], 'source': entry['url'], 'license': entry['license'], **receipt})
        print(entry['id'], receipt['status'], flush=True)
        (root / 'recovery.json').write_text(json.dumps({'records': records}, indent=2), encoding='utf-8')
    return {'records': records, 'complete': all(r['status'] != 'unavailable' for r in records)}
