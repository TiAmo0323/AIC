"""Standalone, standard-library recorder for a real installation run."""
import argparse
from datetime import datetime, timezone
import hashlib
from html import escape
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from uuid import uuid4


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--participant', required=True, help='Use a code, not a real name')
    parser.add_argument('--output', type=Path, default=Path('installation-records'))
    parser.add_argument('--wheel', type=Path)
    parser.add_argument('--input', type=Path, help='Optional new NPY/BVH for participant B')
    parser.add_argument('--actor2', type=Path)
    parser.add_argument('--fps', type=float, default=30)
    parser.add_argument('--unit-scale', type=float, default=1)
    parser.add_argument('--up-axis', type=int, choices=(0, 1, 2), default=1)
    parser.add_argument('--joint-map', type=Path)
    args = parser.parse_args()
    run = args.output.resolve() / ('run-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    run.mkdir(parents=True)
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env['PYTHONIOENCODING'] = 'utf-8'
    rows = []

    def execute(name, argv, expected):
        command = [sys.executable, *argv]
        started = time.perf_counter()
        try:
            result = subprocess.run(command, cwd=run, env=env, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=180)
            row = {'name': name, 'command': command, 'exit_code': result.returncode,
                   'stdout': result.stdout, 'stderr': result.stderr}
        except (OSError, subprocess.TimeoutExpired) as exc:
            row = {'name': name, 'command': command, 'exit_code': None, 'stdout': '', 'stderr': str(exc)}
        row.update(expected_exit_codes=expected, elapsed_seconds=round(time.perf_counter() - started, 3),
                   contract_passed=row['exit_code'] in expected)
        rows.append(row)
        print(f"{name}: exit={row['exit_code']}, expected={expected}", flush=True)
        return row

    module = execute('installed_environment', ['-c',
        "import importlib.metadata as m,importlib.util as u,json,sys,motionlint; "
        "print(json.dumps({'python':sys.version,'module':motionlint.__file__,'version':m.version('motionlint'),"
        "'generator_modules_absent':all(u.find_spec(n) is None for n in ('LODGE_api','InterGen_api'))}))"], [0])
    if module['exit_code'] == 0:
        execute('create_self_authored_examples', ['-m', 'motionlint.benchmark.fixtures', 'demo'], [0])
        if rows[-1]['exit_code'] == 0:
            inputs = {str(p.relative_to(run)): sha(p) for p in (run / 'demo').glob('*.npy')}
            execute('clean_pass', ['-m', 'motionlint', 'check', 'demo/clean_00.npy', '--output-dir', 'reports/clean'], [0])
            execute('quality_failure', ['-m', 'motionlint', 'check', 'demo/foot_sliding_00.npy', '--output-dir', 'reports/slide'], [1])
            execute('bounded_repair', ['-m', 'motionlint', 'repair', 'demo/foot_sliding_00.npy', '--output-dir', 'reports/repair'], [1])
            execute('regression_failure', ['-m', 'motionlint', 'compare', 'demo/clean_00.npy', 'demo/foot_sliding_00.npy', '--output-dir', 'reports/regression'], [1])
            execute('input_error', ['-m', 'motionlint', 'check', 'demo/does_not_exist.npy'], [2])
            unchanged = all((run / name).is_file() and sha(run / name) == digest for name, digest in inputs.items())
        else:
            inputs, unchanged = {}, False
    else:
        inputs, unchanged = {}, False
    if args.input:
        argv = ['-m', 'motionlint', 'check', str(args.input.resolve()), '--output-dir', 'reports/own-input',
                '--fps', str(args.fps), '--unit-scale', str(args.unit_scale), '--up-axis', str(args.up_axis)]
        if args.actor2:
            argv += ['--actor2', str(args.actor2.resolve())]
        if args.joint_map:
            argv += ['--joint-map', str(args.joint_map.resolve())]
        own = execute('own_new_input', argv, [0, 1])
        own['input_sha256'] = sha(args.input) if args.input.is_file() else None
    info = json.loads(module['stdout']) if module['exit_code'] == 0 else None
    record = {'schema_version': 1, 'status': 'verified' if all(r['contract_passed'] for r in rows) and unchanged else 'failed',
        'participant_code': args.participant, 'operating_system': platform.platform(),
        'python_version': platform.python_version(), 'environment': info,
        'wheel_sha256': sha(args.wheel) if args.wheel and args.wheel.is_file() else None,
        'execution_utc': datetime.now(timezone.utc).isoformat(), 'commands': rows,
        'original_inputs_unchanged': unchanged, 'input_sha256': inputs,
        'scope': 'Actual machine execution; independence and user experience require participant/reviewer confirmation',
        'human_feedback': {'completion_status': 'pending', 'developer_assistance': None, 'errors': [], 'notes': ''}}
    (run / 'installation.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    cards = ''.join('<section><h2>' + escape(r['name']) + '</h2><p>实际退出码 ' + str(r['exit_code']) +
                    '</p><pre>' + escape('$ ' + subprocess.list2cmdline(r['command']) + '\n\n' + r['stdout'] + r['stderr']) + '</pre></section>' for r in rows)
    html = '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>MotionLint 真实命令记录</title><link rel="icon" href="data:,">'
    html += '<style>body{margin:24px;font:18px system-ui;background:#101828;color:#e4eaf3}section{padding:20px;background:#1d2939;border-radius:12px;margin:16px 0}pre{white-space:pre-wrap;word-break:break-word;font:16px Consolas,monospace}h1{font-size:28px}button{padding:12px;font-size:18px}</style>'
    html += '<h1>MotionLint · 真实命令输出回放</h1><p>这些命令已实际执行。录屏展示输出记录；这不是实时终端，也不是外部同学复现证据。</p><p>0：通过；1：质量失败或回归；2：输入或运行错误。有限修复仍可能不达标。</p>' + cards + '</html>'
    (run / 'transcript.html').write_text(html, encoding='utf-8')
    print(str(run / 'installation.json'))
    return 0 if record['status'] == 'verified' else 2


if __name__ == '__main__':
    raise SystemExit(main())
