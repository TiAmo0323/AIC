"""Preserve actual local UI QA and decode footage; never create human labels."""
import hashlib
import json
import re
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reports/first_prize/browser'
FFMPEG = ROOT.parent / 'HumanAction-runtime/bin/ffmpeg.exe'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(path, expected_frames=None):
    command = [str(FFMPEG), '-v', 'info', '-nostats', '-progress', 'pipe:1',
               '-xerror', '-err_detect', 'explode', '-i', str(path), '-map', '0:v:0',
               '-an', '-fps_mode', 'passthrough', '-f', 'null', '-']
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', check=True)
    frames = int(re.findall(r'^frame=(\d+)$', result.stdout, re.M)[-1])
    fps = float(re.search(r'Video:.*?\b([0-9.]+) fps\b', result.stderr).group(1))
    if 'progress=end' not in result.stdout or (expected_frames is not None and frames != expected_frames):
        raise ValueError(f'Incomplete or wrong frame count: {path}')
    return {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size,
            'decoded_frames': frames, 'fps': fps, 'duration_s': frames / fps,
            'full_decode_returncode': result.returncode}


def main():
    provenance = json.loads((OUT / 'demo_provenance.json').read_text(encoding='utf-8'))
    task_id = provenance['task_id']
    task = ROOT / 'InterGen_api/task_runs' / task_id
    with urllib.request.urlopen(f'http://127.0.0.1:8003/v1/motionlint/tasks/intergen/{task_id}/character-export-status') as response:
        exported = json.load(response)
    if exported['status'] != 'ready':
        raise ValueError('Character export is not complete')
    folder = Path(exported['export_dir'])
    reports = {}
    for stage in ('repaired', 'repaired_bvh', 'repaired_character'):
        report = json.loads((folder / stage / 'motionlint_report.json').read_text(encoding='utf-8'))
        gate = json.loads((folder / stage / 'quality_gate.json').read_text(encoding='utf-8'))
        reports[stage] = {'score': report['overall_score'], 'gate': gate,
                         'metadata': report['metadata']}
    if len({row['metadata']['config_sha256'] for row in reports.values()}) != 1:
        raise ValueError('Export stages use different rules')
    videos = [decode(task / 'motionlint' / name, 180) for name in ('original.mp4', 'repaired.mp4')]
    videos.append(decode(Path(exported['video_path']), 180))
    verification = {'status': 'verified', 'scope': 'Developer browser QA on copied historical development input; not human validation or new blind samples',
        'task_id': task_id, 'browser_observations': [
            {'check': 'raw_issue_details_and_stage_video', 'result': 'PASS', 'observed': 'Frame 0-1, actor 1, joints 18/20, value 0.1370, threshold 0.12; raw URL, 6 seconds'},
            {'check': 'repair_accept_reject_and_residual_gate', 'result': 'PASS', 'observed': 'foot_lock and bone projection accepted; inter-actor separation rejected for total movement; overall gate FAIL'},
            {'check': 'linked_video_seek_rate_and_play', 'result': 'PASS', 'observed': 'Both videos at 1 second, rate 0.5; both play after leader starts'},
            {'check': 'bvh_has_no_unrelated_video_seek', 'result': 'PASS', 'observed': 'repaired_bvh: no main video, scrub disabled'},
            {'check': 'character_issues_use_character_video', 'result': 'PASS', 'observed': 'repaired_character URL, 6 seconds; issue frame 21, actor 1, joint 21, speed 0.2771 vs 0.16'},
            {'check': 'annotation_load_export_resume', 'result': 'PASS', 'observed': '30 clips loaded; synthetic QA-only record on development clip ig02s0 exported and restored; no tool predictions shown'}],
        'console': {'workbench_errors': 0, 'workbench_warnings': ['QA pauses immediately after seek autoplay, causing AbortError'],
                    'annotation_initial_errors': ['favicon.ico 404; data favicon added subsequently']},
        'human_annotation': 'pending; QA_ONLY_NOT_HUMAN is excluded from annotation truth',
        'export_reports': reports, 'videos': videos}
    (OUT / 'verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding='utf-8')
    video_out = ROOT / 'output/video/motionlint_v4_operations.mp4'
    recordings = [ROOT / 'output/video' / name for name in
                  ('motionlint_v4_operations_take2.webm', 'motionlint_v4_character_take3.webm')]
    # Concatenate real captured operations. Do not extend still frames or fabricate actions.
    command = [str(FFMPEG), '-y', '-v', 'error', '-i', str(recordings[0]), '-i', str(recordings[1]),
               '-filter_complex', '[0:v]fps=25,format=yuv420p,setsar=1[v0];[1:v]trim=duration=32,setpts=PTS-STARTPTS,fps=25,format=yuv420p,setsar=1[v1];[v0][v1]concat=n=2:v=1:a=0[v]',
               '-map', '[v]', '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-movflags', '+faststart', str(video_out)]
    subprocess.run(command, check=True)
    footage = decode(video_out)
    footage.update(status='engineering_operations_draft_not_final_submission',
        competition_duration_and_size_check=180 <= footage['duration_s'] <= 300 and footage['bytes'] <= 300_000_000,
        pending=['Final narration and CLI section', 'Independent human results', 'Team review'],
        edit_note='Full first operation take plus first 32 seconds of the character take; no time extension',
        recordings=[{'path': str(p), 'sha256': sha(p)} for p in recordings])
    (OUT / 'video_verification.json').write_text(json.dumps(footage, ensure_ascii=False, indent=2), encoding='utf-8')
    annotation = ROOT / 'reports/first_prize/study/annotation_pack'
    shutil.copyfile(ROOT / 'tools/annotation/index.html', annotation / 'index.html')
    archive_path = ROOT / 'output/packages/motionlint-annotation-local-only.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ('index.html', 'clips.json', 'INSTRUCTIONS.md'):
            archive.write(annotation / name, name)
    (OUT / 'annotation_handoff.json').write_text(json.dumps({'path': str(archive_path), 'sha256': sha(archive_path),
        'scope': 'Local authorized classmates only; not part of public source candidate', 'clips': 30}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ui_status': verification['status'], 'video': footage,
                      'annotation_archive': str(archive_path)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
