"""Encode timestamped actual browser frames, synthetic narration and captions."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import wave

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from motionlint.artifacts import sha256
from motionlint.character_export import verify_video


def ass_time(seconds):
    value=round(seconds*100)
    return '%d:%02d:%02d.%02d'%(value//360000,(value//6000)%60,(value//100)%60,value%100)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recording',type=Path,required=True)
    parser.add_argument('--runtime',type=Path,required=True)
    args=parser.parse_args();folder=args.recording.resolve()
    capture=json.loads((folder/'capture.json').read_text(encoding='utf-8'))
    chapters=capture['timeline'];assert len(chapters)==9
    frames=capture['frames'];duration=capture['recorded_seconds'];fps=25;count=round(duration*fps);duration=count/fps
    texts=[
        '这是 MotionLint 动作质检工具。画面来自实际浏览器操作。自制骨架示例不需要模型权重，质检可脱离生成服务独立使用。',
        '点击时间轴的问题区间，可定位角色、关节和起止帧，并查看实测数值、阈值及支撑依据。原支撑区间在修复前后比较时保持固定。',
        '修复第六版保存全部候选与拒绝原因。脚滑单步位移上限十五厘米，全流程上限二十厘米。候选经过几何约束和六项复测后才能采用。',
        '左边是原始动作，右边是实际保存的修复数组。两边按同一帧联动。这条自制样例修复后达标，不表示所有真实输入都能修好。',
        '下载包包含实际动作、候选记录和阶段报告。重新导入写出的 BVH，计算前向运动学并复检，避免仅验证内存数组。',
        '这个候选总分提高，但在新的区间出现严重脚滑，仍被回归审查拒绝。内部修复、命令行和网页共用同一个判断模块。',
        '这里复用预先固定的 Bandai 鞠躬样本，查看实际写盘后的 BVH 检查。复用产物不计为新的评测样本。原输入始终保留。',
        '这里播放实际 Kenney 角色视频及对应骨架报告。骨架质量门通过，但网格穿地仍约六点七厘米。六条完整流程中，仅一条通过跨阶段骨架门。',
        '这些是仓库外安装包的实际命令输出。零表示通过，一表示质量失败或回归，二表示输入或运行错误。远程跨平台验证仍待 GitHub 授权后完成。']
    narration=[{'text':text,'path':str(folder/('voice-%02d.wav'%i))} for i,text in enumerate(texts)]
    (folder/'narration.json').write_text(json.dumps(narration,ensure_ascii=False,indent=2),encoding='utf-8')
    subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-File',str(ROOT/'scripts/synthesize_motionlint_narration.ps1'),
                    '-NarrationJson',str(folder/'narration.json')],check=True,timeout=120)
    concat=['ffconcat version 1.0']
    for i,frame in enumerate(frames):
        delta=(frames[i+1]['at'] if i+1<len(frames) else duration)-frame['at']
        concat.extend(["file '"+frame['file']+"'",'duration %.6f'%max(.001,delta)])
    concat.append("file '"+frames[-1]['file']+"'")
    (folder/'frames.ffconcat').write_text('\n'.join(concat)+'\n',encoding='utf-8')
    ass='''[Script Info]
ScriptType: v4.00+
PlayResX: 1440
PlayResY: 1096
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,SimHei,25,&H00FFFFFF,&H00FFFFFF,&H00111D2E,&H00111D2E,0,0,0,0,100,100,0,0,1,0,0,2,30,30,47,1
Style: Note,SimHei,18,&H00BBDDD0,&H00BBDDD0,&H00111D2E,&H00111D2E,0,0,0,0,100,100,0,0,1,0,0,2,30,30,18,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    limits=['无需权重的实际动作预览','测量值、阈值、支撑依据与阶段对应','候选接受不等于所有动作整体达标','自制示例：修复前后同帧播放',
        '实际写盘 → 回读 → FK → 再检测','总分提高仍可拒绝：新增严重问题','固定清单的已验证产物复用；不新增样本计数',
        'Bandai Namco Research (2022) · CC BY-NC 4.0；Kenney · CC0；网格指标单独报告','实际 CLI 输出；Windows 安装已验证，远程矩阵尚未验证']
    for i,chapter in enumerate(chapters):
        start=ass_time(chapter['start_seconds']);end=ass_time(min(duration,chapter['end_seconds']))
        ass+=f"Dialogue: 0,{start},{end},Main,,0,0,0,,MotionLint 0.5.0 · {chapter['title']}\n"
        ass+=f"Dialogue: 0,{start},{end},Note,,0,0,0,,{limits[i]}\n"
    (folder/'captions.ass').write_text(ass,encoding='utf-8-sig')
    ffmpeg=args.runtime.resolve()/'envs/aic-review311/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe'
    final=ROOT/'output/video/MotionLint-050-demo.mp4'
    if final.exists():raise ValueError('Existing final video is immutable; choose a new release name')
    command=[str(ffmpeg),'-hide_banner','-y','-f','concat','-safe','0','-i','frames.ffconcat']
    for row in narration:command.extend(['-i',row['path']])
    filters=[];voice_info=[]
    for i,(chapter,row) in enumerate(zip(chapters,narration)):
        with wave.open(row['path']) as audio:seconds=audio.getnframes()/audio.getframerate()
        window=chapter['end_seconds']-chapter['start_seconds']-.5
        speed=max(1.,seconds/window);assert speed<1.6,(i,seconds,window)
        delay=round((chapter['start_seconds']+.25)*1000)
        filters.append(f'[{i+1}:a]atempo={speed:.6f},adelay={delay}|{delay}[a{i}]')
        voice_info.append({'chapter':i,'synthetic_voice':'Microsoft Huihui Desktop','duration_seconds':seconds,'atempo':speed})
    filters.append(''.join(f'[a{i}]' for i in range(9))+f'amix=inputs=9:duration=longest:normalize=0,apad,atrim=duration={duration}[audio]')
    command.extend(['-filter_complex',';'.join(filters),'-map','0:v:0','-map','[audio]',
        '-vf','fps=25,pad=iw:ih+96:0:0:color=0x111d2e,subtitles=captions.ass',
        '-frames:v',str(count),'-c:v','libx264','-preset','veryfast','-crf','23','-threads','2',
        '-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-t',str(duration),'-movflags','+faststart',str(final)])
    with (folder/'encoding.log').open('w',encoding='utf-8') as log:subprocess.run(command,cwd=folder,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1800)
    checked=verify_video(final,str(ffmpeg),frames=count,fps=fps)
    audio_decode=subprocess.run([str(ffmpeg),'-v','error','-xerror','-i',str(final),'-map','0:a:0','-f','null','-'],capture_output=True,text=True,timeout=120)
    assert audio_decode.returncode==0 and not audio_decode.stderr.strip()
    assert 180<=checked['duration_seconds']<=300 and final.stat().st_size<=300*1024**2
    receipt={'schema_version':3,'status':'PASS','video':final.name,'sha256':sha256(final),'bytes':final.stat().st_size,
        **checked,'has_fully_decoded_audio':True,'captured_browser_frame_count':len(frames),'capture_timing_preserved':True,
        'recording_kind':'Timestamped actual browser frame sampling, encoded at 25 FPS. Synthetic narration, no fabricated human testimony.',
        'motion_video_evidence':'Existing predeclared Bandai bow / actual Kenney export, same source hash in recording-inputs.json',
        'recorded_frontend_commit':'f660e85','recording_receipt_sha256':sha256(folder/'recording-inputs.json'),
        'captions_sha256':sha256(folder/'captions.ass'),'narration':voice_info,'chapters':chapters}
    (ROOT/'evidence/iteration-050-video-validation.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Actual demo verified:',checked['duration_seconds'],'seconds;',final.stat().st_size,'bytes;',count,'frames with audio')


if __name__=='__main__':main()
