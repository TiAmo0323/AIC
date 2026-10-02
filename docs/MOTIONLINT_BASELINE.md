# 2026 AIC MotionLint 基线（2026-09-29）

在接入 MotionLint 前，对当前仓库的生成链路做了新的 API 任务验收。所有生成结果保存在现有 `task_runs` 目录；没有复制模型、SMPL-X、FBX、视频或音频到 Git 跟踪目录。

## 工作区与运行环境

- 代码：`D:\竞赛记录\AIC开源赛道\HumanAction-Platform`
- 大型资源与隔离环境：`D:\竞赛记录\AIC开源赛道\HumanAction-runtime`
- 入口：`./start-local.ps1`
- 验收时 `http://127.0.0.1:8001/docs`、`http://127.0.0.1:8002/docs`、`http://127.0.0.1:5173` 均返回 HTTP 200。
- MotionLint API 使用 `http://127.0.0.1:8003`；它直接扫描两个后端的任务产物，不依赖生成模型常驻显存。
- 验收前 `git status --short` 已有 InterGen、LODGE、角色目录的修改以及本地启动脚本、SMPL-X 渲染脚本等未跟踪文件；这些现有修改没有覆盖或清理。基线提交尚未创建，避免在未审查这些既有变更前一并提交。

## InterGen：英文文本 → 双人 Kenney 视频

- 新任务 ID：`91d1b363-c453-4526-8bb2-8f933f25809b`
- 请求：`POST /v1/intergen/tasks/generate`，`text="Two people are dancing together."`，人物 A/B 均为 `kenney_cc0`，`motion_frames=180`，`num_samples=1`。
- seed：`503107544`；任务状态 `succeeded`；`retarget_status=succeeded`；服务记录约 66 秒（13:56:07Z → 13:57:13Z）。
- 输出：`InterGen_api/task_runs/91d1b363-c453-4526-8bb2-8f933f25809b/output/raw/` 中双人 `joints22.npy`；`retarget/` 中各自 BVH 和 `91d1b363-c453-4526-8bb2-8f933f25809b_dual_retarget.mp4`。
- FFmpeg 解码检查：MP4 长 6.00 秒，1080×1080，H.264，30 FPS。本次请求只选 Kenney，未要求 SMPL 预览。

## LODGE：新音频上传 → 动作 → SMPL-X → 含音频 MP4

- 验收输入：本机新生成的 36 秒单声道节拍 WAV，`HumanAction-runtime/downloads/motionlint_baseline_20260929.wav`，15360 Hz。它用于链路验收，不代表真实音乐数据集上的舞蹈质量评价。
- 成功任务 ID：`3eb8a74d-2729-40e5-9300-f1f0239c03db`
- 请求：`POST /v1/lodge/tasks/infer-from-audio-upload`，`song_id=aic260929`，`skin_ids=smpl`，`mode=smplx`，`fps=30`。
- 任务状态 `succeeded`；`audio_mux_status=succeeded`；服务记录约 64 秒（13:54:40Z → 13:55:44Z）。
- 动作：`LODGE_api/task_runs/3eb8a74d-2729-40e5-9300-f1f0239c03db/input/aic260929.npy`，形状 `(1024, 139)`，`float32`，数值均有限。
- 视频：同任务 `input/video/aic260929-smplx.mp4`。FFmpeg 解码检查：34.13 秒、720×720、H.264、30 FPS；包含 AAC 16 kHz 单声道音轨。源音频超过动作输出长度，最终视频按动作长度截取。

## 验收中发现的输入约束和失败记录

1. 任务 `1b78dc9d-5577-43fc-a671-5fb270878bf1` 使用 `song_id=motionlint_baseline_20260929`。LODGE 上游 `concat_res.py` 按下划线分割文件名，截断了 song ID，导致 `UnboundLocalError: local variable 'modata' referenced before assignment`。后续音频任务应使用不含下划线的简单 song ID，或单独修复该上游解析逻辑。
2. 任务 `b2fd3b35-3728-4816-950c-c877e5942c44` 使用简短 ID，但在 CUDA 采样开始时出现一次 `Memory allocation failure` / `CUDA error: unknown error`。检查时显存已释放，同样请求重试后成功。比赛现场仍需串行运行两个模型，给失败任务提供重试能力。

## 本地检查命令

```powershell
git status --short
Invoke-RestMethod http://127.0.0.1:8001/v1/intergen/tasks/91d1b363-c453-4526-8bb2-8f933f25809b
Invoke-RestMethod http://127.0.0.1:8002/v1/lodge/tasks/3eb8a74d-2729-40e5-9300-f1f0239c03db
D:\竞赛记录\AIC开源赛道\HumanAction-runtime\bin\ffmpeg.exe -hide_banner -i LODGE_api\task_runs\3eb8a74d-2729-40e5-9300-f1f0239c03db\input\video\aic260929-smplx.mp4 -f null NUL
```

生成 API 仍用内存字典负责快速轮询，同时把状态写入任务目录；服务重启后会从 `task_manifest.json` 恢复，新代码也会为没有 manifest 的历史产物建立最小记录。

## MotionLint 初次质检结果

- LODGE 任务 `3eb8a74d-2729-40e5-9300-f1f0239c03db`：1024 帧、30 FPS；总体分数 `92.18`，Quality Gate 为 `FAIL`，原因是 `foot_sliding` 存在高严重度问题（117 个问题段）；`motion_jerk` 为警告级风险。
- 该任务的六项报告保存在 `LODGE_api/task_runs/3eb8a74d-2729-40e5-9300-f1f0239c03db/motionlint/`。此处记录的是接入时的首轮状态；后续 Foot Lock 改进与复测结果见 `MOTIONLINT_EXPERIMENT_20260930.md`。
- InterGen 任务 `91d1b363-c453-4526-8bb2-8f933f25809b` 可以由 `motionlint` API 检查双人 `joints22` NPY；前端面板支持显示测试、时间点和回归选择。
- 任务状态现在写入各自目录的 `task_manifest.json`。服务重启后会恢复新任务；没有旧 manifest 的历史目录会按已有产物生成最小 `succeeded` 记录。
