"""Build a Chinese narrated engineering draft from actual captured operations."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from finalize_motionlint_ui_evidence import decode

FFMPEG = ROOT.parent / 'HumanAction-runtime/bin/ffmpeg.exe'
OUT = ROOT / 'output/video'
TEMP = ROOT / 'tmp/motionlint-narration'


def stamp(seconds):
    milliseconds = round(seconds * 1000)
    return f'{milliseconds // 3600000:02d}:{milliseconds // 60000 % 60:02d}:{milliseconds // 1000 % 60:02d},{milliseconds % 1000:03d}'


def main():
    TEMP.mkdir(parents=True, exist_ok=True)
    operations = OUT / 'motionlint_v4_operations.mp4'
    cli = OUT / 'motionlint_v4_cli_take4.webm'
    first, second = decode(operations), decode(cli)
    cli_duration = min(45, second['duration_s'])
    duration = first['duration_s'] + cli_duration
    if not 180 <= duration <= 300:
        raise ValueError('Actual recordings do not fit the requested duration; edit real footage first')
    cues = [
        (0, 22, 'MotionLint：AI 动作质检、有限修复与复测\n工程草稿；人工盲测与外部反馈待完成',
         '这是 MotionLint，在现有平台上开发的动作质量工具。这段工程演示使用历史开发动作的副本，不计入新的独立盲测。我们已经完成工程检查，真实准确率和外部使用反馈仍待验证。'),
        (25, 50, '六项检测；规则 v4\n分数和质量门只适用于当前阶段',
         '加载动作后，工具检查连续性、骨架、脚滑、地面接触、骨架近距风险和抖动。每份结果保存输入哈希、规则版本和处理阶段。总分不是唯一依据，严重问题仍会阻止整体通过。'),
        (52, 74, '问题定位：区间、人物、关节、数值、阈值\n原始告警定位原始视频',
         '点击时间轴上的问题，可以查看帧区间、人物、关节、实际数值和阈值，并跳到对应阶段的视频。骨架近距只是风险提示，不等于网格穿透。'),
        (76, 109, '接受有限修复；拒绝超过位移上限的候选\n原输入保留，修复后仍为 FAIL',
         '执行修复后，每个候选都重新检查。这条动作的脚滑和骨长修复被接受，人物分离因超过总位移上限而被拒绝。分数从八十五提高到九十点四，但整体质量门仍然失败，残余问题需要继续检查。'),
        (110, 149, '修复前后联动播放\n展示改善，也保留残余问题',
         '前后视频可以联动定位、倍速和播放。界面同时保留修复理由和残余问题。有限修复不保证所有指标都变好，也不保证动作语义自然；语义和外观还需要独立人工判断。'),
        (150, 181.8, '实际 Kenney 导出与角色阶段复检\nBVH 阶段不跳转其他阶段视频',
         '这里播放本次新导出的 Kenney 角色。数组、导出的骨架和角色分别复检，告警只定位对应阶段的视频。骨架阶段没有自己的视频时，页面会关闭视频跳转。这条本机案例不能替代六条独立盲测的完整阶段实验。'),
        (181.8, 201, '真实命令输出回放；不是实时终端\nCPU 独立工具，无生成权重依赖',
         '下面展示已经实际执行的命令输出记录，这是输出回放，不是实时终端。核心工具在仓库外的独立环境运行，不依赖生成服务或模型权重。干净样例通过返回零，缺陷样例质量失败返回一。'),
        (201, duration, '0：通过　1：质量失败或回归　2：输入错误\n正式验收仍需人工标注、外部安装和团队审核',
         '有限修复后仍有问题也会返回一，回归比较识别退步同样返回一。缺失输入文件返回二。安装脚本保存环境、命令、输入哈希和实际结果，方便同学独立复现。真实人工标注、外部反馈和最终审核仍未完成。')]
    payload = [{'start': start, 'end': end, 'caption': caption, 'text': text,
                'output': str(TEMP / f'voice-{i}.wav')} for i, (start, end, caption, text) in enumerate(cues)]
    narration = TEMP / 'narration.json'
    narration.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    ps = TEMP / 'synthesize.ps1'
    ps.write_text('''param([string]$InputJson)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$segments = Get-Content -LiteralPath $InputJson -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($segment in $segments) {
  $speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
  try {
    $speaker.SelectVoice('Microsoft Huihui Desktop')
    $speaker.Rate = 2
    $speaker.SetOutputToWaveFile($segment.output)
    $speaker.Speak($segment.text)
  } finally { $speaker.Dispose() }
}
''', encoding='utf-8')
    subprocess.run(['pwsh', '-NoProfile', '-File', str(ps), str(narration)], check=True)
    for segment in payload:
        with wave.open(segment['output']) as handle:
            spoken_duration = handle.getnframes() / handle.getframerate()
        if spoken_duration > segment['end'] - segment['start']:
            raise ValueError(f'Narration exceeds its segment; shorten text: {segment["start"]}')
        segment['voice_duration_s'] = spoken_duration
    srt = TEMP / 'narration.srt'
    srt.write_text('\n\n'.join(f'{i+1}\n{stamp(s["start"])} --> {stamp(s["end"])}\n{s["caption"]}' for i, s in enumerate(payload)) + '\n', encoding='utf-8')
    command = [str(FFMPEG), '-y', '-v', 'error', '-i', str(operations), '-i', str(cli)]
    for segment in payload:
        command += ['-i', segment['output']]
    filters = ['[0:v]scale=1280:720,fps=25,setsar=1[v0]', f'[1:v]trim=duration={cli_duration},setpts=PTS-STARTPTS,scale=1280:720,fps=25,setsar=1[v1]',
        "[v0][v1]concat=n=2:v=1:a=0,pad=1280:840:0:0:black,subtitles=narration.srt:force_style='FontName=Microsoft YaHei,FontSize=14,Outline=2,MarginV=8'[v]"]
    for i, segment in enumerate(payload):
        filters.append(f'[{i+2}:a]adelay={round(segment["start"] * 1000)}:all=1[a{i}]')
    filters.append(''.join(f'[a{i}]' for i in range(len(payload))) + f'amix=inputs={len(payload)}:normalize=0,apad[a]')
    final = OUT / 'motionlint_v4_narrated_draft.mp4'
    command += ['-filter_complex', ';'.join(filters), '-map', '[v]', '-map', '[a]',
                '-t', str(duration), '-c:v', 'libx264', '-crf', '22', '-preset', 'fast',
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(final)]
    subprocess.run(command, cwd=TEMP, check=True)
    row = decode(final)
    # Verify the narrated audio stream independently, including its tail.
    audio = subprocess.run([str(FFMPEG), '-v', 'error', '-xerror', '-err_detect', 'explode', '-i', str(final),
                            '-map', '0:a:0', '-f', 'null', '-'], capture_output=True, check=True)
    row.update(status='narrated_engineering_draft_not_final_submission', audio_decode_returncode=audio.returncode,
               narration='Windows Microsoft Huihui Desktop synthesized voice; AI-assisted draft text',
               cli_scope='Playback of actual recorded command outputs, not live terminal interaction',
               edit_note=f'Original operations draft plus first {cli_duration} seconds of CLI output capture; no extension',
               input_recordings=[{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in (operations, cli)],
               captions_and_narration=payload, visual_review='pending', human_validation='pending',
               competition_duration_and_size_check=180 <= row['duration_s'] <= 300 and row['bytes'] <= 300_000_000)
    record = ROOT / 'reports/first_prize/browser/narrated_video_verification.json'
    record.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: row[key] for key in ('decoded_frames', 'duration_s', 'bytes', 'audio_decode_returncode', 'competition_duration_and_size_check')}, indent=2))


if __name__ == '__main__':
    main()
