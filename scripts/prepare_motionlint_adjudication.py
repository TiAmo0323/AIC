"""Prepare a review worksheet from two humans; never invent adjudicated truth."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('annotator_a', type=Path)
    parser.add_argument('annotator_b', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    a=json.loads(args.annotator_a.read_text(encoding='utf-8'))
    b=json.loads(args.annotator_b.read_text(encoding='utf-8'))
    if not a.get('annotator') or not b.get('annotator') or a['annotator']==b['annotator']:
        raise ValueError('Two different actual annotators are required')
    if a.get('protocol_sha256')!=b.get('protocol_sha256'):
        raise ValueError('Protocol mismatch')
    left={r['id']:r for r in a['motions']};right={r['id']:r for r in b['motions']}
    if len(left)!=len(a['motions']) or len(right)!=len(b['motions']) or set(left)!=set(right):
        raise ValueError('Duplicate or mismatched motion identifiers')
    rows=[]
    for key, first in left.items():
        second=right[key]
        if any(first.get(field)!=second.get(field) for field in ['sha256','fps','frame_count']):
            raise ValueError(f'Input metadata mismatch: {key}')
        if first.get('status')!='complete' or second.get('status')!='complete':
            raise ValueError(f'Independent annotation incomplete: {key}')
        rows.append({**first,'status':'incomplete','events':[],
                     'review':{'status':'pending','decision':'','reason':'',
                               'annotator_a_events':first['events'],'annotator_b_events':second['events'],
                               'annotator_a_semantics':first.get('semantic_alignment'),
                               'annotator_b_semantics':second.get('semantic_alignment')}})
    result={'schema_version':1,'protocol_sha256':a['protocol_sha256'],'status':'pending_review',
            'reviewed_by':'','source_annotation_sha256':{
                'annotator_a':hashlib.sha256(args.annotator_a.read_bytes()).hexdigest(),
                'annotator_b':hashlib.sha256(args.annotator_b.read_bytes()).hexdigest()},
            'instructions':'Review both labels, fill final events and semantics, record review decision/reason; set each motion status complete and review status reviewed, then top-level status adjudicated and reviewed_by. Do not infer labels from MotionLint outputs.',
            'motions':rows}
    if args.output.exists():raise ValueError('Refusing to overwrite an existing review worksheet')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'{len(rows)} review worksheets prepared; no ground truth adjudicated')


if __name__=='__main__':main()
