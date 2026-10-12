"""Prepare actual inputs, installed CLI output and a verified artifact replay.

Replayed export files are exact copies of a predeclared benchmark sample; this
does not produce an additional evaluation sample or a new quality result.
"""
import argparse
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from motionlint.artifacts import current_run, read_motion, sha256
from motionlint.benchmark.fixtures import build
from motionlint.character_export import checked_character
from motionlint.jobs import Job


def prepare(runtime, data_dir, output):
    output.mkdir(parents=True, exist_ok=False)
    build(output / 'inputs')
    for name in ('baseline', 'candidate'):
        motion = read_motion(ROOT / 'reports/iteration_050/safety-2/new_location_0' / (name + '.npz'))
        if motion.actor_count != 1:
            raise ValueError('The recorded counterexample must have one actor')
        import numpy as np
        np.save(output / 'inputs' / ('regression_' + name + '.npy'), motion.positions[:, 0])
    summary = json.loads((ROOT / 'reports/iteration_050/complete-flows-v3/summary.json').read_text(encoding='utf-8'))
    original = next(row for row in summary['rows'] if row['id'] == 'bandai_bow_normal')['flow']
    task = data_dir / 'imports' / str(uuid4())
    shutil.copytree(original['task_dir'], task)
    imported = json.loads((task / 'import.json').read_text(encoding='utf-8'))
    imported['task_id'] = task.name
    imported['title'] = 'Bandai bow · 本轮已验证产物复用'
    (task / 'import.json').write_text(json.dumps(imported, ensure_ascii=False, indent=2), encoding='utf-8')
    pointer = json.loads((task / 'motionlint/current_character.json').read_text(encoding='utf-8'))
    (task / 'motionlint/character_request.json').write_text(json.dumps(pointer), encoding='utf-8')
    current_run(task)
    folder, state = checked_character(task)
    job = Job(data_dir, kind='validated_artifact_replay')
    job.update('ready', stage='verified_artifact_replay', result={**original, 'task_dir': str(task)},
               evidence_reuse=True, sample_id='bandai_bow_normal')
    python = runtime / 'wheel-verification-050/3.11-optimize/Scripts/python.exe'
    if not python.is_file():
        raise ValueError('Verify the outside-repository installed wheel before recording the CLI')
    commands = [
        ['check', 'inputs/clean_00.npy', '--output-dir', 'cli-clean'],
        ['repair', 'inputs/foot_sliding_00.npy', '--output-dir', 'cli-repair'],
        ['compare', 'inputs/regression_baseline.npy', 'inputs/regression_candidate.npy', '--output-dir', 'cli-regression']]
    rows = []
    env = {**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '2'}
    env.pop('PYTHONPATH', None)
    for i, command in enumerate(commands):
        result = subprocess.run([str(python), '-m', 'motionlint', *command], cwd=output, env=env,
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120)
        stdout = re.sub(r'[A-Za-z]:[\\/][^\s"<>]+', '<local path>', result.stdout + result.stderr)
        rows.append({'command': 'motionlint ' + ' '.join(command), 'exit_code': result.returncode, 'output': stdout})
    assert [row['exit_code'] for row in rows] == [0, 0, 1], rows
    regression = json.loads((output / 'cli-regression/comparison.json').read_text(encoding='utf-8'))
    assert regression['status'] == 'REGRESSION DETECTED', regression
    sections = ''.join('<section><pre>$ ' + html.escape(row['command']) + '\n' + html.escape(row['output']) +
                       '\nexit = ' + str(row['exit_code']) + '</pre></section>' for row in rows)
    (output / 'cli.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>MotionLint 实际 CLI 输出</title>'
        '<style>body{background:#111d2e;color:#deebf5;font:19px/1.65 monospace;padding:38px}h1{font-size:28px;color:#88d8c0}'
        'section{border:1px solid #45607b;padding:16px;margin:18px 0;border-radius:12px}pre{white-space:pre-wrap}</style>'
        '<h1>MotionLint 0.5.0 · 仓库外安装包的实际命令输出</h1><p>退出码：0 通过，1 质量失败或回归，2 输入或运行错误。</p>' + sections,
        encoding='utf-8')
    receipt = {'schema_version': 3, 'scope': 'Actual operations; artifact replay is not a new evaluation sample',
        'output': str(output), 'clean': str(output / 'inputs/clean_00.npy'), 'defect': str(output / 'inputs/foot_sliding_00.npy'),
        'regression_baseline': str(output / 'inputs/regression_baseline.npy'),
        'regression_candidate': str(output / 'inputs/regression_candidate.npy'), 'cli': rows,
        'character_job_id': job.id, 'character_task_id': task.name, 'character_input_id': 'bandai_bow_normal',
        'actual_character_video_sha256': sha256(folder / 'kenney.mp4'),
        'actual_character_video': state['video'], 'wheel_sha256': json.loads((runtime / 'wheel-verification-050/results-3.11-optimize/verification.json').read_text())['wheel_sha256']}
    (output / 'recording-inputs.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf-8')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = (args.output or ROOT / 'output/video' / ('recording-050-' + str(time.time_ns()))).resolve()
    receipt = prepare(args.runtime.resolve(), args.data_dir.resolve(), output)
    print(receipt['output'])
