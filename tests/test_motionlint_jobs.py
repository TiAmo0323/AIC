"""Process loss, cancellation and immutable pipeline retries."""
import json
from pathlib import Path
import numpy as np
import pytest
from motionlint.jobs import Job, Cancelled
from motionlint.benchmark.fixtures import standing
from motionlint.pipeline.local import run_pipeline


def test_cancel_request_persists_and_prevents_publication(tmp_path):
    job = Job(tmp_path)
    job.cancel()
    with pytest.raises(Cancelled):
        job.checkpoint('repair')
    assert Job(tmp_path, job.id, create=False).state['status'] == 'cancelled'
    assert not (job.folder / 'result.json').exists()


def test_lost_process_is_interrupted_with_original_state_preserved(tmp_path):
    job = Job(tmp_path)
    job.update('running', owner_pid=2147480000, stage='export')
    state = Job(tmp_path, job.id, create=False).recover()
    assert state['status'] == 'interrupted' and state['stage'] == 'export'


def test_pipeline_repeated_output_keeps_original_inputs_and_products(tmp_path):
    path = tmp_path / 'input.npy'
    np.save(path, standing(24))
    original = path.read_bytes()
    first = run_pipeline([path], output=tmp_path / 'product', job=Job(tmp_path / 'data'))
    manifest = Path(first['run_dir']) / 'manifest.json'
    saved = manifest.read_bytes()
    second = run_pipeline([path], output=tmp_path / 'product', job=Job(tmp_path / 'data'))
    assert first['task_dir'] != second['task_dir']
    assert manifest.read_bytes() == saved and path.read_bytes() == original
    assert first['stages']['bvh']['round_trip_max_coordinate_error_m'] < .1
    assert first['comparison']['status'] == 'PASS'


def test_error_has_durable_input_failure_and_no_ready_pointer(tmp_path):
    path = tmp_path / 'invalid.npy'
    np.save(path, np.full((8, 22, 3), np.nan))
    job = Job(tmp_path / 'data')
    with pytest.raises(ValueError, match='NaN'):
        run_pipeline([path], output=tmp_path / 'product', job=job)
    state = json.loads(job.path.read_text(encoding='utf-8'))
    assert state['status'] == 'failed'
    assert not (tmp_path / 'product/motionlint/current_repair.json').exists()
