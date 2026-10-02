"""Check local artifacts separately from pending scientific/human acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-submission-ready', action='store_true')
    args = parser.parse_args()
    checks, errors = [], []

    def check(name, action):
        try:
            detail = action()
            checks.append({'name': name, 'status': 'PASS', 'detail': detail})
        except (AssertionError, OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            errors.append(name)
            checks.append({'name': name, 'status': 'FAIL', 'detail': str(exc)})

    packages = ROOT / 'output/packages'

    def checksum_file():
        count = 0
        for line in (packages / 'SHA256SUMS.txt').read_text(encoding='ascii').splitlines():
            digest, name = line.split('  ', 1)
            assert Path(name).name == name, 'Unsafe artifact name'
            assert sha(packages / name) == digest, f'Hash mismatch: {name}'
            count += 1
        assert count >= 4, 'Missing handoff artifact'
        return f'{count} artifact hashes match'

    # The candidate README is generated, rather than copied from the platform README.
    def source_integrity():
        with zipfile.ZipFile(packages / 'motionlint-0.4.0-source-candidate.zip') as archive:
            manifest = json.loads(archive.read('MANIFEST.json'))
            names = [row['path'] for row in manifest['files']]
            assert len(names) == len(set(names))
            assert set(archive.namelist()) == set(names) | {'MANIFEST.json'}
            for row in manifest['files']:
                name = row['path']
                assert not Path(name).is_absolute() and '..' not in Path(name).parts
                assert hashlib.sha256(archive.read(name)).hexdigest() == row['sha256'], name
                if name != 'README.md':
                    assert sha(ROOT / name) == row['sha256'], f'Source changed: {name}'
                assert not name.lower().endswith(('.ckpt', '.pth', '.fbx', '.npy', '.npz', '.mp3', '.mp4'))
            return f'{len(names)} allowlisted files verified'

    def evidence():
        with zipfile.ZipFile(packages / 'motionlint-0.4.0-evidence-candidate.zip') as archive:
            manifest = json.loads(archive.read('EVIDENCE_MANIFEST.json'))
            assert set(archive.namelist()) == {r['path'] for r in manifest['files']} | {'EVIDENCE_MANIFEST.json'}
            for row in manifest['files']:
                assert hashlib.sha256(archive.read(row['path'])).hexdigest() == row['packaged_sha256'], row['path']
                assert sha(ROOT / row['path']) == row['source_sha256'], f'Evidence changed: {row["path"]}'
            return f'{len(manifest["files"])} evidence files verified'

    def wheel():
        with zipfile.ZipFile(packages / 'motionlint-0.4.0-py3-none-any.whl') as archive:
            count = 0
            for name in archive.namelist():
                if name.startswith('motionlint/') and name.endswith(('.py', '.yaml')):
                    assert archive.read(name) == (ROOT / name).read_bytes(), f'Stale wheel: {name}'
                    count += 1
            expected = {p.relative_to(ROOT).as_posix() for p in (ROOT / 'motionlint').rglob('*.py')}
            assert expected <= set(archive.namelist()), 'Wheel lacks current modules'
            assert count > 0
            return f'{count} core files match the wheel'

    def handoff():
        with zipfile.ZipFile(packages / 'motionlint-classmate-install.zip') as archive:
            for line in archive.read('SHA256SUMS.txt').decode('ascii').splitlines():
                digest, name = line.split('  ', 1)
                assert hashlib.sha256(archive.read(name)).hexdigest() == digest, name
            return 'Wheel, executable recorder, instructions and empty feedback template verified'

    def media():
        paths = [('report_validation.json', 'output/pdf/motionlint_v4_review.pdf', 'pdf_sha256'),
                 ('browser/narrated_video_verification.json', 'output/video/motionlint_v4_narrated_draft.mp4', 'sha256')]
        for record_path, artifact, field in paths:
            row = json.loads((ROOT / 'reports/first_prize' / record_path).read_text(encoding='utf-8'))
            assert sha(ROOT / artifact) == row[field], artifact
        assert row['full_decode_returncode'] == 0 and 180 <= row['duration_s'] <= 300
        assert row['bytes'] <= 300_000_000
        return 'Reviewed report hash and fully decoded draft video hash match'

    for name, action in [('artifact_checksums', checksum_file), ('source_integrity', source_integrity),
                         ('evidence_integrity', evidence), ('wheel_matches_core', wheel),
                         ('classmate_handoff', handoff), ('report_and_video', media)]:
        check(name, action)
    # Manual evidence cannot be inferred from artifact presence alone.
    pending = ['Independent annotations and adjudication; development calibration and final rule freeze',
               '19-sample blind evaluation, semantic checks and six-sample stage audit',
               'Two actual external installations and user task feedback',
               'Linux and remote CI validation', 'Ownership/license decision and publication review',
               'Team review of final narration, report and submission contents']
    record = {'schema_version': 1, 'artifact_status': 'verified' if not errors else 'failed',
              'submission_ready': False, 'checks': checks, 'pending_acceptance': pending,
              'scope': 'Local engineering delivery checks; not certification of competition eligibility'}
    path = ROOT / 'reports/first_prize/delivery_audit.json'
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in checks:
        print(f'{row["status"]}: {row["name"]}: {row["detail"]}')
    print('Submission readiness: pending human and final acceptance')
    return 2 if errors else (1 if args.require_submission_ready else 0)


if __name__ == '__main__':
    sys.exit(main())
