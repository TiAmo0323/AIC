"""Optional repository integration: immutable Kenney exports and scene rechecks."""
from pathlib import Path
from uuid import uuid4, UUID
import json
import os
import re
import shutil
import struct
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED

import numpy as np

from motionlint.artifacts import current_run, read_motion, save_motion, sha256
from motionlint.adapters.character_adapter import load_character
from motionlint.cli.main import _write_json, _write_report
from motionlint.core.skeleton import BVH_NAMES
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect


def resources(repo, runtime):
    blender = Path(os.getenv('MOTIONLINT_BLENDER_EXE') or os.getenv('INTERGEN_BLENDER_EXE') or runtime / 'blender-4.2.23-windows-x64/blender.exe')
    model = Path(os.getenv('MOTIONLINT_KENNEY_FBX') or runtime / 'assets/kenney/protagonists/Model/characterMedium.fbx')
    scripts = Path(os.getenv('BLENDER_USER_SCRIPTS') or runtime / 'blender-scripts')
    ffmpeg = os.getenv('LODGE_FFMPEG_EXE') or shutil.which('ffmpeg')
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            ffmpeg = None
    checks = {'Blender': blender.is_file(), 'Kenney CC0 FBX': model.is_file(),
              'Rokoko addon': (scripts / 'addons/rokoko_studio_live_blender/__init__.py').is_file(),
              'FFmpeg': bool(ffmpeg and Path(ffmpeg).is_file()),
              'repository integration': (repo / 'LODGE_api/blender_rokoko_retarget.py').is_file() and (repo / 'scripts/export_blender_motionlint.py').is_file()}
    return {'available': all(checks.values()), 'checks': checks, 'blender': str(blender), 'model': str(model),
            'scripts': str(scripts), 'ffmpeg': str(ffmpeg) if ffmpeg else None}


def _verify_mp4_boxes(path):
    # Decoders can recover frames even from an incomplete trailing moov atom.
    # Check declared container lengths as well as decoded content.
    size, seen = Path(path).stat().st_size, set()
    with Path(path).open('rb') as handle:
        while handle.tell() < size:
            start = handle.tell()
            header = handle.read(8)
            if len(header) != 8:
                raise ValueError('MP4 容器尾部被截断')
            length, kind = struct.unpack('>I4s', header)
            minimum = 8
            if length == 1:
                extra = handle.read(8)
                if len(extra) != 8:
                    raise ValueError('MP4 扩展头被截断')
                length, minimum = struct.unpack('>Q', extra)[0], 16
            if length == 0:
                length = size - start
            if length < minimum or start + length > size:
                raise ValueError('MP4 容器声明的内容未完整写出')
            seen.add(kind)
            handle.seek(start + length)
    if not {b'ftyp', b'moov', b'mdat'} <= seen:
        raise ValueError('MP4 缺少必要的容器数据')


def verify_video(path, ffmpeg, *, frames, fps):
    """Decode every frame and check stream FPS/duration; reject truncated output."""
    _verify_mp4_boxes(path)
    probe = subprocess.run([ffmpeg, '-hide_banner', '-i', str(path)], capture_output=True, text=True, errors='replace', timeout=60)
    match = re.search(r'(\d+(?:\.\d+)?) fps', probe.stderr)
    duration = re.search(r'Duration: (\d+):(\d+):(\d+(?:\.\d+)?)', probe.stderr)
    if not match or not duration:
        raise ValueError('无法读取视频帧率或时长')
    actual_fps = float(match.group(1))
    seconds = int(duration.group(1)) * 3600 + int(duration.group(2)) * 60 + float(duration.group(3))
    command = [ffmpeg, '-v', 'error', '-xerror', '-err_detect', 'explode', '-i', str(path), '-map', '0:v:0',
               '-vsync', '0', '-progress', 'pipe:1', '-nostats', '-f', 'null', '-']
    decoded = subprocess.run(command, capture_output=True, text=True, errors='replace', timeout=3600)
    counts = re.findall(r'^frame=(\d+)\s*$', decoded.stdout, re.MULTILINE)
    count = int(counts[-1]) if counts else 0
    if decoded.returncode or decoded.stderr.strip() or count != frames or abs(actual_fps - fps) > .011 or abs(seconds - frames / fps) > .025:
        raise ValueError(f'视频校验失败：解码 {count}/{frames} 帧，{actual_fps}/{fps} FPS，时长 {seconds:.3f}/{frames / fps:.3f} 秒；{decoded.stderr[-300:]}')
    return {'fully_decoded': True, 'frames': count, 'fps': actual_fps, 'duration_seconds': seconds, 'sha256': sha256(path)}


def export_character(task, repo, runtime, export_id, source_run_id):
    folder = task / 'motionlint/character_exports' / export_id
    folder.mkdir(parents=True, exist_ok=True)
    status = folder / 'status.json'
    state = {'export_id': export_id, 'source_run_id': source_run_id, 'status': 'running'}
    _write_json(status, state)
    try:
        run, source = current_run(task, source_run_id)
        config = resources(repo, runtime)
        if not config['available']:
            raise ValueError('角色导出资源缺失：' + ', '.join(name for name, exists in config['checks'].items() if not exists))
        if 'bvh' not in source['stages']:
            raise ValueError('请先完成 BVH 导出')
        bvh = read_motion(run / 'bvh_motion.npz')
        required = set(BVH_NAMES) - {'Spine2'}
        if bvh.metadata.get('up_axis', 1) != 1 or not required <= set(bvh.joint_names):
            raise ValueError('Kenney 重定向需要 Y-up、根节点、双腿足部和上肢映射；Spine2 可选')
        paths = []
        for entry in source['files']:
            if entry['download'] and entry['path'].endswith('.bvh'):
                output = folder / entry['path']
                shutil.copyfile(run / entry['path'], output)
                paths.append(output)
        policy = folder / 'quality.yaml'
        shutil.copyfile(run / 'quality.yaml', policy)
        mapping = folder / 'kenney_mapping.json'
        aliases = {'Spine1': 'Chest', 'Spine2': 'UpperChest', 'LeftToe': 'LeftToes', 'RightToe': 'RightToes'}
        inverse = {canonical: stored for stored, canonical in bvh.metadata.get('joint_mapping', {}).items()}
        canonical_names = [name for name in BVH_NAMES if name in bvh.joint_names]
        _write_json(mapping, {'bones': [{'SourceBoneName': inverse.get(name, name), 'CanonicalName': name,
            'DestinationBoneName': aliases.get(name, name)} for name in canonical_names]})
        render_paths = paths
        if bvh.metadata.get('unit_scale_to_metres', 1.) != 1.:
            from motionlint.bvh_preserve import write_preserving_bvh
            from dataclasses import replace
            scale = bvh.metadata['unit_scale_to_metres']
            headers = [re.sub(r'(OFFSET\s+)([^\n]+)', lambda m: m.group(1) + ' '.join(
                f'{float(v)*scale:.15g}' for v in m.group(2).split()), header)
                for header in bvh.metadata.get('actor_bvh_headers', [bvh.metadata['bvh_hierarchy_text']])]
            values = bvh.channel_values.copy()
            cursor = 0
            for labels in bvh.metadata['bvh_channel_labels']:
                if len(labels) == 6:
                    values[:, :, cursor:cursor+3] *= scale
                cursor += len(labels)
            metres = replace(bvh, channel_values=values, metadata={**bvh.metadata,
                'unit_scale_to_metres': 1., 'actor_bvh_headers': headers, 'bvh_hierarchy_text': headers[0]})
            render_paths = [write_preserving_bvh(folder / f'render_metres_actor{a+1}.bvh', metres, a) for a in range(bvh.actor_count)]
        render_transform = {'method': 'direct_metre_bvh', 'source_stage': 'accepted_bvh', 'source_unchanged': True}
        if bvh.metadata.get('non_anatomical_bone_ids') or 'Spine2' not in bvh.joint_names:
            # Rokoko's rest-height scale is undefined for some external binds
            # (e.g. horizontal rest spines). Refit a documented canonical proxy
            # from actual world joints; retain and check the original BVH.
            from motionlint.joints_to_bvh import convert_continuous_joints
            from motionlint.adapters.intergen_adapter import JOINT_NAMES
            from motionlint.adapters.bvh_adapter import load_bvh
            index = {name: i for i, name in enumerate(bvh.joint_names)}
            render_paths, errors = [], []
            for actor in range(bvh.actor_count):
                joints = np.zeros((bvh.frame_count, 22, 3))
                for j, name in enumerate(JOINT_NAMES):
                    joints[:, j] = bvh.positions[:, actor, index[name]] if name in index else (
                        bvh.positions[:, actor, index['Spine1']] + bvh.positions[:, actor, index['Neck']]) / 2
                snapshot = folder / f'retarget_proxy_actor{actor+1}.npy'
                np.save(snapshot, joints, allow_pickle=False)
                path = folder / f'retarget_proxy_actor{actor+1}.bvh'
                convert_continuous_joints(snapshot, path, fps=bvh.fps)
                proxy = load_bvh(path)
                common = [name for name in BVH_NAMES if name in index]
                differences = np.linalg.norm(proxy.positions[:, 0, [proxy.joint_names.index(n) for n in common]] -
                    bvh.positions[:, actor, [index[n] for n in common]], axis=-1)
                errors.append({'actor_id': actor, 'common_joints': common, 'mean_error_m': float(differences.mean()),
                               'max_error_m': float(differences.max()), 'p95_error_m': float(np.percentile(differences, 95))})
                render_paths.append(path)
            _write_json(mapping, {'bones': [{'SourceBoneName': name, 'CanonicalName': name,
                'DestinationBoneName': aliases.get(name, name)} for name in BVH_NAMES]})
            render_transform = {'method': 'continuous_canonical_world_joint_fit', 'source_stage': 'accepted_bvh',
                'source_unchanged': True, 'virtual_joint': 'Spine2 halfway between Spine1 and Neck when absent',
                'reason': 'External helper root or noncanonical rest bind; avoid rest-height retarget scaling distortion',
                'measured_geometry_changes': errors}
        _write_json(folder / 'render_transform.json', render_transform)
        video = folder / 'kenney.mp4'
        manifest_path = folder / 'retarget_manifest.json'
        manifest = {'source_bvh_files': [str(p) for p in render_paths], 'target_fbx': config['model'], 'mapping_file': str(mapping),
                    'output_mp4': str(video), 'debug_blend': str(folder / 'kenney.blend'), 'report_path': str(folder / 'retarget_report.json'),
                    'fps': bvh.fps, 'max_render_frames': 0, 'render_size': '384x384', 'render_engine': 'BLENDER_EEVEE_NEXT',
                    'resolution_percentage': 100, 'motionlint_input_stage': 'repaired_bvh', 'person_skin_ids': ['kenney_cc0'] * bvh.actor_count,
                    'target_spacing': 0, 'foot_lock_enabled': False, 'hand_torso_collision_enabled': False,
                    'head_world_stabilization_enabled': False, 'nailong_profile_enabled': False,
                    'core_smoothing_window': 0, 'spine_smoothing_window': 0, 'chest_smoothing_window': 0,
                    'neck_smoothing_window': 0, 'head_smoothing_window': 0,
                    'core_max_rotation_degrees_per_frame': 360, 'spine_max_rotation_degrees_per_frame': 360,
                    'core_max_acceleration_degrees_per_frame2': 720, 'spine_max_acceleration_degrees_per_frame2': 720,
                    'chest_max_rotation_degrees_per_frame': 360, 'neck_max_rotation_degrees_per_frame': 360,
                    'head_max_rotation_degrees_per_frame': 360, 'chest_max_acceleration_degrees_per_frame2': 720,
                    'neck_max_acceleration_degrees_per_frame2': 720, 'head_max_acceleration_degrees_per_frame2': 720}
        _write_json(manifest_path, manifest)
        env = {**os.environ, 'BLENDER_USER_SCRIPTS': config['scripts']}
        commands = [[config['blender'], '-b', '--factory-startup', '--python', str(repo / 'LODGE_api/blender_rokoko_retarget.py'),
                     '--', '--manifest', str(manifest_path)],
                    [config['blender'], '-b', manifest['debug_blend'], '--python', str(repo / 'scripts/export_blender_motionlint.py'),
                     '--', '--manifest', str(manifest_path), '--output', str(folder / 'character.npz')]]
        for index, command in enumerate(commands):
            with (folder / f'blender-{index + 1}.log').open('w', encoding='utf-8') as log:
                subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=3600 if index == 0 else 180)
        checked_video = verify_video(video, config['ffmpeg'], frames=bvh.frame_count, fps=bvh.fps)
        motion = load_character(folder / 'character.npz')
        if motion.frame_count != bvh.frame_count or motion.actor_count != bvh.actor_count or not np.isclose(motion.fps, bvh.fps):
            raise ValueError('角色骨架帧数、人物数量或帧率不匹配')
        motion.metadata.update(stage='character', repair_run_id=source['run_id'])
        from motionlint.character_mesh import measure_mesh
        _write_json(folder / 'character/mesh_metrics.json', measure_mesh(folder / 'character.npz', motion.fps))
        save_motion(folder / 'character_motion.npz', motion)
        report = inspect(motion, config_path=policy)
        report.metadata['inspection_stage'] = 'character'
        gate = evaluate_gate(report, config_path=policy)
        _write_report(folder / 'character', report)
        _write_json(folder / 'character/quality_gate.json', gate.to_dict())
        files = ['character.npz', 'character.json', 'character_motion.npz', 'kenney.mp4', 'quality.yaml',
                 'kenney_mapping.json', 'retarget_manifest.json', 'retarget_report.json',
                 'character/motionlint_report.json', 'character/issues.json', 'character/metrics.csv', 'character/quality_gate.json',
                 'character/mesh_metrics.json', 'character/report.html'] + list(dict.fromkeys(p.name for p in paths + render_paths))
        files.append('render_transform.json')
        state.update(status='ready', gate=gate.to_dict(), video=checked_video, frame_count=motion.frame_count, fps=motion.fps,
                     files=[{'path': p, 'sha256': sha256(folder / p)} for p in files],
                     blend_sha256=sha256(folder / 'kenney.blend'), resources_sha256={'fbx': sha256(config['model'])})
        _write_json(folder / 'export_manifest.json', state)
        with ZipFile(folder / 'bundle.zip', 'w', ZIP_DEFLATED) as bundle:
            for path in files:
                bundle.write(folder / path, path)
            bundle.write(folder / 'export_manifest.json', 'export_status.json')
        state['bundle_sha256'] = sha256(folder / 'bundle.zip')
        _write_json(task / 'motionlint/current_character.json', {'export_id': export_id, 'source_run_id': source['run_id']})
        _write_json(status, state)
    except Exception as exc:
        _write_json(status, {**state, 'status': 'failed', 'error': str(exc)})


def checked_character(task, export_id=None):
    if export_id is None:
        pointer = json.loads((task / 'motionlint/current_character.json').read_text(encoding='utf-8'))
        _, current = current_run(task)
        if pointer['source_run_id'] != current['run_id']:
            raise ValueError('角色对应旧的修复结果，请重新导出')
        export_id = pointer['export_id']
    if str(UUID(export_id)) != export_id:
        raise ValueError('角色导出编号无效')
    folder = task / 'motionlint/character_exports' / export_id
    state = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
    current_run(task, state['source_run_id'])
    if state['status'] != 'ready':
        raise FileNotFoundError('角色导出尚未通过产物校验')
    for entry in state['files']:
        path = (folder / entry['path']).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file() or sha256(path) != entry['sha256']:
            raise ValueError('角色产物已变化，请重新导出')
    if sha256(folder / 'kenney.blend') != state['blend_sha256']:
        raise ValueError('角色场景已变化，请重新导出')
    return folder, state
