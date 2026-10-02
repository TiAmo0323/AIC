"""Build/evaluate the 120 self-authored controlled cases; never a human score."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from motionlint.benchmark.fixtures import build, TESTS
from motionlint.benchmark.evaluation import match_events, metrics, bootstrap
from motionlint.cli.main import load_motion, _write_json, _write_report
from motionlint.pipeline.inspector import inspect


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,default=ROOT/"reports/first_prize/controlled")
    parser.add_argument("--config",type=Path)
    args=parser.parse_args()
    manifest=build(args.output/"inputs")
    rows=[]
    for entry in manifest["motions"]:
        motion=load_motion(args.output/"inputs"/entry["input"])
        motion.metadata["floor_height_m"]=entry["floor_height_m"]
        report=inspect(motion,config_path=args.config)
        _write_report(args.output/entry["id"],report)
        for name in entry["evaluated_tests"]:
            test=next(t for t in report.tests if t.test_name==name)
            counts=match_events([e for e in entry["events"] if e["test_name"]==name],[i.to_dict() for i in test.issues])
            rows.append({"sample_id":entry["id"],"test":name,**counts})
    summary={"status":"measured", "sample_count":len(manifest["motions"]), "scope":manifest["purpose"],
             "human_validation":False,"config_sha256":report.metadata["config_sha256"],
             "tests":{name:{**metrics([r for r in rows if r["test"]==name]),"bootstrap_95_percent":bootstrap([r for r in rows if r["test"]==name])} for name in TESTS},"rows":rows}
    values=[v["f1"] for v in summary["tests"].values() if v["f1"] is not None]
    summary["macro_f1"]=sum(values)/len(values) if values else None
    _write_json(args.output/"summary.json",summary)
    print(json.dumps({"samples":summary["sample_count"],"macro_f1":summary["macro_f1"],"tests":summary["tests"]},indent=2))

if __name__=="__main__":main()
