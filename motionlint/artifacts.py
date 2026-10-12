"""Immutable repair runs and independently checked, downloadable exports."""
from dataclasses import fields
from pathlib import Path
from uuid import uuid4, UUID
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib
import json

import numpy as np

from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.config import DEFAULT_CONFIG
from motionlint.cli.main import _write_json, _write_report, load_motion
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.regression import compare
from motionlint.bvh_writer import write_bvh, matrix_to_zyx_euler_degrees
from motionlint.adapters.bvh_adapter import load_bvh_pair
from motionlint.joints_to_bvh import convert_continuous_joints


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def save_motion(path, motion):
    description, arrays = {}, {}
    for field in fields(motion):
        value = getattr(motion, field.name)
        if isinstance(value, np.ndarray):
            arrays[field.name] = value
        else:
            description[field.name] = value
    np.savez_compressed(path, description=json.dumps(description, ensure_ascii=False), **arrays)


def read_motion(path):
    with np.load(path, allow_pickle=False) as archive:
        description = json.loads(str(archive['description'].item()))
        arrays = {key: archive[key] for key in ('positions', 'rotations_6d', 'rotation_matrices', 'root_translation', 'contacts','local_positions','channel_values') if key in archive}
    return MotionSequence(**description, **arrays)


def current_run(task_folder, run_id=None, *, verify=True):
    task_folder = Path(task_folder).resolve()
    if run_id is None:
        pointer = json.loads((task_folder / 'motionlint/current_repair.json').read_text(encoding='utf-8'))
        run_id = pointer['run_id']
    if str(UUID(run_id)) != run_id:
        raise ValueError('修复记录编号无效')
    folder = task_folder / 'motionlint/repairs' / run_id
    ready = json.loads((folder / 'ready.json').read_text(encoding='utf-8'))
    if sha256(folder / 'manifest.json') != ready['manifest_sha256']:
        raise ValueError('修复清单已变化，请重新修复')
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['run_id'] != run_id:
        raise ValueError('修复记录不一致')
    for entry in manifest['files']:
        path = (folder / entry['path']).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            raise ValueError('修复产物丢失或路径无效')
        if verify and sha256(path) != entry['sha256']:
            raise ValueError('修复产物已变化，请重新修复')
    if verify:
        for entry in manifest['inputs']:
            path = (task_folder / entry['path']).resolve()
            if not path.is_relative_to(task_folder) or not path.is_file() or sha256(path) != entry['sha256']:
                raise ValueError('原始输入已变化，请重新导入或生成')
    return folder, manifest


def stage_motion(task_folder, stage, run_id=None):
    folder, manifest = current_run(task_folder, run_id)
    entry = manifest['stages'].get(stage)
    if entry is None:
        raise FileNotFoundError('该阶段尚未导出')
    return read_motion(folder / entry['snapshot']), folder / 'quality.yaml', manifest


def public_run(manifest, source, task_id):
    base = f'/v1/motionlint/tasks/{source}/{task_id}/repairs/{manifest["run_id"]}'
    result = {key: manifest[key] for key in ('run_id', 'stages', 'export', 'accepted', 'warnings')}
    result['download_url'] = base + '/bundle'
    result['files'] = [{**entry, 'download_url': base + '/files/' + entry['key']}
                       for entry in manifest['files'] if entry.get('download')]
    return result


def persist_repair(task_folder, outcome, original, inputs, *, config_path=None):
    task_folder = Path(task_folder).resolve()
    run_id = str(uuid4())
    folder = task_folder / 'motionlint/repairs' / run_id
    folder.mkdir(parents=True)
    policy = folder / 'quality.yaml'
    policy.write_bytes(Path(config_path or DEFAULT_CONFIG).read_bytes())
    from motionlint.core.context import freeze_pair
    from motionlint.core.config import load_config
    original, candidate = freeze_pair(original, outcome.motion, load_config(policy))
    outcome.motion = candidate
    manifest = {'schema_version': 3, 'run_id': run_id, 'accepted': any(s['applied'] for s in outcome.steps),
                'inputs': [{'path': str(Path(p).resolve().relative_to(task_folder)), 'sha256': sha256(p)} for p in inputs],
                'stages': {}, 'export': [], 'files': [], 'warnings': []}
    save_motion(folder / 'raw_motion.npz', original)
    paths = []
    up = original.metadata.get('up_axis', 1)
    if original.source == 'bvh':
        for actor in range(original.actor_count):
            path = folder / f'repaired_actor{actor + 1}.bvh'
            from motionlint.bvh_preserve import write_preserving_bvh
            write_preserving_bvh(path, outcome.motion, actor)
            paths.append(path)
        exported = load_bvh_pair(paths, up_axis=up, unit_scale=original.metadata.get('unit_scale_to_metres', 1.),
                                 joint_mapping=original.metadata.get('joint_mapping'))
    elif original.source == 'lodge':
        raw = outcome.raw_lodge if outcome.raw_lodge is not None else np.load(inputs[0], allow_pickle=False)
        path = folder / 'repaired.npy'
        np.save(path, raw, allow_pickle=False)
        paths = [path]
        from motionlint.adapters.lodge_adapter import normalize_lodge_array
        exported = normalize_lodge_array(np.load(path, allow_pickle=False), fps=original.fps,
                                       source_path=path, frozen_geometry=original.metadata)
    else:
        for actor in range(original.actor_count):
            path = folder / f'repaired_actor{actor + 1}.npy'
            np.save(path, outcome.motion.positions[:, actor], allow_pickle=False)
            paths.append(path)
        exported = load_motion(paths[0], paths[1] if len(paths) == 2 else None, fps=original.fps)
    # An export whose FK differs from the accepted candidate cannot replace it.
    discrepancy = float(np.max(np.abs(exported.positions - outcome.motion.positions)))
    if discrepancy > 1e-5:
        raise ValueError(f'修复文件回读与接受的候选不一致：{discrepancy:.6f} m')
    exported.metadata.update(stage='repaired', repair_run_id=run_id, floor_height_m=original.metadata.get('floor_height_m'),
                             floor_source=original.metadata.get('floor_source', 'frozen'))
    save_motion(folder / 'repaired_motion.npz', exported)
    outcome.motion = exported
    outcome.before = inspect(original, config_path=policy)
    outcome.after = inspect(exported, config_path=policy)
    for stage, motion, report in [('raw', original, outcome.before), ('repaired', exported, outcome.after)]:
        report.metadata['inspection_stage'] = stage
        report.metadata['stage'] = stage
        _write_report(folder / stage, report)
        gate = evaluate_gate(report, config_path=policy)
        _write_json(folder / stage / 'quality_gate.json', gate.to_dict())
        manifest['stages'][stage] = {'snapshot': f'{stage}_motion.npz', 'report': f'{stage}/motionlint_report.json',
                                     'gate': gate.to_dict(), 'fps': motion.fps, 'frame_count': motion.frame_count,
                                     'up_axis': up, 'bounds': [motion.positions.min(axis=(0, 1, 2)).tolist(), motion.positions.max(axis=(0, 1, 2)).tolist()]}
    bvh_paths = paths if original.source == 'bvh' else []
    try:
        if original.source == 'intergen':
            for actor, path in enumerate(paths, 1):
                output = folder / f'repaired_actor{actor}.bvh'
                convert_continuous_joints(path, output, fps=original.fps)
                bvh_paths.append(output)
        elif original.source == 'lodge':
            output = folder / 'repaired_actor1.bvh'
            offsets = np.asarray(exported.metadata['offsets']).copy()
            offsets[0] = 0
            write_bvh(output, exported.positions[:, 0, 0], matrix_to_zyx_euler_degrees(exported.rotation_matrices[:, 0]),
                      original.fps, names=exported.joint_names, parents=exported.metadata['parents'], offsets=offsets)
            bvh_paths = [output]
        bvh = load_bvh_pair(bvh_paths, up_axis=up,
            unit_scale=original.metadata.get('unit_scale_to_metres', 1.) if original.source == 'bvh' else 1.,
            joint_mapping=original.metadata.get('joint_mapping') if original.source == 'bvh' else None)
        bvh.metadata.update(stage='bvh', repair_run_id=run_id, floor_height_m=original.metadata.get('floor_height_m'),
                            floor_source=original.metadata.get('floor_source', 'frozen'))
        save_motion(folder / 'bvh_motion.npz', bvh)
        report = inspect(bvh, config_path=policy)
        report.metadata['inspection_stage'] = 'bvh'
        gate = evaluate_gate(report, config_path=policy)
        _write_report(folder / 'bvh', report)
        _write_json(folder / 'bvh/quality_gate.json', gate.to_dict())
        common = [name for name in exported.joint_names if name in bvh.joint_names]
        geometry_error = np.linalg.norm(bvh.positions[:, :, [bvh.joint_names.index(n) for n in common]] -
            exported.positions[:, :, [exported.joint_names.index(n) for n in common]], axis=-1) if common else None
        manifest['stages']['bvh'] = {'snapshot': 'bvh_motion.npz', 'report': 'bvh/motionlint_report.json',
                                   'gate': gate.to_dict(), 'fps': bvh.fps, 'frame_count': bvh.frame_count, 'up_axis': up,
                                   'round_trip_max_coordinate_error_m': float(geometry_error.max()) if geometry_error is not None else None,
                                   'conversion_geometry': {'common_joint_names': common,
                                       'mean_joint_error_m': float(geometry_error.mean()) if geometry_error is not None else None,
                                       'p95_joint_error_m': float(np.percentile(geometry_error, 95)) if geometry_error is not None else None,
                                       'policy': 'Align by canonical joint name before comparing global positions; no index-based stage subtraction'},
                                   'bounds': [bvh.positions.min(axis=(0, 1, 2)).tolist(), bvh.positions.max(axis=(0, 1, 2)).tolist()]}
    except (ValueError, RuntimeError) as exc:
        manifest['warnings'].append(f'BVH 导出失败：{exc}')
        bvh_paths = []
    manifest['export'] = [{'key': path.name, 'format': path.suffix[1:], 'options': {'fps': original.fps,
        'unit_scale': original.metadata.get('unit_scale_to_metres', 1.) if original.source == 'bvh' else 1., 'up_axis': up,
        'joint_mapping': original.metadata.get('joint_mapping', {}) if original.source == 'bvh' else {}}} for path in paths]
    manifest['round_trip_max_coordinate_error_m'] = discrepancy
    _write_json(folder / 'repair_report.json', outcome.to_dict())
    _write_json(folder / 'comparison.json', compare(outcome.before, outcome.after, config_path=policy, baseline_motion=original, candidate_motion=exported))
    from motionlint.offline_report import write_html
    write_html(folder / 'report.html', outcome.after, repair=outcome.to_dict(),
               comparison=json.loads((folder / 'comparison.json').read_text(encoding='utf-8')), manifest=manifest)
    note = '# MotionLint 修复导出\n\n原始文件不被覆盖。repaired_actor*.npy 为米 / Y-up 的 joints22；repaired.npy 保留 LODGE 特征布局。导入 BVH 保留原单位、层级、旋转顺序和未修改通道；新生成 BVH 使用米。重新导入时使用 manifest.export 的 options，帧率以 Frame Time 为准。\n\n先阅读 comparison.json 和各阶段 quality_gate.json；接受候选不代表整体达标。BVH 拟合可能引入额外问题，须阅读 bvh 报告。\n'
    (folder / 'README.md').write_text(note, encoding='utf-8')
    for path in sorted(folder.rglob('*')):
        if path.is_file():
            relative = path.relative_to(folder).as_posix()
            manifest['files'].append({'key': relative.replace('/', '__'), 'path': relative, 'sha256': sha256(path),
                                      'download': path in paths or path in bvh_paths or relative in {'repair_report.json', 'comparison.json'}})
    _write_json(folder / 'manifest.json', manifest)
    with ZipFile(folder / 'bundle.zip', 'w', ZIP_DEFLATED) as bundle:
        for entry in manifest['files']:
            bundle.write(folder / entry['path'], entry['path'])
        bundle.write(folder / 'manifest.json', 'manifest.json')
    # Publishing this pointer is the last operation; interrupted runs stay hidden.
    ready = {'run_id': run_id, 'manifest_sha256': sha256(folder / 'manifest.json'), 'bundle_sha256': sha256(folder / 'bundle.zip')}
    _write_json(folder / 'ready.json', ready)
    _write_json(task_folder / 'motionlint/current_repair.json', ready)
    return folder, manifest
