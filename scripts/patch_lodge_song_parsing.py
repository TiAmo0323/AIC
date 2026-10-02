"""Apply and verify a narrowly scoped local upstream compatibility patch."""
from pathlib import Path
import ast
import difflib
import hashlib
import json
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT.parent / 'HumanAction-runtime/LODGE-main/concat_res.py'
OUT = ROOT / 'reports/first_prize/lodge_loading'

NEW_FUNCTION = '''def get_songlist(modir):
    # The final gNNNg marker is structural; g inside a song identifier is data.
    import re
    songs = []
    for name in sorted(os.listdir(modir)):
        match = re.fullmatch(r"dod_\\d+_(.+)g\\d{3}g_l\\d{3}(?:_r\\d+)?\\.(?:npy|pkl)", name)
        if match and match.group(1) not in songs:
            songs.append(match.group(1))
    return songs
'''


def main():
    original = TARGET.read_text(encoding='utf-8')
    tree = ast.parse(original)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'get_songlist')
    lines = original.splitlines(keepends=True)
    patched = ''.join(lines[:function.lineno-1]) + NEW_FUNCTION + ''.join(lines[function.end_lineno:])
    old = '            if len(local_fineme) == 1:\n                local_fineme = local_fineme[0]'
    new = '            if len(local_fineme) != 1:\n                raise ValueError(f"Expected one segment for {song}, global {gi}, local {li}; found {len(local_fineme)}")\n            local_fineme = local_fineme[0]'
    if old in patched:
        patched = patched.replace(old, new)
    ast.parse(patched)
    namespace = {'os': __import__('os')}
    exec(NEW_FUNCTION, namespace)
    with tempfile.TemporaryDirectory(prefix='motionlint-song-parser-') as folder:
        for name in ['dod_0_ml261002lg05g000g_l000.npy', 'dod_1_ml261002lg05g000g_l001.npy',
                     'dod_0_song_with_g_and_underscoresg000g_l000.npy', 'dod_0_063g000g_l000.npy', 'unrelated.npy']:
            (Path(folder) / name).touch()
        observed = namespace['get_songlist'](folder)
        expected = ['063', 'ml261002lg05', 'song_with_g_and_underscores']
        if observed != expected:
            raise AssertionError((observed, expected))
    OUT.mkdir(parents=True, exist_ok=True)
    backup = OUT / 'concat_res.before.py'
    if not backup.exists():
        backup.write_text(original, encoding='utf-8')
    TARGET.write_text(patched, encoding='utf-8')
    baseline = backup.read_text(encoding='utf-8')
    (OUT / 'song_identifier.patch').write_text(''.join(difflib.unified_diff(baseline.splitlines(True), patched.splitlines(True), fromfile='a/concat_res.py', tofile='b/concat_res.py')), encoding='utf-8')
    (OUT / 'song_identifier_validation.json').write_text(json.dumps({
        'target': str(TARGET), 'before_sha256': hashlib.sha256(baseline.encode()).hexdigest(),
        'after_sha256': hashlib.sha256(patched.encode()).hexdigest(), 'parser_cases_passed': True,
        'status': 'local_patch_verified', 'community_submission': 'not_submitted',
        'generation_validation': 'pending_real_retry'}, indent=2), encoding='utf-8')
    print('Song parsing patch applied; numeric, g-containing and underscore identifiers verified')


if __name__ == '__main__':
    main()
