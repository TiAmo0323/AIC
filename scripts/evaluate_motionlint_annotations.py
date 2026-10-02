"""Require human adjudication, two independent annotations and frozen code."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from motionlint.benchmark.evaluation import match_events, metrics, bootstrap, iou
from motionlint.benchmark.fixtures import TESTS
from motionlint.cli.main import load_motion, _write_json, _write_report
from motionlint.pipeline.inspector import inspect


def code_hashes():
    paths=list((ROOT/"motionlint").rglob("*.py"))+list((ROOT/"motionlint/configs").glob("*.yaml"))
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def validate_annotation(payload, samples, digest, require_review=False):
    if payload.get("protocol_sha256")!=digest:raise ValueError("Annotation protocol hash mismatch")
    identity=payload.get("reviewed_by" if require_review else "annotator")
    if not isinstance(identity,str) or not identity.strip():raise ValueError("Missing actual annotator/reviewer identifier")
    if require_review and payload.get("status")!="adjudicated":raise ValueError("Human adjudication is not complete")
    result={}
    for row in payload.get("motions",[]):
        key=row["id"]
        if key in result:raise ValueError("Duplicate annotation motion")
        if key not in samples or row.get("sha256")!=samples[key]["sha256"]:raise ValueError("Annotation input hash mismatch")
        sample=samples[key]
        if row.get("frame_count")!=sample["actual_frame_count"] or row.get("fps")!=sample["actual_fps"]:
            raise ValueError("Annotation frame count or FPS differs from actual input")
        if row.get("status")!="complete":raise ValueError(f"Incomplete human annotation: {key}")
        if require_review:
            review=row.get("review",{})
            if review.get("status")!="reviewed" or not review.get("decision") or not review.get("reason"):
                raise ValueError(f"Missing actual adjudication decision/reason: {key}")
        for event in row.get("events",[]):
            if event.get("test_name") not in TESTS:raise ValueError("Unknown event type")
            first,last=event.get("start_frame"),event.get("end_frame")
            if not isinstance(first,int) or not isinstance(last,int) or first<0 or last<first or last>=row["frame_count"]:raise ValueError("Invalid annotation interval")
            actor=event.get("actor_id")
            if not isinstance(actor,int) or actor<0 or actor>=sample["actual_actor_count"]:raise ValueError("Actor identifier is missing or invalid")
        result[key]=row
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--study",type=Path,default=ROOT/"reports/first_prize/study")
    parser.add_argument("--freeze",action="store_true")
    parser.add_argument("--annotations",type=Path)
    parser.add_argument("--annotator-a",type=Path)
    parser.add_argument("--annotator-b",type=Path)
    parser.add_argument("--split",choices=["development","holdout"],default="holdout")
    args=parser.parse_args()
    study=args.study
    freeze_path=study/"evaluation_freeze.json"
    if args.freeze:
        if freeze_path.exists():raise ValueError("Evaluation freeze already exists; refusing replacement")
        _write_json(freeze_path,{"code_hashes":code_hashes(),"protocol_sha256":hashlib.sha256((study/"protocol.json").read_bytes()).hexdigest()})
        print("Code and rules frozen; no holdout evaluation executed")
        return
    frozen=json.loads(freeze_path.read_text(encoding="utf-8"))
    if frozen["code_hashes"]!=code_hashes():raise ValueError("Frozen code changed; this is no longer a held-out evaluation")
    if not all([args.annotations,args.annotator_a,args.annotator_b]):raise ValueError("Supply adjudicated labels and both independent annotation files")
    state=json.loads((study/"generation.json").read_text(encoding="utf-8"))
    if state["protocol_sha256"]!=frozen["protocol_sha256"]:raise ValueError("Frozen protocol changed")
    samples={r["id"]:r for r in state["samples"] if r.get("status")=="succeeded"}
    for sample in samples.values():
        paths=sample["paths"]
        motion=load_motion(paths[0],paths[1] if len(paths)>1 else None)
        sample["actual_frame_count"]=motion.frame_count
        sample["actual_fps"]=motion.fps
        sample["actual_actor_count"]=motion.actor_count
    read=lambda p:json.loads(p.read_text(encoding="utf-8"))
    first,second=read(args.annotator_a),read(args.annotator_b)
    if first.get("annotator")==second.get("annotator"):raise ValueError("Need two independently identified annotators")
    a=validate_annotation(first,samples,state["protocol_sha256"])
    b=validate_annotation(second,samples,state["protocol_sha256"])
    adjudicated=read(args.annotations)
    expected_sources={"annotator_a":hashlib.sha256(args.annotator_a.read_bytes()).hexdigest(),"annotator_b":hashlib.sha256(args.annotator_b.read_bytes()).hexdigest()}
    if adjudicated.get("source_annotation_sha256")!=expected_sources:raise ValueError("Adjudication is not linked to these original annotations")
    labels=validate_annotation(adjudicated,samples,state["protocol_sha256"],True)
    rows=[];agreement=[];uncertain=0
    selected=[r for r in samples.values() if r["split"]==args.split]
    for sample in selected:
        key=sample["id"]
        if not all(key in records for records in (a,b,labels)):raise ValueError(f"Missing human annotation for {key}")
        paths=sample["paths"]
        if [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths]!=sample["sha256"]:raise ValueError("Input has changed")
        motion=load_motion(paths[0],paths[1] if len(paths)>1 else None)
        report=inspect(motion)
        _write_report(study/"human_evaluation"/args.split/key,report)
        uncertain_events=[e for e in labels[key]["events"] if e.get("uncertain") or e.get("expected_contact")]
        uncertain+=len(uncertain_events)
        for test in report.tests:
            truth=[e for e in labels[key]["events"] if e["test_name"]==test.test_name and not e.get("uncertain") and not e.get("expected_contact")]
            predicted=[i.to_dict() for i in test.issues]
            ignored=[p for p in predicted if any(e["test_name"]==p["test_name"] and e.get("actor_id")==p.get("actor_id") and iou(e,p)>=.5 for e in uncertain_events)]
            predicted=[p for p in predicted if p not in ignored]
            rows.append({"sample_id":key,"test":test.test_name,**match_events(truth,predicted),"ignored_predictions":len(ignored),"coverage":test.metrics.get("evaluation_status")})
            agreement.append({"sample_id":key,"test":test.test_name,**match_events([e for e in a[key]["events"] if e["test_name"]==test.test_name],[e for e in b[key]["events"] if e["test_name"]==test.test_name])})
    summary={"split":args.split,"sample_count":len(selected),"uncertain_or_expected_contact_events":uncertain,
             "generation_failures":[r["id"] for r in state["samples"] if r.get("status")=="failed"],
             "generation_attempt_count":sum(len(r.get("attempts",[])) for r in state["samples"]),
             "prior_failed_attempt_count":sum(len(r.get("failed_attempts",[])) for r in state["samples"]),
             "human_validation":True,"annotation_sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [args.annotations,args.annotator_a,args.annotator_b]},
             "tests":{t:{**metrics([r for r in rows if r["test"]==t]),"bootstrap_95_percent":bootstrap([r for r in rows if r["test"]==t]),"annotator_agreement":metrics([r for r in agreement if r["test"]==t])} for t in TESTS},"rows":rows}
    _write_json(study/"human_evaluation"/args.split/"summary.json",summary)
    print(f"Evaluated {len(selected)} genuinely human-labelled motions")

if __name__=="__main__":main()
