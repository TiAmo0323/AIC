"""Independent numeric oracle: no MotionLint detectors, support code or scores."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('folder',type=Path)
    args=parser.parse_args()
    manifest=json.loads((args.folder/'manifest.json').read_text(encoding='utf-8'))
    rows=[]
    for sample in manifest['motions']:
        path=args.folder/sample['input']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sample['sha256']:
            raise ValueError('Fixture hash mismatch')
        p=np.load(path,allow_pickle=False)
        kind=sample['injection']['type']
        event=sample['events'][0] if sample['events'] else None
        start=event['start_frame'] if event else 0
        if kind=='clean':value=float(np.abs(p-p[0]).max())
        elif kind=='temporal_continuity':value=float(np.linalg.norm(np.diff(p[:,0],axis=0),axis=-1).max())
        elif kind=='skeleton_integrity':
            lengths=np.linalg.norm(p[:,20]-p[:,18],axis=-1)
            value=float(np.abs(lengths-lengths[0]).max()/lengths[0])
        elif kind=='foot_sliding':value=float(np.linalg.norm(np.diff(p[:,10][:,[0,2]],axis=0),axis=-1).max()*sample['fps'])
        elif kind=='ground_contact':value=float(np.maximum(0.,-p[:,[10,11],1]).max())
        elif kind=='collision':value=float(np.linalg.norm(p[start,20]-p[start,15]))
        elif kind=='motion_jerk':value=float(np.linalg.norm(np.diff(p[:,20],n=3,axis=0),axis=-1).max()*sample['fps']**3)
        else:raise ValueError('Unknown injected defect')
        expected=sample['injection']['analytic_quantity']
        if not np.isclose(value,expected,atol=1e-6,rtol=1e-5):raise AssertionError((sample['id'],expected,value))
        rows.append({'id':sample['id'],'analytic_quantity':expected,'independently_measured_quantity':value,'verified':True})
    output=args.folder/'truth_verification.json'
    output.write_text(json.dumps({'status':'verified','count':len(rows),'detectors_imported':False,'scope':'Geometric injection quantities, not human validation or exhaustive collateral labels','rows':rows},indent=2),encoding='utf-8')
    print(f'{len(rows)} geometric injection quantities independently verified')


if __name__=='__main__':main()
