"""Repair downloads must round-trip, preserve inputs and reject stale output."""
import asyncio
import io
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np
import pytest
from fastapi import HTTPException, UploadFile

import motionlint.api as api
from motionlint.benchmark.fixtures import standing
from motionlint.bvh_writer import write_bvh
from motionlint.core.skeleton import BVH_NAMES


@pytest.fixture
def root(tmp_path, monkeypatch):
    root = tmp_path / 'imports'
    monkeypatch.setitem(api.TASK_ROOTS, 'import', root)
    return root


def submit(data, name='test.npy', **options):
    if isinstance(data, np.ndarray):
        stream = io.BytesIO()
        np.save(stream, data)
        data = stream.getvalue()
    return asyncio.run(api.import_motion(files=[UploadFile(filename=name, file=io.BytesIO(data))],
        fps=options.get('fps', 30), unit_scale=options.get('unit_scale', 1), up_axis=options.get('up_axis', 1),
        joint_mapping=json.dumps(options.get('joint_mapping', {}))))


def test_accepted_repair_bundle_and_actual_reimport(root, tmp_path):
    from motionlint.benchmark.fixtures import build
    fixtures = tmp_path / 'fixtures'
    build(fixtures)
    sample = np.load(fixtures / 'foot_sliding_00.npy', allow_pickle=False)
    first = submit(sample, fps=30)
    ref = api.TaskRef(**first['task'])
    task = root / ref.task_id
    original = (task / 'actor1.npy').read_bytes()
    result = api.repair_task(ref)
    artifact = result['artifacts']
    assert (task / 'actor1.npy').read_bytes() == original
    assert result['after']['overall_score'] >= result['before']['overall_score']
    assert any(step['applied'] for step in result['repair']['steps'])
    run_id = artifact['run_id']
    response = api.repair_bundle('import', ref.task_id, run_id)
    with ZipFile(response.path) as bundle:
        assert {'manifest.json', 'quality.yaml', 'comparison.json', 'raw_motion.npz', 'repaired_motion.npz',
                'repaired_actor1.npy', 'repaired/motionlint_report.json'} <= set(bundle.namelist())
        exported = np.load(io.BytesIO(bundle.read('repaired_actor1.npy')), allow_pickle=False)
    preview = api.task_preview('import', ref.task_id, 'repaired', start=31, count=2, run_id=run_id)
    np.testing.assert_allclose(preview['positions'], exported[31:33, None], atol=1e-8)
    repeat = api.reimport_artifact(api.ReimportRequest(**ref.model_dump(), run_id=run_id))
    assert repeat['task']['task_id'] != ref.task_id
    assert repeat['import']['fps'] == 30
    assert repeat['report']['overall_score'] == result['after']['overall_score']
    assert repeat['report']['metadata']['evaluated_array_sha256'] == result['after']['metadata']['evaluated_array_sha256']
    assert repeat['report']['metadata']['input_sha256'] != result['before']['metadata']['input_sha256']
    # Each run is immutable and addressable after another repair.
    newer = api.repair_task(ref)
    assert newer['artifacts']['run_id'] != run_id
    assert Path(api.repair_bundle('import', ref.task_id, run_id).path).read_bytes() == Path(response.path).read_bytes()


@pytest.mark.parametrize('changed', ['original', 'export', 'manifest', 'bundle'])
def test_stale_and_tampered_files_are_not_served(root, changed):
    uploaded = submit(standing(12))
    ref = api.TaskRef(**uploaded['task'])
    result = api.repair_task(ref)
    run = root / ref.task_id / 'motionlint/repairs' / result['artifacts']['run_id']
    path = {'original': root / ref.task_id / 'actor1.npy', 'export': run / 'repaired_actor1.npy',
            'manifest': run / 'manifest.json', 'bundle': run / 'bundle.zip'}[changed]
    path.write_bytes(path.read_bytes() + b'changed')
    with pytest.raises(HTTPException) as error:
        api.repair_bundle('import', ref.task_id, result['artifacts']['run_id'])
    assert error.value.status_code == 409


def test_bvh_round_trip_preserves_fractional_fps_scale_axis_and_mapping(root, tmp_path):
    path = tmp_path / 'source.bvh'
    root_track = np.tile([100, 0, 120.], (15, 1))
    rotations = np.zeros((15, len(BVH_NAMES), 3))
    rotations[:, 0, 0] = np.linspace(0, 2, 15)
    write_bvh(path, root_track, rotations, 29.97)
    data = path.read_text().replace('LeftFoot', 'customLeftFoot').encode()
    uploaded = submit(data, 'motion.bvh', unit_scale=.01, up_axis=2, joint_mapping={'customLeftFoot': 'LeftFoot'})
    ref = api.TaskRef(**uploaded['task'])
    result = api.repair_task(ref)
    artifact = result['artifacts']
    assert artifact['export'][0]['options']['unit_scale'] == .01
    assert artifact['export'][0]['options']['joint_mapping'] == {'customLeftFoot': 'LeftFoot'}
    assert artifact['export'][0]['options']['up_axis'] == 2
    repeated = api.reimport_artifact(api.ReimportRequest(**ref.model_dump(), stage='bvh'))
    assert repeated['import']['fps'] == pytest.approx(29.97, abs=1e-7)
    assert repeated['import']['up_axis'] == 2
    assert repeated['report']['overall_score'] == api.inspect_stage(api.StageRequest(**ref.model_dump(), stage='bvh'))['report']['overall_score']
    original = api.task_preview('import', ref.task_id, 'raw', start=0, count=15)
    exported = api.task_preview('import', ref.task_id, 'repaired', start=0, count=15)
    # This sample needs no supported repair; BVH FK must survive canonical naming.
    np.testing.assert_allclose(original['positions'], exported['positions'], atol=1e-8)


def test_shared_support_bvh_repair_survives_actual_file_reimport(root, tmp_path):
    path = tmp_path / 'drifting.bvh'
    root_track = np.tile([0., 1., 0.], (30, 1))
    root_track[:, 0] = np.linspace(0., .24, 30)
    write_bvh(path, root_track, np.zeros((30, len(BVH_NAMES), 3)), 29.97)
    uploaded = submit(path.read_bytes(), 'drifting.bvh')
    ref = api.TaskRef(**uploaded['task'])
    result = api.repair_task(ref)
    support = result['repair']['support_comparison']
    assert result['repair']['steps'][0]['applied']
    assert support['original_support_distance_after_m'] < 1e-7
    repeated = api.reimport_artifact(api.ReimportRequest(**ref.model_dump(), stage='bvh'))
    assert repeated['import']['fps'] == pytest.approx(29.97, abs=1e-7)
    assert repeated['report']['overall_score'] == result['after']['overall_score']
    original = api.task_preview('import', ref.task_id, 'raw', start=0, count=30)
    exported = api.task_preview('import', ref.task_id, 'bvh', start=0, count=30)
    assert np.linalg.norm(np.asarray(exported['positions']) - original['positions'], axis=-1).max() <= .15 + 1e-6


def test_lodge_repair_uses_frozen_geometry_and_keeps_contacts(root, monkeypatch):
    import motionlint.adapters.lodge_adapter as adapter
    monkeypatch.setattr(adapter, 'resolve_model', lambda _: None)
    raw = np.zeros((30, 139))
    raw[:, :4] = 1
    raw[:, 5] = 1
    raw[:, 4] = np.arange(30) * .008
    raw[:, 7:] = np.tile([1, 0, 0, 0, 1, 0], 22)
    uploaded = submit(raw, fps=24)
    monkeypatch.setattr(adapter, 'resolve_model', lambda _: pytest.fail('Repair must not switch to a different model'))
    ref = api.TaskRef(**uploaded['task'])
    result = api.repair_task(ref)
    path = api.repair_file('import', ref.task_id, result['artifacts']['run_id'], 'repaired.npy').path
    saved = np.load(path, allow_pickle=False)
    np.testing.assert_array_equal(saved[:, :4], raw[:, :4])
    assert result['after']['metadata']['geometry_source'] == 'fixed_bvh_proxy'
    assert result['after']['overall_score'] >= result['before']['overall_score']


def test_download_cannot_escape_manifest(root):
    imported = submit(standing(12))
    ref = api.TaskRef(**imported['task'])
    result = api.repair_task(ref)
    for key in ('../../outside.npy', 'quality.yaml', 'raw_motion.npz'):
        with pytest.raises(HTTPException) as error:
            api.repair_file('import', ref.task_id, result['artifacts']['run_id'], key)
        assert error.value.status_code == 404


def test_two_actor_import_repair_download_and_reimport_keep_roles(root):
    streams, originals = [], []
    for actor in range(2):
        stream = io.BytesIO()
        np.save(stream, standing(24) + [actor * 2.5, 0, 0])
        originals.append(stream.getvalue())
        streams.append(UploadFile(filename=f'person{actor + 1}.npy', file=io.BytesIO(originals[-1])))
    imported = asyncio.run(api.import_motion(files=streams, fps=24, unit_scale=1, up_axis=1, joint_mapping='{}'))
    ref = api.TaskRef(**imported['task'])
    result = api.repair_task(ref)
    assert len(result['artifacts']['export']) == 2
    repeated = api.reimport_artifact(api.ReimportRequest(**ref.model_dump()))
    assert repeated['import']['actor_count'] == 2 and repeated['import']['fps'] == 24
    assert repeated['report']['metadata']['evaluated_array_sha256'] == result['after']['metadata']['evaluated_array_sha256']
    poses = api.task_preview('import', ref.task_id, 'repaired', start=0, count=1)['positions'][0]
    np.testing.assert_allclose(np.array(poses[1]) - poses[0], np.tile([2.5, 0, 0], (22, 1)))
    for actor in range(2):
        assert (root / ref.task_id / f'actor{actor + 1}.npy').read_bytes() == originals[actor]


@pytest.mark.parametrize('cache', ['normalized_motion.npz', 'preview_positions.npy'])
def test_frozen_import_caches_cannot_silently_change(root, cache):
    imported = submit(standing(12))
    ref = api.TaskRef(**imported['task'])
    path = root / ref.task_id / cache
    path.write_bytes(path.read_bytes() + b'changed')
    with pytest.raises(HTTPException) as error:
        if cache == 'normalized_motion.npz':
            api.repair_task(ref)
        else:
            api.imported_preview(ref.task_id, start=0, count=1)
    assert error.value.status_code == 422
