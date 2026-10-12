"""Build once, install minimal and optimized wheels in external fresh venvs."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
build = ROOT / 'reports/ci-build'
subprocess.run([sys.executable,'-m','build','--wheel','--outdir',str(build)], cwd=ROOT,check=True)
wheel = next(build.glob('motionlint-0.5.0-*.whl')).resolve()
outside = Path(tempfile.mkdtemp(prefix='motionlint-wheel-050-'))
env = dict(os.environ); env.pop('PYTHONPATH',None)
env.update(MOTIONLINT_DATA_DIR=str(outside/'tasks'), OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='2')
for name,extra in (('core',''),('optimize','[optimize]')):
    folder = outside/name
    subprocess.run([sys.executable,'-m','venv',str(folder)],check=True)
    python=folder/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    constraints=ROOT/'locks'/('competition.txt' if extra else 'core.txt')
    subprocess.run([str(python),'-m','pip','install','-c',str(constraints),str(wheel)+extra],cwd=outside,env=env,check=True)
    script=outside/f'verify-{name}.py'
    shutil.copyfile(ROOT/'scripts/verify_motionlint_installed.py',script)
    command=[str(python),str(script),'--wheel',str(wheel),'--source',str(ROOT),'--output',str(outside/f'results-{name}')]
    if extra:command.append('--optimize')
    subprocess.run(command,cwd=outside,env=env,check=True)
    destination=ROOT/f'reports/ci-wheel-{name}'
    destination.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(outside/f'results-{name}/verification.json',destination/'verification.json')
print('Matrix wheel installations verified outside',ROOT)
