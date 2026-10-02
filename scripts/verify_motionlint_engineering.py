"""Capture actual engineering checks; human and Linux evidence stay pending."""
import json
import re
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def main():
    commands=[('python_motionlint_tests',[sys.executable,'-m','pytest',*[str(p) for p in sorted((ROOT/'tests').glob('test_motionlint*.py'))],'-q','--tb=short','--basetemp',str(ROOT/'reports/pytest-engineering-recorded')],ROOT),
              ('timeline_actor_separation',['node','tests/test_motionlint_view.mjs'],ROOT),
              ('vue_production_build',['npm.cmd','run','build'],ROOT/'project')]
    rows=[]
    for name, command, cwd in commands:
        result=subprocess.run(command,cwd=cwd,capture_output=True,text=True,encoding='utf-8',errors='replace')
        rows.append({'name':name,'command':command,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
        print(f'{name}: {result.returncode}',flush=True)
    output=ROOT/'reports/first_prize/engineering_verification.json'
    output.write_text(json.dumps({'status':'verified' if all(r['returncode']==0 for r in rows) else 'failed',
        'python_test_count':int(re.search(r'(\d+) passed',rows[0]['stdout']).group(1)) if ' passed' in rows[0]['stdout'] else None,
        'checks':rows,'linux':'not_verified; local Docker unavailable and user requested skip',
        'human_validation':'pending','remote_actions':'configured_not_run'},ensure_ascii=False,indent=2),encoding='utf-8')
    if any(r['returncode'] for r in rows):raise SystemExit(1)


if __name__=='__main__':main()
