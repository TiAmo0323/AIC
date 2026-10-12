"""Frozen evaluation with trajectory-group uncertainty and preserved failures."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from motionlint.adapters.intergen_adapter import JOINT_NAMES, PARENTS
from motionlint.core.motion_sequence import MotionSequence
from motionlint.core.config import load_config, DEFAULT_CONFIG
from motionlint.core.provenance import rule_hash
from motionlint.core.quality_gate import evaluate_gate
from motionlint.pipeline.inspector import inspect
from motionlint.pipeline.repair_pipeline import repair
from motionlint.benchmark.evaluation import match_events, metrics, iou, merge_events


def load_sample(root, row):
    path = Path(root)/row['input']
    if hashlib.sha256(path.read_bytes()).hexdigest() != row['sha256']:
        raise ValueError('Benchmark input hash changed')
    p = np.load(path,allow_pickle=False)
    return MotionSequence('intergen',row['fps'],len(p),p.shape[1],positions=p,
                          root_translation=p[:,:,0].copy(),contacts=np.load(Path(root)/row['contacts'],allow_pickle=False),
                          joint_names=JOINT_NAMES.copy(),metadata={'parents':PARENTS.copy(),'up_axis':1,'floor_height_m':0.,
                              'foot_joint_ids':[7,8,10,11],'left_foot_joint_ids':[7,10],'right_foot_joint_ids':[8,11],
                              'source_paths':[str(path)],'evidence_type':'analytic_injection','trajectory_group':row['group_id']})


def code_hashes():
    package=Path(__file__).resolve().parents[1]
    return {p.relative_to(package).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for folder in ('core','tests','pipeline','repairs','adapters') for p in sorted((package/folder).rglob('*.py'))}


def freeze(manifest_path, output, config_path=None):
    config=load_config(config_path or DEFAULT_CONFIG)
    payload={'schema_version':3,'rules_version':config['version'],'rules_sha256':rule_hash(config),
             'dataset_sha256':hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),'code_sha256':code_hashes()}
    output=Path(output)
    if output.exists() and json.loads(output.read_text(encoding='utf-8'))!=payload:
        raise ValueError('Freeze already exists with a different dataset or code; create a new held-out dataset version')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(payload,indent=2),encoding='utf-8')
    return payload


def grouped_interval(rows, repeats=1000):
    groups=sorted({r['group_id'] for r in rows})
    rng=np.random.default_rng(53000)
    values=[]
    for _ in range(repeats):
        chosen=rng.choice(groups,len(groups),replace=True)
        values.append(metrics([r for g in chosen for r in rows if r['group_id']==g]))
    return {key:np.percentile([v[key] for v in values if v[key] is not None],[2.5,97.5]).tolist()
            for key in ('precision','recall','f1') if any(v[key] is not None for v in values)}


def compact_record(record):
    record = dict(record)
    if record.get('repair'):
        full = record['repair']
        record['repair'] = {key: full.get(key) for key in ('algorithm_version', 'status', 'reason_codes', 'support_comparison', 'final_selection', 'issue_summary')}
        record['repair_report'] = f"{record['id']}/repair.json"
    return record


def run(manifest_path, output, *, split='development', config_path=None, frozen=None, do_repair=False):
    path=Path(manifest_path);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(path.read_text(encoding='utf-8'))
    config=load_config(config_path or DEFAULT_CONFIG)
    if split=='holdout':
        if frozen is None: raise ValueError('Held-out evaluation requires --freeze created before evaluation')
        current={'schema_version':3,'rules_version':config['version'],'rules_sha256':rule_hash(config),
                 'dataset_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'code_sha256':code_hashes()}
        saved=json.loads(Path(frozen).read_text(encoding='utf-8'))
        if saved!=current: raise ValueError('Frozen evaluation context changed; this holdout cannot calibrate the new code')
    selected=[r for r in manifest['motions'] if r['split']==split]
    records=[]
    for row in selected:
        folder=output/row['id'];folder.mkdir(exist_ok=True)
        saved_path=folder/'result.json'
        if saved_path.exists():
            previous=json.loads(saved_path.read_text(encoding='utf-8'))
            if previous['input_sha256']!=row['sha256']:
                raise ValueError('Cannot resume a changed benchmark input')
            if do_repair and previous.get('repair'):
                full=previous['repair']
                if 'steps' in full and not (folder/'repair.json').exists():
                    with (folder/'repair.json').open('w',encoding='utf-8') as handle:
                        json.dump(full,handle,indent=2)
                records.append(compact_record(previous))
                continue
            if not do_repair:
                records.append(previous)
                continue
        started=time.perf_counter()
        motion=load_sample(path.parent,row)
        report=inspect(motion,config_path=config_path)
        predictions=[i.to_dict() for t in report.tests for i in t.issues if t.test_name in row['evaluated_tests']]
        counts=[]
        for kind in row['evaluated_tests']:
            truth=[e for e in row['events'] if e['test_name']==kind]
            pred=[e for e in predictions if e['test_name']==kind]
            counts.append({'test':kind,'group_id':row['group_id'],**match_events(truth,pred)})
        joint_correct=0;joint_total=0
        for event in row['events']:
            joints=set(event['joint_ids']);joint_total+=len(joints)
            found=set()
            for p in predictions:
                if p['test_name']==event['test_name'] and p['actor_id']==event['actor_id'] and iou(event,p)>=.5:
                    found.update(p['joint_ids'])
            joint_correct+=len(joints & found)
        record={'id':row['id'],'group_id':row['group_id'],'split':split,'input_sha256':row['sha256'],
                'seconds':time.perf_counter()-started,'metrics':counts,'joint_correct':joint_correct,'joint_total':joint_total,
                'gate':evaluate_gate(report,config_path=config_path).to_dict(),
                'high_severity_alert':any(i.severity in ('high','critical') for t in report.tests for i in t.issues),
                'coverage':report.metadata['evaluation_coverage'],'kind':row['injection']['type']}
        (folder/'report.json').write_text(json.dumps(report.to_dict(),indent=2),encoding='utf-8')
        if do_repair:
            outcome=repair(motion,config_path=config_path)
            np.save(folder/'selected.npy',outcome.motion.positions,allow_pickle=False)
            full=outcome.to_dict()
            with (folder/'repair.json').open('w',encoding='utf-8') as handle:
                json.dump(full,handle,indent=2)
            record['repair']=full
            record['known_repairable']=row['repairable_by_known_reference']
            record['input_unchanged']=hashlib.sha256((path.parent/row['input']).read_bytes()).hexdigest()==row['sha256']
        record=compact_record(record)
        records.append(record)
        with (folder/'result.json').open('w',encoding='utf-8') as handle:
            json.dump(record,handle,indent=2)
    per_class={kind:{**metrics([v for r in records for v in r['metrics'] if v['test']==kind]),
                     'group_bootstrap_95pct':grouped_interval([v for r in records for v in r['metrics'] if v['test']==kind])}
               for kind in config['tests']}
    normal=[r for r in records if r['kind']=='clean']
    macro=float(np.mean([v['f1'] or 0 for v in per_class.values()]))
    false_rate=sum(r['high_severity_alert'] for r in normal)/len(normal) if normal else None
    summary={'schema_version':3,'dataset_version':manifest['dataset_version'],'split':split,'count':len(records),
             'rules_version':config['version'],'rules_sha256':rule_hash(config),'macro_f1':macro,'per_class':per_class,
             'normal_count':len(normal),'normal_high_severity_false_positive_fraction':false_rate,
             'joint_localization_recall':sum(r['joint_correct'] for r in records)/max(1,sum(r['joint_total'] for r in records)),
             'acceptance':{'macro_f1_ge_095':macro>=.95,'all_classes_ge_090':all((v['f1'] or 0)>=.90 for v in per_class.values()),
                           'normal_high_severity_le_002':false_rate is not None and false_rate<=.02},
             'evidence_type':'controlled_injection_only','event_policy':'Union overlapping intervals per type/actor, then maximum-cardinality one-to-one matching at IoU >= 0.5',
             'records':records}
    (output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return summary
