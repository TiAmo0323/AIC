"""Independent numeric validation of injection truth, without MotionLint imports.

Contact states come from the analytic generator, never inferred from velocity.
The checks validate the stored event and reference, rather than derive labels
from the tested detector. Threshold constants describe the injection contract.
"""
from pathlib import Path
import hashlib
import json
import numpy as np


def verify(manifest_path):
    path = Path(manifest_path)
    manifest = json.loads(path.read_text(encoding='utf-8'))
    records = []
    groups = {}
    for row in manifest['motions']:
        groups.setdefault(row['group_id'],set()).add(row['split'])
        source = path.parent/row['input']
        assert hashlib.sha256(source.read_bytes()).hexdigest()==row['sha256'], row['id']
        p = np.load(source,allow_pickle=False)
        reference_path=path.parent/row['reference']
        assert hashlib.sha256(reference_path.read_bytes()).hexdigest()==row['reference_sha256']
        reference=np.load(reference_path,allow_pickle=False)
        contacts=np.load(path.parent/row['contacts'],allow_pickle=False)
        kind=row['injection']['type']
        valid=True;quantity=None
        if row['events']:
            event=row['events'][0];a=event['actor_id'];start=event['start_frame'];end=event['end_frame']
            if kind=='temporal_continuity':
                quantity=float(np.sqrt(sum((p[start,a,0,d]-p[start-1,a,0,d])**2 for d in range(3))))
                valid=quantity>.18
            elif kind=='skeleton_integrity':
                actual=np.linalg.norm(p[start:end+1,a,20]-p[start:end+1,a,18],axis=1)
                expected=np.linalg.norm(reference[start:end+1,a,20]-reference[start:end+1,a,18],axis=1)
                quantity=float(np.min(np.abs(actual-expected)/expected));valid=quantity>.12
            elif kind=='foot_sliding':
                values=[]
                for frame in range(start,end+1):
                    for j,local in ((10,2),(11,3)):
                        assert contacts[frame,a,local] and contacts[frame-1,a,local], 'Injection must occur during analytic support'
                        values.append(np.sqrt(sum((p[frame,a,j,d]-p[frame-1,a,j,d])**2 for d in (0,2)))*row['fps'])
                quantity=float(min(values));valid=quantity>.16
            elif kind=='ground_contact':
                quantity=float(-np.max(p[start:end+1,a,[10,11],1]));valid=quantity>.035
            elif kind=='collision':
                quantity=float(np.max(np.linalg.norm(p[start:end+1,a,20]-p[start:end+1,a,15],axis=1)));valid=quantity<.12
            elif kind=='motion_jerk':
                quantities=[np.linalg.norm(p[f,a,20]-3*p[f-1,a,20]+3*p[f-2,a,20]-p[f-3,a,20])*row['fps']**3 for f in range(start+3,end-2)]
                quantity=float(min(quantities));valid=quantity>450
        if row['repairable_by_known_reference']:
            maximum=float(np.linalg.norm(p-reference,axis=-1).max())
            valid &= maximum<=.15+1e-10
        records.append({'id':row['id'],'valid':bool(valid),'independent_quantity':quantity})
    assert all(len(splits)==1 for splits in groups.values()), 'Trajectory group leaked across partitions'
    return {'independent_kernel':'motionlint.benchmark.truth (no detector/repair/support imports)',
            'count':len(records),'valid_count':sum(r['valid'] for r in records),'groups':len(groups),'records':records}
