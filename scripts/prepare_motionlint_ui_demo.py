"""Use a copied historical development clip for UI QA; preserve old results."""
import hashlib
import json
import shutil
from pathlib import Path
from uuid import uuid4
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/first_prize/browser'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    record=OUT/'demo_provenance.json'
    if record.exists():
        print(record.read_text(encoding='utf-8'));return
    source_id='91d1b363-c453-4526-8bb2-8f933f25809b'
    source=ROOT/'InterGen_api/task_runs'/source_id
    task_id=str(uuid4());target=source.parent/task_id
    (target/'output/raw').mkdir(parents=True)
    inputs=[]
    for actor in (1,2):
        old=source/'output/raw'/f'{source_id}_person{actor}_joints22.npy'
        new=target/'output/raw'/f'{task_id}_person{actor}_joints22.npy'
        shutil.copyfile(old,new)
        inputs.append({'actor':actor,'source':str(old),'copied':str(new),'sha256':hashlib.sha256(new.read_bytes()).hexdigest()})
    video=target/'output/raw_preview.mp4'
    shutil.copyfile(source/'motionlint/original.mp4',video)
    state=json.loads((source/'task_manifest.json').read_text(encoding='utf-8'))
    stamp=datetime.now(timezone.utc).isoformat()
    state.update(task_id=task_id,status='succeeded',created_at=stamp,updated_at=stamp,
                 output_mp4_path=str(video),output_retarget_mp4_path=None,output_retarget_path=None,
                 output_bvh_path=None,available_skin_ids=['smpl'],skin_id='smpl',requested_skin_ids=['smpl'],
                 message='Copied historical development clip for MotionLint UI QA; no new generation')
    (target/'task_manifest.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')
    provenance={'task_id':task_id,'source_task_id':source_id,'source_class':'historical_development',
                'count_as_new_sample':False,'purpose':'UI operations and demonstration; no held-out scores used',
                'inputs':inputs,'video':str(video),'video_sha256':hashlib.sha256(video.read_bytes()).hexdigest()}
    record.write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
    print(task_id)


if __name__=='__main__':main()
