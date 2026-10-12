"""Resource failures, pinned export jobs and full video validation."""
from concurrent.futures import Future
import subprocess

import pytest
from fastapi import HTTPException

import motionlint.api as api
from motionlint.character_export import verify_video


def test_export_requires_resources_and_does_not_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(api, '_task_folder', lambda _: tmp_path)
    monkeypatch.setattr(api, '_checked_run', lambda _: (tmp_path, {'run_id': 'run', 'stages': {'bvh': {}}}))
    monkeypatch.setattr(api, 'character_resources', lambda *args: {'available': False, 'checks': {'Blender': False}})
    with pytest.raises(HTTPException) as error:
        api.start_character_export(api.TaskRef(source='import', task_id='task'))
    assert error.value.status_code == 422
    assert 'Blender' in error.value.detail
    assert not (tmp_path / 'motionlint/character_request.json').exists()


def test_export_pins_source_run_and_prevents_duplicate_dispatch(tmp_path, monkeypatch):
    calls = []
    future = Future()
    class Executor:
        def submit(self, *args):
            calls.append(args)
            return future
    monkeypatch.setattr(api, '_task_folder', lambda _: tmp_path)
    monkeypatch.setattr(api, '_checked_run', lambda _: (tmp_path, {'run_id': 'frozen-run', 'stages': {'bvh': {}}}))
    monkeypatch.setattr(api, 'character_resources', lambda *args: {'available': True})
    monkeypatch.setattr(api, 'CHARACTER_EXECUTOR', Executor())
    monkeypatch.setattr(api, 'CHARACTER_JOBS', {})
    ref = api.TaskRef(source='import', task_id='task')
    assert api.start_character_export(ref)['status'] == 'queued'
    assert calls[0][-1] == 'frozen-run'
    assert api.start_character_export(ref)['status'] == 'running'
    assert len(calls) == 1


def test_video_validator_decodes_full_clip_and_rejects_wrong_metadata_or_truncation(tmp_path):
    imageio = pytest.importorskip('imageio_ffmpeg', reason='optional local renderer validation')
    ffmpeg = imageio.get_ffmpeg_exe()
    video = tmp_path / 'clip.mp4'
    subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=32x32:r=8',
                    '-frames:v', '4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(video)], check=True, timeout=60)
    assert verify_video(video, ffmpeg, frames=4, fps=8)['fully_decoded']
    for frames, fps in ((5, 8), (4, 10)):
        with pytest.raises(ValueError, match='视频校验失败'):
            verify_video(video, ffmpeg, frames=frames, fps=fps)
    video.write_bytes(video.read_bytes()[:-50])
    with pytest.raises(ValueError):
        verify_video(video, ffmpeg, frames=4, fps=8)


def test_changed_source_before_worker_start_reports_failure(tmp_path, monkeypatch):
    import json
    import motionlint.character_export as module
    monkeypatch.setattr(module, 'current_run', lambda *args: (_ for _ in ()).throw(ValueError('input changed')))
    module.export_character(tmp_path, tmp_path, tmp_path, 'job', 'source-run')
    state = json.loads((tmp_path / 'motionlint/character_exports/job/status.json').read_text())
    assert state['status'] == 'failed' and 'input changed' in state['error']
