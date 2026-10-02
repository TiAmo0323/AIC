"""Build a reviewable, silent AIC demo draft from existing local outputs.

This deliberately uses only already generated task videos and locally drawn
slides. The team should review the rights and add narration before submission.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT.parent / "HumanAction-runtime"
FFMPEG = RUNTIME / "bin" / "ffmpeg.exe"
OUTPUT = ROOT / "output" / "video" / "motionlint_aic_demo_draft.mp4"
WORK = ROOT / "tmp" / "aic_demo"
FONT = Path("C:/Windows/Fonts/Deng.ttf")
FONT_BOLD = Path("C:/Windows/Fonts/Dengb.ttf")
WIDTH, HEIGHT = 1280, 720

INTERGEN = ROOT / "InterGen_api" / "task_runs" / "91d1b363-c453-4526-8bb2-8f933f25809b" / "motionlint"
LODGE_A = ROOT / "LODGE_api" / "task_runs" / "3eb8a74d-2729-40e5-9300-f1f0239c03db" / "motionlint"
LODGE_B = ROOT / "LODGE_api" / "task_runs" / "a394daeb-6ca1-44e3-a5e8-970a73aea88c" / "motionlint"


def run(*args: str) -> None:
    subprocess.run([str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", *map(str, args)], check=True)


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, size: int, color: str = "#102B42", bold: bool = False) -> None:
    draw.text(xy, value, font=ImageFont.truetype(str(FONT_BOLD if bold else FONT), size), fill=color)


def slide(name: str, title: str, lines: list[str], *, screenshot: Path | None = None) -> Path:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#F6F9FC")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 12), fill="#246AA6")
    text(draw, (70, 45), title, 45, bold=True)
    draw.rectangle((70, 113, 1210, 116), fill="#AECDE5")
    if screenshot is not None:
        shot = Image.open(screenshot).convert("RGB")
        shot.thumbnail((1080, 410))
        image.paste(shot, ((WIDTH - shot.width) // 2, 145))
        start = 585
    else:
        start = 174
    for index, line in enumerate(lines):
        text(draw, (80, start + 66 * index), line, 29 if screenshot is None else 25,
             "#24577B" if index == 0 else "#30485D", bold=index == 0)
    text(draw, (70, 674), "MotionLint · 本地演示草稿", 18, "#61798A")
    path = WORK / f"{name}.png"
    image.save(path)
    return path


def pair_background(name: str, title: str, note: str) -> Path:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#F6F9FC")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH, 12), fill="#246AA6")
    text(draw, (40, 36), title, 37, bold=True)
    text(draw, (65, 117), "原始动作", 25, "#24577B", True)
    text(draw, (690, 117), "修复后", 25, "#247760", True)
    text(draw, (45, 640), note, 24, "#30485D")
    text(draw, (45, 685), "同一任务、同一视角；质量门仍按完整六项检查判定", 18, "#61798A")
    path = WORK / f"{name}.png"
    image.save(path)
    return path


def encode_slide(image: Path, duration: int, target: Path) -> None:
    run("-loop", "1", "-framerate", "24", "-i", image, "-t", str(duration),
        "-vf", "format=yuv420p", "-an", "-c:v", "libx264", "-preset", "ultrafast",
        "-crf", "24", "-r", "24", "-movflags", "+faststart", target)


def encode_pair(original: Path, repaired: Path, background: Path, duration: int, target: Path) -> None:
    for path in (original, repaired):
        if not path.is_file():
            raise FileNotFoundError(path)
    filter_graph = (
        "[0:v]fps=24,scale=580:470:force_original_aspect_ratio=decrease,"
        "pad=580:470:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1[left];"
        "[1:v]fps=24,scale=580:470:force_original_aspect_ratio=decrease,"
        "pad=580:470:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1[right];"
        "[2:v][left]overlay=40:165[base];[base][right]overlay=660:165,format=yuv420p[out]"
    )
    run("-stream_loop", "-1", "-i", original, "-stream_loop", "-1", "-i", repaired,
        "-loop", "1", "-framerate", "24", "-i", background,
        "-filter_complex", filter_graph, "-map", "[out]", "-t", str(duration),
        "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-r", "24", target)


def build() -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    screenshot = ROOT / ".playwright-cli" / "element-2026-09-29T16-26-33-478Z.png"
    segments: list[Path] = []

    slides = [
        ("01", 18, "MotionLint 人体动作质检平台", ["生成 → 检测 → 定位 → 有限修复 → 全量复测", "InterGen 双人动作 · LODGE 音乐舞蹈", "Windows 本地 Web + CLI + 可复现测试"], None),
        ("02", 20, "问题：生成动作如何验收？", ["脚底滑动、接缝跳变、骨架异常、碰撞和抖动", "只看最终视频难以定位问题帧", "修复后还需要检查其他指标是否退化"], None),
        ("03", 20, "统一质检界面", ["六项指标、质量门、问题帧和原始／修复视频同步查看"], screenshot if screenshot.is_file() else None),
        ("07", 18, "实测结果与拒绝机制", ["三条非重复任务的脚滑分数提高，修复被接受", "握手与挥手任务复测未改善，系统拒绝修复", "八个已有文件的严格质量门仍全部为 FAIL"], None),
        ("08", 20, "开放成果与限制", ["MotionLint 代码、测试、接口与文档可供复现", "生成模型和 SMPL-X 文件需按各自授权自行获取", "小样本与合成节拍验证，待团队补充授权和人工评审"], None),
    ]
    for name, duration, title, lines, shot in slides[:3]:
        target = WORK / f"{name}.mp4"
        encode_slide(slide(name, title, lines, screenshot=shot), duration, target)
        segments.append(target)

    pairs = [
        ("04", 24, INTERGEN / "original.mp4", INTERGEN / "repaired.mp4", "InterGen 双人动作：原始与修复", "脚滑 50.97 → 63.62    总分 82.03 → 84.17"),
        ("05", 34, LODGE_A.parent / "input" / "video" / "aic260929-smplx.mp4", LODGE_A / "repaired.mp4", "LODGE 舞蹈样例 A：人体网格对比", "脚滑 68.80 → 72.55    总分 92.18 → 92.79"),
        ("06", 34, LODGE_B / "original.mp4", LODGE_B / "repaired.mp4", "LODGE 舞蹈样例 B：人体网格对比", "脚滑 57.77 → 64.78    总分 87.35 → 88.70"),
    ]
    for name, duration, original, repaired, title, note in pairs:
        target = WORK / f"{name}.mp4"
        encode_pair(original, repaired,
                    pair_background(name, title, note), duration, target)
        segments.append(target)

    for name, duration, title, lines, shot in slides[3:]:
        target = WORK / f"{name}.mp4"
        encode_slide(slide(name, title, lines, screenshot=shot), duration, target)
        segments.append(target)

    manifest = WORK / "concat.txt"
    manifest.write_text("".join(f"file '{path.as_posix()}'\n" for path in segments), encoding="utf-8")
    run("-f", "concat", "-safe", "0", "-i", manifest, "-c", "copy", "-movflags", "+faststart", OUTPUT)
    return OUTPUT


if __name__ == "__main__":
    print(build())
