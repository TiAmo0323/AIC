"""Run installed-wheel checks outside the repository without generator modules."""
from __future__ import annotations
import hashlib
import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT.parent/"HumanAction-runtime"


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--python',type=Path,default=RUNTIME/'envs/motionlint-portable310/Scripts/python.exe')
    parser.add_argument('--scratch',type=Path,default=RUNTIME/'portable-validation310')
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports/first_prize/portable')
    args=parser.parse_args()
    scratch=args.scratch.resolve()
    scratch.mkdir(exist_ok=True)
    python=args.python.resolve()
    wheel=ROOT/"output/packages/motionlint-0.4.0-py3-none-any.whl"
    env=dict(os.environ);env.pop("PYTHONPATH",None)
    script='''import importlib.util,json,sys,importlib.metadata
assert importlib.util.find_spec('LODGE_api') is None
assert importlib.util.find_spec('InterGen_api') is None
import motionlint
print(json.dumps({'python':sys.version,'installed_module':motionlint.__file__,'generator_modules_absent':True,'packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions() if d.metadata.get('Name')}}))
'''
    info=subprocess.run([str(python),"-c",script],cwd=scratch,env=env,capture_output=True,text=True,check=True)
    payload=json.loads(info.stdout)
    payload["wheel_sha256"]=hashlib.sha256(wheel.read_bytes()).hexdigest()
    shutil.copyfile(ROOT/"tests/test_motionlint_portable.py",scratch/"test_motionlint_portable.py")
    tests=subprocess.run([str(python),"-m","pytest","test_motionlint_portable.py","-q","--tb=short","--basetemp",str(scratch/"pytest-current")],cwd=scratch,env=env,capture_output=True,text=True)
    payload["test_returncode"]=tests.returncode;payload["test_output"]=tests.stdout+tests.stderr
    demo=subprocess.run([str(python),"-m","motionlint.benchmark.fixtures","demo"],cwd=scratch,env=env,capture_output=True,text=True,check=True)
    commands=[["check","demo/clean_00.npy","--output-dir","reports/clean"],
              ["check","demo/foot_sliding_00.npy","--output-dir","reports/slide"],
              ["repair","demo/foot_sliding_00.npy","--output-dir","reports/repair"],
              ["compare","demo/clean_00.npy","demo/foot_sliding_00.npy","--output-dir","reports/regression"]]
    payload["commands"]=[]
    for cli_args in commands:
        result=subprocess.run([str(python),"-m","motionlint",*cli_args],cwd=scratch,env=env,capture_output=True,text=True)
        payload["commands"].append({"args":cli_args,"exit_code":result.returncode,"stdout":result.stdout,"stderr":result.stderr})
    payload["scope"]="Developer clean Windows environment outside checkout; not an independent human installation or Linux validation"
    out=args.report_dir
    out.mkdir(parents=True,exist_ok=True)
    (out/"verification.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print(tests.stdout)
    print([(r["args"][0],r["exit_code"]) for r in payload["commands"]])
    if tests.returncode or [r["exit_code"] for r in payload["commands"]] != [0,1,1,1]:
        raise SystemExit("Installed wheel contract failed; inspect verification.json")

if __name__=="__main__":main()
