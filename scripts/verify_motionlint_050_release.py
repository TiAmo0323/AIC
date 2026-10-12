"""Audit frozen code, protected inputs and unchanged external BVH round trips."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from motionlint.artifacts import sha256
from motionlint.benchmark.runner import code_hashes
from motionlint.benchmark.truth import verify
from motionlint.adapters.bvh_adapter import load_bvh
from motionlint.adapters.bvh_reader import read_bvh
from motionlint.core.config import load_config
from motionlint.core.provenance import rule_hash


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    args=parser.parse_args();runtime=args.runtime.resolve();base=ROOT/'reports/iteration_050'
    frozen=json.loads((base/'freeze-v5/freeze.json').read_text(encoding='utf-8'))
    assert frozen['code_sha256']==code_hashes(),'Detector or repair changed after held-out freeze'
    assert frozen['rules_sha256']==rule_hash(load_config())
    assert frozen['dataset_sha256']==sha256(base/'dynamic-2/manifest.json')
    seen={};rows=[];contacts={}
    def check(path,expected):
        path=path.resolve()
        actual=seen.setdefault(str(path),sha256(path)) if str(path) not in seen else seen[str(path)]
        if actual!=expected:raise ValueError('Protected input changed: '+str(path))
    dynamic=json.loads((base/'dynamic-2/manifest.json').read_text(encoding='utf-8'))
    for row in dynamic['motions']:
        for key,hashkey in [('input','sha256'),('reference','reference_sha256')]:check(base/'dynamic-2'/row[key],row[hashkey])
        contacts[row['contacts']]=sha256(base/'dynamic-2'/row['contacts'])
        rows.append({'id':row['id'],'source':'controlled','unchanged':True})
    truth=verify(base/'dynamic-2/manifest.json');assert truth['valid_count']==600
    real=json.loads((base/'engineering-1/manifest.json').read_text(encoding='utf-8'))
    bvh=[]
    for row in real['motions']:
        for entry in row.get('input_files',row.get('files',[])):check(runtime/'resources'/entry['path'],entry['sha256'])
        rows.append({'id':row['id'],'source':'real','unchanged':True})
        if row['source']!='bandai_bvh':continue
        original=runtime/'resources'/row['input'];written=base/'bvh-roundtrip'/f"{row['id']}.bvh"
        a=load_bvh(original,**row['options']);b=load_bvh(written,**row['options'])
        da=read_bvh(original);db=read_bvh(written)
        preserved=all(np.array_equal(da[key],db[key]) for key in ('names','parents','channels','rot_order','offsets'))
        preserved &= da['channel_labels']==db['channel_labels'] and np.isclose(da['frame_time'],db['frame_time'],rtol=0,atol=1e-10)
        error=float(np.linalg.norm(a.positions-b.positions,axis=-1).max())
        assert preserved and error<=.0001,(row['id'],error,preserved)
        bvh.append({'id':row['id'],'input_sha256':sha256(original),'written_sha256':sha256(written),
            'max_coordinate_error_m':error,'hierarchy_channels_rotation_order_fps_preserved':bool(preserved)})
    adverse=json.loads((base/'safety-2/manifest.json').read_text(encoding='utf-8'))
    for row in adverse['samples']:
        for entry in row['files']:check(base/'safety-2'/entry['path'],entry['sha256'])
        rows.append({'id':row['id'],'source':'safety','unchanged':True})
    result={'schema_version':3,'status':'PASS','frozen_code_and_rule_unchanged':True,
        'protected_sample_count':len(rows),'unchanged_sample_count':sum(row['unchanged'] for row in rows),
        'unique_protected_file_count':len(seen),'rows':rows,'bvh_roundtrip_count':len(bvh),'bvh_roundtrips':bvh,
        'independent_truth_valid_count':truth['valid_count'],'contact_input_hashes_observed_at_release':contacts,
        'contact_hash_timing_limit':'Contact SHA values were added at release audit. They are not presented as pretest freeze receipts.',
        'scope':'Existing immutable inputs and readback only; no held-out detector recalibration'}
    assert len(rows)==720 and len(bvh)==24
    (ROOT/'evidence/iteration-050-release-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Release audit PASS:',len(rows),'protected samples;',len(bvh),'BVH round trips; frozen code unchanged')


if __name__=='__main__':main()
