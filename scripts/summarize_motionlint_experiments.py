"""Summarize all development attempts and quality-based seed selection."""
import hashlib
import json
import statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STUDY=ROOT/'reports/first_prize/study'


def main():
    folder=STUDY/'comparisons/development'
    experiment=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
    grouped={}
    for method in sorted({r['method'] for r in experiment['rows']}):
        rows=[r for r in experiment['rows'] if r['method']==method]
        attempts=[]
        for row in rows:
            path=folder/row['sample_id']/method/'repair_report.json'
            if path.exists():
                repair=json.loads(path.read_text(encoding='utf-8'))
                attempts.extend(t for s in repair['steps'] for t in s.get('candidate_trials',[]))
        grouped[method]={'sample_count':len(rows),'strict_pass_count':sum(r['gate']=='PASS' for r in rows),
            'regression_count':sum(r['regression']!='PASS' for r in rows),
            'median_original_support_distance_reduction':statistics.median([r['support_distance_reduction'] for r in rows if r['support_distance_reduction'] is not None]) if any(r['support_distance_reduction'] is not None for r in rows) else None,
            'max_joint_shift_m':max(r['max_joint_shift_m'] for r in rows),
            'candidate_attempt_count':len(attempts),'accepted_candidate_count':sum(t.get('status')=='accepted' for t in attempts),
            'rejected_candidate_count':sum(t.get('status')=='rejected' for t in attempts),
            'failed_candidate_count':sum(t.get('status')=='failed' for t in attempts)}
    state=json.loads((STUDY/'generation.json').read_text(encoding='utf-8'))
    samples={r['id']:r for r in state['samples']}
    groups={}
    for row in experiment['rows']:
        sample=samples[row['sample_id']]
        if row['method']=='unrepaired' and sample['source']=='intergen':
            groups.setdefault(sample['group'],[]).append(row)
    selections=[]
    for group, candidates in groups.items():
        candidates=sorted(candidates,key=lambda r:samples[r['sample_id']]['seed'])
        def rank(row):
            report=json.loads((folder/row['sample_id']/'unrepaired/motionlint_report.json').read_text(encoding='utf-8'))
            critical=sum(issue['severity']=='critical' for test in report['tests'] for issue in test['issues'])
            return (row['gate']=='PASS',-critical,row['after_score'])
        chosen=max(candidates,key=rank)
        selections.append({'group':group,'prompt':samples[chosen['sample_id']]['prompt'],
            'first_seed_sample':candidates[0]['sample_id'],'quality_selected_sample':chosen['sample_id'],
            'selection_rule':'strict_gate, fewer critical issues, higher quality score; first seed breaks ties',
            'same_rule_sha256':chosen['rule_sha256'],'all_candidates':candidates,
            'human_semantic_comparison':'pending independent judgement'})
    result={'scope':'Development only; not real-motion detection accuracy or blind-test proof',
        'source_summary_sha256':hashlib.sha256((folder/'summary.json').read_bytes()).hexdigest(),
        'methods':grouped,'failures':experiment['failures'],'seed_selection':selections,
        'post_export_ablation':'pending six held-out actual exports and human evaluation',
        'human_semantics':'pending','physical_reduction_population':'all development inputs with nonzero original support distance; not restricted to human-confirmed supported defects'}
    (folder/'aggregate.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'methods':grouped,'seed_groups':len(selections),'execution_failures':len(experiment['failures'])},indent=2))


if __name__=='__main__':main()
