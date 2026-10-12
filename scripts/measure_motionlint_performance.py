"""Serial CPU measurements on predeclared development inputs and one environment."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import statistics

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', type=Path)
parser.add_argument('--policy', default='v4', choices=('v4','v5'))
parser.add_argument('--jobs', type=Path)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
if args.source:
    source = args.source.resolve()
    sys.path = [str(source)] + [p for p in sys.path if p and not Path(p).resolve().is_relative_to(ROOT)]
    import psutil
    import motionlint
    from motionlint.cli.main import load_motion
    from motionlint.pipeline.inspector import inspect
    from motionlint.pipeline.repair_pipeline import repair
    assert Path(motionlint.__file__).resolve().is_relative_to(source)
    config = source/'motionlint/configs/quality_v4.yaml'
    if args.policy == 'v5' or not config.exists(): config=source/'motionlint/configs/default_quality.yaml'
    jobs=json.loads(args.jobs.read_text(encoding='utf-8'))
    proc=psutil.Process(); peak=[proc.memory_info().rss]; stop=threading.Event()
    def sample():
        while not stop.wait(.01): peak[0]=max(peak[0],proc.memory_info().rss)
    thread=threading.Thread(target=sample,daemon=True); thread.start()
    rows=[]
    for job in jobs:
        motion=load_motion(Path(job['path']),fps=30)
        motion.metadata['floor_height_m']=0.
        inspect(motion,config_path=config)
        measurements=[]
        for _ in range(7):
            start=time.perf_counter(); inspect(motion,config_path=config)
            measurements.append(time.perf_counter()-start)
        start=time.perf_counter(); outcome=repair(motion,config_path=config)
        rows.append({'id':job['id'],'frames':motion.frame_count,
            'detection_seconds_median':statistics.median(measurements),'detection_seconds':measurements,
            'repair_seconds':time.perf_counter()-start,'repair_status':outcome.to_dict().get('status',
                'accepted' if any(step['applied'] for step in outcome.steps) else 'not_accepted')})
    stop.set();thread.join()
    result={'schema_version':3,'python':sys.version,'platform':sys.platform,'policy':args.policy,
        'peak_process_rss_bytes_sampled_10ms':peak[0],'detector_seconds_median':statistics.median(r['detection_seconds_median'] for r in rows),
        'rows':rows,'sampling_limit':'Sampled RSS, not an exact allocation maximum','generator_services_used':False}
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    sys.exit(0)

output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
base=ROOT/'reports/iteration_050/v6_v4_foot/inputs'
ids=['clean_00','clean_08','foot_sliding_00','foot_sliding_04','foot_sliding_09','foot_sliding_14']
jobs=[{'id':key,'path':str(base/f'{key}.npy')} for key in ids]
jobfile=output/'inputs.json';jobfile.write_text(json.dumps(jobs,indent=2),encoding='utf-8')
env={**os.environ,'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'2','MKL_NUM_THREADS':'2'}
results={}
for name,source,policy in [('baseline_v4',ROOT.parent/'HumanAction-runtime/baselines/b833b32','v4'),
                         ('candidate_v4',ROOT,'v4'),('candidate_v5',ROOT,'v5')]:
    path=output/f'{name}.json'
    subprocess.run([sys.executable,str(Path(__file__)), '--source',str(source),'--policy',policy,
                   '--jobs',str(jobfile),'--output',str(path)],env=env,check=True)
    results[name]=json.loads(path.read_text(encoding='utf-8'))
ratio=results['candidate_v4']['detector_seconds_median']/results['baseline_v4']['detector_seconds_median']
result={'schema_version':3,'same_environment_serial':True,'predeclared_development_inputs':ids,
    'same_rule_v4_detection_cost_ratio':ratio,'detection_cost_target_met':ratio<=1.25,
    'maximum_allowed_cost_ratio':1.25,'results':results,
    'scope':'Local automated CPU measurement, excludes generation/rendering, no held-out calibration'}
(output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print('Detection cost ratio:',ratio,'target met:',result['detection_cost_target_met'])
