"""Compare algorithms on development inputs; holdout is gated on human labels."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from motionlint.cli.main import load_motion, _write_json, _write_report
from motionlint.core.foot_support import estimate_support
from motionlint.core.config import load_config
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.repair_pipeline import repair
from motionlint.pipeline.regression import compare


def smooth(values):
    pad=np.pad(values,[(2,2)]+[(0,0)]*(values.ndim-1),mode="edge")
    return sum(pad[i:i+len(values)] for i in range(5))/5


def physical(original,candidate):
    support=estimate_support(original,load_config()["tests"]["foot_sliding"])
    up=original.metadata.get("up_axis",1);axes=[i for i in range(3) if i!=up]
    def distance(motion):
        step=np.linalg.norm(np.diff(motion.positions[:,:,support.feet][:,:,:,axes],axis=0),axis=-1)
        return float(step[support.intervals].sum())
    old,new=distance(original),distance(candidate)
    return {"original_support_joint_intervals":int(support.intervals.sum()),"support_distance_before_m":old,
            "support_distance_after_m":new,"support_distance_reduction":(old-new)/old if old>1e-12 else None,
            "max_joint_shift_m":float(np.linalg.norm(candidate.positions-original.positions,axis=-1).max())}


def save_motion(motion,raw,folder):
    folder.mkdir(parents=True,exist_ok=True)
    if motion.source=="lodge":
        np.save(folder/"repaired.npy",raw)
        return [folder/"repaired.npy"]
    paths=[]
    for actor in range(motion.actor_count):
        path=folder/f"actor{actor}.npy";np.save(path,motion.positions[:,actor]);paths.append(path)
    return paths


def baseline(paths,folder,frozen):
    worker='''import sys,json,numpy as np
from pathlib import Path
sys.path.insert(0,sys.argv[1]);sys.path.insert(0,sys.argv[2])
from motionlint.cli.main import load_motion,_write_json
from motionlint.pipeline.repair_pipeline import repair
out=Path(sys.argv[3]);out.mkdir(parents=True,exist_ok=True)
paths=json.loads(sys.argv[4]);motion=load_motion(paths[0],paths[1] if len(paths)>1 else None)
result=repair(motion)
_write_json(out/'legacy_repair_report.json',result.to_dict())
if motion.source=='lodge':np.save(out/'repaired.npy',result.raw_lodge if result.raw_lodge is not None else np.load(paths[0]))
else:
 for actor in range(motion.actor_count):np.save(out/f'actor{actor}.npy',result.motion.positions[:,actor])
'''
    env=dict(os.environ)
    # Preserve geometry across old/new adapters; version3's relocated implicit
    # model lookup would otherwise silently use a different rest skeleton.
    model=ROOT.parent/"HumanAction-runtime/InterGen/InterGen_master/human_models/smplx/SMPLX_NEUTRAL.npz"
    if model.exists():env["MOTIONLINT_SMPLX_MODEL"]=str(model)
    subprocess.run([sys.executable,"-c",worker,str(ROOT),str(frozen),str(folder),json.dumps([str(p) for p in paths])],check=True,env=env,capture_output=True,text=True)
    return [folder/"repaired.npy"] if (folder/"repaired.npy").exists() else sorted(folder.glob("actor*.npy"))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--study",type=Path,default=ROOT/"reports/first_prize/study")
    parser.add_argument("--split",choices=["development","holdout"],default="development")
    args=parser.parse_args()
    study=args.study
    if args.split=="holdout" and not (study/"human_evaluation/holdout/summary.json").exists():
        raise ValueError("Holdout comparison requires the frozen human evaluation first")
    state=json.loads((study/"generation.json").read_text(encoding="utf-8"))
    output=study/"comparisons"/args.split
    output.mkdir(parents=True,exist_ok=True)
    frozen=ROOT/"reports/first_prize/baseline_v3/frozen_code"
    if not frozen.exists():
        with zipfile.ZipFile(frozen.parent/"source_and_evidence.zip") as archive:
            for name in archive.namelist():
                if name.startswith("motionlint/"):
                    archive.extract(name,frozen)
    rows=[];failures=[]
    for sample in state["samples"]:
        if sample["split"]!=args.split or sample.get("status")!="succeeded":continue
        paths=[Path(p) for p in sample["paths"]]
        original=load_motion(paths[0],paths[1] if len(paths)>1 else None)
        before=inspect(original)
        for method in ["unrepaired","ordinary_smoothing","baseline_v3_algorithm","complete_v4","without_contact","without_regression"]:
            folder=output/sample["id"]/method
            try:
                if method=="unrepaired":candidate=original
                elif method=="baseline_v3_algorithm":
                    saved=baseline(paths,folder,frozen);candidate=load_motion(saved[0],saved[1] if len(saved)>1 else None)
                elif method=="ordinary_smoothing":
                    arrays=[np.load(p,allow_pickle=False) for p in paths]
                    if original.source=="lodge":
                        raw=arrays[0].copy();start=4 if raw.shape[1] in {139,319} else 0;raw[:,start:]=smooth(raw[:,start:])
                        folder.mkdir(parents=True,exist_ok=True);np.save(folder/"repaired.npy",raw);candidate=load_motion(folder/"repaired.npy")
                    else:
                        from dataclasses import replace
                        candidate=replace(original,positions=np.stack([smooth(a) for a in arrays],axis=1),root_translation=smooth(original.root_translation))
                        save_motion(candidate,None,folder)
                else:
                    ablations=frozenset({"contact"}) if method=="without_contact" else frozenset({"regression"}) if method=="without_regression" else frozenset()
                    result=repair(original,experimental_ablations=ablations)
                    candidate=result.motion
                    folder.mkdir(parents=True,exist_ok=True)
                    _write_json(folder/"repair_report.json",result.to_dict())
                    raw=result.raw_lodge if result.raw_lodge is not None else np.load(paths[0],allow_pickle=False) if original.source=="lodge" else None
                    save_motion(candidate,raw,folder)
                candidate.metadata={**candidate.metadata,"stage":method}
                report=inspect(candidate);gate=evaluate_gate(report);comparison=compare(before,report)
                _write_report(folder,report);_write_json(folder/"quality_gate.json",gate.to_dict())
                _write_json(folder/"comparison.json",comparison)
                rows.append({"sample_id":sample["id"],"method":method,"source":original.source,"rule_sha256":report.metadata["config_sha256"],
                             "before_score":before.overall_score,"after_score":report.overall_score,"gate":gate.status,"regression":comparison["status"],**physical(original,candidate)})
            except Exception as exc:
                failures.append({"sample_id":sample["id"],"method":method,"error":str(exc)})
        print(f"Compared development sample {sample['id']}",flush=True)
    with (output/"summary.csv").open("w",encoding="utf-8-sig",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]) if rows else ["sample_id"]);writer.writeheader();writer.writerows(rows)
    _write_json(output/"summary.json",{"split":args.split,"rows":rows,"failures":failures,
                "post_export_ablation":"pending actual-stage audit; not inferred from array comparisons",
                "scope":"Algorithm v3 candidates are re-scored under v4; no cross-policy score deltas", "human_semantic_validation":"pending"})

if __name__=="__main__":main()
