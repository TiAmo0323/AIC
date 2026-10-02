# LODGE Async API

This API wraps LODGE inference and rendering into asynchronous HTTP tasks.

## 1. Install

Run in this folder:

    pip install -r requirements.txt

## 2. Run

Canonical startup entry for the frontend-compatible API:

    start_lodge_api_retarget.bat

All future backend changes must remain reachable through this BAT. The script
configures Blender/FBX/mapping resources; `skin_ids` decides which videos run.

Default port in current code is 8002.

## 3. Endpoint List

- GET /health
- GET /v1/lodge/skins
- POST /v1/lodge/tasks/render-song
- POST /v1/lodge/tasks/infer-and-render
- POST /v1/lodge/tasks/infer-from-audio
- POST /v1/lodge/tasks/infer-from-audio-upload
- POST /v1/lodge/tasks/render-from-npy-upload
- POST /v1/lodge/tasks/infer-from-feature-npy-upload
- GET /v1/lodge/tasks/{task_id}
- GET /v1/lodge/tasks/{task_id}/download
- GET /v1/lodge/tasks/{task_id}/download-bvh
- GET /v1/lodge/tasks/{task_id}/download-retarget
- POST /v1/lodge/tasks/{task_id}/open-output-folder
- POST /v1/lodge/tasks/{task_id}/open-output-player

Task status values:

- queued
- running
- succeeded
- failed

## 4. Core Workflows

### 4.1 Render from existing samples

POST /v1/lodge/tasks/render-song

JSON body example:

    {
      "lodge_root": "D:/LODGE-main",
      "sample_dir": "D:/LODGE-main/experiments/.../samples_dod_xxx",
      "song_id": "132",
      "python_executable": "D:/anaconda3/envs/lodge/python.exe",
      "mode": "smplx",
      "device": "0",
      "fps": 30,
      "skin_ids": ["smpl"]
    }

### 4.2 Infer + render in one call

POST /v1/lodge/tasks/infer-and-render

JSON body example:

    {
      "lodge_root": "D:/LODGE-main",
      "song_id": "132",
      "python_executable": "D:/anaconda3/envs/lodge/python.exe",
      "infer_args": ["--soft", "1.0"],
      "mode": "smplx",
      "device": "0",
      "fps": 30,
      "skin_ids": ["robot"]
    }

Optional field:

- sample_dir_hint: force using a specific samples_dod directory.

### 4.3 Audio upload -> infer -> render

POST /v1/lodge/tasks/infer-from-audio-upload

multipart/form-data fields:

- lodge_root (required)
- song_id (required)
- audio_file (required)
- python_executable (optional)
- mode (optional, default smplx)
- device (optional, default 0)
- fps (optional, default 30)
- skin_ids (optional repeated field, `smpl` and/or `robot`; default smpl)
- skin_id (legacy single-value compatibility)
- infer_args (optional, comma-separated string)

Supported uploaded audio/video formats are converted internally to wav when needed.
After rendering, the API attaches the original uploaded audio to every selected
SMPL/retarget MP4. The video stream is copied without re-encoding and the audio
stream is encoded as AAC. Feature-npy and motion-npy inputs remain silent because
they do not contain an original audio source.

### 4.4 Feature npy upload -> infer -> render

POST /v1/lodge/tasks/infer-from-feature-npy-upload

multipart/form-data fields are similar to audio upload, with npy_file as the file field.

## 5. Query and Download

Query task:

    GET /v1/lodge/tasks/{task_id}

Task response includes progress (0-100), message, requested_skin_ids, available_skin_ids,
output_mp4_path, stdout_tail, and stderr_tail. It also includes output_npy_path,
output_bvh_path, output_retarget_mp4_path, output_retarget_path,
retarget_status, retarget_message, audio_mux_status, audio_mux_message, and
audio_muxed_skin_ids. Audio-upload tasks also report the effective
audio_mux_advance_seconds value after any short-audio fallback.

Download result mp4:

    GET /v1/lodge/tasks/{task_id}/download

Download exported BVH:

    GET /v1/lodge/tasks/{task_id}/download-bvh

Download retargeted character mp4 when retarget_status=succeeded:

    GET /v1/lodge/tasks/{task_id}/download-retarget

Supports:

- inline playback (default)
- attachment download with as_attachment=true
- HTTP Range requests

## 6. Desktop Helper Endpoints

For local deployment on the same machine:

- POST /v1/lodge/tasks/{task_id}/open-output-folder
- POST /v1/lodge/tasks/{task_id}/open-output-player

These endpoints open the output folder or mp4 using the backend host OS.
Both accept an optional `skin_id` query parameter and will locate the selected
SMPL or retarget video instead of always opening the SMPL preview.

## 7. Notes

- The API wraps existing infer_lodge.py and render.py behavior.
- `skin_ids=["robot"]` enables only retarget output; `["smpl"]` enables only
  SMPL output; selecting both generates both.
- `GET /v1/lodge/skins` returns the public skin list used by the frontend.
- The old `retarget_enabled=true` request remains supported for backward compatibility.
- Every rendered motion npy is now exported to a same-name BVH in the task input directory.
- BVH export uses the repository-owned `LODGE_api/lodge2bvh.py`. Generated 6D rotations stay as matrices until the final ZYX Euler conversion, avoiding the numerically unstable matrix/axis-angle round trip near 180-degree rotations.
- `retarget_enabled=true` remains a legacy compatibility input. Global
  `LODGE_RETARGET_ENABLED` no longer overrides explicit task selection.
- Retargeting environment variables:
  - LODGE_MOTION_SEAM_SMOOTHING: enable fixed LODGE chunk-boundary repair before both SMPL and retarget branches. The canonical launcher uses 1.
  - LODGE_MOTION_CHUNK_FRAMES: generated local-motion chunk size. The canonical launcher uses 256.
  - LODGE_MOTION_SEAM_WINDOW_FRAMES: half-window on each side of a chunk boundary. The canonical launcher uses 8.
  - LODGE_BLENDER_EXE: Blender executable path.
  - LODGE_TARGET_FBX: target character FBX path. Defaults to D:/HumanAction_Platform/X Bot.fbx when present.
  - LODGE_RETARGET_MAPPING: Rokoko mapping JSON path. Defaults to momask-main/assets/mapping.json.
  - LODGE_RETARGET_SCRIPT: Blender Python script path. Defaults to LODGE_api/blender_rokoko_retarget.py.
  - LODGE_RETARGET_STRICT: set 1 to fail the whole task when retargeting fails.
  - LODGE_RETARGET_RENDER_ENGINE: Blender render engine. The canonical launcher fixes it to BLENDER_EEVEE_NEXT.
  - LODGE_RETARGET_EEVEE_SAMPLES: Eevee render samples. The canonical launcher uses 32 for the current performance/quality test.
  - LODGE_RETARGET_RESOLUTION_PERCENTAGE: output resolution scale. The canonical launcher fixes it to 100.
  - LODGE_RETARGET_HAND_TORSO_COLLISION: enable experimental target-space hand-to-torso collision avoidance. The canonical launcher uses 0 because the project accepts occasional baseline penetration and avoids adding IK-induced arm jitter.
  - LODGE_RETARGET_HAND_TORSO_CLEARANCE: hand clearance outside the torso proxy in meters. Defaults to 0.025.
  - LODGE_RETARGET_HAND_TORSO_MAX_CORRECTION: maximum wrist correction per frame in meters. Defaults to 0.12.
- Audio mux environment variables:
  - LODGE_FFMPEG_EXE: optional explicit FFmpeg executable. Resolution falls back to PATH and then imageio-ffmpeg.
  - LODGE_AUDIO_MUX_BITRATE: AAC bitrate. The canonical launcher uses 192k.
  - LODGE_AUDIO_MUX_TIMEOUT_SEC: per-video FFmpeg timeout. The canonical launcher uses 300 seconds.
  - LODGE_AUDIO_ADVANCE_SEC: seconds trimmed from the start of the playback audio before muxing. The canonical launcher uses 2.0 to compensate for the measured LODGE motion/music phase offset; set 0 to disable.
- Audio muxing writes a temporary MP4, validates both video and audio streams,
  and atomically replaces the final file. The video duration is authoritative:
  long music is trimmed, while short music never truncates the motion. The task
  reports the applied value in `audio_mux_advance_seconds`. If an upload is too
  short to contain audio after the requested trim, muxing retries with 0 seconds
  rather than failing the completed render.
- When explicitly enabled, hand-to-torso collision avoidance builds an animated proxy from the target mesh and uses temporally smoothed two-bone arm IK. Metrics are written to `hand_torso_collision_avoidance` in `rokoko_retarget_report.json`. The implementation remains available for A/B experiments but is disabled by the canonical launcher.
- Before either selected skin is rendered, chunk seams are repaired on the shared task NPY with raised-cosine quaternion SLERP and a cubic-Hermite root bridge. Frame count, FPS and contact channels stay unchanged. The clipped pre-repair motion is retained as `<song>.raw.npy`, and `<song>.motion_postprocess.json` records every boundary and maximum modification.
- Task state is kept in memory and will be lost after API restart.
- Outputs are stored under LODGE_api/task_runs/{task_id}/.

---

## 中文说明

该服务将 LODGE 推理与渲染封装为异步任务 API，适合前后端分离和本机联调。

### 1. 安装

在当前目录执行：

    pip install -r requirements.txt

### 2. 启动

统一通过：

    start_lodge_api_retarget.bat

当前代码默认端口为 8002。

### 3. 主要接口

- 健康检查：GET /health
- 任务创建：见上方 Endpoint List
- 查询任务：GET /v1/lodge/tasks/{task_id}
- 下载视频：GET /v1/lodge/tasks/{task_id}/download
- 打开目录：POST /v1/lodge/tasks/{task_id}/open-output-folder
- 打开播放器：POST /v1/lodge/tasks/{task_id}/open-output-player

### 4. 常用联调建议

1. 先调用创建任务接口，获取 task_id。
2. 轮询查询接口直到 status=succeeded 或 failed。
3. 成功后调用下载接口获取 mp4。

### 5. 备注

- 任务状态保存在内存中，服务重启后旧 task_id 会失效。
- 输出目录默认在 LODGE_api/task_runs/{task_id}/。
- 查询接口返回 progress 字段，可直接驱动前端进度条。
- 当前统一启动脚本将机器人渲染固定为 Eevee Next、32 samples、100% 分辨率；实际值会同时写入 retarget manifest 和 Blender 报告，便于进行画质和耗时对比。
- 当前统一启动脚本在 SMPL/机器人共用动作分流前，对每个 256 帧边界使用 8 帧半窗口进行局部过渡；关节采用四元数 SLERP，根轨迹采用三次 Hermite，保持总帧数、FPS、音乐时间轴和 contact 通道不变。
- 处理前动作保留为 `input/<song>.raw.npy`，边界前后指标写入 `input/<song>.motion_postprocess.json`。BVH 由仓库内 `LODGE_api/lodge2bvh.py` 导出，6D 旋转矩阵直接进入 ZYX 欧拉角转换，不再经过接近 180°时不稳定的轴角中间表示。
- WAV、MP3 或带音频 MP4 上传任务会在渲染后把原始音乐加入每个所选视频。视频轨直接复制，音频编码为 AAC；特征 NPY 和动作 NPY 没有原始音乐，仍输出静音视频。
- 音频封装先生成临时文件并验证音视频轨，再原子替换正式 MP4。音乐较长时按视频时长截取，音乐较短时不会截断动作。
- 推荐启动脚本默认关闭目标角色空间的手—躯干防穿模处理，接受基线动作的偶发穿模，避免腕部 IK 修正放大局部抖动。
- 防碰撞实现仍保留用于 A/B 实验；显式设为 `LODGE_RETARGET_HAND_TORSO_COLLISION=1` 后，可使用 `LODGE_RETARGET_HAND_TORSO_CLEARANCE=0.025` 和 `LODGE_RETARGET_HAND_TORSO_MAX_CORRECTION=0.12` 等参数，完整指标会写入 `retarget_manifest.json` 和 `rokoko_retarget_report.json`。
- 修改这些环境变量后必须重启 API；历史任务不会自动应用新配置。
