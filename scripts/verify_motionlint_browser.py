"""Drive an actual packaged workbench through the pinned Playwright CLI."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from motionlint.benchmark.fixtures import build
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--url',default='http://127.0.0.1:8004')
parser.add_argument('--output',type=Path,default=ROOT/'reports/iteration_050/browser')
parser.add_argument('--runtime',type=Path)
args=parser.parse_args()
output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
build(output/'inputs')
context={'url':args.url.rstrip('/'),'output':output.as_posix(),
    'clean':(output/'inputs/clean_00.npy').as_posix(),'defect':(output/'inputs/foot_sliding_00.npy').as_posix()}
code=(ROOT/'scripts/browser_verify_motionlint.js').read_text(encoding='utf-8').replace('__CONTEXT__',json.dumps(context,ensure_ascii=False))
codefile=output/'browser-run.js';codefile.write_text(code,encoding='utf-8')
env=dict(os.environ)
if args.runtime:
    cache=args.runtime.resolve()/'review-tools'
    env.update(npm_config_cache=str(cache/'npm-cache'),PLAYWRIGHT_BROWSERS_PATH=str(cache/'playwright-browsers'),
               PWTEST_DAEMON_SESSION_DIR=str(cache/'playwright-daemons'))
npx=shutil.which('npx.cmd' if os.name=='nt' else 'npx')
if not npx:raise RuntimeError('Node/npx is required only for this development browser verification')
prefix=[npx,'--yes','--package','@playwright/cli@0.1.22','playwright-cli','-s=motionlint-verify050']
def execute(arguments,name):
    result=subprocess.run(prefix+arguments,cwd=ROOT,env=env,text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=240)
    log=output/f'{name}.log'
    if log.exists():log.replace(log.with_name(f'{name}.attempt-{time.time_ns()}.log'))
    log.write_text(result.stdout+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError(f'Playwright command failed: {name}; see {output/name}.log')
    return result.stdout
execute(['open',args.url], 'open')
try:
    result=execute(['run-code','--filename',str(codefile)],'verification')
    if '### Error' in result:raise RuntimeError('Browser operation failed; see verification.log')
    payload=result.split('### Result\n',1)[1].split('\n### ',1)[0]
    report=json.loads(payload)
    assert report['status']=='PASS'
    (output/'summary.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print('Actual browser verification:',report['status'],len(report['checks']),'checks')
finally:
    execute(['close'],'close')
