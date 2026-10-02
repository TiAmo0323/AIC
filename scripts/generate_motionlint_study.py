"""Resume serial real generation; never invoke MotionLint on held-out inputs."""
from __future__ import annotations
import hashlib
import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"reports/first_prize/study"
RUNTIME=ROOT.parent/"HumanAction-runtime"


def request(url,payload=None):
    req=urllib.request.Request(url,data=json.dumps(payload).encode() if payload is not None else None,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=180) as response:return json.load(response)


def save(state):
    path=OUT/"generation.json"
    temporary=path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding="utf-8")
    temporary.replace(path)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--retry-failed",action="store_true")
    args=parser.parse_args()
    protocol_path=OUT/"protocol.json"
    digest=hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    if digest!=(OUT/"protocol.sha256").read_text().strip():raise ValueError("Frozen protocol changed")
    protocol=json.loads(protocol_path.read_text(encoding="utf-8"))
    audio={r["id"]:r for r in json.loads((OUT/"music/manifest.json").read_text(encoding="utf-8"))}
    state_path=OUT/"generation.json"
    state=json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"protocol_sha256":digest,"samples":[],"status":"generating"}
    if state["protocol_sha256"]!=digest:raise ValueError("Protocol differs from generation run")
    rows={r["id"]:r for r in state["samples"]}
    for entry in protocol["motions"]:
        sample=rows.get(entry["id"])
        if sample is None:
            sample={**entry,"attempts":[]}
            state["samples"].append(sample)
        if sample.get("status")=="succeeded":continue
        if sample.get("status")=="failed":
            if not args.retry_failed:continue
            sample.setdefault("failed_attempts",[]).append({"task_id":sample.get("task_id"),"result":sample.get("task_result"),"error":sample.get("error")})
            sample.pop("task_id",None)
            sample.pop("error",None)
            sample["status"]="retry_pending"
        base=f"http://127.0.0.1:{8001 if entry['source']=='intergen' else 8002}/v1/{entry['source']}/tasks"
        if not sample.get("task_id"):
            if entry["source"]=="intergen":
                payload={"text":entry["prompt"],"seed":entry["seed"],"num_samples":1,"motion_frames":180,"skin_id":"smpl",
                         "planner_enabled":False,"experiment_group":"motionlint-new-study","experiment_variant":"annotation-first"}
                endpoint="generate"
            else:
                payload={"lodge_root":str(RUNTIME/"LODGE-main"),"audio_path":audio[entry["id"]]["input_audio"],
                         "song_id":"ml261002"+entry["id"],"python_executable":str(RUNTIME/"envs/lodge/Scripts/python.exe"),
                         "mode":"smplx","fps":30,"skin_id":"smpl"}
                endpoint="infer-from-audio"
            try:
                response=request(base+"/"+endpoint,payload)
                sample["task_id"]=response["task_id"]
                sample["attempts"].append({"request":payload,"task_id":sample["task_id"],"submitted_utc":time.time()})
                if entry["source"]=="lodge":
                    sample["attempts"][-1]["inference_code_sha256"]=hashlib.sha256((RUNTIME/"LODGE-main/infer_lodge.py").read_bytes()).hexdigest()
                save(state)
            except Exception as exc:
                sample["status"]="failed";sample["error"]=str(exc);save(state);continue
        print(f"Generating {entry['id']} {sample['task_id']}",flush=True)
        deadline=time.monotonic()+1800
        while True:
            response=request(base+"/"+sample["task_id"])
            if response["status"] in {"succeeded","failed"}:
                sample["status"]=response["status"];sample["task_result"]=response
                break
            if time.monotonic()>deadline:raise TimeoutError(entry["id"])
            time.sleep(5)
        if sample["status"]=="succeeded":
            if entry["source"]=="intergen":
                folder=ROOT/"InterGen_api/task_runs"/sample["task_id"]/"output/raw"
                paths=[folder/f"{sample['task_id']}_person{a}_joints22.npy" for a in (1,2)]
            else:paths=[Path(response["output_npy_path"])]
            if not all(p.is_file() for p in paths):
                sample["status"]="failed";sample["error"]="Missing generated arrays"
            else:
                sample["paths"]=[str(p) for p in paths]
                sample["sha256"]=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        save(state)
        print(f"{entry['id']}: {sample['status']}",flush=True)
    state["status"]="generation_complete";save(state)

if __name__=="__main__":main()
