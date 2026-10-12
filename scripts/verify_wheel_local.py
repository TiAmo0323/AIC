"""Local Windows 3.10/3.11 core and optimize installations outside the repository."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import json

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime',type=Path,required=True)
args=parser.parse_args()
runtime=args.runtime.resolve()
uv=shutil.which('uv') or str(Path.home()/'.local/bin/uv.exe')
outside=runtime/'wheel-verification-050';outside.mkdir(parents=True,exist_ok=True)
env={**os.environ,'UV_CACHE_DIR':str(runtime/'review-tools/uv-cache'),'OPENBLAS_NUM_THREADS':'1',
    'UV_PYTHON_INSTALL_DIR':str(runtime/'review-tools/python'),
    'MOTIONLINT_DATA_DIR':str(outside/'tasks'),'TEMP':str(runtime/'review-tools/temp'),'TMP':str(runtime/'review-tools/temp')}
env.pop('PYTHONPATH',None)
env['PATH']=str(Path(uv).parent)+os.pathsep+env.get('PATH','')
subprocess.run([sys.executable,'-m','build','--installer','uv','--wheel','--outdir',str(ROOT/'reports/iteration_050/dist')],check=True,env=env)
wheel=next((ROOT/'reports/iteration_050/dist').glob('motionlint-0.5.0-*.whl')).resolve()
rows=[]
for version in ('3.10','3.11'):
    for extra in ('core','optimize'):
        folder=outside/f'{version}-{extra}'
        if not folder.exists():subprocess.run([uv,'venv','--python',version,str(folder)],check=True,env=env)
        python=folder/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        spec=str(wheel)+('[optimize]' if extra=='optimize' else '')
        constraints=ROOT/'locks'/('competition.txt' if extra=='optimize' else 'core.txt')
        subprocess.run([uv,'pip','install','--python',str(python),'-c',str(constraints),'--reinstall-package','motionlint',spec],check=True,env=env,cwd=outside)
        script=outside/f'verify-{version}-{extra}.py';shutil.copyfile(ROOT/'scripts/verify_motionlint_installed.py',script)
        result=outside/f'results-{version}-{extra}'
        command=[str(python),str(script),'--wheel',str(wheel),'--source',str(ROOT),'--output',str(result)]
        if extra=='optimize':command.append('--optimize')
        subprocess.run(command,check=True,env=env,cwd=outside)
        rows.append(json.loads((result/'verification.json').read_text(encoding='utf-8')))
output=ROOT/'reports/iteration_050/local-wheel-matrix.json'
output.write_text(json.dumps({'schema_version':3,'rows':rows,'status':'PASS'},indent=2),encoding='utf-8')
