# LODGE 音轨封装回归测试。
# 使用短媒体和替身任务验证 FFmpeg 封装、失败保护、音轨提前量与视频流不重编码；
# 不运行真实 LODGE 模型，也不代表长视频的最终听感已经验收。
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_lodge_module():
    module_path = REPO_ROOT / "LODGE_api" / "lodge_async_api.py"
    spec = importlib.util.spec_from_file_location("lodge_api_audio_mux_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def run(command):
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout or f"Command failed: {command}")
    return proc


def video_stream_hash(ffmpeg_exe: str, video_path: Path) -> str:
    proc = run(
        [
            ffmpeg_exe,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-map",
            "0:v:0",
            "-c",
            "copy",
            "-f",
            "streamhash",
            "-hash",
            "sha256",
            "-",
        ]
    )
    return proc.stdout.strip()


def validate_audio_video_streams(ffmpeg_exe: str, video_path: Path) -> None:
    run(
        [
            ffmpeg_exe,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-t",
            "0.1",
            "-f",
            "null",
            "NUL" if sys.platform == "win32" else "/dev/null",
        ]
    )


def main():
    lodge = load_lodge_module()
    ffmpeg_exe = lodge._resolve_ffmpeg_executable()

    with tempfile.TemporaryDirectory(prefix="lodge_audio_mux_test_") as temp_dir:
        root = Path(temp_dir)
        silent_video = root / "silent.mp4"
        original_audio = root / "original.wav"

        run(
            [
                ffmpeg_exe,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=blue:s=160x160:r=30:d=2",
                "-c:v",
                "mpeg4",
                "-q:v",
                "5",
                str(silent_video),
            ]
        )
        run(
            [
                ffmpeg_exe,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=44100:duration=3",
                "-ac",
                "2",
                "-c:a",
                "pcm_s16le",
                str(original_audio),
            ]
        )
        audio_less_input = root / "audio-less-input.mp4"
        audio_less_input.write_bytes(silent_video.read_bytes())

        task_id = "audio-mux-success"
        now = "2026-07-25T00:00:00Z"
        lodge._tasks[task_id] = lodge.TaskInfo(
            task_id=task_id,
            status="running",
            created_at=now,
            updated_at=now,
            requested_skin_ids=["smpl"],
            audio_mux_status="pending",
        )
        source_hash = video_stream_hash(ffmpeg_exe, silent_video)
        old_advance = os.environ.get("LODGE_AUDIO_ADVANCE_SEC")
        os.environ["LODGE_AUDIO_ADVANCE_SEC"] = "2.0"
        try:
            lodge._mux_original_audio(
                task_id=task_id,
                video_path=silent_video,
                source_audio_path=original_audio,
                duration_seconds=2.0,
                skin_id="smpl",
            )
        finally:
            if old_advance is None:
                os.environ.pop("LODGE_AUDIO_ADVANCE_SEC", None)
            else:
                os.environ["LODGE_AUDIO_ADVANCE_SEC"] = old_advance
        muxed_hash = video_stream_hash(ffmpeg_exe, silent_video)
        validate_audio_video_streams(ffmpeg_exe, silent_video)
        task = lodge._tasks[task_id]
        assert source_hash == muxed_hash
        assert task.audio_mux_status == "succeeded"
        assert task.audio_muxed_skin_ids == ["smpl"]
        assert task.audio_mux_advance_seconds == 2.0
        assert "advanced by 2.000s" in task.audio_mux_message
        assert not list(root.glob(".*.audio-*.tmp.mp4"))

        failed_video = root / "failed.mp4"
        failed_video.write_bytes(audio_less_input.read_bytes())
        failed_hash = video_stream_hash(ffmpeg_exe, failed_video)
        failed_task_id = "audio-mux-failure"
        lodge._tasks[failed_task_id] = lodge.TaskInfo(
            task_id=failed_task_id,
            status="running",
            created_at=now,
            updated_at=now,
            requested_skin_ids=["robot"],
            audio_mux_status="pending",
        )
        try:
            lodge._mux_original_audio(
                task_id=failed_task_id,
                video_path=failed_video,
                source_audio_path=audio_less_input,
                duration_seconds=2.0,
                skin_id="robot",
            )
            raise AssertionError("Audio mux should fail when the source has no audio stream")
        except RuntimeError:
            pass
        assert video_stream_hash(ffmpeg_exe, failed_video) == failed_hash
        assert lodge._tasks[failed_task_id].audio_mux_status == "failed"
        assert not list(root.glob(".*.audio-*.tmp.mp4"))

        short_audio = root / "short.wav"
        run(
            [
                ffmpeg_exe,
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=660:sample_rate=44100:duration=0.5",
                "-c:a",
                "pcm_s16le",
                str(short_audio),
            ]
        )
        short_audio_video = root / "short-audio-video.mp4"
        short_audio_video.write_bytes(audio_less_input.read_bytes())
        short_audio_hash = video_stream_hash(ffmpeg_exe, short_audio_video)
        short_task_id = "short-audio"
        lodge._tasks[short_task_id] = lodge.TaskInfo(
            task_id=short_task_id,
            status="running",
            created_at=now,
            updated_at=now,
            requested_skin_ids=["smpl"],
            audio_mux_status="pending",
        )
        old_advance = os.environ.get("LODGE_AUDIO_ADVANCE_SEC")
        os.environ["LODGE_AUDIO_ADVANCE_SEC"] = "2.0"
        try:
            lodge._mux_original_audio(
                task_id=short_task_id,
                video_path=short_audio_video,
                source_audio_path=short_audio,
                duration_seconds=2.0,
                skin_id="smpl",
            )
        finally:
            if old_advance is None:
                os.environ.pop("LODGE_AUDIO_ADVANCE_SEC", None)
            else:
                os.environ["LODGE_AUDIO_ADVANCE_SEC"] = old_advance
        assert video_stream_hash(ffmpeg_exe, short_audio_video) == short_audio_hash
        validate_audio_video_streams(ffmpeg_exe, short_audio_video)
        assert lodge._tasks[short_task_id].audio_mux_advance_seconds == 0.0
        assert "short-audio fallback" in lodge._tasks[short_task_id].audio_mux_message

        route_task_id = "audio-source-routing"
        route_sample_dir = root / "sample"
        route_npy_dir = route_sample_dir / "concat" / "npy"
        route_npy_dir.mkdir(parents=True)
        route_song_id = "route"
        route_npy = route_npy_dir / f"{route_song_id}.npy"
        np.save(route_npy, np.zeros((60, 3), dtype=np.float32))
        lodge.DEFAULT_TASK_ROOT = root / "task-runs"
        lodge._tasks[route_task_id] = lodge.TaskInfo(
            task_id=route_task_id,
            status="running",
            created_at=now,
            updated_at=now,
            requested_skin_ids=["smpl", "robot"],
            audio_mux_status="pending",
        )
        routed = {}
        original_export = lodge._export_bvh_for_npy
        original_retarget = lodge._run_retarget_if_requested
        original_render = lodge._render_with_retry

        def fake_export(**kwargs):
            target = kwargs["target_npy"].with_suffix(".bvh")
            target.write_text("mock bvh", encoding="utf-8")
            return target

        def fake_retarget(**kwargs):
            routed["retarget"] = kwargs.get("source_audio_path")

        def fake_render(**kwargs):
            routed["smpl"] = kwargs.get("source_audio_path")

        try:
            lodge._export_bvh_for_npy = fake_export
            lodge._run_retarget_if_requested = fake_retarget
            lodge._render_with_retry = fake_render
            lodge._render_from_sample_dir(
                task_id=route_task_id,
                lodge_root=root,
                sample_dir=route_sample_dir,
                song_id=route_song_id,
                python_exe=sys.executable,
                mode="smplx",
                device="0",
                fps=30,
                retarget_options={"enabled": True, "render_smpl": True, "skin_id": "robot"},
                source_audio_path=original_audio,
            )
            routed_npy = (
                lodge.DEFAULT_TASK_ROOT
                / route_task_id
                / "input"
                / f"{route_song_id}.npy"
            )
            assert np.array_equal(
                np.load(routed_npy, allow_pickle=False),
                np.load(route_npy, allow_pickle=False),
            )
            assert not routed_npy.with_name(f"{route_song_id}.raw.npy").exists()
            assert not (
                lodge.DEFAULT_TASK_ROOT
                / route_task_id
                / "grounding_report.json"
            ).exists()
        finally:
            lodge._export_bvh_for_npy = original_export
            lodge._run_retarget_if_requested = original_retarget
            lodge._render_with_retry = original_render

        assert routed["retarget"] == original_audio
        assert routed["smpl"] == original_audio

        results = {
            "ffmpeg": ffmpeg_exe,
            "video_stream_hash_preserved": source_hash == muxed_hash,
            "audio_video_stream_validation": "passed",
            "success_status": task.audio_mux_status,
            "muxed_skin_ids": task.audio_muxed_skin_ids,
            "audio_advance_seconds": task.audio_mux_advance_seconds,
            "failure_preserved_original_video": True,
            "short_audio_preserved_full_video": True,
            "short_audio_advance_fallback_seconds": (
                lodge._tasks[short_task_id].audio_mux_advance_seconds
            ),
            "source_audio_routed_to": sorted(routed),
            "motion_passthrough_after_grounding_rollback": True,
            "temporary_files_remaining": 0,
        }
        lodge._tasks.pop(task_id, None)
        lodge._tasks.pop(failed_task_id, None)
        lodge._tasks.pop(short_task_id, None)
        lodge._tasks.pop(route_task_id, None)

    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
