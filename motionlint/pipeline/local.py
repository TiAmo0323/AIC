"""Standalone import -> inspect -> bounded repair -> actual export recheck."""
from pathlib import Path
import json
import shutil
from uuid import uuid4
from motionlint.jobs import Job, Cancelled
from motionlint.import_io import finish_import, load_imported_motion, MAX_IMPORT_BYTES
from motionlint.pipeline.repair_pipeline import repair
from motionlint.artifacts import persist_repair, sha256


def run_pipeline(input_paths, *, output=None, fps=30., unit_scale=1., up_axis=1,
                 joint_mapping=None, config_path=None, character=False, runtime=None, repo=None, job=None):
    job = job or Job()
    destination = Path(output or job.folder / 'task').resolve()
    # Every invocation has its own immutable task; retries cannot replace output.
    if destination.exists():
        destination = destination / str(uuid4())
    destination.mkdir(parents=True)
    inputs = [Path(p).resolve() for p in input_paths]
    hashes = {str(p): sha256(p) for p in inputs}
    try:
        job.checkpoint('import')
        if any(p.stat().st_size > MAX_IMPORT_BYTES for p in inputs):
            raise ValueError('Import exceeds the 32 MiB per-file limit')
        files = []
        for actor, path in enumerate(inputs, 1):
            name = f'actor{actor}{path.suffix.lower()}'
            shutil.copyfile(path, destination / name)
            files.append({'name': path.name, 'path': name})
        imported = finish_import(destination, files, {'fps': fps, 'unit_scale': unit_scale, 'up_axis': up_axis,
                    'joint_mapping': joint_mapping or {}})
        job.update(stage='imported', task_dir=str(destination), import_result=imported)
        job.checkpoint('repair')
        motion = load_imported_motion(destination)
        outcome = repair(motion, config_path=config_path)
        job.checkpoint('export_recheck')
        run, manifest = persist_repair(destination, outcome, motion, [destination / f['path'] for f in files], config_path=config_path)
        if any(sha256(p) != hashes[str(p)] for p in inputs):
            raise ValueError('Original source input changed during pipeline execution')
        result = {'schema_version': 3, 'task_dir': str(destination), 'run_dir': str(run), 'run_id': manifest['run_id'],
                  'job_id': job.id, 'stages': manifest['stages'], 'warnings': manifest['warnings'],
                  'input_hashes': hashes, 'input_hashes_unchanged': True, 'repair_status': outcome.to_dict()['status'],
                  'comparison': json.loads((run / 'comparison.json').read_text(encoding='utf-8'))}
        if character:
            job.checkpoint('character')
            from motionlint.character_export import export_character, checked_character
            if runtime is None or repo is None:
                raise ValueError('Character rendering requires explicit --runtime and --repo resources')
            export_id = str(uuid4())
            export_character(destination, Path(repo), Path(runtime), export_id, manifest['run_id'])
            folder, state = checked_character(destination, export_id)
            result['character'] = state
            result['character_dir'] = str(folder)
        job.checkpoint('complete')
        result['quality_status'] = 'PASS' if all(stage['gate']['status'] == 'PASS' for stage in manifest['stages'].values()) and (
            not character or result['character']['gate']['status'] == 'PASS') else 'FAIL'
        job.update('ready', result=result, stage='complete')
        return result
    except Cancelled:
        raise
    except Exception as exc:
        job.update('failed', error=f'{type(exc).__name__}: {exc}', task_dir=str(destination))
        raise
