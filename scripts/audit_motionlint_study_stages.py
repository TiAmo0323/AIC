"""Prepare six-case stage worksheet; audit only after independent evaluation."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from motionlint.cli.main import load_motion, _write_json, _write_report
from motionlint.adapters.bvh_adapter import load_bvh_pair
from motionlint.adapters.character_adapter import load_character
from motionlint.pipeline.inspector import inspect
from motionlint.core.quality_gate import evaluate_gate
from evaluate_motionlint_annotations import code_hashes


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--study',type=Path,default=ROOT/'reports/first_prize/study')
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--manifest',type=Path)
    args=parser.parse_args()
    protocol=json.loads((args.study/'protocol.json').read_text(encoding='utf-8'))
    state=json.loads((args.study/'generation.json').read_text(encoding='utf-8'))
    samples={r['id']:r for r in state['samples']}
    if args.prepare:
        path=args.study/'export_stage_worksheet.json'
        if path.exists():raise ValueError('Refusing to replace a stage worksheet')
        rows=[{'id':key,'task_id':samples[key]['task_id'],
               'raw':{'files':samples[key]['paths'],'sha256':samples[key]['sha256']},
               'repaired':None,'bvh':None,'character':None,'video_verification':None,
               'instructions':'Each stage needs files/sha256 and derives_from_sha256 matching the previous stage. BVH also needs explicit unit_scale/up_axis/joint_mapping. Character needs evaluated Blender NPZ with JSON metadata. Keep actual exporter logs; do not substitute raw exports for repaired exports.'} for key in protocol['export_holdout_ids']]
        _write_json(path,{'status':'pending_real_exports','protocol_sha256':state['protocol_sha256'],'motions':rows})
        print('Six original sample identities linked; no quality inspection performed')
        return
    frozen=json.loads((args.study/'evaluation_freeze.json').read_text(encoding='utf-8'))
    if frozen['code_hashes']!=code_hashes():raise ValueError('Code differs from evaluation freeze')
    evaluated=json.loads((args.study/'human_evaluation/holdout/summary.json').read_text(encoding='utf-8'))
    if not evaluated.get('human_validation'):raise ValueError('Independent human evaluation must precede stage audit')
    if not args.manifest:raise ValueError('Supply completed actual-stage manifest')
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    if manifest.get('protocol_sha256')!=state['protocol_sha256']:raise ValueError('Protocol mismatch')
    rows=manifest['motions']
    if len(rows)!=6 or {r['id'] for r in rows}!=set(protocol['export_holdout_ids']):raise ValueError('Use exactly the six frozen original sample identities')
    output=args.study/'stage_audit';results=[]
    for row in rows:
        previous=samples[row['id']]['sha256'];stage_results=[]
        motions=[]
        for stage in ('raw','repaired','bvh','character'):
            entry=row.get(stage)
            if not isinstance(entry,dict) or not entry.get('files'):raise ValueError(f'Missing real {stage} for {row["id"]}')
            paths=[Path(p) for p in entry['files']]
            actual=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
            if actual!=entry.get('sha256'):raise ValueError('Stage artifact hash mismatch')
            if stage=='raw' and actual!=previous:raise ValueError('Raw input differs from original frozen sample')
            if stage!='raw' and entry.get('derives_from_sha256')!=previous:raise ValueError('Missing or inconsistent stage lineage')
            if stage=='character':
                if len(paths)!=1:raise ValueError('Character requires one evaluated multi-actor NPZ')
                motion=load_character(paths[0])
            elif stage=='bvh':
                if not all(k in entry for k in ('unit_scale','up_axis','joint_mapping')):raise ValueError('Explicit BVH convention is required')
                motion=load_bvh_pair(paths,unit_scale=entry['unit_scale'],up_axis=entry['up_axis'],joint_mapping=entry['joint_mapping'])
            else:motion=load_motion(paths[0],paths[1] if len(paths)>1 else None)
            motion.metadata['stage']=stage
            report=inspect(motion);gate=evaluate_gate(report)
            folder=output/row['id']/stage
            _write_report(folder,report);_write_json(folder/'quality_gate.json',gate.to_dict())
            stage_results.append({'stage':stage,'score':report.overall_score,'gate':gate.to_dict(),'input_sha256':actual})
            motions.append(motion);previous=actual
        if any(m.frame_count!=motions[0].frame_count or m.actor_count!=motions[0].actor_count or abs(m.fps-motions[0].fps)>.001 for m in motions[1:]):raise ValueError('Stages do not preserve actors, frames or FPS')
        video=row.get('video_verification') or {}
        if video.get('status')!='verified' or video.get('full_decode_returncode')!=0 or video.get('decoded_frames')!=motions[-1].frame_count:raise ValueError('Final video needs a real complete-decoding record')
        if hashlib.sha256(Path(video['video']).read_bytes()).hexdigest()!=video['sha256']:raise ValueError('Video changed since full decoding')
        results.append({'id':row['id'],'stages':stage_results,'without_export_audit_would_check':'repaired array only',
            'residual_failed_export_stages':[r['stage'] for r in stage_results[2:] if r['gate']['status']=='FAIL']})
    _write_json(output/'summary.json',{'status':'measured','sample_count':6,'count_as_new_samples':False,
        'scope':'Each geometry gets an independent quality gate; cross-stage total score deltas are not repair improvement',
        'manifest_sha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest(),'rows':results})
    print('Six matched actual-stage records audited; failures retained')


if __name__=='__main__':main()
