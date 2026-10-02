"""Decode real outputs completely without inspecting held-out motion quality."""
import hashlib
import json
import subprocess
import re
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from motionlint.cli.main import load_motion


def main():
    study=ROOT/'reports/first_prize/study'
    state=json.loads((study/'generation.json').read_text(encoding='utf-8'))
    bin_dir=ROOT.parent/'HumanAction-runtime/bin'
    rows=[]
    for sample in state['samples']:
        if sample.get('status')!='succeeded':continue
        paths=sample['paths'];motion=load_motion(paths[0],paths[1] if len(paths)>1 else None)
        video=Path(sample['task_result']['output_mp4_path'])
        decoded=subprocess.run([str(bin_dir/'ffmpeg.exe'),'-v','info','-nostats','-progress','pipe:1','-xerror','-err_detect','explode','-i',str(video),'-map','0:v:0','-an','-fps_mode','passthrough','-f','null','-'],capture_output=True,text=True,encoding='utf-8',errors='replace')
        try:
            frame_matches=re.findall(r'^frame=(\d+)$',decoded.stdout,re.M)
            frames=int(frame_matches[-1])
            fps=float(re.search(r'Video:.*?\b([0-9.]+) fps\b',decoded.stderr).group(1))
            if 'progress=end' not in decoded.stdout:raise ValueError('No completed decoding marker')
        except (ValueError,KeyError,IndexError):
            rows.append({'id':sample['id'],'status':'failed','error':'Cannot count video frames','stderr':decoded.stderr});continue
        valid=(decoded.returncode==0 and frames==motion.frame_count and abs(fps-motion.fps)<.001)
        rows.append({'id':sample['id'],'status':'verified' if valid else 'failed','video':str(video),
            'sha256':hashlib.sha256(video.read_bytes()).hexdigest(),'decoded_frames':frames,'expected_frames':motion.frame_count,
            'fps':fps,'expected_fps':motion.fps,'duration_s':frames/fps,'expected_duration_s':motion.duration_seconds,
            'full_decode_returncode':decoded.returncode,'stderr':decoded.stderr[-1500:],
            'music_input_seconds':sample.get('clip_seconds'),
            'music_duration_note':'LODGE emits complete 1024-frame blocks; a 36s input can end at 34.133s, not a claim of full music coverage' if sample['source']=='lodge' else None})
        print(f"{sample['id']}: {rows[-1]['status']} ({frames}/{motion.frame_count} frames)",flush=True)
    (study/'video_verification.json').write_text(json.dumps({'status':'verified' if all(r['status']=='verified' for r in rows) and len(rows)==30 else 'incomplete_or_failed','scope':'File completeness, not human appearance or action quality','rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(r['status']=='verified' for r in rows):raise SystemExit(1)


if __name__=='__main__':main()
